import Link from "next/link";

import { EmptyState } from "@/components/EmptyState";
import { MetricCard } from "@/components/MetricCard";
import { PageHeader } from "@/components/PageHeader";
import { SectionCard } from "@/components/SectionCard";
import { StatusBadge } from "@/components/StatusBadge";
import {
  MidLongBaselineResponse,
  MidLongEntryCombinationRow,
  MidLongEvidenceComparisonRow,
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
  const summary = baseline?.research_summary;

  return (
    <div className="space-y-5">
      <PageHeader
        title="MID_LONG 1h Research Baseline"
        badge="READ-ONLY BASELINE RESET"
        subtitle="Halaman ini menjawab: MID_LONG 1h V2 kalah di mana, evidence apa yang membedakan TP vs SL, dan kombinasi entry mana yang layak diteliti lanjut. Belum ada rule V2.1 yang dipromosikan."
        updatedAt={fmtTime(baseline?.generated_at_utc)}
      />

      <div className="flex flex-wrap gap-2 text-sm">
        <Link className="rounded-md border border-line bg-white px-3 py-2 font-semibold hover:bg-field" href="/signal-performance?stage=MID_LONG&timeframe=1h&position_lock=true">
          Open closed signal history
        </Link>
        <Link className="rounded-md border border-line bg-white px-3 py-2 font-semibold hover:bg-field" href="/scanner?tier=SIGNAL_CANDIDATE">
          Open live signal radar
        </Link>
        <Link className="rounded-md border border-line bg-white px-3 py-2 font-semibold hover:bg-field" href="/signal-quality-lab?stage=MID_LONG&timeframe=1h">
          Open quality lab
        </Link>
      </div>

      {error ? (
        <div className="rounded-md border border-stale bg-red-50 p-4 text-sm text-stale">{error}</div>
      ) : baseline && aggregate && coverage ? (
        <>
          <SectionCard title="Apa fungsi halaman ini?" description="Ini bukan halaman signal live. Ini lab awal untuk membaca kenapa MID_LONG 1h V2 masih lemah sebelum kita berani membuat filter V2.1.">
            <div className="grid gap-3 p-4 md:grid-cols-3">
              <Info
                label="Baseline"
                value="MID_LONG 1h V2"
                helper="Kontrol asli: entry futures, SL/TP asli, fee/spread/slippage realistis."
              />
              <Info
                label="Yang dicari"
                value="TP vs SL separation"
                helper="Cari angka aktual yang beda antara signal yang kena target dan stop."
              />
              <Info
                label="Output sekarang"
                value="Research candidate"
                helper="Ranking kombinasi entry untuk diteliti lanjut, belum jadi rule produksi."
              />
            </div>
          </SectionCard>

          <div className={`rounded-md border p-3 text-sm ${coverage.is_truncated ? "border-amber-300 bg-amber-50 text-amber-950" : "border-emerald-300 bg-emerald-50 text-emerald-950"}`}>
            Snapshot 1h memuat {coverage.source_1h_rows} dari {coverage.source_1h_total} closed signal; cohort MID_LONG 1h berisi {coverage.mid_long_1h_rows} signal.
            {coverage.is_truncated ? " Snapshot belum penuh, jadi angka baseline perlu dibaca hati-hati." : " Snapshot penuh untuk kontrol baseline saat ini."}
          </div>

          <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-8">
            <MetricCard label="Sample" value={aggregate.signals_evaluated} helper="MID_LONG 1h closed" />
            <MetricCard label="TP / SL" value={`${aggregate.tp_count} / ${aggregate.sl_count}`} helper={`${aggregate.closed_count} closed`} tone={Number(aggregate.tp_count) >= Number(aggregate.sl_count) ? "good" : "bad"} />
            <MetricCard label="Winrate" value={formatPct(aggregate.winrate_pct)} helper="TP / (TP + SL)" />
            <MetricCard label="Ideal R" value={`${fmtSigned(aggregate.total_r_closed)}R`} helper="High/low candle ideal" tone={toneFor(aggregate.total_r_closed)} />
            <MetricCard label="Realistic R" value={`${fmtSigned(aggregate.realistic_total_r_closed)}R`} helper="Fee + spread + slippage" tone={toneFor(aggregate.realistic_total_r_closed)} />
            <MetricCard label="Avg realistic" value={`${fmtSigned(aggregate.realistic_avg_r_closed)}R`} helper="Rata-rata per signal" tone={toneFor(aggregate.realistic_avg_r_closed)} />
            <MetricCard label="Median realistic" value={`${fmtSigned(summary?.median_realistic_r_closed)}R`} helper="Tengah distribusi" tone={toneFor(summary?.median_realistic_r_closed)} />
            <MetricCard label="Max DD" value={`${fmtSigned(summary?.max_realistic_drawdown_r)}R`} helper="Drawdown realistic" tone="warn" />
          </section>

          <div className="grid gap-4 xl:grid-cols-[1.2fr_1fr_1fr]">
            <DistributionCard
              title="RR bucket bersih"
              description="RR asli dari log sudah dibulatkan supaya tidak muncul angka precision noise seperti 1.499999999R."
              rows={baseline.rr_distribution}
            />
            <DistributionCard title="Confidence tiers" description="Sebaran confidence dari Signal Factory V2." rows={baseline.confidence_distribution} />
            <DistributionCard title="Strategy versions" description="Memastikan baseline ini hanya membaca versi signal yang sama." rows={baseline.strategy_distribution} />
          </div>

          <SectionCard
            title="TP vs SL evidence comparison"
            description="Median dan kuartil angka aktual. Kalau TP dan SL nyaris sama, field itu belum memisahkan kualitas entry."
          >
            <EvidenceTable rows={(baseline.evidence_comparison || []).slice(0, 18)} sampleTotal={coverage.mid_long_1h_rows} />
          </SectionCard>

          <SectionCard
            title="Entry combination ranking"
            description="Ranking kombinasi evidence untuk MID_LONG 1h. Ini hanya research candidate: belum mengubah scanner, rule, SL/TP, atau execution."
          >
            <CombinationTable rows={baseline.entry_combination_ranking || []} />
          </SectionCard>

          <div className="grid gap-4 xl:grid-cols-2">
            <SectionCard title="Structure-zone breakdown" description="Apakah signal long lebih baik saat dekat support/breakout atau justru netral/konflik.">
              <CompactBreakdownTable rows={baseline.structure_breakdown || []} />
            </SectionCard>
            <SectionCard title="Primary zone state" description="Breakdown state 1h seperti support, resistance, breakout, atau tengah range.">
              <CompactBreakdownTable rows={baseline.primary_zone_breakdown || []} />
            </SectionCard>
          </div>

          <SectionCard
            title="Recent baseline signals"
            description="Riwayat closed terbaru dari V2 baseline. Detail membuka chart, entry futures, SL, TP, dan evidence signal."
          >
            <BaselineSignalTable rows={baseline.items} />
          </SectionCard>

          <SectionCard title="Research status" description="Checkpoint MID_LONG 1h setelah reset.">
            <div className="grid gap-3 p-4 md:grid-cols-4">
              <Info label="Current state" value={summary?.read || "BASELINE_ONLY"} />
              <Info label="Promoted V2.1 rule" value="None" />
              <Info label="Next step" value="Failure anatomy" helper="Bedah kenapa TP dan SL terjadi sebelum bikin filter baru." />
              <Info label="Guardrail" value="Read-only" helper="Tidak mengubah signal live, threshold, outcome, atau execution." />
            </div>
          </SectionCard>
        </>
      ) : (
        <EmptyState title="Baseline belum tersedia" detail="Tunggu snapshot Signal Performance 1h dibuat oleh research loop." />
      )}
    </div>
  );
}

function EvidenceTable({ rows, sampleTotal }: { rows: MidLongEvidenceComparisonRow[]; sampleTotal: number }) {
  if (!rows.length) {
    return <div className="p-4"><EmptyState title="Evidence belum tersedia" detail="Snapshot belum berisi evidence comparison." /></div>;
  }

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
                <div className="font-bold">{row.label}</div>
                <div className="text-xs text-slate-500">{row.field}</div>
              </td>
              <td><StatusBadge value={humanFlag(row.quality_flag)} /></td>
              <td>{row.available_count} / miss {row.missing_count} ({formatPct(row.available_pct)})</td>
              <td>{row.tp_count} / {row.sl_count}</td>
              <td>{fmtNumber(row.tp_median)}</td>
              <td>{fmtNumber(row.sl_median)}</td>
              <td>{fmtSigned(row.delta_tp_minus_sl)}</td>
              <td>{fmtNumber(row.tp_q1)} / {fmtNumber(row.tp_q3)}</td>
              <td>{fmtNumber(row.sl_q1)} / {fmtNumber(row.sl_q3)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="border-t border-line px-4 py-2 text-xs text-slate-500">
        Sample total: {sampleTotal}. Field dengan available rendah belum boleh dianggap kuat.
      </div>
    </div>
  );
}

function CombinationTable({ rows }: { rows: MidLongEntryCombinationRow[] }) {
  if (!rows.length) {
    return <div className="p-4"><EmptyState title="Belum ada kombinasi dengan sample cukup" detail="Perlu lebih banyak closed MID_LONG 1h atau evidence yang lebih lengkap." /></div>;
  }

  return (
    <div className="table-wrap">
      <table className="ops-table">
        <thead>
          <tr>
            <th>Kombinasi</th>
            <th>Sample</th>
            <th>TP / SL</th>
            <th>WR</th>
            <th>Realistic R</th>
            <th>Avg / Median</th>
            <th>Delta avg</th>
            <th>SL share</th>
            <th>DD</th>
            <th>Top symbol</th>
            <th>Verdict</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.filter_id}>
              <td className="min-w-64">
                <div className="font-bold">{row.label}</div>
                <div className="mt-1 text-xs leading-5 text-slate-500">{row.expression}</div>
              </td>
              <td>
                <div className="font-bold">{row.closed_count}</div>
                <div className="text-xs text-slate-500">{formatPct(row.sample_retention_pct)} retained</div>
              </td>
              <td>{row.tp_count} / {row.sl_count}</td>
              <td>{formatPct(row.winrate_pct)}</td>
              <td className={toneClass(row.realistic_total_r_closed)}>{fmtSigned(row.realistic_total_r_closed)}R</td>
              <td>{fmtSigned(row.realistic_avg_r_closed)}R / {fmtSigned(row.median_realistic_r_closed)}R</td>
              <td className={toneClass(row.realistic_avg_r_delta_vs_baseline)}>{fmtSigned(row.realistic_avg_r_delta_vs_baseline)}R</td>
              <td>
                <div>{formatPct(row.sl_share_pct)}</div>
                <div className="text-xs text-slate-500">Δ {fmtSigned(row.sl_share_delta_vs_baseline)}%</div>
              </td>
              <td>
                <div>{fmtSigned(row.max_realistic_drawdown_r)}R</div>
                <div className="text-xs text-slate-500">Δ {fmtSigned(row.max_drawdown_delta_vs_baseline)}R</div>
              </td>
              <td>
                <div className="font-semibold">{row.top_symbol || "-"}</div>
                <div className="text-xs text-slate-500">{formatPct(row.top_symbol_share_pct)}</div>
              </td>
              <td>
                <StatusBadge value={humanFlag(row.verdict)} />
                <div className="mt-1 max-w-72 text-xs leading-5 text-slate-600">{row.note}</div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function CompactBreakdownTable({ rows }: { rows: MidLongEntryCombinationRow[] }) {
  if (!rows.length) {
    return <div className="p-4"><EmptyState title="Breakdown kosong" detail="Belum ada row untuk bucket ini." /></div>;
  }

  return (
    <div className="table-wrap">
      <table className="ops-table">
        <thead>
          <tr>
            <th>Bucket</th>
            <th>Sample</th>
            <th>TP / SL</th>
            <th>Realistic R</th>
            <th>Avg</th>
            <th>SL share</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.filter_id}>
              <td><StatusBadge value={humanFlag(row.label)} /></td>
              <td>{row.closed_count}</td>
              <td>{row.tp_count} / {row.sl_count}</td>
              <td className={toneClass(row.realistic_total_r_closed)}>{fmtSigned(row.realistic_total_r_closed)}R</td>
              <td>{fmtSigned(row.realistic_avg_r_closed)}R</td>
              <td>{formatPct(row.sl_share_pct)}</td>
            </tr>
          ))}
        </tbody>
      </table>
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
            <th>Zone</th>
            <th>Confidence</th>
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
              <td>
                <StatusBadge value={humanFlag(item.structure_zone_status || "ZONE_UNAVAILABLE")} />
                <div className="mt-1 text-xs text-slate-500">{humanFlag(item.structure_zone_primary_state || "-")}</div>
              </td>
              <td>{humanFlag(item.confidence_tier || "-")}</td>
              <td>
                <div>Entry {fmtPrice(item.entry)}</div>
                <div>SL {fmtPrice(item.stop_loss)}</div>
                <div>TP {fmtPrice(item.take_profit)}</div>
              </td>
              <td>{fmtSigned(item.realized_r)}R</td>
              <td className={toneClass(item.realistic_realized_r)}>{fmtSigned(item.realistic_realized_r)}R</td>
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

function DistributionCard({ title, description, rows }: { title: string; description: string; rows: Record<string, number> }) {
  const entries = Object.entries(rows);
  return (
    <SectionCard title={title} description={description}>
      <div className="grid gap-2 p-4">
        {entries.length ? entries.map(([label, count]) => (
          <div key={label} className="flex items-center justify-between rounded-md border border-line bg-field/40 px-3 py-2 text-sm">
            <span className="font-semibold">{humanFlag(label)}</span>
            <span className="font-black">{count}</span>
          </div>
        )) : <span className="text-sm text-slate-500">No rows</span>}
      </div>
    </SectionCard>
  );
}

function Info({ label, value, helper }: { label: string; value: string; helper?: string }) {
  return (
    <div className="rounded-md border border-line bg-field/40 p-3">
      <div className="text-xs font-semibold uppercase text-slate-500">{label}</div>
      <div className="mt-1 break-words font-bold text-ink">{value}</div>
      {helper && <div className="mt-1 text-xs leading-5 text-slate-600">{helper}</div>}
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

function formatPct(value?: string | number | null): string {
  if (value === null || value === undefined || value === "") return "-";
  return `${fmtNumber(value)}%`;
}

function toneFor(value?: string | number | null): "good" | "bad" | undefined {
  if (value === null || value === undefined || value === "") return undefined;
  return Number(value) >= 0 ? "good" : "bad";
}

function toneClass(value?: string | number | null): string {
  if (value === null || value === undefined || value === "") return "";
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return "";
  return numeric >= 0 ? "font-semibold text-ready" : "font-semibold text-stale";
}

function humanFlag(value: string): string {
  return value
    .replace(/_/g, " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase())
    .replace(/\bV2\b/g, "V2")
    .replace(/\bV21\b/g, "V2.1")
    .replace(/\bTp\b/g, "TP")
    .replace(/\bSl\b/g, "SL")
    .replace(/\bRr\b/g, "RR")
    .replace(/\bAtr\b/g, "ATR")
    .replace(/\bOi\b/g, "OI");
}
