import Link from "next/link";

import { MetricCard } from "@/components/MetricCard";
import { PageHeader } from "@/components/PageHeader";
import { SectionCard } from "@/components/SectionCard";
import { StatusBadge } from "@/components/StatusBadge";
import {
  LongDefinitionFamilyRow,
  LongDefinitionLabResponse,
  LongDefinitionSignalRow,
  LongHistoricalBacktestResponse,
  fetchJson,
  fmtNumber,
  fmtTime
} from "@/lib/api";

type SearchParams = Promise<Record<string, string | string[] | undefined>>;

export const dynamic = "force-dynamic";

export default async function LongDefinitionLabPage({ searchParams }: { searchParams: SearchParams }) {
  const params = await searchParams;
  const limit = normalizeNumber(firstParam(params.limit), 80, 20, 200);
  let payload: LongDefinitionLabResponse | null = null;
  let historical: LongHistoricalBacktestResponse | null = null;
  let error: string | null = null;
  let historicalError: string | null = null;

  try {
    payload = await fetchJson<LongDefinitionLabResponse>(
      `/api/signal-candidates/long-definition-lab?limit=${limit}`,
      { revalidateSeconds: 120 }
    );
  } catch (reason) {
    error = reason instanceof Error ? reason.message : "LONG definition lab API failed";
  }
  try {
    historical = await fetchJson<LongHistoricalBacktestResponse>(
      `/api/signal-candidates/long-historical-backtest-1h?limit=${limit}`,
      { revalidateSeconds: 120 }
    );
  } catch (reason) {
    historicalError = reason instanceof Error ? reason.message : "LONG historical backtest API failed";
  }

  const control = payload?.legacy_control;
  const summary = payload?.summary;
  const best = summary?.best_candidate_family;
  const worst = summary?.worst_reject_bucket;
  const historicalBest = historical?.summary.best_candidate_family;
  const historicalWorst = historical?.summary.worst_rejection_bucket;

  return (
    <div className="space-y-5">
      <PageHeader
        title="Long Definition Lab V2"
        badge="READ-ONLY - RULE LIVE BELUM DIUBAH"
        subtitle="Lab ini memecah long menjadi keluarga breakout, retest, squeeze, late chase, crowded, dan unclassified. Bagian atas adalah backtest historis dari semua candle DB; bagian bawah audit signal long lama sebagai pembanding."
        updatedAt={fmtTime(historical?.generated_at_utc || payload?.generated_at_utc)}
      />

      <div className="flex flex-wrap gap-2 text-sm">
        <Link className="rounded-md border border-line bg-white px-3 py-2 font-semibold hover:bg-field" href="/mid-long-research-study">
          Open old MID_LONG archive
        </Link>
        <Link className="rounded-md border border-line bg-white px-3 py-2 font-semibold hover:bg-field" href="/signal-performance?stage=MID_LONG&timeframe=1h&position_lock=true">
          Open closed long history
        </Link>
        <Link className="rounded-md border border-line bg-white px-3 py-2 font-semibold hover:bg-field" href="/scanner?tier=SIGNAL_CANDIDATE">
          Open live radar
        </Link>
      </div>

      {historicalError ? (
        <div className="rounded-md border border-warmup bg-yellow-50 p-4 text-sm text-warmup">
          Historical backtest belum tersedia: {historicalError}. Jalankan runner `run_long_historical_backtest_lab.py` untuk membuat artifact dari DB produksi.
        </div>
      ) : historical ? (
        <>
          <SectionCard
            title="Historical backtest dari semua candle 1h"
            description="Ini yang wajib untuk rule baru: MarketLab scan semua futures 1h yang tersedia di DB, bukan cuma signal lama yang sudah pernah kelog."
          >
            <div className="grid gap-3 p-4 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-8">
              <MetricCard label="Symbols" value={historical.coverage.symbol_count} helper={`${historical.coverage.active_symbol_count} active universe`} />
              <MetricCard label="1h candles" value={historical.coverage.futures_1h_candle_count} helper="AGG_READY futures" />
              <MetricCard label="15m forward" value={historical.coverage.futures_15m_candle_count} helper="Untuk cek TP/SL path" />
              <MetricCard label="Raw long" value={historical.coverage.raw_long_candidate_count_before_lock} helper="Sebelum position lock" tone="info" />
              <MetricCard label="Evaluated" value={historical.coverage.events_evaluated_after_lock} helper="Setelah position lock" tone="info" />
              <MetricCard label="Best family" value={historicalBest?.family_label || "-"} helper={historicalBest ? `${fmtSigned(historicalBest.realistic_total_r_closed)}R` : "Belum ada"} tone={toneFor(historicalBest?.realistic_total_r_closed)} />
              <MetricCard label="Worst bucket" value={historicalWorst?.family_label || "-"} helper={historicalWorst ? `${fmtSigned(historicalWorst.realistic_total_r_closed)}R` : "Belum ada"} tone="warn" />
              <MetricCard label="Latest 1h" value={historical.coverage.latest_futures_1h_close_time_wib || "-"} helper={historical.filters.since_days ? `Scope ${historical.filters.since_days} hari` : "Full DB scope"} />
            </div>
          </SectionCard>

          <SectionCard
            title="Historical family performance"
            description="Hasil keluarga long baru jika entry dibuat ulang dari semua candle DB. Ini masih read-only dan belum mengubah Signal Factory."
          >
            <div className="overflow-x-auto">
              <table className="min-w-full text-sm">
                <thead>
                  <tr className="bg-slate-100 text-left text-xs uppercase text-slate-500">
                    <th className="px-4 py-3">Family</th>
                    <th className="px-4 py-3">Role</th>
                    <th className="px-4 py-3">Sample</th>
                    <th className="px-4 py-3">TP / SL / Timeout</th>
                    <th className="px-4 py-3">Winrate</th>
                    <th className="px-4 py-3">Realistic R</th>
                    <th className="px-4 py-3">Avg / Median</th>
                    <th className="px-4 py-3">Top symbol</th>
                    <th className="px-4 py-3">Research status</th>
                  </tr>
                </thead>
                <tbody>
                  {historical.family_rows.map((row) => <FamilyRow key={`hist-${row.family_id}`} row={row} />)}
                </tbody>
              </table>
            </div>
          </SectionCard>

          <SectionCard
            title="Latest historical replay entries"
            description="Entry ini dibuat ulang dari candle futures 1h. Entry, SL, TP, dan R tetap futures reference; spot/rich hanya evidence."
          >
            <div className="overflow-x-auto">
              <table className="min-w-full text-sm">
                <thead>
                  <tr className="bg-slate-100 text-left text-xs uppercase text-slate-500">
                    <th className="px-4 py-3">Time WIB</th>
                    <th className="px-4 py-3">Symbol</th>
                    <th className="px-4 py-3">Source</th>
                    <th className="px-4 py-3">Family</th>
                    <th className="px-4 py-3">Result</th>
                    <th className="px-4 py-3">R</th>
                    <th className="px-4 py-3">Key evidence</th>
                    <th className="px-4 py-3">Reason</th>
                  </tr>
                </thead>
                <tbody>
                  {historical.latest_items.map((row) => <SignalRow key={`hist-${row.signal_id || row.symbol}-${row.signal_timestamp}`} row={row} />)}
                </tbody>
              </table>
            </div>
          </SectionCard>
        </>
      ) : null}

      {error ? (
        <div className="rounded-md border border-stale bg-red-50 p-4 text-sm text-stale">{error}</div>
      ) : payload && control && summary ? (
        <>
          <SectionCard
            title="Logged signal audit pembanding"
            description="Bagian ini hanya membaca long signal yang dulu sudah tercatat. Gunanya sebagai kontrol, bukan backtest murni."
          >
            <div className="grid gap-3 p-4 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-7">
              <MetricCard label="Raw long 1h" value={payload.snapshot_coverage.long_1h_rows} helper={`${payload.snapshot_coverage.mid_long_rows} MID_LONG / ${payload.snapshot_coverage.early_long_rows} EARLY_LONG`} />
              <MetricCard label="Legacy realistic R" value={`${fmtSigned(control.realistic_total_r_closed)}R`} helper={`${control.tp_count} TP / ${control.sl_count} SL`} tone={toneFor(control.realistic_total_r_closed)} />
              <MetricCard label="Legacy avg R" value={`${fmtSigned(control.realistic_avg_r_closed)}R`} helper="Kontrol lama" tone={toneFor(control.realistic_avg_r_closed)} />
              <MetricCard label="Best family" value={best?.family_label || "-"} helper={best ? `${fmtSigned(best.realistic_total_r_closed)}R | ${best.closed_count} rows` : "Belum ada"} tone={toneFor(best?.realistic_total_r_closed)} />
              <MetricCard label="Worst bucket" value={worst?.family_label || "-"} helper={worst ? `${fmtSigned(worst.realistic_total_r_closed)}R | ${worst.closed_count} rows` : "Belum ada"} tone="warn" />
              <MetricCard label="Candidates" value={summary.candidate_family_count} helper="Breakout/retest/squeeze" tone="info" />
              <MetricCard label="Reject buckets" value={summary.rejection_bucket_count} helper="Late chase/crowded" tone="warn" />
            </div>
          </SectionCard>

          <SectionCard
            title="Apa fungsi lab ini?"
            description="Halaman ini menyerang definisi LONG lama. Kita tidak lagi bertanya apakah MID_LONG lama bagus, tapi memecahnya menjadi keluarga yang bisa diuji satu per satu."
          >
            <div className="grid gap-3 p-4 md:grid-cols-3">
              <Info label="Read" value={humanFlag(summary.read)} helper={summary.next_action} />
              <Info label="Rule live" value={payload.production_rule_change ? "Changed" : "Tidak berubah"} helper="Scanner dan Signal Factory tetap memakai rule yang sama." />
              <Info label="Data source" value={payload.snapshot?.filename || "performance_closed_1h.json"} helper="Artifact 1h closed, bukan query DB berat." />
            </div>
          </SectionCard>

          <SectionCard
            title="Family definition"
            description="Ini definisi proxy read-only. TP/SL/R hanya dipakai setelah klasifikasi untuk membaca performa, bukan sebagai input klasifikasi."
          >
            <div className="grid gap-3 p-4 md:grid-cols-2 xl:grid-cols-3">
              {payload.family_definitions.map((item) => (
                <div key={item.family_id} className="rounded-md border border-line bg-field p-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <StatusBadge value={item.family_id} />
                    <StatusBadge value={item.family_role} />
                  </div>
                  <div className="mt-2 font-bold text-ink">{item.family_label}</div>
                  <p className="mt-1 text-sm leading-5 text-slate-600">{item.description}</p>
                </div>
              ))}
            </div>
          </SectionCard>

          <SectionCard
            title="Family performance"
            description="Bandingkan keluarga baru terhadap legacy long control. Ini belum promosi rule, hanya kandidat penelitian."
          >
            <div className="overflow-x-auto">
              <table className="min-w-full text-sm">
                <thead>
                  <tr className="bg-slate-100 text-left text-xs uppercase text-slate-500">
                    <th className="px-4 py-3">Family</th>
                    <th className="px-4 py-3">Role</th>
                    <th className="px-4 py-3">Sample</th>
                    <th className="px-4 py-3">TP / SL / Timeout</th>
                    <th className="px-4 py-3">Winrate</th>
                    <th className="px-4 py-3">Realistic R</th>
                    <th className="px-4 py-3">Avg / Median</th>
                    <th className="px-4 py-3">Top symbol</th>
                    <th className="px-4 py-3">Research status</th>
                  </tr>
                </thead>
                <tbody>
                  {payload.family_rows.map((row) => <FamilyRow key={row.family_id} row={row} />)}
                </tbody>
              </table>
            </div>
          </SectionCard>

          <SectionCard
            title="Latest classified long samples"
            description="Sample terbaru dari long 1h yang sudah dipetakan ke keluarga baru. Gunakan ini untuk cek alasan angka, bukan sebagai entry page."
          >
            <div className="overflow-x-auto">
              <table className="min-w-full text-sm">
                <thead>
                  <tr className="bg-slate-100 text-left text-xs uppercase text-slate-500">
                    <th className="px-4 py-3">Time WIB</th>
                    <th className="px-4 py-3">Symbol</th>
                    <th className="px-4 py-3">Source</th>
                    <th className="px-4 py-3">Family</th>
                    <th className="px-4 py-3">Result</th>
                    <th className="px-4 py-3">R</th>
                    <th className="px-4 py-3">Key evidence</th>
                    <th className="px-4 py-3">Reason</th>
                  </tr>
                </thead>
                <tbody>
                  {payload.latest_items.map((row) => <SignalRow key={`${row.signal_id || row.symbol}-${row.signal_timestamp}`} row={row} />)}
                </tbody>
              </table>
            </div>
          </SectionCard>

          <SectionCard title="Guardrails" description="Batas aman update ini.">
            <div className="grid gap-2 p-4 text-sm text-slate-700 md:grid-cols-2">
              {payload.guardrails.map((item) => (
                <div key={item} className="rounded-md border border-line bg-field p-3">{item}</div>
              ))}
            </div>
          </SectionCard>
        </>
      ) : (
        <div className="rounded-md border border-line bg-white p-4 text-sm text-slate-600">Snapshot belum tersedia.</div>
      )}
    </div>
  );
}

function FamilyRow({ row }: { row: LongDefinitionFamilyRow }) {
  return (
    <tr className="border-t border-line align-top">
      <td className="px-4 py-3">
        <div className="font-bold text-ink">{row.family_label}</div>
        <div className="mt-1 max-w-lg text-xs leading-5 text-slate-500">{row.description}</div>
      </td>
      <td className="px-4 py-3"><StatusBadge value={row.family_role} /></td>
      <td className="px-4 py-3">{row.closed_count}</td>
      <td className="px-4 py-3">{row.tp_count} / {row.sl_count} / {row.timeout_count ?? 0}</td>
      <td className="px-4 py-3">{formatPct(row.winrate_pct)}</td>
      <td className={`px-4 py-3 font-bold ${toneClass(row.realistic_total_r_closed)}`}>{fmtSigned(row.realistic_total_r_closed)}R</td>
      <td className="px-4 py-3">
        <div>{fmtSigned(row.realistic_avg_r_closed)}R avg</div>
        <div className="text-xs text-slate-500">{fmtSigned(row.median_realistic_r_closed)}R median</div>
      </td>
      <td className="px-4 py-3">{row.top_symbol || "-"} <span className="text-xs text-slate-500">({formatPct(row.top_symbol_share_pct)})</span></td>
      <td className="px-4 py-3"><StatusBadge value={row.research_status} /></td>
    </tr>
  );
}

function SignalRow({ row }: { row: LongDefinitionSignalRow }) {
  return (
    <tr className="border-t border-line align-top">
      <td className="px-4 py-3">{row.signal_time_wib || fmtTime(row.signal_timestamp)}</td>
      <td className="px-4 py-3 font-bold text-blue-700">{row.symbol || "-"}</td>
      <td className="px-4 py-3">
        <StatusBadge value={row.source_stage || "-"} />
        <div className="mt-1 text-xs text-slate-500">{row.timeframe || "-"}</div>
      </td>
      <td className="px-4 py-3">
        <StatusBadge value={row.family_id} />
        <div className="mt-1 text-xs text-slate-500">{row.family_role}</div>
      </td>
      <td className="px-4 py-3"><StatusBadge value={row.result_status || "-"} /></td>
      <td className={`px-4 py-3 font-bold ${toneClass(row.realistic_realized_r)}`}>{fmtSigned(row.realistic_realized_r)}R</td>
      <td className="px-4 py-3 text-xs leading-5 text-slate-700">
        <div>Price {fmtSigned(row.price_return)}%</div>
        <div>Vol {fmtNumber(row.volume_ratio_vs_lookback)}x | Taker {formatRatioPct(row.taker_buy_ratio)}</div>
        <div>OI {fmtSigned(row.oi_change_pct)}% | z {fmtNumber(row.oi_zscore)}</div>
        <div>Room R {fmtNumber(row.room_to_next_resistance_atr)} ATR | ext {fmtNumber(row.atr_extension_normalized)}x</div>
      </td>
      <td className="px-4 py-3">
        <div className="max-w-xl text-sm leading-5 text-slate-700">{row.family_reason}</div>
        {(row.crowding_flags.length > 0 || row.anti_chase_flags.length > 0) && (
          <div className="mt-1 text-xs text-slate-500">
            {[...row.crowding_flags, ...row.anti_chase_flags].join(", ")}
          </div>
        )}
      </td>
    </tr>
  );
}

function Info({ label, value, helper }: { label: string; value: string | number; helper?: string }) {
  return (
    <div className="rounded-md border border-line bg-field p-3">
      <div className="text-xs font-semibold uppercase text-slate-500">{label}</div>
      <div className="mt-1 text-xl font-black text-ink">{value}</div>
      {helper && <div className="mt-1 text-sm leading-5 text-slate-600">{helper}</div>}
    </div>
  );
}

function firstParam(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

function normalizeNumber(value: string | undefined, fallback: number, min: number, max: number): number {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.max(min, Math.min(max, Math.floor(parsed)));
}

function fmtSigned(value?: string | number | null): string {
  if (value === null || value === undefined || value === "") return "-";
  const num = Number(value);
  if (!Number.isFinite(num)) return String(value);
  if (num > 0) return `+${fmtNumber(num)}`;
  return fmtNumber(num);
}

function formatPct(value?: string | number | null): string {
  if (value === null || value === undefined || value === "") return "-";
  return `${fmtNumber(value)}%`;
}

function formatRatioPct(value?: string | number | null): string {
  if (value === null || value === undefined || value === "") return "-";
  const num = Number(value);
  if (!Number.isFinite(num)) return String(value);
  return `${fmtNumber(num > 2 ? num : num * 100)}%`;
}

function toneFor(value?: string | number | null): "good" | "bad" | undefined {
  const num = Number(value);
  if (!Number.isFinite(num)) return undefined;
  if (num > 0) return "good";
  if (num < 0) return "bad";
  return undefined;
}

function toneClass(value?: string | number | null): string {
  const num = Number(value);
  if (!Number.isFinite(num)) return "";
  if (num > 0) return "text-ready";
  if (num < 0) return "text-stale";
  return "";
}

function humanFlag(value: string): string {
  return value
    .replace(/_/g, " ")
    .toLowerCase()
    .replace(/\b\w/g, (char) => char.toUpperCase());
}
