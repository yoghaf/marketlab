import Link from "next/link";

import { MetricCard } from "@/components/MetricCard";
import { PageHeader } from "@/components/PageHeader";
import { SectionCard } from "@/components/SectionCard";
import { StatusBadge } from "@/components/StatusBadge";
import {
  MidShortFailureAnatomyResponse,
  MidShortFailureBucketRow,
  MidShortFailureImprovementCandidate,
  SignalPerformanceItem,
  SignalQualityEvidenceField,
  fetchJson,
  fmtNumber,
  fmtPrice,
  fmtTime
} from "@/lib/api";
import { labelFor } from "@/lib/labels";

type SearchParams = Promise<Record<string, string | string[] | undefined>>;
type AnatomySignalItem = SignalPerformanceItem & Record<string, unknown>;

export const dynamic = "force-dynamic";

export default async function MidShortFailureAnatomyPage({ searchParams }: { searchParams: SearchParams }) {
  const params = await searchParams;
  const includeWatchOnly = firstParam(params.include_watch_only) === "true";
  const positionLock = firstParam(params.position_lock) !== "false";
  const shadowStatus = firstParam(params.shadow_status) || "SHADOW_PASS";
  const minSample = normalizeNumber(firstParam(params.min_sample), 20, 1, 100);
  const limit = normalizeNumber(firstParam(params.limit), 50, 10, 150);
  const query = new URLSearchParams({
    include_watch_only: String(includeWatchOnly),
    position_lock: String(positionLock),
    shadow_status: shadowStatus,
    min_sample: String(minSample),
    limit: String(limit)
  });

  let data: MidShortFailureAnatomyResponse | null = null;
  let error: string | null = null;
  try {
    data = await fetchJson<MidShortFailureAnatomyResponse>(
      `/api/signal-candidates/mid-short-1h-failure-anatomy?${query.toString()}`
    );
  } catch (err) {
    error = err instanceof Error ? err.message : "Failure Anatomy API failed";
  }

  const summary = data?.summary;

  return (
    <div className="space-y-5">
      <PageHeader
        title="MID_SHORT 1h Failure Anatomy"
        badge="READ-ONLY RESEARCH"
        subtitle="Bedah kenapa MID_SHORT 1h SHADOW_PASS masih kena SL: salah arah, stop dulu lalu target, hampir target lalu balik stop, regime BTC/ETH, evidence conflict, symbol, dan jam WIB. Ini tidak mengubah rule live."
        updatedAt={fmtTime(data?.generated_at_utc)}
      />

      <div className="flex flex-wrap gap-2 text-sm">
        <Link className="rounded border border-line bg-white px-3 py-2 font-semibold hover:bg-field" href="/shadow-forward-log">Open Shadow Log</Link>
        <Link className="rounded border border-line bg-white px-3 py-2 font-semibold hover:bg-field" href="/signal-quality-lab?stage=MID_SHORT&timeframe=1h">Open Quality Lab</Link>
        <Link className="rounded border border-line bg-white px-3 py-2 font-semibold hover:bg-field" href="/mid-short-second-filter-shadow">Open Second Filter Shadow</Link>
        <Link className="rounded border border-line bg-white px-3 py-2 font-semibold hover:bg-field" href="/signal-performance?stage=MID_SHORT&timeframe=1h">Open Signal History</Link>
      </div>

      {error ? (
        <div className="rounded border border-stale bg-red-50 p-4 text-sm text-stale">{error}</div>
      ) : (
        <>
          <section className="grid gap-3 md:grid-cols-2 xl:grid-cols-6">
            <MetricCard label="Scope sample" value={summary?.source_count ?? 0} helper={`${summary?.closed_count ?? 0} closed`} />
            <MetricCard label="TP / SL" value={`${summary?.tp_count ?? 0} / ${summary?.sl_count ?? 0}`} helper={`${summary?.open_count ?? 0} open`} />
            <MetricCard label="SL lalu target" value={summary?.sl_then_would_tp_count ?? 0} helper="Stop dulu, setelah itu target tersentuh" tone="warn" />
            <MetricCard label="Nyaris target lalu SL" value={summary?.tp_near_then_sl_count ?? 0} helper="MFE >= +0.75R sebelum SL" tone="warn" />
            <MetricCard label="Salah arah 1h" value={summary?.wrong_direction_1h_count ?? 0} helper={`${summary?.correct_direction_1h_count ?? 0} benar arah`} tone="bad" />
            <MetricCard label="Realistic R" value={`${fmtSigned(data?.baseline.realistic_total_r_closed)}R`} helper={summary?.read || "-"} tone={Number(data?.baseline.realistic_total_r_closed || 0) >= 0 ? "good" : "bad"} />
          </section>

          <SectionCard title="Failure controls" description="Filter ini hanya mengubah audit. Tidak mengubah Signal Factory atau scanner.">
            <form className="grid gap-3 p-4 text-sm md:grid-cols-5">
              <label className="grid gap-1">
                <span className="font-semibold text-slate-600">Shadow status</span>
                <select className="rounded border border-line px-3 py-2" name="shadow_status" defaultValue={shadowStatus}>
                  <option value="SHADOW_PASS">SHADOW_PASS</option>
                  <option value="SHADOW_FAIL">SHADOW_FAIL</option>
                  <option value="SHADOW_UNAVAILABLE">SHADOW_UNAVAILABLE</option>
                  <option value="ALL">ALL</option>
                </select>
              </label>
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

          <SectionCard title="Outcome path anatomy" description="Ini menjawab apakah SL karena arah salah, stop terlalu dekat, atau harga sempat benar dulu.">
            <BucketTable rows={data?.outcome_path_rows || []} />
          </SectionCard>

          <section className="grid gap-4 xl:grid-cols-2">
            <SectionCard title="Direction correctness by horizon" description="Untuk SHORT, benar arah berarti return harga negatif setelah signal.">
              <BucketTable rows={data?.direction_rows || []} showDimension />
            </SectionCard>
            <SectionCard title="MFE / MAE read" description="MFE = gerak terbaik ke arah target; MAE = gerak terburuk melawan posisi.">
              <MfeMaeTable rows={data?.mfe_mae_summary || {}} />
            </SectionCard>
          </section>

          <SectionCard title="Candidate second filters" description="Kandidat filter lanjutan read-only. Ini bukan rule baru; hanya ranking kondisi yang mungkin mengurangi SL.">
            <ImprovementTable rows={data?.improvement_candidates || []} />
          </SectionCard>

          <section className="grid gap-4 xl:grid-cols-2">
            <SectionCard title="BTC / ETH regime split" description="Cek apakah MID_SHORT gagal saat BTC/ETH sedang bullish.">
              <BucketTable rows={data?.regime_rows || []} showDimension />
            </SectionCard>
            <SectionCard title="WIB session split" description="Cek apakah hasil jelek terkonsentrasi di jam tertentu.">
              <BucketTable rows={data?.session_rows || []} />
            </SectionCard>
          </section>

          <SectionCard title="Evidence TP vs SL" description="Median evidence pada TP dibanding SL khusus scope halaman ini.">
            <EvidenceTable rows={(data?.evidence_tp_vs_sl || []).slice(0, 12)} />
          </SectionCard>

          <section className="grid gap-4 xl:grid-cols-2">
            <SectionCard title="Latest SL samples" description="Klik symbol untuk buka detail signal.">
              <SignalTable items={data?.latest_sl_signals || []} />
            </SectionCard>
            <SectionCard title="Latest TP samples" description="Pembanding signal yang target duluan.">
              <SignalTable items={data?.latest_tp_signals || []} />
            </SectionCard>
          </section>

          <SectionCard title="Symbol concentration" description="Cari apakah SL/TP terlalu terkonsentrasi di token tertentu.">
            <BucketTable rows={(data?.symbol_rows || []).slice(0, 30)} />
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
            <th>Winrate</th>
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
              <td>{row.sl_share_pct == null ? "-" : `${fmtNumber(row.sl_share_pct)}%`}</td>
              <td>{row.winrate_pct == null ? "-" : `${fmtNumber(row.winrate_pct)}%`}</td>
              <td>{fmtSigned(row.realistic_total_r_closed)}R</td>
              <td>{fmtSigned(row.realistic_avg_r_closed)}R</td>
              <td className="max-w-md text-slate-600">{row.read}</td>
            </tr>
          ))}
          {!rows.length && (
            <tr>
              <td colSpan={showDimension ? 9 : 8} className="py-8 text-center text-sm text-slate-500">No rows</td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

function ImprovementTable({ rows }: { rows: MidShortFailureImprovementCandidate[] }) {
  return (
    <div className="table-wrap">
      <table className="ops-table">
        <thead>
          <tr>
            <th>Filter</th>
            <th>Family</th>
            <th>Sample</th>
            <th>TP / SL</th>
            <th>Retain</th>
            <th>Realistic R</th>
            <th>Avg delta</th>
            <th>SL delta</th>
            <th>Read</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.filter_id}>
              <td className="max-w-lg">
                <div className="font-semibold">{row.label}</div>
                <div className="text-xs text-slate-500">{row.expression}</div>
              </td>
              <td>{labelFor(row.family)}</td>
              <td>{row.sample_count}</td>
              <td>{row.tp_count} / {row.sl_count}</td>
              <td>{row.sample_retention_pct == null ? "-" : `${fmtNumber(row.sample_retention_pct)}%`}</td>
              <td>{fmtSigned(row.realistic_total_r_closed)}R</td>
              <td>{fmtSigned(row.realistic_avg_r_delta_vs_baseline)}R</td>
              <td>{row.sl_share_delta_vs_baseline == null ? "-" : `${fmtSigned(row.sl_share_delta_vs_baseline)}%`}</td>
              <td><StatusBadge value={row.read} /></td>
            </tr>
          ))}
          {!rows.length && (
            <tr>
              <td colSpan={9} className="py-8 text-center text-sm text-slate-500">No candidates</td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

function MfeMaeTable({ rows }: { rows: MidShortFailureAnatomyResponse["mfe_mae_summary"] }) {
  return (
    <div className="table-wrap">
      <table className="ops-table">
        <thead>
          <tr>
            <th>Status</th>
            <th>Sample</th>
            <th>Median MFE</th>
            <th>Median MAE</th>
            <th>MFE before hit</th>
            <th>MAE before hit</th>
            <th>MFE ≥ 0.5R</th>
            <th>MFE ≥ 1R</th>
          </tr>
        </thead>
        <tbody>
          {Object.entries(rows).map(([status, row]) => (
            <tr key={status}>
              <td><StatusBadge value={status} /></td>
              <td>{row.sample_count}</td>
              <td>{fmtSigned(row.median_mfe_r)}R</td>
              <td>{fmtSigned(row.median_mae_r)}R</td>
              <td>{fmtSigned(row.median_mfe_before_first_hit_r)}R</td>
              <td>{fmtSigned(row.median_mae_before_first_hit_r)}R</td>
              <td>{row.mfe_ge_0_5_count}</td>
              <td>{row.mfe_ge_1_0_count}</td>
            </tr>
          ))}
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
            </tr>
          ))}
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
            <th>Path</th>
            <th>Result</th>
            <th>Realistic R</th>
            <th>MFE / MAE</th>
            <th>Entry / SL / TP</th>
            <th>Detail</th>
          </tr>
        </thead>
        <tbody>
          {items.slice(0, 18).map((raw) => {
            const item = raw as AnatomySignalItem;
            return (
              <tr key={raw.signal_id}>
                <td>{raw.signal_time_wib || fmtTime(raw.signal_timestamp)}</td>
                <td className="font-semibold text-blue-700">{raw.symbol}</td>
                <td><StatusBadge value={String(item.path_type || "-")} /></td>
                <td><StatusBadge value={raw.result_status} /></td>
                <td>{fmtSigned(raw.realistic_realized_r ?? raw.realistic_unrealized_r)}R</td>
                <td>{fmtSigned(raw.mfe_r)} / {fmtSigned(raw.mae_r)}</td>
                <td className="text-xs">
                  <div>Entry {fmtPrice(raw.entry)}</div>
                  <div>SL {fmtPrice(raw.stop_loss)}</div>
                  <div>TP {fmtPrice(raw.take_profit)}</div>
                </td>
                <td><Link className="font-semibold text-blue-700 hover:underline" href={`/signals/${raw.signal_id}`}>Open</Link></td>
              </tr>
            );
          })}
          {!items.length && (
            <tr>
              <td colSpan={8} className="py-8 text-center text-sm text-slate-500">No rows</td>
            </tr>
          )}
        </tbody>
      </table>
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
  return `${num > 0 ? "+" : ""}${fmtNumber(num)}`;
}
