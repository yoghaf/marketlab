# MarketLab Phase 6B - Read-only Outcome Summary

Generated from local DB after Phase 6A.2 refresh.

This is a read-only outcome summary for candidate behavior and forward movement. It is not a backtest and not trading performance. The current sample size is limited, so every table below is descriptive only.

## Scope

- Source rows: `market_candidate_outcomes_15m`
- Forward metric rows: `OUTCOME_READY` only
- Blocked rows: counted only as blocked count
- Mixed context: not forced into a directional bucket
- Spot/futures evidence: joined from `market_feature_context_15m_1h` when available

## Overall Counts

| status | count |
| --- | ---: |
| total outcome rows | 1245 |
| OUTCOME_READY | 150 |
| OUTCOME_BLOCKED | 1095 |
| OUTCOME_WAITING_DATA | 0 |
| OUTCOME_INCOMPLETE | 0 |

Integrity:

| check | value |
| --- | ---: |
| duplicate outcome rows | 0 |
| empty evidence rows | 0 |
| ready rows used for forward metrics | 150 |
| blocked rows used for directional metrics | 0 |

## Candidate Type Counts

Counts below use `OUTCOME_READY` rows only.

| candidate_type | count | sample note |
| --- | ---: | --- |
| NO_SIGNAL_CONTEXT | 76 | ok |
| SQUEEZE_RISK_CONTEXT_READONLY | 50 | ok |
| MID_LONG_CONTEXT_READONLY | 9 | sample size limited |
| MID_SHORT_CONTEXT_READONLY | 8 | sample size limited |
| TRAP_RISK_CONTEXT_READONLY | 5 | sample size limited |
| EARLY_LONG_CANDIDATE_READONLY | 2 | sample size limited |
| EARLY_SHORT_CANDIDATE_READONLY | 0 | sample size limited |

## Direction Counts

Counts below use `OUTCOME_READY` rows only.

| direction | count | sample note |
| --- | ---: | --- |
| MIXED_CONTEXT | 131 | ok |
| BULLISH_CONTEXT | 11 | ok |
| BEARISH_CONTEXT | 8 | sample size limited |

## Median Forward Movement By Candidate Type

Values are percentage movement medians from closed futures 15m candles. These are descriptive forward movement statistics, not trading performance.

| candidate_type | n | return_15m | return_30m | return_1h | return_4h | max_up_1h | max_down_1h | max_up_4h | max_down_4h |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| NO_SIGNAL_CONTEXT | 76 | 0.3683 | 0.2472 | -0.1301 | -0.2484 | 0.9459 | -0.7625 | 1.3958 | -2.2868 |
| SQUEEZE_RISK_CONTEXT_READONLY | 50 | 0.2542 | -0.2127 | -0.3028 | -0.1034 | 0.7547 | -0.5951 | 0.9275 | -1.9386 |
| MID_LONG_CONTEXT_READONLY | 9 | 0.4715 | -0.2892 | -0.2020 | -0.9094 | 0.9592 | -0.8293 | 1.9810 | -2.3639 |
| MID_SHORT_CONTEXT_READONLY | 8 | 0.1182 | -0.0497 | -0.5649 | -3.4089 | 1.4826 | -1.3001 | 1.7462 | -4.5346 |
| TRAP_RISK_CONTEXT_READONLY | 5 | 0.4620 | 0.6755 | 0.5166 | 0.4074 | 1.0303 | -0.5590 | 3.5282 | -1.6527 |
| EARLY_LONG_CANDIDATE_READONLY | 2 | 0.3836 | 0.4772 | -0.1140 | -0.7814 | 0.8290 | -0.7415 | 0.8290 | -2.1733 |

## Directional Movement Medians

Only `BULLISH_CONTEXT` and `BEARISH_CONTEXT` rows are included here. `MIXED_CONTEXT` rows are excluded from favorable/adverse directional metrics.

| direction | n | favorable_1h | adverse_1h | favorable_4h | adverse_4h | sample note |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| BULLISH_CONTEXT | 11 | 0.9592 | -0.8293 | 1.2788 | -2.3639 | ok |
| BEARISH_CONTEXT | 8 | 1.3001 | 1.4826 | 4.5346 | 1.7462 | sample size limited |

## Followthrough And Invalidation Counts

Counts below use `OUTCOME_READY` rows only.

| followthrough_status | count |
| --- | ---: |
| MIXED_CONTEXT_ONLY | 131 |
| FOLLOWTHROUGH | 19 |

| invalidation_status | count |
| --- | ---: |
| MIXED_CONTEXT_ONLY | 131 |
| INVALIDATED | 18 |
| NOT_INVALIDATED | 1 |

## Concentration Checks

| check | value |
| --- | ---: |
| max symbol share | 1.33% |
| top candidate type share | 50.67% |
| max symbol concentration warning | false |
| top candidate type concentration warning | true |
| overall sample size warning | true |

Top symbols by ready candidate count:

| symbol | count |
| --- | ---: |
| 1000PEPEUSDT | 2 |
| AAVEUSDT | 2 |
| ACTUSDT | 2 |
| ADAUSDT | 2 |
| AGLDUSDT | 2 |
| ALLOUSDT | 2 |
| ARXUSDT | 2 |
| AVAXUSDT | 2 |
| BASEDUSDT | 2 |
| BASUSDT | 2 |

The sample is not symbol-concentrated, but it is candidate-type concentrated because `NO_SIGNAL_CONTEXT` is 50.67% of ready rows.

## Spot/Futures Evidence Breakdown

Counts below use `OUTCOME_READY` rows only.

| evidence_status | count |
| --- | ---: |
| SPOT_MISSING | 48 |
| FUTURES_LED | 40 |
| SPOT_UNKNOWN | 33 |
| WEAK_SPOT_SUPPORT | 27 |
| SPOT_SUPPORTING | 2 |

## Guardrails

- Forward metrics use `OUTCOME_READY` rows only.
- `OUTCOME_BLOCKED` rows are not included in directional metrics.
- `MIXED_CONTEXT` rows are not forced into bullish or bearish directional handling.
- This report is descriptive candidate behavior only.
- No order instruction, allocation instruction, or automated action is defined here.
