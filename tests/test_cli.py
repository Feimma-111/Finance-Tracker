"""Drive whole terminal sessions with scripted input."""

import os
import tempfile
import unittest
from datetime import date
from pathlib import Path

from finance_tracker.cli import App
from finance_tracker.models import AssetType, Holding
from finance_tracker.prices import PriceService
from finance_tracker.store import Store

from tests.test_prices import FakeProvider

TODAY = date(2026, 11, 22)


class Session:
    """Feeds scripted answers to App and records everything it prints."""

    def __init__(self, store, answers, folder, prices=None):
        self.answers = list(answers)
        self.lines = []
        self.app = App(
            store,
            PriceService(store, FakeProvider(prices or {})),
            input_fn=self._input,
            print_fn=self.lines.append,
            today=lambda: TODAY,
            legacy_path=Path(folder) / "information_save_file",
            export_dir=Path(folder) / "exports",
        )

    def _input(self, prompt):
        self.lines.append(prompt)
        if not self.answers:
            raise EOFError  # script ran out: behave like Ctrl-D
        return self.answers.pop(0)

    @property
    def output(self):
        return "\n".join(self.lines)


class CliTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.store = Store(":memory:")

    def tearDown(self):
        self.store.close()
        self.folder.cleanup()

    def run_session(self, answers, prices=None):
        session = Session(self.store, answers, self.folder.name, prices)
        session.app.run()
        return session.output

    def test_new_user_adds_transactions_and_sees_reports(self):
        output = self.run_session([
            "Sam",                                                   # name
            "1", "", "Coffee", "ten", "4.50", "Food", "2026-07-01",    # bad amount re-prompts
            "1", "", "Groceries", "30", "1", "",                       # pick category by number
            "1", "i", "Paycheck", "1000", "Salary", "2026-11-01",
            "3", "",                                                   # category report, all time
            "4", "",                                                   # monthly report
            "0",
        ])
        self.assertIn("Nice to meet you, Sam", output)
        self.assertIn("'ten' isn't a number", output)
        self.assertIn("Saved expense: $4.50 - Coffee (Food, 2026-07-01)", output)
        self.assertIn("Saved expense: $30.00 - Groceries (Food, 2026-11-22)", output)
        self.assertIn("Spending for all time: $34.50", output)
        self.assertIn("Income: $1,000.00    Net: $965.50", output)
        self.assertIn("2026-11         $30.00", output)
        self.assertIn("in progress", output)
        self.assertIn("Goodbye!", output)

    def test_returning_user_is_greeted_with_month_total(self):
        self.store.create_profile("Sam")
        output = self.run_session(["0"])
        self.assertIn("Welcome back, Sam. You've spent $0.00 so far this month.", output)

    def test_typo_category_requires_confirmation(self):
        self.store.create_profile("Sam")
        output = self.run_session([
            "1", "", "Milk", "3", "Groceries", "",
            "1", "", "Eggs", "4", "Grocries", "n", "1", "",   # decline typo, pick #1
            "3", "", "0",
        ])
        self.assertIn("'Grocries' is a new category", output)
        self.assertIn("Groceries                $7.00", output)
        self.assertNotIn("Grocries          ", output)

    def test_delete_transaction(self):
        self.store.create_profile("Sam")
        output = self.run_session([
            "1", "", "Oops", "99", "misc", "",
            "2", "1", "y",
            "0",
        ])
        self.assertIn("Deleted.", output)
        self.assertEqual(self.store.transaction_count(), 0)

    def test_holdings_and_net_worth(self):
        self.store.create_profile("Sam")
        output = self.run_session(
            [
                "6",
                "a", "1", "Checking", "1500",
                "a", "2", "aapl", "2.5", "",
                "a", "4", "0.1",
                "a", "2", "FAKE", "n",                 # unknown ticker, don't add
                "",
                "5",
                "0",
            ],
            prices={"AAPL": 342.56, "GC=F": 3614.30},
        )
        self.assertIn("AAPL is at 342.56 USD", output)
        self.assertIn("Couldn't get a price: no market data for 'FAKE'", output)
        self.assertIn("Net worth: $2,717.83", output)  # 1500 + 856.40 + 361.43
        self.assertEqual(self.store.net_worth_history(), [(TODAY, 271783)])
        self.assertEqual(len(self.store.holdings()), 3)

    def test_export_csv(self):
        self.store.create_profile("Sam")
        self.run_session(["1", "", "Coffee", "4.5", "food", "2026-07-01", "7", "0"])
        path = Path(self.folder.name) / "exports" / "transactions-2026-11-22.csv"
        self.assertEqual(
            path.read_text(encoding="utf-8").splitlines(),
            ["id,date,kind,category,description,amount", "1,2026-07-01,expense,food,Coffee,4.50"],
        )

    def test_offers_legacy_import_once(self):
        legacy = Path(self.folder.name) / "information_save_file"
        legacy.write_text(
            '{"name": "dinner", "price": 550.0, "type": "food", "date": "2026-07-18T00:00:00"}\n',
            encoding="utf-8",
        )
        first = self.run_session(["Sam", "y", "0"])
        self.assertIn("Imported 1 transaction(s)", first)
        second = self.run_session(["0"])
        self.assertNotIn("Found a save file", second)
        self.assertEqual(self.store.transaction_count(), 1)

    def test_ctrl_d_exits_cleanly(self):
        output = self.run_session([])  # EOF at the very first prompt
        self.assertIn("Goodbye!", output)


if __name__ == "__main__":
    unittest.main()
