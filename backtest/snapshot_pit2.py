# -*- coding: utf-8 -*-
"""
backtest/snapshot_pit2.py — Session 4: a new self-contained base snapshot `2026-11-04-pit2`.

What it folds in (the frozen snapshots `2026-11-04-pit` and `2026-11-04-pit-r1` are read, never written):
  * ranking rules v2 (independent review Session 3, P1-1..P1-3) in the BASE: share counts are the v2 counts, and the
    manifest says `rank_rules: v2`, so the harness applies the v2 rank-time guards. No overlay (no `base` key).
  * event rules v2 (review P2-1, P2-2; `snapshot_pit.resolve_events_v2`): 8-K-only events where the vendor series has
    a gap (BLK 2015-2022), vendor-only dates that are 10-Q/10-K dates re-timed from the earnings 8-K or dropped.
  * a new data path `filings/<T>.json`: every 8-K (acceptance, accession, items) and original 10-Q/10-K (period end,
    acceptance) of the company's CIKs since 2012 from SEC EDGAR submissions, accepted before the snapshot end. Events
    are rebuilt from it plus the frozen vendor lists (event_crosscheck.json), offline and deterministically.

Inputs reused byte-for-byte, after checking every file against its frozen manifest: prices/, fundamentals/,
splits.json, event_crosscheck.json (from 2026-11-04-pit) and shares/ (v2 counts, from 2026-11-04-pit-r1, computed by
`pit_universe.shares_series(rules="v2")` from the same EDGAR filings). Prices are therefore identical to the
pre-registered run's: any H1 change comes from the universe and event fixes only.

No delisted companies are added: no delisted-price source is reachable (results/delisted_gap_2026-11-04.md).

  python -m backtest.snapshot_pit2 --id 2026-11-04-pit2
A second build from the EDGAR cache must give an identical manifest (tests/test_pit2_snapshot.py checks the parts
that need no network).
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
from typing import Any, Dict, List

from backtest.edgar import EdgarClient, to_et
from backtest.snapshot import SNAP_ROOT, _safe, _sha256
from backtest.snapshot_pit import EDGAR_SINCE, resolve_events_v2

BASE, OVERLAY = "2026-11-04-pit", "2026-11-04-pit-r1"


def verify_frozen(root: str) -> Dict[str, Any]:
    """Every file listed in the manifest exists with the recorded sha256 (raises otherwise)."""
    with open(os.path.join(root, "manifest.json"), encoding="utf-8") as fh:
        man = json.load(fh)
    bad = [f for f, h in man["sha256"].items() if _sha256(os.path.join(root, f)) != h]
    if bad:
        raise RuntimeError(f"{root}: {len(bad)} files differ from the frozen manifest, e.g. {bad[:3]}")
    return man


def filings_index(subs: List[Dict[str, Any]], end: str) -> Dict[str, List[Dict[str, str]]]:
    """Compact, sorted EDGAR filing index: 8-Ks (with items) and original 10-Q/10-K, accepted before `end`."""
    k8, per, seen = [], [], set()
    for s in subs:
        if s["accessionNumber"] in seen:
            continue
        seen.add(s["accessionNumber"])
        acc = to_et(s["acceptanceDateTime"])
        if acc[:10] >= end or s.get("filingDate", "") < EDGAR_SINCE:
            continue
        if s.get("form") == "8-K":
            k8.append({"accepted_at_et": acc, "accession": s["accessionNumber"], "items": str(s.get("items", ""))})
        elif s.get("form") in ("10-Q", "10-K") and s.get("reportDate"):
            per.append({"form": s["form"], "end": s["reportDate"], "accepted_at": acc, "accession": s["accessionNumber"]})
    return {"8k": sorted(k8, key=lambda e: (e["accepted_at_et"], e["accession"])),
            "periodic": sorted(per, key=lambda e: (e["accepted_at"], e["accession"]))}


def item_202(k8: List[Dict[str, str]]) -> List[Dict[str, str]]:
    return [{"accepted_at_et": e["accepted_at_et"], "accession": e["accession"]} for e in k8
            if "2.02" in [i.strip() for i in e["items"].split(",")]]


def build(snapshot_id: str, ed: EdgarClient) -> str:
    broot, oroot = os.path.join(SNAP_ROOT, BASE), os.path.join(SNAP_ROOT, OVERLAY)
    bman, oman = verify_frozen(broot), verify_frozen(oroot)
    if oman.get("base") != BASE or oman.get("base_manifest_sha256") != _sha256(os.path.join(broot, "manifest.json")):
        raise RuntimeError("overlay was not built on this base")
    end = bman["price_end_exclusive"]
    root = os.path.join(SNAP_ROOT, snapshot_id)
    if os.path.exists(root):
        shutil.rmtree(root)
    for sub in ("prices", "fundamentals", "shares", "filings"):
        os.makedirs(os.path.join(root, sub))
    for f in sorted(bman["sha256"]):
        if f.startswith(("prices/", "fundamentals/")) or f in ("splits.json", "event_crosscheck.json"):
            shutil.copyfile(os.path.join(broot, f), os.path.join(root, f))
    for f in sorted(oman["sha256"]):
        if f.startswith("shares/"):
            shutil.copyfile(os.path.join(oroot, f), os.path.join(root, f))
    with open(os.path.join(broot, "universe.json"), encoding="utf-8") as fh:
        uni = json.load(fh)
    with open(os.path.join(broot, "event_crosscheck.json"), encoding="utf-8") as fh:
        xcheck = json.load(fh)
    events: Dict[str, List[Dict[str, Any]]] = {}
    mismatch_202: Dict[str, Dict[str, List[str]]] = {}
    for m in uni["members"]:
        t = m["ticker"]
        subs: List[Dict[str, Any]] = []
        for c in m["ciks"]:
            subs += ed.submissions(c, since=EDGAR_SINCE)
        idx = filings_index(subs, end)
        with open(os.path.join(root, "filings", f"{_safe(t)}.json"), "w", encoding="utf-8", newline="\n") as fh:
            json.dump({"ticker": t, "ciks": m["ciks"], "source": "SEC EDGAR submissions (8-K items, 10-Q/10-K reportDate); "
                       "times = acceptanceDateTime in America/New_York", **idx}, fh, indent=1, sort_keys=True)
        k202 = item_202(idx["8k"])
        old = {e["accession"] for e in xcheck[t]["edgar_2_02"]}
        new = {e["accession"] for e in k202}
        if old != new:
            mismatch_202[t] = {"only_frozen": sorted(old - new), "only_fresh": sorted(new - old)}
        # the frozen Item 2.02 list is the one rules v1 matched against; keep it, so v1 events are reproduced exactly
        events[t] = resolve_events_v2(xcheck[t]["yfinance"], xcheck[t]["edgar_2_02"], idx["8k"], idx["periodic"],
                                      end, bman["events_from"])
    with open(os.path.join(root, "events.json"), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(events, fh, indent=1, sort_keys=True)
    uni = dict(uni, label="POINT-IN-TIME top-100 US-listed domestic filers by market cap at D-1 (decided in the harness); "
               "ranking rules v2, event rules v2 (Session 4)", rank_rules="v2", event_rules="v2")
    with open(os.path.join(root, "universe.json"), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(uni, fh, indent=1, sort_keys=True)
    files = sorted(os.path.relpath(os.path.join(d, f), root) for d, _, fs in os.walk(root) for f in fs if f != "manifest.json")
    man = {k: v for k, v in bman.items() if k != "sha256"}
    man.update({
        "snapshot_id": snapshot_id, "rank_rules": "v2", "event_rules": "v2",
        "derived_from": {BASE: _sha256(os.path.join(broot, "manifest.json")), OVERLAY: _sha256(os.path.join(oroot, "manifest.json")),
                         "note": "prices, fundamentals, splits, vendor event lists copied from the base and share counts (v2) "
                                 "from the review overlay, each verified against its frozen manifest; events rebuilt with "
                                 "event rules v2 from filings/ (new: SEC EDGAR submissions)"},
        "item_202_frozen_vs_fresh_mismatch": mismatch_202,
    })
    man["sources"] = dict(man["sources"], filings="SEC EDGAR submissions: 8-K acceptance + items, 10-Q/10-K reportDate + acceptance",
                          events="rules v1 (yfinance dates matched +-3d to 8-K Item 2.02, earlier timestamp) + rules v2 "
                                 "(review P2-1 8-K-only events in vendor gaps; P2-2 vendor-only 10-Q/10-K dates re-timed or dropped)")
    man["sha256"] = {f: _sha256(os.path.join(root, f)) for f in files}
    with open(os.path.join(root, "manifest.json"), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(man, fh, indent=1, sort_keys=True)
    n_ev = sum(len(v) for v in events.values())
    print(f"snapshot {root}: {len(man['tickers'])} tickers, {n_ev} events, {len(files)} files; "
          f"edgar requests {ed.n_requests}, cache hits {ed.n_cache_hits}; 2.02 mismatches {len(mismatch_202)}")
    return root


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", default="2026-11-04-pit2")
    ap.add_argument("--offline", action="store_true", help="EDGAR cache only (rebuild check)")
    a = ap.parse_args()
    build(a.id, EdgarClient(offline=a.offline))
