import Link from "next/link";

import { EmptyState } from "@/components/EmptyState";
import { FilterBar, SelectFilter } from "@/components/FilterBar";
import { MetricCard } from "@/components/MetricCard";
import { PageHeader } from "@/components/PageHeader";
import { SectionCard } from "@/components/SectionCard";
import { StatusBadge } from "@/components/StatusBadge";
import {
  SignalPerformanceItem,
  SignalQualityBucket,
  SignalQualityEvidenceField,
  SignalQualityLabResponse,
  fetchJson,
  fmtNumber,
  fmtTime
} from "@/lib/api";
import { labelFor } from "@/lib/labels";

type QualitySearchParams = Promise<Record<string, string | string[] | undefined>>;

const stages = ["EARLY_LONG", "EARLY_SHORT", "MID_LONG", "MID_SHORT"];
const timeframes = ["15m", "1h", "4h", "24h"];

export const dynamic = "force-dynamic";

export default async function SignalQualityLabPage({ searchParams }: { searchParams: QualitySearchParams }) {
  const params = await searchParams;
  const stage = firstParam(params.stage);
  const timeframe = firstParam(params.timeframe);
  const includeWatchOnly = firstParam(params.include_watch_only) === "true";
  const positionLock = firstParam(params.position_lock) !== "false";
  const minSample = normalizeNumber(firstParam(params.min_sample), 5, 1, 100);
  const limit = normalizeNumber(firstParam(params.limit), 25, 5, 100);
  const query = new URLSearchParams({
    include_watch_only: String(includeWatchOnly),
    position_lock: String(positionLock),
    min_sample: String(minSample),
    limit: String(limit)
  });
  if (stage) query.set("stage", stage);
  if (timeframe) query.set("timeframe", timeframe);

  let data: SignalQualityLabResponse | null = null;
  let error: string | null = null;
  try {
    data = await fetchJson<SignalQualityLabResponse>(`/api/signal-candidates/quality-lab?${query.toString()}`, { revalidateSeconds: 20 });
  } catch (err) {
    error = err instanceof Error ? err.message : "Signal Quality Lab API failed";
  }

  const aggregate = data?.aggregate;
  const bestStage = data?.by_stage?.[0];
  const weakestStage = [...(data?.by_stage || [])].sort((a, b) => Number(a.total_r_closed) - Number(b.total_r_closed))[0];

  return (
    <div className="space-y-5">
      <PageHeader
        title="Signal Quality Lab"
        badge="READ-ONLY ANALYSIS"
        subtitle="Analisis kenapa Signal Candidate menang/kalah: TP vs SL berdasarkan angka evidence aktual, stage, confidence, symbol, drawdown R, dan best/worst signal. Ini tidak mengubah rule dan bukan execution."
        updatedAt={fmtTime(data?.generated_at_utc)}
      />

      <div className="flex flex-wrap gap-2 text-sm">
        <Link className="rounded border border-line bg-white px-3 py-2 font-semibold hover:bg-field" href="/scanner">Radar</Link>
        <Link className="rounded border border-line bg-white px-3 py-2 font-semibold hover:bg-field" href="/signal-performance">Signal History</Link>
        <Link className="rounded border border-line bg-white px-3 py-2 font-semibold hover:bg-field" href="/signal-factory">Signal Factory Raw</Link>
      </div>

      {error ? (
        <div className="rounded border border-stale bg-red-50 p-4 text-sm text-stale">{error}</div>
      ) : (
        <>
          <section className="grid gap-3 md:grid-cols-2 xl:grid-cols-6">
            <MetricCard label="Evaluated" value={aggregate?.signals_evaluated ?? 0} helper={`${aggregate?.signals_skipped ?? 0} skipped by lock`} />
            <MetricCard label="Total R" value={`${fmtSigned(aggregate?.total_r_closed)}R`} helper="Closed TP/SL/BOTH" tone={Number(aggregate?.total_r_closed || 0) >= 0 ? "good" : "bad"} />
            <MetricCard label="Max Drawdown" value={`${fmtSigned(data?.drawdown.max_drawdown_r)}R`} helper="Dari urutan result closed" tone="warn" />
            <MetricCard label="Current DD" value={`${fmtSigned(data?.drawdown.current_drawdown_r)}R`} helper={`Peak ${fmtSigned(data?.drawdown.peak_r)}R`} />
            <MetricCard label="TP / SL" value={`${aggregate?.tp_count ?? 0} / ${aggregate?.sl_count ?? 0}`} helper={`${aggregate?.closed_count ?? 0} closed`} />
            <MetricCard label="Open" value={aggregate?.open_count ?? 0} helper={`${fmtSigned(aggregate?.open_unrealized_r)}R unrealized`} tone="warn" />
          </section>

          <SectionCard title="Quality controls" description="Filter ini hanya mengubah tampilan analisis. Tidak mengubah rule Signal Factory.">
            <FilterBar>
              <SelectFilter label="Stage" name="stage" value={stage || ""} options={stages} emptyLabel="All stage" />
              <SelectFilter label="Timeframe" name="timeframe" value={timeframe || ""} options={timeframes} emptyLabel="All timeframe" />
              <label className="grid gap-1 text-sm">
                <span className="font-semibold text-slate-600">Min sample</span>
                <input className="rounded border border-line px-3 py-2" min={1} max={100} name="min_sample" type="number" defaultValue={minSample} />
              </label>
              <label className="grid gap-1 text-sm">
                <span className="font-semibold text-slate-600">Rows</span>
                <input className="rounded border border-line px-3 py-2" min={5} max={100} name="limit" type="number" defaultValue={limit} />
              </label>
              <SelectFilter label="Position lock" name="position_lock" value={String(positionLock)} options={["true", "false"]} emptyLabel="Default true" />
              <label className="flex items-end gap-2 pb-2 text-sm font-semibold text-slate-600">
                <input name="include_watch_only" type="checkbox" value="true" defaultChecked={includeWatchOnly} />
                Include WATCH_ONLY
              </label>
            </FilterBar>
          </SectionCard>

          <section className="grid gap-4 xl:grid-cols-2">
            <SectionCard title="Fast read" description="Kesimpulan cepat dari data yang sedang difilter.">
              <div className="grid gap-3 p-4 text-sm md:grid-cols-2">
                <Insight label="Stage terbaik" value={bestStage ? `${labelFor(bestStage.bucket)} (${fmtSigned(bestStage.total_r_closed)}R)` : "-"} />
                <Insight label="Stage terlemah" value={weakestStage ? `${labelFor(weakestStage.bucket)} (${fmtSigned(weakestStage.total_r_closed)}R)` : "-"} />
                <Insight label="Confidence terbaik" value={data?.by_confidence?.[0] ? `${labelFor(data.by_confidence[0].bucket)} (${fmtSigned(data.by_confidence[0].total_r_closed)}R)` : "-"} />
                <Insight label="Symbol paling profit" value={data?.top_symbols?.[0] ? `${data.top_symbols[0].bucket} (${fmtSigned(data.top_symbols[0].total_r_closed)}R)` : "-"} />
              </div>
            </SectionCard>

            <SectionCard title="Drawdown R" description="Bukan PnL. Ini akumulasi R dari closed paper result untuk melihat risk streak.">
              <div className="grid gap-3 p-4 text-sm md:grid-cols-3">
                <Insight label="Closed count" value={String(data?.drawdown.closed_count ?? 0)} />
                <Insight label="Peak R" value={`${fmtSigned(data?.drawdown.peak_r)}R`} />
                <Insight label="Max DD" value={`${fmtSigned(data?.drawdown.max_drawdown_r)}R`} />
              </div>
              <div className="table-wrap border-t border-line">
                <table className="ops-table">
                  <thead>
                    <tr>
                      <th>Time WIB</th>
                      <th>Symbol</th>
                      <th>Stage</th>
                      <th>Result</th>
                      <th>R</th>
                      <th>Cumulative</th>
                      <th>Drawdown</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(data?.drawdown.points || []).slice(-12).reverse().map((point) => (
                      <tr key={`${point.signal_id}-${point.cumulative_r}`}>
                        <td>{point.result_time_wib || fmtTime(point.result_time_utc)}</td>
                        <td className="font-semibold">{point.symbol}</td>
                        <td>{labelFor(point.stage)}</td>
                        <td><StatusBadge value={point.result_status} /></td>
                        <td>{fmtSigned(point.realized_r)}R</td>
                        <td>{fmtSigned(point.cumulative_r)}R</td>
                        <td>{fmtSigned(point.drawdown_r)}R</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </SectionCard>
          </section>

          <SectionCard title="Evidence TP vs SL" description="Median dan kuartil angka evidence aktual dari signal yang TP dibanding yang SL. Pakai filter di atas untuk bedah stage/timeframe tertentu.">
            <EvidenceTable rows={data?.evidence_fields || []} />
          </SectionCard>

          <SectionCard title="Quality by stage" description="Ini yang paling penting untuk memperbaiki definisi EARLY/MID berikutnya.">
            <BucketTable rows={data?.by_stage || []} />
          </SectionCard>

          <section className="grid gap-4 xl:grid-cols-2">
            <SectionCard title="Quality by confidence">
              <BucketTable rows={data?.by_confidence || []} compact />
            </SectionCard>
            <SectionCard title="Quality by timeframe">
              <BucketTable rows={data?.by_timeframe || []} compact />
            </SectionCard>
          </section>

          <section className="grid gap-4 xl:grid-cols-2">
            <SectionCard title="Top symbols" description="Symbol yang paling membantu total R.">
              <BucketTable rows={data?.top_symbols || []} compact />
            </SectionCard>
            <SectionCard title="Weak / noisy symbols" description="Symbol yang paling merusak total R sesuai filter.">
              <BucketTable rows={data?.weak_symbols || []} compact />
            </SectionCard>
          </section>

          <section className="grid gap-4 xl:grid-cols-2">
            <SectionCard title="Best closed signals">
              <SignalTable rows={data?.best_signals || []} />
            </SectionCard>
            <SectionCard title="Worst closed signals">
              <SignalTable rows={data?.worst_signals || []} />
            </SectionCard>
          </section>

          <SectionCard title="Open signals" description="Masih berjalan, belum dihitung sebagai closed R.">
            <SignalTable rows={data?.open_signals || []} />
          </SectionCard>
        </>
      )}
    </div>
  );
}

function EvidenceTable({ rows }: { rows: SignalQualityEvidenceField[] }) {
  return (
    <div className="table-wrap">
      <table className="ops-table">
        <thead>
          <tr>
            <th>Evidence field</th>
            <th>Flag</th>
            <th>Available</th>
            <th>TP / SL</th>
            <th>TP median</th>
            <th>SL median</th>
            <th>Delta</th>
            <th>TP q1/q3</th>
            <th>SL q1/q3</th>
            <th>Open median</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.field}>
              <td>
                <div className="font-semibold">{row.label}</div>
                <div className="text-xs text-slate-500">{row.field}</div>
              </td>
              <td><StatusBadge value={row.quality_flag} /></td>
              <td>{row.available_count} / miss {row.missing_count} ({fmtNumber(row.available_pct)}%)</td>
              <td>{row.tp_count} / {row.sl_count}</td>
              <td>{fmtNumber(row.tp_median)}</td>
              <td>{fmtNumber(row.sl_median)}</td>
              <td>{fmtSigned(row.delta_tp_minus_sl)}</td>
              <td>{fmtNumber(row.tp_q1)} / {fmtNumber(row.tp_q3)}</td>
              <td>{fmtNumber(row.sl_q1)} / {fmtNumber(row.sl_q3)}</td>
              <td>{fmtNumber(row.open_median)}</td>
            </tr>
          ))}
          {!rows.length && (
            <tr>
              <td colSpan={10}>
                <EmptyState title="No evidence rows" detail="Belum ada signal/evidence sesuai filter ini." />
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

function BucketTable({ rows, compact = false }: { rows: SignalQualityBucket[]; compact?: boolean }) {
  return (
    <div className="table-wrap">
      <table className="ops-table">
        <thead>
          <tr>
            <th>Bucket</th>
            <th>Flag</th>
            <th>Sample</th>
            <th>TP / SL / Open</th>
            <th>Winrate</th>
            <th>Total R</th>
            <th>Median R</th>
            {!compact && <th>MFE / MAE</th>}
            <th>Top Symbol</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.bucket}>
              <td className="font-semibold">{labelFor(row.bucket)}</td>
              <td><StatusBadge value={row.quality_flag} /></td>
              <td>{row.signals_evaluated}</td>
              <td>{row.tp_count} / {row.sl_count} / {row.open_count}</td>
              <td>{row.winrate_pct == null ? "-" : `${fmtNumber(row.winrate_pct)}%`}</td>
              <td>{fmtSigned(row.total_r_closed)}R</td>
              <td>{fmtSigned(row.median_r_closed)}R</td>
              {!compact && <td>{fmtSigned(row.median_mfe_r)} / {fmtSigned(row.median_mae_r)}</td>}
              <td>{row.top_symbol} ({fmtNumber(row.top_symbol_share_pct)}%)</td>
            </tr>
          ))}
          {!rows.length && (
            <tr>
              <td colSpan={compact ? 8 : 9}>
                <EmptyState title="No quality rows" detail="Belum ada signal sesuai filter ini." />
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

function SignalTable({ rows }: { rows: SignalPerformanceItem[] }) {
  return (
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
            <th>R</th>
            <th>MFE / MAE</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.signal_id}>
              <td>{row.signal_time_wib || fmtTime(row.signal_timestamp)}</td>
              <td className="font-semibold">{row.symbol}</td>
              <td>{row.timeframe}</td>
              <td>{labelFor(row.stage)}</td>
              <td><StatusBadge value={row.direction} /></td>
              <td><StatusBadge value={row.result_status} /></td>
              <td>{row.realized_r != null ? `${fmtSigned(row.realized_r)}R` : row.unrealized_r != null ? `${fmtSigned(row.unrealized_r)}R open` : "-"}</td>
              <td>{fmtSigned(row.mfe_r)} / {fmtSigned(row.mae_r)}</td>
            </tr>
          ))}
          {!rows.length && (
            <tr>
              <td colSpan={8}><EmptyState title="No signals" detail="Belum ada signal dalam kategori ini." /></td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

function Insight({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded border border-line bg-field/50 p-3">
      <div className="text-xs font-semibold uppercase text-slate-500">{label}</div>
      <div className="mt-1 font-bold text-ink">{value}</div>
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
