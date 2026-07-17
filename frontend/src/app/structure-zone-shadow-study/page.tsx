import Link from "next/link";

import { EmptyState } from "@/components/EmptyState";
import { MetricCard } from "@/components/MetricCard";
import { PageHeader } from "@/components/PageHeader";
import { SectionCard } from "@/components/SectionCard";
import { StatusBadge } from "@/components/StatusBadge";
import { StructureZoneShadowStudyResponse, fetchJson, fmtNumber, fmtTime } from "@/lib/api";
import { labelFor } from "@/lib/labels";

type SearchParams = Promise<Record<string, string | string[] | undefined>>;

export default async function StructureZoneShadowStudyPage({ searchParams }: { searchParams: SearchParams }) {
  const params = await searchParams;
  const positionLock = firstParam(params.position_lock) !== "false";
  const includeWatchOnly = firstParam(params.include_watch_only) === "true";
  const query = new URLSearchParams({
    position_lock: String(positionLock),
    include_watch_only: String(includeWatchOnly),
    min_sample: "20",
    limit: "50"
  });
  let data: StructureZoneShadowStudyResponse | null = null;
  let error: string | null = null;
  try {
    data = await fetchJson<StructureZoneShadowStudyResponse>(`/api/signal-candidates/structure-zone-shadow-study?${query.toString()}`, { revalidateSeconds: 30 });
  } catch (err) {
    error = err instanceof Error ? err.message : "Structure zone shadow gagal dimuat";
  }

  return (
    <div className="space-y-5">
      <PageHeader
        title="Structure Zone Shadow"
        badge="READ-ONLY OBSERVATION"
        subtitle="Perbandingan hasil Signal berdasarkan posisi support/resistance yang benar-benar tersedia saat Signal terbentuk. Label ini bukan gate dan tidak mengubah entry, SL, atau TP."
        updatedAt={fmtTime(data?.generated_at_utc)}
      />

      <div className="flex flex-wrap gap-2 text-sm">
        <Link className="rounded border border-line bg-white px-3 py-2 font-semibold hover:bg-field" href="/scanner">Open Radar</Link>
        <Link className="rounded border border-line bg-white px-3 py-2 font-semibold hover:bg-field" href="/signal-quality-lab">Open Quality Lab</Link>
        <Link className="rounded border border-line bg-white px-3 py-2 font-semibold hover:bg-field" href={positionLock ? "/structure-zone-shadow-study?position_lock=false" : "/structure-zone-shadow-study"}>
          Position lock: {String(positionLock)}
        </Link>
        <Link className="rounded border border-line bg-white px-3 py-2 font-semibold hover:bg-field" href={includeWatchOnly ? "/structure-zone-shadow-study" : "/structure-zone-shadow-study?include_watch_only=true"}>
          WATCH_ONLY: {includeWatchOnly ? "included" : "excluded"}
        </Link>
      </div>

      {error || !data ? (
        <div className="rounded border border-stale bg-red-50 p-4 text-sm text-stale">{error || "Data belum tersedia"}</div>
      ) : (
        <>
          <section className="grid gap-3 md:grid-cols-2 xl:grid-cols-5">
            <MetricCard label="Evaluated" value={data.snapshot_coverage.evaluated_count} helper="Signal pada cohort aktif" />
            <MetricCard label="Zone snapshots" value={data.snapshot_coverage.persisted_snapshot_count} helper={`${fmtNumber(data.snapshot_coverage.coverage_pct)}% coverage`} tone="info" />
            <MetricCard label="Missing snapshots" value={data.snapshot_coverage.missing_snapshot_count} helper="Dapat diisi oleh bounded backfill" tone={data.snapshot_coverage.missing_snapshot_count ? "warn" : "good"} />
            <MetricCard label="Baseline realistic R" value={`${fmtSigned(data.baseline.realistic_total_r_closed)}R`} helper={`${data.baseline.closed_count} closed`} tone={Number(data.baseline.realistic_total_r_closed || 0) >= 0 ? "good" : "bad"} />
            <MetricCard label="Latest candle" value={fmtTime(data.latest_evaluation_candle_time)} helper="Futures evaluation" />
          </section>

          <SectionCard title="Outcome by zone status" description="Bandingkan aligned, conflict, neutral, dan unavailable pada fixed cohort yang sama. Sample kecil tetap ditandai belum cukup.">
            <div className="table-wrap">
              <table className="ops-table">
                <thead>
                  <tr>
                    <th>Zone status</th><th>Sample</th><th>TP / SL</th><th>SL share</th><th>Realistic R</th><th>Avg R</th><th>Delta vs all</th><th>Sample status</th>
                  </tr>
                </thead>
                <tbody>
                  {data.by_zone_status.map((row) => (
                    <tr key={row.bucket}>
                      <td><StatusBadge value={row.bucket} /></td>
                      <td>{row.sample_count} ({fmtNumber(row.sample_share_pct)}%)</td>
                      <td>{row.tp_count} / {row.sl_count}</td>
                      <td>{fmtNumber(row.sl_share_pct)}%</td>
                      <td>{fmtSigned(row.realistic_total_r_closed)}R</td>
                      <td>{fmtSigned(row.realistic_avg_r_closed)}R</td>
                      <td>{fmtSigned(row.realistic_avg_r_delta_vs_all)}R</td>
                      <td><StatusBadge value={row.sample_status} /></td>
                    </tr>
                  ))}
                  {!data.by_zone_status.length ? <tr><td colSpan={8}><EmptyState title="Belum ada snapshot" detail="Jalankan backfill structure-zone lalu refresh halaman." /></td></tr> : null}
                </tbody>
              </table>
            </div>
          </SectionCard>

          <SectionCard title="Stage and timeframe breakdown" description="Pemisahan ini membantu memastikan hasil zona tidak hanya datang dari satu jenis Signal atau timeframe.">
            <div className="table-wrap">
              <table className="ops-table">
                <thead><tr><th>Stage</th><th>TF</th><th>Zone</th><th>Sample</th><th>TP / SL</th><th>SL share</th><th>Realistic avg R</th><th>Status</th></tr></thead>
                <tbody>
                  {data.by_stage_timeframe_zone.map((row) => (
                    <tr key={`${row.stage}-${row.timeframe}-${row.bucket}`}>
                      <td>{labelFor(row.stage || "UNKNOWN")}</td>
                      <td>{row.timeframe}</td>
                      <td><StatusBadge value={row.bucket} /></td>
                      <td>{row.sample_count}</td>
                      <td>{row.tp_count} / {row.sl_count}</td>
                      <td>{fmtNumber(row.sl_share_pct)}%</td>
                      <td>{fmtSigned(row.realistic_avg_r_closed)}R</td>
                      <td><StatusBadge value={row.sample_status} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </SectionCard>

          <SectionCard title="Latest labeled Signals" description="Klik Signal untuk melihat chart Entry/SL/TP beserta overlay repeated-zone yang dibekukan pada waktu Signal.">
            <div className="table-wrap">
              <table className="ops-table">
                <thead><tr><th>Time WIB</th><th>Symbol</th><th>TF</th><th>Stage</th><th>Direction</th><th>Zone</th><th>Primary state</th><th>Result</th><th>Detail</th></tr></thead>
                <tbody>
                  {data.latest_signals.map((item) => (
                    <tr key={item.signal_id}>
                      <td>{item.signal_time_wib || fmtTime(item.signal_timestamp)}</td>
                      <td className="font-semibold">{item.symbol}</td>
                      <td>{item.timeframe}</td>
                      <td>{labelFor(item.stage)}</td>
                      <td><StatusBadge value={item.direction} /></td>
                      <td><StatusBadge value={item.structure_zone_status || "ZONE_UNAVAILABLE"} /></td>
                      <td>{labelFor(item.structure_zone_primary_state || "ZONE_UNAVAILABLE")}</td>
                      <td><StatusBadge value={item.result_status} /></td>
                      <td><Link className="font-semibold text-blue-700 hover:underline" href={`/signals/${encodeURIComponent(item.symbol)}?signal_id=${encodeURIComponent(item.signal_id)}`}>Open</Link></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </SectionCard>
        </>
      )}
    </div>
  );
}

function fmtSigned(value?: string | number | null): string {
  if (value === null || value === undefined || value === "") return "-";
  const number = Number(value);
  if (!Number.isFinite(number)) return String(value);
  return `${number >= 0 ? "+" : ""}${fmtNumber(number)}`;
}

function firstParam(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}
