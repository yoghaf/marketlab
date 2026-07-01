# Phase 2 Multitimeframe Feature Schema Audit

Status: audit for read-only Phase 2/3 implementation. No migration is required for the first implementation.

## Available Tables

| area | tables | status |
|---|---|---|
| Futures OHLCV | `futures_klines_15m`, `futures_klines_1h`, `futures_klines_4h`, `futures_klines_24h` | Available. All use aggregate OHLCV schema and `aggregation_status`. |
| Spot OHLCV | `spot_klines_15m`, `spot_klines_1h`, `spot_klines_4h`, `spot_klines_24h` | Available, but spot may be missing for non-spot symbols. |
| Open interest history | `futures_open_interest_history` | Available at 5m period. Suitable for window nearest-before comparisons. |
| Funding | `futures_funding_history`, `market_state_alignment` | Available. Funding is periodic/carry-forward, not candle-native. |
| Spot/futures context | `market_feature_context_15m_1h`, `market_state_alignment` | Available for 15m+1h, but not generalized for 4h/24h. Phase 2 should compute a new read-only context from OHLCV/OI/funding. |
| Active universe | `marketlab_active_universe` | Available with active flag, rank, volume, tier, and signal eligibility. |
| Existing candidates | `market_signal_candidates_readonly_15m` | Existing 15m readonly classifier output. Do not mutate for Phase 2/3. |
| Outcomes | `market_candidate_outcomes_15m` | Existing outcome tracker. Do not mutate for Phase 2/3. |

## OHLCV Fields

Aggregate kline tables provide:

- `symbol`
- `open_time`
- `close_time`
- `open`
- `high`
- `low`
- `close`
- `volume`
- `quote_volume`
- `number_of_trades`
- `taker_buy_base_volume`
- `taker_buy_quote_volume`
- `taker_sell_base_volume`
- `taker_sell_quote_volume`
- `expected_1m_count`
- `actual_1m_count`
- `missing_1m_count`
- `aggregation_status`

Feature builders must use only rows where `aggregation_status = AGG_READY`.

## Timeframes

| timeframe | current source | fallback |
|---|---|---|
| 15m | `futures_klines_15m` / `spot_klines_15m` | none |
| 1h | `futures_klines_1h` / `spot_klines_1h` | aggregate 15m if needed |
| 4h | `futures_klines_4h` / `spot_klines_4h` | aggregate 15m if needed |
| 24h | `futures_klines_24h` / `spot_klines_24h` | aggregate 15m if needed, but likely sparse until more complete forward history exists |

## Missing Data Risks

- 24h rows may exist but can be sparse or not aligned for every symbol.
- Spot data is missing for futures-only symbols; feature status should remain `PARTIAL_DATA` rather than inventing spot context.
- OI is 5m-native and should be aligned nearest-before window boundaries, not treated as candle-native.
- Funding is periodic/carry-forward and should be represented as a latest-known context, not as 1m/15m-native.
- Existing 15m/1h feature tables are useful references, but Phase 2 should calculate generalized snapshots for 15m/1h/4h/24h without mutating those tables.

## Migration Decision

No migration is required for Phase 2/3 v1. The safer implementation is:

1. Compute multitimeframe feature snapshots read-only from existing DB tables.
2. Write JSON artifacts under `backend/artifacts/signal_factory/v1`.
3. Serve artifacts through read-only API endpoints.
4. Add DB storage only after feature/candidate schema stabilizes.

## Recommended Implementation

- Add `backend/app/services/multitimeframe_features.py`.
- Add `backend/app/services/anomaly_signal_factory.py`.
- Add `backend/scripts/run_multitimeframe_signal_factory_v1.py`.
- Emit:
  - `backend/artifacts/signal_factory/v1/features.json`
  - `backend/artifacts/signal_factory/v1/candidates.json`
  - `backend/artifacts/signal_factory/v1/summary.json`
  - `backend/docs/multitimeframe_signal_factory_v1_report.md`
- API should only read artifacts and return a clear 404 if they are missing.

This keeps Phase 2/3 isolated from the existing scanner, classifier, outcome tracker, Strategy Arena, and collector logic.
