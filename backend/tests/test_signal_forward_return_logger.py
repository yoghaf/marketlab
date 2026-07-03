from __future__ import annotations

import json
import tempfile
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.models.market import FuturesKline15m, SignalForwardReturnLog
from app.services.signal_forward_return_logger import OBSERVATION_EPOCH, PRE_OBSERVATION_EPOCH, SignalForwardReturnLogger


def test_forward_return_logger_upserts_signal_factory_artifact_without_duplicates() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with tempfile.TemporaryDirectory() as tmp:
        artifact_dir = Path(tmp)
        signal_close = datetime(2026, 1, 1, 0, 15)
        payload = {
            "generated_at": "2026-01-01T00:16:00Z",
            "items": [
                {
                    "symbol": "AAAUSDT",
                    "timeframe": "15m",
                    "window_start": "2026-01-01T00:00:00",
                    "window_end": "2026-01-01T00:15:00",
                    "setup_type": "EARLY_LONG",
                    "candidate_status": "SIGNAL_CANDIDATE",
                    "direction": "BULLISH_CONTEXT",
                    "core_score": 8,
                    "evidence_score": 1,
                    "evidence_confidence_tier": "HIGH_CONF",
                    "execution_risk_status": "ACTIVE",
                    "entry_mode": "MARKET_REFERENCE_OK",
                    "stop_loss_reference": "0.95",
                    "take_profit_reference": "1.10",
                    "entry_price": "1.00",
                    "evidence": {"evidence_data_completeness": 3},
                }
            ],
        }
        (artifact_dir / "candidates.json").write_text(json.dumps(payload))
        with Session() as db:
            db.add(
                FuturesKline15m(
                    symbol="AAAUSDT",
                    open_time=signal_close - timedelta(minutes=15),
                    close_time=signal_close,
                    open=Decimal("0.98"),
                    high=Decimal("1.01"),
                    low=Decimal("0.97"),
                    close=Decimal("1.00"),
                    volume=Decimal("100"),
                    source_interval="15m",
                    aggregation_status="AGG_READY",
                    actual_1m_count=15,
                    expected_1m_count=15,
                    missing_1m_count=0,
                    created_at=signal_close,
                    updated_at=signal_close,
                )
            )
            db.add(
                FuturesKline15m(
                    symbol="AAAUSDT",
                    open_time=signal_close,
                    close_time=signal_close + timedelta(minutes=15),
                    open=Decimal("1.00"),
                    high=Decimal("1.04"),
                    low=Decimal("0.99"),
                    close=Decimal("1.03"),
                    volume=Decimal("110"),
                    source_interval="15m",
                    aggregation_status="AGG_READY",
                    actual_1m_count=15,
                    expected_1m_count=15,
                    missing_1m_count=0,
                    created_at=signal_close,
                    updated_at=signal_close,
                )
            )
            db.commit()

            first = SignalForwardReturnLogger(db, artifact_dir=artifact_dir).run()
            second = SignalForwardReturnLogger(db, artifact_dir=artifact_dir).run()

            assert first.inserted_count == 1
            assert second.updated_count == 1
            assert db.query(SignalForwardReturnLog).count() == 1
            row = db.query(SignalForwardReturnLog).one()
            assert abs(row.price_at_signal - Decimal("1.00")) < Decimal("0.00000001")
            assert abs(row.price_at_15m - Decimal("1.03")) < Decimal("0.00000001")
            assert row.status_15m == "READY"
            assert row.status_1h == "WAITING_DATA"
            assert row.observation_epoch == PRE_OBSERVATION_EPOCH
            assert row.observation_marker is False


def test_forward_return_logger_marks_stage8_observation_epoch() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with tempfile.TemporaryDirectory() as tmp:
        artifact_dir = Path(tmp)
        payload = {
            "generated_at": "2026-07-03T06:15:20Z",
            "items": [
                {
                    "symbol": "BBBUSDT",
                    "timeframe": "15m",
                    "window_start": "2026-07-03T06:00:00",
                    "window_end": "2026-07-03T06:15:00",
                    "setup_type": "EARLY_SHORT",
                    "candidate_status": "SIGNAL_CANDIDATE",
                    "direction": "BEARISH_CONTEXT",
                    "evidence": {"evidence_data_completeness": 4},
                }
            ],
        }
        (artifact_dir / "candidates.json").write_text(json.dumps(payload))
        with Session() as db:
            SignalForwardReturnLogger(db, artifact_dir=artifact_dir).run()
            row = db.query(SignalForwardReturnLog).one()
            assert row.observation_epoch == OBSERVATION_EPOCH
            assert row.observation_marker is True
            assert row.observation_start_utc == datetime(2026, 7, 3, 6, 15, 20)
