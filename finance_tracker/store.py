"""SQLite persistence.

Why SQLite instead of a JSON file holding one big list:
* Nothing is loaded into memory up front. Reports like "spending per month" run
  as SQL aggregations (GROUP BY) inside the database file.
* Every change is written immediately and atomically -- no "save" step, and a
  crash can't leave a half-written file behind.
* Storage is compact: amounts are integers, each category name is stored once
  (transactions point at it by id), and an index keeps date lookups fast as the
  history grows.
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Iterable, List, Optional, Tuple, Union

from .models import AssetType, Holding, Kind, Transaction, shift_month

SCHEMA_V1 = """
CREATE TABLE profile (
    id          INTEGER PRIMARY KEY CHECK (id = 1),   -- exactly one row
    name        TEXT NOT NULL,
    created_at  TEXT NOT NULL
);

CREATE TABLE meta (
    key    TEXT PRIMARY KEY,
    value  TEXT NOT NULL
);

CREATE TABLE categories (
    id    INTEGER PRIMARY KEY,
    name  TEXT NOT NULL UNIQUE COLLATE NOCASE
);

CREATE TABLE transactions (
    id            INTEGER PRIMARY KEY,
    description   TEXT    NOT NULL,
    amount_cents  INTEGER NOT NULL CHECK (amount_cents > 0),
    kind          TEXT    NOT NULL CHECK (kind IN ('expense', 'income')),
    category_id   INTEGER NOT NULL REFERENCES categories(id),
    occurred_on   TEXT    NOT NULL                   -- YYYY-MM-DD
);
CREATE INDEX transactions_by_date ON transactions (occurred_on);

CREATE TABLE holdings (
    id                  INTEGER PRIMARY KEY,
    asset_type          TEXT NOT NULL
                        CHECK (asset_type IN ('cash', 'stock', 'crypto', 'gold', 'other')),
    name                TEXT NOT NULL,
    symbol              TEXT,
    quantity            REAL NOT NULL CHECK (quantity >= 0),
    manual_value_cents  INTEGER
);

CREATE TABLE price_cache (
    symbol      TEXT PRIMARY KEY,
    price       REAL NOT NULL,
    currency    TEXT NOT NULL,
    fetched_at  TEXT NOT NULL                        -- ISO timestamp, UTC
);

-- One row per day you checked your net worth. Feeds a line chart later.
CREATE TABLE net_worth_snapshots (
    taken_on     TEXT PRIMARY KEY,                   -- YYYY-MM-DD
    total_cents  INTEGER NOT NULL
);
"""

# Each entry upgrades the schema by one version; PRAGMA user_version records how
# far a database file has been upgraded. Never edit an entry once real data
# depends on it -- append a new one instead.
MIGRATIONS: Tuple[str, ...] = (SCHEMA_V1,)


class Store:
    def __init__(self, path: Union[str, Path]) -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self._migrate()

    def _migrate(self) -> None:
        current = self.conn.execute("PRAGMA user_version").fetchone()[0]
        if current > len(MIGRATIONS):
            raise RuntimeError(f"{self.path} was created by a newer version of this app")
        for version in range(current + 1, len(MIGRATIONS) + 1):
            script = MIGRATIONS[version - 1]
            try:
                self.conn.executescript(
                    f"BEGIN;\n{script}\nPRAGMA user_version = {version};\nCOMMIT;"
                )
            except sqlite3.Error:
                self.conn.rollback()
                raise

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "Store":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # ---------------------------------------------------------------- profile

    def profile_name(self) -> Optional[str]:
        row = self.conn.execute("SELECT name FROM profile WHERE id = 1").fetchone()
        return row["name"] if row else None

    def create_profile(self, name: str) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT INTO profile (id, name, created_at) VALUES (1, ?, ?)",
                (name.strip(), _utc_now()),
            )

    def get_meta(self, key: str) -> Optional[str]:
        row = self.conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None

    def set_meta(self, key: str, value: str) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT INTO meta (key, value) VALUES (?, ?) "
                "ON CONFLICT (key) DO UPDATE SET value = excluded.value",
                (key, value),
            )

    # ------------------------------------------------------------- categories

    def categories(self, kind: Kind = Kind.EXPENSE) -> List[str]:
        """Category names, most-used (for this kind) first.

        Categories only ever used for the other kind (e.g. 'Salary' when
        entering an expense) are left out.
        """
        rows = self.conn.execute(
            """
            SELECT c.name,
                   SUM(CASE WHEN t.kind = ? THEN 1 ELSE 0 END) AS uses,
                   COUNT(t.id) AS all_uses
            FROM categories c
            LEFT JOIN transactions t ON t.category_id = c.id
            GROUP BY c.id
            HAVING uses > 0 OR all_uses = 0
            ORDER BY uses DESC, c.name COLLATE NOCASE
            """,
            (kind.value,),
        ).fetchall()
        return [row["name"] for row in rows]

    def find_category(self, name: str) -> Optional[str]:
        """The stored spelling of a category, matched case-insensitively."""
        row = self.conn.execute(
            "SELECT name FROM categories WHERE name = ?", (_normalize(name),)
        ).fetchone()
        return row["name"] if row else None

    def _category_id(self, name: str) -> int:
        normalized = _normalize(name)
        self.conn.execute("INSERT OR IGNORE INTO categories (name) VALUES (?)", (normalized,))
        row = self.conn.execute(
            "SELECT id FROM categories WHERE name = ?", (normalized,)
        ).fetchone()
        return row["id"]

    # ----------------------------------------------------------- transactions

    def add_transaction(self, tx: Transaction) -> int:
        with self.conn:
            return self._insert_transaction(tx)

    def add_transactions(self, txs: Iterable[Transaction]) -> int:
        """Insert many at once, all-or-nothing. Returns how many were added."""
        count = 0
        with self.conn:
            for tx in txs:
                self._insert_transaction(tx)
                count += 1
        return count

    def _insert_transaction(self, tx: Transaction) -> int:
        cursor = self.conn.execute(
            """
            INSERT INTO transactions (description, amount_cents, kind, category_id, occurred_on)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                tx.description.strip(),
                tx.amount_cents,
                tx.kind.value,
                self._category_id(tx.category),
                tx.occurred_on.isoformat(),
            ),
        )
        return cursor.lastrowid

    def get_transaction(self, tx_id: int) -> Optional[Transaction]:
        row = self.conn.execute(_TX_SELECT + " WHERE t.id = ?", (tx_id,)).fetchone()
        return _row_to_transaction(row) if row else None

    def delete_transaction(self, tx_id: int) -> bool:
        with self.conn:
            cursor = self.conn.execute("DELETE FROM transactions WHERE id = ?", (tx_id,))
        return cursor.rowcount > 0

    def transactions(
        self, *, limit: Optional[int] = None, month: Optional[str] = None
    ) -> List[Transaction]:
        """Newest first. ``month`` is 'YYYY-MM'."""
        sql = _TX_SELECT
        params: list = []
        if month:
            sql += " WHERE " + _MONTH_FILTER
            params += _month_bounds(month)
        sql += " ORDER BY t.occurred_on DESC, t.id DESC"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
        return [_row_to_transaction(row) for row in self.conn.execute(sql, params)]

    def transaction_count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]

    def totals_by_category(
        self, kind: Kind = Kind.EXPENSE, *, month: Optional[str] = None
    ) -> List[Tuple[str, int]]:
        """[(category, total_cents), ...], largest first."""
        sql = """
            SELECT c.name, SUM(t.amount_cents) AS total
            FROM transactions t JOIN categories c ON c.id = t.category_id
            WHERE t.kind = ?
        """
        params: list = [kind.value]
        if month:
            sql += " AND " + _MONTH_FILTER
            params += _month_bounds(month)
        sql += " GROUP BY c.id ORDER BY total DESC, c.name COLLATE NOCASE"
        return [(row["name"], row["total"]) for row in self.conn.execute(sql, params)]

    def totals_by_month(self, kind: Kind = Kind.EXPENSE) -> List[Tuple[str, int]]:
        """[('YYYY-MM', total_cents), ...], oldest first. Empty months are absent."""
        rows = self.conn.execute(
            """
            SELECT substr(occurred_on, 1, 7) AS month, SUM(amount_cents) AS total
            FROM transactions
            WHERE kind = ?
            GROUP BY month
            ORDER BY month
            """,
            (kind.value,),
        )
        return [(row["month"], row["total"]) for row in rows]

    # --------------------------------------------------------------- holdings

    def add_holding(self, holding: Holding) -> int:
        with self.conn:
            cursor = self.conn.execute(
                """
                INSERT INTO holdings (asset_type, name, symbol, quantity, manual_value_cents)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    holding.asset_type.value,
                    holding.name.strip(),
                    holding.symbol.upper() if holding.symbol else None,
                    holding.quantity,
                    holding.manual_value_cents,
                ),
            )
        return cursor.lastrowid

    def holdings(self) -> List[Holding]:
        rows = self.conn.execute(
            "SELECT * FROM holdings ORDER BY asset_type, name COLLATE NOCASE"
        )
        return [_row_to_holding(row) for row in rows]

    def get_holding(self, holding_id: int) -> Optional[Holding]:
        row = self.conn.execute("SELECT * FROM holdings WHERE id = ?", (holding_id,)).fetchone()
        return _row_to_holding(row) if row else None

    def update_holding(
        self,
        holding_id: int,
        *,
        quantity: Optional[float] = None,
        manual_value_cents: Optional[int] = None,
    ) -> bool:
        changes = {}
        if quantity is not None:
            changes["quantity"] = quantity
        if manual_value_cents is not None:
            changes["manual_value_cents"] = manual_value_cents
        if not changes:
            return False
        assignments = ", ".join(f"{column} = ?" for column in changes)  # fixed column names
        with self.conn:
            cursor = self.conn.execute(
                f"UPDATE holdings SET {assignments} WHERE id = ?",
                (*changes.values(), holding_id),
            )
        return cursor.rowcount > 0

    def remove_holding(self, holding_id: int) -> bool:
        with self.conn:
            cursor = self.conn.execute("DELETE FROM holdings WHERE id = ?", (holding_id,))
        return cursor.rowcount > 0

    # ----------------------------------------------------------------- prices

    def cached_price(self, symbol: str) -> Optional[Tuple[float, str, datetime]]:
        row = self.conn.execute(
            "SELECT price, currency, fetched_at FROM price_cache WHERE symbol = ?",
            (symbol.upper(),),
        ).fetchone()
        if not row:
            return None
        return row["price"], row["currency"], datetime.fromisoformat(row["fetched_at"])

    def save_price(self, symbol: str, price: float, currency: str, fetched_at: datetime) -> None:
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO price_cache (symbol, price, currency, fetched_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT (symbol) DO UPDATE SET
                    price = excluded.price,
                    currency = excluded.currency,
                    fetched_at = excluded.fetched_at
                """,
                (symbol.upper(), price, currency, fetched_at.isoformat(timespec="seconds")),
            )

    # -------------------------------------------------------------- net worth

    def record_net_worth(self, day: date, total_cents: int) -> None:
        """One snapshot per day; a later check on the same day replaces it."""
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO net_worth_snapshots (taken_on, total_cents) VALUES (?, ?)
                ON CONFLICT (taken_on) DO UPDATE SET total_cents = excluded.total_cents
                """,
                (day.isoformat(), total_cents),
            )

    def latest_snapshot_before(self, day: date) -> Optional[Tuple[date, int]]:
        row = self.conn.execute(
            """
            SELECT taken_on, total_cents FROM net_worth_snapshots
            WHERE taken_on < ? ORDER BY taken_on DESC LIMIT 1
            """,
            (day.isoformat(),),
        ).fetchone()
        return (date.fromisoformat(row["taken_on"]), row["total_cents"]) if row else None

    def net_worth_history(self) -> List[Tuple[date, int]]:
        rows = self.conn.execute(
            "SELECT taken_on, total_cents FROM net_worth_snapshots ORDER BY taken_on"
        )
        return [(date.fromisoformat(row["taken_on"]), row["total_cents"]) for row in rows]


# ------------------------------------------------------------------- helpers

_TX_SELECT = """
    SELECT t.id, t.description, t.amount_cents, t.kind, t.occurred_on, c.name AS category
    FROM transactions t JOIN categories c ON c.id = t.category_id
"""

# A date range (not substr) so SQLite can use the transactions_by_date index.
_MONTH_FILTER = "t.occurred_on >= ? AND t.occurred_on < ?"


def _month_bounds(month: str) -> List[str]:
    return [f"{month}-01", f"{shift_month(month, 1)}-01"]


def _normalize(name: str) -> str:
    return " ".join(name.split())


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _row_to_transaction(row: sqlite3.Row) -> Transaction:
    return Transaction(
        id=row["id"],
        description=row["description"],
        amount_cents=row["amount_cents"],
        category=row["category"],
        occurred_on=date.fromisoformat(row["occurred_on"]),
        kind=Kind(row["kind"]),
    )


def _row_to_holding(row: sqlite3.Row) -> Holding:
    return Holding(
        id=row["id"],
        asset_type=AssetType(row["asset_type"]),
        name=row["name"],
        symbol=row["symbol"],
        quantity=row["quantity"],
        manual_value_cents=row["manual_value_cents"],
    )
