# Snapshot `2026-11-04-pit2` vs `2026-11-04-pit` — what changed (Session 4 Phase B)

`2026-11-04-pit2` is a self-contained base snapshot (no overlay): the frozen prices, fundamentals, splits and vendor event lists of `2026-11-04-pit`, the ranking-rules-v2 share counts of `2026-11-04-pit-r1`, a new SEC EDGAR filings index (`filings/`), and events rebuilt with event rules v2 (backtest/snapshot_pit2.py). Neither frozen snapshot was modified. No delisted companies were added (no price source; results/delisted_gap_2026-11-04.md). <!-- text-only -->

## Event rules v2

- P2-1: an earnings 8-K (the last Item 2.02 8-K before the period's 10-Q/10-K) with no vendor date within sixty days and no event within forty-five days becomes an 8-K-only event (vendor-series gaps such as BlackRock 2009-2022). <!-- text-only -->
- P2-2: a vendor-only date four to forty-five days after an earnings 8-K, with no release 8-K (Item 2.02 or 7.01, or exhibits only) on that day or the day before, is the 10-Q/10-K date: re-timed from the 8-K, or dropped if that 8-K is already an event. Corroborated vendor-only dates stay (GE 2020-04-29 and Welltower 2019-02-12 furnished their releases as exhibit-only 8-Ks; Berkshire's Saturday releases). <!-- text-only -->
- 8-K-only timing: pre-market of the acceptance day, whatever the acceptance time (can only move D earlier); and only for issuers whose own 8-Ks are timely (at least four events where vendor date and 8-K agree, at most ten percent of them with the 8-K on a later calendar day than the release). Otherwise no 8-K-only event is created. <!-- text-only -->

Events in the file: 24,008 [SOURCED FACT · snapshot 2026-11-04-pit, 2026-11-04] before, 24,520 [SOURCED FACT · snapshot 2026-11-04-pit2, 2026-11-04] after. New or re-timed events by rule:

| rule | events |
|---|---|
| 8-K only; pre-market of acceptance day (gap) | 540 [SOURCED FACT · snapshot 2026-11-04-pit2, 2026-11-04] |
| 8-K only; pre-market of acceptance day (re-timed) | 38 [SOURCED FACT · snapshot 2026-11-04-pit2, 2026-11-04] |

## Validation of the new event path (ground truth: events where the vendor date and an earnings-item (two point zero two) `8-K` agree)

Before the rule was fixed, timing from the raw acceptance time was checked the same way and put D one session late in 357 of 22,869 such events (1.6%); pre-market of the acceptance day alone, 103 (0.45%). The rule below adds the issuer filter. Ground truth here is the earlier of the two sources, so vendor placeholder times (12:00) count against the `8-K`. <!-- text-only -->

- If those events (issuers passing the filter) had been timed from the `8-K` alone: same decision session 12,482 [SOURCED FACT · snapshot 2026-11-04-pit2, 2026-11-04], earlier 10,045 [SOURCED FACT · snapshot 2026-11-04-pit2, 2026-11-04], LATER (would be look-ahead) 44 [SOURCED FACT · snapshot 2026-11-04-pit2, 2026-11-04] of 22,571 [SOURCED FACT · snapshot 2026-11-04-pit2, 2026-11-04] (0.19% [SOURCED FACT · derived, 2026-11-04]).
- Examples of LATER (event, then `8-K` acceptance): APD 2020-11-11 06:00 8-K 2020-11-12 06:28; BFC 2019-04-17 13:00 8-K 2019-04-18 16:24; BFC 2020-01-20 19:00 8-K 2020-01-23 09:32; CELH 2021-11-11 08:00 8-K 2021-11-12 06:02; CLSK 2019-12-16 17:00 8-K 2019-12-18 12:24; CXW 2018-08-08 16:00 8-K 2018-08-10 08:00; DHI 2014-11-11 07:00 8-K 2014-11-12 10:58; FAST 2025-10-13 06:00 8-K 2025-10-14 09:20; FCEL 2014-12-15 17:00 8-K 2014-12-17 16:14; FCEL 2015-06-08 18:00 8-K 2015-06-10 13:44; FCEL 2017-09-07 07:00 8-K 2017-09-08 16:20; FCX 2015-10-22 08:00 8-K 2015-10-23 16:47. <!-- text-only -->
- Release identification: the matched release is the `8-K` that `earnings_8k_events` picks for its period in 21,209 [SOURCED FACT · snapshot 2026-11-04-pit2, 2026-11-04] cases; another earnings-item (two point zero two) `8-K` is picked in 233 [SOURCED FACT · snapshot 2026-11-04-pit2, 2026-11-04].
- Earnings-item lists, frozen (base build of the previous session) vs fresh EDGAR submissions: 0 [SOURCED FACT · snapshot 2026-11-04-pit2, 2026-11-04] companies differ (rules v1 matching keeps the frozen list, so v1 events are reproduced exactly).

## Events added / removed per company (whole event file, decision dates since 2014-06)

| company | added | removed |
|---|---|---|
| AWRE | 43 [SOURCED FACT · snapshot 2026-11-04-pit2, 2026-11-04] | 0 [SOURCED FACT · snapshot 2026-11-04-pit2, 2026-11-04] |
| COFS | 37 [SOURCED FACT · snapshot 2026-11-04-pit2, 2026-11-04] | 0 [SOURCED FACT · snapshot 2026-11-04-pit2, 2026-11-04] |
| INOD | 35 [SOURCED FACT · snapshot 2026-11-04-pit2, 2026-11-04] | 0 [SOURCED FACT · snapshot 2026-11-04-pit2, 2026-11-04] |
| BLK | 32 [SOURCED FACT · snapshot 2026-11-04-pit2, 2026-11-04] | 0 [SOURCED FACT · snapshot 2026-11-04-pit2, 2026-11-04] |
| STGW | 32 [SOURCED FACT · snapshot 2026-11-04-pit2, 2026-11-04] | 0 [SOURCED FACT · snapshot 2026-11-04-pit2, 2026-11-04] |
| CASS | 30 [SOURCED FACT · snapshot 2026-11-04-pit2, 2026-11-04] | 0 [SOURCED FACT · snapshot 2026-11-04-pit2, 2026-11-04] |
| FNWD | 28 [SOURCED FACT · snapshot 2026-11-04-pit2, 2026-11-04] | 0 [SOURCED FACT · snapshot 2026-11-04-pit2, 2026-11-04] |
| BKTI | 25 [SOURCED FACT · snapshot 2026-11-04-pit2, 2026-11-04] | 0 [SOURCED FACT · snapshot 2026-11-04-pit2, 2026-11-04] |
| LRMR | 25 [SOURCED FACT · snapshot 2026-11-04-pit2, 2026-11-04] | 0 [SOURCED FACT · snapshot 2026-11-04-pit2, 2026-11-04] |
| MTCH | 24 [SOURCED FACT · snapshot 2026-11-04-pit2, 2026-11-04] | 0 [SOURCED FACT · snapshot 2026-11-04-pit2, 2026-11-04] |
| ONTO | 21 [SOURCED FACT · snapshot 2026-11-04-pit2, 2026-11-04] | 0 [SOURCED FACT · snapshot 2026-11-04-pit2, 2026-11-04] |
| NKSH | 16 [SOURCED FACT · snapshot 2026-11-04-pit2, 2026-11-04] | 1 [SOURCED FACT · snapshot 2026-11-04-pit2, 2026-11-04] |
| PAR | 16 [SOURCED FACT · snapshot 2026-11-04-pit2, 2026-11-04] | 0 [SOURCED FACT · snapshot 2026-11-04-pit2, 2026-11-04] |
| KDP | 15 [SOURCED FACT · snapshot 2026-11-04-pit2, 2026-11-04] | 0 [SOURCED FACT · snapshot 2026-11-04-pit2, 2026-11-04] |
| DELL | 12 [SOURCED FACT · snapshot 2026-11-04-pit2, 2026-11-04] | 1 [SOURCED FACT · snapshot 2026-11-04-pit2, 2026-11-04] |
| URG | 0 [SOURCED FACT · snapshot 2026-11-04-pit2, 2026-11-04] | 12 [SOURCED FACT · snapshot 2026-11-04-pit2, 2026-11-04] |
| HWM | 10 [SOURCED FACT · snapshot 2026-11-04-pit2, 2026-11-04] | 1 [SOURCED FACT · snapshot 2026-11-04-pit2, 2026-11-04] |
| TLRY | 11 [SOURCED FACT · snapshot 2026-11-04-pit2, 2026-11-04] | 0 [SOURCED FACT · snapshot 2026-11-04-pit2, 2026-11-04] |
| RC | 10 [SOURCED FACT · snapshot 2026-11-04-pit2, 2026-11-04] | 0 [SOURCED FACT · snapshot 2026-11-04-pit2, 2026-11-04] |
| COGT | 8 [SOURCED FACT · snapshot 2026-11-04-pit2, 2026-11-04] | 1 [SOURCED FACT · snapshot 2026-11-04-pit2, 2026-11-04] |
| CPSS | 9 [SOURCED FACT · snapshot 2026-11-04-pit2, 2026-11-04] | 0 [SOURCED FACT · snapshot 2026-11-04-pit2, 2026-11-04] |
| EVC | 9 [SOURCED FACT · snapshot 2026-11-04-pit2, 2026-11-04] | 0 [SOURCED FACT · snapshot 2026-11-04-pit2, 2026-11-04] |
| OPTT | 8 [SOURCED FACT · snapshot 2026-11-04-pit2, 2026-11-04] | 1 [SOURCED FACT · snapshot 2026-11-04-pit2, 2026-11-04] |
| SMCI | 7 [SOURCED FACT · snapshot 2026-11-04-pit2, 2026-11-04] | 2 [SOURCED FACT · snapshot 2026-11-04-pit2, 2026-11-04] |
| ALMU | 6 [SOURCED FACT · snapshot 2026-11-04-pit2, 2026-11-04] | 0 [SOURCED FACT · snapshot 2026-11-04-pit2, 2026-11-04] |
| SRPT | 3 [SOURCED FACT · snapshot 2026-11-04-pit2, 2026-11-04] | 3 [SOURCED FACT · snapshot 2026-11-04-pit2, 2026-11-04] |
| VERI | 3 [SOURCED FACT · snapshot 2026-11-04-pit2, 2026-11-04] | 3 [SOURCED FACT · snapshot 2026-11-04-pit2, 2026-11-04] |
| ATOM | 5 [SOURCED FACT · snapshot 2026-11-04-pit2, 2026-11-04] | 0 [SOURCED FACT · snapshot 2026-11-04-pit2, 2026-11-04] |
| BNL | 5 [SOURCED FACT · snapshot 2026-11-04-pit2, 2026-11-04] | 0 [SOURCED FACT · snapshot 2026-11-04-pit2, 2026-11-04] |
| PDEX | 4 [SOURCED FACT · snapshot 2026-11-04-pit2, 2026-11-04] | 1 [SOURCED FACT · snapshot 2026-11-04-pit2, 2026-11-04] |
| SCYX | 2 [SOURCED FACT · snapshot 2026-11-04-pit2, 2026-11-04] | 3 [SOURCED FACT · snapshot 2026-11-04-pit2, 2026-11-04] |
| CATX | 4 [SOURCED FACT · snapshot 2026-11-04-pit2, 2026-11-04] | 0 [SOURCED FACT · snapshot 2026-11-04-pit2, 2026-11-04] |
| CCL | 2 [SOURCED FACT · snapshot 2026-11-04-pit2, 2026-11-04] | 2 [SOURCED FACT · snapshot 2026-11-04-pit2, 2026-11-04] |
| COST | 2 [SOURCED FACT · snapshot 2026-11-04-pit2, 2026-11-04] | 2 [SOURCED FACT · snapshot 2026-11-04-pit2, 2026-11-04] |
| INVA | 4 [SOURCED FACT · snapshot 2026-11-04-pit2, 2026-11-04] | 0 [SOURCED FACT · snapshot 2026-11-04-pit2, 2026-11-04] |
| KHC | 3 [SOURCED FACT · snapshot 2026-11-04-pit2, 2026-11-04] | 1 [SOURCED FACT · snapshot 2026-11-04-pit2, 2026-11-04] |
| NB | 0 [SOURCED FACT · snapshot 2026-11-04-pit2, 2026-11-04] | 4 [SOURCED FACT · snapshot 2026-11-04-pit2, 2026-11-04] |
| PGR | 2 [SOURCED FACT · snapshot 2026-11-04-pit2, 2026-11-04] | 2 [SOURCED FACT · snapshot 2026-11-04-pit2, 2026-11-04] |
| IMXI | 2 [SOURCED FACT · snapshot 2026-11-04-pit2, 2026-11-04] | 1 [SOURCED FACT · snapshot 2026-11-04-pit2, 2026-11-04] |
| LAKE | 3 [SOURCED FACT · snapshot 2026-11-04-pit2, 2026-11-04] | 0 [SOURCED FACT · snapshot 2026-11-04-pit2, 2026-11-04] |
| PED | 2 [SOURCED FACT · snapshot 2026-11-04-pit2, 2026-11-04] | 1 [SOURCED FACT · snapshot 2026-11-04-pit2, 2026-11-04] |
| PRGO | 3 [SOURCED FACT · snapshot 2026-11-04-pit2, 2026-11-04] | 0 [SOURCED FACT · snapshot 2026-11-04-pit2, 2026-11-04] |
| SPIR | 3 [SOURCED FACT · snapshot 2026-11-04-pit2, 2026-11-04] | 0 [SOURCED FACT · snapshot 2026-11-04-pit2, 2026-11-04] |
| TPL | 3 [SOURCED FACT · snapshot 2026-11-04-pit2, 2026-11-04] | 0 [SOURCED FACT · snapshot 2026-11-04-pit2, 2026-11-04] |
| AIM | 0 [SOURCED FACT · snapshot 2026-11-04-pit2, 2026-11-04] | 2 [SOURCED FACT · snapshot 2026-11-04-pit2, 2026-11-04] |
| ASMB | 1 [SOURCED FACT · snapshot 2026-11-04-pit2, 2026-11-04] | 1 [SOURCED FACT · snapshot 2026-11-04-pit2, 2026-11-04] |
| AZO | 1 [SOURCED FACT · snapshot 2026-11-04-pit2, 2026-11-04] | 1 [SOURCED FACT · snapshot 2026-11-04-pit2, 2026-11-04] |
| BFC | 1 [SOURCED FACT · snapshot 2026-11-04-pit2, 2026-11-04] | 1 [SOURCED FACT · snapshot 2026-11-04-pit2, 2026-11-04] |
| BRK.B | 1 [SOURCED FACT · snapshot 2026-11-04-pit2, 2026-11-04] | 1 [SOURCED FACT · snapshot 2026-11-04-pit2, 2026-11-04] |
| CXW | 2 [SOURCED FACT · snapshot 2026-11-04-pit2, 2026-11-04] | 0 [SOURCED FACT · snapshot 2026-11-04-pit2, 2026-11-04] |
| EVLV | 2 [SOURCED FACT · snapshot 2026-11-04-pit2, 2026-11-04] | 0 [SOURCED FACT · snapshot 2026-11-04-pit2, 2026-11-04] |
| FRST | 2 [SOURCED FACT · snapshot 2026-11-04-pit2, 2026-11-04] | 0 [SOURCED FACT · snapshot 2026-11-04-pit2, 2026-11-04] |
| FWONA | 1 [SOURCED FACT · snapshot 2026-11-04-pit2, 2026-11-04] | 1 [SOURCED FACT · snapshot 2026-11-04-pit2, 2026-11-04] |
| GPN | 2 [SOURCED FACT · snapshot 2026-11-04-pit2, 2026-11-04] | 0 [SOURCED FACT · snapshot 2026-11-04-pit2, 2026-11-04] |
| HPE | 1 [SOURCED FACT · snapshot 2026-11-04-pit2, 2026-11-04] | 1 [SOURCED FACT · snapshot 2026-11-04-pit2, 2026-11-04] |
| IDN | 1 [SOURCED FACT · snapshot 2026-11-04-pit2, 2026-11-04] | 1 [SOURCED FACT · snapshot 2026-11-04-pit2, 2026-11-04] |
| INTC | 1 [SOURCED FACT · snapshot 2026-11-04-pit2, 2026-11-04] | 1 [SOURCED FACT · snapshot 2026-11-04-pit2, 2026-11-04] |
| KEYS | 1 [SOURCED FACT · snapshot 2026-11-04-pit2, 2026-11-04] | 1 [SOURCED FACT · snapshot 2026-11-04-pit2, 2026-11-04] |
| LCTX | 2 [SOURCED FACT · snapshot 2026-11-04-pit2, 2026-11-04] | 0 [SOURCED FACT · snapshot 2026-11-04-pit2, 2026-11-04] |
| LHX | 2 [SOURCED FACT · snapshot 2026-11-04-pit2, 2026-11-04] | 0 [SOURCED FACT · snapshot 2026-11-04-pit2, 2026-11-04] |
| (37 [SOURCED FACT · snapshot 2026-11-04-pit2, 2026-11-04] more companies, all in the .json) | | |

## H1 sample: pre-registered run (Phase D, Session 3) vs rerun (Phase C, Session 4)

Events 4,661 [SOURCED FACT · wf-backtest 2026-11-04-pit_phaseD / 2026-11-04-pit2_phaseD, 2026-11-04] → 4,692 [SOURCED FACT · wf-backtest 2026-11-04-pit_phaseD / 2026-11-04-pit2_phaseD, 2026-11-04]: added 64 [SOURCED FACT · wf-backtest 2026-11-04-pit_phaseD / 2026-11-04-pit2_phaseD, 2026-11-04], removed 33 [SOURCED FACT · wf-backtest 2026-11-04-pit_phaseD / 2026-11-04-pit2_phaseD, 2026-11-04]. Changes come from membership (ranking rules v2) and from the event rules. <!-- text-only -->

| company | added | removed |
|---|---|---|
| BLK | 30 [SOURCED FACT · wf-backtest 2026-11-04-pit_phaseD / 2026-11-04-pit2_phaseD, 2026-11-04] | 0 [SOURCED FACT · wf-backtest 2026-11-04-pit_phaseD / 2026-11-04-pit2_phaseD, 2026-11-04] |
| COP | 13 [SOURCED FACT · wf-backtest 2026-11-04-pit_phaseD / 2026-11-04-pit2_phaseD, 2026-11-04] | 0 [SOURCED FACT · wf-backtest 2026-11-04-pit_phaseD / 2026-11-04-pit2_phaseD, 2026-11-04] |
| RPAY | 0 [SOURCED FACT · wf-backtest 2026-11-04-pit_phaseD / 2026-11-04-pit2_phaseD, 2026-11-04] | 7 [SOURCED FACT · wf-backtest 2026-11-04-pit_phaseD / 2026-11-04-pit2_phaseD, 2026-11-04] |
| COST | 2 [SOURCED FACT · wf-backtest 2026-11-04-pit_phaseD / 2026-11-04-pit2_phaseD, 2026-11-04] | 2 [SOURCED FACT · wf-backtest 2026-11-04-pit_phaseD / 2026-11-04-pit2_phaseD, 2026-11-04] |
| SCCO | 3 [SOURCED FACT · wf-backtest 2026-11-04-pit_phaseD / 2026-11-04-pit2_phaseD, 2026-11-04] | 0 [SOURCED FACT · wf-backtest 2026-11-04-pit_phaseD / 2026-11-04-pit2_phaseD, 2026-11-04] |
| AMT | 1 [SOURCED FACT · wf-backtest 2026-11-04-pit_phaseD / 2026-11-04-pit2_phaseD, 2026-11-04] | 1 [SOURCED FACT · wf-backtest 2026-11-04-pit_phaseD / 2026-11-04-pit2_phaseD, 2026-11-04] |
| BRK.B | 1 [SOURCED FACT · wf-backtest 2026-11-04-pit_phaseD / 2026-11-04-pit2_phaseD, 2026-11-04] | 1 [SOURCED FACT · wf-backtest 2026-11-04-pit_phaseD / 2026-11-04-pit2_phaseD, 2026-11-04] |
| INTC | 1 [SOURCED FACT · wf-backtest 2026-11-04-pit_phaseD / 2026-11-04-pit2_phaseD, 2026-11-04] | 1 [SOURCED FACT · wf-backtest 2026-11-04-pit_phaseD / 2026-11-04-pit2_phaseD, 2026-11-04] |
| KHC | 1 [SOURCED FACT · wf-backtest 2026-11-04-pit_phaseD / 2026-11-04-pit2_phaseD, 2026-11-04] | 1 [SOURCED FACT · wf-backtest 2026-11-04-pit_phaseD / 2026-11-04-pit2_phaseD, 2026-11-04] |
| MU | 2 [SOURCED FACT · wf-backtest 2026-11-04-pit_phaseD / 2026-11-04-pit2_phaseD, 2026-11-04] | 0 [SOURCED FACT · wf-backtest 2026-11-04-pit_phaseD / 2026-11-04-pit2_phaseD, 2026-11-04] |
| PGR | 1 [SOURCED FACT · wf-backtest 2026-11-04-pit_phaseD / 2026-11-04-pit2_phaseD, 2026-11-04] | 1 [SOURCED FACT · wf-backtest 2026-11-04-pit_phaseD / 2026-11-04-pit2_phaseD, 2026-11-04] |
| SHW | 0 [SOURCED FACT · wf-backtest 2026-11-04-pit_phaseD / 2026-11-04-pit2_phaseD, 2026-11-04] | 2 [SOURCED FACT · wf-backtest 2026-11-04-pit_phaseD / 2026-11-04-pit2_phaseD, 2026-11-04] |
| TSLA | 2 [SOURCED FACT · wf-backtest 2026-11-04-pit_phaseD / 2026-11-04-pit2_phaseD, 2026-11-04] | 0 [SOURCED FACT · wf-backtest 2026-11-04-pit_phaseD / 2026-11-04-pit2_phaseD, 2026-11-04] |
| WDC | 2 [SOURCED FACT · wf-backtest 2026-11-04-pit_phaseD / 2026-11-04-pit2_phaseD, 2026-11-04] | 0 [SOURCED FACT · wf-backtest 2026-11-04-pit_phaseD / 2026-11-04-pit2_phaseD, 2026-11-04] |
| ADP | 1 [SOURCED FACT · wf-backtest 2026-11-04-pit_phaseD / 2026-11-04-pit2_phaseD, 2026-11-04] | 0 [SOURCED FACT · wf-backtest 2026-11-04-pit_phaseD / 2026-11-04-pit2_phaseD, 2026-11-04] |
| APP | 1 [SOURCED FACT · wf-backtest 2026-11-04-pit_phaseD / 2026-11-04-pit2_phaseD, 2026-11-04] | 0 [SOURCED FACT · wf-backtest 2026-11-04-pit_phaseD / 2026-11-04-pit2_phaseD, 2026-11-04] |
| BNY | 0 [SOURCED FACT · wf-backtest 2026-11-04-pit_phaseD / 2026-11-04-pit2_phaseD, 2026-11-04] | 1 [SOURCED FACT · wf-backtest 2026-11-04-pit_phaseD / 2026-11-04-pit2_phaseD, 2026-11-04] |
| CB | 1 [SOURCED FACT · wf-backtest 2026-11-04-pit_phaseD / 2026-11-04-pit2_phaseD, 2026-11-04] | 0 [SOURCED FACT · wf-backtest 2026-11-04-pit_phaseD / 2026-11-04-pit2_phaseD, 2026-11-04] |
| CCL | 0 [SOURCED FACT · wf-backtest 2026-11-04-pit_phaseD / 2026-11-04-pit2_phaseD, 2026-11-04] | 1 [SOURCED FACT · wf-backtest 2026-11-04-pit_phaseD / 2026-11-04-pit2_phaseD, 2026-11-04] |
| CI | 0 [SOURCED FACT · wf-backtest 2026-11-04-pit_phaseD / 2026-11-04-pit2_phaseD, 2026-11-04] | 1 [SOURCED FACT · wf-backtest 2026-11-04-pit_phaseD / 2026-11-04-pit2_phaseD, 2026-11-04] |
| CTSH | 0 [SOURCED FACT · wf-backtest 2026-11-04-pit_phaseD / 2026-11-04-pit2_phaseD, 2026-11-04] | 1 [SOURCED FACT · wf-backtest 2026-11-04-pit_phaseD / 2026-11-04-pit2_phaseD, 2026-11-04] |
| D | 0 [SOURCED FACT · wf-backtest 2026-11-04-pit_phaseD / 2026-11-04-pit2_phaseD, 2026-11-04] | 1 [SOURCED FACT · wf-backtest 2026-11-04-pit_phaseD / 2026-11-04-pit2_phaseD, 2026-11-04] |
| EBAY | 0 [SOURCED FACT · wf-backtest 2026-11-04-pit_phaseD / 2026-11-04-pit2_phaseD, 2026-11-04] | 1 [SOURCED FACT · wf-backtest 2026-11-04-pit_phaseD / 2026-11-04-pit2_phaseD, 2026-11-04] |
| ELV | 0 [SOURCED FACT · wf-backtest 2026-11-04-pit_phaseD / 2026-11-04-pit2_phaseD, 2026-11-04] | 1 [SOURCED FACT · wf-backtest 2026-11-04-pit_phaseD / 2026-11-04-pit2_phaseD, 2026-11-04] |
| ENB | 0 [SOURCED FACT · wf-backtest 2026-11-04-pit_phaseD / 2026-11-04-pit2_phaseD, 2026-11-04] | 1 [SOURCED FACT · wf-backtest 2026-11-04-pit_phaseD / 2026-11-04-pit2_phaseD, 2026-11-04] |
| EOG | 0 [SOURCED FACT · wf-backtest 2026-11-04-pit_phaseD / 2026-11-04-pit2_phaseD, 2026-11-04] | 1 [SOURCED FACT · wf-backtest 2026-11-04-pit_phaseD / 2026-11-04-pit2_phaseD, 2026-11-04] |
| KMB | 0 [SOURCED FACT · wf-backtest 2026-11-04-pit_phaseD / 2026-11-04-pit2_phaseD, 2026-11-04] | 1 [SOURCED FACT · wf-backtest 2026-11-04-pit_phaseD / 2026-11-04-pit2_phaseD, 2026-11-04] |
| LIN | 0 [SOURCED FACT · wf-backtest 2026-11-04-pit_phaseD / 2026-11-04-pit2_phaseD, 2026-11-04] | 1 [SOURCED FACT · wf-backtest 2026-11-04-pit_phaseD / 2026-11-04-pit2_phaseD, 2026-11-04] |
| LMT | 1 [SOURCED FACT · wf-backtest 2026-11-04-pit_phaseD / 2026-11-04-pit2_phaseD, 2026-11-04] | 0 [SOURCED FACT · wf-backtest 2026-11-04-pit_phaseD / 2026-11-04-pit2_phaseD, 2026-11-04] |
| NOC | 0 [SOURCED FACT · wf-backtest 2026-11-04-pit_phaseD / 2026-11-04-pit2_phaseD, 2026-11-04] | 1 [SOURCED FACT · wf-backtest 2026-11-04-pit_phaseD / 2026-11-04-pit2_phaseD, 2026-11-04] |
| NSC | 0 [SOURCED FACT · wf-backtest 2026-11-04-pit_phaseD / 2026-11-04-pit2_phaseD, 2026-11-04] | 1 [SOURCED FACT · wf-backtest 2026-11-04-pit_phaseD / 2026-11-04-pit2_phaseD, 2026-11-04] |
| PNC | 1 [SOURCED FACT · wf-backtest 2026-11-04-pit_phaseD / 2026-11-04-pit2_phaseD, 2026-11-04] | 0 [SOURCED FACT · wf-backtest 2026-11-04-pit_phaseD / 2026-11-04-pit2_phaseD, 2026-11-04] |
| RTX | 0 [SOURCED FACT · wf-backtest 2026-11-04-pit_phaseD / 2026-11-04-pit2_phaseD, 2026-11-04] | 1 [SOURCED FACT · wf-backtest 2026-11-04-pit_phaseD / 2026-11-04-pit2_phaseD, 2026-11-04] |
| SO | 0 [SOURCED FACT · wf-backtest 2026-11-04-pit_phaseD / 2026-11-04-pit2_phaseD, 2026-11-04] | 1 [SOURCED FACT · wf-backtest 2026-11-04-pit_phaseD / 2026-11-04-pit2_phaseD, 2026-11-04] |
| SPGI | 0 [SOURCED FACT · wf-backtest 2026-11-04-pit_phaseD / 2026-11-04-pit2_phaseD, 2026-11-04] | 1 [SOURCED FACT · wf-backtest 2026-11-04-pit_phaseD / 2026-11-04-pit2_phaseD, 2026-11-04] |
| TMUS | 0 [SOURCED FACT · wf-backtest 2026-11-04-pit_phaseD / 2026-11-04-pit2_phaseD, 2026-11-04] | 1 [SOURCED FACT · wf-backtest 2026-11-04-pit_phaseD / 2026-11-04-pit2_phaseD, 2026-11-04] |

## Membership: top hundred at quarter-end sessions, rules v1 (old) vs v2 (new)

| session | only in old | only in new |
|---|---|---|
| `2015-09-30` | EBAY | COP |
| `2015-12-31` | DAL | COP |
| `2016-03-31` | SYK | COP |
| `2016-06-30` | TGT | COP |
| `2017-03-31` | KMB | COP |
| `2017-06-30` | ITW | COP |
| `2017-09-29` | NOC | COP |
| `2018-12-31` | BSX | COP |
| `2019-03-29` | BSX | COP |
| `2019-06-28` | SPGI | COP |
| `2019-09-30` | ECL | COP |
| `2019-12-31` | ZTS | COP |
| `2020-06-30` | RTX | EQIX |
| `2020-09-30` | FDX | TSLA |
| `2020-12-31` | SNAP | TSLA |
| `2021-06-30` | SHW | MDLZ |
| `2021-09-30` | SHW | MO |
| `2024-12-31` | RPAY | APP |
| `2025-03-31` | RPAY | MELI |
| `2025-06-30` | RPAY | MRSH |
| `2025-09-30` | RPAY | APP |
| `2025-12-31` | RPAY | SCCO |
| `2026-03-31` | RPAY | SCCO |
| `2026-06-30` | ENB, MO, RPAY, SPGI | MU, SCCO, STX, WDC |
| `2026-09-30` | COF, RPAY | MU, SCCO |
| `2026-11-03` | RPAY | SCCO |

Quarter-end sessions with any difference: 26 [SOURCED FACT · snapshot 2026-11-04-pit2, 2026-11-04] of 51 [SOURCED FACT · snapshot 2026-11-04-pit2, 2026-11-04].

## Phase B on the new data

Survivorship-biased vs point-in-time, Session 2 window, on the new snapshot: results/pit_vs_biased_2026-11-04-pit2.md (summarised in LOG.md and HANDOFF.md). <!-- text-only -->

