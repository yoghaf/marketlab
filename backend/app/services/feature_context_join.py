from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.models.market import (
    MarketFeature1h,
    MarketFeature15m,
    MarketFeatureContext15m1h,
    MarketlabActiveUniverse,
)
from app.services.utils import utcnow

CONTEXT_STATUSES = ("CONTEXT_READY", "CONTEXT_PARTIAL", "CONTEXT_BLOCKED")
USABLE_FEATURE_STATUSES = {"FEATURE_READY", "FEATURE_PARTIAL"}


@dataclass
class FeatureContextJoinResult:
    symbols: int
    inserted_count: int
    updated_count: int
    status_counts: dict[str, int]


class FeatureContextJoinService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def run(
        self,
        symbols: list[str] | None = None,
        limit_windows: int | None = None,
        dry_run: bool = False,
    ) -> FeatureContextJoinResult:
        active_symbols = self._active_symbols(symbols)
        inserted = 0
        updated = 0
        status_counts = {status: 0 for status in CONTEXT_STATUSES}
        now = utcnow()
        for symbol in active_symbols:
            rows_15m = self._feature_15m_windows(symbol, limit_windows)
            for feature_15m in rows_15m:
                payload = self._join_window(feature_15m, now)
                action = self._upsert(payload, dry_run)
                inserted += int(action == "inserted")
                updated += int(action == "updated")
                status_counts[payload["context_status"]] += 1
        if not dry_run:
            self.db.commit()
        return FeatureContextJoinResult(
            symbols=len(active_symbols),
            inserted_count=inserted,
            updated_count=updated,
            status_counts=status_counts,
        )

    def status_summary(self) -> dict[str, Any]:
        latest_context_time = self.db.scalar(select(func.max(MarketFeatureContext15m1h.feature_15m_window_close_time)))
        total_context_rows = self.db.scalar(select(func.count()).select_from(MarketFeatureContext15m1h)) or 0
        rows = self.db.execute(
            select(MarketFeatureContext15m1h.context_status, func.count()).group_by(
                MarketFeatureContext15m1h.context_status
            )
        ).all()
        counts = {status: 0 for status in CONTEXT_STATUSES}
        for status, count in rows:
            counts[status] = count
        latest_symbols_count = 0
        if latest_context_time is not None:
            latest_symbols_count = (
                self.db.scalar(
                    select(func.count(func.distinct(MarketFeatureContext15m1h.symbol))).where(
                        MarketFeatureContext15m1h.feature_15m_window_close_time == latest_context_time,
                        MarketFeatureContext15m1h.context_status.in_(("CONTEXT_READY", "CONTEXT_PARTIAL")),
                    )
                )
                or 0
            )
        return {
            "latest_context_time": latest_context_time,
            "total_context_rows": total_context_rows,
            "context_ready_count": counts["CONTEXT_READY"],
            "context_partial_count": counts["CONTEXT_PARTIAL"],
            "context_blocked_count": counts["CONTEXT_BLOCKED"],
            "latest_symbols_count": latest_symbols_count,
        }

    def list_contexts(self, status: str | None = None, limit: int = 100) -> list[MarketFeatureContext15m1h]:
        query = select(MarketFeatureContext15m1h).order_by(
            desc(MarketFeatureContext15m1h.feature_15m_window_close_time),
            MarketFeatureContext15m1h.symbol,
        )
        if status:
            query = query.where(MarketFeatureContext15m1h.context_status == status)
        return list(self.db.scalars(query.limit(min(max(limit, 1), 500))).all())

    def _join_window(self, feature_15m: MarketFeature15m, now: datetime) -> dict[str, Any]:
        context_1h = self._nearest_closed_1h(feature_15m.symbol, _as_utc(feature_15m.window_close_time))
        reasons: list[str] = []

        if feature_15m.feature_status not in USABLE_FEATURE_STATUSES:
            reasons.append(f"15m feature status {feature_15m.feature_status}")
        if context_1h is None:
            reasons.append("missing closed 1h context")
        else:
            if context_1h.feature_status not in USABLE_FEATURE_STATUSES:
                reasons.append(f"1h feature status {context_1h.feature_status}")
            if _as_utc(context_1h.window_close_time) > _as_utc(feature_15m.window_close_time):
                reasons.append("1h context is future relative to 15m")
            if _as_utc(context_1h.window_open_time) >= _as_utc(feature_15m.window_close_time):
                reasons.append("1h context open time is not before 15m close")

        context_status = "CONTEXT_BLOCKED" if reasons else "CONTEXT_READY"
        return {
            "symbol": feature_15m.symbol,
            "feature_15m_window_open_time": feature_15m.window_open_time,
            "feature_15m_window_close_time": feature_15m.window_close_time,
            "context_1h_window_open_time": context_1h.window_open_time if context_1h else None,
            "context_1h_window_close_time": context_1h.window_close_time if context_1h else None,
            "feature_15m_status": feature_15m.feature_status,
            "feature_1h_status": context_1h.feature_status if context_1h else None,
            "context_status": context_status,
            "context_block_reason": "; ".join(reasons) if reasons else None,
            "price_return_pct_15m": feature_15m.price_return_pct,
            "range_pct_15m": feature_15m.range_pct,
            "close_position_15m": feature_15m.close_position,
            "kline_taker_buy_ratio_15m": feature_15m.kline_taker_buy_ratio,
            "oi_change_pct_15m": feature_15m.oi_change_pct,
            "global_long_short_ratio_15m": feature_15m.global_long_short_ratio,
            "top_trader_position_ratio_15m": feature_15m.top_trader_position_ratio,
            "funding_status_15m": feature_15m.funding_status,
            "price_return_pct_1h": context_1h.price_return_pct if context_1h else None,
            "range_pct_1h": context_1h.range_pct if context_1h else None,
            "close_position_1h": context_1h.close_position if context_1h else None,
            "kline_taker_buy_ratio_1h": context_1h.kline_taker_buy_ratio if context_1h else None,
            "oi_change_pct_1h": context_1h.oi_change_pct if context_1h else None,
            "global_long_short_ratio_1h": context_1h.global_long_short_ratio if context_1h else None,
            "top_trader_position_ratio_1h": context_1h.top_trader_position_ratio if context_1h else None,
            "funding_status_1h": context_1h.funding_status if context_1h else None,
            "created_at": now,
            "updated_at": now,
        }

    def _feature_15m_windows(self, symbol: str, limit_windows: int | None) -> list[MarketFeature15m]:
        query = (
            select(MarketFeature15m)
            .where(MarketFeature15m.symbol == symbol)
            .order_by(desc(MarketFeature15m.window_open_time))
        )
        if limit_windows:
            query = query.limit(limit_windows)
        rows = list(self.db.scalars(query).all())
        rows.reverse()
        return rows

    def _nearest_closed_1h(self, symbol: str, feature_15m_close: datetime) -> MarketFeature1h | None:
        return self.db.scalar(
            select(MarketFeature1h)
            .where(
                MarketFeature1h.symbol == symbol,
                MarketFeature1h.window_close_time <= feature_15m_close,
            )
            .order_by(desc(MarketFeature1h.window_close_time))
            .limit(1)
        )

    def _upsert(self, payload: dict[str, Any], dry_run: bool) -> str:
        row = self.db.scalar(
            select(MarketFeatureContext15m1h).where(
                MarketFeatureContext15m1h.symbol == payload["symbol"],
                MarketFeatureContext15m1h.feature_15m_window_open_time == payload["feature_15m_window_open_time"],
            )
        )
        if dry_run:
            return "updated" if row else "inserted"
        if row:
            for key, value in payload.items():
                if key != "created_at":
                    setattr(row, key, value)
            return "updated"
        self.db.add(MarketFeatureContext15m1h(**payload))
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


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
