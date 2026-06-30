# Candidate Behavior Review v3 - Phase 6G

Generated: 2026-06-30

Scope: read-only behavior review from latest production outcome samples. This document compares the current checkpoint against the Phase 6E baseline and does not promote any rule change.

## 1. Executive verdict

MarketLab has enough new forward samples for a checkpoint review: `OUTCOME_READY` increased from `1942` in Phase 6E to `3450`, a delta of `+1508`.

The behavior remains descriptive and mixed. `MID_SHORT_CONTEXT_READONLY` has the clearest sample growth among directional contexts and now shows more supportive 1h behavior while retaining negative 4h median movement, though the 4h magnitude softened from the Phase 6E baseline. `MID_LONG_CONTEXT_READONLY` gained samples but weakened on median 15m/30m/1h returns, while still showing upside excursion. `SQUEEZE_RISK_CONTEXT_READONLY` remains a risk context with fade-like behavior, not a directional promotion. `TRAP_RISK_CONTEXT_READONLY` remains fragile but less negative than Phase 6E on 4h median return.

Early candidate categories are still too small for promotion. The safest next step is to keep rules frozen, continue sample growth, and add monitoring of drift, concentration, and readiness health.

## 2. Production health snapshot

| metric | current |
| --- | ---: |
| OUTCOME_READY | 3450 |
| OUTCOME_WAITING_DATA | 1104 |
| OUTCOME_INCOMPLETE | 68 |
| OUTCOME_BLOCKED | 1885 |
| Latest ready window close UTC | 2026-06-30 04:00:00 |
| Duplicate feature/context/candidate/outcome rows | 0 |
| Future-context violations | 0 |
| Empty evidence rows | 0 |
| Outcome summary API | HTTP 200 |
| Research loop | Stable at checkpoint |

## 3. Sample growth vs Phase 6E baseline

| metric | Phase 6E | Current | Delta |
| --- | ---: | ---: | ---: |
| OUTCOME_READY | 1942 | 3450 | +1508 |
| OUTCOME_WAITING_DATA | 1102 | 1104 | +2 |
| OUTCOME_INCOMPLETE | 17 | 68 | +51 |
| OUTCOME_BLOCKED | 1823 | 1885 | +62 |
| Latest ready close UTC | 2026-06-29 22:45 | 2026-06-30 04:00 | +5h 15m |

## 4. Candidate sample table

| candidate_type | Phase 6E n | Current n | Delta n | Current share | Sample flag |
| --- | ---: | ---: | ---: | ---: | --- |
| NO_SIGNAL_CONTEXT | 1121 | 1966 | +845 | 56.99% | Large baseline |
| SQUEEZE_RISK_CONTEXT_READONLY | 438 | 727 | +289 | 21.07% | Large enough for drift review |
| MID_LONG_CONTEXT_READONLY | 73 | 110 | +37 | 3.19% | Usable but still modest |
| MID_SHORT_CONTEXT_READONLY | 126 | 297 | +171 | 8.61% | Stronger sample depth |
| TRAP_RISK_CONTEXT_READONLY | 155 | 296 | +141 | 8.58% | Stronger sample depth |
| EARLY_LONG_CANDIDATE_READONLY | 18 | 35 | +17 | 1.01% | Small, inconclusive |
| EARLY_SHORT_CANDIDATE_READONLY | 11 | 19 | +8 | 0.55% | Very small, inconclusive |

Type concentration remains led by `NO_SIGNAL_CONTEXT` at `56.99%`. This is lower than Phase 6E `57.72%` but still dominates the reviewed population.

## 5. Candidate behavior table

All movement values are medians in percent. `max_up` and `max_down` are non-directional excursion fields. Favorable/adverse fields are used only for directional contexts.

| candidate_type | n | ret_15m | ret_30m | ret_1h | ret_4h | max_up_1h | max_down_1h | max_up_4h | max_down_4h | status flag |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| NO_SIGNAL_CONTEXT | 1966 | -0.0310 | -0.0600 | -0.0864 | -0.4092 | 0.6631 | -0.8043 | 1.4101 | -1.7019 | STABLE baseline |
| SQUEEZE_RISK_CONTEXT_READONLY | 727 | -0.0604 | -0.0716 | -0.1050 | -0.5915 | 0.5911 | -0.7483 | 1.0833 | -1.7066 | DRIFTING at 1h, stable at 4h |
| MID_LONG_CONTEXT_READONLY | 110 | -0.0631 | -0.0693 | -0.0059 | -0.3011 | 0.6251 | -0.5974 | 1.3566 | -1.2037 | WEAKENED / noisy |
| MID_SHORT_CONTEXT_READONLY | 297 | 0.0322 | 0.0170 | -0.0159 | -0.4536 | 0.5531 | -0.5656 | 0.9227 | -1.5068 | IMPROVED at 1h, still weak at 4h |
| TRAP_RISK_CONTEXT_READONLY | 296 | -0.0309 | -0.0549 | -0.0125 | -0.4003 | 0.4172 | -0.4942 | 0.5545 | -1.1815 | STABLE risk context |
| EARLY_LONG_CANDIDATE_READONLY | 35 | -0.0540 | -0.0050 | 0.0000 | -0.1706 | 0.3149 | -0.4045 | 0.3770 | -0.8125 | INCONCLUSIVE |
| EARLY_SHORT_CANDIDATE_READONLY | 19 | -0.0528 | -0.2388 | -0.1592 | -1.1907 | 0.1299 | -0.8363 | 0.3353 | -1.7491 | INCONCLUSIVE |

Directional context detail:

| candidate_type | direction | favorable_1h | adverse_1h | favorable_4h | adverse_4h | followthrough | invalidation |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| MID_LONG_CONTEXT_READONLY | BULLISH_CONTEXT | 0.6251 | -0.5974 | 1.3566 | -1.2037 | 107 / 110 | 106 / 110 |
| MID_SHORT_CONTEXT_READONLY | BEARISH_CONTEXT | 0.5656 | 0.5531 | 1.5068 | 0.9227 | 291 / 297 | 290 / 297 |
| EARLY_LONG_CANDIDATE_READONLY | BULLISH_CONTEXT | 0.3149 | -0.4045 | 0.3770 | -0.8125 | 35 / 35 | 34 / 35 |
| EARLY_SHORT_CANDIDATE_READONLY | BEARISH_CONTEXT | 0.8363 | 0.1299 | 1.7491 | 0.3353 | 19 / 19 | 19 / 19 |

## 6. Drift comparison vs Phase 6E

| candidate_type | n delta | ret_1h delta | ret_4h delta | range drift | interpretation |
| --- | ---: | ---: | ---: | --- | --- |
| NO_SIGNAL_CONTEXT | +845 | -0.0597 | +0.0499 | 1h downside slightly wider, 4h broadly similar | Baseline remains noisy and control-like |
| SQUEEZE_RISK_CONTEXT_READONLY | +289 | -0.0935 | +0.0047 | 1h fade stronger, 4h nearly unchanged | Risk context remains valid as descriptive label |
| MID_LONG_CONTEXT_READONLY | +37 | -0.1038 | +0.0201 | Upside excursion remains, median return weakened | Promising only as context, not promotable |
| MID_SHORT_CONTEXT_READONLY | +171 | -0.0940 | +0.2570 | 1h improved for bearish context, 4h weakness softened | Stronger descriptive evidence, still needs more samples |
| TRAP_RISK_CONTEXT_READONLY | +141 | +0.0106 | +0.3261 | Less negative at 4h, low upside remains | Fragile context remains, no promotion |
| EARLY_LONG_CANDIDATE_READONLY | +17 | 0.0000 | +0.0414 | Adverse side widened | Inconclusive |
| EARLY_SHORT_CANDIDATE_READONLY | +8 | +0.2590 | 0.0000 | Still negative median, too small | Inconclusive |

## 7. Baseline/control review

`NO_SIGNAL_CONTEXT` remains the largest group with `1966` ready outcomes and `56.99%` share. Its median path is mildly negative across 15m, 30m, 1h, and 4h, while both upside and downside excursions remain wide.

Compared with Phase 6E, the 1h median moved more negative, but the 4h median became slightly less negative. This supports using it as a control group rather than a promoted candidate group.

Top symbol concentration is low at `2.19%`, led by `TACUSDT`, `SYNUSDT`, `BASUSDT`, `UBUSDT`, and `VELVETUSDT`.

## 8. SQUEEZE review

`SQUEEZE_RISK_CONTEXT_READONLY` grew from `438` to `727` ready outcomes. Median returns remain negative:

| horizon | Phase 6E | Current | Delta |
| --- | ---: | ---: | ---: |
| 15m | -0.0490 | -0.0604 | -0.0114 |
| 30m | -0.0562 | -0.0716 | -0.0154 |
| 1h | -0.0115 | -0.1050 | -0.0935 |
| 4h | -0.5962 | -0.5915 | +0.0047 |

The 1h behavior weakened while the 4h behavior is nearly unchanged. This remains best interpreted as risk/fade context. It should not be treated as a directional promotion.

Top symbol concentration is low at `2.75%`, led by `XMRUSDT`, `LABUSDT`, `ZECUSDT`, `GWEIUSDT`, and `ONDOUSDT`.

## 9. MID_LONG review

`MID_LONG_CONTEXT_READONLY` grew from `73` to `110` ready outcomes. The new sample weakens the earlier constructive 1h observation:

| horizon | Phase 6E | Current | Delta |
| --- | ---: | ---: | ---: |
| 15m | 0.0000 | -0.0631 | -0.0631 |
| 30m | -0.0150 | -0.0693 | -0.0543 |
| 1h | 0.0979 | -0.0059 | -0.1038 |
| 4h | -0.3212 | -0.3011 | +0.0201 |

The category still shows median upside excursion of `0.6251` over 1h and `1.3566` over 4h, but downside excursion also widened. This should remain a monitored context only. It is not clean enough for rule promotion.

Top symbol concentration is `4.55%`, led by `BASUSDT`, `PAXGUSDT`, `BTCUSDT`, `LTCUSDT`, and `PUMPUSDT`.

## 10. MID_SHORT review

`MID_SHORT_CONTEXT_READONLY` grew from `126` to `297` ready outcomes, the strongest growth among directional contexts.

| horizon | Phase 6E | Current | Delta |
| --- | ---: | ---: | ---: |
| 15m | 0.0727 | 0.0322 | -0.0405 |
| 30m | 0.1374 | 0.0170 | -0.1204 |
| 1h | 0.0781 | -0.0159 | -0.0940 |
| 4h | -0.7106 | -0.4536 | +0.2570 |

The 1h median shifted from positive to slightly negative, which is stronger descriptive evidence for the bearish context than Phase 6E. The 4h median remains negative, but the magnitude is less severe than the baseline. Favorable 4h movement remains larger than adverse 4h movement in the directional calculation.

This category is worth monitoring closely, but it remains a read-only candidate behavior group. It should not be promoted into a rule.

Top symbol concentration is `5.05%`, led by `SKYAIUSDT`, `WLDUSDT`, `TRXUSDT`, `[non_ascii_symbol]`, and `AVAXUSDT`.

## 11. TRAP review

`TRAP_RISK_CONTEXT_READONLY` grew from `155` to `296` ready outcomes.

| horizon | Phase 6E | Current | Delta |
| --- | ---: | ---: | ---: |
| 15m | -0.0499 | -0.0309 | +0.0190 |
| 30m | -0.0556 | -0.0549 | +0.0007 |
| 1h | -0.0231 | -0.0125 | +0.0106 |
| 4h | -0.7264 | -0.4003 | +0.3261 |

The category remains fragile but less negative than Phase 6E, especially at 4h. Upside excursion remains modest relative to broad market movement, and downside excursion still exists. It remains a risk context and should stay read-only.

Top symbol concentration is `6.42%`, led by `ESPORTSUSDT`, `PAXGUSDT`, `ETHUSDT`, `DOGEUSDT`, and `ADAUSDT`.

## 12. Early candidate warning

`EARLY_LONG_CANDIDATE_READONLY` has `35` ready outcomes. `EARLY_SHORT_CANDIDATE_READONLY` has `19` ready outcomes.

Both categories are still too small for strong interpretation. `EARLY_SHORT_CANDIDATE_READONLY` has a negative median path, but its sample is still very small. `EARLY_LONG_CANDIDATE_READONLY` has mixed behavior and widened adverse movement versus Phase 6E.

These categories should remain under sample-growth monitoring only.

## 13. Concentration warning

Type concentration is acceptable but still dominated by baseline:

| type | share |
| --- | ---: |
| NO_SIGNAL_CONTEXT | 56.99% |
| SQUEEZE_RISK_CONTEXT_READONLY | 21.07% |
| MID_SHORT_CONTEXT_READONLY | 8.61% |
| TRAP_RISK_CONTEXT_READONLY | 8.58% |
| MID_LONG_CONTEXT_READONLY | 3.19% |
| EARLY_LONG_CANDIDATE_READONLY | 1.01% |
| EARLY_SHORT_CANDIDATE_READONLY | 0.55% |

Symbol concentration is not currently a blocker. Highest reviewed top-symbol share is `10.53%` in `EARLY_SHORT_CANDIDATE_READONLY`, but that category has only `19` samples, so the concentration warning is mostly a small-sample warning.

## 14. What remains frozen

The following remain frozen:

- Classifier rules.
- Psychology label rules.
- Outcome calculation rules.
- Feature builder rules.
- Context join rules.
- Readiness thresholds.
- Candidate status policy.

No production rule should be promoted from this review.

## 15. What is now worth monitoring in scanner

The scanner should continue showing read-only diagnostics only:

- `OUTCOME_READY` count per candidate type.
- Delta versus prior checkpoint.
- 15m, 1h, and 4h median drift.
- Directional favorable/adverse movement for directional contexts only.
- Type concentration and top-symbol concentration.
- `OUTCOME_WAITING_DATA`, `OUTCOME_INCOMPLETE`, and `OUTCOME_BLOCKED` health.
- Future-context violation count.
- Empty evidence count.

`MID_SHORT_CONTEXT_READONLY` deserves the closest monitoring because sample size increased materially and 1h behavior moved in the expected descriptive direction. `MID_LONG_CONTEXT_READONLY` needs more samples because the latest checkpoint weakened the earlier 1h observation. `SQUEEZE_RISK_CONTEXT_READONLY` and `TRAP_RISK_CONTEXT_READONLY` should remain risk-context diagnostics.

## 16. Recommended next step

Continue forward sample growth until the next checkpoint reaches at least:

- `OUTCOME_READY >= 5000` overall.
- `MID_LONG_CONTEXT_READONLY >= 200`.
- `MID_SHORT_CONTEXT_READONLY >= 500`.
- `TRAP_RISK_CONTEXT_READONLY >= 500`.
- Early categories above `100` each before interpretation changes.

After that, run another behavior drift review with the same read-only constraints. No rule change is recommended from Phase 6G.
