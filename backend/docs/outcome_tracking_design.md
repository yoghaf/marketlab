# MarketLab Outcome Tracking Design

Phase: 5C  
Scope: read-only outcome tracking design for candidate classifications.  
Status: design only. No database migration, runner, backtest, execution, entry logic, TP/SL, position sizing, leverage, or strategy is introduced in this phase.

## Purpose

Outcome tracking will measure what happened after a read-only candidate classification window. It is a data quality and research support layer, not a trading system.

The source classification table is expected to be:

- `market_signal_candidates_readonly_15m`

The future outcome table can be designed later as:

- `market_candidate_outcomes_15m`

No migration is created in Phase 5C.

## Candidate Types In Scope

| candidate_type | outcome handling |
| --- | --- |
| `EARLY_LONG_CANDIDATE_READONLY` | bullish-context outcome measurement |
| `MID_LONG_CONTEXT_READONLY` | bullish-context outcome measurement |
| `EARLY_SHORT_CANDIDATE_READONLY` | bearish-context outcome measurement |
| `MID_SHORT_CONTEXT_READONLY` | bearish-context outcome measurement |
| `SQUEEZE_RISK_CONTEXT_READONLY` | mixed/risk outcome measurement, not directional entry measurement |
| `TRAP_RISK_CONTEXT_READONLY` | mixed/risk outcome measurement, not directional entry measurement |
| `NO_SIGNAL_CONTEXT` | baseline/control outcome measurement |
| `DATA_BLOCKED` | not evaluated as a signal outcome |

## Outcome Horizons

Outcome windows are measured from the candidate window close time.

| horizon | measurement window |
| --- | --- |
| `15m` | candidate close to candidate close + 15 minutes |
| `30m` | candidate close to candidate close + 30 minutes |
| `1h` | candidate close to candidate close + 1 hour |
| `4h` | candidate close to candidate close + 4 hours |

Only closed futures OHLCV aggregate windows should be used. If the required future candles are not closed or not available, the outcome row must remain `OUTCOME_WAITING_DATA` or `OUTCOME_INCOMPLETE`.

## Direction Handling

Outcome tracking uses the classifier's context direction as metadata only.

| candidate_direction | handling |
| --- | --- |
| `BULLISH_CONTEXT` | upward movement is favorable; downward movement is adverse |
| `BEARISH_CONTEXT` | downward movement is favorable; upward movement is adverse |
| `MIXED_CONTEXT` | measured separately without converting to bullish or bearish entry direction |
| `BLOCKED_CONTEXT` | outcome is blocked and not evaluated as signal behavior |

Direction handling must not introduce order instructions, entry timing, or trade recommendations.

## Metrics

| metric | description |
| --- | --- |
| `future_return_15m` | percent return from candidate close price to the future 15m horizon close |
| `future_return_30m` | percent return from candidate close price to the future 30m horizon close |
| `future_return_1h` | percent return from candidate close price to the future 1h horizon close |
| `future_return_4h` | percent return from candidate close price to the future 4h horizon close |
| `max_favorable_move_1h` | maximum favorable percent movement inside the 1h horizon |
| `max_adverse_move_1h` | maximum adverse percent movement inside the 1h horizon |
| `max_favorable_move_4h` | maximum favorable percent movement inside the 4h horizon |
| `max_adverse_move_4h` | maximum adverse percent movement inside the 4h horizon |
| `followthrough_status` | categorical outcome describing whether movement followed the candidate context |
| `invalidation_status` | categorical outcome describing whether movement contradicted the candidate context |

Returns should be calculated from futures OHLCV only unless a later phase explicitly designs spot-relative outcome metrics.

## Metric Direction Rules

For `BULLISH_CONTEXT`:

- favorable movement uses future highs and positive closes relative to candidate close.
- adverse movement uses future lows and negative closes relative to candidate close.

For `BEARISH_CONTEXT`:

- favorable movement uses future lows and negative closes relative to candidate close.
- adverse movement uses future highs and positive closes relative to candidate close.

For `MIXED_CONTEXT`:

- `SQUEEZE_RISK_CONTEXT_READONLY` and `TRAP_RISK_CONTEXT_READONLY` are measured as risk-context outcomes.
- They must not be converted into long or short outcome scoring.
- Favorable/adverse directional labels should be null or replaced by neutral risk-context fields in a later implementation.

For `BLOCKED_CONTEXT`:

- `DATA_BLOCKED` rows should not produce directional outcome metrics.
- The outcome row can exist for audit completeness, but status must be `OUTCOME_BLOCKED`.

For `NO_SIGNAL_CONTEXT`:

- measured as a baseline/control group.
- It must not be treated as a missed entry or implicit trade.

## Outcome Status

| status | meaning |
| --- | --- |
| `OUTCOME_READY` | all required closed future candles exist for the requested horizons |
| `OUTCOME_WAITING_DATA` | future time has not elapsed or future candles are not closed yet |
| `OUTCOME_INCOMPLETE` | future time elapsed, but one or more required candles are missing |
| `OUTCOME_BLOCKED` | candidate is `DATA_BLOCKED`, missing source candidate, or has unusable blocked context |

Status is per candidate outcome row. A row may have partial horizon readiness in implementation, but the row-level status should remain conservative until all configured required metrics are valid.

## Proposed Future Table

This is a design sketch only. No migration is created in Phase 5C.

| column | purpose |
| --- | --- |
| `id` | primary key |
| `symbol` | candidate symbol |
| `candidate_window_open_time` | source candidate 15m open time |
| `candidate_window_close_time` | source candidate 15m close time |
| `candidate_type` | copied from read-only candidate |
| `candidate_direction` | copied from read-only candidate |
| `classifier_status` | copied from read-only candidate |
| `outcome_status` | `OUTCOME_READY`, `OUTCOME_WAITING_DATA`, `OUTCOME_INCOMPLETE`, or `OUTCOME_BLOCKED` |
| `candidate_close_price` | futures close at candidate window |
| `future_return_15m` | 15m forward return |
| `future_return_30m` | 30m forward return |
| `future_return_1h` | 1h forward return |
| `future_return_4h` | 4h forward return |
| `max_favorable_move_1h` | max favorable move in first hour |
| `max_adverse_move_1h` | max adverse move in first hour |
| `max_favorable_move_4h` | max favorable move in first four hours |
| `max_adverse_move_4h` | max adverse move in first four hours |
| `followthrough_status` | categorical followthrough status |
| `invalidation_status` | categorical invalidation status |
| `source_candle_count_1h` | number of closed 15m candles used in 1h horizon |
| `source_candle_count_4h` | number of closed 15m candles used in 4h horizon |
| `missing_window_list` | JSON list of missing future windows |
| `evidence` | JSON audit payload with source candidate and candle references |
| `created_at` | UTC creation timestamp |
| `updated_at` | UTC update timestamp |

Suggested unique constraint:

- `unique(symbol, candidate_window_open_time)`

## Followthrough and Invalidation

Initial categorical values can be:

| field | values |
| --- | --- |
| `followthrough_status` | `FOLLOWTHROUGH`, `NO_FOLLOWTHROUGH`, `MIXED_CONTEXT_ONLY`, `NOT_APPLICABLE` |
| `invalidation_status` | `INVALIDATED`, `NOT_INVALIDATED`, `MIXED_CONTEXT_ONLY`, `NOT_APPLICABLE` |

These statuses must be descriptive only. They are not entry, exit, risk, or allocation instructions.

## Guardrails

- Outcome tracking is not a backtest.
- No entry rule is created.
- No live signal is created.
- No alerting is created.
- No TP/SL is created.
- No position sizing is created.
- No leverage is created.
- No execution or order routing is created.
- No strategy logic is created.
- Candidate output remains read-only and must retain `not_entry_signal = true`.
- Metrics must not be summarized as performance final statistics in this phase.
- Do not use terms like winrate, profit factor, expectancy, or PnL in this design phase.

## Implementation Preconditions For A Later Phase

Before implementing outcome tracking:

1. Confirm which aggregate table is authoritative for forward prices, likely `futures_klines_15m`.
2. Confirm closed-window handling for forward horizons.
3. Decide whether all four horizons are required for `OUTCOME_READY` or whether horizon-level status fields are needed.
4. Add tests for direction handling:
   - bullish favorable uses upward movement.
   - bearish favorable uses downward movement.
   - mixed contexts do not become directional entries.
   - blocked contexts stay blocked.
5. Ensure API copy clearly states read-only and non-entry semantics.
