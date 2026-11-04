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

## 2026-11-04 18:45 — Phase 4 checkpoint (stretch: option a, Finnhub adapter)
- Why (a): it improves traceability more than the other options. The sandbox also showed it is needed: yfinance `Ticker.info` returns HTTP 401 here, so the upstream app gets **no fundamentals at all** (PE/ROE all None, and agents fall back to defaults). Finnhub `/quote`, `/stock/profile2` and `/stock/metric` work on the free tier; `/stock/candle` returns 403. (b) needs no live data and is less central. (c) is large with low trust impact. (d) adds scraping and robots.txt risk for little backtest value (no PIT news archive).
- `core/ai_hedge_fund/data_sources.py`: `LUMINA_DATA_PROVIDER=finnhub|yfinance` (default finnhub when a key exists). Finnhub is tried first per field group; on HTTP 403 (memoised per endpoint for the process), error or missing value, the field comes from yfinance. Non-US symbols go straight to yfinance. Every field gets `data_sources[field]`, and fallbacks are written to `data_source_log` and the `lumina.data_sources` logger.
- `MarketDataFeed.get_stock_data` overlays Finnhub before computing technicals. The council report now tags each value with the source that actually produced it, and lists fallbacks in its header.
- Live check (AAPL): price from finnhub /quote, P/E and ROE from finnhub /stock/metric, candles 403 → yfinance history. 7203.T → yfinance.
- Tests: `tests/test_data_sources.py` (5, mocked HTTP). Suite: 52 passed, 1 skipped; UI smoke passed; legacy 19/19 (zero-cost env); flake8 hard errors 0. Tests pin `LUMINA_DATA_PROVIDER=yfinance` so no test calls Finnhub live.
- Not verified: yfinance `dividendYield` units (upstream multiplies by 100; newer yfinance may already return percent). `.info` is 401 here, so this could not be checked. Flagged in HANDOFF.
- Next: Phase 5 handoff.

## 2026-11-04 19:00 — Phase 5 (final)
- Wrote `HANDOFF.md` (changes, how to run, results with interpretation, limitations, next steps) and added a fork notice at the top of the README.
- Final verification: pytest 52 passed, 1 skipped; UI smoke 1 passed; walk-forward rerun into a fresh dir → same sha256 2233f1c1…; secret scan of all tracked files OK.
- Budget: about 2.5 h of the ~24 h window used. I stopped deliberately after Phase 4 (hard rule 6). The remaining items in HANDOFF §5 need owner decisions (enable Actions, SEC contact UA, universe size, LLM-test design) rather than more autonomous time.

---

# Session 2 — wider universe, EDGAR, anonymised live-LLM test

Branch: `claude/quirky-albattani-qc1wt7` (assigned by the session harness; based on `main` at `3817380`).
Times below are from `date -u` at the moment of writing and are cross-checked against `git log`.
**Session 1 time drift:** Session 1's LOG says Phase 0 at 16:50 and Phase 5 at 19:00, but its commits are
stamped 16:46–17:19 UTC (`git log`), so its later entries ran up to ~1h40m ahead of the clock. Session 1's
entries are left unchanged; this note is the correction.

**Live Gemini call counter (cap 1,500):** 0 used at session start.

## 2026-11-04 17:42 UTC — start
- Env: `GEMINI_API_KEY`, `FINNHUB_API_KEY`, `FRED_API_KEY`, `SEC_USER_AGENT` present (checked with `[ -n ]`, values never printed).
- Network: SEC EDGAR now answers 200 with the declared User-Agent (Session 1 got 403 without one). Finnhub, yfinance and the Gemini API answer.
  `ai.google.dev` is blocked by this sandbox's network policy (proxy 403). The model's documented cutoff was taken from web search results
  of that page and of the Vertex AI model page (see Phase C).

## 2026-11-04 17:55 UTC — Phase A checkpoint (SEC EDGAR as primary PIT source)
- `backtest/edgar.py`: EDGAR client, reads the User-Agent from `SEC_USER_AGENT` only. Throttled to 5 req/s, gzip disk cache in `backtest/cache/edgar/` (git-ignored).
  Fundamentals come from `companyfacts`, the PIT key is the submissions `acceptanceDateTime` joined by accession number, and earnings
  times come from 8-K filings with Item 2.02.
- Verified that EDGAR `acceptanceDateTime` really is UTC (AAPL 8-Ks: 21:30Z in Jan and 20:30Z in Jul both give 16:30 ET). Stored as naive ET, like the rest of the snapshot.
- Two data traps found and fixed: (1) AMZN 10-Qs carry trailing-twelve-month columns. A "longest duration" rule picked those
  instead of YTD, giving net-income errors of up to 76%. YTD length is now capped by the fiscal period `fp`. (2) XOM moved to a holding company
  (ExxonMobil Holdings Corp, new CIK) in July 2026, and the SEC ticker map points only at the new CIK, which has 2 filings. Predecessor
  CIKs are now merged through an explicit map (`PREDECESSOR_CIKS`).
- `backtest/sec_crosscheck.py` → `results/sec_vs_finnhub.md`/`.json`, 10 tickers. 1,533 values compared. 77 mismatches above 1%:
  73 are Finnhub diluted EPS truncated to whole numbers (Session 1's known issue), 4 are a different XBRL concept for PG net income
  (incl. vs excl. NCI), 0 are unexplained. Missing values: EDGAR 0, Finnhub 128. Acceptance-time disagreements: 0.
- Events: 240 yfinance events vs 8-K 2.02. 238 give the same decision session D, 1 is off by one session (AMZN 2024-08-01: yfinance's
  placeholder "12:00" vs 8-K at 16:06 ET, so the 8-K is right), and 1 lies before the price window. None are off by more than one session.
  **D now comes from the 8-K acceptance**; the vendor time is used only when no 8-K matches.
- Tagging validator: inline code spans that contain only a date, datetime, date range, accession number or SEC form code
  (`10-Q`, `8-K`) are treated as identifiers. Any other code span is still checked, so a metric cannot hide in backticks.
- `scripts/check_no_secrets.py` now also fails if the value of `SEC_USER_AGENT`, or its e-mail/domain part on its own, appears in a tracked file.
  Test added with a fake value. Note: CI has no `SEC_USER_AGENT`, so this check is effective locally and in this session's pre-commit runs.
- Tests: 60 passed, 1 skipped (`tests/test_edgar.py`: 7 offline tests).
- Live Gemini calls used: 0.

## 2026-11-04 18:41 UTC — Phase B checkpoint (wider universe, sector-neutral benchmark)
- **Universe = S&P 100 *proxy*, not the official list.** The official constituent list was unreachable from this sandbox: en.wikipedia.org,
  spglobal.com, ssga.com and ishares.com were refused by the network policy; Finnhub `/index/constituents` and `/etf/holdings` (REST and MCP
  connector) returned 403; Yahoo index components returned 401; Bright Data said "customer is not active"; web search gave only top-10 holdings.
  Rule (`backtest/universe.py`): S&P 500 members with GICS sector from `datasets/s-and-p-500-companies` (GitHub, from Wikipedia; it shows the
  2026-09 additions DELL/PANW/SNDK; raw file + sha256 frozen in `backtest/universe/`), Finnhub `marketCapitalization` on 2026-11-04,
  one share class per CIK, and the 100 largest. Sector mix: IT 28, Financials 18, Health Care 15, Industrials 10, Cons. Disc. 7, Staples 7,
  Comm. 7, Energy 4, Real Estate 2, Materials 1, Utilities 1. All 10 Session 1 tickers are included.
- **Survivorship / selection bias (important):** the universe is selected by *today's* market cap, i.e. on past returns, and applied to
  2023–2026 events. Buy-and-hold beats its sector ETF by +0.97% at T+20 (clustered CI [+0.46%, +1.47%]); that is the bias, not an effect.
  Any strategy that is long more often looks better. Hence the new **selection-skill** statistic (long-event minus flat-event sector-relative
  return), which does not reward exposure.
- Snapshot `backtest/snapshots/2026-11-04-sp100` (15 MB, sha256 manifest): EDGAR fundamentals (predecessor CIKs for XOM and BLK, which
  reorganised into new holding companies in 2026-07 and 2024-10), yfinance prices for the 100 stocks + SPY, ^VIX and 11 SPDR sector ETFs.
- **Event timestamps — rule changed after evidence.** The first draft used every 8-K Item 2.02 (clustered at 45 days) as the event list. The
  universe-wide cross-check (`results/events_8k_vs_yfinance_2026-11-04-sp100.md`) showed two failures: (1) wrong events. TSLA delivery
  reports, COST monthly sales, ISRG/DHR preliminary results and ABBV pre-announcements are all furnished under Item 2.02, and clustering
  dropped the real earnings release (every TSLA "event" was a delivery report). (2) **look-ahead.** SCHW releases at ~07:00 but its 8-K is
  accepted at ~16:17 the same day, every quarter (22 events), and BRK.B's 8-K comes 1–4 sessions after the Saturday release. Using the
  8-K alone would put the entry at a close that already contains the news. New rule: yfinance dates identify which dates are earnings; each is
  matched to an Item 2.02 8-K within ±3 days; the timestamp is the **earlier** of the two. This departs from the brief's "decide D from
  the 8-K" because following it literally would create a P0 look-ahead. Result: 2,339 events; 2,285 give the same D; 33 differ by one session
  (all resolved to the earlier D); 0 differ by more than one session; 21 have no 8-K within ±3 days (vendor time used); 138 non-earnings Item 2.02 filings excluded.
  Phase A's report was regenerated with the same rule (AMZN 2024-08-01 now uses the earlier vendor D).
- **New PIT fix (P0 class, inherited from Session 1):** the filings cutoff was the announcement time, but entry is at the close of D. For a
  pre-market release (D = previous session), a filing accepted overnight would have leaked. The cutoff is now `min(announcement, D 16:00 ET)`.
  The new test `test_overnight_filing_before_premarket_release_is_excluded` fails on the old code. Session 1 impact: 0 events, 0/360 decisions.
- EDGAR vs Finnhub on Session 1's 10 tickers (same harness): decision dates identical for 120/120 events, council long/flat agrees on 117/120,
  and council − factors-only at T+20 goes from +0.90% [−0.15%, +2.01%] (Session 1) to +1.01% [−0.10%, +2.15%].
- Walk-forward on 100 tickers × last 12 events = **1,183 events** (36 calendar months, 2023-11..2026-10). Statistics: i.i.d. and
  **month-clustered** bootstrap CIs (events in a month share market moves and overlapping T+20 windows), MDE at 80% power, by VIX(D-1)
  bucket and GICS sector. Cells with fewer than 8 months get no CI.
  - Council − factors-only (paired) T+20: +0.73% [+0.17%, +1.32%] clustered (MDE 0.84%). Positive, but the council is long 66% vs 43%.
  - **Selection skill T+20:** council −0.73% [−2.35%, +0.80%] (MDE 2.24%); factors-only −0.42% [−1.59%, +0.68%]. Neither picks better
    events than it skips. The paired "advantage" is exposure to a winner-selected universe.
  - Council excess vs sector ETF T+20: +0.34% [−0.03%, +0.68%]; buy-and-hold: +0.97% [+0.46%, +1.47%].
  - Regimes: VIX<15 229 events, VIX 15–25 899, VIX>25 55 (3 months, so no CI). No regime shows significant selection skill.
- Reproducibility: two full runs, identical output sha256 `5161e20ac61b01ea9fcb1bcf80a7ff614a5d2f26c674ca9d2d25b2947bd39f48`.
- Tests: 73 passed, 1 skipped (EDGAR-snapshot poison test for JPM/XOM/NVDA incl. sector ETF; rerun digest; manifest hashes).
- Live Gemini calls used: 2 / 1,500 (1 smoke OK, 1 HTTP 404 — see Phase C).

## 2026-11-04 18:51 UTC — Phase C checkpoint: BLOCKED by the Gemini free-tier quota (partial, exploratory results only)
- **Model and cutoff.** `gemini-2.5-flash` (documented cutoff January 2025) answered HTTP 404 "no longer available to new users". `gemini-3.5-flash`
  is documented as deprecated and auto-routed to a newer model, so it was rejected (a silent re-route could change the cutoff). The council
  code's own `gemini-3.8-flash` has a March 2026 card cutoff with uneven domains, which would leave few held-out events and a fuzzy boundary.
  **Used: `gemini-3-flash-preview`**, knowledge cutoff **January 2025** per the Google Cloud Vertex AI model page
  (https://docs.cloud.google.com/vertex-ai/generative-ai/docs/models/gemini/3-flash, found by web search; `ai.google.dev` itself is blocked by this
  sandbox's proxy). Every response's `model_version` is checked against the requested model.
- Held-out = decision session after 2025-01-31: **640 events** (577 reach the model; 63 are CRO vetoes, which are HOLD in both arms and are not sent).
  Planned arms: live personas cathie_wood and william_oneil (highest MoE weights; personas dropped before events, as the brief requires) = 1,154 requests.
- Built: `backtest/anonymise.py` (CO-### code, sector, no ticker/name/price/date/news; level 1 = rounded, level 2 = banded),
  `backtest/llm_client.py` (prompt-hash cache committed under `backtest/llm_cache/`, hard cap enforced in code, SDK-internal retries
  disabled so every request is counted), `backtest/live_council.py` (paired live vs mock on identical PIT inputs; council internals are
  forced to mock so no untracked call is possible). Tests: anonymised block has no identifiers; poisoned-future test on the LLM prompt
  (levels 1 and 2); cache/budget discipline; LLM numbers cannot reach a decision.
- **Blocker:** after 20 successful leakage prompts the API returned 429 `GenerateRequestsPerDayPerProjectPerModel-FreeTier`, quota value **20**,
  retry in ~13 h. At 20/day the run needs ~60 days. Not worked around: other Gemini models have different (later or unknown) cutoffs, which would
  break the held-out design, and Gemma 4 has no documented cutoff (third-party listings only).
- **Exploratory leakage result (level 1, 20 of 100 prompts, 20 distinct companies):** the first guess was correct for 5/20 = 25% (Wilson 95% CI 11–47%), and
  the right company was in the top 3 for 8/20 = 40%. The calendar quarter was guessed correctly 0/20. Level 1 **fails** the 10% threshold even on the partial sample. Level 2 is implemented but unverified.
  `results/live_council_2026-11-04-sp100_status.md`.
- My client first misclassified the 429 as per-minute and then as daily from free text. It now parses the violated `quotaId`s.
- **Live Gemini calls used: 28 / 1,500** (22 OK: 1 smoke, 1 diagnostic, 20 leakage; 6 errors: 1 HTTP 404 on gemini-2.5-flash, 5 HTTP 429).
- Phase D was started in parallel at ~18:47 (fresh subagent, given only the repo path and the brief's instruction).

## 2026-11-04 19:05 UTC — Phase D checkpoint (independent review)
- Fresh general-purpose subagent, started ~18:47 UTC, given only the repo path and the brief's instruction verbatim. It changed no files.
  Its report is saved verbatim, with responses, in `results/independent_review.md`.
- **P0-1 (fixed):** a pre-market release could still land after the close when the vendor stamp is "16:00" and the 8-K is late
  (SCHW 2025-01-21: +5.92% on D, 8-K 16:17:50). Fix: point-in-time issuer convention (`apply_issuer_convention`). If the vendor says after-close,
  the 8-K is on the same day, and at least 75% of the issuer's last eight earlier releases were pre-market, the release is treated as pre-market.
  6 events moved one session earlier: SCHW ×2, plus PLTR ×3 and MCD ×1 (time-switching issuers; conservative). Two rule drafts were rejected
  along the way: the first treated "16:00" as a placeholder (54 events, wrong for after-close issuers); the second also fired on
  evening-vendor/next-morning-8-K cases. A price diagnostic was added to the event report (3 flags, each checked against its 8-K: no timing error).
- **P1 fixed:** (1) selection skill is now within-ticker (fixed effects): council T+20 goes from −0.73% to −0.00% [−1.50%, +1.54%]; (2) clusters are now earnings
  seasons (12), not months (36): council − factors T+20 CI goes from [+0.17%, +1.32%] to [+0.01%, +1.45%]; (3) share-count sanity check (MCD tags shares in millions).
  **P1 open:** survivorship (needs a PIT universe); YoY growth across spin-offs. **P2:** source labels and the i.i.d.-CI label fixed; the rest documented.
- Reruns: sp100 walk-forward twice, identical sha256 `f5735aab38bfac3513372436d01f9d12b0d2534605791c93fa2ef5c81a8cdd01`. Session 1 snapshot rerun:
  `929fe3f3…`, stable; 0/360 decisions changed (digest differs from Session 1's only through new output columns). Event cross-check and live-council
  status regenerated. No answer to the three questions changed.
- Tests: 75 passed, 1 skipped.
- Live Gemini calls used: 28 / 1,500 (unchanged).

## 2026-11-04 19:08 UTC — Phase E (final)
- `HANDOFF.md` Session 2 section: answers to the three questions with numbers, CIs and sample sizes, the review outcome, next tests, and what is blocked.
- Final checks (run 19:05–19:08 UTC): pytest **75 passed, 1 skipped**; UI smoke **1 passed**; legacy suite **19/19** (zero-cost env);
  walk-forward rerun into a fresh directory → sha256 `f5735aab…` (same as both Phase D runs); both snapshot manifests verify;
  secret scan of all tracked files OK, with `SEC_USER_AGENT` present in the env, so its value and contact parts were checked.
- Kill switches / broker / social-posting code untouched this session (`git diff 3817380` on those files is empty). Paper only.
- **Final live Gemini count: 28 / 1,500** (22 OK, 6 errors).
- Time check: Session 2 LOG entries 17:42, 17:55, 18:41, 18:51, 19:05 and 19:08 vs commits 17:55:28, 18:41:52, 18:51:09 and 19:05:26. Two entries were
  first written ahead of the commit and corrected (noted in the Phase C and Phase D entries' history).

---

# Session 3 (2026-11-04) — CI, point-in-time universe, longer history, pre-registered H1

Branch: `claude/kind-rubin-ahzsge` (assigned by the harness). Mock LLM mode throughout; no live LLM calls.

## 2026-11-04 19:51 UTC — Phase A: fix CI
- Failing run inspected: run 41899352628 (main, merge of PR 2). Four jobs failed: `test (3.10)` (`streamlit==1.66.1` needs ≥3.11),
  `test (3.11)` and `ui-smoke` (`scipy==1.18.1` needs ≥3.12), `test (3.12)` (`test_cache_replays_offline_and_budget_cap_is_enforced`:
  `GEMINI_API_KEY not set`).
- **Choice: support Python 3.12+ only.** Justification: the alternative (per-version marker fallbacks for 3.10/3.11) already existed for
  numpy/scipy/etc. and still broke, because every new upstream release can drop an old interpreter; it doubles the pin set and the two halves
  are never tested against the same backtest digest. One pin set on ≥3.12 is simpler and keeps results reproducible. Changes:
  `requirements.txt` (markers removed, header notes ≥3.12), CI matrix `["3.12", "3.13"]` (3.13 resolution checked with
  `pip install --dry-run --python-version 3.13 --only-binary=:all:`), `ui-smoke` on 3.12, README badge, `AGENTS.md`, Dockerfile `python:3.12-slim`.
- **Live-council test made offline:** the root cause was ordering. `GeminiCached._call` built the client (needing the key) before checking the budget.
  The budget gate now runs first, before any key, SDK or network access. The test removes `GEMINI_API_KEY` and replaces `google.genai.Client` with
  a function that fails the test if called. A new test drives the live path through a fake client (request counted, response cached, replay free).
  The old code fails the updated test with no key; the new code passes.
- Local env: fresh `.venv` on Python 3.12 with the pinned set. `pytest -q` → 76 passed, 1 skipped.

## 2026-11-04 19:53 UTC — Phase A result
- CI run 41900979973 on `claude/kind-rubin-ahzsge` (commit 0fd8b6c): **all four jobs green** (secrets, test 3.12, test 3.13, ui-smoke).

## 2026-11-04 21:17 UTC — Phase B checkpoint: point-in-time universe built and frozen
- **Membership rule** (`backtest/pit_universe.py`, decided inside the harness): on decision session D, an event counts if its company
  ranks in the top 100 US-listed domestic filers (10-K/10-Q) by market cap at the close of D-1. Cap = PIT share count (latest
  periodic filing accepted before 16:00 ET on D-1) x split factor x split-adjusted close of D-1 (BRK.B x 1500, Class A equivalents).
  Share count per filing: dei cover value if within 0.8–1.25x of the same filing's weighted count; else weighted diluted (or basic,
  or BasicAndDiluted for loss-makers); else NI / diluted EPS; last resort (Visa: everything per class) public float / close on the float date.
- **Data-quality guards, each found on real errors and each PIT-safe (only past filings used):**
  NI/EPS only overrides a weighted count for order-of-magnitude unit errors (WFC 2020Q1 EPS 0.01 gave 65B shares; BA, CRWD rounded EPS);
  a share count > 3x away from the last accepted one waits for confirmation by the next filing (one-off tags such as WTTR);
  cap > 10x latest public float -> not rankable that day (ADS-ratio junk AKTX; banks tagging shares x1000: NKSH, LOB, GRC, PEBK),
  waived only if the float looks tagged in thousands AND the share count is confirmed by two tags (Duke Energy 2023);
  with no float and a single-tag count, cap > 100x total assets -> not rankable (RRBI 2019; removes nothing else from any top-110).
  Excluded as not common stock: commodity/crypto trusts (SIC 6221: GLD, BITW), MLP units (EPD, CQP, SPH), preferred-only listings (CTA.PA, CRD.A).
- **Candidate pool** (`backtest/universe/pit/candidates.json`, inputs frozen with sha256): (1) every S&P 500 member on any date since
  2014-01-01 (fja05680/sp500 historical components, 784 tickers, 175 without a current listing); (2) every NYSE/Nasdaq/CBOE-listed
  company with >= 100M shares in any EDGAR frame; screened by frames shares x yfinance month-end closes (rank <= 200 at any quarter end
  2014Q1–2026Q3); (3) every listed company ranked <= 150 by dei:EntityPublicFloat in any year (needs no prices; caught Visa and MercadoLibre,
  which the share-based screen missed). Screen bugs found and fixed on the way: sparse Q4 frames put small caps at rank 1; frames hold
  split-restated values (AAPL 2020 4x). 569 candidates -> 564 in the snapshot with prices + EDGAR data, 44 flagged (list in universe.json).
- **Ticker changes / share classes / re-registrations:** one entry per CIK; renamed companies keep full Yahoo history under the current
  ticker (FB->META etc.). Dual classes: GOOGL, FOXA, NWSA, BRK.B, LEN, BF.B, HEI. Predecessor CIKs merged: XOM, BLK, AVGO (Avago, Broadcom Ltd),
  DIS (TWDC Enterprises 18), CI (old Cigna), MDT (Medtronic Inc), GOOGL (Google Inc), MRVL (Bermuda parent). Mergers of two operating
  companies (DowDuPont, Linde/Praxair, DXC) are not merged: those companies enter when the new registrant files.
- **Known gaps (no price history: Yahoo keeps none for delisted tickers; Stooq/Nasdaq/Tiingo/Polygon/AlphaVantage/stockanalysis blocked
  by the network policy; Finnhub candles 403; a Bright Data scrape was refused by the permission classifier and not pursued):**
  Allergan, Celgene, Walgreens Boots Alliance, Time Warner, Dow Chemical, Express Scripts, Monsanto, Anadarko, Shire, EMC, Time Warner
  Cable, Reynolds American, Aetna, Raytheon, Activision, Alexion, Kraft Foods Group, Precision Castparts, DirecTV, Yahoo, Discover,
  Pioneer, Covidien, Kenvue (all found by the public-float completeness check). Bias: these are mostly acquisitions, which end with a
  takeover premium, so their absence biases buy-and-hold slightly DOWN, not up. Full table: `results/pit_universe_2026-11-04.md`.
- Membership: 196 distinct companies were top-100 at some quarter end since 2014-06; 96 of them are not in today's top 100
  (e.g. CMCSA, PYPL, NKE, MMM, UPS, ZM, MRNA, SNOW; full list and quarter-by-quarter turnover in the report). Cross-check vs Finnhub market caps of
  Session 2's 100 names on 2026-11-03: 98 within 0.8–1.25x; BX and IBKR differ by definition (Up-C: Finnhub adds LP units).
- **Snapshot `backtest/snapshots/2026-11-04-pit`** (63 MB, gzipped CSV/JSON, 1,709 files, sha256 manifest): prices 2013-01..2026-11 for
  564 candidates + SPY, ^VIX, 11 sector ETFs; EDGAR fundamentals since 2012 incl. same-filing prior-year comparatives (for P1-5);
  PIT share counts and public floats; events since 2014-06. A second build from cache gives an identical manifest.
- **Poisoned-future tests** (`tests/test_pit_snapshot.py`): every candidate's prices from D on, share counts accepted at/after 16:00 on
  D-1 and filings after the announcement are poisoned on three busy days (2016, 2020, 2024): ranks, event set and all decision-time
  columns unchanged. Meta-tests: the detector FAILS for a harness that ranks at D instead of D-1 and for one that sees share counts
  18 hours early. Session 2 regression: sp100 walk-forward rerun with the modified harness reproduces sha256 `f5735aab…`.
- Tests: 91 passed, 1 skipped.

## 2026-11-04 21:21 UTC — Phase B result: survivorship-biased vs point-in-time, Session 2 window
Source: `results/pit_vs_biased_2026-11-04.md` (tagged). Window D in 2023-10-09..2026-09-30 (12 seasons), mock council, season-clustered CIs.
- A = Session 2 as published (1,183 events, 100 tickers); B = today's top 100 recomputed on Session 3 data (1,171 events, 99 tickers);
  C = point-in-time universe (1,198 events, 134 tickers).
- **Buy-and-hold excess vs sector ETF, T+20: A +0.97% [+0.72, +1.24], B +0.95% [+0.64, +1.30], C +0.12% [−0.20, +0.42].**
  B reproduces A on new data (data pipeline consistent); C keeps about 12% of it (C/B = 0.12), and the CI includes zero.
  T+5: B +0.46% -> C −0.05%; T+1: B +0.39% -> C −0.10%. The Session 2 "about 1% per 20 sessions" was survivorship.
- Council excess vs sector ETF T+20: B +0.27% -> C −0.22% [−0.60, +0.18]; factors-only B +0.15% -> C −0.26% [−0.53, −0.01].
- Council − factors-only (paired) T+20 is unchanged at +0.74% in all three (C: [−0.02, +1.52]): it is the long-rate gap
  (council long 71% vs 43% in C) times the market, not stock selection.
- **Within-ticker selection skill stays at zero** in every universe and horizon; council T+5: A +0.08%, B −0.02%, C −0.02% [−1.06, +1.12].
- Output digests: B `5c48ffbd…`, C `63184c87…` (rerun check in progress).

## 2026-11-04 21:21 UTC — Phase C: HYPOTHESIS.md committed before Phase D
- H1: within-ticker selection skill of the mock council at T+5 > 0 on the PIT universe, D >= 2015-01-01, two-way (season x ticker)
  pigeonhole bootstrap, one-sided 5%: reject iff the bootstrap 5th percentile > 0. MDE ≈ 1.0% (one-sided, 80% power), from the
  Phase B SE (0.813%) scaled by sqrt(12/47). Disclosed: the 2023-10..2026-09 part (about a quarter of the sample) was seen in Phase B.
  No decision or return before 2023-10-09 had been computed when the file was committed.

## 2026-11-04 21:29 UTC — Phase D: H1 run as pre-registered (P1-5 fixed, two-way clustering)
- P1-5 (review): YoY revenue growth now uses the prior-year comparative inside the current filing (`edgar.fundamentals_from_companyfacts(comparatives=True)`,
  `pit._yoy_growth(mode="comparative")`; same acceptance time, so PIT-safe; 99.1% of revenue filings since 2014-06 carry it; falls back to the
  old method, labelled, otherwise). Unit test with a spin-off restatement (legacy −34% vs comparative +10%).
- Two-way clustering: `stats.cluster_diff_2way` (season x ticker pigeonhole bootstrap, conservative), unit-tested on simulated data.
- Extended history: events from 2015-01 on the PIT universe; the Phase B snapshot already covered 2013-01..2026-11 (no second download).
  Snapshot frozen in Phase B; rebuild byte-identical. **Two reruns of the pre-registered command: identical sha256 `ccabc089…`.**
- **H1 (confirmatory): S = +0.07%, one-sided lower bound −0.41%, CI [−0.54%, +0.65%], p = 0.41, n = 4,661 events / 47 seasons / 190 tickers.
  Not rejected.** Unseen pre-2023-10 subsample: −0.05%.
- Exploratory (`results/h1_phaseD_2026-11-04.md`): selection skill at T+1/T+20 for both strategies within ±0.4%, all CIs include zero;
  no VIX regime or sector cell excludes zero. Buy-and-hold excess vs sector ETF on the PIT universe 2015–2026: T+20 −0.02% [−0.24, +0.18].
  Council − factors-only T+20 +0.41% [+0.10, +0.72] and T+5 +0.16% [+0.01, +0.31]: exploratory, and explained by exposure (council long
  67% vs factors-only 45%) in a rising market — both strategies trail their sector ETFs (council T+20 −0.16%, factors-only −0.24%).
- Phase B PIT run reproduced: `63184c87…` twice.

## 2026-11-04 22:04 UTC — Phase E: independent review, fixes, robustness
- Fresh general-purpose subagent started ~21:31 UTC (after the Phase D commit), given only the repo path, venv/test hints, a scratch dir,
  "change no files, no live LLM calls", and the brief's instruction verbatim. Report saved verbatim with responses:
  `results/independent_review_session3.md`.
- **No P0.** Membership timing, event timing, the H1 statistic and the pre-registration were found clean; the reviewer's own counterfactual
  with its fixes left H1 and Phase B unchanged.
- P1-1..P1-3 (share-count ×1000 tags passing the guards: COP missing ~3.5 years, RPAY ranked ~19th; SHW 2021 split counted twice;
  float check biased against momentum names: TSLA 2020, MU 2026, MRNA, DD): **fixed as ranking rules v2 in a review overlay**
  `backtest/snapshots/2026-11-04-pit-r1` (only share counts recomputed; base snapshot and the pre-registered result untouched;
  `verify` checks overlay + base + base identity). Poisoned-future and leak meta-tests now run on both snapshots.
  Regression: COP 2016 rank 419 -> 77, RPAY 19 -> 468, SHW 32 -> 118, TSLA unrankable -> 8.
- Robustness (overlay, exploratory): H1 S = +0.08%, lower bound −0.45%, not rejected; Phase B PIT buy-and-hold vs sector T+20 +0.10%
  (biased +0.95%). No conclusion changes.
- P1-4 (S attenuated, W = 0.78; FE slope +0.09%; MDE in effect units ≈ 0.98%, pre-registered ≈ 1.3%): correction appended below the
  line in HYPOTHESIS.md; decision unchanged. P1-5 (gap bias "down" unsupported): corrected to "direction unknown" in both reports.
  This also corrects the Phase B LOG entry above, which said the gaps bias buy-and-hold slightly DOWN.
- P2 open: BLK events before 2022-07 missing (vendor dates), vendor-only non-earnings dates, today's GICS for history, jump-filter lag
  (KHC 2015–16, LIN 2018–19), IPO warm-up. P2-5 comment fixed. P2-6 provenance: the two Phase D runs were started ~21:22 UTC in parallel
  (two processes, ~6 min each), both sha256 `ccabc089…`.

## 2026-11-04 22:15 UTC — Session 3 final
- Final checks (22:02–22:12 UTC): pytest 100 passed, 1 skipped; UI smoke 1 passed; legacy suite 19/19; four snapshot manifests verify;
  digests reproduced in fresh directories (Phase D `ccabc089…`, Session 2 sp100 `f5735aab…`, Phase B PIT `63184c87…`); base PIT snapshot
  rebuilds byte-identically; secret scan of all tracked files OK; kill switches, broker adapters and social-posting code unchanged since the
  Session 2 merge (`git diff 5529c83` on those files is empty). Live LLM calls this session: 0.
- **GitHub Actions on `claude/kind-rubin-ahzsge`: run 41923015186 (commit ccb9c89) green on all four jobs** (secrets, test 3.12, test 3.13, ui-smoke).
- Branch ready for a PR into `main`.

---

# Session 4 (2026-11-04) — one clean data base, H1 rerun unchanged

Branch: `claude/serene-johnson-hofeqi` (assigned by the harness). Mock LLM mode throughout; no live LLM calls.

## 2026-11-04 22:44 UTC — Start; Phase A: no delisted-price provider
- Environment checked (presence only): `GEMINI_API_KEY`, `FINNHUB_API_KEY`, `FRED_API_KEY`, `SEC_USER_AGENT` set. **No delisted-price
  provider was added**: no further API keys, no network secrets on the environment, and the allowed hosts are unchanged (Yahoo, SEC,
  FRED, Hugging Face, Finnhub, Gemini). Yahoo keeps no history for delisted tickers; Finnhub candles are 403 on this plan. Phase A
  therefore keeps the documented gap and sizes it from EDGAR data only (`backtest/delisted_gap.py`, results/delisted_gap_2026-11-04.md).
- Fresh container: venv rebuilt on Python 3.12 from the pinned set; `pytest -q` → 100 passed, 1 skipped (baseline before any change).

## 2026-11-04 23:00 UTC — Phase A result: delisted gap sized from EDGAR (no prices)
- `results/delisted_gap_2026-11-04.md`: 28 gap companies (public-float top 150 in some year, no current listing, plausible float).
  Lost top-100 events in the H1 window, estimated from the latest public float vs the PIT 100th-largest cap on the float date:
  **82 (1.7%)**, upper bound (150th-largest) **147 (3.1%)**, against 4,661 H1 events. Concentrated 2015Q2–2019Q3 (up to ~11 per
  season, ~10% of a season); near zero since 2020. Largest: Shire 11, Celgene 10, Allergan 8, Walgreens 8, Monsanto 8, Time Warner 7.
- No delisted company could be added to the candidate pool (no prices). Direction of the bias stays unknown.
