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
