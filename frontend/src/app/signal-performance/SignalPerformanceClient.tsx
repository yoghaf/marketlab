"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { EmptyState } from "@/components/EmptyState";
import { MetricCard } from "@/components/MetricCard";
import { SectionCard } from "@/components/SectionCard";
import { StatusBadge } from "@/components/StatusBadge";
import { SignalForwardIntegrityResponse, SignalPerformanceBucket, SignalPerformanceItem, SignalPerformanceResponse, fmtPrice } from "@/lib/api";
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
  const [integrityData, setIntegrityData] = useState<SignalForwardIntegrityResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const path = useMemo(() => {
    const query = new URLSearchParams();
    query.set("include_watch_only", String(includeWatchOnly));
    query.set("position_lock", String(positionLock));
    query.set("result_status", "closed");
    query.set("limit", String(limit));
    if (stage) query.set("stage", stage);
    if (timeframe) query.set("timeframe", timeframe);
    return `/api/signal-candidates/performance/live?${query.toString()}`;
  }, [includeWatchOnly, limit, positionLock, stage, timeframe]);

  const integrityPath = useMemo(() => {
    const query = new URLSearchParams();
    query.set("include_watch_only", String(includeWatchOnly));
    query.set("position_lock", String(positionLock));
    query.set("limit", "50");
    if (stage) query.set("stage", stage);
    if (timeframe) query.set("timeframe", timeframe);
    return `/api/signals/forward-integrity?${query.toString()}`;
  }, [includeWatchOnly, positionLock, stage, timeframe]);

  async function load() {
    setLoading(true);
    try {
      const [performanceResponse, integrityResponse] = await Promise.all([
        fetch(path, { cache: "no-store" }),
        fetch(integrityPath, { cache: "no-store" })
      ]);
      if (!performanceResponse.ok) throw new Error(`Performance API failed: ${performanceResponse.status}`);
      if (!integrityResponse.ok) throw new Error(`Forward integrity API failed: ${integrityResponse.status}`);
      setData(await performanceResponse.json());
      setIntegrityData(await integrityResponse.json());
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
  }, [path, integrityPath]);

  const aggregate = data?.aggregate;

  return (
    <div className="space-y-5">
      <section className="grid gap-3 md:grid-cols-2 xl:grid-cols-6">
        <MetricCard label="Ideal R Closed" value={`${fmtSigned(aggregate?.total_r_closed)}R`} helper="Candle high/low ideal" tone={Number(aggregate?.total_r_closed || 0) >= 0 ? "good" : "bad"} />
        <MetricCard label="Realistic R Closed" value={`${fmtSigned(aggregate?.realistic_total_r_closed)}R`} helper="Binance taker fee + spread + slippage" tone={Number(aggregate?.realistic_total_r_closed || 0) >= 0 ? "good" : "bad"} />
        <MetricCard label="Realism penalty" value={`${fmtSigned(aggregate?.realism_penalty_r_closed)}R`} helper="Selisih ideal vs realistic" tone={Number(aggregate?.realism_penalty_r_closed || 0) > 0 ? "warn" : "good"} />
        <MetricCard label="Winrate" value={aggregate?.winrate_pct == null ? "-" : `${fmtNumber(aggregate.winrate_pct)}%`} helper="TP / (TP + SL)" tone="info" />
        <MetricCard label="TP / SL" value={`${aggregate?.tp_count ?? 0} / ${aggregate?.sl_count ?? 0}`} helper={`${aggregate?.closed_count ?? 0} closed`} />
        <MetricCard label="Open realistic" value={`${fmtSigned(aggregate?.realistic_open_unrealized_r)}R`} helper={`${aggregate?.open_count ?? 0} open / ${aggregate?.signals_skipped ?? 0} skipped`} tone="warn" />
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
            Latest eval candle: {fmtTime(data?.latest_evaluation_candle_time || data?.latest_futures_15m_close_time)}
            <div className="text-xs text-slate-500">{data?.evaluation_candle_interval || "1m_closed"}</div>
          </div>
        </div>
        {loading && !data && (
          <div className="border-t border-line bg-amber-50 p-4 text-sm text-slate-700">
            Menghitung ulang TP/SL paper-live dari candle futures. Ini read-only, bukan order.
          </div>
        )}
        {error && <div className="border-t border-line bg-red-50 p-4 text-sm text-stale">{error}</div>}
      </SectionCard>

      <ForwardIntegrityPanel data={integrityData} />

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
                <th>Winrate</th>
                <th>Ideal R</th>
                <th>Realistic R</th>
                <th>Penalty</th>
                <th>Realistic with open</th>
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
        title="Signal paper positions"
        description="Hanya signal yang sudah close TP/SL/BOTH. Posisi yang masih open dibuka dari halaman detail signal di Radar."
        actions={<StatusBadge value={positionLock ? "LOCK_BY_SYMBOL" : "NO_LOCK"} />}
      >
        <div className="table-wrap">
          <table className="ops-table">
            <thead>
              <tr>
                <th>Time WIB</th>
                <th>Symbol</th>
                <th>TF</th>
                <th>Strategy</th>
                <th>Stage</th>
                <th>Dir</th>
                <th>Status</th>
                <th>Entry</th>
                <th>SL</th>
                <th>TP</th>
                <th>Ideal R</th>
                <th>Realistic R</th>
                <th>Penalty</th>
                <th>Fill</th>
                <th>MFE/MAE</th>
                <th>Result Time</th>
              </tr>
            </thead>
            <tbody>
              {data?.items.map((item) => (
                <tr key={item.signal_id}>
                  <td>{item.signal_time_wib || fmtTime(item.signal_timestamp)}</td>
                  <td className="font-semibold">
                    <Link
                      className="text-blue-700 hover:underline"
                      href={`/signals/${encodeURIComponent(item.symbol)}?signal_id=${encodeURIComponent(item.signal_id)}`}
                    >
                      {item.symbol}
                    </Link>
                  </td>
                  <td>{item.timeframe}</td>
                  <td className="min-w-44">
                    <div className="space-y-1 text-xs">
                      <StatusBadge value={shortStrategy(item.strategy_version)} />
                      <StatusBadge value={item.v3_shadow_status || "V3_SHADOW_UNKNOWN"} />
                      {item.v3_shadow_filter_label ? (
                        <div className="text-slate-600">{item.v3_shadow_filter_label}</div>
                      ) : null}
                    </div>
                  </td>
                  <td>{labelFor(item.stage)}</td>
                  <td><StatusBadge value={item.direction} /></td>
                  <td><StatusBadge value={item.result_status} /></td>
                  <td>{fmtPrice(item.entry)}</td>
                  <td>{fmtPrice(item.stop_loss)}</td>
                  <td>{fmtPrice(item.take_profit)}</td>
                  <td>{item.realized_r != null ? `${fmtSigned(item.realized_r)}R` : item.unrealized_r != null ? `${fmtSigned(item.unrealized_r)}R open` : "-"}</td>
                  <td>{item.realistic_realized_r != null ? `${fmtSigned(item.realistic_realized_r)}R` : item.realistic_unrealized_r != null ? `${fmtSigned(item.realistic_unrealized_r)}R open` : "-"}</td>
                  <td>{item.realism_penalty_r == null ? "-" : `${fmtSigned(item.realism_penalty_r)}R`}</td>
                  <td><StatusBadge value={item.realistic_fill_quality || "FILL_UNKNOWN"} /></td>
                  <td>{fmtSigned(item.mfe_r)} / {fmtSigned(item.mae_r)}</td>
                  <td>{item.result_time_wib || fmtTime(item.result_time_utc)}</td>
                </tr>
              ))}
              {!data?.items.length && (
                <tr>
                  <td colSpan={16}><EmptyState title="Belum ada signal" detail="Belum ada Signal dengan entry, SL, dan TP sesuai filter ini." /></td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </SectionCard>
    </div>
  );
}

function ForwardIntegrityPanel({ data }: { data: SignalForwardIntegrityResponse | null }) {
  const summary = data?.summary;
  const hasStale = Number(summary?.stale_forward_count || 0) > 0;
  const hasWaiting = Number(summary?.waiting_data_count || 0) > 0;
  const tone = hasStale ? "bad" : hasWaiting ? "warn" : "good";

  return (
    <SectionCard
      title="Forward integrity audit"
      description="Audit posisi paper yang masih open/waiting/stale. Ini memastikan current R hanya dipercaya kalau candle futures symbol masih fresh."
      actions={<StatusBadge value={summary?.integrity_status || "UNAVAILABLE"} />}
    >
      <div className="grid gap-3 border-b border-line p-4 md:grid-cols-2 xl:grid-cols-6">
        <MetricCard label="Fresh open" value={summary?.fresh_open_count ?? 0} helper={`${summary?.fresh_symbol_count ?? 0} symbol`} tone={tone === "good" ? "good" : "neutral"} />
        <MetricCard label="Stale forward" value={summary?.stale_forward_count ?? 0} helper={`>${data?.stale_after_minutes ?? 30} menit gap`} tone={hasStale ? "bad" : "good"} />
        <MetricCard label="Waiting data" value={summary?.waiting_data_count ?? 0} helper={`${summary?.waiting_symbol_count ?? 0} symbol`} tone={hasWaiting ? "warn" : "neutral"} />
        <MetricCard label="Active/pending" value={summary?.active_or_pending_count ?? 0} helper="Open + waiting + stale" />
        <MetricCard label="Closed checked" value={summary?.closed_count ?? 0} helper={`TP ${summary?.tp_count ?? 0} / SL ${summary?.sl_count ?? 0}`} />
        <MetricCard label="Global latest" value={fmtTime(data?.global_latest_evaluation_candle_time || data?.latest_evaluation_candle_time)} helper="Futures candle acuan" tone="info" />
      </div>
      {hasStale && (
        <div className="border-b border-line bg-red-50 p-4 text-sm text-stale">
          Ada signal stale. Current R untuk row tersebut adalah nilai terakhir dari DB, bukan kondisi market fresh.
        </div>
      )}
      <div className="table-wrap">
        <table className="ops-table">
          <thead>
            <tr>
              <th>Signal WIB</th>
              <th>Symbol</th>
              <th>TF</th>
              <th>Stage</th>
              <th>Status</th>
              <th>Ideal R</th>
              <th>Realistic R</th>
              <th>Fill</th>
              <th>Latest symbol candle</th>
              <th>Gap</th>
              <th>Detail</th>
            </tr>
          </thead>
          <tbody>
            {data?.items.map((item) => (
              <ForwardIntegrityRow item={item} key={item.signal_id} />
            ))}
            {!data?.items.length && (
              <tr>
                <td colSpan={11}>
                  <EmptyState title="Tidak ada open/stale signal" detail="Semua signal yang terhitung sudah close, atau belum ada posisi paper aktif sesuai filter." />
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </SectionCard>
  );
}

function ForwardIntegrityRow({ item }: { item: SignalPerformanceItem }) {
  const rValue = item.result_status === "OPEN" || item.result_status === "STALE_FORWARD_DATA" ? item.unrealized_r : item.realized_r;
  const realisticRValue = item.result_status === "OPEN" || item.result_status === "STALE_FORWARD_DATA" ? item.realistic_unrealized_r : item.realistic_realized_r;
  return (
    <tr>
      <td>{item.signal_time_wib || fmtTime(item.signal_timestamp)}</td>
      <td className="font-semibold">{item.symbol}</td>
      <td>{item.timeframe}</td>
      <td>{labelFor(item.stage)}</td>
      <td><StatusBadge value={item.result_status} /></td>
      <td>{rValue == null ? "-" : `${fmtSigned(rValue)}R`}</td>
      <td>{realisticRValue == null ? "-" : `${fmtSigned(realisticRValue)}R`}</td>
      <td><StatusBadge value={item.realistic_fill_quality || "FILL_UNKNOWN"} /></td>
      <td>{item.latest_symbol_candle_time_wib || fmtTime(item.latest_symbol_candle_time)}</td>
      <td>{fmtGap(item.freshness_gap_minutes ?? item.stale_gap_minutes)}</td>
      <td>
        <Link
          className="rounded border border-line bg-white px-2 py-1 text-xs font-semibold hover:bg-field"
          href={`/signals/${encodeURIComponent(item.symbol)}?signal_id=${encodeURIComponent(item.signal_id)}`}
        >
          Open
        </Link>
      </td>
    </tr>
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
      <td>{row?.winrate_pct == null ? "-" : `${fmtNumber(row.winrate_pct)}%`}</td>
      <td>{fmtSigned(row?.total_r_closed)}R</td>
      <td>{fmtSigned(row?.realistic_total_r_closed)}R</td>
      <td>{fmtSigned(row?.realism_penalty_r_closed)}R</td>
      <td>{fmtSigned(row?.realistic_total_r_with_open)}R</td>
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

function fmtGap(value?: string | number | null): string {
  if (value === null || value === undefined || value === "") return "-";
  const num = Number(value);
  if (!Number.isFinite(num)) return String(value);
  if (Math.abs(num) < 1) return "<1m";
  return `${new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 }).format(num)}m`;
}

function shortStrategy(value?: string | null): string {
  if (!value) return "V2_LIVE";
  if (value.includes("V2") || value.includes("v2")) return "V2_LIVE";
  if (value.includes("V3") || value.includes("v3")) return "V3";
  return value.replace("SIGNAL_FACTORY_", "").replace("_LAYERED_SCORING_2026_07", "");
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
