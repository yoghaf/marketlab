import Link from "next/link";

import { EmptyState } from "@/components/EmptyState";
import { FilterBar, SelectFilter } from "@/components/FilterBar";
import { MetricCard } from "@/components/MetricCard";
import { PageHeader } from "@/components/PageHeader";
import { SectionCard } from "@/components/SectionCard";
import { StatusBadge } from "@/components/StatusBadge";
import {
  SignalPerformanceItem,
  V3ShadowFilterRow,
  V3ShadowForwardLaneRow,
  V3ShadowForwardLogResponse,
  V3ShadowForwardLaneSummary,
  fetchJson,
  fmtNumber,
  fmtPrice,
  fmtTime
} from "@/lib/api";
import { compactReason, labelFor } from "@/lib/labels";

type V3ForwardSearchParams = Promise<Record<string, string | string[] | undefined>>;

const stages = ["EARLY_LONG", "EARLY_SHORT", "MID_LONG", "MID_SHORT"];
const timeframes = ["15m", "1h", "4h", "24h"];

export const dynamic = "force-dynamic";

export default async function V3ForwardLogPage({ searchParams }: { searchParams: V3ForwardSearchParams }) {
  const params = await searchParams;
  const stage = firstParam(params.stage);
  const timeframe = firstParam(params.timeframe);
  const includeWatchOnly = firstParam(params.include_watch_only) === "true";
  const positionLock = firstParam(params.position_lock) !== "false";
  const minSample = normalizeNumber(firstParam(params.min_sample), 5, 1, 100);
  const limit = normalizeNumber(firstParam(params.limit), 50, 10, 200);
  const query = new URLSearchParams({
    include_watch_only: String(includeWatchOnly),
    position_lock: String(positionLock),
    min_sample: String(minSample),
    limit: String(limit)
  });
  if (stage) query.set("stage", stage);
  if (timeframe) query.set("timeframe", timeframe);

  let data: V3ShadowForwardLogResponse | null = null;
  let error: string | null = null;
  try {
    data = await fetchJson<V3ShadowForwardLogResponse>(`/api/v3-shadow/forward-log?${query.toString()}`, { revalidateSeconds: 20 });
  } catch (err) {
    error = err instanceof Error ? err.message : "V3 Shadow Forward API failed";
  }

  const v2 = data?.summary.v2_live;
  const v3 = data?.summary.v3_shadow_signal;
  const v2Perf = v2?.performance;
  const v3Perf = v3?.performance;

  return (
    <div className="space-y-5">
      <PageHeader
        title="V3 Shadow Forward Log"
        badge="READ-ONLY SHADOW LANE"
        subtitle="Pantauan paper-live V3: semua signal tetap dibuat oleh V2, lalu V3 hanya mengambil subset yang lolos shadow filter. Ini bukan execution dan belum mengganti rule live."
        updatedAt={fmtTime(data?.generated_at_utc)}
      />

      <div className="flex flex-wrap gap-2 text-sm">
        <Link className="rounded border border-line bg-white px-3 py-2 font-semibold hover:bg-field" href="/v3-shadow-lab">V3 Shadow Lab</Link>
        <Link className="rounded border border-line bg-white px-3 py-2 font-semibold hover:bg-field" href="/signal-performance">Signal History</Link>
        <Link className="rounded border border-line bg-white px-3 py-2 font-semibold hover:bg-field" href="/scanner?tier=SIGNAL_CANDIDATE&limit=75">Radar Signal</Link>
      </div>

      {error ? (
        <div className="rounded border border-stale bg-red-50 p-4 text-sm text-stale">{error}</div>
      ) : (
        <>
          <section className="grid gap-3 md:grid-cols-2 xl:grid-cols-6">
            <MetricCard label="V2 live R" value={`${fmtSigned(v2Perf?.total_r_closed)}R`} helper={`${v2Perf?.signals_evaluated ?? 0} evaluated`} tone={Number(v2Perf?.total_r_closed || 0) >= 0 ? "good" : "bad"} />
            <MetricCard label="V3 shadow R" value={`${fmtSigned(v3Perf?.total_r_closed)}R`} helper={`${data?.summary.v3_shadow_signal_count ?? 0} shadow signals`} tone={Number(v3Perf?.total_r_closed || 0) >= 0 ? "good" : "bad"} />
            <MetricCard label="Retention" value={`${fmtNumber(data?.summary.v3_sample_retention_pct)}%`} helper="V3 pass / V2 evaluated" tone="info" />
            <MetricCard label="V3 open" value={data?.summary.v3_shadow_open_count ?? 0} helper={`${fmtSigned(v3Perf?.open_unrealized_r)}R unrealized`} tone="warn" />
            <MetricCard label="Drawdown delta" value={`${fmtSigned(data?.summary.max_drawdown_delta_v3_vs_v2)}R`} helper="lebih tinggi berarti DD lebih kecil" tone={Number(data?.summary.max_drawdown_delta_v3_vs_v2 || 0) >= 0 ? "good" : "bad"} />
            <MetricCard label="Read" value={labelFor(data?.summary.read || "-")} helper="shadow-only verdict" tone={data?.summary.read === "V3_FORWARD_HEALTHY_SHADOW" ? "good" : "warn"} />
          </section>

          <SectionCard title="Forward controls" description="Filter ini hanya mengubah tampilan. V3 shadow tidak mengubah rule live, scanner, TP/SL, atau execution.">
            <FilterBar>
              <SelectFilter label="Stage" name="stage" value={stage || ""} options={stages} emptyLabel="All stage" />
              <SelectFilter label="Timeframe" name="timeframe" value={timeframe || ""} options={timeframes} emptyLabel="All timeframe" />
              <label className="grid gap-1 text-sm">
                <span className="font-semibold text-slate-600">Min sample</span>
                <input className="rounded border border-line px-3 py-2" min={1} max={100} name="min_sample" type="number" defaultValue={minSample} />
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

          <section className="grid gap-4 xl:grid-cols-2">
            <SectionCard title="V2 live signal lane" description="Semua signal live V2 sesuai filter halaman.">
              <ForwardSummary summary={v2} />
            </SectionCard>
            <SectionCard title="V3 shadow signal lane" description="Hanya signal V2 yang lolos V3 shadow filter.">
              <ForwardSummary summary={v3} />
            </SectionCard>
          </section>

          <SectionCard title="Lane comparison" description="Baca ini untuk melihat apakah MID_LONG/MID_SHORT V3 benar-benar lebih bersih daripada baseline V2.">
            <LaneTable rows={data?.by_stage_timeframe || []} />
          </SectionCard>

          <SectionCard title="Filter contribution" description="Filter V3 mana yang menghasilkan shadow signal dan bagaimana hasilnya.">
            <FilterTable rows={data?.by_filter || []} />
          </SectionCard>

          <section className="grid gap-4 xl:grid-cols-2">
            <SectionCard title="Open V3 shadow signals" description="Posisi paper-live yang masih aktif. Current R bergerak saat candle futures baru masuk.">
              <SignalTable rows={data?.latest_v3_open_signals || []} empty="Tidak ada V3 shadow signal yang masih open." />
            </SectionCard>
            <SectionCard title="Closed V3 shadow signals" description="Riwayat V3 shadow yang sudah kena TP/SL/BOTH.">
              <SignalTable rows={data?.latest_v3_closed_signals || []} empty="Belum ada V3 shadow signal closed." />
            </SectionCard>
          </section>

          <SectionCard title="Guardrails">
            <div className="grid gap-3 p-4 text-sm md:grid-cols-2 xl:grid-cols-4">
              {(data?.guardrails || []).map((item) => (
                <div className="rounded border border-line bg-field/40 p-3 font-semibold text-slate-700" key={item}>{item}</div>
              ))}
            </div>
          </SectionCard>
        </>
      )}
    </div>
  );
}

function ForwardSummary({ summary }: { summary?: V3ShadowForwardLaneSummary }) {
  const perf = summary?.performance;
  const drawdown = summary?.drawdown;
  const quality = summary?.quality;
  return (
    <div className="grid gap-3 p-4 text-sm md:grid-cols-3">
      <Insight label="Evaluated" value={perf?.signals_evaluated ?? 0} />
      <Insight label="TP / SL / Open" value={`${perf?.tp_count ?? 0} / ${perf?.sl_count ?? 0} / ${perf?.open_count ?? 0}`} />
      <Insight label="Total R" value={`${fmtSigned(perf?.total_r_closed)}R`} />
      <Insight label="With Open" value={`${fmtSigned(perf?.total_r_with_open)}R`} />
      <Insight label="Winrate" value={perf?.winrate_pct == null ? "-" : `${fmtNumber(perf.winrate_pct)}%`} />
      <Insight label="Avg R" value={`${fmtSigned(perf?.avg_r_closed)}R`} />
      <Insight label="Max DD" value={`${fmtSigned(drawdown?.max_drawdown_r)}R`} />
      <Insight label="Median R" value={`${fmtSigned(quality?.median_r_closed)}R`} />
      <Insight label="Top symbol" value={`${quality?.top_symbol || "-"} ${quality?.top_symbol_share_pct == null ? "" : `(${fmtNumber(quality.top_symbol_share_pct)}%)`}`} />
    </div>
  );
}

function LaneTable({ rows }: { rows: V3ShadowForwardLaneRow[] }) {
  return (
    <TableShell>
      <thead>
        <tr>
          <th>Lane</th>
          <th>V2 sample</th>
          <th>V2 R</th>
          <th>V2 DD</th>
          <th>V3 sample</th>
          <th>Retain</th>
          <th>V3 R</th>
          <th>V3 DD</th>
          <th>Avg delta</th>
          <th>Win delta</th>
          <th>Read</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr key={`${row.stage}-${row.timeframe}`}>
            <td>
              <div className="font-semibold">{labelFor(row.stage)}</div>
              <div className="text-xs text-slate-500">{row.timeframe}</div>
            </td>
            <td>{row.v2_live.performance.signals_evaluated}</td>
            <td>{fmtSigned(row.v2_live.performance.total_r_closed)}R</td>
            <td>{fmtSigned(row.v2_live.drawdown.max_drawdown_r)}R</td>
            <td>{row.v3_shadow_signal_count}</td>
            <td>{fmtNumber(row.v3_sample_retention_pct)}%</td>
            <td>{fmtSigned(row.v3_shadow_signal.performance.total_r_closed)}R</td>
            <td>{fmtSigned(row.v3_shadow_signal.drawdown.max_drawdown_r)}R</td>
            <td>{fmtSigned(row.avg_r_delta_v3_vs_v2)}R</td>
            <td>{fmtSigned(row.winrate_delta_v3_vs_v2)}%</td>
            <td><StatusBadge value={row.read} /></td>
          </tr>
        ))}
        {!rows.length && <EmptyRow colSpan={11} title="No lane rows" />}
      </tbody>
    </TableShell>
  );
}

function FilterTable({ rows }: { rows: V3ShadowFilterRow[] }) {
  return (
    <TableShell>
      <thead>
        <tr>
          <th>Filter</th>
          <th>Sample</th>
          <th>TP / SL / Open</th>
          <th>Total R</th>
          <th>Avg R</th>
          <th>Winrate</th>
          <th>SL delta</th>
          <th>Verdict</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr key={row.filter_id}>
            <td>
              <div className="font-semibold">{row.label}</div>
              <div className="text-xs text-slate-500">{compactReason(row.expression || "-", 110)}</div>
            </td>
            <td>{row.sample_count}</td>
            <td>{row.tp_count} / {row.sl_count} / {row.open_count}</td>
            <td>{fmtSigned(row.total_r_closed)}R</td>
            <td>{fmtSigned(row.avg_r_closed)}R</td>
            <td>{row.winrate_pct == null ? "-" : `${fmtNumber(row.winrate_pct)}%`}</td>
            <td>{fmtSigned(row.sl_share_delta_vs_v2)}%</td>
            <td><StatusBadge value={row.verdict} /></td>
          </tr>
        ))}
        {!rows.length && <EmptyRow colSpan={8} title="No filter rows" />}
      </tbody>
    </TableShell>
  );
}

function SignalTable({ rows, empty }: { rows: SignalPerformanceItem[]; empty: string }) {
  return (
    <TableShell>
      <thead>
        <tr>
          <th>Time WIB</th>
          <th>Symbol</th>
          <th>TF</th>
          <th>Stage</th>
          <th>Result</th>
          <th>R</th>
          <th>MFE / MAE</th>
          <th>Entry / SL / TP</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((item) => (
          <tr key={item.signal_id}>
            <td>{item.signal_time_wib || fmtTime(item.signal_timestamp)}</td>
            <td className="font-semibold">
              <Link className="text-blue-700 hover:underline" href={`/signals/${encodeURIComponent(item.symbol)}?signal_id=${encodeURIComponent(item.signal_id)}`}>{item.symbol}</Link>
            </td>
            <td>{item.timeframe}</td>
            <td>{labelFor(item.stage)}</td>
            <td><StatusBadge value={item.result_status} /></td>
            <td>{fmtSigned(item.result_status === "OPEN" ? item.unrealized_r : item.realized_r)}R</td>
            <td>{fmtSigned(item.mfe_r)} / {fmtSigned(item.mae_r)}</td>
            <td className="text-xs">
              <div>Entry {fmtPrice(item.entry)}</div>
              <div>SL {fmtPrice(item.stop_loss)}</div>
              <div>TP {fmtPrice(item.take_profit)}</div>
            </td>
          </tr>
        ))}
        {!rows.length && <EmptyRow colSpan={8} title={empty} />}
      </tbody>
    </TableShell>
  );
}

function TableShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="table-wrap">
      <table className="ops-table text-sm">
        {children}
      </table>
    </div>
  );
}

function EmptyRow({ colSpan, title }: { colSpan: number; title: string }) {
  return (
    <tr>
      <td colSpan={colSpan}><EmptyState title={title} /></td>
    </tr>
  );
}

function Insight({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded border border-line bg-field/40 p-3">
      <div className="text-xs font-semibold uppercase text-slate-500">{label}</div>
      <div className="mt-1 break-words text-lg font-bold text-ink">{value}</div>
    </div>
  );
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
