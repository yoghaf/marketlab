import Link from "next/link";

import { MetricCard } from "@/components/MetricCard";
import { PageHeader } from "@/components/PageHeader";
import { SectionCard } from "@/components/SectionCard";
import { StatusBadge } from "@/components/StatusBadge";
import {
  MidShortFailureBucketRow,
  MidShortSecondFilterRow,
  MidShortTakerSellDeepDiveResponse,
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

export default async function MidShortTakerSellDeepDivePage({ searchParams }: { searchParams: SearchParams }) {
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

  let data: MidShortTakerSellDeepDiveResponse | null = null;
  let error: string | null = null;
  try {
    data = await fetchJson<MidShortTakerSellDeepDiveResponse>(
      `/api/signal-candidates/mid-short-1h-taker-sell-deep-dive?${query.toString()}`
    );
  } catch (err) {
    error = err instanceof Error ? err.message : "Taker Sell Deep Dive API failed";
  }

  const summary = data?.summary;
  const baseline = summary?.baseline;

  return (
    <div className="space-y-5">
      <PageHeader
        title="MID_SHORT 1h Taker Sell Deep Dive"
        badge="READ-ONLY RESEARCH"
        subtitle="Fokus hanya ke MID_SHORT 1h yang sudah lolos Taker Sell >= 52%. Tujuannya menjawab kenapa SL masih banyak dan filter tambahan apa yang bisa menaikkan kualitas TP/SL."
        updatedAt={fmtTime(data?.generated_at_utc)}
      />

      <div className="flex flex-wrap gap-2 text-sm">
        <Link className="rounded border border-line bg-white px-3 py-2 font-semibold hover:bg-field" href="/mid-short-second-filter-shadow">Open Second Filter</Link>
        <Link className="rounded border border-line bg-white px-3 py-2 font-semibold hover:bg-field" href="/mid-short-failure-anatomy">Open Failure Anatomy</Link>
        <Link className="rounded border border-line bg-white px-3 py-2 font-semibold hover:bg-field" href="/shadow-forward-log">Open Shadow Log</Link>
        <Link className="rounded border border-line bg-white px-3 py-2 font-semibold hover:bg-field" href="/signal-quality-lab?stage=MID_SHORT&timeframe=1h">Open Quality Lab</Link>
      </div>

      {error ? (
        <div className="rounded border border-stale bg-red-50 p-4 text-sm text-stale">{error}</div>
      ) : (
        <>
          <section className="grid gap-3 md:grid-cols-2 xl:grid-cols-6">
            <MetricCard label="Taker scope" value={summary?.scope_count ?? 0} helper={`from ${summary?.source_shadow_pass_count ?? 0} SHADOW_PASS`} />
            <MetricCard label="TP / SL" value={`${summary?.tp_count ?? 0} / ${summary?.sl_count ?? 0}`} helper={`${summary?.open_count ?? 0} open`} />
            <MetricCard label="Realistic R" value={`${fmtSigned(baseline?.realistic_total_r_closed)}R`} helper={`${fmtSigned(baseline?.realistic_avg_r_closed)}R avg`} tone={Number(baseline?.realistic_total_r_closed || 0) >= 0 ? "good" : "bad"} />
            <MetricCard label="SL then TP" value={summary?.sl_then_would_tp_count ?? 0} helper="Stop dulu, lalu target" tone="warn" />
            <MetricCard label="Near TP then SL" value={summary?.tp_near_then_sl_count ?? 0} helper="MFE >= +0.75R lalu stop" tone="warn" />
            <MetricCard label="Top filter" value={summary?.top_filter_label || "-"} helper={summary?.read || "-"} />
          </section>

          <SectionCard title="Deep dive controls" description="Ini hanya mengubah audit halaman. Tidak mengubah rule Signal Factory, scanner, TP/SL, atau execution.">
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

          <SectionCard title="Candidate filters inside Taker Sell >= 52%" description="Ranking filter tambahan. Yang dicari: realistic R naik, SL share turun, wrong-direction turun, dan drawdown tidak memburuk.">
            <FilterTable rows={data?.filter_rows || []} />
          </SectionCard>

          <section className="grid gap-4 xl:grid-cols-2">
            <SectionCard title="Why SL still happens" description="Path TP/SL khusus subset Taker Sell >= 52%.">
              <BucketTable rows={data?.outcome_path_rows || []} />
            </SectionCard>
            <SectionCard title="MFE/MAE evidence split" description="Median evidence TP dibanding SL untuk subset ini.">
              <EvidenceTable rows={(data?.evidence_tp_vs_sl || []).slice(0, 14)} />
            </SectionCard>
          </section>

          <section className="grid gap-4 xl:grid-cols-2">
            <SectionCard title="Direction check" description="Untuk SHORT, correct direction berarti return harga negatif setelah signal.">
              <BucketTable rows={data?.direction_rows || []} showDimension />
            </SectionCard>
            <SectionCard title="BTC/ETH regime split" description="Cek apakah loss terkonsentrasi ketika BTC/ETH melawan.">
              <BucketTable rows={data?.regime_rows || []} showDimension />
            </SectionCard>
          </section>

          <section className="grid gap-4 xl:grid-cols-2">
            <SectionCard title="Latest SL samples" description="Sample loss terbaru di subset taker sell; buka detail untuk angka lengkap.">
              <SignalTable items={data?.latest_sl_signals || []} />
            </SectionCard>
            <SectionCard title="Latest TP samples" description="Pembanding signal yang target duluan.">
              <SignalTable items={data?.latest_tp_signals || []} />
            </SectionCard>
          </section>

          <section className="grid gap-4 xl:grid-cols-[1fr_1.2fr]">
            <SectionCard title="Symbol concentration" description="Cek apakah hasil terlalu bergantung ke token tertentu.">
              <BucketTable rows={(data?.symbol_rows || []).slice(0, 30)} />
            </SectionCard>
            <SectionCard title="Latest rows from top filter" description="Signal terbaru yang lolos filter paling atas.">
              <SignalTable items={data?.top_filter_items || []} />
            </SectionCard>
          </section>

          <SectionCard title="Base filter scope" description="Subset yang sedang diteliti.">
            <div className="grid gap-3 p-4 text-sm md:grid-cols-2 xl:grid-cols-4">
              <Info label="Base filter" value={data?.base_filter.label || "-"} />
              <Info label="Expression" value={data?.base_filter.expression || "-"} />
              <Info label="Meaning" value={data?.base_filter.status_meaning || "-"} />
              <Info label="Latest candle" value={fmtTime(data?.latest_evaluation_candle_time)} />
            </div>
          </SectionCard>

          <SectionCard title="Guardrails" description="Batasan interpretasi riset ini.">
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
            <th>SL delta</th>
            <th>Wrong-dir delta</th>
            <th>SL then TP delta</th>
            <th>Drawdown delta</th>
            <th>Top symbol</th>
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
              <td>{fmtSigned(row.max_drawdown_delta_vs_baseline)}R</td>
              <td>{row.top_symbol} ({fmtPct(row.top_symbol_share_pct)})</td>
              <td><StatusBadge value={row.read} /></td>
            </tr>
          ))}
          {!rows.length && (
            <tr>
              <td colSpan={13} className="py-8 text-center text-sm text-slate-500">No deep filter rows</td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

function BucketTable({ rows, showDimension = false }: { rows: MidShortFailureBucketRow[]; showDimension?: boolean }) {
  return (
    <div className="table-wrap">
      <table className="ops-table">
        <thead>
          <tr>
            {showDimension ? <th>Dimension</th> : null}
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
            <tr key={`${row.dimension}-${row.horizon || ""}-${row.bucket}`}>
              {showDimension ? <td>{row.horizon || labelFor(row.dimension)}</td> : null}
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
            <tr>
              <td colSpan={showDimension ? 8 : 7} className="py-8 text-center text-sm text-slate-500">No rows</td>
            </tr>
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
              <td>{row.available_count} / miss {row.missing_count}</td>
              <td>{row.tp_count} / {row.sl_count}</td>
              <td>{fmtNumber(row.tp_median)}</td>
              <td>{fmtNumber(row.sl_median)}</td>
              <td>{fmtSigned(row.delta_tp_minus_sl)}</td>
              <td>{fmtNumber(row.tp_q1)} / {fmtNumber(row.tp_q3)}</td>
              <td>{fmtNumber(row.sl_q1)} / {fmtNumber(row.sl_q3)}</td>
            </tr>
          ))}
          {!rows.length && (
            <tr>
              <td colSpan={9} className="py-8 text-center text-sm text-slate-500">No evidence rows</td>
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
              <td colSpan={7} className="py-8 text-center text-sm text-slate-500">No signal rows</td>
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
