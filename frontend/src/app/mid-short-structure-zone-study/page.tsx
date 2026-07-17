import Link from "next/link";
import type { ReactNode } from "react";

import { MetricCard } from "@/components/MetricCard";
import { PageHeader } from "@/components/PageHeader";
import { SectionCard } from "@/components/SectionCard";
import { SignalPriceChart } from "@/components/SignalPriceChart";
import { StatusBadge } from "@/components/StatusBadge";
import {
  MidShortStructureCase,
  MidShortStructureFixedPerf,
  MidShortStructureGateRow,
  MidShortStructureStateRow,
  MidShortStructureZoneResponse,
  fetchJson,
  fmtPrice,
  fmtTime
} from "@/lib/api";
import { labelFor } from "@/lib/labels";

type SearchParams = Promise<Record<string, string | string[] | undefined>>;

export const dynamic = "force-dynamic";

export default async function MidShortStructureZoneStudyPage({ searchParams }: { searchParams: SearchParams }) {
  const params = await searchParams;
  const includeWatchOnly = firstParam(params.include_watch_only) === "true";
  const positionLock = firstParam(params.position_lock) !== "false";
  const minSample = normalizeNumber(firstParam(params.min_sample), 20, 1, 100);
  const limit = normalizeNumber(firstParam(params.limit), 50, 10, 150);
  const signalId = firstParam(params.signal_id);
  const query = new URLSearchParams({
    include_watch_only: String(includeWatchOnly),
    position_lock: String(positionLock),
    min_sample: String(minSample),
    limit: String(limit)
  });
  if (signalId) query.set("signal_id", signalId);

  let data: MidShortStructureZoneResponse | null = null;
  let error: string | null = null;
  try {
    data = await fetchJson<MidShortStructureZoneResponse>(
      `/api/signal-candidates/mid-short-1h-structure-zone-study?${query.toString()}`
    );
  } catch (err) {
    error = err instanceof Error ? err.message : "Structure Zone Study API failed";
  }

  const summary = data?.summary;
  const selected = data?.selected_case;
  const selectedConfig = data?.config_rows.find((row) => row.config_id === summary?.train_selected_config_id);

  return (
    <div className="space-y-5">
      <PageHeader
        title="MID_SHORT 1h Structure Zone Study"
        badge="LAB-56 - READ-ONLY SHADOW"
        subtitle="Menguji apakah support/resistance 1h yang disentuh berulang dapat menjelaskan TP dan SL MID_SHORT. Zona hanya memakai candle futures yang sudah closed sebelum signal; 4h hanya confluence, bukan hard gate."
        updatedAt={fmtTime(data?.generated_at_utc)}
      />

      <div className="flex flex-wrap gap-2 text-sm">
        <Link className="rounded border border-line bg-white px-3 py-2 font-semibold hover:bg-field" href="/mid-short-failure-anatomy">Failure Anatomy</Link>
        <Link className="rounded border border-line bg-white px-3 py-2 font-semibold hover:bg-field" href="/mid-short-entry-confirmation-study">Entry Confirmation</Link>
        <Link className="rounded border border-line bg-white px-3 py-2 font-semibold hover:bg-field" href="/signal-quality-lab?stage=MID_SHORT&timeframe=1h">Quality Lab</Link>
      </div>

      {error ? (
        <div className="rounded border border-stale bg-red-50 p-4 text-sm text-stale">{error}</div>
      ) : (
        <>
          <section className="grid gap-3 md:grid-cols-2 xl:grid-cols-6">
            <MetricCard label="Fixed cohort" value={summary?.source_count ?? 0} helper={`${summary?.train_count ?? 0} train / ${summary?.validation_count ?? 0} validation`} />
            <MetricCard label="Zone available" value={summary?.zone_available_count ?? 0} helper={`Primary ${summary?.primary_config_id || "-"}`} tone="good" />
            <MetricCard label="4h context" value={summary?.four_hour_context_available_count ?? 0} helper="Optional, bukan hard gate" />
            <MetricCard label="Train choice" value={shortConfig(summary?.train_selected_config_id)} helper="Dipilih dari train saja" tone="warn" />
            <MetricCard label="Validation delta" value={`${fmtSigned(summary?.train_selected_validation_avg_r_delta)}R`} helper={`${summary?.train_selected_validation_sl_avoided ?? 0} SL avoided / ${summary?.train_selected_validation_tp_lost ?? 0} TP lost`} tone={Number(summary?.train_selected_validation_avg_r_delta || 0) > 0 ? "good" : "bad"} />
            <MetricCard label="LAB-56 verdict" value={labelFor(summary?.verdict || "UNAVAILABLE")} helper="Rule live tetap frozen" tone="warn" />
          </section>

          <SectionCard title="Study controls" description="Kontrol hanya mengubah scope laporan dan chart terpilih. Tidak mengubah scanner atau Signal Factory.">
            <form className="grid gap-3 p-4 text-sm md:grid-cols-2 xl:grid-cols-5">
              <NumberInput label="Min sample" name="min_sample" value={minSample} min={1} max={100} />
              <NumberInput label="Ledger rows" name="limit" value={limit} min={10} max={150} />
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

          <SectionCard title="Executive read" description="Keputusan hanya berasal dari train-selected configuration yang kemudian dibaca pada chronological validation.">
            <div className="grid gap-4 p-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,2fr)]">
              <div className="space-y-2">
                <StatusBadge value={summary?.verdict || "UNAVAILABLE"} />
                <p className="text-sm leading-6 text-slate-700">{summary?.recommended_action || "Belum ada hasil."}</p>
              </div>
              <div className="grid gap-2 text-sm sm:grid-cols-3">
                <Fact label="Primary display config" value={summary?.primary_config_id || "-"} />
                <Fact label="Train-selected config" value={summary?.train_selected_config_id || "-"} />
                <Fact label="Validation cutoff" value={fmtTime(summary?.validation_cutoff_utc)} />
              </div>
            </div>
          </SectionCard>

          <SectionCard title="Parameter sensitivity" description="Tiga konfigurasi ditetapkan sebelum membaca hasil. Ranking memakai train delta; kolom validation tidak dipakai untuk memilih.">
            <div className="grid gap-3 p-4 lg:grid-cols-3">
              {(data?.config_rows || []).map((row) => (
                <div className={`border p-4 ${row.config_id === summary?.train_selected_config_id ? "border-blue-500 bg-blue-50/50" : "border-line bg-white"}`} key={row.config_id}>
                  <div className="mb-3 flex items-start justify-between gap-2">
                    <div>
                      <h3 className="font-semibold text-ink">{row.label}</h3>
                      <p className="text-xs text-slate-500">{row.lookback_hours}h | pivot {row.pivot_span} | ±{fmtFixed(row.zone_half_width_atr, 2)} ATR | {row.min_touches} touches</p>
                    </div>
                    {row.config_id === summary?.train_selected_config_id ? <StatusBadge value="TRAIN_SELECTED" /> : null}
                  </div>
                  <div className="grid grid-cols-2 gap-2 text-sm">
                    <Fact label="Zone available" value={`${row.zone_available_count}/${summary?.source_count ?? 0}`} />
                    <Fact label="Train avg delta" value={`${fmtSigned(row.not_conflicted_gate.train.fixed_avg_r_delta_vs_baseline)}R`} />
                    <Fact label="Validation avg delta" value={`${fmtSigned(row.not_conflicted_gate.validation.fixed_avg_r_delta_vs_baseline)}R`} />
                    <Fact label="Validation tradeoff" value={`${row.not_conflicted_gate.validation.sl_avoided_count} SL saved / ${row.not_conflicted_gate.validation.tp_lost_count} TP lost`} />
                  </div>
                </div>
              ))}
            </div>
          </SectionCard>

          <SectionCard title="Fixed-cohort gate tradeoff" description="Signal yang tidak lolos tetap dihitung 0R. Ini mencegah hasil terlihat bagus hanya karena loss dihapus dari tabel.">
            <GateTable rows={data?.gate_rows || []} />
          </SectionCard>

          <div className="grid gap-5 xl:grid-cols-2">
            <SectionCard title="1h structure states" description="Actual TP/SL dan realistic R per posisi harga terhadap zona 1h.">
              <StateTable rows={data?.state_rows || []} />
            </SectionCard>
            <SectionCard title="4h context comparison" description="4h hanya pembanding confluence. Missing 4h tidak menggagalkan signal 1h.">
              <StateTable rows={data?.four_hour_confluence_rows || []} />
            </SectionCard>
          </div>

          <SectionCard
            title={selected ? `${selected.symbol} 1h zone evidence` : "1h zone evidence"}
            description={selected ? `${selected.signal_time_wib || fmtTime(selected.signal_timestamp)} | ${labelFor(selected.structure_state)} | ${selected.structure_reason}` : "Pilih signal dari ledger untuk melihat zona yang tersedia saat signal."}
          >
            {data?.selected_chart ? <SignalPriceChart chartData={data.selected_chart} /> : <Empty text="Chart 1h belum tersedia untuk cohort ini." />}
          </SectionCard>

          <SectionCard title="Full signal ledger" description="Klik View zones untuk mengganti chart di atas. Semua angka menggunakan entry futures dan waktu WIB.">
            <CaseLedger rows={data?.case_rows || []} query={query} selectedSignalId={selected?.signal_id} />
          </SectionCard>

          <SectionCard title="Method and guardrails" description="Apa yang boleh dan tidak boleh disimpulkan dari LAB-56.">
            <div className="grid gap-4 p-4 text-sm leading-6 lg:grid-cols-2">
              <ul className="list-disc space-y-1 pl-5 text-slate-700">
                {(data?.limitations || []).map((item) => <li key={item}>{item}</li>)}
              </ul>
              <ul className="list-disc space-y-1 pl-5 text-slate-700">
                {(data?.guardrails || []).map((item) => <li key={item}>{item}</li>)}
              </ul>
            </div>
          </SectionCard>
        </>
      )}
    </div>
  );
}

function GateTable({ rows }: { rows: MidShortStructureGateRow[] }) {
  return (
    <table className="w-full table-fixed text-left text-xs">
      <thead className="bg-field text-slate-600">
        <tr><Th>Gate</Th><Th>Validation entered</Th><Th>TP kept/lost</Th><Th>SL kept/avoided</Th><Th>Fixed R</Th><Th>Avg delta</Th><Th>Verdict</Th></tr>
      </thead>
      <tbody>
        {rows.map((row) => <GateRow key={row.gate_id} row={row} />)}
      </tbody>
    </table>
  );
}

function GateRow({ row }: { row: MidShortStructureGateRow }) {
  const value = row.validation;
  return (
    <tr className="border-t border-line align-top">
      <Td><strong>{row.label}</strong><span className="mt-1 block text-[0.68rem] text-slate-500">{row.allowed_states.map(labelFor).join(", ")}</span></Td>
      <Td>{value.entered_closed_count}/{value.source_closed_count}<span className="block text-slate-500">{fmtFixed(value.retention_pct, 1)}% rows</span></Td>
      <Td>{value.tp_retained_count} / {value.tp_lost_count}</Td>
      <Td>{value.sl_retained_count} / {value.sl_avoided_count}</Td>
      <Td>{fmtSigned(value.fixed_total_realistic_r)}R<span className="block text-slate-500">DD {fmtSigned(value.fixed_max_drawdown_r)}R</span></Td>
      <Td>{fmtSigned(value.fixed_avg_r_delta_vs_baseline)}R</Td>
      <Td><StatusBadge value={row.verdict} /></Td>
    </tr>
  );
}

function StateTable({ rows }: { rows: MidShortStructureStateRow[] }) {
  const activeRows = rows.filter((row) => Number(row.all.sample_count || 0) > 0);
  if (!activeRows.length) return <Empty text="Belum ada state dengan sample." />;
  return (
    <table className="w-full table-fixed text-left text-xs">
      <thead className="bg-field text-slate-600"><tr><Th>State</Th><Th>All TP/SL</Th><Th>Validation</Th><Th>Validation R</Th></tr></thead>
      <tbody>
        {activeRows.map((row) => (
          <tr className="border-t border-line" key={row.bucket}>
            <Td><StatusBadge value={row.bucket} /></Td>
            <Td>{row.all.tp_count}/{row.all.sl_count}<span className="block text-slate-500">n {row.all.sample_count}</span></Td>
            <Td>{row.validation.tp_count}/{row.validation.sl_count}<span className="block text-slate-500">n {row.validation.sample_count}</span></Td>
            <Td>{fmtSigned(row.validation.realistic_total_r_closed)}R<span className="block text-slate-500">avg {fmtSigned(row.validation.realistic_avg_r_closed)}R</span></Td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function CaseLedger({ rows, query, selectedSignalId }: { rows: MidShortStructureCase[]; query: URLSearchParams; selectedSignalId?: string }) {
  if (!rows.length) return <Empty text="Belum ada signal dalam scope." />;
  return (
    <table className="w-full table-fixed text-left text-xs">
      <thead className="bg-field text-slate-600"><tr><Th>Signal WIB</Th><Th>Symbol</Th><Th>State</Th><Th>Entry / zones</Th><Th>4h context</Th><Th>Result</Th><Th>Evidence</Th></tr></thead>
      <tbody>
        {rows.map((row) => {
          const next = new URLSearchParams(query);
          next.set("signal_id", row.signal_id);
          return (
            <tr className={`border-t border-line align-top ${row.signal_id === selectedSignalId ? "bg-blue-50/50" : ""}`} key={row.signal_id}>
              <Td>{row.signal_time_wib || fmtTime(row.signal_timestamp)}</Td>
              <Td><strong>{row.symbol}</strong><Link className="mt-2 block font-semibold text-blue-700 hover:underline" href={`/mid-short-structure-zone-study?${next.toString()}`}>View zones</Link></Td>
              <Td><StatusBadge value={row.structure_state} /><span className="mt-1 block text-slate-500">{row.structure_reason}</span></Td>
              <Td>Entry {fmtPrice(row.entry)}<span className="block text-slate-500">S {fmtPrice(row.nearest_support?.center)} ({fmtAtrDistance(row.nearest_support_distance_atr)})</span><span className="block text-slate-500">R {fmtPrice(row.nearest_resistance?.center)} ({fmtAtrDistance(row.nearest_resistance_distance_atr)})</span></Td>
              <Td><StatusBadge value={row.four_hour_confluence_status} /><span className="mt-1 block text-slate-500">{row.four_hour_confluence_reason}</span></Td>
              <Td><StatusBadge value={row.result_status} /><span className="mt-1 block font-semibold">{fmtSigned(row.realistic_realized_r)}R</span></Td>
              <Td>{row.zone_count_1h} zones<span className="block text-slate-500">ATR {fmtPrice(row.atr_1h_at_signal)}</span><span className="block text-slate-500">Taker sell {fmtPercentRatio(row.taker_sell_ratio)}</span><Link className="mt-2 block font-semibold text-blue-700 hover:underline" href={row.detail_href}>Signal detail</Link></Td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function NumberInput({ label, name, value, min, max }: { label: string; name: string; value: number; min: number; max: number }) {
  return <label className="grid gap-1"><span className="font-semibold text-slate-600">{label}</span><input className="rounded border border-line px-3 py-2" min={min} max={max} name={name} type="number" defaultValue={value} /></label>;
}

function Fact({ label, value }: { label: string; value: string | number }) {
  return <div className="border border-line bg-field/30 p-3"><span className="block text-[0.65rem] font-semibold uppercase text-slate-500">{label}</span><strong className="mt-1 block break-words text-ink">{value}</strong></div>;
}

function Th({ children }: { children: ReactNode }) { return <th className="px-3 py-2 font-semibold">{children}</th>; }
function Td({ children }: { children: ReactNode }) { return <td className="break-words px-3 py-3">{children}</td>; }
function Empty({ text }: { text: string }) { return <div className="p-6 text-center text-sm text-slate-500">{text}</div>; }
function fmtSigned(value: string | number | null | undefined): string { if (value === null || value === undefined || value === "") return "-"; const number = Number(value); return Number.isFinite(number) ? `${number >= 0 ? "+" : ""}${fmtFixed(number, 3)}` : "-"; }
function fmtPercentRatio(value: string | number | null | undefined): string { if (value === null || value === undefined || value === "") return "-"; const number = Number(value); return Number.isFinite(number) ? `${fmtFixed(number * 100, 1)}%` : "-"; }
function fmtFixed(value: string | number | null | undefined, digits: number): string { if (value === null || value === undefined || value === "") return "-"; const number = Number(value); return Number.isFinite(number) ? number.toFixed(digits).replace(/\.0+$/, "") : "-"; }
function fmtAtrDistance(value: string | number | null | undefined): string { const formatted = fmtFixed(value, 2); return formatted === "-" ? formatted : `${formatted} ATR`; }
function shortConfig(value?: string | null): string { if (!value) return "-"; return value.replace("_168H_030ATR", "").replace("_96H_020ATR", "").replace("_240H_040ATR", ""); }
function firstParam(value: string | string[] | undefined): string | undefined { return Array.isArray(value) ? value[0] : value; }
function normalizeNumber(value: string | undefined, fallback: number, min: number, max: number): number { const parsed = Number(value); return Number.isFinite(parsed) ? Math.max(min, Math.min(max, Math.trunc(parsed))) : fallback; }
