import { EmptyState } from "@/components/EmptyState";
import { FilterBar, SelectFilter } from "@/components/FilterBar";
import { MetricCard } from "@/components/MetricCard";
import { PageHeader } from "@/components/PageHeader";
import { SectionCard } from "@/components/SectionCard";
import { StatusBadge } from "@/components/StatusBadge";
import {
  SignalFactoryCandidatesResponse,
  SignalFactoryCandidate,
  SignalFactorySummaryResponse,
  CandidateNumericEvidenceItem,
  CandidateNumericEvidenceResponse,
  fetchJson,
  fmtNumber
} from "@/lib/api";
import { compactReason, labelFor } from "@/lib/labels";
import { formatLocalDateTime } from "@/lib/time";

type SignalFactorySearchParams = Promise<Record<string, string | string[] | undefined>>;

const timeframes = ["15m", "1h", "4h", "24h"];
const setupTypes = ["MID_SHORT", "MID_LONG", "EARLY_SHORT", "EARLY_LONG", "SQUEEZE", "TRAP_FADE", "NO_SETUP", "BLOCKED_DATA"];
const directions = ["BEARISH_CONTEXT", "BULLISH_CONTEXT", "MIXED_CONTEXT"];
const confidences = ["HIGH", "MEDIUM", "LOW"];

export default async function SignalFactoryPage({ searchParams }: { searchParams: SignalFactorySearchParams }) {
  const params = await searchParams;
  const filters = {
    timeframe: firstParam(params.timeframe),
    setupType: firstParam(params.setup_type),
    direction: firstParam(params.direction),
    confidence: firstParam(params.confidence),
    status: firstParam(params.status),
    limit: normalizeNumber(firstParam(params.limit), 50)
  };
  const query = new URLSearchParams();
  if (filters.timeframe) query.set("timeframe", filters.timeframe);
  if (filters.setupType) query.set("setup_type", filters.setupType);
  if (filters.direction) query.set("direction", filters.direction);
  if (filters.confidence) query.set("confidence", filters.confidence);
  if (filters.status) query.set("status", filters.status);
  query.set("limit", String(filters.limit));

  let summary: SignalFactorySummaryResponse | null = null;
  let candidates: SignalFactoryCandidatesResponse | null = null;
  let evidence: CandidateNumericEvidenceResponse | null = null;
  let error: string | null = null;
  try {
    [summary, candidates, evidence] = await Promise.all([
      fetchJson<SignalFactorySummaryResponse>("/api/signal-factory/v1/summary", { revalidateSeconds: 20 }),
      fetchJson<SignalFactoryCandidatesResponse>(`/api/signal-factory/v1/candidates?${query.toString()}`, { revalidateSeconds: 20 }),
      fetchJson<CandidateNumericEvidenceResponse>(evidencePath(filters), { revalidateSeconds: 20 }).catch(() => null)
    ]);
  } catch (err) {
    error = err instanceof Error ? err.message : "Signal Factory artifact belum tersedia";
  }
  const evidenceByKey = new Map((evidence?.items || []).map((item) => [candidateKey(item), item]));

  return (
    <div className="space-y-5">
      <PageHeader
        title="Signal Factory"
        badge="TEST MODE - BUKAN SINYAL ENTRY LIVE"
        subtitle="Kandidat anomaly multi-timeframe read-only. Lihat setup utama di tabel; evidence teknis tetap tersedia di detail."
        updatedAt={formatLocalDateTime(summary?.generated_at)}
      />

      {error ? (
        <div className="rounded border border-stale bg-red-50 p-4 text-sm text-stale">{error}</div>
      ) : (
        <>
          <section className="grid gap-3 md:grid-cols-3 xl:grid-cols-6">
            <MetricCard label="Signal" value={summary?.candidate_status_counts.SIGNAL_CANDIDATE ?? 0} tone="info" />
            <MetricCard label="Radar" value={summary?.candidate_status_counts.RADAR_ONLY ?? 0} />
            <MetricCard label="Blocked" value={(summary?.candidate_status_counts.BLOCKED_DATA ?? 0) + (summary?.candidate_status_counts.TIMEFRAME_NOT_READY ?? 0)} tone="warn" />
            <MetricCard label="Conflict" value={summary?.conflict_count ?? 0} tone={summary?.conflict_count ? "warn" : "good"} />
            <MetricCard label="Timeframe ready" value={`${summary?.feature_status_counts.PARTIAL_DATA ?? 0} partial`} helper="READY/PARTIAL dari artifact" />
            <MetricCard label="Rows shown" value={candidates?.count ?? 0} helper={`Limit ${filters.limit}`} />
          </section>

          <FilterBar>
            <SelectFilter label="Timeframe" name="timeframe" value={filters.timeframe || ""} options={timeframes} emptyLabel="All timeframe" />
            <SelectFilter label="Setup" name="setup_type" value={filters.setupType || ""} options={setupTypes} emptyLabel="All setup" />
            <SelectFilter label="Arah" name="direction" value={filters.direction || ""} options={directions} emptyLabel="All arah" />
            <SelectFilter label="Confidence" name="confidence" value={filters.confidence || ""} options={confidences} emptyLabel="All confidence" />
            <SelectFilter label="Status" name="status" value={filters.status || ""} options={["SIGNAL_CANDIDATE", "RADAR_ONLY", "CONFLICTED", "BLOCKED_DATA", "TIMEFRAME_NOT_READY"]} emptyLabel="All status" />
            <label className="grid gap-1 text-sm">
              <span className="font-semibold text-slate-600">Limit</span>
              <input className="rounded border border-line px-3 py-2" min={1} max={200} name="limit" type="number" defaultValue={filters.limit} />
            </label>
          </FilterBar>

          <SectionCard title="Candidate table" description="Raw anomaly dan technical label ada di expandable detail.">
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Symbol</th>
                    <th>TF</th>
                    <th>Setup</th>
                    <th>Arah</th>
                    <th>Status</th>
                    <th>Confidence</th>
                    <th>Alasan singkat</th>
                    <th>Flow</th>
                    <th>Relative Strength</th>
                    <th>ATR Ref</th>
                  </tr>
                </thead>
                <tbody>
                  {candidates?.items.map((item) => (
                    <CandidateRow
                      key={`${item.symbol}-${item.timeframe}-${item.window_end}-${item.setup_type}`}
                      item={item}
                      evidence={evidenceByKey.get(candidateKey(item))}
                    />
                  ))}
                  {!candidates?.items.length && (
                    <tr>
                      <td colSpan={10}><EmptyState title="Tidak ada kandidat" detail="Coba ubah filter atau refresh artifact Signal Factory." /></td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </SectionCard>
        </>
      )}
    </div>
  );
}

function CandidateRow({ item, evidence }: { item: SignalFactoryCandidate; evidence?: CandidateNumericEvidenceItem }) {
  return (
    <tr>
      <td className="font-semibold">{item.symbol}</td>
      <td>{item.timeframe}</td>
      <td className="max-w-44 truncate" title={item.setup_type}>{labelFor(item.setup_type)}</td>
      <td><StatusBadge value={item.direction} /></td>
      <td><StatusBadge value={item.candidate_status} /></td>
      <td>{labelFor(item.confidence)}</td>
      <td className="min-w-72">
        <div>{compactReason(item.reason)}</div>
        <details className="mt-1 text-xs text-slate-500">
          <summary className="cursor-pointer font-semibold">Detail angka</summary>
          <div className="mt-2 space-y-3">
            <div>Raw setup: {item.setup_type}</div>
            <div>Feature status: {item.feature_status}</div>
            <div>Conflict: {item.conflict_status || "NONE"}</div>
            <div>Anomaly: {(item.evidence.anomalies || []).join(", ") || "-"}</div>
            <div>Reason: {item.reason}</div>
            {evidence ? <EvidenceDetail evidence={evidence} /> : <div>Belum tersedia di artifact numeric evidence.</div>}
          </div>
        </details>
      </td>
      <td>{flowLabel(item)}</td>
      <td>{labelFor(item.evidence.relative_strength)}</td>
      <td>
        {item.atr_reference_timeframe}
        <div className="mt-1 text-xs text-slate-500">{labelFor(item.atr_reference_status)}</div>
      </td>
    </tr>
  );
}

function EvidenceDetail({ evidence }: { evidence: CandidateNumericEvidenceItem }) {
  return (
    <div className="space-y-3 rounded border border-line bg-field p-3">
      <div className="grid gap-1">
        <div className="font-semibold text-ink">Decision summary</div>
        <div>Final status: {labelFor(evidence.final_decision)}</div>
        <div>READ-ONLY / NOT ENTRY SIGNAL: {String(evidence.not_live_signal)}</div>
        <div>Main blockers: {evidence.blocking_reasons.map(labelFor).join(", ") || "-"}</div>
      </div>
      <div className="overflow-x-auto">
        <table className="min-w-[720px] text-xs">
          <thead>
            <tr>
              <th>Metric</th>
              <th>Required</th>
              <th>Actual</th>
              <th>Result</th>
              <th>Explanation</th>
            </tr>
          </thead>
          <tbody>
            {evidence.numeric_evidence.map((row) => (
              <tr key={`${row.category}-${row.metric}-${row.label}`}>
                <td>{row.label}</td>
                <td>{requiredText(row.required_operator, row.required_value, row.unit)}</td>
                <td>{row.actual_detail || String(row.actual_value ?? "Belum tersedia di artifact")}</td>
                <td><StatusBadge value={row.result} /></td>
                <td>{row.explanation}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="overflow-x-auto">
        <table className="min-w-[560px] text-xs">
          <thead>
            <tr>
              <th>Gate</th>
              <th>Required</th>
              <th>Actual</th>
              <th>Result</th>
            </tr>
          </thead>
          <tbody>
            {evidence.phase7_checklist.map((row) => (
              <tr key={row.gate}>
                <td>{row.gate}</td>
                <td>{row.required}</td>
                <td>{String(row.actual ?? "Belum tersedia di artifact")}</td>
                <td><StatusBadge value={row.result} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div>
        <div className="font-semibold text-ink">What needs to improve</div>
        <ul className="mt-1 list-disc space-y-1 pl-4">
          {evidence.what_needs_to_improve.map((item) => <li key={item}>{item}</li>)}
        </ul>
      </div>
    </div>
  );
}

function flowLabel(item: SignalFactoryCandidate): string {
  const flows = [];
  if (item.evidence.futures_led_flag) flows.push("Futures-led");
  if (item.evidence.spot_led_flag) flows.push("Spot-led");
  if (item.evidence.volume_spike) flows.push("Volume spike");
  const oi = item.evidence.oi_change_pct;
  if (oi !== null && oi !== undefined) flows.push(`OI ${fmtNumber(oi)}%`);
  return flows.join(" / ") || "-";
}

function firstParam(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

function normalizeNumber(value: string | undefined, fallback: number): number {
  const parsed = Number(value || fallback);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.min(Math.max(Math.trunc(parsed), 1), 200);
}

function candidateKey(item: { symbol: string; timeframe: string }) {
  return `${item.symbol}-${item.timeframe}`;
}

function evidencePath(filters: { timeframe?: string; status?: string; limit: number }) {
  const query = new URLSearchParams();
  if (filters.timeframe) query.set("timeframe", filters.timeframe);
  if (filters.status) query.set("status", filters.status);
  query.set("limit", String(Math.max(filters.limit, 200)));
  return `/api/phase7/candidate-evidence?${query.toString()}`;
}

function requiredText(operator: string, value: string | number | boolean | string[] | null, unit: string) {
  const rendered = Array.isArray(value) ? value.join(", ") : String(value ?? "-");
  return `${operator} ${rendered} ${unit}`.trim();
}
