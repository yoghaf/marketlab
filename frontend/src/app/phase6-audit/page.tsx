import { DecisionBanner } from "@/components/DecisionBanner";
import { EmptyState } from "@/components/EmptyState";
import { MetricCard } from "@/components/MetricCard";
import { PageHeader } from "@/components/PageHeader";
import { SectionCard } from "@/components/SectionCard";
import { StatusBadge } from "@/components/StatusBadge";
import {
  Phase6DecisionResponse,
  Phase6ReadinessResponse,
  Phase7CandidateDecisionRow,
  fetchJson,
  fmtNumber,
  fmtTime
} from "@/lib/api";
import { compactReason, labelFor } from "@/lib/labels";

export default async function Phase6AuditPage() {
  let readiness: Phase6ReadinessResponse | null = null;
  let decision: Phase6DecisionResponse | null = null;
  let error: string | null = null;
  try {
    [readiness, decision] = await Promise.all([
      fetchJson<Phase6ReadinessResponse>("/api/phase6/readiness", { revalidateSeconds: 20 }),
      fetchJson<Phase6DecisionResponse>("/api/phase6/phase7-decision", { revalidateSeconds: 20 })
    ]);
  } catch (err) {
    error = err instanceof Error ? err.message : "Phase 6 artifact belum tersedia";
  }

  const featureRows = Object.values(readiness?.feature_readiness.by_timeframe || {});
  const candidateRows = [
    ...(decision?.approved_candidates || []),
    ...(decision?.watchlist_candidates || []),
    ...(decision?.rejected_candidates || []).slice(0, 20)
  ];
  const phase7 = decision?.phase7_decision || "NO_PHASE7_CANDIDATE_YET";
  const mainBlocker = topBlocker(decision?.blocked_reasons || {});

  return (
    <div className="space-y-5">
      <PageHeader
        title="Phase 6 Audit"
        badge="AUDIT MODE - BUKAN SINYAL ENTRY LIVE"
        subtitle="Gate keputusan sebelum shadow forward-test. Halaman ini menjawab boleh lanjut Phase 7 atau belum."
        updatedAt={fmtTime(readiness?.generated_at)}
      />
      <div className="flex flex-wrap gap-2 text-sm">
        <a className="rounded border border-line bg-white px-3 py-2 font-semibold hover:bg-field" href="/strategy-arena">Strategy Arena</a>
        <a className="rounded border border-line bg-white px-3 py-2 font-semibold hover:bg-field" href="/phase6-audit">Phase 6 Audit</a>
      </div>

      {error ? (
        <div className="rounded border border-stale bg-red-50 p-4 text-sm text-stale">{error}</div>
      ) : (
        <>
          <DecisionBanner
            title={phase7 === "HAS_CANDIDATES" ? "Phase 7 boleh disiapkan" : "Phase 7 belum boleh"}
            status={phase7}
            tone={phase7 === "HAS_CANDIDATES" ? "good" : "warn"}
            description={
              phase7 === "HAS_CANDIDATES"
                ? "Ada candidate yang lolos score audit. Tetap shadow forward-test, bukan live execution."
                : `Belum ada candidate score cukup. Blocker utama: ${labelFor(mainBlocker)}. Arena masih noisy dan 4h/24h belum siap.`
            }
          />

          <section className="grid gap-3 md:grid-cols-3 xl:grid-cols-6">
            <MetricCard label="Phase 6 Status" value={readiness?.phase6_status || "-"} tone="good" />
            <MetricCard label="Phase 7 Decision" value={labelFor(phase7)} tone={phase7 === "HAS_CANDIDATES" ? "good" : "warn"} />
            <MetricCard label="Approved" value={readiness?.approved_count ?? 0} />
            <MetricCard label="Watchlist" value={readiness?.watchlist_count ?? 0} tone="info" />
            <MetricCard label="Rejected" value={readiness?.rejected_count ?? 0} tone="warn" />
            <MetricCard label="Main Blocker" value={labelFor(mainBlocker)} tone="warn" />
          </section>

          <SectionCard title="Feature readiness" description="Timeframe tinggi tidak dipaksa siap.">
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Timeframe</th>
                    <th>Ready</th>
                    <th>Partial</th>
                    <th>Missing Candles</th>
                    <th>Missing ATR</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {featureRows.map((row) => (
                    <tr key={row.timeframe}>
                      <td className="font-semibold">{row.timeframe}</td>
                      <td>{row.ready_count}</td>
                      <td>{row.partial_data_count}</td>
                      <td>{row.missing_candles_count}</td>
                      <td>{row.missing_atr_count}</td>
                      <td><StatusBadge value={row.readiness_status} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </SectionCard>

          <SectionCard title="Phase 7 candidate table" description="Approved dan watchlist tampil dulu; rejected dibatasi agar halaman ringan.">
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Symbol</th>
                    <th>TF</th>
                    <th>Setup</th>
                    <th>Score</th>
                    <th>Edge</th>
                    <th>Arena</th>
                    <th>Decision</th>
                    <th>Reason</th>
                  </tr>
                </thead>
                <tbody>
                  {candidateRows.map((row, index) => <CandidateRow key={`${row.symbol}-${row.timeframe}-${row.setup_type}-${index}`} row={row} />)}
                  {!candidateRows.length && (
                    <tr>
                      <td colSpan={8}><EmptyState title="Belum ada candidate decision" detail="Jalankan Phase 6 readiness audit script." /></td>
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

function CandidateRow({ row }: { row: Phase7CandidateDecisionRow }) {
  return (
    <tr>
      <td className="font-semibold">{row.symbol}</td>
      <td>{row.timeframe}</td>
      <td className="max-w-52 truncate" title={row.mapped_setup_family || row.setup_type}>{labelFor(row.mapped_setup_family || row.setup_type)}</td>
      <td>{row.total_score ?? "-"}</td>
      <td>{fmtR(row.edge_vs_baseline)}</td>
      <td><StatusBadge value={row.arena_verdict} /></td>
      <td><StatusBadge value={row.phase7_verdict} /></td>
      <td className="min-w-72">
        <div>{decisionText(row.phase7_verdict)}</div>
        <div className="mt-1 text-xs text-slate-500">{compactReason(row.reason)}</div>
        <details className="mt-1 text-xs text-slate-500">
          <summary className="cursor-pointer font-semibold">Show technical labels</summary>
          <div className="mt-2 space-y-1">
            <div>Raw setup: {row.mapped_setup_family || row.setup_type}</div>
            <div>Direction: {row.direction}</div>
            <div>ATR/RR: {row.recommended_atr_mult ?? "-"}x / {row.recommended_rr ?? "-"} / {row.recommended_arena_horizon || "-"}</div>
            <div>Setup R: {fmtR(row.setup_pessR)} Baseline R: {fmtR(row.baseline_pessR)}</div>
          </div>
        </details>
      </td>
    </tr>
  );
}

function decisionText(value: string): string {
  if (value === "PHASE7_READY") return "Siap shadow forward-test";
  if (value === "WATCHLIST_FOR_MORE_DATA") return "Pantau dulu";
  if (value === "RADAR_ONLY") return "Radar saja";
  if (value === "REJECT_FOR_PHASE7") return "Ditolak untuk Phase 7";
  return labelFor(value);
}

function fmtR(value?: number | null): string {
  if (value === null || value === undefined) return "-";
  return `${fmtNumber(value)}R`;
}

function topBlocker(blockers: Record<string, number>): string {
  const sorted = Object.entries(blockers).sort((a, b) => b[1] - a[1]);
  return sorted[0]?.[0] || "NO_PHASE7_CANDIDATE_YET";
}
