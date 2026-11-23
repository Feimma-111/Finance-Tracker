"""The AI analyst: fact sheet math, reply parsing, and the API with a fake PC."""

import json
import os
import tempfile
import unittest
from datetime import date

from finance_tracker.analyst import (
    FOCUS_PROMPT,
    FOCUS_SCHEMA,
    AIError,
    AIUnavailable,
    OllamaClient,
    Review,
    _trend,
    focus_facts,
    month_facts,
    normalize_url,
    parse_focus_review,
    parse_review,
    pick_model,
)
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


def tx(desc, cents, category, day, kind=Kind.EXPENSE):
    return Transaction(desc, cents, category, day, kind)


class FactSheetTests(unittest.TestCase):
    def setUp(self):
        self.store = Store(":memory:")
        s = self.store
        s.add_transaction(tx("Groceries", 40000, "Groceries", date(2026, 9, 5)))
        s.add_transaction(tx("Groceries", 30000, "Groceries", date(2026, 10, 5)))
        s.add_transaction(tx("Gym", 5000, "Health", date(2026, 10, 9)))
        s.add_transaction(tx("Groceries", 20000, "Groceries", date(2026, 11, 5)))
        s.add_transaction(tx("Concert", 15000, "Fun", date(2026, 11, 8)))
        s.add_transaction(tx("Paycheck", 100000, "Salary", date(2026, 11, 1), Kind.INCOME))
        s.add_recurring(RecurringRule("Netflix", 1549, "Subscriptions", Frequency.MONTHLY, date(2026, 12, 15)))

    def tearDown(self):
        self.store.close()

    def test_numbers_are_precomputed(self):
        facts = month_facts(self.store, "2026-11", TODAY)
        self.assertIn("Month: November 2026 (IN PROGRESS: day 22 of 30)", facts)
        self.assertIn("Total spending: $350.00", facts)
        self.assertIn("Net: $650.00 (saved 65% of income)", facts)
        # Sep $400 and Oct $350 -> $375 average; Nov is $25 less.
        self.assertIn("previous 2 month(s): $375.00", facts)
        self.assertIn("compared with that average: $25.00 less (-6.7%)", facts)
        self.assertIn("- Groceries: $200.00 (57% of spending) | $350.00 | $150.00 less (-42.9%)", facts)
        self.assertIn("- Fun: $150.00 (43% of spending) | $0.00 | new this month", facts)
        self.assertIn("- Health: $0.00 this month | $25.00 | none yet", facts)
        self.assertIn("- Nov 08: Concert (Fun) $150.00", facts)
        self.assertIn("- Netflix (Subscriptions): $15.49 monthly", facts)

    def test_one_off_categories_are_not_called_usual(self):
        # Adding August makes 3 previous months. Travel and Health each appear
        # in only 1 of them, so neither is listed as "usual" spending.
        self.store.add_transaction(tx("Flight", 50000, "Travel", date(2026, 8, 3)))
        facts = month_facts(self.store, "2026-11", TODAY)
        self.assertNotIn("Travel", facts)
        self.assertNotIn("Health: $0.00", facts)
        self.assertIn("previous 3 month(s)", facts)

    def test_covered_categories_are_marked_and_excluded(self):
        # Pretend parents pay for groceries: Nov $200 of $350 is covered.
        self.store.set_setting("covered_categories", '["groceries"]')  # matched case-insensitively
        self.store.set_setting("covered_note", "My parents pay for this")
        facts = month_facts(self.store, "2026-11", TODAY)
        self.assertIn("Covered by someone else (My parents pay for this): Groceries. "
                      "$200.00 of this month's spending is covered.", facts)
        self.assertIn("Spending you control (everything not covered): $150.00", facts)
        # Sep: $400 - $400 groceries = $0; Oct: $350 - $300 = $50 -> average $25
        self.assertIn("Average spending you control over those months: $25.00", facts)
        self.assertIn("Spending you control compared with that average: $125.00 more (+500.0%)", facts)
        self.assertIn("| $150.00 less (-42.9%) [covered: My parents pay for this]", facts)
        self.assertIn("Groceries) $200.00 [covered]", facts)

    def test_first_month_has_no_comparison(self):
        facts = month_facts(self.store, "2026-09", TODAY)
        self.assertIn("(complete)", facts)
        self.assertIn("No earlier months to compare with yet.", facts)


class FocusFactsTests(unittest.TestCase):
    """The fact sheet for "look at just these categories"."""

    def setUp(self):
        self.store = Store(":memory:")
        s = self.store
        # September
        s.add_transaction(tx("Coffee", 500, "Food", date(2026, 9, 2)))
        s.add_transaction(tx("Coffee", 500, "Food", date(2026, 9, 9)))
        s.add_transaction(tx("Groceries", 40000, "Groceries", date(2026, 9, 5)))
        # October
        s.add_transaction(tx("Coffee", 600, "Food", date(2026, 10, 3)))
        s.add_transaction(tx("Dinner out", 4000, "Food", date(2026, 10, 10)))
        s.add_transaction(tx("Bus", 300, "Transport", date(2026, 10, 4)))
        s.add_transaction(tx("Groceries", 30000, "Groceries", date(2026, 10, 5)))
        # November (in progress)
        s.add_transaction(tx("Coffee", 450, "Food", date(2026, 11, 2)))
        s.add_transaction(tx("  Coffee", 550, "Food", date(2026, 11, 9)))  # same place, messier spelling
        s.add_transaction(tx("Dinner out", 6000, "Food", date(2026, 11, 12)))
        s.add_transaction(tx("Groceries", 20000, "Groceries", date(2026, 11, 5)))
        s.add_transaction(tx("Concert", 15000, "Fun", date(2026, 11, 8)))
        s.add_transaction(tx("Paycheck", 100000, "Salary", date(2026, 11, 1), Kind.INCOME))
        s.add_recurring(RecurringRule("Meal kit", 3000, "Food", Frequency.MONTHLY, date(2026, 12, 1)))
        s.add_recurring(RecurringRule("Netflix", 1549, "Subscriptions", Frequency.MONTHLY, date(2026, 12, 15)))

    def tearDown(self):
        self.store.close()

    def test_numbers_are_precomputed(self):
        facts = focus_facts(self.store, "2026-11", ["Transport", "Food"], TODAY)
        self.assertIn("Month: November 2026 (IN PROGRESS: day 22 of 30)", facts)
        self.assertIn("Categories you asked about: Food, Transport", facts)  # biggest first
        # $70 of Nov's $420 total.
        self.assertIn("Spending in these categories: $70.00 (17% of all your spending this month)", facts)
        # Sep $10 and Oct $49 -> $29.50 average; Nov is $40.50 more.
        self.assertIn("over the previous 2 month(s): $29.50", facts)
        self.assertIn("This month compared with that average: $40.50 more (+137.3%)", facts)
        self.assertIn("- Food: $70.00 (100% of these categories) | $28.00 | $42.00 more (+150.0%)", facts)
        self.assertIn("- Transport: $0.00 (0% of these categories) | $1.50 | none yet", facts)
        self.assertIn("- Food: Sep $10.00, Oct $46.00, Nov $70.00 (so far)", facts)
        self.assertIn("- All of these together: Sep $10.00, Oct $49.00, Nov $70.00 (so far)", facts)
        # The trend is worked out here, not left to the model.
        self.assertIn("- Food: Nov so far is higher than any of the previous 2 months; "
                      "$24.00 more (+52.2%) than Oct; up 2 months in a row", facts)
        self.assertIn("- Transport: Nov so far is within the range of the previous 2 months "
                      "($0.00 in Sep to $3.00 in Oct); $3.00 less (-100.0%) than Oct", facts)
        self.assertIn("- All of these together: Nov so far is higher than any of the previous 2 months; "
                      "$21.00 more (+42.9%) than Oct; up 2 months in a row", facts)
        # Purchases come before the totals: the user already sees totals on the chart.
        self.assertLess(facts.index("grouped by description"), facts.index("Spending in these categories"))
        self.assertIn("grouped by description (3 purchases in total)", facts)
        self.assertIn("- Dinner out (Food): 1 purchase, $60.00", facts)
        self.assertIn("- Coffee (Food): 2 purchases, $10.00", facts)
        self.assertIn("- Nov 12: Dinner out (Food) $60.00", facts)
        self.assertIn("- Meal kit (Food): $30.00 monthly", facts)

    def test_other_categories_are_left_out(self):
        facts = focus_facts(self.store, "2026-11", ["Food"], TODAY)
        for absent in ["Groceries", "Concert", "Fun", "Salary", "Netflix", "income", "Net worth"]:
            self.assertNotIn(absent, facts)
        self.assertNotIn("All of these together", facts)  # only one category
        self.assertNotIn("of these categories", facts)

    def test_covered_categories(self):
        self.store.set_setting("covered_categories", '["Food"]')
        self.store.set_setting("covered_note", "Parents pay")
        facts = focus_facts(self.store, "2026-11", ["Food", "Transport"], TODAY)
        self.assertIn("Covered by someone else (Parents pay): Food.", facts)
        self.assertIn("Spending you control in these categories (everything not covered): $0.00", facts)
        # Transport alone: Oct $3, Sep $0 -> $1.50 average.
        self.assertIn("Average spending you control in these categories over those months: $1.50", facts)
        self.assertIn("Spending you control compared with that average: $1.50 less (-100.0%)", facts)
        self.assertIn("$42.00 more (+150.0%) [covered: Parents pay]", facts)
        self.assertIn("Dinner out (Food) $60.00 [covered]", facts)

    def test_first_month_and_empty_categories(self):
        facts = focus_facts(self.store, "2026-09", ["Food"], TODAY)
        self.assertIn("(complete)", facts)
        self.assertIn("No earlier months to compare with yet.", facts)
        self.assertIn("- Food: $10.00\n", facts)
        self.assertIn("- Coffee (Food): 2 purchases, $10.00", facts)
        self.assertNotIn("Month by month", facts)

        facts = focus_facts(self.store, "2026-10", ["Fun"], TODAY)
        self.assertIn("- Fun: $0.00 | $0.00 | no spending in any of these months", facts)
        self.assertIn("No purchases in these categories this month.", facts)
        self.assertNotIn("Trend", facts)  # nothing to describe

    def test_trend_wording(self):
        series = lambda *cents: [(f"2026-{m:02d}", c) for m, c in zip(range(6, 12), cents)]  # noqa: E731
        self.assertEqual(
            _trend("Food", series(300, 200, 100), True, "%b"),
            "- Food: Aug so far is lower than any of the previous 2 months (the month isn't over yet); "
            "$1.00 less (-50.0%) than Jul; down 2 months in a row")
        self.assertEqual(
            _trend("Food", series(100, 200, 200), False, "%b"),
            "- Food: Aug is within the range of the previous 2 months ($1.00 in Jun to $2.00 in Jul); "
            "the same as Jul")
        self.assertIsNone(_trend("Food", series(0, 0), False, "%b"))


class ParsingTests(unittest.TestCase):
    def test_parse_review(self):
        review = parse_review(json.dumps({
            "headline": " Good month ", "observations": ["a", "", "b"], "suggestions": ["c"],
        }))
        self.assertEqual(review, Review("Good month", ["a", "b"], ["c"]))
        for bad in ["not json", "{}", json.dumps({"headline": "", "observations": [], "suggestions": []})]:
            with self.assertRaises(AIError):
                parse_review(bad)

    def test_parse_focus_review(self):
        review = parse_focus_review(json.dumps({
            "headline": "Boba drove it.", "drivers": ["3 boba runs, $87.81."], "trend": "Up 2 months in a row.",
            "ideas": ["Swap one boba run for tea at home."],
        }))
        self.assertEqual(review, Review(
            "Boba drove it.", ["3 boba runs, $87.81.", "Up 2 months in a row."], ["Swap one boba run for tea at home."]))
        with self.assertRaises(AIError):
            parse_focus_review(json.dumps({"headline": "h", "observations": ["o"], "suggestions": []}))

    def test_focus_reviews_use_their_own_prompt_and_shape(self):
        bodies = []

        class Client(OllamaClient):
            def _request(self, path, body=None, timeout=None):
                bodies.append(body)
                return {"message": {"content": json.dumps(
                    {"headline": "h", "drivers": ["d"], "trend": "t", "ideas": ["i"]})}}

        review = Client("http://x:11434").review("m", "facts", focus=True)
        self.assertEqual(review.observations, ["d", "t"])
        self.assertEqual(bodies[0]["format"], FOCUS_SCHEMA)
        self.assertEqual(bodies[0]["messages"][0]["content"], FOCUS_PROMPT)

    def test_normalize_url(self):
        self.assertEqual(normalize_url("100.101.102.103"), "http://100.101.102.103:11434")
        self.assertEqual(normalize_url("http://desktop:11434/"), "http://desktop:11434")
        with self.assertRaises(ValueError):
            normalize_url("ftp://x")

    def test_pick_model(self):
        self.assertEqual(pick_model(["a", "b"], "b"), "b")
        self.assertEqual(pick_model(["a", "b"], "missing"), "a")
        self.assertIsNone(pick_model([], "a"))

    def test_retries_without_think_for_older_models(self):
        calls = []

        class Client(OllamaClient):
            def _request(self, path, body=None, timeout=None):
                calls.append(dict(body))
                if "think" in body:
                    raise AIError('"llama3" does not support thinking')
                return {"message": {"content": json.dumps(
                    {"headline": "h", "observations": ["o"], "suggestions": []})}}

        review = Client("http://x:11434").review("llama3", "facts")
        self.assertEqual(review.headline, "h")
        self.assertEqual(["think" in c for c in calls], [True, False])


class FakeAI:
    """Stands in for OllamaClient so API tests never need the real PC."""

    online = True
    seen = []
    focus = []

    def __init__(self, url):
        self.url = url

    def models(self):
        if not FakeAI.online:
            raise AIUnavailable("can't reach")
        return ["qwen3.5:latest", "llama3:latest"]

    def review(self, model, facts, focus=False):
        FakeAI.seen.append((model, facts))
        FakeAI.focus.append(focus)
        return Review("A steady month.", ["Groceries fell."], ["Keep it up."])


@unittest.skipIf(TestClient is None, "install requirements.txt to test the web API")
class AnalystApiTests(unittest.TestCase):
    def setUp(self):
        FakeAI.online = True
        FakeAI.seen = []
        FakeAI.focus = []
        self.folder = tempfile.TemporaryDirectory()
        app = create_app(
            os.path.join(self.folder.name, "finance.db"),
            provider=FakeProvider({}),
            today=lambda: TODAY,
            static_dir=None,
            ai_client_factory=FakeAI,
        )
        self.client = TestClient(app)
        sign_in(self.client)
        self.client.post("/api/transactions", json={
            "description": "Groceries", "amount": "50", "category": "Groceries", "occurred_on": "2026-11-03"})

    def tearDown(self):
        self.client.close()
        self.folder.cleanup()

    def test_not_configured(self):
        self.assertFalse(self.client.get("/api/ai/status").json()["configured"])
        self.assertEqual(self.client.post("/api/ai/reviews/2026-11").status_code, 400)

    def test_settings_validate_and_normalize_address(self):
        saved = self.client.put("/api/settings", json={"ai_url": "100.101.102.103"}).json()
        self.assertEqual(saved["ai_url"], "http://100.101.102.103:11434")
        self.assertEqual(saved["theme"], "system")  # untouched fields stay put
        self.assertEqual(self.client.put("/api/settings", json={"ai_url": "ftp://nope"}).status_code, 400)
        self.assertEqual(self.client.put("/api/settings", json={"ai_url": ""}).json()["ai_url"], "")
        covered = self.client.put("/api/settings", json={
            "covered_categories": ["groceries"], "covered_note": "Parents pay"}).json()
        self.assertEqual((covered["covered_categories"], covered["covered_note"]), (["Groceries"], "Parents pay"))
        self.assertEqual(self.client.put("/api/settings", json={"covered_categories": ["Nope"]}).status_code, 400)

    def test_generate_and_reread_review(self):
        self.client.put("/api/settings", json={"ai_url": "http://pc:11434", "ai_model": "llama3:latest"})
        status = self.client.get("/api/ai/status").json()
        self.assertEqual((status["reachable"], status["model"]), (True, "llama3:latest"))

        self.assertIsNone(self.client.get("/api/ai/reviews/2026-11").json()["saved"])
        created = self.client.post("/api/ai/reviews/2026-11")
        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.json()["review"]["headline"], "A steady month.")
        model, facts = FakeAI.seen[0]
        self.assertEqual(model, "llama3:latest")
        self.assertIn("Total spending: $50.00", facts)

        # PC goes offline: the saved review is still there.
        FakeAI.online = False
        self.assertFalse(self.client.get("/api/ai/status").json()["reachable"])
        self.assertEqual(self.client.post("/api/ai/reviews/2026-11").status_code, 503)
        saved = self.client.get("/api/ai/reviews/2026-11").json()["saved"]
        self.assertEqual(saved["review"]["observations"], ["Groceries fell."])
        self.assertIn("Total spending: $50.00", saved["facts"])
        self.assertFalse(saved["outdated"])

    def test_review_goes_out_of_date(self):
        self.client.put("/api/settings", json={"ai_url": "http://pc:11434"})
        self.client.post("/api/ai/reviews/2026-11")
        outdated = lambda: self.client.get("/api/ai/reviews/2026-11").json()["saved"]["outdated"]  # noqa: E731
        self.assertFalse(outdated())
        self.client.put("/api/settings", json={"covered_categories": ["Groceries"]})  # covered changed
        self.assertTrue(outdated())
        self.client.post("/api/ai/reviews/2026-11")
        self.assertFalse(outdated())
        self.client.post("/api/transactions", json={  # data changed
            "description": "Gum", "amount": "2", "category": "Groceries", "occurred_on": "2026-11-04"})
        self.assertTrue(outdated())

    def test_focus_review(self):
        self.client.post("/api/transactions", json={
            "description": "Concert", "amount": "80", "category": "Fun", "occurred_on": "2026-11-06"})
        focus = lambda body: self.client.post("/api/ai/focus", json=body)  # noqa: E731
        self.assertEqual(focus({"categories": ["Groceries"]}).status_code, 400)  # AI not set up

        self.client.put("/api/settings", json={"ai_url": "http://pc:11434"})
        result = focus({"month": "2026-11", "categories": ["groceries", "Groceries"]})
        self.assertEqual(result.status_code, 200)
        body = result.json()
        self.assertEqual((body["month"], body["categories"]), ("2026-11", ["Groceries"]))  # matched, deduplicated
        self.assertEqual(body["review"]["headline"], "A steady month.")
        self.assertEqual(FakeAI.focus, [True])
        self.assertIn("Categories you asked about: Groceries", body["facts"])
        self.assertNotIn("Concert", body["facts"])
        # Nothing is saved: the month's own review is still empty.
        self.assertIsNone(self.client.get("/api/ai/reviews/2026-11").json()["saved"])

        self.assertEqual(focus({"categories": ["Nope"]}).status_code, 400)
        self.assertEqual(focus({"categories": []}).status_code, 422)
        self.assertEqual(focus({"month": "2026-13", "categories": ["Fun"]}).status_code, 400)
        FakeAI.online = False
        self.assertEqual(focus({"categories": ["Fun"]}).status_code, 503)

    def test_changed_at_moves_when_data_changes(self):
        changed = lambda: self.client.get("/api/ai/changed").json()["changed_at"]  # noqa: E731
        before = changed()
        self.assertIsNotNone(before)  # setUp added a transaction
        self.client.post("/api/transactions", json={
            "description": "Gum", "amount": "2", "category": "Groceries", "occurred_on": "2026-11-04"})
        self.assertGreater(changed(), before)


if __name__ == "__main__":
    unittest.main()
