"""SEC EDGAR client/parser: offline, synthetic fixtures (no network, no User-Agent needed)."""
import pandas as pd
import pytest

from backtest import edgar
from backtest.sec_crosscheck import match_8k, rel_diff, resolve_decision_session


def _subs():
    return [
        {"accessionNumber": "0000000001-25-000001", "form": "10-Q", "filingDate": "2025-05-02",
         "acceptanceDateTime": "2025-05-02T10:00:46.000Z", "items": ""},
        {"accessionNumber": "0000000001-25-000002", "form": "8-K", "filingDate": "2025-05-01",
         "acceptanceDateTime": "2025-05-01T20:30:21.000Z", "items": "2.02,9.01"},
        {"accessionNumber": "0000000001-25-000003", "form": "8-K", "filingDate": "2025-05-03",
         "acceptanceDateTime": "2025-05-03T20:30:21.000Z", "items": "5.02"},
    ]


def _facts():
    a = "0000000001-25-000001"
    row = lambda start, end, val, fp="Q2": dict(start=start, end=end, val=val, accn=a, fp=fp, form="10-Q", filed="2025-05-02")  # noqa: E731
    return {"facts": {"us-gaap": {
        "NetIncomeLoss": {"units": {"USD": [
            row("2025-01-01", "2025-06-30", 60.0),          # YTD (Q2)
            row("2024-07-01", "2025-06-30", 130.0),         # TTM column (AMZN-style) -> must be ignored
            row("2025-04-01", "2025-06-30", 35.0),          # 3-month
            row("2024-01-01", "2024-06-30", 50.0),          # prior-year comparative (different end)
        ]}},
        "Revenues": {"units": {"USD": [row("2025-01-01", "2025-06-30", 600.0)]}},
        "StockholdersEquity": {"units": {"USD": [dict(end="2025-06-30", val=1000.0, accn=a, fp="Q2", form="10-Q",
                                                      filed="2025-05-02")]}},
        "EarningsPerShareDiluted": {"units": {"USD/shares": [row("2025-01-01", "2025-06-30", 0.6)]}},
    }}}


def test_acceptance_is_converted_from_utc_to_new_york():
    assert edgar.to_et("2025-01-30T21:30:23.000Z") == "2025-01-30 16:30:23"   # EST
    assert edgar.to_et("2025-07-31T20:30:25.000Z") == "2025-07-31 16:30:25"   # EDT


def test_companyfacts_record_is_ytd_and_keyed_by_acceptance():
    recs = edgar.fundamentals_from_companyfacts(_facts(), _subs())
    assert len(recs) == 1
    r = recs[0]
    assert (r["start"], r["end"]) == ("2025-01-01", "2025-06-30")
    assert r["net_income"] == 60.0 and r["revenue"] == 600.0 and r["equity"] == 1000.0 and r["eps_diluted"] == 0.6
    assert r["accepted_at"] == "2025-05-02 06:00:46"
    assert r["net_income_concept"] == "us-gaap_NetIncomeLoss"


def test_filing_without_acceptance_time_is_dropped():
    subs = [s for s in _subs() if s["form"] != "10-Q"]
    assert edgar.fundamentals_from_companyfacts(_facts(), subs) == []


def test_earnings_8k_keeps_only_item_202():
    k8 = edgar.earnings_8k(_subs())
    assert [e["accession"] for e in k8] == ["0000000001-25-000002"]
    assert k8[0]["accepted_at_et"] == "2025-05-01 16:30:21"


def test_event_time_is_the_earlier_of_8k_and_vendor():
    s = pd.bdate_range("2024-07-01", "2024-08-31")
    # SCHW pattern: release ~07:00, 8-K accepted 16:17 the same day. The 8-K alone would put D on
    # the release day, whose close already contains the news -> look-ahead. Earlier timestamp wins.
    D, rule = resolve_decision_session(s, "2024-07-16 16:17:00", "2024-07-16 07:00")
    assert D == pd.Timestamp("2024-07-15") and rule.startswith("vendor")
    # AMZN pattern: vendor placeholder "12:00", 8-K 16:06 -> earlier (vendor) D: one session early, never late
    D, _ = resolve_decision_session(s, "2024-08-01 16:06:02", "2024-08-01 12:00")
    assert D == pd.Timestamp("2024-07-31")
    D, rule = resolve_decision_session(s, "2024-08-01 06:30:00", "2024-08-01 16:00")
    assert D == pd.Timestamp("2024-07-31") and rule.startswith("8-K")
    D, rule = resolve_decision_session(s, None, "2024-08-01 07:00")
    assert D == pd.Timestamp("2024-07-31") and rule.startswith("vendor")
    # only Item 2.02 filings within three days count as the same release
    assert match_8k("2024-08-01 16:00", [{"accepted_at_et": "2024-08-05 16:00:00"}]) is None
    assert match_8k("2024-08-01 16:00", [{"accepted_at_et": "2024-08-02 09:00:00"}]) is not None


def test_missing_user_agent_refuses_network(tmp_path):
    c = edgar.EdgarClient(user_agent="", cache_dir=str(tmp_path))
    with pytest.raises(edgar.EdgarUnavailable):
        c.get_json("https://data.sec.gov/api/xbrl/companyfacts/CIK0000000001.json")
    off = edgar.EdgarClient(user_agent="x", cache_dir=str(tmp_path), offline=True)
    with pytest.raises(edgar.EdgarUnavailable):
        off.get_json("https://data.sec.gov/x.json")


def test_rel_diff():
    assert rel_diff(100.0, 101.0) == pytest.approx(0.0099, abs=1e-4)
    assert rel_diff(0.0, 0.0) == 0.0
