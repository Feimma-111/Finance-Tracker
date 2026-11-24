"""Money in more than one currency, transfers between your own accounts, travel mode."""

import os
import tempfile
import unittest
from datetime import date

from finance_tracker.models import format_amount, to_home_cents

try:
    from fastapi.testclient import TestClient

    from finance_tracker.api import create_app
except ImportError:
    TestClient = None

from tests.support import sign_in
from tests.test_prices import FakeProvider

TODAY = date(2026, 11, 22)


class HelperTests(unittest.TestCase):
    def test_conversion_and_formatting(self):
        self.assertEqual(to_home_cents(35000, 32.0), 1094)  # NT$350 at 32 per dollar = $10.94
        self.assertEqual(format_amount(35000, "TWD"), "NT$350")
        self.assertEqual(format_amount(-123456, "TWD"), "-NT$1,235")
        self.assertEqual(format_amount(1250, "USD"), "$12.50")
        self.assertEqual(format_amount(1250, "EUR"), "€12.50")


@unittest.skipIf(TestClient is None, "install requirements.txt to test the web API")
class CurrencyApiTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        # NT$ per US dollar: 30 on Nov 1, 31 on Nov 20, 32 right now.
        self.provider = FakeProvider(
            {"TWD=X": 32.0},
            histories={"TWD=X": [(date(2026, 11, 1), 30.0), (date(2026, 11, 20), 31.0)]},
        )
        app = create_app(os.path.join(self.folder.name, "finance.db"), provider=self.provider,
                         today=lambda: TODAY, static_dir=None)
        self.client = TestClient(app)
        sign_in(self.client)
        c = self.client
        self.usd = c.post("/api/holdings", json={"asset_type": "cash", "name": "US checking", "value": "1000"}).json()
        self.twd = c.post("/api/holdings", json={
            "asset_type": "cash", "name": "Taiwan bank", "value": "32000", "currency": "twd"}).json()

    def tearDown(self):
        self.client.close()
        self.folder.cleanup()

    def add(self, **kw):
        body = {"description": "Boba", "amount": "350", "category": "Food", "occurred_on": "2026-11-21"}
        return self.client.post("/api/transactions", json={**body, **kw})

    def worth(self):
        return self.client.get("/api/net-worth").json()

    def test_accounts_in_another_currency(self):
        self.assertEqual(self.twd["currency"], "TWD")
        line = next(l for l in self.worth()["lines"] if l["name"] == "Taiwan bank")
        self.assertEqual((line["balance_cents"], line["value_cents"]), (3200000, 100000))  # NT$32,000 = $1,000
        self.assertEqual(self.worth()["liquid_cents"], 200000)
        self.assertEqual(self.client.post("/api/holdings", json={
            "asset_type": "cash", "name": "X", "value": "1", "currency": "XYZ"}).status_code, 400)

    def test_transactions_keep_what_was_paid_and_its_dollar_value(self):
        boba = self.add(account_id=self.twd["id"]).json()
        # Nov 21 uses Nov 20's rate of 31: NT$350 = $11.29.
        self.assertEqual((boba["currency"], boba["paid_cents"], boba["amount_cents"]), ("TWD", 35000, 1129))
        early = self.add(account_id=self.twd["id"], occurred_on="2026-11-05").json()
        self.assertEqual(early["amount_cents"], 1167)  # Nov 1's rate of 30
        # Reports add up dollars; the account moves in NT$.
        self.assertEqual(self.client.get("/api/summary", params={"month": "2026-11"}).json()["spent_cents"], 1129 + 1167)
        line = next(l for l in self.worth()["lines"] if l["name"] == "Taiwan bank")
        self.assertEqual(line["balance_change_cents"], 0)  # both dated before the balance was entered
        self.add(account_id=self.twd["id"], amount="100", occurred_on=TODAY.isoformat())
        line = next(l for l in self.worth()["lines"] if l["name"] == "Taiwan bank")
        self.assertEqual(line["balance_change_cents"], -10000)  # NT$100, in the account's currency

        # A US card purchase on the trip is in dollars.
        card = self.add(account_id=self.usd["id"], amount="12.40").json()
        self.assertEqual((card["currency"], card["amount_cents"]), ("USD", 1240))

        # Edits: a new amount is re-converted; switching currencies needs a new amount.
        edited = self.client.patch(f"/api/transactions/{boba['id']}", json={"amount": "620"}).json()
        self.assertEqual((edited["paid_cents"], edited["amount_cents"]), (62000, 2000))
        self.assertEqual(self.client.patch(f"/api/transactions/{boba['id']}",
                                           json={"account_id": self.usd["id"]}).status_code, 400)
        moved = self.client.patch(f"/api/transactions/{boba['id']}",
                                  json={"account_id": self.usd["id"], "amount": "20"}).json()
        self.assertEqual((moved["currency"], moved["paid_cents"], moved["amount_cents"]), ("USD", 2000, 2000))

        csv = self.client.get("/api/transactions.csv").text.splitlines()
        self.assertEqual(csv[0], "id,date,kind,category,description,amount,currency,amount_paid")
        self.assertIn("TWD,350.00", csv[1])

    def test_offline_without_a_rate(self):
        self.provider.prices.clear()
        self.provider.histories.clear()
        self.assertEqual(self.add(account_id=self.twd["id"]).status_code, 503)
        self.assertEqual(self.add(account_id=self.usd["id"]).status_code, 201)  # dollars need no rate

    def test_transfers_move_money_without_counting_as_spending(self):
        c = self.client
        sent = c.post("/api/transfers", json={
            "from_account_id": self.usd["id"], "to_account_id": self.twd["id"], "amount": "100",
            "occurred_on": "2026-11-22"}).json()
        # No amount received given: converted at that day's rate (31, from Nov 20).
        self.assertEqual((sent["from_cents"], sent["to_cents"], sent["to_currency"]), (10000, 310000, "TWD"))
        exact = c.post("/api/transfers", json={
            "from_account_id": self.usd["id"], "to_account_id": self.twd["id"], "amount": "50",
            "received": "1,540", "note": "Wise"}).json()
        self.assertEqual(exact["to_cents"], 154000)  # the rate your bank actually gave

        lines = {l["name"]: l for l in self.worth()["lines"]}
        self.assertEqual(lines["US checking"]["balance_cents"], 100000 - 15000)
        self.assertEqual(lines["Taiwan bank"]["balance_cents"], 3200000 + 310000 + 154000)
        self.assertEqual(c.get("/api/summary", params={"month": "2026-11"}).json()["spent_cents"], 0)
        self.assertEqual(len(c.get("/api/transfers").json()), 2)

        self.assertEqual(c.delete(f"/api/transfers/{sent['id']}").status_code, 204)
        self.assertEqual(c.delete(f"/api/transfers/{sent['id']}").status_code, 404)
        same = {"from_account_id": self.usd["id"], "to_account_id": self.usd["id"], "amount": "5"}
        self.assertEqual(c.post("/api/transfers", json=same).status_code, 400)
        stock = c.post("/api/holdings", json={"asset_type": "stock", "symbol": "TWD=X", "quantity": 1}).json()
        self.assertEqual(c.post("/api/transfers", json={**same, "to_account_id": stock["id"]}).status_code, 400)

    def test_recurring_rules_in_another_currency(self):
        rule = self.client.post("/api/recurring", json={
            "description": "Phone", "amount": "499", "category": "Utilities", "frequency": "monthly",
            "start_on": "2026-11-05", "account_id": self.twd["id"]}).json()
        self.assertEqual((rule["currency"], rule["amount_cents"]), ("TWD", 49900))
        (phone,) = self.client.get("/api/transactions").json()["items"]
        self.assertEqual((phone["paid_cents"], phone["amount_cents"]), (49900, 1663))  # at 30 per dollar

    def test_recurring_waits_for_a_rate(self):
        self.provider.prices.clear()
        self.provider.histories.clear()
        self.client.post("/api/recurring", json={
            "description": "Phone", "amount": "499", "category": "Utilities", "frequency": "monthly",
            "start_on": "2026-11-05", "account_id": self.twd["id"]})
        self.assertEqual(self.client.get("/api/transactions").json()["items"], [])
        self.provider.prices["TWD=X"] = 32.0  # back online: it catches up
        self.assertEqual(len(self.client.get("/api/transactions").json()["items"]), 1)

    def test_display_currency_and_travel_mode(self):
        c = self.client
        settings = c.get("/api/settings").json()
        self.assertEqual((settings["display_currency"], settings["travel_account_id"]), ("USD", None))
        self.assertIn({"code": "TWD", "symbol": "NT$", "decimals": 0}, settings["currencies"])
        self.assertEqual(c.put("/api/settings", json={"display_currency": "twd"}).json()["display_currency"], "TWD")
        self.assertEqual(c.put("/api/settings", json={"display_currency": "XYZ"}).status_code, 400)
        self.assertEqual(c.get("/api/fx", params={"currency": "TWD"}).json(), {"currency": "TWD", "rate": 32.0})
        self.assertEqual(c.get("/api/fx", params={"currency": "XYZ"}).status_code, 400)

        on = c.put("/api/settings", json={"travel_account_id": self.twd["id"]}).json()
        self.assertEqual(on["travel_account_id"], self.twd["id"])
        self.assertEqual(c.put("/api/settings", json={"theme": "dark"}).json()["travel_account_id"], self.twd["id"])
        self.assertIsNone(c.put("/api/settings", json={"travel_account_id": None}).json()["travel_account_id"])
        self.assertEqual(c.put("/api/settings", json={"travel_account_id": 999}).status_code, 400)
        # Removing the account turns travel mode off.
        c.put("/api/settings", json={"travel_account_id": self.twd["id"]})
        c.delete(f"/api/holdings/{self.twd['id']}")
        self.assertIsNone(c.get("/api/settings").json()["travel_account_id"])


if __name__ == "__main__":
    unittest.main()


@unittest.skipIf(TestClient is None, "install requirements.txt to test the web API")
class ActivityTests(unittest.TestCase):
    """The dropdown under each holding: what moved an account, newest first."""

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        app = create_app(os.path.join(self.folder.name, "finance.db"), provider=FakeProvider({"TWD=X": 32.0}),
                         today=lambda: TODAY, static_dir=None)
        self.client = TestClient(app)
        sign_in(self.client)

    def tearDown(self):
        self.client.close()
        self.folder.cleanup()

    def test_account_activity(self):
        c = self.client
        bank = c.post("/api/holdings", json={"asset_type": "cash", "name": "Bank", "value": "500"}).json()
        savings = c.post("/api/holdings", json={"asset_type": "cash", "name": "Savings", "value": "0"}).json()
        tx = lambda desc, amount, day, **kw: c.post("/api/transactions", json={  # noqa: E731
            "description": desc, "amount": amount, "category": "Food", "occurred_on": day,
            "account_id": bank["id"], **kw}).json()
        tx("Old dinner", "30", "2026-11-10")                          # already in the $500
        tx("Lunch", "12", TODAY.isoformat())                          # after the balance was entered
        tx("Paycheck", "200", TODAY.isoformat(), kind="income", category="Salary")
        c.post("/api/transfers", json={"from_account_id": bank["id"], "to_account_id": savings["id"],
                                       "amount": "50", "note": "monthly"})
        activity = c.get(f"/api/holdings/{bank['id']}/activity").json()
        self.assertEqual(activity["balance"], {"date": TODAY.isoformat(), "amount_cents": 50000})
        self.assertEqual(
            [(i["type"], i["description"], i["amount_cents"], i["counted"]) for i in activity["items"]],
            [("income", "Paycheck", 20000, True),
             ("expense", "Lunch", -1200, True),
             ("transfer", "To Savings", -5000, True),
             ("expense", "Old dinner", -3000, False)],  # older, and already in the balance
        )
        other = c.get(f"/api/holdings/{savings['id']}/activity").json()
        self.assertEqual([(i["description"], i["amount_cents"], i["category"]) for i in other["items"]],
                         [("From Bank", 5000, "monthly")])

        stock = c.post("/api/holdings", json={"asset_type": "stock", "symbol": "AAPL", "quantity": 2,
                                              "bought_on": "2026-01-02", "avg_price": "150"}).json()
        bought = c.get(f"/api/holdings/{stock['id']}/activity").json()["items"]
        self.assertEqual([(i["type"], i["date"], i["quantity"], i["amount_cents"]) for i in bought],
                         [("bought", "2026-01-02", 2, 30000)])
        self.assertEqual(c.get("/api/holdings/999/activity").status_code, 404)
