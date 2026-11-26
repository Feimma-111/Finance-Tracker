"""Investment gains, Robinhood style -- plain functions, no database or network.

For each market-priced holding, from its quantity, what you paid
(``cost_basis_cents``, the total for the quantity held), when you bought it
(``bought_on``), today's value, and its daily closing prices:

- total return: value now minus what you paid
- period return (1W, 1M, 3M, YTD, 1Y, ALL): value now minus value at the start
  of the period; if you bought during the period, minus what you paid instead
- today's change: quantity x (price now - the last close before today)
- a value-over-time series for the chart, where each holding counts from the
  day you bought it

Each holding is one purchase (a "lot") with its own date and price, so buying
more later is another holding. ``positions`` groups the purchases of the same
investment into one row and adds their gains up.
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Dict, List, Optional, Sequence, Tuple

from .models import Holding, add_months

PERIODS = ("1W", "1M", "3M", "YTD", "1Y", "ALL")
MAX_POINTS = 400  # chart points; longer series are thinned evenly

Closes = Sequence[Tuple[date, float]]


def period_start(period: str, today: date, earliest: Optional[date]) -> date:
    """First day of ``period`` ending today. "ALL" starts at the earliest purchase."""
    if period == "1W":
        return today - timedelta(days=7)
    if period == "1M":
        return add_months(today, -1)
    if period == "3M":
        return add_months(today, -3)
    if period == "YTD":
        return date(today.year, 1, 1)
    if period == "1Y":
        return add_months(today, -12)
    if period == "ALL":
        return earliest or add_months(today, -12)
    raise ValueError(f"period must be one of {', '.join(PERIODS)}")


def close_on(closes: Closes, day: date, days: Optional[Sequence[date]] = None) -> Optional[float]:
    """The last close on or before ``day`` (markets are closed on weekends).
    Pass ``days`` (the closes' dates) when calling this in a loop."""
    i = bisect.bisect_right(days if days is not None else [d for d, _ in closes], day)
    return closes[i - 1][1] if i else None


def _cents(price: float, quantity: float) -> int:
    value = Decimal(str(price)) * Decimal(str(quantity)) * 100
    return int(value.to_integral_value(rounding=ROUND_HALF_UP))


def _pct(change: int, base: int) -> Optional[float]:
    return round(change / base * 100, 1) if base > 0 else None


@dataclass(frozen=True)
class Return:
    change_cents: int
    pct: Optional[float]  # None when the starting value was 0


@dataclass(frozen=True)
class HoldingReturns:
    holding: Holding
    value_cents: int
    total: Optional[Return]   # None without a cost
    period: Optional[Return]  # None without price history covering the start
    today: Optional[Return]   # None without yesterday's close


def holding_returns(
    holding: Holding, value_cents: int, closes: Closes, start: date, today: date
) -> HoldingReturns:
    total = None
    if holding.cost_basis_cents is not None:
        change = value_cents - holding.cost_basis_cents
        total = Return(change, _pct(change, holding.cost_basis_cents))

    period = None
    if holding.bought_on and holding.bought_on >= start:
        # Bought during the period (or on its first day): the gain since buying.
        if holding.cost_basis_cents is not None:
            start_value: Optional[int] = holding.cost_basis_cents
        else:
            price = close_on(closes, holding.bought_on)
            start_value = _cents(price, holding.quantity) if price is not None else None
    else:
        price = close_on(closes, start)
        start_value = _cents(price, holding.quantity) if price is not None else None
    if start_value is not None:
        change = value_cents - start_value
        period = Return(change, _pct(change, start_value))

    day = None
    previous = close_on(closes, today - timedelta(days=1))
    if previous is not None and (holding.bought_on is None or holding.bought_on < today):
        before = _cents(previous, holding.quantity)
        day = Return(value_cents - before, _pct(value_cents - before, before))
    return HoldingReturns(holding, value_cents, total, period, day)


def value_series(
    items: Sequence[Tuple[Holding, Closes, int]], start: date, today: date
) -> List[Tuple[date, int]]:
    """[(day, cents)] -- what the holdings were worth each day from ``start``
    through today. ``items`` is (holding, closes, value now). A holding counts
    from its ``bought_on`` (or the whole period if unknown). Today's point is
    the live value."""
    days = sorted({start} | {d for _, closes, _ in items for d, _ in closes if start <= d < today})
    dates = [[d for d, _ in closes] for _, closes, _ in items]
    points: List[Tuple[date, int]] = []
    for day in days:
        total = 0
        for (holding, closes, _), own_dates in zip(items, dates):
            if holding.bought_on and holding.bought_on > day:
                continue
            price = close_on(closes, day, own_dates)
            if price is not None:
                total += _cents(price, holding.quantity)
        points.append((day, total))
    points.append((today, sum(value for _, _, value in items)))
    if len(points) > MAX_POINTS:
        step = len(points) / (MAX_POINTS - 1)
        points = [points[int(i * step)] for i in range(MAX_POINTS - 1)] + [points[-1]]
    return points


def combine(returns: Sequence[Optional[Return]], bases: Sequence[int]) -> Optional[Return]:
    """Add up holdings' returns; the percentage is out of the summed starting values.
    ``bases`` are each holding's value now; None returns are skipped."""
    pairs = [(r, base) for r, base in zip(returns, bases) if r is not None]
    if not pairs:
        return None
    change = sum(r.change_cents for r, _ in pairs)
    start = sum(base - r.change_cents for r, base in pairs)
    return Return(change, _pct(change, start))


def account_balances(cash: Sequence[Holding], changes: Dict[int, int]) -> Dict[int, int]:
    """{cash holding id: balance now} = the checked balance plus what linked
    transactions moved it since."""
    return {h.id: (h.manual_value_cents or 0) + changes.get(h.id, 0) for h in cash if h.id is not None}


# ---------------------------------------------------------------- positions
# Buying the same stock twice is two holdings (two "lots"), each with its own
# date and price. A position is all of them together, shown as one row.


def position_key(holding: Holding) -> str:
    """Same type and symbol = same investment ("stock:AAPL")."""
    return f"{holding.asset_type.value}:{(holding.symbol or holding.name).upper()}"


@dataclass(frozen=True)
class Position:
    key: str
    lots: Sequence[HoldingReturns]  # biggest first

    @property
    def name(self) -> str:
        return self.lots[0].holding.name

    @property
    def quantity(self) -> float:
        return sum(lot.holding.quantity for lot in self.lots)

    @property
    def value_cents(self) -> int:
        return sum(lot.value_cents for lot in self.lots)

    @property
    def cost_cents(self) -> Optional[int]:
        """What all the purchases cost, or None if any purchase's price isn't recorded."""
        costs = [lot.holding.cost_basis_cents for lot in self.lots]
        return None if any(c is None for c in costs) else sum(costs)  # type: ignore[arg-type]

    @property
    def first_bought(self) -> Optional[date]:
        days = [lot.holding.bought_on for lot in self.lots if lot.holding.bought_on]
        return min(days) if days else None

    def combined(self, which: str) -> Optional[Return]:
        """The lots' "total", "period" or "today" returns added up."""
        return combine([getattr(lot, which) for lot in self.lots], [lot.value_cents for lot in self.lots])


def positions(lots: Sequence[HoldingReturns]) -> List[Position]:
    """Group lots by investment, biggest position first."""
    groups: Dict[str, List[HoldingReturns]] = {}
    for lot in lots:
        groups.setdefault(position_key(lot.holding), []).append(lot)
    out = [Position(key, sorted(group, key=lambda l: -l.value_cents)) for key, group in groups.items()]
    return sorted(out, key=lambda p: -p.value_cents)
