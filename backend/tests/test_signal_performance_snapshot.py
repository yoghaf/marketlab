from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.models.market import FuturesKline1m, SignalForwardReturnLog
from app.services.signal_forward_return_logger import OBSERVATION_EPOCH
from app.services.signal_performance_snapshot import (
    FORWARD_INTEGRITY_FILE,
    FORWARD_INTEGRITY_1H_FILE,
    MID_SHORT_ENTRY_CONFIRMATION_1H_FILE,
    MID_SHORT_FAILURE_ANATOMY_1H_FILE,
    MID_SHORT_FILTER_COMBO_1H_FILE,
    MID_SHORT_SECOND_FILTER_1H_FILE,
    MID_SHORT_SHADOW_FORWARD_1H_FILE,
    MID_SHORT_STRUCTURE_ZONE_1H_FILE,
    MID_SHORT_TAKER_SELL_DEEP_DIVE_1H_FILE,
    MID_SHORT_V21_DYNAMIC_EXIT_1H_FILE,
    MID_SHORT_V21_STRUCTURE_EXIT_1H_FILE,
    MID_SHORT_V21_STRUCTURE_INTERACTION_1H_FILE,
    MID_SHORT_VOLUME_SAFE_1H_FILE,
    MID_SHORT_WRONG_DIRECTION_DEEP_DIVE_1H_FILE,
    PERFORMANCE_COMPACT_FILE,
    PERFORMANCE_FILE,
    PERFORMANCE_1H_COMPACT_FILE,
    PERFORMANCE_1H_FILE,
    QUALITY_LAB_FILE,
    SignalPerformanceSnapshotRunner,
    SignalPerformanceSnapshotService,
)
from app.services.structure_zone_shadow import ZoneCandle, classify_directional_structure


def test_breakout_state_diagnostics_are_pre_entry_zone_metrics() -> None:
    signal_time = datetime(2026, 1, 1, 12, 0)
    prior = ZoneCandle(
        open_time=signal_time - timedelta(hours=1),
        close_time=signal_time - timedelta(minutes=1),
        open=Decimal("99"),
        high=Decimal("101"),
        low=Decimal("98"),
        close=Decimal("100"),
    )
    signal = ZoneCandle(
        open_time=signal_time,
        close_time=signal_time + timedelta(hours=1),
        open=Decimal("100"),
        high=Decimal("104"),
        low=Decimal("99"),
        close=Decimal("103"),
    )
    zone = {
        "center": Decimal("100"),
        "lower": Decimal("99"),
        "upper": Decimal("101"),
        "touch_count": 3,
        "support_touch_count": 1,
        "resistance_touch_count": 2,
        "first_touch_time": signal_time - timedelta(hours=10),
        "last_touch_time": signal_time - timedelta(hours=2),
    }
    next_resistance = {
        "center": Decimal("110"),
        "lower": Decimal("109"),
        "upper": Decimal("111"),
        "touch_count": 2,
        "support_touch_count": 0,
        "resistance_touch_count": 2,
        "first_touch_time": signal_time - timedelta(hours=8),
        "last_touch_time": signal_time - timedelta(hours=3),
    }

    result = classify_directional_structure(
        timeframe="1h",
        direction="LONG",
        entry=Decimal("102"),
        signal_candle=signal,
        prior_candle=prior,
        closed_candles=[prior, signal],
        zones=[zone, next_resistance],
        atr=Decimal("10"),
    )

    diagnostics = result["breakout_state_diagnostics"]
    assert diagnostics["status"] == "ZONE_DIAGNOSTICS_AVAILABLE"
    assert diagnostics["zone_upper"] == Decimal("101")
    assert diagnostics["close_penetration_atr"] == Decimal("0.2")
    assert diagnostics["close_penetration_zone_width"] == Decimal("1")
    assert diagnostics["body_above_zone_ratio"] == Decimal("0.6666666666666666666666666667")
    assert diagnostics["upper_wick_to_body_ratio"] == Decimal("0.3333333333333333333333333333")
    assert diagnostics["bars_since_breakout"] == 0
    assert diagnostics["entry_distance_from_zone_atr"] == Decimal("0.1")
    assert diagnostics["room_to_next_resistance_atr"] == Decimal("0.7")
    assert diagnostics["no_future_data"] is True


def test_signal_performance_snapshot_writes_and_reads_default_payloads(tmp_path) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as db:
        signal_time = datetime(2026, 1, 1, 0, 15)
        db.add(_signal("s1", "AAAUSDT", signal_time, "LONG", "EARLY_LONG", "100", "90", "115"))
        db.add(_signal("s2", "BBBUSDT", signal_time, "SHORT", "MID_SHORT", "100", "110", "85", timeframe="1h"))
        db.add(_signal("s3", "CCCUSDT", signal_time, "LONG", "MID_LONG", "100", "90", "115", timeframe="1h"))
        db.add(_candle("AAAUSDT", signal_time, signal_time + timedelta(minutes=15), high="116", low="99", close="115"))
        db.add(_candle("BBBUSDT", signal_time, signal_time + timedelta(minutes=15), high="101", low="84", close="85"))
        db.add(_candle("CCCUSDT", signal_time, signal_time + timedelta(minutes=15), high="116", low="99", close="115"))
        db.commit()

        result = SignalPerformanceSnapshotRunner(db, artifact_dir=tmp_path).run(
            performance_limit=25,
            forward_integrity_limit=25,
        )
        research_result = SignalPerformanceSnapshotRunner(db, artifact_dir=tmp_path).run(
            performance_limit=25,
            forward_integrity_limit=25,
            scope="mid-short-research",
        )

    assert result["performance_items"] == 3
    assert result["performance_1h_items"] == 2
    assert research_result["scope"] == "mid-short-research"
    assert research_result["mid_short_research_artifacts"] == 11
    assert (tmp_path / PERFORMANCE_FILE).exists()
    assert (tmp_path / PERFORMANCE_COMPACT_FILE).exists()
    assert (tmp_path / FORWARD_INTEGRITY_FILE).exists()
    assert (tmp_path / QUALITY_LAB_FILE).exists()
    assert (tmp_path / PERFORMANCE_1H_FILE).exists()
    assert (tmp_path / PERFORMANCE_1H_COMPACT_FILE).exists()
    assert (tmp_path / FORWARD_INTEGRITY_1H_FILE).exists()
    assert (tmp_path / MID_SHORT_FILTER_COMBO_1H_FILE).exists()
    assert (tmp_path / MID_SHORT_SHADOW_FORWARD_1H_FILE).exists()
    assert (tmp_path / MID_SHORT_FAILURE_ANATOMY_1H_FILE).exists()
    assert (tmp_path / MID_SHORT_SECOND_FILTER_1H_FILE).exists()
    assert (tmp_path / MID_SHORT_TAKER_SELL_DEEP_DIVE_1H_FILE).exists()
    assert (tmp_path / MID_SHORT_WRONG_DIRECTION_DEEP_DIVE_1H_FILE).exists()
    assert (tmp_path / MID_SHORT_ENTRY_CONFIRMATION_1H_FILE).exists()
    assert (tmp_path / MID_SHORT_STRUCTURE_ZONE_1H_FILE).exists()
    assert (tmp_path / MID_SHORT_V21_STRUCTURE_INTERACTION_1H_FILE).exists()
    assert (tmp_path / MID_SHORT_V21_STRUCTURE_EXIT_1H_FILE).exists()
    assert (tmp_path / MID_SHORT_V21_DYNAMIC_EXIT_1H_FILE).exists()
    assert (tmp_path / MID_SHORT_VOLUME_SAFE_1H_FILE).exists()
    assert not (tmp_path / f"{PERFORMANCE_FILE}.tmp").exists()

    service = SignalPerformanceSnapshotService(artifact_dir=tmp_path)
    performance = service.performance(limit=1)
    performance_1h = service.performance_1h(limit=1)
    integrity = service.forward_integrity(limit=1)
    integrity_1h = service.forward_integrity_1h(limit=1)
    quality_lab = service.quality_lab(limit=1)
    one_hour_filter = service.one_hour_filter_candidate_study(min_sample=1, limit=5)
    one_hour_walk_forward = service.one_hour_walk_forward_study(min_sample=1, limit=5)
    one_hour_v4_shadow = service.one_hour_v4_shadow_monitor(min_sample=1, limit=5)
    mid_short_combo = service.mid_short_filter_combination_1h(limit=5)
    mid_short_dynamic_exit = service.research_snapshot(MID_SHORT_V21_DYNAMIC_EXIT_1H_FILE, limit=5)
    baseline = service.mid_long_1h_baseline(limit=5)
    v3_filter_map = service.v3_shadow_filter_map()

    assert performance["cache"]["source"] == "artifact_snapshot"
    assert performance["snapshot"]["read_model"] == "artifact_snapshot"
    assert performance["snapshot"]["filename"] == PERFORMANCE_COMPACT_FILE
    assert performance["filters"]["limit"] == 1
    assert performance["aggregate"]["tp_count"] == 3
    assert len(performance["items"]) == 1
    assert performance_1h["snapshot"]["filename"] == PERFORMANCE_1H_COMPACT_FILE
    assert performance_1h["filters"]["timeframe"] == "1h"
    assert performance_1h["aggregate"]["tp_count"] == 2
    assert len(performance_1h["items"]) == 1
    assert integrity["cache"]["source"] == "artifact_snapshot"
    assert integrity["snapshot"]["filename"] == FORWARD_INTEGRITY_FILE
    assert integrity_1h["snapshot"]["filename"] == FORWARD_INTEGRITY_1H_FILE
    assert quality_lab["cache"]["source"] == "artifact_snapshot"
    assert quality_lab["snapshot"]["filename"] == QUALITY_LAB_FILE
    assert one_hour_filter["source"] == "signal_performance_snapshot_1h"
    assert one_hour_filter["snapshot"]["filename"] == PERFORMANCE_1H_FILE
    assert one_hour_filter["filters"]["timeframe"] == "1h"
    assert len(one_hour_filter["lanes"]) == 2
    assert one_hour_walk_forward["source"] == "signal_performance_snapshot_1h"
    assert one_hour_walk_forward["snapshot"]["filename"] == PERFORMANCE_1H_FILE
    assert one_hour_walk_forward["split_method"] == "chronological_70_30"
    assert len(one_hour_walk_forward["lanes"]) == 2
    assert one_hour_v4_shadow["source"] == "signal_performance_snapshot_1h"
    assert one_hour_v4_shadow["snapshot"]["filename"] == PERFORMANCE_1H_FILE
    assert one_hour_v4_shadow["study_scope"] == "one_hour_v4_shadow_forward_monitor_read_only"
    assert one_hour_v4_shadow["summary"]["read"] == "V4_NO_FILTER_SELECTED"
    assert mid_short_combo["cache"]["source"] == "artifact_snapshot"
    assert mid_short_combo["snapshot"]["filename"] == MID_SHORT_FILTER_COMBO_1H_FILE
    assert mid_short_combo["artifact_type"] == "mid_short_1h_filter_combination_study"
    assert mid_short_combo["filters"]["stage"] == "MID_SHORT"
    assert "combination_rows" in mid_short_combo
    assert mid_short_dynamic_exit["cache"]["source"] == "artifact_snapshot"
    assert mid_short_dynamic_exit["snapshot"]["filename"] == MID_SHORT_V21_DYNAMIC_EXIT_1H_FILE
    assert mid_short_dynamic_exit["artifact_type"] == "mid_short_1h_v21_dynamic_exit_study"
    assert baseline["baseline_id"] == "MID_LONG_1H_V2_BASELINE"
    assert baseline["closed_only_snapshot"] is True
    assert baseline["snapshot_coverage"]["mid_long_1h_rows"] == 1
    assert baseline["snapshot_coverage"]["is_truncated"] is False
    assert baseline["aggregate"]["tp_count"] == 1
    assert baseline["filters"]["position_lock"] is True
    assert baseline["filters"]["result_status"] == "closed"
    assert baseline["rr_distribution"] == {"1.5R": 1}
    assert baseline["research_summary"]["read"] in {
        "BASELINE_POSITIVE",
        "BASELINE_WEAK_SL_DOMINANT",
        "BASELINE_MIXED",
    }
    assert "evidence_comparison" in baseline
    assert "entry_combination_ranking" in baseline
    assert "entry_anatomy_summary" in baseline
    assert "outcome_entry_profiles" in baseline
    assert "entry_area_anatomy" in baseline
    assert "path_anatomy" in baseline
    assert "taxonomy_study" in baseline["definition_audit"]
    assert baseline["definition_audit"]["taxonomy_study"]["canonical_acceptance_threshold_r"] == Decimal("0.50")
    assert "setup_family" in baseline["definition_audit"]["taxonomy_study"]["dimension_rows"]
    assert "path_sequence_rows" in baseline["definition_audit"]["taxonomy_study"]
    assert "draft_v21_previews" in baseline["definition_audit"]["taxonomy_study"]
    assert "integrity_audit" in baseline["definition_audit"]
    assert "path_economics_rows" in baseline["definition_audit"]["integrity_audit"]
    assert "damage_isolation" in baseline["definition_audit"]
    assert len(baseline["definition_audit"]["damage_isolation"]["experiment_rows"]) == 6
    assert "mid_range_interactions" in baseline["definition_audit"]["damage_isolation"]
    assert "sub_setup_split_lab" in baseline["definition_audit"]
    assert "rows" in baseline["definition_audit"]["sub_setup_split_lab"]
    assert baseline["definition_audit"]["sub_setup_split_lab"]["summary"]["read"] in {
        "SUB_SETUP_CANDIDATE_FOUND",
        "SUB_SETUP_WATCH_ONLY",
        "NO_SUB_SETUP_READY",
    }
    assert "breakout_accepted_deep_dive" in baseline["definition_audit"]
    breakout_deep_dive = baseline["definition_audit"]["breakout_accepted_deep_dive"]
    assert "field_availability_rows" in breakout_deep_dive
    field_sources = {row["field"]: row["source"] for row in breakout_deep_dive["field_availability_rows"]}
    assert field_sources["close_penetration_atr"] == "precise_zone_metric"
    assert field_sources["body_above_zone_ratio"] == "precise_zone_metric"
    assert field_sources["room_to_next_resistance_atr"] == "precise_zone_metric"
    assert "mechanism_rows" in breakout_deep_dive
    assert "single_filter_rows" in breakout_deep_dive
    assert "draft_cohort_rows" in breakout_deep_dive
    assert breakout_deep_dive["summary"]["read"] in {
        "NO_BREAKOUT_SAMPLE",
        "BREAKOUT_PROXY_ONLY",
        "BREAKOUT_DRAFT_READY_FOR_VALIDATION",
        "BREAKOUT_FILTER_WATCH_ONLY",
        "BREAKOUT_NOT_IMPROVING",
    }
    assert len(baseline["items"]) == 1
    assert ("EARLY_LONG", "15m") in v3_filter_map
    assert ("MID_SHORT", "1h") in v3_filter_map


def test_signal_performance_snapshot_scopes_do_not_rewrite_unrequested_artifacts(tmp_path) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as db:
        default_result = SignalPerformanceSnapshotRunner(db, artifact_dir=tmp_path).run(
            performance_limit=1,
            forward_integrity_limit=1,
            scope="default",
        )

        assert default_result["scope"] == "default"
        assert (tmp_path / PERFORMANCE_FILE).exists()
        assert (tmp_path / PERFORMANCE_COMPACT_FILE).exists()
        assert (tmp_path / FORWARD_INTEGRITY_FILE).exists()
        assert (tmp_path / QUALITY_LAB_FILE).exists()
        assert not (tmp_path / PERFORMANCE_1H_FILE).exists()
        assert not (tmp_path / FORWARD_INTEGRITY_1H_FILE).exists()

        default_mtime = (tmp_path / PERFORMANCE_FILE).stat().st_mtime_ns
        one_hour_result = SignalPerformanceSnapshotRunner(db, artifact_dir=tmp_path).run(
            performance_limit=1,
            forward_integrity_limit=1,
            scope="one-hour",
        )

    assert one_hour_result["scope"] == "one-hour"
    assert (tmp_path / PERFORMANCE_1H_FILE).exists()
    assert (tmp_path / PERFORMANCE_1H_COMPACT_FILE).exists()
    assert (tmp_path / FORWARD_INTEGRITY_1H_FILE).exists()
    assert (tmp_path / MID_SHORT_FILTER_COMBO_1H_FILE).exists()
    assert not (tmp_path / MID_SHORT_V21_DYNAMIC_EXIT_1H_FILE).exists()
    assert (tmp_path / PERFORMANCE_FILE).stat().st_mtime_ns == default_mtime

    with Session() as db:
        research_result = SignalPerformanceSnapshotRunner(db, artifact_dir=tmp_path).run(
            performance_limit=1,
            forward_integrity_limit=1,
            scope="mid-short-research",
        )

    assert research_result["scope"] == "mid-short-research"
    assert (tmp_path / MID_SHORT_V21_DYNAMIC_EXIT_1H_FILE).exists()
    assert (tmp_path / PERFORMANCE_FILE).stat().st_mtime_ns == default_mtime


def _signal(
    signal_id: str,
    symbol: str,
    signal_time: datetime,
    direction: str,
    stage: str,
    entry: str,
    stop: str,
    target: str,
    timeframe: str = "15m",
) -> SignalForwardReturnLog:
    now = datetime(2026, 1, 1, 0, 0)
    return SignalForwardReturnLog(
        signal_id=signal_id,
        symbol=symbol,
        timeframe=timeframe,
        signal_timestamp=signal_time,
        window_open_time=signal_time - timedelta(minutes=15),
        window_close_time=signal_time,
        direction=direction,
        stage=stage,
        candidate_status="SIGNAL_CANDIDATE",
        core_score=Decimal("8"),
        evidence_score=Decimal("1"),
        evidence_data_completeness=4,
        confidence_tier="HIGH_CONF",
        execution_flag="ACTIVE",
        entry_ref="MARKET_REFERENCE_OK",
        sl_ref=Decimal(stop),
        tp_ref=Decimal(target),
        price_at_signal=Decimal(entry),
        status_15m="READY",
        status_1h="WAITING_DATA",
        status_4h="WAITING_DATA",
        status_24h="WAITING_DATA",
        observation_epoch=OBSERVATION_EPOCH,
        observation_start_utc=now,
        observation_marker=True,
        evidence={},
        created_at=now,
        updated_at=now,
    )


def _candle(
    symbol: str,
    open_time: datetime,
    close_time: datetime,
    *,
    high: str,
    low: str,
    close: str,
) -> FuturesKline1m:
    return FuturesKline1m(
        symbol=symbol,
        open_time=open_time,
        close_time=close_time,
        open_price=Decimal("100"),
        high_price=Decimal(high),
        low_price=Decimal(low),
        close_price=Decimal(close),
        volume=Decimal("100"),
        trade_count=1,
        created_at=open_time,
        updated_at=open_time,
    )
