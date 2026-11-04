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
