import Link from "next/link";

import { MetricCard } from "@/components/MetricCard";
import { PageHeader } from "@/components/PageHeader";
import { SectionCard } from "@/components/SectionCard";
import { StatusBadge } from "@/components/StatusBadge";
import {
  MidShortFailureBucketRow,
  MidShortVolumeSafeShadowResponse,
  MidShortVolumeSafeStatusRow,
  SignalPerformanceItem,
  SignalQualityEvidenceField,
  fetchJson,
  fmtNumber,
  fmtPrice,
  fmtTime
} from "@/lib/api";
import { labelFor } from "@/lib/labels";

type SearchParams = Promise<Record<string, string | string[] | undefined>>;

export const dynamic = "force-dynamic";

export default async function MidShortVolumeSafeShadowPage({ searchParams }: { searchParams: SearchParams }) {
  const params = await searchParams;
  const includeWatchOnly = firstParam(params.include_watch_only) === "true";
  const positionLock = firstParam(params.position_lock) !== "false";
  const minSample = normalizeNumber(firstParam(params.min_sample), 20, 1, 100);
  const limit = normalizeNumber(firstParam(params.limit), 50, 10, 150);
  const query = new URLSearchParams({
    include_watch_only: String(includeWatchOnly),
    position_lock: String(positionLock),
    min_sample: String(minSample),
    limit: String(limit)
  });

  let data: MidShortVolumeSafeShadowResponse | null = null;
  let error: string | null = null;
  try {
    data = await fetchJson<MidShortVolumeSafeShadowResponse>(
      `/api/signal-candidates/mid-short-1h-volume-safe-shadow?${query.toString()}`
    );
  } catch (err) {
    error = err instanceof Error ? err.message : "Volume Safe Shadow API failed";
  }

  const summary = data?.summary;
  const baseline = summary?.baseline;
  const pass = summary?.pass;
  const fail = summary?.fail;

  return (
    <div className="space-y-5">
      <PageHeader
        title="MID_SHORT 1h Volume Safe Shadow"
        badge="READ-ONLY SHADOW MONITOR"
        subtitle="Monitor khusus untuk filter anti-salah-arah: MID_SHORT 1h + Taker Sell >= 52% lalu dipisah volume <= 1.50x vs volume > 1.50x. Ini belum mengubah rule live."
        updatedAt={fmtTime(data?.generated_at_utc)}
      />

      <div className="flex flex-wrap gap-2 text-sm">
        <Link className="rounded border border-line bg-white px-3 py-2 font-semibold hover:bg-field" href="/mid-short-wrong-direction-deep-dive">Open Wrong Direction</Link>
        <Link className="rounded border border-line bg-white px-3 py-2 font-semibold hover:bg-field" href="/mid-short-taker-sell-deep-dive">Open Taker Deep Dive</Link>
        <Link className="rounded border border-line bg-white px-3 py-2 font-semibold hover:bg-field" href="/signal-quality-lab?stage=MID_SHORT&timeframe=1h">Open Quality Lab</Link>
      </div>

      {error ? (
        <div className="rounded border border-stale bg-red-50 p-4 text-sm text-stale">{error}</div>
      ) : (
        <>
          <section className="grid gap-3 md:grid-cols-2 xl:grid-cols-6">
            <MetricCard label="Scope" value={summary?.scope_count ?? 0} helper="MID_SHORT 1h + taker sell >=52" />
            <MetricCard label="Pass" value={summary?.pass_count ?? 0} helper={`${fmtPct(summary?.pass_retention_pct)} retained`} tone="good" />
            <MetricCard label="Fail" value={summary?.fail_count ?? 0} helper="Volume > 1.50x" tone="warn" />
            <MetricCard label="Baseline R" value={`${fmtSigned(baseline?.realistic_total_r_closed)}R`} helper={`${baseline?.tp_count ?? 0} TP / ${baseline?.sl_count ?? 0} SL`} tone={Number(baseline?.realistic_total_r_closed || 0) >= 0 ? "good" : "bad"} />
            <MetricCard label="Pass R" value={`${fmtSigned(pass?.realistic_total_r_closed)}R`} helper={`${fmtSigned(pass?.realistic_avg_r_delta_vs_baseline)}R avg delta`} tone="good" />
            <MetricCard label="Verdict" value={labelFor(summary?.read)} helper="read-only shadow" />
          </section>

          <SectionCard title="Controls" description="Filter ini hanya mengubah audit halaman. Tidak mengubah rule Signal Factory, scanner, TP/SL, atau execution.">
            <form className="grid gap-3 p-4 text-sm md:grid-cols-4">
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

          <SectionCard title="Pass vs fail comparison" description="Pass berarti volume <= 1.50x. Fail berarti volume lebih meledak dari batas itu.">
            <StatusTable rows={data?.status_rows || []} />
          </SectionCard>

          <section className="grid gap-4 xl:grid-cols-2">
            <SectionCard title="Pass taxonomy" description="Path signal yang lolos volume-safe.">
              <BucketTable rows={data?.pass_taxonomy_rows || []} />
            </SectionCard>
            <SectionCard title="Fail taxonomy" description="Path signal yang gagal volume-safe. Ini bucket yang dicurigai sebagai overextended/panic sell telat.">
              <BucketTable rows={data?.fail_taxonomy_rows || []} />
            </SectionCard>
          </section>

          <SectionCard title="Pass evidence TP vs SL" description="Evidence actual dalam subset volume-safe yang TP dibanding SL.">
            <EvidenceTable rows={(data?.pass_evidence_tp_vs_sl || []).slice(0, 14)} />
          </SectionCard>

          <section className="grid gap-4 xl:grid-cols-2">
            <SectionCard title="Latest pass signals" description="Signal terbaru yang lolos volume-safe.">
              <SignalTable items={data?.latest_pass_signals || []} />
            </SectionCard>
            <SectionCard title="Latest fail signals" description="Signal terbaru yang volume-nya terlalu meledak menurut shadow filter.">
              <SignalTable items={data?.latest_fail_signals || []} />
            </SectionCard>
          </section>

          <SectionCard title="Scope and guardrails" description="Batas interpretasi shadow monitor ini.">
            <div className="grid gap-3 p-4 text-sm md:grid-cols-2 xl:grid-cols-4">
              <Info label="Base filter" value={data?.base_filter.label || "-"} />
              <Info label="Shadow filter" value={data?.shadow_filter.label || "-"} />
              <Info label="Fail R" value={`${fmtSigned(fail?.realistic_total_r_closed)}R`} />
              <Info label="Latest candle" value={fmtTime(data?.latest_evaluation_candle_time)} />
            </div>
            <ul className="grid gap-2 border-t border-line p-4 text-sm text-slate-700 md:grid-cols-2">
              {(data?.guardrails || []).map((item) => <li key={item} className="rounded border border-line bg-field/40 p-3">{item}</li>)}
            </ul>
          </SectionCard>
        </>
      )}
    </div>
  );
}

function StatusTable({ rows }: { rows: MidShortVolumeSafeStatusRow[] }) {
  return (
    <div className="table-wrap">
      <table className="ops-table">
        <thead>
          <tr>
            <th>Status</th>
            <th>Sample</th>
            <th>TP / SL / Open</th>
            <th>Retain</th>
            <th>Wrong 1h</th>
            <th>Wrong delta</th>
            <th>Realistic R</th>
            <th>Avg delta</th>
            <th>SL share</th>
            <th>Drawdown</th>
            <th>Top symbol</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.shadow_status}>
              <td><StatusBadge value={row.shadow_status} /></td>
              <td>{row.sample_count}</td>
              <td>{row.tp_count} / {row.sl_count} / {row.open_count}</td>
              <td>{fmtPct(row.sample_retention_pct)}</td>
              <td>{row.wrong_direction_1h_count} ({fmtPct(row.wrong_direction_1h_share_pct)})</td>
              <td>{fmtPctDelta(row.wrong_direction_1h_share_pct_delta_vs_baseline)}</td>
              <td className={Number(row.realistic_total_r_closed || 0) >= 0 ? "font-semibold text-ready" : "font-semibold text-stale"}>{fmtSigned(row.realistic_total_r_closed)}R</td>
              <td>{fmtSigned(row.realistic_avg_r_delta_vs_baseline)}R</td>
              <td>{fmtPct(row.sl_share_pct)}</td>
              <td>{fmtSigned(row.max_realistic_drawdown_r)}R</td>
              <td>{row.top_symbol} ({fmtPct(row.top_symbol_share_pct)})</td>
            </tr>
          ))}
          {!rows.length && (
            <tr><td colSpan={11} className="py-8 text-center text-sm text-slate-500">No rows</td></tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

function BucketTable({ rows }: { rows: MidShortFailureBucketRow[] }) {
  return (
    <div className="table-wrap">
      <table className="ops-table">
        <thead>
          <tr>
            <th>Bucket</th>
            <th>Sample</th>
            <th>TP / SL / Open</th>
            <th>SL share</th>
            <th>Realistic R</th>
            <th>Avg R</th>
            <th>Read</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={`${row.dimension}-${row.bucket}`}>
              <td><StatusBadge value={row.bucket} /></td>
              <td>{row.sample_count}</td>
              <td>{row.tp_count} / {row.sl_count} / {row.open_count}</td>
              <td>{fmtPct(row.sl_share_pct)}</td>
              <td>{fmtSigned(row.realistic_total_r_closed)}R</td>
              <td>{fmtSigned(row.realistic_avg_r_closed)}R</td>
              <td className="max-w-md text-slate-600">{row.read}</td>
            </tr>
          ))}
          {!rows.length && (
            <tr><td colSpan={7} className="py-8 text-center text-sm text-slate-500">No rows</td></tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

function EvidenceTable({ rows }: { rows: SignalQualityEvidenceField[] }) {
  return (
    <div className="table-wrap">
      <table className="ops-table">
        <thead>
          <tr>
            <th>Evidence</th>
            <th>Flag</th>
            <th>Available</th>
            <th>TP / SL</th>
            <th>TP median</th>
            <th>SL median</th>
            <th>Delta</th>
            <th>TP Q1/Q3</th>
            <th>SL Q1/Q3</th>
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
              <td>{row.available_count} / miss {row.missing_count} ({fmtPct(row.available_pct)})</td>
              <td>{row.tp_count} / {row.sl_count}</td>
              <td>{fmtNumber(row.tp_median)}</td>
              <td>{fmtNumber(row.sl_median)}</td>
              <td>{fmtSigned(row.delta_tp_minus_sl)}</td>
              <td>{fmtNumber(row.tp_q1)} / {fmtNumber(row.tp_q3)}</td>
              <td>{fmtNumber(row.sl_q1)} / {fmtNumber(row.sl_q3)}</td>
            </tr>
          ))}
          {!rows.length && (
            <tr><td colSpan={9} className="py-8 text-center text-sm text-slate-500">No evidence rows</td></tr>
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
            <th>Direction 1h</th>
            <th>Volume</th>
            <th>Entry / SL / TP</th>
            <th>R</th>
            <th>Detail</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item) => (
            <tr key={item.signal_id}>
              <td>{fmtTime(item.signal_timestamp)}</td>
              <td className="font-semibold">{item.symbol}</td>
              <td><StatusBadge value={item.result_status} /></td>
              <td><StatusBadge value={item.direction_1h} /></td>
              <td>{fmtNumber(item.evidence_snapshot?.volume_ratio_vs_lookback)}x</td>
              <td>
                <div>Entry {fmtPrice(item.entry)}</div>
                <div>SL {fmtPrice(item.stop_loss)}</div>
                <div>TP {fmtPrice(item.take_profit)}</div>
              </td>
              <td>{fmtSigned(item.realistic_realized_r ?? item.realized_r ?? item.realistic_unrealized_r ?? item.unrealized_r)}R</td>
              <td>
                <Link className="text-blue-700 hover:underline" href={`/signals/${item.symbol}?signal_id=${encodeURIComponent(item.signal_id)}`}>Open</Link>
              </td>
            </tr>
          ))}
          {!items.length && (
            <tr><td colSpan={8} className="py-8 text-center text-sm text-slate-500">No signal rows</td></tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

function Info({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded border border-line bg-field/40 p-3">
      <div className="text-xs font-semibold uppercase text-slate-500">{label}</div>
      <div className="mt-1 font-semibold">{value}</div>
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
  if (Math.abs(num) < 0.005) return "0";
  return `${num > 0 ? "+" : ""}${new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 }).format(num)}`;
}

function fmtPct(value?: string | number | null): string {
  if (value === null || value === undefined || value === "") return "-";
  const num = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(num)) return String(value);
  return `${new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 }).format(num)}%`;
}

function fmtPctDelta(value?: string | number | null): string {
  if (value === null || value === undefined || value === "") return "-";
  return `${fmtSigned(value)}pp`;
}
