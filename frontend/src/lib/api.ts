const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "http://127.0.0.1:8000";

export async function fetchJson<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, { cache: "no-store" });
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
    timeZone: "UTC"
  }).format(new Date(value));
}

export function fmtNumber(value?: string | number | null): string {
  if (value === null || value === undefined || value === "") return "-";
  const num = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(num)) return String(value);
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 }).format(num);
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
