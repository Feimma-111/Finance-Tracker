"""The AI analyst: fact sheet math, reply parsing, and the API with a fake PC."""

import json
import os
import tempfile
import unittest
from datetime import date

from finance_tracker.analyst import (
    AIError,
    AIUnavailable,
    OllamaClient,
    Review,
    month_facts,
    normalize_url,
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

    def test_first_month_has_no_comparison(self):
        facts = month_facts(self.store, "2026-09", TODAY)
        self.assertIn("(complete)", facts)
        self.assertIn("No earlier months to compare with yet.", facts)


class ParsingTests(unittest.TestCase):
    def test_parse_review(self):
        review = parse_review(json.dumps({
            "headline": " Good month ", "observations": ["a", "", "b"], "suggestions": ["c"],
        }))
        self.assertEqual(review, Review("Good month", ["a", "b"], ["c"]))
        for bad in ["not json", "{}", json.dumps({"headline": "", "observations": [], "suggestions": []})]:
            with self.assertRaises(AIError):
                parse_review(bad)

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

    def __init__(self, url):
        self.url = url

    def models(self):
        if not FakeAI.online:
            raise AIUnavailable("can't reach")
        return ["qwen3.5:latest", "llama3:latest"]

    def review(self, model, facts):
        FakeAI.seen.append((model, facts))
        return Review("A steady month.", ["Groceries fell."], ["Keep it up."])


@unittest.skipIf(TestClient is None, "install requirements.txt to test the web API")
class AnalystApiTests(unittest.TestCase):
    def setUp(self):
        FakeAI.online = True
        FakeAI.seen = []
        self.folder = tempfile.TemporaryDirectory()
        app = create_app(
            os.path.join(self.folder.name, "finance.db"),
            provider=FakeProvider({}),
            today=lambda: TODAY,
            static_dir=None,
            ai_client_factory=FakeAI,
        )
        self.client = TestClient(app)
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


if __name__ == "__main__":
    unittest.main()
