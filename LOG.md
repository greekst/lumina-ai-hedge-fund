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
