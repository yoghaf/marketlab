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
  Phase7FullBlockerAuditResponse,
  CandidateNumericEvidenceItem,
  CandidateNumericEvidenceResponse,
  fetchJson,
  fmtNumber
} from "@/lib/api";
import { compactReason, labelFor } from "@/lib/labels";
import { formatLocalDateTime } from "@/lib/time";

export default async function Phase6AuditPage() {
  let readiness: Phase6ReadinessResponse | null = null;
  let decision: Phase6DecisionResponse | null = null;
  let blockerAudit: Phase7FullBlockerAuditResponse | null = null;
  let evidence: CandidateNumericEvidenceResponse | null = null;
  let error: string | null = null;

  try {
    [readiness, decision, blockerAudit, evidence] = await Promise.all([
      fetchJson<Phase6ReadinessResponse>("/api/phase6/readiness", { revalidateSeconds: 20 }),
      fetchJson<Phase6DecisionResponse>("/api/phase6/phase7-decision", { revalidateSeconds: 20 }),
      fetchJson<Phase7FullBlockerAuditResponse>("/api/phase7/full-blocker-audit", { revalidateSeconds: 20 }).catch(() => null),
      fetchJson<CandidateNumericEvidenceResponse>("/api/phase7/candidate-evidence?limit=300").catch(() => null)
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
  const approved = readiness?.approved_count ?? blockerAudit?.rerun_result.approved_count ?? 0;
  const watchlist = readiness?.watchlist_count ?? blockerAudit?.rerun_result.watchlist_count ?? 0;
  const edgeOver010 = edgeBucket(blockerAudit, "0.10");
  const atr4h = blockerAudit?.atr_readiness["4h"]?.available_symbols ?? 0;
  const atr24h = blockerAudit?.atr_readiness["24h"]?.available_symbols ?? 0;
  const evidenceByKey = new Map((evidence?.items || []).map((item) => [candidateKey(item), item]));

  return (
    <div className="space-y-5">
      <PageHeader
        title="Phase 6 Audit"
        badge="READ-ONLY - bukan sinyal entry live"
        subtitle="Gate keputusan sebelum Phase 7. Halaman ini menjawab apakah data dan bukti sudah cukup, bukan memberi instruksi trading."
        updatedAt={formatLocalDateTime(readiness?.generated_at || blockerAudit?.generated_at)}
      />
      <div className="flex flex-wrap gap-2 text-sm">
        <a className="rounded border border-line bg-white px-3 py-2 font-semibold hover:bg-field" href="/strategy-arena">Strategy Test</a>
        <a className="rounded border border-line bg-white px-3 py-2 font-semibold hover:bg-field" href="/phase6-audit">Phase 6 Audit</a>
      </div>

      {error ? (
        <div className="rounded border border-stale bg-red-50 p-4 text-sm text-stale">{error}</div>
      ) : (
        <>
          <DecisionBanner
            title={phase7 === "HAS_CANDIDATES" ? "Ada kandidat untuk diuji Phase 7" : "Phase 7 belum aktif"}
            status={phase7}
            tone={phase7 === "HAS_CANDIDATES" ? "good" : "warn"}
            description={
              phase7 === "HAS_CANDIDATES"
                ? "Ada kandidat yang lolos audit. Ini tetap read-only dan belum menjadi sinyal live."
                : `Approved: ${approved}. Watchlist: ${watchlist}. Penyebab utama: ${labelFor(mainBlocker)}. Data 4h/24h dan edge belum cukup kuat.`
            }
          />

          <section className="grid gap-3 md:grid-cols-3 xl:grid-cols-6">
            <MetricCard label="Approved" value={approved} helper="Boleh masuk uji Phase 7" tone={approved > 0 ? "good" : "warn"} />
            <MetricCard label="Watchlist" value={watchlist} helper="Pantauan, belum aktif" tone="info" />
            <MetricCard label="Rejected" value={readiness?.rejected_count ?? 0} helper="Belum lolos gate" tone="warn" />
            <MetricCard label="Highest Score" value={blockerAudit?.phase6_scoring.highest_score ?? "-"} helper="Butuh score memadai" />
            <MetricCard label="Edge > 0.10R" value={edgeOver010} helper="Jumlah bukti edge kuat" tone={edgeOver010 > 0 ? "good" : "warn"} />
            <MetricCard label="ATR 4h / 24h" value={`${atr4h} / ${atr24h}`} helper="Kesiapan timeframe besar" tone={atr4h > 0 && atr24h > 0 ? "good" : "warn"} />
          </section>

          <SectionCard title="Feature readiness" description="Timeframe tinggi tidak dipaksa siap. Status teknis tetap tersedia untuk audit.">
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
                  {candidateRows.map((row, index) => (
                    <CandidateRow
                      key={`${row.symbol}-${row.timeframe}-${row.setup_type}-${index}`}
                      row={row}
                      evidence={evidenceByKey.get(candidateKey(row))}
                    />
                  ))}
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

function CandidateRow({ row, evidence }: { row: Phase7CandidateDecisionRow; evidence?: CandidateNumericEvidenceItem }) {
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
          <summary className="cursor-pointer font-semibold">Detail angka</summary>
          <div className="mt-2 space-y-3">
            <div>Raw setup: {row.mapped_setup_family || row.setup_type}</div>
            <div>Direction: {row.direction}</div>
            <div>ATR/RR: {row.recommended_atr_mult ?? "-"}x / {row.recommended_rr ?? "-"} / {row.recommended_arena_horizon || "-"}</div>
            <div>Setup R: {fmtR(row.setup_pessR)} Baseline R: {fmtR(row.baseline_pessR)}</div>
            {evidence ? <EvidenceDetail evidence={evidence} /> : <div>Belum tersedia di artifact numeric evidence.</div>}
          </div>
        </details>
      </td>
    </tr>
  );
}

function EvidenceDetail({ evidence }: { evidence: CandidateNumericEvidenceItem }) {
  return (
    <div className="space-y-3 rounded border border-line bg-field p-3">
      <div>
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
            {evidence.numeric_evidence.map((item) => (
              <tr key={`${item.category}-${item.metric}-${item.label}`}>
                <td>{item.label}</td>
                <td>{requiredText(item.required_operator, item.required_value, item.unit)}</td>
                <td>{item.actual_detail || String(item.actual_value ?? "Belum tersedia di artifact")}</td>
                <td><StatusBadge value={item.result} /></td>
                <td>{item.explanation}</td>
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
            {evidence.phase7_checklist.map((item) => (
              <tr key={item.gate}>
                <td>{item.gate}</td>
                <td>{item.required}</td>
                <td>{String(item.actual ?? "Belum tersedia di artifact")}</td>
                <td><StatusBadge value={item.result} /></td>
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

function decisionText(value: string): string {
  if (value === "PHASE7_READY") return "Siap diuji Phase 7";
  if (value === "WATCHLIST_FOR_MORE_DATA") return "Pantau dulu";
  if (value === "RADAR_ONLY") return "Pantauan saja";
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

function edgeBucket(data: Phase7FullBlockerAuditResponse | null, needle: string): number {
  const buckets = data?.edge.edge_buckets || {};
  const found = Object.entries(buckets).find(([key]) => key.includes(needle));
  return found?.[1] ?? 0;
}

function candidateKey(item: { symbol: string; timeframe: string }) {
  return `${item.symbol}-${item.timeframe}`;
}

function requiredText(operator: string, value: string | number | boolean | string[] | null, unit: string) {
  const rendered = Array.isArray(value) ? value.join(", ") : String(value ?? "-");
  return `${operator} ${rendered} ${unit}`.trim();
}
