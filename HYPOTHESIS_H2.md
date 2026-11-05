# HYPOTHESIS_H2.md — Session 5 pre-registration (one primary hypothesis)

Written and committed on 2026-11-05, **before** any strategy return, P&L, Sharpe or hit rate was computed on real ETF data.
Nothing above the line "RESULTS (appended after the run)" may be edited after the commit that adds this file; results are appended
below that line only. The git history is the record. Engine under test: `backtest/etf_statarb.py` at commit `e284c5b` (27 synthetic tests green).

## What had been seen before this was written

- Phase A (LOG.md): data coverage only — first/last dates, gaps, columns, volume presence of the 11 sector ETFs and SPY in the frozen snapshot
  `backtest/snapshots/2026-11-04-pit2`. **No return of any ETF, relative or residual, and no strategy quantity was computed** in this session before this commit.
  The engine was tested on synthetic data only.
- Earlier sessions used the sector ETFs and SPY only as *benchmarks* for stock event windows (H1 and its Session 2/3 reports). No ETF-vs-ETF
  analysis, factor residual or mean-reversion statistic was ever computed in this project.
- Outside knowledge, disclosed rather than denied: the Avellaneda–Lee (2010) paper reports a strong 1997–2007 result for sector-ETF stat-arb and a
  weaker one after 2002–2003; practitioners' lore says such strategies decayed after the mid-2000s. This prior is why a clean "no edge" is the most
  likely outcome, and why the test is one-sided on a single number. The project-ideas note ranked this idea first; that ranking is not evidence.

## H2 (primary, confirmatory)

The Avellaneda–Lee residual mean-reversion strategy on the 11 Select Sector SPDR ETFs (XLK, XLF, XLV, XLE, XLY, XLP, XLI, XLU, XLB, XLRE, XLC), run
with the fixed rules below, has a **positive mean daily net return**:

    mu = mean over the sample of  net_t,    net_t = sum_i H_{t-1,i} * r_{i,t}  -  0.0010 * sum_i |H_{t,i} - H_{t-1,i}|

where r is the simple daily return from the snapshot's total-return-adjusted `Close`, H_t is the vector of ETF weights held after the close of day t
(gross exposure 1.0 when any position is open, otherwise 0), and the 0.0010 is 10 bps per side on turnover (5 bps commission + 5 bps slippage,
the harness `CostModel` defaults). Units: fraction of the gross-1.0 capital base per trading day.

H0: mu <= 0.

## The strategy (every choice fixed now)

1. **Lookback M = 60** daily returns, ending at the decision close t (so 61 closes). Nothing else is tuned; no other M enters the decision.
2. **Standardise:** per ETF, time-series demean and divide by the window standard deviation (ddof 1): Y = (R − mean)/std.
3. **ONE primary factor model: cross-sectional demeaning of the standardised returns** (the "xs" model: eps_i = Y_i − mean_j Y_j over the ETFs in the
   universe that day; equivalently projecting out the single flat eigenvector). The alternative (PCA with K = 3 eigenportfolios) is exploratory only.
   **Justification, written before any data was seen:** (a) it has no free parameter — PCA needs a K (and a variance-explained rule), and each K would be one more
   researcher degree of freedom in a test that is allowed only one shot; (b) with N = 9–11 series and M = 60 observations the window correlation matrix has
   N/M ≈ 0.15–0.18, so its eigenvectors beyond the first are dominated by sampling noise (random-matrix theory), whereas the equal-weight standardised
   market factor is estimated with no noise; (c) it is exact and stable when the universe changes size (XLRE and XLC enter later); (d) its cross-sectional
   residuals sum to zero identically, which is a testable invariant. Sector ETFs are all long-only baskets of the same market, so one dominant common factor is the
   natural prior; whether more factors help is a question for the exploratory block.
4. **Cumulative residual** X_s = sum_{j<=s} eps_j over the window; **AR(1)** by OLS: X_{s+1} = a + b X_s + zeta over the window's M−1 pairs;
   kappa = −ln(b) · 252, m = a/(1−b), sigma_eq = sqrt(var(zeta)/(1−b²)) (var with ddof 2), half-life = −ln 2 / ln b days.
5. **S-score** s = (X_M − m) / sigma_eq (no cross-sectional re-centring of m).
6. **Tradable** only if 0 < b < 1 **and** half-life ≤ 30 days (and the fit is finite). Non-tradable ETFs get no new position, and an open position in an ETF that becomes non-tradable is closed.
7. **State machine** per ETF, evaluated at each decision close: open when 1.25 < |s| < 3.5 (long the residual if s < 0, short if s > 0) and the ETF is not blocked;
   **close** a long when s > −0.50 and a short when s < +0.50 (this contains |s| < 0.50 and overshoot through zero); **stop** a long when s ≤ −3.5 and a short when
   s ≥ +3.5 — the ETF is then flat and blocked from re-entry until |s| < 1.25. A position may be closed and, on the same decision, reopened in the other direction.
8. **Weights:** an open position is the residual portfolio h_i (long ETF i, short the standardised-return factor, so that h_i·r = eps_i + const); each is
   scaled by 1/std(eps_i) over the window (inverse residual volatility) and the sum over open positions is normalised to **gross exposure 1.0**. Hedge ratios and
   scales are recomputed every day, so turnover includes re-hedging; all of it is charged. The portfolio is factor-hedged, not dollar-neutral by construction.
9. **Execution lag:** the signal at the close of t uses closes and volumes up to and including t only; the trade is done at the **close of t+1**; the position earns the
   return of day t+2. The same close that produced the signal is never traded.
10. **Costs:** 10 bps of traded notional per side (5 bps commission + 5 bps slippage), charged on the trade date on the sum of absolute weight changes. No borrow fee,
    no financing, no cash interest, no taxes (omissions disclosed below).

## Sample and universe

- Snapshot `backtest/snapshots/2026-11-04-pit2` (frozen, sha256 manifest, untouched). Adjusted `Close` (split- and dividend-adjusted: total returns); `CloseSplitAdj` is not used.
- **First decision date 2013-04-01** (the first close with a full 60-return window for the nine ETFs that exist from 2013-01-02); **last date 2026-11-03** (last close in the snapshot).
  The daily net-return series runs over every trading day from the first decision date to the last date: **n = 3,421 days**, flat days counted as zero.
- **Universe rule (entry of XLRE and XLC):** an ETF is in the universe on day t iff its last 61 closes all exist with positive volume on every one of those bars. XLRE (first
  bar 2015-10-08, with zero-volume stale-price bars through 2016-01-25) therefore enters on its first fully clean window, **2016-04-21**; XLC (first bar 2018-06-19) enters
  when its 61st bar is reached. Before that, N = 9 and 10 respectively. No other filter.
- Exclusions: none beyond the universe rule. No outlier trimming or winsorising; no re-fitting of anything on the full sample.

## Test

- One-sided, alpha = 0.05.
- Uncertainty: **stationary bootstrap** (Politis–Romano) of the sample mean of the daily net returns, **mean block length 20 trading days** (about one calendar month; longer than the
  expected holding period of a 30-day half-life signal is not claimed — it is chosen to cover monthly-scale dependence in P&L and volatility clustering), circular wrap,
  **10,000 replicates, seed 20261105** (`backtest/etf_statarb.py::stationary_bootstrap_means`).
- **Decision rule: reject H0 if and only if the 5th percentile of the bootstrap distribution of the mean (the one-sided 95% lower bound, field `p05`) is greater than zero.**
  The two-sided 95% percentile CI [`lo`, `hi`] and the bootstrap one-sided p-value (share of replicates with mean ≤ 0) are reported alongside; they do not change the decision.

## Reported alongside, not deciding

- Annualised Sharpe = mean/std · sqrt(252) of the same net series (no risk-free subtraction; the book is factor-hedged and carries no cash return in this model).
- **Economic threshold:** a mean net return of at least **1 bp per day (2.52% a year on the gross-1.0 capital base)**; a statistically significant mean below it would be reported
  as significant but not economically useful. (MODEL ASSUMPTION; chosen as an order of magnitude of a cash yield and of what the effort would have to beat; not fitted.)
- **MDE (computed before any run, from assumptions only; it touches no data):** n = 3,421 days; the standard error of the mean is taken as sigma_d · sqrt(1.5/n), where the factor 1.5
  is an assumed variance inflation for autocorrelated, clustered P&L; MDE (one-sided 5%, 80% power) = (1.6449 + 0.8416) · SE.
  For an assumed strategy volatility sigma_d of 0.15% / 0.25% / 0.40% a day this is **0.78 / 1.30 / 2.08 bp a day** (2.0% / 3.3% / 5.2% a year).
  Independent of sigma_d: **an annualised Sharpe of about 0.83**. So an edge smaller than about 0.8 Sharpe would very likely not be detected; a non-rejection is
  "no evidence of an edge of about 0.8 Sharpe or more", not proof of zero. The realised MDE from the realised volatility is reported after the run.
- Operational fields: turnover (mean daily and annualised, sum of |Δweight|), cost drag (mean daily and annualised), gross (pre-cost) mean, number of trades (entries), share of days in the market.

## Exact command

    LUMINA_LLM_MODE=mock PYTHONHASHSEED=0 python -m backtest.etf_statarb \
        --snapshot backtest/snapshots/2026-11-04-pit2 --factor xs --window 60 \
        --block 20 --reps 10000 --seed 20261105 --tag h2

It writes `results/etf_statarb_2026-11-04-pit2_h2.csv` (daily gross, cost, net, turnover) and `results/etf_statarb_2026-11-04-pit2_h2_summary.json`, and prints
`digest sha256 <hex>` over those two files. The decision number is **`mean`**, with fields `p05` (decides), `lo`, `hi`, `p_one_sided`, `sharpe_ann`, `n_days`, `entries`,
`turnover_mean_daily`, `turnover_ann`, `cost_mean`, `cost_drag_ann`, `gross_mean`, `reject_h0`. The run must reproduce byte-identically (same digest twice).
The program refuses to run on real data unless this file is committed and unmodified.

## Exploratory block (labelled; never decides anything; defined now so it cannot be tuned)

Run separately after the primary result is recorded. Every item below is exploratory: with this many cells something will look significant by chance.
1. PCA factor model with K = 3 (all else equal), reported next to the primary result.
2. Gross (pre-cost) result of the primary run.
3. Net beta to SPY: OLS slope of the daily net return on the SPY daily return (SPY is in the snapshot), with its correlation.
4. Results by calendar year, and by VIX regime (VIX close on the decision date of the position in force, i.e. two sessions before the P&L day): < 15, 15–25, > 25.
5. Volume "trading time": returns used in the signal are multiplied by (trailing 10-day mean volume)/(volume that day); P&L uses real returns.
6. Threshold sensitivity grid, shown without picking a winner: open ∈ {1.00, 1.25, 1.50, 2.00} × close ∈ {0.25, 0.50, 0.75}, stop 3.5 and everything else fixed; and M ∈ {40, 60, 90}.
7. Bootstrap block length 5 and 60 (instead of 20) for the primary series.

## Known limitations of the design (disclosed before the run)

- The sector funds' compositions changed during the sample (XLRE carved out of XLF in September 2016; XLC carved out of XLK and XLY in June 2018; the 2023 GICS reclassification
  of payment companies). The strategy does not adjust for them; they alter the cross-fund relationships the model assumes stable.
- No borrow fees, no financing of the gross-1.0 book, no market-impact beyond the 5 bps slippage, no taxes, closes as execution prices. Costs are therefore, if anything, understated.
- Daily re-hedging (item 8) is a deliberate Avellaneda–Lee feature, not an optimisation; a lower-turnover variant would be a different strategy.
- One run on one history: the sample is a single path of about 13.6 years.

---

RESULTS (appended after the run)

Run 2026-11-05 (UTC), the exact command above, twice in parallel plus a third time into `results/`: identical output sha256
`be176bb077c879614ada660b2fe82bac8d653e94be7ae650c688d1417fbb6168` (all three). Full tagged report: `results/etf_statarb_2026-11-04-pit2_h2_summary.md`
(values there carry `[SOURCED FACT · etf-statarb 2026-11-04-pit2 h2, 2026-11-05]`; the exploratory block is in `results/etf_statarb_2026-11-04-pit2_h2_explore.json`).

- Sample: 3,421 trading days, 2013-04-01 to 2026-11-03; 1,176 position entries; in the market on 98.3% of days.
- **Mean daily net return = −1.70 bp** (−4.28% a year on the unit-gross capital base; daily SD 36.6 bp); one-sided 95% lower bound (5th percentile) **−2.67 bp**;
  two-sided 95% CI [−2.87 bp, −0.50 bp]; one-sided bootstrap p = 0.997; bootstrap SE 0.60 bp. Net annualised Sharpe −0.74.
- **Decision: H0 is not rejected.** The entire interval lies below zero: net of costs the strategy lost money over the sample. The economic threshold (1 bp a day) is not met.
- Costs decide it: gross mean +1.11 bp a day (gross Sharpe 0.48; gross 95% CI [−0.12, +2.36] bp, one-sided p 0.037 — exploratory), cost drag 2.81 bp a day (7.1% a year) from a daily
  turnover of 28.1% of gross exposure (about 71 times a year). The gross edge would pay a cost of about 4.0 bp per side, against the registered 10 bp.
- Realised MDE 1.91 bp a day (Sharpe 0.83 a year, as registered). Strategy return and costs are unchanged by the choice of bootstrap block (block 5: lower bound −2.70 bp; block 60: −2.66 bp).
- Exploratory (not evidence; defined before the run): PCA K = 3 net −2.32 bp (CI [−3.11, −1.50]); trading-time variant net −2.45 bp; net beta to SPY 0.04 (corr 0.10); by year the net mean is
  negative in 11 of 14 calendar years, by VIX regime negative at VIX < 15 and 15–25 (CIs below zero) and +3.0 bp at VIX > 25 (CI [−1.45, +8.02] bp, 393 days); the
  threshold grid (12 cells) and lookback grid (M = 40, 60, 90) are all net-negative, the least negative being open 2.0 (fewest trades) and M = 90 (lowest turnover) — consistent with
  cost being the binding constraint, and not a selection of a winner.
