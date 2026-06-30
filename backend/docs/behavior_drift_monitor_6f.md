# MarketLab Phase 6F: Read-only Behavior Drift Monitoring

Review timestamp: 2026-06-30 02:46 UTC  
Baseline: Phase 6E `candidate_behavior_review_6e.md`  
Current source: production VPS SQLite DB and `/api/outcomes/15m/summary`  
Scope: read-only drift comparison on `OUTCOME_READY` rows.

This document compares behavior metrics across checkpoints. It does not change rules, does not evaluate execution, and does not promote any candidate type into an action.

## 1. Executive Verdict

The current checkpoint matches the Phase 6E baseline exactly. No material behavior drift is visible yet because no additional ready sample window has landed between the 6E review and this 6F snapshot.

Main candidate groups are marked `STABLE` for this checkpoint because sample size, medians, type concentration, and symbol concentration are unchanged. Early candidate groups remain `INCONCLUSIVE` because their sample sizes are still small.

Recommended action: continue collecting forward samples and run the next drift checkpoint after at least several new closed 15m windows have become `OUTCOME_READY`.

## 2. Comparison Table

| metric | Phase 6E value | current value | delta | interpretation |
|---|---:|---:|---:|---|
| OUTCOME_READY total | 1942 | 1942 | 0 | STABLE; no new ready window since 6E |
| OUTCOME_WAITING_DATA | 1102 | 1102 | 0 | STABLE |
| OUTCOME_INCOMPLETE | 17 | 17 | 0 | STABLE; incomplete rows remain safely persisted |
| OUTCOME_BLOCKED | 1823 | 1823 | 0 | STABLE |
| reviewed ready rows | 1942 | 1942 | 0 | STABLE |
| latest ready window close | 2026-06-29 22:45 UTC | 2026-06-29 22:45 UTC | 0 windows | STABLE |
| duplicate rows | 0 | 0 | 0 | STABLE |
| future context violations | 0 | 0 | 0 | STABLE |

## 3. Sample Size Drift

| candidate_type | Phase 6E n | current n | delta | stability flag |
|---|---:|---:|---:|---|
| NO_SIGNAL_CONTEXT | 1121 | 1121 | 0 | STABLE |
| SQUEEZE_RISK_CONTEXT_READONLY | 438 | 438 | 0 | STABLE |
| MID_LONG_CONTEXT_READONLY | 73 | 73 | 0 | STABLE |
| MID_SHORT_CONTEXT_READONLY | 126 | 126 | 0 | STABLE |
| TRAP_RISK_CONTEXT_READONLY | 155 | 155 | 0 | STABLE |
| EARLY_LONG_CANDIDATE_READONLY | 18 | 18 | 0 | INCONCLUSIVE |
| EARLY_SHORT_CANDIDATE_READONLY | 11 | 11 | 0 | INCONCLUSIVE |

## 4. Median Return Drift

Values are medians in percent. Deltas are current minus Phase 6E.

| candidate_type | ret_15m 6E | ret_15m current | delta | ret_30m 6E | ret_30m current | delta | ret_1h 6E | ret_1h current | delta | ret_4h 6E | ret_4h current | delta | flag |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| NO_SIGNAL_CONTEXT | -0.0283 | -0.0283 | 0.0000 | -0.0462 | -0.0462 | 0.0000 | -0.0267 | -0.0267 | 0.0000 | -0.4591 | -0.4591 | 0.0000 | STABLE |
| SQUEEZE_RISK_CONTEXT_READONLY | -0.0490 | -0.0490 | 0.0000 | -0.0562 | -0.0562 | 0.0000 | -0.0115 | -0.0115 | 0.0000 | -0.5962 | -0.5962 | 0.0000 | STABLE |
| MID_LONG_CONTEXT_READONLY | 0.0000 | 0.0000 | 0.0000 | -0.0150 | -0.0150 | 0.0000 | 0.0979 | 0.0979 | 0.0000 | -0.3212 | -0.3212 | 0.0000 | STABLE |
| MID_SHORT_CONTEXT_READONLY | 0.0727 | 0.0727 | 0.0000 | 0.1374 | 0.1374 | 0.0000 | 0.0781 | 0.0781 | 0.0000 | -0.7106 | -0.7106 | 0.0000 | STABLE |
| TRAP_RISK_CONTEXT_READONLY | -0.0499 | -0.0499 | 0.0000 | -0.0556 | -0.0556 | 0.0000 | -0.0231 | -0.0231 | 0.0000 | -0.7264 | -0.7264 | 0.0000 | STABLE |
| EARLY_LONG_CANDIDATE_READONLY | 0.0248 | 0.0248 | 0.0000 | 0.0422 | 0.0422 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | -0.2120 | -0.2120 | 0.0000 | INCONCLUSIVE |
| EARLY_SHORT_CANDIDATE_READONLY | -0.0528 | -0.0528 | 0.0000 | -0.1583 | -0.1583 | 0.0000 | -0.4182 | -0.4182 | 0.0000 | -1.1907 | -1.1907 | 0.0000 | INCONCLUSIVE |

## 5. Range Drift

Values are medians in percent.

| candidate_type | max_up_1h 6E | current | delta | max_down_1h 6E | current | delta | max_up_4h 6E | current | delta | max_down_4h 6E | current | delta | flag |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| NO_SIGNAL_CONTEXT | 0.7075 | 0.7075 | 0.0000 | -0.7282 | -0.7282 | 0.0000 | 1.5498 | 1.5498 | 0.0000 | -1.7134 | -1.7134 | 0.0000 | STABLE |
| SQUEEZE_RISK_CONTEXT_READONLY | 0.6717 | 0.6717 | 0.0000 | -0.6317 | -0.6317 | 0.0000 | 1.2128 | 1.2128 | 0.0000 | -1.6996 | -1.6996 | 0.0000 | STABLE |
| MID_LONG_CONTEXT_READONLY | 0.7424 | 0.7424 | 0.0000 | -0.5034 | -0.5034 | 0.0000 | 1.3612 | 1.3612 | 0.0000 | -1.0844 | -1.0844 | 0.0000 | STABLE |
| MID_SHORT_CONTEXT_READONLY | 0.6780 | 0.6780 | 0.0000 | -0.5429 | -0.5429 | 0.0000 | 0.8692 | 0.8692 | 0.0000 | -1.6154 | -1.6154 | 0.0000 | STABLE |
| TRAP_RISK_CONTEXT_READONLY | 0.4308 | 0.4308 | 0.0000 | -0.4961 | -0.4961 | 0.0000 | 0.4819 | 0.4819 | 0.0000 | -1.6152 | -1.6152 | 0.0000 | STABLE |
| EARLY_LONG_CANDIDATE_READONLY | 0.2942 | 0.2942 | 0.0000 | -0.2576 | -0.2576 | 0.0000 | 0.3553 | 0.3553 | 0.0000 | -0.5309 | -0.5309 | 0.0000 | INCONCLUSIVE |
| EARLY_SHORT_CANDIDATE_READONLY | 0.1074 | 0.1074 | 0.0000 | -0.7938 | -0.7938 | 0.0000 | 0.1299 | 0.1299 | 0.0000 | -1.6777 | -1.6777 | 0.0000 | INCONCLUSIVE |

## 6. Directional Favorable/Adverse Drift

Directional favorable/adverse fields are only meaningful for `BULLISH_CONTEXT` and `BEARISH_CONTEXT`. Mixed risk contexts are intentionally not directional.

| candidate_type | fav_1h 6E | current | delta | adv_1h 6E | current | delta | fav_4h 6E | current | delta | adv_4h 6E | current | delta | flag |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| MID_LONG_CONTEXT_READONLY | 0.7424 | 0.7424 | 0.0000 | -0.5034 | -0.5034 | 0.0000 | 1.3612 | 1.3612 | 0.0000 | -1.0844 | -1.0844 | 0.0000 | STABLE |
| MID_SHORT_CONTEXT_READONLY | 0.5429 | 0.5429 | 0.0000 | 0.6780 | 0.6780 | 0.0000 | 1.6154 | 1.6154 | 0.0000 | 0.8692 | 0.8692 | 0.0000 | STABLE |
| EARLY_LONG_CANDIDATE_READONLY | 0.2942 | 0.2942 | 0.0000 | -0.2576 | -0.2576 | 0.0000 | 0.3553 | 0.3553 | 0.0000 | -0.5309 | -0.5309 | 0.0000 | INCONCLUSIVE |
| EARLY_SHORT_CANDIDATE_READONLY | 0.7938 | 0.7938 | 0.0000 | 0.1074 | 0.1074 | 0.0000 | 1.6777 | 1.6777 | 0.0000 | 0.1299 | 0.1299 | 0.0000 | INCONCLUSIVE |

## 7. Type Concentration Drift

| candidate_type | Phase 6E share | current share | delta | flag |
|---|---:|---:|---:|---|
| NO_SIGNAL_CONTEXT | 57.72% | 57.72% | 0.00 pp | STABLE |
| SQUEEZE_RISK_CONTEXT_READONLY | 22.55% | 22.55% | 0.00 pp | STABLE |
| MID_LONG_CONTEXT_READONLY | 3.76% | 3.76% | 0.00 pp | STABLE |
| MID_SHORT_CONTEXT_READONLY | 6.49% | 6.49% | 0.00 pp | STABLE |
| TRAP_RISK_CONTEXT_READONLY | 7.98% | 7.98% | 0.00 pp | STABLE |
| EARLY_LONG_CANDIDATE_READONLY | 0.93% | 0.93% | 0.00 pp | INCONCLUSIVE |
| EARLY_SHORT_CANDIDATE_READONLY | 0.57% | 0.57% | 0.00 pp | INCONCLUSIVE |

Type concentration remains dominated by the baseline/control bucket. This is unchanged from Phase 6E.

## 8. Symbol Concentration Drift

| candidate_type | Phase 6E top symbol share | current top symbol share | delta | flag |
|---|---:|---:|---:|---|
| NO_SIGNAL_CONTEXT | 2.23% | 2.23% | 0.00 pp | STABLE |
| SQUEEZE_RISK_CONTEXT_READONLY | 2.97% | 2.97% | 0.00 pp | STABLE |
| MID_LONG_CONTEXT_READONLY | 5.48% | 5.48% | 0.00 pp | STABLE |
| MID_SHORT_CONTEXT_READONLY | 4.76% | 4.76% | 0.00 pp | STABLE |
| TRAP_RISK_CONTEXT_READONLY | 9.68% | 9.68% | 0.00 pp | STABLE |
| EARLY_LONG_CANDIDATE_READONLY | 16.67% | 16.67% | 0.00 pp | INCONCLUSIVE |
| EARLY_SHORT_CANDIDATE_READONLY | 18.18% | 18.18% | 0.00 pp | INCONCLUSIVE |

Symbol concentration is stable. Early candidate concentration remains high because the sample base is too small.

## 9. Candidate-specific Drift

### NO_SIGNAL_CONTEXT

Status: `STABLE`.

No sample or median movement changed from Phase 6E. It remains the control group and should continue to be used as the baseline for later comparisons.

### SQUEEZE_RISK_CONTEXT_READONLY

Status: `STABLE`.

Sample size, medians, and concentration are unchanged. This remains a risk/context bucket and should not be interpreted as directional.

### MID_LONG_CONTEXT_READONLY

Status: `STABLE`.

The 1h median return and favorable/adverse movement are unchanged. Sample size remains modest at `n=73`, so the prior Phase 6E interpretation still applies: descriptive behavior is interesting but not conclusive.

### MID_SHORT_CONTEXT_READONLY

Status: `STABLE`.

The 4h weakness and early noisy movement observed in Phase 6E are unchanged. Sample size is `n=126`, enough for monitoring but not enough for rule changes.

### TRAP_RISK_CONTEXT_READONLY

Status: `STABLE`.

No drift is visible. It remains a mixed risk/context bucket with lower median upside than the control group, but it should not be turned into directional action.

### EARLY_LONG_CANDIDATE_READONLY

Status: `INCONCLUSIVE`.

Sample size remains `n=18`, so no drift conclusion should be drawn.

### EARLY_SHORT_CANDIDATE_READONLY

Status: `INCONCLUSIVE`.

Sample size remains `n=11`, so no drift conclusion should be drawn.

## 10. Stability Flags

| group | stability flag | reason |
|---|---|---|
| baseline/control | STABLE | unchanged sample size and medians |
| squeeze context | STABLE | unchanged sample size and medians |
| MID_LONG context | STABLE | unchanged sample size and medians, modest n |
| MID_SHORT context | STABLE | unchanged sample size and medians, modest n |
| trap context | STABLE | unchanged sample size and medians |
| early candidates | INCONCLUSIVE | n remains too small |
| overall behavior | STABLE | no measurable drift since Phase 6E |

## 11. What Remains Frozen

- Candidate classification rules.
- Psychology/context label rules.
- Feature math.
- Outcome calculation.
- Status policy.
- Any promotion path from context monitoring into action logic.

## 12. What Needs More Samples

- Early candidate buckets need far more observations before drift can be evaluated.
- MID_LONG and MID_SHORT should be monitored over multiple later checkpoints before any refinement discussion.
- Squeeze and trap should remain separate context buckets and should continue accumulating observations.
- The baseline/control bucket should remain the comparison anchor.

## 13. Recommended Next Checkpoint Timing

Run the next drift checkpoint after at least 300 to 500 additional `OUTCOME_READY` rows, or after several hours of stable collector operation. A checkpoint taken too soon will mostly reproduce Phase 6E, as this report did.

## Validation

- `/api/outcomes/15m/summary`: HTTP 200.
- Duplicate feature/context/candidate/outcome rows: 0.
- Future context violations: 0.
- Outcome status at current checkpoint: `OUTCOME_READY=1942`, `OUTCOME_WAITING_DATA=1102`, `OUTCOME_INCOMPLETE=17`, `OUTCOME_BLOCKED=1823`.
- Runtime code changed: no.
- Migration added: no.
- Rule changes: no.
- Temporary CSV/debug files created: no.
