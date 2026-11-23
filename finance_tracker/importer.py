"""Import transactions from a CSV file (a bank export, a spreadsheet, or this app's own export).

Every bank lays its CSV out differently, so importing is two steps:

1. ``preview`` guesses which column is which (``suggest_mapping``), works out
   the date format, parses every row, and reports what *would* happen:
   how many rows are ready, which are duplicates, and which have problems.
2. ``import_rows`` does the same parsing with the mapping the user confirmed,
   then saves the new rows in one database transaction (all or nothing).

Amounts can come as one signed column (most banks: negative = money out), a
column plus a type column (this app's export), or separate debit / credit
columns. Rows already in the database -- same date, amount, type, and
description -- are skipped, so importing the same file twice is harmless.
"""

from __future__ import annotations

import csv
import io
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Dict, List, Optional, Sequence, Tuple

from .models import Kind, Transaction, dollars_to_cents
from .store import Store

MAX_ROWS = 20000
DEFAULT_CATEGORY = "Uncategorized"

# Label shown to the user -> strptime format. Order matters for "auto": when a
# file fits several (e.g. every day is <= 12), the earlier one is suggested.
DATE_FORMATS: Dict[str, str] = {
    "YYYY-MM-DD": "%Y-%m-%d",
    "MM/DD/YYYY": "%m/%d/%Y",
    "DD/MM/YYYY": "%d/%m/%Y",
    "MM/DD/YY": "%m/%d/%y",
    "DD/MM/YY": "%d/%m/%y",
    "YYYY/MM/DD": "%Y/%m/%d",
    "DD.MM.YYYY": "%d.%m.%Y",
    "MM-DD-YYYY": "%m-%d-%Y",
    "Mon D, YYYY": "%b %d, %Y",
}

# Header words that hint at each field (compared case-insensitively).
HINTS: Dict[str, Tuple[str, ...]] = {
    "date": ("date", "posted", "posting date", "transaction date", "trans date", "occurred_on"),
    "description": ("description", "name", "payee", "merchant", "memo", "details", "narrative", "transaction"),
    "amount": ("amount", "amt", "value", "total"),
    "debit": ("debit", "withdrawal", "withdrawals", "money out", "paid out", "outflow"),
    "credit": ("credit", "deposit", "deposits", "money in", "paid in", "inflow"),
    "category": ("category", "type of spend", "categories"),
    "kind": ("kind", "type", "transaction type", "debit/credit", "dr/cr"),
}

INCOME_WORDS = {"income", "credit", "deposit", "cr", "inflow"}
EXPENSE_WORDS = {"expense", "debit", "withdrawal", "dr", "outflow", "purchase"}


class ImportError_(ValueError):
    """The file or mapping can't be used at all (as opposed to a bad row)."""


@dataclass
class Mapping:
    """Which CSV column holds each field. Column names are the file's headers."""

    date: Optional[str] = None
    description: Optional[str] = None
    amount: Optional[str] = None       # one signed column...
    debit: Optional[str] = None        # ...or separate money-out / money-in columns
    credit: Optional[str] = None
    category: Optional[str] = None     # optional
    kind: Optional[str] = None         # optional: "expense"/"income"/"debit"/"credit"...


@dataclass
class Options:
    date_format: str = "auto"          # a key of DATE_FORMATS, or "auto" (the first that fits)
    positive_is: str = "income"        # for one signed amount column: what a positive number means
    default_category: str = DEFAULT_CATEGORY


@dataclass
class Parsed:
    transactions: List[Tuple[int, Transaction]] = field(default_factory=list)  # (line number, tx)
    errors: List[str] = field(default_factory=list)
    date_format: str = ""
    date_formats: List[str] = field(default_factory=list)  # every format that fits the file


# ------------------------------------------------------------------ reading


def read_csv(text: str) -> Tuple[List[str], List[List[str]]]:
    """(headers, rows). Handles a byte-order mark and ',', ';' or tab separators."""
    text = text.lstrip("﻿")
    if not text.strip():
        raise ImportError_("the file is empty")
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.reader(io.StringIO(text), dialect)
    rows = [row for row in reader if any(cell.strip() for cell in row)]
    if len(rows) < 2:
        raise ImportError_("the file needs a header row and at least one transaction")
    if len(rows) - 1 > MAX_ROWS:
        raise ImportError_(f"the file has more than {MAX_ROWS:,} rows; split it into smaller files")
    headers = [h.strip() or f"Column {i + 1}" for i, h in enumerate(rows[0])]
    if len(set(h.lower() for h in headers)) != len(headers):  # make duplicate names unique
        seen: Counter = Counter()
        unique = []
        for h in headers:
            seen[h.lower()] += 1
            unique.append(h if seen[h.lower()] == 1 else f"{h} ({seen[h.lower()]})")
        headers = unique
    return headers, rows[1:]


def suggest_mapping(headers: Sequence[str], rows: Sequence[List[str]] = ()) -> Mapping:
    """Best guess at which column is which, from the header names.

    A "type" column is only used if every value in it is clearly expense or
    income: banks also put words like "Sale" / "Return" / "Payment" there,
    and for those the sign of the amount is the safer guide.
    """
    lowered = {h: h.lower().strip() for h in headers}
    taken: set = set()

    def find(field_name: str) -> Optional[str]:
        hints = HINTS[field_name]
        for exact in (True, False):  # exact header matches first, then "contains"
            for header, low in lowered.items():
                if header in taken:
                    continue
                if (low in hints) if exact else any(h in low for h in hints if len(h) > 3):
                    taken.add(header)
                    return header
        return None

    mapping = Mapping()
    mapping.date = find("date")
    mapping.debit = find("debit")
    mapping.credit = find("credit")
    mapping.amount = find("amount")
    if mapping.amount and (mapping.debit or mapping.credit):
        mapping.debit = mapping.credit = None  # one signed column wins
    mapping.category = find("category")
    mapping.kind = find("kind")
    if mapping.kind and mapping.amount:
        i = list(headers).index(mapping.kind)
        words = {r[i].strip() for r in rows if i < len(r) and r[i].strip()}
        if not words or any(_kind_from_word(w) is None for w in words):
            mapping.kind = None
    mapping.description = find("description")
    return mapping


# ------------------------------------------------------------------ parsing


def parse_amount(text: str) -> Optional[Decimal]:
    """'$1,234.50' -> 1234.50; '-12.5', '(12.50)', '12.50-' -> -12.50; '' -> None.

    Commas are only accepted as thousands separators ("1,234.50"). European
    files write "42,10" for 42.10; quietly dropping that comma would read it
    as 4,210, so it's rejected instead.
    """
    cleaned = text.strip().replace("$", "").replace(" ", "")
    if not cleaned:
        return None
    if "," in cleaned:
        if not re.fullmatch(r"[-(]?\d{1,3}(,\d{3})+(\.\d+)?[)-]?", cleaned):
            raise ValueError(f"'{text.strip()}' uses a comma as the decimal point, which isn't supported")
        cleaned = cleaned.replace(",", "")
    negative = False
    if cleaned.startswith("(") and cleaned.endswith(")"):  # accounting style
        negative, cleaned = True, cleaned[1:-1]
    if cleaned.endswith("-"):
        negative, cleaned = True, cleaned[:-1]
    try:
        value = Decimal(cleaned)
    except InvalidOperation:
        raise ValueError(f"'{text.strip()}' isn't an amount") from None
    if not value.is_finite():
        raise ValueError(f"'{text.strip()}' isn't an amount")
    return -value if negative else value


def _clean_date_text(text: str) -> str:
    text = text.strip()
    # "2026-07-18T00:00:00" or "2026-07-18 09:30" -> just the date part
    match = re.match(r"^(\d{4}-\d{2}-\d{2})[T ]", text)
    return match.group(1) if match else text


def fitting_date_formats(values: Sequence[str]) -> List[str]:
    """Every DATE_FORMATS label that parses all of ``values``."""
    samples = [_clean_date_text(v) for v in values if v.strip()]
    fits = []
    for label, fmt in DATE_FORMATS.items():
        try:
            for value in samples:
                datetime.strptime(value, fmt)
        except ValueError:
            continue
        fits.append(label)
    return fits


def _kind_from_word(word: str) -> Optional[Kind]:
    low = word.strip().lower()
    if low in INCOME_WORDS:
        return Kind.INCOME
    if low in EXPENSE_WORDS:
        return Kind.EXPENSE
    return None


def parse(text: str, mapping: Mapping, options: Options, today: date) -> Parsed:
    headers, rows = read_csv(text)
    index = {h: i for i, h in enumerate(headers)}
    for name in ("date", "description", "amount", "debit", "credit", "category", "kind"):
        column = getattr(mapping, name)
        if column and column not in index:
            raise ImportError_(f"there's no column called '{column}'")
    if not mapping.date:
        raise ImportError_("choose which column has the date")
    if not mapping.description:
        raise ImportError_("choose which column has the description")
    if not (mapping.amount or mapping.debit or mapping.credit):
        raise ImportError_("choose the amount column (or debit / credit columns)")
    if options.positive_is not in ("income", "expense"):
        raise ImportError_("positive amounts must mean 'income' or 'expense'")

    def cell(row: List[str], column: Optional[str]) -> str:
        if not column:
            return ""
        i = index[column]
        return row[i].strip() if i < len(row) else ""

    result = Parsed()
    result.date_formats = fitting_date_formats([cell(r, mapping.date) for r in rows])
    if options.date_format == "auto":
        if not result.date_formats:
            raise ImportError_("couldn't recognize the date format; pick one from the list")
        result.date_format = result.date_formats[0]
    elif options.date_format in DATE_FORMATS:
        result.date_format = options.date_format
    else:
        raise ImportError_(f"unknown date format '{options.date_format}'")
    fmt = DATE_FORMATS[result.date_format]
    default_category = " ".join(options.default_category.split()) or DEFAULT_CATEGORY

    for line, row in enumerate(rows, start=2):  # line 1 is the header
        try:
            raw_date = cell(row, mapping.date)
            if not raw_date:
                raise ValueError("no date")
            try:
                day = datetime.strptime(_clean_date_text(raw_date), fmt).date()
            except ValueError:
                raise ValueError(f"'{raw_date}' doesn't match {result.date_format}") from None
            if day > today:
                raise ValueError(f"{day.isoformat()} is in the future")

            kind: Optional[Kind] = None
            if mapping.amount:
                amount = parse_amount(cell(row, mapping.amount))
                if amount is None:
                    raise ValueError("no amount")
                if mapping.kind:
                    kind = _kind_from_word(cell(row, mapping.kind))
                    if kind is None:
                        raise ValueError(f"type '{cell(row, mapping.kind)}' isn't expense or income")
                else:
                    positive = Kind(options.positive_is)
                    negative = Kind.EXPENSE if positive is Kind.INCOME else Kind.INCOME
                    kind = positive if amount > 0 else negative
            else:
                debit = parse_amount(cell(row, mapping.debit))
                credit = parse_amount(cell(row, mapping.credit))
                if debit and credit:
                    raise ValueError("has both a debit and a credit")
                if debit:
                    amount, kind = debit, Kind.EXPENSE
                elif credit:
                    amount, kind = credit, Kind.INCOME
                else:
                    raise ValueError("no amount")

            cents = dollars_to_cents(abs(amount))
            if cents == 0:
                raise ValueError("amount is zero")
            description = " ".join(cell(row, mapping.description).split())
            if not description:
                raise ValueError("no description")
            category = " ".join(cell(row, mapping.category).split()) or default_category
            result.transactions.append(
                (line, Transaction(description[:200], cents, category[:60], day, kind))
            )
        except ValueError as exc:
            result.errors.append(f"line {line}: {exc}")
    return result


# ------------------------------------------------------------- duplicates


def _key(tx: Transaction) -> Tuple[str, int, str, str]:
    return (tx.occurred_on.isoformat(), tx.amount_cents, tx.kind.value, tx.description.lower())


def split_duplicates(
    store: Store, parsed: Sequence[Tuple[int, Transaction]]
) -> Tuple[List[Transaction], List[Tuple[int, Transaction]]]:
    """(new, duplicates). A row is a duplicate if the database already has a
    transaction with the same date, amount, type and description. Counts
    matter: if the database has one $4.50 coffee that day and the file has
    two, one of them is new."""
    if not parsed:
        return [], []
    days = [tx.occurred_on for _, tx in parsed]
    existing = Counter(
        _key(tx) for tx in store.search_transactions(start=min(days), end=max(days), limit=10_000_000)
    )
    new, duplicates = [], []
    for line, tx in parsed:
        key = _key(tx)
        if existing[key] > 0:
            existing[key] -= 1
            duplicates.append((line, tx))
        else:
            new.append(tx)
    return new, duplicates


# ------------------------------------------------------------------ steps


def preview(store: Store, text: str, mapping: Optional[Mapping], options: Options, today: date) -> Dict:
    headers, rows = read_csv(text)
    mapping = mapping or suggest_mapping(headers, rows)
    result: Dict = {
        "headers": headers,
        "mapping": mapping.__dict__,
        "total_rows": len(rows),
        "date_format_choices": list(DATE_FORMATS),
    }
    try:
        parsed = parse(text, mapping, options, today)
    except ImportError_ as exc:
        date_formats: List[str] = []
        if mapping.date in headers:
            i = headers.index(mapping.date)
            date_formats = fitting_date_formats([r[i] for r in rows if i < len(r)])
        return {**result, "problem": str(exc), "date_formats": date_formats}
    new, duplicates = split_duplicates(store, parsed.transactions)
    return {
        **result,
        "problem": None,
        "date_format": parsed.date_format,
        "date_formats": parsed.date_formats,
        "ready": len(new),
        "duplicates": len(duplicates),
        "error_count": len(parsed.errors),
        "errors": parsed.errors[:20],
        "sample": [
            {"line": line, "date": tx.occurred_on.isoformat(), "description": tx.description,
             "category": tx.category, "amount_cents": tx.amount_cents, "kind": tx.kind.value}
            for line, tx in parsed.transactions[:8]
        ],
    }


def import_rows(store: Store, text: str, mapping: Mapping, options: Options, today: date) -> Dict:
    parsed = parse(text, mapping, options, today)
    new, duplicates = split_duplicates(store, parsed.transactions)
    imported = store.add_transactions(new)  # one database transaction: all or nothing
    return {
        "imported": imported,
        "duplicates": len(duplicates),
        "error_count": len(parsed.errors),
        "errors": parsed.errors[:20],
    }
