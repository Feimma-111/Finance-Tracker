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
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .models import Kind, format_money, month_of, shift_month
from .reports import group_purchases
from .store import Store

BASELINE_MONTHS = 6

_RULES = """\
Rules:
- Use ONLY the facts provided. Quote dollar amounts and percentages exactly as \
written. Never do arithmetic or produce a number that isn't in the facts.
- If the month is still in progress, say so, and don't conclude spending is low \
just because the month isn't over.
- Focus on spending patterns: which categories changed, unusual expenses, \
recurring charges, and practical budgeting habits.
- Anything marked [covered] is paid for by someone else. You may mention it \
as context, but never suggest cutting it, and judge whether the month was high \
or low using the "spending you control" figures, not the total.
- Do not recommend specific investments, securities, or financial products.
- Write in plain, encouraging language. Address the user as "you".
"""

SYSTEM_PROMPT = """\
You are a friendly, concise personal-finance assistant reviewing one month of \
the user's own spending data.

""" + _RULES

# For a review of just the categories the user picked on the dashboard.
FOCUS_PROMPT = """\
You are a friendly, concise personal-finance assistant. The user picked a few \
spending categories and wants a close look at just those for one month.

""" + _RULES + """\
- You are shown ONLY the chosen categories. Don't comment on the rest of the \
user's spending or on the month as a whole.
- The user can already see these totals on a chart. Your job is the why: name \
the specific purchases and how often they happened. For the trend, use the \
"Trend" lines, which are already worked out.
- Ideas must be practical actions aimed at the most frequent or most \
expensive purchases in the facts. Restating a fact ("You bought coffee 9 \
times") is not an idea.
"""

# Field names a small model takes literally: asking for "drivers" and "trend"
# instead of generic "observations" stops it from just restating the totals
# (which the user already sees on the chart). ``parse_focus_review`` maps the
# answer back to the usual headline / observations / suggestions.
FOCUS_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "headline": {
            "type": "string",
            "description": "One short sentence on what drove these categories, naming the main purchase.",
        },
        "drivers": {
            "type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 3,
            "description": "One short sentence each: a purchase that drove the spending, by name, with how "
                           "many times and how much.",
        },
        "trend": {
            "type": "string",
            "description": "One or two short sentences: is the month-by-month spending rising, falling, steady, "
                           "or up and down?",
        },
        "ideas": {
            "type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 3,
            "description": "One short sentence each: a concrete action aimed at the most frequent or largest "
                           "purchases. Never a restatement of a fact.",
        },
    },
    "required": ["headline", "drivers", "trend", "ideas"],
}

REVIEW_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "headline": {"type": "string", "description": "One sentence summing up what the facts show."},
        "observations": {
            "type": "array", "items": {"type": "string"}, "minItems": 2, "maxItems": 4,
            "description": "Notable facts, each one or two sentences.",
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


def _month_header(month: str, today: date) -> str:
    """'Month: November 2026 (IN PROGRESS: day 22 of 30)'."""
    current = month_of(today)
    year, mon = (int(p) for p in month.split("-"))
    days_in_month = calendar.monthrange(year, mon)[1]
    status = (
        f" (IN PROGRESS: day {today.day} of {days_in_month})" if month == current
        else " (complete)" if month < current else " (in the future)"
    )
    return f"Month: {date(year, mon, 1):%B %Y}{status}"


def _previous_months(store: Store, month: str) -> List[str]:
    """Up to six months before ``month``, newest first, but only since tracking
    began, so months before the first transaction don't count as $0 spending."""
    month_totals = dict(store.totals_by_month(Kind.EXPENSE))
    first = min(month_totals) if month_totals else month
    previous = [shift_month(month, -i) for i in range(1, BASELINE_MONTHS + 1)]
    return [m for m in previous if m >= first]


def month_facts(store: Store, month: str, today: date) -> str:
    """Everything the model is told about ``month``, as plain text."""
    lines: List[str] = [_month_header(month, today)]

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

    # Expenses someone else pays for (e.g. rent and tuition covered by parents).
    covered, note = store.covered_categories()
    covered_set = set(covered)
    tag = lambda name: f" [covered: {note}]" if name in covered_set else ""  # noqa: E731
    covered_spent = sum(c for name, c in spent_rows if name in covered_set)
    controlled = spent - covered_spent
    if covered:
        lines.append(
            f"Covered by someone else ({note}): {', '.join(covered)}. "
            f"{format_money(covered_spent)} of this month's spending is covered."
        )
        lines.append(f"Spending you control (everything not covered): {format_money(controlled)}")

    month_totals = dict(store.totals_by_month(Kind.EXPENSE))
    previous = _previous_months(store, month)
    history = {m: dict(store.totals_by_category(Kind.EXPENSE, month=m)) for m in previous}
    if previous:
        avg = statistics.mean(month_totals.get(m, 0) for m in previous)
        lines.append(
            f"Average monthly spending over the previous {len(previous)} month(s): {format_money(round(avg))}"
        )
        lines.append(f"This month compared with that average: {_change(spent, avg)}")
        if covered:
            avg_controlled = statistics.mean(
                month_totals.get(m, 0) - sum(history[m].get(n, 0) for n in covered) for m in previous
            )
            lines.append(f"Average spending you control over those months: {format_money(round(avg_controlled))}")
            lines.append(f"Spending you control compared with that average: {_change(controlled, avg_controlled)}")
    else:
        lines.append("No earlier months to compare with yet.")

    if spent_rows:
        lines.append("")
        if previous:
            lines.append("Spending by category (this month | previous average | change):")
            for name, cents in spent_rows:
                cat_avg = statistics.mean(history[m].get(name, 0) for m in previous)
                share = cents / spent * 100
                lines.append(
                    f"- {name}: {format_money(cents)} ({share:.0f}% of spending) | "
                    f"{format_money(round(cat_avg))} | {_change(cents, cat_avg) if cat_avg else 'new this month'}"
                    f"{tag(name)}"
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
                    lines.append(
                        f"- {name}: $0.00 this month | {format_money(round(cat_avg))} | none yet{tag(name)}"
                    )
        else:
            lines.append("Spending by category:")
            for name, cents in spent_rows:
                lines.append(f"- {name}: {format_money(cents)} ({cents / spent * 100:.0f}% of spending){tag(name)}")

    expenses = [t for t in store.transactions(month=month) if t.kind is Kind.EXPENSE]
    if expenses:
        biggest = sorted(expenses, key=lambda t: t.amount_cents, reverse=True)[:5]
        lines.append("")
        lines.append("Largest expenses:")
        for tx in biggest:
            lines.append(
                f"- {tx.occurred_on:%b %d}: {tx.description} ({tx.category}) "
                f"{format_money(tx.amount_cents)}{' [covered]' if tx.category in covered_set else ''}"
            )

    rules = [r for r in store.recurring_rules() if r.active and r.kind is Kind.EXPENSE]
    if rules:
        lines.append("")
        lines.append("Active recurring expenses:")
        for rule in rules:
            lines.append(
                f"- {rule.description} ({rule.category}): {format_money(rule.amount_cents)} "
                f"{rule.frequency.value}{' [covered]' if rule.category in covered_set else ''}"
            )

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


MAX_GROUPS = 8


def _trend(label: str, series: List[Tuple[str, int]], in_progress: bool, fmt: str) -> Optional[str]:
    """One precomputed sentence about a month-by-month series (oldest first,
    this month last), e.g. 'Food: Nov so far is higher than any of the previous
    6 months; $112.76 more (+90.2%) than Oct; up 2 months in a row.' Small
    models misread rows of numbers, so the comparisons are done here."""
    values = [cents for _, cents in series]
    if len(series) < 2 or not any(values):
        return None

    def name(m: str) -> str:
        y, mo = (int(p) for p in m.split("-"))
        return f"{date(y, mo, 1):{fmt}}"

    (now_m, now), earlier = series[-1], series[:-1]
    high_m, high = max(earlier, key=lambda p: p[1])
    low_m, low = min(earlier, key=lambda p: p[1])
    n = f"{len(earlier)} month{'s' if len(earlier) > 1 else ''}"
    if now > high:
        rank = f"higher than any of the previous {n}"
    elif now < low:
        rank = f"lower than any of the previous {n}" + (" (the month isn't over yet)" if in_progress else "")
    else:
        rank = (f"within the range of the previous {n} "
                f"({format_money(low)} in {name(low_m)} to {format_money(high)} in {name(high_m)})")
    prev_m, prev = earlier[-1]
    versus = f"the same as {name(prev_m)}" if now == prev else f"{_change(now, prev)} than {name(prev_m)}"

    def run(rising: bool) -> int:
        count, i = 0, len(values) - 1
        while i > 0 and (values[i] > values[i - 1] if rising else values[i] < values[i - 1]):
            count, i = count + 1, i - 1
        return count

    up, down = run(True), run(False)
    streak = f"; up {up} months in a row" if up >= 2 else f"; down {down} months in a row" if down >= 2 else ""
    return f"- {label}: {name(now_m)}{' so far' if in_progress else ''} is {rank}; {versus}{streak}"


def focus_facts(store: Store, month: str, categories: Sequence[str], today: date) -> str:
    """What the model is told when it looks at only some categories.

    ``categories`` are stored category names (see ``Store.find_category``).
    Nothing about the other categories goes in, so the model can't drift into
    reviewing the whole month. Like ``month_facts``, every number is computed
    here; the model only describes them. The purchases come first: the user
    already sees the totals on the chart, and the point is *why*.
    """
    in_progress = month == month_of(today)
    lines: List[str] = [_month_header(month, today)]

    month_rows = dict(store.totals_by_category(Kind.EXPENSE, month=month))
    # Biggest first this month, then alphabetical, so the order is stable.
    names = sorted(dict.fromkeys(categories), key=lambda n: (-month_rows.get(n, 0), n.lower()))
    picked = {name: month_rows.get(name, 0) for name in names}
    spent = sum(picked.values())
    all_spent = sum(month_rows.values())
    lines.append(f"Categories you asked about: {', '.join(names)}")

    covered, note = store.covered_categories()
    covered_here = [name for name in names if name in set(covered)]
    tag = lambda name: f" [covered: {note}]" if name in covered_here else ""  # noqa: E731

    # ---- what was bought
    expenses = [t for t in store.transactions(month=month) if t.kind is Kind.EXPENSE and t.category in picked]
    lines.append("")
    if not expenses:
        lines.append("No purchases in these categories this month.")
    else:
        # Repeat purchases grouped ("Coffee: 9 purchases, $47.25"), so the model
        # can talk about habits, not just single big items.
        groups = group_purchases(expenses)
        if len(groups) < len(expenses):  # at least one description repeats
            lines.append(f"Purchases this month grouped by description ({len(expenses)} purchases in total):")
            for g in groups[:MAX_GROUPS]:
                count = f"{g.count} purchases" if g.count > 1 else "1 purchase"
                lines.append(f"- {g.description} ({g.category}): {count}, {format_money(g.total_cents)}{tag(g.category)}")
            rest = groups[MAX_GROUPS:]
            if rest:
                lines.append(f"- {len(rest)} other descriptions: {format_money(sum(g.total_cents for g in rest))}")
            lines.append("")
        lines.append("Largest purchases in these categories this month:")
        for tx in sorted(expenses, key=lambda t: t.amount_cents, reverse=True)[:5]:
            lines.append(
                f"- {tx.occurred_on:%b %d}: {tx.description} ({tx.category}) "
                f"{format_money(tx.amount_cents)}{' [covered]' if tx.category in covered_here else ''}"
            )

    # ---- totals and averages
    lines.append("")
    share = f" ({spent / all_spent * 100:.0f}% of all your spending this month)" if all_spent else ""
    lines.append(f"Spending in these categories: {format_money(spent)}{share}")
    controlled = spent - sum(picked[name] for name in covered_here)
    if covered_here:
        lines.append(f"Covered by someone else ({note}): {', '.join(covered_here)}.")
        lines.append(f"Spending you control in these categories (everything not covered): {format_money(controlled)}")

    previous = _previous_months(store, month)
    history = {m: dict(store.totals_by_category(Kind.EXPENSE, month=m)) for m in previous}

    def spent_in(m: str, name: str) -> int:
        return picked[name] if m == month else history[m].get(name, 0)

    if previous:
        avg = statistics.mean(sum(spent_in(m, n) for n in names) for m in previous)
        lines.append(
            f"Average monthly spending in these categories over the previous {len(previous)} month(s): "
            f"{format_money(round(avg))}"
        )
        lines.append(f"This month compared with that average: {_change(spent, avg)}")
        if covered_here:
            avg_controlled = statistics.mean(
                sum(spent_in(m, n) for n in names if n not in covered_here) for m in previous
            )
            lines.append(
                f"Average spending you control in these categories over those months: "
                f"{format_money(round(avg_controlled))}"
            )
            lines.append(f"Spending you control compared with that average: {_change(controlled, avg_controlled)}")
    else:
        lines.append("No earlier months to compare with yet.")

    lines.append("")
    lines.append("By category (this month | previous average | change):" if previous else "By category:")
    for name in names:
        cents = picked[name]
        part = f" ({cents / spent * 100:.0f}% of these categories)" if spent and len(names) > 1 else ""
        if not previous:
            lines.append(f"- {name}: {format_money(cents)}{part}{tag(name)}")
            continue
        cat_avg = statistics.mean(history[m].get(name, 0) for m in previous)
        if cents and cat_avg:
            change = _change(cents, cat_avg)
        elif cents:
            change = "new this month"
        elif cat_avg:
            change = "none yet" if in_progress else "none this month"
        else:
            change = "no spending in any of these months"
        lines.append(f"- {name}: {format_money(cents)}{part} | {format_money(round(cat_avg))} | {change}{tag(name)}")

    # ---- the trend
    if previous:
        span = list(reversed(previous)) + [month]
        fmt = "%b %Y" if span[0][:4] != span[-1][:4] else "%b"
        series = {name: [(m, spent_in(m, name)) for m in span] for name in names}
        if len(names) > 1:
            series["All of these together"] = [(m, sum(spent_in(m, n) for n in names)) for m in span]
        trends = [line for label, points in series.items() if (line := _trend(label, points, in_progress, fmt))]
        if trends:
            lines.append("")
            lines.append("Trend (already worked out for you):")
            lines.extend(trends)

        def point(m: str, cents: int) -> str:
            y, mo = (int(p) for p in m.split("-"))
            so_far = " (so far)" if m == month and in_progress else ""
            return f"{date(y, mo, 1):{fmt}} {format_money(cents)}{so_far}"

        lines.append("")
        lines.append("Month by month (oldest first):")
        for label, points in series.items():
            lines.append(f"- {label}: " + ", ".join(point(m, cents) for m, cents in points))

    rules = [r for r in store.recurring_rules() if r.active and r.kind is Kind.EXPENSE and r.category in picked]
    if rules:
        lines.append("")
        lines.append("Active recurring expenses in these categories:")
        for rule in rules:
            lines.append(
                f"- {rule.description} ({rule.category}): {format_money(rule.amount_cents)} "
                f"{rule.frequency.value}{' [covered]' if rule.category in covered_here else ''}"
            )

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

    def _chat(self, body: Dict[str, Any]) -> Dict[str, Any]:
        # Thinking mode is off: every number is computed by the app, so the
        # model only has to describe them or pick a tool, which is ~3x faster.
        body = {"stream": False, "think": False, **body}
        try:
            payload = self._request("/api/chat", body)
        except AIError as exc:
            if "think" not in str(exc).lower():
                raise
            body.pop("think")  # older models don't accept the setting at all
            payload = self._request("/api/chat", body)
        return payload.get("message", {})

    def review(self, model: str, facts: str, *, focus: bool = False) -> Review:
        """A review of the whole month, or with ``focus`` of the chosen categories
        (``facts`` then comes from ``focus_facts``)."""
        system, schema, request = (
            (FOCUS_PROMPT, FOCUS_SCHEMA, "What's driving my spending in these categories?") if focus
            else (SYSTEM_PROMPT, REVIEW_SCHEMA, "Review this month for me.")
        )
        message = self._chat({
            "model": model,
            "format": schema,
            "options": {"temperature": 0.3},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": f"{request}\n\n{facts}"},
            ],
        })
        content = message.get("content", "")
        return parse_focus_review(content) if focus else parse_review(content)

    def chat(self, model: str, messages: List[Dict[str, Any]], tools: List[Dict[str, Any]]) -> Dict[str, Any]:
        """One step of a tool-using conversation; returns the model's message."""
        return self._chat({
            "model": model,
            "messages": messages,
            "tools": tools,
            "options": {"temperature": 0.2},
        })


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


def parse_focus_review(content: str) -> Review:
    """A FOCUS_SCHEMA reply as a Review: drivers then the trend are the
    observations, ideas are the suggestions."""
    try:
        data = json.loads(content)
        drivers = [str(x) for x in data["drivers"]]
        trend = str(data["trend"])
        return parse_review(json.dumps({
            "headline": data["headline"],
            "observations": drivers[:3] + [trend],
            "suggestions": data["ideas"],
        }))
    except (ValueError, KeyError, TypeError) as exc:
        raise AIError("the model's reply wasn't in the expected format; try again") from exc


def pick_model(installed: Sequence[str], preferred: str) -> Optional[str]:
    """The configured model if installed, else the first installed one."""
    if preferred and preferred in installed:
        return preferred
    return installed[0] if installed else None
