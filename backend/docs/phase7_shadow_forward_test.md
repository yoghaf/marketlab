# Phase 7 Shadow Forward-Test

## Executive Verdict

Phase 7 is a read-only shadow forward-test layer. It only tracks candidates that already passed Phase 6 approval and converts them into deterministic paper events for forward outcome monitoring.

If Phase 6 has no approved candidate, Phase 7 remains valid with `WAITING_FOR_APPROVED_CANDIDATE`. That state means the infrastructure is ready, but there is nothing to track yet.

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

An event can be created only when the candidate satisfies all gates:

- `phase7_verdict = PHASE7_READY`
- `total_score >= 7`
- `edge_vs_baseline > 0.10R`
- Strategy Arena verdict is `MONITOR_MORE` or `PROMISING_FOR_FORWARD_TEST`
- Entry reference candle exists
- ATR reference exists and is closed before or at the candidate observation time

Candidates that fail those gates are not promoted by Phase 7.

## Shadow Event Model

Each event has deterministic identity from:

- symbol
- timeframe
- setup family
- direction
- observation timestamp

The event includes:

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
