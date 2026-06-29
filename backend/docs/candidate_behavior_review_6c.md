# MarketLab Phase 6C - Candidate Behavior Review

Source:

- `backend/docs/outcome_summary_readonly_6b.md`
- `GET /api/outcomes/15m/summary`
- `market_candidate_outcomes_15m`

This review is read-only. It describes candidate behavior from closed-candle forward movement and does not define automated action or allocation handling. The sample is still limited.

## Executive Verdict

The current production sample is useful for sanity review, but not enough to promote any candidate type into a stronger decision layer.

Key observations:

- `NO_SIGNAL_CONTEXT` is the largest group and should remain the baseline/control bucket.
- `SQUEEZE_RISK_CONTEXT_READONLY` shows early upward movement but fades by 30m/1h median, so it should remain a risk/context label only.
- `MID_LONG_CONTEXT_READONLY` and `MID_SHORT_CONTEXT_READONLY` have very small samples. Their behavior is observation-only.
- `TRAP_RISK_CONTEXT_READONLY` has only 5 ready samples and should stay descriptive.
- `EARLY_LONG_CANDIDATE_READONLY` has only 2 ready samples and is not usable for rule promotion.
- `EARLY_SHORT_CANDIDATE_READONLY` has no production-ready sample yet.

Recommended next phase: continue outcome collection and repeat this review after a larger, less concentrated sample is available. Keep the current candidate rules frozen unless a clear evidence mismatch is found.

## Candidate Type Review

| candidate_type | n | sample read | median 15m | median 30m | median 1h | median 4h | max_up/down behavior | behavior review | recommendation |
| --- | ---: | --- | ---: | ---: | ---: | ---: | --- | --- | --- |
| NO_SIGNAL_CONTEXT | 76 | usable as baseline/control, still limited | 0.3683 | 0.2472 | -0.1301 | -0.2484 | 1h up 0.9459 vs down -0.7625; 4h up 1.3958 vs down -2.2868 | Mixed and noisy. Early median is slightly positive, but longer windows drift negative and 4h downside range is larger. | Keep as baseline/control. Do not promote. |
| SQUEEZE_RISK_CONTEXT_READONLY | 50 | usable for preliminary risk observation | 0.2542 | -0.2127 | -0.3028 | -0.1034 | 1h up 0.7547 vs down -0.5951; 4h up 0.9275 vs down -1.9386 | Early pop followed by fade. Behavior looks reversal-prone and not directionally durable. | Monitor as risk/context only. Need more forward samples. |
| MID_LONG_CONTEXT_READONLY | 9 | too small | 0.4715 | -0.2892 | -0.2020 | -0.9094 | 1h up 0.9592 vs down -0.8293; 4h up 1.9810 vs down -2.3639 | Short early lift but weak continuation in longer windows. The sample is too small and the 4h downside range is larger than upside median range. | Hold promotion. Treat as observation only. |
| MID_SHORT_CONTEXT_READONLY | 8 | too small | 0.1182 | -0.0497 | -0.5649 | -3.4089 | 1h up 1.4826 vs down -1.3001; 4h up 1.7462 vs down -4.5346 | The longer-window median points lower, but adverse upward range is still meaningful. Sample is too small for a strong read. | Hold promotion. Collect more samples. |
| TRAP_RISK_CONTEXT_READONLY | 5 | too small | 0.4620 | 0.6755 | 0.5166 | 0.4074 | 1h up 1.0303 vs down -0.5590; 4h up 3.5282 vs down -1.6527 | Current sample does not validate a directional trap behavior. With n=5, this is inconclusive. | Keep descriptive only. More samples needed. |
| EARLY_LONG_CANDIDATE_READONLY | 2 | unusably small | 0.3836 | 0.4772 | -0.1140 | -0.7814 | 1h up 0.8290 vs down -0.7415; 4h up 0.8290 vs down -2.1733 | Two rows are not enough. Early movement is positive but later medians fade. | Do not promote. Wait for production sample growth. |
| EARLY_SHORT_CANDIDATE_READONLY | 0 | no ready production sample | n/a | n/a | n/a | n/a | n/a | No production evidence yet. | No review conclusion available. |

## Sample Size Warnings

The overall ready sample is 150 rows. This is enough for a first descriptive review, but still small for robust behavior separation.

Small-sample candidate types:

- `MID_LONG_CONTEXT_READONLY`: 9
- `MID_SHORT_CONTEXT_READONLY`: 8
- `TRAP_RISK_CONTEXT_READONLY`: 5
- `EARLY_LONG_CANDIDATE_READONLY`: 2
- `EARLY_SHORT_CANDIDATE_READONLY`: 0

These groups must not be interpreted as stable. Their current values are observations only.

## Concentration Warnings

| concentration check | value | review |
| --- | ---: | --- |
| top candidate type share | 50.67% | concentrated |
| max symbol share | 1.33% | not symbol-concentrated |
| ready rows | 150 | limited |

The sample is not dominated by one symbol, but it is dominated by `NO_SIGNAL_CONTEXT`. This makes baseline comparison useful, but weakens conclusions for smaller candidate types.

## What Looks Noisy

- `MIXED_CONTEXT` dominates ready rows: 131 of 150.
- `NO_SIGNAL_CONTEXT` has slightly positive 15m/30m medians but negative 1h/4h medians.
- `SQUEEZE_RISK_CONTEXT_READONLY` has a positive 15m median but negative 30m/1h medians.
- `MID_LONG_CONTEXT_READONLY` fades after 15m despite its context name.
- `TRAP_RISK_CONTEXT_READONLY` currently moves upward on median, but n=5 makes this inconclusive.

The common pattern is early movement followed by mixed or weaker longer-window behavior.

## What Needs More Forward Samples

Priority groups for more data:

1. `MID_LONG_CONTEXT_READONLY`
2. `MID_SHORT_CONTEXT_READONLY`
3. `TRAP_RISK_CONTEXT_READONLY`
4. `EARLY_LONG_CANDIDATE_READONLY`
5. `EARLY_SHORT_CANDIDATE_READONLY`

Minimum practical target before another behavior review:

- At least 50 ready rows per candidate type for preliminary stability.
- At least several distinct market sessions per candidate type.
- Continued concentration check so one type or one symbol does not dominate the review.

## What Should Not Be Promoted

- `SQUEEZE_RISK_CONTEXT_READONLY` should not be treated as a directional action label.
- `TRAP_RISK_CONTEXT_READONLY` should not be treated as a directional action label.
- `MID_LONG_CONTEXT_READONLY` should not be promoted with n=9.
- `MID_SHORT_CONTEXT_READONLY` should not be promoted with n=8.
- `EARLY_LONG_CANDIDATE_READONLY` should not be promoted with n=2.
- `EARLY_SHORT_CANDIDATE_READONLY` should not be promoted because it has no ready production sample.

## Recommended Next Phase

Proceed with a data-only continuation:

- Keep collecting 15m candidate outcomes.
- Refresh the read-only outcome summary periodically.
- Add a repeatable review threshold before revisiting candidate behavior.
- Keep current candidate rules frozen unless a clear evidence mismatch appears.
- Do not add action logic based on this review.

Phase 6C status: review complete, no promotion recommended.
