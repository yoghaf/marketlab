import Link from "next/link";

import { DecisionBanner } from "@/components/DecisionBanner";
import { MetricCard } from "@/components/MetricCard";
import { PageHeader } from "@/components/PageHeader";
import { SectionCard } from "@/components/SectionCard";
import { StatusBadge } from "@/components/StatusBadge";
import {
  AggregationStatus,
  CollectorRun,
  Phase6ReadinessResponse,
  StrategyArenaLeaderboardResponse,
  fetchJson,
  fmtTime
} from "@/lib/api";
import { labelFor } from "@/lib/labels";

type HealthResponse = {
  counts: Record<string, number>;
  latest: Record<string, string | null>;
  feature_context_15m_1h: {
    context_ready_count: number;
    context_partial_count: number;
    context_blocked_count: number;
    latest_context_time?: string | null;
  };
  signal_candidates_readonly_15m: {
    classifier_ready_count: number;
    classifier_partial_count: number;
    classifier_blocked_count: number;
    total_rows: number;
    latest_candidate_time?: string | null;
  };
};
type CollectorResponse = { collectors: CollectorRun[]; last_errors: { message: string; created_at: string }[]; request_usage: { latest_used_weight_1m?: number | null } };

export default async function OverviewPage() {
  const [health, collectors, aggregation, phase6, arena] = await Promise.all([
    fetchJson<HealthResponse>("/api/data-health"),
    fetchJson<CollectorResponse>("/api/collectors/status"),
    fetchJson<AggregationStatus>("/api/aggregation/status"),
    fetchJson<Phase6ReadinessResponse>("/api/phase6/readiness", { revalidateSeconds: 20 }).catch(() => null),
    fetchJson<StrategyArenaLeaderboardResponse>("/api/strategy-arena/v1/leaderboard", { revalidateSeconds: 20 }).catch(() => null)
  ]);
  const lastRun = collectors.collectors[0];
  const lastError = collectors.last_errors[0];
  const phase7Decision = phase6?.phase7_decision || "NO_PHASE7_CANDIDATE_YET";
  const dataSummary = `${readinessLabel(phase6, "15m")}, ${readinessLabel(phase6, "1h")}; 4h/24h ${higherTimeframeState(phase6)}`;

  return (
    <div className="space-y-5">
      <PageHeader
        title="Overview"
        subtitle="Ringkasan MarketLab saat ini: kesehatan data, kandidat signal read-only, keputusan Phase 6, dan aksi berikutnya."
        updatedAt={fmtTime(phase6?.generated_at || health.latest.latest_futures_candle_time)}
      />

      <DecisionBanner
        title={phase7Decision === "HAS_CANDIDATES" ? "Phase 7 boleh dipersiapkan" : "Phase 7 belum boleh jalan"}
        status={phase7Decision}
        tone={phase7Decision === "HAS_CANDIDATES" ? "good" : "warn"}
        description={
          phase7Decision === "HAS_CANDIDATES"
            ? "Ada kandidat yang lolos audit untuk shadow forward-test. Tetap read-only dan belum ada eksekusi."
            : "Belum ada kandidat dengan score cukup. Arena masih noisy dan sebagian timeframe tinggi belum siap."
        }
      />

      <section className="grid gap-3 md:grid-cols-2 xl:grid-cols-6">
        <MetricCard label="System Status" value={lastRun?.status || "unknown"} helper={lastRun?.collector_name || "Collector pulse"} tone={lastError ? "warn" : "good"} />
        <MetricCard label="Data Readiness" value={dataSummary} helper={`Latest 15m: ${fmtTime(aggregation.latest_15m_futures)}`} tone="info" />
        <MetricCard label="Signal Candidates" value={health.signal_candidates_readonly_15m.classifier_partial_count || 0} helper="Read-only partial candidates" tone="neutral" />
        <MetricCard label="Phase 6 Decision" value={labelFor(phase7Decision)} helper={`Watchlist ${phase6?.watchlist_count ?? 0}, approved ${phase6?.approved_count ?? 0}`} tone={phase7Decision === "HAS_CANDIDATES" ? "good" : "warn"} />
        <MetricCard label="Strategy Best" value={arena?.summary.best_short_setup?.setup_label || "-"} helper={arena?.summary.best_short_setup?.verdict_label || "Strategy Arena"} tone="neutral" />
        <MetricCard label="Next Action" value={phase7Decision === "HAS_CANDIDATES" ? "Shadow tracker" : "Tunggu data"} helper="Refresh audit setelah sample bertambah" tone="info" />
      </section>

      <section className="grid gap-4 lg:grid-cols-2">
        <SectionCard title="What matters now" description="Ringkasan yang harus dibaca sebelum membuka halaman teknis.">
          <div className="space-y-3 p-4 text-sm leading-6">
            <div className="flex items-center justify-between gap-3">
              <span>Data health</span>
              <span className="font-semibold">{health.counts.READY || 0} ready / {health.counts.STALE || 0} stale</span>
            </div>
            <div className="flex items-center justify-between gap-3">
              <span>15m + 1h context</span>
              <span className="font-semibold">{health.feature_context_15m_1h.context_ready_count} ready, {health.feature_context_15m_1h.context_blocked_count} blocked</span>
            </div>
            <div className="flex items-center justify-between gap-3">
              <span>Phase 6</span>
              <StatusBadge value={phase7Decision} />
            </div>
            <div className="flex flex-wrap gap-2 pt-2">
              <Link className="rounded border border-line px-3 py-2 font-semibold hover:bg-field" href="/scanner">Open Signals</Link>
              <Link className="rounded border border-line px-3 py-2 font-semibold hover:bg-field" href="/phase6-audit">Open Phase 6 Audit</Link>
              <Link className="rounded border border-line px-3 py-2 font-semibold hover:bg-field" href="/data-health">Open System Health</Link>
            </div>
          </div>
        </SectionCard>

        <SectionCard title="Collector pulse" description="Ops ringkas. Detail raw ada di Developer.">
          <div className="space-y-3 p-4 text-sm">
            <div className="flex items-center justify-between gap-3">
              <span>{lastRun?.collector_name || "-"}</span>
              <StatusBadge value={lastRun?.status} />
            </div>
            <div>Last run: {fmtTime(lastRun?.finished_at || lastRun?.started_at)}</div>
            <div>Request weight 1m: {collectors.request_usage.latest_used_weight_1m ?? "-"}</div>
            <div>Last error: {lastError ? `${fmtTime(lastError.created_at)} ${lastError.message}` : "No recent collector error"}</div>
            <Link className="inline-flex rounded border border-line px-3 py-2 font-semibold hover:bg-field" href="/collectors">Developer details</Link>
          </div>
        </SectionCard>
      </section>
    </div>
  );
}

function readinessLabel(phase6: Phase6ReadinessResponse | null, timeframe: string): string {
  const status = phase6?.feature_readiness.by_timeframe[timeframe]?.readiness_status;
  return `${timeframe} ${labelFor(status).toLowerCase()}`;
}

function higherTimeframeState(phase6: Phase6ReadinessResponse | null): string {
  const four = phase6?.feature_readiness.by_timeframe["4h"]?.readiness_status;
  const day = phase6?.feature_readiness.by_timeframe["24h"]?.readiness_status;
  if (four === "TIMEFRAME_READY" && day === "TIMEFRAME_READY") return "siap";
  return "belum siap";
}
