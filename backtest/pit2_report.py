# -*- coding: utf-8 -*-
"""
backtest/pit2_report.py — Session 4 Phase B: what changed from `2026-11-04-pit` to the new base `2026-11-04-pit2`.

  * membership: top 100 at every quarter-end session, old (rules v1) vs new (rules v2)
  * events: added / removed / re-timed per company, in the whole event file and in the H1 sample (Phase D vs Phase C runs)
  * validation of the new event path on events where vendor date AND Item 2.02 8-K agree (ground truth):
      - how often 8-K-only timing (`eight_k_only_time`) would put D AFTER the true D (look-ahead) or before it
      - how often `earnings_8k_events` picks the matched release among the period's Item 2.02 8-Ks
  * Phase B biased-vs-PIT table on the new data (results/pit_vs_biased_2026-11-04-pit2.json)

  python -m backtest.pit2_report      # writes results/pit2_changes_2026-11-04.md / .json
"""

from __future__ import annotations

import json
import os
from collections import Counter, defaultdict
from typing import Any, Dict, List

import pandas as pd

from backtest import pit_universe as PU
from backtest import walkforward as wf
from backtest.pit import Snapshot, decision_session
from backtest.pit_universe_report import season_ends
from backtest.snapshot import _safe
from backtest.snapshot_pit import earnings_8k_events, eight_k_only_time
from core.reporting.tagged import untagged_numbers

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SNAPS = os.path.join(ROOT, "backtest", "snapshots")
RES = os.path.join(ROOT, "results")
OLD, NEW = "2026-11-04-pit", "2026-11-04-pit2"
AS_OF = "2026-11-04"


def membership(old: Snapshot, new: Snapshot) -> List[Dict[str, Any]]:
    out = []
    for d in season_ends(new):
        d = pd.Timestamp(d)
        a = {t for t, r in PU.rank_on(old, d).items() if r <= PU.TOP_N}
        b = {t for t, r in PU.rank_on(new, d).items() if r <= PU.TOP_N}
        out.append({"session": str(d.date()), "only_old": sorted(a - b), "only_new": sorted(b - a), "n_new": len(b)})
    return out


def event_diff(old: Snapshot, new: Snapshot) -> Dict[str, Any]:
    per: Dict[str, Dict[str, List[str]]] = {}
    rules = Counter()
    for t in sorted(new.events):
        a = {e["announced_at_et"] for e in old.events.get(t, [])}
        b = {e["announced_at_et"] for e in new.events[t]}
        for e in new.events[t]:
            if e["announced_at_et"] not in a:
                rules[e["rule"].split(" (")[0] + (" (gap)" if "gap" in e["rule"] else " (re-timed)" if "mis-dated" in e["rule"] else "")] += 1
        if a != b:
            per[t] = {"added": sorted(b - a), "removed": sorted(a - b)}
    return {"per_ticker": per, "added_by_rule": dict(rules),
            "n_old": sum(len(v) for v in old.events.values()), "n_new": sum(len(v) for v in new.events.values())}


def validate(new: Snapshot) -> Dict[str, Any]:
    """Ground truth = events whose vendor date matched an Item 2.02 8-K (rules v1). Measured over every ticker."""
    later = earlier = same = 0
    pick_ok = pick_bad = 0
    bad_examples: List[str] = []
    for t in sorted(new.events):
        p = os.path.join(new.root, "filings", f"{_safe(t)}.json")
        with open(p, encoding="utf-8") as fh:
            fl = json.load(fh)
        k202 = [e for e in fl["8k"] if "2.02" in [i.strip() for i in e["items"].split(",")]]
        picked = {e["accession"] for e in earnings_8k_events(k202, fl["periodic"])}
        sess = new.sessions(t)
        vend = sorted(e["vendor_et"] for e in new.events[t] if e.get("vendor_et"))
        for e in new.events[t]:
            if not (e.get("vendor_et") and e.get("edgar_8k_et")):
                continue
            D = decision_session(sess, e["announced_at_et"])
            ts, _ = eight_k_only_time(e["edgar_8k_et"], [y for y in vend if y < e["edgar_8k_et"]])
            D8 = decision_session(sess, ts)
            if D is None or D8 is None:
                continue
            if D8 > D:
                later += 1
                if len(bad_examples) < 12:
                    bad_examples.append(f"{t} {e['announced_at_et']} 8-K {e['edgar_8k_et'][:16]}")
            elif D8 < D:
                earlier += 1
            else:
                same += 1
            # is the matched release the one earnings_8k_events picks for its period? (only periods it covers)
            if any(pd.Timestamp(q["end"]) < pd.Timestamp(e["edgar_8k_et"]) <= pd.Timestamp(q["accepted_at"])
                   for q in fl["periodic"]):
                if e["accession"] in picked:
                    pick_ok += 1
                else:
                    pick_bad += 1
    return {"timing_8k_only_vs_truth": {"same_D": same, "earlier_D": earlier, "later_D": later, "later_examples": bad_examples},
            "release_pick": {"correct": pick_ok, "other_8k_picked": pick_bad}}


def build() -> Dict[str, Any]:
    old, new = Snapshot.load(os.path.join(SNAPS, OLD)), Snapshot.load(os.path.join(SNAPS, NEW))
    res: Dict[str, Any] = {"membership": membership(old, new), "events": event_diff(old, new), "validation": validate(new)}
    with open(os.path.join(new.root, "manifest.json"), encoding="utf-8") as fh:
        res["item_202_mismatch"] = json.load(fh).get("item_202_frozen_vs_fresh_mismatch", {})
    h = {}
    for k, name in (("old", f"walkforward_{OLD}_phaseD.csv"), ("new", f"walkforward_{NEW}_phaseD.csv")):
        p = os.path.join(RES, name)
        if os.path.exists(p):
            df = pd.read_csv(p, usecols=["ticker", "strategy", "announced_at_et"])
            h[k] = df[df.strategy == "council"]
    if len(h) == 2:
        a = set(zip(h["old"].ticker, h["old"].announced_at_et))
        b = set(zip(h["new"].ticker, h["new"].announced_at_et))
        per: Dict[str, Dict[str, int]] = defaultdict(lambda: {"added": 0, "removed": 0})
        for t, _ in b - a:
            per[t]["added"] += 1
        for t, _ in a - b:
            per[t]["removed"] += 1
        res["h1_sample"] = {"n_old": len(a), "n_new": len(b), "added": len(b - a), "removed": len(a - b),
                            "per_ticker": dict(sorted(per.items()))}
    pb = os.path.join(RES, "pit_vs_biased_2026-11-04-pit2.json")
    if os.path.exists(pb):
        with open(pb, encoding="utf-8") as fh:
            res["phase_b"] = json.load(fh)
    return res


def markdown(res: Dict[str, Any]) -> str:
    def N(x, src=f"snapshot {NEW}"):
        return wf._fmt(x, False, src, AS_OF, decimals=0)

    def P(x, src):
        return wf._fmt(x, True, src, AS_OF)

    ev, va = res["events"], res["validation"]
    L = [f"# Snapshot `{NEW}` vs `{OLD}` — what changed (Session 4 Phase B)", "",
         f"`{NEW}` is a self-contained base snapshot (no overlay): the frozen prices, fundamentals, splits and vendor event lists "
         f"of `{OLD}`, the ranking-rules-v2 share counts of `2026-11-04-pit-r1`, a new SEC EDGAR filings index (`filings/`), and "
         "events rebuilt with event rules v2 (backtest/snapshot_pit2.py). Neither frozen snapshot was modified. No delisted "
         "companies were added (no price source; results/delisted_gap_2026-11-04.md). <!-- text-only -->", "",
         "## Event rules v2", "",
         "- P2-1: an earnings 8-K (the last Item 2.02 8-K before the period's 10-Q/10-K) with no vendor date within sixty days "
         "and no event within forty-five days becomes an 8-K-only event (vendor-series gaps such as BlackRock 2009-2022). <!-- text-only -->",
         "- P2-2: a vendor-only date four to forty-five days after an earnings 8-K, with no release 8-K (Item 2.02 or 7.01, or "
         "exhibits only) on that day or the day before, is the 10-Q/10-K date: re-timed from the 8-K, or dropped if that 8-K "
         "is already an event. Corroborated vendor-only dates stay (GE 2020-04-29 and Welltower 2019-02-12 furnished their "
         "releases as exhibit-only 8-Ks; Berkshire's Saturday releases). <!-- text-only -->",
         "- 8-K-only timing: the acceptance time; an after-close acceptance becomes pre-market when at least three quarters of the "
         "issuer's last eight earlier vendor times were pre-market (can only move D earlier). <!-- text-only -->", "",
         f"Events in the file: {N(ev['n_old'], 'snapshot ' + OLD)} before, {N(ev['n_new'])} after. New or re-timed events by rule:", "",
         "| rule | events |", "|---|---|"]
    for k, v in sorted(ev["added_by_rule"].items()):
        L.append(f"| {k} | {N(v)} |")
    t8 = va["timing_8k_only_vs_truth"]
    tot = t8["same_D"] + t8["earlier_D"] + t8["later_D"]
    rp = va["release_pick"]
    L += ["", "## Validation of the new event path (ground truth: events where the vendor date and an Item 2.02 8-K agree)", "",
          f"- If those events had been timed from the 8-K alone: same decision session {N(t8['same_D'])}, earlier {N(t8['earlier_D'])}, "
          f"LATER (would be look-ahead) {N(t8['later_D'])} of {N(tot)} ({P(t8['later_D'] / tot if tot else 0, 'derived')}). "
          + ("Examples: " + "; ".join(t8["later_examples"]) + ". <!-- text-only -->" if t8["later_examples"] else ""),
          f"- Release identification: the matched release is the 8-K that `earnings_8k_events` picks for its period in "
          f"{N(rp['correct'])} cases; another Item 2.02 8-K is picked in {N(rp['other_8k_picked'])}.",
          f"- Item 2.02 lists, frozen (`{OLD}` build) vs fresh EDGAR submissions: {N(len(res['item_202_mismatch']))} companies differ "
          "(rules v1 matching keeps the frozen list, so v1 events are reproduced exactly).", ""]
    L += ["## Events added / removed per company (whole event file, decision dates since 2014-06)", "",
          "| company | added | removed |", "|---|---|---|"]
    for t, d in sorted(ev["per_ticker"].items(), key=lambda kv: (-len(kv[1]["added"]) - len(kv[1]["removed"]), kv[0]))[:60]:
        L.append(f"| {t} | {N(len(d['added']))} | {N(len(d['removed']))} |")
    if len(ev["per_ticker"]) > 60:
        L.append(f"| ({N(len(ev['per_ticker']) - 60)} more companies, all in the .json) | | |")
    if "h1_sample" in res:
        hs = res["h1_sample"]
        src = f"wf-backtest {OLD}_phaseD / {NEW}_phaseD"
        L += ["", "## H1 sample: pre-registered run (Phase D, Session 3) vs rerun (Phase C, Session 4)", "",
              f"Events {N(hs['n_old'], src)} → {N(hs['n_new'], src)}: added {N(hs['added'], src)}, removed {N(hs['removed'], src)}. "
              "Changes come from membership (ranking rules v2) and from the event rules. <!-- text-only -->", "",
              "| company | added | removed |", "|---|---|---|"]
        for t, d in sorted(hs["per_ticker"].items(), key=lambda kv: (-kv[1]["added"] - kv[1]["removed"], kv[0])):
            L.append(f"| {t} | {N(d['added'], src)} | {N(d['removed'], src)} |")
    L += ["", "## Membership: top hundred at quarter-end sessions, rules v1 (old) vs v2 (new)", "",
          "| session | only in old | only in new |", "|---|---|---|"]
    nchg = 0
    for m in res["membership"]:
        if m["only_old"] or m["only_new"]:
            nchg += 1
            L.append(f"| `{m['session']}` | {', '.join(m['only_old']) or '—'} | {', '.join(m['only_new']) or '—'} |")
    L += ["", f"Quarter-end sessions with any difference: {N(nchg)} of {N(len(res['membership']))}.", ""]
    if "phase_b" in res:
        L += ["## Phase B on the new data", "",
              "Survivorship-biased vs point-in-time, Session 2 window, on the new snapshot: results/pit_vs_biased_2026-11-04-pit2.md "
              "(summarised in LOG.md and HANDOFF.md). <!-- text-only -->", ""]
    md = "\n".join(L) + "\n"
    bad = untagged_numbers(md)
    if bad:
        raise ValueError(f"untagged numbers: {bad[:5]}")
    return md


if __name__ == "__main__":
    r = build()
    with open(os.path.join(RES, "pit2_changes_2026-11-04.md"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(markdown(r))
    with open(os.path.join(RES, "pit2_changes_2026-11-04.json"), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(r, fh, indent=1, sort_keys=True)
    print("events", r["events"]["n_old"], "->", r["events"]["n_new"], "validation", json.dumps(r["validation"])[:400])
