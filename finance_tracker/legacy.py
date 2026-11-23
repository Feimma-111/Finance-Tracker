"""Import transactions from the original JSON-lines save file.

The first version of this app wrote one JSON object per line to
``information_save_file``, shaped like:
    {"name": "Coffee", "price": 4.5, "type": "food", "date": "2026-07-18T00:00:00"}
The file is only read, never modified.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import List, Tuple, Union

from .models import Kind, Transaction, dollars_to_cents

LEGACY_META_KEY = "legacy_import"


def read_legacy_file(path: Union[str, Path]) -> Tuple[List[Transaction], List[str]]:
    """Parse the old file. Returns (transactions, problems-by-line)."""
    transactions: List[Transaction] = []
    problems: List[str] = []
    with open(path, encoding="utf-8") as handle:
        for number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                raw = json.loads(line)
                transactions.append(
                    Transaction(
                        description=str(raw["name"]),
                        amount_cents=dollars_to_cents(Decimal(str(raw["price"]))),
                        category=str(raw.get("type") or "uncategorized"),
                        occurred_on=_parse_legacy_date(str(raw["date"])),
                        kind=Kind.EXPENSE,
                    )
                )
            except (ValueError, KeyError, TypeError, InvalidOperation) as exc:
                problems.append(f"line {number}: {exc}")
    return transactions, problems


def import_legacy_file(store, path: Union[str, Path]) -> Tuple[int, List[str]]:
    """Copy the old file's transactions into ``store``. Returns (count, problems)."""
    transactions, problems = read_legacy_file(path)
    imported = store.add_transactions(transactions)
    if imported or not problems:
        store.set_meta(LEGACY_META_KEY, "done")
    return imported, problems


def _parse_legacy_date(text: str) -> date:
    try:
        return datetime.fromisoformat(text).date()
    except ValueError:
        pass
    try:
        return datetime.strptime(text, "%Y/%m/%d").date()
    except ValueError:
        raise ValueError(f"unrecognized date '{text}'") from None
