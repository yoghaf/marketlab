from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.api import routes
from app.db.base import Base
from app.models.market import DataHealthSnapshot, MarketlabActiveUniverse


def test_data_health_uses_bounded_set_based_queries_for_active_universe() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    now = datetime(2026, 7, 22, tzinfo=UTC)

    with Session() as db:
        for rank in range(1, 76):
            symbol = f"TOKEN{rank}USDT"
            db.add(
                MarketlabActiveUniverse(
                    symbol=symbol,
                    rank=rank,
                    quote_volume=Decimal("1000000"),
                    collection_tier="FULL_ACTIVE",
                    is_full_active=True,
                    is_light_watch=False,
                    is_signal_eligible=True,
                    is_active=True,
                    entered_at=now,
                    exited_at=None,
                    last_seen_at=now,
                    created_at=now,
                    updated_at=now,
                )
            )
            db.add(
                DataHealthSnapshot(
                    symbol=symbol,
                    snapshot_time=now,
                    status="READY",
                    latest_futures_candle_time=now,
                    latest_spot_candle_time=now,
                    latest_open_interest_time=now,
                    latest_funding_time=now,
                    latest_futures_book_time=None,
                    latest_spot_book_time=None,
                    reason="all required datasets fresh",
                    raw_json={"status": "READY", "reason": "all required datasets fresh"},
                    created_at=now,
                    updated_at=now,
                )
            )
        db.commit()

        query_count = 0

        def count_query(*_args, **_kwargs) -> None:
            nonlocal query_count
            query_count += 1

        routes._DATA_HEALTH_CACHE.clear()
        event.listen(engine, "before_cursor_execute", count_query)
        try:
            payload = routes.data_health(db)
            cold_query_count = query_count
            cached_payload = routes.data_health(db)
            cached_query_count = query_count - cold_query_count
        finally:
            event.remove(engine, "before_cursor_execute", count_query)

    assert len(payload["items"]) == 75
    assert payload["universe"]["active_universe_count"] == 75
    assert payload["counts"]["READY"] == 75
    assert payload["rich_counts"]["RICH_MISSING"] == 75
    assert cold_query_count < 45
    assert cached_query_count == 0
    assert cached_payload == payload


def test_latest_health_item_is_selected_without_per_symbol_queries() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    old = datetime(2026, 7, 22, 0, 0, tzinfo=UTC)
    new = datetime(2026, 7, 22, 0, 5, tzinfo=UTC)

    with Session() as db:
        db.add(
            MarketlabActiveUniverse(
                symbol="BTCUSDT",
                rank=1,
                quote_volume=Decimal("1000000"),
                collection_tier="FULL_ACTIVE",
                is_full_active=True,
                is_light_watch=False,
                is_signal_eligible=False,
                is_active=True,
                entered_at=old,
                exited_at=None,
                last_seen_at=new,
                created_at=old,
                updated_at=new,
            )
        )
        for timestamp, status in ((old, "STALE"), (new, "READY")):
            db.add(
                DataHealthSnapshot(
                    symbol="BTCUSDT",
                    snapshot_time=timestamp,
                    status=status,
                    latest_futures_candle_time=timestamp,
                    latest_spot_candle_time=timestamp,
                    latest_open_interest_time=timestamp,
                    latest_funding_time=timestamp,
                    latest_futures_book_time=None,
                    latest_spot_book_time=None,
                    reason=status.lower(),
                    raw_json={"status": status, "reason": status.lower()},
                    created_at=timestamp,
                    updated_at=timestamp,
                )
            )
        db.commit()

        items = routes._latest_health_items(db)

    assert len(items) == 1
    assert items[0]["status"] == "READY"
    assert items[0]["snapshot_time"] == new.replace(tzinfo=None).isoformat()


def test_active_universe_count_does_not_depend_on_health_snapshot_presence() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    now = datetime(2026, 7, 22, tzinfo=UTC)

    with Session() as db:
        db.add(
            MarketlabActiveUniverse(
                symbol="NEWUSDT",
                rank=75,
                quote_volume=Decimal("1000000"),
                collection_tier="FULL_ACTIVE",
                is_full_active=True,
                is_light_watch=False,
                is_signal_eligible=True,
                is_active=True,
                entered_at=now,
                exited_at=None,
                last_seen_at=now,
                created_at=now,
                updated_at=now,
            )
        )
        db.commit()
        routes._DATA_HEALTH_CACHE.clear()
        payload = routes.data_health(db)

    assert payload["items"] == []
    assert payload["universe"]["active_universe_count"] == 1
