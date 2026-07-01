# Multi-Timeframe Signal Factory v1 Report

Read-only anomaly/signal-candidate factory for MarketLab multi-timeframe context. This report is not a live signal, not an entry instruction, and not an execution system.

- generated_at: `2026-07-01T02:05:44.484744+00:00`
- feature_rows: `300`
- candidate_rows: `300`
- conflict_count: `0`
- missing_data_count: `225`

## Feature Count Per Timeframe

| timeframe | count |
|---|---:|
| 15m | 75 |
| 1h | 75 |
| 24h | 75 |
| 4h | 75 |

## Candidate Count Per Setup

| setup_type | count |
|---|---:|
| BLOCKED_DATA | 225 |
| EARLY_LONG | 9 |
| EARLY_SHORT | 32 |
| NO_SETUP | 34 |

## Guardrails

- Read-only artifact output only.
- `not_live_signal=true` on every candidate.
- `not_execution_instruction=true` on every candidate.
- No order, TP/SL, leverage, position sizing, or execution logic.
