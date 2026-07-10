import Link from "next/link";

import { EmptyState } from "@/components/EmptyState";
import { FilterBar, SelectFilter } from "@/components/FilterBar";
import { MetricCard } from "@/components/MetricCard";
import { PageHeader } from "@/components/PageHeader";
import { SectionCard } from "@/components/SectionCard";
import { StatusBadge } from "@/components/StatusBadge";
import {
  SignalCalibrationCandidate,
  StrategyOptimizationArtifactResponse,
  StrategyOptimizationResponse,
  StrategyOptimizationRow,
  StrategyRegimeSplitResponse,
  StrategyRegimeSplitRow,
  fetchJson,
  fmtNumber,
  fmtTime
} from "@/lib/api";
import { labelFor } from "@/lib/labels";

type StrategyOptimizationSearchParams = Promise<Record<string, string | string[] | undefined>>;

const stages = ["EARLY_LONG", "EARLY_SHORT", "MID_LONG", "MID_SHORT"];
const timeframes = ["15m", "1h", "4h", "24h"];
const defaultStage = "MID_SHORT";
const defaultTimeframe = "1h";

export const dynamic = "force-dynamic";

export default async function StrategyOptimizationLabPage({ searchParams }: { searchParams: StrategyOptimizationSearchParams }) {
  const params = await searchParams;
  const stage = firstParam(params.stage) || defaultStage;
  const timeframe = firstParam(params.timeframe) || defaultTimeframe;
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
  let artifactData: StrategyOptimizationArtifactResponse | null = null;
  let error: string | null = null;
  let artifactError: string | null = null;
  try {
    data = await fetchJson<StrategyOptimizationResponse>(`/api/strategy-optimization-lab?${query.toString()}`, { revalidateSeconds: 30 });
  } catch (err) {
    error = err instanceof Error ? err.message : "Strategy Optimization Lab API failed";
  }
  try {
    artifactData = await fetchJson<StrategyOptimizationArtifactResponse>("/api/strategy-optimization-artifacts", { revalidateSeconds: 30 });
  } catch (err) {
    artifactError = err instanceof Error ? err.message : "Strategy optimization artifact API failed";
  }

  const best = data?.summary.best_row;
  const regimeAtr = firstParam(params.atr_mult) || String(best?.atr_mult || "0.75");
  const regimeRr = firstParam(params.rr) || String(best?.rr || "2.0");
  const regimeTimeout = normalizeNumber(firstParam(params.timeout_minutes), Number(best?.timeout_minutes || 480), 15, 1440);
  let regimeData: StrategyRegimeSplitResponse | null = null;
  let regimeError: string | null = null;
  if (data && !error) {
    const regimeQuery = new URLSearchParams({
      include_watch_only: String(includeWatchOnly),
      position_lock: String(positionLock),
      stage,
      timeframe,
      atr_mult: regimeAtr,
      rr: regimeRr,
      timeout_minutes: String(regimeTimeout),
      min_sample: String(minSample),
      limit: "12"
    });
    try {
      regimeData = await fetchJson<StrategyRegimeSplitResponse>(`/api/strategy-optimization-regime-split?${regimeQuery.toString()}`, { revalidateSeconds: 30 });
    } catch (err) {
      regimeError = err instanceof Error ? err.message : "Strategy regime split API failed";
    }
  }

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
            <MetricCard label="Best DD" value={`${fmtSigned(best?.max_drawdown_r)}R`} helper={data?.artifact?.read_from_artifact ? "Dari artifact cepat" : "Live fallback"} tone="warn" />
          </section>

          <SectionCard title="Optimization controls" description="Filter ini hanya mengubah tampilan study. Tidak mengubah Signal Factory, scanner, atau TP/SL live.">
            <FilterBar>
              <SelectFilter label="Stage" name="stage" value={stage} options={stages} emptyLabel="Default MID_SHORT" />
              <SelectFilter label="Timeframe" name="timeframe" value={timeframe} options={timeframes} emptyLabel="Default 1h" />
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

          <SectionCard
            title="Artifact + V3 shadow snapshot"
            description="Artifact membuat halaman cepat. V3 shadow hanya filter riset yang dipantau, belum mengganti Signal Factory V2."
          >
            {artifactError ? (
              <div className="p-4 text-sm text-stale">{artifactError}</div>
            ) : (
              <div className="space-y-4 p-4">
                <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-5">
                  <MetricCard label="Artifact time" value={fmtTime(artifactData?.generated_at_utc)} helper="Precomputed JSON" />
                  <MetricCard label="Precomputed lanes" value={Object.keys(artifactData?.optimization_by_lane || {}).length} helper={(artifactData?.filters.lane_pairs || []).map((pair) => pair.join(" ")).join(", ") || "-"} />
                  <MetricCard label="V3 candidates" value={artifactData?.v3_shadow.v3_candidate_count ?? 0} helper="Research-only filter" tone="info" />
                  <MetricCard label="Monitor more" value={artifactData?.v3_shadow.monitor_more_count ?? 0} helper="Belum rule live" tone="warn" />
                  <MetricCard label="Artifact errors" value={artifactData?.errors.length ?? 0} helper={artifactData?.errors[0]?.lane || "No error"} tone={(artifactData?.errors.length || 0) > 0 ? "bad" : "good"} />
                </div>
                <V3ShadowTable rows={artifactData?.v3_shadow.top_candidates || []} />
              </div>
            )}
          </SectionCard>

          <SectionCard title="Best model per lane" description="Satu konfigurasi terbaik per stage/timeframe berdasarkan total R, avg R, median R, dan sample.">
            <OptimizationTable rows={data?.lanes || []} compact />
          </SectionCard>

          <SectionCard title="Top strategy parameter grid" description="Grid ATR multiplier, RR, dan timeout. Timeout menutup paper position di close candle timeout jika TP/SL belum kena.">
            <OptimizationTable rows={data?.rows || []} />
          </SectionCard>

          <SectionCard
            title="Regime split"
            description={`Menguji parameter ${regimeAtr}x ATR / ${regimeRr}R / timeout ${regimeTimeout}m terhadap BTC, ETH, breadth, dan volatility regime.`}
          >
            {regimeError ? (
              <div className="p-4 text-sm text-stale">{regimeError}</div>
            ) : (
              <div className="space-y-4 p-4">
                <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-5">
                  <MetricCard label="Evaluated" value={regimeData?.summary.evaluated_events ?? 0} helper={`${regimeData?.summary.signals_loaded ?? 0} signals loaded`} />
                  <MetricCard label="Baseline total R" value={`${fmtSigned(regimeData?.summary.baseline.total_r)}R`} helper={`${regimeData?.summary.baseline.tp_count ?? 0}/${regimeData?.summary.baseline.sl_count ?? 0} TP/SL`} tone={Number(regimeData?.summary.baseline.total_r || 0) >= 0 ? "good" : "bad"} />
                  <MetricCard label="Baseline avg R" value={`${fmtSigned(regimeData?.summary.baseline.avg_r)}R`} helper={`median ${fmtSigned(regimeData?.summary.baseline.median_r)}R`} />
                  <MetricCard label="Dependency" value={shortDependency(regimeData?.summary.regime_dependency)} helper={regimeData?.summary.regime_dependency || "-"} tone="warn" />
                  <MetricCard label="Skipped" value={formatSkipped(regimeData?.summary.skipped_counts || {})} helper="Position lock / data gaps" />
                </div>
                <div className="grid gap-4 xl:grid-cols-2">
                  <div>
                    <h3 className="mb-2 text-sm font-semibold">Top helpful regimes</h3>
                    <RegimeSplitTable rows={regimeData?.summary.top_helpful_regimes || []} />
                  </div>
                  <div>
                    <h3 className="mb-2 text-sm font-semibold">Top harmful regimes</h3>
                    <RegimeSplitTable rows={regimeData?.summary.top_harmful_regimes || []} />
                  </div>
                </div>
              </div>
            )}
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

function V3ShadowTable({ rows }: { rows: SignalCalibrationCandidate[] }) {
  return (
    <div className="table-wrap">
      <table className="ops-table text-sm">
        <thead>
          <tr>
            <th>Lane</th>
            <th>Filter</th>
            <th>Status</th>
            <th>Score</th>
            <th>Validation</th>
            <th>SL delta</th>
            <th>Concentration</th>
          </tr>
        </thead>
        <tbody>
          {rows.slice(0, 12).map((row) => (
            <tr key={`${row.stage}-${row.timeframe}-${row.filter_id}`}>
              <td>
                <div className="font-semibold">{labelFor(row.stage || "")}</div>
                <div className="text-xs text-slate-500">{row.timeframe}</div>
              </td>
              <td>
                <div className="font-semibold">{row.label}</div>
                <div className="text-xs text-slate-500">{row.expression}</div>
              </td>
              <td><StatusBadge value={row.promotion_status || row.verdict} /></td>
              <td>{row.promotion_score ?? "-"}</td>
              <td>
                <div>{fmtSigned(row.validation?.avg_r_delta_vs_baseline)}R avg delta</div>
                <div className="text-xs text-slate-500">{fmtSigned(row.validation?.total_r_closed)}R total</div>
              </td>
              <td>{fmtSigned(row.validation?.sl_share_delta_vs_baseline)}%</td>
              <td>{row.validation?.top_symbol ? `${row.validation.top_symbol} ${fmtNumber(row.validation.top_symbol_share_pct)}%` : "-"}</td>
            </tr>
          ))}
          {!rows.length && (
            <tr>
              <td colSpan={7}>
                <EmptyState title="No V3 shadow filter yet" detail="Belum ada filter calibration yang cukup kuat untuk dipantau sebagai V3 shadow." />
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

function RegimeSplitTable({ rows }: { rows: StrategyRegimeSplitRow[] }) {
  return (
    <div className="table-wrap">
      <table className="ops-table text-sm">
        <thead>
          <tr>
            <th>Regime</th>
            <th>Sample</th>
            <th>TP / SL / TO</th>
            <th>Total R</th>
            <th>Avg Delta</th>
            <th>Win Delta</th>
            <th>SL Delta</th>
            <th>Verdict</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={`${row.dimension}-${row.bucket}`}>
              <td>
                <div className="font-semibold">{row.bucket}</div>
                <div className="text-xs text-slate-500">{row.dimension}</div>
              </td>
              <td>{row.sample_count}</td>
              <td>{row.tp_count} / {row.sl_count} / {row.timeout_count}</td>
              <td>{fmtSigned(row.total_r)}R</td>
              <td>{fmtSigned(row.avg_r_delta_vs_baseline)}R</td>
              <td>{fmtSigned(row.winrate_delta_vs_baseline)}%</td>
              <td>{fmtSigned(row.sl_share_delta_vs_baseline)}%</td>
              <td><StatusBadge value={row.verdict || "-"} /></td>
            </tr>
          ))}
          {!rows.length && (
            <tr>
              <td colSpan={8}>
                <EmptyState title="No regime bucket yet" detail="Belum ada bucket regime yang cukup kuat di filter ini." />
              </td>
            </tr>
          )}
        </tbody>
      </table>
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

function shortDependency(value?: string): string {
  if (!value) return "-";
  if (value.includes("BEAR_OR_WEAK")) return "Bear/weak dependent";
  if (value.includes("BULL_OR_STRONG")) return "Bull/strong dependent";
  if (value.includes("NO_CLEAR")) return "No clear regime";
  return "Mixed";
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
