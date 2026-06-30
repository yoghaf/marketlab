# MarketLab Phase 6E: Candidate Behavior Review v2

Review timestamp: 2026-06-30 02:46 UTC  
Source: production VPS SQLite DB and `/api/outcomes/15m/summary`  
Scope: read-only observation of `OUTCOME_READY` rows only.

This document is descriptive monitoring. It is not a backtest, not an execution design, and not a promotion of any candidate type into an action rule.

## 1. Executive Verdict

Production forward samples continued to grow after the outcome JSON serialization fix. The reviewed set contains 1,942 `OUTCOME_READY` rows across the tracked candidate types. The control group remains dominant, while the main context groups now have enough rows for a more useful descriptive review than Phase 6C.

Current behavior is still mixed. `MID_SHORT_CONTEXT_READONLY` and `MID_LONG_CONTEXT_READONLY` show stronger directional movement ranges than the control group, but both also show frequent opposite-side excursions. `SQUEEZE_RISK_CONTEXT_READONLY` and `TRAP_RISK_CONTEXT_READONLY` remain risk/context labels and should not be interpreted directionally.

Rules should remain frozen. The next phase should continue sample growth and add a stricter read-only validation report, not change candidate generation.

## 2. Sample Size Table

| candidate_type | OUTCOME_READY n | share of reviewed ready rows | sample assessment |
|---|---:|---:|---|
| NO_SIGNAL_CONTEXT | 1121 | 57.72% | strong baseline/control |
| SQUEEZE_RISK_CONTEXT_READONLY | 438 | 22.55% | sufficient for descriptive monitoring |
| MID_LONG_CONTEXT_READONLY | 73 | 3.76% | usable but still modest |
| MID_SHORT_CONTEXT_READONLY | 126 | 6.49% | usable but still modest |
| TRAP_RISK_CONTEXT_READONLY | 155 | 7.98% | usable as risk/context sample |
| EARLY_LONG_CANDIDATE_READONLY | 18 | 0.93% | too small, inconclusive |
| EARLY_SHORT_CANDIDATE_READONLY | 11 | 0.57% | too small, inconclusive |

Latest ready candidate window: `2026-06-29 22:30:00` to `2026-06-29 22:45:00` UTC.

## 3. Candidate Behavior Table

Values are medians in percent. `fav_1h` and `adv_1h` are only directional for BULLISH/BEARISH contexts. Mixed contexts intentionally leave directional favorable/adverse blank.

| candidate_type | n | ret_15m | ret_30m | ret_1h | ret_4h | max_up_1h | max_down_1h | max_up_4h | max_down_4h | fav_1h | adv_1h |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| NO_SIGNAL_CONTEXT | 1121 | -0.0283 | -0.0462 | -0.0267 | -0.4591 | 0.7075 | -0.7282 | 1.5498 | -1.7134 | n/a | n/a |
| SQUEEZE_RISK_CONTEXT_READONLY | 438 | -0.0490 | -0.0562 | -0.0115 | -0.5962 | 0.6717 | -0.6317 | 1.2128 | -1.6996 | n/a | n/a |
| MID_LONG_CONTEXT_READONLY | 73 | 0.0000 | -0.0150 | 0.0979 | -0.3212 | 0.7424 | -0.5034 | 1.3612 | -1.0844 | 0.7424 | -0.5034 |
| MID_SHORT_CONTEXT_READONLY | 126 | 0.0727 | 0.1374 | 0.0781 | -0.7106 | 0.6780 | -0.5429 | 0.8692 | -1.6154 | 0.5429 | 0.6780 |
| TRAP_RISK_CONTEXT_READONLY | 155 | -0.0499 | -0.0556 | -0.0231 | -0.7264 | 0.4308 | -0.4961 | 0.4819 | -1.6152 | n/a | n/a |
| EARLY_LONG_CANDIDATE_READONLY | 18 | 0.0248 | 0.0422 | 0.0000 | -0.2120 | 0.2942 | -0.2576 | 0.3553 | -0.5309 | 0.2942 | -0.2576 |
| EARLY_SHORT_CANDIDATE_READONLY | 11 | -0.0528 | -0.1583 | -0.4182 | -1.1907 | 0.1074 | -0.7938 | 0.1299 | -1.6777 | 0.7938 | 0.1074 |

Directional status counts:

| candidate_type | followthrough | no_followthrough | invalidated | not_invalidated |
|---|---:|---:|---:|---:|
| MID_LONG_CONTEXT_READONLY | 71 | 2 | 70 | 3 |
| MID_SHORT_CONTEXT_READONLY | 122 | 4 | 125 | 1 |
| EARLY_LONG_CANDIDATE_READONLY | 18 | 0 | 17 | 1 |
| EARLY_SHORT_CANDIDATE_READONLY | 11 | 0 | 11 | 0 |

The followthrough/invalidation columns are descriptive only. Because the thresholds are currently zero, frequent `FOLLOWTHROUGH` and `INVALIDATED` together mostly indicate two-sided movement inside the forward window.

## 4. Baseline Comparison

`NO_SIGNAL_CONTEXT` is the control group. Its median returns are slightly negative across all horizons, with a 4h median of `-0.4591%`. It also has broad two-sided movement: median `max_up_1h=0.7075%` and `max_down_1h=-0.7282%`.

Compared with this baseline:

- `SQUEEZE_RISK_CONTEXT_READONLY` is similar at 15m/30m/1h and slightly weaker at 4h.
- `MID_LONG_CONTEXT_READONLY` has a better median 1h return than baseline and smaller median 4h downside than baseline, but the sample is still modest.
- `MID_SHORT_CONTEXT_READONLY` has stronger downward 4h behavior than baseline, but the 15m/30m/1h medians are positive, showing noisy early movement.
- `TRAP_RISK_CONTEXT_READONLY` has weaker 4h behavior than baseline and lower median upside, but remains a mixed risk/context label.

No candidate type should be promoted from this comparison alone.

## 5. Squeeze Review

`SQUEEZE_RISK_CONTEXT_READONLY` has `n=438`, which is enough for descriptive monitoring. Median returns are close to the baseline at short horizons and slightly weaker over 4h:

- 15m median: `-0.0490%`
- 30m median: `-0.0562%`
- 1h median: `-0.0115%`
- 4h median: `-0.5962%`

The label behaves like a volatility/risk context rather than a clean directional context. Median two-sided range remains substantial with `max_up_1h=0.6717%` and `max_down_1h=-0.6317%`.

Interpretation: keep as read-only risk context. It needs more forward validation and should not be converted into directional action logic.

## 6. MID_LONG Review

`MID_LONG_CONTEXT_READONLY` has `n=73`. The 1h median return is positive at `0.0979%`, while 4h median return is negative at `-0.3212%`. Median favorable movement over 1h is `0.7424%`, while median adverse movement is `-0.5034%`.

This is more constructive than the baseline at the 1h horizon, but the invalidation count is high (`70 of 73`). That means the forward windows often include meaningful opposite-side movement even when favorable movement appears.

Interpretation: descriptively interesting, not conclusive. Keep frozen and collect more forward samples before any refinement discussion.

## 7. MID_SHORT Review

`MID_SHORT_CONTEXT_READONLY` has `n=126`. The 4h median return is `-0.7106%`, weaker than the baseline 4h median of `-0.4591%`. Median favorable 4h movement is `1.6154%`. However, 15m/30m/1h median returns are positive, and median adverse 1h movement is `0.6780%`.

This suggests the context can be directionally noisy early, with more visible weakness later in the observed window. The high invalidation count (`125 of 126`) confirms the forward path is not clean.

Interpretation: stronger descriptive behavior than earlier phases, but still needs more forward validation. Keep rules frozen.

## 8. TRAP Review

`TRAP_RISK_CONTEXT_READONLY` has `n=155`. It shows weaker median returns than baseline at 15m, 30m, 1h, and 4h. Median 4h return is `-0.7264%`, and median max upside is much lower than the baseline at both 1h and 4h.

Because this is a mixed risk/context label, it should not be mapped to a directional action. Its current value is contextual: it appears to identify more fragile forward behavior than the control group, but that is not enough to create a rule.

Interpretation: keep read-only. Continue measuring as a risk context.

## 9. Early Candidate Warning

`EARLY_LONG_CANDIDATE_READONLY` has `n=18`; `EARLY_SHORT_CANDIDATE_READONLY` has `n=11`. These are too small for stable interpretation.

The early short sample looks directionally cleaner in this checkpoint, but `n=11` is not enough. The early long sample is also too small and shows frequent opposite-side movement.

Interpretation: both early labels are inconclusive. Do not refine them yet.

## 10. Concentration Warning

Type concentration:

- `NO_SIGNAL_CONTEXT`: 57.72% of reviewed ready rows.
- `SQUEEZE_RISK_CONTEXT_READONLY`: 22.55%.
- All other reviewed types are below 8% each.

Symbol concentration is acceptable for most types:

- `NO_SIGNAL_CONTEXT` top symbol share: 2.23%.
- `SQUEEZE_RISK_CONTEXT_READONLY` top symbol share: 2.97%.
- `MID_LONG_CONTEXT_READONLY` top symbol share: 5.48%.
- `MID_SHORT_CONTEXT_READONLY` top symbol share: 4.76%.
- `TRAP_RISK_CONTEXT_READONLY` top symbol share: 9.68%.
- Early labels have higher top-symbol shares because sample sizes are very small.

Concentration is not a blocker for the main groups, but the dataset is still dominated by baseline/control rows.

## 11. What Should Remain Frozen

- Candidate classification rules.
- Psychology/context label rules.
- Feature math and status policy.
- Outcome calculation logic.
- Thresholds used by the read-only tracker.
- Any promotion path from context label to action.

No runtime rule change is recommended from this review.

## 12. What Needs More Data

- Early long and early short labels need substantially more ready samples.
- MID_LONG needs more samples to confirm whether the 1h behavior persists.
- MID_SHORT needs more samples to separate early noise from later weakness.
- Squeeze and trap contexts should continue as separate risk/context buckets.
- Baseline/control should keep growing to support stable comparisons.

## 13. Recommended Next Phase

Proceed to continued forward sample monitoring with frozen rules. A useful next phase would be a read-only stability report that tracks these same medians across multiple checkpoints and reports drift by candidate type, symbol concentration, and blocked/waiting/incomplete movement.

Do not start execution design or strategy design from this review.

## Validation

- `/api/outcomes/15m/summary`: HTTP 200.
- Duplicate feature/context/candidate/outcome rows: 0.
- Future context violations: 0.
- Outcome status at review time: `OUTCOME_READY=1942`, `OUTCOME_WAITING_DATA=1102`, `OUTCOME_INCOMPLETE=17`, `OUTCOME_BLOCKED=1823`.
- Runtime code changed: no.
- Migration added: no.
- Temporary CSV/debug files created: no.
