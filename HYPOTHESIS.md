# HYPOTHESIS.md — Session 3 pre-registration (one primary hypothesis)

Written and committed on 2026-11-04, **before** the extended (Phase D) backtest was run. Nothing above the line
"RESULTS (appended after the run)" may be edited after the commit that adds this file; results are appended below
that line only. The git history is the record.

## What had been seen before this was written

- Sessions 1–2: the mock council on survivorship-biased universes, events 2023-11..2026-10 (no edge; within-ticker
  selection skill at T+5 of +0.08%, CI including zero).
- Session 3 Phase B: the same 2023-10-09..2026-09-30 window on the point-in-time (PIT) universe
  (`results/pit_vs_biased_2026-11-04.md`): council within-ticker selection skill at T+5 = −0.02%
  (season-clustered CI −1.06% to +1.12%). That window is about one quarter of the Phase D sample below.
- Data coverage of the Phase D snapshot (share counts, events, the P1-5 comparatives) was inspected, but **no strategy
  decision or return was computed for any decision date before 2023-10-09**.

## H1 (primary, confirmatory)

The deterministic mock council (LUMINA_LLM_MODE=mock; persona rules, cross-debate, CRO veto, PM verdict; long iff
the verdict is BUY or ACCUMULATE) has **within-ticker selection skill at T+5**:

    S = mean( y_d | council long ) − mean( y_d | council flat ) > 0

where, for every event i of ticker k in the sample,

    y_i   = r_stock(D_i -> D_i+5) − r_sectorETF(D_i -> D_i+5)       (close-to-close, total-return adjusted, before costs)
    y_d,i = y_i − mean_k(y)                                          (demeaned within ticker over ticker k's events in the sample)

The sector ETF is the SPDR fund of the company's GICS sector (SPY when that ETF did not yet trade: XLC before
2018-06, XLRE before 2015-10). D_i is the decision session (the last close strictly before the earnings release);
entry at the close of D_i, exit at the close five sessions later.

H0: S <= 0.

## Test

- One-sided, alpha = 0.05.
- Uncertainty: two-way clustered bootstrap, **earnings season x ticker** (pigeonhole bootstrap: seasons and tickers
  resampled independently with replacement, each event weighted by the product of its season's and its ticker's draw
  counts; 2,000 replicates; seed 20261104; `backtest/stats.py::cluster_diff_2way`). Season = calendar quarter of D.
  Demeaning is done once on the sample, not inside each replicate.
- **Decision rule: reject H0 if and only if the 5th percentile of the bootstrap distribution of S (the one-sided 95%
  lower bound, reported as `p05`) is greater than zero.** The two-sided 95% percentile CI [2.5%, 97.5%] and the
  bootstrap one-sided p-value are reported alongside; they do not change the decision.

## Sample

- Snapshot `backtest/snapshots/2026-11-04-pit` (frozen, sha256 manifest, committed in Phase B; rebuild byte-identical).
- Universe: point-in-time — an event is included only if its company ranks in the top 100 US-listed domestic filers by
  market capitalisation at the close of D−1 (`backtest/pit_universe.py`; rules and guards in LOG.md, Session 3 Phase B).
- Events: every earnings event in the snapshot with decision session D on or after **2015-01-01**, up to the last D whose
  T+20 exit lies inside the price data (the harness also needs all horizons; that bound is mechanical).
- Fundamentals: YoY revenue growth from the prior-year comparative inside the same filing (review P1-5, `--yoy comparative`);
  all other inputs as in Session 2.

## Exclusions (mechanical, decided before the run)

1. Events whose company is not in the PIT top 100 at the close of D−1, or cannot be ranked (no share count, no price that
   day, or failing a data-quality guard: cap > 10x public float, unconfirmed > 3x share-count jump, cap > 100x assets
   without a float).
2. Events with fewer than 300 sessions of price history before D (indicator warm-up), or without five, twenty sessions after D.
3. Companies with no price history in this sandbox (delisted/acquired; listed in `results/pit_universe_2026-11-04.md`).
4. Not common stock: commodity/crypto trusts, MLP units, preferred-only listings.
5. Nothing else. CRO-vetoed events stay in the sample (the council is flat on them). No outlier trimming or winsorising.

## Costs

The statistic S is computed on gross, decision-independent returns (it compares outcomes of events the council would
trade with events it would skip; costs do not enter). The harness's strategy returns use 5 bps commission + 5 bps
slippage per side (20 bps round trip). **Economic threshold:** even a statistically significant S below 0.20% would not
pay for one round trip; it would be reported as significant but not economically useful.

## Exact command

    LUMINA_LLM_MODE=mock PYTHONHASHSEED=0 python -m backtest.walkforward \
        --snapshot backtest/snapshots/2026-11-04-pit --universe pit --from 2015-01-01 --events 0 \
        --yoy comparative --two-way --tag phaseD

The number is `cells.overall["council|5|selection_skill_fe_2way"]` in
`results/walkforward_2026-11-04-pit_phaseD_summary.json` (fields `mean` = S, `p05`, `lo`, `hi`, `p_one_sided`,
`n_in`, `n_out`, `n_c1` = seasons, `n_c2` = tickers). The run must reproduce byte-identically (same output sha256 twice).

## Minimum detectable effect (computed before the run)

From the Phase B PIT run (same harness, 2023-10..2026-09, 12 seasons, 134 tickers, 1,198 events) the two-way bootstrap SE of
S at T+5 is 0.813%. Phase D spans about 47 seasons (2015Q1..2026Q3). Scaling the SE by sqrt(12 / 47) (the same factor as
scaling by events, ~1,200 -> ~4,700) gives SE ≈ 0.41%, so:

- **MDE (one-sided 5%, 80% power) ≈ 2.4865 x 0.41% ≈ 1.0% per event at T+5** (two-sided equivalent ≈ 1.15%).

An effect smaller than about 1% per five sessions will very likely not be detected. A non-rejection is therefore
"no evidence of an effect of 1% or more", not proof of zero.

## Everything else is exploratory

Every other number reported from Phase D — T+1 and T+20, VIX regimes, sectors, factors-only, council minus factors-only,
season-only clustering, the pre-2023-10 subsample, legacy YoY, excess returns vs SPY or sector ETFs, hit rates — is
**exploratory**. With dozens of cells, some will look "significant" by chance; none of them is evidence for or against H1.

---

RESULTS (appended after the run)

Run 2026-11-04 (UTC), the exact command above, twice: identical output sha256
`ccabc08934c2651962ed2c2a47f562303b4db6943c942ef151cf9f6ab353c06d`. Full tagged report: `results/h1_phaseD_2026-11-04.md`
(values there carry `[SOURCED FACT · wf-backtest 2026-11-04-pit_phaseD, 2026-11-04]`).

- Sample: 4,661 events, D from 2015-01-13 to 2026-09-24, 47 seasons, 190 tickers; council long 3,142, flat 1,519.
- **S = +0.07%**; one-sided 95% lower bound (5th percentile, two-way season x ticker bootstrap) **−0.41%**;
  two-sided 95% CI [−0.54%, +0.65%]; one-sided bootstrap p = 0.405; SE 0.31%; realised MDE (one-sided, 80% power) 0.76%.
- **Decision: H0 is not rejected.** No evidence that the mock council's long decisions pick better earnings events within a
  ticker than its flat decisions, at T+5. The point estimate is also far below the 0.20% economic threshold.
- Robustness (not part of the decision): season-only CI [−0.27%, +0.43%]; the subsample not seen before pre-registration
  (D before 2023-10-09, 3,463 events) gives S = −0.05% [−0.66%, +0.48%].

Correction after the independent review (results/independent_review_session3.md, finding P1-4; the decision is unchanged):
S as defined above is attenuated. It equals W x (a weighted average of within-ticker long-minus-flat gaps) with W = 0.78 in this
sample (46 of 190 tickers are all-long or all-flat and add only to the denominators). In those effect units the realised MDE is
about 0.98% (not 0.76%) and the pre-registered "about 1.0%" corresponds to about 1.3%. The ticker fixed-effects slope is +0.09%
(exploratory). So the non-rejection means "no evidence of a within-ticker effect of about 1% or more at T+5".

Session 4 rerun (2026-11-04 UTC; the exact command above with ONLY the snapshot id changed to `2026-11-04-pit2`, nothing above the
RESULTS line edited). The new base snapshot folds in ranking rules v2 (review P1-1..P1-3) and event rules v2 (review P2-1: 8-K-only
events in vendor-series gaps, e.g. BLK 2015-2022; P2-2: vendor-only 10-Q/10-K dates re-timed or dropped); prices are byte-identical
to `2026-11-04-pit`. Exclusion 3 still applies: no delisted-price source was available (estimated 84 lost events, partial upper bound 159 after the review fix;
results/delisted_gap_2026-11-04.md). Two runs started in parallel at 23:15 UTC on the final snapshot (manifest sha256 `8fbf7d7c…`):
identical output sha256 `8337e6b57c733c879bb27733c6a49b2d3f1da8a40403cea409649245b7977371`. Tagged report: `results/h1_rerun_2026-11-04-pit2.md`.

- Sample: 4,692 events, D from 2015-01-13 to 2026-09-30, 47 seasons, 188 tickers; council long 3,169, flat 1,523.
- **S = +0.08%**; one-sided 95% lower bound **−0.45%**; two-sided 95% CI [−0.58%, +0.70%]; one-sided bootstrap p = 0.396;
  SE 0.32%; MDE (one-sided, 80% power) 0.79% in S units, 1.01% in within-ticker effect units (W = 0.78).
- **Decision: H0 is not rejected** — the same decision as the Session 3 run (S +0.07%, lower bound −0.41%). Nothing material changed.
- Exploratory: ticker fixed-effects slope +0.10%; season-only CI [−0.29%, +0.46%].
- Provenance: a first version of `2026-11-04-pit2` (manifest `38efcb28…`, committed in 95d2385) used a stricter 8-K timeliness
  filter measured in calendar days. It was replaced (commit 1ca98af) before any review, after the change report showed it wrongly
  dropped COST's re-timed events. The run on that first version (sha256 `dddfa071…`, 4,689 events) gave S = +0.08%, lower bound
  −0.45%, CI [−0.57%, +0.70%], p = 0.397: the same decision. The rule change was not chosen by its effect on S.
