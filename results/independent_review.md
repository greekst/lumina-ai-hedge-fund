# Independent review — Session 2 (Phase D)

Reviewer: a separate Claude subagent started fresh at ~18:47 UTC on 2026-11-04. It had not seen this session's work. It was given only the
repository path and this instruction, verbatim: "Audit `backtest/` and the new data paths for look-ahead bias, survivorship bias,
data errors, overlapping-window statistics and anything that would overstate results. Report findings ranked P0/P1/P2 with file and line."
It changed no files. Its report is reproduced verbatim below. It is reviewer prose, not a generated report: its figures are the
reviewer's own measurements, not harness outputs. What was fixed is at the end, and in LOG.md.

---

## Audit: `backtest/` and the new EDGAR/S&P 100 data paths

I found one confirmed look-ahead (P0). It hits a single event and has almost no effect on the results. The bigger problem is that the "selection skill" statistic and the month-clustered confidence intervals rest on assumptions the data does not support. I changed no files. I wrote the check scripts in `/tmp/claude-0/-home-user-lumina-ai-hedge-fund/5a7f2323-207e-5561-8f4d-5f01463cd5ae/scratchpad/` (a1.py to a5.py). Offline tests: `python -m pytest -q tests/test_walkforward.py tests/test_edgar.py` gives **19 passed**. The bare `pytest` command fails in this shell because that interpreter has no numpy.

### P0 — look-ahead

**P0-1. A pre-market release can still be placed after the close.**
- **Where:** `backtest/sec_crosscheck.py:50-63` (`resolve_event_time`), used at `backtest/snapshot_sp100.py:320-321`.
- **The gap:** the "earlier of the 8-K time and the vendor time" rule only works if one of the two is right. When the vendor time is a 16:00 placeholder and the 8-K is accepted late, both times say "after the close". The decision day D then becomes the release day, so the entry close already contains the news.
- **Confirmed case:** SCHW 2025-01-21. Vendor time 16:00, 8-K accepted 16:17:50 (SCHW's 8-K arrives about 16:17 every quarter), but SCHW releases at about 07:00. The stock moved +5.92% on D (XLF +0.84%) and −0.41% on D+1. Factors-only and buy-and-hold enter at that post-news close. The council was flat on this event.
- **Impact:** 1 of 1,183 events, so the headline numbers barely change. The bug class is still open: 480 of the events used have a vendor time of exactly 16:00.
- **Fix:** keep a per-issuer timing rule (pre-market vs after-close) and flag events that break it. Or add a price check that raises an error when the abnormal move on D is large but the move on D+1 is small. Three other events show that pattern and should be checked by hand (low confidence, probably market moves): LLY 2024-02-05, MPC 2026-08-03, ETN 2024-07-31.

### P1 — overstated or mis-stated results, and data errors

**P1-1. "Selection skill" is not free of survivorship bias, contrary to the claim at `walkforward.py:460-463` and `stats.py:58-62`.**
- **Why:** in a universe picked by today's market cap, each ticker has a persistent drift. 66% of tickers have a positive mean T+20 return relative to their sector. PLTR averages +12.8% per event, SNDK +25.5% on 2 events and STX +8.6%; UNH averages −4.2%.
- **Effect:** "long minus flat" mixes skill with which tickers a strategy tends to be long on. The council's long rate correlates −0.12 with each ticker's leave-one-out drift.
- **Evidence:** after demeaning returns by ticker, selection skill goes from −0.73% to +0.002% (council) and from −0.42% to −0.005% (factors-only). The current negative figure is therefore partly an artefact too.
- **Fix:** demean within ticker (ticker fixed effects) or use within-ticker comparisons.

**P1-2. Clustering by calendar month understates uncertainty.**
- **Where:** `walkforward.py:365`, `stats.py:24-41`.
- **Why:** 20-session windows starting late in a month overlap the next month. Events are concentrated in Jan/Apr/Jul/Oct (51–70 each) versus 5–8 in Mar/Jun/Sep/Dec. So there are about 13 independent earnings seasons, not 36 months.
- **Evidence (council − factors-only at T+20):** standard error rises from 0.30% (month clusters) to 0.35% (season clusters). The CI widens from [+0.17%, +1.32%] to [+0.04%, +1.41%]. MDEs grow by the same amount.
- **Not covered at all:** correlation within a ticker across its 12 events.
- **Fix:** cluster by earnings season, or two-way by season and ticker.

**P1-3. Universe survivorship (acknowledged in the log, but a few points are understated).**
- **Where:** `universe.py:154-172`.
- **Membership:** members added to the S&P 500 or listed in 2024–26 include PLTR, DELL, CRWD, GEV and SNDK. Their 2023–24 events are in the sample only because of later gains.
- **Exclusions not applied:** GEV and SNDK are flagged in `universe.json` (EDGAR has no periodic filing before 2022) but are still among the 100 tickers in the run.
- **The paired advantage:** council − factors-only (+0.73%) comes from the council being long 66% of the time versus 43% in this universe. It should not be read as an effect.

**P1-4. Share-count unit error gives MCD a P/E of 0.0 on 10 of its 12 events.**
- **Where:** values stored by `edgar.py:235-245`, consumed at `pit.py:198-205`.
- **The data:** MCD's XBRL tags `WeightedAverageNumberOfDilutedSharesOutstanding` in millions (e.g. 718.2), which makes the implied EPS about 1e6 times the reported EPS.
- **Effect:**
  - In mock mode the effect is hidden, because `pe or 18.0` treats 0.0 as missing (`graham_agent.py:19`, `michael_burry_agent.py:19`).
  - The wrong value does reach the CSV and the level-1 LLM prompt ("Trailing P/E: 0").
  - At anonymisation level 2 it is banded as "below 12".
- **Fix:** no sanity check exists. Comparing NI / shares with the reported EPS would catch it (COF and BA also show >25% mismatches).

**P1-5. Year-on-year comparisons across spin-offs and restatements produce false growth figures.**
- **Where:** `pit.py:125-155` compares this year's YTD with the prior year's figure *as originally reported*.
- **Example:** GE revenue growth is −42% to −43% for events from 2024-10 to 2025-07 (the GE Vernova spin), and −11% to −13% earlier (the GE HealthCare spin). P/E and ROE mix continuing and discontinued operations.
- **Fix:** use the prior-period comparative from the current filing. It is in the same accession, so it is point-in-time safe, and companyfacts provides it.

### P2 — reporting and data hygiene

1. **Mislabelled sources.** `walkforward.py:388-389` hard-codes "fundamentals: Finnhub … events: yfinance" in the sp100 summary. That run actually uses EDGAR data and the earlier-of event rule. This is a provenance error under hard rule 5.
2. **Misleading Sharpe and drawdown.** `walkforward.py:303-316` takes the mean event return per quarter, treats it as a quarterly NAV (flat events count as 0) and annualises with √4 for every horizon. It is not the return series of any tradeable portfolio.
3. **i.i.d. CI shown first.** `walkforward.py:290-295, 326-328`: the first council − factors table shows an i.i.d. bootstrap CI as "95% bootstrap CI". It is narrower than the clustered one.
4. **Hit rate is not comparable across strategies.** `walkforward.py:196` counts a flat decision as a hit when the return is ≤ 0. Buy-and-hold is never flat, so its hit rate uses a different definition.
5. **Stops are reported but never applied.** `walkforward.py:197-200` records `stop_breached` but the net return ignores the stop, so the CRO's risk control is not simulated.
6. **Stale or missing fundamentals.**
   - SPGI's FY2024 10-K has no usable revenue or NI rows (`edgar.py:219-221` skips it), so the 2025-04-28 event uses data ending 2024-09-30 (211 days old).
   - DIS: a 10-K/A without revenue, equity or shares replaces the original 10-K for the same period (`pit.py:120`).
   - P/E is null for every V and BRK.B event (12/12 each), for 10/12 BA events and for 9/12 MRVL events.
   - Revenue growth is null for every CRWD, NEE and TJX event.
7. **Loss-making firms look average.** `pit.py:209` sets P/E to None when EPS ≤ 0, and the agents then fall back to 18 or 20.
8. **Many comparisons, no correction.** There are 11 sectors × 3 VIX regimes × 3 horizons × several metrics with no multiple-testing adjustment. The text already avoids claiming significance, which is good.
9. **Live council (still blocked by quota).** The held-out design is sound: D after `MODEL_KNOWLEDGE_CUTOFF` (`llm_client.py:32`) and the quarter guess hit rate is 0/20. Two caveats: level-1 anonymisation fails the leakage check (top-1 hit rate 25%, n=20), and a preview model's documented cutoff is a residual risk.

### Checked and clean
- Price data: no gaps against SPY, no NaNs, no duplicate dates, no high/low inconsistencies. Large daily moves match known earnings days. PGR's 6% adjustment jump is its special dividend.
- Splits: the adjustment ratio is stable.
- The BLK/XOM predecessor-CIK merge shows no duplicates.
- No filing for the quarter being announced is ever available at decision time.
- Features use data through D−1, VIX uses D−1, and the filings cutoff is min(announcement, 16:00 on D).
- Costs are 20 bps round trip.
- Saturday BRK releases and vendor-only events resolve correctly.

---

## Response (what was changed)

| finding | action | effect |
|---|---|---|
| **P0-1** pre-market release placed after the close when the vendor stamp is "16:00" and the 8-K is late (SCHW 2025-01-21) | **Fixed.** `sec_crosscheck.apply_issuer_convention`: if the vendor says after-close, the 8-K is on the same day, and at least 75% of the issuer's last eight *earlier* releases were pre-market, the release is treated as pre-market (D moves one session earlier; it can only remove information). Applied in `snapshot_sp100.py`. A price diagnostic (large sector-relative move on D, small on D+1) was added to `results/events_8k_vs_yfinance_2026-11-04-sp100.md`. | 6 events moved: SCHW ×2 (true positives), PLTR ×3 and MCD ×1 (issuers that changed release time; one session early, conservative). The three remaining diagnostic flags were checked against the filings. AMZN 2026-10-29: 8-K accepted 16:05 ET, vendor 16:00, so the release was after the close of D. LLY 2024-02-05: 8-K accepted 07:04 ET on 02-06, vendor 06:00, so D is the previous session. In both cases the two sources agree and the large move on D came before the filed release. PLTR 2023-02-10 is the conservative shift. None is a timing error. The reviewer's ETN/MPC candidates do not pass the diagnostic threshold. |
| P1-1 selection skill not free of ticker drift | **Fixed.** Within-ticker (fixed-effects) selection skill added and used as the headline. | Council T+20 goes from −0.73% (pooled) to −0.00% [−1.50%, +1.54%]. Conclusion unchanged: no skill. |
| P1-2 month clusters understate uncertainty | **Fixed.** Clusters = earnings season (calendar quarter of D), 12 seasons. | Council − factors T+20 CI widens from [+0.17%, +1.32%] to [+0.01%, +1.45%]. Within-ticker correlation across seasons is still not modelled (documented). |
| P1-3 universe survivorship; GEV/SNDK flagged but kept | **Documented, not fixed** (needs a point-in-time universe). GEV/SNDK are kept on purpose: their flag is "no filings before 2022" (real spin-offs), and the harness requires 300 sessions of history before any event. | HANDOFF states the paired advantage must not be read as an effect. |
| P1-4 MCD share count in millions → P/E 0 | **Fixed.** `pit.py`: if NI / shares disagrees with the same filing's (non-truncated) diluted EPS by more than 25%, shares = NI / EPS from that filing. Unit test added. | MCD P/E restored. Session 1: 0 of 360 decisions changed. |
| P1-5 YoY growth across spin-offs and restatements | **Not fixed** (open). Needs the prior-period comparative from the *current* filing. | Listed in HANDOFF next steps. |
| P2-1 summary hard-coded "Finnhub / yfinance" | **Fixed.** Sources are read from the snapshot manifest. | |
| P2-3 i.i.d. CI shown first, unlabelled | **Fixed.** Labelled "i.i.d. (too narrow, see clustered CIs)". | |
| P2-2, P2-4..P2-8 | **Not fixed**, documented: Sharpe/drawdown are descriptive event aggregates, not a tradeable NAV; hit-rate definitions differ for flat decisions; stops are recorded, not simulated; some fundamentals are stale or null (SPGI, DIS 10-K/A, V/BRK.B P/E); loss-makers fall back to default P/E; many cells, no multiple-testing correction (no cell is claimed significant). | |
| P2-9 live council | Agreed. Level 1 fails the leakage check; level 2 is unverified (quota). | |

Reruns after the fixes: walk-forward on snapshot 2026-11-04-sp100, two runs, identical sha256 `f5735aab38bfac3513372436d01f9d12b0d2534605791c93fa2ef5c81a8cdd01`; Session 1 snapshot rerun `929fe3f3…` (column changes only, 0 decision changes); the event cross-check and the live-council status report were regenerated.
