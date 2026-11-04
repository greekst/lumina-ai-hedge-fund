# -*- coding: utf-8 -*-
"""
data_sources.py — Finnhub adapter behind MarketDataFeed, with automatic fallback to yfinance.

Provider selection (LUMINA_DATA_PROVIDER):
  finnhub   Finnhub first for quote / profile / fundamentals; yfinance for anything Finnhub
            refuses (HTTP 403 = endpoint not in plan), errors on, or does not cover.
  yfinance  upstream behaviour (yfinance only).
  unset     finnhub if FINNHUB_API_KEY is set, else yfinance.

Every field records which source produced it (`data_sources`), and every fallback is logged
(`data_source_log`) so reports can tag numbers with the true source (hard rule 5).
Non-US symbols (e.g. 7203.T, ASML.AS) go straight to yfinance (not covered by Finnhub free tier).
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("lumina.data_sources")

FINNHUB_URL = "https://finnhub.io/api/v1"


def get_provider() -> str:
    p = os.getenv("LUMINA_DATA_PROVIDER", "").strip().lower()
    if p in ("finnhub", "yfinance"):
        return p
    return "finnhub" if os.getenv("FINNHUB_API_KEY", "").strip() else "yfinance"


class EndpointForbidden(Exception):
    """Raised for HTTP 403 (endpoint not included in the API plan)."""


class FinnhubSource:
    _forbidden: Dict[str, str] = {}   # endpoint -> first 403 message (memoised per process)
    _lock = threading.Lock()
    TIMEOUT = 10

    @classmethod
    def reset(cls) -> None:
        with cls._lock:
            cls._forbidden.clear()

    @classmethod
    def _get(cls, endpoint: str, params: Dict[str, Any]) -> Dict[str, Any]:
        if endpoint in cls._forbidden:
            raise EndpointForbidden(cls._forbidden[endpoint])
        key = os.getenv("FINNHUB_API_KEY", "").strip()
        if not key:
            raise RuntimeError("FINNHUB_API_KEY not set")
        import requests
        r = requests.get(f"{FINNHUB_URL}/{endpoint}", params=dict(params, token=key), timeout=cls.TIMEOUT)
        if r.status_code == 403:
            msg = f"finnhub /{endpoint} HTTP 403 (not in plan)"
            with cls._lock:
                cls._forbidden[endpoint] = msg
            raise EndpointForbidden(msg)
        r.raise_for_status()
        return r.json() or {}

    @staticmethod
    def covers(symbol: str) -> bool:
        return "." not in symbol and not symbol.startswith("^") and not symbol.isdigit()

    @classmethod
    def stock_snapshot(cls, symbol: str) -> Tuple[Dict[str, Any], Dict[str, str], List[str]]:
        """Return (fields, field->source, log). Missing/failed groups simply leave fields absent."""
        fields: Dict[str, Any] = {}
        sources: Dict[str, str] = {}
        log: List[str] = []
        if not cls.covers(symbol):
            log.append(f"{symbol}: not covered by Finnhub adapter -> yfinance")
            return fields, sources, log

        def take(group: str, endpoint: str, params: Dict[str, Any], mapping: Dict[str, Tuple[str, float]]) -> None:
            try:
                js = cls._get(endpoint, params)
            except EndpointForbidden as e:
                log.append(f"{symbol}: {e} -> yfinance fallback for {group}")
                return
            except Exception as e:  # network / 5xx / parse
                log.append(f"{symbol}: finnhub /{endpoint} error ({type(e).__name__}) -> yfinance fallback for {group}")
                return
            src = js.get("metric", js) if endpoint == "stock/metric" else js
            for out_key, (in_key, scale) in mapping.items():
                v = src.get(in_key)
                if isinstance(v, (int, float)) and not isinstance(v, bool) and v != 0:
                    fields[out_key] = float(v) * scale
                    sources[out_key] = f"finnhub /{endpoint}"
                elif isinstance(v, str) and v:
                    fields[out_key] = v
                    sources[out_key] = f"finnhub /{endpoint}"

        take("quote", "quote", {"symbol": symbol},
             {"current_price": ("c", 1.0), "previous_close": ("pc", 1.0)})
        take("profile", "stock/profile2", {"symbol": symbol},
             {"company_name": ("name", 1.0), "currency": ("currency", 1.0), "sector": ("finnhubIndustry", 1.0),
              "market_cap": ("marketCapitalization", 1e6)})
        take("fundamentals", "stock/metric", {"symbol": symbol, "metric": "all"},
             {"pe_trailing": ("peTTM", 1.0), "pb_ratio": ("pbQuarterly", 1.0), "roe": ("roeTTM", 1.0),
              "revenue_growth": ("revenueGrowthTTMYoy", 1.0), "dividend_yield": ("currentDividendYieldTTM", 1.0),
              "fifty_two_week_high": ("52WeekHigh", 1.0), "fifty_two_week_low": ("52WeekLow", 1.0),
              "eps": ("epsTTM", 1.0)})
        # Daily candles: premium on Finnhub; try once per process, memoised 403 afterwards.
        try:
            now = int(time.time())
            cls._get("stock/candle", {"symbol": symbol, "resolution": "D", "from": now - 86400 * 5, "to": now})
            log.append(f"{symbol}: finnhub candles available (history still computed from yfinance for consistency)")
        except EndpointForbidden as e:
            log.append(f"{symbol}: {e} -> yfinance history")
        except Exception as e:
            log.append(f"{symbol}: finnhub candles error ({type(e).__name__}) -> yfinance history")
        for line in log:
            logger.info("[data_source] %s", line)
        return fields, sources, log
