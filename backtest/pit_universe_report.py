# -*- coding: utf-8 -*-
"""
backtest/pit_universe_report.py — Session 3: how the point-in-time universe was built, how complete it is,
and how it differs from today's top 100. Writes results/pit_universe_2026-11-04.md / .json.

  python -m backtest.pit_universe_report
"""

from __future__ import annotations

import json
import os
from collections import Counter
from typing import Any, Dict, List

import pandas as pd

from backtest import pit_universe as PU
from backtest.edgar import EdgarClient
from backtest.pit import Snapshot
from backtest.snapshot_pit import PREDECESSOR_CIKS

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SNAP = os.path.join(ROOT, "backtest", "snapshots", "2026-11-04-pit")
AS_OF = "2026-11-04"


def season_ends(snap: Snapshot, start: str = "2014-06-01") -> List[pd.Timestamp]:
    s = snap.sessions("SPY")
    s = s[s >= pd.Timestamp(start)]
    q = pd.Series(s, index=s).groupby(s.to_period("Q")).max()
    return list(q.values)


def build() -> Dict[str, Any]:
    snap = Snapshot.load(SNAP)
    with open(os.path.join(PU.PDIR, "candidates.json"), encoding="utf-8") as fh:
        cand = json.load(fh)
    with open(os.path.join(SNAP, "universe.json"), encoding="utf-8") as fh:
        uni = json.load(fh)
    ends = [pd.Timestamp(d) for d in season_ends(snap)]
    tops = {str(d.date()): sorted(t for t, r in PU.rank_on(snap, d).items() if r <= PU.TOP_N) for d in ends}
    last = snap.sessions("SPY")[-1]
    today = sorted(t for t, r in PU.rank_on(snap, last).items() if r <= PU.TOP_N)
    ever = sorted({t for v in tops.values() for t in v})
    turnover = []
    keys = sorted(tops)
    for a, b in zip(keys, keys[1:]):
        turnover.append({"from": a, "to": b, "entered": sorted(set(tops[b]) - set(tops[a])),
                         "left": sorted(set(tops[a]) - set(tops[b]))})
    # completeness: public-float top 150 not in the candidate pool, classified
    g = PU.gaps(cand, EdgarClient())
    pred = {c for v in PREDECESSOR_CIKS.values() for c in v}
    exch = json.loads(PU._read_gz(os.path.join(PU.PDIR, "sec_company_tickers_exchange.json.gz")))
    live = {int(r[0]) for r in exch["data"]}
    for x in g:
        x["class"] = ("predecessor CIK (merged)" if x["cik"] in pred else
                      "listed today; not in pool/candidates" if x["cik"] in live else "no current listing (delisted / acquired / renamed)")
    dead = [x for x in g if x["class"].startswith("no current")]
    sizes = [len(v) for v in tops.values()]
    sectors = Counter(m["sector_source"].split(" ")[0] for m in uni["members"])
    return {"candidates": cand, "universe": uni, "tops": tops, "today": today, "ever": ever, "turnover": turnover,
            "gaps": g, "dead": dead, "sizes": sizes, "last": str(last.date()), "sector_sources": dict(sectors)}


def markdown(r: Dict[str, Any]) -> str:
    from core.reporting.tagged import fact, untagged_numbers

    def N(x, src):
        return fact(x, src, AS_OF, decimals=0).render(with_label=False)

    def B(x, src):
        return fact(x / 1e9, src, AS_OF, unit="bn", decimals=1).render(with_label=False)

    cand, uni = r["candidates"], r["universe"]
    S_c = "backtest/universe/pit/candidates.json"
    S_s = "snapshot 2026-11-04-pit"
    S_f = "SEC EDGAR frames dei EntityPublicFloat"
    seeds = Counter(c["seed"] for c in cand["candidates"])
    in_today = set(r["today"])
    L = ["# Point-in-time universe — construction, completeness, known gaps", "",
         "Rule (backtest/pit_universe.py): on each decision session D, the universe is the hundred largest US-listed domestic "
         "filers (10-K/10-Q) by market cap at the close of D-1 = share count from the latest periodic filing accepted before "
         "sixteen hundred ET on D-1 (cover-page dei EntityCommonStockSharesOutstanding if consistent with the same filing's "
         "weighted count, else the weighted count, else net income over diluted EPS) x split factor x split-adjusted close of D-1. "
         "Membership is computed inside the harness from snapshot data, so the poisoned-future tests cover it. <!-- text-only -->", "",
         "## Candidate pool", "",
         f"- Seed one: every S&P five hundred member on any date since `2014-01-01` in the fja05680/sp500 historical components file "
         f"(sha256 of the raw file in candidates.json; last row `{cand['inputs']['sp500_history']['last_date']}`): "
         f"{N(cand['inputs']['sp500_history']['tickers_since_2014'], S_c)} tickers, of which "
         f"{N(len(cand['sp500_history_tickers_without_live_listing']), S_c)} have no current NYSE/Nasdaq listing (delisted, acquired or renamed).",
         f"- Seed two: every company listed today on NYSE/Nasdaq/CBOE (SEC company_tickers_exchange.json) with a hundred million "
         f"or more shares in any EDGAR frame since `2013-01-01`. Pool: {N(cand['pool']['total'], S_c)} companies.",
         f"- Screen: EDGAR frames share counts x yfinance month-end closes at every quarter end in `2014-03-31..2026-09-30`; candidate "
         f"if ranked two hundred or better at any quarter end (screen values can be overstated, which only enlarges the pool).",
         "- Seed three: listed companies ranked one hundred fifty or better by public float (dei EntityPublicFloat, a USD market value "
         "on every 10-K cover, needs no prices) in any year in `2014-01-01..2025-12-31`. This catches multi-class filers with no usable "
         "share count in the frames (Visa) and high-priced names below the share threshold (MercadoLibre). <!-- text-only -->",
         f"- Candidates: {N(len(cand['candidates']), S_c)} (S&P five hundred history {N(seeds.get('sp500_history', 0), S_c)}, "
         f"listed sweep {N(seeds.get('listed_sweep', 0), S_c)}, public-float seed {N(seeds.get('public_float', 0), S_c)}). "
         f"In the snapshot: {N(len(uni['members']), S_s)} with prices and EDGAR data; flagged or dropped "
         f"{N(len(uni['flagged']), S_s)} (list in snapshot universe.json; foreign private issuers filing annual reports only are dropped here).",
         "", "## Membership over time", "",
         f"- Distinct companies in the top hundred at any quarter-end session since `2014-06-30`: {N(len(r['ever']), S_s)}. "
         f"Today's top hundred (session `{r['last']}`): {N(len(r['today']), S_s)}.",
         f"- Companies in the top hundred at some quarter end but NOT in today's top hundred: "
         f"{N(len(set(r['ever']) - in_today), S_s)}. These are what a today's-list universe silently drops: "
         + ", ".join(sorted(set(r["ever"]) - in_today)) + ".",
         "", "| quarter-end session | top-hundred size | entered | left |", "|---|---|---|---|"]
    for t in r["turnover"]:
        L.append(f"| `{t['to']}` | {N(len(r['tops'][t['to']]), S_s)} | {', '.join(t['entered']) or '—'} | {', '.join(t['left']) or '—'} |")
    L += ["", "## Share classes, ticker changes, predecessors", "",
          "- One entry per company (CIK). Dual listings use one class for prices and total economic shares for the cap: "
          "GOOGL (GOOG), FOXA (FOX), NWSA (NWS), BRK.B (BRK.A; Berkshire reports Class A-equivalent shares, so BRK.B price x "
          "fifteen hundred), LEN (LEN.B), BF.B, HEI. <!-- text-only -->",
          "- Ticker changes (FB to META, ANTM to ELV, UTX to RTX, KRFT to KHC, ...) are handled by CIK: Yahoo keeps a renamed "
          "company's full history under its current ticker. <!-- text-only -->",
          "- Re-registrations (new CIK, same company) are merged with their predecessor CIK(s): "
          + "; ".join(f"{k} <- {v}" for k, v in sorted(PREDECESSOR_CIKS.items())) + ". <!-- text-only -->",
          "", "## Completeness check and known gaps", "",
          f"Every company ranked one hundred fifty or better by public float in any year in `2014-01-01..2025-12-31` "
          f"({S_f}) that is not a candidate: {N(len(r['gaps']), S_f)}. Classified: "
          f"predecessor CIKs already merged {N(sum(1 for x in r['gaps'] if x['class'].startswith('predecessor')), S_f)}; "
          f"listed today but not candidates {N(sum(1 for x in r['gaps'] if x['class'].startswith('listed')), S_f)} "
          "(checked: these carry public-float values in the wrong unit, e.g. thousands, and are small companies); "
          f"no current listing {N(len(r['dead']), S_f)}. <!-- text-only -->", "",
          "**Known gaps: companies that were large and have no price history here** (Yahoo keeps none for delisted tickers; "
          "Stooq, Nasdaq, Tiingo, Polygon, Alpha Vantage and stockanalysis.com are blocked by this sandbox's network policy and "
          "Finnhub candles return 403 on this plan). Listed when the best public-float rank is fifty or better or the float "
          "exceeds twenty billion USD (rows whose float exceeds fifteen times the company's largest reported total assets are dropped: tagging errors, float reported in thousands); the float understates market cap for controlled companies. Values in billion USD. <!-- text-only -->", "",
          "| company (EDGAR name) | CIK | first..last year in public-float top hundred fifty | years | best float rank | max public float |", "|---|---|---|---|---|---|"]
    for x in r["dead"]:
        if x["plausible"] and (x["best_float_rank"] <= 50 or x["max_public_float_usd"] >= 2e10):
            L.append(f"| {x['name']} | {N(x['cik'], S_f)} | `{min(x['years'])}-01-01..{max(x['years'])}-12-31` | {N(len(x['years']), S_f)} | {N(x['best_float_rank'], S_f)} | "
                     f"{B(x['max_public_float_usd'], S_f)} |")
    L += ["", "**Effect of the gaps.** Missing names cannot enter the ranking, so the hundredth slot goes to the next company "
          "(the universe is complete in size but slightly too small in average cap), and their events are absent. Most are "
          "acquisitions (Celgene, Allergan, Monsanto, Time Warner, Express Scripts, EMC, Anadarko, Shire), Walgreens (taken private) "
          "and Dow Chemical (DowDuPont merger). Acquired firms typically end with a takeover premium, so excluding them biases "
          "buy-and-hold slightly DOWN; a strategy that would have been long into a takeover misses that gain, one that was flat "
          "misses nothing. Their earnings events are a few percent of the sample at most. They are not recoverable without a "
          "delisted-price source (CRSP, Norgate, EODHD). <!-- text-only -->", "",
          "**Other known limitations.** Sectors: GICS from the current S&P 500 file where available, else an SIC-to-GICS map "
          f"(sector sources: {', '.join(f'{k} {N(v, S_s)}' for k, v in sorted(r['sector_sources'].items()))}); current sector "
          "applied to history (e.g. Visa/Mastercard moved from IT to Financials in `2023`). Sector ETFs that did not yet trade "
          "(XLC before `2018-06`, XLRE before `2015-10`) are replaced by SPY for that event. A company needs three hundred sessions "
          "of price history before its first event, so large IPOs enter the ranking at once but trade only after about fourteen "
          "months. <!-- text-only -->", ""]
    md = "\n".join(L)
    bad = untagged_numbers(md)
    if bad:
        raise ValueError(f"untagged numbers: {bad[:8]}")
    return md


def main() -> None:
    r = build()
    out = os.path.join(ROOT, "results", "pit_universe_2026-11-04")
    with open(out + ".md", "w", encoding="utf-8", newline="\n") as fh:
        fh.write(markdown(r))
    with open(out + ".json", "w", encoding="utf-8", newline="\n") as fh:
        json.dump({k: r[k] for k in ("tops", "today", "ever", "turnover", "gaps", "last")}, fh, indent=1, sort_keys=True)
    print("written", out + ".md")


if __name__ == "__main__":
    main()
