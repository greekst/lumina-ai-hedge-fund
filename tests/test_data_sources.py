"""Phase 4(a): Finnhub adapter with automatic yfinance fallback on HTTP 403 (offline, mocked HTTP)."""
import numpy as np
import pandas as pd
import pytest

from core.ai_hedge_fund import data_sources as ds
from core.ai_hedge_fund.data_sources import FinnhubSource


class _Resp:
    def __init__(self, code, js=None):
        self.status_code, self._js = code, js or {}

    def json(self):
        return self._js

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


PAYLOADS = {
    "quote": {"c": 101.0, "pc": 100.0},
    "stock/profile2": {"name": "Test Inc", "currency": "USD", "finnhubIndustry": "Tech", "marketCapitalization": 2000.0},
    "stock/metric": {"metric": {"peTTM": 25.0, "pbQuarterly": 4.0, "roeTTM": 30.0, "revenueGrowthTTMYoy": 12.0,
                                "currentDividendYieldTTM": 0.5, "52WeekHigh": 120.0, "52WeekLow": 80.0, "epsTTM": 4.04}},
}


@pytest.fixture
def finnhub(monkeypatch):
    calls = []
    forbidden = set()

    def fake_get(url, params=None, timeout=None):
        ep = url.split("/api/v1/")[1]
        calls.append(ep)
        if ep in forbidden or ep == "stock/candle":
            return _Resp(403, {"error": "You don't have access to this resource."})
        return _Resp(200, PAYLOADS.get(ep, {}))

    import requests
    monkeypatch.setattr(requests, "get", fake_get)
    monkeypatch.setenv("FINNHUB_API_KEY", "dummy")
    FinnhubSource.reset()
    yield calls, forbidden
    FinnhubSource.reset()


def test_provider_selection(monkeypatch):
    monkeypatch.delenv("LUMINA_DATA_PROVIDER", raising=False)
    monkeypatch.setenv("FINNHUB_API_KEY", "x")
    assert ds.get_provider() == "finnhub"
    monkeypatch.setenv("LUMINA_DATA_PROVIDER", "yfinance")
    assert ds.get_provider() == "yfinance"
    monkeypatch.delenv("LUMINA_DATA_PROVIDER")
    monkeypatch.delenv("FINNHUB_API_KEY")
    assert ds.get_provider() == "yfinance"


def test_finnhub_fields_and_sources(finnhub):
    fields, sources, log = FinnhubSource.stock_snapshot("TEST")
    assert fields["current_price"] == 101.0 and sources["current_price"] == "finnhub /quote"
    assert fields["market_cap"] == pytest.approx(2.0e9)  # Finnhub reports millions
    assert fields["pe_trailing"] == 25.0 and sources["roe"] == "finnhub /stock/metric"
    assert any("stock/candle HTTP 403" in line and "yfinance" in line for line in log)


def test_403_falls_back_and_is_memoised(finnhub):
    calls, forbidden = finnhub
    forbidden.add("stock/metric")
    fields, sources, log = FinnhubSource.stock_snapshot("TEST")
    assert "pe_trailing" not in fields and any("stock/metric HTTP 403" in line for line in log)
    n_metric = calls.count("stock/metric")
    FinnhubSource.stock_snapshot("TEST")
    assert calls.count("stock/metric") == n_metric  # not retried after a 403
    assert calls.count("stock/candle") == 1


def test_non_us_symbols_skip_finnhub(finnhub):
    calls, _ = finnhub
    fields, _, log = FinnhubSource.stock_snapshot("7203.T")
    assert fields == {} and calls == [] and "not covered" in log[0]


def test_market_data_feed_overlays_finnhub_and_falls_back(finnhub, monkeypatch, ohlcv):
    """Integration: Finnhub wins where it answers; yfinance fills what Finnhub refused (403)."""
    _, forbidden = finnhub
    forbidden.add("stock/metric")
    monkeypatch.setenv("LUMINA_DATA_PROVIDER", "finnhub")

    class FakeTicker:
        def __init__(self, sym):
            self.info = {"trailingPE": 19.0, "priceToBook": 3.0, "returnOnEquity": 0.21, "currency": "USD",
                         "longName": "Test (yf)", "currentPrice": 99.0}

        def history(self, period="1y"):
            return ohlcv

    import core.ai_hedge_fund.market_data_feed as mdf
    monkeypatch.setattr(mdf.yf, "Ticker", FakeTicker)
    d = mdf.MarketDataFeed.get_stock_data("TEST", force_refresh=True)
    assert d["current_price"] == 101.0 and d["data_sources"]["current_price"] == "finnhub /quote"
    assert d["company_name"] == "Test Inc"
    assert d["pe_trailing"] == 19.0 and d["data_sources"]["pe_trailing"] == "yfinance Ticker.info"  # fallback
    assert d["roe"] == pytest.approx(21.0)
    assert any("403" in line for line in d["data_source_log"])
    # the council report tags each field with the source that actually produced it
    from core.reporting.council_report import build_from_council
    from core.reporting.tagged import untagged_numbers
    md = build_from_council({"symbol": "TEST", "stock_data": d, "current_price": d["current_price"],
                             "council_dialogues": [], "verdict": {}}).to_markdown()
    assert "finnhub /quote" in md and "yfinance Ticker.info" in md and untagged_numbers(md) == []
