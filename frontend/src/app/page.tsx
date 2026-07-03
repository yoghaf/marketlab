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
  LiveScannerItem,
  LiveScannerResponse,
  fetchJson,
  fmtTime
} from "@/lib/api";
import { compactReason, labelFor } from "@/lib/labels";

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
  const riskCount = scannerCounts.RISK_CONTEXT || 0;
  const baselineCount = scannerCounts.BASELINE_CONTEXT || 0;
  const latestCandidates = (scanner?.items || [])
    .filter((item) => item.scanner_tier !== "BASELINE_CONTEXT" && item.candidate_type !== "NO_SIGNAL_CONTEXT")
    .slice(0, 8);
  const latestSignal = latestCandidates.find((item) => item.scanner_tier === "SIGNAL_CANDIDATE");
  const primaryAction = signalCandidateCount > 0
    ? "Cek Signal Candidate dan evidence angka di Radar."
    : candidateCount > 0
      ? "Pantau Candidate, belum ada yang cukup kuat untuk dinaikkan."
      : "Tunggu cycle data berikutnya atau cek Data Health.";

  return (
    <div className="space-y-5">
      <PageHeader
        title="MarketLab Command Center"
        badge="READ-ONLY - bukan sinyal entry live"
        subtitle="Ringkasan cepat untuk baca market radar, kualitas data, dan status riset. Semua output tetap observasi read-only."
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
        <MetricCard label="Signal Candidate" value={signalCandidateCount} helper="Final read-only, bukan order" tone={signalCandidateCount ? "good" : "warn"} />
        <MetricCard label="Candidate" value={candidateCount} helper="Konteks layak dipantau" tone="info" />
        <MetricCard label="Radar" value={radarCount} helper="Aktivitas awal" tone="info" />
        <MetricCard label="Risk Context" value={riskCount} helper="Campuran/risiko" tone="warn" />
        <MetricCard label="Phase 7 Approved" value={approvedCount} helper="Shadow-test approved" tone={approvedCount ? "good" : "warn"} />
        <MetricCard label="Baseline" value={baselineCount} helper="Kontrol pembanding" />
      </section>

      <section className="grid gap-4 xl:grid-cols-[1.15fr_0.85fr]">
        <SectionCard
          title="Yang harus dicek sekarang"
          description="Prioritas kerja dashboard, bukan keputusan eksekusi."
          actions={<StatusBadge value={phase7Decision} />}
        >
          <div className="grid gap-4 p-4 lg:grid-cols-2">
            <div className="rounded border border-line bg-field/40 p-4">
              <div className="text-xs font-semibold uppercase text-slate-500">Fokus sekarang</div>
              <div className="mt-2 text-lg font-bold text-ink">{primaryAction}</div>
              <div className="mt-3 space-y-2 text-sm leading-6">
                <ReasonRow label="Signal Candidate" value={`${signalCandidateCount} token`} />
                <ReasonRow label="Candidate" value={`${candidateCount} token`} />
                <ReasonRow label="Risk Context" value={`${riskCount} token`} />
                <ReasonRow label="Latest signal" value={latestSignal ? latestSignal.symbol : "-"} />
              </div>
            </div>
            <div className="rounded border border-line bg-field/40 p-4">
              <div className="text-xs font-semibold uppercase text-slate-500">Readiness blocker</div>
              <div className="mt-2 text-lg font-bold text-ink">{edgeOver010 > 0 ? "Edge mulai muncul" : "Edge belum kuat"}</div>
              <div className="mt-3 space-y-2 text-sm leading-6">
                <ReasonRow label="ATR 4h" value={`${atr4}/75 symbol`} />
                <ReasonRow label="ATR 24h" value={`${atr24}/75 symbol`} />
                <ReasonRow label="Edge > 0.10R" value={`${edgeOver010} kandidat`} />
                <ReasonRow label="Score >= 7" value={`${scoreGe7} kandidat`} />
              </div>
            </div>
            <div className="flex flex-wrap gap-2 pt-2">
              <Link className="rounded border border-line px-3 py-2 font-semibold hover:bg-field" href="/scanner">Open Radar</Link>
              <Link className="rounded border border-line px-3 py-2 font-semibold hover:bg-field" href="/phase6-audit">Open Phase 6 Audit</Link>
              <Link className="rounded border border-line px-3 py-2 font-semibold hover:bg-field" href="/data-health">Open System Health</Link>
            </div>
          </div>
        </SectionCard>

        <SectionCard title="Alur keputusan" description="Urutan baca output MarketLab.">
          <div className="space-y-3 p-4">
            <PipelineStep title="Radar" value={`${radarCount} token`} description="Aktivitas awal, belum cukup untuk candidate." />
            <PipelineStep title="Candidate" value={`${candidateCount} token`} description="Konteks layak dipantau, masih butuh bukti." />
            <PipelineStep title="Signal Candidate" value={`${signalCandidateCount} token`} description="Final read-only dengan reference futures." />
            <PipelineStep title="Phase 7 Shadow" value={`${approvedCount} approved`} description="Uji forward, tetap bukan execution." />
          </div>
        </SectionCard>
      </section>

      <SectionCard
        title="Latest market radar"
        description="Token terbaru yang bukan baseline/control. Klik symbol untuk detail token, atau buka Radar untuk evidence lengkap."
        actions={<Link className="rounded border border-line px-3 py-2 text-sm font-semibold hover:bg-field" href="/scanner?limit=75">Open full scanner</Link>}
      >
        <div className="table-wrap">
          <table className="ops-table">
            <thead>
              <tr>
                <th>Symbol</th>
                <th>Tier</th>
                <th>Label</th>
                <th>Arah</th>
                <th>Confidence</th>
                <th>Evidence</th>
                <th>Update WIB</th>
              </tr>
            </thead>
            <tbody>
              {latestCandidates.map((item) => <LatestCandidateRow item={item} key={`${item.symbol}-${item.window_open_time}-${item.scanner_tier}`} />)}
              {!latestCandidates.length && (
                <tr>
                  <td colSpan={7} className="text-sm text-slate-500">Belum ada radar non-baseline.</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </SectionCard>

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

function LatestCandidateRow({ item }: { item: LiveScannerItem }) {
  const ev = item.evidence_summary || {};
  return (
    <tr>
      <td className="font-semibold">
        <Link className="text-blue-700 hover:underline" href={`/tokens/${item.symbol}`}>{item.symbol}</Link>
      </td>
      <td><StatusBadge value={item.scanner_tier} /></td>
      <td>{labelFor(item.candidate_type)}</td>
      <td><StatusBadge value={item.candidate_direction} /></td>
      <td>{labelFor(item.confidence)}</td>
      <td className="text-xs leading-5 text-slate-600">
        <div>Score {valueOrDash(ev.core_score)}/{valueOrDash(ev.core_score_max)} | Evidence {valueOrDash(ev.evidence_data_completeness)}/4</div>
        <div>{compactReason(formatList(ev.core_reasons), 120)}</div>
      </td>
      <td>{fmtTime(item.latest_outcome_update || item.observation_time || item.window_close_time)}</td>
    </tr>
  );
}

function PipelineStep({ title, value, description }: { title: string; value: string; description: string }) {
  return (
    <div className="rounded border border-line bg-white p-3">
      <div className="flex items-center justify-between gap-3">
        <div className="font-bold text-ink">{title}</div>
        <div className="text-sm font-semibold text-blue-700">{value}</div>
      </div>
      <div className="mt-1 text-sm leading-5 text-slate-600">{description}</div>
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

function valueOrDash(value: unknown): string {
  if (value === null || value === undefined || value === "") return "-";
  return String(value);
}

function formatList(value: unknown): string {
  if (Array.isArray(value)) return value.length ? value.join(", ") : "-";
  if (typeof value === "string" && value) return value;
  return "-";
}

function edgeBucket(data: Phase7FullBlockerAuditResponse | null, needle: string): number {
  const buckets = data?.edge.edge_buckets || {};
  const found = Object.entries(buckets).find(([key]) => key.includes(needle));
  return found?.[1] ?? 0;
}
