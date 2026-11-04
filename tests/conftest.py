"""Shared pytest setup: offline, deterministic, isolated state."""
import os
import sys

import numpy as np
import pandas as pd
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# Must be set before core modules read them.
os.environ["LUMINA_LLM_MODE"] = "mock"
os.environ["LUMINA_TEST_MODE"] = "1"
os.environ["LUMINA_DATA_PROVIDER"] = "yfinance"  # no live Finnhub calls from tests (adapter tests mock HTTP)
os.environ.pop("LUMINA_ALLOW_LIVE_BROKER", None)
os.environ.pop("LUMINA_ENABLE_SOCIAL_POSTING", None)


def pytest_configure(config):
    config.addinivalue_line("markers", "network: needs internet (skipped unless LUMINA_NETWORK_TESTS=1)")


def pytest_collection_modifyitems(config, items):
    if os.getenv("LUMINA_NETWORK_TESTS") == "1":
        return
    skip = pytest.mark.skip(reason="network test (set LUMINA_NETWORK_TESTS=1)")
    for item in items:
        if "network" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(autouse=True)
def _isolated_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("LUMINA_DATA_DIR", str(tmp_path / "lumina"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    yield


@pytest.fixture
def ohlcv():
    """Deterministic synthetic daily OHLCV (seeded), 120 business days."""
    rng = np.random.default_rng(7)
    n = 120
    idx = pd.bdate_range("2024-01-01", periods=n)
    close = 100.0 * np.cumprod(1.0 + rng.normal(0.0005, 0.015, n))
    open_ = close * (1.0 + rng.normal(0.0, 0.004, n))
    high = np.maximum(open_, close) * (1.0 + np.abs(rng.normal(0.0, 0.006, n)))
    low = np.minimum(open_, close) * (1.0 - np.abs(rng.normal(0.0, 0.006, n)))
    vol = rng.integers(1_000_000, 5_000_000, n).astype(float)
    return pd.DataFrame({"Open": open_, "High": high, "Low": low, "Close": close, "Volume": vol}, index=idx)


@pytest.fixture
def paper_engine(tmp_path):
    from core.ai_hedge_fund.broker_client import PaperTradingEngine
    eng = PaperTradingEngine(db_path=str(tmp_path / "ledger.db"))
    eng.reset_portfolio(initial_jpy=1_000_000.0, initial_usd=100_000.0)
    return eng
