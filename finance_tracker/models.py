"""Core data types plus money and date helpers.

Design notes
------------
* Money is stored as integer cents. Floats can't represent most decimal amounts
  exactly (0.1 + 0.2 == 0.30000000000000004), and those errors pile up in a
  ledger. Integer cents are exact, compact, and sum correctly inside SQLite.
* Transaction amounts are always positive; ``kind`` says which way the money
  moved. That keeps "how much did I spend on food?" a plain SUM.
* Dates are ``datetime.date`` objects in Python and ISO strings (YYYY-MM-DD) on
  disk -- the storage-vs-logic boundary from the original version.
* Currencies: the home currency is USD, and every report adds up USD. A
  transaction in another currency (from an NT$ account, say) keeps what was
  actually paid in ``original_cents`` + ``currency`` and its USD value on that
  day in ``amount_cents``, so past months never change when rates move.
  Amounts in every currency are stored in hundredths ("cents"), even NT$.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from enum import Enum
from typing import Optional

# Yahoo Finance symbol for gold futures, quoted in USD per troy ounce.
GOLD_SYMBOL = "GC=F"

HOME_CURRENCY = "USD"
# Currencies accounts can be in: code -> (symbol, decimals shown).
CURRENCIES = {
    "USD": ("$", 2),
    "TWD": ("NT$", 0),
    "CNY": ("CN¥", 2),
    "HKD": ("HK$", 2),
    "JPY": ("¥", 0),
    "KRW": ("₩", 0),
    "EUR": ("€", 2),
    "GBP": ("£", 2),
    "CAD": ("CA$", 2),
}


def fx_symbol(currency: str) -> str:
    """Yahoo's symbol for "units of ``currency`` per US dollar", e.g. TWD=X."""
    return f"{currency}=X"


def check_currency(code: str) -> str:
    code = (code or "").strip().upper()
    if code not in CURRENCIES:
        raise ValueError(f"currency must be one of {', '.join(CURRENCIES)}")
    return code


def to_home_cents(cents: int, rate: float) -> int:
    """An amount in a currency worth ``rate`` units per USD, in US cents."""
    value = Decimal(cents) / Decimal(str(rate))
    return int(value.to_integral_value(rounding=ROUND_HALF_UP))

_CENT = Decimal("0.01")
_MAX_AMOUNT = Decimal("1000000000000")  # one trillion dollars; anything above is a typo


class Kind(str, Enum):
    EXPENSE = "expense"
    INCOME = "income"


class AssetType(str, Enum):
    CASH = "cash"      # bank accounts, savings, cash on hand -- valued by hand
    STOCK = "stock"    # shares / ETFs, priced live by ticker
    CRYPTO = "crypto"  # priced live by Yahoo symbol, e.g. BTC-USD
    GOLD = "gold"      # troy ounces, priced live
    OTHER = "other"    # car, collectibles, anything valued by hand

    @property
    def is_market_priced(self) -> bool:
        return self in (AssetType.STOCK, AssetType.CRYPTO, AssetType.GOLD)


class Frequency(str, Enum):
    WEEKLY = "weekly"
    BIWEEKLY = "biweekly"
    MONTHLY = "monthly"
    YEARLY = "yearly"


def _check_entry(description: str, amount_cents: int, category: str) -> None:
    if not isinstance(amount_cents, int) or amount_cents <= 0:
        raise ValueError("amount must be greater than zero")
    if not description.strip():
        raise ValueError("description can't be empty")
    if not category.strip():
        raise ValueError("category can't be empty")


@dataclass(frozen=True)
class Transaction:
    description: str
    amount_cents: int
    category: str
    occurred_on: date
    kind: Kind = Kind.EXPENSE
    id: Optional[int] = None
    recurring_id: Optional[int] = None  # set when a recurring rule created it
    account_id: Optional[int] = None    # the cash account (a cash Holding) it was paid from / into
    currency: str = HOME_CURRENCY       # what it was paid in (its account's currency)
    original_cents: Optional[int] = None  # the amount in ``currency``; None when that's USD

    def __post_init__(self) -> None:
        _check_entry(self.description, self.amount_cents, self.category)

    @property
    def paid_cents(self) -> int:
        """The amount in the currency it was paid in."""
        return self.original_cents if self.original_cents is not None else self.amount_cents


@dataclass(frozen=True)
class RecurringRule:
    """A transaction that repeats, like rent or a subscription.

    ``generated_count`` is how many occurrences have already been turned into
    real transactions. The next one is always computed from ``start_on`` (not
    from the previous occurrence), so a rule on the 31st goes Jan 31 -> Feb 28
    -> Mar 31 instead of drifting to the 28th forever.
    """

    description: str
    amount_cents: int
    category: str
    frequency: Frequency
    start_on: date
    kind: Kind = Kind.EXPENSE
    generated_count: int = 0
    active: bool = True
    id: Optional[int] = None
    account_id: Optional[int] = None  # cash account its transactions use
    currency: str = HOME_CURRENCY     # amount_cents is in this currency (the account's)

    def __post_init__(self) -> None:
        _check_entry(self.description, self.amount_cents, self.category)

    def occurrence(self, n: int) -> date:
        return occurrence(self.start_on, self.frequency, n)

    @property
    def next_due(self) -> date:
        return self.occurrence(self.generated_count)


def add_months(day: date, months: int) -> date:
    """Same day-of-month, ``months`` later; clamped to the month's last day."""
    year, month_index = divmod(day.year * 12 + (day.month - 1) + months, 12)
    month = month_index + 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def occurrence(start: date, frequency: Frequency, n: int) -> date:
    """The date of the n-th occurrence (n=0 is ``start`` itself)."""
    if frequency is Frequency.WEEKLY:
        return start + timedelta(weeks=n)
    if frequency is Frequency.BIWEEKLY:
        return start + timedelta(weeks=2 * n)
    if frequency is Frequency.MONTHLY:
        return add_months(start, n)
    return add_months(start, 12 * n)


@dataclass(frozen=True)
class Holding:
    """Something you own.

    Market-priced holdings (stock, crypto, gold) are worth quantity x live price.
    ``bought_on`` and ``cost_basis_cents`` (the total paid for the quantity
    held) give gain/loss. Cash and "other" holdings carry a value you set by
    hand; for a cash account, ``balance_as_of`` is the day that value was
    checked, and transactions linked to it after that day move it.
    """

    asset_type: AssetType
    name: str
    quantity: float = 1.0
    symbol: Optional[str] = None
    manual_value_cents: Optional[int] = None
    id: Optional[int] = None
    bought_on: Optional[date] = None
    cost_basis_cents: Optional[int] = None
    balance_as_of: Optional[date] = None
    currency: str = HOME_CURRENCY  # cash accounts: the balance's currency

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("name can't be empty")
        if self.quantity < 0:
            raise ValueError("quantity can't be negative")
        if self.cost_basis_cents is not None and self.cost_basis_cents < 0:
            raise ValueError("the amount paid can't be negative")
        if self.asset_type.is_market_priced:
            if not self.symbol:
                raise ValueError(f"{self.asset_type.value} holdings need a market symbol")
        elif self.manual_value_cents is None:
            raise ValueError(f"{self.asset_type.value} holdings need a value")


@dataclass(frozen=True)
class Transfer:
    """Money moved between two of your own accounts. Not spending or income,
    so it never shows up in reports -- it only changes the two balances.
    ``to_cents`` differs from ``from_cents`` when the currencies differ."""

    occurred_on: date
    from_account_id: int
    to_account_id: int
    from_cents: int
    to_cents: int
    note: str = ""
    id: Optional[int] = None

    def __post_init__(self) -> None:
        if self.from_cents <= 0 or self.to_cents <= 0:
            raise ValueError("amount must be greater than zero")
        if self.from_account_id == self.to_account_id:
            raise ValueError("pick two different accounts")


def format_amount(cents: int, currency: str = HOME_CURRENCY) -> str:
    """format_money for any currency: 35000 TWD -> 'NT$350'."""
    if currency == HOME_CURRENCY:
        return format_money(cents)
    symbol, decimals = CURRENCIES.get(currency, (currency + " ", 2))
    sign = "-" if cents < 0 else ""
    value = Decimal(abs(cents)) / 100
    return f"{sign}{symbol}{value:,.{decimals}f}"


# --------------------------------------------------------------------- money

def dollars_to_cents(amount: Decimal) -> int:
    return int((amount * 100).to_integral_value(rounding=ROUND_HALF_UP))


def parse_money(text: str) -> int:
    """Turn user input like '$1,234.50' into cents (123450).

    Raises ValueError with a message that's safe to show the user.
    """
    cleaned = text.strip().replace(",", "").replace("$", "")
    if not cleaned:
        raise ValueError("enter an amount")
    try:
        amount = Decimal(cleaned)
    except InvalidOperation:
        raise ValueError(f"'{text.strip()}' isn't a number") from None
    if not amount.is_finite():
        raise ValueError(f"'{text.strip()}' isn't a number")
    if abs(amount) >= _MAX_AMOUNT:
        raise ValueError("that amount is too large")
    if amount != amount.quantize(_CENT):
        raise ValueError("use at most two decimal places")
    return dollars_to_cents(amount)


def format_money(cents: int) -> str:
    """123450 -> '$1,234.50'; -500 -> '-$5.00'."""
    sign = "-" if cents < 0 else ""
    dollars, remainder = divmod(abs(cents), 100)
    return f"{sign}${dollars:,}.{remainder:02d}"


def cents_to_plain(cents: int) -> str:
    """123450 -> '1234.50' (no symbol or separators; for CSV export)."""
    sign = "-" if cents < 0 else ""
    dollars, remainder = divmod(abs(cents), 100)
    return f"{sign}{dollars}.{remainder:02d}"


# --------------------------------------------------------------------- dates

_DATE_FORMATS = ("%Y-%m-%d", "%Y/%m/%d")


def parse_date(text: str, *, today: date, allow_future: bool = False) -> date:
    """Accept YYYY-MM-DD, YYYY/MM/DD, 'today', 'yesterday', or blank (= today).

    Future dates are rejected unless ``allow_future`` (used for the first date
    of a recurring rule, which may be next month's rent).
    """
    cleaned = text.strip().lower()
    if cleaned in ("", "today"):
        return today
    if cleaned == "yesterday":
        return today - timedelta(days=1)
    for fmt in _DATE_FORMATS:
        try:
            parsed = datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue
        if parsed > today and not allow_future:
            raise ValueError("that date is in the future")
        if allow_future and parsed > add_months(today, 12):
            raise ValueError("pick a date within the next year")
        return parsed
    raise ValueError("use YYYY-MM-DD, or press Enter for today")


def parse_month(text: str) -> str:
    """Validate 'YYYY-MM' (or 'YYYY/MM') and return it as 'YYYY-MM'."""
    cleaned = text.strip().replace("/", "-")
    try:
        return datetime.strptime(cleaned, "%Y-%m").strftime("%Y-%m")
    except ValueError:
        raise ValueError("use YYYY-MM, e.g. 2026-07") from None


def month_of(day: date) -> str:
    return day.strftime("%Y-%m")


def shift_month(month: str, delta: int) -> str:
    """shift_month('2026-01', -1) -> '2025-12'."""
    year, mon = (int(part) for part in month.split("-"))
    index = year * 12 + (mon - 1) + delta
    return f"{index // 12:04d}-{index % 12 + 1:02d}"
