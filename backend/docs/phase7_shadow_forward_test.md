# Phase 7 Shadow Forward-Test

## Executive Verdict

Phase 7 is a read-only dual-lane shadow forward-test layer. It tracks strict Phase 6 approved candidates and separate near-miss lab candidates for forward-test learning.

If Phase 6 has no approved candidate but near-miss candidates pass the lab gate, Phase 7 runs as `ACTIVE_LAB_SHADOW`. If both lanes are empty, Phase 7 remains valid with `WAITING_FOR_CANDIDATE`.

## Scope

Phase 7 creates:

- `forward_test_status.json`
- `forward_test_events.json`
- `forward_test_results.json`
- `forward_test_summary.json`
- API endpoints under `/api/phase7/*`
- Frontend page `/phase7-forward-test`

It does not modify Signal Factory, Phase 6 scoring, Strategy Arena formulas, classifier rules, feature builders, or outcome logic.

## Candidate Eligibility

`APPROVED_SHADOW` can be created only when the candidate satisfies all strict gates:

- `phase7_verdict = PHASE7_READY`
- `total_score >= 7`
- `edge_vs_baseline > 0.10R`
- Strategy Arena verdict is `MONITOR_MORE` or `PROMISING_FOR_FORWARD_TEST`
- Entry reference candle exists
- ATR reference exists and is closed before or at the candidate observation time

`LAB_SHADOW` can be created only when the candidate satisfies the lab gate:

- `candidate_status = SIGNAL_CANDIDATE`
- timeframe is `15m`
- `atr_reference_status = AVAILABLE`
- arena mapping exists
- baseline mapping exists
- not conflicted
- `edge_vs_baseline > 0.05R`
- arena verdict is not `REJECT`

LAB_SHADOW is not an approved signal and must not be used for live action.

## Shadow Event Model

Each event has deterministic identity from:

- symbol
- timeframe
- setup family
- direction
- observation timestamp

The event includes:

- `lane`
- `shadow_type`
- `entry_reference_price`
- `atr_reference_value`
- `atr_mult`
- `rr_target`
- `stop_reference_price`
- `take_profit_reference_price`
- `max_horizon_bars`
- `expiry_time`
- `is_live_signal=false`
- `is_execution=false`

The stop and target levels are shadow simulation references only.

Deduplication uses symbol, timeframe, setup, direction, observation timestamp, and lane.

## Outcome Evaluation

Forward outcomes use closed futures 15m candles after the candidate observation timestamp.

Statuses:

- `WAITING_OUTCOME`
- `TP_HIT`
- `SL_HIT`
- `BOTH_HIT_SAME_CANDLE`
- `EXPIRED`
- `UNKNOWN_FORWARD_DATA`
- `CANNOT_EVALUATE`

If both reference target and stop are touched in the same 15m candle, the result is marked ambiguous as `BOTH_HIT_SAME_CANDLE`.

## Guardrails

Phase 7 is not a live signal system.

It does not create:

- live orders
- execution instructions
- final TP/SL recommendations
- position sizing
- leverage
- strategy automation

The frontend only reads artifact files through API endpoints. It does not trigger pipeline reruns.

All calculations and artifacts remain UTC. User-facing frontend pages show local time with timezone suffix, while UTC remains available in technical details.

## Operations

Run locally or on VPS:

```bash
python backend/scripts/run_phase7_forward_test.py
```

Production deployment should run the script once after pulling code, then restart backend/frontend so `/api/phase7/*` and `/phase7-forward-test` expose the latest artifacts.

## Expected Waiting State

When there are no Phase 6 approved candidates, the correct result is:

- mode: `WAITING_FOR_APPROVED_CANDIDATE`
- approved candidates: `0`
- active events: `0`
- completed events: `0`

This is a PASS state for infrastructure readiness.
