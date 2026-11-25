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


class AccountAndHistoryTests(unittest.TestCase):
    """Schema v5: cash accounts that follow linked transactions, costs, price history."""

    def setUp(self):
        self.store = Store(":memory:")

    def tearDown(self):
        self.store.close()

    def test_account_changes_count_linked_transactions_after_the_check(self):
        s = self.store
        checking = s.add_holding(Holding(AssetType.CASH, "Checking", manual_value_cents=100000,
                                         balance_as_of=date(2026, 11, 20)))
        other = s.add_holding(Holding(AssetType.CASH, "Cash jar", manual_value_cents=5000))  # never checked
        add = lambda desc, cents, day, kind=Kind.EXPENSE, account=checking: s.add_transaction(  # noqa: E731
            Transaction(desc, cents, "Food", day, kind, account_id=account))
        add("Before the check", 999, date(2026, 11, 20))             # added after, but dated that day
        add("Back-dated", 888, date(2026, 11, 19))                   # already in the bank's balance
        add("Lunch", 1500, date(2026, 11, 21))
        add("Paycheck", 50000, date(2026, 11, 22), Kind.INCOME)
        add("Next week", 2000, date(2026, 11, 30))                   # not yet
        add("Not linked", 700, date(2026, 11, 21), account=None)
        add("Jar", 300, date(2026, 11, 21), account=other)            # its account has no check date
        self.assertEqual(s.account_changes(date(2026, 11, 23)), {checking: 48500 - 999})

        # Updating the balance starts over from now: earlier entries are in it.
        s.update_holding(checking, manual_value_cents=150000, balance_as_of=date(2026, 11, 22))
        self.assertEqual(s.account_changes(date(2026, 11, 23)), {})
        add("Same-day coffee", 450, date(2026, 11, 22))              # logged after the update
        self.assertEqual(s.account_changes(date(2026, 11, 23)), {checking: -450})
        self.assertTrue(s.is_cash_account(checking))
        stock = s.add_holding(Holding(AssetType.STOCK, "Apple", 1, symbol="AAPL"))
        self.assertFalse(s.is_cash_account(stock))

        # Removing an account keeps its transactions, unlinked.
        s.remove_holding(checking)
        self.assertTrue(all(t.account_id is None for t in s.transactions() if t.description != "Jar"))

    def test_holding_costs_round_trip_and_clear(self):
        s = self.store
        hid = s.add_holding(Holding(AssetType.STOCK, "Apple", 10, symbol="AAPL",
                                    bought_on=date(2025, 3, 10), cost_basis_cents=210000))
        h = s.get_holding(hid)
        self.assertEqual((h.bought_on, h.cost_basis_cents), (date(2025, 3, 10), 210000))
        s.update_holding(hid, clear=["bought_on", "cost_basis_cents"])
        h = s.get_holding(hid)
        self.assertEqual((h.bought_on, h.cost_basis_cents), (None, None))
        with self.assertRaises(ValueError):
            s.update_holding(hid, clear=["name"])

    def test_price_history_round_trip(self):
        when = datetime(2026, 11, 23, 12, 0, tzinfo=timezone.utc)
        self.store.save_price_history("aapl", [(date(2026, 11, 20), 120.0), (date(2026, 11, 19), 118.5)], "USD", when)
        self.store.save_price_history("AAPL", [(date(2026, 11, 20), 121.0)], "USD", when)  # corrected close
        self.assertEqual(self.store.price_history("AAPL"),
                         [(date(2026, 11, 19), 118.5), (date(2026, 11, 20), 121.0)])
        self.assertEqual(self.store.price_history_fetched("AAPL"), (when, "USD"))

    def test_recurring_rules_keep_their_account(self):
        from finance_tracker.models import Frequency, RecurringRule
        s = self.store
        account = s.add_holding(Holding(AssetType.CASH, "Checking", manual_value_cents=0, balance_as_of=date(2026, 1, 1)))
        s.add_recurring(RecurringRule("Phone", 4500, "Utilities", Frequency.MONTHLY, date(2026, 9, 5),
                                      account_id=account))
        s.apply_recurring(date(2026, 11, 23))
        self.assertEqual({t.account_id for t in s.transactions()}, {account})
        self.assertEqual(s.account_changes(date(2026, 11, 23)), {account: -13500})


class UpgradeTests(unittest.TestCase):
    def test_version_4_database_upgrades_with_data_intact(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "finance.db")
            conn = sqlite3.connect(path)
            for version, script in enumerate(MIGRATIONS[:4], start=1):
                conn.executescript(f"BEGIN;\n{script}\nPRAGMA user_version = {version};\nCOMMIT;")
            conn.execute("INSERT INTO categories (name) VALUES ('Food')")
            conn.execute("INSERT INTO transactions (description, amount_cents, kind, category_id, occurred_on) "
                         "VALUES ('Lunch', 1200, 'expense', 1, '2026-11-02')")
            conn.execute("INSERT INTO holdings (asset_type, name, quantity, manual_value_cents) "
                         "VALUES ('cash', 'Checking', 1, 250000)")
            conn.commit()
            conn.close()

            store = Store(path)
            try:
                self.assertEqual(store.conn.execute("PRAGMA user_version").fetchone()[0], len(MIGRATIONS))
                (lunch,) = store.transactions()
                self.assertEqual((lunch.description, lunch.account_id), ("Lunch", None))
                (checking,) = store.holdings()
                self.assertEqual((checking.manual_value_cents, checking.balance_as_of), (250000, None))
            finally:
                store.close()
            # The upgrade made a safety backup first.
            self.assertTrue(os.listdir(os.path.join(folder, "backups")))


class SuggestCategoryTests(unittest.TestCase):
    def setUp(self):
        self.store = Store(":memory:")
        add = lambda desc, cat, kind=Kind.EXPENSE, day=1: self.store.add_transaction(  # noqa: E731
            Transaction(desc, 500, cat, date(2026, 11, day), kind))
        add("Boba", "Food", day=1)
        add("boba ", "Food", day=2)
        add("Boba", "Treats", day=3)       # less common
        add("Uber to airport", "Transport")
        add("Paycheck", "Salary", Kind.INCOME)
        add("Bobatime cafe", "Coffee")    # contains "boba" inside a word, not as one

    def tearDown(self):
        self.store.close()

    def test_same_description_wins(self):
        self.assertEqual(self.store.suggest_category("  BOBA "),
                         {"category": "Food", "count": 2, "match": "same"})

    def test_a_shared_word(self):
        self.assertEqual(self.store.suggest_category("Boba Guys")["category"], "Food")
        self.assertEqual(self.store.suggest_category("uber home"),
                         {"category": "Transport", "count": 1, "match": "similar"})

    def test_no_suggestion(self):
        self.assertIsNone(self.store.suggest_category("Dentist"))
        self.assertIsNone(self.store.suggest_category("b"))
        self.assertIsNone(self.store.suggest_category("Paycheck"))  # only used for income
        self.assertEqual(self.store.suggest_category("paycheck", Kind.INCOME)["category"], "Salary")
        self.assertIsNone(self.store.suggest_category("50% off"))  # wildcards don't match everything
