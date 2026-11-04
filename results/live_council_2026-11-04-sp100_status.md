# Live LLM council — status (snapshot 2026-11-04-sp100)

**Result: BLOCKED.** The paired live-vs-mock run was not executed. The Gemini API key in this session is on the free tier, whose quota for the chosen model is twenty requests per day per model (`GenerateRequestsPerDayPerProjectPerModel-FreeTier`, quota value twenty, observed on `2026-11-04`). The planned run needs more than a thousand requests. Everything is built, tested and cached; see HANDOFF.md for the command. <!-- text-only -->

Model `gemini-3-flash-preview` (documented knowledge cutoff January 2025, Google Cloud Vertex AI model page). Held-out rule: decision session after `2025-01-31`. <!-- text-only -->

## Held-out sample and budget plan

- held-out events (last twelve per ticker, D after the cutoff): 640 [SOURCED FACT · live-council status, 2026-11-04]
- of which reach the model (no CRO veto): 577 [SOURCED FACT · live-council status, 2026-11-04]
- planned live personas per event under the cap: cathie_wood and william_oneil (highest MoE weights; personas dropped before events, as the brief requires) -> planned requests 1,154 [SOURCED FACT · live-council status, 2026-11-04]
- Gemini requests sent this session (all purposes, incl. errors): 28 [SOURCED FACT · live-council status, 2026-11-04] of cap 1,500 [SOURCED FACT · live-council status, 2026-11-04]

## Leakage check, anonymisation level one (EXPLORATORY: quota stopped it after twenty of one hundred prompts)

- prompts answered: 20 [SOURCED FACT · leak check L1 (gemini-3-flash-preview), 2026-11-04] (distinct companies: 20 [SOURCED FACT · leak check L1 (gemini-3-flash-preview), 2026-11-04])
- company named correctly as first guess: 5 [SOURCED FACT · leak check L1 (gemini-3-flash-preview), 2026-11-04] -> 25.0% [SOURCED FACT · leak check L1 (gemini-3-flash-preview), 2026-11-04] (Wilson CI 11.2% [SOURCED FACT · leak check L1 (gemini-3-flash-preview), 2026-11-04] to 46.9% [SOURCED FACT · leak check L1 (gemini-3-flash-preview), 2026-11-04]); threshold ten percent
- correct company among the three guesses: 8 [SOURCED FACT · leak check L1 (gemini-3-flash-preview), 2026-11-04] -> 40.0% [SOURCED FACT · leak check L1 (gemini-3-flash-preview), 2026-11-04]
- calendar quarter guessed correctly: 0.0% [SOURCED FACT · leak check L1 (gemini-3-flash-preview), 2026-11-04]

Verdict: level one FAILS the leakage test even on this partial sample (the lower CI bound is above the threshold). The model recognises mega-caps from sector plus distinctive ratios (e.g. the only utility, the two card networks, a semiconductor leader). Timing does not leak. Level two (banded ratios, integer technicals) is implemented and tested (`backtest/anonymise.py`) but its leakage check was not run. If level two also fails, the next step is to coarsen the sector (the brief keeps it; with only one or two companies in some sectors, sector alone identifies them). <!-- text-only -->

| company (hidden from the model) | model's first guess | in top-3 |
|---|---|---|
| GE | CPRT | no |
| NEE | NEE | yes |
| BMY | BMY | yes |
| MO | KR | no |
| PANW | CRM | no |
| BX | MSCI | no |
| UNP | MMM | no |
| HD | LULU | no |
| PFE | JNJ | no |
| CB | JPM | no |
| GILD | LLY | no |
| V | V | yes |
| XOM | CVX | yes |
| JNJ | LLY | no |
| MA | MA | yes |
| ANET | CRWD | no |
| SBUX | NKE | yes |
| NVDA | NVDA | yes |
| TJX | HD | no |
| NFLX | META | yes |
