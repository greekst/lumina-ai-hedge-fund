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
