"""Hard rule 5: every number in a generated report carries source + as_of, and is labelled
SOURCED FACT or MODEL ASSUMPTION. These tests fail if any report emits an untagged number."""
import glob
import os

import pytest

from core.reporting.council_report import Report, build_from_council, build_from_pit, redact_numbers
from core.reporting.tagged import MODEL_ASSUMPTION, SOURCED_FACT, Tagged, assumption, fact, untagged_numbers

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SNAP = os.path.join(ROOT, "backtest", "snapshots", "2026-11-04")


def test_tagged_requires_source_and_date():
    with pytest.raises(ValueError):
        Tagged(1.0, "", "2026-01-01")
    with pytest.raises(ValueError):
        Tagged(1.0, "yfinance", "yesterday")
    with pytest.raises(ValueError):
        Tagged(1.0, "yfinance", "2026-01-01", kind="GUESS")
    assert fact(24.1, "yfinance", "2026-11-03", label="P/E", decimals=1).render() == \
        "P/E 24.1 [SOURCED FACT · yfinance, 2026-11-03]"


def test_validator_flags_untagged_numbers():
    assert untagged_numbers("| P/E | 24.1 |") == [(1, "24.1")]
    assert untagged_numbers("The price rose 3% today") == [(1, "3")]
    assert untagged_numbers("| P/E | 24.1 [SOURCED FACT · yfinance, 2026-11-03] |") == []
    assert untagged_numbers("| P/E | n/a [SOURCED FACT · yfinance, 2026-11-03] |") == []
    assert untagged_numbers("# Heading 2026\n| RSI 14 | 55.0 [MODEL ASSUMPTION · x, 2026-01-01] |") == []


def test_section_rejects_raw_numbers_and_redacts_prose():
    rep = Report("t", "2026-01-01")
    sec = rep.section("s")
    with pytest.raises(TypeError):
        sec.add("raw", 12.5)
    sec.text("prose", "ROE is 25% and P/E 30x")
    assert "25" not in rep.to_markdown() and "‹n›" in rep.to_markdown()
    assert redact_numbers("up 3.5% on 1,000 shares") == "up ‹n›% on ‹n› shares"


def _fake_ai_res():
    return {
        "symbol": "TEST", "current_price": 101.5, "timestamp": "2026-11-03 10:00:00",
        "stock_data": {"symbol": "TEST", "currency": "USD", "fetched_at": "2026-11-03 09:59:00", "pe_trailing": 24.1,
                       "pb_ratio": 3.2, "roe": 18.0, "revenue_growth": 7.5, "market_cap": 1.2e12, "dividend_yield": 0.8,
                       "history_metrics": {"atr_pct": 2.1}},
        "deterministic_metrics": {"volatility_20d_annualized_pct": 22.0, "max_drawdown_pct": -12.0, "sharpe_ratio_1y": 0.9,
                                  "rsi_14": 55.0, "var_95_daily_pct": -2.1, "high_52w": 120.0, "low_52w": 80.0},
        "timesfm_forecast": {"expected_return_pct": 1.2, "downside_risk_prob": 14.0},
        "chronos_forecast": {"expected_return_pct": 0.8},
        "council_dialogues": [
            {"agent_id": "buffett", "name": "Buffett", "stance": "BULLISH", "score": 80,
             "dialogue": "ROE of 18% is great; I expect 25% upside"},
            {"agent_id": "risk_manager", "name": "CRO", "stance": "NEUTRAL", "score": 70, "stop_loss_price": 95.0,
             "max_allocation_pct": 10.0, "veto_triggered": False},
        ],
        "verdict": {"action": "ACCUMULATE", "confidence_score": 66, "allocation_pct": 7.0, "target_price": 116.7,
                    "stop_loss_price": 95.0, "thesis_summary": "Model prose citing 42% growth."},
    }


def test_live_council_report_is_fully_tagged():
    rep = build_from_council(_fake_ai_res())
    md = rep.to_markdown()
    assert untagged_numbers(md) == []
    assert "42" not in md  # numbers in model prose redacted
    kinds = {t.kind for t in rep.tagged_values()}
    assert kinds == {SOURCED_FACT, MODEL_ASSUMPTION}
    for t in rep.tagged_values():
        assert t.source and t.as_of[:4].isdigit()
    forecast = [t for s in rep.sections if s.heading.startswith("Forecasts") for t in
                [r.value for r in s.rows if isinstance(r.value, Tagged)]]
    assert forecast and all(t.kind == MODEL_ASSUMPTION for t in forecast)


@pytest.mark.skipif(not os.path.exists(SNAP), reason="snapshot not present")
def test_pit_report_is_fully_tagged_and_dated_before_decision():
    rep = build_from_pit(SNAP, "MSFT", -2)
    md = rep.to_markdown()
    assert untagged_numbers(md) == []
    pre_outcome = [r.value for s in rep.sections if not s.heading.startswith("Outcome") for r in s.rows
                   if isinstance(r.value, Tagged)]
    # point-in-time: nothing used for the decision is dated after the report's as_of
    assert all(t.as_of[:10] <= rep.as_of for t in pre_outcome)


def test_every_committed_report_is_tagged():
    files = glob.glob(os.path.join(ROOT, "reports", "**", "*.md"), recursive=True) + \
        glob.glob(os.path.join(ROOT, "results", "*_summary.md"))
    assert files, "expected committed example reports / summaries"
    for f in files:
        with open(f, encoding="utf-8") as fh:
            assert untagged_numbers(fh.read()) == [], f
