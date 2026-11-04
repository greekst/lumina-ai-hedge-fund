# -*- coding: utf-8 -*-
"""
backtest/snapshot_pit_overlay.py — Session 3 review overlay on the frozen PIT snapshot.

The pre-registered H1 ran on `2026-11-04-pit` with ranking rules v1; that snapshot is never changed. The independent review
(results/independent_review_session3.md) found share-count/ranking errors (P1-1 to P1-3). This overlay recomputes the share
counts with rules v2 from the same cached EDGAR filings and stores ONLY `shares/*.json` plus a manifest that names the base;
prices, events, fundamentals and splits come from the base snapshot unchanged (see `Snapshot.load`).

  python -m backtest.snapshot_pit_overlay --base 2026-11-04-pit --id 2026-11-04-pit-r1
"""

from __future__ import annotations

import argparse
import json
import os

from backtest import pit_universe as PU
from backtest.edgar import EdgarClient
from backtest.pit import Snapshot
from backtest.snapshot import SNAP_ROOT, _safe, _sha256
from backtest.snapshot_pit import EDGAR_SINCE


def build(base: str, overlay_id: str, rules: str = "v2") -> str:
    b = Snapshot.load(os.path.join(SNAP_ROOT, base))
    root = os.path.join(SNAP_ROOT, overlay_id)
    os.makedirs(os.path.join(root, "shares"), exist_ok=True)
    ed = EdgarClient(offline=True)          # everything is in the EDGAR cache from the base build
    for t in b.manifest["tickers"]:
        m = b.universe[t]
        bd = ed.bundle_ciks(m["ciks"], since=EDGAR_SINCE)
        sp = b.splits.get(t, [])
        shares = PU.shares_series(bd["facts"], bd["subs"], since=EDGAR_SINCE, rules=rules, splits=sp)
        if not shares:
            shares = PU.shares_from_public_float(bd["facts"], bd["subs"], b.prices[t], since=EDGAR_SINCE)
        floats = PU.public_floats(bd["facts"], bd["subs"], since=EDGAR_SINCE)
        with open(os.path.join(root, "shares", f"{_safe(t)}.json"), "w", encoding="utf-8", newline="\n") as fh:
            json.dump({"ticker": t, "ciks": m["ciks"], "rules": rules,
                       "source": "SEC EDGAR companyfacts dei/us-gaap; PIT key = acceptanceDateTime", "shares": shares,
                       "public_float": floats}, fh, indent=1, sort_keys=True)
    files = sorted(os.path.relpath(os.path.join(d, f), root) for d, _, fs in os.walk(root) for f in fs if f != "manifest.json")
    man = {"snapshot_id": overlay_id, "base": base, "rank_rules": rules,
           "base_manifest_sha256": _sha256(os.path.join(SNAP_ROOT, base, "manifest.json")),
           "tickers": b.manifest["tickers"],
           "note": "review overlay: share counts recomputed with ranking rules v2 (independent review P1-1..P1-3); "
                   "everything else from the base snapshot",
           "sha256": {f: _sha256(os.path.join(root, f)) for f in files}}
    with open(os.path.join(root, "manifest.json"), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(man, fh, indent=1, sort_keys=True)
    print(f"overlay {root}: {len(files)} files on base {base}")
    return root


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="2026-11-04-pit")
    ap.add_argument("--id", default="2026-11-04-pit-r1")
    a = ap.parse_args()
    build(a.base, a.id)
