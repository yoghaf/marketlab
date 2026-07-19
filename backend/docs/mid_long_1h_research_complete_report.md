# MID_LONG 1h Research Report

- Status: read-only research report
- Production snapshot: 19 July 2026, approximately 17:55 WIB
- Primary lane: `MID_LONG`, signal timeframe `1h`
- Current formal research checkpoint: `LAB-63`
- Current rule status: V2 remains unchanged
- Promotion status: not approved for live execution or rule replacement

## LAB-63 Timeout Policy Validation

LAB-63 keeps the candidate geometry fixed at `0.75 x ATR(14) 1h` risk and `1.0R` target. It changes only the position duration policy:

- timeout after 60 minutes;
- timeout after 120 minutes;
- timeout after 4 hours, used as the official comparison reference;
- no timeout, where a position remains open until target or stop is touched.

All four policies use the same futures entry, causal 1h ATR, closed `AGG_READY` futures 15m path, Binance taker fee, signal spread, slippage, position lock, and chronological 70/30 split. The no-timeout policy never converts the latest candle into a completed result: unresolved positions remain `OPEN`, contribute only unrealized R, and keep the symbol lock active. Missing or gapped forward candles remain `WAITING_DATA` or `INCOMPLETE_FORWARD_DATA`.

The production numbers are generated in `backend/artifacts/strategy_optimization/v1/mid_long_lab63.json`. They must be read as a timeout-policy study, not a live rule recommendation.

## 1. Executive Verdict

MID_LONG 1h has enough production samples to be researched, but the current V2 definition is not usable as-is. The latest direct production cohort is clearly negative after realistic costs:

| Metric | Current MID_LONG 1h V2 |
|---|---:|
| Evaluated | 510 |
| Closed | 490 |
| Open | 20 |
| TP / SL | 174 / 316 |
| TP share | 35.51% |
| SL share | 64.49% |
| Ideal total R | -28.00R |
| Realistic total R | -84.94R |
| Realistic average R | -0.173R |
| Realistic result including open | -86.16R |

The current definition therefore receives this verdict:

`MID_LONG_1H_V2_NEGATIVE_BUT_GEOMETRY_SHADOW_PROMISING`

The promising part is not the current V2 signal. It is a separate ideal-path hypothesis found by the ATR/RR/timeout study:

- Risk distance: `0.75 x ATR(14) 1h`
- Target: `1.0R`
- Maximum observation horizon: `60 minutes`
- Ideal sample: 642 evaluated signals
- Ideal total: `+37.25R`
- Ideal average: `+0.058R`
- Ideal median: `+0.042R`
- Ideal maximum drawdown: `-14.87R`

This result must not be promoted yet. It was selected from a parameter grid on the same historical sample, excludes realistic fee/spread/slippage, and has not passed a chronological out-of-sample validation. The correct next project is a `MID_LONG 1h V2.1 shadow` study that validates this geometry first, not an immediate change to the live rule.

## 2. Important Cohort Differences

The studies below do not all use the same rows. Their totals must not be compared as if they were one backtest.

| Study | Sample | Purpose | Important limitation |
|---|---:|---|---|
| Current Quality Lab | 510 evaluated, 490 closed | Current V2 health and realistic result | Best representation of current lane |
| Current simple filter study | 510 evaluated | Explore evidence filters | Mostly in-sample; no independent validation |
| Walk-forward filter artifact | 277 closed | Chronological train/validation check | Bounded older artifact, not the current 510 cohort |
| Misidentification artifact | 277 closed | Coarse failure taxonomy | Detailed forward-path classification was unavailable |
| ATR/RR/timeout optimization | 642 evaluated | Explore exit geometry | Ideal R, grid-selected, no realistic costs |
| Current optimized regime split | 642 evaluated | Diagnose market-condition sensitivity | Same ideal optimized sample; not an independent test |
| Historical regime study | 148 total | Early regime hypothesis | Stale and ideal-only; context, not current evidence |

## 3. Current V2 Production Baseline

The latest Quality Lab production query used:

- Stage: `MID_LONG`
- Signal timeframe: `1h`
- Position lock: enabled
- `WATCH_ONLY`: excluded
- Entry source: futures only
- Spot and rich futures data: evidence only

### 3.1 Outcome summary

| Metric | Value |
|---|---:|
| Total evaluated | 510 |
| Closed | 490 |
| Open | 20 |
| TP | 174 |
| SL | 316 |
| Ideal total R | -28.00R |
| Ideal average R | -0.057R |
| Realistic total R | -84.94R |
| Realistic average R | -0.173R |
| Realism penalty on closed rows | -56.94R |
| Open ideal R | +1.56R |
| Open realistic R | -1.22R |
| Realistic result with open | -86.16R |

The lane is not being damaged only by fees. It is already negative before the realistic execution penalty, and costs make the result substantially worse.

### 3.2 Concentration examples

| Symbol | Closed | TP / SL | Realistic R | Read |
|---|---:|---:|---:|---|
| `1000PEPEUSDT` | 16 | 4 / 12 | -7.72R | Largest current loss contributor |
| `LDOUSDT` | 4 | 4 / 0 | +5.68R | Largest current positive contributor, but very small sample |

The positive symbol result cannot be generalized because four rows are not enough. The negative result is broader and is not caused by one symbol alone.

## 4. Evidence Differences Between TP and SL

The table below compares actual evidence medians in the current 510-row cohort. A positive delta means the TP median is higher than the SL median.

| Evidence | TP median | SL median | Delta | Interpretation |
|---|---:|---:|---:|---|
| Price return | +1.183% | +1.442% | -0.259 pp | SL entries were more extended before entry |
| ATR extension | 0.761x | 0.844x | -0.083x | TP entries were less extended |
| OI change | +0.545% | +0.623% | -0.078 pp | Larger raw OI expansion did not improve the lane |
| OI z-score | 3.546 | 3.113 | +0.433 | Relative OI abnormality was stronger in TP rows |
| Funding percentile | 71.37 | 73.21 | -1.83 | More crowded funding was slightly worse |
| Kline taker buy | 53.57% | 52.86% | +0.72 pp | TP rows had slightly stronger buy aggression |
| Kline taker sell | 46.43% | 47.14% | -0.72 pp | Inverse of taker buy evidence |
| Volume versus lookback | 1.349x | 1.368x | -0.019x | Volume alone barely separated outcomes |
| Range / ATR | 1.417x | 1.401x | +0.017x | No useful clean separation |
| Price / ATR multiple | 0.899x | 0.864x | +0.035x | Small difference only |
| Global long/short ratio | 1.384 | 1.349 | +0.035 | Weak positive separation; 72 rows missing |
| Top trader position ratio | 1.551 | 1.526 | +0.025 | Weak positive separation; 68 rows missing |
| Top trader account ratio | 1.610 | 1.559 | +0.051 | Weak positive separation; 71 rows missing |
| Futures spread | 0.0134% | 0.0159% | -0.0025 pp | Better liquidity was mildly favorable |
| Spot spread | 0.0263% | 0.0277% | -0.0014 pp | Mild separation; 148 rows missing |

### 4.1 Evidence conclusion

The clearest current pattern is late or crowded long entry:

1. Losing rows entered after a larger price move.
2. Losing rows had greater ATR extension.
3. Losing rows had slightly higher funding percentile.
4. Winning rows had higher relative OI z-score, slightly stronger taker buy, and lower spread.

Most gaps are still small. No single evidence field cleanly separates TP from SL, so changing one threshold is unlikely to repair MID_LONG 1h by itself.

### 4.2 Missing evidence

The current signal snapshot has no usable values for these fields:

- `body_pct`
- `lower_wick_pct`
- `upper_wick_pct`
- `spot_futures_volume_ratio`

These fields cannot currently be used to claim a validated MID_LONG filter from this cohort. Their absence also limits detailed rejection-candle and spot-confirmation analysis.

## 5. Simple Filter Study

The current filter study tested filters against the same 510-row production cohort. Therefore, these are research hypotheses, not independent validation.

### 5.1 Best all-sample filter

`funding percentile >= 75 AND volume <= 1.50x AND spot spread <= 0.03%`

| Metric | Result |
|---|---:|
| Evaluated | 44 |
| Closed | 43 |
| TP / SL | 21 / 22 |
| Realistic total R | +4.57R |
| Realistic average R | +0.106R |
| Median R | -1.00R |
| SL share | 51.16% |
| Maximum drawdown | -5.00R |
| Top-symbol concentration | 13.64% (`DOGEUSDT`) |

This is the only current simple combination with a positive realistic total. It is not ready for promotion because:

- only 43 rows are closed;
- the median remains `-1R`;
- symbol concentration is elevated;
- 148 rows cannot be evaluated because spot spread is missing;
- the combination has not passed chronological validation.

### 5.2 Filters that reduced damage but remained negative

| Filter | Closed | TP / SL | Realistic R | Avg R | Read |
|---|---:|---:|---:|---:|---|
| Volume <= 1.50x and OI z-score <= 1.80 | 83 | 33 / 50 | -6.24R | -0.075R | Better than baseline, still negative |
| Global L/S >= 1.20 and volume <= 1.50x | 144 | 58 / 86 | -14.64R | -0.102R | Damage reduction only |
| Funding >= 75 and global L/S >= 1.20 | 126 | 50 / 76 | -12.13R | -0.096R | Damage reduction only |
| Spot spread <= 0.03% | 191 | 75 / 116 | -25.50R | -0.133R | Liquidity helps, not enough |
| OI change <= 0.50% | 211 | 81 / 130 | -30.76R | -0.146R | Useful research lead only |
| OI z-score <= 1.80 | 111 | 41 / 70 | -15.53R | -0.140R | Still weak |
| ATR extension <= 0.90x | 279 | 104 / 175 | -40.76R | -0.146R | Reduces late extension, still negative |

Volume alone, confidence tier alone, funding alone, and price/ATR alone did not fix the lane.

## 6. Chronological Walk-Forward Check

The available walk-forward artifact contains an older bounded MID_LONG cohort of 277 closed rows. It cannot be directly substituted for the current 490 closed rows.

### 6.1 Walk-forward baseline

| Split | Closed | TP / SL | Realistic R | Avg R | Max drawdown |
|---|---:|---:|---:|---:|---:|
| All | 277 | 101 / 176 | -42.12R | -0.152R | -63.14R |
| Train | 193 | 67 / 126 | -35.51R | -0.184R | Not used as promotion evidence |
| Validation | 84 | 34 / 50 | -6.61R | -0.079R | -12.41R |

### 6.2 Most relevant walk-forward filter

`OI change <= 0.50%`

| Split | Closed | TP / SL | Realistic R | Avg R |
|---|---:|---:|---:|---:|
| All | 110 | Not used for promotion | -18.79R | -0.171R |
| Train | 81 | Not used for promotion | -19.83R | -0.245R |
| Validation | 29 | 14 / 15 | +1.04R | +0.036R |

The later validation slice became slightly positive, but train and full-sample results stayed negative. This may represent changing market regime rather than a robust relationship. It is a useful candidate for shadow monitoring, not a production rule.

Other walk-forward filters, including ATR extension, spread, and funding, remained negative in validation.

## 7. Failure and Misidentification Audit

The available misidentification artifact also uses the older 277-row cohort.

| Primary reason | Rows | TP / SL | Realistic R | Avg R |
|---|---:|---:|---:|---:|
| Entry overextended | 152 | 60 / 92 | -5.85R | -0.039R |
| Mixed or no clear cause | 101 | 36 / 65 | -18.72R | -0.185R |
| Wrong-direction reverse candidate | 13 | 0 / 13 | -15.16R | -1.166R |
| Cost or fill drag | 11 | 5 / 6 | -2.39R | -0.217R |

### 7.1 What this audit proves

- Overextended entry is common.
- A small but severe clean reverse group exists: all 13 rows lost.
- Cost and fill quality worsen the result but are not the main cause.
- A large residual group still lacks a precise causal explanation.

### 7.2 What this audit does not prove

The artifact reports zero `wrong_direction_1h` rows because detailed path classification is unavailable for all 277 rows. This does not mean wrong direction never occurred. The path field is `UNKNOWN`, so the result cannot be used to conclude that direction is correct.

MID_LONG still needs the same candle-path anatomy already built for MID_SHORT:

- immediate adverse move;
- target-near then reversal;
- stop first then later target;
- late entry after extension;
- support/resistance interaction;
- BTC/ETH regime conflict;
- 15m rejection after the 1h signal.

## 8. ATR/RR/Timeout Geometry Study

The strategy optimizer evaluated 642 MID_LONG 1h signals using futures entry and forward 15m futures candles. ATR is `ATR(14)` from closed 1h candles available at signal time.

The strongest grid row was:

| Parameter | Value |
|---|---:|
| ATR risk multiplier | 0.75x |
| Reward/risk target | 1.0R |
| Timeout | 60 minutes |
| Evaluated | 642 |
| Closed | 639 |
| TP | 210 |
| SL | 148 |
| Both same candle | 7 |
| Timeout | 274 |
| Waiting | 3 |
| Ideal total R | +37.25R |
| Ideal average R | +0.058R |
| Ideal median R | +0.042R |
| Ideal maximum drawdown | -14.87R |

The second useful row used the same `0.75 ATR / 1.0R` geometry with a 120-minute timeout:

- Ideal total: `+33.47R`
- Ideal average: `+0.052R`
- Ideal median: `+0.127R`
- Maximum drawdown: `-21.65R`

### 8.1 Why this matters

The current V2 lane uses geometry that permits many long positions to remain exposed after the initial impulse has weakened. The grid suggests that MID_LONG may behave more like a short-lived continuation setup than a long-duration trend position.

### 8.2 Why this is not yet a result to deploy

1. The optimizer selected the best row from 60 parameter combinations.
2. The same data were used for selection and measurement.
3. The result is ideal, before realistic fee, spread, and slippage.
4. Timeout rows use close-at-horizon R, not a guaranteed executable fill.
5. No chronological holdout or rolling walk-forward has approved this geometry.

This is the strongest next hypothesis, but it is still only a hypothesis.

## 9. Market Regime Sensitivity

The current optimized regime split uses the best `0.75 ATR / 1R / 60m` geometry on the same 642-row ideal sample.

### 9.1 Helpful conditions

| Condition | Sample | Ideal total R | Avg R | Median R | Read |
|---|---:|---:|---:|---:|---|
| 1h volatility high | 219 | +33.09R | +0.151R | +0.194R | Strongest positive split |
| BTC 4h flat | 446 | +60.47R | +0.137R | +0.157R | Flat BTC favored token continuation |
| 1h breadth strong | 394 | +47.04R | +0.120R | +0.161R | Broad participation helped |
| 4h breadth mixed | 202 | +23.28R | +0.115R | - | Not independently validated |
| ETH 4h flat | 370 | +35.77R | +0.097R | - | Not independently validated |

### 9.2 Harmful conditions

| Condition | Sample | Ideal total R | Avg R | Median R | Read |
|---|---:|---:|---:|---:|---|
| BTC 4h bullish | 125 | -24.01R | -0.192R | -0.285R | Possible late/crowded long environment |
| 1h breadth weak | 102 | -16.06R | -0.157R | -0.364R | Long impulse lacked market support |
| BTC 1h bearish | 43 | -4.09R | -0.095R | - | Small sample |
| Risk-off | 38 | -3.53R | -0.093R | - | Small sample |

The counterintuitive BTC 4h bullish weakness is plausible: token MID_LONG signals may arrive late after the broader move is already extended. It must be tested out-of-sample before becoming a gate.

## 10. Earlier V4 Shadow Result

The old one-hour V4 shadow artifact combined MID_LONG and MID_SHORT and did not improve the overall lane:

| Cohort | Rows | TP / SL | Realistic R | Avg R |
|---|---:|---:|---:|---:|
| V2 baseline | 500 | 196 / 304 | -53.03R | -0.106R |
| V4 pass | 476 | 186 / 290 | -52.95R | -0.111R |
| V4 fail | 24 | 10 / 14 | -0.08R | -0.003R |

Verdict: `V4_SHADOW_WEAKER_THAN_V2_BASELINE`.

This confirms that stacking old filters is not the correct next step. V4 should not be revived as a shortcut for MID_LONG.

## 11. What Is Proven

1. Current MID_LONG 1h V2 is negative both ideally and realistically.
2. Realistic execution costs materially worsen the lane.
3. Losing rows tend to enter after more price and ATR extension.
4. No single current evidence field cleanly separates TP and SL.
5. Simple filters reduce damage but mostly remain negative.
6. The positive funding/volume/spot-spread combination is too small and unvalidated.
7. The strongest current research lead is shorter and tighter geometry, not a new evidence score.
8. Market context matters, especially weak breadth and bullish BTC 4h conditions.
9. Old V4 filtering did not improve the combined one-hour signal population.

## 12. What Is Not Proven

1. The `0.75 ATR / 1R / 60m` geometry is not proven after costs.
2. It has not passed a chronological holdout.
3. BTC 4h bullish must not yet be used as a hard rejection rule.
4. OI change <= 0.50% has only a small positive validation slice.
5. The funding/volume/spot-spread combination is not robust enough.
6. MID_LONG direction accuracy has not yet been reconstructed candle by candle.
7. No MID_LONG rule is approved for execution.

## 13. Recommended MID_LONG 1h V2.1 Shadow Plan

The next research should be bounded and sequential.

### Step 1: Geometry-only shadow comparison

Keep the candidate population unchanged and compare:

- Control: current logged V2 TP/SL lifecycle.
- Variant A: `0.75 ATR / 1.0R / 60m timeout`.
- Variant B: `0.75 ATR / 1.0R / 120m timeout`.

Apply the realistic paper model to every variant:

- Binance USD-M taker fee reference;
- entry and exit spread;
- slippage per side;
- causal candle ordering;
- position lock;
- same-candle TP/SL ambiguity kept separate.

### Step 2: Chronological validation

Use an explicit time split or rolling walk-forward. The geometry must improve:

- realistic average R;
- realistic total R;
- median R;
- maximum drawdown;
- result stability across symbols;
- result stability across time blocks.

It must not be selected only because one period or one symbol performed well.

### Step 3: Path anatomy

For every validation TP, SL, and timeout row, classify:

- immediate continuation;
- immediate reversal;
- target-near reversal;
- stop first then later recovery;
- overextended entry;
- support/resistance conflict;
- BTC/ETH context conflict;
- breadth conflict;
- exit caused only by timeout.

This answers whether the shorter holding horizon is fixing a real behavioral property or merely fitting historical noise.

### Step 4: One evidence filter at a time

Only after geometry validation, test these candidates separately:

1. `OI change <= 0.50%`
2. Exclude `BTC 4h bullish`
3. Exclude `1h breadth weak`
4. Funding >= 75 + volume <= 1.50x + spot spread <= 0.03%

Do not stack all filters immediately. Each filter must show an incremental out-of-sample contribution over the geometry-only control.

### Step 5: Shadow observation

If a variant passes validation, log it alongside V2 without changing scanner output. Recommended minimum before reconsideration:

- at least 120 closed shadow rows;
- at least 40 later-time validation rows;
- no symbol concentration above 10%;
- positive realistic total and average R;
- lower drawdown than the V2 control;
- no single regime responsible for most of the result.

## 14. Final Decision

| Question | Answer |
|---|---|
| Is current MID_LONG 1h V2 finished? | No. It is clearly negative. |
| Can it be used as-is? | No. |
| Is there enough data to continue research? | Yes. |
| Is a simple evidence filter ready? | No. |
| Is there a promising direction? | Yes: tighter risk, 1R target, and 60-120m timeout. |
| Should the current rule be changed now? | No. |
| Next formal work | MID_LONG 1h V2.1 geometry shadow with realistic costs and chronological validation. |

The recommended order is therefore:

1. Keep MID_SHORT V2.1 in one-month paper observation.
2. Freeze current MID_LONG V2 as a control, not a promoted setup.
3. Build and validate a geometry-only MID_LONG V2.1 shadow.
4. Add regime or evidence filters only after geometry survives out-of-sample testing.

## 15. Production Sources

The report was assembled from these read-only production endpoints and artifacts:

- `/api/signal-candidates/quality-lab?stage=MID_LONG&timeframe=1h`
- `/api/signal-candidates/filter-study?stage=MID_LONG&timeframe=1h`
- `/api/signal-candidates/one-hour-walk-forward`
- `/api/signal-candidates/misidentification-audit`
- `/api/signal-candidates/market-regime-study`
- `/api/strategy-optimization-artifacts`
- `/api/signal-candidates/one-hour-v4-shadow`

No Signal Factory rule, scanner decision, outcome calculation, TP/SL rule, threshold, database schema, or execution behavior was changed for this report.
