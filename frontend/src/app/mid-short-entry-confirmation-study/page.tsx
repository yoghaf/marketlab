import Link from "next/link";
import type { ReactNode } from "react";

import { MetricCard } from "@/components/MetricCard";
import { PageHeader } from "@/components/PageHeader";
import { SectionCard } from "@/components/SectionCard";
import { StatusBadge } from "@/components/StatusBadge";
import {
  MidShortEntryConfirmationCase,
  MidShortEntryConfirmationResponse,
  MidShortEntryConfirmationResult,
  MidShortEntryConfirmationVariant,
  fetchJson,
  fmtNumber,
  fmtPrice,
  fmtTime
} from "@/lib/api";
import { labelFor } from "@/lib/labels";

type SearchParams = Promise<Record<string, string | string[] | undefined>>;

export const dynamic = "force-dynamic";

export default async function MidShortEntryConfirmationStudyPage({ searchParams }: { searchParams: SearchParams }) {
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

  let data: MidShortEntryConfirmationResponse | null = null;
  let error: string | null = null;
  try {
    data = await fetchJson<MidShortEntryConfirmationResponse>(
      `/api/signal-candidates/mid-short-1h-entry-confirmation-study?${query.toString()}`
    );
  } catch (err) {
    error = err instanceof Error ? err.message : "Entry Confirmation Study API failed";
  }

  const summary = data?.summary;
  const control = data?.control.all;
  const best = data?.variant_rows.find((row) => row.config_id === summary?.best_validation_config_id);

  return (
    <div className="space-y-5">
      <PageHeader
        title="MID_SHORT 1h Entry Confirmation Study"
        badge="LAB-55 - READ-ONLY SHADOW"
        subtitle="Menguji apakah menunggu satu candle futures 15m closed dapat mengurangi salah arah tanpa membuang terlalu banyak TP. Entry, SL, TP, biaya, dan R dihitung ulang dari harga konfirmasi."
        updatedAt={fmtTime(data?.generated_at_utc)}
      />

      <div className="flex flex-wrap gap-2 text-sm">
        <Link className="rounded border border-line bg-white px-3 py-2 font-semibold hover:bg-field" href="/mid-short-failure-anatomy">Failure Anatomy</Link>
        <Link className="rounded border border-line bg-white px-3 py-2 font-semibold hover:bg-field" href="/mid-short-wrong-direction-deep-dive">Wrong Direction</Link>
        <Link className="rounded border border-line bg-white px-3 py-2 font-semibold hover:bg-field" href="/signal-performance?stage=MID_SHORT&timeframe=1h">Signal History</Link>
      </div>

      {error ? (
        <div className="rounded border border-stale bg-red-50 p-4 text-sm text-stale">{error}</div>
      ) : (
        <>
          <section className="grid gap-3 md:grid-cols-2 xl:grid-cols-6">
            <MetricCard label="Fixed cohort" value={summary?.source_count ?? 0} helper={`${summary?.train_count ?? 0} train / ${summary?.validation_count ?? 0} validation`} />
            <MetricCard label="Immediate reversal" value={summary?.immediate_reversal_count ?? 0} helper="15m close >= +0.05%" tone="bad" />
            <MetricCard label="Direction confirmed" value={summary?.direction_confirmed_count ?? 0} helper="15m close di bawah entry" tone="good" />
            <MetricCard label="Control realistic R" value={`${fmtSigned(control?.total_realistic_r)}R`} helper={`Avg ${fmtSigned(control?.avg_realistic_r)}R`} tone={Number(control?.total_realistic_r || 0) >= 0 ? "good" : "bad"} />
            <MetricCard label="Best validation" value={labelFor(summary?.best_validation_config_id || "UNAVAILABLE")} helper={`${fmtSigned(summary?.best_validation_total_realistic_r)}R | avg ${fmtSigned(summary?.best_validation_avg_realistic_r)}R`} tone="warn" />
            <MetricCard label="LAB-55 verdict" value={labelFor(summary?.verdict || "UNAVAILABLE")} helper="Belum mengubah rule live" tone="warn" />
          </section>

          <SectionCard title="Study controls" description="Filter ini hanya mengubah tampilan audit dan fixed cohort. Signal Factory tetap dibekukan.">
            <form className="grid gap-3 p-4 text-sm md:grid-cols-2 xl:grid-cols-5">
              <label className="grid gap-1">
                <span className="font-semibold text-slate-600">Min sample</span>
                <input className="rounded border border-line px-3 py-2" min={1} max={100} name="min_sample" type="number" defaultValue={minSample} />
              </label>
              <label className="grid gap-1">
                <span className="font-semibold text-slate-600">Ledger rows</span>
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

          <SectionCard
            title="Baseline vs 15m confirmation variants"
            description="Validation adalah 30% timestamp terbaru. Nilai R mencakup hasil TP/SL dan close-at-4h untuk NEITHER; WAITING tidak dipaksa menjadi hasil."
          >
            <VariantTable rows={data?.variant_rows || []} />
            <div className="border-t border-line p-4 text-sm text-slate-700">
              <span className="font-semibold">Current read: </span>
              {summary?.recommended_action || "Belum tersedia."}
            </div>
          </SectionCard>

          {best ? (
            <section className="grid gap-3 md:grid-cols-2 xl:grid-cols-5">
              <MetricCard label="Best retained" value={`${fmtNumber(best.validation.sample_retention_pct)}%`} helper={`${best.validation.entered_count}/${best.validation.source_count} validation`} />
              <MetricCard label="SL avoided" value={best.tradeoff_vs_control.validation.avoided_sl_count} helper="Control loss yang tidak dientry" tone="good" />
              <MetricCard label="TP lost" value={best.tradeoff_vs_control.validation.lost_tp_count} helper="Control TP yang ikut tersaring" tone="bad" />
              <MetricCard label="TP -> SL" value={best.tradeoff_vs_control.validation.tp_to_sl_count} helper="Memburuk setelah delay" tone="bad" />
              <MetricCard label="SL -> TP" value={best.tradeoff_vs_control.validation.sl_to_tp_count} helper="Membaik setelah delay" tone="good" />
            </section>
          ) : null}

          <SectionCard title="What the first 15m candle actually predicts" description="Bucket memakai return close candle konfirmasi terhadap entry signal. Ini deskriptif dan bukan threshold live baru.">
            <ConfirmationBucketTable rows={data?.confirmation_bucket_rows || []} />
          </SectionCard>

          <SectionCard
            title="Full confirmation ledger"
            description="Setiap baris menunjukkan angka signal asli dan hasil simulasi setelah konfirmasi. Candle konfirmasi tidak pernah dipakai kembali sebagai candle TP/SL."
          >
            <ConfirmationLedger rows={data?.case_rows || []} />
          </SectionCard>

          <SectionCard title="Method and limitations" description={data?.method || "Metode belum tersedia."}>
            <div className="border-b border-line p-4 text-sm text-slate-700">
              <div className="grid gap-3 md:grid-cols-2">
                {Object.entries(data?.definitions || {}).map(([key, value]) => (
                  <div key={key} className="border-l-2 border-blue-700 pl-3">
                    <div className="font-semibold">{labelFor(key)}</div>
                    <div>{value}</div>
                  </div>
                ))}
              </div>
            </div>
            <ul className="grid gap-2 p-4 text-sm text-slate-700 md:grid-cols-2">
              {(data?.limitations || []).map((item) => <li key={item} className="rounded border border-line bg-field/40 p-3">{item}</li>)}
            </ul>
          </SectionCard>
        </>
      )}
    </div>
  );
}

function VariantTable({ rows }: { rows: MidShortEntryConfirmationVariant[] }) {
  if (!rows.length) return <EmptyState text="Belum ada hasil variant." />;
  return (
    <div className="w-full">
      <table className="w-full table-fixed text-left text-xs">
        <thead className="bg-field text-slate-600">
          <tr>
            <Th className="w-[18%]">Variant</Th>
            <Th>All sample</Th>
            <Th>All outcome</Th>
            <Th>All realistic</Th>
            <Th>Validation</Th>
            <Th>Val delta</Th>
            <Th>TP/SL impact</Th>
            <Th>Verdict</Th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.config_id} className="border-t border-line align-top">
              <Td><div className="font-semibold">{row.label}</div><div className="mt-1 text-[11px] text-slate-500">{row.definition}</div></Td>
              <Td>{row.all.entered_count}/{row.all.source_count} entered<div className="text-slate-500">{row.all.filtered_count} filtered | {fmtNumber(row.all.sample_retention_pct)}%</div></Td>
              <Td>{row.all.tp_count} TP / {row.all.sl_count + row.all.both_count} SL<div className="text-slate-500">{row.all.neither_count} neither | {row.all.waiting_count} waiting</div></Td>
              <Td>{fmtSigned(row.all.total_realistic_r)}R<div className="text-slate-500">avg {fmtSigned(row.all.avg_realistic_r)} | DD {fmtSigned(row.all.max_drawdown_r)}R</div></Td>
              <Td>{row.validation.tp_count} TP / {row.validation.sl_count + row.validation.both_count} SL<div className="text-slate-500">{fmtSigned(row.validation.total_realistic_r)}R | avg {fmtSigned(row.validation.avg_realistic_r)}</div></Td>
              <Td>avg {fmtSigned(row.validation_avg_r_delta_vs_control)}R<div className="text-slate-500">total {fmtSigned(row.validation_total_r_delta_vs_control)}R | DD {fmtSigned(row.validation_drawdown_delta_vs_control)}R</div></Td>
              <Td>{row.tradeoff_vs_control.validation.avoided_sl_count} SL avoided<div className="text-slate-500">{row.tradeoff_vs_control.validation.lost_tp_count} TP lost | {row.tradeoff_vs_control.validation.tp_to_sl_count} TP to SL</div></Td>
              <Td><StatusBadge value={row.verdict} /></Td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ConfirmationBucketTable({ rows }: { rows: MidShortEntryConfirmationResponse["confirmation_bucket_rows"] }) {
  if (!rows.length) return <EmptyState text="Belum ada candle konfirmasi." />;
  return (
    <table className="w-full table-fixed text-left text-xs">
      <thead className="bg-field text-slate-600">
        <tr><Th>15m bucket</Th><Th>Sample</Th><Th>Wrong 1h</Th><Th>Logged TP/SL</Th><Th>Fixed 4h TP/SL</Th><Th>Neither</Th><Th>Avg realistic R</Th><Th>Read</Th></tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr key={row.bucket} className="border-t border-line">
            <Td><StatusBadge value={row.bucket} /></Td><Td>{row.sample_count}</Td><Td>{row.wrong_direction_1h_count}</Td>
            <Td>{row.logged_tp_count} / {row.logged_sl_count}</Td><Td>{row.control_4h_tp_count} / {row.control_4h_sl_count}</Td>
            <Td>{row.control_4h_neither_count}</Td><Td>{fmtSigned(row.control_4h_avg_realistic_r)}R</Td><Td>{labelFor(row.read)}</Td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function ConfirmationLedger({ rows }: { rows: MidShortEntryConfirmationCase[] }) {
  if (!rows.length) return <EmptyState text="Belum ada case dalam cohort." />;
  return (
    <table className="w-full table-fixed text-left text-xs">
      <thead className="bg-field text-slate-600">
        <tr><Th className="w-[12%]">Signal</Th><Th className="w-[15%]">Confirmation 15m</Th><Th>Logged</Th><Th>Immediate</Th><Th>Wait all</Th><Th>Veto up</Th><Th>Confirm below</Th><Th>Below + taker</Th></tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr key={row.signal_id} className="border-t border-line align-top">
            <Td>
              <Link className="font-semibold text-blue-700 hover:underline" href={`/signals/${encodeURIComponent(row.symbol)}?timeframe=1h&signal_id=${encodeURIComponent(row.signal_id)}`}>{row.symbol}</Link>
              <div className="text-slate-500">{row.signal_time_wib || fmtTime(row.signal_timestamp)}</div>
            </Td>
            <Td><div>{labelFor(row.confirmation_return_bucket)}</div><div>{fmtSigned(row.confirmation_return_pct)}%</div><div className="text-slate-500">Close {fmtPrice(row.confirmation_close)} | sell {fmtPctRatio(row.confirmation_taker_sell_ratio)}</div></Td>
            <Td><StatusBadge value={row.logged_result_status} /><div className="mt-1">E {fmtPrice(row.original_entry)}</div><div className="text-slate-500">SL {fmtPrice(row.original_stop)} | TP {fmtPrice(row.original_target)}</div></Td>
            <ResultCell result={row.results.CONTROL_IMMEDIATE} />
            <ResultCell result={row.results.WAIT_15M_ALWAYS} />
            <ResultCell result={row.results.VETO_UP_REVERSAL_0_05} />
            <ResultCell result={row.results.CONFIRM_CLOSE_BELOW_ENTRY} />
            <ResultCell result={row.results.CONFIRM_BELOW_ENTRY_TAKER_SELL_52} />
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function ResultCell({ result }: { result?: MidShortEntryConfirmationResult }) {
  if (!result) return <Td>-</Td>;
  return (
    <Td>
      <StatusBadge value={result.status} />
      {result.entered ? (
        <><div className="mt-1">E {fmtPrice(result.entry)}</div><div className="text-slate-500">SL {fmtPrice(result.stop)} | TP {fmtPrice(result.target)}</div><div>{fmtSigned(result.realistic_r)}R</div></>
      ) : <div className="mt-1 text-slate-500">{result.gate_reason}</div>}
    </Td>
  );
}

function Th({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <th className={`px-3 py-2 font-semibold ${className}`}>{children}</th>;
}

function Td({ children }: { children: ReactNode }) {
  return <td className="break-words px-3 py-3">{children}</td>;
}

function EmptyState({ text }: { text: string }) {
  return <div className="p-5 text-sm text-slate-500">{text}</div>;
}

function fmtSigned(value: string | number | null | undefined): string {
  if (value == null || value === "") return "-";
  const number = Number(value);
  if (!Number.isFinite(number)) return "-";
  return `${number > 0 ? "+" : ""}${fmtNumber(number)}`;
}

function fmtPctRatio(value: string | number | null | undefined): string {
  if (value == null || value === "") return "-";
  return `${fmtNumber(Number(value) * 100)}%`;
}

function firstParam(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

function normalizeNumber(value: string | undefined, fallback: number, min: number, max: number): number {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.max(min, Math.min(max, Math.trunc(parsed)));
}
