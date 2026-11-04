# Independent review — Session 3 (Phase E)

Reviewer: a separate Claude subagent, started fresh at ~21:30 UTC on 2026-11-04, after the Phase D run. It had not seen this
session's work. It was given only the repository path (with how to activate the virtualenv and run the tests, a scratch directory,
and the instruction to change no files and make no live LLM calls) and this instruction, verbatim: "Audit the point-in-time universe
construction, the extended snapshot, and the H1 test for survivorship bias, look-ahead, data errors, clustering mistakes and anything
that would overstate results. Rank findings P0/P1/P2 with file and line." It changed no files. Its report is reproduced verbatim below.
It is reviewer prose, not a generated report: its figures are the reviewer's own measurements. What was done about each finding is at
the end, and in LOG.md.

---

## Audit: PIT universe, extended snapshot `2026-11-04-pit`, and the H1 test

**Bottom line:** I found no P0. There is no look-ahead in the membership rule, the event timing or the H1 test. The universe does have real data errors, and some of the written claims are overstated, but a corrected rerun leaves the H1 result and the Phase B result unchanged.

I modified nothing in the repo. Scratch scripts and outputs are in `/tmp/claude-0/-home-user-lumina-ai-hedge-fund/66c8314e-a542-5033-a15c-68f5b2a4907e/scratchpad/review/`:
- `corrected_run.py`: a counterfactual Phase D run with the universe errors below fixed in memory.
- `corrected.csv` and `corrected_summary.json`: its output.
- `caps.pkl` and `top.pkl`: PIT market caps at every month-end from 2014-11 to 2026-11.

**Counterfactual result.** It fixes the share-unit errors, the SHW split error and the float check (P1-1 to P1-3), and uses the pre-registered settings (mock LLM, `PYTHONHASHSEED=0`).
- It removes 26 events (RPAY 7, SHW 2, 17 names displaced from rank 100) and adds 27 (COP 13, SCCO 3, MU 2, TSLA 2, WDC 2, APP, CB, LIN, LMT, PNC).
- **H1:** S goes from +0.072% to +0.093%; p05 from −0.41% to −0.44%; CI from [−0.54, +0.65] to [−0.55, +0.71]. H0 is still not rejected.
- **Phase B, column C:** buy-and-hold excess vs sector ETF at T+20 over 2023-10..2026-09 goes from +0.116% to +0.104%. The "about 12% survives" conclusion stands.
- **2015–2026 buy-and-hold at T+20:** −0.022% becomes −0.029%.

---

### P0 — none found

### P1 — data errors and overstated or mis-stated claims

**P1-1. Share counts tagged ×1000 pass every guard** (`backtest/pit_universe.py:111-113`, `:237-243`, `:302-305`)
- **Cause:**
  - The NI/EPS unit check `1e-3 <= w/implied <= 1e3` (line 112) is inclusive at exactly 1e-3, so an error of exactly one thousand passes.
  - The jump filter accepts a wrong level once a second filing repeats it.
  - The float check cannot catch a company that tags both its shares and its float ×1000.
  - The cap/assets guard only runs when there is no float (line 304).
- **COP:** weighted diluted shares tagged at 1.24e6 in most 10-Qs/10-Ks, so its cap shows as about $0.1bn in 2015-08..2016-08, 2017-02..2017-10 and 2018-10..2020-11. ConocoPhillips (about $50–90bn) drops out of the universe for about 3.5 years, 13 events. The "COP left/entered" lines in the turnover table of `results/pit_universe_2026-11-04.md` are this artefact.
- **RPAY (Repay Holdings, about $0.3–0.8bn):** shares tagged at 89–103bn and the float at $696bn–$950bn. It ranks 9th to 45th from 2024-11 to today: 25 month-ends, cap/assets about 275x.
  - It has 7 events in Phase D and Phase B column C, 12 in column B.
  - It sits in "today's top 100", which takes a slot from a real company.
- **LIN:** the 2018-11-09 10-Q gives 25,000 shares (NI/EPS), so Linde plc (about $90bn) is missing from 2018-11 to 2019-05.
- The same ×1000 pattern hits GRMN, ICE, HSY, MPWR and others, but those are outside the top 100.
- **Fix:**
  - Treat w/implied outside [1/200, 200] as a unit error.
  - Apply the cap > 100x assets guard always, not only when there is no float.
  - Check a confirmed jump against total assets as well.
  - Add COP, RPAY and LIN as regression cases.
- The module docstring (lines 17-18) says NI/EPS replaces a weighted count that is off by more than 25%; the code uses 1000x.

**P1-2. SHW split counted twice for six months** (`pit_universe.py:171`, `:298`)
- **Cause:** the 2021-04-28 10-Q tags the post-split cover count (2.66e8) with dei end 2021-03-31, one day before the 3:1 split on 2021-04-01. `split_factor_after(as_of)` then multiplies by 3 again.
- The correct next filing is held by the jump filter: 263/797 = 0.330, just under 1/3.
- **Effect:** the cap reads about $217bn instead of about $73bn from 2021-04-28 to 2021-10-26; SHW ranks about 30th and has 2 events that should not be in the sample.
- **Fix:**
  - When a dei cover count disagrees with the same filing's weighted count by about the split ratio, take the split basis from the weighted count.
  - Alternatively, use the filing's acceptance date as `as_of` when the cover date falls before a split that precedes acceptance.

**P1-3. The float check removes momentum winners and some legitimate names** (`pit_universe.py:256-271`, `:300-303`)
- **Cause:** today's cap is compared with a public float that can be up to 15 months old (measured at mid-year), and anything above 10x is unrankable.
- **Companies wrongly unrankable:**
  - TSLA, 2020-08..2021-01 (rank about 6).
  - APP, 2024-11..2025-09.
  - MU (2026-05..09), WDC, STX, NET (2020-11..2021-11) and MRNA (2020-11..2021-02).
  - DD for 12 months (2020-02..2021-01), because its float is tagged in billions ("56.1"); the waiver only covers thousands.
- The rule is PIT-safe, but it removes exactly the names with large recent run-ups, which skews the universe.
- **Fix:** compare the float with the cap on the float's own `as_of` date (shares × close on that date). This is what `corrected_run.py` does.

**P1-4. The H1 statistic is attenuated, so the stated MDE overstates power** (`backtest/walkforward.py:390-397`; `HYPOTHESIS.md` results)
- **Cause:** S = mean(yd | long) − mean(yd | flat) on within-ticker demeaned y. That is a weighted sum of per-ticker long−flat gaps whose weights add up to W = (1/N_L + 1/N_F) · Σ n_Lk·n_Fk/n_k, not to 1.
- **Measured:**
  - W = 0.78.
  - 46 of 190 tickers (235 events) are all-long or all-flat and contribute only to the denominators.
  - 27 tickers have fewer than 4 events.
  - The proper fixed-effects slope is +0.092%, against S = +0.072%.
- The test is still valid: zero under H0 and the same decision rule.
- **What is mis-stated:** "realised MDE 0.76%" and "no evidence of an effect of 1% or more". In terms of the within-ticker long−flat effect, the MDE is about 0.76/0.78 ≈ 0.98%. The pre-registered "≈1.0%" in the same units is about 1.3%.
- **Fix:** state the MDE in effect units, or report the fixed-effects slope beside S as exploratory. Do not edit the decision.

**P1-5. The claim that the survivorship gap biases buy-and-hold DOWN is not supported**
- **Where it is made:** `backtest/compare_universes.py:119-121` (printed into `results/pit_vs_biased_2026-11-04.md`), the "Effect of the gaps" paragraph in `results/pit_universe_2026-11-04.md`, and LOG Phase B.
- **Why it doesn't hold:**
  - The missing large names include long decliners before they exited: Walgreens (taken private after a fall of roughly 90%), Allergan, Celgene, Express Scripts, Kraft Foods Group and Time Warner Cable.
  - A takeover premium lands on one announcement day, which rarely falls inside an earnings T+20 window.
- The direction is therefore unknown and plausibly upward. Excluding the ~10 gap firms with float rank ≤ 100 removes, I estimate, about 100–150 events, or 2–3% of the sample. I could not measure this: there are no prices for them.
- H1 is within-ticker, so it is largely immune to this.
- **Fix:** say "direction unknown" and give the gap's estimated share of events, unless delisted prices (CRSP, Norgate) are added.

### P2 — hygiene

1. **BLK is missing all events from 2015 to 2022-06** (29 top-100 quarters), because yfinance returns no dates for 2009-10..2022-07 and events need a vendor date (`backtest/snapshot_pit.py:105-157`). EDGAR has 60 Item 2.02 8-Ks for BLK. Fix: fall back to 8-K-only events when the vendor series has a gap.
2. **Vendor-only events that are not earnings dates** (46 events in Phase D have no 8-K match; most are BRK.B, which is legitimate). Examples: LIN 2020-03-01 19:00 (a Sunday, 16 days after the real report), COST 2023-06-01 and 2024-06-06 (monthly sales), INTC 2015-04-27. Fix: require an 8-K match for non-BRK filers, or drop a second event within about 45 days.
3. **Sectors use today's GICS for history** (`snapshot_pit.py:215`). The 2018 Communication Services and 2023 Financials/Staples reclassifications affect the sector-ETF benchmark before those dates. This is disclosed but not quantified; keep it.
4. **Jump-confirmation lag delays real mergers.** KHC enters only at 2016-03, although Kraft Heinz was about $90bn from 2015-07; Linde is similar. This is by design, but should be listed among the known limitations.
5. **Comment at `pit_universe.py:226` is garbled:** the float-ratio comment is glued onto the `MAX_CAP_TO_ASSETS` line.
6. **Provenance timing.** `HYPOTHESIS.md` was committed at 21:21:43 and the Phase D results were written at 21:28:30, 6m47s later, for "two reruns". One instrumented run here took 9m55s, though my patched ranking is slower and the hardware may differ. This is not evidence of a problem; recording the run start times in LOG would remove the doubt.
7. **Exclusion rule 2 disclosure** (300-session warm-up) keeps big IPOs (ABNB, SNOW, PLTR, SPCX) out for about 14 months. It is disclosed; it could also go in the H1 caveats.

### Checked and found clean
- **Membership timing:** rank at the close of D−1, with shares accepted strictly before 16:00 ET on D−1 (`shares_at` bisect on `acceptanceDateTime`).
  - `accepted_series` judges each record only on earlier records, so it is PIT-safe.
  - The public float is keyed by acceptance and limited to 460 days.
  - `tests/test_pit_snapshot.py`, including the poisoned-future tests and the meta-tests: 8 passed.
- **Split handling:** shares × splits after `as_of` × CloseSplitAdj is a ratio-only conversion. Yahoo pseudo-splits from spin-offs (DD, EBAY, HPQ) are applied consistently, so those caps are correct apart from P1-2.
- **Prices:** the dividend adjustment only scales whole windows, so technical features carry no look-ahead.
- **Event timing:**
  - `decision_session`: pre-market maps to the previous session, after-close to the same day.
  - The fundamentals cutoff is min(announcement, 16:00 on D).
  - The same-filing YoY comparative has the same acceptance time.
- **Same-quarter duplicate events:** COST, PEP, MU and NKE are real fiscal-calendar reports, not duplicates.
- **Event coverage:** 4,600 top-100 ticker-quarters from 2015 to 2026Q2; only 30 have no event within 100 days (BLK 29, PEP 1).
- **Pre-registration integrity:** nothing above the RESULTS line changed between e43319c and HEAD, and the command, metric key, seed and decision rule match. Season clusters use the calendar quarter of D as registered.
- **`cluster_diff_2way`:** the pigeonhole weights, p05 percentile and one-sided p are implemented as described; the variance estimate is conservative.
- **Universe sanity:** the 100th-largest cap is monotone and plausible ($41bn in 2014 to $118bn in 2026). Apart from RPAY, no top-100 member has cap/assets above 45x.
- The SPY fallback for XLC before 2018-06 and XLRE before 2015-10 is applied correctly.

---

## Response (what was changed)

There was no P0, so nothing invalidates a headline result, and the pre-registered H1 result stands as run (snapshot `2026-11-04-pit`,
ranking rules v1, never modified). The P1 data errors were fixed in a **review overlay** (`backtest/snapshots/2026-11-04-pit-r1`):
the same frozen base data, with share counts recomputed under ranking rules v2 (`backtest/snapshot_pit_overlay.py`; `Snapshot.load`
reads the base and replaces only shares; `verify` checks the overlay, the base and that the base is the one it was built on).
Phase D and Phase B were rerun on the overlay as a labelled robustness check.

| finding | action | effect |
|---|---|---|
| P1-1 ×1000 share tags (COP, RPAY) | **Fixed in v2.** Unit band [1/200, 200] for NI/EPS vs weighted; cap > 100× total assets → not rankable, always. Regression test (COP-style tag: v1 keeps it, v2 replaces it). Docstring corrected. | COP rank 2016-03-31: 419 → 77. RPAY 2025-06-30: 19 → 468. LIN 2018-11..2019-05 remains missing: the pre-merger Linde plc shell reported 25,000 shares and the first post-merger 10-Q still carried the shell's numbers; the real count enters after one confirming filing (jump-filter lag, P2-4). |
| P1-2 SHW split counted twice | **Fixed in v2.** A cover count dated before a split that took effect before acceptance is put on the acceptance-date basis. | SHW rank 2021-06-30: 32 → 118. |
| P1-3 float check biased against momentum names | **Fixed in v2.** The float is compared with the cap on the float's own date; floats below 10M USD are treated as unit-scaled and ignored (DD "56.1"). | TSLA 2020-10-30: unrankable → 8; MU 2026-07-31 → 12; MRNA 2021-01-29 → 108; DD 2020-06-30 → 151. |
| P1-4 S attenuated; MDE mis-stated | **Corrected in the text, decision unchanged.** The fixed-effects slope and W are now reported (exploratory) in `results/h1_phaseD_2026-11-04.md`; a correction note is appended below the line in HYPOTHESIS.md (nothing above it changed). | W = 0.78; 46 tickers all-long or all-flat; FE slope +0.09%. In effect units the realised MDE is ≈ 0.98%, the pre-registered ≈ 1.3%. |
| P1-5 gap bias "DOWN" unsupported | **Corrected**: direction unknown, a few percent of events (reviewer's estimate), within-ticker H1 largely immune. `compare_universes.py`, `pit_universe_report.py` regenerated; LOG note. | — |
| P2-1 BLK 2015–2022 events missing (vendor dates) | **Open** (needs an 8-K-only event fallback and a new base snapshot). | BLK contributes no events before 2022-07. |
| P2-2 vendor-only non-earnings dates | **Open** (same reason). | 46 vendor-only events, most BRK.B (legitimate). |
| P2-3 today's GICS for history | Open, disclosed. | — |
| P2-4 jump-confirmation lag | Documented as a known limitation (KHC 2015–16, LIN 2018–19). | — |
| P2-5 garbled comment | Fixed. | — |
| P2-6 provenance timing | Recorded in LOG: the two Phase D runs were started at about 21:22 UTC, **in parallel** (two processes), each ~6 minutes; both wrote sha256 `ccabc089…`. | — |
| P2-7 IPO warm-up in H1 caveats | Added to HANDOFF. | — |

### Robustness rerun on the review overlay (rules v2) — exploratory, does not replace the pre-registered result

Same commands, snapshot `2026-11-04-pit-r1` instead of `2026-11-04-pit` (output files carry the `-r1` id; unlike the reviewer prose
above, these figures are copied from `results/walkforward_2026-11-04-pit-r1_*_summary.json`, tagged there).

| | pre-registered base (v1) | review overlay (v2) |
|---|---|---|
| H1: S at T+5 (events) | +0.07% (4,661) | +0.08% (4,663) |
| H1: one-sided lower bound / two-sided CI | −0.41% / [−0.54%, +0.65%] | −0.45% / [−0.56%, +0.71%] |
| H1: one-sided p / decision | 0.41 / not rejected | 0.39 / not rejected |
| Buy-and-hold vs sector ETF T+20, 2015–2026 | −0.02% | −0.04% |
| Phase B window, today's top 100 (B): buy-and-hold vs sector ETF T+20 | +0.95% [+0.64, +1.30] | +0.95% [+0.63, +1.30] |
| Phase B window, point-in-time (C): buy-and-hold vs sector ETF T+20 | +0.12% [−0.20, +0.42] | +0.10% [−0.20, +0.42] |
| Phase B window, PIT: council selection skill T+5 | −0.02% | −0.02% |

Output sha256 (overlay runs): Phase D `16ae9016…`, C `4de4785d…`, B `8eb45e12…`. No conclusion changes. This matches the reviewer's own
counterfactual (S +0.093%, C +0.104%).

