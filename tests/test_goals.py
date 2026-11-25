"""Savings goals, your pay, and the AI's savings check."""

import os
import tempfile
import unittest
from datetime import date

from finance_tracker.analyst import Review, savings_facts
from finance_tracker.models import AssetType, Holding, Kind, SavingsGoal, Transaction
from finance_tracker.prices import PriceService
from finance_tracker.reports import GoalPlan, monthly_pay_cents
from finance_tracker.store import Store

try:
    from fastapi.testclient import TestClient

    from finance_tracker.api import create_app
except ImportError:
    TestClient = None

from tests.support import sign_in
from tests.test_prices import FakeProvider

TODAY = date(2026, 11, 22)


class GoalMathTests(unittest.TestCase):
    def test_per_month(self):
        plan = GoalPlan("Japan", 150000, 60000, date(2027, 5, 22), TODAY)  # 181 days away
        self.assertEqual((plan.left_cents, round(plan.share, 2)), (90000, 0.4))
        self.assertAlmostEqual(plan.months_left, 5.95, delta=0.01)
        self.assertEqual(plan.per_month_cents, 15135)  # $900 over 5.95 months
        self.assertIsNone(GoalPlan("Fund", 100000, 0, None, TODAY).per_month_cents)
        self.assertEqual(GoalPlan("Late", 100000, 40000, date(2026, 11, 1), TODAY).per_month_cents, 60000)
        self.assertEqual(GoalPlan("Done", 100000, 120000, date(2027, 1, 1), TODAY).per_month_cents, 0)

    def test_take_home_pay(self):
        # $18.50 x 20 hours x 52 weeks / 12 = $1,603.33 a month, minus 7% tax = $1,491.10
        self.assertEqual(monthly_pay_cents(1850, 20, 7), 149110)
        self.assertEqual(monthly_pay_cents(1850, 20), 160333)


class SavingsFactsTests(unittest.TestCase):
    def setUp(self):
        self.store = Store(":memory:")
        s = self.store
        for month in (8, 9, 10):
            s.add_transaction(Transaction("Paycheck", 150000, "Salary", date(2026, month, 1), Kind.INCOME))
            s.add_transaction(Transaction("Food", 40000, "Food", date(2026, month, 5)))
            s.add_transaction(Transaction("Rent", 120000, "Housing", date(2026, month, 1)))  # covered
        s.set_setting("covered_categories", '["Housing"]')
        s.set_setting("covered_note", "Family pays")
        s.set_setting("income_hourly_cents", "1850")
        s.set_setting("income_hours_per_week", "20")
        s.set_setting("income_tax_pct", "7")
        savings = s.add_holding(Holding(AssetType.CASH, "Savings", manual_value_cents=60000, balance_as_of=TODAY))
        s.add_goal(SavingsGoal("Japan trip", 150000, target_date=date(2027, 5, 22), account_id=savings))
        s.add_goal(SavingsGoal("Laptop", 120000, saved_cents=20000))

    def tearDown(self):
        self.store.close()

    def test_numbers_are_worked_out(self):
        facts = savings_facts(self.store, PriceService(self.store, FakeProvider({})), TODAY)
        self.assertIn("Your pay: $18.50 an hour, about 20 hours a week, with about 7% taken out for taxes. "
                      "That's about $1,491.10 a month take-home ($17.21 an hour after tax).", facts)
        self.assertIn("Income recorded in the last 3 complete month(s): Aug $1,500.00, Sep $1,500.00, "
                      "Oct $1,500.00; average $1,500.00.", facts)
        self.assertIn("Spending you control in those months: average $400.00 (costs covered by someone else "
                      "-- Housing -- left out).", facts)
        self.assertIn("- From recorded income: $1,100.00 on average", facts)
        self.assertIn("- From your pay estimate: $1,091.10", facts)
        self.assertIn("Cash in your accounts right now: $600.00.", facts)
        self.assertIn("- Japan trip: $600.00 of $1,500.00 saved (40%), $900.00 to go, by May 22, 2027: "
                      "$151.35 a month (about 8.8 hours of work a month)", facts)
        self.assertIn("- Laptop: $200.00 of $1,200.00 saved (17%), $1,000.00 to go, no date set", facts)
        self.assertIn("Goals with dates need $151.35 a month together: 14% of what's left over each month.", facts)

    def test_without_pay_set(self):
        self.store.set_setting("income_hourly_cents", "")
        facts = savings_facts(self.store, PriceService(self.store, FakeProvider({})), TODAY)
        self.assertIn("Your hourly pay isn't set in Settings", facts)
        self.assertNotIn("hours of work", facts)


class FakeAI:
    sent = []

    def __init__(self, url):
        pass

    def models(self):
        return ["qwen3.5:latest"]

    def savings_review(self, model, facts):
        FakeAI.sent.append(facts)
        return {"headline": "You can save about $1,100 a month.", "can_save": ["a"], "goals": ["b"], "ideas": ["c"]}

    def review(self, model, facts, focus=False):
        return Review("h", ["o"], ["s"])

    def chat(self, model, messages, tools):
        FakeAI.sent.append(messages)
        return {"content": "The Japan trip needs $151.35 a month."}


@unittest.skipIf(TestClient is None, "install requirements.txt to test the web API")
class GoalApiTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        app = create_app(os.path.join(self.folder.name, "finance.db"), provider=FakeProvider({"TWD=X": 32.0}),
                         today=lambda: TODAY, static_dir=None, ai_client_factory=FakeAI)
        self.client = TestClient(app)
        sign_in(self.client)
        FakeAI.sent = []

    def tearDown(self):
        self.client.close()
        self.folder.cleanup()

    def test_goals(self):
        c = self.client
        savings = c.post("/api/holdings", json={"asset_type": "cash", "name": "Savings", "value": "400"}).json()
        trip = c.post("/api/goals", json={"name": "Japan trip", "target": "1,500", "target_date": "2027-05-22",
                                          "account_id": savings["id"]}).json()
        self.assertEqual((trip["saved_cents"], trip["left_cents"], trip["account_name"]), (40000, 110000, "Savings"))
        self.assertEqual(trip["per_month_cents"], 18498)  # $1,100 over 5.95 months
        # A goal in NT$ with an amount set aside by hand: NT$9,600 of NT$32,000 at 32 per dollar.
        laptop = c.post("/api/goals", json={"name": "Laptop", "target": "32000", "currency": "TWD", "saved": "9600"}).json()
        self.assertEqual((laptop["target_cents"], laptop["saved_cents"], laptop["per_month_cents"]), (100000, 30000, None))

        moved = c.put(f"/api/goals/{laptop['id']}", json={"name": "Laptop", "target": "32000", "currency": "TWD",
                                                          "saved": "16000", "target_date": "2027-01-22"}).json()
        self.assertEqual((moved["saved_cents"], moved["target_date"]), (50000, "2027-01-22"))
        self.assertEqual([g["name"] for g in c.get("/api/goals").json()], ["Laptop", "Japan trip"])  # soonest first

        for bad in [{"name": "", "target": "5"}, {"name": "X", "target": "0"}, {"name": "X", "target": "5", "currency": "XYZ"},
                    {"name": "X", "target": "5", "account_id": 999}]:
            self.assertEqual(c.post("/api/goals", json=bad).status_code, 400)
        self.assertEqual(c.delete(f"/api/goals/{laptop['id']}").status_code, 204)
        self.assertEqual(c.delete(f"/api/goals/{laptop['id']}").status_code, 404)
        self.assertEqual(c.put("/api/goals/999", json={"name": "X", "target": "5"}).status_code, 404)

    def test_income_settings_and_savings_check(self):
        c = self.client
        income = c.put("/api/settings", json={"income_hourly": "18.50", "income_hours_per_week": 20,
                                              "income_tax_pct": 7}).json()["income"]
        self.assertEqual((income["hourly_cents"], income["hours_per_week"], income["monthly_cents"]), (1850, 20, 149110))
        self.assertEqual(c.put("/api/settings", json={"income_hourly": "lots"}).status_code, 400)
        self.assertEqual(c.put("/api/settings", json={"income_tax_pct": 99}).status_code, 422)

        self.assertEqual(c.post("/api/ai/savings").status_code, 400)  # AI not set up
        c.put("/api/settings", json={"ai_url": "http://pc:11434"})
        check = c.post("/api/ai/savings").json()
        self.assertEqual(check["review"]["headline"], "You can save about $1,100 a month.")
        self.assertIn("Your pay: $18.50 an hour", check["facts"])

        follow_up = c.post("/api/ai/ask", json={"question": "How long for Japan?", "savings": True})
        self.assertEqual(follow_up.status_code, 200)
        self.assertIn("Your pay: $18.50 an hour", FakeAI.sent[-1][1]["content"])

        cleared = c.put("/api/settings", json={"income_hourly": ""}).json()["income"]
        self.assertEqual((cleared["hourly_cents"], cleared["monthly_cents"]), (None, None))


if __name__ == "__main__":
    unittest.main()
