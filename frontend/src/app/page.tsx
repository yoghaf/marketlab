import Link from "next/link";

import { DecisionBanner } from "@/components/DecisionBanner";
import { MetricCard } from "@/components/MetricCard";
import { PageHeader } from "@/components/PageHeader";
import { SectionCard } from "@/components/SectionCard";
import { StatusBadge } from "@/components/StatusBadge";
import {
  AggregationStatus,
  CollectorRun,
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
  const [health, collectors, aggregation, scanner] = await Promise.all([
    fetchJson<HealthResponse>("/api/data-health"),
    fetchJson<CollectorResponse>("/api/collectors/status"),
    fetchJson<AggregationStatus>("/api/aggregation/status"),
    fetchJson<LiveScannerResponse>("/api/scanner/live?limit=200", { revalidateSeconds: 20 }).catch(() => null)
  ]);

  const lastRun = collectors.collectors[0];
  const lastError = collectors.last_errors[0];
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
    ? "Cek Signal dan evidence angka di Radar."
    : candidateCount > 0
      ? "Pantau Candidate, belum ada yang cukup kuat untuk dinaikkan."
      : "Tunggu cycle data berikutnya atau cek Data Health.";

  return (
    <div className="space-y-5">
      <PageHeader
        title="MarketLab Command Center"
        badge="READ-ONLY - bukan sinyal entry live"
        subtitle="Ringkasan cepat untuk baca market radar, kualitas data, dan status riset. Semua output tetap observasi read-only."
        updatedAt={fmtTime(health.latest.latest_futures_candle_time)}
      />

      <DecisionBanner
        title={signalCandidateCount > 0 ? "Ada Signal read-only" : candidateCount > 0 ? "Ada Candidate untuk dipantau" : "Belum ada Signal"}
        status={`Signal: ${signalCandidateCount}`}
        tone={signalCandidateCount > 0 ? "good" : "warn"}
        description={
          signalCandidateCount > 0
            ? "Signal tetap read-only: ada entry futures reference, risk reference, dan tidak ada order otomatis."
            : "Radar/Candidate bisa ada walau Signal masih kosong. Itu berarti setup terpantau, tapi belum lolos quality gate final."
        }
      />

      <section className="grid gap-3 md:grid-cols-2 xl:grid-cols-6">
        <MetricCard label="Signal" value={signalCandidateCount} helper="Final read-only, bukan order" tone={signalCandidateCount ? "good" : "warn"} />
        <MetricCard label="Candidate" value={candidateCount} helper="Konteks layak dipantau" tone="info" />
        <MetricCard label="Radar" value={radarCount} helper="Aktivitas awal" tone="info" />
        <MetricCard label="Risk Context" value={riskCount} helper="Campuran/risiko" tone="warn" />
        <MetricCard label="Data Ready" value={`${health.counts.READY || 0}/75`} helper="Symbol data utama fresh" tone="good" />
        <MetricCard label="Baseline" value={baselineCount} helper="Kontrol pembanding" />
      </section>

      <section className="grid gap-4 xl:grid-cols-[1.15fr_0.85fr]">
        <SectionCard
          title="Yang harus dicek sekarang"
          description="Prioritas kerja dashboard, bukan keputusan eksekusi."
          actions={<StatusBadge value="LEAN_CORE_LOOP" />}
        >
          <div className="grid gap-4 p-4 lg:grid-cols-2">
            <div className="rounded border border-line bg-field/40 p-4">
              <div className="text-xs font-semibold uppercase text-slate-500">Fokus sekarang</div>
              <div className="mt-2 text-lg font-bold text-ink">{primaryAction}</div>
              <div className="mt-3 space-y-2 text-sm leading-6">
                <ReasonRow label="Signal" value={`${signalCandidateCount} token`} />
                <ReasonRow label="Candidate" value={`${candidateCount} token`} />
                <ReasonRow label="Risk Context" value={`${riskCount} token`} />
                <ReasonRow label="Latest signal" value={latestSignal ? latestSignal.symbol : "-"} />
              </div>
            </div>
            <div className="rounded border border-line bg-field/40 p-4">
              <div className="text-xs font-semibold uppercase text-slate-500">Core process</div>
              <div className="mt-2 text-lg font-bold text-ink">Core ringan, riset legacy manual</div>
              <div className="mt-3 space-y-2 text-sm leading-6">
                <ReasonRow label="Latest 15m" value={fmtTime(aggregation.latest_15m_futures)} />
                <ReasonRow label="Data ready" value={`${health.counts.READY || 0}/75 symbol`} />
                <ReasonRow label="Request weight" value={String(collectors.request_usage.latest_used_weight_1m ?? "-")} />
                <ReasonRow label="Legacy gate" value="Manual only" />
              </div>
            </div>
            <div className="flex flex-wrap gap-2 pt-2">
              <Link className="rounded border border-line px-3 py-2 font-semibold hover:bg-field" href="/scanner">Open Radar</Link>
              <Link className="rounded border border-line px-3 py-2 font-semibold hover:bg-field" href="/signal-quality-lab">Open Quality Lab</Link>
              <Link className="rounded border border-line px-3 py-2 font-semibold hover:bg-field" href="/data-health">Open System Health</Link>
            </div>
          </div>
        </SectionCard>

        <SectionCard title="Alur keputusan" description="Urutan baca output MarketLab.">
          <div className="space-y-3 p-4">
            <PipelineStep title="Radar" value={`${radarCount} token`} description="Aktivitas awal, belum cukup untuk candidate." />
            <PipelineStep title="Candidate" value={`${candidateCount} token`} description="Konteks layak dipantau, masih butuh bukti." />
            <PipelineStep title="Signal" value={`${signalCandidateCount} token`} description="Final read-only dengan reference futures." />
            <PipelineStep title="Signal History" value="Paper-live" description="TP/SL, realistic R, dan forward integrity untuk hasil signal." />
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
