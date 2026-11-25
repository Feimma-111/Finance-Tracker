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
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple, Union

from .models import (
    HOME_CURRENCY,
    AssetType,
    Frequency,
    Holding,
    Kind,
    RecurringRule,
    SavingsGoal,
    Transaction,
    Transfer,
    fx_symbol,
    occurrence,
    shift_month,
    to_home_cents,
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

# Version 4: signed-in devices for the passcode lock. Only a SHA-256 of each
# session token is stored, never the token itself.
SCHEMA_V4 = """
CREATE TABLE sessions (
    token_hash  TEXT PRIMARY KEY,
    created_at  TEXT NOT NULL,
    last_seen   TEXT NOT NULL,
    user_agent  TEXT
);
"""

# Version 5: what investments cost (for gain/loss), cash accounts that follow
# the transactions linked to them, and daily closing prices for charts.
SCHEMA_V5 = """
ALTER TABLE holdings ADD COLUMN bought_on TEXT;            -- YYYY-MM-DD, first bought
ALTER TABLE holdings ADD COLUMN cost_basis_cents INTEGER;  -- total paid for the quantity held
ALTER TABLE holdings ADD COLUMN balance_as_of TEXT;        -- cash: day the balance was checked
ALTER TABLE holdings ADD COLUMN balance_mark INTEGER;      -- cash: newest transaction id at that moment
ALTER TABLE transactions ADD COLUMN account_id INTEGER
    REFERENCES holdings(id) ON DELETE SET NULL;
ALTER TABLE recurring ADD COLUMN account_id INTEGER
    REFERENCES holdings(id) ON DELETE SET NULL;
CREATE INDEX transactions_by_account ON transactions (account_id, occurred_on);

CREATE TABLE price_history (
    symbol  TEXT NOT NULL,
    day     TEXT NOT NULL,             -- YYYY-MM-DD (exchange's local date)
    close   REAL NOT NULL,
    PRIMARY KEY (symbol, day)
) WITHOUT ROWID;
CREATE TABLE price_history_fetched (
    symbol      TEXT PRIMARY KEY,
    currency    TEXT NOT NULL,
    fetched_at  TEXT NOT NULL          -- ISO timestamp, UTC
);
"""

# Version 6: money in more than one currency, and transfers between your own
# accounts. A transaction's amount_cents stays in USD (so every report still
# adds up one currency); original_cents is what was paid, in ``currency``.
SCHEMA_V6 = """
ALTER TABLE holdings ADD COLUMN currency TEXT NOT NULL DEFAULT 'USD';  -- cash accounts
ALTER TABLE holdings ADD COLUMN balance_set_at TEXT;                    -- UTC time the balance was entered
ALTER TABLE transactions ADD COLUMN currency TEXT NOT NULL DEFAULT 'USD';
ALTER TABLE transactions ADD COLUMN original_cents INTEGER;            -- in currency; NULL when USD
ALTER TABLE recurring ADD COLUMN currency TEXT NOT NULL DEFAULT 'USD';  -- amount_cents is in this

CREATE TABLE transfers (
    id               INTEGER PRIMARY KEY,
    occurred_on      TEXT NOT NULL,
    from_account_id  INTEGER REFERENCES holdings(id) ON DELETE SET NULL,
    to_account_id    INTEGER REFERENCES holdings(id) ON DELETE SET NULL,
    from_cents       INTEGER NOT NULL CHECK (from_cents > 0),   -- in the from account's currency
    to_cents         INTEGER NOT NULL CHECK (to_cents > 0),     -- in the to account's currency
    note             TEXT NOT NULL DEFAULT '',
    created_at       TEXT NOT NULL                              -- UTC
);
CREATE INDEX transfers_by_date ON transfers (occurred_on);
"""

# Version 7: a monthly spending cap per category, in the currency it was set in.
SCHEMA_V7 = """
CREATE TABLE category_caps (
    category_id  INTEGER PRIMARY KEY REFERENCES categories(id) ON DELETE CASCADE,
    cap_cents    INTEGER NOT NULL CHECK (cap_cents > 0),
    currency     TEXT NOT NULL DEFAULT 'USD'
);
"""

# Version 8: savings goals.
SCHEMA_V8 = """
CREATE TABLE savings_goals (
    id            INTEGER PRIMARY KEY,
    name          TEXT NOT NULL,
    target_cents  INTEGER NOT NULL CHECK (target_cents > 0),
    currency      TEXT NOT NULL DEFAULT 'USD',
    target_date   TEXT,                                         -- YYYY-MM-DD, optional
    account_id    INTEGER REFERENCES holdings(id) ON DELETE SET NULL,  -- progress = its balance
    saved_cents   INTEGER NOT NULL DEFAULT 0 CHECK (saved_cents >= 0),  -- progress otherwise
    created_at    TEXT NOT NULL
);
"""

MIGRATIONS: Tuple[str, ...] = (SCHEMA_V1, SCHEMA_V2, SCHEMA_V3, SCHEMA_V4, SCHEMA_V5, SCHEMA_V6, SCHEMA_V7, SCHEMA_V8)

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
        if 0 < current < len(MIGRATIONS):
            # Upgrading real data: keep a copy of it exactly as it was first.
            from .backup import make_backup
            make_backup(self.path, label=f"before-upgrade-v{current}")
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

    def suggest_category(self, description: str, kind: Kind = Kind.EXPENSE) -> Optional[Dict[str, Any]]:
        """The category you've used before for this description.

        First, past transactions with the same description (ignoring case and
        spaces) -- their most common category. Failing that, ones whose
        description shares a word with it ("Boba Guys" finds "Boba"). Returns
        {category, count, match: "same" | "similar"}, or None.
        """
        text = " ".join(description.lower().split())
        if len(text) < 2:
            return None
        same = self.conn.execute(
            """
            SELECT c.name, COUNT(*) AS uses FROM transactions t JOIN categories c ON c.id = t.category_id
            WHERE lower(trim(t.description)) = ? AND t.kind = ?
            GROUP BY c.id ORDER BY uses DESC, MAX(t.occurred_on) DESC LIMIT 1
            """,
            (text, kind.value),
        ).fetchone()
        if same:
            return {"category": same["name"], "count": same["uses"], "match": "same"}
        # Whole words of 3+ letters, longest first; LIKE's wildcards are escaped.
        words = sorted({w for w in text.replace("'", " ").split() if len(w) >= 3 and w.isalnum()}, key=len, reverse=True)
        for word in words[:3]:
            pattern = "%" + word.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            rows = self.conn.execute(
                """
                SELECT c.name, t.description FROM transactions t JOIN categories c ON c.id = t.category_id
                WHERE t.kind = ? AND lower(t.description) LIKE ? ESCAPE '\\'
                ORDER BY t.occurred_on DESC LIMIT 200
                """,
                (kind.value, pattern),
            ).fetchall()
            counts: Dict[str, int] = {}
            for row in rows:  # LIKE matches inside words too; keep whole-word matches only
                if word in row["description"].lower().replace("'", " ").split():
                    counts[row["name"]] = counts.get(row["name"], 0) + 1
            if counts:
                name = max(counts, key=lambda n: counts[n])
                return {"category": name, "count": counts[name], "match": "similar"}
        return None

    def caps(self) -> List[Tuple[str, int, str]]:
        """[(category, cap_cents, currency)] -- monthly spending caps, by name."""
        rows = self.conn.execute(
            """
            SELECT c.name, k.cap_cents, k.currency
            FROM category_caps k JOIN categories c ON c.id = k.category_id
            ORDER BY c.name COLLATE NOCASE
            """
        )
        return [(row["name"], row["cap_cents"], row["currency"]) for row in rows]

    def set_cap(self, category: str, cap_cents: Optional[int], currency: str = HOME_CURRENCY) -> None:
        """Give an existing category a monthly cap, or remove it (None)."""
        name = self.find_category(category)
        if name is None:
            raise ValueError(f"no category called {category!r}")
        with self.conn:
            category_id = self._category_id(name)
            if cap_cents is None:
                self.conn.execute("DELETE FROM category_caps WHERE category_id = ?", (category_id,))
            else:
                if cap_cents <= 0:
                    raise ValueError("a cap must be more than zero")
                self.conn.execute(
                    "INSERT INTO category_caps (category_id, cap_cents, currency) VALUES (?, ?, ?) "
                    "ON CONFLICT (category_id) DO UPDATE SET cap_cents = excluded.cap_cents, "
                    "currency = excluded.currency",
                    (category_id, cap_cents, currency),
                )
            self._mark_facts_changed()  # reviews mention caps

    def covered_categories(self) -> Tuple[List[str], str]:
        """(category names, note) for expenses someone else pays for, e.g. rent
        a family member covers. Names that no longer exist are dropped."""
        try:
            names = json.loads(self.get_setting("covered_categories", "[]"))
        except ValueError:
            names = []
        existing = [self.find_category(n) for n in names if isinstance(n, str)]
        note = self.get_setting("covered_note", "") or "Paid by someone else"
        return [n for n in existing if n], note

    # ------------------------------------------------------------- passcode

    def passcode_hash(self) -> Optional[str]:
        return self.get_meta("passcode_hash")

    def set_passcode_hash(self, value: str) -> None:
        self.set_meta("passcode_hash", value)

    def clear_passcode(self) -> None:
        """Forget the passcode and sign out every device (for a forgotten passcode)."""
        with self.conn:
            self.conn.execute("DELETE FROM meta WHERE key IN ('passcode_hash', 'auth_failures', 'auth_locked_until')")
            self.conn.execute("DELETE FROM sessions")

    def auth_failures(self) -> Tuple[int, Optional[datetime]]:
        """(wrong guesses in a row, locked until)."""
        locked = self.get_meta("auth_locked_until")
        return int(self.get_meta("auth_failures") or 0), datetime.fromisoformat(locked) if locked else None

    def set_auth_failures(self, count: int, locked_until: Optional[datetime]) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM meta WHERE key IN ('auth_failures', 'auth_locked_until')")
            if count:
                self.conn.execute("INSERT INTO meta (key, value) VALUES ('auth_failures', ?)", (str(count),))
            if locked_until:
                self.conn.execute("INSERT INTO meta (key, value) VALUES ('auth_locked_until', ?)",
                                  (locked_until.isoformat(),))

    def add_session(self, token_hash: str, user_agent: str) -> None:
        now = _utc_now()
        with self.conn:
            self.conn.execute(
                "INSERT INTO sessions (token_hash, created_at, last_seen, user_agent) VALUES (?, ?, ?, ?)",
                (token_hash, now, now, user_agent[:200]),
            )

    def check_session(self, token_hash: str, *, max_idle_days: int) -> bool:
        """True if the session exists and was used recently; refreshes its last-seen time."""
        row = self.conn.execute("SELECT last_seen FROM sessions WHERE token_hash = ?", (token_hash,)).fetchone()
        if not row:
            return False
        now = datetime.now(timezone.utc)
        last_seen = datetime.fromisoformat(row["last_seen"])
        if (now - last_seen).days >= max_idle_days:
            self.delete_session(token_hash)
            return False
        if (now - last_seen).total_seconds() > 60:  # don't write on every single request
            with self.conn:
                self.conn.execute("UPDATE sessions SET last_seen = ? WHERE token_hash = ?", (_utc_now(), token_hash))
        return True

    def delete_session(self, token_hash: str) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))

    def delete_other_sessions(self, keep_token_hash: str) -> int:
        with self.conn:
            cursor = self.conn.execute("DELETE FROM sessions WHERE token_hash != ?", (keep_token_hash,))
        return cursor.rowcount

    def session_count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]

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
                SET description = ?, amount_cents = ?, kind = ?, category_id = ?, occurred_on = ?,
                    account_id = ?, currency = ?, original_cents = ?
                WHERE id = ?
                """,
                (tx.description.strip(), tx.amount_cents, tx.kind.value,
                 self._category_id(tx.category), tx.occurred_on.isoformat(), tx.account_id,
                 tx.currency, tx.original_cents, tx_id),
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
                (description, amount_cents, kind, category_id, occurred_on, recurring_id, account_id,
                 currency, original_cents)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                tx.description.strip(),
                tx.amount_cents,
                tx.kind.value,
                self._category_id(tx.category),
                tx.occurred_on.isoformat(),
                tx.recurring_id,
                tx.account_id,
                tx.currency,
                tx.original_cents,
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

    def daily_totals(
        self,
        kind: Kind,
        start: date,
        end: date,
        *,
        exclude_categories: Sequence[str] = (),
        only_categories: Optional[Sequence[str]] = None,
    ) -> Dict[date, int]:
        """{day: total_cents} for days with transactions between start and end,
        optionally leaving some categories out or keeping only some."""
        sql = """
            SELECT t.occurred_on AS day, SUM(t.amount_cents) AS total
            FROM transactions t JOIN categories c ON c.id = t.category_id
            WHERE t.kind = ? AND t.occurred_on BETWEEN ? AND ?
        """
        params: list = [kind.value, start.isoformat(), end.isoformat()]
        if exclude_categories:
            sql += f" AND c.name NOT IN ({', '.join('?' * len(exclude_categories))})"
            params += list(exclude_categories)
        if only_categories is not None:
            if not only_categories:
                return {}
            sql += f" AND c.name IN ({', '.join('?' * len(only_categories))})"
            params += list(only_categories)
        sql += " GROUP BY t.occurred_on"
        return {date.fromisoformat(row["day"]): row["total"] for row in self.conn.execute(sql, params)}

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
                INSERT INTO recurring (description, amount_cents, kind, category_id, frequency,
                                       start_on, generated_count, next_due, active, account_id, currency)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    rule.account_id,
                    rule.currency,
                ),
            )
        return cursor.lastrowid

    def make_recurring(
        self, tx_id: int, frequency: Frequency, *, today: date, fill_missing: bool, match_days: int = 3
    ) -> Optional[Dict[str, int]]:
        """Turn an existing transaction into the first occurrence of a recurring rule.

        Later occurrences up to today are matched against transactions you
        already have -- same description and type, dated within ``match_days``
        of the expected date (banks post a day or two late) -- and *linked*
        rather than duplicated. Occurrences with no match are filled in only
        if ``fill_missing``; otherwise the rule just continues from the next
        date after today. Returns {rule_id, linked, created}, or None if the
        transaction doesn't exist. Raises ValueError if it's already recurring.
        """
        tx = self.get_transaction(tx_id)
        if tx is None:
            return None
        if tx.recurring_id is not None:
            raise ValueError("this transaction is already part of a recurring rule")

        # The rule repeats what was actually paid, in the currency it was paid in.
        rule = RecurringRule(tx.description, tx.paid_cents, tx.category, frequency, tx.occurred_on, tx.kind,
                             account_id=tx.account_id, currency=tx.currency)
        linked = created = 0
        with self.conn:
            category_id = self._category_id(tx.category)
            cursor = self.conn.execute(
                """
                INSERT INTO recurring (description, amount_cents, kind, category_id, frequency,
                                       start_on, generated_count, next_due, active, account_id, currency)
                VALUES (?, ?, ?, ?, ?, ?, 1, ?, 1, ?, ?)
                """,
                (tx.description, tx.paid_cents, tx.kind.value, category_id, frequency.value,
                 tx.occurred_on.isoformat(), rule.occurrence(1).isoformat(), tx.account_id, tx.currency),
            )
            rule_id = cursor.lastrowid
            self.conn.execute("UPDATE transactions SET recurring_id = ? WHERE id = ?", (rule_id, tx_id))

            n = 1
            while rule.occurrence(n) <= today:
                due = rule.occurrence(n)
                match = self.conn.execute(
                    """
                    SELECT id FROM transactions
                    WHERE lower(trim(description)) = lower(trim(?)) AND kind = ? AND recurring_id IS NULL
                      AND occurred_on BETWEEN ? AND ?
                    ORDER BY abs(julianday(occurred_on) - julianday(?)) LIMIT 1
                    """,
                    (tx.description, tx.kind.value, (due - timedelta(days=match_days)).isoformat(),
                     (due + timedelta(days=match_days)).isoformat(), due.isoformat()),
                ).fetchone()
                if match:
                    self.conn.execute("UPDATE transactions SET recurring_id = ? WHERE id = ?", (rule_id, match["id"]))
                    linked += 1
                elif fill_missing:
                    home = self._home_cents(tx.paid_cents, tx.currency, due)
                    if home is None:  # no exchange rate saved for that day; leave it out
                        n += 1
                        continue
                    self.conn.execute(
                        """
                        INSERT INTO transactions
                            (description, amount_cents, kind, category_id, occurred_on, recurring_id, account_id,
                             currency, original_cents)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (tx.description, home, tx.kind.value, category_id, due.isoformat(), rule_id,
                         tx.account_id, tx.currency, tx.original_cents),
                    )
                    created += 1
                n += 1
            self.conn.execute(
                "UPDATE recurring SET generated_count = ?, next_due = ? WHERE id = ?",
                (n, rule.occurrence(n).isoformat(), rule_id),
            )
            self._mark_facts_changed()
        return {"rule_id": rule_id, "linked": linked, "created": created}

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
                    # Another currency: its USD value on that day. With no saved
                    # rate yet, the occurrence waits until one is (see api.py).
                    home = self._home_cents(row["amount_cents"], row["currency"], due)
                    if home is None:
                        break
                    original = None if row["currency"] == HOME_CURRENCY else row["amount_cents"]
                    self.conn.execute(
                        """
                        INSERT INTO transactions
                            (description, amount_cents, kind, category_id, occurred_on, recurring_id, account_id,
                             currency, original_cents)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (row["description"], home, row["kind"], row["category_id"], due.isoformat(), row["id"],
                         row["account_id"], row["currency"], original),
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
                INSERT INTO holdings (asset_type, name, symbol, quantity, manual_value_cents,
                                      bought_on, cost_basis_cents, balance_as_of, currency,
                                      balance_mark, balance_set_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, (SELECT COALESCE(MAX(id), 0) FROM transactions), ?)
                """,
                (
                    holding.asset_type.value,
                    holding.name.strip(),
                    holding.symbol.upper() if holding.symbol else None,
                    holding.quantity,
                    holding.manual_value_cents,
                    holding.bought_on.isoformat() if holding.bought_on else None,
                    holding.cost_basis_cents,
                    holding.balance_as_of.isoformat() if holding.balance_as_of else None,
                    holding.currency,
                    _utc_now_precise(),
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
        bought_on: Optional[date] = None,
        cost_basis_cents: Optional[int] = None,
        balance_as_of: Optional[date] = None,
        clear: Sequence[str] = (),
    ) -> bool:
        """Change the fields given; ``clear`` names fields to empty
        ("bought_on", "cost_basis_cents")."""
        changes: dict = {}
        if quantity is not None:
            changes["quantity"] = quantity
        if manual_value_cents is not None:
            changes["manual_value_cents"] = manual_value_cents
        if name is not None:
            changes["name"] = name.strip()
        if symbol is not None:
            changes["symbol"] = symbol.strip().upper()
        if bought_on is not None:
            changes["bought_on"] = bought_on.isoformat()
        if cost_basis_cents is not None:
            changes["cost_basis_cents"] = cost_basis_cents
        if balance_as_of is not None:
            changes["balance_as_of"] = balance_as_of.isoformat()
            changes["balance_mark"] = self.conn.execute(
                "SELECT COALESCE(MAX(id), 0) FROM transactions").fetchone()[0]
            changes["balance_set_at"] = _utc_now_precise()
        for column in clear:
            if column not in ("bought_on", "cost_basis_cents"):
                raise ValueError(f"can't clear {column}")
            changes[column] = None
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

    # ---------------------------------------------------------- cash accounts

    def account_changes(self, today: date) -> Dict[int, int]:
        """{cash holding id: cents} -- how much each cash account has moved
        since its balance was checked: income linked to it adds, expenses
        subtract. A transaction counts if it's dated after the day the balance
        was checked, or that same day but added afterwards (lunch logged after
        updating the balance this morning). Back-dated entries are assumed to
        be in the bank's balance already; future-dated ones wait for their day.
        """
        # In the account's own currency: what was actually paid. Transfers
        # follow the same rule, using the time they were entered.
        rows = self.conn.execute(
            """
            SELECT h.id, SUM(change) AS change FROM holdings h JOIN (
                SELECT t.account_id AS account, t.occurred_on AS day,
                       CASE t.kind WHEN 'income' THEN 1 ELSE -1 END
                           * COALESCE(t.original_cents, t.amount_cents) AS change,
                       t.id AS seq, NULL AS entered
                FROM transactions t
                UNION ALL
                SELECT from_account_id, occurred_on, -from_cents, NULL, created_at FROM transfers
                UNION ALL
                SELECT to_account_id, occurred_on, to_cents, NULL, created_at FROM transfers
            ) m ON m.account = h.id
            WHERE h.asset_type = 'cash' AND h.balance_as_of IS NOT NULL
              AND (m.day > h.balance_as_of
                   OR (m.day = h.balance_as_of AND (
                       m.seq > COALESCE(h.balance_mark, 0)
                       OR m.entered > COALESCE(h.balance_set_at, ''))))
              AND m.day <= ?
            GROUP BY h.id
            """,
            (today.isoformat(),),
        )
        return {row["id"]: row["change"] for row in rows}

    def account_activity(self, holding_id: int, limit: int = 60) -> List[Dict[str, Any]]:
        """What moved a cash account, newest first: its linked transactions and
        transfers, in the account's currency. ``counted`` says whether an item
        is in the balance shown (it came after the balance was last entered)
        rather than already part of the number you typed."""
        h = self.conn.execute(
            "SELECT balance_as_of, balance_mark, balance_set_at FROM holdings WHERE id = ?", (holding_id,)
        ).fetchone()
        if h is None:
            return []
        as_of, mark, set_at = h["balance_as_of"], h["balance_mark"] or 0, h["balance_set_at"] or ""

        def counted(day: str, after: bool) -> bool:
            return as_of is not None and (day > as_of or (day == as_of and after))

        items: List[Dict[str, Any]] = []
        for row in self.conn.execute(
            """
            SELECT t.id, t.description, t.kind, t.occurred_on, c.name AS category,
                   COALESCE(t.original_cents, t.amount_cents) AS paid
            FROM transactions t JOIN categories c ON c.id = t.category_id
            WHERE t.account_id = ? ORDER BY t.occurred_on DESC, t.id DESC LIMIT ?
            """,
            (holding_id, limit),
        ):
            sign = 1 if row["kind"] == "income" else -1
            items.append({
                "type": row["kind"], "id": row["id"], "date": row["occurred_on"], "description": row["description"],
                "category": row["category"], "amount_cents": sign * row["paid"],
                "counted": counted(row["occurred_on"], row["id"] > mark),
            })
        for row in self.conn.execute(
            """
            SELECT tr.*, f.name AS from_name, o.name AS to_name
            FROM transfers tr
            LEFT JOIN holdings f ON f.id = tr.from_account_id
            LEFT JOIN holdings o ON o.id = tr.to_account_id
            WHERE tr.from_account_id = ? OR tr.to_account_id = ?
            ORDER BY tr.occurred_on DESC, tr.id DESC LIMIT ?
            """,
            (holding_id, holding_id, limit),
        ):
            outgoing = row["from_account_id"] == holding_id
            other = row["to_name"] if outgoing else row["from_name"]
            items.append({
                "type": "transfer", "id": row["id"], "date": row["occurred_on"],
                "description": f"{'To' if outgoing else 'From'} {other or 'a removed account'}",
                "category": row["note"] or None,
                "amount_cents": -row["from_cents"] if outgoing else row["to_cents"],
                "counted": counted(row["occurred_on"], row["created_at"] > set_at),
            })
        # Newest first; on the day the balance was entered, items in it go below the ones after it.
        items.sort(key=lambda i: (i["date"], i["counted"], i["id"]), reverse=True)
        return items[:limit]

    # ---------------------------------------------------------- savings goals

    def add_goal(self, goal: SavingsGoal) -> int:
        with self.conn:
            cursor = self.conn.execute(
                """
                INSERT INTO savings_goals (name, target_cents, currency, target_date, account_id, saved_cents,
                                           created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (goal.name.strip(), goal.target_cents, goal.currency,
                 goal.target_date.isoformat() if goal.target_date else None, goal.account_id, goal.saved_cents,
                 _utc_now()),
            )
        return cursor.lastrowid

    def goals(self) -> List[SavingsGoal]:
        rows = self.conn.execute(
            "SELECT * FROM savings_goals ORDER BY target_date IS NULL, target_date, id"
        )
        return [_row_to_goal(row) for row in rows]

    def get_goal(self, goal_id: int) -> Optional[SavingsGoal]:
        row = self.conn.execute("SELECT * FROM savings_goals WHERE id = ?", (goal_id,)).fetchone()
        return _row_to_goal(row) if row else None

    def update_goal(self, goal_id: int, goal: SavingsGoal) -> bool:
        with self.conn:
            cursor = self.conn.execute(
                """
                UPDATE savings_goals SET name = ?, target_cents = ?, currency = ?, target_date = ?,
                       account_id = ?, saved_cents = ?
                WHERE id = ?
                """,
                (goal.name.strip(), goal.target_cents, goal.currency,
                 goal.target_date.isoformat() if goal.target_date else None, goal.account_id, goal.saved_cents,
                 goal_id),
            )
        return cursor.rowcount > 0

    def delete_goal(self, goal_id: int) -> bool:
        with self.conn:
            cursor = self.conn.execute("DELETE FROM savings_goals WHERE id = ?", (goal_id,))
        return cursor.rowcount > 0

    # -------------------------------------------------------------- transfers

    def add_transfer(self, transfer: Transfer) -> int:
        with self.conn:
            cursor = self.conn.execute(
                """
                INSERT INTO transfers (occurred_on, from_account_id, to_account_id, from_cents, to_cents,
                                       note, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (transfer.occurred_on.isoformat(), transfer.from_account_id, transfer.to_account_id,
                 transfer.from_cents, transfer.to_cents, transfer.note.strip(), _utc_now_precise()),
            )
        return cursor.lastrowid

    def transfers(self, limit: int = 100) -> List[Transfer]:
        rows = self.conn.execute(
            "SELECT * FROM transfers ORDER BY occurred_on DESC, id DESC LIMIT ?", (limit,)
        )
        return [
            Transfer(date.fromisoformat(r["occurred_on"]), r["from_account_id"], r["to_account_id"],
                     r["from_cents"], r["to_cents"], r["note"], r["id"])
            for r in rows
            if r["from_account_id"] is not None and r["to_account_id"] is not None
        ]

    def delete_transfer(self, transfer_id: int) -> bool:
        with self.conn:
            cursor = self.conn.execute("DELETE FROM transfers WHERE id = ?", (transfer_id,))
        return cursor.rowcount > 0

    # ---------------------------------------------------------- exchange rates

    def fx_rate(self, currency: str, day: date) -> Optional[float]:
        """Units of ``currency`` per US dollar on ``day``, from saved prices:
        the last daily close on or before it, else the latest quote. None if
        nothing is saved yet. (PriceService.fx_rate fetches them.)"""
        if currency == HOME_CURRENCY:
            return 1.0
        symbol = fx_symbol(currency)
        row = self.conn.execute(
            "SELECT close FROM price_history WHERE symbol = ? AND day <= ? ORDER BY day DESC LIMIT 1",
            (symbol, day.isoformat()),
        ).fetchone()
        if row:
            return row["close"]
        cached = self.cached_price(symbol)
        return cached[0] if cached else None

    def _home_cents(self, cents: int, currency: str, day: date) -> Optional[int]:
        if currency == HOME_CURRENCY:
            return cents
        rate = self.fx_rate(currency, day)
        return to_home_cents(cents, rate) if rate else None

    def currencies_due(self, today: date) -> List[str]:
        """Non-USD currencies of recurring rules with an occurrence due, so the
        API can fetch their exchange rates before catching up."""
        rows = self.conn.execute(
            "SELECT DISTINCT currency FROM recurring WHERE active = 1 AND next_due <= ? AND currency != ?",
            (today.isoformat(), HOME_CURRENCY),
        )
        return [row["currency"] for row in rows]

    def is_cash_account(self, holding_id: int) -> bool:
        return self.conn.execute(
            "SELECT 1 FROM holdings WHERE id = ? AND asset_type = 'cash'", (holding_id,)
        ).fetchone() is not None

    # ---------------------------------------------------------- price history

    def save_price_history(
        self, symbol: str, closes: Sequence[Tuple[date, float]], currency: str, fetched_at: datetime
    ) -> None:
        symbol = symbol.upper()
        with self.conn:
            self.conn.executemany(
                "INSERT INTO price_history (symbol, day, close) VALUES (?, ?, ?) "
                "ON CONFLICT (symbol, day) DO UPDATE SET close = excluded.close",
                [(symbol, day.isoformat(), close) for day, close in closes],
            )
            self.conn.execute(
                "INSERT INTO price_history_fetched (symbol, currency, fetched_at) VALUES (?, ?, ?) "
                "ON CONFLICT (symbol) DO UPDATE SET currency = excluded.currency, fetched_at = excluded.fetched_at",
                (symbol, currency, fetched_at.isoformat(timespec="seconds")),
            )

    def price_history(self, symbol: str) -> List[Tuple[date, float]]:
        """Daily closes, oldest first."""
        rows = self.conn.execute(
            "SELECT day, close FROM price_history WHERE symbol = ? ORDER BY day", (symbol.upper(),)
        )
        return [(date.fromisoformat(row["day"]), row["close"]) for row in rows]

    def price_history_fetched(self, symbol: str) -> Optional[Tuple[datetime, str]]:
        row = self.conn.execute(
            "SELECT fetched_at, currency FROM price_history_fetched WHERE symbol = ?", (symbol.upper(),)
        ).fetchone()
        return (datetime.fromisoformat(row["fetched_at"]), row["currency"]) if row else None

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
           t.account_id, t.currency, t.original_cents, c.name AS category
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
        account_id=row["account_id"],
        currency=row["currency"],
        original_cents=row["original_cents"],
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
        account_id=row["account_id"],
        currency=row["currency"],
    )


def _row_to_goal(row: sqlite3.Row) -> SavingsGoal:
    return SavingsGoal(
        id=row["id"],
        name=row["name"],
        target_cents=row["target_cents"],
        currency=row["currency"],
        target_date=date.fromisoformat(row["target_date"]) if row["target_date"] else None,
        account_id=row["account_id"],
        saved_cents=row["saved_cents"],
    )


def _row_to_holding(row: sqlite3.Row) -> Holding:
    return Holding(
        id=row["id"],
        asset_type=AssetType(row["asset_type"]),
        name=row["name"],
        symbol=row["symbol"],
        quantity=row["quantity"],
        manual_value_cents=row["manual_value_cents"],
        bought_on=date.fromisoformat(row["bought_on"]) if row["bought_on"] else None,
        cost_basis_cents=row["cost_basis_cents"],
        balance_as_of=date.fromisoformat(row["balance_as_of"]) if row["balance_as_of"] else None,
        currency=row["currency"],
    )
