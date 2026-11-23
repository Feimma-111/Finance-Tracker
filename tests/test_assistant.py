"""Ask-a-question: the lookup tools, the tool-calling loop, and the number check."""

import os
import tempfile
import unittest
from datetime import date

from finance_tracker.assistant import Tools, ask, unverified_numbers
from finance_tracker.models import Frequency, Kind, RecurringRule, Transaction
from finance_tracker.store import Store

try:
    from fastapi.testclient import TestClient

    from finance_tracker.api import create_app
except ImportError:
    TestClient = None

from tests.support import sign_in
from tests.test_prices import FakeProvider

TODAY = date(2026, 11, 22)


def seed(store):
    add = store.add_transaction
    add(Transaction("Groceries", 30000, "Groceries", date(2026, 8, 5)))
    add(Transaction("Lunch", 1250, "Food", date(2026, 8, 20)))
    add(Transaction("Flight home", 48900, "Travel", date(2026, 8, 12)))
    add(Transaction("Groceries", 20000, "Groceries", date(2026, 9, 5)))
    add(Transaction("Boba", 650, "Food", date(2026, 10, 3)))
    add(Transaction("Dinner out", 4200, "Food", date(2026, 11, 8)))
    add(Transaction("Paycheck", 210000, "Salary", date(2026, 11, 1), Kind.INCOME))
    store.add_recurring(RecurringRule("Netflix", 1549, "Subscriptions", Frequency.MONTHLY, date(2026, 12, 15)))
    store.add_recurring(RecurringRule("Gym", 1000, "Health", Frequency.WEEKLY, date(2026, 12, 1)))


class ToolTests(unittest.TestCase):
    def setUp(self):
        self.store = Store(":memory:")
        seed(self.store)
        self.tools = Tools(self.store, TODAY)

    def tearDown(self):
        self.store.close()

    def test_totals(self):
        self.assertEqual(
            self.tools.run("spending_total", {"start": "2026-08-01", "end": "2026-11-22", "category": "food"}),
            {"period": "2026-08-01 to 2026-11-22", "category": "Food", "total": "$61.00", "transactions": 3},
        )
        # Month shorthand covers the whole month.
        self.assertEqual(self.tools.run("spending_total", {"start": "2026-08", "end": "2026-08"})["total"], "$801.50")
        self.assertEqual(self.tools.run("income_total", {"start": "2026-11-01", "end": "2026-11-30"})["total"],
                         "$2,100.00")

    def test_bad_arguments_come_back_as_errors(self):
        unknown = self.tools.run("spending_total", {"start": "2026-01-01", "end": "2026-12-31", "category": "Pets"})
        self.assertIn("no category called 'Pets'", unknown["error"])
        self.assertIn("Groceries", unknown["error"])  # lists the real ones so the model can retry
        self.assertIn("isn't a date", self.tools.run("spending_total", {"start": "August", "end": "2026-11-22"})["error"])
        self.assertIn("after the end", self.tools.run("spending_total", {"start": "2026-11-01", "end": "2026-10-01"})["error"])
        self.assertIn("no tool named", self.tools.run("delete_everything", {})["error"])
        self.assertIn("bad arguments", self.tools.run("spending_total", {"start": "2026-11-01"})["error"])

    def test_breakdown_and_comparison(self):
        by_cat = self.tools.run("spending_by_category", {"start": "2026-08-01", "end": "2026-08-31"})
        self.assertEqual(by_cat["categories"][0], {"category": "Travel", "total": "$489.00", "share": "61.0%"})
        compare = self.tools.run("compare_spending", {
            "first_start": "2026-08-01", "first_end": "2026-08-31",
            "second_start": "2026-09-01", "second_end": "2026-09-30", "category": "Groceries"})
        self.assertEqual(compare["difference"], "$100.00 less in the second period")
        self.assertEqual(compare["percent_change"], "-33.3%")

    def test_monthly_spending(self):
        result = self.tools.run("monthly_spending", {"start_month": "2026-08", "end_month": "2026-11"})
        self.assertEqual([m["total"] for m in result["months"]], ["$801.50", "$200.00", "$6.50", "$42.00"])
        # November is in progress: left out of the average, highest and lowest.
        self.assertEqual(result["monthly_average"], "$336.00")  # (801.50 + 200 + 6.50) / 3
        self.assertEqual(result["months_averaged"], 3)
        self.assertEqual(result["highest_month"], {"month": "2026-08", "total": "$801.50"})
        self.assertEqual(result["lowest_month"], {"month": "2026-10", "total": "$6.50"})
        self.assertIn("still in progress", result["note"])

    def test_find_transactions(self):
        # No kind given: expenses only, so the $2,100 paycheck isn't a "purchase".
        largest = self.tools.run("find_transactions", {"order": "largest", "limit": 2})
        self.assertEqual([t["description"] for t in largest["transactions"]], ["Flight home", "Groceries"])
        anything = self.tools.run("find_transactions", {"order": "largest", "limit": 1, "kind": "any"})
        self.assertEqual(anything["transactions"][0]["description"], "Paycheck")
        search = self.tools.run("find_transactions", {"text": "boba"})
        self.assertEqual(search["count"], 1)
        # SQL wildcards in the search text are treated literally.
        self.assertEqual(self.tools.run("find_transactions", {"text": "%"})["count"], 0)

    def test_covered_categories(self):
        self.store.set_setting("covered_categories", '["Groceries", "Travel", "Deleted category"]')
        self.store.set_setting("covered_note", "My parents pay for these")
        tools = Tools(self.store, TODAY)
        self.assertEqual(tools.covered, ["Groceries", "Travel"])  # missing names dropped
        aug = tools.run("spending_total", {"start": "2026-08-01", "end": "2026-08-31"})
        self.assertEqual((aug["total"], aug["covered_by_others"], aug["spending_you_control"]),
                         ("$801.50", "$789.00", "$12.50"))
        by_cat = tools.run("spending_by_category", {"start": "2026-08-01", "end": "2026-08-31"})
        self.assertTrue(by_cat["categories"][0]["covered_by_someone_else"])  # Travel
        self.assertEqual(by_cat["spending_you_control"], "$12.50")
        monthly = tools.run("monthly_spending", {"start_month": "2026-08", "end_month": "2026-10"})
        self.assertEqual([m["spending_you_control"] for m in monthly["months"]], ["$12.50", "$0.00", "$6.50"])
        self.assertEqual(monthly["monthly_average_you_control"], "$6.33")
        compare = tools.run("compare_spending", {"first_start": "2026-08-01", "first_end": "2026-08-31",
                                                 "second_start": "2026-10-01", "second_end": "2026-10-31"})
        self.assertEqual(compare["spending_you_control_difference"], "$6.00 less in the second period")
        self.assertEqual(tools.run("spending_total", {"start": "2026-08-01", "end": "2026-08-31",
                                                      "category": "Travel"})["covered_by_someone_else"],
                         "My parents pay for these")
        from finance_tracker.assistant import system_prompt
        self.assertIn("paid for by someone else (My parents pay for these): Groceries, Travel",
                      system_prompt(self.store, TODAY))

    def test_recurring_monthly_equivalents(self):
        result = self.tools.run("recurring_charges", {})
        gym = next(r for r in result["recurring"] if r["description"] == "Gym")
        self.assertEqual(gym["monthly_equivalent"], "$43.33")  # $10 x 52 / 12
        self.assertEqual(result["recurring_expenses_per_month"], "$58.82")


class FakeModel:
    """Plays back scripted replies and records what it was sent."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.sent = []

    def __call__(self, messages, tools):
        self.sent.append(list(messages))
        return self.replies.pop(0)


def tool_call(name, **arguments):
    return {"content": "", "tool_calls": [{"function": {"name": name, "arguments": arguments}}]}


class AskLoopTests(unittest.TestCase):
    def setUp(self):
        self.store = Store(":memory:")
        seed(self.store)

    def tearDown(self):
        self.store.close()

    def test_tool_then_answer(self):
        model = FakeModel([
            tool_call("spending_total", start="2026-08-01", end="2026-11-22", category="Food"),
            {"content": "You've spent $61.00 on food since August."},
        ])
        result = ask(self.store, TODAY, "How much on food since August?", model)
        self.assertEqual(result["answer"], "You've spent $61.00 on food since August.")
        self.assertEqual(result["unverified"], [])
        self.assertEqual(result["steps"][0]["result"]["total"], "$61.00")
        # The second request carried the tool result back to the model.
        tool_message = model.sent[1][-1]
        self.assertEqual((tool_message["role"], tool_message["tool_name"]), ("tool", "spending_total"))
        self.assertIn("Today is 2026-11-22", model.sent[0][0]["content"])

    def test_invented_numbers_are_flagged(self):
        model = FakeModel([
            tool_call("spending_total", start="2026-08-01", end="2026-11-22", category="Food"),
            {"content": "You spent $61.00 on food, about $20.33 a month (33% of your budget)."},
        ])
        result = ask(self.store, TODAY, "Food since August?", model)
        self.assertEqual(result["unverified"], ["$20.33", "33%"])

    def test_history_and_round_limit(self):
        endless = FakeModel([tool_call("list_categories")] * 10)
        result = ask(self.store, TODAY, "?", endless,
                     history=[{"role": "user", "content": "hi"}, {"role": "system", "content": "ignored"}])
        self.assertIn("couldn't work that out", result["answer"])
        roles = [m["role"] for m in endless.sent[0]]
        self.assertEqual(roles, ["system", "user", "user"])  # injected "system" turn dropped

    def test_number_check_allows_rounding(self):
        steps = [{"result": {"total": "$1,084.27", "share": "15.9%", "change": "-33.3%"}}]
        self.assertEqual(unverified_numbers("About $1,084 (16%), down 33.3%.", steps), [])
        self.assertEqual(unverified_numbers("That's $1,100.", steps), ["$1,100"])


class FakeAI:
    def __init__(self, url):
        pass

    def models(self):
        return ["qwen3.5:latest"]

    def chat(self, model, messages, tools):
        if messages[-1]["role"] == "user":
            return tool_call("list_categories")
        return {"content": "You have categories for food and groceries."}


@unittest.skipIf(TestClient is None, "install requirements.txt to test the web API")
class AskApiTests(unittest.TestCase):
    def test_ask_endpoint(self):
        with tempfile.TemporaryDirectory() as folder:
            app = create_app(os.path.join(folder, "f.db"), provider=FakeProvider({}),
                             today=lambda: TODAY, static_dir=None, ai_client_factory=FakeAI)
            with TestClient(app) as client:
                sign_in(client)
                self.assertEqual(client.post("/api/ai/ask", json={"question": "hi"}).status_code, 400)  # not set up
                client.put("/api/settings", json={"ai_url": "http://pc:11434"})
                reply = client.post("/api/ai/ask", json={
                    "question": "What categories do I have?",
                    "history": [{"role": "user", "content": "hello"}, {"role": "assistant", "content": "hi!"}],
                }).json()
                self.assertEqual(reply["answer"], "You have categories for food and groceries.")
                self.assertEqual(reply["steps"][0]["tool"], "list_categories")
                self.assertEqual(reply["model"], "qwen3.5:latest")
                self.assertEqual(client.post("/api/ai/ask", json={"question": ""}).status_code, 422)


if __name__ == "__main__":
    unittest.main()
