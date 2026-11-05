# Independent review — Session 4 (Phase D)

Reviewer: a separate Claude subagent, started fresh at ~23:29 UTC on 2026-11-04, after the Phase C commit. It had not seen this
session's work. It was given only the repository path (with how to activate the virtualenv, run the tests and rebuild the snapshot
offline to a scratch id, a scratch directory, the SEC rate limit, and the instruction to change no repository files and make no live
LLM calls) and this instruction, verbatim: "Audit the new snapshot, the delisted-price data, the event fixes and the H1 rerun for
survivorship bias, look-ahead, data errors, clustering mistakes and anything that would overstate results. Rank findings P0/P1/P2
with file and line." It changed no repository files. Its report is reproduced verbatim below (reviewer prose: its figures are its own
measurements, not generated report values). Responses are at the end and in LOG.md.

Note on the reviewer's "provenance note": the "other process" that edited `backtest/snapshot_pit.py` during the review was this
session's main agent fixing a CI static-check failure (commit ce48f64: a module-level `import numpy` for a string type annotation).
The offline rebuild it ran gave a byte-identical snapshot (no diff in git).

---

# Independent review (Session 4): pit2 snapshot, delisted gap, event rules v2, H1 rerun

## Bottom line
**No P0. Nothing I found overstates H1 or changes its decision.** I reran the pre-registered command on `2026-11-04-pit2` into scratch. It reproduced the CSV (`e82c04cc…`), the summary JSON (`8228b5a4…`) and the combined digest `8337e6b5…` byte for byte: S = +0.078%, p05 = −0.453%, p = 0.396, n = 4,692 / 47 / 188.

Look-ahead checks on the H1 event timing came out clean. The new 8-K-only events and the "issuer convention" events err early (one session too soon), not late.

The real problems are elsewhere:
- **Delisted-gap estimate is not a bound.** It misses whole top-100 companies and counts one spurious one, so the stated "upper bound 147" is not an upper bound (P1).
- **Spin-offs stored as yfinance "splits"** inflate point-in-time market caps and put a +61% artifact in DHR's Close series (P2, older data, effect on H1 is negligible).

Tests: `LUMINA_LLM_MODE=mock pytest -q` gives **131 passed, 1 skipped** (182 s).
Offline rebuild of pit2 to a scratch id: identical sha256 for all 2,273 files; only `snapshot_id` differs. The scratch directory was removed and `git status` is clean.

**Provenance note:** partway through my review another process (not me) edited `backtest/snapshot_pit.py` (moved `import numpy`) and rebuilt pit2 in place (`python -m backtest.snapshot_pit2 --id 2026-11-04-pit2 --offline`). The tree was clean again when it finished. All my numbers come from a `git archive HEAD` copy, except the reaction pickle from the in-repo snapshot, which was taken before that process started.

## P0
None.

## P1

**P1-1. The delisted-gap search misses top-100 companies, and the "upper bound" is not one.**
Files: `backtest/delisted_gap.py:55-57`, `backtest/pit_universe.py:554` and `:575`.

Three separate causes:

- **(a) A CIK counts as "live" if any security still trades.** E. I. du Pont (CIK 30554) still has a listed preferred (`CTA.PA`). It is in the candidate pool but carries `exclude_reason` "only listed security is a preferred share", so it is never ranked and never counted as a gap.
  - Its public float was $57.8B / $56.6B / $70.0B in 2015/16/17. The 100th plausible float in those years was $46.4B / $43.2B / $49.8B, so it was clearly top 100.
  - It had **11 earnings 8-Ks** from 2015-01 to 2017-07 (`filings/CTA_PA.json`), none counted.
  - The `DD` ticker only ranks from 2017-09 (CIK 1666700), so these events are simply missing.
- **(b) The search relies only on `dei:EntityPublicFloat` XBRL frames.**
  - 21st Century Fox (CIK 1308161) has no float frames after 2012 (checked with one `companyconcept` request). With a cap of roughly $55–90B it was top 100 from 2015 to 2019; I estimate **~16–17 lost events**, not verified with prices.
  - Controlled companies are invisible to a float screen. VMware's float was $7–12B, but its cap was about $55–75B, so it was plausibly top 100 around 2018–2020. That is an unquantified few to ~10 events.
- **(c) The top 150 is taken before the plausibility filter (`:554` before `:575`).** Floats tagged ×1000 by mistake fill **16–67 of the 150 slots per year** (2022: 67). Applying the filter first adds 5 companies at plausible rank 131–142: Baker Hughes Inc, Johnson Controls Inc, Electronic Arts, Mylan II, Williams Partners (an MLP, so not relevant). These affect the upper bound only.
- **(d) One counted company is spurious.** Discover Financial's 2022-12-31 float frame is $82.5B (`0001393612-23-000007`), but its cap then was about $25–35B. Its 4 "lost (estimate)" events in 2023Q2–2024Q1 are wrong.
  - Without them, the 2023-10..2026-09 Phase B window has essentially 0 estimated lost events, not 2.

**Measured effect:** estimate goes from 82 to about ≥105 (≈2.2%); upper bound from 147 to ≥~175 (≈3.6%), plus VMware.
- The conclusion does not change: the gap is still small and concentrated in 2015–2019.
- The wording is wrong: "upper bound" should read "partial upper bound for the companies found". The docstring's "public-float top 150" is effectively a top ~85–135.
- The H1 count used for the percentages is the Session 3 figure (4,661), not 4,692.

**Fix:**
- Rank floats among plausible filers only.
- Do not treat a CIK as live when its only listing is a preferred or another non-common security (reuse `exclude_reason`).
- Add a hand list for float-invisible companies (21CF, VMware) and a sanity check of float against assets/cap (it would catch Discover).
- Relabel the bound. A wrong upper bound overstates how complete the PIT universe is.

## P2

**P2-1. Spin-offs stored as yfinance "splits" inflate PIT market caps** (`backtest/pit_universe.py:318-320`).
- Market cap is computed as shares × Π(split ratios in (as_of, day]) × raw price. Spin ratios (DD 1.487, HPQ 2.202, T 1.324, GE 1.281, DHR 1.319, …; 60 such entries on large caps) therefore inflate share counts until the next post-spin filing.
  - DD 2019-07-30: computed $77.9B vs about $55B true.
  - HPQ 2015-11-02: computed $54.8B vs about $24B true.
- I recomputed every D-1 rank for H1-window events with the spin ratios neutralised:
  - **Wrongly in:** HPQ 2015-11-24 (rank 76, true ~164) and DD 2019-07-31 (rank 74, true ~107).
  - **Wrongly out (rank 101 → 100):** CTSH 2015-11-03, CCL 2015-12-17, SO 2019-07-30, BMY 2026-02-04.
  - RTX 2020 is also flagged by my correction, but the Yahoo ratio happens to approximate the Raytheon merger, so I am not counting it.
  - Dropping the two wrong inclusions moves S from +0.078% to +0.082%.
- **Fix:** keep a whitelist of true splits (simple ratios plus a hand list such as DD 2019-06-03 = 1/3 and HLT 2017 = 1/3); give spin entries a ratio of 1 for share counts.

**P2-2. DHR's Close series has a +61.2% one-day artifact on 2016-07-05 (Fortive spin)** (`backtest/snapshot.py:73`, where `Close` = Yahoo Adj Close).
- CloseSplitAdj moves only +3.6% that day.
- DD 2019-06-03 shows +17.8% in both columns, and HPQ 2015-11-02 shows +13%.
- No H1 return window (T+1/5/20) crosses any artifact; I checked all 18 Close-vs-CloseSplitAdj divergences and all non-standard split dates.
- They do contaminate the 60-day features for about 7 H1 events, e.g. DHR 2016-07-22 (both strategies went flat), DD 2019-07-31, HPQ 2015-11-24, T 2022-04-20, GE 2023-01-23. That is 0.15% of the sample.
- **Fix:** flag days where |Close return − CloseSplitAdj return| > 3% and the date is in `splits` with a non-simple ratio; rebuild the adjusted Close.

**P2-3. Both "pre-market" timing rules put D one session early, most of the time** (`backtest/sec_crosscheck.py:79`, `backtest/snapshot_pit.py:200`). This removes information, so it is not look-ahead, but it is mis-timing.
- Largest |return| within D..D+2 (liquid names, median |r| > 0.5%):
  - issuer-convention events: peak at **D+2 in 67.5%** (n = 271);
  - 8-K-only events: peak at D+2 in 47.4% (n = 460).
- Volume peaks in the H1 sample (D+2 share): issuer-convention 82% (n = 22), 8-K-only 36% (n = 36). Normal vendor events peak at D+1 in 84%.
- Cause: an 8-K accepted after 16:00 is timed at 07:00 the same day.
- Effect on S: dropping both groups moves it to +0.091%. T+1 results for these events measure the pre-announcement day.
- **Fix:** for 8-Ks accepted ≥ 16:00 use the acceptance time itself when the issuer's past agreeing events show after-close releases, and re-validate the issuer-convention rule against D+1 vs D+2 reactions.

**P2-4. The event-selection filters use future filings** (`snapshot_pit.py:177` `earnings_8k_events` needs the later 10-Q; `:216` `eight_k_lag_ok` uses the issuer's whole history; `VENDOR_GAP_DAYS` looks ±60 days).
- These choose which events exist from non-return data that was not available at D.
- In H1 this touches only 36 events (BLK 30). I checked BLK by hand: one Item 2.02 8-K per quarter, accepted 06:46–10:13, pre-market releases, so D is correct.
- Disclose it; or make the timeliness filter expanding-window.

**P2-5. Stale labels and survivor replacements.**
- `compare_universes.py:92` still labels column B "Session 3 data" in the pit2 report.
- `delisted_gap.py` divides by the Session 3 H1 count (4,661).
- The gap reports do not mention that each lost top-100 event is replaced by a rank-101-ish survivor's event, so roughly the same number of events in the sample are survivor substitutes.

## Checked and found clean
- **Event timing look-ahead, H1 sample (4,692):** volume-peak test (D-1/D/D+1/D+2). Only 7 events peak at or before D with volume > 2.5× baseline and > 1.5× D+1.
  - All 7 have non-earnings explanations: TMUS–Sprint merger news, BKNG falling with Expedia's results, ECB QE day, and so on.
  - Return-reaction test: "late" rate 1.3–2.6% by class, against a 1.3% baseline.
- **All 6 P2-2 re-timed H1 events** (BRK.B, COST ×2, INTC, KHC, PGR) are correct or early. All 39 vendor-only H1 events look plausible. None of the 7 vendor-only events kept by the "release 8-K on that day" exception is in H1.
- **8-Ks coded Item 2.01 instead of 2.02** (C, MS, AMAT, GEV, RTX, ELV) occur only on vendor-matched events, so timing is unaffected.
- **Snapshot integrity:** inputs match the frozen manifests; the Item 2.02 lists show 0 frozen-vs-fresh mismatches; offline rebuild is identical.
- **Reproducibility:** H1 rerun byte-identical, as listed in the bottom line.
- **Clustering:** S's SE barely moves across cluster definitions (0.307–0.325%):

  | clusters (× ticker) | SE | p05 |
  |---|---|---|
  | season (as reported) | 0.317% | −0.453% |
  | season shifted 3 weeks | 0.318% | −0.452% |
  | half-year | 0.307% | −0.416% |
  | year | 0.325% | −0.472% |
  | week | 0.316% | −0.448% |
  | season × sector | 0.310% | −0.468% |

  Re-demeaning within each bootstrap replicate gives SE 0.267%, so the reported 0.317% is conservative.
- **Data errors in H1 rows:** no duplicate (ticker, D) pairs, no same-ticker events < 30 days apart, no missing sector returns. Every |T+5| > 35% outlier is a real event. No spin artifact falls inside a return window.
- **DELL/DVMT price splice:** DELL ranks 148–223 from 2016 to 2019, so it is never in the sample.
- **Ranking at D-1 and the 300-session warm-up** are point-in-time safe.
- **HYPOTHESIS.md:** nothing above the RESULTS line changed.

## Could not verify
- No delisted prices exist anywhere in the repo or cache, so there is nothing price-based to audit for delisted names. The bias direction remains unknown.
- 21CF and VMware event counts and top-100 status are estimates without prices or filings fetched (I made one EDGAR request each, to my scratch cache).
- 2026 prices cannot be checked against an outside source.
- The "true" caps in P2-1 assume spin entries should have ratio 1 (1/3 for DD 2019-06 and HLT 2017).

---

## Response (what was changed)

No P0, so the H1 rerun stands as run (snapshot `2026-11-04-pit2`, digest `8337e6b5…`) and nothing was rerun. Every P2 effect the
reviewer measured moves S by at most +0.013 percentage points, in the direction of more skill, and none changes the decision.

| finding | action | effect |
|---|---|---|
| P1-1 delisted-gap search incomplete; "upper bound" not one | **Fixed** in `backtest/delisted_gap.py` (`find_gaps`): plausibility before ranking; companies whose only listing is a preferred share count as gaps (du Pont); isolated float spikes (> 2x both neighbouring years) dropped (Discover 2022; a global-median screen was tried first and wrongly cut Aetna's real growth); denominator is the Session 4 H1 count; "upper bound" relabelled "partial upper bound"; 21st Century Fox and VMware named as invisible to a float screen; survivor substitution stated. Session 3's `pit_universe.gaps` and its report are unchanged. | Estimate 82 → **84 events (1.8%)**, partial upper bound 147 → **159 (3.3%)**; plus 21CF (reviewer: ~16) and VMware (unquantified). Du Pont adds 6 (the float-based test is stricter than the reviewer's 11), Johnson Controls/EA/Mylan add to the bound, Discover's spurious 4 are gone. Still concentrated in 2015–2019. |
| P2-1 spin-offs as splits inflate PIT caps | **Open** (needs a split whitelist and a new snapshot; prices are byte-copies of the frozen base). Listed in HANDOFF. | Reviewer: 2 events wrongly in (HPQ 2015, DD 2019), 4 wrongly out; S +0.078% → +0.082%. |
| P2-2 DHR/DD/HPQ adjusted-Close artifacts | **Open**, same fix path. | No H1 return window affected; ~7 events' 60-day features (0.15%). |
| P2-3 pre-market timing rules often one session early | **Open**, disclosed. Early timing removes information; it is not look-ahead. | Dropping both groups: S +0.091%. |
| P2-4 event selection uses later filings / whole-history filter | **Disclosed** here and in HANDOFF (identification only, no outcome; BLK checked by hand). | 36 H1 events. |
| P2-5 stale labels; survivor substitution | **Fixed**: column-B label in the pit2 comparison; delisted-gap denominator and wording. | — |
