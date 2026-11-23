"""CSV import: column guessing, bank formats, dates, duplicates, and the API."""

import os
import tempfile
import unittest
from datetime import date

from finance_tracker import importer
from finance_tracker.importer import Mapping, Options, import_rows, parse, parse_amount, preview, suggest_mapping
from finance_tracker.models import Kind, Transaction
from finance_tracker.store import Store

try:
    from fastapi.testclient import TestClient

    from finance_tracker.api import create_app
except ImportError:
    TestClient = None

from tests.test_prices import FakeProvider

TODAY = date(2026, 11, 22)

BANK = """Date,Description,Amount
11/03/2026,TRADER JOE'S #123,-45.20
11/01/2026,PAYROLL DEPOSIT,"2,100.00"
10/28/2026,Coffee,(4.50)
"""

CHASE = """Transaction Date,Post Date,Description,Category,Type,Amount,Memo
11/05/2026,11/06/2026,NETFLIX.COM,Entertainment,Sale,-15.49,
11/02/2026,11/03/2026,AMAZON RETURN,Shopping,Return,23.99,
10/30/2026,10/31/2026,WHOLE FOODS,Groceries,Sale,-82.10,
"""

EURO = """Date;Details;Debit;Credit
25/10/2026;Supermarket;42,10;
26/10/2026;Salary;;1500
"""  # note: comma decimal "42,10" is NOT supported -> reported as a problem row

# A shared-expense app's export (tab-separated): "Amount" is the whole bill,
# and the per-person column ("Sam Lee") is that person's share.
SPLIT_APP = (
    "Transaction Type\tName\tAmount\tDate\tCategory\tTags\tPaid By\tSam Lee\n"
    "debit\tDoor Hook\t-9.94\t2026/10/02\tLifestyle\t\tSam Lee\t-9.94\n"
    "debit\tDinner\t-40.00\t2026/10/05\tFood\t\tSam Lee\t-20.00\n"
    "credit\tVenmo from Alex\t20.00\t2026/10/06\tSettle up\t\tAlex\t20.00\n"
)

EXPORT = """id,date,kind,category,description,amount
1,2026-07-01,expense,Food,Coffee,4.50
2,2026-07-15,income,Salary,Paycheck,2100.00
"""


def run(store, text, **options):
    headers, rows = importer.read_csv(text)
    return import_rows(store, text, suggest_mapping(headers, rows), Options(**options), TODAY)


class ParsingTests(unittest.TestCase):
    def setUp(self):
        self.store = Store(":memory:")

    def tearDown(self):
        self.store.close()

    def test_amount_formats(self):
        self.assertEqual(str(parse_amount("$1,234.50")), "1234.50")
        self.assertEqual(str(parse_amount("(12.50)")), "-12.50")
        self.assertEqual(str(parse_amount("12.50-")), "-12.50")
        self.assertEqual(str(parse_amount("(1,250.00)")), "-1250.00")
        self.assertIsNone(parse_amount("  "))
        for bad in ["twelve", "42,10", "1,23", "12,5"]:  # decimal commas must not become 4,210
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    parse_amount(bad)

    def test_generic_bank_signed_amounts(self):
        result = run(self.store, BANK)
        self.assertEqual((result["imported"], result["error_count"]), (3, 0))
        txs = {t.description: t for t in self.store.transactions()}
        self.assertEqual((txs["TRADER JOE'S #123"].kind, txs["TRADER JOE'S #123"].amount_cents), (Kind.EXPENSE, 4520))
        self.assertEqual((txs["PAYROLL DEPOSIT"].kind, txs["PAYROLL DEPOSIT"].amount_cents), (Kind.INCOME, 210000))
        self.assertEqual(txs["Coffee"].kind, Kind.EXPENSE)  # (4.50) is negative
        self.assertEqual(txs["Coffee"].occurred_on, date(2026, 10, 28))
        self.assertEqual(txs["Coffee"].category, "Uncategorized")

    def test_chase_style_type_column_is_not_trusted(self):
        headers, rows = importer.read_csv(CHASE)
        mapping = suggest_mapping(headers, rows)
        self.assertEqual((mapping.date, mapping.amount, mapping.category), ("Transaction Date", "Amount", "Category"))
        self.assertIsNone(mapping.kind)  # "Sale"/"Return" aren't expense/income words
        run(self.store, CHASE)
        txs = {t.description: t for t in self.store.transactions()}
        self.assertEqual(txs["NETFLIX.COM"].kind, Kind.EXPENSE)
        self.assertEqual(txs["AMAZON RETURN"].kind, Kind.INCOME)
        self.assertEqual(txs["WHOLE FOODS"].category, "Groceries")

    def test_debit_credit_columns_and_semicolons(self):
        headers, rows = importer.read_csv(EURO)
        mapping = suggest_mapping(headers, rows)
        self.assertEqual((mapping.debit, mapping.credit, mapping.amount), ("Debit", "Credit", None))
        parsed = parse(EURO, mapping, Options(), TODAY)
        self.assertEqual(parsed.date_format, "DD/MM/YYYY")  # day 25 rules out MM/DD
        [(line, salary)] = parsed.transactions
        self.assertEqual((salary.kind, salary.amount_cents), (Kind.INCOME, 150000))
        self.assertIn("line 2", parsed.errors[0])
        self.assertIn("comma as the decimal point", parsed.errors[0])  # not silently $4,210

    def test_split_app_export(self):
        headers, rows = importer.read_csv(SPLIT_APP)
        mapping = suggest_mapping(headers, rows)
        self.assertEqual(
            (mapping.date, mapping.description, mapping.amount, mapping.category, mapping.kind),
            ("Date", "Name", "Amount", "Category", "Transaction Type"),
        )
        parsed = parse(SPLIT_APP, mapping, Options(), TODAY)
        self.assertEqual(parsed.date_format, "YYYY/MM/DD")
        got = [(t.description, t.kind, t.amount_cents, t.category) for _, t in parsed.transactions]
        self.assertEqual(got, [
            ("Door Hook", Kind.EXPENSE, 994, "Lifestyle"),
            ("Dinner", Kind.EXPENSE, 4000, "Food"),            # the whole bill...
            ("Venmo from Alex", Kind.INCOME, 2000, "Settle up"),
        ])
        # ...or just your share, by picking the per-person column as the amount.
        mapping.amount = "Sam Lee"
        mine = parse(SPLIT_APP, mapping, Options(), TODAY)
        self.assertEqual(mine.transactions[1][1].amount_cents, 2000)

    def test_own_export_round_trip(self):
        self.assertEqual(run(self.store, EXPORT)["imported"], 2)
        again = run(self.store, EXPORT)
        self.assertEqual((again["imported"], again["duplicates"]), (0, 2))
        self.assertEqual(self.store.transaction_count(), 2)

    def test_duplicates_respect_counts(self):
        self.store.add_transaction(Transaction("Coffee", 450, "Food", date(2026, 11, 3)))
        text = "Date,Description,Amount\n11/03/2026,Coffee,-4.50\n11/03/2026,Coffee,-4.50\n"
        result = run(self.store, text)
        self.assertEqual((result["imported"], result["duplicates"]), (1, 1))  # one was new

    def test_ambiguous_dates_can_be_overridden(self):
        text = "Date,Description,Amount\n03/04/2026,Thing,-1\n"
        headers, rows = importer.read_csv(text)
        mapping = suggest_mapping(headers, rows)
        auto = parse(text, mapping, Options(), TODAY)
        self.assertEqual(auto.date_formats[:2], ["MM/DD/YYYY", "DD/MM/YYYY"])
        self.assertEqual(auto.transactions[0][1].occurred_on, date(2026, 3, 4))
        uk = parse(text, mapping, Options(date_format="DD/MM/YYYY"), TODAY)
        self.assertEqual(uk.transactions[0][1].occurred_on, date(2026, 4, 3))

    def test_bad_rows_are_reported_and_good_ones_kept(self):
        text = (
            "﻿Date,Description,Amount\n"                 # byte-order mark from Excel
            "2026-11-01T00:00:00,Good,-10\n"
            "2026-11-02,Zero,0\n"
            "2026-12-25,Future,-5\n"
            "2026-11-03,,-5\n"
            "2026-11-04,No amount,\n"
        )
        parsed = parse(text, suggest_mapping(*importer.read_csv(text)), Options(), TODAY)
        self.assertEqual([t.description for _, t in parsed.transactions], ["Good"])
        self.assertEqual(len(parsed.errors), 4)
        self.assertTrue(any("in the future" in e for e in parsed.errors))

    def test_file_level_problems(self):
        for text in ["", "Date,Description,Amount\n"]:
            with self.assertRaises(importer.ImportError_):
                importer.read_csv(text)
        with self.assertRaises(importer.ImportError_):
            parse(BANK, Mapping(date="Date", description="Description"), Options(), TODAY)  # no amount
        with self.assertRaises(importer.ImportError_):
            parse(BANK, Mapping(date="Nope", description="Description", amount="Amount"), Options(), TODAY)

    def test_preview_saves_nothing(self):
        result = preview(self.store, BANK, None, Options(), TODAY)
        self.assertEqual((result["ready"], result["duplicates"], result["problem"]), (3, 0, None))
        self.assertEqual(result["sample"][0]["description"], "TRADER JOE'S #123")
        self.assertEqual(self.store.transaction_count(), 0)

    def test_positive_means_expense_for_credit_cards(self):
        text = "Date,Description,Amount\n11/03/2026,Charge,25.00\n11/04/2026,Payment,-100.00\n"
        run(self.store, text, positive_is="expense")
        kinds = {t.description: t.kind for t in self.store.transactions()}
        self.assertEqual(kinds, {"Charge": Kind.EXPENSE, "Payment": Kind.INCOME})


@unittest.skipIf(TestClient is None, "install requirements.txt to test the web API")
class ImportApiTests(unittest.TestCase):
    def test_preview_then_import(self):
        with tempfile.TemporaryDirectory() as folder:
            app = create_app(os.path.join(folder, "f.db"), provider=FakeProvider({}),
                             today=lambda: TODAY, static_dir=None)
            with TestClient(app) as client:
                first = client.post("/api/import/preview", json={"csv": BANK}).json()
                self.assertEqual(first["mapping"]["amount"], "Amount")
                self.assertEqual(first["ready"], 3)

                # Importing needs the confirmed mapping.
                self.assertEqual(client.post("/api/import", json={"csv": BANK}).status_code, 400)
                done = client.post("/api/import", json={
                    "csv": BANK, "mapping": first["mapping"], "options": {"default_category": "Imported"},
                }).json()
                self.assertEqual(done["imported"], 3)
                cats = {t["category"] for t in client.get("/api/transactions").json()["items"]}
                self.assertEqual(cats, {"Imported"})

                again = client.post("/api/import/preview", json={"csv": BANK, "mapping": first["mapping"]}).json()
                self.assertEqual((again["ready"], again["duplicates"]), (0, 3))

                bad = client.post("/api/import/preview", json={
                    "csv": BANK, "mapping": {**first["mapping"], "amount": None}}).json()
                self.assertIn("amount column", bad["problem"])
                self.assertEqual(client.post("/api/import/preview", json={"csv": ""}).status_code, 400)


if __name__ == "__main__":
    unittest.main()
