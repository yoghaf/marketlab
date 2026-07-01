import { EmptyState } from "@/components/EmptyState";
import { FilterBar, SelectFilter } from "@/components/FilterBar";
import { MetricCard } from "@/components/MetricCard";
import { PageHeader } from "@/components/PageHeader";
import { SectionCard } from "@/components/SectionCard";
import { StatusBadge } from "@/components/StatusBadge";
import {
  StrategyArenaLeaderboardResponse,
  StrategyArenaResult,
  StrategyArenaResultsResponse,
  fetchJson,
  fmtNumber,
  fmtTime
} from "@/lib/api";
import { labelFor } from "@/lib/labels";

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
const verdictOptions = ["PROMISING_FOR_FORWARD_TEST", "MONITOR_MORE", "NOISY", "REJECT", "INSUFFICIENT_SAMPLE"];

export default async function StrategyArenaPage({ searchParams }: { searchParams: ArenaSearchParams }) {
  const params = await searchParams;
  const filters = {
    setup: firstParam(params.setup),
    direction: firstParam(params.direction) || "ALL",
    horizon: firstParam(params.horizon),
    verdict: firstParam(params.verdict),
    minSample: normalizeNumber(firstParam(params.min_sample), 50),
    hideRejected: firstParam(params.hide_rejected) !== "false"
  };

  let leaderboard: StrategyArenaLeaderboardResponse | null = null;
  let results: StrategyArenaResultsResponse | null = null;
  let error: string | null = null;
  try {
    [leaderboard, results] = await Promise.all([
      fetchJson<StrategyArenaLeaderboardResponse>("/api/strategy-arena/v1/leaderboard", { revalidateSeconds: 30 }),
      fetchJson<StrategyArenaResultsResponse>("/api/strategy-arena/v1/results", { revalidateSeconds: 30 })
    ]);
  } catch (err) {
    error = err instanceof Error ? err.message : "Strategy Arena artifact belum tersedia";
  }

  const edgeMap = buildEdgeMap(leaderboard?.baseline_comparison || []);
  const filteredRows = filterRows(results?.results || [], filters, edgeMap).slice(0, 100);
  const bestShort = leaderboard?.summary.best_short_setup;
  const bestLong = leaderboard?.summary.best_long_setup;

  return (
    <div className="space-y-5">
      <PageHeader
        title="Strategy Test"
        badge="TEST MODE - BUKAN SINYAL ENTRY LIVE"
        subtitle="Arena read-only untuk melihat setup mana yang diuji, R konservatif, baseline edge, sample, dan verdict."
        updatedAt={fmtTime(leaderboard?.metadata.generated_at)}
      />
      <div className="flex flex-wrap gap-2 text-sm">
        <a className="rounded border border-line bg-white px-3 py-2 font-semibold hover:bg-field" href="/strategy-arena">Strategy Arena</a>
        <a className="rounded border border-line bg-white px-3 py-2 font-semibold hover:bg-field" href="/phase6-audit">Phase 6 Audit</a>
      </div>

      {error ? (
        <div className="rounded border border-stale bg-red-50 p-4 text-sm text-stale">{error}</div>
      ) : (
        <>
          <section className="grid gap-3 md:grid-cols-3 xl:grid-cols-6">
            <MetricCard label="Best Setup" value={bestShort?.setup_label || "-"} helper={bestShort?.verdict_label} tone="info" />
            <MetricCard label="Best Short" value={bestShort?.setup_label || "-"} helper={bestShort ? `${bestShort.horizon_label} ${bestShort.rr_label}` : undefined} />
            <MetricCard label="Best Long" value={bestLong?.setup_label || "-"} helper={bestLong ? `${bestLong.horizon_label} ${bestLong.rr_label}` : undefined} />
            <MetricCard label="Baseline Warning" value="Wajib dibandingkan" helper="Raw R saja tidak cukup" tone="warn" />
            <MetricCard label="Promising" value={leaderboard?.summary.promising_count ?? 0} tone="good" />
            <MetricCard label="Noisy" value={leaderboard?.summary.noisy_count ?? 0} tone="warn" />
          </section>

          <FilterBar>
            <SelectFilter label="Setup" name="setup" value={filters.setup || ""} options={setupOptions} emptyLabel="All setup" />
            <SelectFilter label="Arah" name="direction" value={filters.direction} options={["ALL", "LONG", "SHORT"]} emptyLabel="All arah" />
            <SelectFilter label="Horizon" name="horizon" value={filters.horizon || ""} options={["15m", "1h", "4h", "24h"]} emptyLabel="All horizon" />
            <SelectFilter label="Verdict" name="verdict" value={filters.verdict || ""} options={verdictOptions} emptyLabel="All verdict" />
            <label className="grid gap-1 text-sm">
              <span className="font-semibold text-slate-600">Minimum sample</span>
              <input className="rounded border border-line px-3 py-2" min={0} name="min_sample" type="number" defaultValue={filters.minSample} />
            </label>
            <label className="flex items-end gap-2 pb-2 text-sm font-semibold text-slate-600">
              <input name="hide_rejected" type="checkbox" value="true" defaultChecked={filters.hideRejected} />
              Hide rejected
            </label>
          </FilterBar>

          <SectionCard title="Strategy test results" description="Default view dibatasi 100 rows dan rejected disembunyikan.">
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Rank</th>
                    <th>Setup</th>
                    <th>Arah</th>
                    <th>Horizon</th>
                    <th>ATR</th>
                    <th>RR</th>
                    <th>Avg R konservatif</th>
                    <th>Edge vs Baseline</th>
                    <th>Sample</th>
                    <th>Verdict</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredRows.map((row, index) => {
                    const edge = edgeFor(row, edgeMap);
                    return (
                      <tr key={`${row.setup_family}-${row.horizon}-${row.atr_mult}-${row.rr}`}>
                        <td>{index + 1}</td>
                        <td className="max-w-56 truncate" title={row.setup_family}>{labelFor(row.setup_family)}</td>
                        <td>{row.direction_label}</td>
                        <td>{row.horizon_label}</td>
                        <td>{row.risk_label}</td>
                        <td>{row.rr_label}</td>
                        <td>{fmtR(row.pessimistic_avg_r)}</td>
                        <td>{fmtR(edge)}</td>
                        <td>{row.sample_size}</td>
                        <td>
                          <StatusBadge value={row.verdict} />
                          <details className="mt-1 text-xs text-slate-500">
                            <summary className="cursor-pointer font-semibold">Show technical labels</summary>
                            <div className="mt-2">Raw setup: {row.setup_family}</div>
                            <div>Target first: {fmtPct(row.tp_first_share)} Stop first: {fmtPct(row.sl_first_share)}</div>
                            <div>Top symbol share: {fmtPct(row.top_symbol_share)}</div>
                          </details>
                        </td>
                      </tr>
                    );
                  })}
                  {!filteredRows.length && (
                    <tr>
                      <td colSpan={10}><EmptyState title="Tidak ada hasil cocok filter" detail="Longgarkan filter atau tampilkan rejected." /></td>
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

function buildEdgeMap(rows: StrategyArenaLeaderboardResponse["baseline_comparison"]): Record<string, number | null> {
  const output: Record<string, number | null> = {};
  for (const row of rows) {
    output[`${row.setup_family}|${row.horizon}|${row.atr_mult}|${row.rr}`] = row.pessimistic_avg_r_delta ?? null;
  }
  return output;
}

function edgeFor(row: StrategyArenaResult, edgeMap: Record<string, number | null>): number | null {
  return edgeMap[`${row.setup_family}|${row.horizon}|${row.atr_mult}|${row.rr}`] ?? null;
}

function filterRows(rows: StrategyArenaResult[], filters: {
  setup?: string;
  direction: string;
  horizon?: string;
  verdict?: string;
  minSample: number;
  hideRejected: boolean;
}, edgeMap: Record<string, number | null>): StrategyArenaResult[] {
  return rows
    .filter((row) => !filters.setup || row.setup_family === filters.setup)
    .filter((row) => filters.direction === "ALL" || directionSide(row) === filters.direction)
    .filter((row) => !filters.horizon || row.horizon === filters.horizon)
    .filter((row) => !filters.verdict || row.verdict === filters.verdict)
    .filter((row) => row.sample_size >= filters.minSample)
    .filter((row) => !filters.hideRejected || row.verdict !== "REJECT")
    .sort((a, b) => (edgeFor(b, edgeMap) ?? b.pessimistic_avg_r ?? -999) - (edgeFor(a, edgeMap) ?? a.pessimistic_avg_r ?? -999));
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
