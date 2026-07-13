import Link from "next/link";

import { MetricCard } from "@/components/MetricCard";
import { PageHeader } from "@/components/PageHeader";
import { SectionCard } from "@/components/SectionCard";
import { StatusBadge } from "@/components/StatusBadge";
import {
  MidShortFailureBucketRow,
  MidShortSecondFilterRow,
  MidShortSecondFilterShadowResponse,
  SignalPerformanceItem,
  fetchJson,
  fmtNumber,
  fmtPrice,
  fmtTime
} from "@/lib/api";
import { labelFor } from "@/lib/labels";

type SearchParams = Promise<Record<string, string | string[] | undefined>>;

export const dynamic = "force-dynamic";

export default async function MidShortSecondFilterShadowPage({ searchParams }: { searchParams: SearchParams }) {
  const params = await searchParams;
  const includeWatchOnly = firstParam(params.include_watch_only) === "true";
  const positionLock = firstParam(params.position_lock) !== "false";
  const shadowStatus = firstParam(params.shadow_status) || "SHADOW_PASS";
  const minSample = normalizeNumber(firstParam(params.min_sample), 20, 1, 100);
  const limit = normalizeNumber(firstParam(params.limit), 50, 10, 150);
  const query = new URLSearchParams({
    include_watch_only: String(includeWatchOnly),
    position_lock: String(positionLock),
    shadow_status: shadowStatus,
    min_sample: String(minSample),
    limit: String(limit)
  });

  let data: MidShortSecondFilterShadowResponse | null = null;
  let error: string | null = null;
  try {
    data = await fetchJson<MidShortSecondFilterShadowResponse>(
      `/api/signal-candidates/mid-short-1h-second-filter-shadow?${query.toString()}`
    );
  } catch (err) {
    error = err instanceof Error ? err.message : "Second Filter Shadow API failed";
  }

  const summary = data?.summary;
  const baseline = summary?.baseline;

  return (
    <div className="space-y-5">
      <PageHeader
        title="MID_SHORT 1h Second Filter Shadow"
        badge="READ-ONLY RESEARCH"
        subtitle="Riset lanjutan setelah Failure Anatomy: uji filter tambahan di dalam scope MID_SHORT 1h SHADOW_PASS untuk melihat mana yang mengurangi SL, salah arah, dan timing stop. Ini belum mengubah rule live."
        updatedAt={fmtTime(data?.generated_at_utc)}
      />

      <div className="flex flex-wrap gap-2 text-sm">
        <Link className="rounded border border-line bg-white px-3 py-2 font-semibold hover:bg-field" href="/mid-short-failure-anatomy">Open Failure Anatomy</Link>
        <Link className="rounded border border-line bg-white px-3 py-2 font-semibold hover:bg-field" href="/shadow-forward-log">Open Shadow Log</Link>
        <Link className="rounded border border-line bg-white px-3 py-2 font-semibold hover:bg-field" href="/signal-quality-lab?stage=MID_SHORT&timeframe=1h">Open Quality Lab</Link>
        <Link className="rounded border border-line bg-white px-3 py-2 font-semibold hover:bg-field" href="/signal-performance?stage=MID_SHORT&timeframe=1h">Open Signal History</Link>
      </div>

      {error ? (
        <div className="rounded border border-stale bg-red-50 p-4 text-sm text-stale">{error}</div>
      ) : (
        <>
          <section className="grid gap-3 md:grid-cols-2 xl:grid-cols-6">
            <MetricCard label="Scope sample" value={summary?.source_count ?? 0} helper={`${baseline?.closed_count ?? 0} baseline closed`} />
            <MetricCard label="Baseline realistic" value={`${fmtSigned(baseline?.realistic_total_r_closed)}R`} helper={`${baseline?.tp_count ?? 0} TP / ${baseline?.sl_count ?? 0} SL`} tone={Number(baseline?.realistic_total_r_closed || 0) >= 0 ? "good" : "bad"} />
            <MetricCard label="Filter tested" value={summary?.filter_count ?? 0} helper={`${summary?.monitor_count ?? 0} monitor`} />
            <MetricCard label="Reduce damage" value={summary?.damage_reduction_count ?? 0} helper="Avg R, SL share, atau wrong direction membaik" tone="warn" />
            <MetricCard label="Top filter" value={summary?.top_filter_label || "-"} helper={summary?.top_filter_id || "-"} />
            <MetricCard label="Latest candle" value={fmtTime(data?.latest_evaluation_candle_time)} helper={data?.cache?.hit ? "cache hit" : "fresh read"} />
          </section>

          <SectionCard title="Second filter controls" description="Filter ini hanya mengubah audit halaman. Signal Factory, scanner, TP/SL, dan execution tidak berubah.">
            <form className="grid gap-3 p-4 text-sm md:grid-cols-5">
              <label className="grid gap-1">
                <span className="font-semibold text-slate-600">Shadow status</span>
                <select className="rounded border border-line px-3 py-2" name="shadow_status" defaultValue={shadowStatus}>
                  <option value="SHADOW_PASS">SHADOW_PASS</option>
                  <option value="SHADOW_FAIL">SHADOW_FAIL</option>
                  <option value="SHADOW_UNAVAILABLE">SHADOW_UNAVAILABLE</option>
                  <option value="ALL">ALL</option>
                </select>
              </label>
              <label className="grid gap-1">
                <span className="font-semibold text-slate-600">Min sample</span>
                <input className="rounded border border-line px-3 py-2" min={1} max={100} name="min_sample" type="number" defaultValue={minSample} />
              </label>
              <label className="grid gap-1">
                <span className="font-semibold text-slate-600">Limit rows</span>
                <input className="rounded border border-line px-3 py-2" min={10} max={150} name="limit" type="number" defaultValue={limit} />
              </label>
              <label className="grid gap-1">
                <span className="font-semibold text-slate-600">Position lock</span>
                <select className="rounded border border-line px-3 py-2" name="position_lock" defaultValue={String(positionLock)}>
                  <option value="true">true</option>
                  <option value="false">false</option>
                </select>
              </label>
              <label className="flex items-end gap-2 pb-2 font-semibold text-slate-600">
                <input name="include_watch_only" type="checkbox" value="true" defaultChecked={includeWatchOnly} />
                Include WATCH_ONLY
              </label>
              <div className="flex items-end">
                <button className="rounded border border-line bg-white px-4 py-2 font-semibold hover:bg-field" type="submit">Apply</button>
              </div>
            </form>
          </SectionCard>

          <SectionCard title="Filter comparison vs baseline" description="Yang dicari bukan cuma Total R naik, tapi SL share turun, wrong-direction turun, dan timing stop lebih bersih. Semua read-only.">
            <FilterTable rows={data?.filter_rows || []} />
          </SectionCard>

          <section className="grid gap-4 xl:grid-cols-[1fr_1.4fr]">
            <SectionCard title="Baseline failure paths" description="Baseline path dari semua MID_SHORT 1h dalam shadow scope sebelum filter tambahan.">
              <PathTable rows={data?.baseline_path_rows || []} />
            </SectionCard>
            <SectionCard title="Latest rows from top filter" description="Signal terbaru yang lolos filter ranking teratas; klik Open untuk detail signal.">
              <SignalTable items={data?.top_filter_items || []} />
            </SectionCard>
          </section>

          <SectionCard title="Current shadow scope" description="Filter utama yang sedang dibedah sebelum second filter.">
            <div className="grid gap-3 p-4 text-sm md:grid-cols-2 xl:grid-cols-4">
              <Info label="Shadow filter" value={data?.shadow_filter.label || "-"} />
              <Info label="Expression" value={data?.shadow_filter.expression || "-"} />
              <Info label="Status meaning" value={data?.shadow_filter.status_meaning || "-"} />
              <Info label="Study scope" value={data?.study_scope || "-"} />
            </div>
          </SectionCard>

          <SectionCard title="Guardrails" description="Batasan interpretasi halaman ini.">
            <ul className="grid gap-2 p-4 text-sm text-slate-700 md:grid-cols-2">
              {(data?.guardrails || []).map((item) => <li key={item} className="rounded border border-line bg-field/40 p-3">{item}</li>)}
            </ul>
          </SectionCard>
        </>
      )}
    </div>
  );
}

function FilterTable({ rows }: { rows: MidShortSecondFilterRow[] }) {
  return (
    <div className="table-wrap">
      <table className="ops-table">
        <thead>
          <tr>
            <th>Filter</th>
            <th>Family</th>
            <th>Sample</th>
            <th>TP / SL / Open</th>
            <th>Retain</th>
            <th>Realistic R</th>
            <th>Avg delta</th>
            <th>SL share delta</th>
            <th>Wrong-dir delta</th>
            <th>SL then TP delta</th>
            <th>Near TP then SL delta</th>
            <th>Read</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.filter_id}>
              <td className="max-w-xl">
                <div className="font-semibold">{row.label}</div>
                <div className="text-xs text-slate-500">{row.expression}</div>
                {row.missing_data_count ? <div className="mt-1 text-xs text-warmup">Missing {row.missing_data_count} ({fmtPct(row.missing_data_pct)})</div> : null}
              </td>
              <td>{labelFor(row.family)}</td>
              <td>{row.sample_count}</td>
              <td>{row.tp_count} / {row.sl_count} / {row.open_count}</td>
              <td>{fmtPct(row.sample_retention_pct)}</td>
              <td className={Number(row.realistic_total_r_closed || 0) >= 0 ? "font-semibold text-ready" : "font-semibold text-stale"}>{fmtSigned(row.realistic_total_r_closed)}R</td>
              <td>{fmtSigned(row.realistic_avg_r_delta_vs_baseline)}R</td>
              <td>{fmtPctDelta(row.sl_share_delta_vs_baseline)}</td>
              <td>{fmtPctDelta(row.wrong_direction_1h_share_pct_delta_vs_baseline)}</td>
              <td>{fmtPctDelta(row.sl_then_would_tp_share_pct_delta_vs_baseline)}</td>
              <td>{fmtPctDelta(row.tp_near_then_sl_share_pct_delta_vs_baseline)}</td>
              <td><StatusBadge value={row.read} /></td>
            </tr>
          ))}
          {!rows.length && (
            <tr>
              <td colSpan={12} className="py-8 text-center text-sm text-slate-500">No second-filter rows</td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

function PathTable({ rows }: { rows: MidShortFailureBucketRow[] }) {
  return (
    <div className="table-wrap">
      <table className="ops-table">
        <thead>
          <tr>
            <th>Path</th>
            <th>Sample</th>
            <th>TP / SL / Open</th>
            <th>SL share</th>
            <th>Realistic R</th>
            <th>Read</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.bucket}>
              <td><StatusBadge value={row.bucket} /></td>
              <td>{row.sample_count}</td>
              <td>{row.tp_count} / {row.sl_count} / {row.open_count}</td>
              <td>{fmtPct(row.sl_share_pct)}</td>
              <td>{fmtSigned(row.realistic_total_r_closed)}R</td>
              <td className="max-w-md text-slate-600">{row.read}</td>
            </tr>
          ))}
          {!rows.length && (
            <tr>
              <td colSpan={6} className="py-8 text-center text-sm text-slate-500">No path rows</td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

function SignalTable({ items }: { items: SignalPerformanceItem[] }) {
  return (
    <div className="table-wrap">
      <table className="ops-table">
        <thead>
          <tr>
            <th>Time WIB</th>
            <th>Symbol</th>
            <th>Status</th>
            <th>Realistic R</th>
            <th>MFE / MAE</th>
            <th>Entry / SL / TP</th>
            <th>Detail</th>
          </tr>
        </thead>
        <tbody>
          {items.slice(0, 25).map((item) => (
            <tr key={item.signal_id}>
              <td>{item.signal_time_wib || fmtTime(item.signal_timestamp)}</td>
              <td className="font-semibold text-blue-700">{item.symbol}</td>
              <td><StatusBadge value={item.result_status} /></td>
              <td>{fmtSigned(item.realistic_realized_r ?? item.realistic_unrealized_r)}R</td>
              <td>{fmtSigned(item.mfe_r)} / {fmtSigned(item.mae_r)}</td>
              <td className="text-xs">
                <div>Entry {fmtPrice(item.entry)}</div>
                <div>SL {fmtPrice(item.stop_loss)}</div>
                <div>TP {fmtPrice(item.take_profit)}</div>
              </td>
              <td><Link className="font-semibold text-blue-700 hover:underline" href={`/signals/${item.signal_id}`}>Open</Link></td>
            </tr>
          ))}
          {!items.length && (
            <tr>
              <td colSpan={7} className="py-8 text-center text-sm text-slate-500">No top-filter signals</td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

function Info({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded border border-line bg-field/50 p-3">
      <div className="text-xs font-semibold uppercase text-slate-500">{label}</div>
      <div className="mt-1 text-sm font-semibold text-ink">{value}</div>
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
  if (Math.abs(num) < 0.005) return "0";
  return `${num > 0 ? "+" : ""}${fmtNumber(num)}`;
}

function fmtPct(value?: string | number | null): string {
  if (value === null || value === undefined || value === "") return "-";
  return `${fmtNumber(value)}%`;
}

function fmtPctDelta(value?: string | number | null): string {
  if (value === null || value === undefined || value === "") return "-";
  return `${fmtSigned(value)}%`;
}
