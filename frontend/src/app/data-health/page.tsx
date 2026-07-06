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
  Phase7FullBlockerAuditResponse,
  RichAlignmentStatus,
  fetchJson
} from "@/lib/api";
import { formatLocalDateTime, formatRelativeTime, formatTimeWithUtcDetail } from "@/lib/time";

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
  const [data, audit] = await Promise.all([
    fetchJson<HealthResponse>("/api/data-health"),
    fetchJson<Phase7FullBlockerAuditResponse>("/api/phase7/full-blocker-audit", { revalidateSeconds: 20 }).catch(() => null)
  ]);
  const visibleItems = data.items.slice(0, 75);
  const atr4 = audit?.atr_readiness["4h"]?.available_symbols ?? 0;
  const atr24 = audit?.atr_readiness["24h"]?.available_symbols ?? 0;
  return (
    <div className="space-y-5">
      <PageHeader title="System Health" subtitle="Kesehatan data dan kematangan timeframe yang menentukan apakah MarketLab bisa menilai kandidat." updatedAt={`${formatLocalDateTime(data.latest.latest_futures_candle_time)}, ${formatRelativeTime(data.latest.latest_futures_candle_time)}`} />

      <section className="grid gap-3 md:grid-cols-3 xl:grid-cols-6">
        <MetricCard label="System Status" value="Running" helper="Collector API online" tone="good" />
        <MetricCard label="Symbol Ready" value={`${data.counts.READY || 0}/75`} helper="Data utama fresh" tone="good" />
        <MetricCard label="Latest 15m" value={formatLocalDateTime(data.aggregation.latest.latest_15m_futures)} helper={formatRelativeTime(data.aggregation.latest.latest_15m_futures)} />
        <MetricCard label="4h ATR" value={atr4 > 0 ? `${atr4}/75` : "Belum siap"} helper="Butuh minimal 15 candle" tone={atr4 > 0 ? "warn" : "bad"} />
        <MetricCard label="24h ATR" value={atr24 > 0 ? `${atr24}/75` : "Belum siap"} helper="Butuh minimal 15 candle" tone={atr24 > 0 ? "warn" : "bad"} />
        <MetricCard label="Missing Spot" value={data.counts.MISSING_SPOT || 0} helper="Spot belum tersedia" />
      </section>

      <SectionCard title="Kematangan data 4h/24h" description="Blocker utama signal gate dan forward-test saat ini.">
        <div className="grid gap-3 p-4 text-sm md:grid-cols-4">
          <MaturityItem label="4h candles" value={`${audit?.data_coverage["4h"]?.futures.ready_rows ?? 0} ready rows`} />
          <MaturityItem label="24h candles" value={`${audit?.data_coverage["24h"]?.futures.ready_rows ?? 0} ready rows`} />
          <MaturityItem label="ATR 4h" value={`${atr4}/75`} />
          <MaturityItem label="ATR 24h" value={`${atr24}/75`} />
        </div>
      </SectionCard>

      <SectionCard title="Latest data timestamps" description="Yang utama untuk cek apakah loop terus maju.">
        <dl className="grid gap-0 text-sm md:grid-cols-2">
          {Object.entries(data.latest).map(([key, value]) => (
            <div key={key} className="grid grid-cols-2 border-b border-line px-4 py-3">
              <dt className="font-medium text-slate-600">{key.replaceAll("_", " ")}</dt>
              <dd><LocalTimeDetail value={value} /></dd>
            </div>
          ))}
        </dl>
      </SectionCard>

      <SectionCard title="Symbol health" description="Dibatasi 75 active symbols. Raw enum tersedia di detail teknis.">
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Symbol</th>
                <th>Rank</th>
                <th>Status</th>
                <th>Futures Data</th>
                <th>Spot Data</th>
                <th>Reason</th>
              </tr>
            </thead>
            <tbody>
              {visibleItems.map((item) => (
                <tr key={item.symbol}>
                  <td><Link className="font-semibold text-blue-700 hover:underline" href={`/tokens/${item.symbol}`}>{item.symbol}</Link></td>
                  <td>{item.rank ?? "-"}</td>
                  <td><StatusBadge value={item.status} /></td>
                  <td><LocalTimeDetail value={item.latest_futures_candle_time} compact /></td>
                  <td><LocalTimeDetail value={item.latest_spot_candle_time} compact /></td>
                  <td className="truncate-cell" title={item.reason || item.rich_reason || "-"}>{healthReason(item.reason || item.rich_reason)}</td>
                </tr>
              ))}
              {!visibleItems.length && (
                <tr>
                  <td colSpan={6}><EmptyState title="No health rows" detail="Build the active universe first." /></td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </SectionCard>

      <SectionCard title="Advanced details" description="Technical aggregation and rich alignment counters.">
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

function MaturityItem({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded border border-line p-3">
      <div className="text-xs font-semibold uppercase text-slate-500">{label}</div>
      <div className="mt-1 font-bold text-ink">{value}</div>
    </div>
  );
}

function LocalTimeDetail({ value, compact = false }: { value?: string | null; compact?: boolean }) {
  const detail = formatTimeWithUtcDetail(value);
  return (
    <div>
      <div>{detail.local}</div>
      {!compact && <div className="text-xs text-slate-500">{detail.relative}</div>}
      <details className="mt-1 text-xs text-slate-500">
        <summary className="cursor-pointer font-semibold">UTC detail</summary>
        <div>Local time: {detail.local}</div>
        <div>UTC: {detail.utc}</div>
      </details>
    </div>
  );
}

function healthReason(reason?: string | null): string {
  if (!reason) return "Data utama fresh";
  const lower = reason.toLowerCase();
  if (lower.includes("rich") || lower.includes("stale")) return "Raw data belum fresh";
  if (lower.includes("spot") && lower.includes("1m")) return "Spot 1m belum tersedia";
  if (lower.includes("all required datasets fresh")) return "Data utama fresh";
  return reason;
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
