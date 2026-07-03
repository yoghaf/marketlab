import Link from "next/link";

import { EmptyState } from "@/components/EmptyState";
import { FilterBar, SelectFilter } from "@/components/FilterBar";
import { MetricCard } from "@/components/MetricCard";
import { PageHeader } from "@/components/PageHeader";
import { SectionCard } from "@/components/SectionCard";
import { StatusBadge } from "@/components/StatusBadge";
import {
  EarlyBacktestEvent,
  EarlyBacktestEventsResponse,
  EarlyBacktestSummaryResponse,
  fetchJson,
  fmtNumber,
  fmtTime
} from "@/lib/api";
import { labelFor } from "@/lib/labels";

type EarlyBacktestSearchParams = Promise<Record<string, string | string[] | undefined>>;

const stages = ["EARLY_LONG", "EARLY_SHORT"];
const horizons = ["15m", "1h", "4h", "24h"];
const outcomes = ["TP_FIRST", "SL_FIRST", "BOTH_HIT_SAME_CANDLE", "NEITHER_CLOSE_AT_HORIZON", "WAITING_DATA"];

export default async function EarlyBacktestLabPage({ searchParams }: { searchParams: EarlyBacktestSearchParams }) {
  const params = await searchParams;
  const filters = {
    stage: firstParam(params.stage),
    horizon: firstParam(params.horizon) || "1h",
    outcome: firstParam(params.outcome),
    limit: normalizeNumber(firstParam(params.limit), 200)
  };
  const query = new URLSearchParams({ horizon: filters.horizon, limit: String(filters.limit) });
  if (filters.stage) query.set("stage", filters.stage);
  if (filters.outcome) query.set("outcome", filters.outcome);

  let summary: EarlyBacktestSummaryResponse | null = null;
  let events: EarlyBacktestEventsResponse | null = null;
  let error: string | null = null;
  try {
    [summary, events] = await Promise.all([
      fetchJson<EarlyBacktestSummaryResponse>("/api/backtests/early-lab/summary", { revalidateSeconds: 30 }),
      fetchJson<EarlyBacktestEventsResponse>(`/api/backtests/early-lab/events?${query.toString()}`, { revalidateSeconds: 30 })
    ]);
  } catch (err) {
    error = err instanceof Error ? err.message : "Early Backtest Lab artifact belum tersedia";
  }

  const selectedHorizon = summary?.summary.by_horizon[filters.horizon];
  const earlyLong = summary?.summary.by_stage.EARLY_LONG || 0;
  const earlyShort = summary?.summary.by_stage.EARLY_SHORT || 0;

  return (
    <div className="space-y-5">
      <PageHeader
        title="Early Backtest Lab"
        badge="READ-ONLY BACKTEST - bukan live signal"
        subtitle="Lab historis untuk menguji identifikasi EARLY_LONG / EARLY_SHORT memakai entry futures, ATR 1h, position lock per symbol, dan data candle yang sudah ada di DB."
        updatedAt={fmtTime(summary?.metadata.generated_at_utc)}
      />

      <div className="flex flex-wrap gap-2 text-sm">
        <Link className="rounded border border-line bg-white px-3 py-2 font-semibold hover:bg-field" href="/early-backtest-lab">Early Lab</Link>
        <Link className="rounded border border-line bg-white px-3 py-2 font-semibold hover:bg-field" href="/scanner?tier=SIGNAL_CANDIDATE&limit=75">Live Signal Candidate</Link>
        <Link className="rounded border border-line bg-white px-3 py-2 font-semibold hover:bg-field" href="/strategy-arena?setup=EARLY_LONG&min_sample=0&hide_rejected=false">Strategy Arena Early</Link>
      </div>

      {error ? (
        <div className="rounded border border-stale bg-red-50 p-4 text-sm text-stale">{error}</div>
      ) : (
        <>
          <section className="grid gap-3 md:grid-cols-2 xl:grid-cols-6">
            <MetricCard label="Early Events" value={summary?.summary.total_events || 0} helper={`Source ${summary?.metadata.epoch || "-"}`} tone="info" />
            <MetricCard label="EARLY_LONG" value={earlyLong} helper="Candidate long awal" tone="info" />
            <MetricCard label="EARLY_SHORT" value={earlyShort} helper="Candidate short awal" tone="warn" />
            <MetricCard label={`${filters.horizon} Ready`} value={selectedHorizon?.ready || 0} helper={`Waiting ${selectedHorizon?.waiting || 0}`} />
            <MetricCard label={`${filters.horizon} Median R`} value={fmtR(selectedHorizon?.median_r)} helper={`Avg ${fmtR(selectedHorizon?.avg_r)}`} tone={(selectedHorizon?.median_r || 0) > 0 ? "good" : "warn"} />
            <MetricCard label="Best Horizon" value={summary?.summary.best_horizon || "-"} helper="Berdasar median R ready" />
          </section>

          <SectionCard title="Read-only guardrail" description="Halaman ini hanya membaca hasil backtest artifact. Tidak menjalankan order, tidak membuat live signal, dan tidak mengubah rule.">
            <div className="grid gap-3 p-4 text-sm md:grid-cols-4">
              <Guardrail label="Entry market" value={summary?.guardrails.entry_market || "futures"} />
              <Guardrail label="Spot usage" value={summary?.guardrails.spot_usage || "evidence/filter only"} />
              <Guardrail label="Live signal" value={summary?.guardrails.not_live_signal ? "NO" : "UNKNOWN"} />
              <Guardrail label="Execution" value={summary?.guardrails.not_execution_instruction ? "NO" : "UNKNOWN"} />
            </div>
          </SectionCard>

          <SectionCard title="Horizon summary" description="Perbandingan hasil RR per horizon untuk EARLY_LONG dan EARLY_SHORT saja.">
            <div className="table-wrap">
              <table className="ops-table">
                <thead>
                  <tr>
                    <th>Horizon</th>
                    <th>Ready</th>
                    <th>Waiting</th>
                    <th>TP</th>
                    <th>SL</th>
                    <th>Neither</th>
                    <th>Avg R</th>
                    <th>Median R</th>
                    <th>Best/Worst</th>
                  </tr>
                </thead>
                <tbody>
                  {horizons.map((horizon) => {
                    const row = summary?.summary.by_horizon[horizon];
                    return (
                      <tr key={horizon}>
                        <td className="font-semibold">{horizon}</td>
                        <td>{row?.ready ?? 0}</td>
                        <td>{row?.waiting ?? 0}</td>
                        <td>{row?.tp ?? 0}</td>
                        <td>{row?.sl ?? 0}</td>
                        <td>{row?.neither ?? 0}</td>
                        <td>{fmtR(row?.avg_r)}</td>
                        <td>{fmtR(row?.median_r)}</td>
                        <td>{fmtR(row?.best_r)} / {fmtR(row?.worst_r)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </SectionCard>

          <SectionCard title="Event list" description="Daftar entry futures hasil replay historis. Filter default 1h karena early V0 diuji dengan horizon 4 candle 15m.">
            <div className="space-y-4 p-4">
              <FilterBar>
                <SelectFilter label="Stage" name="stage" value={filters.stage || ""} options={stages} emptyLabel="All early" />
                <SelectFilter label="Horizon" name="horizon" value={filters.horizon} options={horizons} emptyLabel="1h" />
                <SelectFilter label="Outcome" name="outcome" value={filters.outcome || ""} options={outcomes} emptyLabel="All outcome" />
                <label className="grid gap-1 text-sm">
                  <span className="font-semibold text-slate-600">Limit</span>
                  <input className="rounded border border-line px-3 py-2" min={1} max={1000} name="limit" type="number" defaultValue={filters.limit} />
                </label>
              </FilterBar>
            </div>
            <div className="table-wrap">
              <table className="ops-table">
                <thead>
                  <tr>
                    <th>Waktu WIB</th>
                    <th>Symbol</th>
                    <th>Stage</th>
                    <th>Direction</th>
                    <th>Confidence</th>
                    <th>Entry Futures</th>
                    <th>SL</th>
                    <th>TP</th>
                    <th>Outcome</th>
                    <th>R</th>
                    <th>MFE/MAE</th>
                    <th>Result WIB</th>
                  </tr>
                </thead>
                <tbody>
                  {events?.items.map((item) => <EventRow key={`${item.signal_id}-${item.horizon}`} item={item} />)}
                  {!events?.items.length && (
                    <tr>
                      <td colSpan={12}>
                        <EmptyState title="Belum ada event cocok filter" detail="Ubah filter atau jalankan ulang Signal Factory V2 backtest setelah data bertambah." />
                      </td>
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

function EventRow({ item }: { item: EarlyBacktestEvent }) {
  return (
    <tr>
      <td>{item.signal_time_wib || fmtTime(item.signal_time_utc)}</td>
      <td className="font-semibold">{item.symbol}</td>
      <td>{labelFor(item.stage)}</td>
      <td><StatusBadge value={item.direction === "LONG" ? "BULLISH_CONTEXT" : "BEARISH_CONTEXT"} /></td>
      <td>{labelFor(item.confidence_tier)}</td>
      <td>
        {fmtNumber(item.entry)}
        <div className="text-xs text-slate-500">{item.entry_market || "futures"}</div>
      </td>
      <td>{fmtNumber(item.stop)}</td>
      <td>{fmtNumber(item.target)}</td>
      <td><StatusBadge value={item.outcome} /></td>
      <td className="font-semibold">{fmtR(item.realized_r)}</td>
      <td>{fmtR(item.mfe_r)} / {fmtR(item.mae_r)}</td>
      <td>{item.result_time_wib || fmtTime(item.result_time_utc)}</td>
    </tr>
  );
}

function Guardrail({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded border border-line bg-field/40 p-3">
      <div className="text-xs font-semibold uppercase text-slate-500">{label}</div>
      <div className="mt-1 font-bold text-ink">{value}</div>
    </div>
  );
}

function firstParam(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

function normalizeNumber(value: string | undefined, fallback: number): number {
  const parsed = Number(value || fallback);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.min(Math.max(Math.trunc(parsed), 1), 1000);
}

function fmtR(value?: string | number | null): string {
  if (value === null || value === undefined || value === "") return "-";
  const num = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(num)) return String(value);
  return `${new Intl.NumberFormat("en-US", { maximumFractionDigits: 3 }).format(num)}R`;
}
