import os
import sqlite3
import tempfile
import unittest
from datetime import date

from finance_tracker.models import (
    Frequency,
    Kind,
    RecurringRule,
    Transaction,
    add_months,
    occurrence,
    parse_date,
)
from finance_tracker.store import MIGRATIONS, SCHEMA_V1, Store


def rent(start=date(2026, 9, 1), frequency=Frequency.MONTHLY, cents=125000):
    return RecurringRule("Rent", cents, "Housing", frequency, start)


class DateMathTests(unittest.TestCase):
    def test_month_end_clamps_without_drifting(self):
        start = date(2026, 1, 31)
        self.assertEqual(
            [occurrence(start, Frequency.MONTHLY, n) for n in range(4)],
            [date(2026, 1, 31), date(2026, 2, 28), date(2026, 3, 31), date(2026, 4, 30)],
        )

    def test_other_frequencies(self):
        start = date(2026, 11, 1)
        self.assertEqual(occurrence(start, Frequency.WEEKLY, 2), date(2026, 11, 15))
        self.assertEqual(occurrence(start, Frequency.BIWEEKLY, 2), date(2026, 11, 29))
        self.assertEqual(occurrence(date(2024, 2, 29), Frequency.YEARLY, 1), date(2025, 2, 28))
        self.assertEqual(add_months(date(2026, 12, 15), 1), date(2027, 1, 15))

    def test_future_start_allowed_only_for_recurring(self):
        today = date(2026, 11, 22)
        self.assertEqual(parse_date("2026-12-01", today=today, allow_future=True), date(2026, 12, 1))
        with self.assertRaises(ValueError):
            parse_date("2026-12-01", today=today)
        with self.assertRaises(ValueError):
            parse_date("2028-01-01", today=today, allow_future=True)


class ApplyRecurringTests(unittest.TestCase):
    def setUp(self):
        self.store = Store(":memory:")

    def tearDown(self):
        self.store.close()

    def test_backfills_due_occurrences_once(self):
        rule_id = self.store.add_recurring(rent())
        self.assertEqual(self.store.apply_recurring(date(2026, 11, 22)), 3)  # Sep, Oct, Nov
        self.assertEqual(self.store.apply_recurring(date(2026, 11, 22)), 0)  # idempotent
        dates = sorted(t.occurred_on for t in self.store.transactions())
        self.assertEqual(dates, [date(2026, 9, 1), date(2026, 10, 1), date(2026, 11, 1)])
        self.assertTrue(all(t.recurring_id == rule_id for t in self.store.transactions()))
        self.assertEqual(self.store.get_recurring(rule_id).next_due, date(2026, 12, 1))

        # Opening the app on Dec 1 adds exactly December's rent.
        self.assertEqual(self.store.apply_recurring(date(2026, 12, 1)), 1)

    def test_future_rule_waits(self):
        self.store.add_recurring(rent(start=date(2026, 12, 1)))
        self.assertEqual(self.store.apply_recurring(date(2026, 11, 22)), 0)
        self.assertEqual(self.store.transaction_count(), 0)

    def test_pause_skips_missed_occurrences(self):
        rule_id = self.store.add_recurring(rent())
        self.store.apply_recurring(date(2026, 9, 15))  # September only
        self.store.update_recurring(rule_id, today=date(2026, 9, 15), active=False)
        self.assertEqual(self.store.apply_recurring(date(2026, 12, 15)), 0)  # paused: nothing

        self.store.update_recurring(rule_id, today=date(2026, 12, 15), active=True)
        self.assertEqual(self.store.get_recurring(rule_id).next_due, date(2027, 1, 1))
        self.assertEqual(self.store.apply_recurring(date(2026, 12, 15)), 0)  # Oct-Dec not backfilled
        self.assertEqual(self.store.transaction_count(), 1)

    def test_amount_change_applies_going_forward(self):
        rule_id = self.store.add_recurring(rent())
        self.store.apply_recurring(date(2026, 11, 22))
        self.store.update_recurring(rule_id, today=date(2026, 11, 22), amount_cents=130000)
        self.store.apply_recurring(date(2026, 12, 1))
        amounts = [t.amount_cents for t in sorted(self.store.transactions(), key=lambda t: t.occurred_on)]
        self.assertEqual(amounts, [125000, 125000, 125000, 130000])

    def test_deleting_rule_keeps_history(self):
        rule_id = self.store.add_recurring(rent())
        self.store.apply_recurring(date(2026, 11, 22))
        self.assertTrue(self.store.delete_recurring(rule_id))
        self.assertEqual(self.store.transaction_count(), 3)
        self.assertTrue(all(t.recurring_id is None for t in self.store.transactions()))

    def test_income_rules_and_categories(self):
        self.store.add_recurring(
            RecurringRule("Paycheck", 210000, "Salary", Frequency.BIWEEKLY, date(2026, 11, 6), Kind.INCOME)
        )
        self.store.apply_recurring(date(2026, 11, 22))
        self.assertEqual(self.store.totals_by_category(Kind.INCOME), [("Salary", 420000)])


class UpgradeTests(unittest.TestCase):
    def test_version_1_database_upgrades_in_place(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "old.db")
            # Build a database exactly as the previous release would have.
            conn = sqlite3.connect(path)
            conn.executescript(f"BEGIN; {SCHEMA_V1} PRAGMA user_version = 1; COMMIT;")
            conn.execute("INSERT INTO categories (name) VALUES ('Food')")
            conn.execute(
                "INSERT INTO transactions (description, amount_cents, kind, category_id, occurred_on) "
                "VALUES ('Coffee', 450, 'expense', 1, '2026-07-01')"
            )
            conn.commit()
            conn.close()

            with Store(path) as store:
                self.assertEqual(store.conn.execute("PRAGMA user_version").fetchone()[0], len(MIGRATIONS))
                [old] = store.transactions()
                self.assertEqual((old.description, old.recurring_id), ("Coffee", None))
                store.add_transaction(Transaction("Tea", 300, "Food", date(2026, 7, 2)))
                self.assertEqual(store.transaction_count(), 2)


if __name__ == "__main__":
    unittest.main()
