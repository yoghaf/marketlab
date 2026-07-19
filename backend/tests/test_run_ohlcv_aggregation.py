from __future__ import annotations

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.models.market import CollectorError, CollectorRun
from scripts import run_ohlcv_aggregation


def test_failed_aggregation_rolls_back_before_persisting_error(monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)

    class FailingAggregationService:
        def __init__(self, _db) -> None:
            pass

        def run(self, **_kwargs):
            raise RuntimeError("controlled aggregation failure")

    monkeypatch.setattr(run_ohlcv_aggregation, "SessionLocal", Session)
    monkeypatch.setattr(
        run_ohlcv_aggregation,
        "OhlcvAggregationService",
        FailingAggregationService,
    )

    try:
        run_ohlcv_aggregation.run_cycle(
            timeframes=["15m"],
            markets=["futures"],
            symbols=None,
            limit_windows=1,
            dry_run=False,
        )
    except RuntimeError as exc:
        assert str(exc) == "controlled aggregation failure"
    else:
        raise AssertionError("controlled failure must propagate to the bounded runner")

    with Session() as db:
        run = db.scalar(select(CollectorRun))
        error = db.scalar(select(CollectorError))

    assert run is not None
    assert run.status == "ERROR"
    assert run.error_count == 1
    assert run.finished_at is not None
    assert run.duration_seconds is not None
    assert error is not None
    assert error.collector_run_id == run.id
    assert error.error_type == "RuntimeError"
    assert error.message == "controlled aggregation failure"
