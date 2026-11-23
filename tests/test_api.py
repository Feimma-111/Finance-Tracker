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
