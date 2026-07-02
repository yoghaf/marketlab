# Candidate Numeric Evidence Audit

Read-only explanation layer. This document explains labels with actual numbers, required thresholds, pass/fail status, and missing evidence fields. It is not a live signal, not final TP/SL, and not execution logic.

## Aggregate

- generated_at: `2026-07-01T16:27:28.140757+00:00`
- total_candidates: `300`
- signal_candidate_count: `7`
- numeric_evidence_complete_count: `97`
- numeric_evidence_incomplete_count: `203`
- production_approved: `0`
- phase7_decision: `NO_PHASE7_CANDIDATE_YET`
- phase7_checklist_available: `True`

## Threshold Audit

- thresholds_extracted: `13`
- thresholds_missing_or_implicit: `7`

| rule | metric | required | unit | source |
|---|---|---|---|---|
| PRICE_UP_IMPULSE | price_return | >= 0.35 | % | anomaly_signal_factory.py |
| PRICE_DOWN_IMPULSE | price_return | <= -0.35 | % | anomaly_signal_factory.py |
| VOLUME_SPIKE | volume_ratio_vs_lookback | >= 1.5 | x_avg | multitimeframe_features.py |
| OI_EXPANSION | oi_change_pct | >= 0.1 | % | anomaly_signal_factory.py |
| OI_CONTRACTION | oi_change_pct | <= -0.1 | % | anomaly_signal_factory.py |
| CLOSE_NEAR_HIGH | close_position_in_range | >= 0.7 | 0_to_1 | anomaly_signal_factory.py |
| CLOSE_NEAR_LOW | close_position_in_range | <= 0.3 | 0_to_1 | anomaly_signal_factory.py |
| FUTURES_LED | abs(price_return) | >= 0.25 | % | multitimeframe_features.py |
| RELATIVE_OUTPERFORM | relative_return | >= 0.5 | % | multitimeframe_features.py |
| RELATIVE_UNDERPERFORM | relative_return | <= -0.5 | % | multitimeframe_features.py |
| PHASE7_EDGE | edge_vs_baseline | > 0.1 | R | phase6_readiness_audit.py |
| PHASE7_SCORE | total_score | >= 7 | points | phase6_readiness_audit.py |
| ARENA_NOISY | pessimistic_avg_r | < 0.1 | R | strategy_arena.py |

## Missing / Implicit Thresholds

| rule | status |
|---|---|
| EARLY_LONG final confidence threshold | RULE_THRESHOLD_NOT_EXPLICIT |
| EARLY_SHORT final confidence threshold | RULE_THRESHOLD_NOT_EXPLICIT |
| SQUEEZE volatility compression threshold | RULE_THRESHOLD_NOT_EXPLICIT |
| RADAR_ONLY promotion threshold beyond coded branch order | RULE_THRESHOLD_NOT_EXPLICIT |
| WATCHLIST_FOR_MORE_DATA semantic threshold beyond score bands | RULE_THRESHOLD_NOT_EXPLICIT |
| win_rate | RULE_THRESHOLD_NOT_EXPLICIT |
| expectancy | RULE_THRESHOLD_NOT_EXPLICIT |

## Top Failure Reasons

| reason | count |
|---|---:|
| SCORE_BELOW_7 | 300 |
| NOT_SIGNAL_CANDIDATE | 293 |
| LOW_CONFIDENCE | 290 |
| ATR_MISSING | 232 |
| ARENA_NOT_OK | 203 |
| EDGE_MISSING | 203 |
| EVIDENCE_FIELD_NOT_EXPOSED | 203 |
| DATA_PARTIAL | 143 |
| ARENA_NOISY | 82 |
| EDGE_BELOW_THRESHOLD | 74 |
| CONFLICTED | 24 |
| ARENA_REJECT | 15 |

## Top Missing Evidence Fields

| field | count |
|---|---:|
| edge_vs_baseline | 203 |
| sample_size | 203 |
| setup_pessR_vs_baseline_pessR | 203 |
| volume_ratio_vs_lookback | 79 |
| relative_return | 77 |
| price_return | 15 |
| oi_change_pct | 15 |
| close_position_in_range | 15 |

## Example Candidate Explanation

- symbol: `SOLUSDT`
- timeframe: `15m`
- setup: `MID_LONG`
- candidate_status: `SIGNAL_CANDIDATE`
- final_decision: `RADAR_ONLY`
- phase7_ready: `False`

### Numeric Evidence

| category | metric | required | actual | result | explanation |
|---|---|---|---|---|---|
| price | price_return | >= 0.35 % | 0.4983 % | PASS | Price return aktual 0.4983%; rule impulse membutuhkan >= 0.35%. |
| volume | volume_ratio_vs_lookback | >= 1.5 x_avg | current volume 1374678.85 vs avg 407744.9488 | PASS | Volume ratio aktual 3.3714x; rule spike membutuhkan >= 1.5x. |
| oi | oi_change_pct | >= 0.1 % | 0.2288 % | PASS | OI change aktual 0.2288%; threshold rule >= 0.1%. |
| price | close_position_in_range | >= 0.7 0_to_1 | 0.4206 0_to_1 | FAIL | Close position aktual 0.4206; close-near-high threshold >= 0.7. |
| relative_strength | relative_return | >= 0.5 % | -0.3183 % | FAIL | Relative return aktual -0.3183%, label INLINE_WITH_MARKET. |
| flow | futures_led_flag | equals True bool | True bool | PASS | Futures-led flag aktual True; rule futures-led juga membutuhkan price abs >= 0.25%, volume spike, dan OI > 0. |
| atr_risk | atr_reference_status | equals AVAILABLE status | reference timeframe 1h; ATR value current timeframe EVIDENCE_FIELD_NOT_EXPOSED | PASS | ATR reference status aktual AVAILABLE; candidate memakai reference 1h. |
| candidate | candidate_status | equals SIGNAL_CANDIDATE status | SIGNAL_CANDIDATE status | PASS | Candidate status aktual SIGNAL_CANDIDATE. |
| phase7 | arena_match | exists True bool | True bool | PASS | Arena mapping tersedia. |
| phase7 | baseline_match | exists True bool | True bool | PASS | Baseline mapping tersedia. |
| edge | edge_vs_baseline | > 0.1 R | setup 0.0486R vs baseline -0.0163R | FAIL | edge_vs_baseline aktual 0.0649R; required > 0.1R. |
| arena | arena_verdict | in ['MONITOR_MORE', 'PROMISING_FOR_FORWARD_TEST'] status | sample 283; pessR 0.0486R | FAIL | Arena verdict aktual NOISY; required minimal MONITOR_MORE. |
| phase6 | total_score | >= 7 points | 3 points | FAIL | Score aktual 3; required >= 7. |
| candidate | conflict_status | equals NONE status | NONE status | PASS | Conflict status aktual NONE. |
| arena | sample_size | RULE_THRESHOLD_NOT_EXPLICIT Strategy Arena min_sample config rows | 283 rows | INFO | Sample size tersedia. Threshold sample berasal dari konfigurasi Strategy Arena, bukan Phase 7 candidate gate langsung. |
| edge | setup_pessR_vs_baseline_pessR | > baseline_pessR R | baseline sample 4823 | PASS | Setup pessR 0.0486R dibanding baseline -0.0163R. |

### Phase 7 Checklist

| gate | required | actual | result |
|---|---|---|---|
| ATR reference available | atr_reference_status = AVAILABLE | AVAILABLE | PASS |
| Arena mapping | arena_match exists | True | PASS |
| Baseline mapping | baseline_match exists | True | PASS |
| Edge | edge_vs_baseline > +0.1R | 0.06491884653462904 | FAIL |
| Arena verdict | MONITOR_MORE or PROMISING_FOR_FORWARD_TEST | NOISY | FAIL |
| Score | score >= 7 | 3 | FAIL |
| Conflict | conflict_status = NONE | NONE | PASS |
| Candidate status | candidate_status = SIGNAL_CANDIDATE | SIGNAL_CANDIDATE | PASS |

### What Needs To Improve

- edge_vs_baseline harus naik dari 0.0649R ke > 0.1R.
- Arena verdict harus naik dari NOISY ke minimal MONITOR_MORE.
- Score harus naik dari 3 ke >= 7.
- Confidence harus membaik dari LOW melalui evidence price/OI/flow yang lebih jelas.
- Data partial harus membaik menjadi READY atau penalty data tetap menahan score.

## Glossary

- RR: Risk reward ratio dari test setup. Contoh target 2R dan stop 1R berarti RR 2.
- R: Unit risiko. Kalau entry 100 dan stop 98, maka 1R = 2.
- edge_vs_baseline: Selisih performa setup dibanding baseline dalam satuan R. Ini bukan TP dan bukan RR.
- pessR: Conservative R performance metric dari Strategy Arena.

## Guardrails

- No live signal.
- No execution or order.
- No final TP/SL.
- No fake data.
- No Signal Factory rule change.
- No Phase 6 threshold change.
- No Strategy Arena formula change.
