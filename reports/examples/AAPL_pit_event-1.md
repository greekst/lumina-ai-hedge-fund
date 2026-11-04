# Point-in-time council report — AAPL before earnings 2026-11-02 16:00 ET

Report as of: 2026-10-30 <!-- text-only -->

> Built from frozen snapshot 2026-11-04: prices through the close of 2026-10-30; filings accepted before the announcement. <!-- text-only -->
> LLM mode: mock (deterministic persona rules). <!-- text-only -->

Legend: `value [SOURCED FACT · source, as_of]` = observed or deterministically computed from sourced data; `[MODEL ASSUMPTION · …]` = forecast, score or rule output. Numbers in model prose are redacted as ‹n›.

## Market & fundamentals — SOURCED FACT

| item | value |
|---|---|
| price (adjusted close, D-1) | 344.63 [SOURCED FACT · yfinance adjusted close (snapshot 2026-11-04), 2026-10-30] |
| P/E (TTM) | 39.4 [SOURCED FACT · finnhub financials-reported (SEC XBRL); split-adj close(D-1) / (TTM net income / weighted diluted shares), 2026-07-31] |
| P/B | 57.64 [SOURCED FACT · finnhub financials-reported (SEC XBRL); split-adj close(D-1) / (equity / weighted diluted shares), 2026-01-30] |
| ROE (TTM) | 146.2% [SOURCED FACT · finnhub financials-reported (SEC XBRL); TTM net income / latest equity, 2026-07-31] |
| revenue growth (YoY YTD) | 16.2% [SOURCED FACT · finnhub financials-reported (SEC XBRL); YoY revenue growth, same-length YTD, 2026-07-31] |
| VIX close (D-1) | 19.42 [SOURCED FACT · yfinance ^VIX close (snapshot 2026-11-04), 2026-10-30] |
| ATR(14) % of price | 1.94 [SOURCED FACT · computed from snapshot OHLC, 2026-10-30] |

## Risk metrics — SOURCED FACT (deterministic)

| item | value |
|---|---|
| volatility 20d (ann.) | 14.6% [SOURCED FACT · DeterministicMetrics on snapshot prices, 2026-10-30] |
| max drawdown 1y | -13.8% [SOURCED FACT · DeterministicMetrics on snapshot prices, 2026-10-30] |
| Sharpe 1y (rf assumption 4%) | 0.97 [SOURCED FACT · DeterministicMetrics on snapshot prices, 2026-10-30] |
| RSI 14 | 54.9 [SOURCED FACT · DeterministicMetrics on snapshot prices, 2026-10-30] |
| VaR 95% 1d (historical) | -2.00% [SOURCED FACT · DeterministicMetrics on snapshot prices, 2026-10-30] |
| 52w high | 348.91 [SOURCED FACT · DeterministicMetrics on snapshot prices, 2026-10-30] |
| 52w low | 246.03 [SOURCED FACT · DeterministicMetrics on snapshot prices, 2026-10-30] |

## Alpha158 factors — SOURCED FACT (deterministic)

| item | value |
|---|---|
| ROC5 | -0.0089 [SOURCED FACT · Alpha158Engine on snapshot OHLCV, 2026-10-30] |
| ROC20 | 0.0328 [SOURCED FACT · Alpha158Engine on snapshot OHLCV, 2026-10-30] |
| ROC60 | 0.1041 [SOURCED FACT · Alpha158Engine on snapshot OHLCV, 2026-10-30] |
| MA20 | -0.0074 [SOURCED FACT · Alpha158Engine on snapshot OHLCV, 2026-10-30] |
| STD20 | 0.0131 [SOURCED FACT · Alpha158Engine on snapshot OHLCV, 2026-10-30] |
| RSV20 | 0.6637 [SOURCED FACT · Alpha158Engine on snapshot OHLCV, 2026-10-30] |
| RSQR20 | 0.7237 [SOURCED FACT · Alpha158Engine on snapshot OHLCV, 2026-10-30] |
| CORR20 | 0.4707 [SOURCED FACT · Alpha158Engine on snapshot OHLCV, 2026-10-30] |

## Council views — MODEL ASSUMPTION

_Stances are categorical model judgements; scores are deterministic (stance map / persona rules), never LLM numbers._

| item | value |
|---|---|
| ウォーレン・バフェット stance | BULLISH |
| ウォーレン・バフェット score | 96 [MODEL ASSUMPTION · Lumina agents (LUMINA_LLM_MODE=mock); score = llm_guard stance map or persona rule, 2026-10-30] |
| ベンジャミン・グレアム stance | BEARISH |
| ベンジャミン・グレアム score | 20 [MODEL ASSUMPTION · Lumina agents (LUMINA_LLM_MODE=mock); score = llm_guard stance map or persona rule, 2026-10-30] |
| キャシー・ウッド stance | BULLISH |
| キャシー・ウッド score | 80 [MODEL ASSUMPTION · Lumina agents (LUMINA_LLM_MODE=mock); score = llm_guard stance map or persona rule, 2026-10-30] |
| マイケル・バーリ stance | BEARISH |
| マイケル・バーリ score | 15 [MODEL ASSUMPTION · Lumina agents (LUMINA_LLM_MODE=mock); score = llm_guard stance map or persona rule, 2026-10-30] |
| ジョージ・ソロス stance | BULLISH |
| ジョージ・ソロス score | 79 [MODEL ASSUMPTION · Lumina agents (LUMINA_LLM_MODE=mock); score = llm_guard stance map or persona rule, 2026-10-30] |
| ウィリアム・オニール stance | BULLISH |
| ウィリアム・オニール score | 96 [MODEL ASSUMPTION · Lumina agents (LUMINA_LLM_MODE=mock); score = llm_guard stance map or persona rule, 2026-10-30] |
| cis / BNF風（日本株スイング） stance | BULLISH |
| cis / BNF風（日本株スイング） score | 79 [MODEL ASSUMPTION · Lumina agents (LUMINA_LLM_MODE=mock); score = llm_guard stance map or persona rule, 2026-10-30] |

## Risk (CRO) — MODEL ASSUMPTION

_Rule outputs of RiskManagerAgent (ATR floor, veto rules)._

| item | value |
|---|---|
| veto | no |
| stop-loss price | 328.09 [MODEL ASSUMPTION · RiskManagerAgent ATR/dynamic stop rule, 2026-10-30] |
| max allocation | 12.0% [MODEL ASSUMPTION · RiskManagerAgent allocation rule, 2026-10-30] |
| safety score | 61 [MODEL ASSUMPTION · RiskManagerAgent volatility rule, 2026-10-30] |

## Verdict — MODEL ASSUMPTION

_PortfolioManagerAgent weighted scores → action thresholds._

| item | value |
|---|---|
| action | BUY |
| confidence score | 77 [MODEL ASSUMPTION · PortfolioManagerAgent weighted mean of agent scores, 2026-10-30] |
| allocation | 12.0% [MODEL ASSUMPTION · PortfolioManagerAgent (capped by CRO), 2026-10-30] |
| target price | 430.79 [MODEL ASSUMPTION · PortfolioManagerAgent fixed multiple of price, 2026-10-30] |
| stop-loss price | 328.09 [MODEL ASSUMPTION · CRO stop, exchange-tick rounded, 2026-10-30] |
| degraded mode | no |
| thesis (model prose) | [MOCK LLM ‹n›dd‹n›b‹n›ab] Deterministic placeholder text; no model was called. |

## Outcome (after decision; post-mortem only) — SOURCED FACT

| item | value |
|---|---|
| return close D → D+1 | -1.90% [SOURCED FACT · yfinance adjusted close (snapshot 2026-11-04), 2026-11-03] |
