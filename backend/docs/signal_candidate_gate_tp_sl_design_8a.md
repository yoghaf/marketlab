# Signal Candidate Gate + TP/SL Feasibility Design - Phase 8A

Generated: 2026-06-30

Scope: design only. This document defines a read-only gate for deciding which existing candidate contexts are worth evaluating further, plus an initial method for TP/SL feasibility research. It does not change runtime code, scanner behavior, classifier rules, outcome logic, feature logic, or universe selection.

## 1. Executive Verdict

`MID_SHORT_CONTEXT_READONLY` should be the first priority for a future read-only signal-candidate gate because it has the strongest directional sample growth and the clearest descriptive behavior among directional contexts in the latest review.

`MID_LONG_CONTEXT_READONLY` should be secondary because it has usable but smaller sample depth, and its latest median behavior is noisier than earlier checkpoints.

`EARLY_LONG_CANDIDATE_READONLY` and `EARLY_SHORT_CANDIDATE_READONLY` should remain radar-only because sample sizes are still too small.

`SQUEEZE_RISK_CONTEXT_READONLY` and `TRAP_RISK_CONTEXT_READONLY` should remain risk-only. They are useful market context labels, but they should not be converted into directional candidates.

Phase 8A is not a runtime phase. It only prepares the decision framework for a later read-only validation phase.

## 2. Candidate Eligibility Matrix

| candidate_type | current role | eligibility for signal-candidate research | reason | allowed next handling |
| --- | --- | --- | --- | --- |
| `MID_SHORT_CONTEXT_READONLY` | directional context | Primary | strongest directional sample growth; 4h median remains negative; 1h behavior improved descriptively | first candidate for read-only gate feasibility |
| `MID_LONG_CONTEXT_READONLY` | directional context | Secondary | usable sample, but weaker and noisier latest median behavior | monitor and evaluate only after stronger filters |
| `EARLY_LONG_CANDIDATE_READONLY` | radar-only | Hold | small sample; behavior inconclusive | keep collecting outcomes |
| `EARLY_SHORT_CANDIDATE_READONLY` | radar-only | Hold | very small sample; behavior inconclusive | keep collecting outcomes |
| `SQUEEZE_RISK_CONTEXT_READONLY` | risk context | Not directional | risk/fade context; not a directional instruction | risk-only dashboard context |
| `TRAP_RISK_CONTEXT_READONLY` | risk context | Not directional | fragile/risk context; not a directional instruction | risk-only dashboard context |
| `NO_SIGNAL_CONTEXT` | baseline/control | Not eligible | control group only | baseline comparison |
| `DATA_BLOCKED` | blocked data state | Not eligible | upstream readiness failed | exclude from feasibility metrics |

## 3. Why MID_SHORT Is Priority One

Phase 6G showed `MID_SHORT_CONTEXT_READONLY` grew from `126` to `297` ready outcomes, the strongest growth among directional contexts.

Descriptive behavior from Phase 6G:

| metric | value |
| --- | ---: |
| ready sample count | 297 |
| median return 15m | 0.0322 |
| median return 30m | 0.0170 |
| median return 1h | -0.0159 |
| median return 4h | -0.4536 |
| median favorable 1h | 0.5656 |
| median adverse 1h | 0.5531 |
| median favorable 4h | 1.5068 |
| median adverse 4h | 0.9227 |

The most useful observation is not that the category is ready for action. It is that the sample size improved while the longer horizon median remained directionally consistent with bearish context. That makes `MID_SHORT_CONTEXT_READONLY` the best first candidate for a stricter read-only gate feasibility study.

## 4. Why MID_LONG Is Secondary / Noisy

Phase 6G showed `MID_LONG_CONTEXT_READONLY` grew from `73` to `110` ready outcomes. This is usable for observation but still modest.

Descriptive behavior from Phase 6G:

| metric | value |
| --- | ---: |
| ready sample count | 110 |
| median return 15m | -0.0631 |
| median return 30m | -0.0693 |
| median return 1h | -0.0059 |
| median return 4h | -0.3011 |
| median favorable 1h | 0.6251 |
| median adverse 1h | -0.5974 |
| median favorable 4h | 1.3566 |
| median adverse 4h | -1.2037 |

The category still shows upside excursion, but median returns weakened at 15m, 30m, and 1h versus the earlier baseline. It should stay secondary until additional gates can separate cleaner context from noisy context.

## 5. Why EARLY Is Held

Phase 6G sample sizes:

| candidate_type | ready sample count | decision |
| --- | ---: | --- |
| `EARLY_LONG_CANDIDATE_READONLY` | 35 | hold |
| `EARLY_SHORT_CANDIDATE_READONLY` | 19 | hold |

These counts are too small for feasibility design beyond monitoring. The categories can remain visible in the scanner as radar-only context, but they should not be included in the first signal-candidate gate.

Minimum before reconsideration:

- `EARLY_LONG_CANDIDATE_READONLY >= 100`.
- `EARLY_SHORT_CANDIDATE_READONLY >= 100`.
- no symbol concentration issue.
- stable behavior across at least two future checkpoints.

## 6. Why SQUEEZE/TRAP Are Not Directional Signal Candidates

`SQUEEZE_RISK_CONTEXT_READONLY` and `TRAP_RISK_CONTEXT_READONLY` are mixed/risk labels. They describe fragile market conditions and possible instability, not a clean direction.

Phase 6G interpretation:

| candidate_type | review status | 8A decision |
| --- | --- | --- |
| `SQUEEZE_RISK_CONTEXT_READONLY` | risk/fade context; large sample | keep risk-only |
| `TRAP_RISK_CONTEXT_READONLY` | fragile context; stronger sample but not directional | keep risk-only |

These categories may be useful as veto/risk modifiers in a later read-only gate, but not as standalone directional candidates.

## 7. Draft Signal-Candidate Gate

This gate is a future read-only filter. It does not create live instructions or execution logic.

### Gate Inputs

| input | source |
| --- | --- |
| candidate classification | `market_signal_candidates_readonly_15m` |
| 15m + 1h context join | `market_feature_context_15m_1h` |
| psychology labels | `market_psychology_labels_15m` |
| outcome history | `market_candidate_outcomes_15m` |
| active universe status | `marketlab_active_universe` |

### Gate V1 Rules

| gate | rule | failure handling |
| --- | --- | --- |
| active universe | symbol must be active | blocked from signal-candidate research output |
| candidate type | allow only `MID_SHORT_CONTEXT_READONLY` initially; optionally allow `MID_LONG_CONTEXT_READONLY` as secondary | other types stay scanner/risk/baseline only |
| classifier status | must not be blocked | blocked |
| context status | 15m+1h context must be usable | blocked |
| evidence presence | core evidence must be non-empty | blocked |
| outcome readiness | use only `OUTCOME_READY` rows for feasibility metrics | waiting/incomplete excluded from feasibility summary |
| sample size | candidate type should pass minimum sample threshold | marked insufficient sample |
| concentration | no single symbol should dominate sample | marked concentration warning |
| risk labels | squeeze/trap may be attached as caution metadata, not direction | caution only |

### Proposed Gate Status

| status | meaning |
| --- | --- |
| `GATE_RESEARCH_READY` | enough clean historical/read-only evidence for feasibility study |
| `GATE_MONITOR_ONLY` | visible in scanner, but not enough for feasibility study |
| `GATE_RISK_ONLY` | context is risk-only, not directional |
| `GATE_BLOCKED` | missing, stale, blocked, inactive, or invalid data |

## 8. Outcome Data Used For TP/SL Feasibility

Only already-computed read-only outcome fields should be used.

| data | purpose |
| --- | --- |
| `future_return_15m` | short horizon close-to-close movement |
| `future_return_30m` | early continuation check |
| `future_return_1h` | main near-term behavior check |
| `future_return_4h` | extended behavior check |
| `max_favorable_move_1h` | best favorable excursion inside 1h |
| `max_adverse_move_1h` | worst adverse excursion inside 1h |
| `max_favorable_move_4h` | best favorable excursion inside 4h |
| `max_adverse_move_4h` | worst adverse excursion inside 4h |
| `followthrough_status` | descriptive followthrough count |
| `invalidation_status` | descriptive invalidation count |

`OUTCOME_BLOCKED`, `OUTCOME_WAITING_DATA`, and `OUTCOME_INCOMPLETE` must not be included in feasibility metrics.

## 9. Draft TP/SL Feasibility Method

This method evaluates whether historical outcome movement distribution has enough separation to justify further read-only research. It does not produce final TP/SL levels.

### Step 1: Select Eligible Samples

For each candidate type:

1. Select only `OUTCOME_READY`.
2. Exclude `DATA_BLOCKED`.
3. Exclude inactive universe rows.
4. Require evidence JSON not empty.
5. Require no future-context violation.

### Step 2: Compute Distribution Summary

For each eligible candidate type:

| metric family | calculation |
| --- | --- |
| returns | median and quartiles for 15m, 30m, 1h, 4h returns |
| favorable movement | median and quartiles for 1h and 4h favorable excursion |
| adverse movement | median and quartiles for 1h and 4h adverse excursion |
| followthrough | descriptive count by status |
| invalidation | descriptive count by status |

### Step 3: Feasibility Criteria

A candidate type is feasible for further read-only testing only if:

- sample size passes threshold.
- favorable excursion distribution is meaningfully larger than adverse excursion distribution.
- behavior is stable across checkpoints.
- no single symbol dominates the sample.
- outcome waiting/incomplete rows are not masking missing data quality.
- risk-only labels are not being converted into direction.

### Step 4: Feasibility Output

Use descriptive feasibility labels only:

| label | meaning |
| --- | --- |
| `FEASIBILITY_STUDY_READY` | enough data for deeper read-only threshold study |
| `FEASIBILITY_MONITOR_MORE` | promising but needs more forward samples |
| `FEASIBILITY_NOISY` | movement distribution is not clean |
| `FEASIBILITY_BLOCKED` | data quality or sample issue blocks study |

## 10. Output Schema Draft For Future Read-Only Signal Candidate

Possible future table or API payload. No migration is created in Phase 8A.

| field | description |
| --- | --- |
| `symbol` | active universe symbol |
| `window_open_time` | source 15m candidate window open |
| `window_close_time` | source 15m candidate window close |
| `source_candidate_type` | source read-only candidate type |
| `source_candidate_direction` | source context direction |
| `gate_status` | `GATE_RESEARCH_READY`, `GATE_MONITOR_ONLY`, `GATE_RISK_ONLY`, `GATE_BLOCKED` |
| `gate_reason` | concise reason for the gate status |
| `sample_size_type` | outcome sample count for candidate type |
| `sample_size_symbol` | outcome sample count for symbol/type |
| `concentration_warning` | concentration warning if applicable |
| `feasibility_status` | feasibility label from Section 9 |
| `feasibility_reason` | concise feasibility explanation |
| `median_return_1h` | read-only distribution metric |
| `median_return_4h` | read-only distribution metric |
| `median_favorable_1h` | read-only distribution metric |
| `median_adverse_1h` | read-only distribution metric |
| `median_favorable_4h` | read-only distribution metric |
| `median_adverse_4h` | read-only distribution metric |
| `followthrough_count` | descriptive count |
| `invalidation_count` | descriptive count |
| `risk_context_flags` | attached squeeze/trap/risk labels as caution metadata |
| `not_live_signal` | always true |
| `not_execution_instruction` | always true |
| `created_at` | UTC timestamp |
| `updated_at` | UTC timestamp |

## 11. Guardrails

- Phase 8A is design only.
- Do not change scanner logic.
- Do not change classifier rules.
- Do not change outcome calculation.
- Do not change feature/context logic.
- Do not change universe selection.
- Do not create runtime code.
- Do not create migrations.
- Do not create final TP/SL levels.
- Do not create execution logic.
- Do not create strategy logic.
- Do not make an edge claim.
- Keep all future output read-only and clearly marked as not a live signal.
- Risk-only categories must stay risk-only.
- Early categories must stay radar-only until sample size is materially larger.

## 12. Next Phase 8B

Recommended Phase 8B: implement a read-only feasibility report, not runtime signal output.

Phase 8B should:

1. Read from `market_candidate_outcomes_15m`.
2. Focus first on `MID_SHORT_CONTEXT_READONLY`.
3. Include `MID_LONG_CONTEXT_READONLY` as secondary comparison.
4. Keep early categories and risk categories out of directional feasibility.
5. Compute distribution tables only.
6. Add concentration warnings.
7. Add sample-size warnings.
8. Produce a document or API summary marked read-only.
9. Avoid runtime scanner promotion until feasibility is stable across more checkpoints.

Suggested Phase 8B pass condition:

- `MID_SHORT_CONTEXT_READONLY` has enough `OUTCOME_READY` samples for a distribution study.
- feasibility output contains no live instruction.
- risk-only and early categories remain frozen.
- no rule, classifier, scanner, outcome, feature, or context logic is changed.
