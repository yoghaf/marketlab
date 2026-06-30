import { Metric } from "@/components/Metric";
import { StatusBadge } from "@/components/StatusBadge";
import {
  StrategyArenaLeaderboardResponse,
  StrategyArenaResult,
  StrategyArenaResultsResponse,
  fetchJson,
  fmtNumber,
  fmtTime
} from "@/lib/api";

type ArenaSearchParams = Promise<Record<string, string | string[] | undefined>>;

const setupOptions = [
  "MID_SHORT_FUTURES_LED",
  "MID_SHORT_NON_FUTURES_LED",
  "EARLY_SHORT",
  "MID_LONG",
  "EARLY_LONG",
  "SQUEEZE_CONTINUATION",
  "SQUEEZE_FADE",
  "TRAP_FADE",
  "NO_SIGNAL_BASELINE_SHORT",
  "NO_SIGNAL_BASELINE_LONG"
];

const verdictOptions = [
  "PROMISING_FOR_FORWARD_TEST",
  "MONITOR_MORE",
  "NOISY",
  "REJECT",
  "INSUFFICIENT_SAMPLE"
];

const setupDescriptions: Record<string, string> = {
  MID_SHORT_FUTURES_LED:
    "Mid Short + Futures Dominan adalah kondisi bearish yang didukung aktivitas futures lebih dominan daripada spot. Setup ini diuji sebagai short test, bukan sinyal entry live.",
  MID_SHORT_NON_FUTURES_LED:
    "Mid Short non-Futures Dominan adalah kondisi bearish tanpa bukti futures-led eksplisit. Setup ini dipakai untuk membandingkan apakah futures-led memang memberi konteks lebih bersih.",
  EARLY_SHORT:
    "Early Short adalah konteks bearish awal. Sample biasanya lebih kecil dan diperlakukan sebagai observasi awal.",
  MID_LONG:
    "Mid Long adalah kondisi bullish 15m dan 1h yang selaras. Hasilnya tetap test offline dan bukan instruksi live.",
  EARLY_LONG:
    "Early Long adalah konteks bullish awal. Sample kecil harus dibaca hati-hati.",
  SQUEEZE_CONTINUATION:
    "Squeeze Continuation menguji apakah konteks squeeze berlanjut mengikuti impulse candle.",
  SQUEEZE_FADE:
    "Squeeze Fade menguji apakah konteks squeeze lebih sering memudar berlawanan dengan impulse candle.",
  TRAP_FADE:
    "Trap Fade menguji fade terhadap konteks trap/risk. Ini tetap konteks risiko, bukan arahan live.",
  NO_SIGNAL_BASELINE_SHORT:
    "Baseline short dari NO_SIGNAL_CONTEXT dipakai sebagai kontrol pembanding.",
  NO_SIGNAL_BASELINE_LONG:
    "Baseline long dari NO_SIGNAL_CONTEXT dipakai sebagai kontrol pembanding."
};

export default async function StrategyArenaPage({ searchParams }: { searchParams: ArenaSearchParams }) {
  const params = await searchParams;
  const filters = {
    setup: firstParam(params.setup),
    direction: firstParam(params.direction) || "ALL",
    horizon: firstParam(params.horizon),
    verdict: firstParam(params.verdict),
    minSample: normalizeNumber(firstParam(params.min_sample), 50),
    rr: firstParam(params.rr),
    atr: firstParam(params.atr),
    hideRejected: firstParam(params.hide_rejected) === "true",
    onlyPromising: firstParam(params.only_promising) === "true"
  };

  let leaderboard: StrategyArenaLeaderboardResponse | null = null;
  let results: StrategyArenaResultsResponse | null = null;
  let error: string | null = null;
  try {
    [leaderboard, results] = await Promise.all([
      fetchJson<StrategyArenaLeaderboardResponse>("/api/strategy-arena/v1/leaderboard"),
      fetchJson<StrategyArenaResultsResponse>("/api/strategy-arena/v1/results")
    ]);
  } catch (err) {
    error = err instanceof Error ? err.message : "Strategy Arena artifact belum tersedia";
  }

  const filteredRows = filterRows(results?.results || [], filters).slice(0, 250);
  const bestShort = leaderboard?.summary.best_short_setup;
  const bestLong = leaderboard?.summary.best_long_setup;

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold tracking-normal">Strategy Arena</h1>
          <div className="mt-2 inline-flex rounded border border-blue-700 bg-blue-50 px-3 py-1 text-xs font-bold text-blue-700">
            TEST MODE - BUKAN SINYAL ENTRY LIVE
          </div>
          <p className="mt-2 max-w-3xl text-sm text-slate-600">
            Arena ini menguji label MarketLab secara offline dengan ATR 1h dan grid RR multi-horizon. Hasil dipakai untuk riset dan monitoring, bukan instruksi eksekusi.
          </p>
        </div>
        <div className="text-right text-xs text-slate-500">
          Artifact: {fmtTime(leaderboard?.metadata.generated_at)}
        </div>
      </div>

      {error ? (
        <div className="border border-stale bg-red-50 p-4 text-sm text-stale">{error}</div>
      ) : (
        <>
          <section className="grid gap-3 md:grid-cols-4 xl:grid-cols-8">
            <Metric label="Setup Diuji" value={leaderboard?.summary.total_setups_tested ?? 0} />
            <Metric label="Kombinasi ATR/RR" value={leaderboard?.summary.total_combinations ?? 0} />
            <Metric label="Best Short" value={bestShort?.setup_label || "-"} />
            <Metric label="Best Long" value={bestLong?.setup_label || "-"} />
            <Metric label="Best Horizon" value={leaderboard?.summary.best_horizon || "-"} />
            <Metric label="Layak Dipantau" value={leaderboard?.summary.promising_count ?? 0} />
            <Metric label="Noise" value={leaderboard?.summary.noisy_count ?? 0} />
            <Metric label="Ditolak" value={leaderboard?.summary.rejected_count ?? 0} />
          </section>

          <form className="grid gap-3 border border-line bg-white p-4 md:grid-cols-4 xl:grid-cols-8" method="get">
            <SelectField label="Setup" name="setup" value={filters.setup || ""} options={setupOptions} emptyLabel="All setup" />
            <SelectField label="Arah" name="direction" value={filters.direction} options={["ALL", "LONG", "SHORT"]} emptyLabel={null} />
            <SelectField label="Horizon" name="horizon" value={filters.horizon || ""} options={["15m", "1h", "4h", "24h"]} emptyLabel="All horizon" />
            <SelectField label="Verdict" name="verdict" value={filters.verdict || ""} options={verdictOptions} emptyLabel="All verdict" />
            <label className="grid gap-1 text-sm">
              <span className="font-semibold text-slate-600">Minimum sample</span>
              <input className="border border-line px-3 py-2" min={0} name="min_sample" type="number" defaultValue={filters.minSample} />
            </label>
            <SelectField label="RR" name="rr" value={filters.rr || ""} options={["1", "1.5", "2", "2.5", "3"]} emptyLabel="All RR" />
            <SelectField label="ATR" name="atr" value={filters.atr || ""} options={["0.75", "1", "1.25", "1.5", "2"]} emptyLabel="All ATR" />
            <div className="flex flex-col justify-end gap-2 text-sm font-semibold text-slate-600">
              <label className="flex gap-2"><input name="hide_rejected" type="checkbox" value="true" defaultChecked={filters.hideRejected} /> Hide rejected</label>
              <label className="flex gap-2"><input name="only_promising" type="checkbox" value="true" defaultChecked={filters.onlyPromising} /> Only promising</label>
            </div>
            <div className="md:col-span-4 xl:col-span-8">
              <button className="border border-line px-4 py-2 text-sm font-semibold hover:bg-field" type="submit">
                Apply
              </button>
            </div>
          </form>

          <div className="overflow-x-auto border border-line bg-white">
            <table>
              <thead>
                <tr>
                  <th>Rank</th>
                  <th>Setup</th>
                  <th>Arah</th>
                  <th>Horizon</th>
                  <th>Risk</th>
                  <th>RR</th>
                  <th>Sample</th>
                  <th>Avg R konservatif</th>
                  <th>Target dulu</th>
                  <th>Stop dulu</th>
                  <th>Dua arah</th>
                  <th>Belum selesai</th>
                  <th>Konsentrasi koin</th>
                  <th>Verdict</th>
                </tr>
              </thead>
              <tbody>
                {filteredRows.map((row, index) => (
                  <tr key={`${row.setup_family}-${row.horizon}-${row.atr_mult}-${row.rr}`}>
                    <td>{index + 1}</td>
                    <td className="min-w-72">
                      <details>
                        <summary className="cursor-pointer font-semibold text-ink">{row.setup_label}</summary>
                        <div className="mt-2 space-y-2 text-xs text-slate-600">
                          <p>{setupDescriptions[row.setup_family] || "Setup test offline MarketLab."}</p>
                          <p>ATR model: ATR(14) futures 1h yang sudah closed sebelum/di waktu signal.</p>
                          <p>Entry assumption: close candle candidate 15m.</p>
                          <p>Raw backend label: {row.source_candidate_type}</p>
                          <p>Warning: {row.warning_label}</p>
                        </div>
                      </details>
                    </td>
                    <td>{row.direction_label}</td>
                    <td>{row.horizon_label}</td>
                    <td>{row.risk_label}</td>
                    <td>{row.rr_label}</td>
                    <td>{row.sample_size}</td>
                    <td>{fmtR(row.pessimistic_avg_r)}</td>
                    <td>{fmtPct(row.tp_first_share)}</td>
                    <td>{fmtPct(row.sl_first_share)}</td>
                    <td>{fmtPct(row.both_same_candle_share)}</td>
                    <td>{fmtPct(row.neither_share)}</td>
                    <td>{fmtPct(row.top_symbol_share)}</td>
                    <td><StatusBadge value={row.verdict} /></td>
                  </tr>
                ))}
                {!filteredRows.length && (
                  <tr>
                    <td colSpan={14}>Tidak ada kombinasi yang cocok dengan filter.</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>

          <section className="grid gap-4 lg:grid-cols-2">
            <div className="border border-line bg-white p-4">
              <h2 className="text-lg font-bold">Baseline comparison</h2>
              <div className="mt-3 max-h-96 overflow-auto">
                <table>
                  <thead>
                    <tr>
                      <th>Setup</th>
                      <th>Horizon</th>
                      <th>ATR</th>
                      <th>RR</th>
                      <th>Status</th>
                      <th>Delta R</th>
                    </tr>
                  </thead>
                  <tbody>
                    {leaderboard?.baseline_comparison.slice(0, 80).map((row) => (
                      <tr key={`${row.setup_family}-${row.horizon}-${row.atr_mult}-${row.rr}`}>
                        <td>{row.setup_family}</td>
                        <td>{row.horizon}</td>
                        <td>{fmtNumber(row.atr_mult)}</td>
                        <td>{fmtNumber(row.rr)}</td>
                        <td>{baselineLabel(row.baseline_status)}</td>
                        <td>{fmtR(row.pessimistic_avg_r_delta)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            <div className="border border-line bg-white p-4">
              <h2 className="text-lg font-bold">Data coverage</h2>
              <div className="mt-3 grid gap-3 md:grid-cols-2">
                <Metric label="Candidate rows" value={results?.metadata.candidate_rows_loaded ?? 0} />
                <Metric label="Missing ATR" value={results?.metadata.skipped_counts.MISSING_ATR ?? 0} />
                <Metric label="Forward data kurang" value={results?.metadata.skipped_counts.INSUFFICIENT_FORWARD_DATA ?? 0} />
                <Metric label="Unknown direction" value={results?.metadata.skipped_counts.UNKNOWN_DIRECTION ?? 0} />
              </div>
            </div>
          </section>
        </>
      )}
    </div>
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
  emptyLabel: string | null;
}) {
  return (
    <label className="grid gap-1 text-sm">
      <span className="font-semibold text-slate-600">{label}</span>
      <select className="border border-line bg-white px-3 py-2" name={name} defaultValue={value}>
        {emptyLabel !== null && <option value="">{emptyLabel}</option>}
        {options.map((option) => (
          <option key={option} value={option}>{option}</option>
        ))}
      </select>
    </label>
  );
}

function filterRows(rows: StrategyArenaResult[], filters: {
  setup?: string;
  direction: string;
  horizon?: string;
  verdict?: string;
  minSample: number;
  rr?: string;
  atr?: string;
  hideRejected: boolean;
  onlyPromising: boolean;
}): StrategyArenaResult[] {
  return rows
    .filter((row) => !filters.setup || row.setup_family === filters.setup)
    .filter((row) => filters.direction === "ALL" || directionSide(row) === filters.direction)
    .filter((row) => !filters.horizon || row.horizon === filters.horizon)
    .filter((row) => !filters.verdict || row.verdict === filters.verdict)
    .filter((row) => row.sample_size >= filters.minSample)
    .filter((row) => !filters.rr || Number(row.rr) === Number(filters.rr))
    .filter((row) => !filters.atr || Number(row.atr_mult) === Number(filters.atr))
    .filter((row) => !filters.hideRejected || row.verdict !== "REJECT")
    .filter((row) => !filters.onlyPromising || row.verdict === "PROMISING_FOR_FORWARD_TEST")
    .sort((a, b) => (b.pessimistic_avg_r ?? -999) - (a.pessimistic_avg_r ?? -999));
}

function directionSide(row: StrategyArenaResult): string {
  if (row.setup_family.includes("LONG") || row.direction_label.toLowerCase().includes("long")) return "LONG";
  if (row.setup_family.includes("SHORT") || row.direction_label.toLowerCase().includes("short")) return "SHORT";
  return "ALL";
}

function firstParam(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

function normalizeNumber(value: string | undefined, fallback: number): number {
  const parsed = Number(value || fallback);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function fmtPct(value?: number | null): string {
  if (value === null || value === undefined) return "-";
  return `${fmtNumber(value)}%`;
}

function fmtR(value?: number | null): string {
  if (value === null || value === undefined) return "-";
  return `${fmtNumber(value)}R`;
}

function baselineLabel(value: string): string {
  if (value === "BEATS_BASELINE") return "Mengalahkan baseline";
  if (value === "DOES_NOT_BEAT_BASELINE") return "Belum mengalahkan baseline";
  return "Baseline belum tersedia";
}
