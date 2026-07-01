# Phase 6 Signal Factory Readiness + Edge Audit

This is a read-only audit gate. It is not a live signal, not an entry instruction, and not an execution system.

## Executive Verdict

- phase6_status: `PASS`
- phase7_decision: `NO_PHASE7_CANDIDATE_YET`
- approved_candidates: `0`
- watchlist_candidates: `6`
- rejected_candidates: `294`

## Feature Readiness Per Timeframe

| timeframe | total | ready | partial | missing candles | missing ATR | missing OI | status |
|---|---:|---:|---:|---:|---:|---:|---|
| 15m | 75 | 0 | 75 | 0 | 0 | 0 | TIMEFRAME_PARTIAL_USABLE |
| 1h | 75 | 0 | 70 | 1 | 4 | 0 | TIMEFRAME_PARTIAL_USABLE |
| 4h | 75 | 0 | 0 | 5 | 70 | 0 | TIMEFRAME_NOT_READY |
| 24h | 75 | 0 | 0 | 75 | 0 | 0 | TIMEFRAME_NOT_READY |

## Candidate Readiness Summary

- total_candidates: `300`
- eligible_candidate_count: `6`
- radar_only_count: `137`
- conflicted_count: `2`
- blocked_candidate_count: `155`

## Strategy Arena Mapping Summary

- arena rows evaluated: `300`
- arena verdict counts: `{'ARENA_RESULT_MISSING': 223, 'REJECT': 47, 'INSUFFICIENT_SAMPLE': 15, 'NOISY': 15}`

## Baseline Comparison Summary

- beats baseline counts: `{'None': 223, 'False': 58, 'True': 19}`

## Relative Strength / Anomaly Warning

- relative/anomaly flags: `{'RELATIVE_STRENGTH_SUPPORTS_DIRECTION': 69, 'FLOW_MIXED': 5, 'FLOW_SUPPORTS_DIRECTION': 10}`

## Approved Phase 7 Candidates

No candidates.

## Watchlist Candidates

| symbol | timeframe | setup | direction | score | edge_vs_baseline | verdict |
|---|---|---|---|---:|---:|---|
| LABUSDT | 15m | MID_LONG | BULLISH_CONTEXT | 4 | 0.02801977781696904 | WATCHLIST_FOR_MORE_DATA |
| AAVEUSDT | 15m | MID_LONG | BULLISH_CONTEXT | 4 | 0.02801977781696904 | WATCHLIST_FOR_MORE_DATA |
| GWEIUSDT | 15m | MID_SHORT_FUTURES_LED | BEARISH_CONTEXT | 5 | 0.024940219569512964 | WATCHLIST_FOR_MORE_DATA |
| FILUSDT | 15m | MID_LONG | BULLISH_CONTEXT | 4 | 0.02801977781696904 | WATCHLIST_FOR_MORE_DATA |
| XPLUSDT | 15m | MID_LONG | BULLISH_CONTEXT | 4 | 0.02801977781696904 | WATCHLIST_FOR_MORE_DATA |
| HEIUSDT | 15m | MID_LONG | BULLISH_CONTEXT | 4 | 0.02801977781696904 | WATCHLIST_FOR_MORE_DATA |

## Rejected Candidates

| symbol | timeframe | setup | direction | score | edge_vs_baseline | verdict |
|---|---|---|---|---:|---:|---|
| BTCUSDT | 15m | NO_SETUP | MIXED_CONTEXT | -2 | None | REJECT_FOR_PHASE7 |
| BTCUSDT | 1h | NO_SETUP | MIXED_CONTEXT | -2 | None | REJECT_FOR_PHASE7 |
| BTCUSDT | 4h | BLOCKED_DATA | MIXED_CONTEXT | -1 | None | REJECT_FOR_PHASE7 |
| BTCUSDT | 24h | BLOCKED_DATA | MIXED_CONTEXT | -1 | None | REJECT_FOR_PHASE7 |
| ETHUSDT | 15m | EARLY_LONG | BULLISH_CONTEXT | -4 | -4.1178953448275e-05 | REJECT_FOR_PHASE7 |
| ETHUSDT | 1h | NO_SETUP | MIXED_CONTEXT | -2 | None | REJECT_FOR_PHASE7 |
| ETHUSDT | 4h | BLOCKED_DATA | MIXED_CONTEXT | -1 | None | REJECT_FOR_PHASE7 |
| ETHUSDT | 24h | BLOCKED_DATA | MIXED_CONTEXT | -1 | None | REJECT_FOR_PHASE7 |
| SOLUSDT | 15m | EARLY_LONG | BULLISH_CONTEXT | -4 | -4.1178953448275e-05 | REJECT_FOR_PHASE7 |
| SOLUSDT | 1h | NO_SETUP | MIXED_CONTEXT | -2 | None | REJECT_FOR_PHASE7 |
| SOLUSDT | 4h | BLOCKED_DATA | MIXED_CONTEXT | -1 | None | REJECT_FOR_PHASE7 |
| SOLUSDT | 24h | BLOCKED_DATA | MIXED_CONTEXT | -1 | None | REJECT_FOR_PHASE7 |
| INUSDT | 15m | NO_SETUP | MIXED_CONTEXT | -2 | None | REJECT_FOR_PHASE7 |
| INUSDT | 1h | EARLY_SHORT | BEARISH_CONTEXT | 1 | 0.0162768401386328 | REJECT_FOR_PHASE7 |
| INUSDT | 4h | BLOCKED_DATA | MIXED_CONTEXT | -1 | None | REJECT_FOR_PHASE7 |
| INUSDT | 24h | BLOCKED_DATA | MIXED_CONTEXT | -1 | None | REJECT_FOR_PHASE7 |
| HYPEUSDT | 15m | NO_SETUP | MIXED_CONTEXT | -2 | None | REJECT_FOR_PHASE7 |
| HYPEUSDT | 1h | EARLY_SHORT | BEARISH_CONTEXT | 1 | 0.0162768401386328 | REJECT_FOR_PHASE7 |
| HYPEUSDT | 4h | BLOCKED_DATA | MIXED_CONTEXT | -1 | None | REJECT_FOR_PHASE7 |
| HYPEUSDT | 24h | BLOCKED_DATA | MIXED_CONTEXT | -1 | None | REJECT_FOR_PHASE7 |
| SYNUSDT | 15m | NO_SETUP | MIXED_CONTEXT | -2 | None | REJECT_FOR_PHASE7 |
| SYNUSDT | 1h | EARLY_SHORT | BEARISH_CONTEXT | 1 | 0.0162768401386328 | REJECT_FOR_PHASE7 |
| SYNUSDT | 4h | BLOCKED_DATA | MIXED_CONTEXT | -1 | None | REJECT_FOR_PHASE7 |
| SYNUSDT | 24h | BLOCKED_DATA | MIXED_CONTEXT | -1 | None | REJECT_FOR_PHASE7 |
| LABUSDT | 1h | NO_SETUP | MIXED_CONTEXT | -2 | None | REJECT_FOR_PHASE7 |

## Blockers

`{'NOT_ELIGIBLE_SIGNAL_FACTORY_CANDIDATE': 294, 'MISSING_ATR_REFERENCE': 230, 'BLOCKED_DATA': 74, 'MISSING_ATR': 74, 'MISSING_CANDLES': 81, 'TIMEFRAME_NOT_READY': 81}`

## What To Do Next

If `HAS_CANDIDATES`, move only approved rows into a shadow forward-test tracker. If `NO_PHASE7_CANDIDATE_YET`, let data grow and rerun Signal Factory, Strategy Arena, and Phase 6.

## What Not To Do Yet

- Do not create live execution.
- Do not finalize TP/SL.
- Do not mutate old classifier, scanner, outcome tracker, collectors, or Strategy Arena formula.
