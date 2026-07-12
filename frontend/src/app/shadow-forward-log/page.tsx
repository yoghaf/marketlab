import Link from "next/link";

import { MetricCard } from "@/components/MetricCard";
import { PageHeader } from "@/components/PageHeader";
import { SectionCard } from "@/components/SectionCard";
import { StatusBadge } from "@/components/StatusBadge";
import {
  MidShortShadowForwardLogResponse,
  SignalPerformanceItem,
  fetchJson,
  fmtNumber,
  fmtPrice,
  fmtTime
} from "@/lib/api";
import { labelFor } from "@/lib/labels";

type SearchParams = Promise<Record<string, string | string[] | undefined>>;

export const dynamic = "force-dynamic";

export default async function ShadowForwardLogPage({ searchParams }: { searchParams: SearchParams }) {
  const params = await searchParams;
  const includeWatchOnly = firstParam(params.include_watch_only) === "true";
  const positionLock = firstParam(params.position_lock) !== "false";
  const resultStatus = firstParam(params.result_status);
  const limit = normalizeNumber(firstParam(params.limit), 100, 10, 300);
  const query = new URLSearchParams({
    include_watch_only: String(includeWatchOnly),
    position_lock: String(positionLock),
    limit: String(limit)
  });
  if (resultStatus) query.set("result_status", resultStatus);

  let data: MidShortShadowForwardLogResponse | null = null;
  let error: string | null = null;
  try {
    data = await fetchJson<MidShortShadowForwardLogResponse>(
      `/api/signal-candidates/mid-short-1h-shadow-forward-log?${query.toString()}`
    );
  } catch (err) {
    error = err instanceof Error ? err.message : "Shadow Forward Log API failed";
  }

  const pass = data?.by_shadow_status.find((row) => row.shadow_status === "SHADOW_PASS");
  const fail = data?.by_shadow_status.find((row) => row.shadow_status === "SHADOW_FAIL");
  const unavailable = data?.by_shadow_status.find((row) => row.shadow_status === "SHADOW_UNAVAILABLE");

  return (
    <div className="space-y-5">
      <PageHeader
        title="MID_SHORT 1h Shadow Forward Log"
        badge="READ-ONLY SHADOW MONITOR"
        subtitle="Log forward untuk memantau apakah filter MID_SHORT 1h fill-good + range/ATR bersih benar-benar memisahkan signal yang lebih sehat. Ini tidak mengubah rule Signal Factory, scanner, TP/SL, atau execution."
        updatedAt={fmtTime(data?.generated_at_utc)}
      />

      <div className="flex flex-wrap gap-2 text-sm">
        <Link className="rounded border border-line bg-white px-3 py-2 font-semibold hover:bg-field" href="/signal-quality-lab?stage=MID_SHORT&timeframe=1h&position_lock=false">Open Quality Lab</Link>
        <Link className="rounded border border-line bg-white px-3 py-2 font-semibold hover:bg-field" href="/scanner?tier=SIGNAL_CANDIDATE&limit=75">Open Radar Signal</Link>
        <Link className="rounded border border-line bg-white px-3 py-2 font-semibold hover:bg-field" href="/signal-performance">Open Signal History</Link>
      </div>

      {error ? (
        <div className="rounded border border-stale bg-red-50 p-4 text-sm text-stale">{error}</div>
      ) : (
        <>
          <section className="grid gap-3 md:grid-cols-2 xl:grid-cols-6">
            <MetricCard label="Source MID_SHORT 1h" value={data?.summary.source_count ?? 0} helper={`${sumSkipped(data)} skipped by lock`} />
            <MetricCard label="Shadow pass" value={data?.summary.pass_count ?? 0} helper={`${fmtNumber(data?.summary.pass_retention_pct)}% retained`} tone="good" />
            <MetricCard label="Shadow fail" value={data?.summary.fail_count ?? 0} helper={`${fmtNumber(data?.summary.fail_retention_pct)}% filtered`} tone="warn" />
            <MetricCard label="Unavailable" value={data?.summary.unavailable_count ?? 0} helper="Missing range/ATR or fill quality" />
            <MetricCard label="Pass vs fail delta" value={`${fmtSigned(data?.summary.realistic_total_r_delta_pass_vs_fail)}R`} helper="Realistic total R delta" tone={Number(data?.summary.realistic_total_r_delta_pass_vs_fail || 0) >= 0 ? "good" : "bad"} />
            <MetricCard label="Latest candle" value={fmtTime(data?.latest_evaluation_candle_time)} helper="15m + 1m tail" />
          </section>

          <SectionCard
            title="Shadow controls"
            description="Filter ini hanya mengubah tampilan log. Tidak mengubah rule live."
          >
            <form className="grid gap-3 p-4 text-sm md:grid-cols-5">
              <label className="grid gap-1">
                <span className="font-semibold text-slate-600">Result status</span>
                <select className="rounded border border-line px-3 py-2" name="result_status" defaultValue={resultStatus || ""}>
                  <option value="">All result</option>
                  <option value="CLOSED">Closed only</option>
                  <option value="OPEN">Open only</option>
                  <option value="TP_SL">TP/SL only</option>
                </select>
              </label>
              <label className="grid gap-1">
                <span className="font-semibold text-slate-600">Limit rows</span>
                <input className="rounded border border-line px-3 py-2" min={10} max={300} name="limit" type="number" defaultValue={limit} />
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

          <SectionCard
            title="Filter definition"
            description={data?.shadow_filter.expression || "MID_SHORT 1h quality shadow filter."}
          >
            <div className="grid gap-3 p-4 text-sm md:grid-cols-3">
              <Info label="Filter ID" value={data?.shadow_filter.filter_id} />
              <Info label="Label" value={data?.shadow_filter.label} />
              <Info label="Read" value={data?.summary.read} />
            </div>
          </SectionCard>

          <SectionCard title="Forward result by shadow status" description="Bandingkan PASS, FAIL, dan UNAVAILABLE memakai realistic R paper-live.">
            <div className="table-wrap">
              <table className="ops-table">
                <thead>
                  <tr>
                    <th>Status</th>
                    <th>Sample</th>
                    <th>TP / SL / Open</th>
                    <th>Winrate</th>
                    <th>Ideal R</th>
                    <th>Realistic R</th>
                    <th>Avg realistic</th>
                    <th>SL share</th>
                    <th>Max DD</th>
                    <th>Read</th>
                  </tr>
                </thead>
                <tbody>
                  {(data?.by_shadow_status || []).map((row) => (
                    <tr key={row.shadow_status}>
                      <td>
                        <StatusBadge value={row.shadow_status} />
                        <div className="mt-1 text-xs text-slate-500">{row.label}</div>
                      </td>
                      <td>{row.sample_count}</td>
                      <td>{row.tp_count} / {row.sl_count} / {row.open_count}</td>
                      <td>{row.winrate_pct == null ? "-" : `${fmtNumber(row.winrate_pct)}%`}</td>
                      <td>{fmtSigned(row.total_r_closed)}R</td>
                      <td>{fmtSigned(row.realistic_total_r_closed)}R</td>
                      <td>{fmtSigned(row.realistic_avg_r_closed)}R</td>
                      <td>{row.sl_share_pct == null ? "-" : `${fmtNumber(row.sl_share_pct)}%`}</td>
                      <td>{fmtSigned(row.max_realistic_drawdown_r)}R</td>
                      <td className="max-w-sm text-slate-600">{row.read}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </SectionCard>

          <section className="grid gap-4 xl:grid-cols-3">
            <SignalList title="Latest SHADOW_PASS" items={data?.latest_pass_signals || []} tone="good" />
            <SignalList title="Latest SHADOW_FAIL" items={data?.latest_fail_signals || []} tone="warn" />
            <SignalList title="Latest SHADOW_UNAVAILABLE" items={data?.latest_unavailable_signals || []} />
          </section>

          <SectionCard title="All latest MID_SHORT 1h rows" description="Gabungan terbaru sesuai filter. Klik symbol untuk membuka detail signal.">
            <SignalTable items={data?.items || []} />
          </SectionCard>

          <SectionCard title="Guardrails" description="Batasan supaya log ini tidak dibaca sebagai execution.">
            <ul className="grid gap-2 p-4 text-sm text-slate-700 md:grid-cols-2">
              {(data?.guardrails || []).map((item) => <li key={item} className="rounded border border-line bg-field/40 p-3">{item}</li>)}
            </ul>
          </SectionCard>
        </>
      )}
    </div>
  );
}

function SignalList({ title, items, tone = "neutral" }: { title: string; items: SignalPerformanceItem[]; tone?: "good" | "warn" | "neutral" }) {
  const border = tone === "good" ? "border-emerald-200" : tone === "warn" ? "border-amber-200" : "border-line";
  return (
    <section className={`rounded-md border bg-white ${border}`}>
      <div className="border-b border-line px-4 py-3">
        <h2 className="text-base font-bold text-ink">{title}</h2>
        <p className="mt-1 text-sm text-slate-600">{items.length} rows</p>
      </div>
      <div className="divide-y divide-line">
        {items.slice(0, 8).map((item) => (
          <Link key={item.signal_id} className="block p-4 text-sm hover:bg-field" href={`/signals/${item.signal_id}`}>
            <div className="flex items-center justify-between gap-2">
              <span className="font-bold text-blue-700">{item.symbol}</span>
              <StatusBadge value={item.result_status} />
            </div>
            <div className="mt-2 grid grid-cols-2 gap-2 text-xs text-slate-600">
              <span>{item.signal_time_wib || fmtTime(item.signal_timestamp)}</span>
              <span>{labelFor(item.stage)} {item.timeframe}</span>
              <span>Realistic {fmtSigned(item.realistic_realized_r ?? item.realistic_unrealized_r)}R</span>
              <span>Range/ATR {fmtNumber(item.quality_shadow_range_ratio_vs_atr)}</span>
            </div>
            <p className="mt-2 text-xs text-slate-500">{item.quality_shadow_reason || "-"}</p>
          </Link>
        ))}
        {!items.length && <div className="p-4 text-sm text-slate-500">No rows</div>}
      </div>
    </section>
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
            <th>Result</th>
            <th>Shadow</th>
            <th>Realistic R</th>
            <th>Ideal R</th>
            <th>MFE / MAE</th>
            <th>Entry / SL / TP</th>
            <th>Fill</th>
            <th>Reason</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item) => (
            <tr key={item.signal_id}>
              <td>{item.signal_time_wib || fmtTime(item.signal_timestamp)}</td>
              <td><Link className="font-semibold text-blue-700 hover:underline" href={`/signals/${item.signal_id}`}>{item.symbol}</Link></td>
              <td><StatusBadge value={item.result_status} /></td>
              <td><StatusBadge value={item.quality_shadow_status || "-"} /></td>
              <td>{fmtSigned(item.realistic_realized_r ?? item.realistic_unrealized_r)}R</td>
              <td>{fmtSigned(item.realized_r ?? item.unrealized_r)}R</td>
              <td>{fmtSigned(item.mfe_r)} / {fmtSigned(item.mae_r)}</td>
              <td className="text-xs">
                <div>Entry {fmtPrice(item.entry)}</div>
                <div>SL {fmtPrice(item.stop_loss)}</div>
                <div>TP {fmtPrice(item.take_profit)}</div>
              </td>
              <td className="text-xs">
                <div>{item.realistic_fill_quality || "-"}</div>
                <div>Range/ATR {fmtNumber(item.quality_shadow_range_ratio_vs_atr)}</div>
              </td>
              <td className="max-w-md text-xs text-slate-600">{item.quality_shadow_reason || "-"}</td>
            </tr>
          ))}
          {!items.length && (
            <tr>
              <td colSpan={10} className="py-8 text-center text-sm text-slate-500">No shadow rows for current filter.</td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

function Info({ label, value }: { label: string; value?: string | number | null }) {
  return (
    <div className="rounded border border-line bg-field/40 p-3">
      <div className="text-xs font-semibold uppercase text-slate-500">{label}</div>
      <div className="mt-1 break-words text-sm font-semibold text-ink">{value || "-"}</div>
    </div>
  );
}

function firstParam(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

function normalizeNumber(value: string | undefined, fallback: number, min: number, max: number): number {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.max(min, Math.min(max, Math.trunc(parsed)));
}

function fmtSigned(value?: string | number | null): string {
  if (value === null || value === undefined || value === "") return "-";
  const num = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(num)) return String(value);
  return `${num >= 0 ? "+" : ""}${fmtNumber(num)}`;
}

function sumSkipped(data: MidShortShadowForwardLogResponse | null): number {
  return Object.values(data?.skipped_by_position_lock || {}).reduce((total, value) => total + Number(value || 0), 0);
}
