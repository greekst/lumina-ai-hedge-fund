# HANDOFF — Lumina Capital research fork, hardening session (2026-11-04)

This session hardened the fork so it can be trusted as a research tool. The bottom line is plain: **the walk-forward test found no edge.** The council (in deterministic mock mode) behaves like buy-and-hold with a small drag. Several headline features of the upstream project showed fabricated or non-empirical numbers, and those are now fixed or labelled. Details: `AUDIT.md` (findings and status), `SECURITY_AUDIT.md`, `LOG.md` (timeline and decisions).

## 1. What changed

| Area | Change | Where |
|---|---|---|
| Agent rules | Hard rules persisted for future agent sessions | `AGENTS.md`, `CLAUDE.md` |
| LLM ↔ numbers (rule 3) | LLM output is limited to categories and prose. Agent scores come from a stance map. CRO/CIO sizing and stops, the debate re-score and news credibility are all deterministic, and raw LLM numbers are kept only as `llm_raw_*` for audit | `core/ai_hedge_fund/llm_guard.py` |
| LLM access | `LUMINA_LLM_MODE=live\|mock\|off`. Fixes the key bug where 14 call sites read `google_api_key` but settings stored `gemini_api_key`, which silently made the council always HOLD. Mock mode is deterministic and offline | `core/llm_mode.py` |
| Look-ahead (rule 4) | Alpha158 `.bfill()` removed (it copied future values into the past) | `alpha158_engine.py` |
| Fabricated numbers | Tear-sheet Sharpe 1.94, Sortino 2.85, MaxDD −3.8% and win rate 66.7% were constants, and the NAV chart was a random walk. All are now computed from the ledger or shown as n/a. The LightGBM "win probability" (trained on `np.random`) is now labelled `MODEL ASSUMPTION`, non-empirical | `fund_tear_sheet.py`, `lightgbm_gatekeeper.py` |
| Paper trader | It claimed "real commissions & slippage" but charged neither. Added a cost model (5 bps commission, minimum 1, plus 5 bps slippage per side; env-configurable), ledger columns, the idempotency-reservation leak fix and a consistent average-entry basis | `cost_model.py`, `broker_client.py` |
| Safety (rule 1) | IBKR/Kabu order routing, X posting and Discord posting are hard-disabled unless `LUMINA_ALLOW_LIVE_BROKER=1` / `LUMINA_ENABLE_SOCIAL_POSTING=1` (never set) | `broker_client.py`, `x_publisher.py`, `hedge_fund_notifier.py`, UI |
| Secrets (rule 2) | Secret scanner covers known key formats and the actual values of secret env vars. It runs in CI and in the local pre-commit hook. The dashboard no longer sends the server's API key to the browser. `settings.json` is now 0600 | `scripts/check_no_secrets.py`, `app.py`, `state_manager.py` |
| Docker | No default Neo4j password, ports bound to localhost, non-root user, pinned image | `Dockerfile`, `docker-compose.yml` |
| Dependencies | Pinned (`requirements.txt`). Optional integrations split out (`requirements-optional.txt`). Dev tools in `requirements-dev.txt` | |
| Tests and CI | 52 pytest tests plus a Playwright UI smoke test. CI runs on every push: secret scan, tests on Python 3.10/3.11/3.12, UI smoke | `tests/`, `.github/workflows/ci.yml` |
| Walk-forward (Phase 2) | Frozen, hashed data snapshot. Point-in-time inputs. Council vs factors-only vs buy-and-hold at T+1/T+5/T+20 with costs. Post-mortem records. Byte-identical reruns | `backtest/`, `results/` |
| Reporting (Phase 3) | Every report number renders as `value [SOURCED FACT\|MODEL ASSUMPTION · source, as_of]`. Numbers in model prose are redacted. A validator test fails on any untagged number. Streamlit panel added with .md download | `core/reporting/`, `reports/examples/` |
| Data feed (Phase 4a) | Finnhub first for quote, profile and fundamentals, with per-field yfinance fallback on 403 or error. Per-field provenance and a fallback log | `core/ai_hedge_fund/data_sources.py` |

## 2. How to run

```bash
python -m venv .venv && . .venv/bin/activate
```

```bash
pip install -r requirements-dev.txt
```

```bash
LUMINA_LLM_MODE=mock python -m pytest -q
```

```bash
LUMINA_UI_SMOKE=1 python -m pytest -q tests/test_ui_smoke.py
```

```bash
python -m backtest.walkforward --snapshot backtest/snapshots/2026-11-04
```

```bash
LUMINA_LLM_MODE=mock streamlit run app.py
```

To refresh data, build a new snapshot. This is the only networked backtest step and needs `FINNHUB_API_KEY`:

```bash
python -m backtest.snapshot --id 2026-12-01
```

The legacy script suite asserts exact fill prices, so run it with zero costs:

```bash
LUMINA_SLIPPAGE_BPS=0 LUMINA_COMMISSION_BPS=0 LUMINA_COMMISSION_MIN=0 python tests/test_institutional_hardening.py
```

## 3. Backtest results and interpretation

Source: `results/walkforward_2026-11-04_summary.json` (fully tagged version: `results/walkforward_2026-11-04_summary.md`), as of snapshot 2026-11-04. Setup: 10 US large caps (AAPL, MSFT, NVDA, AMZN, GOOGL, META, JPM, JNJ, XOM, PG) × their last 12 earnings events = 120 events (announcements from 2023Q4 to 2026Q3). Entry is at the last close before each announcement, using features through the prior close. Returns are net of costs.

| Strategy | Longs | T+1 avg net | T+5 avg net | T+20 avg net | T+20 avg excess vs SPY | T+20 hit rate | T+20 Sharpe (quarterly, ann.) |
|---|---|---|---|---|---|---|---|
| council (mock LLM) | 102/120 | +0.03% | +0.37% | +1.99% | −0.39% | 50.8% | 1.12 |
| factors-only | 63/120 | +0.00% | +0.06% | +1.09% | −0.04% | 46.7% | 0.87 |
| buy-and-hold | 120/120 | +0.18% | +0.47% | +2.40% | −0.43% | 54.2% | 1.38 |

Council minus factors-only, paired by event, at T+20: +0.90% mean, 95% bootstrap CI [−0.15%, +2.01%]. Not significant.

**Interpretation:**
- **No edge found.** Neither strategy beats buy-and-hold, and none beats SPY over the same windows. The council's higher raw return versus factors-only comes from being long 85% of the time in a rising market (beta), not from stock selection. Conditional on being long, its T+20 return (+2.34%) is roughly the same as buy-and-hold (+2.40%).
- The T+1 hit rates (45–48%) show no ability to call the earnings reaction itself.
- This tests the **deterministic persona rules** (mock mode), not a live LLM. A live-LLM backtest over 2023–2026 would be contaminated by training-data look-ahead, since the model may know the outcomes. Do not run one without anonymising tickers and dates.
- The sample is small (120 events, 12 quarters), so even a real effect of ±1% would be hard to detect. Treat every figure as descriptive.
- Inputs that are excluded because no point-in-time history exists, or because they are fabricated: the "TimesFM" heuristic, Chronos, the LightGBM gate, news, FRED macro and options GEX. Turbulence uses VIX(D−1) ≥ 30 as a proxy.

## 4. Known limitations

- **GitHub Actions has not run.** The fork shows no workflow runs, probably because Actions is disabled on forks by default. Everything was verified locally. Enable Actions, then check the 3.10 job, whose marker-pinned versions were never exercised here.
- **Data:** event times come from yfinance `get_earnings_dates`, which gives exchange-local times; generic "16:00" and one "12:00" entry can be imprecise. SEC EDGAR (the preferred primary source) blocked this sandbox with 403 "undeclared automated tool" after the first request, so fundamentals come from Finnhub as-reported XBRL with `acceptedDate`. Finnhub EPS is truncated to integers for some filers, so EPS is derived from net income / diluted shares. 15 of 520 fundamental values are missing, and agents use their built-in defaults for those.
- **Adjusted prices:** split and dividend adjustment uses today's factors. Returns are unaffected; price levels inside decisions are slightly rescaled (ratios are invariant).
- **No PIT news, macro or options history.** Those agents' inputs are absent in the backtest.
- **Legacy surfaces remain untagged:** `fund_content_generator`, `quant_reporter`, note/X drafts, most of `ui/mode_ai_hedge_fund.py` (3.6k lines) and the ~80 other `unsafe_allow_html` sites. Social posting is disabled, but these outputs still contain untagged numbers.
- **Unverified:** yfinance `dividendYield` units (upstream multiplies by 100; newer yfinance may already return a percent; `.info` returned 401 here). The `chronos` and `torch` paths were not installed or run. Neo4j was not run.
- **Not done:** full multi-agent `security-audit-skill` run (focused mode was used), full-history git secret scan (`gitleaks`), TradingAgents baseline (no mock mode).

## 5. Recommended next steps

1. Enable Actions on the fork and get CI green on 3.10/3.11/3.12.
2. Use SEC EDGAR companyfacts and 8-K Item 2.02 acceptance times as the primary PIT source. Set `SEC_USER_AGENT` to a real contact address. Cross-check against the Finnhub snapshot.
3. Widen the universe (e.g. 100+ names) so effects of ±1% become detectable. Add a sector/market-neutral benchmark and report by regime.
4. If an LLM council is tested at all, use anonymised tickers and dates in a held-out period after the model's training cutoff, and a fixed cost budget.
5. Bring the legacy report generators into `core/reporting` (tagged), or delete them.
6. Replace or retire the LightGBM gate. Training it walk-forward on the post-mortem records in `results/postmortem_*` is the natural next experiment, but keep it labelled until it shows out-of-sample skill.
7. Fix the remaining `unsafe_allow_html` sites and run `gitleaks` over the full history.

---

# Session 2 (2026-11-04) — wider universe, SEC EDGAR, anonymised live-LLM test

Branch `claude/quirky-albattani-qc1wt7`. Timeline and decisions: `LOG.md` (Session 2 section). All numbers below come from committed result files and are tagged in those files.

## The three questions

**1. Does "no edge" hold on a wider universe with sector-neutral benchmarks? — Yes. Still no edge.**
Source: `results/walkforward_2026-11-04-sp100_summary.md` (snapshot `2026-11-04-sp100`). 100 tickers × last 12 earnings events = 1,183 events, 2023-11..2026-10, 36 calendar months. CIs are 95% bootstrap clustered by earnings season (calendar quarter of D, 12 seasons). The independent review showed that month clusters were too narrow.

| T+20 | long rate | avg net | excess vs SPY | excess vs sector ETF |
|---|---|---|---|---|
| council (mock) | 65.8% | +1.74% [+0.99, +2.48] | +0.27% [−0.40, +0.88] | +0.34% [−0.03, +0.69] |
| factors-only | 43.0% | +1.01% [+0.62, +1.43] | +0.28% [−0.18, +0.71] | +0.23% [−0.05, +0.50] |
| buy-and-hold | 100% | +3.34% [+2.09, +4.56] | +0.91% [+0.30, +1.50] | +0.97% [+0.72, +1.24] |

- Council − factors-only, paired, T+20: +0.73% [+0.01%, +1.45%] (MDE 1.02%). It looks positive, but the **selection-skill** test says otherwise. Long-event minus flat-event sector-relative return, demeaned within ticker, at T+20: council **−0.00% [−1.50%, +1.54%]** (MDE 2.20%), factors-only −0.00% [−1.01%, +0.91%]. At T+1 and T+5 both are within ±0.31% and their CIs include 0. Neither strategy times a stock's events. The paired gap comes from the council being long more often (66% vs 43%) in a universe selected on past winners (next bullet).
- **Survivorship:** the universe is today's 100 largest companies, applied to past events. Buy-and-hold beating its sector ETF by about 1% per 20 sessions is that selection effect, not an opportunity. Any exposure-heavy strategy inherits it.
- By regime (VIX on D-1): <15 has 229 events (9 seasons), 15–25 has 899 (12), >25 has 55 (3 seasons, too few for a CI). Within-ticker council selection skill at T+20: VIX 15–25 +0.41% [−1.16%, +1.82%], VIX<15 −0.28% [−3.67%, +2.78%]. By sector, the cells have 12–326 events; none has a CI that excludes 0 (largest: IT +1.28% [−2.17%, +4.13%]). Materials and Utilities have 12 events each, so no estimate.
- **Detectable effect:** with this sample the minimum detectable effect (80% power, 5% two-sided) is about 0.25% (T+1) to 1.0% (T+20) for paired strategy differences, and about 0.8–2.2% for selection skill. Sector cells need 3.5–7.5%. A real edge smaller than about 1% per event would not be visible.
- Reproducibility: two full runs, identical sha256 `f5735aab…` (after the Phase D fixes).

**2. Does a live LLM council add anything over the deterministic persona rules? — Not answered. The run is blocked by the API quota.**
Source: `results/live_council_2026-11-04-sp100_status.md`.
- Design (built and tested, not executed): model `gemini-3-flash-preview`, documented knowledge cutoff January 2025 (Google Cloud Vertex AI model page). Held-out = decision session after 2025-01-31, which gives **640 events** (577 reach the model; CRO vetoes are HOLD either way). Inputs are anonymised (code CO-###, sector, no ticker/name/price/date/news). The live and mock arms see identical PIT inputs, and the only difference is the stance of two live personas (cathie_wood, william_oneil). Personas are dropped before events to fit the 1,500-call cap: 1,154 requests are planned.
- Blocker: this key is on the free tier, and `gemini-3-flash-preview` allows **20 requests per day** (`GenerateRequestsPerDayPerProjectPerModel-FreeTier`).
- **Exploratory leakage check** (level-1 anonymisation, 20 of 100 prompts before the quota hit): the model named the hidden company as its first guess for **25%** (Wilson CI 11–47%; threshold 10%) and in its top 3 for 40%. It never guessed the quarter. So **level-1 anonymisation fails**: sector plus distinctive ratios identify mega-caps. Level 2 (banded ratios) is implemented but unverified.
- Gemini calls used this session: **28 / 1,500**.

**3. Do SEC EDGAR primary filings agree with Finnhub? — Yes for every value Finnhub has. EDGAR is more complete and more precise, and the harness now uses it.**
Source: `results/sec_vs_finnhub.md` (Session 1's 10 tickers, 1,533 values compared by accession number).
- 77 values differ by more than 1%. 73 are Finnhub diluted EPS truncated to whole numbers, and 4 are a different XBRL concept for PG net income. **0 are unexplained.** Missing values: EDGAR 0, Finnhub 128. Acceptance timestamps: 0 disagreements.
- Earnings dates: 238/240 yfinance events give the same decision session as the 8-K. On the full universe (`results/events_8k_vs_yfinance_2026-11-04-sp100.md`): 2,285/2,339 match, 33 are off by one session, 0 by more.
- Re-running Session 1's 10 tickers on EDGAR data changes 3 of 120 council decisions. Council − factors-only goes from +0.90% to +1.01%; the conclusion does not change.

## Bugs found and fixed this session (both P0 class, look-ahead)
1. **Filings cutoff** was the announcement time, while entry is at the close of D. For pre-market releases, an overnight filing could leak. It is now `min(announcement, 16:00 ET on D)`. Session 1 was unaffected (0 events). The new test fails on the old code.
2. **8-K as the sole event timestamp** (the brief's literal instruction) would be look-ahead. SCHW's 8-K is accepted about 9 hours after its 07:00 release every quarter, and BRK.B's 1–4 sessions after a Saturday release. Item 2.02 also covers non-earnings disclosures (TSLA deliveries, COST monthly sales, preliminary results). Rule now: yfinance identifies earnings dates, each is matched to an 8-K within ±3 days, and the **earlier** timestamp wins.
3. Data traps fixed: AMZN trailing-twelve-month columns in 10-Qs (YTD capped by fiscal period); XOM (2026) and BLK (2024) holding-company re-registrations (predecessor CIKs merged).

## Independent review (Phase D)
A fresh subagent that had not seen the work audited `backtest/` and the new data paths. Its report is saved verbatim with responses in `results/independent_review.md`.
- **P0 (fixed):** a pre-market release could still be placed after the close when the vendor stamp is "16:00" and the 8-K is late (SCHW 2025-01-21, +5.9% on D). Fixed with a point-in-time issuer timing convention; 6 events moved earlier. Results rerun.
- **P1 fixed:** ticker drift in selection skill (now within-ticker, which turns the council's −0.73% into −0.00%); month clusters were too narrow (now 12 earnings seasons); MCD share count tagged in millions (sanity check).
- **P1 open:** survivorship from today's universe (needs a PIT universe); YoY growth across spin-offs (GE) uses the originally reported prior year.
- **P2:** source labels and the CI label are fixed. Sharpe/drawdown aggregation, stops not simulated, some stale or null fundamentals and the many-cells problem are documented.
- None of the fixes changes an answer above.

## What I would test next
1. **Finish question 2 on a paid Gemini tier** (≈1,250 requests; or keep the free tier for ~60 days). First run the level-2 leakage check (100 prompts). If it is still above 10%, coarsen the sector, then run the council:
   `LUMINA_LLM_MODE=live python -m backtest.live_council --snapshot backtest/snapshots/2026-11-04-sp100 --leak-check 100 --level 2`, then
   `LUMINA_LLM_MODE=live python -m backtest.live_council --snapshot backtest/snapshots/2026-11-04-sp100 --level 2`. Cached responses are replayed free.
2. **Point-in-time universe:** get historical S&P 100 membership (or build the universe from market caps *as of each event date* using EDGAR shares outstanding × price) to remove the survivorship bias that dominates the level effects above.
3. Fix review P1-5: compute YoY growth from the prior-period comparative inside the current filing (spin-offs, restatements). Add two-way clustering (season × ticker).
4. More events per name (e.g. all events since 2015 with a longer price history) to bring the selection-skill MDE below 1%.
5. Pre-register one primary hypothesis (selection skill at T+5, say) before looking at new data. This session reports many cells; treat any single significant cell as noise.

## Final checks (2026-11-04 19:05–19:08 UTC)
pytest 75 passed, 1 skipped · UI smoke 1 passed · legacy suite 19/19 (zero-cost env) · walk-forward rerun digest `f5735aab…` reproduced in a fresh directory · both snapshot manifests verify · secret scan OK, including the `SEC_USER_AGENT` value check · kill switches untouched · Gemini calls 28/1,500.

## Blocked / not done
- Official S&P 100 list (network policy, provider 403s, Bright Data inactive) → documented proxy universe.
- Live LLM council (Gemini free-tier quota 20/day) → harness ready, partial leakage check only.
- `ai.google.dev` unreachable from this sandbox → model cutoffs taken from web search of Google's pages (sources in LOG.md).
- GitHub Actions still not verified on the fork (Session 1 note stands).

---

# Session 3 (2026-11-04) — CI, point-in-time universe, longer history, one pre-registered test

Branch `claude/kind-rubin-ahzsge`. Timeline and decisions: `LOG.md` (Session 3 section). Every number below comes from a committed,
tagged result file named next to it. Mock LLM mode throughout; **0 live LLM calls** this session.

## Bottom line

- **The ~1% buy-and-hold "excess" of Session 2 was survivorship.** On a point-in-time universe it falls to +0.12% per 20 sessions, CI includes 0.
- **H1 (pre-registered) is not rejected.** The mock council shows no within-ticker selection skill at T+5 over 2015–2026:
  S = +0.07%, one-sided lower bound −0.41%, n = 4,661 events. Every exploratory cell agrees. **No edge.**

## 1. CI fix (Phase A)

- Failure causes (run 41899352628): pins `scipy==1.18.1` / `streamlit==1.66.1` need Python ≥3.12 / ≥3.11, so the 3.10/3.11 and ui-smoke jobs
  could not install; `test_cache_replays_offline_and_budget_cap_is_enforced` needed `GEMINI_API_KEY` because the client was built before the budget check.
- Fix: **Python 3.12+ only** (one pin set, no marker fallbacks; CI matrix 3.12 + 3.13, ui-smoke on 3.12; README, AGENTS.md, Dockerfile updated).
  Chosen over per-version constraints because those already existed and still broke, and two pin sets cannot share one backtest digest.
  The budget gate now runs before any key/SDK/network access; the test removes the key and makes client construction fail the test;
  a new fake-client test covers the live path offline.
- Result: run 41900979973 green on all four jobs. Final run: see "Final checks".

## 2. Point-in-time universe (Phase B)

How it is built (`backtest/pit_universe.py`, report `results/pit_universe_2026-11-04.md`):
- On decision session D, an event counts if its company is in the **top 100 US-listed domestic filers by market cap at the close of D-1**:
  EDGAR share count from the latest 10-K/10-Q accepted before 16:00 ET on D-1 × split factor × split-adjusted close (BRK.B × 1,500).
  Membership is computed inside the harness, so the poisoned-future tests cover it.
- Candidates (569; 564 with data): every S&P 500 member since 2014 (dated historical list), plus every listed company with ≥100M shares
  in any EDGAR frame (screened at rank ≤200 by quarter), plus every company ranked ≤150 by public float in any year (no prices needed;
  catches Visa and MercadoLibre). Completeness check: public-float top-150 of every year 2014–2025.
- Share classes (GOOGL, BRK.B, FOXA, NWSA, ...), ticker changes (by CIK), and re-registrations (8 predecessor CIKs) handled explicitly.
- Data-quality guards, each found on a real filing error and PIT-safe: unit-only NI/EPS override (WFC 2020Q1), unconfirmed share-count
  jumps held back (WTTR), cap vs public float (ADS ratios, banks tagging shares ×1000), cap vs assets (RRBI; always on in rules v2).
  MLP units, commodity/crypto trusts and preferred-only listings excluded. The review found errors these v1 guards missed (see section 4). Cross-check vs Finnhub caps of Session 2's 100 names: 98 within ±20–25%;
  BX/IBKR differ by definition (Up-C units).
- **Known gaps:** ~25 large companies later delisted have no price history reachable from this sandbox (Allergan, Celgene, Walgreens,
  Time Warner, Dow Chemical, Express Scripts, Monsanto, Anadarko, Shire, EMC, Aetna, Raytheon, Activision, Pioneer, Discover, Kenvue, ...).
  The direction of the resulting bias is **unknown** (several were long decliners before they left; a takeover premium rarely falls in an
  earnings window); the reviewer estimates a few percent of events. The within-ticker H1 is largely immune. Fix requires a delisted-price source.

Biased vs PIT on the Session 2 window (2023-10..2026-09; `results/pit_vs_biased_2026-11-04.md`), T+20, season-clustered CIs:

| | A: Session 2 (biased) | B: today's top 100, new data (biased) | C: point-in-time |
|---|---|---|---|
| events / tickers | 1,183 / 100 | 1,171 / 99 | 1,198 / 134 |
| buy-and-hold excess vs sector ETF | +0.97% [+0.72, +1.24] | +0.95% [+0.64, +1.30] | **+0.12% [−0.20, +0.42]** |
| council excess vs sector ETF | +0.34% | +0.27% | −0.22% [−0.60, +0.18] |
| factors-only excess vs sector ETF | +0.23% | +0.15% | −0.26% [−0.53, −0.01] |
| council − factors-only | +0.73% | +0.74% | +0.74% [−0.02, +1.52] |
| council selection skill (within ticker) | −0.00% | −0.20% | −0.08% [−1.91, +1.80] |

B ≈ A shows the new data pipeline agrees with Session 2's; B → C isolates the universe: **about 12% of the excess survives** (C/B = 0.12).

## 3. H1 (Phase C pre-registration, Phase D run)

`HYPOTHESIS.md` committed in e43319c before any Phase D decision was computed (it discloses that ~25% of the sample, 2023-10..2026-09, had been seen in Phase B).
- H1: within-ticker selection skill of the mock council at T+5 > 0; one-sided 5%; two-way (season × ticker) bootstrap; reject iff the 5th percentile > 0.
  Pre-computed MDE ≈ 1.0% (≈ 1.3% in effect units, see section 4).
- **Result (`results/h1_phaseD_2026-11-04.md`): S = +0.07%, lower bound −0.41%, 95% CI [−0.54%, +0.65%], p = 0.41; 4,661 events,
  47 seasons, 190 tickers. Not rejected.** Realised MDE 0.76% for S, ≈ 0.98% in within-ticker effect units (S is attenuated, W = 0.78). Unseen subsample (before 2023-10): −0.05%. Two runs: identical sha256 `ccabc089…`.
- P1-5 fixed for this run: YoY growth from the same filing's prior-year comparative (99.1% coverage).

Exploratory (not evidence for anything): selection skill at T+1/T+20 within ±0.4% for both strategies; no VIX regime or sector cell excludes zero.
Buy-and-hold vs sector ETF 2015–2026 on the PIT universe: −0.02% at T+20. Council − factors-only: +0.41% [+0.10, +0.72] at T+20, explained by
exposure (long 67% vs 45%); both trail their sector ETFs.

## 4. Independent review (Phase E)

A fresh subagent audited the PIT universe, the snapshot and the H1 test (`results/independent_review_session3.md`, verbatim + responses).
- **No P0** (no look-ahead found; pre-registration intact).
- P1 data errors in the universe (share counts tagged ×1000 — COP missing ~3.5 years, RPAY ranked ~19th; SHW split counted twice;
  float check biased against momentum names such as TSLA 2020) were fixed as ranking rules v2 in a **review overlay**
  `2026-11-04-pit-r1`. The pre-registered result stays as run. Robustness on the overlay: **H1 S = +0.08%, lower bound −0.45%,
  not rejected; Phase B PIT buy-and-hold +0.10% vs +0.95% biased.** No conclusion changes.
- P1 wording: S is attenuated (W = 0.78), so the MDE in effect units is ≈ 1% (not 0.76%); the "gaps bias buy-and-hold down" claim was
  unsupported and now reads "direction unknown". Correction appended below the line in HYPOTHESIS.md.
- P2 open: BLK has no events before 2022-07; a few vendor dates are not earnings releases; today's GICS used for history; share-count
  jump filter delays real mergers by one filing (KHC 2015–16, LIN 2018–19); big IPOs wait ~14 months (300-session warm-up).

## 5. Open items / what to test next

1. **Delisted prices** (CRSP/Norgate/EODHD or an allowed host) to close the known gaps; then rerun H1 unchanged (same command, new snapshot id).
   Fold the v2 ranking rules and the open P2 event fixes (8-K-only events for BLK, drop vendor-only non-earnings dates) into that new base snapshot.
2. Live LLM council (Session 2 question 2) is still blocked by the Gemini free-tier quota; anonymisation level 2 still unverified.
3. Point-in-time sectors (GICS history) instead of today's sector applied to the past; sector ETF before XLC/XLRE existed is SPY.
4. Up-C companies (BX, IBKR, ...) are ranked on the listed class only; decide whether to add exchangeable units.
5. Session 2 P2 items still open: stops recorded but not simulated; Sharpe/drawdown are event aggregates; legacy untagged report surfaces.
6. With no selection skill at any horizon, the next useful question is not more cells but a different signal; any new idea should be
   pre-registered the same way before it touches the 2015–2026 data.

## Final checks

Run 2026-11-04 22:02–22:12 UTC on the final code:
- pytest **100 passed, 1 skipped** (incl. poisoned-future + leak meta-tests on both PIT snapshots) · UI smoke **1 passed** ·
  legacy suite **19/19** (zero-cost env) · all four snapshot manifests verify (`2026-11-04`, `-sp100`, `-pit`, `-pit-r1`).
- Rerun digests in fresh directories: pre-registered Phase D `ccabc089…` (third identical run), Session 2 sp100 `f5735aab…` (unchanged
  since Session 2), Phase B PIT `63184c87…` (twice); base snapshot `2026-11-04-pit` rebuilds byte-identically from cache.
- Secret scan of all tracked files OK with `SEC_USER_AGENT` present in the env. Kill switches, broker adapters and social posting untouched.
- Live LLM calls this session: **0**. GitHub Actions on the branch: run 41923015186 (commit ccb9c89) green on all four jobs; LOG.md has the final entry.

---

# Session 4 (2026-11-04) — one clean data base, H1 rerun unchanged

Branch `claude/serene-johnson-hofeqi`. Timeline and decisions: `LOG.md` (Session 4 section). Mock LLM mode throughout; **0 live LLM
calls**. Every number below comes from a committed, tagged result file named next to it.

## Bottom line

- **H1, rerun exactly as pre-registered on a cleaner base (only the snapshot id changed): S = +0.08%, one-sided lower bound −0.45%,
  CI [−0.58%, +0.70%], p = 0.40, n = 4,692. Not rejected — the same answer as Session 3 (+0.07%, −0.41%, n = 4,661).** Still no edge.
- No delisted-price source was available, so the survivorship gap from delisted companies remains: an estimated 84 top-100 events
  (1.8%), partial upper bound 159 (3.3%), mostly 2015–2019, direction unknown. **Decision (2026-11-05): delisted companies stay
  excluded; the provider route (EODHD) is documented as the future fix (LOG.md).**

## 1. Data added (Phase A)

- **No delisted-price provider was configured** (no key, no network secret; allowed hosts unchanged). Nothing could be added to the
  candidate pool. The gap was sized from EDGAR (`backtest/delisted_gap.py`, `results/delisted_gap_2026-11-04.md`): 34 gap companies,
  8-K earnings events, top-100 test = latest public float vs the PIT 100th-largest cap on the float date. Revised after the review
  (P1-1): du Pont (only a preferred listed) counted, plausibility before ranking, Discover's mis-tagged float dropped, bound relabelled
  partial. Not findable by a float screen: 21st Century Fox (reviewer: ~16 events) and VMware (controlled).
- New data path: `filings/<T>.json` in the snapshot — every 8-K (items) and original 10-Q/10-K from SEC EDGAR submissions
  (1,197 requests at 5/s, cached). Frozen Item 2.02 lists = fresh EDGAR for all 564 companies.

## 2. Snapshot `2026-11-04-pit2` (Phase B; `results/pit2_changes_2026-11-04.md`)

- **Self-contained base, no overlay**: `rank_rules: v2` (review P1-1..P1-3 of Session 3) and `event_rules: v2`. Prices, fundamentals,
  splits and vendor lists are byte-copies of `2026-11-04-pit`, share counts of `2026-11-04-pit-r1`, both verified against their frozen
  manifests (neither modified). Rebuild from cache byte-identical (manifest `8fbf7d7c…`).
- **Event rules v2** (`snapshot_pit.resolve_events_v2`): P2-1 8-K-only events in vendor-series gaps (BLK +32 events 2014–2022; one per
  reporting period); P2-2 vendor-only 10-Q/10-K dates re-timed from the earnings 8-K or dropped (COST ×2, INTC, KHC, PGR, CCL, USB, BRK.B
  2016, MRNA, DELL; LIN 2020-03-01 dropped), unless a release 8-K corroborates the vendor date (GE 2020-04-29, WELL 2019-02-12 kept).
  8-K-only timing = pre-market of the acceptance day, only for issuers with timely 8-Ks; validated on 22,571 events where both
  sources agree: 0.19% would be one session late (raw acceptance time: 1.6%).
- H1 sample vs Session 3: +64 events (BLK 30, COP 13, re-timed releases, v2 membership), −33 (RPAY 7, SHW 2, rank-100 displacements).
- **Provenance:** a first pit2 build (manifest `38efcb28…`) measured 8-K timeliness in calendar days and wrongly dropped COST's events;
  replaced before review. Its H1 run gave the same decision (recorded in HYPOTHESIS.md).
- Tests: `tests/test_pit2_snapshot.py` (17), incl. offline event rebuild and a reaction-day leak detector (8-K-only events of top-150
  companies: |r(D)|/|r(D+1)| = 0.33; shifted one session late 2.05 — the meta-test). Poisoned-future + leak meta-tests run on all three
  PIT snapshots with a fourth day covering a BLK 8-K-only event.
- **Phase B on the new data** (`results/pit_vs_biased_2026-11-04-pit2.md`): buy-and-hold excess vs sector ETF T+20, biased
  +0.96% [+0.63, +1.33] → point-in-time +0.12% [−0.20, +0.43]; 12% survives, as in Session 3.

## 3. H1 rerun (Phase C; `results/h1_rerun_2026-11-04-pit2.md`, HYPOTHESIS.md below the line)

| | Session 3 (`2026-11-04-pit`) | Session 4 (`2026-11-04-pit2`) |
|---|---|---|
| events / seasons / tickers | 4,661 / 47 / 190 | 4,692 / 47 / 188 |
| S / lower bound / CI | +0.07% / −0.41% / [−0.54, +0.65] | +0.08% / −0.45% / [−0.58, +0.70] |
| p / decision | 0.405 / not rejected | 0.396 / not rejected |
| FE slope; MDE (S / effect units) | +0.09%; 0.76% / 0.98% | +0.10%; 0.79% / 1.01% |

Two parallel runs, identical sha256 `8337e6b5…` (the reviewer reproduced it a third time). **Nothing changed.** The remaining
survivorship gap is the delisted companies only (section 1); H1 is within-ticker, so it is largely immune.

## 4. Independent review (Phase D; `results/independent_review_session4.md`, verbatim + responses)

- **No P0.** H1 rerun reproduced byte for byte; event timing clean (8-K-only and issuer-convention events err early, not late);
  clustering robust (SE 0.307–0.325% across six cluster definitions).
- P1-1 delisted-gap search incomplete / bound mislabelled: **fixed** (84 / 159, see above).
- P2 open: spin-offs stored as yfinance splits inflate PIT caps (HPQ 2015, DD 2019 wrongly in; 4 wrongly out; S → +0.082%) and leave
  adjusted-Close artifacts (DHR 2016 +61%; no H1 return window affected); pre-market timing rules are often one session early
  (dropping them: S → +0.091%); event identification uses later filings (disclosed; BLK checked by hand). P2-5 labels fixed.

## 5. Open items

1. **Delisted companies: excluded by decision (2026-11-05, owner).** The universe keeps only companies with a current listing (all 564
   in pit2 have one); the cost is ~84 events (1.8%, partial upper bound 3.3%), see results/delisted_gap_2026-11-04.md. Future fix if
   revisited: EODHD (allow `eodhd.com`, key as env var, probe the ~36 gap companies first), fallback Sharadar; steps in LOG.md
   (2026-11-05 13:15 entry). Then add the gap companies to the pool and rerun H1 unchanged on a new snapshot id.
2. Split whitelist (spin-offs as ratio 1; DD 2019-06 and HLT 2017 = 1/3) and rebuilt adjusted Close (review P2-1/P2-2).
3. 8-K-only after-close timing per issuer habit, and re-validate the issuer-convention rule on D+1 vs D+2 reactions (review P2-3).
4. Still open from Session 3: point-in-time GICS; Up-C share classes; stops not simulated; legacy untagged report surfaces; the live
   LLM council (Gemini free-tier quota).
5. H1 is settled at "no within-ticker selection skill ≥ ~1% at T+5". A new question needs a different signal, pre-registered first.

## Final checks
pytest 131 passed, 1 skipped · UI smoke 1 passed · legacy 19/19 · H1 rerun `8337e6b5…` and Session 3 `ccabc089…` reproduced in fresh directories · manifests verify, frozen snapshots untouched · secret scan OK · CI run 41937894208 (58b398e) green on all four jobs. Details: last LOG.md entry.

---

# Session 5 (2026-11-05) — H2: Avellaneda–Lee sector-ETF statistical arbitrage

Branch `claude/elegant-sagan-vh8d9x`. Timeline: `LOG.md` (Session 5). Mock LLM mode, **0 LLM calls**, no new data (frozen snapshot `2026-11-04-pit2`, untouched).
Numbers below come from `HYPOTHESIS_H2.md` (RESULTS) and the tagged `results/etf_statarb_2026-11-04-pit2_h2_summary.md`.

## Bottom line
- **H2 is not rejected — and the strategy lost money net of costs.** Pre-registered (commit 610fb6f, before any real-data run): mean daily net return **−1.70 bp**, one-sided 95% lower bound −2.67 bp,
  CI [−2.87, −0.50] bp, p = 0.997, net Sharpe −0.74, n = 3,421 days (2013-04-01..2026-11-03), 1,176 entries. Exact command reproduced byte-identically (digest `be176bb0…`).
- Gross (pre-cost) point estimate +1.11 bp/day (Sharpe 0.48) but **its CI [−0.12, +2.36] includes zero** — not an edge. Turnover is 28% of gross a day (daily re-hedge), costing 2.81 bp/day at 10 bp per side.
  Exact cost sensitivity: net +0.55 / −0.29 / −1.70 bp at 2 / 5 / 10 bp per side. No cost level turns this into evidence of an edge.
- Exploratory (labelled): PCA K=3 −2.32 bp; trading time −2.45 bp; SPY beta 0.04; net negative in 11/14 years; all 12 threshold cells and M = 40/60/90 net-negative; block 5/60 do not matter.
  The strategy is an Avellaneda–Lee-*style* variant; "no edge" is for this variant.

## What was built
- `backtest/etf_statarb.py` (engine, bootstrap, CLI that refuses to run unless HYPOTHESIS_H2.md is committed), `backtest/etf_statarb_report.py` (tagged report + exploratory block +
  registration/manifest checks), `tests/test_etf_statarb.py` (27 synthetic tests: invariants, OU makes money, random walk does not, poisoned-future on S-scores/hedges/positions for xs/pca/trading-time,
  same-close shock test, meta-tests that the detectors fail for a same-close variant and a t+1 window, mutation checks on the real engine).
- Rules kept: signal at close t, trade at close t+1, earn t+2; costs 10 bp per side on turnover; one primary factor model fixed with a written justification; nothing tuned after the result.

## Independent review (`results/independent_review_session5.md`, verbatim + responses)
No P0. P1-1 (run guard only checks the file is committed; no hash pinning) — report now verifies prereg-above-line, engine file and price manifest; the engine guard is left as is to keep the registered digest. P1-2 and P2-3
wording fixed (gross not distinguishable from zero; "variant"). Added: cost sensitivity, realised-SE MDE (1.5 bp/day, Sharpe 0.65 vs registered 1.91 / 0.83). Sub-sample bootstraps flagged as indicative only.

## Open items / next
1. If a lower-cost or lower-turnover design is wanted, it is a different strategy and needs its own pre-registration (hedge ratios frozen at entry, wider bands, longer M — the M = 90 and open = 2.0 cells hint turnover is the constraint, which is *not* a result to chase).
2. Not modelled: borrow, financing, impact, fund-composition changes (2016-09, 2018-06, 2023-03).
3. The guard in `etf_statarb.prereg_committed` is an accident guard, not tamper proof; consider pinning the pre-registration commit and engine hash in the CLI for any future one-shot test.
4. Other ideas from the Drive note remain unstarted (quarter-end flows, TradingAgents test bench, ...); each is pre-registered first.
