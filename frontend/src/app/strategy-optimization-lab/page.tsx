import Link from "next/link";

import { EmptyState } from "@/components/EmptyState";
import { FilterBar, SelectFilter } from "@/components/FilterBar";
import { MetricCard } from "@/components/MetricCard";
import { PageHeader } from "@/components/PageHeader";
import { SectionCard } from "@/components/SectionCard";
import { StatusBadge } from "@/components/StatusBadge";
import { StrategyOptimizationResponse, StrategyOptimizationRow, fetchJson, fmtNumber, fmtTime } from "@/lib/api";
import { labelFor } from "@/lib/labels";

type StrategyOptimizationSearchParams = Promise<Record<string, string | string[] | undefined>>;

const stages = ["EARLY_LONG", "EARLY_SHORT", "MID_LONG", "MID_SHORT"];
const timeframes = ["15m", "1h", "4h", "24h"];

export const dynamic = "force-dynamic";

export default async function StrategyOptimizationLabPage({ searchParams }: { searchParams: StrategyOptimizationSearchParams }) {
  const params = await searchParams;
  const stage = firstParam(params.stage);
  const timeframe = firstParam(params.timeframe);
  const includeWatchOnly = firstParam(params.include_watch_only) === "true";
  const positionLock = firstParam(params.position_lock) !== "false";
  const minSample = normalizeNumber(firstParam(params.min_sample), 20, 1, 200);
  const limit = normalizeNumber(firstParam(params.limit), 80, 10, 200);
  const query = new URLSearchParams({
    include_watch_only: String(includeWatchOnly),
    position_lock: String(positionLock),
    min_sample: String(minSample),
    limit: String(limit)
  });
  if (stage) query.set("stage", stage);
  if (timeframe) query.set("timeframe", timeframe);

  let data: StrategyOptimizationResponse | null = null;
  let error: string | null = null;
  try {
    data = await fetchJson<StrategyOptimizationResponse>(`/api/strategy-optimization-lab?${query.toString()}`, { revalidateSeconds: 30 });
  } catch (err) {
    error = err instanceof Error ? err.message : "Strategy Optimization Lab API failed";
  }

  const best = data?.summary.best_row;
  return (
    <div className="space-y-5">
      <PageHeader
        title="Strategy Optimization Lab"
        badge="READ-ONLY PARAMETER STUDY"
        subtitle="Grid RR/ATR/timeout dari Signal V2 log. Tujuannya mencari apakah SL terlalu dekat, TP terlalu jauh, atau timeout perlu beda. Ini bukan rule live dan bukan execution."
        updatedAt={fmtTime(data?.generated_at_utc)}
      />

      <div className="flex flex-wrap gap-2 text-sm">
        <Link className="rounded border border-line bg-white px-3 py-2 font-semibold hover:bg-field" href="/signal-quality-lab">Signal Quality Lab</Link>
        <Link className="rounded border border-line bg-white px-3 py-2 font-semibold hover:bg-field" href="/signal-performance">Signal History</Link>
        <Link className="rounded border border-line bg-white px-3 py-2 font-semibold hover:bg-field" href="/strategy-arena">Strategy Test</Link>
      </div>

      {error ? (
        <div className="rounded border border-stale bg-red-50 p-4 text-sm text-stale">{error}</div>
      ) : (
        <>
          <section className="grid gap-3 md:grid-cols-2 xl:grid-cols-6">
            <MetricCard label="Signals loaded" value={data?.summary.signals_loaded ?? 0} helper="Signal V2 log" />
            <MetricCard label="Ready rows" value={data?.summary.ready_rows ?? 0} helper={`${data?.summary.grid_rows ?? 0} grid rows`} />
            <MetricCard label="Promising" value={data?.summary.promising_rows ?? 0} helper="Read-only verdict" tone="good" />
            <MetricCard label="Best lane" value={best ? `${labelFor(best.stage)} ${best.timeframe}` : "-"} helper={best ? `${best.atr_mult}x ATR / ${best.rr}R / ${best.timeout_minutes}m` : "No ready row"} tone="info" />
            <MetricCard label="Best total R" value={`${fmtSigned(best?.total_r)}R`} helper={`${best?.sample_count ?? 0} sample`} tone={Number(best?.total_r || 0) >= 0 ? "good" : "bad"} />
            <MetricCard label="Best DD" value={`${fmtSigned(best?.max_drawdown_r)}R`} helper="Dari urutan result" tone="warn" />
          </section>

          <SectionCard title="Optimization controls" description="Filter ini hanya mengubah tampilan study. Tidak mengubah Signal Factory, scanner, atau TP/SL live.">
            <FilterBar>
              <SelectFilter label="Stage" name="stage" value={stage || ""} options={stages} emptyLabel="All stage" />
              <SelectFilter label="Timeframe" name="timeframe" value={timeframe || ""} options={timeframes} emptyLabel="All timeframe" />
              <label className="grid gap-1 text-sm">
                <span className="font-semibold text-slate-600">Min sample</span>
                <input className="rounded border border-line px-3 py-2" min={1} max={200} name="min_sample" type="number" defaultValue={minSample} />
              </label>
              <label className="grid gap-1 text-sm">
                <span className="font-semibold text-slate-600">Rows</span>
                <input className="rounded border border-line px-3 py-2" min={10} max={200} name="limit" type="number" defaultValue={limit} />
              </label>
              <SelectFilter label="Position lock" name="position_lock" value={String(positionLock)} options={["true", "false"]} emptyLabel="Default true" />
              <label className="flex items-end gap-2 pb-2 text-sm font-semibold text-slate-600">
                <input name="include_watch_only" type="checkbox" value="true" defaultChecked={includeWatchOnly} />
                Include WATCH_ONLY
              </label>
            </FilterBar>
          </SectionCard>

          <SectionCard title="Best model per lane" description="Satu konfigurasi terbaik per stage/timeframe berdasarkan total R, avg R, median R, dan sample.">
            <OptimizationTable rows={data?.lanes || []} compact />
          </SectionCard>

          <SectionCard title="Top strategy parameter grid" description="Grid ATR multiplier, RR, dan timeout. Timeout menutup paper position di close candle timeout jika TP/SL belum kena.">
            <OptimizationTable rows={data?.rows || []} />
          </SectionCard>

          <SectionCard title="Guardrails" description="Batasan study ini supaya tidak dibaca sebagai sistem trading live.">
            <div className="grid gap-3 p-4 text-sm md:grid-cols-2 xl:grid-cols-4">
              {(data?.guardrails || []).map((item) => (
                <div key={item} className="rounded border border-line bg-field/50 p-3 font-semibold text-slate-700">{item}</div>
              ))}
            </div>
          </SectionCard>
        </>
      )}
    </div>
  );
}

function OptimizationTable({ rows, compact = false }: { rows: StrategyOptimizationRow[]; compact?: boolean }) {
  return (
    <div className="table-wrap">
      <table className="ops-table">
        <thead>
          <tr>
            <th>Setup</th>
            <th>ATR</th>
            <th>RR</th>
            <th>Timeout</th>
            <th>Sample</th>
            <th>TP / SL / Timeout</th>
            <th>Winrate</th>
            <th>Total R</th>
            <th>Avg / Median R</th>
            <th>Drawdown</th>
            {!compact && <th>Skipped</th>}
            <th>Verdict</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={`${row.stage}-${row.timeframe}-${row.atr_mult}-${row.rr}-${row.timeout_minutes}`}>
              <td>
                <div className="font-semibold">{labelFor(row.stage)}</div>
                <div className="text-xs text-slate-500">{row.timeframe}</div>
              </td>
              <td>{fmtNumber(row.atr_mult)}x</td>
              <td>{fmtNumber(row.rr)}R</td>
              <td>{row.timeout_minutes}m</td>
              <td>{row.sample_count}</td>
              <td>
                <div>{row.tp_count} / {row.sl_count} / {row.timeout_count}</div>
                <div className="text-xs text-slate-500">timeout +{row.positive_timeout_count} / -{row.negative_timeout_count}</div>
              </td>
              <td>{row.winrate_pct == null ? "-" : `${fmtNumber(row.winrate_pct)}%`}</td>
              <td>{fmtSigned(row.total_r)}R</td>
              <td>{fmtSigned(row.avg_r)} / {fmtSigned(row.median_r)}</td>
              <td>{fmtSigned(row.max_drawdown_r)}R</td>
              {!compact && <td className="text-xs text-slate-500">{formatSkipped(row.skipped_counts)}</td>}
              <td><StatusBadge value={row.verdict} /></td>
            </tr>
          ))}
          {!rows.length && (
            <tr>
              <td colSpan={compact ? 11 : 12}>
                <EmptyState title="No strategy optimization rows" detail="Belum ada sample sesuai filter/min sample." />
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

function formatSkipped(value: Record<string, number>): string {
  const entries = Object.entries(value).filter(([, count]) => count > 0);
  return entries.length ? entries.map(([key, count]) => `${key}: ${count}`).join(", ") : "-";
}

function firstParam(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

function normalizeNumber(value: string | undefined, fallback: number, min: number, max: number): number {
  const parsed = Number(value ?? fallback);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.min(Math.max(Math.trunc(parsed), min), max);
}

function fmtSigned(value?: string | number | null): string {
  if (value === null || value === undefined || value === "") return "-";
  const num = Number(value);
  if (!Number.isFinite(num)) return String(value);
  return `${num >= 0 ? "+" : ""}${new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 }).format(num)}`;
}
