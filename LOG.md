# LOG.md — autonomous hardening session

Times are UTC (container clock). Budget proxy: elapsed wall time (no cost readout available).

## Assumptions
- **Branch**: the session harness mandates development on `claude/wizardly-davinci-3zuc53` and forbids pushing to other branches; the brief asked for `claude/24h-hardening`. I used the harness branch (same purpose: one PR into `main` at the end). Rename on GitHub if desired.
- **Vendor repos** are cloned shallow into `vendor/` (git-ignored), read-only.
- **Python**: sandbox has 3.13; CI tests 3.10/3.11/3.12.
- **Docker** binary present but no daemon use; native venv used. **Neo4j** not run (optional; falls back to SQLite).
- **Archify** is an interactive agent skill (LLM-driven HTML), not a headless CLI → Mermaid fallback in AUDIT.md.
- Network: yfinance works (occasional 429 on crumb), SEC EDGAR works, Finnhub free tier: `/quote` and `/stock/earnings` OK, `/stock/candle` 403, FRED API OK.

## 2026-11-04 16:50 — Phase 0 checkpoint
- Done: deps installed (full `requirements.txt` resolve hung >10 min on unpinned LLM libs → installed core set explicitly; pinning is a Phase 1 task). `python -c "import app"` OK. Legacy suite `tests/test_institutional_hardening.py`: 19/19 PASS (hits network).
- Wrote `AGENTS.md` (+ `CLAUDE.md` pointer) encoding the hard rules, `AUDIT.md` (Mermaid architecture, LLM-number map, look-ahead map, P0/P1/P2).
- Headline findings: LLM key never read (council always HOLD), no fees/slippage in paper trader, LightGBM gate trained on random data, tear-sheet NAV curve is a random walk, Alpha158 `bfill` look-ahead, LLM numbers drive sizing, live broker + X posting reachable.
- Next: Phase 1 — fix P0s, mock LLM mode, pytest suite, CI on every push, pin deps.

## 2026-11-04 17:10 — Phase 1 checkpoint
- Fixed P0s: LLM numbers into sizing/scores (`llm_guard.py`: stance→score map, CRO/CIO numbers deterministic, debate adjustment rule, news credibility from flag); Alpha158 `bfill` look-ahead; no fees/slippage (`cost_model.py`, wired into `PaperTradingEngine`, new ledger columns); live broker + X/Discord posting kill switches; fabricated tear-sheet KPIs/NAV curve; LightGBM gate labelled `MODEL ASSUMPTION` + deterministic params; API key sent to browser (found by the new UI smoke test).
- Fixed P1s: LLM key mismatch (`core/llm_mode.py`, `LUMINA_LLM_MODE=live|mock|off`), missing `compute_symbol_summary`, idempotency leak, DB path, bracket note, Docker (no default Neo4j password, localhost ports, non-root, pinned image), settings.json 0600, escaped LLM/news HTML in council cards.
- Mock LLM mode: agents use their deterministic persona rules (flagged `llm_mode=mock`, not degraded); other LLM call sites get a template-shaped deterministic JSON from `MockGenAIClient`.
- Tests: `pytest -q` → 35 passed, 1 skipped (UI smoke runs with `LUMINA_UI_SMOKE=1`: 1 passed). Covers Alpha158 hand-computed refs + PIT invariance (verified it FAILS with the upstream `bfill`), cost math, ledger conservation & rejection integrity, CRO veto (5 paths + OOD), ATR floor (5%/16% clamps) + patrol stop exit, LLM guard, mock determinism, kill switches, secret guard, tear sheet.
- Legacy suite: 19/19 pass with zero-cost env (`LUMINA_*_BPS=0`); with default costs its exact-price assertion (2000 vs 2001) fails by design — documented, CI runs it zero-cost and non-blocking (it needs network).
- CI: every push; secret scan job, pytest on 3.10/3.11/3.12, Playwright UI smoke job. Deps pinned (`requirements.txt`, `-dev`, `-optional`).
- Security audit (cloudflare skill, guidance mode — focused scope given): `SECURITY_AUDIT.md`.
- Decision: did not run the skill's full 6-phase multi-agent workflow; scope was explicitly 4 areas and the brief asks not to burn budget.
- Next: Phase 2 walk-forward harness.

## 2026-11-04 17:55 — Phase 2 checkpoint
- `backtest/snapshot.py` (only networked step) → frozen, sha256-manifested snapshot `backtest/snapshots/2026-11-04` (committed, 1.5 MB): yfinance adjusted OHLCV + split-only close, splits, yfinance earnings timestamps, Finnhub as-reported financials with `acceptedDate`.
- SEC EDGAR: first request worked, then 403 "undeclared automated tool" for the rest of the session (UA policy; I will not spoof). Switched fundamentals to Finnhub `/stock/financials-reported` (the same XBRL data, with acceptance timestamps). Found and handled two data-quality problems: (1) as-reported EPS is truncated to an integer for some filers (AMZN shows 1.0 and 0.0) → EPS derived as TTM net income / weighted diluted shares; (2) as-reported per-share values are pre-split → normalised by subsequent splits (a unit conversion only, no look-ahead). 15 of 520 fundamental values remain missing, and agents use their built-in defaults for those.
- `backtest/pit.py`: D = last close before the announcement; features through D-1; filings accepted before the announcement; TTM = FY + YTD − prior-year YTD (52/53-week tolerant).
- `backtest/walkforward.py`: 10 tickers × 12 events, council (mock) vs factors-only (Alpha158 trend + same CRO veto) vs buy-and-hold; T+1/5/20; 5+5 bps per side; post-mortem JSON per quarter. Options-GEX turbulence is replaced by a PIT VIX(D-1) ≥ 30 proxy. The TimesFM/Chronos/LightGBM/news/macro inputs are excluded (no PIT history, or fabricated); documented.
- Reproducibility: two full runs give identical sha256 `a901a264…` for all outputs. Tests: rerun digest equality, plus a poisoned-future test (all prices ≥ D scrambled, a post-dated filing injected → identical decisions). Verified that test FAILS when the harness is mutated to use day D.
- Result (honest): **no edge found.** Council is long 85% of events, ≈ buy-and-hold minus costs (T+20 avg net +1.99% vs +2.40% B&H; excess vs SPY −0.39% vs −0.43%). Council − factors-only at T+20: +0.90% mean, 95% CI [−0.15%, +2.01%] — not significant, and mostly beta (more time long in a rising market).
- TradingAgents baseline skipped (LLM-only, no mock mode, conflicting pandas pin, LLM training-data look-ahead) — `backtest/tradingagents_adapter.py`.
- GitHub Actions: no runs are recorded for this branch (forks have Actions disabled by default) → CI verified locally only. Owner action: enable Actions on the fork.
- Next: Phase 3 source-tagged reporting.

## 2026-11-04 18:20 — Phase 3 checkpoint
- `core/reporting/tagged.py`: `Tagged(value, source, as_of, kind)` refuses to exist without a source and an ISO date. It renders as `value [SOURCED FACT|MODEL ASSUMPTION · source, YYYY-MM-DD]`. `untagged_numbers()` is the validator: it skips headings, label cells and table header rows, and flags every other number.
- `core/reporting/council_report.py`: `Report` and `Section` reject raw numbers. `to_markdown()` raises if any untagged number survives. Model prose (LLM or persona) has its digits redacted to ‹n›, because a number in prose has no verifiable source. Builders: `build_from_council(ai_res)` (live, tagged `yfinance Ticker.info`, as_of = fetch date, with a "not point-in-time" banner) and `build_from_pit(snapshot, ticker, i)` (offline, deterministic, outcome section kept separate).
- The Streamlit council view has a new "Source-tagged report" expander with a .md download. The walk-forward summary Markdown is also fully tagged. Example reports: `reports/examples/`.
- Forecasts ("TimesFM" heuristic, Chronos, LightGBM synthetic gate), agent scores, CRO and PM outputs are all labelled `MODEL ASSUMPTION`.
- Tests: `tests/test_report_tagging.py` (7). It fails on any untagged number in the live or PIT reports, or in any committed `reports/**/*.md` or `results/*_summary.md`. Suite: 47 passed, 1 skipped. UI smoke: 1 passed. flake8 hard errors: 0.
- Walk-forward output changed only in summary formatting; the new digest `2233f1c1…` reproduced twice.
- Legacy content generators (`fund_content_generator`, `quant_reporter`, note/X drafts) are NOT converted. They are marketing/social outputs, now unpublishable (kill switch), and are listed in HANDOFF as remaining work.
- Next: Phase 4 stretch decision.
