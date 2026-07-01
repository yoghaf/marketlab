import { Metric } from "@/components/Metric";
import { StatusBadge } from "@/components/StatusBadge";
import {
  SignalFactoryCandidatesResponse,
  SignalFactoryCandidate,
  SignalFactorySummaryResponse,
  fetchJson,
  fmtNumber,
  fmtTime
} from "@/lib/api";

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
    limit: normalizeNumber(firstParam(params.limit), 100)
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
  let error: string | null = null;
  try {
    [summary, candidates] = await Promise.all([
      fetchJson<SignalFactorySummaryResponse>("/api/signal-factory/v1/summary"),
      fetchJson<SignalFactoryCandidatesResponse>(`/api/signal-factory/v1/candidates?${query.toString()}`)
    ]);
  } catch (err) {
    error = err instanceof Error ? err.message : "Signal Factory artifact belum tersedia";
  }

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold tracking-normal">Signal Factory</h1>
          <div className="mt-2 inline-flex rounded border border-blue-700 bg-blue-50 px-3 py-1 text-xs font-bold text-blue-700">
            TEST MODE - BUKAN SINYAL ENTRY LIVE
          </div>
          <p className="mt-2 max-w-3xl text-sm text-slate-600">
            Factory ini menampilkan kandidat anomaly multi-timeframe read-only dari data MarketLab. Output dipakai untuk observasi dan validasi konteks, bukan instruksi eksekusi.
          </p>
        </div>
        <div className="text-right text-xs text-slate-500">
          Artifact: {fmtTime(summary?.generated_at)}
        </div>
      </div>

      {error ? (
        <div className="border border-stale bg-red-50 p-4 text-sm text-stale">{error}</div>
      ) : (
        <>
          <section className="grid gap-3 md:grid-cols-4 xl:grid-cols-8">
            <Metric label="Feature Rows" value={summary?.feature_count ?? 0} />
            <Metric label="Candidate Rows" value={summary?.candidate_count ?? 0} />
            <Metric label="Signal Candidates" value={summary?.candidate_status_counts.SIGNAL_CANDIDATE ?? 0} />
            <Metric label="Radar Only" value={summary?.candidate_status_counts.RADAR_ONLY ?? 0} />
            <Metric label="Conflicted" value={summary?.candidate_status_counts.CONFLICTED ?? 0} />
            <Metric label="Missing Data" value={summary?.missing_data_count ?? 0} />
            <Metric label="Conflicts" value={summary?.conflict_count ?? 0} />
            <Metric label="Rows Shown" value={candidates?.count ?? 0} />
          </section>

          <form className="grid gap-3 border border-line bg-white p-4 md:grid-cols-3 xl:grid-cols-7" method="get">
            <SelectField label="Timeframe" name="timeframe" value={filters.timeframe || ""} options={timeframes} emptyLabel="All timeframe" />
            <SelectField label="Setup" name="setup_type" value={filters.setupType || ""} options={setupTypes} emptyLabel="All setup" />
            <SelectField label="Arah" name="direction" value={filters.direction || ""} options={directions} emptyLabel="All arah" />
            <SelectField label="Confidence" name="confidence" value={filters.confidence || ""} options={confidences} emptyLabel="All confidence" />
            <SelectField label="Status" name="status" value={filters.status || ""} options={["SIGNAL_CANDIDATE", "RADAR_ONLY", "CONFLICTED", "BLOCKED_DATA", "TIMEFRAME_NOT_READY"]} emptyLabel="All status" />
            <label className="grid gap-1 text-sm">
              <span className="font-semibold text-slate-600">Limit</span>
              <input className="border border-line px-3 py-2" min={1} name="limit" type="number" defaultValue={filters.limit} />
            </label>
            <div className="flex items-end">
              <button className="border border-line px-4 py-2 text-sm font-semibold hover:bg-field" type="submit">
                Apply
              </button>
            </div>
          </form>

          <div className="overflow-x-auto border border-line bg-white">
            <table>
              <thead>
                <tr>
                  <th>Symbol</th>
                  <th>Timeframe</th>
                  <th>Setup</th>
                  <th>Arah</th>
                  <th>Confidence</th>
                  <th>Alasan</th>
                  <th>Relative Strength</th>
                  <th>Flow</th>
                  <th>ATR Ref</th>
                  <th>Status</th>
                  <th>Updated</th>
                </tr>
              </thead>
              <tbody>
                {candidates?.items.map((item) => (
                  <CandidateRow key={`${item.symbol}-${item.timeframe}-${item.window_end}-${item.setup_type}`} item={item} />
                ))}
                {!candidates?.items.length && (
                  <tr>
                    <td colSpan={11}>Tidak ada candidate yang cocok dengan filter.</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}

function CandidateRow({ item }: { item: SignalFactoryCandidate }) {
  return (
    <tr>
      <td className="font-semibold">{item.symbol}</td>
      <td>{item.timeframe}</td>
      <td>{item.setup_type}</td>
      <td>{item.direction}</td>
      <td>{item.confidence}</td>
      <td className="min-w-80">
        <div className="space-y-1">
          <p>{item.reason}</p>
          <p className="text-xs text-slate-500">{(item.evidence.anomalies || []).join(", ") || "-"}</p>
          <span className="inline-flex rounded border border-blue-700 bg-blue-50 px-2 py-0.5 text-xs font-bold text-blue-700">
            READ-ONLY / NOT ENTRY SIGNAL
          </span>
        </div>
      </td>
      <td>{item.evidence.relative_strength || "-"}</td>
      <td>{flowLabel(item)}</td>
      <td>
        {item.atr_reference_timeframe}
        <div className="mt-1 text-xs text-slate-500">{item.atr_reference_status}</div>
      </td>
      <td>
        <div className="space-y-1">
          <StatusBadge value={item.candidate_status} />
          <StatusBadge value={item.feature_status} />
          {item.conflict_status && item.conflict_status !== "NONE" && <StatusBadge value={item.conflict_status} />}
        </div>
      </td>
      <td>{fmtTime(item.window_end)}</td>
    </tr>
  );
}

function SelectField({
  label,
  name,
  value,
  options,
  emptyLabel
}: {
  label: string;
  name: string;
  value: string;
  options: string[];
  emptyLabel: string;
}) {
  return (
    <label className="grid gap-1 text-sm">
      <span className="font-semibold text-slate-600">{label}</span>
      <select className="border border-line bg-white px-3 py-2" name={name} defaultValue={value}>
        <option value="">{emptyLabel}</option>
        {options.map((option) => (
          <option key={option} value={option}>{option}</option>
        ))}
      </select>
    </label>
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
  return Number.isFinite(parsed) ? parsed : fallback;
}
