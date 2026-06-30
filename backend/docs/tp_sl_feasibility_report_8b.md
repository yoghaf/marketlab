# TP/SL Feasibility Report - Phase 8B

Generated: 2026-06-30

Scope: read-only feasibility report for `MID_SHORT_CONTEXT_READONLY`, with `MID_LONG_CONTEXT_READONLY` as secondary comparison and `NO_SIGNAL_CONTEXT` as baseline/control. This report does not change runtime code, scanner behavior, classifier rules, outcome logic, feature logic, or database schema.

Production source:

| item | value |
| --- | --- |
| DB | `/var/www/marketlab/data/marketlab.db` |
| total `OUTCOME_READY` | 4965 |
| latest candidate window close | 2026-06-30 13:15:00 UTC |
| latest outcome update | 2026-06-30 13:31:05 UTC |

## 1. Executive Verdict

`MID_SHORT_CONTEXT_READONLY` is suitable for a limited read-only threshold feasibility study. The category has `381` ready outcomes, broad symbol coverage, low top-symbol concentration, and a stronger 4h favorable/adverse excursion ratio than `MID_LONG_CONTEXT_READONLY`.

This is not a final TP/SL design. The close-to-close returns remain noisy, and `MID_SHORT_CONTEXT_READONLY` is only modestly different from the baseline on median 4h return. The useful part is the excursion profile: median 4h favorable movement is `1.6076%` versus median 4h adverse movement of `0.9022%`, a descriptive ratio of `1.78`.

`MID_LONG_CONTEXT_READONLY` remains noisy. It has `150` ready outcomes, but favorable/adverse ratios are below `1.0` at both 1h and 4h.

Early categories remain radar-only. Squeeze/trap categories remain risk-only and are excluded from directional feasibility.

## 2. Sample Size By Candidate Type

| candidate_type | OUTCOME_READY n | 8B handling |
| --- | ---: | --- |
| `NO_SIGNAL_CONTEXT` | 2893 | baseline/control |
| `SQUEEZE_RISK_CONTEXT_READONLY` | 999 | risk-only, excluded from directional feasibility |
| `TRAP_RISK_CONTEXT_READONLY` | 444 | risk-only, excluded from directional feasibility |
| `MID_SHORT_CONTEXT_READONLY` | 381 | primary feasibility candidate |
| `MID_LONG_CONTEXT_READONLY` | 150 | secondary comparison, noisy |
| `EARLY_LONG_CANDIDATE_READONLY` | 62 | radar-only, sample still small |
| `EARLY_SHORT_CANDIDATE_READONLY` | 36 | radar-only, sample still small |

Outcome status context:

| status | count |
| --- | ---: |
| `OUTCOME_READY` | 4965 |
| `OUTCOME_WAITING_DATA` | 1098 |
| `OUTCOME_INCOMPLETE` | 116 |
| `OUTCOME_BLOCKED` | 1967 |

Only `OUTCOME_READY` rows are included in this report's feasibility metrics.

## 3. Return Distribution

Values are percent. Each cell is `q1 / median / q3`.

| candidate_type | horizon | q1 | median | q3 |
| --- | --- | ---: | ---: | ---: |
| `NO_SIGNAL_CONTEXT` | 15m | -0.3645 | -0.0299 | 0.3110 |
| `NO_SIGNAL_CONTEXT` | 30m | -0.4872 | -0.0625 | 0.3940 |
| `NO_SIGNAL_CONTEXT` | 1h | -0.7035 | -0.0959 | 0.5767 |
| `NO_SIGNAL_CONTEXT` | 4h | -1.8557 | -0.5637 | 0.8715 |
| `MID_SHORT_CONTEXT_READONLY` | 15m | -0.3284 | 0.0243 | 0.3246 |
| `MID_SHORT_CONTEXT_READONLY` | 30m | -0.4396 | 0.0000 | 0.3797 |
| `MID_SHORT_CONTEXT_READONLY` | 1h | -0.5714 | -0.0476 | 0.4526 |
| `MID_SHORT_CONTEXT_READONLY` | 4h | -1.5622 | -0.5154 | 0.2914 |
| `MID_LONG_CONTEXT_READONLY` | 15m | -0.3711 | -0.0674 | 0.1842 |
| `MID_LONG_CONTEXT_READONLY` | 30m | -0.4288 | -0.0467 | 0.4365 |
| `MID_LONG_CONTEXT_READONLY` | 1h | -0.7098 | -0.0805 | 0.5767 |
| `MID_LONG_CONTEXT_READONLY` | 4h | -1.3357 | -0.4243 | 1.1661 |

Interpretation:

- `MID_SHORT_CONTEXT_READONLY` does not show a clean close-to-close separation versus baseline.
- The 4h median return for `MID_SHORT_CONTEXT_READONLY` is slightly less negative than `NO_SIGNAL_CONTEXT`, not materially stronger by itself.
- The main feasibility signal is in favorable/adverse excursion distribution, not close-to-close returns.
- `MID_LONG_CONTEXT_READONLY` remains noisy because median returns are negative across all horizons.

## 4. Favorable / Adverse Excursion Distribution

Values are percent. Each cell is `q1 / median / q3`.

| candidate_type | metric | q1 | median | q3 |
| --- | --- | ---: | ---: | ---: |
| `MID_SHORT_CONTEXT_READONLY` | `max_favorable_move_1h` | 0.2740 | 0.6138 | 1.4660 |
| `MID_SHORT_CONTEXT_READONLY` | `max_adverse_move_1h` | 0.2459 | 0.5117 | 1.2369 |
| `MID_SHORT_CONTEXT_READONLY` | `max_favorable_move_4h` | 0.7226 | 1.6076 | 3.1038 |
| `MID_SHORT_CONTEXT_READONLY` | `max_adverse_move_4h` | 0.3753 | 0.9022 | 2.5042 |
| `MID_LONG_CONTEXT_READONLY` | `max_favorable_move_1h` | 0.2351 | 0.5125 | 1.7486 |
| `MID_LONG_CONTEXT_READONLY` | `max_adverse_move_1h` | -1.5416 | -0.5872 | -0.2266 |
| `MID_LONG_CONTEXT_READONLY` | `max_favorable_move_4h` | 0.2704 | 1.0543 | 2.6809 |
| `MID_LONG_CONTEXT_READONLY` | `max_adverse_move_4h` | -2.9706 | -1.2331 | -0.6402 |

For mixed baseline categories, favorable/adverse directional fields are not applicable.

## 5. Favorable / Adverse Ratio

Ratios use absolute median adverse movement.

| candidate_type | ratio 1h | ratio 4h | interpretation |
| --- | ---: | ---: | --- |
| `MID_SHORT_CONTEXT_READONLY` | 1.20 | 1.78 | favorable excursion is larger than adverse, especially at 4h |
| `MID_LONG_CONTEXT_READONLY` | 0.87 | 0.86 | adverse excursion is larger than favorable |
| `NO_SIGNAL_CONTEXT` | n/a | n/a | mixed baseline, no directional favorable/adverse metric |

`MID_SHORT_CONTEXT_READONLY` is the only reviewed directional context with a materially better 4h favorable/adverse profile.

## 6. Followthrough / Invalidation Counts

| candidate_type | followthrough | no_followthrough | invalidated | not_invalidated |
| --- | ---: | ---: | ---: | ---: |
| `MID_SHORT_CONTEXT_READONLY` | 374 | 7 | 373 | 8 |
| `MID_LONG_CONTEXT_READONLY` | 144 | 6 | 146 | 4 |
| `NO_SIGNAL_CONTEXT` | mixed-context-only: 2893 | n/a | mixed-context-only: 2893 | n/a |

These counts are descriptive only. They confirm that the outcome tracker is populating directional categories, but they are not enough to define thresholds by themselves because both followthrough and invalidation can occur inside the same forward window.

## 7. Symbol Concentration

| candidate_type | distinct symbols | top symbol | top symbol count | top symbol share |
| --- | ---: | --- | ---: | ---: |
| `MID_SHORT_CONTEXT_READONLY` | 72 | `SKYAIUSDT` | 20 | 5.25% |
| `MID_LONG_CONTEXT_READONLY` | 61 | `LTCUSDT` | 7 | 4.67% |
| `NO_SIGNAL_CONTEXT` | 80 | `TACUSDT` | 59 | 2.04% |

Top `MID_SHORT_CONTEXT_READONLY` symbols:

| symbol | count | share |
| --- | ---: | ---: |
| `SKYAIUSDT` | 20 | 5.25% |
| `WLDUSDT` | 12 | 3.15% |
| `FILUSDT` | 11 | 2.89% |
| `WIFUSDT` | 10 | 2.62% |
| `ENAUSDT` | 9 | 2.36% |
| `TRXUSDT` | 9 | 2.36% |
| `HYPEUSDT` | 9 | 2.36% |
| `[non_ascii_symbol]` | 9 | 2.36% |
| `PENGUUSDT` | 9 | 2.36% |
| `UNIUSDT` | 9 | 2.36% |

Concentration is not a blocker for `MID_SHORT_CONTEXT_READONLY`. The top-symbol share is low enough for a read-only feasibility study.

## 8. MID_SHORT vs NO_SIGNAL Baseline

| metric | `MID_SHORT_CONTEXT_READONLY` | `NO_SIGNAL_CONTEXT` | read-only interpretation |
| --- | ---: | ---: | --- |
| sample count | 381 | 2893 | baseline is much larger |
| median return 15m | 0.0243 | -0.0299 | near flat, small difference |
| median return 30m | 0.0000 | -0.0625 | near flat, small difference |
| median return 1h | -0.0476 | -0.0959 | slightly less negative |
| median return 4h | -0.5154 | -0.5637 | slightly less negative |
| top symbol share | 5.25% | 2.04% | acceptable concentration |

Baseline comparison does not prove a strong close-to-close separation. The feasibility case for `MID_SHORT_CONTEXT_READONLY` comes from the 4h excursion profile, where favorable movement is larger than adverse movement.

## 9. MID_SHORT vs MID_LONG

| metric | `MID_SHORT_CONTEXT_READONLY` | `MID_LONG_CONTEXT_READONLY` | read-only interpretation |
| --- | ---: | ---: | --- |
| sample count | 381 | 150 | MID_SHORT has stronger depth |
| median return 1h | -0.0476 | -0.0805 | both noisy |
| median return 4h | -0.5154 | -0.4243 | both negative |
| favorable/adverse ratio 1h | 1.20 | 0.87 | MID_SHORT cleaner |
| favorable/adverse ratio 4h | 1.78 | 0.86 | MID_SHORT materially cleaner |
| top symbol share | 5.25% | 4.67% | both acceptable |

`MID_LONG_CONTEXT_READONLY` should stay secondary. Its favorable/adverse ratio does not support a threshold study yet.

## 10. Feasibility Labels

| candidate_type | label | reason |
| --- | --- | --- |
| `MID_SHORT_CONTEXT_READONLY` | `FEASIBILITY_STUDY_READY` | sample count is usable, 4h favorable/adverse ratio is 1.78, symbol concentration is acceptable |
| `MID_LONG_CONTEXT_READONLY` | `FEASIBILITY_NOISY` | sample count is modest and favorable/adverse ratios are below 1.0 |
| `NO_SIGNAL_CONTEXT` | `FEASIBILITY_BLOCKED` | baseline/control only, not directional |
| `EARLY_LONG_CANDIDATE_READONLY` | `FEASIBILITY_MONITOR_MORE` | radar-only and sample remains small |
| `EARLY_SHORT_CANDIDATE_READONLY` | `FEASIBILITY_MONITOR_MORE` | radar-only and sample remains small |
| `SQUEEZE_RISK_CONTEXT_READONLY` | `FEASIBILITY_BLOCKED` | risk-only, not directional |
| `TRAP_RISK_CONTEXT_READONLY` | `FEASIBILITY_BLOCKED` | risk-only, not directional |

## 11. Draft Read-Only Threshold Study Method

For Phase 8C, if implemented, the study should remain offline/read-only and use only `OUTCOME_READY` rows.

Suggested method:

1. Focus only on `MID_SHORT_CONTEXT_READONLY`.
2. Use closed 15m outcome data already stored in `market_candidate_outcomes_15m`.
3. Evaluate threshold bands over historical distributions only:
   - favorable 1h and 4h excursion percent.
   - adverse 1h and 4h excursion percent.
   - return 15m, 30m, 1h, and 4h.
4. Compare candidate distribution to `NO_SIGNAL_CONTEXT`.
5. Track symbol concentration per threshold band.
6. Require enough samples per band before interpreting.
7. Output feasibility labels only, not final levels.

Potential read-only study bands:

| horizon | descriptive band family |
| --- | --- |
| 1h | conservative / median / upper-quartile favorable movement |
| 4h | conservative / median / upper-quartile favorable movement |
| adverse control | median / upper-quartile adverse movement |

No final level is selected in Phase 8B.

## 12. Guardrails

- This report is read-only.
- No runtime code is changed.
- No scanner behavior is changed.
- No classifier rule is changed.
- No outcome calculation is changed.
- No migration is created.
- No final TP/SL level is produced.
- No order-routing design is produced.
- No strategy is produced.
- No claim of edge is made.
- Early categories remain radar-only.
- Squeeze/trap categories remain risk-only.
- `NO_SIGNAL_CONTEXT` remains baseline/control.

## 13. Recommended Next Phase

Phase 8C should be a read-only threshold distribution study for `MID_SHORT_CONTEXT_READONLY`.

Minimum requirements for Phase 8C:

- keep `MID_SHORT_CONTEXT_READONLY` as the only primary candidate.
- include `NO_SIGNAL_CONTEXT` baseline comparison.
- keep `MID_LONG_CONTEXT_READONLY` as secondary/noisy comparison.
- do not include early categories in directional feasibility.
- do not convert squeeze/trap into directional feasibility.
- produce only descriptive threshold tables.
- preserve all existing runtime rules.

Phase 8B verdict: `MID_SHORT_CONTEXT_READONLY` is ready for a read-only threshold feasibility study, but not for any live operational use.
