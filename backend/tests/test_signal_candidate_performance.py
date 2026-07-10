from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.models.market import FuturesKline1m, MarketlabActiveUniverse, SignalForwardReturnLog
from app.services.signal_candidate_performance import (
    FilterStudySpec,
    SignalCandidatePerformanceService,
    signal_factory_v3_shadow_for_candidate,
)
from app.services.signal_forward_return_logger import OBSERVATION_EPOCH


def test_live_performance_counts_tp_open_and_position_lock() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as db:
        first_time = datetime(2026, 1, 1, 0, 15)
        second_time = datetime(2026, 1, 1, 0, 20)
        db.add(_signal("s1", "AAAUSDT", first_time, "LONG", "EARLY_LONG", "100", "90", "115"))
        db.add(_signal("s2", "AAAUSDT", second_time, "LONG", "EARLY_LONG", "101", "91", "116"))
        db.add(_signal("s3", "BBBUSDT", first_time, "SHORT", "MID_SHORT", "100", "110", "85"))
        db.add(
            _candle(
                "AAAUSDT",
                first_time,
                first_time + timedelta(minutes=15),
                high="116",
                low="99",
                close="115",
            )
        )
        db.add(
            _candle(
                "BBBUSDT",
                first_time,
                first_time + timedelta(minutes=15),
                high="105",
                low="95",
                close="98",
            )
        )
        db.commit()

        payload = SignalCandidatePerformanceService(db).summary(position_lock=True)

        aggregate = payload["aggregate"]
        assert aggregate["signals_evaluated"] == 2
        assert aggregate["signals_skipped"] == 1
        assert aggregate["tp_count"] == 1
        assert aggregate["open_count"] == 1
        assert aggregate["winrate_pct"] == Decimal("100")
        assert aggregate["total_r_closed"] == Decimal("1.5")
        assert aggregate["open_unrealized_r"] == Decimal("0.2")
        assert aggregate["fixed_risk_return_pct_1pct_closed"] == Decimal("1.5")
        assert aggregate["fixed_risk_return_pct_1pct_with_open"] == Decimal("1.7")
        tf = aggregate["by_timeframe_performance"]["15m"]
        assert tf["signals_evaluated"] == 2
        assert tf["tp_count"] == 1
        assert tf["open_count"] == 1
        assert tf["total_r_closed"] == Decimal("1.5")
        assert aggregate["by_timeframe_performance"]["4h"]["signals_evaluated"] == 0


def test_watch_only_filter_can_include_or_exclude_rows() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as db:
        signal_time = datetime(2026, 1, 1, 0, 15)
        db.add(_signal("s1", "AAAUSDT", signal_time, "LONG", "EARLY_LONG", "100", "90", "115", execution="WATCH_ONLY"))
        db.add(_candle("AAAUSDT", signal_time, signal_time + timedelta(minutes=15), high="116", low="99", close="115"))
        db.commit()

        excluded = SignalCandidatePerformanceService(db).summary(include_watch_only=False)
        included = SignalCandidatePerformanceService(db).summary(include_watch_only=True)

        assert excluded["aggregate"]["signals_evaluated"] == 0
        assert included["aggregate"]["signals_evaluated"] == 1
        assert included["aggregate"]["tp_count"] == 1


def test_summary_can_filter_closed_only_rows() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as db:
        first_time = datetime(2026, 1, 1, 0, 15)
        second_time = datetime(2026, 1, 1, 0, 30)
        db.add(_signal("s1", "AAAUSDT", first_time, "LONG", "EARLY_LONG", "100", "90", "115"))
        db.add(_signal("s2", "BBBUSDT", second_time, "SHORT", "MID_SHORT", "100", "110", "85"))
        db.add(_candle("AAAUSDT", first_time, first_time + timedelta(minutes=15), high="116", low="99", close="115"))
        db.add(_candle("BBBUSDT", second_time, second_time + timedelta(minutes=15), high="105", low="95", close="98"))
        db.commit()

        payload = SignalCandidatePerformanceService(db).summary(position_lock=False, result_status="closed")

        assert payload["aggregate"]["signals_evaluated"] == 1
        assert payload["aggregate"]["tp_count"] == 1
        assert payload["aggregate"]["open_count"] == 0
        assert payload["items"][0]["signal_id"] == "s1"


def test_realistic_execution_adds_fee_spread_and_slippage_penalty() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as db:
        signal_time = datetime(2026, 1, 1, 0, 15)
        db.add(
            _signal(
                "tp",
                "AAAUSDT",
                signal_time,
                "LONG",
                "EARLY_LONG",
                "100",
                "90",
                "115",
                evidence={"futures_spread_pct": "0.10"},
            )
        )
        db.add(_candle("AAAUSDT", signal_time, signal_time + timedelta(minutes=15), high="116", low="99", close="115"))
        db.commit()

        payload = SignalCandidatePerformanceService(db).summary(position_lock=False)

        item = payload["items"][0]
        assert item["result_status"] == "TP_HIT"
        assert item["realized_r"] == Decimal("1.5")
        assert item["realistic_model_version"] == "REALISTIC_PAPER_EXECUTION_V1"
        assert item["realistic_fill_quality"] == "FILL_GOOD"
        assert item["realistic_realized_r"] < item["realized_r"]
        assert item["realism_penalty_r"] > Decimal("0")
        assert payload["aggregate"]["realistic_total_r_closed"] < payload["aggregate"]["total_r_closed"]
        assert payload["aggregate"]["realism_penalty_r_closed"] > Decimal("0")


def test_realistic_execution_marks_missing_spread_quality() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as db:
        signal_time = datetime(2026, 1, 1, 0, 15)
        db.add(_signal("tp", "AAAUSDT", signal_time, "LONG", "EARLY_LONG", "100", "90", "115"))
        db.add(_candle("AAAUSDT", signal_time, signal_time + timedelta(minutes=15), high="116", low="99", close="115"))
        db.commit()

        item = SignalCandidatePerformanceService(db).summary(position_lock=False)["items"][0]

        assert item["realistic_fill_quality"] == "SPREAD_UNKNOWN"
        assert item["realistic_spread_source"] == "missing"
        assert item["realistic_futures_spread_pct"] is None


def test_realistic_execution_treats_both_hit_same_candle_as_conservative_stop() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as db:
        signal_time = datetime(2026, 1, 1, 0, 15)
        db.add(
            _signal(
                "both",
                "AAAUSDT",
                signal_time,
                "LONG",
                "EARLY_LONG",
                "100",
                "90",
                "115",
                evidence={"futures_spread_pct": "0.10"},
            )
        )
        db.add(_candle("AAAUSDT", signal_time, signal_time + timedelta(minutes=15), high="116", low="89", close="100"))
        db.commit()

        item = SignalCandidatePerformanceService(db).summary(position_lock=False)["items"][0]

        assert item["result_status"] == "BOTH_HIT_SAME_CANDLE"
        assert item["realized_r"] == Decimal("0")
        assert item["realistic_result_status"] == "SL_HIT_CONSERVATIVE"
        assert item["realistic_realized_r"] < Decimal("-1")


def test_detail_returns_latest_symbol_signal_with_current_open_r() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as db:
        first_time = datetime(2026, 1, 1, 0, 15)
        second_time = datetime(2026, 1, 1, 0, 30)
        db.add(_signal("old", "AAAUSDT", first_time, "LONG", "EARLY_LONG", "100", "90", "115"))
        db.add(
            _signal(
                "latest",
                "AAAUSDT",
                second_time,
                "LONG",
                "MID_LONG",
                "100",
                "90",
                "115",
                evidence={"price_return": "1.25", "oi_zscore": "2.0"},
            )
        )
        db.add(_candle("AAAUSDT", second_time, second_time + timedelta(minutes=15), high="108", low="98", close="105"))
        db.commit()

        payload = SignalCandidatePerformanceService(db).detail(symbol="AAAUSDT", timeframe="15m")

        assert payload is not None
        assert payload["item"]["signal_id"] == "latest"
        assert payload["item"]["result_status"] == "OPEN"
        assert payload["item"]["unrealized_r"] == Decimal("0.5")
        assert payload["item"]["evidence_snapshot"]["price_return"] == Decimal("1.25")


def test_detail_can_load_exact_signal_id() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as db:
        first_time = datetime(2026, 1, 1, 0, 15)
        second_time = datetime(2026, 1, 1, 0, 30)
        db.add(_signal("old", "AAAUSDT", first_time, "LONG", "EARLY_LONG", "100", "90", "115"))
        db.add(_signal("latest", "AAAUSDT", second_time, "LONG", "MID_LONG", "100", "90", "115"))
        db.add(_candle("AAAUSDT", first_time, first_time + timedelta(minutes=15), high="116", low="99", close="115"))
        db.add(_candle("AAAUSDT", second_time, second_time + timedelta(minutes=15), high="108", low="98", close="105"))
        db.commit()

        payload = SignalCandidatePerformanceService(db).detail(signal_id="old")

        assert payload is not None
        assert payload["item"]["signal_id"] == "old"
        assert payload["item"]["result_status"] == "TP_HIT"


def test_open_signal_with_symbol_candle_behind_global_latest_is_marked_stale() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as db:
        stale_time = datetime(2026, 1, 1, 0, 15)
        fresh_time = stale_time + timedelta(hours=2)
        db.add(_signal("stale", "AAAUSDT", stale_time, "LONG", "EARLY_LONG", "100", "90", "115"))
        db.add(_signal("fresh", "BBBUSDT", fresh_time, "LONG", "MID_LONG", "100", "90", "115"))
        db.add(_candle("AAAUSDT", stale_time, stale_time + timedelta(minutes=15), high="108", low="98", close="105"))
        db.add(_candle("BBBUSDT", fresh_time, fresh_time + timedelta(minutes=15), high="108", low="98", close="105"))
        db.commit()

        payload = SignalCandidatePerformanceService(db).summary(position_lock=False, symbol="AAAUSDT")

        assert payload["aggregate"]["signals_evaluated"] == 1
        item = payload["items"][0]
        assert item["result_status"] == "STALE_FORWARD_DATA"
        assert item["stale_forward_data"] is True
        assert item["unrealized_r"] == Decimal("0.5")
        assert item["latest_symbol_candle_time"] == stale_time + timedelta(minutes=15)
        assert payload["aggregate"]["open_count"] == 0


def test_forward_integrity_separates_fresh_open_from_stale_forward_data() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as db:
        stale_time = datetime(2026, 1, 1, 0, 15)
        fresh_time = stale_time + timedelta(hours=2)
        db.add(_signal("stale", "AAAUSDT", stale_time, "LONG", "EARLY_LONG", "100", "90", "115"))
        db.add(_signal("fresh", "BBBUSDT", fresh_time, "LONG", "MID_LONG", "100", "90", "115"))
        db.add(_candle("AAAUSDT", stale_time, stale_time + timedelta(minutes=15), high="108", low="98", close="105"))
        db.add(_candle("BBBUSDT", fresh_time, fresh_time + timedelta(minutes=15), high="108", low="98", close="105"))
        db.commit()

        payload = SignalCandidatePerformanceService(db).forward_integrity(position_lock=False)

        summary = payload["summary"]
        assert summary["integrity_status"] == "STALE_FOUND"
        assert summary["fresh_open_count"] == 1
        assert summary["stale_forward_count"] == 1
        assert summary["active_or_pending_count"] == 2
        stale_item = next(item for item in payload["items"] if item["symbol"] == "AAAUSDT")
        assert stale_item["result_status"] == "STALE_FORWARD_DATA"
        assert stale_item["freshness_gap_minutes"] == Decimal("120")
        fresh_item = next(item for item in payload["items"] if item["symbol"] == "BBBUSDT")
        assert fresh_item["result_status"] == "OPEN"


def test_forward_integrity_does_not_report_closed_signal_as_open() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as db:
        signal_time = datetime(2026, 1, 1, 0, 15)
        db.add(_signal("closed", "AAAUSDT", signal_time, "SHORT", "MID_SHORT", "100", "110", "85"))
        db.add(_candle("AAAUSDT", signal_time, signal_time + timedelta(minutes=15), high="111", low="99", close="110"))
        db.commit()

        payload = SignalCandidatePerformanceService(db).forward_integrity(position_lock=False)

        assert payload["summary"]["active_or_pending_count"] == 0
        assert payload["summary"]["sl_count"] == 1
        assert payload["items"] == []


def test_quality_lab_groups_stage_confidence_and_drawdown() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as db:
        first_time = datetime(2026, 1, 1, 0, 15)
        second_time = datetime(2026, 1, 1, 0, 30)
        db.add(
            _signal(
                "s1",
                "AAAUSDT",
                first_time,
                "LONG",
                "EARLY_LONG",
                "100",
                "90",
                "115",
                evidence={"price_return": "2.5", "oi_zscore": "3.0", "kline_taker_buy_ratio": "0.70"},
            )
        )
        db.add(
            _signal(
                "s2",
                "BBBUSDT",
                second_time,
                "SHORT",
                "MID_SHORT",
                "100",
                "110",
                "85",
                evidence={"price_return": "-1.0", "oi_zscore": "0.5", "kline_taker_buy_ratio": "0.40"},
            )
        )
        db.add(_candle("AAAUSDT", first_time, first_time + timedelta(minutes=15), high="116", low="99", close="115"))
        db.add(_candle("BBBUSDT", second_time, second_time + timedelta(minutes=15), high="111", low="98", close="109"))
        db.commit()

        payload = SignalCandidatePerformanceService(db).quality_lab(position_lock=False, min_sample=1)

        assert payload["aggregate"]["signals_evaluated"] == 2
        assert payload["drawdown"]["total_r_closed"] == Decimal("0.5")
        assert payload["drawdown"]["max_drawdown_r"] == Decimal("-1.0")
        by_stage = {row["bucket"]: row for row in payload["by_stage"]}
        assert by_stage["EARLY_LONG"]["tp_count"] == 1
        assert by_stage["EARLY_LONG"]["median_r_closed"] == Decimal("1.5")
        assert by_stage["MID_SHORT"]["sl_count"] == 1
        evidence_by_field = {row["field"]: row for row in payload["evidence_fields"]}
        assert evidence_by_field["price_return"]["tp_median"] == Decimal("2.5")
        assert evidence_by_field["price_return"]["sl_median"] == Decimal("-1.0")
        assert evidence_by_field["price_return"]["delta_tp_minus_sl"] == Decimal("3.5")
        assert payload["best_signals"][0]["symbol"] == "AAAUSDT"
        assert payload["worst_signals"][0]["symbol"] == "BBBUSDT"


def test_quality_lab_reads_nested_forward_log_evidence() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as db:
        signal_time = datetime(2026, 1, 1, 0, 15)
        db.add(
            _signal(
                "s1",
                "AAAUSDT",
                signal_time,
                "LONG",
                "EARLY_LONG",
                "100",
                "90",
                "115",
                evidence={"evidence": {"price_return": "1.25", "volume_ratio_vs_lookback": "2.50"}},
            )
        )
        db.add(_candle("AAAUSDT", signal_time, signal_time + timedelta(minutes=15), high="116", low="99", close="115"))
        db.commit()

        payload = SignalCandidatePerformanceService(db).quality_lab(position_lock=False, min_sample=1)

        evidence_by_field = {row["field"]: row for row in payload["evidence_fields"]}
        assert evidence_by_field["price_return"]["available_count"] == 1
        assert evidence_by_field["price_return"]["tp_median"] == Decimal("1.25")
        assert evidence_by_field["volume_ratio_vs_lookback"]["tp_median"] == Decimal("2.50")


def test_quality_lab_groups_return_by_volume_rank_cutoffs() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as db:
        signal_time = datetime(2026, 1, 1, 0, 15)
        db.add(_universe("AAAUSDT", 3))
        db.add(_universe("BBBUSDT", 8))
        db.add(_universe("CCCUSDT", 18))
        db.add(_universe("DDDUSDT", 30))
        db.add(_signal("s1", "AAAUSDT", signal_time, "LONG", "EARLY_LONG", "100", "90", "115"))
        db.add(_signal("s2", "BBBUSDT", signal_time, "LONG", "EARLY_LONG", "100", "90", "115"))
        db.add(_signal("s3", "CCCUSDT", signal_time, "SHORT", "MID_SHORT", "100", "110", "85"))
        db.add(_signal("s4", "DDDUSDT", signal_time, "SHORT", "MID_SHORT", "100", "110", "85"))
        db.add(_candle("AAAUSDT", signal_time, signal_time + timedelta(minutes=15), high="116", low="99", close="115"))
        db.add(_candle("BBBUSDT", signal_time, signal_time + timedelta(minutes=15), high="116", low="99", close="115"))
        db.add(_candle("CCCUSDT", signal_time, signal_time + timedelta(minutes=15), high="105", low="84", close="86"))
        db.add(_candle("DDDUSDT", signal_time, signal_time + timedelta(minutes=15), high="111", low="99", close="109"))
        db.commit()

        payload = SignalCandidatePerformanceService(db).quality_lab(position_lock=False, min_sample=1)

        by_volume = {row["bucket"]: row for row in payload["by_volume_rank"]}
        assert by_volume["TOP_5_VOLUME"]["signals_evaluated"] == 1
        assert by_volume["TOP_5_VOLUME"]["total_r_closed"] == Decimal("1.5")
        assert by_volume["TOP_10_VOLUME"]["signals_evaluated"] == 2
        assert by_volume["TOP_20_VOLUME"]["signals_evaluated"] == 3
        assert by_volume["ALL_VOLUME"]["signals_evaluated"] == 4
        assert by_volume["ALL_VOLUME"]["total_r_closed"] == Decimal("3.5")


def test_filter_study_targets_mid_short_1h_and_ranks_filters() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as db:
        first_time = datetime(2026, 1, 1, 0, 15)
        second_time = datetime(2026, 1, 1, 0, 30)
        third_time = datetime(2026, 1, 1, 0, 45)
        ignored_time = datetime(2026, 1, 1, 1, 0)
        db.add(
            _signal(
                "s1",
                "AAAUSDT",
                first_time,
                "SHORT",
                "MID_SHORT",
                "100",
                "110",
                "85",
                timeframe="1h",
                evidence={"funding_percentile_30d": "82", "volume_ratio_vs_lookback": "1.20", "global_long_short_ratio": "1.30"},
            )
        )
        db.add(
            _signal(
                "s2",
                "BBBUSDT",
                second_time,
                "SHORT",
                "MID_SHORT",
                "100",
                "110",
                "85",
                timeframe="1h",
                evidence={"funding_percentile_30d": "55", "volume_ratio_vs_lookback": "2.10", "global_long_short_ratio": "1.00"},
            )
        )
        db.add(
            _signal(
                "s3",
                "CCCUSDT",
                third_time,
                "SHORT",
                "MID_SHORT",
                "100",
                "110",
                "85",
                timeframe="1h",
                evidence={"funding_percentile_30d": "90", "volume_ratio_vs_lookback": "1.10", "global_long_short_ratio": "1.40"},
            )
        )
        db.add(
            _signal(
                "ignored",
                "DDDUSDT",
                ignored_time,
                "LONG",
                "MID_LONG",
                "100",
                "90",
                "115",
                timeframe="1h",
                evidence={"funding_percentile_30d": "95", "volume_ratio_vs_lookback": "1.10", "global_long_short_ratio": "1.50"},
            )
        )
        db.add(_candle("AAAUSDT", first_time, first_time + timedelta(minutes=15), high="101", low="84", close="86"))
        db.add(_candle("BBBUSDT", second_time, second_time + timedelta(minutes=15), high="111", low="98", close="109"))
        db.add(_candle("CCCUSDT", third_time, third_time + timedelta(minutes=15), high="101", low="84", close="86"))
        db.add(_candle("DDDUSDT", ignored_time, ignored_time + timedelta(minutes=15), high="116", low="99", close="115"))
        db.commit()

        payload = SignalCandidatePerformanceService(db).filter_study(position_lock=False, min_sample=1)

        assert payload["filters"]["stage"] == "MID_SHORT"
        assert payload["filters"]["timeframe"] == "1h"
        assert payload["baseline"]["sample_count"] == 3
        assert payload["baseline"]["tp_count"] == 2
        assert payload["baseline"]["sl_count"] == 1
        rows = {row["filter_id"]: row for row in payload["rows"]}
        assert rows["FUNDING_GE_75"]["sample_count"] == 2
        assert rows["FUNDING_GE_75"]["tp_count"] == 2
        assert rows["FUNDING_GE_75"]["sl_count"] == 0
        assert rows["FUNDING_GE_75"]["avg_r_delta_vs_baseline"] > 0
        assert rows["VOLUME_LE_1_50"]["sample_count"] == 2


def test_calibration_lab_splits_train_validation_and_marks_promising_filter() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as db:
        base_time = datetime(2026, 1, 1, 0, 15)
        rows = [
            ("s1", "AAAUSDT", "82", True),
            ("s2", "BBBUSDT", "30", False),
            ("s3", "CCCUSDT", "88", True),
            ("s4", "DDDUSDT", "35", False),
            ("s5", "EEEUSDT", "91", True),
            ("s6", "FFFUSDT", "25", False),
        ]
        for index, (signal_id, symbol, funding, is_tp) in enumerate(rows):
            signal_time = base_time + timedelta(minutes=15 * index)
            db.add(
                _signal(
                    signal_id,
                    symbol,
                    signal_time,
                    "SHORT",
                    "MID_SHORT",
                    "100",
                    "110",
                    "85",
                    timeframe="1h",
                    evidence={"funding_percentile_30d": funding, "volume_ratio_vs_lookback": "1.20"},
                )
            )
            db.add(
                _candle(
                    symbol,
                    signal_time,
                    signal_time + timedelta(minutes=15),
                    high="101" if is_tp else "111",
                    low="84" if is_tp else "98",
                    close="86" if is_tp else "109",
                )
            )
        db.commit()

        payload = SignalCandidatePerformanceService(db).calibration_lab(position_lock=False, min_sample=1, limit=50)

        lanes = {lane["lane"]: lane for lane in payload["lanes"]}
        lane = lanes["MID_SHORT_1h"]
        assert lane["status"] == "READY_FOR_CALIBRATION"
        assert lane["train_count"] == 4
        assert lane["validation_count"] == 2
        candidates = {row["filter_id"]: row for row in lane["filter_candidates"]}
        funding = candidates["FUNDING_GE_75"]
        assert funding["train"]["tp_count"] == 2
        assert funding["validation"]["tp_count"] == 1
        assert funding["validation"]["sl_count"] == 0
        assert funding["validation"]["avg_r_delta_vs_baseline"] > 0
        assert funding["verdict"] == "VALIDATION_PROMISING"
        assert funding["promotion_status"] == "V3_CANDIDATE"
        assert funding["promotion_score"] >= 6
        assert funding["promotion_reasons"]
        assert payload["top_candidates"][0]["stage"] == "MID_SHORT"


def test_calibration_lab_rejects_train_only_overfit_filter() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as db:
        base_time = datetime(2026, 1, 1, 0, 15)
        rows = [
            ("s1", "AAAUSDT", "82", True),
            ("s2", "BBBUSDT", "88", True),
            ("s3", "CCCUSDT", "20", False),
            ("s4", "DDDUSDT", "25", False),
            ("s5", "EEEUSDT", "91", False),
            ("s6", "FFFUSDT", "22", True),
        ]
        for index, (signal_id, symbol, funding, is_tp) in enumerate(rows):
            signal_time = base_time + timedelta(minutes=15 * index)
            db.add(
                _signal(
                    signal_id,
                    symbol,
                    signal_time,
                    "SHORT",
                    "MID_SHORT",
                    "100",
                    "110",
                    "85",
                    timeframe="1h",
                    evidence={"funding_percentile_30d": funding, "volume_ratio_vs_lookback": "1.20"},
                )
            )
            db.add(
                _candle(
                    symbol,
                    signal_time,
                    signal_time + timedelta(minutes=15),
                    high="101" if is_tp else "111",
                    low="84" if is_tp else "98",
                    close="86" if is_tp else "109",
                )
            )
        db.commit()

        payload = SignalCandidatePerformanceService(db).calibration_lab(position_lock=False, min_sample=1, limit=50)

        lane = {lane["lane"]: lane for lane in payload["lanes"]}["MID_SHORT_1h"]
        funding = {row["filter_id"]: row for row in lane["filter_candidates"]}["FUNDING_GE_75"]
        assert funding["train"]["tp_count"] == 2
        assert funding["validation"]["sl_count"] == 1
        assert funding["verdict"] == "TRAIN_ONLY_OVERFIT"
        assert funding["promotion_status"] == "REJECT_OVERFIT"


def test_v3_shadow_helper_matches_candidate_evidence() -> None:
    filter_map = {
        ("MID_SHORT", "1h"): [
            {
                "filter_id": "FUNDING_GE_75",
                "label": "Funding percentile tinggi",
                "expression": "funding_percentile_30d >= 75",
                "promotion_score": 7,
                "promotion_reasons": ["validation ok"],
                "_spec": FilterStudySpec(
                    "FUNDING_GE_75",
                    "Funding percentile tinggi",
                    "funding_percentile_30d >= 75",
                    "funding",
                    ("funding_percentile_30d",),
                    lambda item: item["evidence_snapshot"]["funding_percentile_30d"] >= Decimal("75"),
                ),
            }
        ]
    }

    passing = signal_factory_v3_shadow_for_candidate(
        {
            "setup_type": "MID_SHORT",
            "timeframe": "1h",
            "evidence": {"funding_percentile_30d": "82"},
        },
        filter_map,
    )
    failing = signal_factory_v3_shadow_for_candidate(
        {
            "setup_type": "MID_SHORT",
            "timeframe": "1h",
            "evidence": {"funding_percentile_30d": "20"},
        },
        filter_map,
    )
    missing = signal_factory_v3_shadow_for_candidate(
        {
            "setup_type": "MID_SHORT",
            "timeframe": "1h",
            "evidence": {},
        },
        filter_map,
    )

    assert passing["v3_shadow_status"] == "V3_SHADOW_PASS"
    assert passing["v3_shadow_filter_id"] == "FUNDING_GE_75"
    assert failing["v3_shadow_status"] == "V3_SHADOW_FAIL"
    assert missing["v3_shadow_status"] == "V3_SHADOW_UNAVAILABLE"


def test_v3_shadow_comparison_splits_pass_subset_from_v2_baseline() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as db:
        base_time = datetime(2026, 1, 1, 0, 15)
        for index in range(30):
            signal_time = base_time + timedelta(minutes=15 * index)
            is_high_funding = index < 10 or index >= 25
            symbol = f"SYM{index:02d}USDT"
            db.add(
                _signal(
                    f"sig-{index}",
                    symbol,
                    signal_time,
                    "SHORT",
                    "MID_SHORT",
                    "100",
                    "110",
                    "85",
                    timeframe="1h",
                    evidence={"funding_percentile_30d": "82" if is_high_funding else "20"},
                )
            )
            db.add(
                _candle(
                    symbol,
                    signal_time,
                    signal_time + timedelta(minutes=15),
                    high="101" if is_high_funding else "111",
                    low="84" if is_high_funding else "98",
                    close="86" if is_high_funding else "109",
                )
            )
        db.commit()

        payload = SignalCandidatePerformanceService(db).v3_shadow_comparison(position_lock=False, min_sample=5)

        assert payload["summary"]["v3_pass_count"] == 15
        assert payload["summary"]["v3_fail_count"] == 15
        assert payload["summary"]["v2_live"]["tp_count"] == 15
        assert payload["summary"]["v2_live"]["sl_count"] == 15
        assert payload["summary"]["v3_shadow_pass"]["tp_count"] == 15
        assert payload["summary"]["v3_shadow_pass"]["sl_count"] == 0
        assert payload["summary"]["read"] == "V3_SHADOW_IMPROVES_V2"
        by_status = {row["bucket"]: row for row in payload["by_v3_status"]}
        assert by_status["V3_SHADOW_PASS"]["verdict"] == "BETTER_THAN_V2_BASELINE"
        assert payload["by_filter"][0]["filter_id"] == "FUNDING_GE_75"

        forward = SignalCandidatePerformanceService(db).v3_shadow_forward_log(position_lock=False, min_sample=5)

        assert forward["summary"]["v3_shadow_signal_count"] == 15
        assert forward["summary"]["v2_live"]["performance"]["tp_count"] == 15
        assert forward["summary"]["v2_live"]["performance"]["sl_count"] == 15
        assert forward["summary"]["v3_shadow_signal"]["performance"]["tp_count"] == 15
        assert forward["summary"]["v3_shadow_signal"]["performance"]["sl_count"] == 0
        assert forward["summary"]["read"] == "V3_FORWARD_HEALTHY_SHADOW"
        assert forward["source_table"] == "signal_forward_return_logs"
        assert forward["logging_model"] == "derived_shadow_lane_from_v2_signal_forward_log"
        assert forward["not_live_signal"] is True
        assert forward["not_execution_instruction"] is True


def _signal(
    signal_id: str,
    symbol: str,
    signal_time: datetime,
    direction: str,
    stage: str,
    entry: str,
    stop: str,
    target: str,
    execution: str = "ACTIVE",
    evidence: dict | None = None,
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
        execution_flag=execution,
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
        evidence=evidence or {},
        created_at=now,
        updated_at=now,
    )


def _universe(symbol: str, rank: int) -> MarketlabActiveUniverse:
    now = datetime(2026, 1, 1, 0, 0)
    return MarketlabActiveUniverse(
        symbol=symbol,
        rank=rank,
        quote_volume=Decimal("1000000") / Decimal(rank),
        collection_tier="FULL_ACTIVE",
        is_full_active=True,
        is_light_watch=False,
        is_signal_eligible=True,
        is_active=True,
        entered_at=now,
        last_seen_at=now,
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
