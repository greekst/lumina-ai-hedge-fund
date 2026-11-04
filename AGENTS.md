# AGENTS.md — Lumina Capital (research fork)

Instructions for AI coding agents (Claude Code, Codex, Gemini CLI, Cursor, ...) working in this repository. Format follows the [AGENTS.md](https://agents.md) convention; structure adapted from `khasky/awesome-agents-md` (MIT). Explicit instructions from the human owner in the chat override this file.

License: upstream is CC BY-NC 4.0. This fork is for **personal research only**. Never add commercial features or remove the license notice.

## Hard rules (never break)

1. **Paper trading only.** Never configure, test against, or enable the IBKR (`IBKRClient`) or Kabu-Station (`KabuStationClient`) adapters with real credentials or a live gateway. Never set `LUMINA_ENABLE_SOCIAL_POSTING`, never call `XPublisher.post_tweet` for real, never enable any social posting or webhook publishing.
2. **No secrets in git.** `.env`, `config/settings.json`, `*.db` stay ignored. Run `python scripts/check_no_secrets.py` before every commit; it also runs in CI and fails loudly. Never print secret env vars (`env`, `printenv`); test presence with `[ -n "$X" ]`.
3. **Models reason, software calculates.** No LLM-produced number may flow into a metric, signal, position size, stop, or report figure. LLM output is restricted to categorical stances and prose; every number is computed by deterministic code. LLM-returned numeric fields are discarded/clamped by `core/ai_hedge_fund/llm_guard.py`.
4. **Point-in-time correctness.** A backtest decision at time T may only use data with an availability timestamp `< T` (prices up to the close of T-1, filings by their SEC `filed`/acceptance date, never `yfinance.Ticker.info` snapshots). Look-ahead bias is a **P0 bug**. Use `backtest/pit.py` (`PITSnapshot`) for anything historical.
5. **Source tagging.** Every number in a generated report carries `source` and `as_of`. Facts are labelled `SOURCED FACT`; forecasts/model outputs are labelled `MODEL ASSUMPTION`. Use `core/reporting/tagged.py` (`Tagged`) and keep `tests/test_report_tagging.py` green.
6. **Don't spend for the sake of spending.** Tests and backtests run offline with `LUMINA_LLM_MODE=mock`. Never make live LLM calls in tests or CI.

## Working conventions

- Python 3.12+ (the pinned set needs it; CI runs 3.12 and 3.13). Install: `pip install -r requirements.txt` (pinned). Run tests: `LUMINA_LLM_MODE=mock pytest -q`. Legacy suite: `python tests/test_institutional_hardening.py`.
- Network-dependent tests are marked `@pytest.mark.network` and are skipped in CI; core tests use fixtures in `tests/fixtures/`.
- Backtests: `python -m backtest.walkforward --help`. A rerun with the same snapshot must produce byte-identical output; keep it that way (seeded RNGs, sorted iteration, fixed float formatting, no wall-clock timestamps in result files).
- Third-party repos live read-only in `vendor/` (git-ignored). Do not copy their code into `core/` unless the license allows it and the log says so.
- Keep `LOG.md` updated with a dated checkpoint after each meaningful step. Small, verified commits.
- Before claiming "done": run the test command and quote the result.
