import Link from "next/link";

import { Metric } from "@/components/Metric";
import { StatusBadge } from "@/components/StatusBadge";
import {
  AggregationStatus,
  CollectorRun,
  FeatureContext15m1hStatus,
  Feature1hStatus,
  Feature15mStatus,
  HealthItem,
  MarketStateAlignmentStatus,
  Outcomes15mStatus,
  Psychology15mStatus,
  RichAlignmentStatus,
  SignalCandidatesReadonly15mStatus,
  UniverseItem,
  fetchJson,
  fmtTime
} from "@/lib/api";

type UniverseResponse = {
  count: number;
  active_universe_count: number;
  universe_count: number;
  full_active_count: number;
  signal_eligible_count: number;
  items: UniverseItem[];
};
type HealthResponse = { counts: Record<string, number>; latest: Record<string, string | null>; items: HealthItem[] };
type CollectorResponse = { collectors: CollectorRun[]; last_errors: { message: string; created_at: string }[]; request_usage: { latest_used_weight_1m?: number | null } };

export default async function DashboardPage() {
  const [universe, health, collectors, aggregation, richAlignment, marketStateAlignment, features15m, features1h, featureContext, psychology15m, signalCandidates, outcomes15m] = await Promise.all([
    fetchJson<UniverseResponse>("/api/universe/active"),
    fetchJson<HealthResponse>("/api/data-health"),
    fetchJson<CollectorResponse>("/api/collectors/status"),
    fetchJson<AggregationStatus>("/api/aggregation/status"),
    fetchJson<RichAlignmentStatus>("/api/rich-alignment/status"),
    fetchJson<MarketStateAlignmentStatus>("/api/market-state-alignment/status"),
    fetchJson<Feature15mStatus>("/api/features/15m/status"),
    fetchJson<Feature1hStatus>("/api/features/1h/status"),
    fetchJson<FeatureContext15m1hStatus>("/api/features/context/15m-1h/status"),
    fetchJson<Psychology15mStatus>("/api/psychology/15m/status"),
    fetchJson<SignalCandidatesReadonly15mStatus>("/api/signal-candidates/readonly/15m/status"),
    fetchJson<Outcomes15mStatus>("/api/outcomes/15m/status")
  ]);
  const lastRun = collectors.collectors[0];
  const lastError = collectors.last_errors[0];

  return (
    <div className="space-y-6">
      <section>
        <h1 className="text-2xl font-bold tracking-normal">Dashboard</h1>
      </section>

      <section className="grid gap-3 md:grid-cols-4">
        <Metric label="Active Universe" value={universe.active_universe_count ?? universe.universe_count ?? universe.count} />
        <Metric label="Full Active" value={universe.full_active_count ?? 0} />
        <Metric label="Signal Eligible" value={universe.signal_eligible_count ?? 0} />
        <Metric label="Request Weight 1m" value={collectors.request_usage.latest_used_weight_1m ?? "-"} />
      </section>

      <section className="grid gap-3 md:grid-cols-4">
        <Metric label="Ready" value={health.counts.READY || 0} />
        <Metric label="Warmup" value={health.counts.WARMUP || 0} />
        <Metric label="Stale" value={health.counts.STALE || 0} />
        <Metric label="Missing Spot" value={health.counts.MISSING_SPOT || 0} />
      </section>

      <section className="grid gap-3 md:grid-cols-5">
        <Metric label="Agg Ready" value={aggregation.ready_count || 0} />
        <Metric label="Agg Incomplete" value={aggregation.incomplete_count || 0} />
        <Metric label="Agg Warmup" value={aggregation.warmup_count || 0} />
        <Metric label="Agg Stale" value={aggregation.stale_count || 0} />
        <Metric label="Agg Missing Spot" value={aggregation.missing_spot_count || 0} />
      </section>

      <section className="grid gap-3 md:grid-cols-5">
        <Metric label="Rich Aligned" value={richAlignment.aligned_count || 0} />
        <Metric label="Rich Incomplete" value={richAlignment.incomplete_count || 0} />
        <Metric label="Rich Warmup" value={richAlignment.warmup_count || 0} />
        <Metric label="Rich Stale" value={richAlignment.stale_count || 0} />
        <Metric label="Rich No Data" value={richAlignment.no_data_count || 0} />
      </section>

      <section className="grid gap-3 md:grid-cols-4">
        <Metric label="State Fresh" value={marketStateAlignment.fresh_count || 0} />
        <Metric label="State Stale" value={marketStateAlignment.stale_count || 0} />
        <Metric label="State Missing" value={marketStateAlignment.missing_count || 0} />
        <Metric label="Funding Carried" value={marketStateAlignment.funding_carried_forward_count || 0} />
      </section>

      <section className="grid gap-3 md:grid-cols-4">
        <Metric label="15m Feature Partial" value={features15m.feature_partial_count || 0} />
        <Metric label="15m Feature Blocked" value={features15m.feature_blocked_count || 0} />
        <Metric label="1h Feature Partial" value={features1h.feature_partial_count || 0} />
        <Metric label="1h Feature Blocked" value={features1h.feature_blocked_count || 0} />
      </section>

      <section className="grid gap-3 md:grid-cols-4">
        <Metric label="Context Ready" value={featureContext.context_ready_count || 0} />
        <Metric label="Context Partial" value={featureContext.context_partial_count || 0} />
        <Metric label="Context Blocked" value={featureContext.context_blocked_count || 0} />
        <Metric label="Latest Context Symbols" value={featureContext.latest_symbols_count || 0} />
      </section>

      <section className="grid gap-3 md:grid-cols-5">
        <Metric label="Spot Supporting" value={featureContext.spot_support_counts?.SPOT_SUPPORTING || 0} />
        <Metric label="Weak Spot Support" value={featureContext.spot_support_counts?.WEAK_SPOT_SUPPORT || 0} />
        <Metric label="Futures Led" value={featureContext.spot_support_counts?.FUTURES_LED || 0} />
        <Metric label="Spot Missing" value={featureContext.spot_support_counts?.SPOT_MISSING || 0} />
        <Metric label="Spot Unknown" value={featureContext.spot_support_counts?.SPOT_UNKNOWN || 0} />
      </section>

      <section className="grid gap-3 md:grid-cols-4">
        <Metric label="Labels Ready" value={psychology15m.label_ready_count || 0} />
        <Metric label="Labels Partial" value={psychology15m.label_partial_count || 0} />
        <Metric label="Labels Blocked" value={psychology15m.label_blocked_count || 0} />
        <Metric label="Total Labels" value={psychology15m.total_labels || 0} />
      </section>

      <section className="grid gap-3 md:grid-cols-4">
        <Metric label="Read-only Ready" value={signalCandidates.classifier_ready_count || 0} />
        <Metric label="Read-only Partial" value={signalCandidates.classifier_partial_count || 0} />
        <Metric label="Read-only Blocked" value={signalCandidates.classifier_blocked_count || 0} />
        <Metric label="Read-only Rows" value={signalCandidates.total_rows || 0} />
      </section>

      <section className="grid gap-3 md:grid-cols-4">
        <Metric label="Outcome Ready" value={outcomes15m.outcome_status_counts.OUTCOME_READY || 0} />
        <Metric label="Outcome Waiting" value={outcomes15m.outcome_status_counts.OUTCOME_WAITING_DATA || 0} />
        <Metric label="Outcome Incomplete" value={outcomes15m.outcome_status_counts.OUTCOME_INCOMPLETE || 0} />
        <Metric label="Outcome Blocked" value={outcomes15m.outcome_status_counts.OUTCOME_BLOCKED || 0} />
      </section>

      <section className="grid gap-4 lg:grid-cols-2">
        <div className="border border-line bg-white">
          <h2 className="border-b border-line px-4 py-3 text-base font-semibold">Latest Data</h2>
          <dl className="grid gap-0 text-sm">
            {Object.entries(health.latest).map(([key, value]) => (
              <div key={key} className="grid grid-cols-2 border-b border-line px-4 py-3 last:border-b-0">
                <dt className="font-medium text-slate-600">{key.replaceAll("_", " ")}</dt>
                <dd>{fmtTime(value)}</dd>
              </div>
            ))}
          </dl>
        </div>
        <div className="border border-line bg-white">
          <h2 className="border-b border-line px-4 py-3 text-base font-semibold">Collector Pulse</h2>
          <div className="space-y-3 p-4 text-sm">
            <div className="flex items-center justify-between gap-3">
              <span>{lastRun?.collector_name || "-"}</span>
              <StatusBadge value={lastRun?.status} />
            </div>
            <div>Last run: {fmtTime(lastRun?.finished_at || lastRun?.started_at)}</div>
            <div>Duration: {lastRun?.duration ?? "-"}s</div>
            <div>Last error: {lastError ? `${fmtTime(lastError.created_at)} ${lastError.message}` : "-"}</div>
            <Link className="inline-flex rounded border border-line px-3 py-1.5 hover:bg-field" href="/collectors">
              Open collectors
            </Link>
          </div>
        </div>
      </section>

      <section className="border border-line bg-white">
        <h2 className="border-b border-line px-4 py-3 text-base font-semibold">Aggregation Latest</h2>
        <dl className="grid gap-0 text-sm md:grid-cols-2">
          {[
            ["15m futures", aggregation.latest_15m_futures],
            ["15m spot", aggregation.latest_15m_spot],
            ["1h futures", aggregation.latest_1h_futures],
            ["1h spot", aggregation.latest_1h_spot],
            ["4h futures", aggregation.latest_4h_futures],
            ["4h spot", aggregation.latest_4h_spot],
            ["24h futures", aggregation.latest_24h_futures],
            ["24h spot", aggregation.latest_24h_spot]
          ].map(([label, value]) => (
            <div key={label} className="grid grid-cols-2 border-b border-line px-4 py-3">
              <dt className="font-medium text-slate-600">{label}</dt>
              <dd>{fmtTime(value)}</dd>
            </div>
          ))}
        </dl>
      </section>

      <section className="border border-line bg-white">
        <h2 className="border-b border-line px-4 py-3 text-base font-semibold">Rich 5m Alignment Latest</h2>
        <dl className="grid gap-0 text-sm md:grid-cols-2">
          {[
            ["15m", richAlignment.latest_15m],
            ["1h", richAlignment.latest_1h],
            ["4h", richAlignment.latest_4h],
            ["24h", richAlignment.latest_24h]
          ].map(([label, value]) => (
            <div key={label} className="grid grid-cols-2 border-b border-line px-4 py-3">
              <dt className="font-medium text-slate-600">{label}</dt>
              <dd>{fmtTime(value)}</dd>
            </div>
          ))}
        </dl>
      </section>

      <section className="border border-line bg-white">
        <h2 className="border-b border-line px-4 py-3 text-base font-semibold">Market State Alignment Latest</h2>
        <dl className="grid gap-0 text-sm md:grid-cols-2">
          {[
            ["15m", marketStateAlignment.latest_15m],
            ["1h", marketStateAlignment.latest_1h],
            ["4h", marketStateAlignment.latest_4h],
            ["24h", marketStateAlignment.latest_24h]
          ].map(([label, value]) => (
            <div key={label} className="grid grid-cols-2 border-b border-line px-4 py-3">
              <dt className="font-medium text-slate-600">{label}</dt>
              <dd>{fmtTime(value)}</dd>
            </div>
          ))}
        </dl>
      </section>

      <section className="border border-line bg-white">
        <h2 className="border-b border-line px-4 py-3 text-base font-semibold">Feature Builders</h2>
        <dl className="grid gap-0 text-sm md:grid-cols-2">
          <div className="grid grid-cols-2 border-b border-line px-4 py-3">
            <dt className="font-medium text-slate-600">15m latest feature time</dt>
            <dd>{fmtTime(features15m.latest_feature_time)}</dd>
          </div>
          <div className="grid grid-cols-2 border-b border-line px-4 py-3">
            <dt className="font-medium text-slate-600">15m total features</dt>
            <dd>{features15m.total_features || 0}</dd>
          </div>
          <div className="grid grid-cols-2 border-b border-line px-4 py-3">
            <dt className="font-medium text-slate-600">1h latest feature time</dt>
            <dd>{fmtTime(features1h.latest_feature_time)}</dd>
          </div>
          <div className="grid grid-cols-2 border-b border-line px-4 py-3">
            <dt className="font-medium text-slate-600">1h total features</dt>
            <dd>{features1h.total_features || 0}</dd>
          </div>
          <div className="grid grid-cols-2 border-b border-line px-4 py-3">
            <dt className="font-medium text-slate-600">context latest time</dt>
            <dd>{fmtTime(featureContext.latest_context_time)}</dd>
          </div>
          <div className="grid grid-cols-2 border-b border-line px-4 py-3">
            <dt className="font-medium text-slate-600">context rows</dt>
            <dd>{featureContext.total_context_rows || 0}</dd>
          </div>
          <div className="grid grid-cols-2 border-b border-line px-4 py-3">
            <dt className="font-medium text-slate-600">label latest time</dt>
            <dd>{fmtTime(psychology15m.latest_label_time)}</dd>
          </div>
          <div className="grid grid-cols-2 border-b border-line px-4 py-3">
            <dt className="font-medium text-slate-600">top label</dt>
            <dd>{psychology15m.top_primary_labels[0]?.label || "-"}</dd>
          </div>
          <div className="grid grid-cols-2 border-b border-line px-4 py-3">
            <dt className="font-medium text-slate-600">readonly candidate latest time</dt>
            <dd>{fmtTime(signalCandidates.latest_candidate_time)}</dd>
          </div>
          <div className="grid grid-cols-2 border-b border-line px-4 py-3">
            <dt className="font-medium text-slate-600">top readonly type</dt>
            <dd>{signalCandidates.candidate_type_counts[0]?.type || "-"}</dd>
          </div>
          <div className="grid grid-cols-2 border-b border-line px-4 py-3">
            <dt className="font-medium text-slate-600">outcome latest update</dt>
            <dd>{fmtTime(outcomes15m.latest_outcome_update)}</dd>
          </div>
          <div className="grid grid-cols-2 border-b border-line px-4 py-3">
            <dt className="font-medium text-slate-600">outcome rows</dt>
            <dd>{outcomes15m.total_rows || 0}</dd>
          </div>
        </dl>
      </section>
    </div>
  );
}
