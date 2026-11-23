"""Moving the database out of the project folder, safely."""

import os
import sqlite3
import stat
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

from finance_tracker import paths, relocate
from finance_tracker.models import Kind, Transaction
from finance_tracker.store import Store


def seed(db):
    with Store(db) as store:
        store.create_profile("Sam")
        for day in range(1, 11):
            store.add_transaction(Transaction("Coffee", 450, "Food", date(2026, 11, day), Kind.EXPENSE))


class MoveTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        root = Path(self.folder.name)
        self.old = root / "project" / "data" / "finance.db"
        self.new = root / "Application Support" / "Finance Tracker" / "finance.db"
        seed(self.old)
        (self.old.parent / "backups").mkdir()
        (self.old.parent / "backups" / "finance-2026-11-20.db").write_bytes(self.old.read_bytes())

    def tearDown(self):
        self.folder.cleanup()

    def test_moves_data_and_backups_and_keeps_the_old_copy(self):
        message = relocate.move_database(self.old, self.new)
        self.assertIn(str(self.new), message)
        with Store(self.new) as store:
            self.assertEqual((store.profile_name(), store.transaction_count()), ("Sam", 10))
        self.assertFalse(self.old.exists())                                   # nothing keeps using it
        self.assertTrue(self.old.with_name("finance.db.moved").exists())      # but it isn't deleted
        self.assertIn(str(self.new), (self.old.parent / "MOVED.txt").read_text())
        self.assertTrue((self.new.parent / "backups" / "finance-2026-11-20.db").exists())
        self.assertEqual(stat.S_IMODE(self.new.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.new.parent.stat().st_mode), 0o700)
        self.assertEqual(list(self.new.parent.glob("*.moving")), [])

    def test_only_once(self):
        relocate.move_database(self.old, self.new)
        seed(self.old)  # pretend something recreated an old-location file
        self.assertIsNone(relocate.move_database(self.old, self.new))  # new one exists: hands off
        self.assertTrue(self.old.exists())

    def test_a_mismatched_copy_stops_the_move(self):
        with mock.patch.object(relocate, "_row_counts", side_effect=[{"transactions": 10}, {"transactions": 9}]):
            with self.assertRaises(relocate.RelocationError):
                relocate.move_database(self.old, self.new)
        self.assertTrue(self.old.exists())        # untouched
        self.assertFalse(self.new.exists())       # nothing half-moved
        self.assertEqual(list(self.new.parent.glob("*")), [])

    def test_prepare_falls_back_to_the_old_location_on_failure(self):
        with mock.patch.object(paths, "PROJECT_DB", self.old), \
             mock.patch.object(paths, "DEFAULT_DB", self.new), \
             mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("FINANCE_TRACKER_DB", None)
            with mock.patch.object(relocate, "move_database", side_effect=OSError("disk full")):
                self.assertEqual(relocate.prepare(str(self.new)), str(self.old))
            self.assertEqual(relocate.prepare(str(self.new)), str(self.new))  # the real move
            self.assertTrue(self.new.exists())

    def test_an_explicit_db_path_is_never_moved(self):
        with mock.patch.dict(os.environ, {"FINANCE_TRACKER_DB": str(self.old)}):
            self.assertEqual(relocate.prepare(str(self.old)), str(self.old))
        self.assertTrue(self.old.exists())


class LocationTests(unittest.TestCase):
    def test_platform_folders(self):
        with mock.patch.object(paths.sys, "platform", "darwin"):
            self.assertTrue(str(paths.default_data_dir()).endswith("Library/Application Support/Finance Tracker"))
        with mock.patch.object(paths.sys, "platform", "linux"), mock.patch.object(paths.os, "name", "posix"), \
             mock.patch.dict(os.environ, {"XDG_DATA_HOME": "/srv/data"}):
            self.assertEqual(paths.default_data_dir(), Path("/srv/data/finance-tracker"))

    def test_default_is_outside_the_project(self):
        self.assertNotIn(str(paths.PROJECT_ROOT), str(paths.DEFAULT_DB))


if __name__ == "__main__":
    unittest.main()
