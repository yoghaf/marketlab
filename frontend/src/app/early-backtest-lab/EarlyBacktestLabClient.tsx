"use client";

import { useMemo, useState } from "react";

import { EmptyState } from "@/components/EmptyState";
import { MetricCard } from "@/components/MetricCard";
import { SectionCard } from "@/components/SectionCard";
import { StatusBadge } from "@/components/StatusBadge";
import {
  EarlyBacktestEvent,
  EarlyBacktestEventsResponse,
  EarlyBacktestSummaryResponse,
  fmtTime
} from "@/lib/api";
import { labelFor } from "@/lib/labels";

type Props = {
  initialSummary: EarlyBacktestSummaryResponse | null;
  initialEventsByHorizon: Record<string, EarlyBacktestEventsResponse | null>;
  initialError: string | null;
};

const stages = ["EARLY_LONG", "EARLY_SHORT"];
const outcomes = ["TP_FIRST", "SL_FIRST", "NEITHER"];
const horizons = ["15m", "1h", "4h", "24h"];

export function EarlyBacktestLabClient({ initialSummary, initialEventsByHorizon, initialError }: Props) {
  const [horizon, setHorizon] = useState("4h");
  const [stage, setStage] = useState("");
  const [outcome, setOutcome] = useState("");
  const [limit, setLimit] = useState(200);

  const items = initialEventsByHorizon[horizon]?.items || [];
  const filteredItems = useMemo(() => {
    return items
      .filter((item) => !stage || item.stage === stage)
      .filter((item) => !outcome || item.outcome === outcome)
      .slice(0, limit);
  }, [items, limit, outcome, stage]);

  const summary = initialSummary;
  const selectedHorizon = summary?.summary.by_horizon[horizon];
  const earlyLong = summary?.summary.by_stage.EARLY_LONG || 0;
  const earlyShort = summary?.summary.by_stage.EARLY_SHORT || 0;

  return (
    <div className="space-y-5">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <h1 className="text-2xl font-bold tracking-normal text-ink">Early Backtest Lab</h1>
          <div className="mt-2 inline-flex rounded border border-blue-700 bg-blue-50 px-3 py-1 text-xs font-bold text-blue-700">
            READ-ONLY BACKTEST - bukan live signal
          </div>
          <p className="mt-2 max-w-4xl text-sm leading-6 text-slate-600">
            Lab historis untuk menguji identifikasi EARLY_LONG / EARLY_SHORT. Entry dan outcome memakai futures,
            spot hanya evidence/filter. Filter di halaman ini tidak reload full page.
          </p>
        </div>
        <div className="text-right text-xs text-slate-500">
          <div>Terakhir diperbarui: {fmtTime(summary?.metadata.generated_at_utc)}</div>
          <div>Source: {summary?.metadata.epoch || "-"}</div>
        </div>
      </header>

      {initialError ? (
        <div className="rounded border border-stale bg-red-50 p-4 text-sm text-stale">{initialError}</div>
      ) : (
        <>
          <section className="grid gap-3 md:grid-cols-2 xl:grid-cols-6">
            <MetricCard label="Early Events" value={summary?.summary.total_events || 0} helper={`${summary?.metadata.feature_rows || 0} feature rows`} tone="info" />
            <MetricCard label="EARLY_LONG" value={earlyLong} helper="Long awal historis" tone="info" />
            <MetricCard label="EARLY_SHORT" value={earlyShort} helper="Short awal historis" tone="warn" />
            <MetricCard label={`${horizon} Ready`} value={selectedHorizon?.ready || 0} helper={`Waiting ${selectedHorizon?.waiting || 0}`} />
            <MetricCard label="Planned RR" value={fmtRR(selectedHorizon?.planned_rr)} helper="Target dibanding risk" tone="info" />
            <MetricCard label={`${horizon} Total R`} value={fmtR(selectedHorizon?.total_r)} helper={`Fixed-risk 1%: ${fmtPct(selectedHorizon?.fixed_risk_return_pct_1pct)}`} tone={(selectedHorizon?.total_r || 0) > 0 ? "good" : "bad"} />
            <MetricCard label={`${horizon} Median Raw Move`} value={fmtPct(selectedHorizon?.median_return_pct)} helper={`Median R ${fmtR(selectedHorizon?.median_r)}`} tone={(selectedHorizon?.median_return_pct || 0) > 0 ? "good" : "warn"} />
            <MetricCard label="Candles" value={summary?.metadata.candles_15m || 0} helper="Futures 15m di artifact" />
          </section>

          <SectionCard title="Backtest horizon" description="Early V0 sekarang dievaluasi di 15m, 1h, 4h, dan 24h. Tiap horizon punya position lock sendiri, jadi hasil 24h tidak mengunci hasil 15m.">
            <div className="grid gap-3 p-4 text-sm md:grid-cols-4">
              <Guardrail label="Selected horizon" value={horizon} />
              <Guardrail label="Entry market" value={summary?.guardrails.entry_market || "futures"} />
              <Guardrail label="Spot usage" value={summary?.guardrails.spot_usage || "evidence/filter only"} />
              <Guardrail label="Execution" value={summary?.guardrails.not_execution_instruction ? "NO" : "UNKNOWN"} />
            </div>
          </SectionCard>

          <SectionCard title="Horizon result summary" description="Total R adalah hasil utama untuk backtest risk-based. Fixed-risk 1% berarti 1R = 1% account risk. Raw move sum hanya jumlah persen gerak harga futures dan bisa berbeda arah karena ATR/risk tiap token beda.">
            <div className="table-wrap">
              <table className="ops-table">
                <thead>
                  <tr>
                    <th>Horizon</th>
                    <th>Ready</th>
                    <th>TP</th>
                    <th>SL</th>
                    <th>Neither</th>
                    <th>RR Plan</th>
                    <th>Total R</th>
                    <th>Fixed-risk 1%</th>
                    <th>Raw Move Sum</th>
                    <th>Avg / Median Raw Move</th>
                    <th>Avg / Median R</th>
                    <th>Best/Worst</th>
                  </tr>
                </thead>
                <tbody>
                  {horizons.map((item) => {
                    const row = summary?.summary.by_horizon[item];
                    return (
                      <tr key={item} className={item === horizon ? "bg-blue-50/60" : ""}>
                        <td className="font-semibold">{item}</td>
                        <td>{row?.ready ?? 0}</td>
                        <td>{row?.tp ?? 0}</td>
                        <td>{row?.sl ?? 0}</td>
                        <td>{row?.neither ?? 0}</td>
                        <td>{fmtRR(row?.planned_rr)}</td>
                        <td className="font-semibold">{fmtR(row?.total_r)}</td>
                        <td>{fmtPct(row?.fixed_risk_return_pct_1pct)}</td>
                        <td>{fmtPct(row?.total_return_pct)}</td>
                        <td>{fmtPct(row?.avg_return_pct)} / {fmtPct(row?.median_return_pct)}</td>
                        <td>{fmtR(row?.avg_r)} / {fmtR(row?.median_r)}</td>
                        <td>{fmtR(row?.best_r)} / {fmtR(row?.worst_r)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </SectionCard>

          <SectionCard title="History entry + trigger evidence" description={`Satu baris adalah satu paper entry futures historis. Waktu invalid/result adalah waktu TP, SL, atau close horizon ${horizon} jika neither.`}>
            <div className="grid gap-3 p-4 md:grid-cols-4 xl:grid-cols-5">
              <label className="grid gap-1 text-sm">
                <span className="font-semibold text-slate-600">Horizon</span>
                <select className="rounded border border-line bg-white px-3 py-2" value={horizon} onChange={(event) => setHorizon(event.target.value)}>
                  {horizons.map((value) => <option key={value} value={value}>{value}</option>)}
                </select>
              </label>
              <label className="grid gap-1 text-sm">
                <span className="font-semibold text-slate-600">Stage</span>
                <select className="rounded border border-line bg-white px-3 py-2" value={stage} onChange={(event) => setStage(event.target.value)}>
                  <option value="">All early</option>
                  {stages.map((value) => <option key={value} value={value}>{value}</option>)}
                </select>
              </label>
              <label className="grid gap-1 text-sm">
                <span className="font-semibold text-slate-600">Outcome</span>
                <select className="rounded border border-line bg-white px-3 py-2" value={outcome} onChange={(event) => setOutcome(event.target.value)}>
                  <option value="">All outcome</option>
                  {outcomes.map((value) => <option key={value} value={value}>{value}</option>)}
                </select>
              </label>
              <label className="grid gap-1 text-sm">
                <span className="font-semibold text-slate-600">Limit</span>
                <input className="rounded border border-line px-3 py-2" min={1} max={1000} type="number" value={limit} onChange={(event) => setLimit(normalizeNumber(event.target.value, 200))} />
              </label>
              <div className="flex items-end text-sm text-slate-600">
                Showing {filteredItems.length} of {items.length} loaded rows
              </div>
            </div>
            <div className="table-wrap">
              <table className="ops-table">
                <thead>
                  <tr>
                    <th>Entry / Invalid WIB</th>
                    <th>Symbol</th>
                    <th>Setup</th>
                    <th>Entry Plan Futures</th>
                    <th>Outcome</th>
                    <th>Return / R</th>
                    <th>Trigger Evidence</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredItems.map((item) => <EventRow key={`${item.signal_id}-${item.horizon}`} item={item} />)}
                  {!filteredItems.length && (
                    <tr>
                      <td colSpan={7}>
                        <EmptyState title="Belum ada event cocok filter" detail="Ubah filter stage/outcome atau naikkan limit." />
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
      <td>
        <div className="font-semibold">{item.signal_time_wib || fmtTime(item.signal_time_utc)}</div>
        <div className="text-xs text-slate-500">invalid/result: {item.result_time_wib || fmtTime(item.result_time_utc)}</div>
      </td>
      <td className="font-semibold">{item.symbol}</td>
      <td>
        <div>{labelFor(item.stage)}</div>
        <div className="mt-1"><StatusBadge value={item.direction === "LONG" ? "BULLISH_CONTEXT" : "BEARISH_CONTEXT"} /></div>
      </td>
      <td>
        <div>Entry: <span className="font-semibold">{fmtPrice(item.entry)}</span></div>
        <div>SL: {fmtPrice(item.stop)}</div>
        <div>TP: {fmtPrice(item.target)}</div>
        <div>RR: <span className="font-semibold">{fmtRR(item.rr)}</span></div>
        <div className="text-xs text-slate-500">TP {fmtPct(item.target_return_pct)} / SL {fmtPct(item.stop_return_pct)}</div>
        <div className="text-xs text-slate-500">{item.entry_price_source || "futures_klines_15m.close"}</div>
      </td>
      <td><StatusBadge value={item.outcome} /></td>
      <td>
        <div className="font-semibold">{fmtPct(item.realized_return_pct)}</div>
        <div className="text-xs text-slate-500">R {fmtR(item.realized_r)}</div>
        <div className="text-xs text-slate-500">MFE {fmtR(item.mfe_r)} / MAE {fmtR(item.mae_r)}</div>
        <div className="text-xs text-slate-500">MFE {fmtPct(item.max_favorable_return_pct)} / MAE {fmtPct(item.max_adverse_return_pct)}</div>
      </td>
      <td><EvidenceSummary item={item} /></td>
    </tr>
  );
}

function EvidenceSummary({ item }: { item: EarlyBacktestEvent }) {
  const evidence = item.evidence || {};
  return (
    <div className="min-w-72 space-y-1 text-xs leading-5">
      <EvidenceLine label="Price 15m" value={fmtPct(numericEvidence(evidence.price_return_pct))} />
      <EvidenceLine label="Volume vs 20" value={fmtX(numericEvidence(evidence.volume_spike_ratio_20))} />
      <EvidenceLine label="Range vs 20" value={fmtX(numericEvidence(evidence.range_spike_ratio_20))} />
      <EvidenceLine label="OI vs 20" value={fmtX(numericEvidence(evidence.oi_spike_ratio_20))} />
      <EvidenceLine label="OI change" value={fmtPct(numericEvidence(evidence.oi_change_pct))} />
      <EvidenceLine label="Move / ATR 1h" value={fmtX(numericEvidence(evidence.price_move_atr_1h))} />
      <EvidenceLine label="Spot" value={String(evidence.spot_support_status || "-")} />
      <EvidenceLine label="1h return" value={fmtPct(numericEvidence(evidence.price_return_pct_1h))} />
      <EvidenceLine label="Rank" value={evidence.universe_rank ? `#${evidence.universe_rank}` : "-"} />
    </div>
  );
}

function EvidenceLine({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-3">
      <span className="text-slate-500">{label}</span>
      <span className="font-semibold text-ink">{value}</span>
    </div>
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

function fmtPct(value?: string | number | null): string {
  if (value === null || value === undefined || value === "") return "-";
  const num = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(num)) return String(value);
  return `${new Intl.NumberFormat("en-US", { maximumFractionDigits: 3 }).format(num)}%`;
}

function fmtX(value?: string | number | null): string {
  if (value === null || value === undefined || value === "") return "-";
  const num = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(num)) return String(value);
  return `${new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 }).format(num)}x`;
}

function fmtPrice(value?: string | number | null): string {
  if (value === null || value === undefined || value === "") return "-";
  const num = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(num)) return String(value);
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 8 }).format(num);
}

function fmtRR(value?: string | number | null): string {
  if (value === null || value === undefined || value === "") return "-";
  const num = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(num)) return String(value);
  return `1:${new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 }).format(num)}`;
}

function numericEvidence(value: string | number | boolean | null | undefined): string | number | null | undefined {
  return typeof value === "boolean" ? undefined : value;
}
