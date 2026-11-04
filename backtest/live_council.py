# -*- coding: utf-8 -*-
"""
backtest/live_council.py — Phase C: does a live LLM council add anything over the deterministic
persona rules, once the LLM cannot use training-data knowledge?

Design
  * Held-out events: decision session D strictly after the model's documented knowledge cutoff
    (llm_client.MODEL_KNOWLEDGE_CUTOFF), with the T+20 exit inside the snapshot.
  * The LLM sees only backtest.anonymise.data_block (code, sector, rounded/banded ratios).
  * Live vs mock are run on identical events and identical PIT inputs. The ONLY difference is the
    stance of the live personas; debate re-score, CRO veto/limits and PM synthesis are the same
    deterministic code (hard rule 3: the stance -> score map in llm_guard is the only LLM-to-number path).
  * CRO veto events are not sent to the LLM: the veto does not depend on analyst output, so the
    decision is HOLD either way (saves budget, changes nothing).
  * Budget: personas are dropped (lowest MoE weight first) before events are dropped.
  * Event order is a seeded shuffle, so a run stopped by the budget/quota is a random subset.

  LUMINA_LLM_MODE=live python -m backtest.live_council --snapshot backtest/snapshots/2026-11-04-sp100 \
      --leak-check 100 --level 1
  python -m backtest.live_council ... (no live mode: replays the committed cache, offline)
"""

from __future__ import annotations

import argparse
import json
import os
from typing import Any, Dict, List, Tuple

import numpy as np
import pandas as pd

_LIVE = os.getenv("LUMINA_LLM_MODE") == "live"
os.environ["LUMINA_LLM_MODE"] = "mock"  # council internals never call an LLM on their own (untracked spend)

from backtest import anonymise as A  # noqa: E402
from backtest import walkforward as wf  # noqa: E402
from backtest.llm_client import MODEL, MODEL_KNOWLEDGE_CUTOFF, BudgetExceeded, GeminiCached, budget  # noqa: E402
from backtest.pit import Snapshot, decision_session  # noqa: E402
from backtest.stats import describe  # noqa: E402

SEED = 20261104
# MoE weights in the regime the backtest always lands in (PortfolioManagerAgent, "bull liquidity"):
# cathie_wood .22, william_oneil .22, george_soros .14, cis_trader .14, buffett .10, graham .06, michael_burry .04
PERSONA_PRIORITY = ["cathie_wood", "william_oneil", "george_soros", "cis_trader", "buffett", "graham", "michael_burry"]
RESULTS = wf.RESULTS_DIR


def held_out_events(snap: Snapshot, n_events: int = 12) -> List[Tuple[str, Dict[str, str], pd.Timestamp]]:
    """Same event selection as walkforward.run (last n per ticker), then D > cutoff."""
    cutoff = pd.Timestamp(MODEL_KNOWLEDGE_CUTOFF)
    out = []
    for t in snap.manifest["tickers"]:
        sessions = snap.sessions(t)
        evs = []
        for ev in snap.events.get(t, []):
            D = decision_session(sessions, ev["announced_at_et"])
            if D is None:
                continue
            i0 = sessions.get_loc(D)
            if i0 < 300 or i0 + max(wf.HORIZONS) >= len(sessions):
                continue
            evs.append((ev, D))
        for k, (ev, D) in enumerate(evs[-n_events:], 1):
            if D > cutoff:
                out.append((t, dict(ev, event_no=k), D))
    rng = np.random.default_rng(SEED)
    order = rng.permutation(len(out))
    return [out[i] for i in order]


def _agent(agent_id: str):
    from core.ai_hedge_fund.agents import ALL_ANALYST_AGENTS
    return next(a for a in ALL_ANALYST_AGENTS if a.agent_id == agent_id)


def live_analyst(llm: GeminiCached, agent_id: str, block: str) -> Dict[str, Any]:
    from core.ai_hedge_fund.llm_guard import sanitize_agent_output
    cls = _agent(agent_id)
    rec = llm.generate(cls.get_system_prompt(), A.persona_prompt(block), purpose=f"council:{agent_id}")
    js = rec.get("json") or {}
    res = sanitize_agent_output({"stance": js.get("stance"), "score": js.get("score"), "dialogue": js.get("dialogue", "")})
    res.update({"agent_id": cls.agent_id, "name": cls.name, "title": cls.title, "avatar": cls.avatar,
                "is_degraded_fallback": False, "llm_mode": "live", "llm_key": rec["key"],
                "llm_parse_ok": int(bool(js.get("stance")))})
    return res


def run_leak_check(snap: Snapshot, events, level: int, n: int, llm: GeminiCached) -> Dict[str, Any]:
    tickers = snap.manifest["tickers"]
    # one prompt per event, preferring distinct tickers (first occurrence in the shuffled order)
    seen, sample = set(), []
    for t, ev, D in events:
        if t not in seen:
            seen.add(t)
            sample.append((t, ev, D))
    for t, ev, D in events:
        if len(sample) >= n:
            break
        if (t, ev["announced_at_et"]) not in {(s[0], s[1]["announced_at_et"]) for s in sample}:
            sample.append((t, ev, D))
    sample = sample[:n]
    rows = []
    for t, ev, D in sample:
        inp = wf.build_inputs(snap, t, D, ev["announced_at_et"])
        sector = (snap.universe.get(t) or {}).get("sector", "n/a")
        block = A.data_block(inp, A.company_code(t, tickers), sector, level)
        rec = llm.generate(A.LEAK_SYSTEM, A.leak_prompt(block), purpose=f"leak:L{level}")
        js = rec.get("json") or {}
        guesses = [str((g or {}).get("ticker", "")).upper().replace("-", ".").strip() for g in (js.get("guesses") or [])][:3]
        norm = {"GOOG": "GOOGL"}
        guesses = [norm.get(g, g) for g in guesses]
        q_true = f"{D.year}Q{(D.month - 1) // 3 + 1}"
        q_guess = f"{js.get('year')}{str(js.get('quarter', '')).upper()}"
        rows.append({"ticker": t, "decision_date": str(D.date()), "top1": int(bool(guesses) and guesses[0] == t),
                     "top3": int(t in guesses), "quarter_hit": int(q_guess == q_true), "parse_ok": int(bool(guesses)),
                     "guess1": guesses[0] if guesses else "", "llm_key": rec["key"]})
    df = pd.DataFrame(rows)
    return {"level": level, "n": int(len(df)), "top1_rate": float(df.top1.mean()), "top3_rate": float(df.top3.mean()),
            "quarter_rate": float(df.quarter_hit.mean()), "parse_ok": float(df.parse_ok.mean()),
            "n_distinct_tickers": int(df.ticker.nunique()), "rows": rows}


def run_council(snap: Snapshot, events, level: int, personas: List[str], llm: GeminiCached) -> pd.DataFrame:
    from core.ai_hedge_fund.cost_model import CostModel
    cost = CostModel()
    tickers = snap.manifest["tickers"]
    rows = []
    for t, ev, D in events:
        inp = wf.build_inputs(snap, t, D, ev["announced_at_et"])
        mock = wf.decide_council(inp)
        sector = (snap.universe.get(t) or {}).get("sector", "n/a")
        if mock["veto"]:
            live, over = dict(mock), {}
        else:
            block = A.data_block(inp, A.company_code(t, tickers), sector, level)
            try:
                over = {aid: live_analyst(llm, aid, block) for aid in personas}
            except BudgetExceeded:
                break
            live = wf.decide_council(inp, analyst_override=over)
        base = {"ticker": t, "event_no": ev["event_no"], "announced_at_et": ev["announced_at_et"],
                "decision_date": str(D.date()), "sector": sector, "vix_d1": inp["vix"], "vix_bucket": wf.vix_bucket(inp["vix"]),
                "cro_veto": mock["veto"], "personas_live": ",".join(personas) if over else ""}
        for name, dec in (("mock", mock), ("live", live)):
            sc = wf.score(snap, t, D, "council", dec, cost)
            r = dict(base, arm=name, action=dec["action"], long=dec["long"], confidence=dec["confidence"])
            for aid in personas:
                r[f"stance_{aid}"] = dec.get("agent_stances", {}).get(aid, "")
            if name == "live":
                r["parse_ok"] = int(all(o.get("llm_parse_ok", 0) for o in over.values())) if over else 1
            r.update({k: v for k, v in sc.items() if k.startswith(("net_ret_", "excess_ret_", "excess_sector_", "underlying_ret_"))})
            rows.append(r)
    return pd.DataFrame(rows)


def summarize(df: pd.DataFrame, personas: List[str]) -> Dict[str, Any]:
    df = df.assign(month=df["decision_date"].str[:7])
    a = df[df.arm == "live"].set_index(["ticker", "event_no"]).sort_index()
    b = df[df.arm == "mock"].set_index(["ticker", "event_no"]).sort_index()
    out: Dict[str, Any] = {"n_events": int(len(a)), "n_llm_events": int((a.cro_veto == 0).sum()),
                           "share_decisions_differ": float((a.long != b.long).mean()) if len(a) else None,
                           "live_long_rate": float(a.long.mean()) if len(a) else None,
                           "mock_long_rate": float(b.long.mean()) if len(a) else None,
                           "parse_ok_rate": float(a.parse_ok.mean()) if len(a) else None, "horizons": {}, "stance_agreement": {}}
    for h in wf.HORIZONS:
        for m in ("net_ret", "excess_sector"):
            d = (a[f"{m}_{h}"] - b[f"{m}_{h}"])
            out["horizons"][f"live_minus_mock|{h}|{m}"] = describe(d.to_numpy(), a["month"].to_numpy())
            out["horizons"][f"live|{h}|{m}"] = describe(a[f"{m}_{h}"].to_numpy(), a["month"].to_numpy())
            out["horizons"][f"mock|{h}|{m}"] = describe(b[f"{m}_{h}"].to_numpy(), b["month"].to_numpy())
    nv = a.cro_veto == 0
    for aid in personas:
        col = f"stance_{aid}"
        la, mo = a.loc[nv, col], b.loc[nv, col]
        out["stance_agreement"][aid] = {
            "agree": float((la == mo).mean()) if nv.any() else None,
            "live_counts": {k: int(v) for k, v in la.value_counts().sort_index().items()},
            "mock_counts": {k: int(v) for k, v in mo.value_counts().sort_index().items()},
        }
    return out


def markdown(summary: Dict[str, Any], leak: List[Dict[str, Any]], meta: Dict[str, Any]) -> str:
    from core.reporting.tagged import fact, untagged_numbers
    src, as_of = f"live-council {meta['snapshot_id']}", meta["run_date"]
    F = lambda x: fact(None if x is None else x * 100, src, as_of, unit="%", decimals=2).render(with_label=False)  # noqa: E731
    N = lambda x: fact(x, src, as_of, decimals=0).render(with_label=False)  # noqa: E731

    def ci(m):
        c = m.get("cluster") or {}
        return f"{F(m['mean'])} [{F(c.get('lo'))} … {F(c.get('hi'))}]" if m.get("mean") is not None else "n/a"

    L = [f"# Live LLM council vs mock council — held-out, anonymised (snapshot {meta['snapshot_id']})", "",
         f"Model `{MODEL}`. Documented knowledge cutoff: January 2025 (Google Cloud Vertex AI model page; see LOG.md, "
         f"Phase C). Held-out = decision session after `{MODEL_KNOWLEDGE_CUTOFF}`. "
         "Live personas: " + ", ".join(meta["personas"]) + ". All other personas, the debate re-score, the CRO and the "
         "PM are the same deterministic code in both arms; only the live personas' stances differ. "
         "CRO-veto events are HOLD in both arms and were not sent to the model. <!-- text-only -->", "",
         "Values are labelled MODEL ASSUMPTION where they come from a model decision; the returns themselves are "
         "computed from snapshot prices. <!-- text-only -->", "",
         "## Leakage check (can the model name the company from the anonymised profile?)", "",
         "| anonymisation level | prompts | distinct companies | top-1 hit rate | top-3 hit rate | quarter hit rate | parsed |",
         "|---|---|---|---|---|---|---|"]
    for lk in leak:
        L.append(f"| level {lk['level']} | {N(lk['n'])} | {N(lk['n_distinct_tickers'])} | {F(lk['top1_rate'])} | "
                 f"{F(lk['top3_rate'])} | {F(lk['quarter_rate'])} | {F(lk['parse_ok'])} |")
    s = summary
    L += ["", "## Paired result (live − mock, same events)", "",
          f"Held-out events scored: {N(s['n_events'])}; sent to the model (no CRO veto): {N(s['n_llm_events'])}. "
          f"Share of events where the long/flat decision differs: {F(s['share_decisions_differ'])}. "
          f"Long rate live {F(s['live_long_rate'])} vs mock {F(s['mock_long_rate'])}. "
          f"Responses parsed: {F(s['parse_ok_rate'])}.", "",
          "Each cell: mean and 95% month-clustered bootstrap CI. MDE = minimum detectable effect (five percent two-sided, "
          "eighty percent power). <!-- text-only -->", "",
          "| horizon / metric | live | mock | live − mock | MDE (live − mock) |", "|---|---|---|---|---|"]
    for h in wf.HORIZONS:
        for m, label in (("net_ret", "net return"), ("excess_sector", "excess vs sector ETF")):
            H = s["horizons"]
            d = H[f"live_minus_mock|{h}|{m}"]
            L.append(f"| T+{h} {label} | {ci(H[f'live|{h}|{m}'])} | {ci(H[f'mock|{h}|{m}'])} | {ci(d)} | {F(d['mde80'])} |")
    L += ["", "## Stance agreement, live persona vs its deterministic rule (events sent to the model)", "",
          "| persona | agreement | live stances | rule stances |", "|---|---|---|---|"]
    for aid, g in s["stance_agreement"].items():
        lc = ", ".join(f"{k} {N(v)}" for k, v in g["live_counts"].items())
        mc = ", ".join(f"{k} {N(v)}" for k, v in g["mock_counts"].items())
        L.append(f"| {aid} | {F(g['agree'])} | {lc} | {mc} |")
    md = "\n".join(L) + "\n"
    bad = untagged_numbers(md)
    if bad:
        raise ValueError(f"untagged numbers: {bad[:5]}")
    return md


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot", required=True)
    ap.add_argument("--level", type=int, default=1)
    ap.add_argument("--leak-check", type=int, default=0, help="run the leakage check on N prompts and stop")
    ap.add_argument("--personas", type=int, default=0, help="number of live personas (0 = fit to budget)")
    ap.add_argument("--reserve", type=int, default=10, help="calls kept in reserve")
    ap.add_argument("--plan", action="store_true", help="print held-out counts and the budget plan only")
    a = ap.parse_args()
    snap = Snapshot.load(a.snapshot)
    events = held_out_events(snap)
    llm = GeminiCached(allow_live=_LIVE)
    if a.leak_check:
        res = run_leak_check(snap, events, a.level, a.leak_check, llm)
        path = os.path.join(RESULTS, f"leak_check_L{a.level}_{snap.snapshot_id}.json")
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(res, fh, indent=1, sort_keys=True)
        print({k: v for k, v in res.items() if k != "rows"}, "budget:", budget()["requests_sent"])
        return
    # Count events that need the LLM (no CRO veto) to size the persona set.
    need = [e for e in events if not wf.decide_council(wf.build_inputs(snap, e[0], e[2], e[1]["announced_at_et"]))["veto"]]
    left = budget()["cap"] - budget()["requests_sent"] - a.reserve
    k = a.personas or max(0, min(len(PERSONA_PRIORITY), left // max(1, len(need))))
    personas = PERSONA_PRIORITY[:k]
    print(f"held-out events {len(events)}, needing LLM {len(need)}, budget left {left} -> personas {k}: {personas}")
    if a.plan or k == 0:
        return
    df = run_council(snap, events, a.level, personas, llm)
    summary = summarize(df, personas)
    sid = snap.snapshot_id
    meta = {"snapshot_id": sid, "personas": personas, "run_date": pd.Timestamp(snap.manifest["price_end_exclusive"]).strftime("%Y-%m-%d")}
    leaks = []
    for lv in (1, 2):
        p = os.path.join(RESULTS, f"leak_check_L{lv}_{sid}.json")
        if os.path.exists(p):
            with open(p, encoding="utf-8") as fh:
                leaks.append({k: v for k, v in json.load(fh).items() if k != "rows"})
    df.to_csv(os.path.join(RESULTS, f"live_council_{sid}.csv"), index=False, float_format="%.8f", lineterminator="\n")
    with open(os.path.join(RESULTS, f"live_council_{sid}_summary.json"), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(dict(summary, meta=meta, level=a.level), fh, indent=1, sort_keys=True, default=lambda x: None)
    with open(os.path.join(RESULTS, f"live_council_{sid}_summary.md"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(markdown(summary, leaks, meta))
    print(json.dumps({k: v for k, v in summary.items() if k in ("n_events", "n_llm_events", "share_decisions_differ")}),
          "budget:", budget()["requests_sent"], "cache hits:", llm.hits, "live:", llm.live)


if __name__ == "__main__":
    main()
