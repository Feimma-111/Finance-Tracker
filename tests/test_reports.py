import unittest
from datetime import datetime, timezone

from finance_tracker.models import AssetType, Holding
from finance_tracker.prices import PriceUnavailable, Quote
from finance_tracker.reports import bar, month_range, monthly_report, value_holdings

NOW = datetime(2026, 11, 22, tzinfo=timezone.utc)


class MonthlyReportTests(unittest.TestCase):
    def test_empty(self):
        report = monthly_report([], current_month="2026-11")
        self.assertEqual(report.rows, [])

    def test_gaps_filled_and_current_month_excluded_from_baseline(self):
        totals = [("2026-07", 10000), ("2026-09", 20000), ("2026-11", 99999)]
        report = monthly_report(totals, current_month="2026-11")

        self.assertEqual(
            [(r.month, r.total_cents) for r in report.rows],
            [("2026-07", 10000), ("2026-08", 0), ("2026-09", 20000),
             ("2026-10", 0), ("2026-11", 99999)],
        )
        self.assertEqual(report.mean_cents, 7500)  # (100 + 0 + 200 + 0) / 4, Nov excluded
        self.assertTrue(report.rows[-1].in_progress)
        self.assertIsNone(report.rows[-1].z_score)
        self.assertEqual(report.rows[-1].label, "in progress")
        self.assertEqual(report.rows[2].label, "above usual")  # September stands out

    def test_window_ignores_ancient_history(self):
        # One stray entry from 2000 shouldn't produce 300 months of zeros.
        report = monthly_report([("2000-01", 500), ("2026-10", 100)], current_month="2026-11")
        self.assertEqual(report.rows[0].month, "2025-12")
        self.assertEqual(len(report.rows), 12)

    def test_single_completed_month_has_no_stdev(self):
        report = monthly_report([("2026-10", 100)], current_month="2026-11")
        self.assertEqual(report.mean_cents, 100)
        self.assertIsNone(report.stdev_cents)

    def test_month_range(self):
        self.assertEqual(month_range("2025-11", "2026-02"),
                         ["2025-11", "2025-12", "2026-01", "2026-02"])


class NetWorthTests(unittest.TestCase):
    def test_values_each_kind_of_holding(self):
        holdings = [
            Holding(AssetType.CASH, "Checking", manual_value_cents=150000),
            Holding(AssetType.STOCK, "Apple", 2.5, symbol="AAPL"),
            Holding(AssetType.GOLD, "Gold", 0.1, symbol="GC=F"),
        ]
        prices = {"AAPL": 342.56, "GC=F": 3614.30}
        report = value_holdings(holdings, lambda s: Quote(s, prices[s], "USD", NOW))

        self.assertEqual([line.value_cents for line in report.lines], [150000, 85640, 36143])
        self.assertEqual(report.total_cents, 150000 + 85640 + 36143)
        self.assertTrue(report.complete)

    def test_missing_stale_and_foreign_prices(self):
        holdings = [
            Holding(AssetType.STOCK, "Gone", 1, symbol="GONE"),
            Holding(AssetType.STOCK, "Old", 1, symbol="OLD"),
            Holding(AssetType.STOCK, "Euro", 1, symbol="EURO"),
        ]

        def quote(symbol):
            if symbol == "GONE":
                raise PriceUnavailable("no market data for 'GONE'")
            if symbol == "OLD":
                return Quote(symbol, 10.0, "USD", NOW, stale=True)
            return Quote(symbol, 10.0, "EUR", NOW)

        report = value_holdings(holdings, quote)
        self.assertEqual([line.value_cents for line in report.lines], [None, 1000, None])
        self.assertIn("no market data", report.lines[0].note)
        self.assertIn("offline", report.lines[1].note)
        self.assertIn("EUR", report.lines[2].note)
        self.assertEqual(report.total_cents, 1000)
        self.assertFalse(report.complete)


class BarTests(unittest.TestCase):
    def test_bar(self):
        self.assertEqual(bar(50, 100, width=10), "█████")
        self.assertEqual(bar(1, 1000, width=10), "█")  # tiny but visible
        self.assertEqual(bar(0, 100), "")


if __name__ == "__main__":
    unittest.main()
