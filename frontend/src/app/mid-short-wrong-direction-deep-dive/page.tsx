import Link from "next/link";

import { MetricCard } from "@/components/MetricCard";
import { PageHeader } from "@/components/PageHeader";
import { SectionCard } from "@/components/SectionCard";
import { StatusBadge } from "@/components/StatusBadge";
import {
  MidShortFailureBucketRow,
  MidShortWrongDirectionDeepDiveResponse,
  MidShortWrongDirectionEvidenceRow,
  MidShortWrongDirectionFilterRow,
  SignalPerformanceItem,
  fetchJson,
  fmtNumber,
  fmtPrice,
  fmtTime
} from "@/lib/api";
import { labelFor } from "@/lib/labels";

type SearchParams = Promise<Record<string, string | string[] | undefined>>;

export const dynamic = "force-dynamic";

export default async function MidShortWrongDirectionDeepDivePage({ searchParams }: { searchParams: SearchParams }) {
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

  let data: MidShortWrongDirectionDeepDiveResponse | null = null;
  let error: string | null = null;
  try {
    data = await fetchJson<MidShortWrongDirectionDeepDiveResponse>(
      `/api/signal-candidates/mid-short-1h-wrong-direction-deep-dive?${query.toString()}`
    );
  } catch (err) {
    error = err instanceof Error ? err.message : "Wrong Direction Deep Dive API failed";
  }

  const summary = data?.summary;
  const baseline = summary?.baseline;
  const wrongPerf = summary?.wrong_direction_perf;
  const correctPerf = summary?.correct_direction_perf;

  return (
    <div className="space-y-5">
      <PageHeader
        title="MID_SHORT 1h Wrong Direction Deep Dive"
        badge="READ-ONLY RESEARCH"
        subtitle="Membedah kenapa MID_SHORT 1h + Taker Sell >= 52% masih salah arah. Fokusnya mencari tanda sebelum signal yang membedakan short yang benar turun vs yang malah naik."
        updatedAt={fmtTime(data?.generated_at_utc)}
      />

      <div className="flex flex-wrap gap-2 text-sm">
        <Link className="rounded border border-line bg-white px-3 py-2 font-semibold hover:bg-field" href="/mid-short-taker-sell-deep-dive">Open Taker Deep Dive</Link>
        <Link className="rounded border border-line bg-white px-3 py-2 font-semibold hover:bg-field" href="/mid-short-second-filter-shadow">Open Second Filter</Link>
        <Link className="rounded border border-line bg-white px-3 py-2 font-semibold hover:bg-field" href="/mid-short-failure-anatomy">Open Failure Anatomy</Link>
        <Link className="rounded border border-line bg-white px-3 py-2 font-semibold hover:bg-field" href="/signal-quality-lab?stage=MID_SHORT&timeframe=1h">Open Quality Lab</Link>
      </div>

      {error ? (
        <div className="rounded border border-stale bg-red-50 p-4 text-sm text-stale">{error}</div>
      ) : (
        <>
          <section className="grid gap-3 md:grid-cols-2 xl:grid-cols-6">
            <MetricCard label="Scope" value={summary?.scope_count ?? 0} helper={`from ${summary?.source_shadow_pass_count ?? 0} SHADOW_PASS`} />
            <MetricCard label="Wrong 1h" value={`${summary?.wrong_direction_1h_count ?? 0}`} helper={fmtPct(summary?.wrong_direction_1h_share_pct)} tone="bad" />
            <MetricCard label="Correct 1h" value={`${summary?.correct_direction_1h_count ?? 0}`} helper={fmtPct(summary?.correct_direction_1h_share_pct)} tone="good" />
            <MetricCard label="Baseline R" value={`${fmtSigned(baseline?.realistic_total_r_closed)}R`} helper={`${summary?.tp_count ?? 0} TP / ${summary?.sl_count ?? 0} SL`} tone={Number(baseline?.realistic_total_r_closed || 0) >= 0 ? "good" : "bad"} />
            <MetricCard label="Wrong bucket R" value={`${fmtSigned(wrongPerf?.realistic_total_r_closed)}R`} helper={`${wrongPerf?.sample_count ?? 0} sample`} tone="bad" />
            <MetricCard label="Top anti-filter" value={summary?.top_filter_label || "-"} helper={summary?.read || "-"} />
          </section>

          <SectionCard title="Controls" description="Filter ini hanya untuk audit halaman. Tidak mengubah rule Signal Factory, scanner, TP/SL, atau execution.">
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

          <section className="grid gap-4 xl:grid-cols-[0.9fr_1.1fr]">
            <SectionCard title="Wrong-direction taxonomy" description="Klasifikasi alasan awal kenapa short bergerak naik setelah signal.">
              <BucketTable rows={data?.wrong_direction_taxonomy_rows || []} />
            </SectionCard>
            <SectionCard title="Followthrough flags" description="Baca apakah short langsung followthrough, langsung reversal, atau tertarik BTC/ETH.">
              <BucketTable rows={data?.followthrough_rows || []} showDimension />
            </SectionCard>
          </section>

          <SectionCard title="Anti wrong-direction filters" description="Ranking filter sebelum signal yang berpotensi mengurangi kasus salah arah. Ini tetap research-only.">
            <FilterTable rows={data?.anti_wrong_direction_filter_rows || []} />
          </SectionCard>

          <SectionCard title="Correct vs wrong evidence" description="Median evidence actual dari signal yang 1h-nya benar turun dibanding yang salah arah naik.">
            <EvidenceDirectionTable rows={data?.evidence_correct_vs_wrong || []} />
          </SectionCard>

          <section className="grid gap-4 xl:grid-cols-2">
            <SectionCard title="BTC/ETH regime split" description="Cek apakah wrong direction terkonsentrasi saat BTC/ETH 1h bullish.">
              <BucketTable rows={data?.regime_rows || []} showDimension />
            </SectionCard>
            <SectionCard title="Wrong-direction symbols" description="Token yang paling sering masuk bucket salah arah di scope ini.">
              <BucketTable rows={data?.symbol_wrong_rows || []} />
            </SectionCard>
          </section>

          <section className="grid gap-4 xl:grid-cols-2">
            <SectionCard title="Latest wrong-direction samples" description="Signal terbaru yang 1h setelah entry bergerak melawan short.">
              <SignalTable items={data?.latest_wrong_direction_signals || []} />
            </SectionCard>
            <SectionCard title="Latest correct-direction samples" description="Pembanding signal yang 1h setelah entry benar turun.">
              <SignalTable items={data?.latest_correct_direction_signals || []} />
            </SectionCard>
          </section>

          <SectionCard title="Rows from top anti-filter" description="Signal terbaru yang lolos filter paling atas.">
            <SignalTable items={data?.top_filter_items || []} />
          </SectionCard>

          <SectionCard title="Base scope and guardrails" description="Batas interpretasi riset ini.">
            <div className="grid gap-3 p-4 text-sm md:grid-cols-2 xl:grid-cols-4">
              <Info label="Base filter" value={data?.base_filter.label || "-"} />
              <Info label="Expression" value={data?.base_filter.expression || "-"} />
              <Info label="Latest candle" value={fmtTime(data?.latest_evaluation_candle_time)} />
              <Info label="Correct bucket R" value={`${fmtSigned(correctPerf?.realistic_total_r_closed)}R`} />
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

function FilterTable({ rows }: { rows: MidShortWrongDirectionFilterRow[] }) {
  return (
    <div className="table-wrap">
      <table className="ops-table">
        <thead>
          <tr>
            <th>Filter</th>
            <th>Family</th>
            <th>Sample</th>
            <th>TP / SL / Open</th>
            <th>Wrong 1h</th>
            <th>Wrong delta</th>
            <th>Realistic R</th>
            <th>Avg delta</th>
            <th>SL delta</th>
            <th>Retain</th>
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
              <td>{row.wrong_direction_1h_count} ({fmtPct(row.wrong_direction_1h_share_pct)})</td>
              <td>{fmtPctDelta(row.wrong_direction_1h_share_pct_delta_vs_baseline)}</td>
              <td className={Number(row.realistic_total_r_closed || 0) >= 0 ? "font-semibold text-ready" : "font-semibold text-stale"}>{fmtSigned(row.realistic_total_r_closed)}R</td>
              <td>{fmtSigned(row.realistic_avg_r_delta_vs_baseline)}R</td>
              <td>{fmtPctDelta(row.sl_share_delta_vs_baseline)}</td>
              <td>{fmtPct(row.sample_retention_pct)}</td>
              <td>{row.top_symbol} ({fmtPct(row.top_symbol_share_pct)})</td>
              <td><StatusBadge value={row.read} /></td>
            </tr>
          ))}
          {!rows.length && (
            <tr>
              <td colSpan={12} className="py-8 text-center text-sm text-slate-500">No anti-filter rows</td>
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

function EvidenceDirectionTable({ rows }: { rows: MidShortWrongDirectionEvidenceRow[] }) {
  return (
    <div className="table-wrap">
      <table className="ops-table">
        <thead>
          <tr>
            <th>Evidence</th>
            <th>Flag</th>
            <th>Available</th>
            <th>Correct / Wrong</th>
            <th>Correct median</th>
            <th>Wrong median</th>
            <th>Delta</th>
            <th>Correct Q1/Q3</th>
            <th>Wrong Q1/Q3</th>
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
              <td>{row.correct_count} / {row.wrong_count}</td>
              <td>{fmtNumber(row.correct_median)}</td>
              <td>{fmtNumber(row.wrong_median)}</td>
              <td>{fmtSigned(row.delta_correct_minus_wrong)}</td>
              <td>{fmtNumber(row.correct_q1)} / {fmtNumber(row.correct_q3)}</td>
              <td>{fmtNumber(row.wrong_q1)} / {fmtNumber(row.wrong_q3)}</td>
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
            <th>Direction 1h</th>
            <th>Wrong type</th>
            <th>Entry / SL / TP</th>
            <th>R</th>
            <th>Return 15m / 1h</th>
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
              <td><StatusBadge value={item.wrong_direction_type} /></td>
              <td>
                <div>Entry {fmtPrice(item.entry)}</div>
                <div>SL {fmtPrice(item.stop_loss)}</div>
                <div>TP {fmtPrice(item.take_profit)}</div>
              </td>
              <td>{fmtSigned(item.realistic_realized_r ?? item.realized_r ?? item.realistic_unrealized_r ?? item.unrealized_r)}R</td>
              <td>{fmtSigned(item.return_15m_pct)}% / {fmtSigned(item.return_1h_pct)}%</td>
              <td>
                <Link className="text-blue-700 hover:underline" href={`/signals/${item.symbol}?signal_id=${encodeURIComponent(item.signal_id)}`}>Open</Link>
              </td>
            </tr>
          ))}
          {!items.length && (
            <tr>
              <td colSpan={9} className="py-8 text-center text-sm text-slate-500">No signal rows</td>
            </tr>
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
