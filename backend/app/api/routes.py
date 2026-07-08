import json
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
from app.services.snapshot_funding_alignment import SnapshotFundingAlignmentService
from app.services.strategy_arena import StrategyArenaArtifactService
from app.services.utils import duration_seconds, json_safe, model_to_dict, utcnow

router = APIRouter()

_SIGNAL_PERFORMANCE_CACHE_TTL_SECONDS = 30.0
_SIGNAL_PERFORMANCE_CACHE_LOCK = Lock()
_SIGNAL_PERFORMANCE_CACHE: dict[tuple, tuple[float, dict]] = {}
_SIGNAL_QUALITY_CACHE_LOCK = Lock()
_SIGNAL_QUALITY_CACHE: dict[tuple, tuple[float, dict]] = {}
_SIGNAL_FILTER_STUDY_CACHE_LOCK = Lock()
_SIGNAL_FILTER_STUDY_CACHE: dict[tuple, tuple[float, dict]] = {}


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
    items = _latest_health_items(db)
    rich_counts = {"RICH_READY": 0, "RICH_WARMUP": 0, "RICH_STALE": 0, "RICH_MISSING": 0}
    for item in items:
        rich_status = _rich_symbol_status(db, item["symbol"])
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
    latest = {
        "latest_futures_candle_time": _max_time(db, FuturesKline1m.close_time),
        "latest_spot_candle_time": _max_time(db, SpotKline1m.close_time),
        "latest_open_interest_time": _max_time(db, FuturesOpenInterest.event_time),
        "latest_funding_time": _max_time(db, FuturesMarkFunding.event_time),
    }
    return json_safe(
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
            "latest": latest,
            "items": items,
        }
    )


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
    payload = SignalCandidatePerformanceService(db).detail(
        signal_id=signal_id,
        symbol=symbol,
        timeframe=timeframe,
        include_watch_only=True,
    )
    if payload is None:
        raise HTTPException(status_code=404, detail="Signal not found")
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
    db: Session = Depends(get_db),
):
    items = LiveCandidateScannerService(db, signal_factory_artifact_dir=DEFAULT_SIGNAL_FACTORY_DIR).list_live(
        tier=tier,
        candidate_type=candidate_type,
        limit=limit,
        include_blocked=include_blocked,
        include_inactive=include_inactive,
    )
    tier_counts: dict[str, int] = {}
    for item in items:
        tier_counts[item["scanner_tier"]] = tier_counts.get(item["scanner_tier"], 0) + 1
    return json_safe(
        {
            "count": len(items),
            "filters": {
                "tier": tier,
                "candidate_type": candidate_type,
                "limit": limit,
                "include_blocked": include_blocked,
                "include_inactive": include_inactive,
            },
            "tier_counts": tier_counts,
            "read_only": True,
            "not_entry_signal": True,
            "items": items,
        }
    )


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
    active_rows = db.scalars(
        select(MarketlabActiveUniverse)
        .where(MarketlabActiveUniverse.is_active.is_(True))
        .order_by(MarketlabActiveUniverse.rank.asc())
    ).all()
    items = []
    for universe_row in active_rows:
        row = db.scalar(
            select(DataHealthSnapshot)
            .where(DataHealthSnapshot.symbol == universe_row.symbol)
            .order_by(desc(DataHealthSnapshot.snapshot_time))
            .limit(1)
        )
        if row:
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


def _rich_symbol_status(db: Session, symbol: str) -> dict[str, str]:
    now = utcnow()
    checks = [
        ("taker buy/sell", _latest_rich_timestamp(db, FuturesTakerBuySellVolume, symbol), 15),
        ("global long/short", _latest_rich_timestamp(db, FuturesGlobalLongShortAccountRatio, symbol), 15),
        ("top trader position", _latest_rich_timestamp(db, FuturesTopTraderPositionRatio, symbol), 15),
        ("top trader account", _latest_rich_timestamp(db, FuturesTopTraderAccountRatio, symbol), 15),
        ("open interest history", _latest_rich_timestamp(db, FuturesOpenInterestHistory, symbol), 15),
        ("funding history", _latest_funding_timestamp(db, symbol), 600),
    ]
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


def _latest_rich_timestamp(db: Session, model, symbol: str):
    return db.scalar(select(func.max(model.timestamp)).where(model.symbol == symbol, model.period == "5m"))


def _latest_funding_timestamp(db: Session, symbol: str):
    return db.scalar(select(func.max(FuturesFundingHistory.funding_time)).where(FuturesFundingHistory.symbol == symbol))
