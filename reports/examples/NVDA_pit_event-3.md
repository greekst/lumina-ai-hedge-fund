# Point-in-time council report — NVDA before earnings 2026-02-25 16:00 ET

Report as of: 2026-02-24 <!-- text-only -->

> Built from frozen snapshot 2026-11-04: prices through the close of 2026-02-24; filings accepted before the announcement. <!-- text-only -->
> LLM mode: mock (deterministic persona rules). <!-- text-only -->

Legend: `value [SOURCED FACT · source, as_of]` = observed or deterministically computed from sourced data; `[MODEL ASSUMPTION · …]` = forecast, score or rule output. Numbers in model prose are redacted as ‹n›.

## Market & fundamentals — SOURCED FACT

| item | value |
|---|---|
| price (adjusted close, D-1) | 192.40 [SOURCED FACT · yfinance adjusted close (snapshot 2026-11-04), 2026-02-24] |
| P/E (TTM) | 47.7 [SOURCED FACT · finnhub financials-reported (SEC XBRL); split-adj close(D-1) / (TTM net income / weighted diluted shares), 2025-11-19] |
| P/B | 39.81 [SOURCED FACT · finnhub financials-reported (SEC XBRL); split-adj close(D-1) / (equity / weighted diluted shares), 2025-11-19] |
| ROE (TTM) | 83.4% [SOURCED FACT · finnhub financials-reported (SEC XBRL); TTM net income / latest equity, 2025-11-19] |
| revenue growth (YoY YTD) | 62.1% [SOURCED FACT · finnhub financials-reported (SEC XBRL); YoY revenue growth, same-length YTD, 2025-11-19] |
| VIX close (D-1) | 19.55 [SOURCED FACT · yfinance ^VIX close (snapshot 2026-11-04), 2026-02-24] |
| ATR(14) % of price | 3.42 [SOURCED FACT · computed from snapshot OHLC, 2026-02-24] |

## Risk metrics — SOURCED FACT (deterministic)

| item | value |
|---|---|
| volatility 20d (ann.) | 39.4% [SOURCED FACT · DeterministicMetrics on snapshot prices, 2026-02-24] |
| max drawdown 1y | -28.2% [SOURCED FACT · DeterministicMetrics on snapshot prices, 2026-02-24] |
| Sharpe 1y (rf assumption 4%) | 1.02 [SOURCED FACT · DeterministicMetrics on snapshot prices, 2026-02-24] |
| RSI 14 | 63.3 [SOURCED FACT · DeterministicMetrics on snapshot prices, 2026-02-24] |
| VaR 95% 1d (historical) | -4.17% [SOURCED FACT · DeterministicMetrics on snapshot prices, 2026-02-24] |
| 52w high | 206.55 [SOURCED FACT · DeterministicMetrics on snapshot prices, 2026-02-24] |
| 52w low | 94.07 [SOURCED FACT · DeterministicMetrics on snapshot prices, 2026-02-24] |

## Alpha158 factors — SOURCED FACT (deterministic)

| item | value |
|---|---|
| ROC5 | 0.0426 [SOURCED FACT · Alpha158Engine on snapshot OHLCV, 2026-02-24] |
| ROC20 | 0.0342 [SOURCED FACT · Alpha158Engine on snapshot OHLCV, 2026-02-24] |
| ROC60 | 0.0846 [SOURCED FACT · Alpha158Engine on snapshot OHLCV, 2026-02-24] |
| MA20 | -0.0317 [SOURCED FACT · Alpha158Engine on snapshot OHLCV, 2026-02-24] |
| STD20 | 0.0296 [SOURCED FACT · Alpha158Engine on snapshot OHLCV, 2026-02-24] |
| RSV20 | 0.9301 [SOURCED FACT · Alpha158Engine on snapshot OHLCV, 2026-02-24] |
| RSQR20 | 0.0285 [SOURCED FACT · Alpha158Engine on snapshot OHLCV, 2026-02-24] |
| CORR20 | -0.4592 [SOURCED FACT · Alpha158Engine on snapshot OHLCV, 2026-02-24] |

## Council views — MODEL ASSUMPTION

_Stances are categorical model judgements; scores are deterministic (stance map / persona rules), never LLM numbers._

| item | value |
|---|---|
| ウォーレン・バフェット stance | BULLISH |
| ウォーレン・バフェット score | 96 [MODEL ASSUMPTION · Lumina agents (LUMINA_LLM_MODE=mock); score = llm_guard stance map or persona rule, 2026-02-24] |
| ベンジャミン・グレアム stance | BEARISH |
| ベンジャミン・グレアム score | 20 [MODEL ASSUMPTION · Lumina agents (LUMINA_LLM_MODE=mock); score = llm_guard stance map or persona rule, 2026-02-24] |
| キャシー・ウッド stance | BULLISH |
| キャシー・ウッド score | 98 [MODEL ASSUMPTION · Lumina agents (LUMINA_LLM_MODE=mock); score = llm_guard stance map or persona rule, 2026-02-24] |
| マイケル・バーリ stance | BEARISH |
| マイケル・バーリ score | 15 [MODEL ASSUMPTION · Lumina agents (LUMINA_LLM_MODE=mock); score = llm_guard stance map or persona rule, 2026-02-24] |
| ジョージ・ソロス stance | BULLISH |
| ジョージ・ソロス score | 95 [MODEL ASSUMPTION · Lumina agents (LUMINA_LLM_MODE=mock); score = llm_guard stance map or persona rule, 2026-02-24] |
| ウィリアム・オニール stance | BULLISH |
| ウィリアム・オニール score | 96 [MODEL ASSUMPTION · Lumina agents (LUMINA_LLM_MODE=mock); score = llm_guard stance map or persona rule, 2026-02-24] |
| cis / BNF風（日本株スイング） stance | BULLISH |
| cis / BNF風（日本株スイング） score | 85 [MODEL ASSUMPTION · Lumina agents (LUMINA_LLM_MODE=mock); score = llm_guard stance map or persona rule, 2026-02-24] |

## Risk (CRO) — MODEL ASSUMPTION

_Rule outputs of RiskManagerAgent (ATR floor, veto rules)._

| item | value |
|---|---|
| veto | no |
| stop-loss price | 175.85 [MODEL ASSUMPTION · RiskManagerAgent ATR/dynamic stop rule, 2026-02-24] |
| max allocation | 12.0% [MODEL ASSUMPTION · RiskManagerAgent allocation rule, 2026-02-24] |
| safety score | 47 [MODEL ASSUMPTION · RiskManagerAgent volatility rule, 2026-02-24] |

## Verdict — MODEL ASSUMPTION

_PortfolioManagerAgent weighted scores → action thresholds._

| item | value |
|---|---|
| action | BUY |
| confidence score | 83 [MODEL ASSUMPTION · PortfolioManagerAgent weighted mean of agent scores, 2026-02-24] |
| allocation | 12.0% [MODEL ASSUMPTION · PortfolioManagerAgent (capped by CRO), 2026-02-24] |
| target price | 240.50 [MODEL ASSUMPTION · PortfolioManagerAgent fixed multiple of price, 2026-02-24] |
| stop-loss price | 175.85 [MODEL ASSUMPTION · CRO stop, exchange-tick rounded, 2026-02-24] |
| degraded mode | no |
| thesis (model prose) | [MOCK LLM aaeac‹n›f‹n›] Deterministic placeholder text; no model was called. |

## Outcome (after decision; post-mortem only) — SOURCED FACT

| item | value |
|---|---|
| return close D → D+1 | -5.46% [SOURCED FACT · yfinance adjusted close (snapshot 2026-11-04), 2026-02-26] |
| return close D → D+5 | -6.40% [SOURCED FACT · yfinance adjusted close (snapshot 2026-11-04), 2026-03-04] |
| return close D → D+20 | -8.63% [SOURCED FACT · yfinance adjusted close (snapshot 2026-11-04), 2026-03-25] |
