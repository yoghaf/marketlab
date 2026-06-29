import Link from "next/link";

import { Metric } from "@/components/Metric";
import { StatusBadge } from "@/components/StatusBadge";
import {
  AggregationStatus,
  FeatureContext15m1hStatus,
  Feature1hStatus,
  Feature15mStatus,
  HealthItem,
  MarketStateAlignmentStatus,
  Outcomes15mStatus,
  Psychology15mStatus,
  RichAlignmentStatus,
  SignalCandidatesReadonly15mStatus,
  fetchJson,
  fmtTime
} from "@/lib/api";

type HealthResponse = {
  counts: Record<string, number>;
  rich_counts: Record<string, number>;
  aggregation: {
    latest: Record<string, string | null>;
    counts: AggregationStatus;
    tables: Record<string, Record<string, number>>;
  };
  rich_alignment: {
    latest: Record<string, string | null>;
    counts: RichAlignmentStatus;
    tables: Record<string, Record<string, number>>;
  };
  market_state_alignment: {
    latest: Record<string, string | null>;
    counts: MarketStateAlignmentStatus;
    tables: Record<string, Record<string, Record<string, number>>>;
  };
  features_15m: Feature15mStatus;
  features_1h: Feature1hStatus;
  feature_context_15m_1h: FeatureContext15m1hStatus;
  psychology_15m: Psychology15mStatus;
  signal_candidates_readonly_15m: SignalCandidatesReadonly15mStatus;
  outcomes_15m: Outcomes15mStatus;
  universe: {
    active_universe_count: number;
    universe_count: number;
    full_active_count: number;
    signal_eligible_count: number;
  };
  latest: Record<string, string | null>;
  items: HealthItem[];
};

export default async function DataHealthPage() {
  const data = await fetchJson<HealthResponse>("/api/data-health");
  return (
    <div className="space-y-5">
      <h1 className="text-2xl font-bold tracking-normal">Data Health</h1>
      <section className="grid gap-3 md:grid-cols-4">
        <Metric label="Active Universe" value={data.universe.active_universe_count ?? data.universe.universe_count} />
        <Metric label="Full Active" value={data.universe.full_active_count} />
        <Metric label="Signal Eligible" value={data.universe.signal_eligible_count} />
        <Metric label="Not Active" value={data.counts.NOT_ACTIVE || 0} />
      </section>
      <section className="grid gap-3 md:grid-cols-4 lg:grid-cols-7">
        <Metric label="Ready" value={data.counts.READY || 0} />
        <Metric label="Warmup" value={data.counts.WARMUP || 0} />
        <Metric label="Stale" value={data.counts.STALE || 0} />
        <Metric label="Missing Spot" value={data.counts.MISSING_SPOT || 0} />
        <Metric label="Missing Futures" value={data.counts.MISSING_FUTURES || 0} />
        <Metric label="Missing OI" value={data.counts.MISSING_OI || 0} />
        <Metric label="Missing Funding" value={data.counts.MISSING_FUNDING || 0} />
      </section>
      <section className="grid gap-3 md:grid-cols-4">
        <Metric label="Rich Ready" value={data.rich_counts.RICH_READY || 0} />
        <Metric label="Rich Warmup" value={data.rich_counts.RICH_WARMUP || 0} />
        <Metric label="Rich Stale" value={data.rich_counts.RICH_STALE || 0} />
        <Metric label="Rich Missing" value={data.rich_counts.RICH_MISSING || 0} />
      </section>
      <section className="grid gap-3 md:grid-cols-5">
        <Metric label="Agg Ready" value={data.aggregation.counts.ready_count || 0} />
        <Metric label="Agg Incomplete" value={data.aggregation.counts.incomplete_count || 0} />
        <Metric label="Agg Warmup" value={data.aggregation.counts.warmup_count || 0} />
        <Metric label="Agg Stale" value={data.aggregation.counts.stale_count || 0} />
        <Metric label="Agg Missing Spot" value={data.aggregation.counts.missing_spot_count || 0} />
      </section>
      <section className="grid gap-3 md:grid-cols-5">
        <Metric label="Aligned" value={data.rich_alignment.counts.aligned_count || 0} />
        <Metric label="Incomplete" value={data.rich_alignment.counts.incomplete_count || 0} />
        <Metric label="Warmup" value={data.rich_alignment.counts.warmup_count || 0} />
        <Metric label="Stale" value={data.rich_alignment.counts.stale_count || 0} />
        <Metric label="No Data" value={data.rich_alignment.counts.no_data_count || 0} />
      </section>
      <section className="grid gap-3 md:grid-cols-4">
        <Metric label="State Fresh" value={data.market_state_alignment.counts.fresh_count || 0} />
        <Metric label="State Stale" value={data.market_state_alignment.counts.stale_count || 0} />
        <Metric label="State Missing" value={data.market_state_alignment.counts.missing_count || 0} />
        <Metric label="Funding Missing" value={data.market_state_alignment.counts.funding_missing_count || 0} />
      </section>
      <section className="grid gap-3 md:grid-cols-4">
        <Metric label="15m Feature Partial" value={data.features_15m.feature_partial_count || 0} />
        <Metric label="15m Feature Blocked" value={data.features_15m.feature_blocked_count || 0} />
        <Metric label="1h Feature Partial" value={data.features_1h.feature_partial_count || 0} />
        <Metric label="1h Feature Blocked" value={data.features_1h.feature_blocked_count || 0} />
      </section>
      <section className="grid gap-3 md:grid-cols-4">
        <Metric label="Context Ready" value={data.feature_context_15m_1h.context_ready_count || 0} />
        <Metric label="Context Partial" value={data.feature_context_15m_1h.context_partial_count || 0} />
        <Metric label="Context Blocked" value={data.feature_context_15m_1h.context_blocked_count || 0} />
        <Metric label="Latest Context Symbols" value={data.feature_context_15m_1h.latest_symbols_count || 0} />
      </section>
      <section className="grid gap-3 md:grid-cols-5">
        <Metric label="Spot Supporting" value={data.feature_context_15m_1h.spot_support_counts?.SPOT_SUPPORTING || 0} />
        <Metric label="Weak Spot Support" value={data.feature_context_15m_1h.spot_support_counts?.WEAK_SPOT_SUPPORT || 0} />
        <Metric label="Futures Led" value={data.feature_context_15m_1h.spot_support_counts?.FUTURES_LED || 0} />
        <Metric label="Spot Missing" value={data.feature_context_15m_1h.spot_support_counts?.SPOT_MISSING || 0} />
        <Metric label="Spot Unknown" value={data.feature_context_15m_1h.spot_support_counts?.SPOT_UNKNOWN || 0} />
      </section>
      <section className="grid gap-3 md:grid-cols-4">
        <Metric label="Label Ready" value={data.psychology_15m.label_ready_count || 0} />
        <Metric label="Label Partial" value={data.psychology_15m.label_partial_count || 0} />
        <Metric label="Label Blocked" value={data.psychology_15m.label_blocked_count || 0} />
        <Metric label="Top Label" value={data.psychology_15m.top_primary_labels[0]?.label || "-"} />
      </section>
      <section className="grid gap-3 md:grid-cols-4">
        <Metric label="Readonly Ready" value={data.signal_candidates_readonly_15m.classifier_ready_count || 0} />
        <Metric label="Readonly Partial" value={data.signal_candidates_readonly_15m.classifier_partial_count || 0} />
        <Metric label="Readonly Blocked" value={data.signal_candidates_readonly_15m.classifier_blocked_count || 0} />
        <Metric label="Top Readonly Type" value={data.signal_candidates_readonly_15m.candidate_type_counts[0]?.type || "-"} />
      </section>
      <section className="grid gap-3 md:grid-cols-4">
        <Metric label="Outcome Ready" value={data.outcomes_15m.outcome_status_counts.OUTCOME_READY || 0} />
        <Metric label="Outcome Waiting" value={data.outcomes_15m.outcome_status_counts.OUTCOME_WAITING_DATA || 0} />
        <Metric label="Outcome Incomplete" value={data.outcomes_15m.outcome_status_counts.OUTCOME_INCOMPLETE || 0} />
        <Metric label="Outcome Blocked" value={data.outcomes_15m.outcome_status_counts.OUTCOME_BLOCKED || 0} />
      </section>
      <div className="overflow-x-auto border border-line bg-white">
        <table>
          <thead>
            <tr>
              <th>Symbol</th>
              <th>Rank</th>
              <th>Tier</th>
              <th>Status</th>
              <th>Rich</th>
              <th>Futures Candle</th>
              <th>Spot Candle</th>
              <th>Open Interest</th>
              <th>Funding</th>
              <th>Reason</th>
            </tr>
          </thead>
          <tbody>
            {data.items.map((item) => (
              <tr key={item.symbol}>
                <td>
                  <Link className="font-semibold text-blue-700 hover:underline" href={`/tokens/${item.symbol}`}>
                    {item.symbol}
                  </Link>
                </td>
                <td>{item.rank ?? "-"}</td>
                <td><StatusBadge value={item.collection_tier} /></td>
                <td><StatusBadge value={item.status} /></td>
                <td><StatusBadge value={item.rich_status} /></td>
                <td>{fmtTime(item.latest_futures_candle_time)}</td>
                <td>{fmtTime(item.latest_spot_candle_time)}</td>
                <td>{fmtTime(item.latest_open_interest_time)}</td>
                <td>{fmtTime(item.latest_funding_time)}</td>
                <td>{item.reason || item.rich_reason || "-"}</td>
              </tr>
            ))}
            {!data.items.length && (
              <tr>
                <td colSpan={10}>No health rows yet. Build the active universe first.</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
