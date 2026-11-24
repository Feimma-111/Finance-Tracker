"""Exercise the REST API end to end with FastAPI's test client."""

import os
import tempfile
import unittest
from datetime import date

try:
    from fastapi.testclient import TestClient

    from finance_tracker.api import create_app
except ImportError:  # web packages not installed; the terminal app still works
    TestClient = None

from tests.support import sign_in
from tests.test_prices import FakeProvider

TODAY = date(2026, 11, 22)


@unittest.skipIf(TestClient is None, "install requirements.txt to test the web API")
class ApiTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.provider = FakeProvider({"AAPL": 342.56, "GC=F": 3614.30})
        app = create_app(
            os.path.join(self.folder.name, "finance.db"),
            provider=self.provider,
            today=lambda: TODAY,
            static_dir=None,
        )
        self.client = TestClient(app)
        sign_in(self.client)

    def tearDown(self):
        self.client.close()
        self.folder.cleanup()

    def add_tx(self, **overrides):
        body = {"description": "Coffee", "amount": "4.50", "category": "Food",
                "occurred_on": "2026-11-01", "kind": "expense"}
        body.update(overrides)
        return self.client.post("/api/transactions", json=body)

    # ---------------------------------------------------------------- profile

    def test_profile_lifecycle(self):
        self.assertEqual(self.client.get("/api/profile").json(), {"name": None})
        self.assertEqual(self.client.post("/api/profile", json={"name": " Sam "}).status_code, 201)
        self.assertEqual(self.client.get("/api/profile").json(), {"name": "Sam"})
        self.assertEqual(self.client.post("/api/profile", json={"name": "Again"}).status_code, 409)
        self.assertEqual(self.client.post("/api/profile", json={"name": "   "}).status_code, 400)

    # ----------------------------------------------------------- transactions

    def test_add_list_delete_transactions(self):
        created = self.add_tx()
        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.json()["amount_cents"], 450)
        self.add_tx(description="Paycheck", amount="$1,000", category="Salary", kind="income")

        listing = self.client.get("/api/transactions").json()
        self.assertEqual(listing["total"], 2)
        self.assertEqual({t["description"] for t in listing["items"]}, {"Coffee", "Paycheck"})

        tx_id = created.json()["id"]
        self.assertEqual(self.client.delete(f"/api/transactions/{tx_id}").status_code, 204)
        self.assertEqual(self.client.delete(f"/api/transactions/{tx_id}").status_code, 404)

    def test_edit_transaction(self):
        rent = self.add_tx(description="Rent", amount="1450", category="Lifestyle").json()
        self.add_tx(description="rent ", amount="1450", category="Wants", occurred_on="2026-10-01")
        self.add_tx(description="Rent", amount="100", category="Wants", kind="income")  # different type

        got = self.client.get(f"/api/transactions/{rent['id']}").json()
        self.assertEqual(got["matching"], 1)  # the other expense named "rent"; not the income

        edited = self.client.patch(f"/api/transactions/{rent['id']}", json={
            "category": "Rent", "amount": "1,451.59", "occurred_on": "2026-11-03",
            "apply_category_to_matching": True,
        }).json()
        self.assertEqual(
            (edited["category"], edited["amount_cents"], edited["occurred_on"], edited["also_updated"]),
            ("Rent", 145159, "2026-11-03", 1),
        )
        cats = sorted((t["category"], t["kind"]) for t in self.client.get("/api/transactions").json()["items"])
        self.assertEqual(cats, [("Rent", "expense"), ("Rent", "expense"), ("Wants", "income")])

        # Only the fields sent change; bad values are refused with a message.
        self.assertEqual(self.client.patch(f"/api/transactions/{rent['id']}", json={"description": "Apartment"})
                         .json()["amount_cents"], 145159)
        for body, message in [({"amount": "0"}, "greater than zero"), ({"occurred_on": "2030-01-01"}, "future"),
                              ({"description": "  "}, "description")]:
            with self.subTest(body=body):
                response = self.client.patch(f"/api/transactions/{rent['id']}", json=body)
                self.assertEqual(response.status_code, 400)
                self.assertIn(message, response.json()["detail"])
        self.assertEqual(self.client.patch("/api/transactions/9999", json={"amount": "1"}).status_code, 404)

    def test_validation_errors_are_readable(self):
        cases = [
            ({"amount": "ten"}, "'ten' isn't a number"),
            ({"amount": "0"}, "greater than zero"),
            ({"occurred_on": "2027-01-01"}, "in the future"),
            ({"description": "  "}, "description"),
        ]
        for overrides, message in cases:
            with self.subTest(overrides=overrides):
                response = self.add_tx(**overrides)
                self.assertEqual(response.status_code, 400)
                self.assertIn(message, response.json()["detail"])

    def test_blank_date_means_today(self):
        self.assertEqual(self.add_tx(occurred_on="").json()["occurred_on"], "2026-11-22")

    def test_summary_months_and_reports(self):
        self.add_tx(amount="30", category="Groceries", occurred_on="2026-10-05")
        self.add_tx(amount="10", category="food")  # matches "Food" case-insensitively later
        self.add_tx(amount="5")
        self.add_tx(description="Paycheck", amount="100", category="Salary", kind="income")

        summary = self.client.get("/api/summary").json()
        self.assertEqual(
            (summary["month"], summary["spent_cents"], summary["income_cents"], summary["net_cents"]),
            ("2026-11", 1500, 10000, 8500),
        )
        self.assertEqual(self.client.get("/api/months").json(), ["2026-11", "2026-10"])

        report = self.client.get("/api/reports/categories", params={"month": "2026-11"}).json()
        self.assertEqual([(i["category"], i["total_cents"]) for i in report["items"]], [("food", 1500)])

        monthly = self.client.get("/api/reports/monthly").json()
        self.assertEqual([m["month"] for m in monthly["months"]], ["2026-10", "2026-11"])
        self.assertTrue(monthly["months"][-1]["in_progress"])

        self.assertEqual(self.client.get("/api/summary", params={"month": "nope"}).status_code, 400)

    def test_purchases_report(self):
        self.add_tx(description="Boba", amount="6", occurred_on="2026-11-02")
        self.add_tx(description="boba ", amount="7", occurred_on="2026-11-09")  # same place, messier spelling
        self.add_tx(description="Lunch", amount="20", occurred_on="2026-11-05")
        self.add_tx(description="Boba", amount="5", occurred_on="2026-10-30")  # another month
        self.add_tx(description="Bus", amount="3", category="Transport", occurred_on="2026-11-05")
        self.add_tx(description="Boba", amount="99", kind="income", category="Food", occurred_on="2026-11-06")

        report = self.client.get("/api/reports/purchases", params={"category": "food", "month": "2026-11"}).json()
        self.assertEqual((report["category"], report["total_cents"], report["count"]), ("Food", 3300, 3))
        self.assertEqual(
            [(i["description"], i["count"], i["total_cents"]) for i in report["items"]],
            [("Lunch", 1, 2000), ("boba", 2, 1300)],  # spelled like the newest one
        )
        self.assertAlmostEqual(report["items"][0]["share"], 2000 / 3300)
        everything = self.client.get("/api/reports/purchases", params={"category": "Food"}).json()
        self.assertEqual(everything["total_cents"], 3800)
        self.assertEqual(self.client.get("/api/reports/purchases", params={"category": "Nope"}).status_code, 404)

    def test_spending_pace(self):
        self.add_tx(amount="100", occurred_on="2026-10-02")
        self.add_tx(amount="50", occurred_on="2026-10-20")
        self.add_tx(amount="1450", category="Rent", occurred_on="2026-11-01")
        self.add_tx(amount="30", occurred_on="2026-11-05")
        self.add_tx(amount="20", occurred_on="2026-11-05")
        self.add_tx(description="Pay", amount="999", category="Salary", kind="income", occurred_on="2026-11-06")

        pace = self.client.get("/api/reports/pace").json()  # Nov 22, in progress
        self.assertEqual((pace["month"], pace["through_day"], pace["in_progress"]), ("2026-11", 22, True))
        self.assertEqual(len(pace["this_month"]), 22)
        self.assertEqual(pace["this_month"][4], {"day": 5, "cumulative_cents": 150000})  # 1450 + 30 + 20
        self.assertEqual(len(pace["last_month"]), 31)
        self.assertEqual(pace["last_month_same_point_cents"], 15000)  # Oct 1-22: $100 + $50
        self.assertEqual(pace["difference_cents"], 150000 - 15000)
        self.assertFalse(pace["controlled"])

        # Mark rent as covered: it drops out of the running total.
        self.client.put("/api/settings", json={"covered_categories": ["Rent"]})
        controlled = self.client.get("/api/reports/pace").json()
        self.assertTrue(controlled["controlled"])
        self.assertEqual(controlled["spent_cents"], 5000)
        everything = self.client.get("/api/reports/pace", params={"controlled": "false"}).json()
        self.assertEqual(everything["spent_cents"], 150000)

        october = self.client.get("/api/reports/pace", params={"month": "2026-10"}).json()
        self.assertEqual((october["through_day"], october["spent_cents"], october["in_progress"]), (31, 15000, False))

        # Only some categories: covered ones count when you pick them yourself.
        rent = self.client.get("/api/reports/pace", params={"category": ["rent"]}).json()
        self.assertEqual((rent["categories"], rent["spent_cents"], rent["controlled"]), (["Rent"], 145000, False))
        both = self.client.get("/api/reports/pace", params={"category": ["Rent", "Food"]}).json()
        self.assertEqual((both["spent_cents"], both["last_month_same_point_cents"]), (150000, 15000))
        self.assertEqual(self.client.get("/api/reports/pace", params={"category": ["Nope"]}).status_code, 400)

    def test_csv_export(self):
        self.add_tx()
        response = self.client.get("/api/transactions.csv")
        self.assertEqual(response.status_code, 200)
        self.assertIn("attachment", response.headers["content-disposition"])
        self.assertIn("2026-11-01,expense,Food,Coffee,4.50", response.text)

    # --------------------------------------------------- holdings / net worth

    def test_holdings_and_net_worth(self):
        post = lambda body: self.client.post("/api/holdings", json=body)
        self.assertEqual(post({"asset_type": "cash", "name": "Checking", "value": "1500"}).status_code, 201)
        stock = post({"asset_type": "stock", "symbol": "aapl", "quantity": 2.5}).json()
        self.assertEqual((stock["symbol"], stock["name"]), ("AAPL", "AAPL"))
        self.assertEqual(post({"asset_type": "gold", "quantity": 0.1}).status_code, 201)
        self.assertEqual(post({"asset_type": "stock", "symbol": "", "quantity": 1}).status_code, 400)
        self.assertEqual(post({"asset_type": "cash", "name": "x"}).status_code, 400)  # no value

        worth = self.client.get("/api/net-worth").json()
        self.assertEqual(worth["total_cents"], 150000 + 85640 + 36143)
        self.assertTrue(worth["complete"])
        self.assertEqual([t["asset_type"] for t in worth["by_type"]], ["cash", "stock", "gold"])
        self.assertEqual(
            self.client.get("/api/net-worth/history").json(),
            [{"date": "2026-11-22", "total_cents": 271783}],
        )

        updated = self.client.patch(f"/api/holdings/{stock['id']}", json={"quantity": 10})
        self.assertEqual(updated.json()["quantity"], 10)
        renamed = self.client.patch(f"/api/holdings/{stock['id']}", json={"name": "Apple Inc.", "symbol": "aapl"}).json()
        self.assertEqual((renamed["name"], renamed["symbol"], renamed["quantity"]), ("Apple Inc.", "AAPL", 10))
        cash_id = next(h["id"] for h in self.client.get("/api/holdings").json() if h["asset_type"] == "cash")
        self.assertEqual(self.client.patch(f"/api/holdings/{cash_id}", json={"symbol": "X"}).status_code, 400)
        self.assertEqual(self.client.patch(f"/api/holdings/{cash_id}", json={"name": " "}).status_code, 400)
        self.assertEqual(self.client.patch(f"/api/holdings/{cash_id}", json={"name": "Savings", "value": "2000"})
                         .json()["manual_value_cents"], 200000)
        self.assertEqual(self.client.patch(f"/api/holdings/{stock['id']}", json={"quantity": -1}).status_code, 400)
        self.assertEqual(self.client.delete(f"/api/holdings/{stock['id']}").status_code, 204)
        self.assertEqual(len(self.client.get("/api/holdings").json()), 2)

    def test_unpriceable_holding_skips_snapshot(self):
        self.client.post("/api/holdings", json={"asset_type": "stock", "symbol": "GONE", "quantity": 1})
        worth = self.client.get("/api/net-worth").json()
        self.assertFalse(worth["complete"])
        self.assertIn("no market data", worth["lines"][0]["note"])
        self.assertEqual(self.client.get("/api/net-worth/history").json(), [])

    # ------------------------------------------------- recurring / settings

    def test_recurring_rules(self):
        body = {"description": "Rent", "amount": "1250", "category": "Housing",
                "frequency": "monthly", "start_on": "2026-10-01"}
        created = self.client.post("/api/recurring", json=body)
        self.assertEqual(created.status_code, 201)
        rule = created.json()
        self.assertEqual((rule["created"], rule["next_due"]), (2, "2026-12-01"))  # Oct + Nov added

        items = self.client.get("/api/transactions").json()["items"]
        self.assertEqual(len(items), 2)
        self.assertTrue(all(t["recurring_id"] == rule["id"] for t in items))

        paused = self.client.patch(f"/api/recurring/{rule['id']}", json={"active": False}).json()
        self.assertFalse(paused["active"])
        raised = self.client.patch(f"/api/recurring/{rule['id']}", json={"amount": "1300"}).json()
        self.assertEqual(raised["amount_cents"], 130000)
        self.assertEqual(self.client.patch(f"/api/recurring/{rule['id']}", json={"amount": "-5"}).status_code, 400)

        self.assertEqual(self.client.delete(f"/api/recurring/{rule['id']}").status_code, 204)
        self.assertEqual(self.client.get("/api/recurring").json(), [])
        self.assertEqual(len(self.client.get("/api/transactions").json()["items"]), 2)  # history kept

    def test_recurring_validation(self):
        bad = {"description": "Gym", "amount": "40", "category": "Health",
               "frequency": "monthly", "start_on": "2030-01-01"}
        self.assertEqual(self.client.post("/api/recurring", json=bad).status_code, 400)
        bad.update(start_on="", frequency="hourly")
        self.assertEqual(self.client.post("/api/recurring", json=bad).status_code, 422)

    def test_due_rules_are_caught_up_on_any_request(self):
        state = {"today": TODAY}
        app = create_app(
            os.path.join(self.folder.name, "catchup.db"),
            provider=self.provider,
            today=lambda: state["today"],
            static_dir=None,
        )
        with TestClient(app) as client:
            sign_in(client)
            client.post("/api/recurring", json={
                "description": "Spotify", "amount": "11.99", "category": "Subscriptions",
                "frequency": "monthly", "start_on": "2026-12-05",
            })
            self.assertEqual(client.get("/api/transactions").json()["total"], 0)
            state["today"] = date(2027, 2, 10)  # app wasn't opened for a while
            self.assertEqual(client.get("/api/profile").status_code, 200)  # any request
            self.assertEqual(client.get("/api/transactions").json()["total"], 3)  # Dec, Jan, Feb

    def test_settings_and_rename(self):
        self.assertEqual(self.client.get("/api/settings").json()["theme"], "system")
        self.assertEqual(self.client.put("/api/settings", json={"theme": "dark"}).json()["theme"], "dark")
        self.assertEqual(self.client.get("/api/settings").json()["theme"], "dark")
        self.assertEqual(self.client.put("/api/settings", json={"theme": "purple"}).status_code, 422)

        self.assertEqual(self.client.put("/api/profile", json={"name": "Sam"}).status_code, 404)
        self.client.post("/api/profile", json={"name": "Sam"})
        self.assertEqual(self.client.put("/api/profile", json={"name": "Pete"}).json(), {"name": "Pete"})
        self.assertEqual(self.client.get("/api/profile").json(), {"name": "Pete"})

    def test_quotes(self):
        self.assertEqual(self.client.get("/api/quotes/aapl").json()["price"], 342.56)
        self.assertEqual(self.client.get("/api/quotes/NOPE").status_code, 404)


if __name__ == "__main__":
    unittest.main()


@unittest.skipIf(TestClient is None, "install requirements.txt to test the web API")
class AccountsAndPortfolioTests(unittest.TestCase):
    """Cash accounts that follow transactions, what investments cost, and gains."""

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        # Fri Nov 20 is the last close before Sat Nov 22.
        self.provider = FakeProvider(
            {"AAPL": 125.0},
            histories={"AAPL": [(date(2026, 10, 22), 100.0), (date(2026, 11, 13), 110.0),
                                (date(2026, 11, 20), 120.0)]},
        )
        app = create_app(os.path.join(self.folder.name, "finance.db"), provider=self.provider,
                         today=lambda: TODAY, static_dir=None)
        self.client = TestClient(app)
        sign_in(self.client)

    def tearDown(self):
        self.client.close()
        self.folder.cleanup()

    def test_cash_accounts_follow_linked_transactions(self):
        c = self.client
        checking = c.post("/api/holdings", json={"asset_type": "cash", "name": "Checking", "value": "1,000"}).json()
        self.assertEqual(checking["balance_as_of"], TODAY.isoformat())
        c.post("/api/holdings", json={"asset_type": "cash", "name": "Savings", "value": "5000"})
        add = lambda **kw: c.post("/api/transactions", json={  # noqa: E731
            "description": "Lunch", "amount": "25.50", "category": "Food", "occurred_on": TODAY.isoformat(), **kw})
        lunch = add(account_id=checking["id"]).json()
        self.assertEqual(lunch["account_id"], checking["id"])
        add(description="Paycheck", amount="400", kind="income", category="Salary", account_id=checking["id"])
        add(description="Rent (paid by family)", amount="1200")  # not from my accounts
        self.assertEqual(add(account_id=999).status_code, 400)

        worth = c.get("/api/net-worth").json()
        self.assertEqual(worth["liquid_cents"], 100000 - 2550 + 40000 + 500000)
        line = next(l for l in worth["lines"] if l["name"] == "Checking")
        self.assertEqual((line["value_cents"], line["balance_change_cents"]), (137450, 37450))

        # Unlinking a transaction takes it out again; leaving account_id out keeps it.
        c.patch(f"/api/transactions/{lunch['id']}", json={"description": "Big lunch"})
        self.assertEqual(c.get(f"/api/transactions/{lunch['id']}").json()["account_id"], checking["id"])
        c.patch(f"/api/transactions/{lunch['id']}", json={"account_id": None})
        self.assertEqual(c.get("/api/net-worth").json()["liquid_cents"], 100000 + 40000 + 500000)

        # A new balance starts over from now.
        c.patch(f"/api/holdings/{checking['id']}", json={"value": "1500"})
        self.assertEqual(c.get("/api/net-worth").json()["liquid_cents"], 150000 + 500000)

        stock = c.post("/api/holdings", json={"asset_type": "stock", "symbol": "AAPL", "quantity": 1}).json()
        self.assertEqual(add(account_id=stock["id"]).status_code, 400)  # not a cash account

    def test_recurring_rules_use_the_account(self):
        checking = self.client.post("/api/holdings", json={"asset_type": "cash", "name": "Checking", "value": "100"}).json()
        rule = self.client.post("/api/recurring", json={
            "description": "Phone", "amount": "45", "category": "Utilities", "frequency": "monthly",
            "start_on": TODAY.isoformat(), "account_id": checking["id"]}).json()
        self.assertEqual(rule["account_id"], checking["id"])
        self.assertEqual(self.client.get("/api/net-worth").json()["liquid_cents"], 10000 - 4500)

    def test_investment_costs_and_gains(self):
        c = self.client
        apple = c.post("/api/holdings", json={
            "asset_type": "stock", "symbol": "aapl", "quantity": 10, "bought_on": "2026-01-05", "avg_price": "$80"}).json()
        self.assertEqual((apple["bought_on"], apple["cost_basis_cents"]), ("2026-01-05", 80000))
        self.assertEqual(c.post("/api/holdings", json={
            "asset_type": "stock", "symbol": "X", "quantity": 1, "avg_price": "lots"}).status_code, 400)
        self.assertEqual(c.post("/api/holdings", json={
            "asset_type": "stock", "symbol": "X", "quantity": 1, "bought_on": "2030-01-01"}).status_code, 400)

        report = c.get("/api/portfolio", params={"period": "1M"}).json()  # since Oct 22: $100
        self.assertEqual(report["value_cents"], 125000)
        self.assertEqual(report["total"], {"change_cents": 45000, "pct": 56.2})
        self.assertEqual(report["period_change"], {"change_cents": 25000, "pct": 25.0})
        self.assertEqual(report["today"], {"change_cents": 5000, "pct": 4.2})
        row = report["holdings"][0]
        self.assertEqual(row["avg_price"], 80.0)
        self.assertEqual(report["series"][-1], {"date": TODAY.isoformat(), "value_cents": 125000})
        self.assertEqual(report["series"][0], {"date": "2026-10-22", "value_cents": 100000})
        self.assertEqual(c.get("/api/portfolio", params={"period": "5Y"}).status_code, 400)

        # History is cached: a second report doesn't fetch it again.
        calls = self.provider.history_calls
        c.get("/api/portfolio", params={"period": "1W"})
        self.assertEqual(self.provider.history_calls, calls)

        # Selling half keeps the average price; clearing removes the cost.
        half = c.patch(f"/api/holdings/{apple['id']}", json={"quantity": 5}).json()
        self.assertEqual(half["cost_basis_cents"], 40000)
        cleared = c.patch(f"/api/holdings/{apple['id']}", json={"avg_price": "", "bought_on": ""}).json()
        self.assertEqual((cleared["cost_basis_cents"], cleared["bought_on"]), (None, None))
        self.assertIsNone(c.get("/api/portfolio").json()["total"])
