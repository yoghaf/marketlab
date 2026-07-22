import json
from decimal import Decimal
from threading import Lock
from time import monotonic

from sqlalchemy import desc, func, select, text
from sqlalchemy.orm import Session

from fastapi import APIRouter, Depends, HTTPException

from app.db.session import get_db
from app.models.market import (
    CollectorError,
    CollectorRun,
    DataHealthSnapshot,
    FuturesBookTicker,
    FuturesFundingHistory,
    FuturesGlobalLongShortAccountRatio,
    FuturesKline1m,
    FuturesMarkFunding,
    FuturesOpenInterest,
    FuturesOpenInterestHistory,
    FuturesTakerBuySellVolume,
    FuturesTopTraderAccountRatio,
    FuturesTopTraderPositionRatio,
    MarketlabActiveUniverse,
    RateLimitUsage,
    RichFutures5mAlignment,
    SpotBookTicker,
    SpotKline1m,
)
from app.services.feature_builder_1h import FeatureBuilder1hService
from app.services.feature_builder_15m import FeatureBuilder15mService
from app.services.feature_context_join import FeatureContextJoinService
from app.services.live_candidate_scanner import LiveCandidateScannerService
from app.services.market_regime_study import DEFAULT_ARTIFACT_DIR as DEFAULT_MARKET_REGIME_STUDY_DIR
from app.services.mid_long_geometry_validation import MidLongGeometryValidationArtifactService
from app.services.mid_long_evidence_separation import MidLongEvidenceSeparationArtifactService
from app.services.mid_long_failure_anatomy import MidLongFailureAnatomyArtifactService
from app.services.ohlcv_aggregation import OhlcvAggregationService
from app.services.outcome_summary_readonly_15m import OutcomeSummaryReadonly15mService
from app.services.outcome_tracker_15m import OutcomeTracker15mService
from app.services.paper_signal_evaluator import PaperSignalEvaluatorService
from app.services.phase6_readiness_audit import DEFAULT_PHASE6_DIR, Phase6ArtifactService
from app.services.phase7_forward_test import Phase7ForwardTestArtifactService
from app.services.psychology_labeler_15m import PsychologyLabeler15mService
from app.services.rich_5m_alignment import Rich5mAlignmentService
from app.services.anomaly_signal_factory import DEFAULT_SIGNAL_FACTORY_DIR, SignalFactoryArtifactService
from app.services.candidate_numeric_evidence import CandidateNumericEvidenceArtifactService
from app.services.early_backtest_lab import EarlyBacktestLabArtifactService
from app.services.signal_candidate_classifier_readonly_15m import SignalCandidateClassifierReadonly15mService
from app.services.signal_candidate_performance import SignalCandidatePerformanceService
from app.services.signal_performance_snapshot import SignalPerformanceSnapshotService
from app.services.snapshot_funding_alignment import SnapshotFundingAlignmentService
from app.services.strategy_optimization_artifacts import StrategyOptimizationArtifactService
from app.services.strategy_optimization_regime_split import StrategyOptimizationRegimeSplitService
from app.services.strategy_optimization_lab import StrategyOptimizationLabService
from app.services.strategy_arena import StrategyArenaArtifactService
from app.services.utils import duration_seconds, json_safe, model_to_dict, utcnow

router = APIRouter()

_SIGNAL_PERFORMANCE_CACHE_TTL_SECONDS = 30.0
_DATA_HEALTH_CACHE_TTL_SECONDS = 30.0
_MID_SHORT_FAILURE_ANATOMY_CACHE_TTL_SECONDS = 900.0
_MID_SHORT_V21_STRUCTURE_INTERACTION_CACHE_TTL_SECONDS = 3600.0
_MID_SHORT_V21_STRUCTURE_EXIT_CACHE_TTL_SECONDS = 3600.0
_MID_SHORT_V21_DYNAMIC_EXIT_CACHE_TTL_SECONDS = 3600.0
_SIGNAL_PERFORMANCE_CACHE_LOCK = Lock()
_SIGNAL_PERFORMANCE_CACHE: dict[tuple, tuple[float, dict]] = {}
_SIGNAL_FORWARD_INTEGRITY_CACHE_LOCK = Lock()
_SIGNAL_FORWARD_INTEGRITY_CACHE: dict[tuple, tuple[float, dict]] = {}
_SCANNER_LIVE_CACHE_LOCK = Lock()
_SCANNER_LIVE_CACHE: dict[tuple, tuple[float, dict]] = {}
_DATA_HEALTH_CACHE_LOCK = Lock()
_DATA_HEALTH_CACHE: dict[int, tuple[float, dict]] = {}
_SIGNAL_QUALITY_CACHE_LOCK = Lock()
_SIGNAL_QUALITY_CACHE: dict[tuple, tuple[float, dict]] = {}
_STRUCTURE_ZONE_SHADOW_CACHE_LOCK = Lock()
_STRUCTURE_ZONE_SHADOW_CACHE: dict[tuple, tuple[float, dict]] = {}
_MID_SHORT_SHADOW_FORWARD_CACHE_LOCK = Lock()
_MID_SHORT_SHADOW_FORWARD_CACHE: dict[tuple, tuple[float, dict]] = {}
_MID_SHORT_FAILURE_ANATOMY_CACHE_LOCK = Lock()
_MID_SHORT_FAILURE_ANATOMY_CACHE: dict[tuple, tuple[float, dict]] = {}
_MID_SHORT_SECOND_FILTER_CACHE_LOCK = Lock()
_MID_SHORT_SECOND_FILTER_CACHE: dict[tuple, tuple[float, dict]] = {}
_MID_SHORT_TAKER_SELL_DEEP_CACHE_LOCK = Lock()
_MID_SHORT_TAKER_SELL_DEEP_CACHE: dict[tuple, tuple[float, dict]] = {}
_MID_SHORT_WRONG_DIRECTION_CACHE_LOCK = Lock()
_MID_SHORT_WRONG_DIRECTION_CACHE: dict[tuple, tuple[float, dict]] = {}
_MID_SHORT_ENTRY_CONFIRMATION_CACHE_LOCK = Lock()
_MID_SHORT_ENTRY_CONFIRMATION_CACHE: dict[tuple, tuple[float, dict]] = {}
_MID_SHORT_STRUCTURE_ZONE_CACHE_LOCK = Lock()
_MID_SHORT_STRUCTURE_ZONE_CACHE: dict[tuple, tuple[float, dict]] = {}
_MID_SHORT_V21_STRUCTURE_INTERACTION_CACHE_LOCK = Lock()
_MID_SHORT_V21_STRUCTURE_INTERACTION_CACHE: dict[tuple, tuple[float, dict]] = {}
_MID_SHORT_V21_STRUCTURE_EXIT_CACHE_LOCK = Lock()
_MID_SHORT_V21_STRUCTURE_EXIT_CACHE: dict[tuple, tuple[float, dict]] = {}
_MID_SHORT_V21_DYNAMIC_EXIT_CACHE_LOCK = Lock()
_MID_SHORT_V21_DYNAMIC_EXIT_CACHE: dict[tuple, tuple[float, dict]] = {}
_MID_SHORT_VOLUME_SAFE_CACHE_LOCK = Lock()
_MID_SHORT_VOLUME_SAFE_CACHE: dict[tuple, tuple[float, dict]] = {}
_MID_SHORT_FILTER_COMBO_CACHE_LOCK = Lock()
_MID_SHORT_FILTER_COMBO_CACHE: dict[tuple, tuple[float, dict]] = {}
_SIGNAL_FILTER_STUDY_CACHE_LOCK = Lock()
_SIGNAL_FILTER_STUDY_CACHE: dict[tuple, tuple[float, dict]] = {}
_SIGNAL_ONE_HOUR_FILTER_STUDY_CACHE_LOCK = Lock()
_SIGNAL_ONE_HOUR_FILTER_STUDY_CACHE: dict[tuple, tuple[float, dict]] = {}
_SIGNAL_ONE_HOUR_WALK_FORWARD_CACHE_LOCK = Lock()
_SIGNAL_ONE_HOUR_WALK_FORWARD_CACHE: dict[tuple, tuple[float, dict]] = {}
_SIGNAL_ONE_HOUR_V4_SHADOW_CACHE_LOCK = Lock()
_SIGNAL_ONE_HOUR_V4_SHADOW_CACHE: dict[tuple, tuple[float, dict]] = {}
_SIGNAL_CALIBRATION_CACHE_LOCK = Lock()
_SIGNAL_CALIBRATION_CACHE: dict[tuple, tuple[float, dict]] = {}
_SIGNAL_MISIDENTIFICATION_CACHE_LOCK = Lock()
_SIGNAL_MISIDENTIFICATION_CACHE: dict[tuple, tuple[float, dict]] = {}
_V3_SHADOW_COMPARISON_CACHE_LOCK = Lock()
_V3_SHADOW_COMPARISON_CACHE: dict[tuple, tuple[float, dict]] = {}
_V3_SHADOW_FORWARD_CACHE_LOCK = Lock()
_V3_SHADOW_FORWARD_CACHE: dict[tuple, tuple[float, dict]] = {}
_STRATEGY_OPTIMIZATION_CACHE_LOCK = Lock()
_STRATEGY_OPTIMIZATION_CACHE: dict[tuple, tuple[float, dict]] = {}
_STRATEGY_REGIME_SPLIT_CACHE_LOCK = Lock()
_STRATEGY_REGIME_SPLIT_CACHE: dict[tuple, tuple[float, dict]] = {}


@router.get("/health")
def health(db: Session = Depends(get_db)):
    db.execute(text("select 1"))
    return {"status": "ok", "service": "marketlab", "utc": utcnow().isoformat()}


@router.get("/api/universe/active")
def active_universe(db: Session = Depends(get_db)):
    rows = db.scalars(
        select(MarketlabActiveUniverse)
        .where(MarketlabActiveUniverse.is_active.is_(True))
        .order_by(MarketlabActiveUniverse.rank.asc())
    ).all()
    full_active_count = sum(1 for row in rows if row.collection_tier == "FULL_ACTIVE")
    light_watch_count = sum(1 for row in rows if row.collection_tier == "LIGHT_WATCH")
    signal_eligible_count = sum(1 for row in rows if row.is_signal_eligible)
    items = []
    for row in rows:
        item = model_to_dict(row)
        item["rank_volume"] = row.quote_volume
        items.append(item)
    return {
        "count": len(rows),
        "active_universe_count": len(rows),
        "universe_count": len(rows),
        "full_active_count": full_active_count,
        "light_watch_count": light_watch_count,
        "signal_eligible_count": signal_eligible_count,
        "items": items,
    }


@router.get("/api/collectors/status")
def collectors_status(db: Session = Depends(get_db)):
    runs = db.scalars(select(CollectorRun).order_by(desc(CollectorRun.started_at)).limit(200)).all()
    latest_by_name: dict[str, dict] = {}
    for run in runs:
        if run.collector_name not in latest_by_name:
            latest_by_name[run.collector_name] = _collector_run_payload(run)

    errors = db.scalars(select(CollectorError).order_by(desc(CollectorError.created_at)).limit(50)).all()
    usage = db.scalars(select(RateLimitUsage).order_by(desc(RateLimitUsage.created_at)).limit(100)).all()
    latest_used_weight = next((row.used_weight_1m for row in usage if row.used_weight_1m is not None), None)
    return {
        "collectors": list(latest_by_name.values()),
        "last_errors": [model_to_dict(row) for row in errors],
        "request_usage": {
            "latest_used_weight_1m": latest_used_weight,
            "recent": [model_to_dict(row) for row in usage[:25]],
        },
    }


@router.get("/api/data-health")
def data_health(db: Session = Depends(get_db)):
    bind_key = id(db.get_bind())
    now_monotonic = monotonic()
    with _DATA_HEALTH_CACHE_LOCK:
        cached = _DATA_HEALTH_CACHE.get(bind_key)
        if cached and now_monotonic - cached[0] <= _DATA_HEALTH_CACHE_TTL_SECONDS:
            return cached[1]

    items = _latest_health_items(db)
    rich_counts = {"RICH_READY": 0, "RICH_WARMUP": 0, "RICH_STALE": 0, "RICH_MISSING": 0}
    rich_by_symbol = _rich_status_by_symbol(db, [item["symbol"] for item in items])
    for item in items:
        rich_status = rich_by_symbol[item["symbol"]]
        item["rich_status"] = rich_status["status"]
        item["rich_reason"] = rich_status["reason"]
        rich_counts[item["rich_status"]] = rich_counts.get(item["rich_status"], 0) + 1
    statuses = [
        "READY",
        "WARMUP",
        "STALE",
        "MISSING_SPOT",
        "MISSING_FUTURES",
        "MISSING_OI",
        "MISSING_FUNDING",
        "NOT_ACTIVE",
    ]
    counts = {status: 0 for status in statuses}
    for item in items:
        counts[item["status"]] = counts.get(item["status"], 0) + 1
    universe_counts = _active_universe_counts(db)
    payload = json_safe(
        {
            "counts": counts,
            "rich_counts": rich_counts,
            "aggregation": OhlcvAggregationService(db).status_summary(),
            "rich_alignment": Rich5mAlignmentService(db).status_summary(),
            "market_state_alignment": SnapshotFundingAlignmentService(db).status_summary(),
            "features_15m": FeatureBuilder15mService(db).status_summary(),
            "features_1h": FeatureBuilder1hService(db).status_summary(),
            "feature_context_15m_1h": FeatureContextJoinService(db).status_summary(),
            "psychology_15m": PsychologyLabeler15mService(db).status_summary(),
            "signal_candidates_readonly_15m": SignalCandidateClassifierReadonly15mService(db).status_summary(),
            "outcomes_15m": OutcomeTracker15mService(db).status_summary(),
            "universe": universe_counts,
            "latest": _latest_market_times(items),
            "items": items,
        }
    )
    with _DATA_HEALTH_CACHE_LOCK:
        _DATA_HEALTH_CACHE[bind_key] = (monotonic(), payload)
    return payload


@router.get("/api/aggregation/status")
def aggregation_status(db: Session = Depends(get_db)):
    summary = OhlcvAggregationService(db).status_summary()
    payload = {
        **summary["latest"],
        **summary["counts"],
        "tables": summary["tables"],
    }
    return json_safe(payload)


@router.get("/api/rich-alignment/status")
def rich_alignment_status(db: Session = Depends(get_db)):
    summary = Rich5mAlignmentService(db).status_summary()
    payload = {
        **summary["latest"],
        **summary["counts"],
        "tables": summary["tables"],
    }
    return json_safe(payload)


@router.get("/api/market-state-alignment/status")
def market_state_alignment_status(db: Session = Depends(get_db)):
    summary = SnapshotFundingAlignmentService(db).status_summary()
    payload = {
        **summary["latest"],
        **summary["counts"],
        "tables": summary["tables"],
        "thresholds": summary["thresholds"],
    }
    return json_safe(payload)


@router.get("/api/features/15m/status")
def features_15m_status(db: Session = Depends(get_db)):
    return json_safe(FeatureBuilder15mService(db).status_summary())


@router.get("/api/features/15m")
def features_15m(status: str | None = None, limit: int = 100, db: Session = Depends(get_db)):
    rows = FeatureBuilder15mService(db).list_features(status=status, limit=limit)
    return json_safe(
        {
            "count": len(rows),
            "items": [model_to_dict(row) for row in rows],
        }
    )


@router.get("/api/features/1h/status")
def features_1h_status(db: Session = Depends(get_db)):
    return json_safe(FeatureBuilder1hService(db).status_summary())


@router.get("/api/features/1h")
def features_1h(status: str | None = None, limit: int = 100, db: Session = Depends(get_db)):
    rows = FeatureBuilder1hService(db).list_features(status=status, limit=limit)
    return json_safe(
        {
            "count": len(rows),
            "items": [model_to_dict(row) for row in rows],
        }
    )


@router.get("/api/features/context/15m-1h/status")
def feature_context_15m_1h_status(db: Session = Depends(get_db)):
    return json_safe(FeatureContextJoinService(db).status_summary())


@router.get("/api/features/context/15m-1h")
def feature_context_15m_1h(status: str | None = None, limit: int = 100, db: Session = Depends(get_db)):
    rows = FeatureContextJoinService(db).list_contexts(status=status, limit=limit)
    return json_safe(
        {
            "count": len(rows),
            "items": [model_to_dict(row) for row in rows],
        }
    )


@router.get("/api/psychology/15m/status")
def psychology_15m_status(db: Session = Depends(get_db)):
    return json_safe(PsychologyLabeler15mService(db).status_summary())


@router.get("/api/psychology/15m")
def psychology_15m(label_status: str | None = None, limit: int = 100, db: Session = Depends(get_db)):
    rows = PsychologyLabeler15mService(db).list_labels(label_status=label_status, limit=limit)
    return json_safe(
        {
            "count": len(rows),
            "items": [model_to_dict(row) for row in rows],
        }
    )


@router.get("/api/signal-candidates/readonly/15m/status")
def signal_candidates_readonly_15m_status(db: Session = Depends(get_db)):
    return json_safe(SignalCandidateClassifierReadonly15mService(db).status_summary())


@router.get("/api/signal-candidates/readonly/15m")
def signal_candidates_readonly_15m(
    type: str | None = None,
    classifier_status: str | None = None,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    rows = SignalCandidateClassifierReadonly15mService(db).list_candidates(
        candidate_type=type,
        classifier_status=classifier_status,
        limit=limit,
    )
    return json_safe(
        {
            "count": len(rows),
            "items": [model_to_dict(row) for row in rows],
        }
    )


@router.get("/api/signal-candidates/performance/live")
def signal_candidates_performance_live(
    include_watch_only: bool = False,
    position_lock: bool = True,
    stage: str | None = None,
    timeframe: str | None = None,
    symbol: str | None = None,
    result_status: str | None = None,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    normalized_limit = max(1, min(limit, 500))
    artifact_payload = _default_signal_performance_snapshot(
        include_watch_only=include_watch_only,
        position_lock=position_lock,
        stage=stage,
        timeframe=timeframe,
        symbol=symbol,
        result_status=result_status,
        limit=normalized_limit,
    )
    if artifact_payload is not None:
        return artifact_payload

    cache_key = (
        bool(include_watch_only),
        bool(position_lock),
        stage or "",
        timeframe or "",
        symbol or "",
        result_status or "",
        normalized_limit,
    )
    now = monotonic()
    with _SIGNAL_PERFORMANCE_CACHE_LOCK:
        cached = _SIGNAL_PERFORMANCE_CACHE.get(cache_key)
        if cached and now - cached[0] <= _SIGNAL_PERFORMANCE_CACHE_TTL_SECONDS:
            payload = dict(cached[1])
            payload["cache"] = {"hit": True, "ttl_seconds": _SIGNAL_PERFORMANCE_CACHE_TTL_SECONDS}
            return payload

    payload = json_safe(
        SignalCandidatePerformanceService(db).summary(
            include_watch_only=include_watch_only,
            position_lock=position_lock,
            stage=stage,
            timeframe=timeframe,
            symbol=symbol,
            result_status=result_status,
            limit=normalized_limit,
        )
    )
    payload["cache"] = {"hit": False, "ttl_seconds": _SIGNAL_PERFORMANCE_CACHE_TTL_SECONDS}
    with _SIGNAL_PERFORMANCE_CACHE_LOCK:
        _SIGNAL_PERFORMANCE_CACHE[cache_key] = (monotonic(), payload)
    return payload


@router.get("/api/signals/detail")
def signal_detail(
    signal_id: str | None = None,
    symbol: str | None = None,
    timeframe: str | None = None,
    db: Session = Depends(get_db),
):
    if not signal_id and not symbol:
        raise HTTPException(status_code=400, detail="signal_id or symbol is required")
    try:
        v3_filter_map = SignalPerformanceSnapshotService().v3_shadow_filter_map()
    except (FileNotFoundError, json.JSONDecodeError):
        v3_filter_map = None
    payload = SignalCandidatePerformanceService(db).detail(
        signal_id=signal_id,
        symbol=symbol,
        timeframe=timeframe,
        include_watch_only=True,
        v3_filter_map=v3_filter_map,
    )
    if payload is None:
        raise HTTPException(status_code=404, detail="Signal not found")
    return json_safe(payload)


@router.get("/api/signals/forward-integrity")
def signal_forward_integrity(
    include_watch_only: bool = False,
    position_lock: bool = True,
    stage: str | None = None,
    timeframe: str | None = None,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    normalized_limit = max(1, min(limit, 200))
    artifact_payload = _default_forward_integrity_snapshot(
        include_watch_only=include_watch_only,
        position_lock=position_lock,
        stage=stage,
        timeframe=timeframe,
        limit=normalized_limit,
    )
    if artifact_payload is not None:
        return artifact_payload

    cache_key = (
        bool(include_watch_only),
        bool(position_lock),
        stage or "",
        timeframe or "",
        normalized_limit,
    )
    now = monotonic()
    with _SIGNAL_FORWARD_INTEGRITY_CACHE_LOCK:
        cached = _SIGNAL_FORWARD_INTEGRITY_CACHE.get(cache_key)
        if cached and now - cached[0] <= _SIGNAL_PERFORMANCE_CACHE_TTL_SECONDS:
            payload = dict(cached[1])
            payload["cache"] = {"hit": True, "ttl_seconds": _SIGNAL_PERFORMANCE_CACHE_TTL_SECONDS}
            return payload

    payload = json_safe(
        SignalCandidatePerformanceService(db).forward_integrity(
            include_watch_only=include_watch_only,
            position_lock=position_lock,
            stage=stage,
            timeframe=timeframe,
            limit=normalized_limit,
        )
    )
    payload["cache"] = {"hit": False, "ttl_seconds": _SIGNAL_PERFORMANCE_CACHE_TTL_SECONDS}
    with _SIGNAL_FORWARD_INTEGRITY_CACHE_LOCK:
        _SIGNAL_FORWARD_INTEGRITY_CACHE[cache_key] = (monotonic(), payload)
    return json_safe(payload)


@router.get("/api/signal-candidates/quality-lab")
def signal_candidates_quality_lab(
    include_watch_only: bool = False,
    position_lock: bool = True,
    stage: str | None = None,
    timeframe: str | None = None,
    min_sample: int = 5,
    limit: int = 25,
    db: Session = Depends(get_db),
):
    normalized_limit = max(1, min(limit, 100))
    normalized_min_sample = max(1, min(min_sample, 100))
    cache_key = (
        bool(include_watch_only),
        bool(position_lock),
        stage or "",
        timeframe or "",
        normalized_min_sample,
        normalized_limit,
    )
    now = monotonic()
    with _SIGNAL_QUALITY_CACHE_LOCK:
        cached = _SIGNAL_QUALITY_CACHE.get(cache_key)
        if cached and now - cached[0] <= _SIGNAL_PERFORMANCE_CACHE_TTL_SECONDS:
            payload = dict(cached[1])
            payload["cache"] = {"hit": True, "ttl_seconds": _SIGNAL_PERFORMANCE_CACHE_TTL_SECONDS}
            return payload

    payload = json_safe(
        SignalCandidatePerformanceService(db).quality_lab(
            include_watch_only=include_watch_only,
            position_lock=position_lock,
            stage=stage,
            timeframe=timeframe,
            min_sample=normalized_min_sample,
            limit=normalized_limit,
        )
    )
    payload["cache"] = {"hit": False, "ttl_seconds": _SIGNAL_PERFORMANCE_CACHE_TTL_SECONDS}
    with _SIGNAL_QUALITY_CACHE_LOCK:
        _SIGNAL_QUALITY_CACHE[cache_key] = (monotonic(), payload)
    return payload


@router.get("/api/signal-candidates/mid-long-1h-lab62")
def signal_candidates_mid_long_1h_lab62(
    min_sample: int = 20,
    limit: int = 50,
):
    normalized_limit = max(1, min(limit, 100))
    normalized_min_sample = max(1, min(min_sample, 100))
    try:
        return json_safe(
            SignalPerformanceSnapshotService().mid_long_1h_lab62(
                min_sample=normalized_min_sample,
                limit=normalized_limit,
            )
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail="MID_LONG 1h LAB-62 snapshot is not available yet") from exc


@router.get("/api/signal-candidates/mid-long-1h-lab63")
def signal_candidates_mid_long_1h_lab63():
    try:
        return json_safe(MidLongGeometryValidationArtifactService().summary())
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail="MID_LONG 1h LAB-63 artifact is not available yet") from exc


@router.get("/api/signal-candidates/mid-long-1h-lab64")
def signal_candidates_mid_long_1h_lab64():
    try:
        return json_safe(MidLongEvidenceSeparationArtifactService().summary())
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail="MID_LONG 1h LAB-64 artifact is not available yet") from exc


@router.get("/api/signal-candidates/mid-long-1h-lab65")
def signal_candidates_mid_long_1h_lab65():
    try:
        return json_safe(MidLongFailureAnatomyArtifactService().summary())
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail="MID_LONG 1h LAB-65 artifact is not available yet") from exc


@router.get("/api/signal-candidates/structure-zone-shadow-study")
def signal_candidates_structure_zone_shadow_study(
    include_watch_only: bool = False,
    position_lock: bool = True,
    min_sample: int = 20,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    normalized_limit = max(1, min(limit, 150))
    normalized_min_sample = max(1, min(min_sample, 100))
    cache_key = (
        bool(include_watch_only),
        bool(position_lock),
        normalized_min_sample,
        normalized_limit,
    )
    now = monotonic()
    with _STRUCTURE_ZONE_SHADOW_CACHE_LOCK:
        cached = _STRUCTURE_ZONE_SHADOW_CACHE.get(cache_key)
        if cached and now - cached[0] <= _SIGNAL_PERFORMANCE_CACHE_TTL_SECONDS:
            payload = dict(cached[1])
            payload["cache"] = {"hit": True, "ttl_seconds": _SIGNAL_PERFORMANCE_CACHE_TTL_SECONDS}
            return payload

    payload = json_safe(
        SignalCandidatePerformanceService(db).structure_zone_shadow_study(
            include_watch_only=include_watch_only,
            position_lock=position_lock,
            min_sample=normalized_min_sample,
            limit=normalized_limit,
        )
    )
    payload["cache"] = {"hit": False, "ttl_seconds": _SIGNAL_PERFORMANCE_CACHE_TTL_SECONDS}
    with _STRUCTURE_ZONE_SHADOW_CACHE_LOCK:
        _STRUCTURE_ZONE_SHADOW_CACHE[cache_key] = (monotonic(), payload)
    return payload


@router.get("/api/signal-candidates/mid-short-1h-shadow-forward-log")
def signal_candidates_mid_short_1h_shadow_forward_log(
    include_watch_only: bool = False,
    position_lock: bool = True,
    result_status: str | None = None,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    normalized_limit = max(1, min(limit, 300))
    normalized_result_status = None if result_status in {"", "ALL"} else result_status
    cache_key = (
        bool(include_watch_only),
        bool(position_lock),
        normalized_result_status or "",
        normalized_limit,
    )
    now = monotonic()
    with _MID_SHORT_SHADOW_FORWARD_CACHE_LOCK:
        cached = _MID_SHORT_SHADOW_FORWARD_CACHE.get(cache_key)
        if cached and now - cached[0] <= _SIGNAL_PERFORMANCE_CACHE_TTL_SECONDS:
            payload = dict(cached[1])
            payload["cache"] = {"hit": True, "ttl_seconds": _SIGNAL_PERFORMANCE_CACHE_TTL_SECONDS}
            return payload

    payload = json_safe(
        SignalCandidatePerformanceService(db).mid_short_1h_shadow_forward_log(
            include_watch_only=include_watch_only,
            position_lock=position_lock,
            result_status=normalized_result_status,
            limit=normalized_limit,
        )
    )
    payload["cache"] = {"hit": False, "ttl_seconds": _SIGNAL_PERFORMANCE_CACHE_TTL_SECONDS}
    with _MID_SHORT_SHADOW_FORWARD_CACHE_LOCK:
        _MID_SHORT_SHADOW_FORWARD_CACHE[cache_key] = (monotonic(), payload)
    return payload


@router.get("/api/signal-candidates/mid-short-1h-failure-anatomy")
def signal_candidates_mid_short_1h_failure_anatomy(
    include_watch_only: bool = False,
    position_lock: bool = True,
    shadow_status: str = "SHADOW_PASS",
    base_filter: str = "ALL",
    min_sample: int = 20,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    normalized_limit = max(1, min(limit, 150))
    normalized_min_sample = max(1, min(min_sample, 100))
    normalized_shadow_status = (shadow_status or "SHADOW_PASS").upper()
    normalized_base_filter = (base_filter or "ALL").upper()
    if normalized_base_filter not in {"ALL", "TAKER_SELL_GE_52"}:
        normalized_base_filter = "ALL"
    cache_key = (
        bool(include_watch_only),
        bool(position_lock),
        normalized_shadow_status,
        normalized_base_filter,
        normalized_min_sample,
        normalized_limit,
    )
    now = monotonic()
    with _MID_SHORT_FAILURE_ANATOMY_CACHE_LOCK:
        cached = _MID_SHORT_FAILURE_ANATOMY_CACHE.get(cache_key)
        if cached and now - cached[0] <= _MID_SHORT_FAILURE_ANATOMY_CACHE_TTL_SECONDS:
            payload = dict(cached[1])
            payload["cache"] = {"hit": True, "ttl_seconds": _MID_SHORT_FAILURE_ANATOMY_CACHE_TTL_SECONDS}
            return payload

    payload = json_safe(
        SignalCandidatePerformanceService(db).mid_short_1h_failure_anatomy(
            include_watch_only=include_watch_only,
            position_lock=position_lock,
            shadow_status=normalized_shadow_status,
            base_filter=normalized_base_filter,
            min_sample=normalized_min_sample,
            limit=normalized_limit,
        )
    )
    payload["cache"] = {"hit": False, "ttl_seconds": _MID_SHORT_FAILURE_ANATOMY_CACHE_TTL_SECONDS}
    with _MID_SHORT_FAILURE_ANATOMY_CACHE_LOCK:
        _MID_SHORT_FAILURE_ANATOMY_CACHE[cache_key] = (monotonic(), payload)
    return payload


@router.get("/api/signal-candidates/mid-short-1h-second-filter-shadow")
def signal_candidates_mid_short_1h_second_filter_shadow(
    include_watch_only: bool = False,
    position_lock: bool = True,
    shadow_status: str = "SHADOW_PASS",
    min_sample: int = 20,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    normalized_limit = max(1, min(limit, 150))
    normalized_min_sample = max(1, min(min_sample, 100))
    normalized_shadow_status = (shadow_status or "SHADOW_PASS").upper()
    cache_key = (
        bool(include_watch_only),
        bool(position_lock),
        normalized_shadow_status,
        normalized_min_sample,
        normalized_limit,
    )
    now = monotonic()
    with _MID_SHORT_SECOND_FILTER_CACHE_LOCK:
        cached = _MID_SHORT_SECOND_FILTER_CACHE.get(cache_key)
        if cached and now - cached[0] <= _SIGNAL_PERFORMANCE_CACHE_TTL_SECONDS:
            payload = dict(cached[1])
            payload["cache"] = {"hit": True, "ttl_seconds": _SIGNAL_PERFORMANCE_CACHE_TTL_SECONDS}
            return payload

    payload = json_safe(
        SignalCandidatePerformanceService(db).mid_short_1h_second_filter_shadow(
            include_watch_only=include_watch_only,
            position_lock=position_lock,
            shadow_status=normalized_shadow_status,
            min_sample=normalized_min_sample,
            limit=normalized_limit,
        )
    )
    payload["cache"] = {"hit": False, "ttl_seconds": _SIGNAL_PERFORMANCE_CACHE_TTL_SECONDS}
    with _MID_SHORT_SECOND_FILTER_CACHE_LOCK:
        _MID_SHORT_SECOND_FILTER_CACHE[cache_key] = (monotonic(), payload)
    return payload


@router.get("/api/signal-candidates/mid-short-1h-taker-sell-deep-dive")
def signal_candidates_mid_short_1h_taker_sell_deep_dive(
    include_watch_only: bool = False,
    position_lock: bool = True,
    min_sample: int = 20,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    normalized_limit = max(1, min(limit, 150))
    normalized_min_sample = max(1, min(min_sample, 100))
    cache_key = (
        bool(include_watch_only),
        bool(position_lock),
        normalized_min_sample,
        normalized_limit,
    )
    now = monotonic()
    with _MID_SHORT_TAKER_SELL_DEEP_CACHE_LOCK:
        cached = _MID_SHORT_TAKER_SELL_DEEP_CACHE.get(cache_key)
        if cached and now - cached[0] <= _SIGNAL_PERFORMANCE_CACHE_TTL_SECONDS:
            payload = dict(cached[1])
            payload["cache"] = {"hit": True, "ttl_seconds": _SIGNAL_PERFORMANCE_CACHE_TTL_SECONDS}
            return payload

    payload = json_safe(
        SignalCandidatePerformanceService(db).mid_short_1h_taker_sell_deep_dive(
            include_watch_only=include_watch_only,
            position_lock=position_lock,
            min_sample=normalized_min_sample,
            limit=normalized_limit,
        )
    )
    payload["cache"] = {"hit": False, "ttl_seconds": _SIGNAL_PERFORMANCE_CACHE_TTL_SECONDS}
    with _MID_SHORT_TAKER_SELL_DEEP_CACHE_LOCK:
        _MID_SHORT_TAKER_SELL_DEEP_CACHE[cache_key] = (monotonic(), payload)
    return payload


@router.get("/api/signal-candidates/mid-short-1h-wrong-direction-deep-dive")
def signal_candidates_mid_short_1h_wrong_direction_deep_dive(
    include_watch_only: bool = False,
    position_lock: bool = True,
    min_sample: int = 20,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    normalized_limit = max(1, min(limit, 150))
    normalized_min_sample = max(1, min(min_sample, 100))
    cache_key = (
        bool(include_watch_only),
        bool(position_lock),
        normalized_min_sample,
        normalized_limit,
    )
    now = monotonic()
    with _MID_SHORT_WRONG_DIRECTION_CACHE_LOCK:
        cached = _MID_SHORT_WRONG_DIRECTION_CACHE.get(cache_key)
        if cached and now - cached[0] <= _SIGNAL_PERFORMANCE_CACHE_TTL_SECONDS:
            payload = dict(cached[1])
            payload["cache"] = {"hit": True, "ttl_seconds": _SIGNAL_PERFORMANCE_CACHE_TTL_SECONDS}
            return payload

    payload = json_safe(
        SignalCandidatePerformanceService(db).mid_short_1h_wrong_direction_deep_dive(
            include_watch_only=include_watch_only,
            position_lock=position_lock,
            min_sample=normalized_min_sample,
            limit=normalized_limit,
        )
    )
    payload["cache"] = {"hit": False, "ttl_seconds": _SIGNAL_PERFORMANCE_CACHE_TTL_SECONDS}
    with _MID_SHORT_WRONG_DIRECTION_CACHE_LOCK:
        _MID_SHORT_WRONG_DIRECTION_CACHE[cache_key] = (monotonic(), payload)
    return payload


@router.get("/api/signal-candidates/mid-short-1h-entry-confirmation-study")
def signal_candidates_mid_short_1h_entry_confirmation_study(
    include_watch_only: bool = False,
    position_lock: bool = True,
    min_sample: int = 20,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    normalized_limit = max(1, min(limit, 150))
    normalized_min_sample = max(1, min(min_sample, 100))
    cache_key = (
        bool(include_watch_only),
        bool(position_lock),
        normalized_min_sample,
        normalized_limit,
    )
    now = monotonic()
    with _MID_SHORT_ENTRY_CONFIRMATION_CACHE_LOCK:
        cached = _MID_SHORT_ENTRY_CONFIRMATION_CACHE.get(cache_key)
        if cached and now - cached[0] <= _MID_SHORT_FAILURE_ANATOMY_CACHE_TTL_SECONDS:
            payload = dict(cached[1])
            payload["cache"] = {"hit": True, "ttl_seconds": _MID_SHORT_FAILURE_ANATOMY_CACHE_TTL_SECONDS}
            return payload

    payload = json_safe(
        SignalCandidatePerformanceService(db).mid_short_1h_entry_confirmation_study(
            include_watch_only=include_watch_only,
            position_lock=position_lock,
            min_sample=normalized_min_sample,
            limit=normalized_limit,
        )
    )
    payload["cache"] = {"hit": False, "ttl_seconds": _MID_SHORT_FAILURE_ANATOMY_CACHE_TTL_SECONDS}
    with _MID_SHORT_ENTRY_CONFIRMATION_CACHE_LOCK:
        _MID_SHORT_ENTRY_CONFIRMATION_CACHE[cache_key] = (monotonic(), payload)
    return payload


@router.get("/api/signal-candidates/mid-short-1h-structure-zone-study")
def signal_candidates_mid_short_1h_structure_zone_study(
    include_watch_only: bool = False,
    position_lock: bool = True,
    min_sample: int = 20,
    limit: int = 50,
    signal_id: str | None = None,
    db: Session = Depends(get_db),
):
    normalized_limit = max(1, min(limit, 150))
    normalized_min_sample = max(1, min(min_sample, 100))
    normalized_signal_id = (signal_id or "").strip() or None
    cache_key = (
        bool(include_watch_only),
        bool(position_lock),
        normalized_min_sample,
    )
    now = monotonic()
    cache_hit = False
    with _MID_SHORT_STRUCTURE_ZONE_CACHE_LOCK:
        cached = _MID_SHORT_STRUCTURE_ZONE_CACHE.get(cache_key)
        if cached and now - cached[0] <= _MID_SHORT_FAILURE_ANATOMY_CACHE_TTL_SECONDS:
            base_payload = dict(cached[1])
            cache_hit = True

    service = SignalCandidatePerformanceService(db)
    if not cache_hit:
        base_payload = json_safe(
            service.mid_short_1h_structure_zone_study(
                include_watch_only=include_watch_only,
                position_lock=position_lock,
                min_sample=normalized_min_sample,
                limit=150,
                signal_id=None,
            )
        )
        with _MID_SHORT_STRUCTURE_ZONE_CACHE_LOCK:
            _MID_SHORT_STRUCTURE_ZONE_CACHE[cache_key] = (monotonic(), base_payload)

    payload = dict(base_payload)
    payload["filters"] = {
        **dict(base_payload.get("filters") or {}),
        "limit": normalized_limit,
        "signal_id": normalized_signal_id,
    }
    payload["case_rows"] = list(base_payload.get("case_rows") or [])[:normalized_limit]
    if normalized_signal_id:
        payload.update(
            json_safe(
                service.mid_short_1h_structure_zone_case(
                    signal_id=normalized_signal_id,
                    include_watch_only=include_watch_only,
                )
            )
        )
    payload["cache"] = {
        "hit": cache_hit,
        "ttl_seconds": _MID_SHORT_FAILURE_ANATOMY_CACHE_TTL_SECONDS,
    }
    return payload


@router.get("/api/signal-candidates/mid-short-1h-v2-1-structure-interaction-study")
def signal_candidates_mid_short_1h_v21_structure_interaction_study(
    include_watch_only: bool = False,
    position_lock: bool = True,
    min_sample: int = 20,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    normalized_limit = max(1, min(limit, 150))
    normalized_min_sample = max(1, min(min_sample, 100))
    cache_key = (
        bool(include_watch_only),
        bool(position_lock),
        normalized_min_sample,
    )
    now = monotonic()
    with _MID_SHORT_V21_STRUCTURE_INTERACTION_CACHE_LOCK:
        cached = _MID_SHORT_V21_STRUCTURE_INTERACTION_CACHE.get(cache_key)
        if cached and now - cached[0] <= _MID_SHORT_V21_STRUCTURE_INTERACTION_CACHE_TTL_SECONDS:
            payload = dict(cached[1])
            payload["case_rows"] = list(payload.get("case_rows") or [])[:normalized_limit]
            payload["filters"] = {
                **dict(payload.get("filters") or {}),
                "limit": normalized_limit,
            }
            payload["cache"] = {
                "hit": True,
                "ttl_seconds": _MID_SHORT_V21_STRUCTURE_INTERACTION_CACHE_TTL_SECONDS,
            }
            return payload

    payload = json_safe(
        SignalCandidatePerformanceService(db).mid_short_1h_v21_structure_interaction_study(
            include_watch_only=include_watch_only,
            position_lock=position_lock,
            min_sample=normalized_min_sample,
            limit=150,
        )
    )
    with _MID_SHORT_V21_STRUCTURE_INTERACTION_CACHE_LOCK:
        _MID_SHORT_V21_STRUCTURE_INTERACTION_CACHE[cache_key] = (monotonic(), payload)
    payload = dict(payload)
    payload["case_rows"] = list(payload.get("case_rows") or [])[:normalized_limit]
    payload["filters"] = {
        **dict(payload.get("filters") or {}),
        "limit": normalized_limit,
    }
    payload["cache"] = {
        "hit": False,
        "ttl_seconds": _MID_SHORT_V21_STRUCTURE_INTERACTION_CACHE_TTL_SECONDS,
    }
    return payload


@router.get("/api/signal-candidates/mid-short-1h-v2-1-structure-exit-study")
def signal_candidates_mid_short_1h_v21_structure_exit_study(
    include_watch_only: bool = False,
    position_lock: bool = True,
    min_sample: int = 20,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    normalized_limit = max(1, min(limit, 150))
    normalized_min_sample = max(1, min(min_sample, 100))
    cache_key = (
        bool(include_watch_only),
        bool(position_lock),
        normalized_min_sample,
    )
    now = monotonic()
    with _MID_SHORT_V21_STRUCTURE_EXIT_CACHE_LOCK:
        cached = _MID_SHORT_V21_STRUCTURE_EXIT_CACHE.get(cache_key)
        if cached and now - cached[0] <= _MID_SHORT_V21_STRUCTURE_EXIT_CACHE_TTL_SECONDS:
            payload = dict(cached[1])
            payload["case_rows"] = list(payload.get("case_rows") or [])[:normalized_limit]
            payload["filters"] = {
                **dict(payload.get("filters") or {}),
                "limit": normalized_limit,
            }
            payload["cache"] = {
                "hit": True,
                "ttl_seconds": _MID_SHORT_V21_STRUCTURE_EXIT_CACHE_TTL_SECONDS,
            }
            return payload

    payload = json_safe(
        SignalCandidatePerformanceService(db).mid_short_1h_v21_structure_exit_study(
            include_watch_only=include_watch_only,
            position_lock=position_lock,
            min_sample=normalized_min_sample,
            limit=150,
        )
    )
    with _MID_SHORT_V21_STRUCTURE_EXIT_CACHE_LOCK:
        _MID_SHORT_V21_STRUCTURE_EXIT_CACHE[cache_key] = (monotonic(), payload)
    payload = dict(payload)
    payload["case_rows"] = list(payload.get("case_rows") or [])[:normalized_limit]
    payload["filters"] = {
        **dict(payload.get("filters") or {}),
        "limit": normalized_limit,
    }
    payload["cache"] = {
        "hit": False,
        "ttl_seconds": _MID_SHORT_V21_STRUCTURE_EXIT_CACHE_TTL_SECONDS,
    }
    return payload


@router.get("/api/signal-candidates/mid-short-1h-v2-1-dynamic-exit-study")
def signal_candidates_mid_short_1h_v21_dynamic_exit_study(
    include_watch_only: bool = False,
    position_lock: bool = True,
    min_sample: int = 20,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    normalized_limit = max(1, min(limit, 150))
    normalized_min_sample = max(1, min(min_sample, 100))
    cache_key = (
        bool(include_watch_only),
        bool(position_lock),
        normalized_min_sample,
    )
    now = monotonic()
    with _MID_SHORT_V21_DYNAMIC_EXIT_CACHE_LOCK:
        cached = _MID_SHORT_V21_DYNAMIC_EXIT_CACHE.get(cache_key)
        if cached and now - cached[0] <= _MID_SHORT_V21_DYNAMIC_EXIT_CACHE_TTL_SECONDS:
            payload = dict(cached[1])
            payload["case_rows"] = list(payload.get("case_rows") or [])[:normalized_limit]
            payload["filters"] = {
                **dict(payload.get("filters") or {}),
                "limit": normalized_limit,
            }
            payload["cache"] = {
                "hit": True,
                "ttl_seconds": _MID_SHORT_V21_DYNAMIC_EXIT_CACHE_TTL_SECONDS,
            }
            return payload

    payload = json_safe(
        SignalCandidatePerformanceService(db).mid_short_1h_v21_dynamic_exit_study(
            include_watch_only=include_watch_only,
            position_lock=position_lock,
            min_sample=normalized_min_sample,
            limit=150,
        )
    )
    with _MID_SHORT_V21_DYNAMIC_EXIT_CACHE_LOCK:
        _MID_SHORT_V21_DYNAMIC_EXIT_CACHE[cache_key] = (monotonic(), payload)
    payload = dict(payload)
    payload["case_rows"] = list(payload.get("case_rows") or [])[:normalized_limit]
    payload["filters"] = {
        **dict(payload.get("filters") or {}),
        "limit": normalized_limit,
    }
    payload["cache"] = {
        "hit": False,
        "ttl_seconds": _MID_SHORT_V21_DYNAMIC_EXIT_CACHE_TTL_SECONDS,
    }
    return payload


@router.get("/api/signal-candidates/mid-short-1h-volume-safe-shadow")
def signal_candidates_mid_short_1h_volume_safe_shadow(
    include_watch_only: bool = False,
    position_lock: bool = True,
    min_sample: int = 20,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    normalized_limit = max(1, min(limit, 150))
    normalized_min_sample = max(1, min(min_sample, 100))
    cache_key = (
        bool(include_watch_only),
        bool(position_lock),
        normalized_min_sample,
        normalized_limit,
    )
    now = monotonic()
    with _MID_SHORT_VOLUME_SAFE_CACHE_LOCK:
        cached = _MID_SHORT_VOLUME_SAFE_CACHE.get(cache_key)
        if cached and now - cached[0] <= _SIGNAL_PERFORMANCE_CACHE_TTL_SECONDS:
            payload = dict(cached[1])
            payload["cache"] = {"hit": True, "ttl_seconds": _SIGNAL_PERFORMANCE_CACHE_TTL_SECONDS}
            return payload

    payload = json_safe(
        SignalCandidatePerformanceService(db).mid_short_1h_volume_safe_shadow(
            include_watch_only=include_watch_only,
            position_lock=position_lock,
            min_sample=normalized_min_sample,
            limit=normalized_limit,
        )
    )
    payload["cache"] = {"hit": False, "ttl_seconds": _SIGNAL_PERFORMANCE_CACHE_TTL_SECONDS}
    with _MID_SHORT_VOLUME_SAFE_CACHE_LOCK:
        _MID_SHORT_VOLUME_SAFE_CACHE[cache_key] = (monotonic(), payload)
    return payload


@router.get("/api/signal-candidates/mid-short-1h-filter-combination-study")
def signal_candidates_mid_short_1h_filter_combination_study(
    include_watch_only: bool = False,
    position_lock: bool = True,
    min_sample: int = 20,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    normalized_limit = max(1, min(limit, 150))
    normalized_min_sample = max(1, min(min_sample, 100))
    cache_key = (
        bool(include_watch_only),
        bool(position_lock),
        normalized_min_sample,
        normalized_limit,
    )
    now = monotonic()
    with _MID_SHORT_FILTER_COMBO_CACHE_LOCK:
        cached = _MID_SHORT_FILTER_COMBO_CACHE.get(cache_key)
        if cached and now - cached[0] <= _SIGNAL_PERFORMANCE_CACHE_TTL_SECONDS:
            payload = dict(cached[1])
            payload["cache"] = {"hit": True, "ttl_seconds": _SIGNAL_PERFORMANCE_CACHE_TTL_SECONDS}
            return payload

    payload = json_safe(
        SignalCandidatePerformanceService(db).mid_short_1h_filter_combination_study(
            include_watch_only=include_watch_only,
            position_lock=position_lock,
            min_sample=normalized_min_sample,
            limit=normalized_limit,
        )
    )
    payload["cache"] = {"hit": False, "ttl_seconds": _SIGNAL_PERFORMANCE_CACHE_TTL_SECONDS}
    with _MID_SHORT_FILTER_COMBO_CACHE_LOCK:
        _MID_SHORT_FILTER_COMBO_CACHE[cache_key] = (monotonic(), payload)
    return payload


@router.get("/api/signal-candidates/filter-study")
def signal_candidates_filter_study(
    include_watch_only: bool = False,
    position_lock: bool = True,
    stage: str = "MID_SHORT",
    timeframe: str = "1h",
    min_sample: int = 20,
    limit: int = 40,
    db: Session = Depends(get_db),
):
    normalized_limit = max(1, min(limit, 100))
    normalized_min_sample = max(1, min(min_sample, 100))
    cache_key = (
        bool(include_watch_only),
        bool(position_lock),
        stage or "",
        timeframe or "",
        normalized_min_sample,
        normalized_limit,
    )
    now = monotonic()
    with _SIGNAL_FILTER_STUDY_CACHE_LOCK:
        cached = _SIGNAL_FILTER_STUDY_CACHE.get(cache_key)
        if cached and now - cached[0] <= _SIGNAL_PERFORMANCE_CACHE_TTL_SECONDS:
            payload = dict(cached[1])
            payload["cache"] = {"hit": True, "ttl_seconds": _SIGNAL_PERFORMANCE_CACHE_TTL_SECONDS}
            return payload

    payload = json_safe(
        SignalCandidatePerformanceService(db).filter_study(
            include_watch_only=include_watch_only,
            position_lock=position_lock,
            stage=stage,
            timeframe=timeframe,
            min_sample=normalized_min_sample,
            limit=normalized_limit,
        )
    )
    payload["cache"] = {"hit": False, "ttl_seconds": _SIGNAL_PERFORMANCE_CACHE_TTL_SECONDS}
    with _SIGNAL_FILTER_STUDY_CACHE_LOCK:
        _SIGNAL_FILTER_STUDY_CACHE[cache_key] = (monotonic(), payload)
    return payload


@router.get("/api/signal-candidates/misidentification-audit")
def signal_candidates_misidentification_audit(
    include_watch_only: bool = False,
    position_lock: bool = False,
    timeframe: str = "1h",
    stages: str = "MID_LONG,MID_SHORT",
    min_sample: int = 20,
    limit: int = 50,
    max_signals_per_stage: int = 120,
    db: Session = Depends(get_db),
):
    normalized_limit = max(1, min(limit, 100))
    normalized_min_sample = max(1, min(min_sample, 100))
    normalized_max_signals = max(20, min(max_signals_per_stage, 500))
    normalized_timeframe = timeframe or "1h"
    normalized_stages = tuple(
        stage.strip().upper()
        for stage in stages.split(",")
        if stage.strip()
    ) or ("MID_LONG", "MID_SHORT")
    cache_key = (
        bool(include_watch_only),
        bool(position_lock),
        normalized_timeframe,
        normalized_stages,
        normalized_min_sample,
        normalized_limit,
        normalized_max_signals,
    )
    now = monotonic()
    with _SIGNAL_MISIDENTIFICATION_CACHE_LOCK:
        cached = _SIGNAL_MISIDENTIFICATION_CACHE.get(cache_key)
        if cached and now - cached[0] <= _SIGNAL_PERFORMANCE_CACHE_TTL_SECONDS:
            payload = dict(cached[1])
            payload["cache"] = {"hit": True, "ttl_seconds": _SIGNAL_PERFORMANCE_CACHE_TTL_SECONDS}
            return payload

    if not include_watch_only and normalized_timeframe == "1h":
        try:
            payload = json_safe(
                SignalPerformanceSnapshotService().misidentification_audit_1h(
                    stages=normalized_stages,
                    min_sample=normalized_min_sample,
                    limit=normalized_limit,
                    max_signals_per_stage=normalized_max_signals,
                )
            )
        except FileNotFoundError:
            payload = json_safe(
                SignalCandidatePerformanceService(db).misidentification_audit(
                    include_watch_only=include_watch_only,
                    position_lock=position_lock,
                    timeframe=normalized_timeframe,
                    stages=normalized_stages,
                    min_sample=normalized_min_sample,
                    limit=normalized_limit,
                    max_signals_per_stage=normalized_max_signals,
                )
            )
    else:
        payload = json_safe(
            SignalCandidatePerformanceService(db).misidentification_audit(
                include_watch_only=include_watch_only,
                position_lock=position_lock,
                timeframe=normalized_timeframe,
                stages=normalized_stages,
                min_sample=normalized_min_sample,
                limit=normalized_limit,
                max_signals_per_stage=normalized_max_signals,
            )
        )
    payload["cache"] = {"hit": False, "ttl_seconds": _SIGNAL_PERFORMANCE_CACHE_TTL_SECONDS}
    with _SIGNAL_MISIDENTIFICATION_CACHE_LOCK:
        _SIGNAL_MISIDENTIFICATION_CACHE[cache_key] = (monotonic(), payload)
    return payload


@router.get("/api/signal-candidates/one-hour-filter-study")
def signal_candidates_one_hour_filter_study(
    include_watch_only: bool = False,
    position_lock: bool = True,
    min_sample: int = 20,
    limit: int = 12,
    db: Session = Depends(get_db),
):
    normalized_limit = max(1, min(limit, 50))
    normalized_min_sample = max(1, min(min_sample, 100))
    cache_key = (
        bool(include_watch_only),
        bool(position_lock),
        normalized_min_sample,
        normalized_limit,
    )
    now = monotonic()
    with _SIGNAL_ONE_HOUR_FILTER_STUDY_CACHE_LOCK:
        cached = _SIGNAL_ONE_HOUR_FILTER_STUDY_CACHE.get(cache_key)
        if cached and now - cached[0] <= _SIGNAL_PERFORMANCE_CACHE_TTL_SECONDS:
            payload = dict(cached[1])
            payload["cache"] = {"hit": True, "ttl_seconds": _SIGNAL_PERFORMANCE_CACHE_TTL_SECONDS}
            return payload

    if not include_watch_only and position_lock:
        try:
            payload = json_safe(
                SignalPerformanceSnapshotService().one_hour_filter_candidate_study(
                    min_sample=normalized_min_sample,
                    limit=normalized_limit,
                )
            )
        except FileNotFoundError:
            payload = json_safe(
                SignalCandidatePerformanceService(db).one_hour_filter_candidate_study(
                    include_watch_only=include_watch_only,
                    position_lock=position_lock,
                    min_sample=normalized_min_sample,
                    limit=normalized_limit,
                )
            )
    else:
        payload = json_safe(
            SignalCandidatePerformanceService(db).one_hour_filter_candidate_study(
                include_watch_only=include_watch_only,
                position_lock=position_lock,
                min_sample=normalized_min_sample,
                limit=normalized_limit,
            )
        )
    payload["cache"] = {"hit": False, "ttl_seconds": _SIGNAL_PERFORMANCE_CACHE_TTL_SECONDS}
    with _SIGNAL_ONE_HOUR_FILTER_STUDY_CACHE_LOCK:
        _SIGNAL_ONE_HOUR_FILTER_STUDY_CACHE[cache_key] = (monotonic(), payload)
    return payload


@router.get("/api/signal-candidates/one-hour-walk-forward")
def signal_candidates_one_hour_walk_forward(
    include_watch_only: bool = False,
    position_lock: bool = True,
    min_sample: int = 20,
    limit: int = 12,
    db: Session = Depends(get_db),
):
    normalized_limit = max(1, min(limit, 50))
    normalized_min_sample = max(1, min(min_sample, 100))
    cache_key = (
        bool(include_watch_only),
        bool(position_lock),
        normalized_min_sample,
        normalized_limit,
    )
    now = monotonic()
    with _SIGNAL_ONE_HOUR_WALK_FORWARD_CACHE_LOCK:
        cached = _SIGNAL_ONE_HOUR_WALK_FORWARD_CACHE.get(cache_key)
        if cached and now - cached[0] <= _SIGNAL_PERFORMANCE_CACHE_TTL_SECONDS:
            payload = dict(cached[1])
            payload["cache"] = {"hit": True, "ttl_seconds": _SIGNAL_PERFORMANCE_CACHE_TTL_SECONDS}
            return payload

    if not include_watch_only and position_lock:
        try:
            payload = json_safe(
                SignalPerformanceSnapshotService().one_hour_walk_forward_study(
                    min_sample=normalized_min_sample,
                    limit=normalized_limit,
                )
            )
        except FileNotFoundError:
            payload = json_safe(
                SignalCandidatePerformanceService(db).one_hour_walk_forward_study(
                    include_watch_only=include_watch_only,
                    position_lock=position_lock,
                    min_sample=normalized_min_sample,
                    limit=normalized_limit,
                )
            )
    else:
        payload = json_safe(
            SignalCandidatePerformanceService(db).one_hour_walk_forward_study(
                include_watch_only=include_watch_only,
                position_lock=position_lock,
                min_sample=normalized_min_sample,
                limit=normalized_limit,
            )
        )
    payload["cache"] = {"hit": False, "ttl_seconds": _SIGNAL_PERFORMANCE_CACHE_TTL_SECONDS}
    with _SIGNAL_ONE_HOUR_WALK_FORWARD_CACHE_LOCK:
        _SIGNAL_ONE_HOUR_WALK_FORWARD_CACHE[cache_key] = (monotonic(), payload)
    return payload


@router.get("/api/signal-candidates/one-hour-v4-shadow")
def signal_candidates_one_hour_v4_shadow(
    include_watch_only: bool = False,
    position_lock: bool = True,
    min_sample: int = 20,
    limit: int = 20,
    db: Session = Depends(get_db),
):
    normalized_limit = max(1, min(limit, 100))
    normalized_min_sample = max(1, min(min_sample, 100))
    cache_key = (
        bool(include_watch_only),
        bool(position_lock),
        normalized_min_sample,
        normalized_limit,
    )
    now = monotonic()
    with _SIGNAL_ONE_HOUR_V4_SHADOW_CACHE_LOCK:
        cached = _SIGNAL_ONE_HOUR_V4_SHADOW_CACHE.get(cache_key)
        if cached and now - cached[0] <= _SIGNAL_PERFORMANCE_CACHE_TTL_SECONDS:
            payload = dict(cached[1])
            payload["cache"] = {"hit": True, "ttl_seconds": _SIGNAL_PERFORMANCE_CACHE_TTL_SECONDS}
            return payload

    if not include_watch_only and position_lock:
        try:
            payload = json_safe(
                SignalPerformanceSnapshotService().one_hour_v4_shadow_monitor(
                    min_sample=normalized_min_sample,
                    limit=normalized_limit,
                )
            )
        except FileNotFoundError:
            payload = json_safe(
                SignalCandidatePerformanceService(db).one_hour_v4_shadow_monitor(
                    include_watch_only=include_watch_only,
                    position_lock=position_lock,
                    min_sample=normalized_min_sample,
                    limit=normalized_limit,
                )
            )
    else:
        payload = json_safe(
            SignalCandidatePerformanceService(db).one_hour_v4_shadow_monitor(
                include_watch_only=include_watch_only,
                position_lock=position_lock,
                min_sample=normalized_min_sample,
                limit=normalized_limit,
            )
        )
    payload["cache"] = {"hit": False, "ttl_seconds": _SIGNAL_PERFORMANCE_CACHE_TTL_SECONDS}
    with _SIGNAL_ONE_HOUR_V4_SHADOW_CACHE_LOCK:
        _SIGNAL_ONE_HOUR_V4_SHADOW_CACHE[cache_key] = (monotonic(), payload)
    return payload


@router.get("/api/signal-candidates/calibration-lab")
def signal_candidates_calibration_lab(
    include_watch_only: bool = False,
    position_lock: bool = True,
    min_sample: int = 5,
    limit: int = 30,
    db: Session = Depends(get_db),
):
    normalized_limit = max(1, min(limit, 100))
    normalized_min_sample = max(1, min(min_sample, 100))
    cache_key = (
        bool(include_watch_only),
        bool(position_lock),
        normalized_min_sample,
        normalized_limit,
    )
    now = monotonic()
    with _SIGNAL_CALIBRATION_CACHE_LOCK:
        cached = _SIGNAL_CALIBRATION_CACHE.get(cache_key)
        if cached and now - cached[0] <= _SIGNAL_PERFORMANCE_CACHE_TTL_SECONDS:
            payload = dict(cached[1])
            payload["cache"] = {"hit": True, "ttl_seconds": _SIGNAL_PERFORMANCE_CACHE_TTL_SECONDS}
            return payload

    payload = json_safe(
        SignalCandidatePerformanceService(db).calibration_lab(
            include_watch_only=include_watch_only,
            position_lock=position_lock,
            min_sample=normalized_min_sample,
            limit=normalized_limit,
        )
    )
    payload["cache"] = {"hit": False, "ttl_seconds": _SIGNAL_PERFORMANCE_CACHE_TTL_SECONDS}
    with _SIGNAL_CALIBRATION_CACHE_LOCK:
        _SIGNAL_CALIBRATION_CACHE[cache_key] = (monotonic(), payload)
    return payload


@router.get("/api/v3-shadow/comparison")
def v3_shadow_comparison(
    include_watch_only: bool = False,
    position_lock: bool = True,
    stage: str | None = None,
    timeframe: str | None = None,
    min_sample: int = 5,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    normalized_limit = max(1, min(limit, 200))
    normalized_min_sample = max(1, min(min_sample, 100))
    normalized_stage = None if stage in {"", "ALL"} else stage
    normalized_timeframe = None if timeframe in {"", "ALL"} else timeframe
    cache_key = (
        bool(include_watch_only),
        bool(position_lock),
        normalized_stage or "",
        normalized_timeframe or "",
        normalized_min_sample,
        normalized_limit,
    )
    now = monotonic()
    with _V3_SHADOW_COMPARISON_CACHE_LOCK:
        cached = _V3_SHADOW_COMPARISON_CACHE.get(cache_key)
        if cached and now - cached[0] <= _SIGNAL_PERFORMANCE_CACHE_TTL_SECONDS:
            payload = dict(cached[1])
            payload["cache"] = {"hit": True, "ttl_seconds": _SIGNAL_PERFORMANCE_CACHE_TTL_SECONDS}
            return payload

    payload = json_safe(
        SignalCandidatePerformanceService(db).v3_shadow_comparison(
            include_watch_only=include_watch_only,
            position_lock=position_lock,
            stage=normalized_stage,
            timeframe=normalized_timeframe,
            min_sample=normalized_min_sample,
            limit=normalized_limit,
        )
    )
    payload["cache"] = {"hit": False, "ttl_seconds": _SIGNAL_PERFORMANCE_CACHE_TTL_SECONDS}
    with _V3_SHADOW_COMPARISON_CACHE_LOCK:
        _V3_SHADOW_COMPARISON_CACHE[cache_key] = (monotonic(), payload)
    return payload


@router.get("/api/v3-shadow/forward-log")
def v3_shadow_forward_log(
    include_watch_only: bool = False,
    position_lock: bool = True,
    stage: str | None = None,
    timeframe: str | None = None,
    min_sample: int = 5,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    normalized_limit = max(1, min(limit, 200))
    normalized_min_sample = max(1, min(min_sample, 100))
    normalized_stage = None if stage in {"", "ALL"} else stage
    normalized_timeframe = None if timeframe in {"", "ALL"} else timeframe
    cache_key = (
        bool(include_watch_only),
        bool(position_lock),
        normalized_stage or "",
        normalized_timeframe or "",
        normalized_min_sample,
        normalized_limit,
    )
    now = monotonic()
    with _V3_SHADOW_FORWARD_CACHE_LOCK:
        cached = _V3_SHADOW_FORWARD_CACHE.get(cache_key)
        if cached and now - cached[0] <= _SIGNAL_PERFORMANCE_CACHE_TTL_SECONDS:
            payload = dict(cached[1])
            payload["cache"] = {"hit": True, "ttl_seconds": _SIGNAL_PERFORMANCE_CACHE_TTL_SECONDS}
            return payload

    payload = json_safe(
        SignalCandidatePerformanceService(db).v3_shadow_forward_log(
            include_watch_only=include_watch_only,
            position_lock=position_lock,
            stage=normalized_stage,
            timeframe=normalized_timeframe,
            min_sample=normalized_min_sample,
            limit=normalized_limit,
        )
    )
    payload["cache"] = {"hit": False, "ttl_seconds": _SIGNAL_PERFORMANCE_CACHE_TTL_SECONDS}
    with _V3_SHADOW_FORWARD_CACHE_LOCK:
        _V3_SHADOW_FORWARD_CACHE[cache_key] = (monotonic(), payload)
    return payload


@router.get("/api/strategy-optimization-lab")
def strategy_optimization_lab(
    include_watch_only: bool = False,
    position_lock: bool = True,
    stage: str | None = "MID_SHORT",
    timeframe: str | None = "1h",
    min_sample: int = 20,
    limit: int = 80,
    db: Session = Depends(get_db),
):
    normalized_limit = max(1, min(limit, 200))
    normalized_min_sample = max(1, min(min_sample, 200))
    normalized_stage = None if stage in {"", "ALL"} else stage
    normalized_timeframe = None if timeframe in {"", "ALL"} else timeframe
    artifact_payload = StrategyOptimizationArtifactService().optimization_for(
        include_watch_only=include_watch_only,
        position_lock=position_lock,
        stage=normalized_stage,
        timeframe=normalized_timeframe,
        min_sample=normalized_min_sample,
        limit=normalized_limit,
    )
    if artifact_payload:
        artifact_payload["cache"] = {"hit": True, "source": "artifact", "ttl_seconds": None}
        return json_safe(artifact_payload)

    cache_key = (
        bool(include_watch_only),
        bool(position_lock),
        normalized_stage or "",
        normalized_timeframe or "",
        normalized_min_sample,
        normalized_limit,
    )
    now = monotonic()
    with _STRATEGY_OPTIMIZATION_CACHE_LOCK:
        cached = _STRATEGY_OPTIMIZATION_CACHE.get(cache_key)
        if cached and now - cached[0] <= _SIGNAL_PERFORMANCE_CACHE_TTL_SECONDS:
            payload = dict(cached[1])
            payload["cache"] = {"hit": True, "ttl_seconds": _SIGNAL_PERFORMANCE_CACHE_TTL_SECONDS}
            return payload

    payload = json_safe(
        StrategyOptimizationLabService(db).summary(
            include_watch_only=include_watch_only,
            position_lock=position_lock,
            stage=normalized_stage,
            timeframe=normalized_timeframe,
            min_sample=normalized_min_sample,
            limit=normalized_limit,
        )
    )
    payload["cache"] = {"hit": False, "ttl_seconds": _SIGNAL_PERFORMANCE_CACHE_TTL_SECONDS}
    with _STRATEGY_OPTIMIZATION_CACHE_LOCK:
        _STRATEGY_OPTIMIZATION_CACHE[cache_key] = (monotonic(), payload)
    return payload


@router.get("/api/strategy-optimization-regime-split")
def strategy_optimization_regime_split(
    include_watch_only: bool = False,
    position_lock: bool = True,
    stage: str = "MID_SHORT",
    timeframe: str = "1h",
    atr_mult: str = "0.75",
    rr: str = "2.0",
    timeout_minutes: int = 480,
    min_sample: int = 20,
    limit: int = 80,
    db: Session = Depends(get_db),
):
    normalized_limit = max(1, min(limit, 200))
    normalized_min_sample = max(1, min(min_sample, 200))
    normalized_timeout = max(15, min(timeout_minutes, 1440))
    try:
        normalized_atr_mult = Decimal(str(atr_mult))
        normalized_rr = Decimal(str(rr))
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid atr_mult or rr") from exc
    artifact_payload = StrategyOptimizationArtifactService().regime_for(
        include_watch_only=include_watch_only,
        position_lock=position_lock,
        stage=stage,
        timeframe=timeframe,
        atr_mult=normalized_atr_mult,
        rr=normalized_rr,
        timeout_minutes=normalized_timeout,
        min_sample=normalized_min_sample,
        limit=normalized_limit,
    )
    if artifact_payload:
        artifact_payload["cache"] = {"hit": True, "source": "artifact", "ttl_seconds": None}
        return json_safe(artifact_payload)

    cache_key = (
        bool(include_watch_only),
        bool(position_lock),
        stage,
        timeframe,
        str(normalized_atr_mult),
        str(normalized_rr),
        normalized_timeout,
        normalized_min_sample,
        normalized_limit,
    )
    now = monotonic()
    with _STRATEGY_REGIME_SPLIT_CACHE_LOCK:
        cached = _STRATEGY_REGIME_SPLIT_CACHE.get(cache_key)
        if cached and now - cached[0] <= _SIGNAL_PERFORMANCE_CACHE_TTL_SECONDS:
            payload = dict(cached[1])
            payload["cache"] = {"hit": True, "ttl_seconds": _SIGNAL_PERFORMANCE_CACHE_TTL_SECONDS}
            return payload

    payload = json_safe(
        StrategyOptimizationRegimeSplitService(db).summary(
            include_watch_only=include_watch_only,
            position_lock=position_lock,
            stage=stage,
            timeframe=timeframe,
            atr_mult=normalized_atr_mult,
            rr=normalized_rr,
            timeout_minutes=normalized_timeout,
            min_sample=normalized_min_sample,
            limit=normalized_limit,
        )
    )
    payload["cache"] = {"hit": False, "ttl_seconds": _SIGNAL_PERFORMANCE_CACHE_TTL_SECONDS}
    with _STRATEGY_REGIME_SPLIT_CACHE_LOCK:
        _STRATEGY_REGIME_SPLIT_CACHE[cache_key] = (monotonic(), payload)
    return payload


@router.get("/api/strategy-optimization-artifacts")
def strategy_optimization_artifacts():
    try:
        return json_safe(StrategyOptimizationArtifactService().summary())
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail="Strategy optimization artifact not found. Run run_strategy_optimization_artifacts.py first.",
        ) from exc


@router.get("/api/signal-candidates/market-regime-study")
def signal_candidates_market_regime_study():
    artifact_path = DEFAULT_MARKET_REGIME_STUDY_DIR / "results.json"
    if not artifact_path.exists():
        raise HTTPException(
            status_code=404,
            detail="Market regime study artifact not found. Run run_market_regime_study_v1.py first.",
        )
    return json_safe(json.loads(artifact_path.read_text(encoding="utf-8")))


@router.get("/api/outcomes/15m/status")
def outcomes_15m_status(db: Session = Depends(get_db)):
    return json_safe(OutcomeTracker15mService(db).status_summary())


@router.get("/api/outcomes/15m/summary")
def outcomes_15m_summary(db: Session = Depends(get_db)):
    return json_safe(OutcomeSummaryReadonly15mService(db).summary())


@router.get("/api/outcomes/15m")
def outcomes_15m(symbol: str | None = None, limit: int = 100, db: Session = Depends(get_db)):
    rows = OutcomeTracker15mService(db).list_outcomes(symbol=symbol, limit=limit)
    return json_safe(
        {
            "count": len(rows),
            "items": [model_to_dict(row) for row in rows],
        }
    )


@router.get("/api/scanner/live")
def scanner_live(
    tier: str | None = None,
    candidate_type: str | None = None,
    limit: int = 100,
    include_blocked: bool = False,
    include_inactive: bool = False,
    include_v3_shadow: bool = False,
    db: Session = Depends(get_db),
):
    normalized_limit = max(1, min(limit, 500))
    cache_key = (
        tier or "",
        candidate_type or "",
        normalized_limit,
        bool(include_blocked),
        bool(include_inactive),
        bool(include_v3_shadow),
    )
    now = monotonic()
    with _SCANNER_LIVE_CACHE_LOCK:
        cached = _SCANNER_LIVE_CACHE.get(cache_key)
        if cached and now - cached[0] <= _SIGNAL_PERFORMANCE_CACHE_TTL_SECONDS:
            payload = dict(cached[1])
            payload["cache"] = {"hit": True, "ttl_seconds": _SIGNAL_PERFORMANCE_CACHE_TTL_SECONDS}
            return payload

    items = LiveCandidateScannerService(db, signal_factory_artifact_dir=DEFAULT_SIGNAL_FACTORY_DIR).list_live(
        tier=tier,
        candidate_type=candidate_type,
        limit=normalized_limit,
        include_blocked=include_blocked,
        include_inactive=include_inactive,
        include_v3_shadow=include_v3_shadow,
    )
    tier_counts: dict[str, int] = {}
    for item in items:
        tier_counts[item["scanner_tier"]] = tier_counts.get(item["scanner_tier"], 0) + 1
    payload = json_safe(
        {
            "count": len(items),
            "filters": {
                "tier": tier,
                "candidate_type": candidate_type,
                "limit": normalized_limit,
                "include_blocked": include_blocked,
                "include_inactive": include_inactive,
                "include_v3_shadow": include_v3_shadow,
            },
            "tier_counts": tier_counts,
            "read_only": True,
            "not_entry_signal": True,
            "items": items,
            "cache": {"hit": False, "ttl_seconds": _SIGNAL_PERFORMANCE_CACHE_TTL_SECONDS},
        }
    )
    with _SCANNER_LIVE_CACHE_LOCK:
        _SCANNER_LIVE_CACHE[cache_key] = (monotonic(), payload)
    return payload


@router.get("/api/paper-signals/short-candidates")
def paper_short_candidates(
    limit: int = 100,
    include_rejected: bool = True,
    db: Session = Depends(get_db),
):
    return PaperSignalEvaluatorService(db).list_short_candidates(
        limit=limit,
        include_rejected=include_rejected,
    )


@router.get("/api/strategy-arena/v1/leaderboard")
def strategy_arena_v1_leaderboard():
    try:
        return json_safe(StrategyArenaArtifactService().leaderboard())
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/api/strategy-arena/v1/results")
def strategy_arena_v1_results():
    try:
        return json_safe(StrategyArenaArtifactService().results())
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/api/strategy-arena/v1/setup/{setup_family}")
def strategy_arena_v1_setup(setup_family: str):
    try:
        return json_safe(StrategyArenaArtifactService().setup(setup_family))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/api/backtests/early-lab/summary")
def early_backtest_lab_summary():
    try:
        return json_safe(EarlyBacktestLabArtifactService().summary())
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Early backtest artifact not found. Run signal factory v2 backtest script first.") from exc


@router.get("/api/backtests/early-lab/events")
def early_backtest_lab_events(
    stage: str | None = None,
    horizon: str = "4h",
    outcome: str | None = None,
    limit: int = 200,
):
    try:
        return json_safe(
            EarlyBacktestLabArtifactService().events(
                stage=stage,
                horizon=horizon,
                outcome=outcome,
                limit=limit,
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Early backtest artifact not found. Run signal factory v2 backtest script first.") from exc


@router.get("/api/signal-factory/v1/summary")
def signal_factory_v1_summary():
    try:
        return json_safe(SignalFactoryArtifactService().summary())
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Signal factory artifact not found. Run signal factory script first.") from exc


@router.get("/api/signal-factory/v1/candidates")
def signal_factory_v1_candidates(
    timeframe: str | None = None,
    setup_type: str | None = None,
    direction: str | None = None,
    confidence: str | None = None,
    symbol: str | None = None,
    status: str | None = None,
    limit: int = 100,
):
    try:
        return json_safe(
            SignalFactoryArtifactService().candidates(
                timeframe=timeframe,
                setup_type=setup_type,
                direction=direction,
                confidence=confidence,
                symbol=symbol,
                status=status,
                limit=limit,
            )
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Signal factory artifact not found. Run signal factory script first.") from exc


@router.get("/api/signal-factory/v1/candidates/{symbol}")
def signal_factory_v1_symbol(symbol: str):
    try:
        return json_safe(SignalFactoryArtifactService().candidates_for_symbol(symbol))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Signal factory artifact not found. Run signal factory script first.") from exc


@router.get("/api/phase6/readiness")
def phase6_readiness():
    try:
        return json_safe(Phase6ArtifactService().readiness())
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Phase 6 artifact not found. Run phase6 readiness audit script first.") from exc


@router.get("/api/phase6/edge-audit")
def phase6_edge_audit():
    try:
        return json_safe(Phase6ArtifactService().edge_audit())
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Phase 6 artifact not found. Run phase6 readiness audit script first.") from exc


@router.get("/api/phase6/phase7-decision")
def phase6_phase7_decision():
    try:
        return json_safe(Phase6ArtifactService().phase7_decision())
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Phase 6 artifact not found. Run phase6 readiness audit script first.") from exc


@router.get("/api/phase7/full-blocker-audit")
def phase7_full_blocker_audit():
    path = DEFAULT_PHASE6_DIR / "phase7_full_blocker_audit.json"
    try:
        return json_safe(json.loads(path.read_text()))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Phase 7 full blocker audit artifact not found. Run full blocker audit script first.") from exc


@router.get("/api/phase7/candidate-evidence")
def phase7_candidate_evidence(
    symbol: str | None = None,
    timeframe: str | None = None,
    status: str | None = None,
    limit: int = 100,
):
    try:
        return json_safe(
            CandidateNumericEvidenceArtifactService().read(
                symbol=symbol,
                timeframe=timeframe,
                status=status,
                limit=limit,
            )
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Candidate numeric evidence artifact not found. Run candidate numeric evidence audit script first.") from exc


@router.get("/api/phase7/status")
def phase7_forward_status():
    return json_safe(Phase7ForwardTestArtifactService().status())


@router.get("/api/phase7/events")
def phase7_forward_events():
    return json_safe(Phase7ForwardTestArtifactService().events())


@router.get("/api/phase7/results")
def phase7_forward_results():
    return json_safe(Phase7ForwardTestArtifactService().results())


@router.get("/api/phase7/summary")
def phase7_forward_summary():
    return json_safe(Phase7ForwardTestArtifactService().summary())


@router.get("/api/rich-futures/status")
def rich_futures_status(db: Session = Depends(get_db)):
    latest = {
        "taker_buy_sell_latest": _max_time(db, FuturesTakerBuySellVolume.timestamp),
        "global_long_short_latest": _max_time(db, FuturesGlobalLongShortAccountRatio.timestamp),
        "top_trader_position_latest": _max_time(db, FuturesTopTraderPositionRatio.timestamp),
        "top_trader_account_latest": _max_time(db, FuturesTopTraderAccountRatio.timestamp),
        "open_interest_history_latest": _max_time(db, FuturesOpenInterestHistory.timestamp),
        "funding_history_latest": _max_time(db, FuturesFundingHistory.funding_time),
        "liquidation_stream_status": "NOT_RUNNING",
    }
    table_counts = {
        "futures_taker_buy_sell_volume": _table_count(db, FuturesTakerBuySellVolume),
        "futures_global_long_short_account_ratio": _table_count(db, FuturesGlobalLongShortAccountRatio),
        "futures_top_trader_position_ratio": _table_count(db, FuturesTopTraderPositionRatio),
        "futures_top_trader_account_ratio": _table_count(db, FuturesTopTraderAccountRatio),
        "futures_open_interest_history": _table_count(db, FuturesOpenInterestHistory),
        "futures_funding_history": _table_count(db, FuturesFundingHistory),
    }
    collectors = db.scalars(
        select(CollectorRun)
        .where(CollectorRun.collector_name.like("rich_futures_%"))
        .order_by(desc(CollectorRun.started_at))
        .limit(50)
    ).all()
    universe_counts = _active_universe_counts(db)
    return json_safe(
        {
            "latest": latest,
            "table_counts": table_counts,
            "alignment": Rich5mAlignmentService(db).status_summary(),
            "universe": universe_counts,
            "collectors": [_collector_run_payload(run) for run in collectors],
        }
    )


@router.get("/api/tokens/{symbol}")
def token_detail(symbol: str, db: Session = Depends(get_db)):
    normalized = symbol.upper()
    active = db.scalar(select(MarketlabActiveUniverse).where(MarketlabActiveUniverse.symbol == normalized))
    if not active:
        raise HTTPException(status_code=404, detail="symbol not found in universe history")

    latest_health = db.scalar(
        select(DataHealthSnapshot)
        .where(DataHealthSnapshot.symbol == normalized)
        .order_by(desc(DataHealthSnapshot.snapshot_time))
        .limit(1)
    )
    health_payload = model_to_dict(latest_health) if latest_health else None
    if health_payload:
        raw_json = health_payload.get("raw_json") or {}
        health_payload["status"] = _normalize_health_status(raw_json.get("status") or health_payload.get("status"))
        if raw_json.get("reason"):
            health_payload["reason"] = raw_json["reason"]

    payload = {
        "symbol": normalized,
        "universe": model_to_dict(active),
        "health": health_payload,
        "latest": {
            "futures_candle": _latest_row(db, FuturesKline1m, normalized, FuturesKline1m.close_time),
            "spot_candle": _latest_row(db, SpotKline1m, normalized, SpotKline1m.close_time),
            "open_interest": _latest_row(db, FuturesOpenInterest, normalized, FuturesOpenInterest.event_time),
            "mark_funding": _latest_row(db, FuturesMarkFunding, normalized, FuturesMarkFunding.event_time),
            "futures_book": _latest_row(db, FuturesBookTicker, normalized, FuturesBookTicker.event_time),
            "spot_book": _latest_row(db, SpotBookTicker, normalized, SpotBookTicker.event_time),
        },
    }
    return json_safe(payload)


@router.get("/api/tokens/{symbol}/raw-status")
def token_raw_status(symbol: str, db: Session = Depends(get_db)):
    normalized = symbol.upper()
    errors = db.scalars(
        select(CollectorError)
        .where((CollectorError.symbol == normalized) | (CollectorError.symbol.is_(None)))
        .order_by(desc(CollectorError.created_at))
        .limit(25)
    ).all()
    return {
        "symbol": normalized,
        "raw": {
            "futures_candle": _latest_raw(db, FuturesKline1m, normalized, FuturesKline1m.close_time),
            "spot_candle": _latest_raw(db, SpotKline1m, normalized, SpotKline1m.close_time),
            "open_interest": _latest_raw(db, FuturesOpenInterest, normalized, FuturesOpenInterest.event_time),
            "mark_funding": _latest_raw(db, FuturesMarkFunding, normalized, FuturesMarkFunding.event_time),
            "futures_book": _latest_raw(db, FuturesBookTicker, normalized, FuturesBookTicker.event_time),
            "spot_book": _latest_raw(db, SpotBookTicker, normalized, SpotBookTicker.event_time),
        },
        "recent_errors": [model_to_dict(row) for row in errors],
    }


def _max_time(db: Session, column):
    return db.scalar(select(func.max(column)))


def _latest_row(db: Session, model, symbol: str, order_column):
    row = db.scalar(select(model).where(model.symbol == symbol).order_by(desc(order_column)).limit(1))
    return model_to_dict(row) if row else None


def _latest_raw(db: Session, model, symbol: str, order_column):
    row = db.scalar(select(model).where(model.symbol == symbol).order_by(desc(order_column)).limit(1))
    return json_safe(row.raw_json) if row else None


def _table_count(db: Session, model) -> int:
    return db.scalar(select(func.count()).select_from(model)) or 0


def _collector_run_payload(run: CollectorRun) -> dict:
    payload = model_to_dict(run)
    duration = run.duration_seconds
    if duration is None and run.finished_at is not None:
        duration = duration_seconds(run.started_at, run.finished_at)
    payload.update(
        {
            "start_time": json_safe(run.started_at),
            "end_time": json_safe(run.finished_at),
            "duration": duration,
            "rows_inserted": run.inserted_count,
            "rows_updated": run.updated_count,
            "errors_count": run.error_count,
        }
    )
    return payload


def _latest_health_items(db: Session) -> list[dict]:
    latest_snapshot = (
        select(
            DataHealthSnapshot.symbol.label("symbol"),
            func.max(DataHealthSnapshot.snapshot_time).label("snapshot_time"),
        )
        .group_by(DataHealthSnapshot.symbol)
        .subquery()
    )
    rows = db.execute(
        select(DataHealthSnapshot, MarketlabActiveUniverse)
        .join(MarketlabActiveUniverse, MarketlabActiveUniverse.symbol == DataHealthSnapshot.symbol)
        .join(
            latest_snapshot,
            (latest_snapshot.c.symbol == DataHealthSnapshot.symbol)
            & (latest_snapshot.c.snapshot_time == DataHealthSnapshot.snapshot_time),
        )
        .where(MarketlabActiveUniverse.is_active.is_(True))
        .order_by(MarketlabActiveUniverse.rank.asc())
    ).all()
    items = []
    for row, universe_row in rows:
        item = model_to_dict(row)
        raw_json = item.get("raw_json") or {}
        item.update(
            {
                "rank": universe_row.rank,
                "rank_volume": universe_row.quote_volume,
                "quote_volume": universe_row.quote_volume,
                "collection_tier": universe_row.collection_tier,
                "is_full_active": universe_row.is_full_active,
                "is_light_watch": universe_row.is_light_watch,
                "is_signal_eligible": universe_row.is_signal_eligible,
            }
        )
        if raw_json.get("status"):
            item["status"] = _normalize_health_status(raw_json["status"])
        else:
            item["status"] = _normalize_health_status(item.get("status"))
        if raw_json.get("reason"):
            item["reason"] = raw_json["reason"]
        items.append(item)
    return items


def _latest_market_times(items: list[dict]) -> dict[str, object]:
    fields = (
        "latest_futures_candle_time",
        "latest_spot_candle_time",
        "latest_open_interest_time",
        "latest_funding_time",
    )
    return {
        field: max((item[field] for item in items if item.get(field) is not None), default=None)
        for field in fields
    }


def _active_universe_counts(db: Session) -> dict[str, int]:
    rows = db.scalars(
        select(MarketlabActiveUniverse)
        .where(MarketlabActiveUniverse.is_active.is_(True))
        .order_by(MarketlabActiveUniverse.rank.asc())
    ).all()
    return {
        "active_universe_count": len(rows),
        "universe_count": len(rows),
        "full_active_count": sum(1 for row in rows if row.collection_tier == "FULL_ACTIVE"),
        "light_watch_count": sum(1 for row in rows if row.collection_tier == "LIGHT_WATCH"),
        "signal_eligible_count": sum(1 for row in rows if row.is_signal_eligible),
    }


def _default_signal_performance_snapshot(
    *,
    include_watch_only: bool,
    position_lock: bool,
    stage: str | None,
    timeframe: str | None,
    symbol: str | None,
    result_status: str | None,
    limit: int,
) -> dict | None:
    if include_watch_only or not position_lock or stage or timeframe or symbol:
        if not (timeframe == "1h" and not include_watch_only and position_lock and not stage and not symbol):
            return None
    if (result_status or "").lower() != "closed":
        return None
    try:
        service = SignalPerformanceSnapshotService()
        return service.performance_1h(limit=limit) if timeframe == "1h" else service.performance(limit=limit)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def _default_forward_integrity_snapshot(
    *,
    include_watch_only: bool,
    position_lock: bool,
    stage: str | None,
    timeframe: str | None,
    limit: int,
) -> dict | None:
    if include_watch_only or not position_lock or stage or timeframe:
        if not (timeframe == "1h" and not include_watch_only and position_lock and not stage):
            return None
    try:
        service = SignalPerformanceSnapshotService()
        return service.forward_integrity_1h(limit=limit) if timeframe == "1h" else service.forward_integrity(limit=limit)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def _normalize_health_status(status: str | None) -> str:
    legacy = {
        "FULL_READY": "READY",
        "FULL_WARMUP": "WARMUP",
        "FULL_STALE": "STALE",
        "FULL_MISSING_SPOT": "MISSING_SPOT",
        "FULL_MISSING_FUTURES": "MISSING_FUTURES",
        "FULL_MISSING_OI": "MISSING_OI",
        "FULL_MISSING_FUNDING": "MISSING_FUNDING",
        "LIGHT_WATCH": "NOT_ACTIVE",
    }
    return legacy.get(status or "", status or "NOT_ACTIVE")


def _rich_status_by_symbol(db: Session, symbols: list[str]) -> dict[str, dict[str, str]]:
    if not symbols:
        return {}
    unique_symbols = sorted(set(symbols))
    sources = [
        ("taker buy/sell", FuturesTakerBuySellVolume, 15),
        ("global long/short", FuturesGlobalLongShortAccountRatio, 15),
        ("top trader position", FuturesTopTraderPositionRatio, 15),
        ("top trader account", FuturesTopTraderAccountRatio, 15),
        ("open interest history", FuturesOpenInterestHistory, 15),
    ]
    latest_by_source: dict[str, dict[str, object]] = {}
    for label, model, _max_age_minutes in sources:
        latest_timestamp = (
            select(model.timestamp)
            .where(
                model.symbol == MarketlabActiveUniverse.symbol,
                model.period == "5m",
            )
            .order_by(model.timestamp.desc())
            .limit(1)
            .correlate(MarketlabActiveUniverse)
            .scalar_subquery()
        )
        rows = db.execute(
            select(MarketlabActiveUniverse.symbol, latest_timestamp).where(
                MarketlabActiveUniverse.symbol.in_(unique_symbols)
            )
        ).all()
        latest_by_source[label] = {symbol: timestamp for symbol, timestamp in rows}
    latest_funding_time = (
        select(FuturesFundingHistory.funding_time)
        .where(FuturesFundingHistory.symbol == MarketlabActiveUniverse.symbol)
        .order_by(FuturesFundingHistory.funding_time.desc())
        .limit(1)
        .correlate(MarketlabActiveUniverse)
        .scalar_subquery()
    )
    funding_rows = db.execute(
        select(MarketlabActiveUniverse.symbol, latest_funding_time).where(
            MarketlabActiveUniverse.symbol.in_(unique_symbols)
        )
    ).all()
    latest_by_source["funding history"] = {symbol: timestamp for symbol, timestamp in funding_rows}

    now = utcnow()
    results: dict[str, dict[str, str]] = {}
    for symbol in unique_symbols:
        checks = [
            (label, latest_by_source[label].get(symbol), max_age_minutes)
            for label, _model, max_age_minutes in sources
        ]
        checks.append(("funding history", latest_by_source["funding history"].get(symbol), 600))
        results[symbol] = _rich_status_from_checks(now, checks)
    return results


def _rich_status_from_checks(now, checks) -> dict[str, str]:
    missing = [label for label, value, _minutes in checks if value is None]
    if len(missing) == len(checks):
        return {"status": "RICH_MISSING", "reason": "all rich futures datasets missing"}
    if missing:
        return {"status": "RICH_WARMUP", "reason": "missing: " + ", ".join(missing)}

    stale = []
    for label, value, max_age_minutes in checks:
        if value.tzinfo is None:
            value = value.replace(tzinfo=now.tzinfo)
        if (now - value).total_seconds() > max_age_minutes * 60:
            stale.append(label)
    if stale:
        return {"status": "RICH_STALE", "reason": "stale: " + ", ".join(stale)}
    return {"status": "RICH_READY", "reason": "rich futures datasets fresh"}
