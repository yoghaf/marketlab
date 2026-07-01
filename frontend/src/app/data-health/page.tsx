import Link from "next/link";

import { EmptyState } from "@/components/EmptyState";
import { MetricCard } from "@/components/MetricCard";
import { PageHeader } from "@/components/PageHeader";
import { SectionCard } from "@/components/SectionCard";
import { StatusBadge } from "@/components/StatusBadge";
import {
  AggregationStatus,
  FeatureContext15m1hStatus,
  HealthItem,
  RichAlignmentStatus,
  fetchJson,
  fmtTime
} from "@/lib/api";

type HealthResponse = {
  counts: Record<string, number>;
  rich_counts: Record<string, number>;
  aggregation: { latest: Record<string, string | null>; counts: AggregationStatus; tables: Record<string, Record<string, number>> };
  rich_alignment: { latest: Record<string, string | null>; counts: RichAlignmentStatus; tables: Record<string, Record<string, number>> };
  feature_context_15m_1h: FeatureContext15m1hStatus;
  latest: Record<string, string | null>;
  items: HealthItem[];
};

export default async function DataHealthPage() {
  const data = await fetchJson<HealthResponse>("/api/data-health");
  const visibleItems = data.items.slice(0, 75);
  return (
    <div className="space-y-5">
      <PageHeader title="System Health" subtitle="Ops view untuk memastikan collector, candle, alignment, dan data health tetap maju." updatedAt={fmtTime(data.latest.latest_futures_candle_time)} />

      <section className="grid gap-3 md:grid-cols-3 xl:grid-cols-6">
        <MetricCard label="Ready" value={data.counts.READY || 0} tone="good" />
        <MetricCard label="Warmup" value={data.counts.WARMUP || 0} tone="warn" />
        <MetricCard label="Stale" value={data.counts.STALE || 0} tone={data.counts.STALE ? "bad" : "neutral"} />
        <MetricCard label="Missing Spot" value={data.counts.MISSING_SPOT || 0} />
        <MetricCard label="Latest 15m" value={fmtTime(data.aggregation.latest.latest_15m_futures)} helper="Futures aggregate" />
        <MetricCard label="Context Ready" value={data.feature_context_15m_1h.context_ready_count || 0} />
      </section>

      <SectionCard title="Latest data timestamps" description="Yang utama untuk cek apakah loop terus maju.">
        <dl className="grid gap-0 text-sm md:grid-cols-2">
          {Object.entries(data.latest).map(([key, value]) => (
            <div key={key} className="grid grid-cols-2 border-b border-line px-4 py-3">
              <dt className="font-medium text-slate-600">{key.replaceAll("_", " ")}</dt>
              <dd>{fmtTime(value)}</dd>
            </div>
          ))}
        </dl>
      </SectionCard>

      <SectionCard title="Symbol health" description="Dibatasi 75 active symbols. Raw rich/aggregation enum tetap terlihat di badge.">
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Symbol</th>
                <th>Rank</th>
                <th>Status</th>
                <th>Rich</th>
                <th>Futures Candle</th>
                <th>Spot Candle</th>
                <th>Reason</th>
              </tr>
            </thead>
            <tbody>
              {visibleItems.map((item) => (
                <tr key={item.symbol}>
                  <td><Link className="font-semibold text-blue-700 hover:underline" href={`/tokens/${item.symbol}`}>{item.symbol}</Link></td>
                  <td>{item.rank ?? "-"}</td>
                  <td><StatusBadge value={item.status} /></td>
                  <td><StatusBadge value={item.rich_status} /></td>
                  <td>{fmtTime(item.latest_futures_candle_time)}</td>
                  <td>{fmtTime(item.latest_spot_candle_time)}</td>
                  <td className="truncate-cell" title={item.reason || item.rich_reason || "-"}>{item.reason || item.rich_reason || "-"}</td>
                </tr>
              ))}
              {!visibleItems.length && (
                <tr>
                  <td colSpan={7}><EmptyState title="No health rows" detail="Build the active universe first." /></td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </SectionCard>

      <SectionCard title="Developer details" description="Technical aggregation and rich alignment counters.">
        <details className="p-4 text-sm">
          <summary className="cursor-pointer font-semibold">Show technical labels</summary>
          <div className="mt-4 grid gap-4 lg:grid-cols-2">
            <KeyValue title="OHLCV Aggregation" data={data.aggregation.counts as unknown as Record<string, unknown>} />
            <KeyValue title="Rich 5m Alignment" data={data.rich_alignment.counts as unknown as Record<string, unknown>} />
          </div>
        </details>
      </SectionCard>
    </div>
  );
}

function KeyValue({ title, data }: { title: string; data: Record<string, unknown> }) {
  return (
    <div className="rounded border border-line">
      <h3 className="border-b border-line px-3 py-2 font-semibold">{title}</h3>
      <dl>
        {Object.entries(data).map(([key, value]) => (
          <div key={key} className="grid grid-cols-2 border-b border-line px-3 py-2 last:border-b-0">
            <dt className="text-slate-600">{key}</dt>
            <dd>{String(value ?? "-")}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}
