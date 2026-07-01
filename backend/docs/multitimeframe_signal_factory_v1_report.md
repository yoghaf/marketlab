# Multi-Timeframe Signal Factory v1 Report

Read-only anomaly/signal-candidate factory for MarketLab multi-timeframe context. This report is not a live signal, not an entry instruction, and not an execution system.

- generated_at: `2026-07-01T02:07:47.571329+00:00`
- feature_rows: `300`
- candidate_rows: `300`
- conflict_count: `12`
- missing_data_count: `155`

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
| BLOCKED_DATA | 155 |
| EARLY_LONG | 33 |
| EARLY_SHORT | 15 |
| MID_LONG | 17 |
| MID_SHORT | 9 |
| NO_SETUP | 68 |
| SQUEEZE | 3 |

## Guardrails

- Read-only artifact output only.
- `not_live_signal=true` on every candidate.
- `not_execution_instruction=true` on every candidate.
- No order, TP/SL, leverage, position sizing, or execution logic.
