import Link from "next/link";

import { EmptyState } from "@/components/EmptyState";
import { MetricCard } from "@/components/MetricCard";
import { PageHeader } from "@/components/PageHeader";
import { SectionCard } from "@/components/SectionCard";
import { StatusBadge } from "@/components/StatusBadge";
import {
  MisidentificationAuditResponse,
  MisidentificationBucketRow,
  MisidentificationEvidenceRow,
  MisidentificationLane,
  SignalPerformanceItem,
  fetchJson,
  fmtNumber,
  fmtPrice,
  fmtTime
} from "@/lib/api";
import { labelFor } from "@/lib/labels";

type SearchParams = Promise<Record<string, string | string[] | undefined>>;

export const dynamic = "force-dynamic";

const defaultStages = "MID_LONG,MID_SHORT";

export default async function SignalMisidentificationAuditPage({ searchParams }: { searchParams: SearchParams }) {
  const params = await searchParams;
  const includeWatchOnly = firstParam(params.include_watch_only) === "true";
  const positionLock = firstParam(params.position_lock) === "true";
  const timeframe = firstParam(params.timeframe) || "1h";
  const stages = firstParam(params.stages) || defaultStages;
  const minSample = normalizeNumber(firstParam(params.min_sample), 20, 1, 100);
  const limit = normalizeNumber(firstParam(params.limit), 50, 10, 100);
  const maxSignalsPerStage = normalizeNumber(firstParam(params.max_signals_per_stage), 500, 50, 2000);
  const query = new URLSearchParams({
    include_watch_only: String(includeWatchOnly),
    position_lock: String(positionLock),
    timeframe,
    stages,
    min_sample: String(minSample),
    limit: String(limit),
    max_signals_per_stage: String(maxSignalsPerStage)
  });

  let data: MisidentificationAuditResponse | null = null;
  let error: string | null = null;
  try {
    data = await fetchJson<MisidentificationAuditResponse>(`/api/signal-candidates/misidentification-audit?${query.toString()}`, {
      revalidateSeconds: 120
    });
  } catch (err) {
    error = err instanceof Error ? err.message : "Signal Misidentification Audit API failed";
  }

  const lanes = data?.lanes || [];
  const worstLane = lanes.find((lane) => lane.lane === data?.summary.worst_lane) || lanes[0] || null;

  return (
    <div className="space-y-5">
      <PageHeader
        title="Signal Misidentification Audit"
        badge="READ-ONLY DIAGNOSTIC"
        subtitle="Audit ini menjawab apakah SL banyak karena salah arah, entry telat/overextended, stop/timeout, cost/fill, atau apakah reverse hanya layak diteliti. Tidak mengubah Signal Factory, scanner, TP/SL, atau execution."
        updatedAt={fmtTime(data?.generated_at_utc)}
      />

      <div className="flex flex-wrap gap-2 text-sm">
        <Link className="rounded-md border border-line bg-white px-3 py-2 font-semibold hover:bg-field" href="/signal-quality-lab">
          Open Quality Lab
        </Link>
        <Link className="rounded-md border border-line bg-white px-3 py-2 font-semibold hover:bg-field" href="/mid-long-research-study">
          Open MID_LONG Research
        </Link>
        <Link className="rounded-md border border-line bg-white px-3 py-2 font-semibold hover:bg-field" href="/signal-performance?timeframe=1h&position_lock=false">
          Open Signal History 1h
        </Link>
      </div>

      {error ? (
        <div className="rounded border border-stale bg-red-50 p-4 text-sm text-stale">{error}</div>
      ) : (
        <>
          <section className="grid gap-3 md:grid-cols-2 xl:grid-cols-6">
            <MetricCard label="Lanes" value={data?.summary.lane_count ?? 0} helper={data?.filters.stages.join(", ") || "-"} />
            <MetricCard label="Reverse worth test" value={data?.summary.reverse_worth_testing_count ?? 0} helper="Bukan rule, hanya hipotesis" tone="warn" />
            <MetricCard label="Direction weak" value={data?.summary.direction_weak_count ?? 0} helper="Arah 1h sering salah" tone="bad" />
            <MetricCard label="Entry/risk weak" value={data?.summary.entry_or_risk_weak_count ?? 0} helper="SL tinggi, arah tidak selalu salah" tone="warn" />
            <MetricCard label="Best lane" value={labelFor(data?.summary.best_lane || "-")} helper="Realistic R tertinggi" tone="good" />
            <MetricCard label="Worst lane" value={labelFor(data?.summary.worst_lane || "-")} helper="Fokus bedah utama" tone="bad" />
          </section>

          <SectionCard title="Audit controls" description="Filter ini hanya mengubah pembacaan audit. Tidak mengubah rule live.">
            <form className="grid gap-3 p-4 md:grid-cols-2 xl:grid-cols-6">
              <label className="grid gap-1 text-sm">
                <span className="font-semibold text-slate-600">Timeframe</span>
                <select className="rounded border border-line px-3 py-2" name="timeframe" defaultValue={timeframe}>
                  {["15m", "1h", "4h", "24h"].map((value) => (
                    <option key={value} value={value}>{value}</option>
                  ))}
                </select>
              </label>
              <label className="grid gap-1 text-sm xl:col-span-2">
                <span className="font-semibold text-slate-600">Stages</span>
                <input className="rounded border border-line px-3 py-2" name="stages" defaultValue={stages} />
              </label>
              <label className="grid gap-1 text-sm">
                <span className="font-semibold text-slate-600">Min sample</span>
                <input className="rounded border border-line px-3 py-2" min={1} max={100} name="min_sample" type="number" defaultValue={minSample} />
              </label>
              <label className="grid gap-1 text-sm">
                <span className="font-semibold text-slate-600">Rows</span>
                <input className="rounded border border-line px-3 py-2" min={10} max={100} name="limit" type="number" defaultValue={limit} />
              </label>
              <label className="grid gap-1 text-sm">
                <span className="font-semibold text-slate-600">Max signals/stage</span>
                <input className="rounded border border-line px-3 py-2" min={50} max={2000} name="max_signals_per_stage" type="number" defaultValue={maxSignalsPerStage} />
              </label>
              <label className="grid gap-1 text-sm">
                <span className="font-semibold text-slate-600">Position lock</span>
                <select className="rounded border border-line px-3 py-2" name="position_lock" defaultValue={String(positionLock)}>
                  <option value="false">false</option>
                  <option value="true">true</option>
                </select>
              </label>
              <label className="flex items-end gap-2 pb-2 text-sm font-semibold text-slate-600">
                <input name="include_watch_only" type="checkbox" value="true" defaultChecked={includeWatchOnly} />
                Include WATCH_ONLY
              </label>
              <div className="flex items-end">
                <button className="rounded-md border border-line bg-white px-4 py-2 text-sm font-semibold hover:bg-field" type="submit">
                  Apply
                </button>
              </div>
            </form>
          </SectionCard>

          <SectionCard title="Fast read" description="Jawaban ringkas dari audit arah vs risk model.">
            <div className="grid gap-3 p-4 md:grid-cols-2 xl:grid-cols-4">
              <Info label="Lane terburuk" value={worstLane ? `${labelFor(worstLane.stage)} ${worstLane.timeframe}` : "-"} />
              <Info label="Verdict terburuk" value={labelFor(worstLane?.summary.verdict)} />
              <Info label="Wrong 1h share" value={worstLane?.summary.wrong_direction_1h_share_pct == null ? "-" : `${fmtNumber(worstLane.summary.wrong_direction_1h_share_pct)}%`} />
              <Info label="Reverse clean share" value={worstLane?.summary.reverse_clean_share_pct == null ? "-" : `${fmtNumber(worstLane.summary.reverse_clean_share_pct)}%`} />
            </div>
            <div className="border-t border-line p-4 text-sm leading-6 text-slate-700">
              {worstLane?.summary.read || "Belum ada data audit."}
            </div>
          </SectionCard>

          {lanes.length ? (
            lanes.map((lane) => <LanePanel key={lane.lane} lane={lane} />)
          ) : (
            <SectionCard title="No lanes" description="Tidak ada lane untuk filter ini.">
              <EmptyState title="No data" detail="Coba longgarkan stage/timeframe atau include WATCH_ONLY." />
            </SectionCard>
          )}

          <SectionCard title="Guardrails" description="Batas interpretasi audit ini.">
            <ul className="grid gap-2 p-4 text-sm text-slate-700 md:grid-cols-2">
              {(data?.guardrails || []).map((item) => (
                <li key={item} className="rounded border border-line bg-field/40 p-3">{item}</li>
              ))}
            </ul>
          </SectionCard>
        </>
      )}
    </div>
  );
}

function LanePanel({ lane }: { lane: MisidentificationLane }) {
  return (
    <SectionCard
      title={`${labelFor(lane.stage)} ${lane.timeframe}`}
      description="Ringkasan apakah lane ini rugi karena salah arah, reverse hypothesis, atau model entry/risk."
    >
      <div className="grid gap-3 p-4 md:grid-cols-2 xl:grid-cols-6">
        <MetricCard label="Sample / closed" value={`${lane.summary.sample_count} / ${lane.summary.closed_count}`} helper={`${lane.summary.tp_count} TP, ${lane.summary.sl_count} SL`} />
        <MetricCard label="Realistic R" value={`${fmtSigned(lane.baseline.realistic_total_r_closed)}R`} helper={`Avg ${fmtSigned(lane.baseline.realistic_avg_r_closed)}R`} tone={Number(lane.baseline.realistic_total_r_closed || 0) >= 0 ? "good" : "bad"} />
        <MetricCard label="SL share" value={lane.summary.sl_share_pct == null ? "-" : `${fmtNumber(lane.summary.sl_share_pct)}%`} helper="SL / closed" tone="warn" />
        <MetricCard label="Wrong 1h" value={lane.summary.wrong_direction_1h_count} helper={lane.summary.wrong_direction_1h_share_pct == null ? "-" : `${fmtNumber(lane.summary.wrong_direction_1h_share_pct)}% closed`} tone="bad" />
        <MetricCard label="Reverse clean" value={lane.summary.reverse_clean_count} helper={lane.summary.reverse_clean_share_pct == null ? "-" : `${fmtNumber(lane.summary.reverse_clean_share_pct)}% closed`} tone="warn" />
        <MetricCard label="Verdict" value={labelFor(lane.summary.verdict)} helper={lane.summary.read} />
      </div>

      <div className="grid gap-4 border-t border-line p-4 xl:grid-cols-2">
        <MiniTable title="Loss reason buckets" rows={lane.reason_rows} />
        <MiniTable title="Reverse proxy buckets" rows={lane.reverse_rows} />
      </div>

      <div className="grid gap-4 border-t border-line p-4 xl:grid-cols-2">
        <MiniTable title="Path anatomy" rows={lane.path_rows} />
        <EvidenceTable rows={lane.evidence_correct_vs_wrong} />
      </div>

      <div className="grid gap-4 border-t border-line p-4 xl:grid-cols-3">
        <SignalTable title="Latest SL" items={lane.latest_sl_signals} />
        <SignalTable title="Latest TP" items={lane.latest_tp_signals} />
        <SignalTable title="Reverse-clean examples" items={lane.reverse_clean_examples} />
      </div>
    </SectionCard>
  );
}

function MiniTable({ title, rows }: { title: string; rows: MisidentificationBucketRow[] }) {
  return (
    <div className="overflow-hidden rounded-lg border border-line">
      <div className="border-b border-line bg-field/50 px-3 py-2 text-sm font-bold">{title}</div>
      <div className="table-wrap">
        <table className="ops-table">
          <thead>
            <tr>
              <th>Bucket</th>
              <th>Read</th>
              <th>Sample</th>
              <th>TP/SL/Open</th>
              <th>Realistic R</th>
              <th>SL share</th>
              <th>Top symbol</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={`${row.dimension}-${row.bucket}`}>
                <td>
                  <div className="font-semibold">{labelFor(row.bucket)}</div>
                  <div className="text-xs text-slate-500">{row.dimension}</div>
                </td>
                <td><StatusBadge value={row.read} /></td>
                <td>{row.sample_count}</td>
                <td>{row.tp_count} / {row.sl_count} / {row.open_count}</td>
                <td>{fmtSigned(row.realistic_total_r_closed)}R</td>
                <td>{row.sl_share_pct == null ? "-" : `${fmtNumber(row.sl_share_pct)}%`}</td>
                <td>{row.top_symbol} {row.top_symbol_share_pct == null ? "" : `(${fmtNumber(row.top_symbol_share_pct)}%)`}</td>
              </tr>
            ))}
            {!rows.length && (
              <tr>
                <td colSpan={7}><EmptyState title="No rows" detail="Tidak ada bucket untuk scope ini." /></td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function EvidenceTable({ rows }: { rows: MisidentificationEvidenceRow[] }) {
  const selected = rows.filter((row) => row.available_count > 0).slice(0, 14);
  return (
    <div className="overflow-hidden rounded-lg border border-line">
      <div className="border-b border-line bg-field/50 px-3 py-2 text-sm font-bold">Evidence correct vs wrong 1h</div>
      <div className="table-wrap">
        <table className="ops-table">
          <thead>
            <tr>
              <th>Evidence</th>
              <th>Flag</th>
              <th>Available</th>
              <th>Correct / wrong</th>
              <th>Correct median</th>
              <th>Wrong median</th>
              <th>Delta</th>
            </tr>
          </thead>
          <tbody>
            {selected.map((row) => (
              <tr key={row.field}>
                <td>
                  <div className="font-semibold">{row.label}</div>
                  <div className="text-xs text-slate-500">{row.field}</div>
                </td>
                <td><StatusBadge value={row.quality_flag} /></td>
                <td>{row.available_count} / miss {row.missing_count}</td>
                <td>{row.correct_count} / {row.wrong_count}</td>
                <td>{fmtNumber(row.correct_median)}</td>
                <td>{fmtNumber(row.wrong_median)}</td>
                <td>{fmtSigned(row.delta_correct_minus_wrong)}</td>
              </tr>
            ))}
            {!selected.length && (
              <tr>
                <td colSpan={7}><EmptyState title="No evidence" detail="Evidence belum tersedia untuk correct-vs-wrong." /></td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function SignalTable({ title, items }: { title: string; items: SignalPerformanceItem[] }) {
  return (
    <div className="overflow-hidden rounded-lg border border-line">
      <div className="border-b border-line bg-field/50 px-3 py-2 text-sm font-bold">{title}</div>
      <div className="table-wrap">
        <table className="ops-table">
          <thead>
            <tr>
              <th>Time WIB</th>
              <th>Symbol</th>
              <th>Stage</th>
              <th>Status</th>
              <th>Entry / SL / TP</th>
              <th>R</th>
              <th>MFE/MAE</th>
            </tr>
          </thead>
          <tbody>
            {items.map((item) => (
              <tr key={item.signal_id}>
                <td>{item.signal_time_wib || fmtTime(item.signal_timestamp)}</td>
                <td>
                  <Link
                    className="font-bold text-blue-700 hover:underline"
                    href={`/signals/${encodeURIComponent(item.symbol)}?signal_id=${encodeURIComponent(item.signal_id)}`}
                  >
                    {item.symbol}
                  </Link>
                </td>
                <td>{labelFor(item.stage)}</td>
                <td><StatusBadge value={item.result_status} /></td>
                <td>
                  <div>Entry {fmtPrice(item.entry)}</div>
                  <div>SL {fmtPrice(item.stop_loss)}</div>
                  <div>TP {fmtPrice(item.take_profit)}</div>
                </td>
                <td>{fmtSigned(item.realistic_realized_r ?? item.realized_r ?? item.unrealized_r)}R</td>
                <td>{fmtSigned(item.mfe_r)} / {fmtSigned(item.mae_r)}</td>
              </tr>
            ))}
            {!items.length && (
              <tr>
                <td colSpan={7}><EmptyState title="No signals" detail="Belum ada sample untuk tabel ini." /></td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Info({ label, value }: { label: string; value?: string | number | null }) {
  return (
    <div className="rounded border border-line bg-field/40 p-3 text-sm">
      <div className="text-xs font-semibold uppercase text-slate-500">{label}</div>
      <div className="mt-1 font-bold text-ink">{value == null || value === "" ? "-" : value}</div>
    </div>
  );
}

function fmtSigned(value?: string | number | null): string {
  if (value === null || value === undefined || value === "") return "-";
  const num = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(num)) return String(value);
  return `${num > 0 ? "+" : ""}${fmtNumber(num)}`;
}

function firstParam(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

function normalizeNumber(value: string | undefined, fallback: number, min: number, max: number): number {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.max(min, Math.min(max, Math.trunc(parsed)));
}
