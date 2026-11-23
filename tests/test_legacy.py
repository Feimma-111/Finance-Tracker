import os
import tempfile
import unittest
from datetime import date
from pathlib import Path

from finance_tracker.legacy import LEGACY_META_KEY, import_legacy_file, read_legacy_file
from finance_tracker.store import Store

LEGACY_LINES = [
    '{"name": "dinner", "price": 550.0, "type": "food", "date": "2026-07-18T00:00:00"}',
    '{"name": "coffee", "price": 4.5, "type": "food", "date": "2026/07/19"}',
    "",
    '{"name": "mystery", "price": 3, "type": "misc", "date": "July 3"}',
    '{"name": "free", "price": 0, "type": "misc", "date": "2026-07-01"}',
    "not json",
]


class LegacyImportTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.folder.name, "information_save_file")
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write("\n".join(LEGACY_LINES) + "\n")

    def tearDown(self):
        self.folder.cleanup()

    def test_reads_good_lines_and_reports_bad_ones(self):
        transactions, problems = read_legacy_file(self.path)
        self.assertEqual([t.description for t in transactions], ["dinner", "coffee"])
        self.assertEqual(transactions[0].amount_cents, 55000)
        self.assertEqual(transactions[1].occurred_on, date(2026, 7, 19))
        self.assertEqual(len(problems), 3)
        self.assertTrue(problems[0].startswith("line 4"))

    def test_import_marks_done_and_leaves_file_alone(self):
        before = Path(self.path).read_text(encoding="utf-8")
        with Store(":memory:") as store:
            imported, _ = import_legacy_file(store, self.path)
            self.assertEqual(imported, 2)
            self.assertEqual(store.get_meta(LEGACY_META_KEY), "done")
            self.assertEqual(store.totals_by_category(), [("food", 55450)])
        self.assertEqual(Path(self.path).read_text(encoding="utf-8"), before)


if __name__ == "__main__":
    unittest.main()
