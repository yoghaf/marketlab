import { StatusBadge } from "@/components/StatusBadge";
import { MetricCard } from "@/components/MetricCard";
import { PageHeader } from "@/components/PageHeader";
import {
  AggregationStatus,
  CollectorRun,
  FeatureContext15m1hStatus,
  Feature1hStatus,
  Feature15mStatus,
  MarketStateAlignmentStatus,
  Outcomes15mStatus,
  Psychology15mStatus,
  RichAlignmentStatus,
  SignalCandidatesReadonly15mStatus,
  fetchJson,
  fmtTime
} from "@/lib/api";

type CollectorError = { id: number; collector_name: string; symbol?: string | null; error_type: string; message: string; created_at: string };
type Usage = { id: number; collector_name?: string | null; endpoint: string; status_code?: number | null; used_weight_1m?: number | null; created_at: string };
type CollectorResponse = {
  collectors: CollectorRun[];
  last_errors: CollectorError[];
  request_usage: { latest_used_weight_1m?: number | null; recent: Usage[] };
};
type RichFuturesResponse = {
  latest: Record<string, string | null>;
  table_counts: Record<string, number>;
  universe: {
    active_universe_count: number;
    universe_count: number;
    full_active_count: number;
    signal_eligible_count: number;
  };
  collectors: CollectorRun[];
};
type RichAlignmentResponse = RichAlignmentStatus;
type MarketStateAlignmentResponse = MarketStateAlignmentStatus;
type Feature15mResponse = Feature15mStatus;
type Feature1hResponse = Feature1hStatus;
type FeatureContextResponse = FeatureContext15m1hStatus;
type Psychology15mResponse = Psychology15mStatus;
type SignalCandidatesReadonly15mResponse = SignalCandidatesReadonly15mStatus;
type Outcomes15mResponse = Outcomes15mStatus;

const richLatestKey: Record<string, string> = {
  futures_taker_buy_sell_volume: "taker_buy_sell_latest",
  futures_global_long_short_account_ratio: "global_long_short_latest",
  futures_top_trader_position_ratio: "top_trader_position_latest",
  futures_top_trader_account_ratio: "top_trader_account_latest",
  futures_open_interest_history: "open_interest_history_latest",
  futures_funding_history: "funding_history_latest"
};

export default async function CollectorsPage() {
  const [data, rich, aggregation, richAlignment, marketStateAlignment, features15m, features1h, featureContext, psychology15m, signalCandidates, outcomes15m] = await Promise.all([
    fetchJson<CollectorResponse>("/api/collectors/status"),
    fetchJson<RichFuturesResponse>("/api/rich-futures/status"),
    fetchJson<AggregationStatus>("/api/aggregation/status"),
    fetchJson<RichAlignmentResponse>("/api/rich-alignment/status"),
    fetchJson<MarketStateAlignmentResponse>("/api/market-state-alignment/status"),
    fetchJson<Feature15mResponse>("/api/features/15m/status"),
    fetchJson<Feature1hResponse>("/api/features/1h/status"),
    fetchJson<FeatureContextResponse>("/api/features/context/15m-1h/status"),
    fetchJson<Psychology15mResponse>("/api/psychology/15m/status"),
    fetchJson<SignalCandidatesReadonly15mResponse>("/api/signal-candidates/readonly/15m/status"),
    fetchJson<Outcomes15mResponse>("/api/outcomes/15m/status")
  ]);
  return (
    <div className="space-y-5">
      <PageHeader title="Advanced" subtitle="Raw ops/debug view untuk collector, request usage, rich datasets, dan status pipeline. Halaman ini untuk investigasi teknis, bukan halaman sinyal." />
      <section className="grid gap-3 md:grid-cols-4">
        <MetricCard label="Active Universe" value={rich.universe.active_universe_count ?? rich.universe.universe_count} />
        <MetricCard label="Core Target" value={rich.universe.full_active_count} />
        <MetricCard label="Rich Target" value={rich.universe.full_active_count} />
        <MetricCard label="Signal Eligible" value={rich.universe.signal_eligible_count} />
      </section>
      <section className="overflow-x-auto border border-line bg-white">
        <h2 className="border-b border-line px-4 py-3 text-base font-semibold">OHLCV Aggregation</h2>
        <table>
          <thead>
            <tr>
              <th>Metric</th>
              <th>Value</th>
            </tr>
          </thead>
          <tbody>
            <tr><td>AGG_READY</td><td>{aggregation.ready_count || 0}</td></tr>
            <tr><td>AGG_INCOMPLETE</td><td>{aggregation.incomplete_count || 0}</td></tr>
            <tr><td>AGG_WARMUP</td><td>{aggregation.warmup_count || 0}</td></tr>
            <tr><td>AGG_STALE</td><td>{aggregation.stale_count || 0}</td></tr>
            <tr><td>AGG_MISSING_SPOT</td><td>{aggregation.missing_spot_count || 0}</td></tr>
            <tr><td>latest_15m_futures</td><td>{fmtTime(aggregation.latest_15m_futures)}</td></tr>
            <tr><td>latest_15m_spot</td><td>{fmtTime(aggregation.latest_15m_spot)}</td></tr>
            <tr><td>latest_1h_futures</td><td>{fmtTime(aggregation.latest_1h_futures)}</td></tr>
            <tr><td>latest_1h_spot</td><td>{fmtTime(aggregation.latest_1h_spot)}</td></tr>
            <tr><td>latest_4h_futures</td><td>{fmtTime(aggregation.latest_4h_futures)}</td></tr>
            <tr><td>latest_4h_spot</td><td>{fmtTime(aggregation.latest_4h_spot)}</td></tr>
            <tr><td>latest_24h_futures</td><td>{fmtTime(aggregation.latest_24h_futures)}</td></tr>
            <tr><td>latest_24h_spot</td><td>{fmtTime(aggregation.latest_24h_spot)}</td></tr>
          </tbody>
        </table>
      </section>
      <section className="overflow-x-auto border border-line bg-white">
        <h2 className="border-b border-line px-4 py-3 text-base font-semibold">Rich Futures</h2>
        <table>
          <thead>
            <tr>
              <th>Dataset</th>
              <th>Latest</th>
              <th>Rows</th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(rich.table_counts).map(([name, count]) => (
              <tr key={name}>
                <td>{name}</td>
                <td>{fmtTime(rich.latest[richLatestKey[name]])}</td>
                <td>{count}</td>
              </tr>
            ))}
            <tr>
              <td>liquidation_stream_status</td>
              <td>{rich.latest.liquidation_stream_status || "NOT_RUNNING"}</td>
              <td>-</td>
            </tr>
          </tbody>
        </table>
      </section>
      <section className="overflow-x-auto border border-line bg-white">
        <h2 className="border-b border-line px-4 py-3 text-base font-semibold">Rich 5m Alignment</h2>
        <table>
          <thead>
            <tr>
              <th>Metric</th>
              <th>Value</th>
            </tr>
          </thead>
          <tbody>
            <tr><td>ALIGNED</td><td>{richAlignment.aligned_count || 0}</td></tr>
            <tr><td>INCOMPLETE</td><td>{richAlignment.incomplete_count || 0}</td></tr>
            <tr><td>WARMUP</td><td>{richAlignment.warmup_count || 0}</td></tr>
            <tr><td>STALE</td><td>{richAlignment.stale_count || 0}</td></tr>
            <tr><td>NO_DATA</td><td>{richAlignment.no_data_count || 0}</td></tr>
            <tr><td>latest_15m</td><td>{fmtTime(richAlignment.latest_15m)}</td></tr>
            <tr><td>latest_1h</td><td>{fmtTime(richAlignment.latest_1h)}</td></tr>
            <tr><td>latest_4h</td><td>{fmtTime(richAlignment.latest_4h)}</td></tr>
            <tr><td>latest_24h</td><td>{fmtTime(richAlignment.latest_24h)}</td></tr>
          </tbody>
        </table>
      </section>
      <section className="overflow-x-auto border border-line bg-white">
        <h2 className="border-b border-line px-4 py-3 text-base font-semibold">Market State Alignment</h2>
        <table>
          <thead>
            <tr>
              <th>Metric</th>
              <th>Value</th>
            </tr>
          </thead>
          <tbody>
            <tr><td>FRESH</td><td>{marketStateAlignment.fresh_count || 0}</td></tr>
            <tr><td>STALE</td><td>{marketStateAlignment.stale_count || 0}</td></tr>
            <tr><td>MISSING</td><td>{marketStateAlignment.missing_count || 0}</td></tr>
            <tr><td>FUNDING_ALIGNED</td><td>{marketStateAlignment.funding_aligned_count || 0}</td></tr>
            <tr><td>FUNDING_CARRIED_FORWARD</td><td>{marketStateAlignment.funding_carried_forward_count || 0}</td></tr>
            <tr><td>FUNDING_STALE</td><td>{marketStateAlignment.funding_stale_count || 0}</td></tr>
            <tr><td>FUNDING_MISSING</td><td>{marketStateAlignment.funding_missing_count || 0}</td></tr>
            <tr><td>latest_15m</td><td>{fmtTime(marketStateAlignment.latest_15m)}</td></tr>
            <tr><td>latest_1h</td><td>{fmtTime(marketStateAlignment.latest_1h)}</td></tr>
            <tr><td>latest_4h</td><td>{fmtTime(marketStateAlignment.latest_4h)}</td></tr>
            <tr><td>latest_24h</td><td>{fmtTime(marketStateAlignment.latest_24h)}</td></tr>
          </tbody>
        </table>
      </section>
      <section className="overflow-x-auto border border-line bg-white">
        <h2 className="border-b border-line px-4 py-3 text-base font-semibold">Feature Builders</h2>
        <table>
          <thead>
            <tr>
              <th>Metric</th>
              <th>Value</th>
            </tr>
          </thead>
          <tbody>
            <tr><td>FEATURE_READY</td><td>{features15m.feature_ready_count || 0}</td></tr>
            <tr><td>FEATURE_PARTIAL</td><td>{features15m.feature_partial_count || 0}</td></tr>
            <tr><td>FEATURE_BLOCKED</td><td>{features15m.feature_blocked_count || 0}</td></tr>
            <tr><td>latest_feature_time</td><td>{fmtTime(features15m.latest_feature_time)}</td></tr>
            <tr><td>latest_ready_symbols_count</td><td>{features15m.latest_ready_symbols_count || 0}</td></tr>
            <tr><td>total_features</td><td>{features15m.total_features || 0}</td></tr>
            <tr><td>1h_FEATURE_READY</td><td>{features1h.feature_ready_count || 0}</td></tr>
            <tr><td>1h_FEATURE_PARTIAL</td><td>{features1h.feature_partial_count || 0}</td></tr>
            <tr><td>1h_FEATURE_BLOCKED</td><td>{features1h.feature_blocked_count || 0}</td></tr>
            <tr><td>1h_latest_feature_time</td><td>{fmtTime(features1h.latest_feature_time)}</td></tr>
            <tr><td>1h_latest_ready_symbols_count</td><td>{features1h.latest_ready_symbols_count || 0}</td></tr>
            <tr><td>1h_total_features</td><td>{features1h.total_features || 0}</td></tr>
            <tr><td>CONTEXT_READY</td><td>{featureContext.context_ready_count || 0}</td></tr>
            <tr><td>CONTEXT_PARTIAL</td><td>{featureContext.context_partial_count || 0}</td></tr>
            <tr><td>CONTEXT_BLOCKED</td><td>{featureContext.context_blocked_count || 0}</td></tr>
            <tr><td>context_latest_time</td><td>{fmtTime(featureContext.latest_context_time)}</td></tr>
            <tr><td>context_latest_symbols</td><td>{featureContext.latest_symbols_count || 0}</td></tr>
            <tr><td>context_total_rows</td><td>{featureContext.total_context_rows || 0}</td></tr>
            <tr><td>SPOT_SUPPORTING</td><td>{featureContext.spot_support_counts?.SPOT_SUPPORTING || 0}</td></tr>
            <tr><td>WEAK_SPOT_SUPPORT</td><td>{featureContext.spot_support_counts?.WEAK_SPOT_SUPPORT || 0}</td></tr>
            <tr><td>FUTURES_LED</td><td>{featureContext.spot_support_counts?.FUTURES_LED || 0}</td></tr>
            <tr><td>SPOT_MISSING</td><td>{featureContext.spot_support_counts?.SPOT_MISSING || 0}</td></tr>
            <tr><td>SPOT_UNKNOWN</td><td>{featureContext.spot_support_counts?.SPOT_UNKNOWN || 0}</td></tr>
            <tr><td>LABEL_READY</td><td>{psychology15m.label_ready_count || 0}</td></tr>
            <tr><td>LABEL_PARTIAL</td><td>{psychology15m.label_partial_count || 0}</td></tr>
            <tr><td>LABEL_BLOCKED</td><td>{psychology15m.label_blocked_count || 0}</td></tr>
            <tr><td>label_latest_time</td><td>{fmtTime(psychology15m.latest_label_time)}</td></tr>
            <tr><td>top_primary_label</td><td>{psychology15m.top_primary_labels[0]?.label || "-"}</td></tr>
            <tr><td>CLASSIFIER_READY</td><td>{signalCandidates.classifier_ready_count || 0}</td></tr>
            <tr><td>CLASSIFIER_PARTIAL</td><td>{signalCandidates.classifier_partial_count || 0}</td></tr>
            <tr><td>CLASSIFIER_BLOCKED</td><td>{signalCandidates.classifier_blocked_count || 0}</td></tr>
            <tr><td>readonly_candidate_latest_time</td><td>{fmtTime(signalCandidates.latest_candidate_time)}</td></tr>
            <tr><td>top_readonly_candidate_type</td><td>{signalCandidates.candidate_type_counts[0]?.type || "-"}</td></tr>
            <tr><td>OUTCOME_READY</td><td>{outcomes15m.outcome_status_counts.OUTCOME_READY || 0}</td></tr>
            <tr><td>OUTCOME_WAITING_DATA</td><td>{outcomes15m.outcome_status_counts.OUTCOME_WAITING_DATA || 0}</td></tr>
            <tr><td>OUTCOME_INCOMPLETE</td><td>{outcomes15m.outcome_status_counts.OUTCOME_INCOMPLETE || 0}</td></tr>
            <tr><td>OUTCOME_BLOCKED</td><td>{outcomes15m.outcome_status_counts.OUTCOME_BLOCKED || 0}</td></tr>
            <tr><td>outcome_latest_update</td><td>{fmtTime(outcomes15m.latest_outcome_update)}</td></tr>
            <tr><td>outcome_15m_ready</td><td>{outcomes15m.horizon_15m_status_counts.OUTCOME_READY || 0}</td></tr>
            <tr><td>outcome_30m_ready</td><td>{outcomes15m.horizon_30m_status_counts.OUTCOME_READY || 0}</td></tr>
            <tr><td>outcome_1h_ready</td><td>{outcomes15m.horizon_1h_status_counts.OUTCOME_READY || 0}</td></tr>
            <tr><td>outcome_4h_ready</td><td>{outcomes15m.horizon_4h_status_counts.OUTCOME_READY || 0}</td></tr>
          </tbody>
        </table>
      </section>
      <section className="overflow-x-auto border border-line bg-white">
        <table>
          <thead>
            <tr>
              <th>Collector</th>
              <th>Status</th>
              <th>Started</th>
              <th>Finished</th>
              <th>Duration</th>
              <th>Requests</th>
              <th>Inserted</th>
              <th>Updated</th>
              <th>Errors</th>
            </tr>
          </thead>
          <tbody>
            {data.collectors.map((run) => (
              <tr key={run.id}>
                <td>{run.collector_name}</td>
                <td><StatusBadge value={run.status} /></td>
                <td>{fmtTime(run.started_at)}</td>
                <td>{fmtTime(run.finished_at)}</td>
                <td>{run.duration ?? "-"}s</td>
                <td>{run.request_count}</td>
                <td>{run.rows_inserted ?? 0}</td>
                <td>{run.rows_updated ?? run.updated_count}</td>
                <td>{run.errors_count ?? run.error_count}</td>
              </tr>
            ))}
            {!data.collectors.length && (
              <tr>
                <td colSpan={9}>No collector runs yet.</td>
              </tr>
            )}
          </tbody>
        </table>
      </section>
      <section className="grid gap-4 lg:grid-cols-2">
        <div className="border border-line bg-white">
          <h2 className="border-b border-line px-4 py-3 text-base font-semibold">Last Errors</h2>
          <div className="max-h-96 overflow-auto">
            {data.last_errors.map((error) => (
              <div key={error.id} className="border-b border-line p-4 text-sm last:border-b-0">
                <div className="font-semibold">{error.collector_name} {error.symbol || ""}</div>
                <div className="text-slate-600">{fmtTime(error.created_at)} {error.error_type}</div>
                <div>{error.message}</div>
              </div>
            ))}
            {!data.last_errors.length && <div className="p-4 text-sm">No collector errors recorded.</div>}
          </div>
        </div>
        <div className="border border-line bg-white">
          <h2 className="border-b border-line px-4 py-3 text-base font-semibold">Request Usage</h2>
          <div className="max-h-96 overflow-auto">
            {data.request_usage.recent.map((row) => (
              <div key={row.id} className="grid grid-cols-[1fr_auto] gap-3 border-b border-line p-4 text-sm last:border-b-0">
                <div>
                  <div className="font-semibold">{row.collector_name || "-"} {row.endpoint}</div>
                  <div className="text-slate-600">{fmtTime(row.created_at)} status {row.status_code || "-"}</div>
                </div>
                <div className="font-semibold">{row.used_weight_1m ?? "-"}</div>
              </div>
            ))}
            {!data.request_usage.recent.length && <div className="p-4 text-sm">No request usage recorded.</div>}
          </div>
        </div>
      </section>
    </div>
  );
}
