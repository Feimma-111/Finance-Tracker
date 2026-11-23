"""Live market prices with an offline-friendly cache.

Prices come from Yahoo Finance's public chart endpoint (no API key needed).
It's unofficial, so everything else talks to the ``PriceProvider`` interface:
swapping in another source later (Alpha Vantage, Finnhub, ...) means writing
one new class with a ``fetch`` method.

``PriceService`` answers the question "what if I'm offline or the API is
down?": fresh cached prices are reused, and when a fetch fails the last known
price is returned and marked stale instead of crashing.
"""

from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Tuple

try:  # Python 3.8+
    from typing import Protocol
except ImportError:  # pragma: no cover
    Protocol = object  # type: ignore


class PriceUnavailable(Exception):
    """No price could be fetched and none is cached."""


class PriceProvider(Protocol):
    def fetch(self, symbol: str) -> Tuple[float, str]:
        """Return (price, currency) or raise PriceUnavailable."""
        ...


def _tls_context() -> ssl.SSLContext:
    """Certificate checking for HTTPS.

    Python from python.org on macOS doesn't trust any certificates until its
    "Install Certificates" step is run. If ``certifi`` (installed with the web
    packages) is available, use its up-to-date bundle so prices work either way.
    Verification is never turned off.
    """
    try:
        import certifi
    except ImportError:
        return ssl.create_default_context()
    return ssl.create_default_context(cafile=certifi.where())


class YahooPriceProvider:
    URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=1d&interval=1d"

    def __init__(self, timeout: float = 8.0) -> None:
        self.timeout = timeout
        self.tls = _tls_context()

    def fetch(self, symbol: str) -> Tuple[float, str]:
        url = self.URL.format(symbol=urllib.parse.quote(symbol, safe=""))
        request = urllib.request.Request(
            url, headers={"User-Agent": "Mozilla/5.0 (personal finance tracker)"}
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout, context=self.tls) as response:
                payload = json.load(response)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                raise PriceUnavailable(f"no market data for '{symbol}'") from exc
            raise PriceUnavailable(f"price service returned HTTP {exc.code}") from exc
        except (urllib.error.URLError, OSError, ValueError) as exc:
            raise PriceUnavailable(f"couldn't reach the price service ({exc})") from exc
        return self.parse(symbol, payload)

    @staticmethod
    def parse(symbol: str, payload: Any) -> Tuple[float, str]:
        try:
            result = payload["chart"]["result"]
            if not result:
                raise PriceUnavailable(f"no market data for '{symbol}'")
            meta = result[0]["meta"]
            price = float(meta["regularMarketPrice"])
            currency = str(meta.get("currency") or "USD").upper()
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise PriceUnavailable(f"unexpected response for '{symbol}'") from exc
        if price <= 0:
            raise PriceUnavailable(f"got a non-positive price for '{symbol}'")
        return price, currency


@dataclass(frozen=True)
class Quote:
    symbol: str
    price: float
    currency: str
    fetched_at: datetime
    stale: bool = False  # True when the live fetch failed and this is the last known price


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class PriceService:
    def __init__(
        self,
        store: Any,  # finance_tracker.store.Store (typed loosely to avoid a circular import)
        provider: PriceProvider,
        *,
        max_age: timedelta = timedelta(minutes=15),
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self.store = store
        self.provider = provider
        self.max_age = max_age
        self.clock = clock

    def quote(self, symbol: str) -> Quote:
        symbol = symbol.upper()
        cached = self.store.cached_price(symbol)
        now = self.clock()
        if cached and now - cached[2] < self.max_age:
            return Quote(symbol, cached[0], cached[1], cached[2])
        try:
            price, currency = self.provider.fetch(symbol)
        except PriceUnavailable:
            if cached:
                return Quote(symbol, cached[0], cached[1], cached[2], stale=True)
            raise
        self.store.save_price(symbol, price, currency, now)
        return Quote(symbol, price, currency, now)
