# MID_SHORT Filter Study - Phase 8D

Generated: 2026-06-30

Scope: read-only filter study for `MID_SHORT_CONTEXT_READONLY` only. This study uses the Phase 8C median 4h band and checks whether simple filters reduce adverse breach and both-hit behavior without making sample size or concentration unusable.

No runtime code, scanner logic, classifier rule, outcome logic, migration, final TP/SL level, execution logic, or strategy logic is changed.

## 1. Executive Verdict

The cleanest simple filter is **futures-led context present**.

Compared with the current MID_SHORT median-band baseline:

- eligible sample remains usable: `233`.
- adverse breach share drops from `49.10%` to `41.20%`.
- both-hit share drops from `26.22%` to `17.60%`.
- favorable/adverse count ratio improves from `1.01` to `1.18`.
- top-symbol concentration stays low at `4.72%`.

The second useful filter is **current active Top 25 rank**, but it is less attractive because sample count falls to `110` and top-symbol concentration rises to `10.91%`.

Filters that do not help:

- confidence filter: no discrimination, because all current MID_SHORT rows are `MEDIUM`.
- 1h context support: no discrimination, because all current MID_SHORT rows already have bearish 1h support by the simple price-return check.
- strong 1h bearish context: worsens adverse and both-hit behavior.
- spot missing and non-futures-led rows: worse than baseline.
- spot supporting: promising ratios but too small and concentrated.

Conclusion: MID_SHORT is **not clean enough for paper signal promotion yet**, but the futures-led subset is clean enough to monitor in a Phase 8E read-only paper-candidate study.

## 2. Baseline 8C Median Band

User-provided Phase 8C baseline:

| metric | value |
| --- | ---: |
| eligible n | 381 |
| favorable threshold 4h | 1.6076% |
| adverse threshold 4h | 0.9022% |
| favorable hit | 191 |
| adverse breach | 191 |
| both-hit | 102 |
| neither-hit | 101 |

Production moved while this study was computed. Current production baseline using the same thresholds:

| metric | current value |
| --- | ---: |
| eligible n | 389 |
| favorable hit | 193 |
| adverse breach | 191 |
| both-hit | 102 |
| neither-hit | 107 |
| adverse breach share | 49.10% |
| both-hit share | 26.22% |
| favorable/adverse ratio | 1.01 |
| top-symbol concentration | `SKYAIUSDT` 5.14% |

The delta is small and does not change the 8C interpretation.

## 3. Filter Summary Table

All rows use:

- candidate type: `MID_SHORT_CONTEXT_READONLY`
- status: `OUTCOME_READY`
- favorable threshold 4h: `1.6076%`
- adverse threshold 4h: `0.9022%`

| filter | eligible | favorable hit | adverse breach | both-hit | neither-hit | adverse share | both-hit share | fav/adv ratio | top-symbol concentration | verdict |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| baseline current | 389 | 193 | 191 | 102 | 107 | 49.10% | 26.22% | 1.01 | `SKYAIUSDT` 5.14% | reference |
| confidence `MEDIUM/HIGH` | 389 | 193 | 191 | 102 | 107 | 49.10% | 26.22% | 1.01 | `SKYAIUSDT` 5.14% | no effect |
| confidence `HIGH` only | 0 | 0 | 0 | 0 | 0 | n/a | n/a | n/a | n/a | no samples |
| 1h supports bearish | 389 | 193 | 191 | 102 | 107 | 49.10% | 26.22% | 1.01 | `SKYAIUSDT` 5.14% | no effect |
| 1h strong bearish | 229 | 136 | 141 | 84 | 36 | 61.57% | 36.68% | 0.96 | `SKYAIUSDT` 8.30% | worse |
| spot supporting | 24 | 9 | 7 | 2 | 10 | 29.17% | 8.33% | 1.29 | `TRXUSDT` 25.00% | too small/concentrated |
| futures-led context | 233 | 113 | 96 | 41 | 65 | 41.20% | 17.60% | 1.18 | `WLDUSDT` 4.72% | best simple filter |
| spot missing | 107 | 69 | 84 | 59 | 13 | 78.50% | 55.14% | 0.82 | `SKYAIUSDT` 18.69% | worse |
| not futures-led | 156 | 80 | 95 | 61 | 42 | 60.90% | 39.10% | 0.84 | `SKYAIUSDT` 12.82% | worse |
| rank Top 25 | 110 | 56 | 44 | 24 | 34 | 40.00% | 21.82% | 1.27 | `WLDUSDT` 10.91% | useful but smaller |
| rank 26-50 | 118 | 52 | 53 | 25 | 38 | 44.92% | 21.19% | 0.98 | `FILUSDT` 9.32% | mixed |
| rank 51-75 | 128 | 63 | 69 | 36 | 32 | 53.91% | 28.13% | 0.91 | `SKYAIUSDT` 15.63% | worse/concentrated |
| rank missing/inactive | 33 | 22 | 25 | 17 | 3 | 75.76% | 51.52% | 0.88 | `[non_ascii_symbol]` 27.27% | exclude |
| current full active | 356 | 171 | 166 | 85 | 104 | 46.63% | 23.88% | 1.03 | `SKYAIUSDT` 5.62% | slight improvement |

## 4. Confidence Filter

Result:

| filter | eligible | adverse share | both-hit share | interpretation |
| --- | ---: | ---: | ---: | --- |
| `MEDIUM/HIGH` | 389 | 49.10% | 26.22% | same as baseline |
| `HIGH` only | 0 | n/a | n/a | no samples |

All current `MID_SHORT_CONTEXT_READONLY` rows are `MEDIUM`. Confidence is not a useful filter yet.

## 5. 1h Context Filter

Simple 1h support was evaluated using `price_return_pct_1h < 0` from candidate evidence.

| filter | eligible | adverse share | both-hit share | fav/adv ratio | verdict |
| --- | ---: | ---: | ---: | ---: | --- |
| 1h supports bearish | 389 | 49.10% | 26.22% | 1.01 | no discrimination |
| 1h strong bearish (`<= -0.5%`) | 229 | 61.57% | 36.68% | 0.96 | worse |

The category already requires bearish 1h support in practice. Making the 1h condition stricter makes the median band noisier, not cleaner.

## 6. Spot Support Filter

No rows currently have `WEAK_SPOT_SUPPORT`, so weak-vs-not-weak cannot separate the sample.

| spot status filter | eligible | adverse share | both-hit share | fav/adv ratio | top concentration | verdict |
| --- | ---: | ---: | ---: | ---: | --- | --- |
| weak spot | 0 | n/a | n/a | n/a | n/a | no samples |
| not weak | 389 | 49.10% | 26.22% | 1.01 | `SKYAIUSDT` 5.14% | same as baseline |
| spot supporting | 24 | 29.17% | 8.33% | 1.29 | `TRXUSDT` 25.00% | too small/concentrated |
| spot missing | 107 | 78.50% | 55.14% | 0.82 | `SKYAIUSDT` 18.69% | bad filter |

`SPOT_SUPPORTING` looks cleaner but has only `24` rows and high concentration. It should not be used yet.

## 7. Futures-Led Filter

Futures-led was checked from either:

- `spot_support_status_15m = FUTURES_LED`
- supporting psychology label contains `FUTURES_LED_MOVE`

| filter | eligible | favorable hit | adverse breach | both-hit | neither-hit | adverse share | both-hit share | fav/adv ratio | top concentration |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| futures-led context | 233 | 113 | 96 | 41 | 65 | 41.20% | 17.60% | 1.18 | `WLDUSDT` 4.72% |
| not futures-led | 156 | 80 | 95 | 61 | 42 | 60.90% | 39.10% | 0.84 | `SKYAIUSDT` 12.82% |

This is the best simple filter in Phase 8D. It lowers adverse breach and both-hit counts without making the sample too small or too concentrated.

Important nuance: this does not mean futures-led is a final rule. It means this subset is cleaner for the next read-only paper-candidate study.

## 8. Universe Rank / Liquidity Tier Filter

| rank bucket | eligible | favorable hit | adverse breach | both-hit | neither-hit | adverse share | both-hit share | fav/adv ratio | top concentration | verdict |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| Top 25 | 110 | 56 | 44 | 24 | 34 | 40.00% | 21.82% | 1.27 | `WLDUSDT` 10.91% | useful but smaller |
| 26-50 | 118 | 52 | 53 | 25 | 38 | 44.92% | 21.19% | 0.98 | `FILUSDT` 9.32% | mixed |
| 51-75 | 128 | 63 | 69 | 36 | 32 | 53.91% | 28.13% | 0.91 | `SKYAIUSDT` 15.63% | worse |
| missing/inactive rank | 33 | 22 | 25 | 17 | 3 | 75.76% | 51.52% | 0.88 | `[non_ascii_symbol]` 27.27% | exclude |
| current full active | 356 | 171 | 166 | 85 | 104 | 46.63% | 23.88% | 1.03 | `SKYAIUSDT` 5.62% | slight improvement |

Rank Top 25 improves adverse behavior but has a smaller sample and higher top-symbol concentration than futures-led context. Missing/inactive rank is clearly bad and should be excluded from future paper studies.

## 9. Simple Combination Checks

These are not new rules. They are sanity checks for whether combining simple filters helps.

| combo | eligible | favorable hit | adverse breach | both-hit | neither-hit | adverse share | both-hit share | fav/adv ratio | top concentration | interpretation |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| 1h supports + not futures-led | 156 | 80 | 95 | 61 | 42 | 60.90% | 39.10% | 0.84 | `SKYAIUSDT` 12.82% | worse |
| 1h supports + rank Top 25 | 110 | 56 | 44 | 24 | 34 | 40.00% | 21.82% | 1.27 | `WLDUSDT` 10.91% | useful but smaller |
| 1h supports + current full active | 356 | 171 | 166 | 85 | 104 | 46.63% | 23.88% | 1.03 | `SKYAIUSDT` 5.62% | slight improvement |
| not futures-led + current full active | 145 | 73 | 85 | 55 | 42 | 58.62% | 37.93% | 0.86 | `SKYAIUSDT` 13.79% | worse |

No combination beats the simple futures-led filter on overall balance of sample size, reduced adverse share, reduced both-hit share, and concentration.

## 10. Comparison vs Baseline 8C Median Band

| metric | 8C baseline | current baseline | futures-led filter | rank Top 25 filter |
| --- | ---: | ---: | ---: | ---: |
| eligible | 381 | 389 | 233 | 110 |
| favorable hit | 191 | 193 | 113 | 56 |
| adverse breach | 191 | 191 | 96 | 44 |
| both-hit | 102 | 102 | 41 | 24 |
| neither-hit | 101 | 107 | 65 | 34 |
| adverse share | 50.13% | 49.10% | 41.20% | 40.00% |
| both-hit share | 26.77% | 26.22% | 17.60% | 21.82% |
| fav/adv ratio | 1.00 | 1.01 | 1.18 | 1.27 |
| top concentration | `SKYAIUSDT` 5.25% | `SKYAIUSDT` 5.14% | `WLDUSDT` 4.72% | `WLDUSDT` 10.91% |

Futures-led is the better next filter because it improves the noise profile while keeping more than half the MID_SHORT sample and does not raise concentration.

## 11. Answer

Best filter:

- `MID_SHORT_CONTEXT_READONLY` + futures-led context.

Secondary filter worth monitoring:

- current active Top 25 rank.

Filters to reject for now:

- confidence.
- stricter 1h bearish context.
- spot missing.
- not futures-led.
- rank missing/inactive.
- lower rank bucket.

Final Phase 8D answer:

> Futures-led MID_SHORT improves the median 4h band enough to justify a Phase 8E read-only paper-candidate study. It is not clean enough for runtime promotion, and no final TP/SL should be selected yet.

## 12. Guardrails

- This is a read-only filter study.
- No runtime code is changed.
- No migration is created.
- No scanner behavior is changed.
- No classifier rule is changed.
- No outcome logic is changed.
- No final TP/SL level is selected.
- No execution logic is created.
- No strategy logic is created.
- No edge claim is made.
