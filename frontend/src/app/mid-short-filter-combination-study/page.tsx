import Link from "next/link";

import { MetricCard } from "@/components/MetricCard";
import { PageHeader } from "@/components/PageHeader";
import { SectionCard } from "@/components/SectionCard";
import { StatusBadge } from "@/components/StatusBadge";
import {
  MidShortFailureBucketRow,
  MidShortFilterCombinationDecisionBrief,
  MidShortFilterCombinationRow,
  MidShortFilterCombinationStudyResponse,
  SignalPerformanceItem,
  fetchJson,
  fmtNumber,
  fmtPrice,
  fmtTime
} from "@/lib/api";
import { labelFor } from "@/lib/labels";

type SearchParams = Promise<Record<string, string | string[] | undefined>>;

export const dynamic = "force-dynamic";

export default async function MidShortFilterCombinationStudyPage({ searchParams }: { searchParams: SearchParams }) {
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

  let data: MidShortFilterCombinationStudyResponse | null = null;
  let error: string | null = null;
  try {
    data = await fetchJson<MidShortFilterCombinationStudyResponse>(
      `/api/signal-candidates/mid-short-1h-filter-combination-study?${query.toString()}`
    );
  } catch (err) {
    error = err instanceof Error ? err.message : "Filter Combination API failed";
  }

  const summary = data?.summary;
  const baseline = summary?.baseline;
  const top = data?.top_filter;

  return (
    <div className="space-y-5">
      <PageHeader
        title="MID_SHORT 1h Filter Combination Study"
        badge="READ-ONLY V2.1 SHADOW RESEARCH"
        subtitle="Riset kombinasi filter untuk mengurangi SL dan salah arah di MID_SHORT 1h. Ini belum mengubah Signal Factory, scanner, TP/SL, atau execution."
        updatedAt={fmtTime(data?.generated_at_utc)}
      />

      <div className="flex flex-wrap gap-2 text-sm">
        <Link className="rounded border border-line bg-white px-3 py-2 font-semibold hover:bg-field" href="/mid-short-volume-safe-shadow">Open Volume Safe</Link>
        <Link className="rounded border border-line bg-white px-3 py-2 font-semibold hover:bg-field" href="/mid-short-wrong-direction-deep-dive">Open Wrong Direction</Link>
        <Link className="rounded border border-line bg-white px-3 py-2 font-semibold hover:bg-field" href="/signal-quality-lab?stage=MID_SHORT&timeframe=1h">Open Quality Lab</Link>
      </div>

      {error ? (
        <div className="rounded border border-stale bg-red-50 p-4 text-sm text-stale">{error}</div>
      ) : (
        <>
          <section className="grid gap-3 md:grid-cols-2 xl:grid-cols-6">
            <MetricCard label="Scope" value={summary?.scope_count ?? 0} helper="MID_SHORT 1h + taker sell >=52" />
            <MetricCard label="Baseline R" value={`${fmtSigned(baseline?.realistic_total_r_closed)}R`} helper={`${baseline?.tp_count ?? 0} TP / ${baseline?.sl_count ?? 0} SL`} tone={Number(baseline?.realistic_total_r_closed || 0) >= 0 ? "good" : "bad"} />
            <MetricCard label="Wrong 1h" value={`${fmtPct(summary?.baseline_direction?.wrong_direction_1h_share_pct)}`} helper={`${summary?.wrong_direction_1h_count ?? 0} signal salah arah`} tone="warn" />
            <MetricCard label="Shadow candidate" value={summary?.shadow_candidate_count ?? 0} helper="Kombinasi paling layak dipantau" tone="good" />
            <MetricCard label="Damage reduction" value={summary?.damage_reduction_count ?? 0} helper="Membaik tapi belum bersih" tone="info" />
            <MetricCard label="Verdict" value={labelFor(summary?.read)} helper={top?.label || "No top filter"} />
          </section>

          <SectionCard title="Controls" description="Filter halaman ini hanya mengubah audit. Tidak mengubah rule Signal Factory atau output scanner.">
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

          <SectionCard title="Top V2.1 shadow candidate" description="Filter terbaik menurut ranking saat ini. Masih research-only, bukan rule live.">
            {top ? (
              <div className="grid gap-3 p-4 md:grid-cols-2 xl:grid-cols-4">
                <Info label="Filter" value={top.label} />
                <Info label="Read" value={labelFor(top.read)} />
                <Info label="Realistic R" value={`${fmtSigned(top.realistic_total_r_closed)}R`} />
                <Info label="Wrong-direction" value={`${fmtPct(top.wrong_direction_1h_share_pct)} (${fmtPctDelta(top.wrong_direction_1h_share_pct_delta_vs_baseline)})`} />
                <Info label="SL share" value={`${fmtPct(top.sl_share_pct)} (${fmtPctDelta(top.sl_share_delta_vs_baseline)})`} />
                <Info label="Avg delta" value={`${fmtSigned(top.realistic_avg_r_delta_vs_baseline)}R`} />
                <Info label="Retained" value={fmtPct(top.sample_retention_pct)} />
                <Info label="Recommendation" value={top.shadow_recommendation} />
                <div className="rounded border border-line bg-field/40 p-3 md:col-span-2 xl:col-span-4">
                  <div className="text-xs font-semibold uppercase text-slate-500">Risk notes</div>
                  <div className="mt-2 flex flex-wrap gap-2 text-sm">
                    {(top.risk_notes || []).map((note) => <span key={note} className="rounded border border-line bg-white px-2 py-1">{note}</span>)}
                  </div>
                </div>
              </div>
            ) : (
              <div className="p-4 text-sm text-slate-500">No top filter</div>
            )}
          </SectionCard>

          <DecisionPanel data={data?.decision_panel} />

          <SectionCard title="Combination ranking" description="Cari baris yang realistic R naik, SL share turun, wrong-direction turun, drawdown tidak memburuk, dan sample tidak terlalu kecil.">
            <CombinationTable rows={data?.combination_rows || []} />
          </SectionCard>

          <section className="grid gap-4 xl:grid-cols-2">
            <SectionCard title="Top pass taxonomy" description="Path signal yang lolos kombinasi top filter.">
              <BucketTable rows={data?.top_filter_pass_taxonomy || []} />
            </SectionCard>
            <SectionCard title="Top fail taxonomy" description="Path signal yang gagal kombinasi top filter.">
              <BucketTable rows={data?.top_filter_fail_taxonomy || []} />
            </SectionCard>
          </section>

          <section className="grid gap-4 xl:grid-cols-2">
            <SectionCard title="Latest pass signals" description="Signal terbaru yang lolos kombinasi top filter.">
              <SignalTable items={data?.top_filter_pass_signals || []} />
            </SectionCard>
            <SectionCard title="Latest fail signals" description="Signal terbaru yang tidak lolos kombinasi top filter.">
              <SignalTable items={data?.top_filter_fail_signals || []} />
            </SectionCard>
          </section>

          <SectionCard title="Scope and guardrails" description="Batas interpretasi studi kombinasi ini.">
            <div className="grid gap-3 p-4 text-sm md:grid-cols-2 xl:grid-cols-4">
              <Info label="Base filter" value={data?.base_filter.label || "-"} />
              <Info label="Expression" value={data?.base_filter.expression || "-"} />
              <Info label="Latest candle" value={fmtTime(data?.latest_evaluation_candle_time)} />
              <Info label="Cache" value={data?.cache?.hit ? "hit" : "fresh"} />
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

function DecisionPanel({ data }: { data?: MidShortFilterCombinationStudyResponse["decision_panel"] }) {
  if (!data) {
    return (
      <SectionCard title="V2.1 decision panel" description="Ringkasan keputusan belum tersedia dari API.">
        <div className="p-4 text-sm text-slate-500">No decision panel</div>
      </SectionCard>
    );
  }
  return (
    <SectionCard
      title="V2.1 decision panel"
      description="Ringkasan praktis: apa yang layak dipantau, apa blocker promosi, dan validasi berikutnya. Ini tetap read-only."
    >
      <div className="grid gap-3 p-4 md:grid-cols-2 xl:grid-cols-4">
        <Info label="Decision" value={labelFor(data.decision)} />
        <Info label="Baseline" value={`${fmtSigned(data.baseline_snapshot.realistic_total_r_closed)}R / ${data.baseline_snapshot.tp_count}-${data.baseline_snapshot.sl_count}`} />
        <Info label="Baseline SL" value={fmtPct(data.baseline_snapshot.sl_share_pct)} />
        <Info label="Baseline wrong 1h" value={fmtPct(data.baseline_snapshot.wrong_direction_1h_share_pct)} />
      </div>
      <div className="grid gap-4 border-t border-line p-4 xl:grid-cols-4">
        <DecisionBrief title="Watch filter" row={data.watch_filter} />
        <DecisionBrief title="Best SL reducer" row={data.best_sl_reducer} />
        <DecisionBrief title="Best wrong-direction reducer" row={data.best_wrong_direction_reducer} />
        <DecisionBrief title="Best drawdown reducer" row={data.best_drawdown_reducer} />
      </div>
      <div className="grid gap-4 border-t border-line p-4 lg:grid-cols-3">
        <div className="rounded border border-line bg-field/40 p-3 lg:col-span-1">
          <div className="text-xs font-semibold uppercase text-slate-500">Recommendation</div>
          <div className="mt-2 text-sm font-semibold">{data.recommendation}</div>
        </div>
        <div className="rounded border border-line bg-field/40 p-3">
          <div className="text-xs font-semibold uppercase text-slate-500">Promotion blockers</div>
          <ul className="mt-2 grid gap-1 text-sm">
            {data.promotion_blockers.map((item) => <li key={item}>- {item}</li>)}
          </ul>
        </div>
        <div className="rounded border border-line bg-field/40 p-3">
          <div className="text-xs font-semibold uppercase text-slate-500">Next validation</div>
          <ul className="mt-2 grid gap-1 text-sm">
            {data.next_validation.map((item) => <li key={item}>- {item}</li>)}
          </ul>
        </div>
      </div>
    </SectionCard>
  );
}

function DecisionBrief({ title, row }: { title: string; row?: MidShortFilterCombinationDecisionBrief | null }) {
  if (!row) {
    return (
      <div className="rounded border border-line bg-field/40 p-3">
        <div className="text-xs font-semibold uppercase text-slate-500">{title}</div>
        <div className="mt-2 text-sm text-slate-500">No row</div>
      </div>
    );
  }
  return (
    <div className="rounded border border-line bg-field/40 p-3">
      <div className="text-xs font-semibold uppercase text-slate-500">{title}</div>
      <div className="mt-1 font-semibold">{row.label || row.filter_id}</div>
      <div className="mt-2 grid gap-1 text-xs text-slate-600">
        <div>Sample: {row.sample_count ?? 0}, closed {row.closed_count ?? 0}</div>
        <div>TP/SL: {row.tp_count ?? 0} / {row.sl_count ?? 0}</div>
        <div>Realistic: {fmtSigned(row.realistic_total_r_closed)}R ({fmtSigned(row.realistic_avg_r_delta_vs_baseline)}R avg delta)</div>
        <div>SL: {fmtPct(row.sl_share_pct)} ({fmtPctDelta(row.sl_share_delta_vs_baseline)})</div>
        <div>Wrong 1h: {fmtPct(row.wrong_direction_1h_share_pct)} ({fmtPctDelta(row.wrong_direction_1h_share_pct_delta_vs_baseline)})</div>
        <div>Top symbol: {row.top_symbol || "-"} ({fmtPct(row.top_symbol_share_pct)})</div>
      </div>
    </div>
  );
}

function CombinationTable({ rows }: { rows: MidShortFilterCombinationRow[] }) {
  return (
    <div className="table-wrap">
      <table className="ops-table">
        <thead>
          <tr>
            <th>Read</th>
            <th>Filter</th>
            <th>Sample</th>
            <th>TP / SL / Open</th>
            <th>Retain</th>
            <th>Realistic R</th>
            <th>Avg delta</th>
            <th>Wrong 1h</th>
            <th>SL share</th>
            <th>Drawdown</th>
            <th>Top symbol</th>
            <th>Risk</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.filter_id}>
              <td><StatusBadge value={row.read} /></td>
              <td>
                <div className="font-semibold">{row.label}</div>
                <div className="max-w-lg text-xs text-slate-500">{row.expression}</div>
              </td>
              <td>{row.sample_count} / miss {row.missing_data_count}</td>
              <td>{row.tp_count} / {row.sl_count} / {row.open_count}</td>
              <td>{fmtPct(row.sample_retention_pct)}</td>
              <td className={Number(row.realistic_total_r_closed || 0) >= 0 ? "font-semibold text-ready" : "font-semibold text-stale"}>{fmtSigned(row.realistic_total_r_closed)}R</td>
              <td>{fmtSigned(row.realistic_avg_r_delta_vs_baseline)}R</td>
              <td>{row.wrong_direction_1h_count} ({fmtPct(row.wrong_direction_1h_share_pct)}, {fmtPctDelta(row.wrong_direction_1h_share_pct_delta_vs_baseline)})</td>
              <td>{fmtPct(row.sl_share_pct)} ({fmtPctDelta(row.sl_share_delta_vs_baseline)})</td>
              <td>{fmtSigned(row.max_realistic_drawdown_r)}R</td>
              <td>{row.top_symbol} ({fmtPct(row.top_symbol_share_pct)})</td>
              <td className="max-w-sm text-xs text-slate-600">{(row.risk_notes || []).join(" ")}</td>
            </tr>
          ))}
          {!rows.length && (
            <tr><td colSpan={12} className="py-8 text-center text-sm text-slate-500">No rows</td></tr>
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
