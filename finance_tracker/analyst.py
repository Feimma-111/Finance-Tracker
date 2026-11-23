"""The AI analyst: monthly reviews written by a local model (Ollama).

How it works
------------
1. ``month_facts`` turns one month of data into a plain-text fact sheet. Every
   number in it -- totals, differences, percentages -- is computed here in
   Python. Small language models are good at describing numbers and bad at
   arithmetic (in testing, one confidently reported $467 saved when the true
   figure was $167), so the model is never asked to calculate anything.
2. ``OllamaClient`` sends the fact sheet to Ollama running on your own PC
   (reached over Tailscale) and asks for a reply in a fixed JSON shape:
   a headline, some observations, and a few suggestions.
3. The API saves each review, so past reviews stay readable when the PC is off.

Nothing leaves your own devices: the model runs on your PC, not a cloud service.
"""

from __future__ import annotations

import calendar
import json
import statistics
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Sequence

from .models import Kind, format_money, month_of, shift_month
from .store import Store

BASELINE_MONTHS = 6

SYSTEM_PROMPT = """\
You are a friendly, concise personal-finance assistant reviewing one month of \
the user's own spending data.

Rules:
- Use ONLY the facts provided. Quote dollar amounts and percentages exactly as \
written. Never do arithmetic or produce a number that isn't in the facts.
- If the month is still in progress, say so, and don't conclude spending is low \
just because the month isn't over.
- Focus on spending patterns: which categories changed, unusual expenses, \
recurring charges, and practical budgeting habits.
- Do not recommend specific investments, securities, or financial products.
- Write in plain, encouraging language. Address the user as "you".
"""

REVIEW_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "headline": {"type": "string", "description": "One sentence summing up the month."},
        "observations": {
            "type": "array", "items": {"type": "string"}, "minItems": 2, "maxItems": 4,
            "description": "Notable facts about this month, each one or two sentences.",
        },
        "suggestions": {
            "type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 3,
            "description": "Practical, specific budgeting ideas based on the facts.",
        },
    },
    "required": ["headline", "observations", "suggestions"],
}


# ----------------------------------------------------------------- facts


def _change(now: int, before: float) -> str:
    """'$65.08 less (-15.9%)' style comparison, computed exactly."""
    diff = now - round(before)
    if diff == 0:
        return "about the same"
    direction = "more" if diff > 0 else "less"
    pct = f" ({diff / before * 100:+.1f}%)" if before else ""
    return f"{format_money(abs(diff))} {direction}{pct}"


def month_facts(store: Store, month: str, today: date) -> str:
    """Everything the model is told about ``month``, as plain text."""
    current = month_of(today)
    year, mon = (int(p) for p in month.split("-"))
    days_in_month = calendar.monthrange(year, mon)[1]
    lines: List[str] = []

    status = (
        f" (IN PROGRESS: day {today.day} of {days_in_month})" if month == current
        else " (complete)" if month < current else " (in the future)"
    )
    lines.append(f"Month: {date(year, mon, 1):%B %Y}{status}")

    spent_rows = store.totals_by_category(Kind.EXPENSE, month=month)
    income_rows = store.totals_by_category(Kind.INCOME, month=month)
    spent = sum(c for _, c in spent_rows)
    income = sum(c for _, c in income_rows)
    lines.append(f"Total spending: {format_money(spent)}")
    lines.append(f"Total income: {format_money(income)}")
    if income:
        net = income - spent
        rate = net / income * 100
        verb = "saved" if net >= 0 else "overspent by"
        lines.append(f"Net: {format_money(net)} ({verb} {abs(rate):.0f}% of income)")

    # Baseline: up to six previous months, but only since tracking began, so
    # months before the first transaction don't count as $0 spending.
    month_totals = dict(store.totals_by_month(Kind.EXPENSE))
    first = min(month_totals) if month_totals else month
    previous = [shift_month(month, -i) for i in range(1, BASELINE_MONTHS + 1)]
    previous = [m for m in previous if m >= first]
    if previous:
        avg = statistics.mean(month_totals.get(m, 0) for m in previous)
        lines.append(
            f"Average monthly spending over the previous {len(previous)} month(s): {format_money(round(avg))}"
        )
        lines.append(f"This month compared with that average: {_change(spent, avg)}")
    else:
        lines.append("No earlier months to compare with yet.")

    if spent_rows:
        lines.append("")
        if previous:
            lines.append("Spending by category (this month | previous average | change):")
            history = {m: dict(store.totals_by_category(Kind.EXPENSE, month=m)) for m in previous}
            for name, cents in spent_rows:
                cat_avg = statistics.mean(history[m].get(name, 0) for m in previous)
                share = cents / spent * 100
                lines.append(
                    f"- {name}: {format_money(cents)} ({share:.0f}% of spending) | "
                    f"{format_money(round(cat_avg))} | {_change(cents, cat_avg) if cat_avg else 'new this month'}"
                )
            # Regular categories (spending in at least half of the previous
            # months) with nothing yet this month. One-offs like a single trip
            # are left out, or the model calls them "usual" spending.
            this_month = {name for name, _ in spent_rows}
            seen = {name for m in previous for name in history[m]}
            for name in sorted(seen - this_month):
                months_with = sum(1 for m in previous if history[m].get(name))
                cat_avg = statistics.mean(history[m].get(name, 0) for m in previous)
                if months_with * 2 >= len(previous) and cat_avg >= 1000:  # and over $10/month
                    lines.append(f"- {name}: $0.00 this month | {format_money(round(cat_avg))} | none yet")
        else:
            lines.append("Spending by category:")
            for name, cents in spent_rows:
                lines.append(f"- {name}: {format_money(cents)} ({cents / spent * 100:.0f}% of spending)")

    expenses = [t for t in store.transactions(month=month) if t.kind is Kind.EXPENSE]
    if expenses:
        biggest = sorted(expenses, key=lambda t: t.amount_cents, reverse=True)[:5]
        lines.append("")
        lines.append("Largest expenses:")
        for tx in biggest:
            lines.append(f"- {tx.occurred_on:%b %d}: {tx.description} ({tx.category}) {format_money(tx.amount_cents)}")

    rules = [r for r in store.recurring_rules() if r.active and r.kind is Kind.EXPENSE]
    if rules:
        lines.append("")
        lines.append("Active recurring expenses:")
        for rule in rules:
            lines.append(f"- {rule.description} ({rule.category}): {format_money(rule.amount_cents)} {rule.frequency.value}")

    history_points = store.net_worth_history()
    if history_points:
        latest_day, latest = history_points[-1]
        line = f"Net worth: {format_money(latest)} as of {latest_day:%b %d}"
        month_ago = [p for p in history_points if p[0] <= latest_day - timedelta(days=28)]
        if month_ago:
            day, then = month_ago[-1]
            change = latest - then
            word = "up" if change >= 0 else "down"
            line += f", {word} {format_money(abs(change))} since {day:%b %d}"
        lines.append("")
        lines.append(line)

    return "\n".join(lines)


# ---------------------------------------------------------------- Ollama


class AIUnavailable(Exception):
    """The PC (or Ollama on it) can't be reached right now."""


class AIError(Exception):
    """Ollama answered, but not with something usable."""


@dataclass(frozen=True)
class Review:
    headline: str
    observations: List[str]
    suggestions: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {"headline": self.headline, "observations": self.observations, "suggestions": self.suggestions}


def normalize_url(url: str) -> str:
    """Validate an Ollama address like 'http://100.101.102.103:11434'."""
    url = url.strip().rstrip("/")
    if url and "://" not in url:
        url = "http://" + url
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("enter an address like http://100.101.102.103:11434")
    if parsed.port is None:
        url += ":11434"  # Ollama's default port
    return url


class OllamaClient:
    def __init__(self, base_url: str, *, timeout: float = 240.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _request(self, path: str, body: Optional[Dict[str, Any]] = None, timeout: Optional[float] = None) -> Any:
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(
            self.base_url + path, data=data, headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout or self.timeout) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = json.load(exc).get("error", "")
            except Exception:
                pass
            raise AIError(detail or f"Ollama returned HTTP {exc.code}") from exc
        except (urllib.error.URLError, OSError) as exc:
            raise AIUnavailable(f"can't reach {self.base_url}") from exc
        except ValueError as exc:
            raise AIError("Ollama sent a response that wasn't JSON") from exc

    def models(self) -> List[str]:
        """Installed models. A short timeout, since this is the 'is the PC on?' check."""
        payload = self._request("/api/tags", timeout=3)
        return [m["name"] for m in payload.get("models", [])]

    def review(self, model: str, facts: str) -> Review:
        body: Dict[str, Any] = {
            "model": model,
            "stream": False,
            "format": REVIEW_SCHEMA,
            # Thinking mode is off: the facts already contain every number,
            # so the model only has to describe them, which is ~3x faster.
            "think": False,
            "options": {"temperature": 0.3},
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": "Review this month for me.\n\n" + facts},
            ],
        }
        try:
            payload = self._request("/api/chat", body)
        except AIError as exc:
            if "think" not in str(exc).lower():
                raise
            body.pop("think")  # older models don't accept the setting at all
            payload = self._request("/api/chat", body)
        return parse_review(payload.get("message", {}).get("content", ""))


def parse_review(content: str) -> Review:
    try:
        data = json.loads(content)
        headline = str(data["headline"]).strip()
        observations = [str(x).strip() for x in data["observations"] if str(x).strip()]
        suggestions = [str(x).strip() for x in data["suggestions"] if str(x).strip()]
    except (ValueError, KeyError, TypeError) as exc:
        raise AIError("the model's reply wasn't in the expected format; try again") from exc
    if not headline or not observations:
        raise AIError("the model's reply was empty; try again")
    return Review(headline, observations[:4], suggestions[:3])


def pick_model(installed: Sequence[str], preferred: str) -> Optional[str]:
    """The configured model if installed, else the first installed one."""
    if preferred and preferred in installed:
        return preferred
    return installed[0] if installed else None
