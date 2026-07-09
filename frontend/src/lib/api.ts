const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "http://127.0.0.1:8000";

export async function fetchJson<T>(path: string, options?: { revalidateSeconds?: number }): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, options?.revalidateSeconds ? { next: { revalidate: options.revalidateSeconds } } : { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`API ${path} failed: ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export function fmtTime(value?: string | null): string {
  if (!value) return "-";
  return new Intl.DateTimeFormat("en-GB", {
    dateStyle: "short",
    timeStyle: "medium",
    timeZone: "Asia/Jakarta"
  }).format(new Date(value));
}

export function fmtNumber(value?: string | number | null): string {
  if (value === null || value === undefined || value === "") return "-";
  const num = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(num)) return String(value);
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 }).format(num);
}

export function fmtPrice(value?: string | number | null): string {
  if (value === null || value === undefined || value === "") return "-";
  const num = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(num)) return String(value);

  let maximumFractionDigits = 2;
  if (Math.abs(num) < 0.01) maximumFractionDigits = 8;
  else if (Math.abs(num) < 1) maximumFractionDigits = 6;
  else if (Math.abs(num) < 100) maximumFractionDigits = 5;
  else if (Math.abs(num) < 1000) maximumFractionDigits = 4;

  return new Intl.NumberFormat("en-US", {
    maximumFractionDigits,
    minimumSignificantDigits: Math.abs(num) < 1 ? 3 : undefined,
    maximumSignificantDigits: Math.abs(num) < 0.01 ? 8 : undefined
  }).format(num);
}

export type UniverseItem = {
  symbol: string;
  rank: number;
  quote_volume: string;
  price_change_percent?: string | null;
  last_price?: string | null;
  high_price?: string | null;
  low_price?: string | null;
  volume?: string | null;
  trade_count_24h?: number | null;
  rank_volume?: string | null;
  collection_tier: "FULL_ACTIVE" | "LIGHT_WATCH" | "NOT_ACTIVE";
  is_full_active: boolean;
  is_light_watch: boolean;
  is_signal_eligible: boolean;
  is_active: boolean;
  entered_at: string;
  last_seen_at: string;
};

export type HealthItem = {
  symbol: string;
  rank?: number | null;
  rank_volume?: string | null;
  quote_volume?: string | null;
  collection_tier?: "FULL_ACTIVE" | "LIGHT_WATCH" | "NOT_ACTIVE";
  is_signal_eligible?: boolean;
  status:
    | "READY"
    | "WARMUP"
    | "STALE"
    | "MISSING_SPOT"
    | "MISSING_FUTURES"
    | "MISSING_OI"
    | "MISSING_FUNDING"
    | "NOT_ACTIVE";
  rich_status?: "RICH_READY" | "RICH_WARMUP" | "RICH_STALE" | "RICH_MISSING";
  rich_reason?: string | null;
  latest_futures_candle_time?: string | null;
  latest_spot_candle_time?: string | null;
  latest_open_interest_time?: string | null;
  latest_funding_time?: string | null;
  reason?: string | null;
};

export type CollectorRun = {
  id: number;
  collector_name: string;
  status: string;
  started_at: string;
  finished_at?: string | null;
  request_count: number;
  updated_count: number;
  error_count: number;
  duration?: number | null;
  rows_inserted?: number;
  rows_updated?: number;
  errors_count?: number;
};

export type AggregationStatus = {
  latest_15m_futures?: string | null;
  latest_15m_spot?: string | null;
  latest_1h_futures?: string | null;
  latest_1h_spot?: string | null;
  latest_4h_futures?: string | null;
  latest_4h_spot?: string | null;
  latest_24h_futures?: string | null;
  latest_24h_spot?: string | null;
  ready_count: number;
  incomplete_count: number;
  warmup_count: number;
  stale_count: number;
  missing_spot_count: number;
  tables?: Record<string, Record<string, number>>;
};

export type RichAlignmentStatus = {
  latest_15m?: string | null;
  latest_1h?: string | null;
  latest_4h?: string | null;
  latest_24h?: string | null;
  aligned_count: number;
  incomplete_count: number;
  warmup_count: number;
  stale_count: number;
  no_data_count: number;
  tables?: Record<string, Record<string, number>>;
};

export type MarketStateAlignmentStatus = {
  latest_15m?: string | null;
  latest_1h?: string | null;
  latest_4h?: string | null;
  latest_24h?: string | null;
  fresh_count: number;
  stale_count: number;
  missing_count: number;
  not_applicable_count: number;
  funding_aligned_count: number;
  funding_carried_forward_count: number;
  funding_stale_count: number;
  funding_missing_count: number;
  tables?: Record<string, Record<string, Record<string, number>>>;
  thresholds?: Record<string, number>;
};

export type Feature15mStatus = {
  latest_feature_time?: string | null;
  total_features: number;
  feature_ready_count: number;
  feature_partial_count: number;
  feature_blocked_count: number;
  latest_ready_symbols_count: number;
};

export type Feature1hStatus = Feature15mStatus;

export type SpotSupportCounts = {
  SPOT_SUPPORTING?: number;
  WEAK_SPOT_SUPPORT?: number;
  FUTURES_LED?: number;
  SPOT_MISSING?: number;
  SPOT_UNKNOWN?: number;
};

export type FeatureContext15m1hStatus = {
  latest_context_time?: string | null;
  total_context_rows: number;
  context_ready_count: number;
  context_partial_count: number;
  context_blocked_count: number;
  latest_symbols_count: number;
  spot_support_counts?: SpotSupportCounts;
  thresholds?: Record<string, number | string>;
};

export type Psychology15mStatus = {
  latest_label_time?: string | null;
  total_labels: number;
  label_ready_count: number;
  label_partial_count: number;
  label_blocked_count: number;
  top_primary_labels: { label: string; count: number }[];
};

export type SignalCandidatesReadonly15mStatus = {
  latest_candidate_time?: string | null;
  total_rows: number;
  classifier_ready_count: number;
  classifier_partial_count: number;
  classifier_blocked_count: number;
  candidate_type_counts: { type: string; count: number }[];
  direction_counts: { direction: string; count: number }[];
};

export type OutcomeStatusCounts = {
  OUTCOME_READY?: number;
  OUTCOME_WAITING_DATA?: number;
  OUTCOME_INCOMPLETE?: number;
  OUTCOME_BLOCKED?: number;
};

export type Outcomes15mStatus = {
  total_rows: number;
  latest_candidate_time?: string | null;
  latest_outcome_update?: string | null;
  outcome_status_counts: OutcomeStatusCounts;
  horizon_15m_status_counts: OutcomeStatusCounts;
  horizon_30m_status_counts: OutcomeStatusCounts;
  horizon_1h_status_counts: OutcomeStatusCounts;
  horizon_4h_status_counts: OutcomeStatusCounts;
  candidate_type_counts: { type: string; count: number }[];
  direction_counts: { direction: string; count: number }[];
};

export type LiveScannerItem = {
  symbol: string;
  timeframe?: string | null;
  is_active: boolean;
  collection_tier: string;
  universe_rank?: number | null;
  inactive_warning?: string | null;
  scanner_visibility_reason: string;
  latest_actual_status?: string | null;
  latest_actual_observation_timestamp?: string | null;
  using_fallback_usable_row: boolean;
  fallback_reason?: string | null;
  observation_time?: string | null;
  window_open_time?: string | null;
  window_close_time?: string | null;
  candidate_type: string;
  candidate_direction: string;
  classifier_status: string;
  confidence: string;
  confidence_score?: string | null;
  scanner_tier: string;
  tier_reason: string;
  warning_reason?: string | null;
  evidence_summary: Record<string, string | string[] | number | boolean | null>;
  signal_status?: string | null;
  signal_reason?: string | null;
  entry_market?: string | null;
  entry_price_source?: string | null;
  entry_price?: string | number | null;
  stop_loss_reference?: string | number | null;
  take_profit_reference?: string | number | null;
  rr?: string | number | null;
  timeout_minutes?: number | null;
  atr_reference_timeframe?: string | null;
  atr_reference_value?: string | number | null;
  quality_score?: number | null;
  quality_bucket?: string | null;
  quality_reasons?: string[];
  position_lock_mode?: string | null;
  not_execution_instruction?: boolean;
  latest_outcome_status?: string | null;
  latest_outcome_update?: string | null;
  not_entry_signal: boolean;
};

export type LiveScannerResponse = {
  count: number;
  filters: {
    tier?: string | null;
    candidate_type?: string | null;
    limit: number;
    include_blocked: boolean;
    include_inactive: boolean;
  };
  tier_counts: Record<string, number>;
  read_only: boolean;
  not_entry_signal: boolean;
  items: LiveScannerItem[];
};

export type StrategyArenaLeaderboardItem = {
  rank: number;
  setup_label: string;
  setup_family: string;
  direction_label: string;
  horizon_label: string;
  risk_label: string;
  rr_label: string;
  sample_size: number;
  pessimistic_avg_r?: number | null;
  resolved_avg_r?: number | null;
  tp_first_share: number;
  sl_first_share: number;
  both_same_candle_share: number;
  neither_share: number;
  top_symbol_share: number;
  verdict: string;
  verdict_label: string;
};

export type StrategyArenaResult = Omit<StrategyArenaLeaderboardItem, "rank"> & {
  source_candidate_type: string;
  direction: string;
  horizon: string;
  atr_mult: number;
  rr: number;
  tp_first_count: number;
  sl_first_count: number;
  both_same_candle_count: number;
  neither_count: number;
  insufficient_forward_data_count: number;
  median_r?: number | null;
  worst_r?: number | null;
  best_r?: number | null;
  top_symbol?: string | null;
  top_symbol_count: number;
  distinct_symbols: number;
  warning_label: string;
};

export type StrategyArenaLeaderboardResponse = {
  metadata: {
    generated_at?: string;
    ranking_metric: string;
    read_only: boolean;
    not_live_signal: boolean;
  };
  summary: {
    total_setups_tested: number;
    total_combinations: number;
    promising_count: number;
    noisy_count: number;
    rejected_count: number;
    best_short_setup?: StrategyArenaLeaderboardItem | null;
    best_long_setup?: StrategyArenaLeaderboardItem | null;
    best_horizon?: string | null;
  };
  top_by_pessimistic_avg_r: StrategyArenaLeaderboardItem[];
  top_by_resolved_avg_r: StrategyArenaLeaderboardItem[];
  best_short_setup: StrategyArenaLeaderboardItem[];
  best_long_setup: StrategyArenaLeaderboardItem[];
  best_by_horizon: Record<string, StrategyArenaLeaderboardItem[]>;
  worst_setups: StrategyArenaLeaderboardItem[];
  noisy_setups: StrategyArenaLeaderboardItem[];
  rejected_setups: StrategyArenaLeaderboardItem[];
  baseline_comparison: {
    setup_family: string;
    horizon: string;
    atr_mult: number;
    rr: number;
    baseline_status: string;
    pessimistic_avg_r_delta?: number | null;
  }[];
};

export type StrategyArenaResultsResponse = {
  metadata: {
    generated_at?: string;
    candidate_rows_loaded: number;
    setup_candidate_counts: Record<string, number>;
    skipped_counts: Record<string, number>;
  };
  results: StrategyArenaResult[];
};

export type EarlyBacktestHorizonSummary = {
  events: number;
  ready: number;
  waiting: number;
  tp: number;
  sl: number;
  both: number;
  neither: number;
  outcomes: Record<string, number>;
  total_r?: number | null;
  fixed_risk_return_pct_1pct?: number | null;
  avg_r?: number | null;
  median_r?: number | null;
  total_return_pct?: number | null;
  avg_return_pct?: number | null;
  median_return_pct?: number | null;
  planned_rr?: number | null;
  best_r?: number | null;
  worst_r?: number | null;
};

export type EarlyBacktestEvent = {
  signal_id: string;
  symbol: string;
  timeframe: string;
  signal_time_utc?: string | null;
  signal_time_wib?: string | null;
  stage: "EARLY_LONG" | "EARLY_SHORT" | string;
  direction: "LONG" | "SHORT" | string;
  confidence_tier?: string | null;
  core_score?: string | number | null;
  evidence_score?: string | number | null;
  evidence_data_completeness?: number | null;
  execution_flag?: string | null;
  entry_market?: string | null;
  entry_price_source?: string | null;
  entry?: string | number | null;
  stop?: string | number | null;
  target?: string | number | null;
  risk?: string | number | null;
  rr?: string | number | null;
  target_return_pct?: string | number | null;
  stop_return_pct?: string | number | null;
  horizon: string;
  outcome: string;
  status?: string | null;
  realized_r?: string | number | null;
  realized_return_pct?: string | number | null;
  mfe_r?: string | number | null;
  mae_r?: string | number | null;
  max_favorable_return_pct?: string | number | null;
  max_adverse_return_pct?: string | number | null;
  result_time_utc?: string | null;
  result_time_wib?: string | null;
  evidence?: Record<string, string | number | boolean | null | undefined>;
  not_live_signal: boolean;
  not_execution_instruction: boolean;
};

export type EarlyBacktestSummaryResponse = {
  metadata: {
    generated_at_utc?: string | null;
    epoch?: string | null;
    signals_loaded?: number;
    events_evaluated?: number;
    source_candidate_count?: number;
    position_lock_mode?: string | null;
    artifact_type?: string | null;
    feature_rows?: number | null;
    candles_15m?: number | null;
    candles_1h?: number | null;
    include_watch_only?: boolean;
    entry_market?: string;
    spot_usage?: string;
  };
  source: Record<string, string>;
  guardrails: {
    read_only: boolean;
    not_live_signal: boolean;
    not_execution_instruction: boolean;
    entry_market: string;
    spot_usage: string;
  };
  summary: {
    total_events: number;
    by_stage: Record<string, number>;
    by_confidence: Record<string, number>;
    by_horizon: Record<string, EarlyBacktestHorizonSummary>;
    best_horizon?: string | null;
  };
  latest_events: EarlyBacktestEvent[];
};

export type EarlyBacktestEventsResponse = {
  count: number;
  filters: {
    stage?: string | null;
    horizon: string;
    outcome?: string | null;
    limit: number;
  };
  read_only: boolean;
  not_live_signal: boolean;
  not_execution_instruction: boolean;
  items: EarlyBacktestEvent[];
};

export type SignalFactoryCandidate = {
  symbol: string;
  timeframe: string;
  window_start?: string | null;
  window_end?: string | null;
  setup_type: string;
  setup_family: string;
  setup_name: string;
  direction: string;
  confidence: string;
  reason: string;
  evidence: {
    anomalies?: string[];
    price_return?: number | null;
    volume_spike?: boolean | null;
    oi_change_pct?: number | null;
    funding_pressure?: string | null;
    relative_strength?: string | null;
    futures_led_flag?: boolean | null;
    spot_led_flag?: boolean | null;
    feature_status?: string | null;
    status_reasons?: string[];
  };
  feature_status: string;
  candidate_status: string;
  conflict_status?: string | null;
  atr_reference_timeframe: string;
  atr_reference_status: string;
  not_live_signal: boolean;
  not_execution_instruction: boolean;
};

export type SignalFactoryCandidatesResponse = {
  generated_at?: string;
  count: number;
  total_matching: number;
  read_only: boolean;
  not_live_signal: boolean;
  not_execution_instruction: boolean;
  items: SignalFactoryCandidate[];
};

export type SignalFactorySummaryResponse = {
  generated_at?: string;
  feature_count: number;
  candidate_count: number;
  feature_count_by_timeframe: Record<string, number>;
  feature_status_counts: Record<string, number>;
  candidate_count_by_timeframe: Record<string, number>;
  candidate_count_by_setup: Record<string, number>;
  candidate_status_counts: Record<string, number>;
  conflict_count: number;
  missing_data_count: number;
  guardrails: {
    read_only: boolean;
    not_live_signal: boolean;
    not_execution_instruction: boolean;
  };
};

export type SignalPerformanceItem = {
  signal_id: string;
  symbol: string;
  timeframe: string;
  signal_timestamp?: string | null;
  signal_time_wib?: string | null;
  stage: string;
  direction: string;
  candidate_status: string;
  confidence_tier?: string | null;
  execution_flag?: string | null;
  core_score?: string | number | null;
  evidence_score?: string | number | null;
  evidence_data_completeness?: number | null;
  entry?: string | number | null;
  stop_loss?: string | number | null;
  take_profit?: string | number | null;
  risk?: string | number | null;
  rr?: string | number | null;
  result_status: string;
  result_time_utc?: string | null;
  result_time_wib?: string | null;
  exit_price?: string | number | null;
  realized_r?: string | number | null;
  unrealized_r?: string | number | null;
  mfe_r?: string | number | null;
  mae_r?: string | number | null;
  candles_seen: number;
  not_live_signal: boolean;
  not_execution_instruction: boolean;
};

export type SignalPerformanceBucket = {
  signals_evaluated: number;
  open_count: number;
  waiting_count: number;
  tp_count: number;
  sl_count: number;
  both_hit_count: number;
  closed_count: number;
  winrate_pct?: string | number | null;
  total_r_closed: string | number;
  open_unrealized_r: string | number;
  total_r_with_open: string | number;
  fixed_risk_return_pct_1pct_closed: string | number;
  fixed_risk_return_pct_1pct_with_open: string | number;
  avg_r_closed?: string | number | null;
};

export type SignalPerformanceResponse = {
  generated_at_utc: string;
  epoch: string;
  filters: {
    include_watch_only: boolean;
    position_lock: boolean;
    stage?: string | null;
    timeframe?: string | null;
    symbol?: string | null;
    result_status?: string | null;
    limit: number;
  };
  read_only: boolean;
  not_live_signal: boolean;
  not_execution_instruction: boolean;
  entry_market: string;
  entry_price_source: string;
  evaluation_candle_interval?: string | null;
  latest_evaluation_candle_time?: string | null;
  latest_futures_15m_close_time?: string | null;
  aggregate: SignalPerformanceBucket & {
    signals_skipped: number;
    skip_reasons: Record<string, number>;
    status_counts: Record<string, number>;
    by_stage: Record<string, number>;
    by_timeframe: Record<string, number>;
    by_timeframe_performance: Record<string, SignalPerformanceBucket>;
    by_confidence: Record<string, number>;
  };
  items: SignalPerformanceItem[];
};

export type SignalDetailResponse = {
  generated_at_utc: string;
  epoch: string;
  read_only: boolean;
  not_live_signal: boolean;
  not_execution_instruction: boolean;
  entry_market: string;
  entry_price_source: string;
  evaluation_candle_interval?: string | null;
  latest_evaluation_candle_time?: string | null;
  item: SignalPerformanceItem & {
    evidence_snapshot?: Record<string, string | number | null>;
  };
  raw_signal: {
    signal_id: string;
    symbol: string;
    timeframe: string;
    signal_timestamp?: string | null;
    window_open_time?: string | null;
    window_close_time?: string | null;
    direction: string;
    stage: string;
    candidate_status: string;
    confidence_tier?: string | null;
    execution_flag?: string | null;
    source_artifact_generated_at?: string | null;
    observation_epoch?: string | null;
    created_at?: string | null;
    updated_at?: string | null;
  };
  evidence: Record<string, unknown>;
};

export type SignalQualityBucket = SignalPerformanceBucket & {
  bucket: string;
  quality_flag: string;
  symbol_count: number;
  top_symbol: string;
  top_symbol_share_pct?: string | number | null;
  median_r_closed?: string | number | null;
  median_mfe_r?: string | number | null;
  median_mae_r?: string | number | null;
  best_r?: string | number | null;
  worst_r?: string | number | null;
};

export type SignalQualityEvidenceField = {
  field: string;
  label: string;
  quality_flag: string;
  available_count: number;
  missing_count: number;
  available_pct?: string | number | null;
  tp_count: number;
  sl_count: number;
  open_count: number;
  waiting_count: number;
  both_count: number;
  tp_median?: string | number | null;
  sl_median?: string | number | null;
  open_median?: string | number | null;
  waiting_median?: string | number | null;
  tp_avg?: string | number | null;
  sl_avg?: string | number | null;
  tp_q1?: string | number | null;
  tp_q3?: string | number | null;
  sl_q1?: string | number | null;
  sl_q3?: string | number | null;
  delta_tp_minus_sl?: string | number | null;
};

export type SignalFilterStudyRow = SignalPerformanceBucket & {
  filter_id: string;
  label: string;
  expression: string;
  family: string;
  required_fields: string[];
  source_count: number;
  sample_count: number;
  sample_retention_pct?: string | number | null;
  missing_data_count: number;
  missing_data_pct?: string | number | null;
  median_r_closed?: string | number | null;
  max_drawdown_r?: string | number | null;
  top_symbol: string;
  top_symbol_count: number;
  top_symbol_share_pct?: string | number | null;
  avg_r_delta_vs_baseline?: string | number | null;
  winrate_delta_vs_baseline?: string | number | null;
  sl_share_pct?: string | number | null;
  sl_share_delta_vs_baseline?: string | number | null;
  verdict: string;
  note: string;
};

export type SignalFilterStudyResponse = {
  generated_at_utc: string;
  epoch: string;
  filters: {
    include_watch_only: boolean;
    position_lock: boolean;
    stage: string;
    timeframe: string;
    min_sample: number;
    limit: number;
  };
  read_only: boolean;
  not_live_signal: boolean;
  not_execution_instruction: boolean;
  study_scope: string;
  latest_futures_15m_close_time?: string | null;
  skipped_by_position_lock: Record<string, number>;
  baseline: SignalFilterStudyRow;
  rows: SignalFilterStudyRow[];
};

export type SignalCalibrationPerf = SignalPerformanceBucket & {
  sample_count: number;
  median_r_closed?: string | number | null;
  max_drawdown_r?: string | number | null;
  sl_share_pct?: string | number | null;
  top_symbol: string;
  top_symbol_count: number;
  top_symbol_share_pct?: string | number | null;
  sample_delta_vs_baseline?: string | number | null;
  avg_r_delta_vs_baseline?: string | number | null;
  total_r_delta_vs_baseline?: string | number | null;
  winrate_delta_vs_baseline?: string | number | null;
  sl_share_delta_vs_baseline?: string | number | null;
  max_drawdown_delta_vs_baseline?: string | number | null;
};

export type SignalCalibrationCandidate = {
  stage?: string;
  timeframe?: string;
  filter_id: string;
  label: string;
  expression: string;
  family: string;
  required_fields: string[];
  missing_data: {
    all: number;
    train: number;
    validation: number;
  };
  all: SignalCalibrationPerf;
  train: SignalCalibrationPerf;
  validation: SignalCalibrationPerf;
  verdict: string;
  promotion_status: string;
  promotion_score: number;
  promotion_reasons: string[];
  note: string;
};

export type SignalCalibrationLane = {
  lane: string;
  stage: string;
  timeframe: string;
  sample_count: number;
  train_count: number;
  validation_count: number;
  split_method: string;
  status: string;
  baseline_all: SignalCalibrationPerf;
  baseline_train: SignalCalibrationPerf;
  baseline_validation: SignalCalibrationPerf;
  filter_candidates: SignalCalibrationCandidate[];
};

export type SignalCalibrationLabResponse = {
  generated_at_utc: string;
  epoch: string;
  filters: {
    include_watch_only: boolean;
    position_lock: boolean;
    min_sample: number;
    limit: number;
  };
  read_only: boolean;
  not_live_signal: boolean;
  not_execution_instruction: boolean;
  study_scope: string;
  method: string;
  latest_evaluation_candle_time?: string | null;
  latest_futures_15m_close_time?: string | null;
  skipped_by_position_lock: Record<string, number>;
  aggregate: SignalPerformanceResponse["aggregate"];
  lanes: SignalCalibrationLane[];
  top_candidates: SignalCalibrationCandidate[];
  guardrails: string[];
};

export type MarketRegimeStudyBucket = SignalPerformanceBucket & {
  dimension: string;
  bucket: string;
  sample_count: number;
  avg_r_delta_vs_baseline?: string | number | null;
  winrate_delta_vs_baseline?: string | number | null;
  sl_share_delta_vs_baseline?: string | number | null;
  verdict: string;
  note: string;
};

export type MarketRegimeStudyLane = {
  lane: string;
  stage: string;
  timeframe: string;
  direction: string;
  raw_count: number;
  sample_count: number;
  lock_skipped: number;
  baseline: SignalPerformanceBucket;
  top_helpful_regimes: MarketRegimeStudyBucket[];
  top_harmful_regimes: MarketRegimeStudyBucket[];
  interpretation: string;
};

export type MarketRegimeStudyResponse = {
  generated_at: string;
  epoch: string;
  include_watch_only: boolean;
  position_lock: boolean;
  read_only: boolean;
  not_live_signal: boolean;
  not_execution_instruction: boolean;
  method: string;
  lanes: Record<string, MarketRegimeStudyLane>;
};

export type SignalQualityDrawdownPoint = {
  signal_id: string;
  symbol: string;
  stage: string;
  timeframe: string;
  result_status: string;
  result_time_utc?: string | null;
  result_time_wib?: string | null;
  realized_r: string | number;
  cumulative_r: string | number;
  drawdown_r: string | number;
};

export type SignalQualityLabResponse = {
  generated_at_utc: string;
  epoch: string;
  filters: {
    include_watch_only: boolean;
    position_lock: boolean;
    stage?: string | null;
    timeframe?: string | null;
    min_sample: number;
    limit: number;
  };
  read_only: boolean;
  not_live_signal: boolean;
  not_execution_instruction: boolean;
  evaluation_candle_interval?: string | null;
  latest_evaluation_candle_time?: string | null;
  latest_futures_15m_close_time?: string | null;
  aggregate: SignalPerformanceResponse["aggregate"];
  drawdown: {
    closed_count: number;
    total_r_closed: string | number;
    peak_r: string | number;
    max_drawdown_r: string | number;
    current_drawdown_r: string | number;
    points: SignalQualityDrawdownPoint[];
  };
  by_stage: SignalQualityBucket[];
  by_confidence: SignalQualityBucket[];
  by_timeframe: SignalQualityBucket[];
  evidence_fields: SignalQualityEvidenceField[];
  top_symbols: SignalQualityBucket[];
  weak_symbols: SignalQualityBucket[];
  best_signals: SignalPerformanceItem[];
  worst_signals: SignalPerformanceItem[];
  open_signals: SignalPerformanceItem[];
};

export type Phase6FeatureReadinessRow = {
  timeframe: string;
  total_feature_rows: number;
  ready_count: number;
  partial_data_count: number;
  missing_candles_count: number;
  missing_atr_count: number;
  missing_oi_count: number;
  readiness_status: string;
};

export type Phase7CandidateDecisionRow = {
  symbol: string;
  timeframe: string;
  setup_type: string;
  mapped_setup_family?: string | null;
  direction: string;
  confidence: string;
  reason?: string | null;
  recommended_arena_horizon?: string | null;
  recommended_atr_mult?: number | null;
  recommended_rr?: number | null;
  arena_verdict?: string | null;
  setup_pessR?: number | null;
  baseline_pessR?: number | null;
  edge_vs_baseline?: number | null;
  total_score?: number | null;
  phase7_verdict: string;
};

export type Phase6ReadinessResponse = {
  generated_at?: string;
  phase6_status: string;
  artifact_status: string;
  phase7_decision: string;
  approved_count: number;
  watchlist_count: number;
  rejected_count: number;
  best_setup?: Phase7CandidateDecisionRow | null;
  most_blocked_timeframe?: string | null;
  feature_readiness: {
    by_timeframe: Record<string, Phase6FeatureReadinessRow>;
    most_ready_timeframe?: string | null;
    most_blocked_timeframe?: string | null;
  };
  candidate_readiness: {
    total_candidates: number;
    eligible_candidate_count: number;
    blocked_candidate_count: number;
    radar_only_count: number;
    conflicted_count: number;
    status_counts: Record<string, number>;
    setup_counts: Record<string, number>;
  };
};

export type Phase6DecisionResponse = {
  phase6_status: string;
  phase7_decision: string;
  approved_candidates: Phase7CandidateDecisionRow[];
  watchlist_candidates: Phase7CandidateDecisionRow[];
  rejected_candidates: Phase7CandidateDecisionRow[];
  blocked_reasons: Record<string, number>;
  best_setup?: Phase7CandidateDecisionRow | null;
  generated_at?: string;
};

export type Phase7FullBlockerAuditResponse = {
  generated_at?: string;
  final_verdicts: string[];
  next_action: string;
  data_coverage: Record<
    string,
    {
      futures: {
        ready_rows: number;
        non_ready_rows: number;
        total_rows: number;
        status_counts: Record<string, number>;
        symbols_with_ready_rows: number;
      };
      spot: {
        ready_rows: number;
        non_ready_rows: number;
        total_rows: number;
        status_counts: Record<string, number>;
      };
    }
  >;
  atr_readiness: Record<
    string,
    {
      available_symbols: number;
      failed_symbols: number;
      fail_reasons: Record<string, number>;
    }
  >;
  signal_factory: {
    total_candidates: number;
    signal_candidate_count: number;
    radar_only_count: number;
    blocked_count: number;
    status_counts: Record<string, number>;
  };
  radar_only: {
    counts: Record<string, number>;
  };
  edge: {
    eligible_edge_rows: number;
    edge_buckets: Record<string, number>;
    diagnosis: string;
    best_edges: {
      symbol: string;
      timeframe: string;
      setup: string;
      edge_vs_baseline?: number | null;
      arena_verdict?: string | null;
      score?: number | null;
    }[];
  };
  phase6_scoring: {
    highest_score: number;
    score_ge_7_count: number;
    score_6_count: number;
    score_5_count: number;
    score_4_count: number;
    diagnosis: string;
  };
  runtime_health: {
    checked: boolean;
    problems?: string[];
  };
  fix: {
    technical_fix_applied: boolean;
    fix_summary: string;
  };
  rerun_result: {
    phase7_decision?: string;
    approved_count: number;
    watchlist_count: number;
    unlock_verdict?: string;
  };
};

export type CandidateNumericEvidenceMetric = {
  category: string;
  metric: string;
  label: string;
  required_operator: string;
  required_value: string | number | boolean | string[] | null;
  actual_value: string | number | boolean | null;
  unit: string;
  actual_detail: string;
  result: "PASS" | "FAIL" | "UNAVAILABLE" | "INFO";
  explanation: string;
  source: string;
};

export type CandidatePhase7ChecklistItem = {
  gate: string;
  required: string;
  actual: string | number | boolean | null;
  result: "PASS" | "FAIL";
};

export type CandidateNumericEvidenceItem = {
  symbol: string;
  timeframe: string;
  window_start?: string | null;
  window_end?: string | null;
  setup: string;
  mapped_setup_family?: string | null;
  candidate_status: string;
  direction: string;
  confidence: string;
  final_decision: string;
  is_phase7_ready: boolean;
  not_live_signal: boolean;
  not_execution_instruction: boolean;
  numeric_evidence: CandidateNumericEvidenceMetric[];
  phase7_checklist: CandidatePhase7ChecklistItem[];
  blocking_reasons: string[];
  what_needs_to_improve: string[];
  missing_evidence_fields: string[];
  label_explanation: {
    explanation: string[];
    numeric_context: Record<string, string | number | boolean | null>;
  };
};

export type CandidateNumericEvidenceResponse = {
  generated_at?: string;
  count: number;
  total_matching: number;
  aggregate: {
    total_candidates?: number;
    signal_candidate_count?: number;
    numeric_evidence_complete_count?: number;
    numeric_evidence_incomplete_count?: number;
    top_failure_reasons?: Record<string, number>;
    missing_evidence_fields?: Record<string, number>;
    phase7_checklist_available?: boolean;
    production_approved?: number;
    phase7_decision?: string;
  };
  read_only: boolean;
  not_live_signal: boolean;
  not_execution_instruction: boolean;
  items: CandidateNumericEvidenceItem[];
};

export type Phase7ForwardStatus = {
  generated_at?: string | null;
  generated_at_utc?: string | null;
  last_run_at_utc?: string | null;
  display_timezone_hint?: string | null;
  stale_after_minutes?: number;
  is_stale?: boolean;
  stale_reason?: string | null;
  age_seconds?: number;
  phase: string;
  mode: string;
  verdict: string;
  approved_candidate_count: number;
  approved_shadow_event_count?: number;
  lab_shadow_candidate_count?: number;
  lab_shadow_event_count?: number;
  active_event_count: number;
  completed_event_count: number;
  waiting_event_count: number;
  created_event_count?: number;
  error_count: number;
  reason: string;
  is_live_signal: boolean;
  is_execution_enabled: boolean;
  next_action: string;
};

export type Phase7ForwardEvent = {
  event_id: string;
  symbol: string;
  timeframe: string;
  setup: string;
  direction: "LONG" | "SHORT" | "MIXED";
  lane?: "APPROVED_SHADOW" | "LAB_SHADOW";
  shadow_type?: "STRICT_APPROVED" | "LAB_NEAR_MISS";
  confidence?: string | null;
  candidate_timestamp?: string | null;
  observation_timestamp?: string | null;
  observation_timestamp_utc?: string | null;
  status: string;
  entry_reference_price?: number | null;
  entry_reference_time?: string | null;
  entry_reference_time_utc?: string | null;
  atr_reference_timeframe?: string | null;
  atr_reference_value?: number | null;
  atr_mult?: number | null;
  rr_target?: number | null;
  risk_reference_value?: number | null;
  stop_reference_price?: number | null;
  take_profit_reference_price?: number | null;
  max_horizon_bars?: number | null;
  max_horizon_minutes?: number | null;
  expiry_time?: string | null;
  expiry_time_utc?: string | null;
  event_created_at_utc?: string | null;
  phase6_score?: number | null;
  edge_vs_baseline?: number | null;
  arena_verdict?: string | null;
  cannot_create_reason?: string | null;
  is_live_signal: boolean;
  is_execution: boolean;
  disclaimer: string;
};

export type Phase7ForwardEventsResponse = {
  generated_at?: string | null;
  generated_at_utc?: string | null;
  display_timezone_hint?: string | null;
  events: Phase7ForwardEvent[];
};

export type Phase7ForwardResult = {
  event_id: string;
  symbol: string;
  setup?: string | null;
  direction?: string | null;
  lane?: string | null;
  shadow_type?: string | null;
  result_status: string;
  hit_time?: string | null;
  hit_time_utc?: string | null;
  expiry_time?: string | null;
  expiry_time_utc?: string | null;
  evaluated_at_utc?: string | null;
  bars_to_result?: number | null;
  minutes_to_result?: number | null;
  realized_R?: number | null;
  max_favorable_excursion_R?: number | null;
  max_adverse_excursion_R?: number | null;
  close_return_R_at_expiry?: number | null;
  ambiguous_same_candle: boolean;
  reason?: string | null;
  is_live_signal: boolean;
  is_execution: boolean;
};

export type Phase7ForwardResultsResponse = {
  generated_at?: string | null;
  generated_at_utc?: string | null;
  display_timezone_hint?: string | null;
  results: Phase7ForwardResult[];
};

export type Phase7LaneSummary = {
  total_events: number;
  active_events: number;
  completed_events: number;
  tp_hit: number;
  sl_hit: number;
  expired: number;
  unknown_forward_data?: number;
  ambiguous: number;
  win_rate?: number | null;
  average_realized_R?: number | null;
  median_realized_R?: number | null;
  avg_R?: number | null;
  median_R?: number | null;
};

export type Phase7ForwardSummary = {
  generated_at?: string | null;
  generated_at_utc?: string | null;
  last_run_at_utc?: string | null;
  display_timezone_hint?: string | null;
  total_events: number;
  active_events: number;
  completed_events: number;
  tp_hit?: number;
  sl_hit?: number;
  expired?: number;
  unknown_forward_data?: number;
  ambiguous?: number;
  win_rate?: number | null;
  average_realized_R?: number | null;
  median_realized_R?: number | null;
  approved_shadow_summary?: Phase7LaneSummary;
  lab_shadow_summary?: Phase7LaneSummary;
  verdict: string;
  is_live_signal?: boolean;
  is_execution_enabled?: boolean;
};
