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
  signal_id?: string | null;
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
  structure_zone_shadow?: Record<string, unknown> | null;
  structure_zone_status?: string | null;
  structure_zone_reason?: string | null;
  structure_zone_primary_timeframe?: string | null;
  structure_zone_primary_state?: string | null;
  structure_zone_primary_reason?: string | null;
  structure_zone_primary_zone_count?: number | null;
  structure_zone_nearest_support_distance_atr?: string | number | null;
  structure_zone_nearest_resistance_distance_atr?: string | number | null;
  structure_zone_context_timeframe?: string | null;
  structure_zone_context_status?: string | null;
  structure_zone_context_state?: string | null;
  structure_zone_context_reason?: string | null;
  structure_zone_snapshot_time?: string | null;
  structure_zone_snapshot_source?: string | null;
  structure_zone_read_only?: boolean;
  structure_zone_not_signal_gate?: boolean;
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
  structure_zone_shadow?: Record<string, unknown> | null;
  structure_zone_status?: string | null;
  structure_zone_reason?: string | null;
  structure_zone_primary_timeframe?: string | null;
  structure_zone_primary_state?: string | null;
  structure_zone_primary_reason?: string | null;
  structure_zone_primary_zone_count?: number | null;
  structure_zone_nearest_support_distance_atr?: string | number | null;
  structure_zone_nearest_resistance_distance_atr?: string | number | null;
  structure_zone_context_timeframe?: string | null;
  structure_zone_context_status?: string | null;
  structure_zone_context_state?: string | null;
  structure_zone_context_reason?: string | null;
  structure_zone_snapshot_time?: string | null;
  structure_zone_snapshot_source?: string | null;
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

export type StructureZoneShadowBucket = SignalPerformanceBucket & {
  bucket: string;
  stage?: string;
  timeframe?: string;
  sample_count: number;
  sample_share_pct?: string | number | null;
  sl_share_pct?: string | number | null;
  realistic_avg_r_delta_vs_all?: string | number | null;
  sample_status: string;
};

export type StructureZoneShadowStudyResponse = {
  generated_at_utc: string;
  latest_evaluation_candle_time?: string | null;
  read_only: boolean;
  not_live_signal: boolean;
  not_execution_instruction: boolean;
  snapshot_coverage: {
    evaluated_count: number;
    persisted_snapshot_count: number;
    missing_snapshot_count: number;
    coverage_pct?: string | number | null;
  };
  baseline: SignalPerformanceBucket;
  by_zone_status: StructureZoneShadowBucket[];
  by_stage_timeframe_zone: StructureZoneShadowBucket[];
  latest_signals: SignalPerformanceItem[];
  guardrails: string[];
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
  structure_zones?: SignalStructureZone[];
};

export type SignalStructureZone = {
  center: string | number;
  lower: string | number;
  upper: string | number;
  touch_count: number;
  support_touch_count: number;
  resistance_touch_count: number;
  origin_role: string;
  latest_pivot_kind: string;
  first_touch_time: string;
  last_touch_time: string;
  start_time: string;
  end_time: string;
  source_timeframe?: string | null;
  signal_state?: string | null;
  is_signal_zone?: boolean;
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

export type MidShortSlFailureCauseRow = {
  cause: string;
  label: string;
  sl_count: number;
  sl_share_pct?: string | number | null;
  median_mfe_before_sl_r?: string | number | null;
  median_mae_before_sl_r?: string | number | null;
  median_first_hit_candle_index?: string | number | null;
  after_sl_target_within_4h_count: number;
  tp_near_before_sl_count: number;
  reverse_clean_count: number;
  regime_conflict_count: number;
  overextended_count: number;
  evidence_strength: string;
  research_action?: string | null;
};

export type MidShortTargetDistanceDistribution = {
  sample_count: number;
  available_count: number;
  q1?: string | number | null;
  median?: string | number | null;
  q3?: string | number | null;
};

export type MidShortTargetDistanceMetricRow = {
  field: string;
  label: string;
  target_too_far: MidShortTargetDistanceDistribution;
  tp_control: MidShortTargetDistanceDistribution;
  other_sl: MidShortTargetDistanceDistribution;
  median_delta_vs_tp?: string | number | null;
};

export type MidShortCounterfactualPerf = {
  sample_count: number;
  tp_count: number;
  sl_count: number;
  both_count: number;
  breakeven_count: number;
  neither_count: number;
  total_realistic_r?: string | number | null;
  avg_realistic_r?: string | number | null;
  median_realistic_r?: string | number | null;
  max_drawdown_r?: string | number | null;
  sl_share_pct?: string | number | null;
  top_symbol?: string | null;
  top_symbol_count: number;
  top_symbol_share_pct?: string | number | null;
};

export type MidShortCounterfactualRow = {
  config_id: string;
  label: string;
  risk_scale: string | number;
  target_rr?: string | number | null;
  protect_at_r?: string | number | null;
  use_logged_target: boolean;
  evaluation_horizon: string;
  all: MidShortCounterfactualPerf;
  train: MidShortCounterfactualPerf;
  validation: MidShortCounterfactualPerf;
  target_too_far_subset: MidShortCounterfactualPerf;
  validation_avg_r_delta_vs_control?: string | number | null;
  verdict: string;
};

export type MidShortTargetDistanceCase = {
  signal_id: string;
  symbol: string;
  signal_timestamp: string;
  signal_time_wib?: string | null;
  entry?: string | number | null;
  stop_loss?: string | number | null;
  take_profit?: string | number | null;
  rr?: string | number | null;
  result_time_wib?: string | null;
  mfe_before_first_hit_r?: string | number | null;
  mae_before_first_hit_r?: string | number | null;
  first_hit_candle_index?: string | number | null;
  atr_1h_at_entry?: string | number | null;
  atr_pct_entry?: string | number | null;
  logged_risk_atr_ratio?: string | number | null;
  atr_vs_30_median?: string | number | null;
  atr_signal_inflation_ratio?: string | number | null;
  signal_true_range_atr?: string | number | null;
  pre_entry_1h_move_atr?: string | number | null;
  pre_entry_4h_move_atr?: string | number | null;
  support_distance_r?: string | number | null;
  support_before_target: boolean;
  forward_1h_realized_range_atr?: string | number | null;
  entry_taker_sell_ratio?: string | number | null;
  forward_1h_taker_sell_ratio?: string | number | null;
  taker_sell_delta_1h?: string | number | null;
  forward_1h_volume_vs_pre30?: string | number | null;
  forward_1h_oi_change_pct?: string | number | null;
  target_distance_context_status: string;
  target_distance_primary_hypothesis: string;
  target_distance_hypotheses: string[];
};

export type MidShortStructureClearanceStatusRow = {
  status: string;
  sample_retention_pct?: string | number | null;
  all: OneHourWalkForwardPerf;
  train: OneHourWalkForwardPerf;
  validation: OneHourWalkForwardPerf;
  read: string;
};

export type MidShortStructureExitVariantRow = {
  config_id: string;
  label: string;
  risk_scale: string | number;
  target_rr?: string | number | null;
  protect_at_r?: string | number | null;
  use_logged_target: boolean;
  clear_all: MidShortCounterfactualPerf;
  clear_train: MidShortCounterfactualPerf;
  clear_validation: MidShortCounterfactualPerf;
  blocked_validation: MidShortCounterfactualPerf;
  clear_validation_avg_delta_vs_logged?: string | number | null;
  clear_validation_avg_delta_vs_blocked?: string | number | null;
  verdict: string;
};

export type MidShortStructureBlockedCase = {
  signal_id: string;
  symbol: string;
  signal_timestamp: string;
  signal_time_wib?: string | null;
  entry?: string | number | null;
  stop_loss?: string | number | null;
  take_profit?: string | number | null;
  rr?: string | number | null;
  support_price_proxy?: string | number | null;
  support_distance_r?: string | number | null;
  support_clearance_to_target_r?: string | number | null;
  support_method?: string | null;
  result_status: string;
  realistic_r?: string | number | null;
  failure_primary_cause?: string | null;
};

export type MidShortSupportTargetPerformance = {
  source_count: number;
  evaluated_count: number;
  waiting_count: number;
  missing_count: number;
  closed_count: number;
  tp_count: number;
  sl_count: number;
  both_count: number;
  breakeven_count: number;
  neither_count: number;
  total_realistic_r: string | number;
  avg_realistic_r?: string | number | null;
  median_realistic_r?: string | number | null;
  max_drawdown_r: string | number;
  tp_share_pct_closed?: string | number | null;
  sl_share_pct_closed?: string | number | null;
  target_rr_q1?: string | number | null;
  target_rr_median?: string | number | null;
  target_rr_q3?: string | number | null;
  top_symbol?: string | null;
  top_symbol_count: number;
  top_symbol_share_pct?: string | number | null;
};

export type MidShortSupportTargetVariantRow = {
  config_id: string;
  label: string;
  target_method: string;
  all: MidShortSupportTargetPerformance;
  train: MidShortSupportTargetPerformance;
  validation: MidShortSupportTargetPerformance;
  train_avg_r_delta_vs_control?: string | number | null;
  validation_avg_r_delta_vs_control?: string | number | null;
  validation_total_r_delta_vs_control?: string | number | null;
  validation_drawdown_delta_vs_control?: string | number | null;
  validation_sl_share_delta_vs_control?: string | number | null;
  verdict: string;
};

export type MidShortSupportTargetResult = {
  status: string;
  target?: string | number | null;
  target_rr?: string | number | null;
  realistic_r?: string | number | null;
  result_time_utc?: string | null;
  mfe_r?: string | number | null;
  mae_r?: string | number | null;
  support_buffer_price?: string | number | null;
};

export type MidShortSupportTargetCase = {
  signal_id: string;
  symbol: string;
  signal_timestamp: string;
  signal_time_wib?: string | null;
  entry?: string | number | null;
  stop_loss?: string | number | null;
  risk?: string | number | null;
  support_price_proxy?: string | number | null;
  support_method?: string | null;
  support_distance_r?: string | number | null;
  control: MidShortSupportTargetResult;
  fixed_0_75r: MidShortSupportTargetResult;
  support_touch: MidShortSupportTargetResult;
  support_cost_buffer: MidShortSupportTargetResult;
};

export type MidShortEntryConfirmationPerformance = {
  source_count: number;
  entered_count: number;
  filtered_count: number;
  missing_confirmation_count: number;
  waiting_count: number;
  evaluated_count: number;
  closed_count: number;
  tp_count: number;
  sl_count: number;
  both_count: number;
  neither_count: number;
  total_realistic_r: string | number;
  avg_realistic_r?: string | number | null;
  median_realistic_r?: string | number | null;
  max_drawdown_r: string | number;
  sample_retention_pct?: string | number | null;
  tp_share_pct_closed?: string | number | null;
  sl_share_pct_closed?: string | number | null;
  top_symbol?: string | null;
  top_symbol_count: number;
  top_symbol_share_pct?: string | number | null;
};

export type MidShortEntryConfirmationTradeoff = {
  lost_tp_count: number;
  avoided_sl_count: number;
  retained_tp_count: number;
  tp_to_sl_count: number;
  sl_to_tp_count: number;
  retained_sl_count: number;
};

export type MidShortEntryConfirmationVariant = {
  config_id: string;
  label: string;
  definition: string;
  all: MidShortEntryConfirmationPerformance;
  train: MidShortEntryConfirmationPerformance;
  validation: MidShortEntryConfirmationPerformance;
  tradeoff_vs_control: {
    all: MidShortEntryConfirmationTradeoff;
    train: MidShortEntryConfirmationTradeoff;
    validation: MidShortEntryConfirmationTradeoff;
  };
  train_avg_r_delta_vs_control?: string | number | null;
  validation_avg_r_delta_vs_control?: string | number | null;
  validation_total_r_delta_vs_control?: string | number | null;
  validation_drawdown_delta_vs_control?: string | number | null;
  verdict: string;
};

export type MidShortEntryConfirmationResult = {
  status: string;
  entered: boolean;
  gate_reason: string;
  entry_time_utc?: string | null;
  entry_time_wib?: string | null;
  entry?: string | number | null;
  stop?: string | number | null;
  target?: string | number | null;
  realistic_r?: string | number | null;
  result_time_utc?: string | null;
  mfe_r?: string | number | null;
  mae_r?: string | number | null;
};

export type MidShortEntryConfirmationCase = {
  signal_id: string;
  symbol: string;
  signal_timestamp: string;
  signal_time_wib?: string | null;
  logged_result_status: string;
  failure_primary_cause?: string | null;
  original_entry?: string | number | null;
  original_stop?: string | number | null;
  original_target?: string | number | null;
  original_risk?: string | number | null;
  original_rr?: string | number | null;
  confirmation_time_utc?: string | null;
  confirmation_time_wib?: string | null;
  confirmation_open?: string | number | null;
  confirmation_high?: string | number | null;
  confirmation_low?: string | number | null;
  confirmation_close?: string | number | null;
  confirmation_return_pct?: string | number | null;
  confirmation_return_bucket: string;
  confirmation_taker_sell_ratio?: string | number | null;
  results: Record<string, MidShortEntryConfirmationResult>;
};

export type MidShortEntryConfirmationResponse = {
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
  study_id: string;
  study_scope: string;
  method: string;
  evaluation_horizon: string;
  definitions: Record<string, string>;
  latest_evaluation_candle_time?: string | null;
  skipped_by_position_lock: Record<string, number>;
  summary: {
    source_count: number;
    train_count: number;
    validation_count: number;
    validation_cutoff_utc?: string | null;
    confirmation_available_count: number;
    immediate_reversal_count: number;
    direction_confirmed_count: number;
    best_validation_config_id?: string | null;
    best_validation_avg_realistic_r?: string | number | null;
    best_validation_total_realistic_r?: string | number | null;
    best_validation_avoided_sl_count: number;
    best_validation_lost_tp_count: number;
    verdict: string;
    recommended_action: string;
  };
  control: {
    all: MidShortEntryConfirmationPerformance;
    train: MidShortEntryConfirmationPerformance;
    validation: MidShortEntryConfirmationPerformance;
  };
  variant_rows: MidShortEntryConfirmationVariant[];
  confirmation_bucket_rows: Array<{
    bucket: string;
    sample_count: number;
    wrong_direction_1h_count: number;
    logged_tp_count: number;
    logged_sl_count: number;
    control_4h_tp_count: number;
    control_4h_sl_count: number;
    control_4h_neither_count: number;
    control_4h_avg_realistic_r?: string | number | null;
    read: string;
  }>;
  case_rows: MidShortEntryConfirmationCase[];
  limitations: string[];
  guardrails: string[];
};

export type MidShortStructureZone = {
  center: string | number;
  lower: string | number;
  upper: string | number;
  touch_count: number;
  support_touch_count: number;
  resistance_touch_count: number;
  origin_role: string;
  latest_pivot_kind: string;
  first_touch_time: string;
  last_touch_time: string;
};

export type MidShortStructureFixedPerf = {
  source_count: number;
  source_closed_count: number;
  entered_count: number;
  entered_closed_count: number;
  filtered_no_entry_count: number;
  retention_pct?: string | number | null;
  tp_retained_count: number;
  tp_lost_count: number;
  sl_retained_count: number;
  sl_avoided_count: number;
  both_retained_count: number;
  fixed_total_realistic_r: string | number;
  fixed_avg_realistic_r?: string | number | null;
  fixed_median_realistic_r?: string | number | null;
  fixed_max_drawdown_r: string | number;
  baseline_total_realistic_r: string | number;
  baseline_avg_realistic_r?: string | number | null;
  baseline_max_drawdown_r?: string | number | null;
  fixed_total_r_delta_vs_baseline: string | number;
  fixed_avg_r_delta_vs_baseline?: string | number | null;
  top_symbol?: string | null;
  top_symbol_count: number;
  top_symbol_share_pct?: string | number | null;
};

export type MidShortStructureGateRow = {
  gate_id: string;
  label: string;
  allowed_states: string[];
  all: MidShortStructureFixedPerf;
  train: MidShortStructureFixedPerf;
  validation: MidShortStructureFixedPerf;
  selected_performance: Record<string, OneHourWalkForwardPerf>;
  verdict: string;
};

export type MidShortStructureStateRow = {
  bucket: string;
  all: OneHourWalkForwardPerf;
  train: OneHourWalkForwardPerf;
  validation: OneHourWalkForwardPerf;
};

export type MidShortStructureConfigRow = {
  config_id: string;
  label: string;
  lookback_hours: number;
  pivot_span: number;
  zone_half_width_atr: string | number;
  min_touches: number;
  zone_available_count: number;
  not_conflicted_gate: MidShortStructureGateRow;
};

export type MidShortStructureCase = {
  signal_id: string;
  symbol: string;
  signal_timestamp: string;
  signal_time_wib?: string | null;
  entry?: string | number | null;
  stop_loss?: string | number | null;
  take_profit?: string | number | null;
  result_status: string;
  realistic_realized_r?: string | number | null;
  structure_state: string;
  structure_reason: string;
  atr_1h_at_signal?: string | number | null;
  one_hour_history_count: number;
  zone_count_1h: number;
  nearest_support?: MidShortStructureZone | null;
  nearest_resistance?: MidShortStructureZone | null;
  nearest_support_distance_atr?: string | number | null;
  nearest_resistance_distance_atr?: string | number | null;
  state_zone?: MidShortStructureZone | null;
  four_hour_confluence_status: string;
  four_hour_confluence_reason: string;
  nearest_4h_zone?: MidShortStructureZone | null;
  taker_sell_ratio?: string | number | null;
  detail_href: string;
};

export type MidShortStructureZoneResponse = {
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
    signal_id?: string | null;
  };
  read_only: boolean;
  not_live_signal: boolean;
  not_execution_instruction: boolean;
  study_id: string;
  method: string;
  definitions: Record<string, unknown>;
  summary: {
    source_count: number;
    train_count: number;
    validation_count: number;
    validation_cutoff_utc?: string | null;
    zone_available_count: number;
    four_hour_context_available_count: number;
    primary_config_id: string;
    train_selected_config_id?: string | null;
    train_selected_validation_avg_r_delta?: string | number | null;
    train_selected_validation_sl_avoided: number;
    train_selected_validation_tp_lost: number;
    verdict: string;
    recommended_action: string;
  };
  cohort_rows: Array<{
    cohort_id: string;
    performance: OneHourWalkForwardPerf;
    state_counts: Record<string, number>;
  }>;
  config_rows: MidShortStructureConfigRow[];
  state_rows: MidShortStructureStateRow[];
  gate_rows: MidShortStructureGateRow[];
  four_hour_confluence_rows: MidShortStructureStateRow[];
  case_rows: MidShortStructureCase[];
  selected_case?: MidShortStructureCase | null;
  selected_chart?: SignalChartPayload | null;
  limitations: string[];
  guardrails: string[];
};

export type MidShortV21StructureVariant = {
  variant_id: string;
  label: string;
  selection_rule: string;
  all: MidShortStructureFixedPerf;
  train: MidShortStructureFixedPerf;
  validation: MidShortStructureFixedPerf;
  selected_performance: Record<string, OneHourWalkForwardPerf>;
  selected_state_counts: Record<string, number>;
  selected_target_path_counts: Record<string, number>;
  verdict: string;
};

export type MidShortV21StructureCase = MidShortStructureCase & {
  target_path_status: string;
  target_path_reason: string;
  target_path_support_center?: string | number | null;
  support_clearance_to_target_r?: string | number | null;
  primary_conflict: boolean;
  variant_membership: Record<string, boolean>;
};

export type MidShortV21StructureInteractionResponse = {
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
  study_id: string;
  method: string;
  definitions: Record<string, unknown>;
  summary: {
    fixed_cohort_count: number;
    fixed_cohort_closed_count: number;
    train_count: number;
    validation_count: number;
    validation_closed_count: number;
    validation_cutoff_utc?: string | null;
    zone_available_count: number;
    zone_unavailable_count: number;
    primary_conflict_count: number;
    target_path_blocked_count: number;
    four_hour_context_available_count: number;
    open_count: number;
    waiting_count: number;
    readiness_target_closed: number;
    readiness_status: string;
    best_validation_variant_id?: string | null;
    best_validation_verdict?: string | null;
    study_verdict: string;
    recommended_action: string;
  };
  baseline: Record<string, OneHourWalkForwardPerf>;
  variant_rows: MidShortV21StructureVariant[];
  state_rows: MidShortStructureStateRow[];
  target_path_rows: MidShortStructureStateRow[];
  four_hour_context_rows: MidShortStructureStateRow[];
  case_rows: MidShortV21StructureCase[];
  research_answers: Record<string, string>;
  limitations: string[];
  guardrails: string[];
};

export type MidShortV21ExitPerformance = {
  source_count: number;
  evaluated_count: number;
  waiting_count: number;
  missing_count: number;
  closed_count: number;
  tp_count: number;
  sl_count: number;
  both_count: number;
  neither_count: number;
  total_realistic_r: string | number;
  avg_realistic_r?: string | number | null;
  median_realistic_r?: string | number | null;
  max_drawdown_r: string | number;
  tp_share_pct_closed?: string | number | null;
  loss_share_pct_closed?: string | number | null;
  target_rr_q1?: string | number | null;
  target_rr_median?: string | number | null;
  target_rr_q3?: string | number | null;
  stop_multiple_q1?: string | number | null;
  stop_multiple_median?: string | number | null;
  stop_multiple_q3?: string | number | null;
  geometry_adjusted_count: number;
  geometry_fallback_count: number;
  geometry_status_counts: Record<string, number>;
  top_symbol?: string | null;
  top_symbol_count: number;
  top_symbol_share_pct?: string | number | null;
  total_realistic_r_delta_vs_control?: string | number | null;
  avg_realistic_r_delta_vs_control?: string | number | null;
  max_drawdown_delta_vs_control?: string | number | null;
  tp_lost_count: number;
  tp_gained_count: number;
  sl_avoided_count: number;
  sl_added_count: number;
};

export type MidShortV21ExitVariant = {
  variant_id: string;
  label: string;
  method: string;
  all: MidShortV21ExitPerformance;
  train: MidShortV21ExitPerformance;
  validation: MidShortV21ExitPerformance;
  verdict: string;
};

export type MidShortV21PathSequence = {
  path_status: string;
  path_complete: boolean;
  terminal_candle_index?: number | null;
  terminal_time_utc?: string | null;
  mfe_r_to_terminal?: string | number | null;
  mae_r_to_terminal?: string | number | null;
  tp_candle_index?: number | null;
  sl_candle_index?: number | null;
  first_level_candle_index?: Record<string, number | null>;
  reached_0_50r_before_sl?: boolean;
  reached_1_00r_before_sl?: boolean;
  reached_1_25r_before_sl?: boolean;
  reached_1_50r_before_sl?: boolean;
  time_to_0_50r_minutes?: string | number | null;
  time_to_1_00r_minutes?: string | number | null;
  time_to_tp_minutes?: string | number | null;
  time_to_sl_minutes?: string | number | null;
};

export type MidShortV21ExitResult = {
  status: string;
  realistic_r?: string | number | null;
  target?: string | number | null;
  stop?: string | number | null;
  target_rr?: string | number | null;
  stop_risk_multiple?: string | number | null;
  geometry_status: string;
  adjusted: boolean;
};

export type MidShortV21ExitCase = MidShortV21StructureCase & {
  path_sequence: MidShortV21PathSequence;
  exit_results: Record<string, MidShortV21ExitResult>;
};

export type MidShortV21StructureExitResponse = {
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
  study_id: string;
  method: string;
  definitions: Record<string, unknown>;
  summary: {
    fixed_cohort_count: number;
    fixed_cohort_closed_count: number;
    train_count: number;
    validation_count: number;
    validation_closed_count: number;
    validation_cutoff_utc?: string | null;
    zone_available_count: number;
    path_complete_count: number;
    path_waiting_count: number;
    readiness_target_closed: number;
    readiness_status: string;
    best_validation_variant_id?: string | null;
    best_validation_verdict?: string | null;
    best_validation_avg_r_delta?: string | number | null;
    study_verdict: string;
    recommended_action: string;
  };
  control: Record<string, MidShortV21ExitPerformance>;
  variant_rows: MidShortV21ExitVariant[];
  path_summary: {
    source_count: number;
    path_complete_count: number;
    tp_first_count: number;
    sl_first_count: number;
    both_same_candle_count: number;
    neither_4h_count: number;
    waiting_4h_count: number;
    missing_context_count: number;
    sl_after_0_50r_count: number;
    sl_after_1_00r_count: number;
    sl_after_1_25r_count: number;
    sl_after_1_50r_count: number;
    tp_mae_r_median?: string | number | null;
    tp_mae_r_q3?: string | number | null;
    tp_mae_r_q90?: string | number | null;
    sl_mfe_r_median?: string | number | null;
    sl_mfe_r_q3?: string | number | null;
    sl_mfe_r_q90?: string | number | null;
    time_to_tp_minutes_median?: string | number | null;
    time_to_sl_minutes_median?: string | number | null;
  };
  case_rows: MidShortV21ExitCase[];
  research_answers: Record<string, string>;
  limitations: string[];
  guardrails: string[];
};

export type MidShortV21DynamicExitPerformance = {
  source_count: number;
  evaluated_count: number;
  waiting_count: number;
  missing_count: number;
  terminal_count: number;
  tp_count: number;
  sl_count: number;
  both_count: number;
  neither_count: number;
  early_exit_count: number;
  early_exit_positive_count: number;
  early_exit_negative_count: number;
  early_exit_nonnegative_count: number;
  total_realistic_r: string | number;
  avg_realistic_r?: string | number | null;
  median_realistic_r?: string | number | null;
  max_drawdown_r: string | number;
  status_counts: Record<string, number>;
  trigger_status_counts: Record<string, number>;
  top_symbol?: string | null;
  top_symbol_count: number;
  top_symbol_share_pct?: string | number | null;
  total_realistic_r_delta_vs_control?: string | number | null;
  avg_realistic_r_delta_vs_control?: string | number | null;
  max_drawdown_delta_vs_control?: string | number | null;
  tp_sacrificed_count: number;
  sl_avoided_count: number;
  nonloss_degraded_count: number;
  improved_row_count: number;
  degraded_row_count: number;
  r_saved_from_control_losses: string | number;
  r_sacrificed_from_control_tps: string | number;
};

export type MidShortV21DynamicExitVariant = {
  variant_id: string;
  label: string;
  method: string;
  all: MidShortV21DynamicExitPerformance;
  train: MidShortV21DynamicExitPerformance;
  validation: MidShortV21DynamicExitPerformance;
  verdict: string;
};

export type MidShortV21DynamicExitResult = {
  status: string;
  realistic_r?: string | number | null;
  dynamic_action_taken: boolean;
  trigger_status?: string | null;
  trigger_reason?: string | null;
  trigger_time_utc?: string | null;
  fill_time_utc?: string | null;
  fill_price?: string | number | null;
  fill_source_interval?: string | null;
  cumulative_mfe_r?: string | number | null;
  control_status?: string | null;
  control_realistic_r?: string | number | null;
};

export type MidShortV21DynamicExitCase = MidShortV21StructureCase & {
  path_sequence: MidShortV21PathSequence;
  dynamic_exit_results: Record<string, MidShortV21DynamicExitResult>;
};

export type MidShortV21DynamicExitResponse = {
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
  study_id: string;
  method: string;
  definitions: Record<string, string>;
  summary: {
    fixed_cohort_count: number;
    fixed_cohort_closed_count: number;
    train_count: number;
    validation_count: number;
    validation_closed_count: number;
    validation_cutoff_utc?: string | null;
    zone_available_count: number;
    blocking_support_count: number;
    first_reclaim_trigger_count: number;
    confirmed_reversal_trigger_count: number;
    reclaim_after_0_50r_trigger_count: number;
    readiness_target_closed: number;
    readiness_status: string;
    best_validation_variant_id?: string | null;
    best_validation_verdict?: string | null;
    best_validation_avg_r_delta?: string | number | null;
    study_verdict: string;
    recommended_action: string;
  };
  control: Record<string, MidShortV21DynamicExitPerformance>;
  variant_rows: MidShortV21DynamicExitVariant[];
  case_rows: MidShortV21DynamicExitCase[];
  research_answers: Record<string, string>;
  limitations: string[];
  guardrails: string[];
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
    base_filter: string;
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
  base_filter: {
    filter_id: string;
    label: string;
    expression: string;
  };
  latest_evaluation_candle_time?: string | null;
  latest_futures_15m_close_time?: string | null;
  skipped_by_position_lock: Record<string, number>;
  summary: {
    source_before_base_filter_count: number;
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
    classified_sl_count: number;
    unresolved_sl_count: number;
    dominant_failure_cause?: string | null;
    dominant_failure_count: number;
    dominant_failure_share_pct?: string | number | null;
    legacy_path_read: string;
    read: string;
  };
  baseline: OneHourWalkForwardPerf;
  sl_failure_cause_summary: {
    sl_count: number;
    classified_sl_count: number;
    unresolved_sl_count: number;
    classification_coverage_pct?: string | number | null;
    dominant_failure_cause?: string | null;
    dominant_failure_count: number;
    dominant_failure_share_pct?: string | number | null;
    cause_count: number;
    method: string;
  };
  sl_failure_cause_rows: MidShortSlFailureCauseRow[];
  structure_clearance_study: {
    study_id: string;
    read_only: boolean;
    not_live_signal: boolean;
    not_execution_instruction: boolean;
    method: string;
    definition: {
      structure_clear: string;
      structure_blocked: string;
      structure_unavailable: string;
      live_effect: string;
    };
    summary: {
      source_count: number;
      context_available_count: number;
      structure_clear_count: number;
      structure_blocked_count: number;
      structure_unavailable_count: number;
      clear_validation_closed_count: number;
      blocked_validation_closed_count: number;
      validation_cutoff_utc?: string | null;
      verdict: string;
      recommended_action: string;
    };
    baseline: {
      all: OneHourWalkForwardPerf;
      train: OneHourWalkForwardPerf;
      validation: OneHourWalkForwardPerf;
    };
    status_rows: MidShortStructureClearanceStatusRow[];
    exit_variant_rows: MidShortStructureExitVariantRow[];
    blocked_case_rows: MidShortStructureBlockedCase[];
    limitations: string[];
  };
  support_target_study: {
    study_id: string;
    read_only: boolean;
    not_live_signal: boolean;
    not_execution_instruction: boolean;
    evaluation_horizon: string;
    method: string;
    target_definitions: Record<string, string>;
    summary: {
      source_count: number;
      structure_blocked_count: number;
      blocked_train_count: number;
      blocked_validation_count: number;
      validation_cutoff_utc?: string | null;
      control_validation_evaluated_count: number;
      control_validation_waiting_count: number;
      best_validation_config_id?: string | null;
      best_validation_avg_realistic_r?: string | number | null;
      best_validation_total_realistic_r?: string | number | null;
      verdict: string;
      recommended_action: string;
    };
    control: {
      all: MidShortSupportTargetPerformance;
      train: MidShortSupportTargetPerformance;
      validation: MidShortSupportTargetPerformance;
    };
    variant_rows: MidShortSupportTargetVariantRow[];
    case_rows: MidShortSupportTargetCase[];
    limitations: string[];
  };
  target_distance_study: {
    study_id: string;
    read_only: boolean;
    method: string;
    summary: {
      target_too_far_count: number;
      tp_control_count: number;
      other_sl_count: number;
      unique_symbol_count: number;
      dominant_hypothesis: string;
      dominant_hypothesis_count: number;
      dominant_hypothesis_share_pct?: string | number | null;
      complete_context_count: number;
      verdict: string;
    };
    data_derived_thresholds: Record<string, {
      field: string;
      percentile: string | number;
      value?: string | number | null;
      available_count: number;
      source: string;
    }>;
    hypothesis_rows: Array<{
      hypothesis: string;
      primary_count: number;
      primary_share_pct?: string | number | null;
      multi_label_count: number;
      multi_label_share_pct?: string | number | null;
      read: string;
    }>;
    metric_comparison_rows: MidShortTargetDistanceMetricRow[];
    counterfactual_rows: MidShortCounterfactualRow[];
    case_rows: MidShortTargetDistanceCase[];
    limitations: string[];
  };
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

export type MidLongLab62Response = {
  generated_at_utc?: string | null;
  lab: string;
  study_scope: string;
  read_only: boolean;
  not_live_signal: boolean;
  not_execution_instruction: boolean;
  closed_only_snapshot: boolean;
  snapshot_coverage: {
    source_1h_rows: number;
    source_1h_total: number;
    mid_long_1h_rows: number;
    is_truncated: boolean;
  };
  quality: SignalQualityLabResponse;
  filter_study: SignalFilterStudyResponse;
  snapshot?: {
    source?: string | null;
    filename?: string | null;
    generated_at_utc?: string | null;
  } | null;
  guardrails: string[];
};

export type MidLongLab63Metrics = {
  source_signal_count: number;
  evaluated_count: number;
  skipped_count: number;
  skipped_counts: Record<string, number>;
  closed_count: number;
  tp_count: number;
  sl_count: number;
  both_hit_count: number;
  timeout_count: number;
  positive_timeout_count: number;
  negative_timeout_count: number;
  open_count: number;
  waiting_count: number;
  incomplete_count: number;
  missing_atr_count: number;
  ideal_total_r_closed?: string | number | null;
  realistic_total_r_closed?: string | number | null;
  realistic_avg_r_closed?: string | number | null;
  realistic_median_r_closed?: string | number | null;
  realistic_open_r?: string | number | null;
  realistic_total_r_with_open?: string | number | null;
  realism_penalty_r_closed?: string | number | null;
  max_realistic_drawdown_r?: string | number | null;
  spread_missing_count: number;
  top_symbol?: string | null;
  top_symbol_count: number;
  top_symbol_share_pct?: string | number | null;
  realistic_total_r_delta_vs_4h?: string | number | null;
  realistic_avg_r_delta_vs_4h?: string | number | null;
};

export type MidLongLab63Policy = {
  policy_id: string;
  policy_label: string;
  timeout_minutes?: number | null;
  atr_multiplier: string | number;
  reward_risk: string | number;
  all: MidLongLab63Metrics;
  train: MidLongLab63Metrics;
  validation: MidLongLab63Metrics;
  latest_results: Array<Record<string, unknown>>;
  verdict: string;
};

export type MidLongLab63Response = {
  generated_at_utc?: string | null;
  lab: string;
  study_scope: string;
  read_only: boolean;
  not_live_signal: boolean;
  not_execution_instruction: boolean;
  filters: {
    epoch: string;
    stage: string;
    timeframe: string;
    include_watch_only: boolean;
    position_lock: boolean;
    min_validation_sample: number;
    limit: number;
  };
  geometry: {
    atr_source: string;
    atr_multiplier: string | number;
    reward_risk: string | number;
    entry_source: string;
    forward_source: string;
    realistic_model: string;
  };
  split: {
    method: string;
    source_signal_count: number;
    train_source_count: number;
    validation_source_count: number;
  };
  latest_futures_15m_close_time?: string | null;
  reference_policy: string;
  best_observed_policy?: MidLongLab63Policy | null;
  policies: MidLongLab63Policy[];
  guardrails: string[];
};

export type MidLongLab64FieldStats = {
  source_count: number;
  available_count: number;
  missing_count: number;
  available_pct?: string | number | null;
  tp_count: number;
  sl_count: number;
  tp_median?: string | number | null;
  sl_median?: string | number | null;
  delta_tp_minus_sl?: string | number | null;
  tp_q1?: string | number | null;
  tp_q3?: string | number | null;
  sl_q1?: string | number | null;
  sl_q3?: string | number | null;
  auc_tp_above_sl?: string | number | null;
  separation_strength?: string | number | null;
};

export type MidLongLab64Field = {
  field: string;
  label: string;
  all: MidLongLab64FieldStats;
  train: MidLongLab64FieldStats;
  validation: MidLongLab64FieldStats;
  train_direction?: string | null;
  validation_direction?: string | null;
  direction_consistent?: boolean | null;
  verdict: string;
  research_read: string;
};

export type MidLongLab64Response = {
  generated_at_utc?: string | null;
  lab: string;
  study_scope: string;
  read_only: boolean;
  not_live_signal: boolean;
  not_execution_instruction: boolean;
  filters: {
    epoch: string;
    stage: string;
    timeframe: string;
    direction: string;
    include_watch_only: boolean;
    position_lock: boolean;
    min_group_sample: number;
    limit: number;
  };
  policy: {
    policy_id: string;
    timeout_minutes: number;
    atr_source: string;
    atr_multiplier: string | number;
    reward_risk: string | number;
    realistic_model: string;
  };
  split: {
    method: string;
    source_signal_count: number;
    train_source_count: number;
    validation_source_count: number;
  };
  latest_futures_15m_close_time?: string | null;
  outcome_summary: {
    all: MidLongLab63Metrics;
    train: MidLongLab63Metrics;
    validation: MidLongLab63Metrics;
  };
  field_summary: {
    field_count: number;
    stable_field_count: number;
    moderate_field_count: number;
    weak_field_count: number;
    direction_flip_count: number;
    insufficient_count: number;
    no_clear_separation_count: number;
  };
  verdict: string;
  best_observed_field?: MidLongLab64Field | null;
  field_rows: MidLongLab64Field[];
  latest_tp_examples: Array<Record<string, unknown>>;
  latest_sl_examples: Array<Record<string, unknown>>;
  guardrails: string[];
};

export type MidLongLab65FailureStats = {
  count: number;
  share_pct?: string | number | null;
  total_realistic_r?: string | number | null;
  avg_realistic_r?: string | number | null;
  median_realistic_r?: string | number | null;
  median_mfe_before_result_r?: string | number | null;
  median_mae_before_result_r?: string | number | null;
  median_first_15m_close_r?: string | number | null;
  median_first_30m_close_r?: string | number | null;
  median_time_to_result_minutes?: string | number | null;
  target_after_stop_count?: number;
  structure_conflict_count?: number;
  regime_conflict_count?: number;
  entry_extension_high_count?: number;
  top_symbol?: string | null;
  top_symbol_count?: number;
  top_symbol_share_pct?: string | number | null;
  evidence_medians?: Record<string, string | number | null>;
};

export type MidLongLab65Cause = {
  cause: string;
  label: string;
  definition: string;
  research_action: string;
  all: MidLongLab65FailureStats;
  train: MidLongLab65FailureStats;
  validation: MidLongLab65FailureStats;
};

export type MidLongLab65Example = {
  signal_id: string;
  symbol: string;
  signal_timestamp?: string | null;
  result_status: string;
  result_time_utc?: string | null;
  realistic_realized_r?: string | number | null;
  failure_primary_cause: string;
  failure_contributors: string[];
  result_candle_index?: number | null;
  time_to_result_minutes?: string | number | null;
  mfe_before_result_r?: string | number | null;
  mae_before_result_r?: string | number | null;
  first_15m_close_r?: string | number | null;
  after_sl_would_hit_target_within_4h?: boolean;
  structure_status?: string | null;
  regime_conflict?: boolean;
  evidence?: Record<string, string | number | null>;
};

export type MidLongLab65Response = {
  generated_at_utc?: string | null;
  lab: string;
  study_scope: string;
  read_only: boolean;
  not_live_signal: boolean;
  not_execution_instruction: boolean;
  filters: {
    epoch: string;
    stage: string;
    timeframe: string;
    direction: string;
    include_watch_only: boolean;
    position_lock: boolean;
    min_failure_sample: number;
    limit: number;
  };
  policy: {
    policy_id: string;
    timeout_minutes: number;
    atr_source: string;
    atr_multiplier: string | number;
    reward_risk: string | number;
    forward_source: string;
    realistic_model: string;
  };
  split: {
    method: string;
    source_signal_count: number;
    train_source_count: number;
    validation_source_count: number;
  };
  latest_futures_15m_close_time?: string | null;
  outcome_summary: {
    all: MidLongLab63Metrics;
    train: MidLongLab63Metrics;
    validation: MidLongLab63Metrics;
  };
  failure_summary: {
    all: MidLongLab65FailureStats;
    train: MidLongLab65FailureStats;
    validation: MidLongLab65FailureStats;
    dominant_cause?: string | null;
    dominant_cause_share_pct?: string | number | null;
  };
  train_thresholds: {
    method: string;
    values: Record<string, string | number | null>;
  };
  cause_rows: MidLongLab65Cause[];
  contributor_rows: Array<{
    contributor: string;
    all_count: number;
    all_share_pct?: string | number | null;
    train_count: number;
    validation_count: number;
  }>;
  outcome_path_rows: Array<Record<string, string | number | null>>;
  latest_failure_examples: MidLongLab65Example[];
  verdict: string;
  next_research_targets: Array<Record<string, unknown>>;
  guardrails: string[];
};

export type MidLongLab66Availability = {
  source_count: number;
  available_count: number;
  missing_count: number;
  matched_count: number;
  available_pct?: string | number | null;
  retention_pct?: string | number | null;
};

export type MidLongLab66Delta = {
  realistic_total_r?: string | number | null;
  realistic_avg_r?: string | number | null;
  realistic_median_r?: string | number | null;
  max_drawdown_r?: string | number | null;
};

export type MidLongLab66FilterRow = {
  filter_id: string;
  label: string;
  expression: string;
  component_ids: string[];
  fields: string[];
  threshold_source: string;
  availability: {
    all: MidLongLab66Availability;
    train: MidLongLab66Availability;
    validation: MidLongLab66Availability;
  };
  all_available_signal_count: number;
  all: MidLongLab63Metrics;
  train: MidLongLab63Metrics;
  validation: MidLongLab63Metrics;
  deltas: {
    all: MidLongLab66Delta;
    train: MidLongLab66Delta;
    validation: MidLongLab66Delta;
  };
  verdict: string;
  risk_notes: string[];
};

export type MidLongLab66Example = {
  signal_id: string;
  symbol: string;
  signal_timestamp?: string | null;
  result_status: string;
  realistic_realized_r?: string | number | null;
  structure_status?: string | null;
  regime_conflict?: boolean;
  evidence: Record<string, string | number | null>;
};

export type MidLongLab66Response = {
  generated_at_utc?: string | null;
  lab: string;
  study_scope: string;
  read_only: boolean;
  not_live_signal: boolean;
  not_execution_instruction: boolean;
  filters: {
    epoch: string;
    stage: string;
    timeframe: string;
    direction: string;
    include_watch_only: boolean;
    position_lock: boolean;
    min_validation_sample: number;
    limit: number;
  };
  policy: {
    policy_id: string;
    timeout_minutes: number;
    atr_source: string;
    atr_multiplier: string | number;
    reward_risk: string | number;
    realistic_model: string;
  };
  split: {
    method: string;
    source_signal_count: number;
    train_source_count: number;
    validation_source_count: number;
    evaluated_fixed_cohort_count: number;
  };
  latest_futures_15m_close_time?: string | null;
  baseline: {
    all: MidLongLab63Metrics;
    train: MidLongLab63Metrics;
    validation: MidLongLab63Metrics;
  };
  threshold_discovery: {
    method: string;
    atom_count: number;
    combination_atom_count: number;
    field_rows: Array<{
      field: string;
      label: string;
      train_available_count: number;
      train_positive_count: number;
      train_nonpositive_count: number;
      positive_median?: string | number | null;
      nonpositive_median?: string | number | null;
      direction?: string | null;
      q25?: string | number | null;
      q50?: string | number | null;
      q75?: string | number | null;
    }>;
  };
  summary: {
    single_filter_count: number;
    combination_count: number;
    candidate_count: number;
    promising_count: number;
    damage_reduction_count: number;
    overfit_count: number;
    verdict: string;
  };
  top_candidate?: MidLongLab66FilterRow | null;
  best_observed?: MidLongLab66FilterRow | null;
  filter_rows: MidLongLab66FilterRow[];
  candidate_rows: MidLongLab66FilterRow[];
  latest_pass_examples: MidLongLab66Example[];
  latest_fail_examples: MidLongLab66Example[];
  next_step: string;
  guardrails: string[];
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
