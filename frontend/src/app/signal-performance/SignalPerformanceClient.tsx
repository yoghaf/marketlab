"use client";

import { useEffect, useMemo, useState } from "react";

import { EmptyState } from "@/components/EmptyState";
import { MetricCard } from "@/components/MetricCard";
import { SectionCard } from "@/components/SectionCard";
import { StatusBadge } from "@/components/StatusBadge";
import { SignalPerformanceBucket, SignalPerformanceResponse, fmtPrice } from "@/lib/api";
import { labelFor } from "@/lib/labels";

const stages = ["EARLY_LONG", "EARLY_SHORT", "MID_LONG", "MID_SHORT"];
const timeframes = ["15m", "1h", "4h", "24h"];

export function SignalPerformanceClient() {
  const [stage, setStage] = useState("");
  const [timeframe, setTimeframe] = useState("");
  const [includeWatchOnly, setIncludeWatchOnly] = useState(false);
  const [positionLock, setPositionLock] = useState(true);
  const [limit, setLimit] = useState(50);
  const [data, setData] = useState<SignalPerformanceResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const path = useMemo(() => {
    const query = new URLSearchParams();
    query.set("include_watch_only", String(includeWatchOnly));
    query.set("position_lock", String(positionLock));
    query.set("limit", String(limit));
    if (stage) query.set("stage", stage);
    if (timeframe) query.set("timeframe", timeframe);
    return `/api/signal-candidates/performance/live?${query.toString()}`;
  }, [includeWatchOnly, limit, positionLock, stage, timeframe]);

  async function load() {
    setLoading(true);
    try {
      const response = await fetch(path, { cache: "no-store" });
      if (!response.ok) throw new Error(`API failed: ${response.status}`);
      setData(await response.json());
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Gagal memuat signal performance");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    const timer = window.setInterval(load, 30_000);
    return () => window.clearInterval(timer);
  }, [path]);

  const aggregate = data?.aggregate;

  return (
    <div className="space-y-5">
      <section className="grid gap-3 md:grid-cols-2 xl:grid-cols-6">
        <MetricCard label="Total R Closed" value={`${fmtSigned(aggregate?.total_r_closed)}R`} helper="TP/SL/BOTH closed only" tone={Number(aggregate?.total_r_closed || 0) >= 0 ? "good" : "bad"} />
        <MetricCard label="Fixed-risk Return" value={`${fmtSigned(aggregate?.fixed_risk_return_pct_1pct_closed)}%`} helper="Jika 1R = 1% risk" tone={Number(aggregate?.fixed_risk_return_pct_1pct_closed || 0) >= 0 ? "good" : "bad"} />
        <MetricCard label="Winrate" value={aggregate?.winrate_pct == null ? "-" : `${fmtNumber(aggregate.winrate_pct)}%`} helper="TP / (TP + SL)" tone="info" />
        <MetricCard label="TP / SL" value={`${aggregate?.tp_count ?? 0} / ${aggregate?.sl_count ?? 0}`} helper={`${aggregate?.closed_count ?? 0} closed`} />
        <MetricCard label="Open" value={aggregate?.open_count ?? 0} helper={`${fmtSigned(aggregate?.open_unrealized_r)}R unrealized`} tone="warn" />
        <MetricCard label="Evaluated" value={aggregate?.signals_evaluated ?? 0} helper={`${aggregate?.signals_skipped ?? 0} skipped by lock`} />
      </section>

      <SectionCard
        title="Live paper controls"
        description="Filter ini tidak mengubah rule. Position lock membuat hitungan lebih mirip live: satu posisi aktif per symbol sampai TP/SL."
        actions={<button className="rounded border border-line px-3 py-2 text-sm font-semibold hover:bg-field" onClick={load} type="button">{loading ? "Menghitung..." : "Refresh now"}</button>}
      >
        <div className="grid gap-3 p-4 md:grid-cols-3 xl:grid-cols-6">
          <label className="grid gap-1 text-sm">
            <span className="font-semibold text-slate-600">Stage</span>
            <select className="rounded border border-line bg-white px-3 py-2" value={stage} onChange={(event) => setStage(event.target.value)}>
              <option value="">All stage</option>
              {stages.map((item) => <option key={item} value={item}>{item}</option>)}
            </select>
          </label>
          <label className="grid gap-1 text-sm">
            <span className="font-semibold text-slate-600">Timeframe</span>
            <select className="rounded border border-line bg-white px-3 py-2" value={timeframe} onChange={(event) => setTimeframe(event.target.value)}>
              <option value="">All timeframe</option>
              {timeframes.map((item) => <option key={item} value={item}>{item}</option>)}
            </select>
          </label>
          <label className="grid gap-1 text-sm">
            <span className="font-semibold text-slate-600">Limit rows</span>
            <input className="rounded border border-line px-3 py-2" min={10} max={500} type="number" value={limit} onChange={(event) => setLimit(clamp(Number(event.target.value), 10, 500))} />
          </label>
          <label className="flex items-center gap-2 pt-6 text-sm font-semibold text-slate-700">
            <input checked={positionLock} type="checkbox" onChange={(event) => setPositionLock(event.target.checked)} />
            Position lock
          </label>
          <label className="flex items-center gap-2 pt-6 text-sm font-semibold text-slate-700">
            <input checked={includeWatchOnly} type="checkbox" onChange={(event) => setIncludeWatchOnly(event.target.checked)} />
            Include WATCH_ONLY
          </label>
          <div className="pt-6 text-sm text-slate-600">
            Latest candle: {fmtTime(data?.latest_futures_15m_close_time)}
          </div>
        </div>
        {loading && !data && (
          <div className="border-t border-line bg-amber-50 p-4 text-sm text-slate-700">
            Menghitung ulang TP/SL paper-live dari candle futures. Ini read-only, bukan order.
          </div>
        )}
        {error && <div className="border-t border-line bg-red-50 p-4 text-sm text-stale">{error}</div>}
      </SectionCard>

      <SectionCard title="Performance by signal timeframe" description="Ini membagi hasil berdasarkan timeframe asal signal, bukan horizon evaluasi. Jika 4h/24h kosong berarti belum ada signal dari TF itu.">
        <div className="table-wrap">
          <table className="ops-table">
            <thead>
              <tr>
                <th>Signal TF</th>
                <th>Evaluated</th>
                <th>TP</th>
                <th>SL</th>
                <th>Open</th>
                <th>Waiting</th>
                <th>Winrate</th>
                <th>Total R</th>
                <th>Fixed-risk 1%</th>
                <th>With Open</th>
              </tr>
            </thead>
            <tbody>
              {timeframes.map((tf) => {
                const row = data?.aggregate.by_timeframe_performance?.[tf];
                return <TimeframeRow key={tf} timeframe={tf} row={row} />;
              })}
            </tbody>
          </table>
        </div>
      </SectionCard>

      <section className="grid gap-4 xl:grid-cols-3">
        <SectionCard title="Status counts">
          <KeyValueTable rows={data?.aggregate.status_counts || {}} />
        </SectionCard>
        <SectionCard title="Stage counts">
          <KeyValueTable rows={data?.aggregate.by_stage || {}} />
        </SectionCard>
        <SectionCard title="Confidence counts">
          <KeyValueTable rows={data?.aggregate.by_confidence || {}} />
        </SectionCard>
      </section>

      <SectionCard
        title="Signal Candidate paper positions"
        description="Entry/SL/TP berasal dari Signal Factory V2 log. Hasil dihitung ulang dari futures 15m candle terbaru saat halaman ini dibuka."
        actions={<StatusBadge value={positionLock ? "LOCK_BY_SYMBOL" : "NO_LOCK"} />}
      >
        <div className="table-wrap">
          <table className="ops-table">
            <thead>
              <tr>
                <th>Time WIB</th>
                <th>Symbol</th>
                <th>TF</th>
                <th>Stage</th>
                <th>Dir</th>
                <th>Status</th>
                <th>Entry</th>
                <th>SL</th>
                <th>TP</th>
                <th>R</th>
                <th>MFE/MAE</th>
                <th>Result Time</th>
              </tr>
            </thead>
            <tbody>
              {data?.items.map((item) => (
                <tr key={item.signal_id}>
                  <td>{item.signal_time_wib || fmtTime(item.signal_timestamp)}</td>
                  <td className="font-semibold">{item.symbol}</td>
                  <td>{item.timeframe}</td>
                  <td>{labelFor(item.stage)}</td>
                  <td><StatusBadge value={item.direction} /></td>
                  <td><StatusBadge value={item.result_status} /></td>
                  <td>{fmtPrice(item.entry)}</td>
                  <td>{fmtPrice(item.stop_loss)}</td>
                  <td>{fmtPrice(item.take_profit)}</td>
                  <td>{item.realized_r != null ? `${fmtSigned(item.realized_r)}R` : item.unrealized_r != null ? `${fmtSigned(item.unrealized_r)}R open` : "-"}</td>
                  <td>{fmtSigned(item.mfe_r)} / {fmtSigned(item.mae_r)}</td>
                  <td>{item.result_time_wib || fmtTime(item.result_time_utc)}</td>
                </tr>
              ))}
              {!data?.items.length && (
                <tr>
                  <td colSpan={12}><EmptyState title="Belum ada signal" detail="Belum ada SIGNAL_CANDIDATE dengan entry, SL, dan TP sesuai filter ini." /></td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </SectionCard>
    </div>
  );
}

function TimeframeRow({ timeframe, row }: { timeframe: string; row?: SignalPerformanceBucket }) {
  return (
    <tr>
      <td className="font-semibold">{timeframe}</td>
      <td>{row?.signals_evaluated ?? 0}</td>
      <td>{row?.tp_count ?? 0}</td>
      <td>{row?.sl_count ?? 0}</td>
      <td>{row?.open_count ?? 0}</td>
      <td>{row?.waiting_count ?? 0}</td>
      <td>{row?.winrate_pct == null ? "-" : `${fmtNumber(row.winrate_pct)}%`}</td>
      <td>{fmtSigned(row?.total_r_closed)}R</td>
      <td>{fmtSigned(row?.fixed_risk_return_pct_1pct_closed)}%</td>
      <td>{fmtSigned(row?.total_r_with_open)}R</td>
    </tr>
  );
}

function KeyValueTable({ rows }: { rows: Record<string, number> }) {
  const entries = Object.entries(rows);
  return (
    <div className="p-4">
      {entries.length ? (
        <div className="space-y-2 text-sm">
          {entries.map(([key, value]) => (
            <div className="flex items-center justify-between gap-3" key={key}>
              <span>{labelFor(key)}</span>
              <span className="font-semibold">{value}</span>
            </div>
          ))}
        </div>
      ) : (
        <div className="text-sm text-slate-500">No rows</div>
      )}
    </div>
  );
}

function fmtNumber(value?: string | number | null): string {
  if (value === null || value === undefined || value === "") return "-";
  const num = Number(value);
  if (!Number.isFinite(num)) return String(value);
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 4 }).format(num);
}

function fmtSigned(value?: string | number | null): string {
  if (value === null || value === undefined || value === "") return "-";
  const num = Number(value);
  if (!Number.isFinite(num)) return String(value);
  return `${num >= 0 ? "+" : ""}${new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 }).format(num)}`;
}

function fmtTime(value?: string | null): string {
  if (!value) return "-";
  return new Intl.DateTimeFormat("en-GB", {
    dateStyle: "short",
    timeStyle: "medium",
    timeZone: "Asia/Jakarta"
  }).format(new Date(value));
}

function clamp(value: number, min: number, max: number): number {
  if (!Number.isFinite(value)) return min;
  return Math.min(Math.max(Math.trunc(value), min), max);
}
