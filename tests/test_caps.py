"""Monthly spending caps per category: status, currencies, the API, and the AI's facts."""

import os
import tempfile
import unittest
from datetime import date

from finance_tracker.analyst import focus_facts, month_facts
from finance_tracker.models import Kind, Transaction
from finance_tracker.reports import CapStatus, cap_statuses, month_share
from finance_tracker.store import Store

try:
    from fastapi.testclient import TestClient

    from finance_tracker.api import create_app
except ImportError:
    TestClient = None

from tests.support import sign_in
from tests.test_prices import FakeProvider

TODAY = date(2026, 11, 22)


class CapMathTests(unittest.TestCase):
    def test_status(self):
        self.assertEqual(CapStatus("Food", 20000, 26091, 0.7).status, "over")
        self.assertEqual(CapStatus("Food", 20000, 18000, 0.7).status, "near")  # 90%
        self.assertEqual(CapStatus("Food", 20000, 17999, 0.7).status, "ok")
        self.assertEqual(CapStatus("Food", 20000, 26091, 0.7).left_cents, -6091)

    def test_month_share(self):
        self.assertAlmostEqual(month_share("2026-11", "2026-11-15"), 0.5)
        self.assertEqual(month_share("2026-10", "2026-11-15"), 1.0)
        self.assertEqual(month_share("2026-12", "2026-11-15"), 0.0)

    def test_caps_in_another_currency_and_order(self):
        caps = [("Food", 20000, "USD"), ("Boba", 320000, "TWD"), ("Gifts", 5000, "EUR")]
        rates = {"USD": 1.0, "TWD": 32.0}  # no EUR rate: that cap is left out
        result = cap_statuses(caps, {"Food": 10000, "Boba": 9000}, rates.get, 0.5)
        self.assertEqual([(c.category, c.cap_cents, c.spent_cents) for c in result],
                         [("Boba", 10000, 9000), ("Food", 20000, 10000)])  # most used first


class CapStoreAndFactsTests(unittest.TestCase):
    def setUp(self):
        self.store = Store(":memory:")
        s = self.store
        s.add_transaction(Transaction("Boba", 2600, "Food", date(2026, 11, 3)))
        s.add_transaction(Transaction("Dinner", 4000, "Food", date(2026, 11, 9)))
        s.add_transaction(Transaction("Groceries", 9000, "Groceries", date(2026, 11, 5)))

    def tearDown(self):
        self.store.close()

    def test_set_change_and_remove(self):
        s = self.store
        s.set_cap("food", 5000)
        s.set_cap("Groceries", 20000)
        s.set_cap("Food", 6000)  # change it
        self.assertEqual(s.caps(), [("Food", 6000, "USD"), ("Groceries", 20000, "USD")])
        s.set_cap("Groceries", None)
        self.assertEqual(s.caps(), [("Food", 6000, "USD")])
        with self.assertRaises(ValueError):
            s.set_cap("Nope", 100)
        with self.assertRaises(ValueError):
            s.set_cap("Food", 0)

    def test_facts_mention_caps(self):
        self.store.set_cap("Food", 5000)
        self.store.set_cap("Groceries", 20000)
        facts = month_facts(self.store, "2026-11", TODAY)
        self.assertIn("Spending caps you set (worked out by the app):", facts)
        self.assertIn("- Food: $66.00 of a $50.00 monthly cap (132%), over by $16.00", facts)
        self.assertIn("- Groceries: $90.00 of a $200.00 monthly cap (45%), $110.00 left", facts)
        focus = focus_facts(self.store, "2026-11", ["Food"], TODAY)
        self.assertIn("- Food: $66.00 of a $50.00 monthly cap (132%), over by $16.00", focus)
        self.assertNotIn("Groceries", focus)  # only the categories asked about


@unittest.skipIf(TestClient is None, "install requirements.txt to test the web API")
class CapApiTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        app = create_app(os.path.join(self.folder.name, "finance.db"), provider=FakeProvider({"TWD=X": 32.0}),
                         today=lambda: TODAY, static_dir=None)
        self.client = TestClient(app)
        sign_in(self.client)
        for desc, amount, category in [("Boba", "26", "Food"), ("Dinner", "40", "Food"), ("Bus", "3", "Transport")]:
            self.client.post("/api/transactions", json={
                "description": desc, "amount": amount, "category": category, "occurred_on": "2026-11-10"})

    def tearDown(self):
        self.client.close()
        self.folder.cleanup()

    def test_caps(self):
        c = self.client
        result = c.put("/api/caps", json={"caps": [{"category": "food", "amount": "50"},
                                                   {"category": "Transport", "amount": "100"}]}).json()
        food, transport = result["caps"]
        self.assertEqual((food["category"], food["status"], food["spent_cents"], food["left_cents"]),
                         ("Food", "over", 6600, -1600))
        self.assertEqual((transport["status"], transport["left_cents"]), ("ok", 9700))
        self.assertAlmostEqual(result["month_share"], 22 / 30)

        # In NT$: NT$1,600 at 32 per dollar is a $50 cap.
        twd = c.put("/api/caps", json={"caps": [{"category": "Food", "amount": "1,600"}], "currency": "TWD"}).json()
        food = next(x for x in twd["caps"] if x["category"] == "Food")
        self.assertEqual((food["cap_cents"], food["set_cents"], food["set_currency"]), (5000, 160000, "TWD"))

        c.put("/api/caps", json={"caps": [{"category": "Transport", "amount": None}]})
        self.assertEqual([x["category"] for x in c.get("/api/caps").json()["caps"]], ["Food"])
        october = c.get("/api/caps", params={"month": "2026-10"}).json()
        self.assertEqual((october["month_share"], october["caps"][0]["spent_cents"]), (1.0, 0))

        self.assertEqual(c.put("/api/caps", json={"caps": [{"category": "Nope", "amount": "5"}]}).status_code, 400)
        self.assertEqual(c.put("/api/caps", json={"caps": [{"category": "Food", "amount": "0"}]}).status_code, 400)
        self.assertEqual(c.put("/api/caps", json={"caps": [], "currency": "XYZ"}).status_code, 400)


if __name__ == "__main__":
    unittest.main()
