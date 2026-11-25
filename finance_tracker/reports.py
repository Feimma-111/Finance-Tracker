"""Pure calculations behind the reports -- no database, no printing.

Keeping these as plain functions over plain data makes them easy to test and
reusable by a future web dashboard (Phase 4) or AI summary (Phase 5).
"""

from __future__ import annotations

import calendar
import statistics
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from .models import Holding, Transaction, shift_month, to_home_cents
from .prices import PriceUnavailable, Quote

# ------------------------------------------------------------- purchases


@dataclass(frozen=True)
class PurchaseGroup:
    description: str  # the spelling of the first one seen (transactions come newest first)
    category: str
    count: int
    total_cents: int


def group_purchases(transactions: Sequence[Transaction]) -> List[PurchaseGroup]:
    """Repeat purchases together ("Boba: 3 purchases, $87.81"): the same
    description, ignoring capitals and extra spaces, in the same category.
    Biggest total first."""
    amounts: Dict[Tuple[str, str], List[int]] = {}
    shown: Dict[Tuple[str, str], str] = {}
    for tx in transactions:
        key = (" ".join(tx.description.lower().split()), tx.category)
        amounts.setdefault(key, []).append(tx.amount_cents)
        shown.setdefault(key, " ".join(tx.description.split()))
    groups = [PurchaseGroup(shown[key], key[1], len(a), sum(a)) for key, a in amounts.items()]
    return sorted(groups, key=lambda g: (-g.total_cents, g.description.lower()))


# ------------------------------------------------------------- spending caps

NEAR_CAP = 0.9  # "close to the cap" from 90% of it


@dataclass(frozen=True)
class CapStatus:
    category: str
    cap_cents: int          # in US dollars, at today's rate if it was set in another currency
    spent_cents: int
    month_share: float      # how much of the month has gone: 1.0 for a finished month

    @property
    def share(self) -> float:
        return self.spent_cents / self.cap_cents

    @property
    def left_cents(self) -> int:
        return self.cap_cents - self.spent_cents  # negative when over

    @property
    def status(self) -> str:
        """'over', 'near' (90%+ of the cap), or 'ok'."""
        if self.spent_cents > self.cap_cents:
            return "over"
        return "near" if self.share >= NEAR_CAP else "ok"


def month_share(month: str, today_iso: str) -> float:
    """How much of ``month`` has gone by ``today``: 0 for the future, 1 once it's over."""
    year, mon = (int(p) for p in month.split("-"))
    days = calendar.monthrange(year, mon)[1]
    current = today_iso[:7]
    if month < current:
        return 1.0
    if month > current:
        return 0.0
    return int(today_iso[8:10]) / days


def cap_statuses(
    caps: Sequence[Tuple[str, int, str]],
    spent: Dict[str, int],
    rate: Callable[[str], Optional[float]],
    share: float,
) -> List[CapStatus]:
    """Each cap against the month's spending (``spent`` is USD cents by
    category), most used first. ``rate(currency)`` converts caps set in
    another currency; a cap with no rate available is left out."""
    out = []
    for name, cents, currency in caps:
        units_per_dollar = rate(currency)
        if not units_per_dollar:
            continue
        out.append(CapStatus(name, to_home_cents(cents, units_per_dollar), spent.get(name, 0), share))
    return sorted(out, key=lambda c: (-c.share, c.category.lower()))


# ------------------------------------------------------------- monthly spend


@dataclass(frozen=True)
class MonthRow:
    month: str
    total_cents: int
    z_score: Optional[float]  # standard deviations away from the average month
    in_progress: bool = False

    @property
    def label(self) -> str:
        if self.in_progress:
            return "in progress"
        if self.z_score is None:
            return ""
        if self.z_score >= 2:
            return "well above usual"
        if self.z_score >= 1:
            return "above usual"
        if self.z_score <= -2:
            return "well below usual"
        if self.z_score <= -1:
            return "below usual"
        return ""


@dataclass(frozen=True)
class MonthlyReport:
    rows: List[MonthRow]
    mean_cents: Optional[float]   # average of completed months
    stdev_cents: Optional[float]  # typical swing between completed months


def month_range(start: str, end: str) -> List[str]:
    """Inclusive list of 'YYYY-MM' strings."""
    months = []
    month = start
    while month <= end:
        months.append(month)
        month = shift_month(month, 1)
    return months


def monthly_report(
    month_totals: Sequence[Tuple[str, int]], *, current_month: str, window: int = 12
) -> MonthlyReport:
    """Spending per month, with how unusual each month was.

    * Months with no spending count as $0 (gaps are filled in).
    * Only the last ``window`` months are shown, starting no earlier than your
      first recorded month -- so months before you started tracking don't drag
      the average down.
    * The current month is still in progress, so it's shown but left out of the
      average and standard deviation.
    """
    totals = dict(month_totals)
    if not totals:
        return MonthlyReport([], None, None)

    start = max(min(totals), shift_month(current_month, -(window - 1)))
    end = max(max(totals), current_month)
    months = month_range(start, end)

    baseline = [totals.get(m, 0) for m in months if m < current_month]
    mean = statistics.mean(baseline) if baseline else None
    stdev = statistics.stdev(baseline) if len(baseline) >= 2 else None

    rows = []
    for month in months:
        value = totals.get(month, 0)
        finished = month < current_month
        z_score = (value - mean) / stdev if (finished and stdev and mean is not None) else None
        rows.append(MonthRow(month, value, z_score, in_progress=not finished))
    return MonthlyReport(rows, mean, stdev)


# ----------------------------------------------------------------- net worth


@dataclass(frozen=True)
class HoldingValue:
    holding: Holding
    value_cents: Optional[int]          # None when it couldn't be valued
    unit_price: Optional[float] = None  # USD per unit, for market-priced holdings
    note: str = ""


@dataclass(frozen=True)
class NetWorthReport:
    lines: List[HoldingValue]
    total_cents: int
    complete: bool  # False if any holding is missing from the total


def value_holdings(
    holdings: Sequence[Holding],
    quote: Callable[[str], Quote],
    balances: Optional[Dict[int, int]] = None,
    fx: Optional[Callable[[str], float]] = None,
) -> NetWorthReport:
    """Value everything in USD. ``balances`` overrides cash accounts'
    hand-entered values with their balance now (see
    ``portfolio.account_balances``), in each account's currency; ``fx(code)``
    gives units of that currency per US dollar."""
    lines = []
    balances = balances or {}
    for holding in holdings:
        if not holding.asset_type.is_market_priced:
            value = balances.get(holding.id, holding.manual_value_cents) if holding.id is not None \
                else holding.manual_value_cents
            if value is not None and holding.currency != "USD":
                try:
                    if fx is None:
                        raise PriceUnavailable("no exchange rates available")
                    value = to_home_cents(value, fx(holding.currency))
                except PriceUnavailable as exc:
                    lines.append(HoldingValue(holding, None, note=f"not counted: no {holding.currency} rate ({exc})"))
                    continue
            lines.append(HoldingValue(holding, value))
            continue
        try:
            q = quote(holding.symbol or "")
        except PriceUnavailable as exc:
            lines.append(HoldingValue(holding, None, note=f"not counted: {exc}"))
            continue
        if q.currency != "USD":
            lines.append(
                HoldingValue(holding, None, note=f"priced in {q.currency}; not counted")
            )
            continue
        value = Decimal(str(q.price)) * Decimal(str(holding.quantity)) * 100
        note = (
            f"last known price from {q.fetched_at:%Y-%m-%d %H:%M} UTC (offline)"
            if q.stale
            else ""
        )
        lines.append(
            HoldingValue(
                holding,
                int(value.to_integral_value(rounding=ROUND_HALF_UP)),
                unit_price=q.price,
                note=note,
            )
        )
    total = sum(line.value_cents for line in lines if line.value_cents is not None)
    complete = all(line.value_cents is not None for line in lines)
    return NetWorthReport(lines, total, complete)


# ------------------------------------------------------------------ charting


def bar(value: float, largest: float, width: int = 24) -> str:
    """A text bar scaled so ``largest`` fills ``width`` characters."""
    if largest <= 0 or value <= 0:
        return ""
    return "█" * max(1, round(width * value / largest))
