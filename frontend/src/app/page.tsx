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
  Phase7FullBlockerAuditResponse,
  LiveScannerResponse,
  fetchJson,
  fmtTime
} from "@/lib/api";

type HealthResponse = {
  counts: Record<string, number>;
  latest: Record<string, string | null>;
};
type CollectorResponse = {
  collectors: CollectorRun[];
  last_errors: { message: string; created_at: string }[];
  request_usage: { latest_used_weight_1m?: number | null };
};

export default async function OverviewPage() {
  const [health, collectors, aggregation, phase6, audit, scanner] = await Promise.all([
    fetchJson<HealthResponse>("/api/data-health"),
    fetchJson<CollectorResponse>("/api/collectors/status"),
    fetchJson<AggregationStatus>("/api/aggregation/status"),
    fetchJson<Phase6ReadinessResponse>("/api/phase6/readiness", { revalidateSeconds: 20 }).catch(() => null),
    fetchJson<Phase7FullBlockerAuditResponse>("/api/phase7/full-blocker-audit", { revalidateSeconds: 20 }).catch(() => null),
    fetchJson<LiveScannerResponse>("/api/scanner/live?limit=200", { revalidateSeconds: 20 }).catch(() => null)
  ]);

  const lastRun = collectors.collectors[0];
  const lastError = collectors.last_errors[0];
  const phase7Decision = phase6?.phase7_decision || audit?.rerun_result.phase7_decision || "NO_PHASE7_CANDIDATE_YET";
  const approvedCount = phase6?.approved_count ?? audit?.rerun_result.approved_count ?? 0;
  const watchlistCount = phase6?.watchlist_count ?? audit?.rerun_result.watchlist_count ?? 0;
  const atr4 = audit?.atr_readiness["4h"]?.available_symbols ?? 0;
  const atr24 = audit?.atr_readiness["24h"]?.available_symbols ?? 0;
  const edgeOver010 = edgeBucket(audit, "0.10");
  const scoreGe7 = audit?.phase6_scoring.score_ge_7_count ?? 0;
  const scannerCounts = scanner?.tier_counts || {};
  const radarCount = scannerCounts.RADAR_ONLY || 0;
  const candidateCount = scannerCounts.WATCHLIST_CONTEXT || 0;
  const signalCandidateCount = scannerCounts.SIGNAL_CANDIDATE || 0;

  return (
    <div className="space-y-5">
      <PageHeader
        title="Overview"
        badge="READ-ONLY - bukan sinyal entry live"
        subtitle="Ringkasan hirarki MarketLab: radar, candidate, signal candidate, dan alasan kenapa belum jadi eksekusi."
        updatedAt={fmtTime(phase6?.generated_at || audit?.generated_at || health.latest.latest_futures_candle_time)}
      />

      <DecisionBanner
        title={signalCandidateCount > 0 ? "Ada Signal Candidate read-only" : candidateCount > 0 ? "Ada Candidate untuk dipantau" : "Belum ada Signal Candidate"}
        status={`Signal Candidate: ${signalCandidateCount}`}
        tone={phase7Decision === "HAS_CANDIDATES" ? "good" : "warn"}
        description={
          signalCandidateCount > 0
            ? "Signal Candidate tetap read-only: ada entry futures reference, risk reference, dan tidak ada order otomatis."
            : "Radar/Candidate bisa ada walau Signal Candidate masih kosong. Itu berarti setup terpantau, tapi belum lolos quality gate final."
        }
      />

      <section className="grid gap-3 md:grid-cols-2 xl:grid-cols-6">
        <MetricCard label="Radar" value={radarCount} helper="Pantauan awal" tone="info" />
        <MetricCard label="Candidate" value={candidateCount} helper="Konteks layak dipantau" tone="info" />
        <MetricCard label="Signal Candidate" value={signalCandidateCount} helper="Final read-only, bukan order" tone={signalCandidateCount ? "good" : "warn"} />
        <MetricCard label="Phase 7 Approved" value={approvedCount} helper="Shadow-test approved" tone={approvedCount ? "good" : "warn"} />
        <MetricCard label="Data 4h" value={atr4 > 0 ? "Mulai siap" : "Belum cukup"} helper={`ATR ${atr4}/75 symbol`} tone={atr4 > 0 ? "warn" : "bad"} />
        <MetricCard label="Edge" value={edgeOver010 > 0 ? "Mulai kuat" : "Belum kuat"} helper={`edge > 0.10R: ${edgeOver010}`} tone={edgeOver010 > 0 ? "info" : "warn"} />
      </section>

      <section className="grid gap-4 lg:grid-cols-2">
        <SectionCard title="Yang penting sekarang" description="Keputusan utama tanpa label teknis.">
          <div className="space-y-3 p-4 text-sm leading-6">
            <ReasonRow label="Radar" value={`${radarCount} token`} />
            <ReasonRow label="Candidate" value={`${candidateCount} token`} />
            <ReasonRow label="Signal Candidate" value={`${signalCandidateCount} token`} />
            <ReasonRow label="Phase 7 approved" value={String(approvedCount)} />
            <ReasonRow label="Data 4h/24h" value="Belum cukup untuk ATR" />
            <ReasonRow label="Aksi" value="Backfill data atau tunggu data 4h/24h matang." />
            <div className="flex flex-wrap gap-2 pt-2">
              <Link className="rounded border border-line px-3 py-2 font-semibold hover:bg-field" href="/scanner">Open Radar</Link>
              <Link className="rounded border border-line px-3 py-2 font-semibold hover:bg-field" href="/phase6-audit">Open Phase 6 Audit</Link>
              <Link className="rounded border border-line px-3 py-2 font-semibold hover:bg-field" href="/data-health">Open System Health</Link>
            </div>
          </div>
        </SectionCard>

        <SectionCard title="Kenapa belum ada sinyal?" description="Blocker utama yang menentukan Phase 7.">
          <div className="space-y-3 p-4 text-sm leading-6">
            <ReasonRow label="ATR 4h belum tersedia" value={`${atr4}/75 symbol`} />
            <ReasonRow label="ATR 24h belum tersedia" value={`${atr24}/75 symbol`} />
            <ReasonRow label="Edge > 0.10R" value={`${edgeOver010} kandidat`} />
            <ReasonRow label="Score >= 7" value={`${scoreGe7} kandidat`} />
          </div>
        </SectionCard>
      </section>

      <SectionCard title="Collector pulse" description="Ops ringkas. Detail raw ada di Advanced.">
        <div className="grid gap-3 p-4 text-sm leading-6 md:grid-cols-4">
          <div>
            <div className="font-semibold">{lastRun?.collector_name || "-"}</div>
            <StatusBadge value={lastRun?.status} />
          </div>
          <div>Latest 15m: {fmtTime(aggregation.latest_15m_futures)}</div>
          <div>Request weight 1m: {collectors.request_usage.latest_used_weight_1m ?? "-"}</div>
          <div>Last error: {lastError ? fmtTime(lastError.created_at) : "No recent collector error"}</div>
        </div>
        <div className="border-t border-line px-4 py-3 text-sm">
          <Link className="inline-flex rounded border border-line px-3 py-2 font-semibold hover:bg-field" href="/collectors">Advanced details</Link>
        </div>
      </SectionCard>
    </div>
  );
}

function ReasonRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <span>{label}</span>
      <span className="text-right font-semibold">{value}</span>
    </div>
  );
}

function edgeBucket(data: Phase7FullBlockerAuditResponse | null, needle: string): number {
  const buckets = data?.edge.edge_buckets || {};
  const found = Object.entries(buckets).find(([key]) => key.includes(needle));
  return found?.[1] ?? 0;
}
