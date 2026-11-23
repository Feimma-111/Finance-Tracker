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

import json
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Iterable, List, Optional, Tuple, Union

from .models import (
    AssetType,
    Frequency,
    Holding,
    Kind,
    RecurringRule,
    Transaction,
    occurrence,
    shift_month,
)

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

# Version 2: recurring transactions (rent, subscriptions, paychecks).
SCHEMA_V2 = """
CREATE TABLE recurring (
    id               INTEGER PRIMARY KEY,
    description      TEXT    NOT NULL,
    amount_cents     INTEGER NOT NULL CHECK (amount_cents > 0),
    kind             TEXT    NOT NULL CHECK (kind IN ('expense', 'income')),
    category_id      INTEGER NOT NULL REFERENCES categories(id),
    frequency        TEXT    NOT NULL
                     CHECK (frequency IN ('weekly', 'biweekly', 'monthly', 'yearly')),
    start_on         TEXT    NOT NULL,           -- YYYY-MM-DD, the first occurrence
    generated_count  INTEGER NOT NULL DEFAULT 0, -- occurrences already turned into transactions
    next_due         TEXT    NOT NULL,           -- cached so "anything due?" is one indexed lookup
    active           INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX recurring_due ON recurring (active, next_due);

-- Which rule (if any) created a transaction. Deleting a rule keeps its past
-- transactions; they just stop pointing at it.
ALTER TABLE transactions ADD COLUMN recurring_id INTEGER
    REFERENCES recurring(id) ON DELETE SET NULL;
"""

# Each entry upgrades the schema by one version; PRAGMA user_version records how
# far a database file has been upgraded. Never edit an entry once real data
# depends on it -- append a new one instead.
# Version 3: saved AI reviews, so they stay readable when the PC is off.
SCHEMA_V3 = """
CREATE TABLE ai_reviews (
    id          INTEGER PRIMARY KEY,
    month       TEXT NOT NULL,          -- YYYY-MM the review is about
    created_at  TEXT NOT NULL,          -- ISO timestamp, UTC
    model       TEXT NOT NULL,
    review      TEXT NOT NULL,          -- JSON: headline, observations, suggestions
    facts       TEXT NOT NULL           -- exactly what the model was shown
);
CREATE INDEX ai_reviews_by_month ON ai_reviews (month, created_at);
"""

MIGRATIONS: Tuple[str, ...] = (SCHEMA_V1, SCHEMA_V2, SCHEMA_V3)

# Safety valve: never create more than this many transactions in one catch-up.
MAX_CATCH_UP = 1000


class Store:
    def __init__(self, path: Union[str, Path], *, check_same_thread: bool = True) -> None:
        """Open (and if needed create/upgrade) the database at ``path``.

        The web API opens one Store per request; its framework may create the
        connection on one worker thread and use it on another, so it passes
        ``check_same_thread=False``. That's safe because a request's Store is
        only ever used by that one request, one step at a time.
        """
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path, check_same_thread=check_same_thread)
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

    def rename_profile(self, name: str) -> None:
        with self.conn:
            self.conn.execute("UPDATE profile SET name = ? WHERE id = 1", (name.strip(),))

    def get_setting(self, name: str, default: str) -> str:
        return self.get_meta(f"setting:{name}") or default

    def set_setting(self, name: str, value: str) -> None:
        self.set_meta(f"setting:{name}", value)

    def covered_categories(self) -> Tuple[List[str], str]:
        """(category names, note) for expenses someone else pays for, e.g. rent
        covered by parents. Names that no longer exist are dropped."""
        try:
            names = json.loads(self.get_setting("covered_categories", "[]"))
        except ValueError:
            names = []
        existing = [self.find_category(n) for n in names if isinstance(n, str)]
        note = self.get_setting("covered_note", "") or "Paid by someone else"
        return [n for n in existing if n], note

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
            self._mark_facts_changed()
            return self._insert_transaction(tx)

    def add_transactions(self, txs: Iterable[Transaction]) -> int:
        """Insert many at once, all-or-nothing. Returns how many were added."""
        count = 0
        with self.conn:
            for tx in txs:
                self._insert_transaction(tx)
                count += 1
            if count:
                self._mark_facts_changed()
        return count

    def update_transaction(self, tx_id: int, tx: Transaction) -> bool:
        """Replace a transaction's fields (its link to a recurring rule is kept)."""
        with self.conn:
            cursor = self.conn.execute(
                """
                UPDATE transactions
                SET description = ?, amount_cents = ?, kind = ?, category_id = ?, occurred_on = ?
                WHERE id = ?
                """,
                (tx.description.strip(), tx.amount_cents, tx.kind.value,
                 self._category_id(tx.category), tx.occurred_on.isoformat(), tx_id),
            )
            if cursor.rowcount:
                self._mark_facts_changed()
        return cursor.rowcount > 0

    def count_matching(self, description: str, kind: Kind, *, exclude_id: int) -> int:
        """Other transactions with the same description (ignoring case) and type."""
        return self.conn.execute(
            "SELECT COUNT(*) FROM transactions WHERE lower(trim(description)) = lower(trim(?)) "
            "AND kind = ? AND id != ?",
            (description, kind.value, exclude_id),
        ).fetchone()[0]

    def set_category_for_matching(self, description: str, kind: Kind, category: str) -> int:
        """Give every transaction with this description and type the same category."""
        with self.conn:
            cursor = self.conn.execute(
                "UPDATE transactions SET category_id = ? "
                "WHERE lower(trim(description)) = lower(trim(?)) AND kind = ?",
                (self._category_id(category), description, kind.value),
            )
            if cursor.rowcount:
                self._mark_facts_changed()
        return cursor.rowcount

    # When anything an AI review depends on changes (transactions or covered
    # categories), this timestamp moves, so saved reviews can say they're out of date.
    def _mark_facts_changed(self) -> None:
        self.conn.execute(
            "INSERT INTO meta (key, value) VALUES ('facts_changed_at', ?) "
            "ON CONFLICT (key) DO UPDATE SET value = excluded.value",
            (_utc_now_precise(),),
        )

    def mark_facts_changed(self) -> None:
        with self.conn:
            self._mark_facts_changed()

    def facts_changed_at(self) -> Optional[datetime]:
        value = self.get_meta("facts_changed_at")
        return datetime.fromisoformat(value) if value else None

    def _insert_transaction(self, tx: Transaction) -> int:
        cursor = self.conn.execute(
            """
            INSERT INTO transactions
                (description, amount_cents, kind, category_id, occurred_on, recurring_id)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                tx.description.strip(),
                tx.amount_cents,
                tx.kind.value,
                self._category_id(tx.category),
                tx.occurred_on.isoformat(),
                tx.recurring_id,
            ),
        )
        return cursor.lastrowid

    def get_transaction(self, tx_id: int) -> Optional[Transaction]:
        row = self.conn.execute(_TX_SELECT + " WHERE t.id = ?", (tx_id,)).fetchone()
        return _row_to_transaction(row) if row else None

    def delete_transaction(self, tx_id: int) -> bool:
        with self.conn:
            cursor = self.conn.execute("DELETE FROM transactions WHERE id = ?", (tx_id,))
            if cursor.rowcount:
                self._mark_facts_changed()
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

    # ---------------------------------------------- date-range queries (AI tools)

    def first_transaction_date(self) -> Optional[date]:
        row = self.conn.execute("SELECT MIN(occurred_on) FROM transactions").fetchone()
        return date.fromisoformat(row[0]) if row and row[0] else None

    def total_between(
        self, kind: Kind, start: date, end: date, *, category: Optional[str] = None
    ) -> Tuple[int, int]:
        """(total_cents, transaction_count) from ``start`` to ``end`` inclusive."""
        sql = """
            SELECT COALESCE(SUM(t.amount_cents), 0), COUNT(*)
            FROM transactions t JOIN categories c ON c.id = t.category_id
            WHERE t.kind = ? AND t.occurred_on BETWEEN ? AND ?
        """
        params: list = [kind.value, start.isoformat(), end.isoformat()]
        if category:
            sql += " AND c.name = ?"  # the column is COLLATE NOCASE
            params.append(" ".join(category.split()))
        total, count = self.conn.execute(sql, params).fetchone()
        return total, count

    def category_totals_between(self, kind: Kind, start: date, end: date) -> List[Tuple[str, int]]:
        rows = self.conn.execute(
            """
            SELECT c.name, SUM(t.amount_cents) AS total
            FROM transactions t JOIN categories c ON c.id = t.category_id
            WHERE t.kind = ? AND t.occurred_on BETWEEN ? AND ?
            GROUP BY c.id ORDER BY total DESC, c.name COLLATE NOCASE
            """,
            (kind.value, start.isoformat(), end.isoformat()),
        )
        return [(row["name"], row["total"]) for row in rows]

    def search_transactions(
        self,
        *,
        text: Optional[str] = None,
        category: Optional[str] = None,
        kind: Optional[Kind] = None,
        start: Optional[date] = None,
        end: Optional[date] = None,
        order: str = "newest",
        limit: int = 20,
    ) -> List[Transaction]:
        """Filtered transactions. ``order`` is 'newest' or 'largest'."""
        clauses, params = [], []
        if text:
            clauses.append("t.description LIKE ? ESCAPE '\\'")
            escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            params.append(f"%{escaped}%")
        if category:
            clauses.append("c.name = ?")
            params.append(" ".join(category.split()))
        if kind:
            clauses.append("t.kind = ?")
            params.append(kind.value)
        if start:
            clauses.append("t.occurred_on >= ?")
            params.append(start.isoformat())
        if end:
            clauses.append("t.occurred_on <= ?")
            params.append(end.isoformat())
        sql = _TX_SELECT + (" WHERE " + " AND ".join(clauses) if clauses else "")
        sql += " ORDER BY t.amount_cents DESC, t.occurred_on DESC" if order == "largest" else \
               " ORDER BY t.occurred_on DESC, t.id DESC"
        sql += " LIMIT ?"
        params.append(limit)
        return [_row_to_transaction(row) for row in self.conn.execute(sql, params)]

    # -------------------------------------------------------------- recurring

    def add_recurring(self, rule: RecurringRule) -> int:
        with self.conn:
            cursor = self.conn.execute(
                """
                INSERT INTO recurring (description, amount_cents, kind, category_id,
                                       frequency, start_on, generated_count, next_due, active)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    rule.description.strip(),
                    rule.amount_cents,
                    rule.kind.value,
                    self._category_id(rule.category),
                    rule.frequency.value,
                    rule.start_on.isoformat(),
                    rule.generated_count,
                    rule.next_due.isoformat(),
                    int(rule.active),
                ),
            )
        return cursor.lastrowid

    def recurring_rules(self) -> List[RecurringRule]:
        rows = self.conn.execute(
            _RULE_SELECT + " ORDER BY r.active DESC, r.next_due, r.description COLLATE NOCASE"
        )
        return [_row_to_rule(row) for row in rows]

    def get_recurring(self, rule_id: int) -> Optional[RecurringRule]:
        row = self.conn.execute(_RULE_SELECT + " WHERE r.id = ?", (rule_id,)).fetchone()
        return _row_to_rule(row) if row else None

    def update_recurring(
        self,
        rule_id: int,
        *,
        today: date,
        active: Optional[bool] = None,
        amount_cents: Optional[int] = None,
    ) -> bool:
        """Pause/resume a rule or change its amount (rent went up).

        Resuming skips the occurrences that fell while it was paused --
        otherwise un-pausing three months later would backfill three rents.
        A new amount applies to future occurrences only.
        """
        rule = self.get_recurring(rule_id)
        if rule is None:
            return False
        count = rule.generated_count
        if active and not rule.active:
            while rule.occurrence(count) < today:
                count += 1
        with self.conn:
            self.conn.execute(
                """
                UPDATE recurring
                SET active = ?, amount_cents = ?, generated_count = ?, next_due = ?
                WHERE id = ?
                """,
                (
                    int(rule.active if active is None else active),
                    rule.amount_cents if amount_cents is None else amount_cents,
                    count,
                    rule.occurrence(count).isoformat(),
                    rule_id,
                ),
            )
        return True

    def delete_recurring(self, rule_id: int) -> bool:
        """Stop a rule. Transactions it already created are kept."""
        with self.conn:
            cursor = self.conn.execute("DELETE FROM recurring WHERE id = ?", (rule_id,))
        return cursor.rowcount > 0

    def apply_recurring(self, today: date) -> int:
        """Turn every occurrence due on or before ``today`` into a real transaction.

        Safe to call as often as you like: each occurrence is created exactly
        once, because ``generated_count`` moves forward in the same database
        transaction that inserts it. Returns how many were created.
        """
        today_iso = today.isoformat()
        # Cheap check first (uses the recurring_due index), so most calls do no writing.
        if not self.conn.execute(
            "SELECT 1 FROM recurring WHERE active = 1 AND next_due <= ? LIMIT 1", (today_iso,)
        ).fetchone():
            return 0

        created = 0
        with self.conn:
            # IMMEDIATE takes the write lock *before* reading, so two requests
            # arriving at once can't both see the same rule as due and double-post.
            self.conn.execute("BEGIN IMMEDIATE")
            rows = self.conn.execute(
                "SELECT * FROM recurring WHERE active = 1 AND next_due <= ?", (today_iso,)
            ).fetchall()
            for row in rows:
                frequency = Frequency(row["frequency"])
                start = date.fromisoformat(row["start_on"])
                count = row["generated_count"]
                due = occurrence(start, frequency, count)
                while due <= today and created < MAX_CATCH_UP:
                    self.conn.execute(
                        """
                        INSERT INTO transactions
                            (description, amount_cents, kind, category_id, occurred_on, recurring_id)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (row["description"], row["amount_cents"], row["kind"],
                         row["category_id"], due.isoformat(), row["id"]),
                    )
                    count += 1
                    created += 1
                    due = occurrence(start, frequency, count)
                self.conn.execute(
                    "UPDATE recurring SET generated_count = ?, next_due = ? WHERE id = ?",
                    (count, due.isoformat(), row["id"]),
                )
            if created:
                self._mark_facts_changed()
        return created

    # ------------------------------------------------------------- AI reviews

    def save_review(self, month: str, model: str, review: dict, facts: str) -> dict:
        created_at = _utc_now_precise()
        with self.conn:
            self.conn.execute(
                "INSERT INTO ai_reviews (month, created_at, model, review, facts) VALUES (?, ?, ?, ?, ?)",
                (month, created_at, model, json.dumps(review), facts),
            )
        return {"month": month, "created_at": created_at, "model": model, "review": review, "facts": facts}

    def latest_review(self, month: str) -> Optional[dict]:
        row = self.conn.execute(
            "SELECT * FROM ai_reviews WHERE month = ? ORDER BY created_at DESC, id DESC LIMIT 1",
            (month,),
        ).fetchone()
        if not row:
            return None
        return {
            "month": row["month"],
            "created_at": row["created_at"],
            "model": row["model"],
            "review": json.loads(row["review"]),
            "facts": row["facts"],
        }

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
        name: Optional[str] = None,
        symbol: Optional[str] = None,
    ) -> bool:
        changes: dict = {}
        if quantity is not None:
            changes["quantity"] = quantity
        if manual_value_cents is not None:
            changes["manual_value_cents"] = manual_value_cents
        if name is not None:
            changes["name"] = name.strip()
        if symbol is not None:
            changes["symbol"] = symbol.strip().upper()
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
    SELECT t.id, t.description, t.amount_cents, t.kind, t.occurred_on, t.recurring_id,
           c.name AS category
    FROM transactions t JOIN categories c ON c.id = t.category_id
"""

_RULE_SELECT = """
    SELECT r.*, c.name AS category
    FROM recurring r JOIN categories c ON c.id = r.category_id
"""

# A date range (not substr) so SQLite can use the transactions_by_date index.
_MONTH_FILTER = "t.occurred_on >= ? AND t.occurred_on < ?"


def _month_bounds(month: str) -> List[str]:
    return [f"{month}-01", f"{shift_month(month, 1)}-01"]


def _normalize(name: str) -> str:
    return " ".join(name.split())


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _utc_now_precise() -> str:
    # Microseconds, so "changed after this review" holds even within one second.
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _row_to_transaction(row: sqlite3.Row) -> Transaction:
    return Transaction(
        id=row["id"],
        description=row["description"],
        amount_cents=row["amount_cents"],
        category=row["category"],
        occurred_on=date.fromisoformat(row["occurred_on"]),
        kind=Kind(row["kind"]),
        recurring_id=row["recurring_id"],
    )


def _row_to_rule(row: sqlite3.Row) -> RecurringRule:
    return RecurringRule(
        id=row["id"],
        description=row["description"],
        amount_cents=row["amount_cents"],
        category=row["category"],
        frequency=Frequency(row["frequency"]),
        start_on=date.fromisoformat(row["start_on"]),
        kind=Kind(row["kind"]),
        generated_count=row["generated_count"],
        active=bool(row["active"]),
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
