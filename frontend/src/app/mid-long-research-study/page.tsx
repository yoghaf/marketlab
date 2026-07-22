import Link from "next/link";

import { EmptyState } from "@/components/EmptyState";
import { MetricCard } from "@/components/MetricCard";
import { PageHeader } from "@/components/PageHeader";
import { SectionCard } from "@/components/SectionCard";
import { StatusBadge } from "@/components/StatusBadge";
import {
  MidLongBaselineResponse,
  SignalPerformanceItem,
  fetchJson,
  fmtNumber,
  fmtPrice,
  fmtTime
} from "@/lib/api";

type SearchParams = Promise<Record<string, string | string[] | undefined>>;

export const dynamic = "force-dynamic";

export default async function MidLongBaselinePage({ searchParams }: { searchParams: SearchParams }) {
  const params = await searchParams;
  const limit = normalizeNumber(firstParam(params.limit), 50, 10, 100);
  let baseline: MidLongBaselineResponse | null = null;
  let error: string | null = null;

  try {
    baseline = await fetchJson<MidLongBaselineResponse>(
      `/api/signal-candidates/mid-long-1h-baseline?limit=${limit}`,
      { revalidateSeconds: 120 }
    );
  } catch (reason) {
    error = reason instanceof Error ? reason.message : "MID_LONG 1h baseline API failed";
  }

  const aggregate = baseline?.aggregate;
  const coverage = baseline?.snapshot_coverage;

  return (
    <div className="space-y-5">
      <PageHeader
        title="MID_LONG 1h Baseline"
        badge="RESET - BASELINE V2 ONLY"
        subtitle="Titik awal bersih untuk menilai MID_LONG 1h. Halaman ini hanya membaca signal V2 closed yang benar-benar tercatat; seluruh eksperimen geometry dan filter lama sudah dipensiunkan."
        updatedAt={fmtTime(baseline?.generated_at_utc)}
      />

      <div className="flex flex-wrap gap-2 text-sm">
        <Link className="rounded-md border border-line bg-white px-3 py-2 font-semibold hover:bg-field" href="/signal-performance?stage=MID_LONG&timeframe=1h&position_lock=true">
          Open closed signal history
        </Link>
        <Link className="rounded-md border border-line bg-white px-3 py-2 font-semibold hover:bg-field" href="/scanner">
          Open live radar
        </Link>
      </div>

      <div className="rounded-md border border-blue-300 bg-blue-50 p-4 text-sm text-blue-950">
        <div className="font-bold">Baseline dikunci sebelum penelitian diulang</div>
        <p className="mt-1 leading-6">
          Tidak ada filter tambahan, RR override, timeout eksperimen, train/validation verdict, atau rekomendasi V2.1 di halaman ini. Angka RR, entry, stop, target, biaya, dan hasil berasal dari log V2 asli.
        </p>
      </div>

      {error ? (
        <div className="rounded-md border border-stale bg-red-50 p-4 text-sm text-stale">{error}</div>
      ) : baseline && aggregate && coverage ? (
        <>
          <div className={`rounded-md border p-3 text-sm ${coverage.is_truncated ? "border-amber-300 bg-amber-50 text-amber-950" : "border-emerald-300 bg-emerald-50 text-emerald-950"}`}>
            Snapshot 1h memuat {coverage.source_1h_rows} dari {coverage.source_1h_total} signal closed; cohort MID_LONG 1h berisi {coverage.mid_long_1h_rows} signal.
            {coverage.is_truncated ? " Snapshot belum penuh, sehingga baseline belum boleh dibekukan untuk keputusan riset." : " Snapshot penuh dan dapat dipakai sebagai kontrol awal."}
          </div>

          <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-7">
            <MetricCard label="Baseline sample" value={aggregate.signals_evaluated} helper="MID_LONG 1h closed" />
            <MetricCard label="TP / SL" value={`${aggregate.tp_count} / ${aggregate.sl_count}`} helper={`${aggregate.closed_count} closed`} />
            <MetricCard label="Winrate" value={aggregate.winrate_pct == null ? "-" : `${fmtNumber(aggregate.winrate_pct)}%`} helper="TP / (TP + SL)" />
            <MetricCard label="Ideal R" value={`${fmtSigned(aggregate.total_r_closed)}R`} helper="Candle high/low" tone={toneFor(aggregate.total_r_closed)} />
            <MetricCard label="Realistic R" value={`${fmtSigned(aggregate.realistic_total_r_closed)}R`} helper="Fee + spread + slippage" tone={toneFor(aggregate.realistic_total_r_closed)} />
            <MetricCard label="Cost penalty" value={`${fmtSignedNegative(aggregate.realism_penalty_r_closed)}R`} helper="Ideal minus realistic" tone="warn" />
            <MetricCard label="Avg realistic" value={`${fmtSigned(aggregate.realistic_avg_r_closed)}R`} helper="Per closed signal" tone={toneFor(aggregate.realistic_avg_r_closed)} />
          </section>

          <SectionCard title="Baseline definition" description="Semua penelitian berikutnya wajib memakai kontrol ini terlebih dahulu agar perbandingan tetap setara.">
            <div className="grid gap-3 p-4 sm:grid-cols-2 lg:grid-cols-4">
              <Info label="Stage" value="MID_LONG" />
              <Info label="Signal timeframe" value="1h" />
              <Info label="Entry market" value="Binance Futures" />
              <Info label="Position lock" value="ON" />
              <Info label="Outcome scope" value="Closed only" />
              <Info label="WATCH_ONLY" value="Excluded" />
              <Info label="Evaluation source" value="Logged V2 signal plan" />
              <Info label="Latest evaluation candle" value={fmtTime(baseline.latest_evaluation_candle_time)} />
            </div>
          </SectionCard>

          <div className="grid gap-4 lg:grid-cols-3">
            <DistributionCard title="RR actually logged" rows={baseline.rr_distribution} />
            <DistributionCard title="Strategy versions" rows={baseline.strategy_distribution} />
            <DistributionCard title="Confidence tiers" rows={baseline.confidence_distribution} />
          </div>

          <SectionCard title="Recent baseline signals" description="Riwayat closed terbaru dari cohort V2 asli. Gunakan Detail untuk memeriksa chart, entry futures, SL, TP, dan evidence signal.">
            <BaselineSignalTable rows={baseline.items} />
          </SectionCard>

          <SectionCard title="Reset status" description="Checkpoint sebelum memulai penelitian MID_LONG 1h dari awal.">
            <div className="grid gap-3 p-4 md:grid-cols-3">
              <Info label="Current state" value="BASELINE_ONLY" />
              <Info label="Active MID_LONG experiment" value="None" />
              <Info label="Next permitted step" value="Baseline integrity audit" />
            </div>
          </SectionCard>
        </>
      ) : (
        <EmptyState title="Baseline belum tersedia" detail="Tunggu snapshot Signal Performance 1h selesai dibuat oleh research loop." />
      )}
    </div>
  );
}

function BaselineSignalTable({ rows }: { rows: SignalPerformanceItem[] }) {
  if (!rows.length) {
    return <div className="p-4"><EmptyState title="Belum ada closed signal" detail="Cohort MID_LONG 1h baseline masih kosong." /></div>;
  }

  return (
    <div className="table-wrap">
      <table className="ops-table">
        <thead>
          <tr>
            <th>Signal WIB</th>
            <th>Symbol</th>
            <th>Result</th>
            <th>Confidence</th>
            <th>RR</th>
            <th>Entry / SL / TP</th>
            <th>Ideal R</th>
            <th>Realistic R</th>
            <th>Result WIB</th>
            <th>Detail</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((item) => (
            <tr key={item.signal_id}>
              <td>{item.signal_time_wib || fmtTime(item.signal_timestamp)}</td>
              <td className="font-bold">{item.symbol}</td>
              <td><StatusBadge value={item.result_status} /></td>
              <td>{item.confidence_tier || "-"}</td>
              <td>{item.rr == null ? "-" : `${fmtNumber(item.rr)}R`}</td>
              <td>
                <div>Entry {fmtPrice(item.entry)}</div>
                <div>SL {fmtPrice(item.stop_loss)}</div>
                <div>TP {fmtPrice(item.take_profit)}</div>
              </td>
              <td>{fmtSigned(item.realized_r)}R</td>
              <td>{fmtSigned(item.realistic_realized_r)}R</td>
              <td>{item.result_time_wib || fmtTime(item.result_time_utc)}</td>
              <td>
                <Link className="font-semibold text-blue-700 hover:underline" href={`/signals/${encodeURIComponent(item.symbol)}?signal_id=${encodeURIComponent(item.signal_id)}`}>
                  Open
                </Link>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function DistributionCard({ title, rows }: { title: string; rows: Record<string, number> }) {
  const entries = Object.entries(rows);
  return (
    <SectionCard title={title} description="Distribusi faktual dari cohort baseline.">
      <div className="grid gap-2 p-4">
        {entries.length ? entries.map(([label, count]) => (
          <div key={label} className="flex items-center justify-between rounded-md border border-line bg-field/40 px-3 py-2 text-sm">
            <span className="font-semibold">{label}</span>
            <span className="font-black">{count}</span>
          </div>
        )) : <span className="text-sm text-slate-500">No rows</span>}
      </div>
    </SectionCard>
  );
}

function Info({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-line bg-field/40 p-3">
      <div className="text-xs font-semibold uppercase text-slate-500">{label}</div>
      <div className="mt-1 break-words font-bold text-ink">{value}</div>
    </div>
  );
}

function firstParam(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

function normalizeNumber(raw: string | undefined, fallback: number, min: number, max: number): number {
  const parsed = Number(raw);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.max(min, Math.min(max, Math.trunc(parsed)));
}

function fmtSigned(value?: string | number | null): string {
  if (value === null || value === undefined || value === "") return "-";
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return String(value);
  return `${numeric >= 0 ? "+" : ""}${fmtNumber(numeric)}`;
}

function fmtSignedNegative(value?: string | number | null): string {
  if (value === null || value === undefined || value === "") return "-";
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return String(value);
  return fmtSigned(-Math.abs(numeric));
}

function toneFor(value?: string | number | null): "good" | "bad" | undefined {
  if (value === null || value === undefined || value === "") return undefined;
  return Number(value) >= 0 ? "good" : "bad";
}
