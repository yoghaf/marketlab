import { Metric } from "@/components/Metric";
import { StatusBadge } from "@/components/StatusBadge";
import {
  Phase6DecisionResponse,
  Phase6ReadinessResponse,
  Phase7CandidateDecisionRow,
  fetchJson,
  fmtNumber,
  fmtTime
} from "@/lib/api";

export default async function Phase6AuditPage() {
  let readiness: Phase6ReadinessResponse | null = null;
  let decision: Phase6DecisionResponse | null = null;
  let error: string | null = null;
  try {
    [readiness, decision] = await Promise.all([
      fetchJson<Phase6ReadinessResponse>("/api/phase6/readiness"),
      fetchJson<Phase6DecisionResponse>("/api/phase6/phase7-decision")
    ]);
  } catch (err) {
    error = err instanceof Error ? err.message : "Phase 6 artifact belum tersedia";
  }

  const featureRows = Object.values(readiness?.feature_readiness.by_timeframe || {});
  const candidateRows = [
    ...(decision?.approved_candidates || []),
    ...(decision?.watchlist_candidates || []),
    ...(decision?.rejected_candidates || []).slice(0, 40)
  ];

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold tracking-normal">Phase 6 Audit</h1>
          <div className="mt-2 inline-flex rounded border border-blue-700 bg-blue-50 px-3 py-1 text-xs font-bold text-blue-700">
            AUDIT MODE - BUKAN SINYAL ENTRY LIVE
          </div>
          <p className="mt-2 max-w-3xl text-sm text-slate-600">
            Readiness gate untuk menentukan setup/timeframe yang boleh masuk shadow forward-test. Dashboard ini membaca artifact audit, bukan menghitung ulang dan bukan instruksi eksekusi.
          </p>
        </div>
        <div className="text-right text-xs text-slate-500">Artifact: {fmtTime(readiness?.generated_at)}</div>
      </div>

      {error ? (
        <div className="border border-stale bg-red-50 p-4 text-sm text-stale">{error}</div>
      ) : (
        <>
          <section className="grid gap-3 md:grid-cols-4 xl:grid-cols-8">
            <Metric label="Phase 6 Status" value={readiness?.phase6_status || "-"} />
            <Metric label="Phase 7 Decision" value={decisionLabel(readiness?.phase7_decision)} />
            <Metric label="Eligible Candidates" value={readiness?.candidate_readiness.eligible_candidate_count ?? 0} />
            <Metric label="Approved" value={readiness?.approved_count ?? 0} />
            <Metric label="Watchlist" value={readiness?.watchlist_count ?? 0} />
            <Metric label="Rejected" value={readiness?.rejected_count ?? 0} />
            <Metric label="Best Setup" value={readiness?.best_setup?.mapped_setup_family || readiness?.best_setup?.setup_type || "-"} />
            <Metric label="Most Blocked TF" value={readiness?.most_blocked_timeframe || "-"} />
          </section>

          <section className="overflow-x-auto border border-line bg-white">
            <div className="border-b border-line p-4">
              <h2 className="text-lg font-bold">Feature readiness</h2>
            </div>
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
          </section>

          <section className="overflow-x-auto border border-line bg-white">
            <div className="border-b border-line p-4">
              <h2 className="text-lg font-bold">Phase 7 candidate decision</h2>
            </div>
            <table>
              <thead>
                <tr>
                  <th>Symbol</th>
                  <th>Timeframe</th>
                  <th>Setup</th>
                  <th>Arah</th>
                  <th>Confidence</th>
                  <th>Score</th>
                  <th>Edge vs Baseline</th>
                  <th>Arena Verdict</th>
                  <th>Relative Strength</th>
                  <th>Decision</th>
                  <th>Reason</th>
                </tr>
              </thead>
              <tbody>
                {candidateRows.map((row, index) => (
                  <CandidateRow key={`${row.symbol}-${row.timeframe}-${row.setup_type}-${index}`} row={row} />
                ))}
                {!candidateRows.length && (
                  <tr>
                    <td colSpan={11}>Belum ada candidate decision artifact.</td>
                  </tr>
                )}
              </tbody>
            </table>
          </section>
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
      <td>{row.mapped_setup_family || row.setup_type}</td>
      <td>{row.direction}</td>
      <td>{row.confidence}</td>
      <td>{row.total_score ?? "-"}</td>
      <td>{fmtR(row.edge_vs_baseline)}</td>
      <td>{row.arena_verdict || "-"}</td>
      <td>{relativeLabel(row)}</td>
      <td><StatusBadge value={row.phase7_verdict} /></td>
      <td className="min-w-80">
        <div className="space-y-1">
          <p>{decisionText(row.phase7_verdict)}</p>
          <p className="text-xs text-slate-500">{row.reason || "-"}</p>
          {row.recommended_arena_horizon && (
            <p className="text-xs text-slate-500">
              ATR model {row.recommended_atr_mult}x / RR {row.recommended_rr} / horizon {row.recommended_arena_horizon}
            </p>
          )}
        </div>
      </td>
    </tr>
  );
}

function decisionLabel(value?: string | null): string {
  if (value === "HAS_CANDIDATES") return "Ada kandidat shadow";
  if (value === "NO_PHASE7_CANDIDATE_YET") return "Belum ada kandidat";
  return value || "-";
}

function decisionText(value: string): string {
  if (value === "PHASE7_READY") return "Siap shadow forward-test";
  if (value === "WATCHLIST_FOR_MORE_DATA") return "Pantau dulu";
  if (value === "RADAR_ONLY") return "Radar saja";
  if (value === "REJECT_FOR_PHASE7") return "Ditolak untuk Phase 7";
  return value;
}

function relativeLabel(_row: Phase7CandidateDecisionRow): string {
  return "Lihat edge audit";
}

function fmtR(value?: number | null): string {
  if (value === null || value === undefined) return "-";
  return `${fmtNumber(value)}R`;
}
