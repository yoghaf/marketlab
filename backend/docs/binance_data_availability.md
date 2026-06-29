# Binance Data Availability Audit

MarketLab uses Binance market data at different native resolutions. This document is the source of truth for what Binance actually provides, what fields are available, and how later data alignment should treat each dataset. It is intentionally limited to data availability and alignment rules. It does not define aggregation engines, feature builders, signal classifiers, backtests, execution, or strategy logic.

## Final Data Mapping

1. Native 1m data:
   - Futures OHLCV from futures klines.
   - Spot OHLCV from spot klines.
   - Candle taker buy/sell fields derived from kline payloads.

2. Native 5m data:
   - Open interest history.
   - Global long/short account ratio.
   - Top trader long/short account ratio.
   - Top trader long/short position ratio.
   - Futures taker buy/sell volume endpoint.

3. Snapshot/current data:
   - Current open interest.
   - Mark price and current funding fields.
   - Futures and spot book ticker.

4. Funding-periodic data:
   - Current funding rate and next funding time from mark price/premium index.
   - Funding history by funding timestamp.

5. Event stream data:
   - Liquidation events.
   - Aggregate trades as optional/candidate-only event data.

## Audit Table

| data_name | endpoint_or_stream | market | minimum_interval_or_period | supported_intervals_or_periods | fields_available | native_resolution | can_align_to_15m | can_align_to_1h | can_align_to_4h | can_align_to_24h | caveat | MarketLab usage |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Futures kline | `GET /fapi/v1/klines` | USD-M futures | `1m` | Kline intervals including `1m`, `3m`, `5m`, `15m`, `30m`, `1h`, `2h`, `4h`, `6h`, `8h`, `12h`, `1d`, `3d`, `1w`, `1M` | open time, open, high, low, close, volume, close time, quote asset volume, number of trades, taker buy base asset volume, taker buy quote asset volume, ignore | Native candle interval | Yes, from closed 1m candles or native 15m | Yes, from closed 1m candles or native 1h | Yes, from closed 1m candles or native 4h | Yes, from closed 1m candles or native 1d | Do not use incomplete current candle. Use UTC open/close boundaries. | Core futures OHLCV for Top 75. |
| Spot kline | `GET /api/v3/klines` | Spot | `1m` | Kline intervals including `1s`, `1m`, `3m`, `5m`, `15m`, `30m`, `1h`, `2h`, `4h`, `6h`, `8h`, `12h`, `1d`, `3d`, `1w`, `1M` | open time, open, high, low, close, volume, close time, quote asset volume, number of trades, taker buy base asset volume, taker buy quote asset volume, unused field | Native candle interval | Yes, from closed 1m candles or native 15m | Yes, from closed 1m candles or native 1h | Yes, from closed 1m candles or native 4h | Yes, from closed 1m candles or native 1d | Some futures symbols have no valid spot pair. Missing spot must remain `MISSING_SPOT`, not READY. | Core spot OHLCV where matching spot symbol exists. |
| Futures kline taker buy fields | `GET /fapi/v1/klines` fields inside futures kline payload | USD-M futures | `1m` | Same as futures kline intervals | taker buy base asset volume, taker buy quote asset volume, total base/quote volume, trade count | Same as candle interval | Yes, sum per window from closed candles | Yes, sum per window from closed candles | Yes, sum per window from closed candles | Yes, sum per window from closed candles | This is candle-level taker activity, not the same dataset as futures taker buy/sell volume ratio endpoint. | Derive candle taker buy/sell context from futures 1m klines. |
| Current open interest | `GET /fapi/v1/openInterest` | USD-M futures | Snapshot/current | Snapshot request only | symbol, openInterest, time | Request-time snapshot | Yes, by freshness-tagged last observation, not by candle aggregation | Yes, by freshness-tagged last observation | Yes, by freshness-tagged last observation | Yes, by freshness-tagged last observation | Snapshot data must have freshness status. It is not native 1m history. | Core current OI snapshot per Top 75. |
| Open interest history | `GET /futures/data/openInterestHist` | USD-M futures data | `5m` | `5m`, `15m`, `30m`, `1h`, `2h`, `4h`, `6h`, `12h`, `1d` | symbol, sumOpenInterest, sumOpenInterestValue, timestamp | Native period series, minimum 5m | Yes, align from 5m or request native 15m | Yes, align from 5m or request native 1h | Yes, align from 5m or request native 4h | Yes, align from 5m or request native 1d | No 1m OI history. Do not create `open_interest_history_1m`. | Rich futures 5m dataset for Top 75. |
| Mark price / funding current | `GET /fapi/v1/premiumIndex` | USD-M futures | Snapshot/current | Snapshot request only | symbol, markPrice, indexPrice, estimatedSettlePrice, lastFundingRate, nextFundingTime, interestRate, time | Request-time snapshot plus funding metadata | Yes, by freshness-tagged last observation | Yes, by freshness-tagged last observation | Yes, by freshness-tagged last observation | Yes, by freshness-tagged last observation | Funding fields are periodic, not 1m. Mark price snapshot freshness must be tracked separately. | Core mark/funding snapshot per Top 75. |
| Funding history | `GET /fapi/v1/fundingRate` | USD-M futures | Funding event timestamp | Funding events, normally tied to exchange funding schedule | symbol, fundingRate, fundingTime, markPrice | Funding-periodic event series | Yes, forward-fill or window-join only with explicit alignment status | Yes, same | Yes, same | Yes, same | Funding is not 1m data. Do not force it into candle cadence without alignment metadata. | Rich futures funding history per Top 75. |
| Futures taker buy/sell volume endpoint | `GET /futures/data/takerlongshortRatio` | USD-M futures data | `5m` | `5m`, `15m`, `30m`, `1h`, `2h`, `4h`, `6h`, `12h`, `1d` | buySellRatio, buyVol, sellVol, timestamp | Native period series, minimum 5m | Yes, align from 5m or request native 15m | Yes, align from 5m or request native 1h | Yes, align from 5m or request native 4h | Yes, align from 5m or request native 1d | Not available at 1m. Do not confuse with kline taker buy fields. | Rich futures 5m taker endpoint per Top 75. |
| Global long/short account ratio | `GET /futures/data/globalLongShortAccountRatio` | USD-M futures data | `5m` | `5m`, `15m`, `30m`, `1h`, `2h`, `4h`, `6h`, `12h`, `1d` | symbol, longShortRatio, longAccount, shortAccount, timestamp | Native period series, minimum 5m | Yes, align from 5m or request native 15m | Yes, align from 5m or request native 1h | Yes, align from 5m or request native 4h | Yes, align from 5m or request native 1d | No 1m global long/short ratio. Do not create `global_long_short_1m`. | Rich futures 5m positioning dataset per Top 75. |
| Top trader long/short position ratio | `GET /futures/data/topLongShortPositionRatio` | USD-M futures data | `5m` | `5m`, `15m`, `30m`, `1h`, `2h`, `4h`, `6h`, `12h`, `1d` | symbol, longShortRatio, longPosition, shortPosition, timestamp | Native period series, minimum 5m | Yes, align from 5m or request native 15m | Yes, align from 5m or request native 1h | Yes, align from 5m or request native 4h | Yes, align from 5m or request native 1d | No 1m top trader position ratio. Do not create `top_trader_position_1m`. | Rich futures 5m top trader position dataset per Top 75. |
| Top trader long/short account ratio | `GET /futures/data/topLongShortAccountRatio` | USD-M futures data | `5m` | `5m`, `15m`, `30m`, `1h`, `2h`, `4h`, `6h`, `12h`, `1d` | symbol, longShortRatio, longAccount, shortAccount, timestamp | Native period series, minimum 5m | Yes, align from 5m or request native 15m | Yes, align from 5m or request native 1h | Yes, align from 5m or request native 4h | Yes, align from 5m or request native 1d | No 1m top trader account ratio. | Rich futures 5m top trader account dataset per Top 75. |
| Futures book ticker | `GET /fapi/v1/ticker/bookTicker` or `!bookTicker` stream | USD-M futures | Snapshot/current or realtime stream update | Snapshot per request or stream updates | symbol, bidPrice, bidQty, askPrice, askQty, time/update identifiers depending on source | Snapshot/event update | Yes, with freshness status or window sampling rules | Yes, same | Yes, same | Yes, same | Book ticker is not a candle. It must be freshness-tagged and never treated as OHLCV. | Core best bid/ask snapshot per Top 75. |
| Spot book ticker | `GET /api/v3/ticker/bookTicker` or spot book ticker stream | Spot | Snapshot/current or realtime stream update | Snapshot per request or stream updates | symbol, bidPrice, bidQty, askPrice, askQty | Snapshot/event update | Yes, with freshness status or window sampling rules | Yes, same | Yes, same | Yes, same | Spot availability depends on matching spot symbol. | Core best bid/ask snapshot for valid spot pairs in Top 75. |
| Liquidation stream | `<symbol>@forceOrder` or `!forceOrder@arr` | USD-M futures websocket | Event stream | Realtime events | event type, event time, order details including symbol, side, order type, time in force, original quantity, price, average price, order status, last filled quantity, filled accumulated quantity, trade time | Event stream | Yes, only after explicit window aggregation | Yes, only after explicit window aggregation | Yes, only after explicit window aggregation | Yes, only after explicit window aggregation | Liquidation is event data, not candle data. It must be aggregated per window before use. | Available but not part of current REST collector. Stream status remains separate. |
| Aggregate trade stream | `<symbol>@aggTrade` stream, optional candidate-only | USD-M futures or spot, depending stream namespace | Event stream | Realtime events | aggregate trade id, price, quantity, first trade id, last trade id, trade time, buyer maker flag | Event stream | Yes, only after explicit window aggregation | Yes, only after explicit window aggregation | Yes, only after explicit window aggregation | Yes, only after explicit window aggregation | Candidate-only. Do not add to active collection until a separate collection design exists. | Optional future event dataset; not active in Phase 1.8. |

## Alignment Rules

1. Do not create fake 1m fields such as `global_long_short_1m`.
2. Do not create fake 1m fields such as `top_trader_position_1m`.
3. Open interest history and positioning ratios have a minimum native period of 5m.
4. Kline OHLCV and kline taker buy fields can be collected at 1m.
5. Funding is not 1m data. It is funding-periodic and must be aligned explicitly.
6. A future feature builder must store `data_alignment_status` for every aligned dataset.
7. A classifier must not read data that has not been aligned and marked usable.
8. Native 5m data must be aligned to 15m, 1h, 4h, and 24h by period boundaries or requested directly at those periods when appropriate.
9. Snapshot/current data must be assigned freshness status before being joined to any analysis window.
10. Liquidation events must be aggregated per window and must never be treated as candles.

## Recommended Window Treatment

| Source type | Treatment for 15m/1h/4h/24h |
|---|---|
| 1m klines | Build closed-window OHLCV from complete 1m candles, or request native larger interval if the collector later supports it. |
| Kline taker buy fields | Sum taker buy base/quote volume per closed window; derive sell-side from total minus taker buy where needed. |
| 5m period endpoints | Align by timestamp into closed 15m/1h/4h/24h windows; do not invent 1m rows. |
| Snapshot/current endpoints | Use last known value only with freshness status and timestamp distance. |
| Funding history | Join by funding time and explicit carry-forward rules; mark alignment status. |
| Event streams | Aggregate count, notional, side splits, and other event metrics per closed window only after a dedicated event collector exists. |

## References

- Binance USD-M Futures REST market data: `https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api`
- Binance USD-M Futures websocket market streams: `https://developers.binance.com/docs/derivatives/usds-margined-futures/websocket-market-streams`
- Binance Spot REST market data: `https://developers.binance.com/docs/binance-spot-api-docs/rest-api/market-data-endpoints`
- Binance Spot websocket streams: `https://developers.binance.com/docs/binance-spot-api-docs/web-socket-streams`
