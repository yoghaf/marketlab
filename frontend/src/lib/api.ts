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
  strategy_version?: string | null;
  strategy_family?: string | null;
  shadow_strategy_version?: string | null;
  v3_shadow_filter_count?: number | null;
  v3_shadow_status?: string | null;
  v3_shadow_filter_id?: string | null;
  v3_shadow_filter_label?: string | null;
  v3_shadow_filter_expression?: string | null;
  v3_shadow_promotion_score?: number | null;
  v3_shadow_reason?: string | null;
  quality_shadow_status?: string | null;
  quality_shadow_filter_id?: string | null;
  quality_shadow_filter_label?: string | null;
  quality_shadow_filter_expression?: string | null;
  quality_shadow_reason?: string | null;
  quality_shadow_pass?: boolean | null;
  quality_shadow_range_ratio_vs_atr?: string | number | null;
  quality_shadow_fill_quality?: string | null;
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

export type StrategyOptimizationRow = {
  stage: string;
  timeframe: string;
  atr_mult: string | number;
  rr: string | number;
  timeout_minutes: number;
  sample_count: number;
  closed_count: number;
  tp_count: number;
  sl_count: number;
  both_hit_count: number;
  timeout_count: number;
  waiting_count: number;
  positive_timeout_count: number;
  negative_timeout_count: number;
  total_r?: string | number | null;
  avg_r?: string | number | null;
  median_r?: string | number | null;
  winrate_pct?: string | number | null;
  max_drawdown_r?: string | number | null;
  current_drawdown_r?: string | number | null;
  skipped_counts: Record<string, number>;
  verdict: string;
};

export type StrategyOptimizationResponse = {
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
  study_scope: string;
  entry_market: string;
  entry_model: string;
  atr_model: string;
  outcome_model: string;
  grid: {
    atr_multipliers: string[];
    rr_values: string[];
    timeout_minutes: number[];
  };
  summary: {
    signals_loaded: number;
    lane_count: number;
    grid_rows: number;
    ready_rows: number;
    promising_rows: number;
    best_row?: StrategyOptimizationRow | null;
  };
  lanes: StrategyOptimizationRow[];
  rows: StrategyOptimizationRow[];
  guardrails: string[];
  artifact?: {
    source: string;
    generated_at_utc?: string | null;
    artifact_type?: string | null;
    read_from_artifact: boolean;
  };
  cache?: {
    hit: boolean;
    source?: string | null;
    ttl_seconds?: number | null;
  };
};

export type StrategyRegimeSplitRow = {
  dimension?: string;
  bucket?: string;
  sample_count: number;
  closed_count: number;
  tp_count: number;
  sl_count: number;
  both_hit_count: number;
  timeout_count: number;
  waiting_count: number;
  positive_timeout_count: number;
  negative_timeout_count: number;
  total_r?: string | number | null;
  avg_r?: string | number | null;
  median_r?: string | number | null;
  winrate_pct?: string | number | null;
  sl_share_pct?: string | number | null;
  max_drawdown_r?: string | number | null;
  avg_r_delta_vs_baseline?: string | number | null;
  winrate_delta_vs_baseline?: string | number | null;
  sl_share_delta_vs_baseline?: string | number | null;
  verdict?: string;
  note?: string;
};

export type StrategyRegimeSplitResponse = {
  generated_at_utc: string;
  filters: {
    include_watch_only: boolean;
    position_lock: boolean;
    stage: string;
    timeframe: string;
    atr_mult: string;
    rr: string;
    timeout_minutes: number;
    min_sample: number;
    limit: number;
  };
  read_only: boolean;
  not_live_signal: boolean;
  not_execution_instruction: boolean;
  summary: {
    signals_loaded: number;
    evaluated_events: number;
    skipped_counts: Record<string, number>;
    regime_dependency: string;
    baseline: StrategyRegimeSplitRow;
    top_helpful_regimes: StrategyRegimeSplitRow[];
    top_harmful_regimes: StrategyRegimeSplitRow[];
  };
  dimensions: Record<string, StrategyRegimeSplitRow[]>;
  guardrails: string[];
  artifact?: {
    source: string;
    generated_at_utc?: string | null;
    artifact_type?: string | null;
    read_from_artifact: boolean;
  };
};

export type StrategyOptimizationArtifactResponse = {
  generated_at_utc: string;
  artifact_type: string;
  read_only: boolean;
  not_live_signal: boolean;
  not_execution_instruction: boolean;
  filters: {
    include_watch_only: boolean;
    position_lock: boolean;
    min_sample: number;
    limit: number;
    lane_pairs: string[][];
  };
  optimization_by_lane: Record<string, StrategyOptimizationResponse>;
  regime_by_lane: Record<string, StrategyRegimeSplitResponse>;
  v3_shadow: {
    generated_at_utc?: string | null;
    strategy_version?: string | null;
    shadow_strategy_version?: string | null;
    promotion_counts: Record<string, number>;
    v3_candidate_count: number;
    monitor_more_count: number;
    reject_overfit_count: number;
    weak_filter_count: number;
    top_candidates: SignalCalibrationCandidate[];
    lane_filters: {
      stage: string;
      timeframe: string;
      sample_count: number;
      status: string;
      selected_filters: SignalCalibrationCandidate[];
    }[];
    guardrail: string;
  };
  errors: { lane: string; error: string }[];
  guardrails: string[];
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
  strategy_version?: string | null;
  strategy_family?: string | null;
  shadow_strategy_version?: string | null;
  v3_shadow_filter_count?: number | null;
  v3_shadow_status?: string | null;
  v3_shadow_filter_id?: string | null;
  v3_shadow_filter_label?: string | null;
  v3_shadow_filter_expression?: string | null;
  v3_shadow_promotion_score?: number | null;
  v3_shadow_reason?: string | null;
  quality_shadow_status?: string | null;
  quality_shadow_filter_id?: string | null;
  quality_shadow_filter_label?: string | null;
  quality_shadow_filter_expression?: string | null;
  quality_shadow_reason?: string | null;
  quality_shadow_pass?: boolean | null;
  quality_shadow_range_ratio_vs_atr?: string | number | null;
  quality_shadow_fill_quality?: string | null;
  confidence_tier?: string | null;
  execution_flag?: string | null;
  core_score?: string | number | null;
  evidence_score?: string | number | null;
  evidence_data_completeness?: number | null;
  evidence_snapshot?: Record<string, string | number | null>;
  entry?: string | number | null;
  stop_loss?: string | number | null;
  take_profit?: string | number | null;
  risk?: string | number | null;
  rr?: string | number | null;
  realistic_model_version?: string | null;
  realistic_fee_model?: string | null;
  realistic_fee_source?: string | null;
  realistic_fee_pct_per_side?: string | number | null;
  realistic_taker_fee_pct_per_side?: string | number | null;
  realistic_maker_fee_pct_per_side?: string | number | null;
  realistic_slippage_pct_per_side?: string | number | null;
  realistic_futures_spread_pct?: string | number | null;
  realistic_spread_source?: string | null;
  realistic_round_trip_cost_pct_estimate?: string | number | null;
  realistic_cost_r_estimate?: string | number | null;
  realistic_fill_quality?: string | null;
  result_status: string;
  result_time_utc?: string | null;
  result_time_wib?: string | null;
  exit_price?: string | number | null;
  realized_r?: string | number | null;
  unrealized_r?: string | number | null;
  realistic_result_status?: string | null;
  realistic_entry_price?: string | number | null;
  realistic_exit_price?: string | number | null;
  realistic_realized_r?: string | number | null;
  realistic_unrealized_r?: string | number | null;
  realism_penalty_r?: string | number | null;
  mfe_r?: string | number | null;
  mae_r?: string | number | null;
  path_type?: string | null;
  direction_15m?: string | null;
  direction_30m?: string | null;
  direction_1h?: string | null;
  direction_2h?: string | null;
  direction_4h?: string | null;
  return_15m_pct?: string | number | null;
  return_30m_pct?: string | number | null;
  return_1h_pct?: string | number | null;
  return_2h_pct?: string | number | null;
  return_4h_pct?: string | number | null;
  wrong_direction_type?: string | null;
  candles_seen: number;
  stale_forward_data?: boolean;
  stale_reason?: string | null;
  stale_gap_minutes?: string | number | null;
  freshness_gap_minutes?: string | number | null;
  latest_symbol_candle_time?: string | null;
  latest_symbol_candle_time_wib?: string | null;
  global_latest_evaluation_candle_time?: string | null;
  global_latest_evaluation_candle_time_wib?: string | null;
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
  realistic_total_r_closed?: string | number;
  realistic_open_unrealized_r?: string | number;
  realistic_total_r_with_open?: string | number;
  realism_penalty_r_closed?: string | number;
  realism_penalty_r_with_open?: string | number;
  fixed_risk_return_pct_1pct_closed: string | number;
  fixed_risk_return_pct_1pct_with_open: string | number;
  avg_r_closed?: string | number | null;
  realistic_avg_r_closed?: string | number | null;
};

export type SignalPerformanceResponse = {
  generated_at_utc: string;
  snapshot?: {
    source: string;
    filename: string;
    generated_at_utc: string;
    refresh_owner: string;
    read_model: string;
  };
  cache?: {
    hit: boolean;
    source?: string;
    ttl_seconds?: number | null;
  };
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

export type SignalForwardIntegrityResponse = {
  generated_at_utc: string;
  snapshot?: {
    source: string;
    filename: string;
    generated_at_utc: string;
    refresh_owner: string;
    read_model: string;
  };
  cache?: {
    hit: boolean;
    source?: string;
    ttl_seconds?: number | null;
  };
  epoch: string;
  filters: {
    include_watch_only: boolean;
    position_lock: boolean;
    stage?: string | null;
    timeframe?: string | null;
    limit: number;
  };
  read_only: boolean;
  not_live_signal: boolean;
  not_execution_instruction: boolean;
  stale_after_minutes: number;
  latest_evaluation_candle_time?: string | null;
  global_latest_evaluation_candle_time?: string | null;
  global_latest_evaluation_candle_time_wib?: string | null;
  summary: {
    integrity_status: string;
    signals_evaluated: number;
    signals_skipped: number;
    fresh_open_count: number;
    stale_forward_count: number;
    waiting_data_count: number;
    active_or_pending_count: number;
    closed_count: number;
    tp_count: number;
    sl_count: number;
    both_hit_count: number;
    status_counts: Record<string, number>;
    skip_reasons: Record<string, number>;
    fresh_symbol_count: number;
    stale_symbol_count: number;
    waiting_symbol_count: number;
  };
  items: SignalPerformanceItem[];
  stale_items: SignalPerformanceItem[];
  guardrails: string[];
};

export type V3ShadowStatusRow = SignalPerformanceBucket & {
  bucket: string;
  sample_count: number;
  sample_retention_pct?: string | number | null;
  sl_share_pct?: string | number | null;
  avg_r_delta_vs_v2?: string | number | null;
  total_r_delta_vs_v2?: string | number | null;
  winrate_delta_vs_v2?: string | number | null;
  sl_share_delta_vs_v2?: string | number | null;
  verdict: string;
};

export type V3ShadowLaneRow = {
  stage: string;
  timeframe: string;
  v2_live: SignalPerformanceBucket;
  v3_shadow_pass: SignalPerformanceBucket;
  v3_pass_count: number;
  v3_fail_count: number;
  v3_unavailable_count: number;
  v3_no_filter_count: number;
  sample_retention_pct?: string | number | null;
  avg_r_delta_v3_pass_vs_v2?: string | number | null;
  total_r_delta_v3_pass_vs_v2?: string | number | null;
  winrate_delta_v3_pass_vs_v2?: string | number | null;
  sl_share_delta_v3_pass_vs_v2?: string | number | null;
  verdict: string;
};

export type V3ShadowFilterRow = SignalPerformanceBucket & {
  filter_id: string;
  label: string;
  expression: string;
  sample_count: number;
  sample_retention_pct?: string | number | null;
  avg_r_delta_vs_v2?: string | number | null;
  winrate_delta_vs_v2?: string | number | null;
  sl_share_delta_vs_v2?: string | number | null;
  verdict: string;
};

export type V3ShadowComparisonResponse = {
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
  study_scope: string;
  strategy_version: string;
  shadow_strategy_version: string;
  latest_evaluation_candle_time?: string | null;
  latest_futures_15m_close_time?: string | null;
  skipped_by_position_lock: Record<string, number>;
  summary: {
    v2_live: SignalPerformanceBucket;
    v3_shadow_pass: SignalPerformanceBucket;
    v3_pass_count: number;
    v3_fail_count: number;
    v3_unavailable_count: number;
    v3_no_filter_count: number;
    v3_not_evaluated_count: number;
    sample_retention_pct?: string | number | null;
    total_r_delta_v3_pass_vs_v2?: string | number | null;
    avg_r_delta_v3_pass_vs_v2?: string | number | null;
    winrate_delta_v3_pass_vs_v2?: string | number | null;
    sl_share_delta_v3_pass_vs_v2?: string | number | null;
    read: string;
  };
  by_v3_status: V3ShadowStatusRow[];
  by_lane: V3ShadowLaneRow[];
  by_filter: V3ShadowFilterRow[];
  latest_pass_signals: SignalPerformanceItem[];
  latest_fail_signals: SignalPerformanceItem[];
  guardrails: string[];
};

export type V3ShadowForwardLaneSummary = {
  performance: SignalPerformanceBucket;
  drawdown: {
    closed_count: number;
    total_r_closed: string | number;
    peak_r: string | number;
    max_drawdown_r: string | number;
    current_drawdown_r: string | number;
  };
  quality: {
    quality_flag?: string | null;
    median_r_closed?: string | number | null;
    median_mfe_r?: string | number | null;
    median_mae_r?: string | number | null;
    best_r?: string | number | null;
    worst_r?: string | number | null;
    top_symbol?: string | null;
    top_symbol_share_pct?: string | number | null;
    symbol_count?: number | null;
  };
};

export type V3ShadowForwardLaneRow = {
  stage: string;
  timeframe: string;
  v2_live: V3ShadowForwardLaneSummary;
  v3_shadow_signal: V3ShadowForwardLaneSummary;
  v3_shadow_signal_count: number;
  v3_sample_retention_pct?: string | number | null;
  total_r_delta_v3_vs_v2?: string | number | null;
  avg_r_delta_v3_vs_v2?: string | number | null;
  winrate_delta_v3_vs_v2?: string | number | null;
  max_drawdown_delta_v3_vs_v2?: string | number | null;
  read: string;
};

export type V3ShadowForwardStageDecision = {
  stage: string;
  timeframe: string;
  decision: string;
  quality_flag: string;
  reason: string;
  v2_evaluated: number;
  v2_closed_count: number;
  v2_total_r_closed?: string | number | null;
  v2_realistic_total_r_closed?: string | number | null;
  v2_max_drawdown_r?: string | number | null;
  v3_signal_count: number;
  v3_closed_count: number;
  v3_total_r_closed?: string | number | null;
  v3_realistic_total_r_closed?: string | number | null;
  v3_avg_r_closed?: string | number | null;
  v3_realistic_avg_r_closed?: string | number | null;
  v3_winrate_pct?: string | number | null;
  v3_max_drawdown_r?: string | number | null;
  v3_top_symbol?: string | null;
  v3_top_symbol_share_pct?: string | number | null;
  v3_symbol_count?: number | null;
  retention_pct?: string | number | null;
  total_r_delta_vs_v2?: string | number | null;
  avg_r_delta_vs_v2?: string | number | null;
  realistic_total_r_delta_vs_v2?: string | number | null;
  max_drawdown_delta_vs_v2?: string | number | null;
  read?: string | null;
};

export type V3ShadowForwardFilterDecision = {
  filter_id: string;
  filter_label: string;
  expression: string;
  decision: string;
  reason: string;
  sample_count: number;
  closed_count: number;
  tp_count: number;
  sl_count: number;
  open_count: number;
  total_r_closed?: string | number | null;
  realistic_total_r_closed?: string | number | null;
  avg_r_closed?: string | number | null;
  realistic_avg_r_closed?: string | number | null;
  winrate_pct?: string | number | null;
  avg_r_delta_vs_v2?: string | number | null;
  sl_share_delta_vs_v2?: string | number | null;
  verdict?: string | null;
};

export type V3FailureEvidenceRow = {
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

export type V3FailureBucketRow = SignalPerformanceBucket & {
  bucket: string;
  label: string;
  expression?: string | null;
  sample_count: number;
  sl_share_pct?: string | number | null;
  read: string;
};

export type V3FailureLaneRow = SignalPerformanceBucket & {
  stage: string;
  timeframe: string;
  sample_count: number;
  sl_share_pct?: string | number | null;
  read: string;
};

export type V3FailureAnalysis = {
  scope: string;
  readiness_verdict: string;
  failure_read: string;
  summary: {
    v2_closed_count: number;
    v3_closed_count: number;
    v3_tp_count: number;
    v3_sl_count: number;
    v3_both_count: number;
    v3_open_count: number;
    v3_total_r_closed?: string | number | null;
    v3_realistic_total_r_closed?: string | number | null;
    v3_winrate_pct?: string | number | null;
    v3_sl_share_pct?: string | number | null;
    v3_retention_closed_pct?: string | number | null;
    realistic_total_r_delta_vs_v2?: string | number | null;
  };
  evidence_tp_vs_sl: V3FailureEvidenceRow[];
  top_evidence_gaps: V3FailureEvidenceRow[];
  loss_by_filter: V3FailureBucketRow[];
  loss_by_symbol: V3FailureBucketRow[];
  loss_by_lane: V3FailureLaneRow[];
  latest_v3_sl_signals: SignalPerformanceItem[];
  latest_v3_tp_signals: SignalPerformanceItem[];
  guardrails: string[];
};

export type V3HigherTimeframeSummaryRow = {
  timeframe: string;
  v2_signal_count: number;
  v3_signal_count: number;
  v3_closed_count: number;
  v3_tp_count: number;
  v3_sl_count: number;
  v3_total_r_closed?: string | number | null;
  v3_realistic_total_r_closed?: string | number | null;
  v3_winrate_pct?: string | number | null;
  v3_sl_share_pct?: string | number | null;
  realistic_avg_delta_vs_v2?: string | number | null;
  verdict: string;
  read: string;
};

export type V3HigherTimeframeLaneRow = V3HigherTimeframeSummaryRow & {
  stage: string;
  v3_both_count: number;
  v3_open_count: number;
  v3_avg_r_closed?: string | number | null;
  v3_realistic_avg_r_closed?: string | number | null;
  worst_filter_id?: string | null;
  worst_filter_label?: string | null;
  worst_filter_sl_count: number;
  worst_symbol?: string | null;
  worst_symbol_sl_count: number;
  top_evidence_field?: string | null;
  top_evidence_label?: string | null;
  top_evidence_quality_flag?: string | null;
  top_evidence_tp_median?: string | number | null;
  top_evidence_sl_median?: string | number | null;
};

export type V3HigherTimeframeQualityAudit = {
  scope: string;
  timeframes: string[];
  summary: {
    higher_timeframe_v2_signal_count: number;
    higher_timeframe_v3_signal_count: number;
    higher_timeframe_v3_closed_count: number;
    active_lane_count: number;
    ready_lane_count: number;
    monitor_lane_count: number;
    noisy_lane_count: number;
    waiting_lane_count: number;
    audit_readiness: string;
  };
  timeframe_rows: V3HigherTimeframeSummaryRow[];
  lane_rows: V3HigherTimeframeLaneRow[];
  priority_lanes: V3HigherTimeframeLaneRow[];
  guardrails: string[];
};

export type V3ShadowForwardAudit = {
  executive_verdict: string;
  promotion_readiness: string;
  main_findings: string[];
  next_recommendation: string;
  promising_stage_count: number;
  monitor_stage_count: number;
  promising_filter_count: number;
  risk_flags: { flag: string; severity: string; detail: string }[];
  stage_decisions: V3ShadowForwardStageDecision[];
  filter_decisions: V3ShadowForwardFilterDecision[];
  guardrails: string[];
};

export type V3ShadowForwardLogResponse = {
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
  artifact_type: string;
  study_scope: string;
  source_table: string;
  logging_model: string;
  strategy_version: string;
  shadow_strategy_version: string;
  latest_evaluation_candle_time?: string | null;
  latest_futures_15m_close_time?: string | null;
  latest_v3_signal_time?: string | null;
  skipped_by_position_lock: Record<string, number>;
  summary: {
    v2_live: V3ShadowForwardLaneSummary;
    v3_shadow_signal: V3ShadowForwardLaneSummary;
    v3_shadow_signal_count: number;
    v3_shadow_closed_count: number;
    v3_shadow_open_count: number;
    v3_sample_retention_pct?: string | number | null;
    total_r_delta_v3_vs_v2?: string | number | null;
    avg_r_delta_v3_vs_v2?: string | number | null;
    winrate_delta_v3_vs_v2?: string | number | null;
    max_drawdown_delta_v3_vs_v2?: string | number | null;
    read: string;
  };
  audit?: V3ShadowForwardAudit;
  failure_analysis?: V3FailureAnalysis;
  higher_timeframe_quality_audit?: V3HigherTimeframeQualityAudit;
  by_stage_timeframe: V3ShadowForwardLaneRow[];
  by_filter: V3ShadowFilterRow[];
  latest_v3_open_signals: SignalPerformanceItem[];
  latest_v3_closed_signals: SignalPerformanceItem[];
  latest_v3_signals: SignalPerformanceItem[];
  guardrails: string[];
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
    strategy_version?: string | null;
    shadow_strategy_version?: string | null;
    v3_shadow_status?: string | null;
    v3_shadow_filter_id?: string | null;
    v3_shadow_filter_label?: string | null;
    confidence_tier?: string | null;
    execution_flag?: string | null;
    source_artifact_generated_at?: string | null;
    observation_epoch?: string | null;
    created_at?: string | null;
    updated_at?: string | null;
  };
  chart?: SignalChartPayload;
  evidence: Record<string, unknown>;
};

export type SignalChartCandle = {
  open_time: string;
  close_time: string;
  open: string | number;
  high: string | number;
  low: string | number;
  close: string | number;
  volume?: string | number | null;
  source_interval: "15m" | "1m" | string;
};

export type SignalChartPayload = {
  market: string;
  price_source: string;
  display_interval: string;
  candle_count: number;
  signal_time: string;
  signal_time_wib?: string | null;
  result_time?: string | null;
  result_time_wib?: string | null;
  box_end_time: string;
  direction: string;
  result_status: string;
  entry: string | number;
  stop_loss: string | number;
  take_profit: string | number;
  latest_price?: string | number | null;
  latest_candle_time?: string | null;
  candles: SignalChartCandle[];
};

export type SignalQualityBucket = SignalPerformanceBucket & {
  bucket: string;
  label?: string;
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

export type SignalQualityVolumeRankBucket = SignalQualityBucket & {
  rank_cutoff?: number | null;
  rank_scope: string;
  missing_rank_count: number;
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

export type SignalQualityTopSymbolR = {
  symbol: string;
  sample_count: number;
  closed_count: number;
  tp_count: number;
  sl_count: number;
  total_r_closed: string | number;
  realistic_total_r_closed?: string | number | null;
};

export type SignalQualityEvidenceGap = {
  field: string;
  label: string;
  quality_flag: string;
  tp_median?: string | number | null;
  sl_median?: string | number | null;
  delta_tp_minus_sl?: string | number | null;
};

export type SignalQualityProfitLossDriver = SignalQualityEvidenceGap & {
  direction_read: string;
  available_count: number;
  missing_count: number;
  available_pct?: string | number | null;
  tp_count: number;
  sl_count: number;
  tp_q1?: string | number | null;
  tp_q3?: string | number | null;
  sl_q1?: string | number | null;
  sl_q3?: string | number | null;
  read: string;
};

export type SignalQualityProfitLossLane = SignalPerformanceBucket & {
  stage: string;
  timeframe: string;
  sample_count: number;
  sl_share_pct?: string | number | null;
  realistic_read: string;
  top_evidence_gap?: SignalQualityEvidenceGap | null;
  top_loss_symbol?: SignalQualityTopSymbolR | null;
  top_profit_symbol?: SignalQualityTopSymbolR | null;
};

export type SignalQualityRealisticDragRow = SignalPerformanceBucket & {
  dimension: string;
  bucket: string;
  sample_count: number;
  sl_share_pct?: string | number | null;
  avg_penalty_r_closed?: string | number | null;
  realistic_read: string;
};

export type SignalQualityProfitLossResearch = {
  scope: string;
  method: string;
  summary: SignalPerformanceBucket & {
    sl_share_pct?: string | number | null;
    realistic_read: string;
  };
  tp_drivers: SignalQualityProfitLossDriver[];
  lane_rows: SignalQualityProfitLossLane[];
  realistic_drag: {
    by_symbol: SignalQualityRealisticDragRow[];
    by_stage: SignalQualityRealisticDragRow[];
    by_timeframe: SignalQualityRealisticDragRow[];
    by_confidence: SignalQualityRealisticDragRow[];
    by_fill_quality: SignalQualityRealisticDragRow[];
  };
  read: string;
  guardrails: string[];
};

export type SignalQualityMidShortRefinementRow = OneHourWalkForwardPerf & {
  filter_id: string;
  label: string;
  expression: string;
  family: string;
  required_fields: string[];
  source_count: number;
  missing_data_count: number;
  missing_data_pct?: string | number | null;
  sample_retention_pct?: string | number | null;
  verdict: string;
  mitigation_read: string;
  risk_notes: string[];
};

export type SignalQualityMidShortRefinement = {
  scope: string;
  stage: string;
  timeframe: string;
  direction: string;
  method: string;
  baseline: OneHourWalkForwardPerf;
  summary: {
    source_count: number;
    promising_count: number;
    damage_reduction_count: number;
    rejected_count: number;
    readiness: string;
  };
  shadow_filter?: {
    filter_id: string;
    label: string;
    expression: string;
    status_meaning: string;
  };
  shadow_monitor?: {
    pass_count: number;
    fail_count: number;
    unavailable_count: number;
    pass: OneHourWalkForwardPerf;
    fail: OneHourWalkForwardPerf;
    unavailable: OneHourWalkForwardPerf;
  };
  top_filters: SignalQualityMidShortRefinementRow[];
  promising_filters: SignalQualityMidShortRefinementRow[];
  rejected_filters: SignalQualityMidShortRefinementRow[];
  mitigation_plan: string[];
  guardrails: string[];
};

export type MidShortShadowStatusRow = OneHourWalkForwardPerf & {
  shadow_status: string;
  bucket: string;
  label: string;
  sample_retention_pct?: string | number | null;
  read: string;
};

export type MidShortShadowForwardLogResponse = {
  generated_at_utc: string;
  epoch: string;
  filters: {
    include_watch_only: boolean;
    position_lock: boolean;
    stage: string;
    timeframe: string;
    result_status?: string | null;
    limit: number;
    min_sample: number;
  };
  read_only: boolean;
  not_live_signal: boolean;
  not_execution_instruction: boolean;
  artifact_type: string;
  study_scope: string;
  source_table: string;
  strategy_version: string;
  shadow_strategy_version: string;
  shadow_filter: {
    filter_id: string;
    label: string;
    expression: string;
    range_atr_max: string | number;
    status_meaning: string;
  };
  latest_evaluation_candle_time?: string | null;
  latest_futures_15m_close_time?: string | null;
  skipped_by_position_lock: Record<string, number>;
  summary: {
    source_count: number;
    pass_count: number;
    fail_count: number;
    unavailable_count: number;
    not_applicable_count: number;
    pass_retention_pct?: string | number | null;
    fail_retention_pct?: string | number | null;
    realistic_total_r_delta_pass_vs_fail?: string | number | null;
    realistic_avg_r_delta_pass_vs_fail?: string | number | null;
    read: string;
  };
  baseline: OneHourWalkForwardPerf;
  by_shadow_status: MidShortShadowStatusRow[];
  latest_pass_signals: SignalPerformanceItem[];
  latest_fail_signals: SignalPerformanceItem[];
  latest_unavailable_signals: SignalPerformanceItem[];
  items: SignalPerformanceItem[];
  guardrails: string[];
  cache?: {
    hit: boolean;
    ttl_seconds?: number | null;
  };
};

export type MidShortFailureBucketRow = OneHourWalkForwardPerf & {
  dimension: string;
  bucket: string;
  label: string;
  sample_count: number;
  sl_share_pct?: string | number | null;
  read: string;
  horizon?: string;
};

export type MidShortFailureImprovementCandidate = OneHourWalkForwardPerf & {
  filter_id: string;
  label: string;
  expression: string;
  family: string;
  required_fields: string[];
  source_count: number;
  missing_data_count: number;
  missing_data_pct?: string | number | null;
  sample_retention_pct?: string | number | null;
  read: string;
};

export type MidShortFailureAnatomyResponse = {
  generated_at_utc: string;
  epoch: string;
  filters: {
    include_watch_only: boolean;
    position_lock: boolean;
    stage: string;
    timeframe: string;
    shadow_status: string;
    min_sample: number;
    limit: number;
  };
  read_only: boolean;
  not_live_signal: boolean;
  not_execution_instruction: boolean;
  artifact_type: string;
  study_scope: string;
  source_table: string;
  strategy_version: string;
  shadow_strategy_version: string;
  shadow_filter: {
    filter_id: string;
    label: string;
    expression: string;
    status_meaning: string;
  };
  latest_evaluation_candle_time?: string | null;
  latest_futures_15m_close_time?: string | null;
  skipped_by_position_lock: Record<string, number>;
  summary: {
    source_count: number;
    closed_count: number;
    tp_count: number;
    sl_count: number;
    both_hit_count: number;
    open_count: number;
    sl_then_would_tp_count: number;
    tp_near_then_sl_count: number;
    sl_direct_count: number;
    wrong_direction_1h_count: number;
    correct_direction_1h_count: number;
    read: string;
  };
  baseline: OneHourWalkForwardPerf;
  mfe_mae_summary: Record<string, {
    sample_count: number;
    median_mfe_r?: string | number | null;
    median_mae_r?: string | number | null;
    median_mfe_before_first_hit_r?: string | number | null;
    median_mae_before_first_hit_r?: string | number | null;
    mfe_ge_0_5_count: number;
    mfe_ge_1_0_count: number;
    mae_le_minus_1_count: number;
  }>;
  outcome_path_rows: MidShortFailureBucketRow[];
  direction_rows: MidShortFailureBucketRow[];
  regime_rows: MidShortFailureBucketRow[];
  session_rows: MidShortFailureBucketRow[];
  symbol_rows: MidShortFailureBucketRow[];
  evidence_tp_vs_sl: SignalQualityEvidenceField[];
  improvement_candidates: MidShortFailureImprovementCandidate[];
  latest_sl_signals: SignalPerformanceItem[];
  latest_tp_signals: SignalPerformanceItem[];
  latest_open_signals: SignalPerformanceItem[];
  guardrails: string[];
  cache?: {
    hit: boolean;
    ttl_seconds?: number | null;
  };
};

export type MidShortSecondFilterRow = OneHourWalkForwardPerf & {
  filter_id: string;
  label: string;
  expression: string;
  family: string;
  required_fields: string[];
  source_count: number;
  missing_data_count: number;
  missing_data_pct?: string | number | null;
  sample_retention_pct?: string | number | null;
  sl_then_would_tp_count: number;
  tp_near_then_sl_count: number;
  wrong_direction_1h_count: number;
  correct_direction_1h_count: number;
  sl_direct_count: number;
  sl_then_would_tp_share_pct?: string | number | null;
  tp_near_then_sl_share_pct?: string | number | null;
  wrong_direction_1h_share_pct?: string | number | null;
  correct_direction_1h_share_pct?: string | number | null;
  sl_then_would_tp_share_pct_delta_vs_baseline?: string | number | null;
  tp_near_then_sl_share_pct_delta_vs_baseline?: string | number | null;
  wrong_direction_1h_share_pct_delta_vs_baseline?: string | number | null;
  correct_direction_1h_share_pct_delta_vs_baseline?: string | number | null;
  read: string;
};

export type MidShortSecondFilterShadowResponse = {
  generated_at_utc: string;
  epoch: string;
  filters: {
    include_watch_only: boolean;
    position_lock: boolean;
    stage: string;
    timeframe: string;
    shadow_status: string;
    min_sample: number;
    limit: number;
  };
  read_only: boolean;
  not_live_signal: boolean;
  not_execution_instruction: boolean;
  artifact_type: string;
  study_scope: string;
  source_table: string;
  strategy_version: string;
  shadow_strategy_version: string;
  shadow_filter: {
    filter_id: string;
    label: string;
    expression: string;
    status_meaning: string;
  };
  latest_evaluation_candle_time?: string | null;
  latest_futures_15m_close_time?: string | null;
  skipped_by_position_lock: Record<string, number>;
  summary: {
    source_count: number;
    baseline: OneHourWalkForwardPerf;
    filter_count: number;
    monitor_count: number;
    damage_reduction_count: number;
    top_filter_id?: string | null;
    top_filter_label?: string | null;
    read: string;
  };
  filter_rows: MidShortSecondFilterRow[];
  top_filter_items: SignalPerformanceItem[];
  baseline_path_rows: MidShortFailureBucketRow[];
  guardrails: string[];
  cache?: {
    hit: boolean;
    ttl_seconds?: number | null;
  };
};

export type MidShortTakerSellDeepDiveResponse = {
  generated_at_utc: string;
  epoch: string;
  filters: {
    include_watch_only: boolean;
    position_lock: boolean;
    stage: string;
    timeframe: string;
    shadow_status: string;
    base_filter_id: string;
    min_sample: number;
    limit: number;
  };
  read_only: boolean;
  not_live_signal: boolean;
  not_execution_instruction: boolean;
  artifact_type: string;
  study_scope: string;
  source_table: string;
  strategy_version: string;
  shadow_strategy_version: string;
  base_filter: {
    filter_id: string;
    label: string;
    expression: string;
    status_meaning: string;
  };
  latest_evaluation_candle_time?: string | null;
  latest_futures_15m_close_time?: string | null;
  skipped_by_position_lock: Record<string, number>;
  summary: {
    source_shadow_pass_count: number;
    scope_count: number;
    closed_count: number;
    tp_count: number;
    sl_count: number;
    open_count: number;
    sl_then_would_tp_count: number;
    tp_near_then_sl_count: number;
    wrong_direction_1h_count: number;
    correct_direction_1h_count: number;
    baseline: OneHourWalkForwardPerf;
    filter_count: number;
    promising_count: number;
    damage_reduction_count: number;
    top_filter_id?: string | null;
    top_filter_label?: string | null;
    read: string;
  };
  filter_rows: MidShortSecondFilterRow[];
  outcome_path_rows: MidShortFailureBucketRow[];
  direction_rows: MidShortFailureBucketRow[];
  regime_rows: MidShortFailureBucketRow[];
  session_rows: MidShortFailureBucketRow[];
  symbol_rows: MidShortFailureBucketRow[];
  evidence_tp_vs_sl: SignalQualityEvidenceField[];
  top_filter_items: SignalPerformanceItem[];
  latest_sl_signals: SignalPerformanceItem[];
  latest_tp_signals: SignalPerformanceItem[];
  latest_open_signals: SignalPerformanceItem[];
  guardrails: string[];
  cache?: {
    hit: boolean;
    ttl_seconds?: number | null;
  };
};

export type MidShortWrongDirectionEvidenceRow = {
  field: string;
  label: string;
  quality_flag: string;
  available_count: number;
  missing_count: number;
  available_pct?: string | number | null;
  correct_count: number;
  wrong_count: number;
  correct_median?: string | number | null;
  wrong_median?: string | number | null;
  correct_q1?: string | number | null;
  correct_q3?: string | number | null;
  wrong_q1?: string | number | null;
  wrong_q3?: string | number | null;
  delta_correct_minus_wrong?: string | number | null;
};

export type MidShortWrongDirectionFilterRow = MidShortSecondFilterRow & {
  flat_1h_count: number;
  missing_direction_1h_count: number;
  flat_1h_share_pct?: string | number | null;
  missing_direction_1h_share_pct?: string | number | null;
};

export type MidShortWrongDirectionDeepDiveResponse = {
  generated_at_utc: string;
  epoch: string;
  filters: {
    include_watch_only: boolean;
    position_lock: boolean;
    stage: string;
    timeframe: string;
    shadow_status: string;
    base_filter_id: string;
    min_sample: number;
    limit: number;
  };
  read_only: boolean;
  not_live_signal: boolean;
  not_execution_instruction: boolean;
  artifact_type: string;
  study_scope: string;
  source_table: string;
  strategy_version: string;
  shadow_strategy_version: string;
  base_filter: {
    filter_id: string;
    label: string;
    expression: string;
    status_meaning: string;
  };
  latest_evaluation_candle_time?: string | null;
  latest_futures_15m_close_time?: string | null;
  skipped_by_position_lock: Record<string, number>;
  summary: {
    source_shadow_pass_count: number;
    scope_count: number;
    closed_count: number;
    tp_count: number;
    sl_count: number;
    open_count: number;
    wrong_direction_1h_count: number;
    correct_direction_1h_count: number;
    neutral_direction_1h_count: number;
    wrong_direction_1h_share_pct?: string | number | null;
    correct_direction_1h_share_pct?: string | number | null;
    baseline: OneHourWalkForwardPerf;
    wrong_direction_perf: OneHourWalkForwardPerf;
    correct_direction_perf: OneHourWalkForwardPerf;
    filter_count: number;
    promising_count: number;
    damage_reduction_count: number;
    top_filter_id?: string | null;
    top_filter_label?: string | null;
    read: string;
  };
  wrong_direction_taxonomy_rows: MidShortFailureBucketRow[];
  followthrough_rows: MidShortFailureBucketRow[];
  evidence_correct_vs_wrong: MidShortWrongDirectionEvidenceRow[];
  anti_wrong_direction_filter_rows: MidShortWrongDirectionFilterRow[];
  regime_rows: MidShortFailureBucketRow[];
  symbol_wrong_rows: MidShortFailureBucketRow[];
  top_filter_items: SignalPerformanceItem[];
  latest_wrong_direction_signals: SignalPerformanceItem[];
  latest_correct_direction_signals: SignalPerformanceItem[];
  guardrails: string[];
  cache?: {
    hit: boolean;
    ttl_seconds?: number | null;
  };
};

export type MidShortVolumeSafeStatusRow = OneHourWalkForwardPerf & {
  shadow_status: string;
  bucket: string;
  label: string;
  sample_retention_pct?: string | number | null;
  wrong_direction_1h_count: number;
  correct_direction_1h_count: number;
  flat_1h_count: number;
  missing_direction_1h_count: number;
  wrong_direction_1h_share_pct?: string | number | null;
  correct_direction_1h_share_pct?: string | number | null;
  wrong_direction_1h_share_pct_delta_vs_baseline?: string | number | null;
  correct_direction_1h_share_pct_delta_vs_baseline?: string | number | null;
};

export type MidShortVolumeSafeShadowResponse = {
  generated_at_utc: string;
  epoch: string;
  filters: {
    include_watch_only: boolean;
    position_lock: boolean;
    stage: string;
    timeframe: string;
    shadow_status: string;
    base_filter_id: string;
    shadow_filter_id: string;
    min_sample: number;
    limit: number;
  };
  read_only: boolean;
  not_live_signal: boolean;
  not_execution_instruction: boolean;
  artifact_type: string;
  study_scope: string;
  source_table: string;
  strategy_version: string;
  shadow_strategy_version: string;
  base_filter: {
    filter_id: string;
    label: string;
    expression: string;
    status_meaning: string;
  };
  shadow_filter: {
    filter_id: string;
    label: string;
    expression: string;
    status_meaning: string;
  };
  latest_evaluation_candle_time?: string | null;
  latest_futures_15m_close_time?: string | null;
  skipped_by_position_lock: Record<string, number>;
  summary: {
    scope_count: number;
    pass_count: number;
    fail_count: number;
    missing_count: number;
    pass_retention_pct?: string | number | null;
    baseline: OneHourWalkForwardPerf;
    pass: OneHourWalkForwardPerf;
    fail: OneHourWalkForwardPerf;
    missing: OneHourWalkForwardPerf;
    pass_direction: {
      wrong_direction_1h_count: number;
      correct_direction_1h_count: number;
      wrong_direction_1h_share_pct?: string | number | null;
      correct_direction_1h_share_pct?: string | number | null;
      wrong_direction_1h_share_pct_delta_vs_baseline?: string | number | null;
      correct_direction_1h_share_pct_delta_vs_baseline?: string | number | null;
    };
    fail_direction: {
      wrong_direction_1h_count: number;
      correct_direction_1h_count: number;
      wrong_direction_1h_share_pct?: string | number | null;
      correct_direction_1h_share_pct?: string | number | null;
      wrong_direction_1h_share_pct_delta_vs_baseline?: string | number | null;
      correct_direction_1h_share_pct_delta_vs_baseline?: string | number | null;
    };
    read: string;
  };
  status_rows: MidShortVolumeSafeStatusRow[];
  pass_taxonomy_rows: MidShortFailureBucketRow[];
  fail_taxonomy_rows: MidShortFailureBucketRow[];
  pass_evidence_tp_vs_sl: SignalQualityEvidenceField[];
  latest_pass_signals: SignalPerformanceItem[];
  latest_fail_signals: SignalPerformanceItem[];
  latest_missing_signals: SignalPerformanceItem[];
  guardrails: string[];
  cache?: {
    hit: boolean;
    ttl_seconds?: number | null;
  };
};

export type MidShortFilterCombinationRow = MidShortSecondFilterRow & {
  shadow_recommendation: string;
  risk_notes: string[];
};

export type MidShortFilterCombinationDecisionBrief = {
  filter_id?: string | null;
  label?: string | null;
  expression?: string | null;
  read?: string | null;
  sample_count?: number | null;
  closed_count?: number | null;
  tp_count?: number | null;
  sl_count?: number | null;
  realistic_total_r_closed?: string | number | null;
  realistic_avg_r_closed?: string | number | null;
  realistic_avg_r_delta_vs_baseline?: string | number | null;
  sl_share_pct?: string | number | null;
  sl_share_delta_vs_baseline?: string | number | null;
  wrong_direction_1h_share_pct?: string | number | null;
  wrong_direction_1h_share_pct_delta_vs_baseline?: string | number | null;
  max_realistic_drawdown_r?: string | number | null;
  max_drawdown_delta_vs_baseline?: string | number | null;
  top_symbol?: string | null;
  top_symbol_share_pct?: string | number | null;
};

export type MidShortFilterCombinationStudyResponse = {
  generated_at_utc: string;
  epoch: string;
  filters: {
    include_watch_only: boolean;
    position_lock: boolean;
    stage: string;
    timeframe: string;
    shadow_status: string;
    base_filter_id: string;
    min_sample: number;
    limit: number;
  };
  read_only: boolean;
  not_live_signal: boolean;
  not_execution_instruction: boolean;
  artifact_type: string;
  study_scope: string;
  source_table: string;
  strategy_version: string;
  shadow_strategy_version: string;
  base_filter: {
    filter_id: string;
    label: string;
    expression: string;
    status_meaning: string;
  };
  latest_evaluation_candle_time?: string | null;
  latest_futures_15m_close_time?: string | null;
  skipped_by_position_lock: Record<string, number>;
  summary: {
    scope_count: number;
    closed_count: number;
    tp_count: number;
    sl_count: number;
    wrong_direction_1h_count: number;
    correct_direction_1h_count: number;
    baseline: OneHourWalkForwardPerf;
    baseline_direction: {
      wrong_direction_1h_count: number;
      correct_direction_1h_count: number;
      wrong_direction_1h_share_pct?: string | number | null;
      correct_direction_1h_share_pct?: string | number | null;
    };
    combo_count: number;
    shadow_candidate_count: number;
    damage_reduction_count: number;
    reject_count: number;
    top_filter_id?: string | null;
    top_filter_label?: string | null;
    read: string;
  };
  decision_panel?: {
    decision: string;
    recommendation: string;
    baseline_snapshot: {
      closed_count: number;
      tp_count: number;
      sl_count: number;
      realistic_total_r_closed?: string | number | null;
      realistic_avg_r_closed?: string | number | null;
      sl_share_pct?: string | number | null;
      wrong_direction_1h_share_pct?: string | number | null;
    };
    watch_filter?: MidShortFilterCombinationDecisionBrief | null;
    best_sl_reducer?: MidShortFilterCombinationDecisionBrief | null;
    best_wrong_direction_reducer?: MidShortFilterCombinationDecisionBrief | null;
    best_drawdown_reducer?: MidShortFilterCombinationDecisionBrief | null;
    promotion_blockers: string[];
    next_validation: string[];
  };
  combination_rows: MidShortFilterCombinationRow[];
  candidate_rows: MidShortFilterCombinationRow[];
  baseline_path_rows: MidShortFailureBucketRow[];
  top_filter?: MidShortFilterCombinationRow | null;
  top_filter_pass: OneHourWalkForwardPerf;
  top_filter_fail: OneHourWalkForwardPerf;
  top_filter_missing: OneHourWalkForwardPerf;
  top_filter_pass_direction: {
    wrong_direction_1h_count: number;
    correct_direction_1h_count: number;
    wrong_direction_1h_share_pct?: string | number | null;
    correct_direction_1h_share_pct?: string | number | null;
    wrong_direction_1h_share_pct_delta_vs_baseline?: string | number | null;
  };
  top_filter_fail_direction: {
    wrong_direction_1h_count: number;
    correct_direction_1h_count: number;
    wrong_direction_1h_share_pct?: string | number | null;
    correct_direction_1h_share_pct?: string | number | null;
    wrong_direction_1h_share_pct_delta_vs_baseline?: string | number | null;
  };
  top_filter_pass_taxonomy: MidShortFailureBucketRow[];
  top_filter_fail_taxonomy: MidShortFailureBucketRow[];
  top_filter_pass_signals: SignalPerformanceItem[];
  top_filter_fail_signals: SignalPerformanceItem[];
  top_filter_missing_signals: SignalPerformanceItem[];
  guardrails: string[];
  cache?: {
    hit: boolean;
    ttl_seconds?: number | null;
  };
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

export type OneHourFilterCandidateRow = SignalFilterStudyRow & {
  stage: string;
  direction: string;
  timeframe: string;
  action: string;
  action_reason: string;
  risk_notes: string[];
};

export type OneHourFilterCandidateLane = {
  lane: string;
  stage: string;
  direction: string;
  timeframe: string;
  source_count: number;
  baseline: SignalFilterStudyRow;
  filter_candidates: OneHourFilterCandidateRow[];
  actionable_candidates: OneHourFilterCandidateRow[];
  lane_status: string;
  lane_note: string;
};

export type OneHourFilterCandidateStudyResponse = {
  generated_at_utc: string;
  epoch: string;
  filters: {
    include_watch_only: boolean;
    position_lock: boolean;
    timeframe: string;
    stages: string[];
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
  lanes: OneHourFilterCandidateLane[];
  top_candidates: OneHourFilterCandidateRow[];
  guardrails: string[];
};

export type OneHourWalkForwardPerf = SignalPerformanceBucket & {
  sample_count: number;
  median_realistic_r_closed?: string | number | null;
  max_realistic_drawdown_r?: string | number | null;
  sl_share_pct?: string | number | null;
  top_symbol: string;
  top_symbol_count: number;
  top_symbol_share_pct?: string | number | null;
  sample_delta_vs_baseline?: string | number | null;
  realistic_avg_r_delta_vs_baseline?: string | number | null;
  realistic_total_r_delta_vs_baseline?: string | number | null;
  winrate_delta_vs_baseline?: string | number | null;
  sl_share_delta_vs_baseline?: string | number | null;
  max_drawdown_delta_vs_baseline?: string | number | null;
};

export type OneHourWalkForwardCandidate = {
  stage: string;
  direction: string;
  timeframe: string;
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
  all: OneHourWalkForwardPerf;
  train: OneHourWalkForwardPerf;
  validation: OneHourWalkForwardPerf;
  verdict: string;
  score: number;
  note: string;
  risk_notes: string[];
};

export type OneHourWalkForwardLane = {
  lane: string;
  stage: string;
  direction: string;
  timeframe: string;
  sample_count: number;
  train_count: number;
  validation_count: number;
  split_method: string;
  baseline_all: OneHourWalkForwardPerf;
  baseline_train: OneHourWalkForwardPerf;
  baseline_validation: OneHourWalkForwardPerf;
  lane_status: string;
  lane_note: string;
  filter_candidates: OneHourWalkForwardCandidate[];
  actionable_candidates: OneHourWalkForwardCandidate[];
};

export type OneHourWalkForwardResponse = {
  generated_at_utc: string;
  epoch: string;
  filters: {
    include_watch_only: boolean;
    position_lock: boolean;
    timeframe: string;
    stages: string[];
    min_sample: number;
    limit: number;
    max_signals_per_stage: number;
  };
  read_only: boolean;
  not_live_signal: boolean;
  not_execution_instruction: boolean;
  study_scope: string;
  source: string;
  method: string;
  split_method: string;
  latest_evaluation_candle_time?: string | null;
  latest_futures_15m_close_time?: string | null;
  skipped_by_position_lock: Record<string, number>;
  aggregate: SignalPerformanceResponse["aggregate"];
  lanes: OneHourWalkForwardLane[];
  top_candidates: OneHourWalkForwardCandidate[];
  guardrails: string[];
};

export type MisidentificationBucketRow = OneHourWalkForwardPerf & {
  dimension: string;
  bucket: string;
  label: string;
  sample_count: number;
  read: string;
};

export type MisidentificationEvidenceRow = {
  field: string;
  label: string;
  quality_flag: string;
  available_count: number;
  missing_count: number;
  available_pct?: string | number | null;
  correct_count: number;
  wrong_count: number;
  correct_median?: string | number | null;
  wrong_median?: string | number | null;
  delta_correct_minus_wrong?: string | number | null;
};

export type MisidentificationLane = {
  lane: string;
  stage: string;
  timeframe: string;
  direction: string;
  summary: {
    sample_count: number;
    closed_count: number;
    tp_count: number;
    sl_count: number;
    wrong_direction_1h_count: number;
    correct_direction_1h_count: number;
    reverse_clean_count: number;
    reverse_both_zone_count: number;
    sl_share_pct?: string | number | null;
    wrong_direction_1h_share_pct?: string | number | null;
    reverse_clean_share_pct?: string | number | null;
    verdict: string;
    read: string;
  };
  baseline: OneHourWalkForwardPerf;
  reason_rows: MisidentificationBucketRow[];
  reverse_rows: MisidentificationBucketRow[];
  path_rows: MisidentificationBucketRow[];
  evidence_correct_vs_wrong: MisidentificationEvidenceRow[];
  latest_sl_signals: SignalPerformanceItem[];
  latest_tp_signals: SignalPerformanceItem[];
  reverse_clean_examples: SignalPerformanceItem[];
};

export type MisidentificationAuditResponse = {
  generated_at_utc: string;
  epoch: string;
  filters: {
    include_watch_only: boolean;
    position_lock: boolean;
    timeframe: string;
    stages: string[];
    min_sample: number;
    limit: number;
  };
  read_only: boolean;
  not_live_signal: boolean;
  not_execution_instruction: boolean;
  strategy_version: string;
  study_scope: string;
  method: string;
  latest_evaluation_candle_time?: string | null;
  latest_futures_15m_close_time?: string | null;
  skipped_by_position_lock: Record<string, number>;
  lanes: MisidentificationLane[];
  summary: {
    lane_count: number;
    reverse_worth_testing_count: number;
    direction_weak_count: number;
    entry_or_risk_weak_count: number;
    best_lane?: string | null;
    worst_lane?: string | null;
  };
  guardrails: string[];
  cache?: {
    hit: boolean;
    ttl_seconds?: number | null;
  };
};

export type OneHourV4ShadowSelectedFilter = {
  stage: string;
  direction: string;
  timeframe: string;
  filter_id: string;
  label: string;
  expression: string;
  family: string;
  required_fields: string[];
  walk_forward_verdict: string;
  walk_forward_score: number;
  validation: OneHourWalkForwardPerf;
  risk_notes: string[];
};

export type OneHourV4ShadowItem = SignalPerformanceItem & {
  v4_shadow_status?: string | null;
  v4_filter_id?: string | null;
  v4_filter_label?: string | null;
  v4_filter_expression?: string | null;
  v4_walk_forward_verdict?: string | null;
  v4_walk_forward_score?: number | null;
  v4_shadow_reason?: string | null;
};

export type OneHourV4ShadowStageRow = {
  stage: string;
  timeframe: string;
  v2_baseline: OneHourWalkForwardPerf;
  v4_shadow_pass: OneHourWalkForwardPerf;
  v4_shadow_fail: OneHourWalkForwardPerf;
  v4_shadow_pass_count: number;
  v4_shadow_fail_count: number;
  v4_shadow_unavailable_count: number;
  v4_shadow_no_filter_count: number;
  sample_retention_pct?: string | number | null;
  read: string;
};

export type OneHourV4ShadowResponse = {
  generated_at_utc: string;
  epoch: string;
  filters: {
    include_watch_only: boolean;
    position_lock: boolean;
    timeframe: string;
    stages: string[];
    min_sample: number;
    limit: number;
  };
  read_only: boolean;
  not_live_signal: boolean;
  not_execution_instruction: boolean;
  strategy_version: string;
  shadow_strategy_version: string;
  study_scope: string;
  source: string;
  method: string;
  filter_source: string;
  latest_evaluation_candle_time?: string | null;
  latest_futures_15m_close_time?: string | null;
  skipped_by_position_lock: Record<string, number>;
  selected_filters: OneHourV4ShadowSelectedFilter[];
  walk_forward_summary: {
    lane_count: number;
    top_candidate_count: number;
  };
  summary: {
    v2_baseline: OneHourWalkForwardPerf;
    v4_shadow_pass: OneHourWalkForwardPerf;
    v4_shadow_fail: OneHourWalkForwardPerf;
    v4_shadow_pass_count: number;
    v4_shadow_fail_count: number;
    v4_shadow_unavailable_count: number;
    v4_shadow_no_filter_count: number;
    sample_retention_pct?: string | number | null;
    realistic_total_r_delta_v4_vs_v2?: string | number | null;
    realistic_avg_r_delta_v4_vs_v2?: string | number | null;
    winrate_delta_v4_vs_v2?: string | number | null;
    sl_share_delta_v4_vs_v2?: string | number | null;
    read: string;
  };
  by_stage: OneHourV4ShadowStageRow[];
  latest_v4_pass_signals: OneHourV4ShadowItem[];
  latest_v4_fail_signals: OneHourV4ShadowItem[];
  guardrails: string[];
  snapshot?: { generated_at_utc?: string; filename?: string; read_model?: string };
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
  by_volume_rank: SignalQualityVolumeRankBucket[];
  evidence_fields: SignalQualityEvidenceField[];
  profit_loss_research?: SignalQualityProfitLossResearch;
  mid_short_1h_refinement?: SignalQualityMidShortRefinement;
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
