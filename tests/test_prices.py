import unittest
from datetime import datetime, timedelta, timezone

from finance_tracker.prices import PriceService, PriceUnavailable, YahooPriceProvider
from finance_tracker.store import Store


class FakeProvider:
    def __init__(self, prices):
        self.prices = prices
        self.calls = 0

    def fetch(self, symbol):
        self.calls += 1
        if symbol not in self.prices:
            raise PriceUnavailable(f"no market data for '{symbol}'")
        return self.prices[symbol], "USD"


class FakeClock:
    def __init__(self):
        self.now = datetime(2026, 11, 22, 12, 0, tzinfo=timezone.utc)

    def __call__(self):
        return self.now


class PriceServiceTests(unittest.TestCase):
    def setUp(self):
        self.store = Store(":memory:")
        self.provider = FakeProvider({"AAPL": 342.56})
        self.clock = FakeClock()
        self.service = PriceService(self.store, self.provider, clock=self.clock)

    def tearDown(self):
        self.store.close()

    def test_fresh_cache_avoids_network(self):
        self.assertEqual(self.service.quote("aapl").price, 342.56)
        self.clock.now += timedelta(minutes=5)
        self.service.quote("AAPL")
        self.assertEqual(self.provider.calls, 1)

    def test_old_cache_refetches(self):
        self.service.quote("AAPL")
        self.provider.prices["AAPL"] = 350.0
        self.clock.now += timedelta(hours=1)
        quote = self.service.quote("AAPL")
        self.assertEqual(quote.price, 350.0)
        self.assertFalse(quote.stale)
        self.assertEqual(self.provider.calls, 2)

    def test_offline_falls_back_to_last_known_price(self):
        self.service.quote("AAPL")
        del self.provider.prices["AAPL"]  # simulate the API failing
        self.clock.now += timedelta(days=1)
        quote = self.service.quote("AAPL")
        self.assertTrue(quote.stale)
        self.assertEqual(quote.price, 342.56)

    def test_no_cache_and_no_network_raises(self):
        with self.assertRaises(PriceUnavailable):
            self.service.quote("NOPE")


class YahooParsingTests(unittest.TestCase):
    def test_parse_good_payload(self):
        payload = {"chart": {"result": [{"meta": {"regularMarketPrice": 342.56, "currency": "USD"}}]}}
        self.assertEqual(YahooPriceProvider.parse("AAPL", payload), (342.56, "USD"))

    def test_parse_bad_payloads(self):
        for payload in [
            {"chart": {"result": None, "error": {"code": "Not Found"}}},
            {"chart": {"result": [{"meta": {}}]}},
            {"unexpected": True},
            {"chart": {"result": [{"meta": {"regularMarketPrice": 0}}]}},
        ]:
            with self.subTest(payload=payload):
                with self.assertRaises(PriceUnavailable):
                    YahooPriceProvider.parse("X", payload)


if __name__ == "__main__":
    unittest.main()
