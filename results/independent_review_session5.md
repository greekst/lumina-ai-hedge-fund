# Independent review — Session 5 (Phase E)

Reviewer: a fresh Claude subagent that had not seen this session's work. It was given the repository path, a housekeeping line (change no tracked file, no live
LLM calls, scratch directory) and this instruction, verbatim: "Audit the ETF stat-arb engine, the pre-registration and the H2 run for look-ahead, data errors,
cost understatement, overfitting, bootstrap mistakes and anything that would overstate results. Rank findings P0/P1/P2 with file and line." It changed no tracked file.
Its report is reproduced below (reviewer prose; figures are its own measurements). Responses follow it.

## Report (verbatim)

**Verdict: no P0 found.** No look-ahead; data clean; bootstrap correct; pre-registration honoured; the reported H2 result is negative (net −1.70 bp/day, Sharpe −0.74, whole CI below zero) and not overstated. The issues are P1/P2 and mostly wording, guard weakness and interpretation.

Cleared:
- Look-ahead/timing: scrambling every close after index 2000 on the real snapshot left `W` and `s` for all earlier days bit-identical; a brute-force loop of "decide at t, trade at close t+1, earn t+2" reproduces `res.net` to 1.7e-18; the window (`etf_statarb.py:170-184`) covers returns t-M+1..t and eligibility closes t-M..t; `apply_execution` (`:241-255`) matches pre-registration steps 9-10.
- Pre-registration: `etf_statarb.py` byte-identical between the engine commit (e284c5b) and HEAD; `HYPOTHESIS_H2.md` changed only by an append below the RESULTS line; commit order engine → pre-registration → run; the exploratory block matches items 1-7.
- Arithmetic: mean, std, n, net = gross − cost reproduce from the CSV; cost = 10 bp × turnover exactly; break-even 3.96 bp correct; "negative in 11 of 14 years" matches.
- Data: unique dates aligned with SPY, no gaps > 5 days, no interior NaNs; adjusted vs split-adjusted differences are only dividend ex-dates (incl. the XLE 2019-12-30 special); OHLC consistent; large moves real; XLRE's five zero-volume bars excluded (entry 2016-04-21).
- Bootstrap: block starts, geometric lengths and wrap correct; SE 0.617 bp at block 20 vs Newey-West(20) 0.604 bp and iid 0.626 bp.

**P1**
1. *The run guard does not enforce the registration it claims to* (`etf_statarb.py:359-365`, `401-403`): `prereg_committed()` only checks that the file is tracked and clean against HEAD; it does not pin the pre-registration commit, check the engine hash or verify the snapshot against `manifest.json`; "(frozen, untouched)" and "run twice gave identical digests" in the report are hard-coded strings. No effect on this run (verified by git diff).
2. *"Gross edge" is presented as a finding but is not significant two-sided*: gross +1.11 bp, CI [−0.12, +2.36]; the one-sided p 0.037 is exploratory (its 5th percentile is +0.09 bp). "The gross edge would pay 4.0 bp per side" and "costs decide it" treat an unresolved positive as an edge; label it "point estimate, not distinguishable from zero".

**P2**
3. "Avellaneda–Lee" overstates fidelity: cross-sectional demeaning rather than eigenportfolios/sector regressions; symmetric 0.50 close (paper: 0.75 for shorts); 3.5 stop, inverse-residual-vol weights and ETF-on-ETF are not from the paper. "No edge" applies to this variant.
4. Realised MDE is inflated by the assumed 1.5 variance factor: assumed SE 0.77 bp vs bootstrap SE 0.60 bp (realised inflation ≈ 0.92); a realised-SE MDE is ≈ 1.5 bp/day (Sharpe ≈ 0.65), not 1.91 / 0.83.
5. The 10 bp per side cost cuts both ways: probably above real execution cost of liquid sector SPDRs at the close, yet no borrow/financing (book roughly half short), no impact, closes as fills, thin XLRE/XLC early. Present a cost sensitivity (2, 5, 10 bp). Daily full re-hedge turnover is 28% of gross a day (max 181%, 99th percentile 128%).
6. By-year and by-VIX bootstraps resample selected days (non-adjacent for VIX), so they are not block-valid; VIX>25 (+3.0 bp, n = 393) and the positive years are noise-prone and unadjusted for ~40 cells.
7. Grid/lookback cells have different samples (M = 90 starts ~30 days later) and share one history.
8. Structural breaks (2016-09 XLRE carve-out, 2018-06 XLC launch, 2023-03 GICS reclassification) are unhandled but disclosed; XLRE enters 2016-04-21, before its composition was settled.
9. Design note: with time-demeaned Y the cumulative residual ends at X_M = 0 exactly, so s = −m/σ_eq; matches Avellaneda–Lee but rests on one intercept estimate per window and explains the weak gross edge.
10. Minor: `p_one_sided` is the share of bootstrap means ≤ 0, not a classical p-value; NaN returns are zero-filled in `apply_execution` (harmless here: no interior NaNs).

Bottom line (reviewer): no detectable net edge for this variant at 10 bp per side, and a gross mean indistinguishable from zero; fix P1-1, P1-2 and P2-3 wording before relying on the process again.

## Responses

- **No P0, so no rerun of the pre-registered run was needed.** `etf_statarb.py` is unchanged; the registered output digest `be176bb0…6168` stands.
- **P1-1 (guard): partly fixed.** `etf_statarb_report.py` now *checks* instead of asserting: the pre-registration above the RESULTS line against commit 610fb6f, the engine file against its commit
  e284c5b, and the sha256 of the 13 price files against the snapshot manifest; the report fails if any check fails and states the result. The run guard in `etf_statarb.py` itself stays as is,
  because changing the engine's summary output would change the registered digest; it is an accident guard, not a tamper proof — the git history is the record. Left open as a note for a future session.
- **P1-2 and P2-3 (wording): fixed** in the report (gross labelled "point estimate, not distinguishable from zero", break-even stated conditionally; the strategy named an Avellaneda–Lee-style *variant*, differences listed).
  Corrections for the same wording in `HYPOTHESIS_H2.md` RESULTS are appended below the line. (A note on P2-3: the pre-registration already states every rule; it is the label that overreached.)
- **P2-4: added** the MDE from the realised bootstrap SE (1.50 bp/day, Sharpe 0.65) next to the registered one (1.91 bp/day, 0.83); the registered inflation proved conservative.
- **P2-5: added** an exact cost sensitivity: net mean +1.11 bp at 0 bp, +0.55 bp at 2 bp, −0.29 bp at 5 bp, −1.70 bp at 10 bp per side (cost is linear in turnover). The sign of net return depends on the assumed cost; the registered
  10 bp decides H2 and is unchanged. Even at 2 bp the gross mean is not distinguishable from zero, so no cost level turns this into evidence of an edge.
- **P2-6, P2-7: labelled** in the report headings (indicative only; ~40 cells; unequal starts; one shared history). **P2-8, P2-9, P2-10:** accepted as disclosed limitations; no change.
