import Link from "next/link";
import type { ReactNode } from "react";

import { EmptyState } from "@/components/EmptyState";
import { FilterBar, SelectFilter } from "@/components/FilterBar";
import { MetricCard } from "@/components/MetricCard";
import { PageHeader } from "@/components/PageHeader";
import { SectionCard } from "@/components/SectionCard";
import { StatusBadge } from "@/components/StatusBadge";
import {
  SignalPerformanceBucket,
  SignalPerformanceItem,
  V3ShadowComparisonResponse,
  V3ShadowFilterRow,
  V3ShadowLaneRow,
  V3ShadowStatusRow,
  fetchJson,
  fmtNumber,
  fmtPrice,
  fmtTime
} from "@/lib/api";
import { compactReason, labelFor } from "@/lib/labels";

type V3ShadowSearchParams = Promise<Record<string, string | string[] | undefined>>;

const stages = ["EARLY_LONG", "EARLY_SHORT", "MID_LONG", "MID_SHORT"];
const timeframes = ["15m", "1h", "4h", "24h"];

export const dynamic = "force-dynamic";

export default async function V3ShadowLabPage({ searchParams }: { searchParams: V3ShadowSearchParams }) {
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

  let data: V3ShadowComparisonResponse | null = null;
  let error: string | null = null;
  try {
    data = await fetchJson<V3ShadowComparisonResponse>(`/api/v3-shadow/comparison?${query.toString()}`, { revalidateSeconds: 20 });
  } catch (err) {
    error = err instanceof Error ? err.message : "V3 Shadow Comparison API failed";
  }

  const v2 = data?.summary.v2_live;
  const v3 = data?.summary.v3_shadow_pass;

  return (
    <div className="space-y-5">
      <PageHeader
        title="V3 Shadow Lab"
        badge="READ-ONLY V2 VS V3"
        subtitle="Membandingkan semua Signal V2 live dengan subset yang lolos V3 shadow filter. Ini belum mengganti rule live dan bukan execution."
        updatedAt={fmtTime(data?.generated_at_utc)}
      />

      <div className="flex flex-wrap gap-2 text-sm">
        <Link className="rounded border border-line bg-white px-3 py-2 font-semibold hover:bg-field" href="/scanner?tier=SIGNAL_CANDIDATE&limit=75">Radar Signal</Link>
        <Link className="rounded border border-line bg-white px-3 py-2 font-semibold hover:bg-field" href="/signal-performance">Signal History</Link>
        <Link className="rounded border border-line bg-white px-3 py-2 font-semibold hover:bg-field" href="/strategy-optimization-lab">Strategy Optimization</Link>
      </div>

      {error ? (
        <div className="rounded border border-stale bg-red-50 p-4 text-sm text-stale">{error}</div>
      ) : (
        <>
          <section className="grid gap-3 md:grid-cols-2 xl:grid-cols-6">
            <MetricCard label="V2 evaluated" value={v2?.signals_evaluated ?? 0} helper={`${data?.skipped_by_position_lock?.ACTIVE_POSITION_LOCK || 0} skipped by lock`} />
            <MetricCard label="V2 total R" value={`${fmtSigned(v2?.total_r_closed)}R`} helper={`${v2?.tp_count ?? 0}/${v2?.sl_count ?? 0} TP/SL`} tone={Number(v2?.total_r_closed || 0) >= 0 ? "good" : "bad"} />
            <MetricCard label="V3 pass" value={data?.summary.v3_pass_count ?? 0} helper={`${fmtNumber(data?.summary.sample_retention_pct)}% retention`} tone="info" />
            <MetricCard label="V3 total R" value={`${fmtSigned(v3?.total_r_closed)}R`} helper={`${v3?.tp_count ?? 0}/${v3?.sl_count ?? 0} TP/SL`} tone={Number(v3?.total_r_closed || 0) >= 0 ? "good" : "bad"} />
            <MetricCard label="Avg R delta" value={`${fmtSigned(data?.summary.avg_r_delta_v3_pass_vs_v2)}R`} helper="V3 pass vs V2 all" tone={Number(data?.summary.avg_r_delta_v3_pass_vs_v2 || 0) >= 0 ? "good" : "bad"} />
            <MetricCard label="Read" value={labelFor(data?.summary.read || "-")} helper="Research-only verdict" tone={data?.summary.read === "V3_SHADOW_IMPROVES_V2" ? "good" : "warn"} />
          </section>

          <SectionCard title="V3 controls" description="Filter ini hanya mengubah tampilan comparison. Tidak mengubah Signal Factory V2, scanner, TP/SL, atau execution.">
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
            <SectionCard title="V2 live baseline" description="Semua Signal V2 sesuai filter halaman.">
              <PerfGrid row={v2} />
            </SectionCard>
            <SectionCard title="V3 shadow pass" description="Subset Signal V2 yang lolos filter V3 shadow.">
              <PerfGrid row={v3} />
            </SectionCard>
          </section>

          <SectionCard title="Comparison by V3 status" description="PASS adalah subset yang akan dipantau sebagai calon V3. FAIL berarti filter ada tapi evidence signal tidak cocok.">
            <StatusTable rows={data?.by_v3_status || []} />
          </SectionCard>

          <SectionCard title="Comparison by lane" description="Lihat stage/timeframe mana yang membaik atau melemah saat hanya memakai V3 shadow pass.">
            <LaneTable rows={data?.by_lane || []} />
          </SectionCard>

          <SectionCard title="V3 filter contribution" description="Filter mana yang menghasilkan V3 pass dan bagaimana hasilnya dibanding V2 all-signal baseline.">
            <FilterTable rows={data?.by_filter || []} />
          </SectionCard>

          <section className="grid gap-4 xl:grid-cols-2">
            <SectionCard title="Latest V3 pass signals" description="Contoh signal terbaru yang lolos shadow filter.">
              <SignalTable rows={data?.latest_pass_signals || []} />
            </SectionCard>
            <SectionCard title="Latest V3 fail signals" description="Contoh signal terbaru yang tidak lolos shadow filter.">
              <SignalTable rows={data?.latest_fail_signals || []} />
            </SectionCard>
          </section>

          <SectionCard title="Guardrails">
            <div className="grid gap-3 p-4 text-sm md:grid-cols-3">
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

function PerfGrid({ row }: { row?: SignalPerformanceBucket }) {
  return (
    <div className="grid gap-3 p-4 text-sm md:grid-cols-3">
      <Insight label="Evaluated" value={row?.signals_evaluated ?? 0} />
      <Insight label="TP / SL" value={`${row?.tp_count ?? 0} / ${row?.sl_count ?? 0}`} />
      <Insight label="Open" value={row?.open_count ?? 0} />
      <Insight label="Winrate" value={row?.winrate_pct == null ? "-" : `${fmtNumber(row.winrate_pct)}%`} />
      <Insight label="Total R" value={`${fmtSigned(row?.total_r_closed)}R`} />
      <Insight label="Avg R" value={`${fmtSigned(row?.avg_r_closed)}R`} />
    </div>
  );
}

function StatusTable({ rows }: { rows: V3ShadowStatusRow[] }) {
  return (
    <TableShell emptyTitle="No V3 status rows" colSpan={10}>
      <thead>
        <tr>
          <th>Status</th>
          <th>Sample</th>
          <th>Retain</th>
          <th>TP / SL / Open</th>
          <th>Winrate</th>
          <th>Total R</th>
          <th>Avg R</th>
          <th>Avg delta</th>
          <th>SL delta</th>
          <th>Verdict</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr key={row.bucket}>
            <td><StatusBadge value={row.bucket} /></td>
            <td>{row.sample_count}</td>
            <td>{fmtNumber(row.sample_retention_pct)}%</td>
            <td>{row.tp_count} / {row.sl_count} / {row.open_count}</td>
            <td>{row.winrate_pct == null ? "-" : `${fmtNumber(row.winrate_pct)}%`}</td>
            <td>{fmtSigned(row.total_r_closed)}R</td>
            <td>{fmtSigned(row.avg_r_closed)}R</td>
            <td>{fmtSigned(row.avg_r_delta_vs_v2)}R</td>
            <td>{fmtSigned(row.sl_share_delta_vs_v2)}%</td>
            <td><StatusBadge value={row.verdict} /></td>
          </tr>
        ))}
        {!rows.length && <EmptyRow colSpan={10} title="No V3 status rows" />}
      </tbody>
    </TableShell>
  );
}

function LaneTable({ rows }: { rows: V3ShadowLaneRow[] }) {
  return (
    <TableShell emptyTitle="No lane rows" colSpan={11}>
      <thead>
        <tr>
          <th>Lane</th>
          <th>V2 sample</th>
          <th>V3 pass</th>
          <th>Retain</th>
          <th>V2 R</th>
          <th>V3 R</th>
          <th>Avg delta</th>
          <th>Win delta</th>
          <th>SL delta</th>
          <th>No filter</th>
          <th>Verdict</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr key={`${row.stage}-${row.timeframe}`}>
            <td>
              <div className="font-semibold">{labelFor(row.stage)}</div>
              <div className="text-xs text-slate-500">{row.timeframe}</div>
            </td>
            <td>{row.v2_live.signals_evaluated}</td>
            <td>{row.v3_pass_count}</td>
            <td>{fmtNumber(row.sample_retention_pct)}%</td>
            <td>{fmtSigned(row.v2_live.total_r_closed)}R</td>
            <td>{fmtSigned(row.v3_shadow_pass.total_r_closed)}R</td>
            <td>{fmtSigned(row.avg_r_delta_v3_pass_vs_v2)}R</td>
            <td>{fmtSigned(row.winrate_delta_v3_pass_vs_v2)}%</td>
            <td>{fmtSigned(row.sl_share_delta_v3_pass_vs_v2)}%</td>
            <td>{row.v3_no_filter_count}</td>
            <td><StatusBadge value={row.verdict} /></td>
          </tr>
        ))}
        {!rows.length && <EmptyRow colSpan={11} title="No lane rows" />}
      </tbody>
    </TableShell>
  );
}

function FilterTable({ rows }: { rows: V3ShadowFilterRow[] }) {
  return (
    <TableShell emptyTitle="No V3 filter pass rows" colSpan={9}>
      <thead>
        <tr>
          <th>Filter</th>
          <th>Sample</th>
          <th>TP / SL</th>
          <th>Total R</th>
          <th>Avg R</th>
          <th>Avg delta</th>
          <th>Win delta</th>
          <th>SL delta</th>
          <th>Verdict</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr key={row.filter_id}>
            <td>
              <div className="font-semibold">{row.label}</div>
              <div className="text-xs text-slate-500">{row.expression}</div>
            </td>
            <td>{row.sample_count}</td>
            <td>{row.tp_count} / {row.sl_count}</td>
            <td>{fmtSigned(row.total_r_closed)}R</td>
            <td>{fmtSigned(row.avg_r_closed)}R</td>
            <td>{fmtSigned(row.avg_r_delta_vs_v2)}R</td>
            <td>{fmtSigned(row.winrate_delta_vs_v2)}%</td>
            <td>{fmtSigned(row.sl_share_delta_vs_v2)}%</td>
            <td><StatusBadge value={row.verdict} /></td>
          </tr>
        ))}
        {!rows.length && <EmptyRow colSpan={9} title="No V3 filter pass rows" />}
      </tbody>
    </TableShell>
  );
}

function SignalTable({ rows }: { rows: SignalPerformanceItem[] }) {
  return (
    <TableShell emptyTitle="No signal rows" colSpan={8}>
      <thead>
        <tr>
          <th>Time WIB</th>
          <th>Symbol</th>
          <th>TF</th>
          <th>Stage</th>
          <th>V3</th>
          <th>Result</th>
          <th>R</th>
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
            <td>
              <StatusBadge value={item.v3_shadow_status || "-"} />
              {item.v3_shadow_filter_label && <div className="mt-1 text-xs text-slate-500">{compactReason(item.v3_shadow_filter_label, 60)}</div>}
            </td>
            <td><StatusBadge value={item.result_status} /></td>
            <td>{fmtSigned(item.result_status === "OPEN" ? item.unrealized_r : item.realized_r)}R</td>
            <td className="text-xs">
              <div>Entry {fmtPrice(item.entry)}</div>
              <div>SL {fmtPrice(item.stop_loss)}</div>
              <div>TP {fmtPrice(item.take_profit)}</div>
            </td>
          </tr>
        ))}
        {!rows.length && <EmptyRow colSpan={8} title="No signal rows" />}
      </tbody>
    </TableShell>
  );
}

function TableShell({ children }: { children: ReactNode; emptyTitle: string; colSpan: number }) {
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
      <div className="mt-1 text-lg font-bold text-ink">{value}</div>
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
