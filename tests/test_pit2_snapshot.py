# -*- coding: utf-8 -*-
"""Session 4: the new base snapshot `2026-11-04-pit2` (ranking rules v2 + event rules v2, no overlay).

* event rules v2 (review P2-1/P2-2) on synthetic cases taken from the real ones (GE, COST, LIN, BLK, OXY, SCHW-like)
* the snapshot: self-contained, inputs identical to the frozen snapshots, events rebuild offline byte-identically
* event timing (hard rule 4) on the new data path: every event is at or before each of its sources, and an empirical
  detector — the earnings reaction must fall AFTER the decision close, not on it — passes for the 8-K-only events and
  FAILS when those events are deliberately timed one session late (meta-test).
The poisoned-future tests and leak meta-tests of tests/test_pit_snapshot.py also run on this snapshot.
"""

import json
import os

import numpy as np
import pandas as pd
import pytest

from backtest.pit import Snapshot, decision_session
from backtest.snapshot import _safe, _sha256
from backtest.snapshot_pit import eight_k_only_time, earnings_8k_events, resolve_events, resolve_events_v2

SNAPS = os.path.join(os.path.dirname(os.path.dirname(__file__)), "backtest", "snapshots")
NEW, BASE, OVL = (os.path.join(SNAPS, s) for s in ("2026-11-04-pit2", "2026-11-04-pit", "2026-11-04-pit-r1"))
need_snap = pytest.mark.skipif(not os.path.exists(os.path.join(NEW, "manifest.json")), reason="pit2 snapshot not built")


def k(ts, acc, items="2.02,9.01"):
    return {"accepted_at_et": ts, "accession": acc, "items": items}


def per(end, acc_at, form="10-Q"):
    return {"form": form, "end": end, "accepted_at": acc_at}


# ---------------------------------------------------------------- rules (synthetic, no snapshot needed)

def test_v2_reproduces_v1_when_vendor_and_8k_agree():
    yfe = ["2019-01-29 16:00", "2019-04-30 16:00", "2019-07-30 16:00"]
    k8 = [k("2019-01-29 16:30:00", "a1"), k("2019-04-30 16:31:00", "a2"), k("2019-07-30 16:32:00", "a3")]
    p = [per("2018-12-29", "2019-01-30 08:00:00"), per("2019-03-30", "2019-05-01 08:00:00"), per("2019-06-29", "2019-07-31 08:00:00")]
    strip = lambda e: {k: e[k] for k in ("announced_at_et", "accession")}   # noqa: E731
    assert [strip(e) for e in resolve_events_v2(yfe, k8, k8, p, "2026-11-04", "2014-06-01")] == \
           [strip(e) for e in resolve_events(yfe, k8, "2026-11-04", "2014-06-01")]


def test_misdated_vendor_date_is_retimed_from_the_earnings_8k():
    # COST 2023: release 8-K 05-25 16:22 (after the close), 10-Q 05-31 19:21, vendor says 06-01 06:00
    yfe = ["2023-03-02 16:15", "2023-06-01 06:00"]
    k8 = [k("2023-03-02 16:20:00", "x1"), k("2023-05-25 16:22:40", "x2")]
    p = [per("2023-02-12", "2023-03-08 18:00:00"), per("2023-05-07", "2023-05-31 19:21:00")]
    ev = resolve_events_v2(yfe, k8, k8, p, "2026-11-04", "2014-06-01")
    assert [e["announced_at_et"] for e in ev] == ["2023-03-02 16:15", "2023-05-25 16:22"]
    assert ev[1]["accession"] == "x2" and "mis-dated" in ev[1]["rule"]


def test_vendor_date_kept_when_a_release_8k_corroborates_it():
    # GE 2020: Item 2.02 8-K on 04-13 (not the release); the release came 04-29 06:27 as a 9.01-only 8-K
    yfe = ["2020-01-28 06:00", "2020-04-29 06:00"]
    k202 = [k("2020-01-28 06:30:00", "g0"), k("2020-04-13 08:51:27", "g1", "2.02,8.01,9.01")]
    all8k = k202 + [k("2020-04-29 06:27:17", "g2", "9.01")]
    p = [per("2019-12-31", "2020-02-24 08:00:00", "10-K"), per("2020-03-31", "2020-04-29 06:38:37")]
    ev = resolve_events_v2(yfe, k202, all8k, p, "2026-11-04", "2014-06-01")
    assert [e["announced_at_et"] for e in ev] == ["2020-01-28 06:00", "2020-04-29 06:00"]
    # without the corroborating 8-K the same vendor date would be re-timed (the COST pattern)
    ev2 = resolve_events_v2(yfe, k202, k202, p, "2026-11-04", "2014-06-01")
    assert ev2[-1]["accession"] == "g1"


def test_duplicate_vendor_date_is_dropped():
    # LIN 2020: real release 02-13 (matched), vendor adds 03-01 19:00 (10-K date)
    yfe = ["2020-02-13 06:00", "2020-03-01 19:00"]
    k8 = [k("2020-02-13 06:09:00", "l1")]
    p = [per("2019-12-31", "2020-03-02 15:19:00", "10-K")]
    assert [e["announced_at_et"] for e in resolve_events_v2(yfe, k8, k8, p, "2026-11-04", "2014-06-01")] == ["2020-02-13 06:00"]


def test_vendor_only_without_any_8k_is_kept():
    # BRK.B Saturday release, C/MS quarters without Item 2.02: nothing to replace them with
    yfe = ["2019-02-23 08:00", "2019-05-04 08:00"]
    ev = resolve_events_v2(yfe, [], [], [per("2019-03-31", "2019-05-06 16:00:00")], "2026-11-04", "2014-06-01")
    assert [e["announced_at_et"] for e in ev] == yfe


def test_vendor_gap_filled_from_8k_only_one_per_period():
    # BLK: no vendor dates 2009-10..2022-07; 8-Ks every quarter (plus a non-earnings 2.02 in the same window)
    yfe = ["2009-07-17 07:00", "2022-07-15 07:00"]
    k8 = [k("2017-01-03 08:00:00", "bx"), k("2017-01-13 09:21:04", "b1"), k("2017-04-19 09:12:35", "b2")]
    p = [per("2016-12-31", "2017-02-28 16:00:00", "10-K"), per("2017-03-31", "2017-05-05 16:00:00")]
    ev = resolve_events_v2(yfe, k8, k8, p, "2026-11-04", "2014-06-01")
    assert [e["accession"] for e in ev if e["accession"]] == ["b1", "b2"]   # one per period; bx is not the release
    assert all(e["rule"].endswith("(vendor-series gap)") for e in ev if e["accession"])


def test_no_8k_only_event_when_vendor_series_is_present():
    # OXY 2023-01-04 preliminary Item 2.02 8-K: vendor dates 57 and 55 days away -> not a vendor gap
    yfe = ["2022-11-08 16:10", "2023-02-28 16:10"]
    k8 = [k("2022-11-08 16:15:00", "o1"), k("2023-01-04 17:00:00", "o2"), k("2023-02-28 16:20:00", "o3")]
    p = [per("2022-09-30", "2022-11-08 17:00:00"), per("2022-12-31", "2023-02-24 12:00:00", "10-K")]
    assert "o2" not in [e["accession"] for e in resolve_events_v2(yfe, k8, k8, p, "2026-11-04", "2014-06-01")]


def test_8k_only_after_close_uses_issuer_convention():
    pre = ["2019-01-15 07:00", "2019-04-15 07:00", "2019-07-15 06:30", "2019-10-15 07:00"]
    assert eight_k_only_time("2020-01-15 16:40:00", pre) == ("2020-01-15 07:00", "8-K only; issuer convention: pre-market")
    assert eight_k_only_time("2020-01-15 16:40:00", ["2019-10-15 16:05"] * 4)[0] == "2020-01-15 16:40:00"
    assert eight_k_only_time("2020-01-15 08:40:00", pre)[0] == "2020-01-15 08:40:00"


def test_earnings_8k_events_picks_the_release_not_other_item_202():
    k8 = [k("2021-04-02 16:00:00", "deliveries"), k("2021-04-26 16:05:00", "earnings")]
    assert [e["accession"] for e in earnings_8k_events(k8, [per("2021-03-31", "2021-04-28 08:00:00")])] == ["earnings"]


# ---------------------------------------------------------------- the snapshot

@pytest.fixture(scope="module")
def man():
    if not os.path.exists(os.path.join(NEW, "manifest.json")):
        pytest.skip("pit2 snapshot not built")
    with open(os.path.join(NEW, "manifest.json"), encoding="utf-8") as fh:
        return json.load(fh)


@need_snap
def test_self_contained_v2_manifest_verifies(man):
    assert "base" not in man and man["rank_rules"] == "v2" and man["event_rules"] == "v2"
    bad = [f for f, h in man["sha256"].items() if _sha256(os.path.join(NEW, f)) != h]
    assert bad == []
    s = Snapshot.load(NEW)
    assert s.manifest["rank_rules"] == "v2" and len(s.shares) == len(man["tickers"])


@need_snap
def test_inputs_identical_to_the_frozen_snapshots(man):
    with open(os.path.join(BASE, "manifest.json"), encoding="utf-8") as fh:
        b = json.load(fh)["sha256"]
    with open(os.path.join(OVL, "manifest.json"), encoding="utf-8") as fh:
        o = json.load(fh)["sha256"]
    for f, h in man["sha256"].items():
        if f.startswith(("prices/", "fundamentals/")) or f in ("splits.json", "event_crosscheck.json"):
            assert b[f] == h, f
        elif f.startswith("shares/"):
            assert o[f] == h, f
    assert man["derived_from"]["2026-11-04-pit"] == _sha256(os.path.join(BASE, "manifest.json"))
    assert man["derived_from"]["2026-11-04-pit-r1"] == _sha256(os.path.join(OVL, "manifest.json"))


@need_snap
def test_events_rebuild_offline_byte_identical(man):
    with open(os.path.join(NEW, "event_crosscheck.json"), encoding="utf-8") as fh:
        xc = json.load(fh)
    with open(os.path.join(NEW, "events.json"), "rb") as fh:
        frozen = fh.read()
    ev = {}
    for t in man["tickers"]:
        with open(os.path.join(NEW, "filings", f"{_safe(t)}.json"), encoding="utf-8") as fh:
            fl = json.load(fh)
        ev[t] = resolve_events_v2(xc[t]["yfinance"], xc[t]["edgar_2_02"], fl["8k"], fl["periodic"],
                                  man["price_end_exclusive"], man["events_from"])
    assert json.dumps(ev, indent=1, sort_keys=True).encode("utf-8") == frozen


@need_snap
def test_every_event_is_at_or_before_each_of_its_sources(man):
    with open(os.path.join(NEW, "events.json"), encoding="utf-8") as fh:
        ev = json.load(fh)
    n = 0
    for t, es in ev.items():
        for e in es:
            a = pd.Timestamp(e["announced_at_et"])
            for src in (e.get("vendor_et"), e.get("edgar_8k_et")):
                if src:
                    assert a <= pd.Timestamp(src[:16]), (t, e)
                    n += 1
    assert n > 10000


def _reaction_ratio(snap: Snapshot, events, shift: int = 0) -> float:
    """mean |sector-relative return on the decision session D| / mean |... on D+1 (the reaction day)|. With correct
    timing the earnings reaction is on D+1 (ratio well below 1); with timing one session late it is inside D."""
    on_d, after = [], []
    for t, e in events:
        px = snap.prices[t]["Close"]
        etf = snap.prices[snap.universe[t]["sector_etf"]]["Close"]
        D = decision_session(px.index, e["announced_at_et"])
        if D is None:
            continue
        i = px.index.get_loc(D) + shift
        if i < 1 or i + 1 >= len(px):
            continue
        r = lambda j: float(px.iloc[j] / px.iloc[j - 1] - 1) - float(etf.loc[px.index[j]] / etf.loc[px.index[j - 1]] - 1)  # noqa: E731
        on_d.append(abs(r(i)))
        after.append(abs(r(i + 1)))
    assert len(on_d) >= 30
    return float(np.mean(on_d) / np.mean(after))


@need_snap
def test_8k_only_events_react_after_the_decision_close(man):
    s = Snapshot.load(NEW)
    ev = [(t, e) for t, es in s.events.items() for e in es
          if not e.get("vendor_et") and e["announced_at_et"] >= "2014-06-01" and t in s.prices
          and s.universe[t].get("sector_etf") in s.prices]
    assert _reaction_ratio(s, ev) < 0.6


@need_snap
def test_reaction_detector_fails_if_8k_only_events_are_one_session_late(man):
    s = Snapshot.load(NEW)
    ev = [(t, e) for t, es in s.events.items() for e in es
          if not e.get("vendor_et") and e["announced_at_et"] >= "2014-06-01" and t in s.prices
          and s.universe[t].get("sector_etf") in s.prices]
    assert _reaction_ratio(s, ev, shift=1) > 1.0
