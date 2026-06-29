from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.models.market import MarketStateAlignment, MarketlabActiveUniverse, RichFutures5mAlignment
from app.services.utils import utcnow

FEATURE_STATUSES = ("FEATURE_READY", "FEATURE_PARTIAL", "FEATURE_BLOCKED")
VALID_FUNDING_STATUSES = {"FUNDING_ALIGNED", "FUNDING_CARRIED_FORWARD"}


@dataclass
class FeatureBuildResult:
    symbols: int
    inserted_count: int
    updated_count: int
    status_counts: dict[str, int]


class TimeframeFeatureBuilderService:
    def __init__(self, db: Session, timeframe: str, futures_model, spot_model, feature_model) -> None:
        self.db = db
        self.timeframe = timeframe
        self.futures_model = futures_model
        self.spot_model = spot_model
        self.feature_model = feature_model

    def run(
        self,
        symbols: list[str] | None = None,
        limit_windows: int | None = None,
        dry_run: bool = False,
    ) -> FeatureBuildResult:
        active_symbols = self._active_symbols(symbols)
        inserted = 0
        updated = 0
        status_counts = {status: 0 for status in FEATURE_STATUSES}
        now = utcnow()
        for symbol in active_symbols:
            windows = self._futures_windows(symbol, limit_windows)
            for futures_row in windows:
                payload = self._build_window(symbol, futures_row, now)
                action = self._upsert(payload, dry_run)
                inserted += int(action == "inserted")
                updated += int(action == "updated")
                status_counts[payload["feature_status"]] += 1
        if not dry_run:
            self.db.commit()
        return FeatureBuildResult(
            symbols=len(active_symbols),
            inserted_count=inserted,
            updated_count=updated,
            status_counts=status_counts,
        )

    def status_summary(self) -> dict[str, Any]:
        latest_feature_time = self.db.scalar(select(func.max(self.feature_model.window_close_time)))
        total_features = self.db.scalar(select(func.count()).select_from(self.feature_model)) or 0
        rows = self.db.execute(
            select(self.feature_model.feature_status, func.count()).group_by(self.feature_model.feature_status)
        ).all()
        counts = {status: 0 for status in FEATURE_STATUSES}
        for status, count in rows:
            counts[status] = count
        latest_ready_symbols_count = 0
        if latest_feature_time is not None:
            latest_ready_symbols_count = (
                self.db.scalar(
                    select(func.count(func.distinct(self.feature_model.symbol))).where(
                        self.feature_model.window_close_time == latest_feature_time,
                        self.feature_model.feature_status.in_(("FEATURE_READY", "FEATURE_PARTIAL")),
                    )
                )
                or 0
            )
        return {
            "latest_feature_time": latest_feature_time,
            "total_features": total_features,
            "feature_ready_count": counts["FEATURE_READY"],
            "feature_partial_count": counts["FEATURE_PARTIAL"],
            "feature_blocked_count": counts["FEATURE_BLOCKED"],
            "latest_ready_symbols_count": latest_ready_symbols_count,
        }

    def list_features(self, status: str | None = None, limit: int = 100) -> list[Any]:
        query = select(self.feature_model).order_by(desc(self.feature_model.window_close_time), self.feature_model.symbol)
        if status:
            query = query.where(self.feature_model.feature_status == status)
        return list(self.db.scalars(query.limit(min(max(limit, 1), 500))).all())

    def _build_window(self, symbol: str, futures, now: datetime) -> dict[str, Any]:
        window_open = _as_utc(futures.open_time)
        window_close = _as_utc(futures.close_time)
        spot = self._spot_window(symbol, window_open)
        rich = self._rich_window(symbol, window_open)
        state = self._state_window(symbol, window_open)

        reasons: list[str] = []
        partial_reasons: list[str] = []
        ohlcv_status = futures.aggregation_status
        rich_status = rich.alignment_status if rich else None
        snapshot_status = state.snapshot_alignment_status if state else None
        funding_status = state.funding_alignment_status if state else None

        if ohlcv_status != "AGG_READY":
            reasons.append(f"futures OHLCV status {ohlcv_status}")
        if rich is None:
            reasons.append("missing rich 5m alignment")
        elif rich_status != "ALIGNED":
            reasons.append(f"rich alignment status {rich_status}")
        if state is None:
            reasons.append("missing market state alignment")
        elif snapshot_status != "FRESH":
            reasons.append(f"snapshot status {snapshot_status}")
        if state is None:
            reasons.append("missing funding alignment")
        elif funding_status not in VALID_FUNDING_STATUSES:
            reasons.append(f"funding status {funding_status}")
        if state is not None and funding_status == "FUNDING_CARRIED_FORWARD":
            partial_reasons.append("funding carried forward")

        spot_missing = spot is None or spot.aggregation_status != "AGG_READY"
        if spot_missing:
            partial_reasons.append("spot OHLCV unavailable")

        if any(
            value is None
            for value in (futures.open, futures.high, futures.low, futures.close, futures.volume, futures.quote_volume)
        ):
            reasons.append("required futures OHLCV fields missing")
        if futures.open == Decimal("0"):
            reasons.append("futures open price is zero")
        if futures.high == futures.low:
            reasons.append("zero price range")
        if rich is not None and rich_status == "ALIGNED" and self._rich_required_missing(rich):
            reasons.append("required rich alignment fields missing")
        if state is not None and snapshot_status == "FRESH" and self._state_required_missing(state):
            reasons.append("required market state fields missing")

        if reasons:
            feature_status = "FEATURE_BLOCKED"
            block_reason = "; ".join(reasons)
        elif partial_reasons:
            feature_status = "FEATURE_PARTIAL"
            block_reason = "; ".join(partial_reasons)
        else:
            feature_status = "FEATURE_READY"
            block_reason = None

        taker_buy_base = futures.taker_buy_base_volume
        taker_sell_base = futures.taker_sell_base_volume
        taker_buy_quote = futures.taker_buy_quote_volume
        taker_sell_quote = futures.taker_sell_quote_volume
        spot_taker_buy_ratio = _ratio(spot.taker_buy_base_volume, spot.volume) if spot else None

        return {
            "symbol": symbol,
            "window_open_time": window_open,
            "window_close_time": window_close,
            "price_open": futures.open,
            "price_high": futures.high,
            "price_low": futures.low,
            "price_close": futures.close,
            "price_return_pct": _pct_change(futures.close, futures.open),
            "range_pct": _pct(futures.high - futures.low, futures.open)
            if futures.high is not None and futures.low is not None
            else None,
            "close_position": _ratio(futures.close - futures.low, futures.high - futures.low)
            if futures.close is not None and futures.low is not None and futures.high is not None
            else None,
            "body_pct": _pct(abs(futures.close - futures.open), futures.open)
            if futures.close is not None and futures.open is not None
            else None,
            "upper_wick_pct": _pct(futures.high - max(futures.open, futures.close), futures.open)
            if futures.high is not None and futures.open is not None and futures.close is not None
            else None,
            "lower_wick_pct": _pct(min(futures.open, futures.close) - futures.low, futures.open)
            if futures.low is not None and futures.open is not None and futures.close is not None
            else None,
            "futures_volume": futures.volume,
            "futures_quote_volume": futures.quote_volume,
            "futures_trade_count": futures.number_of_trades,
            "kline_taker_buy_base": taker_buy_base,
            "kline_taker_sell_base": taker_sell_base,
            "kline_taker_buy_quote": taker_buy_quote,
            "kline_taker_sell_quote": taker_sell_quote,
            "kline_taker_buy_ratio": _ratio(taker_buy_base, futures.volume),
            "kline_taker_sell_ratio": _ratio(taker_sell_base, futures.volume),
            "spot_volume": spot.volume if spot else None,
            "spot_quote_volume": spot.quote_volume if spot else None,
            "spot_taker_buy_ratio": spot_taker_buy_ratio,
            "spot_futures_volume_ratio": _ratio(spot.quote_volume, futures.quote_volume) if spot else None,
            "spot_missing_flag": spot_missing,
            "oi_open": rich.oi_open if rich else None,
            "oi_close": rich.oi_close if rich else None,
            "oi_change": rich.oi_change if rich else None,
            "oi_change_pct": _pct_change(rich.oi_close, rich.oi_open) if rich else None,
            "oi_value_open": rich.oi_value_open if rich else None,
            "oi_value_close": rich.oi_value_close if rich else None,
            "oi_value_change_pct": _pct_change(rich.oi_value_close, rich.oi_value_open) if rich else None,
            "global_long_short_ratio": rich.global_long_short_ratio_avg if rich else None,
            "global_long_account": rich.global_long_account_avg if rich else None,
            "global_short_account": rich.global_short_account_avg if rich else None,
            "top_trader_position_ratio": rich.top_trader_position_ratio_avg if rich else None,
            "top_trader_long_position": rich.top_trader_long_position_avg if rich else None,
            "top_trader_short_position": rich.top_trader_short_position_avg if rich else None,
            "top_trader_account_ratio": rich.top_trader_account_ratio_avg if rich else None,
            "top_trader_long_account": rich.top_trader_long_account_avg if rich else None,
            "top_trader_short_account": rich.top_trader_short_account_avg if rich else None,
            "futures_taker_buy_volume": rich.taker_buy_volume_sum if rich else None,
            "futures_taker_sell_volume": rich.taker_sell_volume_sum if rich else None,
            "futures_taker_buy_sell_ratio": rich.taker_buy_sell_ratio_avg if rich else None,
            "funding_rate": state.latest_funding_rate if state else None,
            "funding_status": state.funding_alignment_status if state else None,
            "funding_age_seconds": state.funding_age_seconds if state else None,
            "current_oi_age_seconds": state.current_oi_age_seconds if state else None,
            "mark_age_seconds": state.mark_age_seconds if state else None,
            "futures_spread_pct": state.futures_spread_pct if state else None,
            "futures_book_age_seconds": state.futures_book_age_seconds if state else None,
            "spot_spread_pct": state.spot_spread_pct if state else None,
            "spot_book_age_seconds": state.spot_book_age_seconds if state else None,
            "ohlcv_status": ohlcv_status,
            "rich_alignment_status": rich_status,
            "snapshot_alignment_status": snapshot_status,
            "funding_alignment_status": funding_status,
            "feature_status": feature_status,
            "feature_block_reason": block_reason,
            "created_at": now,
            "updated_at": now,
        }

    def _futures_windows(self, symbol: str, limit_windows: int | None) -> list[Any]:
        query = (
            select(self.futures_model)
            .where(self.futures_model.symbol == symbol)
            .order_by(desc(self.futures_model.open_time))
        )
        if limit_windows:
            query = query.limit(limit_windows)
        rows = list(self.db.scalars(query).all())
        rows.reverse()
        return rows

    def _spot_window(self, symbol: str, window_open: datetime) -> Any | None:
        return self.db.scalar(
            select(self.spot_model).where(
                self.spot_model.symbol == symbol,
                self.spot_model.open_time == window_open,
            )
        )

    def _rich_window(self, symbol: str, window_open: datetime) -> RichFutures5mAlignment | None:
        return self.db.scalar(
            select(RichFutures5mAlignment).where(
                RichFutures5mAlignment.symbol == symbol,
                RichFutures5mAlignment.timeframe == self.timeframe,
                RichFutures5mAlignment.window_open_time == window_open,
            )
        )

    def _state_window(self, symbol: str, window_open: datetime) -> MarketStateAlignment | None:
        return self.db.scalar(
            select(MarketStateAlignment).where(
                MarketStateAlignment.symbol == symbol,
                MarketStateAlignment.timeframe == self.timeframe,
                MarketStateAlignment.window_open_time == window_open,
            )
        )

    def _rich_required_missing(self, row: RichFutures5mAlignment) -> bool:
        return any(
            value is None
            for value in (
                row.oi_open,
                row.oi_close,
                row.global_long_short_ratio_avg,
                row.top_trader_position_ratio_avg,
                row.top_trader_account_ratio_avg,
                row.taker_buy_volume_sum,
                row.taker_sell_volume_sum,
            )
        )

    def _state_required_missing(self, row: MarketStateAlignment) -> bool:
        return any(
            value is None
            for value in (
                row.latest_funding_rate,
                row.current_oi_age_seconds,
                row.mark_age_seconds,
                row.futures_spread_pct,
                row.futures_book_age_seconds,
            )
        )

    def _upsert(self, payload: dict[str, Any], dry_run: bool) -> str:
        row = self.db.scalar(
            select(self.feature_model).where(
                self.feature_model.symbol == payload["symbol"],
                self.feature_model.window_open_time == payload["window_open_time"],
            )
        )
        if dry_run:
            return "updated" if row else "inserted"
        if row:
            for key, value in payload.items():
                if key != "created_at":
                    setattr(row, key, value)
            return "updated"
        self.db.add(self.feature_model(**payload))
        return "inserted"

    def _active_symbols(self, requested: list[str] | None) -> list[str]:
        query = (
            select(MarketlabActiveUniverse.symbol)
            .where(
                MarketlabActiveUniverse.is_active.is_(True),
                MarketlabActiveUniverse.collection_tier == "FULL_ACTIVE",
                MarketlabActiveUniverse.is_full_active.is_(True),
            )
            .order_by(MarketlabActiveUniverse.rank.asc())
        )
        active = self.db.scalars(query).all()
        if not requested:
            return active
        requested_set = {symbol.upper() for symbol in requested}
        return [symbol for symbol in active if symbol in requested_set]


def _pct_change(new_value: Decimal | None, old_value: Decimal | None) -> Decimal | None:
    if new_value is None or old_value in (None, Decimal("0")):
        return None
    return ((new_value - old_value) / old_value) * Decimal("100")


def _pct(numerator: Decimal | None, denominator: Decimal | None) -> Decimal | None:
    if numerator is None or denominator in (None, Decimal("0")):
        return None
    return (numerator / denominator) * Decimal("100")


def _ratio(numerator: Decimal | None, denominator: Decimal | None) -> Decimal | None:
    if numerator is None or denominator in (None, Decimal("0")):
        return None
    return numerator / denominator


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
