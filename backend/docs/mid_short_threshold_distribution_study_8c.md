# MID_SHORT Threshold Distribution Study - Phase 8C

Generated: 2026-06-30

Scope: read-only threshold distribution study for `MID_SHORT_CONTEXT_READONLY`. This document compares MID_SHORT bands against `NO_SIGNAL_CONTEXT` baseline and `MID_LONG_CONTEXT_READONLY` secondary/noisy comparison. It does not change runtime code, scanner logic, classifier rules, outcome logic, or database schema.

Production source:

| item | value |
| --- | --- |
| DB | `/var/www/marketlab/data/marketlab.db` |
| primary candidate | `MID_SHORT_CONTEXT_READONLY` |
| baseline/control | `NO_SIGNAL_CONTEXT` |
| secondary/noisy comparison | `MID_LONG_CONTEXT_READONLY` |

## 1. Executive Verdict

`MID_SHORT_CONTEXT_READONLY` remains the only directional category worth a read-only paper-threshold study, but none of the tested bands should be treated as final TP/SL.

The median 4h band is the best candidate for continued paper-threshold monitoring. It has enough eligible samples (`381`), a manageable favorable-hit sample (`191`), and avoids the high concentration problem seen in the upper-quartile band. However, adverse breach count is still equal to favorable hit count by the tested median thresholds, and `both-hit` is material (`102`), so the band is not clean enough for operational promotion.

Conservative band is too noisy because both favorable and adverse thresholds are easy to touch. Upper-quartile band is too aggressive for now because the favorable-hit sample drops to `96` and top-symbol concentration rises to `16.67%`.

All output remains read-only.

## 2. OUTCOME_READY Sample Size

| candidate_type | OUTCOME_READY n | included in directional threshold study |
| --- | ---: | --- |
| `MID_SHORT_CONTEXT_READONLY` | 381 | yes, primary |
| `NO_SIGNAL_CONTEXT` | 2893 | baseline proxy only |
| `MID_LONG_CONTEXT_READONLY` | 150 | secondary/noisy comparison |
| `EARLY_LONG_CANDIDATE_READONLY` | 62 | no, radar-only |
| `EARLY_SHORT_CANDIDATE_READONLY` | 36 | no, radar-only |
| `SQUEEZE_RISK_CONTEXT_READONLY` | 999 | no, risk-only |
| `TRAP_RISK_CONTEXT_READONLY` | 444 | no, risk-only |

`EARLY_LONG_CANDIDATE_READONLY` and `EARLY_SHORT_CANDIDATE_READONLY` are excluded because sample sizes remain too small. `SQUEEZE_RISK_CONTEXT_READONLY` and `TRAP_RISK_CONTEXT_READONLY` are excluded because they are risk-only contexts, not directional threshold candidates.

## 3. MID_SHORT Distribution Bands

Values are percent. These quartiles are calculated from `MID_SHORT_CONTEXT_READONLY` `OUTCOME_READY` rows.

| metric | q1 | median | q3 |
| --- | ---: | ---: | ---: |
| `max_favorable_move_1h` | 0.2740 | 0.6138 | 1.4660 |
| `max_adverse_move_1h` | 0.2459 | 0.5117 | 1.2369 |
| `max_favorable_move_4h` | 0.7226 | 1.6076 | 3.1038 |
| `max_adverse_move_4h` | 0.3753 | 0.9022 | 2.5042 |

The 4h distribution keeps the useful separation from Phase 8B:

| horizon | median favorable | median adverse | favorable/adverse magnitude ratio |
| --- | ---: | ---: | ---: |
| 1h | 0.6138 | 0.5117 | 1.20 |
| 4h | 1.6076 | 0.9022 | 1.78 |

## 4. Candidate Threshold Bands

The tested bands use MID_SHORT 4h quartiles:

| band | favorable threshold 4h | adverse threshold 4h | intended interpretation |
| --- | ---: | ---: | --- |
| conservative | 0.7226 | 0.3753 | easy-to-touch thresholds; expected high activity |
| median | 1.6076 | 0.9022 | central paper-threshold candidate |
| upper-quartile | 3.1038 | 2.5042 | aggressive threshold, likely lower sample |

These are descriptive bands only. They are not final TP/SL levels.

## 5. MID_SHORT Band Results

| band | eligible n | favorable hit | adverse breach | both-hit | neither-hit | fav hit share | adverse breach share | top symbol in favorable hits |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| conservative | 381 | 286 | 286 | 214 | 23 | 75.07% | 75.07% | `SKYAIUSDT` 6.99% |
| median | 381 | 191 | 191 | 102 | 101 | 50.13% | 50.13% | `SKYAIUSDT` 9.95% |
| upper-quartile | 381 | 96 | 96 | 33 | 222 | 25.20% | 25.20% | `SKYAIUSDT` 16.67% |

Because the favorable and adverse thresholds come from the same candidate distribution quartiles, favorable-hit and adverse-breach counts are symmetric by construction. The useful signals are:

- `both-hit` declines from `214` to `102` to `33`.
- `neither-hit` rises from `23` to `101` to `222`.
- top-symbol concentration rises as the threshold becomes aggressive.

## 6. MID_SHORT Horizon Behavior By Band

Median returns below are measured among rows that hit the favorable threshold for that band.

| band | median return 15m | median return 30m | median return 1h | median return 4h |
| --- | ---: | ---: | ---: | ---: |
| conservative | -0.0445 | -0.1183 | -0.2238 | -1.0255 |
| median | -0.2174 | -0.2899 | -0.3916 | -1.5622 |
| upper-quartile | -0.2859 | -0.6230 | -0.9664 | -2.8950 |

For a bearish-context candidate, the favorable-hit subsets show increasingly negative median future returns as the favorable threshold becomes stricter. This is directionally coherent for research, but it still does not remove adverse-breach risk.

## 7. Baseline Comparison: NO_SIGNAL_CONTEXT

`NO_SIGNAL_CONTEXT` has no directional favorable/adverse fields, so this comparison uses a bearish-oriented proxy:

- favorable proxy = absolute `max_down_move_4h`
- adverse proxy = `max_up_move_4h`

| band | baseline eligible n | favorable proxy hit | adverse proxy breach | both-hit | neither-hit | fav hit share | adverse breach share | top symbol in favorable proxy hits |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| conservative | 2893 | 2294 | 2139 | 1648 | 108 | 79.29% | 73.94% | `TACUSDT` 2.53% |
| median | 2893 | 1580 | 1615 | 948 | 646 | 54.61% | 55.82% | `TACUSDT` 3.42% |
| upper-quartile | 2893 | 883 | 964 | 408 | 1454 | 30.52% | 33.32% | `TACUSDT` 4.98% |

Baseline takeaways:

- Baseline bearish proxy hit rates are similar to, and sometimes higher than, MID_SHORT hit rates.
- MID_SHORT does not yet separate cleanly from baseline by hit counts alone.
- MID_SHORT's stronger argument remains its native favorable/adverse magnitude ratio, not raw hit-count superiority.

## 8. Secondary Comparison: MID_LONG_CONTEXT_READONLY

MID_LONG is compared using its native bullish favorable/adverse fields. This is a noisy directional comparison, not a primary threshold candidate.

| band | eligible n | favorable hit | adverse breach | both-hit | neither-hit | fav hit share | adverse breach share | top symbol in favorable hits |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| conservative | 150 | 80 | 125 | 57 | 2 | 53.33% | 83.33% | `BASUSDT` 6.25% |
| median | 150 | 63 | 94 | 34 | 27 | 42.00% | 62.67% | `BASUSDT` 7.94% |
| upper-quartile | 150 | 32 | 44 | 19 | 93 | 21.33% | 29.33% | `BASUSDT` 15.63% |

MID_LONG takeaways:

- adverse breach exceeds favorable hit in every band.
- sample size is only `150`.
- upper-quartile favorable-hit concentration rises to `15.63%`.

`MID_LONG_CONTEXT_READONLY` remains secondary/noisy and should not be promoted into a threshold study before MID_SHORT.

## 9. Band Interpretation

### Conservative Band

Verdict: too noisy.

Reason:

- `MID_SHORT_CONTEXT_READONLY` favorable hit and adverse breach are both `286 / 381`.
- `both-hit` is `214`, or `56.17%` of eligible rows.
- Baseline proxy has similarly high activity.

This band is too easy to touch on both sides and would not provide useful threshold separation.

### Median Band

Verdict: candidate for paper-threshold study.

Reason:

- `MID_SHORT_CONTEXT_READONLY` has `191` favorable hits and `191` adverse breaches.
- `both-hit` drops to `102`, while `neither-hit` rises to `101`.
- favorable-hit concentration is acceptable at `9.95%` top-symbol share.
- median favorable-hit 4h return is `-1.5622%`, directionally coherent for bearish research.

Limitation:

- baseline proxy remains competitive by hit count.
- adverse breach is not reduced enough.

This band is the most useful starting point for read-only threshold exploration, but it needs additional filters before it can become cleaner.

### Upper-Quartile Band

Verdict: aggressive / monitor more.

Reason:

- favorable hits drop to `96`.
- top-symbol concentration among favorable hits rises to `16.67%`.
- `neither-hit` grows to `222`, meaning many rows never touch either high threshold.

This band may be useful for stress-testing large-move behavior, but current sample depth and concentration make it too aggressive for the next practical paper-threshold iteration.

## 10. Recommended Monitoring Path

| band | recommendation | reason |
| --- | --- | --- |
| conservative | do not prioritize | too noisy; both sides hit too often |
| median | monitor next | best balance of sample size and threshold strictness |
| upper-quartile | monitor later | aggressive; sample and concentration warning |

The next read-only study should focus on the median band and search for additional non-execution filters that reduce adverse breach and both-hit counts. Candidate filters can be evaluated descriptively only, such as context readiness quality, 1h confirmation state, symbol concentration, and funding/snapshot freshness.

## 11. Guardrails

- This is a read-only distribution study.
- No runtime code is changed.
- No migration is created.
- No scanner behavior is changed.
- No classifier rule is changed.
- No outcome logic is changed.
- No final TP/SL level is selected.
- No execution logic is created.
- No strategy logic is created.
- No edge claim is made.
- Early categories remain radar-only.
- Squeeze/trap categories remain risk-only.

## 12. Definition Of Done Check

Phase 8C is complete because:

- MID_SHORT favorable/adverse distribution bands are documented.
- conservative, median, and upper-quartile bands are compared.
- baseline proxy comparison is included.
- MID_LONG noisy secondary comparison is included.
- concentration is reported.
- no final TP/SL is selected.
- no live signal behavior is introduced.
