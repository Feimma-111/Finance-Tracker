"""Ask questions about your money, answered by the model on your PC.

The model never sees your raw database and never does arithmetic. Instead it
gets a small set of read-only *tools* -- "total spending between two dates",
"compare two periods", "find transactions"... -- and works like this:

    question -> model picks a tool + arguments -> Python runs the query
             -> model reads the exact result -> (maybe another tool) -> answer

Every number in a tool result is computed here. As a final safety net,
``unverified_numbers`` checks that every dollar amount and percentage in the
answer actually appeared in a tool result; anything else is flagged in the UI.
"""

from __future__ import annotations

import calendar
import json
import re
from datetime import date
from decimal import Decimal
from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Tuple

from .models import Frequency, Kind, format_money, month_of, shift_month
from .store import Store

MAX_TOOL_ROUNDS = 6
MAX_HISTORY_MESSAGES = 6
MAX_MONTHS = 36

SYSTEM_PROMPT = """\
You answer questions about the user's personal finances, using ONLY the tools \
provided to look up their data. Today is {today} ({weekday}). The current month \
is {month}. Their records start on {first}.

Rules:
- Always call a tool to get numbers. Never guess, and never do arithmetic \
yourself: for differences or comparisons use compare_spending, for averages use \
monthly_spending, for monthly costs of subscriptions use recurring_charges.
- Quote dollar amounts and percentages exactly as the tools return them.
- Turn relative dates into exact ones: "since August" means {year}-08-01 to \
{today}; "last month" means all of {last_month}; "this year" means {year}-01-01 \
to {today}.
- Category names come from list_categories; match the user's words to them.
- If the data can't answer the question, say so plainly.
- Be brief: one to four sentences, or a short list.
- Do not recommend specific investments, securities, or financial products.
"""


def _date_param(description: str) -> Dict[str, str]:
    return {"type": "string", "description": description + " (YYYY-MM-DD)"}


_CATEGORY = {"type": "string", "description": "Optional category name from list_categories"}

TOOLS: List[Dict[str, Any]] = [
    {"type": "function", "function": {
        "name": "list_categories",
        "description": "The user's spending and income category names.",
        "parameters": {"type": "object", "properties": {}},
    }},
    {"type": "function", "function": {
        "name": "spending_total",
        "description": "Total spending between two dates (inclusive), optionally for one category.",
        "parameters": {"type": "object", "properties": {
            "start": _date_param("First day"), "end": _date_param("Last day"), "category": _CATEGORY,
        }, "required": ["start", "end"]},
    }},
    {"type": "function", "function": {
        "name": "income_total",
        "description": "Total income between two dates (inclusive), optionally for one category.",
        "parameters": {"type": "object", "properties": {
            "start": _date_param("First day"), "end": _date_param("Last day"), "category": _CATEGORY,
        }, "required": ["start", "end"]},
    }},
    {"type": "function", "function": {
        "name": "spending_by_category",
        "description": "Spending per category between two dates, largest first, with each one's share.",
        "parameters": {"type": "object", "properties": {
            "start": _date_param("First day"), "end": _date_param("Last day"),
        }, "required": ["start", "end"]},
    }},
    {"type": "function", "function": {
        "name": "compare_spending",
        "description": "Compare spending in two periods: both totals, the difference, and the percent change "
                       "from the first period to the second.",
        "parameters": {"type": "object", "properties": {
            "first_start": _date_param("First period start"), "first_end": _date_param("First period end"),
            "second_start": _date_param("Second period start"), "second_end": _date_param("Second period end"),
            "category": _CATEGORY,
        }, "required": ["first_start", "first_end", "second_start", "second_end"]},
    }},
    {"type": "function", "function": {
        "name": "monthly_spending",
        "description": "Spending for each month in a range, plus the monthly average, highest and lowest month.",
        "parameters": {"type": "object", "properties": {
            "start_month": {"type": "string", "description": "YYYY-MM"},
            "end_month": {"type": "string", "description": "YYYY-MM"},
            "category": _CATEGORY,
        }, "required": ["start_month", "end_month"]},
    }},
    {"type": "function", "function": {
        "name": "find_transactions",
        "description": "Look up individual transactions, filtered by words in the description, category, "
                       "type, and dates. Use order='largest' for biggest purchases. Returns expenses "
                       "unless kind is 'income' or 'any'.",
        "parameters": {"type": "object", "properties": {
            "text": {"type": "string", "description": "Words to search for in the description"},
            "category": _CATEGORY,
            "kind": {"type": "string", "enum": ["expense", "income", "any"]},
            "start": _date_param("Optional first day"), "end": _date_param("Optional last day"),
            "order": {"type": "string", "enum": ["newest", "largest"]},
            "limit": {"type": "integer", "description": "How many to return (max 20)"},
        }},
    }},
    {"type": "function", "function": {
        "name": "recurring_charges",
        "description": "Active recurring transactions (subscriptions, rent, paychecks) with their monthly "
                       "equivalent cost and the total per month.",
        "parameters": {"type": "object", "properties": {}},
    }},
    {"type": "function", "function": {
        "name": "net_worth_history",
        "description": "Recorded net worth: the latest value and the change since a starting date.",
        "parameters": {"type": "object", "properties": {"since": _date_param("Optional starting date")}},
    }},
]


class ToolError(ValueError):
    """Bad arguments from the model; sent back to it so it can try again."""


# ---------------------------------------------------------------- tools


class Tools:
    def __init__(self, store: Store, today: date) -> None:
        self.store = store
        self.today = today

    def run(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        handler = getattr(self, f"tool_{name}", None)
        if handler is None:
            return {"error": f"there is no tool named {name}"}
        try:
            return handler(**{k: v for k, v in (arguments or {}).items() if v not in (None, "")})
        except TypeError as exc:
            return {"error": f"bad arguments for {name}: {exc}"}
        except ToolError as exc:
            return {"error": str(exc)}

    # -- helpers

    def _day(self, value: str, *, end: bool = False) -> date:
        text = str(value).strip()
        try:
            if re.fullmatch(r"\d{4}-\d{2}", text):  # a whole month
                year, month = map(int, text.split("-"))
                return date(year, month, calendar.monthrange(year, month)[1] if end else 1)
            return date.fromisoformat(text)
        except ValueError:
            raise ToolError(f"'{value}' isn't a date; use YYYY-MM-DD") from None

    def _period(self, start: str, end: str) -> Tuple[date, date]:
        first, last = self._day(start), self._day(end, end=True)
        if first > last:
            raise ToolError("the start date is after the end date")
        return first, last

    def _category(self, name: Optional[str]) -> Optional[str]:
        if not name:
            return None
        found = self.store.find_category(name)
        if not found:
            names = ", ".join(self.store.categories(Kind.EXPENSE) + self.store.categories(Kind.INCOME))
            raise ToolError(f"there's no category called '{name}'. The categories are: {names}")
        return found

    @staticmethod
    def _label(first: date, last: date) -> str:
        return f"{first.isoformat()} to {last.isoformat()}"

    # -- the tools

    def tool_list_categories(self) -> Dict[str, Any]:
        return {"expense_categories": self.store.categories(Kind.EXPENSE),
                "income_categories": self.store.categories(Kind.INCOME)}

    def _total(self, kind: Kind, start: str, end: str, category: Optional[str]) -> Dict[str, Any]:
        first, last = self._period(start, end)
        name = self._category(category)
        cents, count = self.store.total_between(kind, first, last, category=name)
        return {"period": self._label(first, last), "category": name or "all categories",
                "total": format_money(cents), "transactions": count}

    def tool_spending_total(self, start: str, end: str, category: Optional[str] = None) -> Dict[str, Any]:
        return self._total(Kind.EXPENSE, start, end, category)

    def tool_income_total(self, start: str, end: str, category: Optional[str] = None) -> Dict[str, Any]:
        return self._total(Kind.INCOME, start, end, category)

    def tool_spending_by_category(self, start: str, end: str) -> Dict[str, Any]:
        first, last = self._period(start, end)
        rows = self.store.category_totals_between(Kind.EXPENSE, first, last)
        total = sum(c for _, c in rows)
        return {
            "period": self._label(first, last),
            "total": format_money(total),
            "categories": [
                {"category": name, "total": format_money(cents), "share": f"{cents / total * 100:.1f}%"}
                for name, cents in rows
            ],
        }

    def tool_compare_spending(
        self, first_start: str, first_end: str, second_start: str, second_end: str,
        category: Optional[str] = None,
    ) -> Dict[str, Any]:
        name = self._category(category)
        a_first, a_last = self._period(first_start, first_end)
        b_first, b_last = self._period(second_start, second_end)
        a, _ = self.store.total_between(Kind.EXPENSE, a_first, a_last, category=name)
        b, _ = self.store.total_between(Kind.EXPENSE, b_first, b_last, category=name)
        diff = b - a
        result: Dict[str, Any] = {
            "category": name or "all categories",
            "first_period": {"period": self._label(a_first, a_last), "total": format_money(a)},
            "second_period": {"period": self._label(b_first, b_last), "total": format_money(b)},
            "difference": "the same" if diff == 0 else
                          f"{format_money(abs(diff))} {'more' if diff > 0 else 'less'} in the second period",
        }
        if a:
            result["percent_change"] = f"{diff / a * 100:+.1f}%"
        return result

    def tool_monthly_spending(
        self, start_month: str, end_month: str, category: Optional[str] = None
    ) -> Dict[str, Any]:
        first = self._day(start_month)
        last = self._day(end_month, end=True)
        if first > last:
            raise ToolError("the start month is after the end month")
        name = self._category(category)
        months: List[str] = []
        month = month_of(first)
        while month <= month_of(last) and len(months) < MAX_MONTHS:
            months.append(month)
            month = shift_month(month, 1)
        values = []
        for m in months:
            y, mo = map(int, m.split("-"))
            cents, _ = self.store.total_between(
                Kind.EXPENSE, date(y, mo, 1), date(y, mo, calendar.monthrange(y, mo)[1]), category=name
            )
            values.append(cents)
        result: Dict[str, Any] = {
            "category": name or "all categories",
            "months": [{"month": m, "total": format_money(v)} for m, v in zip(months, values)],
        }
        # The current month isn't over, so it would drag the average down and
        # always look like the "lowest" month. Leave it out of those stats.
        current = month_of(self.today)
        done = [(m, v) for m, v in zip(months, values) if m < current]
        if current in months:
            result["note"] = (f"{current} is still in progress, so it is left out of the average, "
                              "highest and lowest")
        if done:
            average = Decimal(sum(v for _, v in done)) / len(done)
            hi = max(done, key=lambda mv: mv[1])
            lo = min(done, key=lambda mv: mv[1])
            result["monthly_average"] = format_money(int(average.to_integral_value()))
            result["months_averaged"] = len(done)
            result["highest_month"] = {"month": hi[0], "total": format_money(hi[1])}
            result["lowest_month"] = {"month": lo[0], "total": format_money(lo[1])}
        return result

    def tool_find_transactions(
        self, text: Optional[str] = None, category: Optional[str] = None, kind: str = "expense",
        start: Optional[str] = None, end: Optional[str] = None, order: str = "newest", limit: int = 10,
    ) -> Dict[str, Any]:
        # Defaults to expenses: "my biggest purchases" shouldn't come back as paychecks.
        if kind not in ("expense", "income", "any"):
            raise ToolError("kind must be 'expense', 'income', or 'any'")
        rows = self.store.search_transactions(
            text=text, category=self._category(category), kind=None if kind == "any" else Kind(kind),
            start=self._day(start) if start else None, end=self._day(end, end=True) if end else None,
            order="largest" if order == "largest" else "newest", limit=max(1, min(int(limit), 20)),
        )
        return {"count": len(rows), "transactions": [
            {"date": t.occurred_on.isoformat(), "description": t.description, "category": t.category,
             "amount": format_money(t.amount_cents), "type": t.kind.value}
            for t in rows
        ]}

    def tool_recurring_charges(self) -> Dict[str, Any]:
        per_year = {Frequency.WEEKLY: 52, Frequency.BIWEEKLY: 26, Frequency.MONTHLY: 12, Frequency.YEARLY: 1}
        rules = [r for r in self.store.recurring_rules() if r.active]
        items, monthly_expense = [], 0
        for r in rules:
            monthly = round(r.amount_cents * per_year[r.frequency] / 12)
            if r.kind is Kind.EXPENSE:
                monthly_expense += monthly
            items.append({"description": r.description, "category": r.category, "type": r.kind.value,
                          "amount": format_money(r.amount_cents), "frequency": r.frequency.value,
                          "monthly_equivalent": format_money(monthly), "next_date": r.next_due.isoformat()})
        return {"recurring": items, "recurring_expenses_per_month": format_money(monthly_expense)}

    def tool_net_worth_history(self, since: Optional[str] = None) -> Dict[str, Any]:
        points = self.store.net_worth_history()
        if not points:
            return {"error": "no net worth has been recorded yet (add holdings and open the Holdings page)"}
        latest_day, latest = points[-1]
        result: Dict[str, Any] = {"latest": {"date": latest_day.isoformat(), "net_worth": format_money(latest)}}
        if since:
            start = self._day(since)
            earlier = [p for p in points if p[0] >= start]
            if earlier:
                day, value = earlier[0]
                change = latest - value
                result["earliest_since"] = {"date": day.isoformat(), "net_worth": format_money(value)}
                result["change"] = f"{'up' if change >= 0 else 'down'} {format_money(abs(change))}"
        return result


# ---------------------------------------------------------- the conversation


def system_prompt(store: Store, today: date) -> str:
    earliest = store.first_transaction_date()
    return SYSTEM_PROMPT.format(
        today=today.isoformat(), weekday=f"{today:%A}", month=month_of(today), year=today.year,
        last_month=shift_month(month_of(today), -1),
        first=earliest.isoformat() if earliest else "today (no data yet)",
    )


def ask(
    store: Store,
    today: date,
    question: str,
    chat: Callable[[List[Dict[str, Any]], List[Dict[str, Any]]], Dict[str, Any]],
    history: Sequence[Dict[str, str]] = (),
) -> Dict[str, Any]:
    """Run the question -> tools -> answer loop. ``chat`` sends messages to the model."""
    tools = Tools(store, today)
    messages: List[Dict[str, Any]] = [{"role": "system", "content": system_prompt(store, today)}]
    for turn in list(history)[-MAX_HISTORY_MESSAGES:]:
        if turn.get("role") in ("user", "assistant") and turn.get("content"):
            messages.append({"role": turn["role"], "content": str(turn["content"])[:2000]})
    messages.append({"role": "user", "content": question})

    steps: List[Dict[str, Any]] = []
    for _ in range(MAX_TOOL_ROUNDS):
        reply = chat(messages, TOOLS)
        calls = reply.get("tool_calls") or []
        if not calls:
            answer = (reply.get("content") or "").strip()
            if not answer:
                break
            return {"answer": answer, "steps": steps,
                    "unverified": unverified_numbers(answer, steps)}
        messages.append({"role": "assistant", "content": reply.get("content") or "", "tool_calls": calls})
        for call in calls:
            function = call.get("function", {})
            name = function.get("name", "")
            arguments = function.get("arguments") or {}
            if isinstance(arguments, str):  # some models send JSON text
                try:
                    arguments = json.loads(arguments)
                except ValueError:
                    arguments = {}
            result = tools.run(name, arguments)
            steps.append({"tool": name, "arguments": arguments, "result": result})
            messages.append({"role": "tool", "tool_name": name, "content": json.dumps(result)})
    return {"answer": "Sorry, I couldn't work that out. Try asking in a different way.",
            "steps": steps, "unverified": []}


# --------------------------------------------------------- number checking

_MONEY = re.compile(r"-?\$\s?[\d,]+(?:\.\d+)?")
_PERCENT = re.compile(r"[+-]?\d+(?:\.\d+)?\s?%")


def _money_cents(text: str) -> int:
    value = Decimal(text.replace("$", "").replace(",", "").replace(" ", ""))
    return int((value * 100).to_integral_value())


def _percent(text: str) -> Decimal:
    return abs(Decimal(text.replace("%", "").replace(" ", "")))


def unverified_numbers(answer: str, steps: Sequence[Dict[str, Any]]) -> List[str]:
    """Dollar amounts / percentages in ``answer`` that no tool returned.

    Rounding is allowed: "$1,084" matches a tool's "$1,084.27", and "16%"
    matches "15.9%". Anything else was not computed by the app.
    """
    blob = json.dumps([s["result"] for s in steps])
    known_cents: Set[int] = {abs(_money_cents(m)) for m in _MONEY.findall(blob)}
    known_pcts: Set[Decimal] = {_percent(p) for p in _PERCENT.findall(blob)}

    flagged = []
    for match in _MONEY.findall(answer):
        cents = abs(_money_cents(match))
        if not any(cents == k or cents == round(k / 100) * 100 for k in known_cents):
            flagged.append(match.strip())
    for match in _PERCENT.findall(answer):
        pct = _percent(match)
        if not any(pct == k or pct == k.quantize(Decimal(1)) or pct == k.quantize(Decimal("0.1"))
                   for k in known_pcts):
            flagged.append(match.strip())
    return flagged
