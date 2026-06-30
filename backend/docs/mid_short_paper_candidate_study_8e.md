# MID_SHORT Paper Candidate Study - Phase 8E

Generated: 2026-06-30

Scope: read-only paper candidate definition for `MID_SHORT_CONTEXT_READONLY` with futures-led context present, using the Phase 8C median 4h threshold reference. This document does not change runtime code, scanner behavior, classifier rules, outcome logic, feature/context logic, or database schema.

## 1. Executive Verdict

`MID_SHORT_CONTEXT_READONLY` + futures-led context is the first MarketLab candidate subset suitable for a read-only paper-candidate study.

The subset improves the Phase 8C median-band noise profile:

- eligible sample: `233`
- favorable hit: `113`
- adverse breach: `96`
- both-hit: `41`
- neither-hit: `65`
- adverse share: `41.20%`
- both-hit share: `17.60%`
- favorable/adverse ratio: `1.18`
- top-symbol concentration: `4.72%`

This is still not safe for live use. It is only clean enough to track as a paper candidate with strict warnings and no final TP/SL.

## 2. Paper Candidate Definition

A row qualifies for the Phase 8E paper candidate study only if all required filters pass:

| requirement | rule |
| --- | --- |
| candidate type | `MID_SHORT_CONTEXT_READONLY` |
| direction | `BEARISH_CONTEXT` |
| futures-led context | present |
| universe status | active universe row exists |
| evidence | candidate evidence exists and is not empty |
| outcome status for metrics | `OUTCOME_READY` only |
| excluded metric rows | `OUTCOME_BLOCKED`, `OUTCOME_INCOMPLETE`, `OUTCOME_WAITING_DATA` |
| threshold reference | Phase 8C median 4h band |

Futures-led context is considered present when either:

- `spot_support_status_15m = FUTURES_LED`
- supporting psychology labels include `FUTURES_LED_MOVE`

## 3. Required Filters

| filter | required value | purpose |
| --- | --- | --- |
| `candidate_type` | `MID_SHORT_CONTEXT_READONLY` | primary studied context only |
| futures-led context | true | best simple filter from Phase 8D |
| active universe | true | avoid stale/inactive symbols |
| evidence | non-empty | avoid un-auditable paper rows |
| outcome metrics | `OUTCOME_READY` | keep study metrics closed and complete |
| blocked/incomplete/waiting outcomes | excluded from metrics | avoid false readiness |

Rows that do not pass these filters can still exist in the database and scanner, but they are not part of the paper-candidate metric population.

## 4. Median 4h Threshold Reference

The Phase 8E paper candidate uses the Phase 8C median 4h band as reference:

| threshold | value |
| --- | ---: |
| favorable threshold 4h | 1.6076% |
| adverse threshold 4h | 0.9022% |

For bearish context:

- favorable means downside movement reaches or exceeds the favorable threshold.
- adverse means upside movement reaches or exceeds the adverse threshold.

These values are reference thresholds only. They are not final TP/SL levels.

## 5. Paper Candidate Metrics

Baseline from Phase 8D for `MID_SHORT_CONTEXT_READONLY` + futures-led context:

| metric | value |
| --- | ---: |
| eligible sample | 233 |
| favorable hit | 113 |
| adverse breach | 96 |
| both-hit | 41 |
| neither-hit | 65 |
| adverse share | 41.20% |
| both-hit share | 17.60% |
| favorable/adverse ratio | 1.18 |
| top-symbol concentration | 4.72% |

Interpretation:

- adverse and both-hit rates are lower than the unfiltered MID_SHORT median band.
- sample size remains usable for continued paper tracking.
- concentration is acceptable.
- favorable/adverse separation is positive but not large enough for operational use.

## 6. Failure / Rejection Reasons

| rejection reason | meaning |
| --- | --- |
| `NOT_MID_SHORT` | source candidate type is not `MID_SHORT_CONTEXT_READONLY` |
| `NOT_FUTURES_LED` | futures-led context is absent |
| `INACTIVE_OR_MISSING_UNIVERSE` | symbol is not currently active or active rank is missing |
| `BLOCKED_CONTEXT` | source classifier/context is blocked |
| `MISSING_EVIDENCE` | evidence payload is empty or unavailable |
| `OUTCOME_NOT_READY` | outcome is waiting, incomplete, or blocked |
| `RISK_ONLY_CATEGORY` | source type is squeeze/trap or other risk-only category |
| `RADAR_ONLY_CATEGORY` | source type is early long/short candidate |
| `BASELINE_ONLY_CATEGORY` | source type is `NO_SIGNAL_CONTEXT` |

Rejection reasons should be audit labels only. They should not produce runtime action.

## 7. Paper Output Schema Draft

This is a future read-only payload or table sketch. No migration is created in Phase 8E.

| field | description |
| --- | --- |
| `symbol` | candidate symbol |
| `candidate_type` | expected `MID_SHORT_CONTEXT_READONLY` |
| `direction` | expected `BEARISH_CONTEXT` |
| `window_open_time` | source candidate window open |
| `window_close_time` | source candidate window close |
| `paper_candidate_status` | `PAPER_CANDIDATE_INCLUDED`, `PAPER_CANDIDATE_REJECTED`, or `PAPER_CANDIDATE_WAITING_OUTCOME` |
| `paper_reason` | concise inclusion/rejection reason |
| `paper_warning` | read-only warning text |
| `threshold_reference` | JSON reference to median 4h favorable/adverse thresholds |
| `futures_led_context` | boolean |
| `active_universe` | boolean |
| `universe_rank` | active universe rank if available |
| `outcome_status` | copied outcome status |
| `favorable_hit_4h` | boolean for paper metric, nullable if outcome not ready |
| `adverse_breach_4h` | boolean for paper metric, nullable if outcome not ready |
| `both_hit_4h` | boolean for paper metric, nullable if outcome not ready |
| `neither_hit_4h` | boolean for paper metric, nullable if outcome not ready |
| `not_live_signal` | always true |
| `not_execution_instruction` | always true |
| `created_at` | UTC timestamp |
| `updated_at` | UTC timestamp |

Example threshold reference:

```json
{
  "source_phase": "8C",
  "band": "median_4h",
  "favorable_threshold_pct": "1.6076",
  "adverse_threshold_pct": "0.9022",
  "direction_context": "BEARISH_CONTEXT",
  "final_tp_sl": false
}
```

## 8. What Remains Unsafe

The Phase 8E paper candidate remains unsafe for operational use because:

- no final TP/SL exists.
- no live entry exists.
- no execution path exists.
- no strategy is defined.
- both-hit count remains material at `41`.
- adverse breach remains material at `96`.
- favorable/adverse ratio is only `1.18`.
- the baseline comparison from Phase 8C showed hit-count separation is not strong enough by itself.

The candidate can be observed, not acted on.

## 9. Next Step Recommendation

Recommended Phase 8F: implement a read-only paper-candidate report or offline evaluator for this exact subset only.

Phase 8F should:

1. Include only `MID_SHORT_CONTEXT_READONLY` rows with futures-led context.
2. Mark all rows as paper/read-only.
3. Use the Phase 8C median 4h threshold reference.
4. Track favorable hit, adverse breach, both-hit, neither-hit.
5. Track symbol concentration and active-universe rank.
6. Exclude blocked, waiting, and incomplete outcomes from metric summaries.
7. Emit rejection reasons for excluded rows.
8. Avoid changing scanner, classifier, feature, context, or outcome logic.

Phase 8F should not create final TP/SL, live signals, execution logic, or strategy behavior.

## 10. Guardrails

- This is read-only.
- This is a paper candidate definition, not a live signal.
- Runtime code is not changed in Phase 8E.
- Database schema is not changed.
- Scanner behavior is not changed.
- Classifier logic is not changed.
- Outcome logic is not changed.
- Feature/context logic is not changed.
- No final TP/SL level is selected.
- No execution logic is introduced.
- No strategy logic is introduced.
- No edge claim is made.
