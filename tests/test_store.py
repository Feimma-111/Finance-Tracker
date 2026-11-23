import os
import sqlite3
import tempfile
import unittest
from datetime import date, datetime, timezone

from finance_tracker.models import AssetType, Holding, Kind, Transaction
from finance_tracker.store import MIGRATIONS, Store


def tx(desc, cents, category, day, kind=Kind.EXPENSE):
    return Transaction(desc, cents, category, day, kind)


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.store = Store(":memory:")

    def tearDown(self):
        self.store.close()

    def test_schema_version_recorded(self):
        version = self.store.conn.execute("PRAGMA user_version").fetchone()[0]
        self.assertEqual(version, len(MIGRATIONS))

    def test_profile(self):
        self.assertIsNone(self.store.profile_name())
        self.store.create_profile("  Sam ")
        self.assertEqual(self.store.profile_name(), "Sam")
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.create_profile("Someone else")

    def test_categories_are_case_insensitive_and_ordered_by_use(self):
        self.store.add_transaction(tx("Coffee", 450, "Food", date(2026, 7, 1)))
        self.store.add_transaction(tx("Bagel", 300, "food", date(2026, 7, 2)))
        self.store.add_transaction(tx("Bus", 200, "Transport", date(2026, 7, 3)))
        self.store.add_transaction(tx("Paycheck", 100000, "Salary", date(2026, 7, 4), Kind.INCOME))

        self.assertEqual(self.store.categories(Kind.EXPENSE), ["Food", "Transport"])
        self.assertEqual(self.store.categories(Kind.INCOME), ["Salary"])
        self.assertEqual(self.store.find_category("  FOOD "), "Food")
        self.assertIsNone(self.store.find_category("rent"))

    def test_totals(self):
        self.store.add_transaction(tx("Coffee", 450, "food", date(2026, 6, 30)))
        self.store.add_transaction(tx("Milk", 325, "food", date(2026, 7, 1)))
        self.store.add_transaction(tx("Bus", 200, "transport", date(2026, 7, 31)))
        self.store.add_transaction(tx("Paycheck", 5000, "salary", date(2026, 7, 15), Kind.INCOME))

        self.assertEqual(self.store.totals_by_category(), [("food", 775), ("transport", 200)])
        self.assertEqual(
            self.store.totals_by_category(month="2026-07"), [("food", 325), ("transport", 200)]
        )
        self.assertEqual(self.store.totals_by_month(), [("2026-06", 450), ("2026-07", 525)])
        self.assertEqual(self.store.totals_by_month(Kind.INCOME), [("2026-07", 5000)])

    def test_transactions_newest_first_and_delete(self):
        first = self.store.add_transaction(tx("Old", 100, "misc", date(2026, 1, 1)))
        self.store.add_transaction(tx("New", 200, "misc", date(2026, 2, 1)))
        self.assertEqual([t.description for t in self.store.transactions()], ["New", "Old"])
        self.assertEqual(len(self.store.transactions(month="2026-01")), 1)
        self.assertEqual(self.store.get_transaction(first).amount_cents, 100)
        self.assertTrue(self.store.delete_transaction(first))
        self.assertFalse(self.store.delete_transaction(first))
        self.assertEqual(self.store.transaction_count(), 1)

    def test_bulk_insert_is_all_or_nothing(self):
        good = tx("Fine", 100, "misc", date(2026, 1, 1))

        class Broken:  # not a Transaction; fails mid-batch
            description = "x"

        with self.assertRaises(AttributeError):
            self.store.add_transactions([good, Broken()])
        self.assertEqual(self.store.transaction_count(), 0)

    def test_holdings_crud(self):
        stock_id = self.store.add_holding(Holding(AssetType.STOCK, "Apple", 3, symbol="aapl"))
        cash_id = self.store.add_holding(
            Holding(AssetType.CASH, "Checking", manual_value_cents=150000)
        )
        stock = self.store.get_holding(stock_id)
        self.assertEqual(stock.symbol, "AAPL")
        self.assertTrue(self.store.update_holding(stock_id, quantity=5))
        self.assertEqual(self.store.get_holding(stock_id).quantity, 5)
        self.assertTrue(self.store.update_holding(cash_id, manual_value_cents=0))
        self.assertEqual(self.store.get_holding(cash_id).manual_value_cents, 0)
        self.assertTrue(self.store.remove_holding(stock_id))
        self.assertEqual([h.name for h in self.store.holdings()], ["Checking"])

    def test_price_cache_round_trip(self):
        when = datetime(2026, 11, 22, 15, 0, tzinfo=timezone.utc)
        self.store.save_price("aapl", 342.5, "USD", when)
        self.assertEqual(self.store.cached_price("AAPL"), (342.5, "USD", when))
        self.store.save_price("AAPL", 350.0, "USD", when)
        self.assertEqual(self.store.cached_price("aapl")[0], 350.0)

    def test_net_worth_snapshots(self):
        self.store.record_net_worth(date(2026, 11, 1), 1000)
        self.store.record_net_worth(date(2026, 11, 2), 2000)
        self.store.record_net_worth(date(2026, 11, 2), 2500)  # same day replaces
        self.assertEqual(
            self.store.latest_snapshot_before(date(2026, 11, 2)), (date(2026, 11, 1), 1000)
        )
        self.assertEqual(self.store.net_worth_history()[-1], (date(2026, 11, 2), 2500))


class PersistenceTests(unittest.TestCase):
    def test_data_survives_reopening(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "nested", "finance.db")
            with Store(path) as store:
                store.create_profile("Sam")
                store.add_transaction(tx("Coffee", 450, "food", date(2026, 7, 1)))
            with Store(path) as store:  # reopening must not re-run migrations
                self.assertEqual(store.profile_name(), "Sam")
                self.assertEqual(store.transaction_count(), 1)


if __name__ == "__main__":
    unittest.main()
