"""Backups and turning a transaction into a recurring rule."""

import os
import sqlite3
import stat
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path

from tests.support import sign_in
from finance_tracker import backup
from finance_tracker.cli import main as cli_main
from finance_tracker.models import Frequency, Kind, Transaction
from finance_tracker.store import SCHEMA_V1, Store

try:
    from fastapi.testclient import TestClient

    from finance_tracker.api import create_app
except ImportError:
    TestClient = None

from tests.test_prices import FakeProvider

TODAY = date(2026, 11, 22)


def tx(desc, cents, day, category="Subscriptions", kind=Kind.EXPENSE):
    return Transaction(desc, cents, category, day, kind)


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.folder.name, "data", "finance.db")
        with Store(self.db) as store:
            store.add_transaction(tx("Coffee", 450, date(2026, 11, 1), "Food"))

    def tearDown(self):
        self.folder.cleanup()

    def count(self, path):
        conn = sqlite3.connect(path)
        try:
            return conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
        finally:
            conn.close()

    def test_daily_backup_once_per_day_and_private(self):
        first = backup.make_backup(self.db, now=datetime(2026, 11, 22, 9))
        self.assertEqual(first.name, "finance-2026-11-22.db")
        self.assertIsNone(backup.make_backup(self.db, now=datetime(2026, 11, 22, 18)))  # already done today
        self.assertEqual(self.count(first), 1)
        self.assertEqual(stat.S_IMODE(first.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(first.parent.stat().st_mode), 0o700)
        self.assertEqual(list(first.parent.glob("*.tmp")), [])

    def test_pruning_keeps_the_newest(self):
        # 35 daily backups: Oct 1-31 and Nov 1-4.
        days = [datetime(2026, 10, d) for d in range(1, 32)] + [datetime(2026, 11, d) for d in range(1, 5)]
        for day in days:
            backup.make_backup(self.db, now=day)
        for i in range(12):
            backup.make_backup(self.db, label="before-import", now=datetime(2026, 11, 22, 10, i))
        names = [b["name"] for b in backup.list_backups(self.db)]
        daily = [n for n in names if n.count("-") == 3]
        labeled = [n for n in names if "before-import" in n]
        self.assertEqual((len(daily), len(labeled)), (backup.KEEP_DAILY, backup.KEEP_LABELED))
        self.assertNotIn("finance-2026-10-01.db", names)  # oldest dropped
        self.assertIn("finance-2026-11-04.db", names)

    def test_restore_saves_current_data_first(self):
        saved = backup.make_backup(self.db, now=datetime(2026, 11, 20))
        with Store(self.db) as store:
            store.add_transaction(tx("Oops", 100, date(2026, 11, 21), "Food"))
        safety = backup.restore(self.db, saved)
        self.assertIn("before-restore", safety.name)
        self.assertEqual(self.count(self.db), 1)      # back to the backup
        self.assertEqual(self.count(safety), 2)       # the newer data wasn't lost
        self.assertEqual(stat.S_IMODE(Path(self.db).stat().st_mode), 0o600)

    def test_restore_refuses_damaged_backups(self):
        bad = Path(self.folder.name) / "bad.db"
        bad.write_bytes(b"not a database")
        with self.assertRaises((backup.BackupError, sqlite3.DatabaseError)):
            backup.restore(self.db, bad)
        self.assertEqual(self.count(self.db), 1)

    def test_upgrading_an_old_database_backs_it_up_first(self):
        old = os.path.join(self.folder.name, "old", "finance.db")
        os.makedirs(os.path.dirname(old))
        conn = sqlite3.connect(old)
        conn.executescript(f"BEGIN; {SCHEMA_V1} PRAGMA user_version = 1; COMMIT;")
        conn.close()
        Store(old).close()
        names = [b["name"] for b in backup.list_backups(old)]
        self.assertTrue(any("before-upgrade-v1" in n for n in names), names)

    def test_cli_restore_by_name(self):
        saved = backup.make_backup(self.db, now=datetime(2026, 11, 20))
        with Store(self.db) as store:
            store.add_transaction(tx("Oops", 100, date(2026, 11, 21), "Food"))
        cli_main(["--db", self.db, "--restore-backup", saved.name])
        self.assertEqual(self.count(self.db), 1)


class MakeRecurringTests(unittest.TestCase):
    def setUp(self):
        self.store = Store(":memory:")

    def tearDown(self):
        self.store.close()

    def test_links_existing_charges_instead_of_duplicating(self):
        first = self.store.add_transaction(tx("YouTube", 1399, date(2026, 8, 5)))
        self.store.add_transaction(tx("youtube ", 1399, date(2026, 9, 6)))   # posted a day late
        self.store.add_transaction(tx("YouTube", 1599, date(2026, 11, 4)))   # price went up
        self.store.add_transaction(tx("YouTube", 1399, date(2026, 10, 20)))  # not near Oct 5: left alone
        result = self.store.make_recurring(first, Frequency.MONTHLY, today=TODAY, fill_missing=False)
        self.assertEqual((result["linked"], result["created"]), (2, 0))
        rule = self.store.get_recurring(result["rule_id"])
        self.assertEqual(rule.next_due, date(2026, 12, 5))
        linked = sorted(t.occurred_on for t in self.store.transactions() if t.recurring_id == rule.id)
        self.assertEqual(linked, [date(2026, 8, 5), date(2026, 9, 6), date(2026, 11, 4)])
        self.assertEqual(self.store.transaction_count(), 4)  # nothing added
        # And from now on it's added automatically.
        self.assertEqual(self.store.apply_recurring(date(2026, 12, 5)), 1)

    def test_fill_missing_adds_the_gaps(self):
        first = self.store.add_transaction(tx("YouTube", 1399, date(2026, 8, 5)))
        self.store.add_transaction(tx("YouTube", 1399, date(2026, 10, 5)))
        result = self.store.make_recurring(first, Frequency.MONTHLY, today=TODAY, fill_missing=True)
        self.assertEqual((result["linked"], result["created"]), (1, 2))  # Oct linked; Sep and Nov added
        days = sorted(t.occurred_on for t in self.store.transactions())
        self.assertEqual(days, [date(2026, 8, 5), date(2026, 9, 5), date(2026, 10, 5), date(2026, 11, 5)])

    def test_already_recurring_is_refused(self):
        first = self.store.add_transaction(tx("YouTube", 1399, date(2026, 8, 5)))
        self.store.make_recurring(first, Frequency.MONTHLY, today=TODAY, fill_missing=False)
        with self.assertRaises(ValueError):
            self.store.make_recurring(first, Frequency.MONTHLY, today=TODAY, fill_missing=False)
        self.assertIsNone(self.store.make_recurring(999, Frequency.MONTHLY, today=TODAY, fill_missing=False))


@unittest.skipIf(TestClient is None, "install requirements.txt to test the web API")
class BackupAndRecurringApiTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.folder.name, "finance.db")
        app = create_app(self.db, provider=FakeProvider({}), today=lambda: TODAY, static_dir=None)
        self.client = TestClient(app)
        sign_in(self.client)

    def tearDown(self):
        self.client.close()
        self.folder.cleanup()

    def test_backups_endpoints(self):
        self.assertEqual(len(self.client.get("/api/backups").json()["backups"]), 1)  # made at startup
        made = self.client.post("/api/backups").json()
        self.assertIn("manual", made["name"])
        download = self.client.get("/api/backups/download")
        self.assertEqual(download.status_code, 200)
        self.assertTrue(download.content.startswith(b"SQLite format 3"))
        self.assertIn("attachment", download.headers["content-disposition"])

    def test_import_makes_a_safety_backup(self):
        csv = "Date,Description,Amount\n11/03/2026,Coffee,-4.50\n"
        mapping = self.client.post("/api/import/preview", json={"csv": csv}).json()["mapping"]
        self.client.post("/api/import", json={"csv": csv, "mapping": mapping})
        names = [b["name"] for b in self.client.get("/api/backups").json()["backups"]]
        self.assertTrue(any("before-import" in n for n in names))

    def test_make_recurring_endpoint(self):
        tx_id = self.client.post("/api/transactions", json={
            "description": "YouTube", "amount": "13.99", "category": "Subscriptions",
            "occurred_on": "2026-10-05"}).json()["id"]
        made = self.client.post(f"/api/transactions/{tx_id}/recurring", json={"frequency": "monthly"}).json()
        self.assertEqual((made["frequency"], made["next_due"], made["linked"], made["created"]),
                         ("monthly", "2026-12-05", 0, 0))
        self.assertEqual(self.client.get(f"/api/transactions/{tx_id}").json()["recurring_id"], made["id"])
        again = self.client.post(f"/api/transactions/{tx_id}/recurring", json={"frequency": "monthly"})
        self.assertEqual(again.status_code, 409)


if __name__ == "__main__":
    unittest.main()
