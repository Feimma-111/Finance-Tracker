"""Investment gains: since buying, over a period, today, and the chart series."""

import unittest
from datetime import date, timedelta

from finance_tracker.models import AssetType, Holding
from finance_tracker.portfolio import (
    Return,
    account_balances,
    close_on,
    combine,
    holding_returns,
    period_start,
    value_series,
)

TODAY = date(2026, 11, 23)  # a Monday

# Weekday closes only, like a stock: Fri Nov 20 is the last close before today.
CLOSES = [
    (date(2026, 10, 23), 100.0),
    (date(2026, 11, 13), 110.0),
    (date(2026, 11, 16), 112.0),
    (date(2026, 11, 20), 120.0),
]


def stock(**kw):
    return Holding(AssetType.STOCK, "Apple", kw.pop("quantity", 10), symbol="AAPL", id=kw.pop("id", 1), **kw)


class PortfolioTests(unittest.TestCase):
    def test_period_start(self):
        self.assertEqual(period_start("1W", TODAY, None), date(2026, 11, 16))
        self.assertEqual(period_start("1M", TODAY, None), date(2026, 10, 23))
        self.assertEqual(period_start("YTD", TODAY, None), date(2026, 1, 1))
        self.assertEqual(period_start("1Y", TODAY, None), date(2025, 11, 23))
        self.assertEqual(period_start("ALL", TODAY, date(2024, 3, 1)), date(2024, 3, 1))
        with self.assertRaises(ValueError):
            period_start("5Y", TODAY, None)

    def test_close_on_uses_the_last_trading_day(self):
        self.assertEqual(close_on(CLOSES, date(2026, 11, 22)), 120.0)  # Sunday -> Friday's close
        self.assertEqual(close_on(CLOSES, date(2026, 11, 16)), 112.0)
        self.assertIsNone(close_on(CLOSES, date(2026, 1, 1)))

    def test_returns_for_a_holding_bought_before_the_period(self):
        h = stock(bought_on=date(2026, 1, 5), cost_basis_cents=80000)  # 10 shares at $80
        r = holding_returns(h, 125000, CLOSES, date(2026, 11, 16), TODAY)  # worth $1,250 now ($125)
        self.assertEqual(r.total, Return(45000, 56.2))   # $1,250 - $800
        self.assertEqual(r.period, Return(13000, 11.6))  # since Nov 16 close of $112: $1,250 - $1,120
        self.assertEqual(r.today, Return(5000, 4.2))     # since Friday's $120: $1,250 - $1,200

    def test_bought_during_the_period_counts_from_what_you_paid(self):
        h = stock(bought_on=date(2026, 11, 10), cost_basis_cents=105000)
        r = holding_returns(h, 125000, CLOSES, date(2026, 10, 23), TODAY)
        self.assertEqual(r.period, Return(20000, 19.0))  # not since Oct 23's $100
        # Without a cost, the close on the day it was bought is used instead.
        r = holding_returns(stock(bought_on=date(2026, 11, 13)), 125000, CLOSES, date(2026, 10, 23), TODAY)
        self.assertEqual(r.period, Return(15000, 13.6))
        self.assertIsNone(r.total)

    def test_bought_today_has_no_day_change(self):
        r = holding_returns(stock(bought_on=TODAY, cost_basis_cents=125000), 125000, CLOSES, TODAY, TODAY)
        self.assertIsNone(r.today)
        self.assertEqual(r.period, Return(0, 0.0))

    def test_no_history_means_no_period_or_day_change(self):
        r = holding_returns(stock(), 125000, [], date(2026, 11, 16), TODAY)
        self.assertIsNone(r.period)
        self.assertIsNone(r.today)

    def test_value_series_starts_each_holding_on_its_purchase(self):
        apple = stock(bought_on=date(2026, 11, 14))
        gold = Holding(AssetType.GOLD, "Gold", 1, symbol="GC=F", id=2)
        gold_closes = [(date(2026, 11, 13), 2000.0), (date(2026, 11, 20), 2100.0)]
        series = value_series(
            [(apple, CLOSES, 125000), (gold, gold_closes, 215000)], date(2026, 11, 13), TODAY)
        self.assertEqual(series, [
            (date(2026, 11, 13), 200000),          # gold only; Apple wasn't bought yet
            (date(2026, 11, 16), 112000 + 200000),
            (date(2026, 11, 20), 120000 + 210000),
            (TODAY, 125000 + 215000),              # live values
        ])

    def test_long_series_are_thinned(self):
        closes = [(date(2020, 1, 1) + timedelta(days=i), 100.0) for i in range(2000)]
        series = value_series([(stock(), closes, 100000)], date(2020, 1, 1), TODAY)
        self.assertLessEqual(len(series), 400)
        self.assertEqual(series[-1], (TODAY, 100000))

    def test_combine(self):
        total = combine([Return(1000, 10.0), None, Return(-500, -5.0)], [11000, 3000, 9500])
        self.assertEqual(total, Return(500, 2.5))  # started at $100 + $100 = $200
        self.assertIsNone(combine([None], [100]))

    def test_account_balances(self):
        checking = Holding(AssetType.CASH, "Checking", manual_value_cents=100000, id=7)
        savings = Holding(AssetType.CASH, "Savings", manual_value_cents=500000, id=8)
        self.assertEqual(account_balances([checking, savings], {7: -2550}), {7: 97450, 8: 500000})


if __name__ == "__main__":
    unittest.main()


class PositionTests(unittest.TestCase):
    def test_purchases_of_the_same_investment_are_grouped(self):
        from finance_tracker.portfolio import positions
        first = holding_returns(stock(id=1, quantity=10, bought_on=date(2026, 1, 5), cost_basis_cents=80000),
                                125000, CLOSES, date(2026, 11, 16), TODAY)
        second = holding_returns(stock(id=2, quantity=2, bought_on=date(2026, 11, 13), cost_basis_cents=22000),
                                 25000, CLOSES, date(2026, 11, 16), TODAY)
        gold = holding_returns(Holding(AssetType.GOLD, "Gold", 1, symbol="GC=F", id=3), 300000, [], TODAY, TODAY)
        apple, bullion = positions([first, second, gold])[::-1]  # biggest first: gold, then Apple
        self.assertEqual((bullion.key, apple.key), ("gold:GC=F", "stock:AAPL"))
        self.assertEqual((apple.quantity, apple.value_cents, apple.cost_cents), (12, 150000, 102000))
        self.assertEqual(apple.first_bought, date(2026, 1, 5))
        self.assertEqual([lot.holding.id for lot in apple.lots], [1, 2])
        self.assertEqual(apple.combined("total"), Return(48000, 47.1))  # $1,500 - $1,020
        self.assertIsNone(bullion.cost_cents)
