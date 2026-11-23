import unittest
from datetime import date

from finance_tracker.models import (
    AssetType,
    Holding,
    Transaction,
    cents_to_plain,
    format_money,
    parse_date,
    parse_money,
    parse_month,
    shift_month,
)

TODAY = date(2026, 11, 22)


class MoneyTests(unittest.TestCase):
    def test_parse_money_accepts_common_formats(self):
        self.assertEqual(parse_money("4.50"), 450)
        self.assertEqual(parse_money("$1,234.5"), 123450)
        self.assertEqual(parse_money(" 12 "), 1200)
        self.assertEqual(parse_money("0.1"), 10)

    def test_parse_money_rejects_bad_input(self):
        for bad in ["", "ten", "1.234", "nan", "inf", "1e30"]:
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    parse_money(bad)

    def test_format_money(self):
        self.assertEqual(format_money(123450), "$1,234.50")
        self.assertEqual(format_money(5), "$0.05")
        self.assertEqual(format_money(-500), "-$5.00")
        self.assertEqual(cents_to_plain(123405), "1234.05")


class DateTests(unittest.TestCase):
    def test_parse_date_formats(self):
        self.assertEqual(parse_date("2026-07-03", today=TODAY), date(2026, 7, 3))
        self.assertEqual(parse_date("2026/7/3", today=TODAY), date(2026, 7, 3))
        self.assertEqual(parse_date("", today=TODAY), TODAY)
        self.assertEqual(parse_date("yesterday", today=TODAY), date(2026, 11, 21))

    def test_parse_date_rejects_future_and_garbage(self):
        for bad in ["2026-12-01", "July 3", "2026-13-01"]:
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    parse_date(bad, today=TODAY)

    def test_months(self):
        self.assertEqual(parse_month("2026/7"), "2026-07")
        self.assertEqual(shift_month("2026-01", -1), "2025-12")
        self.assertEqual(shift_month("2025-12", 1), "2026-01")
        self.assertEqual(shift_month("2026-03", -14), "2025-01")
        with self.assertRaises(ValueError):
            parse_month("2026-13")


class ValidationTests(unittest.TestCase):
    def test_transaction_requires_positive_amount(self):
        with self.assertRaises(ValueError):
            Transaction("Coffee", 0, "food", TODAY)

    def test_holding_rules(self):
        with self.assertRaises(ValueError):
            Holding(AssetType.STOCK, "Apple", 3)  # no symbol
        with self.assertRaises(ValueError):
            Holding(AssetType.CASH, "Checking")  # no value
        Holding(AssetType.CASH, "Checking", manual_value_cents=0)  # zero is fine


if __name__ == "__main__":
    unittest.main()
