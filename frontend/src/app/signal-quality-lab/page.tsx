import Link from "next/link";

import { EmptyState } from "@/components/EmptyState";
import { FilterBar, SelectFilter } from "@/components/FilterBar";
import { MetricCard } from "@/components/MetricCard";
import { PageHeader } from "@/components/PageHeader";
import { SectionCard } from "@/components/SectionCard";
import { StatusBadge } from "@/components/StatusBadge";
import {
  MarketRegimeStudyBucket,
  MarketRegimeStudyResponse,
  MidShortStructureStateRow,
  MidShortV21ExitVariant,
  MidShortV21StructureInteractionResponse,
  MidShortV21StructureExitResponse,
  MidShortV21StructureVariant,
  SignalCalibrationCandidate,
  SignalCalibrationLabResponse,
  SignalCalibrationLane,
  SignalFilterStudyResponse,
  SignalFilterStudyRow,
  SignalPerformanceItem,
  SignalQualityBucket,
  SignalQualityEvidenceField,
  SignalQualityLabResponse,
  SignalQualityMidShortRefinement,
  SignalQualityMidShortRefinementRow,
  SignalQualityProfitLossLane,
  SignalQualityProfitLossResearch,
  SignalQualityRealisticDragRow,
  SignalQualityVolumeRankBucket,
  fetchJson,
  fmtNumber,
  fmtTime
} from "@/lib/api";
import { labelFor } from "@/lib/labels";

type QualitySearchParams = Promise<Record<string, string | string[] | undefined>>;

const stages = ["EARLY_LONG", "EARLY_SHORT", "MID_LONG", "MID_SHORT"];
const timeframes = ["15m", "1h", "4h", "24h"];

export const dynamic = "force-dynamic";

export default async function SignalQualityLabPage({ searchParams }: { searchParams: QualitySearchParams }) {
  const params = await searchParams;
  const stage = firstParam(params.stage);
  const timeframe = firstParam(params.timeframe);
  const includeWatchOnly = firstParam(params.include_watch_only) === "true";
  const positionLock = firstParam(params.position_lock) !== "false";
  const showArchive = firstParam(params.show_archive) === "true";
  const activeLab = firstParam(params.lab);
  const showV21Structure = activeLab === "structure-v21";
  const showV21Exit = activeLab === "exit-v21";
  const focusedLab = showV21Structure || showV21Exit;
  const minSample = normalizeNumber(firstParam(params.min_sample), 5, 1, 100);
  const limit = normalizeNumber(firstParam(params.limit), 25, 5, 100);
  const query = new URLSearchParams({
    include_watch_only: String(includeWatchOnly),
    position_lock: String(positionLock),
    min_sample: String(minSample),
    limit: String(limit)
  });
  if (stage) query.set("stage", stage);
  if (timeframe) query.set("timeframe", timeframe);

  let data: SignalQualityLabResponse | null = null;
  let filterStudy: SignalFilterStudyResponse | null = null;
  let marketRegimeStudy: MarketRegimeStudyResponse | null = null;
  let v21StructureStudy: MidShortV21StructureInteractionResponse | null = null;
  let v21ExitStudy: MidShortV21StructureExitResponse | null = null;
  let error: string | null = null;
  let filterStudyError: string | null = null;
  let marketRegimeError: string | null = null;
  let v21StructureError: string | null = null;
  let v21ExitError: string | null = null;
  if (!focusedLab) {
    try {
      data = await fetchJson<SignalQualityLabResponse>(`/api/signal-candidates/quality-lab?${query.toString()}`, { revalidateSeconds: 120 });
    } catch (err) {
      error = err instanceof Error ? err.message : "Signal Quality Lab API failed";
    }
    const studyQuery = new URLSearchParams({
      include_watch_only: String(includeWatchOnly),
      position_lock: String(positionLock),
      stage: stage || "MID_SHORT",
      timeframe: timeframe || "1h",
      min_sample: String(minSample),
      limit: String(limit)
    });
    try {
      filterStudy = await fetchJson<SignalFilterStudyResponse>(`/api/signal-candidates/filter-study?${studyQuery.toString()}`, { revalidateSeconds: 120 });
    } catch (err) {
      filterStudyError = err instanceof Error ? err.message : "Signal Filter Study API failed";
    }
    try {
      marketRegimeStudy = await fetchJson<MarketRegimeStudyResponse>("/api/signal-candidates/market-regime-study", { revalidateSeconds: 300 });
    } catch (err) {
      marketRegimeError = err instanceof Error ? err.message : "Market Regime Study API failed";
    }
  }
  if (showV21Structure) {
    const structureQuery = new URLSearchParams({
      include_watch_only: String(includeWatchOnly),
      position_lock: String(positionLock),
      min_sample: String(Math.max(20, minSample)),
      limit: String(limit)
    });
    try {
      v21StructureStudy = await fetchJson<MidShortV21StructureInteractionResponse>(
        `/api/signal-candidates/mid-short-1h-v2-1-structure-interaction-study?${structureQuery.toString()}`,
        { revalidateSeconds: 300 }
      );
    } catch (err) {
      v21StructureError = err instanceof Error ? err.message : "V2.1 Structure Interaction API failed";
    }
  }
  if (showV21Exit) {
    const exitQuery = new URLSearchParams({
      include_watch_only: String(includeWatchOnly),
      position_lock: String(positionLock),
      min_sample: String(Math.max(20, minSample)),
      limit: String(limit)
    });
    try {
      v21ExitStudy = await fetchJson<MidShortV21StructureExitResponse>(
        `/api/signal-candidates/mid-short-1h-v2-1-structure-exit-study?${exitQuery.toString()}`,
        { revalidateSeconds: 300 }
      );
    } catch (err) {
      v21ExitError = err instanceof Error ? err.message : "V2.1 Structure Exit API failed";
    }
  }

  if (showV21Exit) {
    return (
      <div className="space-y-5">
        <PageHeader
          title="Signal Quality Lab / LAB-60"
          badge="READ-ONLY EXIT STUDY"
          subtitle="Fixed-cohort MID_SHORT 1h V2.1: membandingkan target, stop, dan urutan jalur harga tanpa mengubah Signal live atau geometry yang sudah tercatat."
          updatedAt={fmtTime(v21ExitStudy?.generated_at_utc)}
        />
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <Link className="rounded-md border border-line bg-white px-3 py-2 font-semibold hover:bg-field" href="/signal-quality-lab">Back to Quality Lab</Link>
          <Link className="rounded-md border border-line bg-white px-3 py-2 font-semibold hover:bg-field" href="/signal-quality-lab?lab=structure-v21">Open LAB-59 Structure</Link>
          <Link className="rounded-md border border-line bg-white px-3 py-2 font-semibold hover:bg-field" href="/mid-short-filter-combination-study">Open V2.1 Decision</Link>
          <Link className="rounded-md border border-line bg-white px-3 py-2 font-semibold hover:bg-field" href="/patch-notes">Patch Notes</Link>
        </div>
        <V21StructureExitPanel data={v21ExitStudy} error={v21ExitError} />
      </div>
    );
  }

  if (showV21Structure) {
    return (
      <div className="space-y-5">
        <PageHeader
          title="Signal Quality Lab / LAB-59"
          badge="READ-ONLY V2.1 STUDY"
          subtitle="Fixed-cohort MID_SHORT 1h SHADOW_PASS + taker sell >= 52%. Halaman fokus ini tidak memuat studi lama yang berat dan tidak mengubah rule produksi."
          updatedAt={fmtTime(v21StructureStudy?.generated_at_utc)}
        />
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <Link className="rounded-md border border-line bg-white px-3 py-2 font-semibold hover:bg-field" href="/signal-quality-lab">Back to Quality Lab</Link>
          <Link className="rounded-md border border-line bg-white px-3 py-2 font-semibold hover:bg-field" href="/mid-short-filter-combination-study">Open V2.1 Decision</Link>
          <Link className="rounded-md border border-line bg-white px-3 py-2 font-semibold hover:bg-field" href="/signal-quality-lab?lab=exit-v21">Open LAB-60 Exit Path</Link>
          <Link className="rounded-md border border-line bg-white px-3 py-2 font-semibold hover:bg-field" href="/mid-short-structure-zone-study">Open LAB-56 Zone Evidence</Link>
          <Link className="rounded-md border border-line bg-white px-3 py-2 font-semibold hover:bg-field" href="/patch-notes">Patch Notes</Link>
        </div>
        <V21StructureInteractionPanel data={v21StructureStudy} error={v21StructureError} />
      </div>
    );
  }

  const aggregate = data?.aggregate;
  const bestStage = data?.by_stage?.[0];
  const weakestStage = [...(data?.by_stage || [])].sort((a, b) => Number(a.total_r_closed) - Number(b.total_r_closed))[0];

  return (
    <div className="space-y-5">
      <PageHeader
        title="Signal Quality Lab"
        badge="READ-ONLY ANALYSIS"
        subtitle="Fokus aktif sekarang: evaluasi V2 realistis. Halaman ini membaca kenapa Signal TP/SL, variabel mana yang membantu, dan bagian mana yang bocor setelah fee/spread/slippage. Ini tidak mengubah rule dan bukan execution."
        updatedAt={fmtTime(data?.generated_at_utc)}
      />

      <div className="flex flex-wrap items-center gap-2 text-sm">
        <Link className="rounded-md border border-line bg-white px-3 py-2 font-semibold hover:bg-field" href="/scanner">Open Live Radar</Link>
        <Link className="rounded-md border border-line bg-white px-3 py-2 font-semibold hover:bg-field" href="/signal-performance">Open Signal History</Link>
        <Link className="rounded-md border border-line bg-white px-3 py-2 font-semibold hover:bg-field" href="/signal-misidentification-audit">Open Misidentification Audit</Link>
        <Link className="rounded-md border border-line bg-white px-3 py-2 font-semibold hover:bg-field" href="/mid-short-filter-combination-study">Open V2.1 Decision</Link>
        <Link className="rounded-md border border-line bg-white px-3 py-2 font-semibold hover:bg-field" href="/signal-quality-lab?lab=exit-v21">Open LAB-60 Exit Path</Link>
        <Link
          className={`rounded-md border px-3 py-2 font-semibold ${showV21Structure ? "border-primary bg-primary text-white" : "border-line bg-white hover:bg-field"}`}
          href={showV21Structure ? "/signal-quality-lab" : "/signal-quality-lab?lab=structure-v21"}
        >
          {showV21Structure ? "Close V2.1 Structure" : "Open V2.1 Structure"}
        </Link>
        <details className="relative">
          <summary className="cursor-pointer list-none rounded-md border border-line bg-white px-3 py-2 font-semibold hover:bg-field">Deep research links</summary>
          <div className="absolute left-0 top-11 z-10 grid w-72 gap-1 rounded-lg border border-line bg-white p-2 shadow-lg">
            <Link className="rounded px-3 py-2 hover:bg-field" href="/shadow-forward-log">MID_SHORT Shadow Log</Link>
            <Link className="rounded px-3 py-2 hover:bg-field" href="/mid-short-failure-anatomy">Failure Anatomy</Link>
            <Link className="rounded px-3 py-2 hover:bg-field" href="/mid-short-wrong-direction-deep-dive">Wrong Direction</Link>
            <Link className="rounded px-3 py-2 hover:bg-field" href="/mid-short-entry-confirmation-study">Entry Confirmation</Link>
            <Link className="rounded px-3 py-2 hover:bg-field" href="/mid-short-structure-zone-study">Structure Zone Study</Link>
            <Link className="rounded px-3 py-2 hover:bg-field" href="/mid-short-volume-safe-shadow">Volume Safe</Link>
            <Link className="rounded px-3 py-2 hover:bg-field" href="/mid-short-taker-sell-deep-dive">Taker Sell Deep Dive</Link>
            <Link className="rounded px-3 py-2 hover:bg-field" href="/mid-short-second-filter-shadow">Second Filter</Link>
            <Link className="rounded px-3 py-2 hover:bg-field" href="/signal-factory">Signal Factory Raw</Link>
          </div>
        </details>
        <Link className="rounded-md border border-line bg-white px-3 py-2 font-semibold hover:bg-field" href={showArchive ? "/signal-quality-lab" : "/signal-quality-lab?show_archive=true"}>{showArchive ? "Hide Archive" : "Show V3/V4 Archive"}</Link>
      </div>

      {error ? (
        <div className="rounded border border-stale bg-red-50 p-4 text-sm text-stale">{error}</div>
      ) : (
        <>
          <section className="grid gap-3 md:grid-cols-2 xl:grid-cols-6">
            <MetricCard label="Evaluated" value={aggregate?.signals_evaluated ?? 0} helper={`${aggregate?.signals_skipped ?? 0} skipped by lock`} />
            <MetricCard label="Total R" value={`${fmtSigned(aggregate?.total_r_closed)}R`} helper="Closed TP/SL/BOTH" tone={Number(aggregate?.total_r_closed || 0) >= 0 ? "good" : "bad"} />
            <MetricCard label="Max Drawdown" value={`${fmtSigned(data?.drawdown.max_drawdown_r)}R`} helper="Dari urutan result closed" tone="warn" />
            <MetricCard label="Current DD" value={`${fmtSigned(data?.drawdown.current_drawdown_r)}R`} helper={`Peak ${fmtSigned(data?.drawdown.peak_r)}R`} />
            <MetricCard label="TP / SL" value={`${aggregate?.tp_count ?? 0} / ${aggregate?.sl_count ?? 0}`} helper={`${aggregate?.closed_count ?? 0} closed`} />
            <MetricCard label="Open" value={aggregate?.open_count ?? 0} helper={`${fmtSigned(aggregate?.open_unrealized_r)}R unrealized`} tone="warn" />
          </section>

          <SectionCard title="Quality controls" description="Filter ini hanya mengubah tampilan analisis. Tidak mengubah rule Signal Factory.">
            <FilterBar>
              <SelectFilter label="Stage" name="stage" value={stage || ""} options={stages} emptyLabel="All stage" />
              <SelectFilter label="Timeframe" name="timeframe" value={timeframe || ""} options={timeframes} emptyLabel="All timeframe" />
              <label className="grid gap-1 text-sm">
                <span className="font-semibold text-slate-600">Min sample</span>
                <input className="rounded border border-line px-3 py-2" min={1} max={100} name="min_sample" type="number" defaultValue={minSample} />
              </label>
              <label className="grid gap-1 text-sm">
                <span className="font-semibold text-slate-600">Rows</span>
                <input className="rounded border border-line px-3 py-2" min={5} max={100} name="limit" type="number" defaultValue={limit} />
              </label>
              <SelectFilter label="Position lock" name="position_lock" value={String(positionLock)} options={["true", "false"]} emptyLabel="Default true" />
              <label className="flex items-end gap-2 pb-2 text-sm font-semibold text-slate-600">
                <input name="include_watch_only" type="checkbox" value="true" defaultChecked={includeWatchOnly} />
                Include WATCH_ONLY
              </label>
            </FilterBar>
          </SectionCard>

          <MidShortRefinementPanel data={data?.mid_short_1h_refinement || null} />

          {showV21Structure ? (
            <V21StructureInteractionPanel data={v21StructureStudy} error={v21StructureError} />
          ) : null}

          <V2ProfitLossResearchPanel data={data?.profit_loss_research || null} />

          <OtherLaneResearchQueue data={data?.profit_loss_research || null} />

          <CollapsiblePanel
            title={`Filter Study ${filterStudy?.filters.timeframe || "1h"} ${labelFor(filterStudy?.filters.stage || "MID_SHORT")}`}
            description="Ranking filter read-only untuk melihat mana yang memperbaiki Signal. Ini belum mengubah rule produksi."
          >
            {filterStudyError ? (
              <div className="p-4 text-sm text-stale">{filterStudyError}</div>
            ) : (
              <FilterStudyTable rows={filterStudy?.rows || []} />
            )}
          </CollapsiblePanel>

          {showArchive ? (
            <SectionCard title="Archived V3/V4 studies" description="Archive ini tidak auto-load endpoint berat. Buka halaman spesifik hanya kalau perlu membandingkan history lama.">
              <div className="grid gap-3 p-4 md:grid-cols-3">
                <ArchiveLink href="/v3-forward-log" title="V3 Forward Archive" detail="Shadow forward log, failure analysis, dan 1h+ V3 audit lama." />
                <ArchiveLink href="/signal-1h-review" title="1h Review Archive" detail="Filter study, walk-forward, dan V4 shadow monitor yang dibekukan." />
                <ArchiveLink href="/strategy-optimization-lab" title="Optimization Archive" detail="Eksperimen optimization/read-only yang tidak mengubah rule live." />
              </div>
            </SectionCard>
          ) : (
            <SectionCard title="Archived V3/V4 studies" description="Disembunyikan dari default supaya fokus web kembali ke V2 Profit/Loss Research. Buka hanya kalau perlu membandingkan history lama.">
              <div className="flex flex-wrap gap-2 p-4 text-sm">
                <Link className="rounded border border-line bg-white px-3 py-2 font-semibold hover:bg-field" href="/signal-quality-lab?show_archive=true">Open archived calibration</Link>
                <Link className="rounded border border-line bg-white px-3 py-2 font-semibold hover:bg-field" href="/v3-forward-log">Open V3 Forward Archive</Link>
                <Link className="rounded border border-line bg-white px-3 py-2 font-semibold hover:bg-field" href="/signal-1h-review">Open 1h Review Archive</Link>
              </div>
            </SectionCard>
          )}

          <CollapsiblePanel
            title="Market Regime Study"
            description="Split read-only berdasarkan kondisi BTC, ETH, breadth market, dan volatility. Ini menjawab setup bekerja di rezim market apa, tanpa mengubah Signal Factory."
          >
            {marketRegimeError ? (
              <div className="p-4 text-sm text-stale">{marketRegimeError}</div>
            ) : (
              <MarketRegimeStudy data={marketRegimeStudy} />
            )}
          </CollapsiblePanel>

          <section className="grid gap-4 xl:grid-cols-2">
            <SectionCard title="Fast read" description="Kesimpulan cepat dari data yang sedang difilter.">
              <div className="grid gap-3 p-4 text-sm md:grid-cols-2">
                <Insight label="Stage terbaik" value={bestStage ? `${labelFor(bestStage.bucket)} (${fmtSigned(bestStage.total_r_closed)}R)` : "-"} />
                <Insight label="Stage terlemah" value={weakestStage ? `${labelFor(weakestStage.bucket)} (${fmtSigned(weakestStage.total_r_closed)}R)` : "-"} />
                <Insight label="Confidence terbaik" value={data?.by_confidence?.[0] ? `${labelFor(data.by_confidence[0].bucket)} (${fmtSigned(data.by_confidence[0].total_r_closed)}R)` : "-"} />
                <Insight label="Symbol paling profit" value={data?.top_symbols?.[0] ? `${data.top_symbols[0].bucket} (${fmtSigned(data.top_symbols[0].total_r_closed)}R)` : "-"} />
              </div>
            </SectionCard>

            <SectionCard title="Drawdown R" description="Bukan PnL. Ini akumulasi R dari closed paper result untuk melihat risk streak.">
              <div className="grid gap-3 p-4 text-sm md:grid-cols-3">
                <Insight label="Closed count" value={String(data?.drawdown.closed_count ?? 0)} />
                <Insight label="Peak R" value={`${fmtSigned(data?.drawdown.peak_r)}R`} />
                <Insight label="Max DD" value={`${fmtSigned(data?.drawdown.max_drawdown_r)}R`} />
              </div>
              <div className="table-wrap border-t border-line">
                <table className="ops-table">
                  <thead>
                    <tr>
                      <th>Time WIB</th>
                      <th>Symbol</th>
                      <th>Stage</th>
                      <th>Result</th>
                      <th>R</th>
                      <th>Cumulative</th>
                      <th>Drawdown</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(data?.drawdown.points || []).slice(-12).reverse().map((point) => (
                      <tr key={`${point.signal_id}-${point.cumulative_r}`}>
                        <td>{point.result_time_wib || fmtTime(point.result_time_utc)}</td>
                        <td className="font-semibold">{point.symbol}</td>
                        <td>{labelFor(point.stage)}</td>
                        <td><StatusBadge value={point.result_status} /></td>
                        <td>{fmtSigned(point.realized_r)}R</td>
                        <td>{fmtSigned(point.cumulative_r)}R</td>
                        <td>{fmtSigned(point.drawdown_r)}R</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </SectionCard>
          </section>

          <SectionCard
            title="Top volume rank return"
            description="Membandingkan hasil Signal jika hanya melihat token rank volume futures Top 5, Top 10, Top 20, dan All. Rank berasal dari active universe terbaru."
          >
            <VolumeRankTable rows={data?.by_volume_rank || []} />
          </SectionCard>

          <SectionCard title="Evidence TP vs SL" description="Median dan kuartil angka evidence aktual dari signal yang TP dibanding yang SL. Pakai filter di atas untuk bedah stage/timeframe tertentu.">
            <EvidenceTable rows={data?.evidence_fields || []} />
          </SectionCard>

          <CollapsiblePanel title="Quality buckets" description="Stage, confidence, timeframe, dan symbol. Buka saat perlu bedah detail lane tertentu." defaultOpen>
            <div className="space-y-4">
              <SectionCard title="Quality by stage" description="Ini yang paling penting untuk memperbaiki definisi EARLY/MID berikutnya.">
                <BucketTable rows={data?.by_stage || []} />
              </SectionCard>

              <section className="grid gap-4 xl:grid-cols-2">
                <SectionCard title="Quality by confidence">
                  <BucketTable rows={data?.by_confidence || []} compact />
                </SectionCard>
                <SectionCard title="Quality by timeframe">
                  <BucketTable rows={data?.by_timeframe || []} compact />
                </SectionCard>
              </section>

              <section className="grid gap-4 xl:grid-cols-2">
                <SectionCard title="Top symbols" description="Symbol yang paling membantu total R.">
                  <BucketTable rows={data?.top_symbols || []} compact />
                </SectionCard>
                <SectionCard title="Weak / noisy symbols" description="Symbol yang paling merusak total R sesuai filter.">
                  <BucketTable rows={data?.weak_symbols || []} compact />
                </SectionCard>
              </section>
            </div>
          </CollapsiblePanel>

          <CollapsiblePanel title="Signal samples" description="Best/worst/open signal mentah. Ini disembunyikan default supaya halaman tidak terlalu panjang.">
            <div className="space-y-4">
              <section className="grid gap-4 xl:grid-cols-2">
                <SectionCard title="Best closed signals">
                  <SignalTable rows={data?.best_signals || []} />
                </SectionCard>
                <SectionCard title="Worst closed signals">
                  <SignalTable rows={data?.worst_signals || []} />
                </SectionCard>
              </section>

              <SectionCard title="Open signals" description="Masih berjalan, belum dihitung sebagai closed R.">
                <SignalTable rows={data?.open_signals || []} />
              </SectionCard>
            </div>
          </CollapsiblePanel>
        </>
      )}
    </div>
  );
}

function CollapsiblePanel({
  title,
  description,
  defaultOpen = false,
  children
}: {
  title: string;
  description?: string;
  defaultOpen?: boolean;
  children: React.ReactNode;
}) {
  return (
    <details className="rounded-md border border-line bg-white" open={defaultOpen}>
      <summary className="cursor-pointer list-none px-4 py-3 hover:bg-field">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <div className="font-bold text-ink">{title}</div>
            {description ? <div className="mt-1 text-sm text-slate-600">{description}</div> : null}
          </div>
          <span className="rounded border border-line px-2 py-1 text-xs font-semibold text-slate-600">Open / close</span>
        </div>
      </summary>
      <div className="border-t border-line p-4">
        {children}
      </div>
    </details>
  );
}

function V21StructureInteractionPanel({
  data,
  error
}: {
  data: MidShortV21StructureInteractionResponse | null;
  error: string | null;
}) {
  if (error) {
    return (
      <SectionCard title="LAB-59 V2.1 Structure Interaction" description="Studi fixed-cohort gagal dimuat.">
        <div className="p-4 text-sm text-stale">{error}</div>
      </SectionCard>
    );
  }
  if (!data) {
    return (
      <SectionCard title="LAB-59 V2.1 Structure Interaction" description="Menunggu payload studi read-only.">
        <EmptyState title="No LAB-59 data" detail="Buka ulang setelah endpoint studi tersedia." />
      </SectionCard>
    );
  }

  const summary = data.summary;
  return (
    <div className="space-y-4" id="v21-structure-interaction">
      <section className="rounded-md border border-line bg-white">
        <div className="border-b border-line px-4 py-3">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 className="font-bold text-ink">LAB-59 V2.1 Structure Interaction</h2>
              <p className="mt-1 text-sm text-slate-600">
                Hanya MID_SHORT 1h SHADOW_PASS + taker sell &gt;= 52%. Semua varian memakai cohort dan position lock yang sama.
              </p>
            </div>
            <div className="flex gap-2">
              <StatusBadge value={summary.readiness_status} />
              <StatusBadge value={summary.study_verdict} />
            </div>
          </div>
        </div>
        <div className="grid gap-px bg-line sm:grid-cols-2 xl:grid-cols-6">
          <LabMetric label="Fixed cohort" value={String(summary.fixed_cohort_count)} detail={`${summary.fixed_cohort_closed_count} closed`} />
          <LabMetric label="Train / validation" value={`${summary.train_count} / ${summary.validation_count}`} detail={`${summary.validation_closed_count} validation closed`} />
          <LabMetric label="Zone available" value={`${summary.zone_available_count}/${summary.fixed_cohort_count}`} detail={`${summary.zone_unavailable_count} unavailable`} />
          <LabMetric label="Primary conflict" value={String(summary.primary_conflict_count)} detail="Support / failed reclaim" />
          <LabMetric label="Target blocked" value={String(summary.target_path_blocked_count)} detail="Support between entry and TP" />
          <LabMetric label="Best validation read" value={summary.best_validation_variant_id || "-"} detail={summary.best_validation_verdict || "No variant"} />
        </div>
        <div className="border-t border-line p-4 text-sm">
          <div className="font-semibold text-ink">Kesimpulan checkpoint</div>
          <p className="mt-1 text-slate-700">{summary.recommended_action}</p>
          <p className="mt-2 text-xs text-slate-500">Read-only. Varian yang ditolak tetap dihitung 0R; 4h hanya konteks dan tidak memblokir sinyal.</p>
        </div>
      </section>

      <CollapsiblePanel
        title="V2.1 fixed-cohort variant comparison"
        description="Kontrol dibandingkan dengan veto konflik, jalur target bersih, dan struktur selaras. Fokus pada validation, TP yang hilang, SL yang dihindari, serta drawdown."
        defaultOpen
      >
        <V21VariantTable rows={data.variant_rows} />
      </CollapsiblePanel>

      <section className="grid gap-4 xl:grid-cols-2">
        <CollapsiblePanel title="Primary 1h structure states" description="Performa tiap interaksi support/resistance pada cohort V2.1 yang sama." defaultOpen>
          <V21BucketTable rows={data.state_rows} />
        </CollapsiblePanel>
        <CollapsiblePanel title="Target path diagnosis" description="Apakah repeated support berada di antara entry short dan target tercatat." defaultOpen>
          <V21BucketTable rows={data.target_path_rows} />
        </CollapsiblePanel>
      </section>

      <CollapsiblePanel title="4h context, diagnostic only" description="Konteks 4h dilaporkan untuk diagnosis, tetapi tidak pernah menjadi hard gate LAB-59.">
        <V21BucketTable rows={data.four_hour_context_rows} />
      </CollapsiblePanel>

      <CollapsiblePanel title="Latest fixed-cohort cases" description="Bukti per sinyal: state, jalur target, hasil realistis, dan keanggotaan tiap varian.">
        <div className="table-wrap">
          <table className="ops-table">
            <thead>
              <tr>
                <th>Time WIB</th>
                <th>Symbol</th>
                <th>Result</th>
                <th>Realistic R</th>
                <th>1h state</th>
                <th>Target path</th>
                <th>Support / clearance</th>
                <th>4h context</th>
                <th>Variant pass</th>
                <th>Detail</th>
              </tr>
            </thead>
            <tbody>
              {data.case_rows.map((row) => (
                <tr key={row.signal_id}>
                  <td>{row.signal_time_wib || fmtTime(row.signal_timestamp)}</td>
                  <td className="font-semibold">{row.symbol}</td>
                  <td><StatusBadge value={row.result_status} /></td>
                  <td>{row.realistic_realized_r == null ? "-" : `${fmtSigned(row.realistic_realized_r)}R`}</td>
                  <td>
                    <StatusBadge value={row.structure_state} />
                    <div className="mt-1 max-w-xs text-xs text-slate-500">{row.structure_reason}</div>
                  </td>
                  <td>
                    <StatusBadge value={row.target_path_status} />
                    <div className="mt-1 max-w-xs text-xs text-slate-500">{row.target_path_reason}</div>
                  </td>
                  <td>{fmtNumber(row.target_path_support_center)} / {fmtSigned(row.support_clearance_to_target_r)}R</td>
                  <td><StatusBadge value={row.four_hour_confluence_status} /></td>
                  <td className="text-xs">
                    {Object.entries(row.variant_membership)
                      .filter(([, selected]) => selected)
                      .map(([variant]) => variant.replaceAll("_", " "))
                      .join(", ") || "None"}
                  </td>
                  <td><Link className="font-semibold text-primary hover:underline" href={row.detail_href}>Open</Link></td>
                </tr>
              ))}
              {!data.case_rows.length ? (
                <tr><td colSpan={10}><EmptyState title="No V2.1 cases" detail="Belum ada fixed-cohort signal untuk ditampilkan." /></td></tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </CollapsiblePanel>
    </div>
  );
}

function V21StructureExitPanel({
  data,
  error
}: {
  data: MidShortV21StructureExitResponse | null;
  error: string | null;
}) {
  if (error) {
    return (
      <SectionCard title="LAB-60 Structure-aware Exit Path" description="Studi fixed-cohort gagal dimuat.">
        <div className="p-4 text-sm text-stale">{error}</div>
      </SectionCard>
    );
  }
  if (!data) {
    return (
      <SectionCard title="LAB-60 Structure-aware Exit Path" description="Menunggu payload studi read-only.">
        <EmptyState title="No LAB-60 data" detail="Buka ulang setelah endpoint studi tersedia." />
      </SectionCard>
    );
  }

  const summary = data.summary;
  const path = data.path_summary;
  return (
    <div className="space-y-4" id="v21-structure-exit-study">
      <section className="rounded-md border border-line bg-white">
        <div className="border-b border-line px-4 py-3">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 className="font-bold text-ink">LAB-60 V2.1 Exit Geometry + Price Path</h2>
              <p className="mt-1 text-sm text-slate-600">
                Sembilan geometry diuji pada signal yang sama. Tidak ada signal dibuang, dan target short structure selalu ditempatkan di atas support.
              </p>
            </div>
            <div className="flex gap-2">
              <StatusBadge value={summary.readiness_status} />
              <StatusBadge value={summary.study_verdict} />
            </div>
          </div>
        </div>
        <div className="grid gap-px bg-line sm:grid-cols-2 xl:grid-cols-6">
          <LabMetric label="Fixed cohort" value={String(summary.fixed_cohort_count)} detail={`${summary.fixed_cohort_closed_count} original closed`} />
          <LabMetric label="Train / validation" value={`${summary.train_count} / ${summary.validation_count}`} detail={`${summary.validation_closed_count} validation closed`} />
          <LabMetric label="Structure available" value={`${summary.zone_available_count}/${summary.fixed_cohort_count}`} detail="Causal 1h zones" />
          <LabMetric label="Complete paths" value={String(summary.path_complete_count)} detail={`${summary.path_waiting_count} waiting 4h`} />
          <LabMetric label="Best validation" value={summary.best_validation_variant_id || "-"} detail={`${fmtSigned(summary.best_validation_avg_r_delta)}R vs control`} />
          <LabMetric label="Readiness target" value={`${summary.fixed_cohort_closed_count}/${summary.readiness_target_closed}`} detail={summary.best_validation_verdict || "No comparable variant"} />
        </div>
        <div className="border-t border-line p-4 text-sm">
          <div className="font-semibold text-ink">Keputusan riset</div>
          <p className="mt-1 text-slate-700">{summary.recommended_action}</p>
          <p className="mt-2 text-xs text-slate-500">Geometry hasil studi tidak mengganti entry, target, stop, atau keputusan Signal live.</p>
        </div>
      </section>

      <CollapsiblePanel
        title="Exit geometry comparison"
        description="All/train/validation memakai signal yang sama. Delta positif belum berarti promosi; perhatikan drawdown, TP yang hilang, dan SL yang bertambah."
        defaultOpen
      >
        <V21ExitVariantTable rows={data.variant_rows} />
      </CollapsiblePanel>

      <section className="rounded-md border border-line bg-white">
        <div className="border-b border-line px-4 py-3">
          <h2 className="font-bold text-ink">Logged path sequence</h2>
          <p className="mt-1 text-sm text-slate-600">Membedakan target lebih dulu, stop lebih dulu, reversal setelah sempat profit, dan ambiguity pada candle yang sama.</p>
        </div>
        <div className="grid gap-px bg-line sm:grid-cols-2 xl:grid-cols-6">
          <LabMetric label="TP first" value={String(path.tp_first_count)} detail={`Median ${fmtNumber(path.time_to_tp_minutes_median)}m`} />
          <LabMetric label="SL first" value={String(path.sl_first_count)} detail={`Median ${fmtNumber(path.time_to_sl_minutes_median)}m`} />
          <LabMetric label="Both same candle" value={String(path.both_same_candle_count)} detail="Conservative loss-side" />
          <LabMetric label="SL after +0.50R" value={String(path.sl_after_0_50r_count)} detail={`${path.sl_after_1_00r_count} reached +1R first`} />
          <LabMetric label="TP adverse median" value={`${fmtSigned(path.tp_mae_r_median)}R`} detail={`Q90 ${fmtSigned(path.tp_mae_r_q90)}R`} />
          <LabMetric label="SL favorable median" value={`${fmtSigned(path.sl_mfe_r_median)}R`} detail={`Q90 ${fmtSigned(path.sl_mfe_r_q90)}R`} />
        </div>
        <div className="grid gap-3 border-t border-line p-4 lg:grid-cols-3">
          {Object.entries(data.research_answers).map(([key, value]) => (
            <div className="rounded border border-line bg-field/40 p-3" key={key}>
              <div className="text-xs font-semibold uppercase text-slate-500">{key.replaceAll("_", " ")}</div>
              <div className="mt-1 text-sm text-slate-700">{value}</div>
            </div>
          ))}
        </div>
      </section>

      <CollapsiblePanel
        title="Latest fixed-cohort path evidence"
        description="Control dan geometry structure ditampilkan per signal agar hasil agregat dapat dilacak kembali ke symbol dan waktu nyata."
      >
        <div className="table-wrap">
          <table className="ops-table">
            <thead>
              <tr>
                <th>Time WIB</th>
                <th>Symbol</th>
                <th>Logged result</th>
                <th>Path</th>
                <th>MFE / MAE</th>
                <th>Control</th>
                <th>Support target</th>
                <th>Resistance stop</th>
                <th>Structure both</th>
                <th>Detail</th>
              </tr>
            </thead>
            <tbody>
              {data.case_rows.map((row) => {
                const control = row.exit_results.CONTROL_LOGGED;
                const support = row.exit_results.SUPPORT_FRONT_0_10ATR;
                const resistance = row.exit_results.RESISTANCE_BACK_0_10ATR;
                const combined = row.exit_results.ZONE_ADAPTIVE_BOTH;
                return (
                  <tr key={row.signal_id}>
                    <td>{row.signal_time_wib || fmtTime(row.signal_timestamp)}</td>
                    <td className="font-semibold">{row.symbol}</td>
                    <td><StatusBadge value={row.result_status} /></td>
                    <td>
                      <StatusBadge value={row.path_sequence?.path_status || "MISSING_CONTEXT"} />
                      {row.path_sequence?.reached_0_50r_before_sl ? <div className="mt-1 text-xs text-slate-500">Reached +0.50R before later stop</div> : null}
                    </td>
                    <td>{fmtSigned(row.path_sequence?.mfe_r_to_terminal)} / {fmtSigned(row.path_sequence?.mae_r_to_terminal)}</td>
                    <td><ExitCaseRead result={control} /></td>
                    <td><ExitCaseRead result={support} /></td>
                    <td><ExitCaseRead result={resistance} /></td>
                    <td><ExitCaseRead result={combined} /></td>
                    <td><Link className="font-semibold text-primary hover:underline" href={row.detail_href}>Open</Link></td>
                  </tr>
                );
              })}
              {!data.case_rows.length ? (
                <tr><td colSpan={10}><EmptyState title="No V2.1 cases" detail="Belum ada fixed-cohort signal untuk ditampilkan." /></td></tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </CollapsiblePanel>

      <SectionCard title="Study limits" description="Batas interpretasi yang wajib dibaca sebelum memakai hasil.">
        <div className="grid gap-2 p-4 md:grid-cols-2">
          {data.limitations.map((item) => <div className="rounded border border-line bg-field/40 p-3 text-sm text-slate-700" key={item}>{item}</div>)}
        </div>
      </SectionCard>
    </div>
  );
}

function V21ExitVariantTable({ rows }: { rows: MidShortV21ExitVariant[] }) {
  return (
    <div className="table-wrap">
      <table className="ops-table">
        <thead>
          <tr>
            <th>Variant</th>
            <th>Verdict</th>
            <th>All TP / SL / Both / Neither</th>
            <th>All R / avg / DD</th>
            <th>Validation n</th>
            <th>Validation TP / SL</th>
            <th>Validation R / avg delta</th>
            <th>Validation DD / delta</th>
            <th>TP lost/gained</th>
            <th>SL avoided/added</th>
            <th>Geometry use</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.variant_id}>
              <td>
                <div className="font-semibold">{row.label}</div>
                <div className="mt-1 text-xs text-slate-500">{row.method}</div>
              </td>
              <td><StatusBadge value={row.verdict} /></td>
              <td>{row.all.tp_count} / {row.all.sl_count} / {row.all.both_count} / {row.all.neither_count}</td>
              <td>{fmtSigned(row.all.total_realistic_r)}R / {fmtSigned(row.all.avg_realistic_r)}R / {fmtSigned(row.all.max_drawdown_r)}R</td>
              <td>{row.validation.evaluated_count}/{row.validation.source_count}</td>
              <td>{row.validation.tp_count} / {row.validation.sl_count + row.validation.both_count}</td>
              <td>{fmtSigned(row.validation.total_realistic_r)}R / {fmtSigned(row.validation.avg_realistic_r_delta_vs_control)}R</td>
              <td>{fmtSigned(row.validation.max_drawdown_r)}R / {fmtSigned(row.validation.max_drawdown_delta_vs_control)}R</td>
              <td>{row.validation.tp_lost_count} / {row.validation.tp_gained_count}</td>
              <td>{row.validation.sl_avoided_count} / {row.validation.sl_added_count}</td>
              <td>{row.all.geometry_adjusted_count} adjusted / {row.all.geometry_fallback_count} fallback</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ExitCaseRead({ result }: { result?: { status: string; realistic_r?: string | number | null; target?: string | number | null; stop?: string | number | null; geometry_status: string } }) {
  if (!result) return <span className="text-slate-500">-</span>;
  return (
    <div className="min-w-32 text-xs">
      <StatusBadge value={result.status} />
      <div className="mt-1 font-semibold">{fmtSigned(result.realistic_r)}R</div>
      <div className="mt-1 text-slate-500">TP {fmtNumber(result.target)} / SL {fmtNumber(result.stop)}</div>
      <div className="mt-1 text-slate-500">{result.geometry_status.replaceAll("_", " ")}</div>
    </div>
  );
}

function LabMetric({ label, value, detail }: { label: string; value: string; detail: string }) {
  return (
    <div className="min-w-0 bg-white p-4">
      <div className="text-xs font-semibold uppercase text-slate-500">{label}</div>
      <div className="mt-1 break-words text-xl font-bold text-ink">{value}</div>
      <div className="mt-2 text-xs text-slate-500">{detail}</div>
    </div>
  );
}

function V21VariantTable({ rows }: { rows: MidShortV21StructureVariant[] }) {
  return (
    <div className="table-wrap">
      <table className="ops-table">
        <thead>
          <tr>
            <th>Variant</th>
            <th>Verdict</th>
            <th>All retained</th>
            <th>All fixed R</th>
            <th>Train avg delta</th>
            <th>Validation retained</th>
            <th>Validation TP lost / SL avoided</th>
            <th>Validation fixed R</th>
            <th>Validation avg delta</th>
            <th>Validation DD</th>
            <th>Top symbol</th>
            <th>Rule</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.variant_id}>
              <td>
                <div className="font-semibold">{row.label}</div>
                <div className="text-xs text-slate-500">{row.variant_id}</div>
              </td>
              <td><StatusBadge value={row.verdict} /></td>
              <td>{row.all.entered_count}/{row.all.source_count} ({fmtNumber(row.all.retention_pct)}%)</td>
              <td>{fmtSigned(row.all.fixed_total_realistic_r)}R</td>
              <td>{fmtSigned(row.train.fixed_avg_r_delta_vs_baseline)}R</td>
              <td>{row.validation.entered_closed_count}/{row.validation.source_closed_count}</td>
              <td>{row.validation.tp_lost_count} / {row.validation.sl_avoided_count}</td>
              <td>{fmtSigned(row.validation.fixed_total_realistic_r)}R</td>
              <td>{fmtSigned(row.validation.fixed_avg_r_delta_vs_baseline)}R</td>
              <td>{fmtSigned(row.validation.fixed_max_drawdown_r)}R</td>
              <td>{row.validation.top_symbol || "-"} ({fmtNumber(row.validation.top_symbol_share_pct)}%)</td>
              <td className="max-w-sm text-xs text-slate-600">{row.selection_rule}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function V21BucketTable({ rows }: { rows: MidShortStructureStateRow[] }) {
  return (
    <div className="table-wrap">
      <table className="ops-table">
        <thead>
          <tr>
            <th>Bucket</th>
            <th>All sample</th>
            <th>TP / SL</th>
            <th>Avg realistic R</th>
            <th>Validation sample</th>
            <th>Validation avg R</th>
            <th>Top symbol</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.bucket}>
              <td><StatusBadge value={row.bucket} /></td>
              <td>{row.all.sample_count}</td>
              <td>{row.all.tp_count} / {row.all.sl_count}</td>
              <td>{fmtSigned(row.all.realistic_avg_r_closed)}R</td>
              <td>{row.validation.sample_count}</td>
              <td>{fmtSigned(row.validation.realistic_avg_r_closed)}R</td>
              <td>{row.validation.top_symbol || "-"} ({fmtNumber(row.validation.top_symbol_share_pct)}%)</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function MidShortRefinementPanel({ data }: { data: SignalQualityMidShortRefinement | null }) {
  if (!data) {
    return (
      <SectionCard title="Main Research: MID_SHORT 1h Refinement" description="Belum ada payload refinement dari API.">
        <EmptyState title="No MID_SHORT 1h research data" detail="Refresh setelah backend Quality Lab mengirim mid_short_1h_refinement." />
      </SectionCard>
    );
  }

  const baseline = data.baseline;
  const bestRows = data.promising_filters.length ? data.promising_filters : data.top_filters.slice(0, 6);

  return (
    <SectionCard
      title="Main Research: MID_SHORT 1h Refinement"
      description="Fokus aktif: mencari filter read-only yang bisa mengurangi SL dan realistic R bocor pada MID_SHORT 1h. Ini belum mengubah rule live."
    >
      <div className="grid gap-3 p-4 md:grid-cols-2 xl:grid-cols-6">
        <Insight label="Readiness" value={labelFor(data.summary.readiness)} />
        <Insight label="Source" value={`${data.summary.source_count} signal`} />
        <Insight label="Baseline ideal" value={`${fmtSigned(baseline.total_r_closed)}R`} />
        <Insight label="Baseline realistic" value={`${fmtSigned(baseline.realistic_total_r_closed)}R`} />
        <Insight label="TP / SL" value={`${baseline.tp_count ?? 0} / ${baseline.sl_count ?? 0}`} />
        <Insight label="SL share" value={baseline.sl_share_pct == null ? "-" : `${fmtNumber(baseline.sl_share_pct)}%`} />
      </div>

      {data.shadow_monitor ? (
        <div className="border-t border-line p-4">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
            <div>
              <div className="font-bold text-ink">Shadow Filter Monitor</div>
              <div className="text-sm text-slate-600">
                {data.shadow_filter?.label || "MID_SHORT 1h fill good + range/ATR <= 1.25"}.
                Monitor read-only, belum mengubah rule live.
              </div>
            </div>
            <StatusBadge value="READ_ONLY_SHADOW" />
          </div>
          <div className="grid gap-3 md:grid-cols-3">
            <Insight label="Shadow pass" value={`${data.shadow_monitor.pass_count} signal`} />
            <Insight label="Shadow fail" value={`${data.shadow_monitor.fail_count} signal`} />
            <Insight label="Unavailable" value={`${data.shadow_monitor.unavailable_count} signal`} />
          </div>
          <div className="mt-3">
            <ShadowMonitorTable monitor={data.shadow_monitor} />
          </div>
        </div>
      ) : null}

      <div className="grid gap-4 border-t border-line p-4 xl:grid-cols-[1fr_2fr]">
        <div className="space-y-3">
          <div className="rounded border border-line bg-field/50 p-3 text-sm">
            <div className="font-bold text-ink">Rencana mitigasi sekarang</div>
            <ul className="mt-3 list-disc space-y-2 pl-5 text-slate-700">
              {data.mitigation_plan.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </div>
          <div className="rounded border border-line bg-field/50 p-3 text-sm">
            <div className="font-bold text-ink">Guardrail</div>
            <ul className="mt-3 list-disc space-y-2 pl-5 text-slate-700">
              {data.guardrails.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </div>
        </div>

        <div>
          <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
            <div>
              <div className="font-bold text-ink">Filter paling layak dipantau</div>
              <div className="text-sm text-slate-600">Urutan berdasarkan realistic R delta, SL share delta, sample, dan concentration.</div>
            </div>
            <StatusBadge value={data.summary.readiness} />
          </div>
          <MidShortRefinementTable rows={bestRows} />
        </div>
      </div>

      <CollapsiblePanel
        title="Rejected / weak filters"
        description="Filter yang saat ini memperburuk baseline atau belum punya edge jelas. Ini penting supaya kita tidak promosi asumsi yang salah."
      >
        <MidShortRefinementTable rows={data.rejected_filters.slice(0, 12)} />
      </CollapsiblePanel>
    </SectionCard>
  );
}

function ShadowMonitorTable({ monitor }: { monitor: NonNullable<SignalQualityMidShortRefinement["shadow_monitor"]> }) {
  const rows = [
    { status: "SHADOW_PASS", count: monitor.pass_count, perf: monitor.pass, read: "Filter cocok: fill good dan range/ATR tidak overextended." },
    { status: "SHADOW_FAIL", count: monitor.fail_count, perf: monitor.fail, read: "Filter gagal: cost/range masih perlu dihindari." },
    { status: "SHADOW_UNAVAILABLE", count: monitor.unavailable_count, perf: monitor.unavailable, read: "Evidence belum cukup untuk menilai filter." }
  ];

  return (
    <div className="table-wrap">
      <table className="ops-table">
        <thead>
          <tr>
            <th>Status</th>
            <th>Sample</th>
            <th>TP / SL</th>
            <th>Realistic R</th>
            <th>Avg realistic</th>
            <th>SL share</th>
            <th>Max DD</th>
            <th>Read</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.status}>
              <td><StatusBadge value={row.status} /></td>
              <td>{row.count}</td>
              <td>{row.perf.tp_count ?? 0} / {row.perf.sl_count ?? 0}</td>
              <td className={Number(row.perf.realistic_total_r_closed || 0) >= 0 ? "text-ready" : "text-stale"}>{fmtSigned(row.perf.realistic_total_r_closed)}R</td>
              <td>{fmtSigned(row.perf.realistic_avg_r_closed)}R</td>
              <td>{row.perf.sl_share_pct == null ? "-" : `${fmtNumber(row.perf.sl_share_pct)}%`}</td>
              <td>{fmtSigned(row.perf.max_realistic_drawdown_r)}R</td>
              <td className="max-w-md text-sm text-slate-600">{row.read}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function MidShortRefinementTable({ rows }: { rows: SignalQualityMidShortRefinementRow[] }) {
  return (
    <div className="table-wrap">
      <table className="ops-table">
        <thead>
          <tr>
            <th>Filter</th>
            <th>Verdict</th>
            <th>Sample</th>
            <th>TP / SL</th>
            <th>Realistic R</th>
            <th>Avg Delta</th>
            <th>SL Delta</th>
            <th>Max DD</th>
            <th>Top symbol</th>
            <th>Read</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.filter_id}>
              <td>
                <div className="font-semibold">{row.label}</div>
                <div className="text-xs text-slate-500">{row.expression}</div>
              </td>
              <td><StatusBadge value={row.verdict} /></td>
              <td>
                <div>{row.sample_count} / {row.source_count}</div>
                <div className="text-xs text-slate-500">keep {fmtNumber(row.sample_retention_pct)}%, miss {fmtNumber(row.missing_data_pct)}%</div>
              </td>
              <td>{row.tp_count ?? 0} / {row.sl_count ?? 0}</td>
              <td className={Number(row.realistic_total_r_closed || 0) >= 0 ? "text-ready" : "text-stale"}>{fmtSigned(row.realistic_total_r_closed)}R</td>
              <td>{fmtSigned(row.realistic_avg_r_delta_vs_baseline)}R</td>
              <td>{fmtSigned(row.sl_share_delta_vs_baseline)}%</td>
              <td>{fmtSigned(row.max_realistic_drawdown_r)}R</td>
              <td>{row.top_symbol} ({fmtNumber(row.top_symbol_share_pct)}%)</td>
              <td className="max-w-md text-sm text-slate-600">
                <div>{row.mitigation_read}</div>
                {row.risk_notes?.length ? (
                  <div className="mt-1 text-xs text-stale">{row.risk_notes.join(" ")}</div>
                ) : null}
              </td>
            </tr>
          ))}
          {!rows.length && (
            <tr>
              <td colSpan={10}>
                <EmptyState title="No refinement rows" detail="Belum ada filter MID_SHORT 1h sesuai sample minimum." />
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

function V2ProfitLossResearchPanel({ data }: { data: SignalQualityProfitLossResearch | null }) {
  if (!data) {
    return (
      <SectionCard title="V2 Profit/Loss Research" description="Belum ada payload riset V2 dari API.">
        <EmptyState title="No V2 research data" detail="Refresh setelah backend Quality Lab mengirim profit_loss_research." />
      </SectionCard>
    );
  }

  const summary = data.summary;
  const dragRows = [
    ...data.realistic_drag.by_stage.slice(0, 4),
    ...data.realistic_drag.by_timeframe.slice(0, 4),
    ...data.realistic_drag.by_fill_quality.slice(0, 4),
    ...data.realistic_drag.by_symbol.slice(0, 8)
  ].slice(0, 16);

  return (
    <SectionCard
      title="V2 Profit/Loss Research"
      description="Membaca kenapa V2 TP/SL dan kenapa realistic R bisa beda dari ideal R. Ini riset read-only, bukan perubahan rule."
    >
      <div className="grid gap-3 p-4 md:grid-cols-3 xl:grid-cols-6">
        <Insight label="Read" value={labelFor(data.read)} />
        <Insight label="Ideal closed" value={`${fmtSigned(summary.total_r_closed)}R`} />
        <Insight label="Realistic closed" value={`${fmtSigned(summary.realistic_total_r_closed)}R`} />
        <Insight label="Penalty" value={`${fmtSigned(summary.realism_penalty_r_closed)}R`} />
        <Insight label="TP / SL" value={`${summary.tp_count ?? 0} / ${summary.sl_count ?? 0}`} />
        <Insight label="SL share" value={summary.sl_share_pct == null ? "-" : `${fmtNumber(summary.sl_share_pct)}%`} />
      </div>

      <div className="grid gap-4 border-t border-line p-4 xl:grid-cols-2">
        <div>
          <div className="mb-2 text-sm font-bold">Variabel yang sering membedakan TP vs SL</div>
          <ProfitLossDriverTable rows={data.tp_drivers.slice(0, 8)} />
        </div>
        <div>
          <div className="mb-2 text-sm font-bold">Realistic drag terbesar</div>
          <RealisticDragTable rows={dragRows} />
        </div>
      </div>

      <div className="border-t border-line">
        <div className="px-4 py-3 text-sm font-bold">Stage + timeframe V2</div>
        <ProfitLossLaneTable rows={data.lane_rows} />
      </div>
    </SectionCard>
  );
}

function OtherLaneResearchQueue({ data }: { data: SignalQualityProfitLossResearch | null }) {
  const targets = [
    {
      stage: "MID_LONG",
      timeframe: "1h",
      priority: "Prioritas 1",
      read: "Pembanding paling dekat dengan MID_SHORT 1h. Cocok untuk cek apakah long 1h punya pattern profit/loss yang lebih stabil."
    },
    {
      stage: "EARLY_LONG",
      timeframe: "15m",
      priority: "Prioritas 2",
      read: "Menguji impulse fresh long. Fokusnya bukan banyak signal, tapi apakah volume/taker/OI awal benar-benar memisahkan TP dan SL."
    },
    {
      stage: "EARLY_SHORT",
      timeframe: "15m",
      priority: "Prioritas 3",
      read: "Menguji impulse fresh short. Berguna untuk tahu apakah short cepat hanya noise atau punya kondisi awal yang bisa dipisahkan."
    },
    {
      stage: "MID_LONG",
      timeframe: "15m",
      priority: "Pantau",
      read: "Lane ini sering lebih noisy. Tetap dipantau untuk tahu apakah problemnya direction, cost, atau entry terlalu telat."
    }
  ];

  const laneRows = data?.lane_rows || [];
  const rows = targets.map((target) => ({
    ...target,
    lane: laneRows.find((row) => row.stage === target.stage && row.timeframe === target.timeframe)
  }));

  return (
    <SectionCard
      title="Other Lane Research Queue"
      description="Sambil menunggu MID_SHORT 1h bertambah sample, ini lane lain yang paling masuk akal diteliti. Panel ini tidak mengubah rule live."
    >
      <div className="grid gap-3 p-4 md:grid-cols-2 xl:grid-cols-4">
        {rows.map((row) => {
          const href = `/signal-quality-lab?stage=${row.stage}&timeframe=${row.timeframe}&position_lock=false`;
          const dedicatedHref = row.stage === "MID_LONG" && row.timeframe === "1h" ? "/mid-long-research-study" : href;
          return (
            <div key={`${row.stage}-${row.timeframe}`} className="flex min-h-full flex-col rounded-lg border border-line bg-field/40 p-4 text-sm">
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div>
                  <div className="text-xs font-semibold uppercase text-slate-500">{row.priority}</div>
                  <div className="mt-1 text-lg font-bold text-ink">{labelFor(row.stage)} {row.timeframe}</div>
                </div>
                <StatusBadge value={row.lane?.realistic_read || "WAITING_SAMPLE"} />
              </div>

              <div className="mt-4 grid gap-2">
                <Insight label="Sample" value={row.lane ? String(row.lane.sample_count) : "-"} />
                <Insight label="TP / SL / Open" value={row.lane ? `${row.lane.tp_count ?? 0} / ${row.lane.sl_count ?? 0} / ${row.lane.open_count ?? 0}` : "-"} />
                <Insight
                  label="Realistic R"
                  value={row.lane ? `${fmtSigned(row.lane.realistic_total_r_closed)}R` : "-"}
                />
                <Insight
                  label="SL share"
                  value={row.lane?.sl_share_pct == null ? "-" : `${fmtNumber(row.lane.sl_share_pct)}%`}
                />
              </div>

              <p className="mt-4 flex-1 text-slate-600">{row.read}</p>

              {row.lane?.top_evidence_gap ? (
                <div className="mt-3 rounded border border-line bg-white p-3">
                  <div className="text-xs font-semibold uppercase text-slate-500">Evidence gap</div>
                  <div className="mt-1 font-semibold">{row.lane.top_evidence_gap.label}</div>
                  <div className="text-xs text-slate-500">TP-SL median delta {fmtSigned(row.lane.top_evidence_gap.delta_tp_minus_sl)}</div>
                </div>
              ) : null}

              <div className="mt-4 flex flex-wrap gap-2">
                <Link className="rounded-md border border-line bg-white px-3 py-2 font-semibold hover:bg-field" href={dedicatedHref}>
                  Open lane
                </Link>
                <Link className="rounded-md border border-line bg-white px-3 py-2 font-semibold hover:bg-field" href={`${href}&min_sample=10`}>
                  Stricter sample
                </Link>
              </div>
            </div>
          );
        })}
      </div>
      <div className="border-t border-line p-4 text-sm text-slate-600">
        Urutan ini sengaja masih read-only: kita cari lane yang punya sample cukup, realistic R tidak bocor parah, SL share bisa turun, dan evidence gap lebih jelas dari baseline. Kalau ada lane bagus, baru dibuat deep-dive terpisah seperti MID_SHORT.
      </div>
    </SectionCard>
  );
}

function ProfitLossDriverTable({ rows }: { rows: SignalQualityProfitLossResearch["tp_drivers"] }) {
  return (
    <div className="table-wrap">
      <table className="ops-table">
        <thead>
          <tr>
            <th>Evidence</th>
            <th>Flag</th>
            <th>TP / SL</th>
            <th>TP median</th>
            <th>SL median</th>
            <th>Delta</th>
            <th>Read</th>
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
              <td>{row.tp_count} / {row.sl_count}</td>
              <td>{fmtNumber(row.tp_median)}</td>
              <td>{fmtNumber(row.sl_median)}</td>
              <td>{fmtSigned(row.delta_tp_minus_sl)}</td>
              <td className="max-w-sm text-sm text-slate-600">{row.read}</td>
            </tr>
          ))}
          {!rows.length && (
            <tr>
              <td colSpan={7}>
                <EmptyState title="Belum ada TP driver bersih" detail="TP dan SL belum punya gap median evidence yang cukup menurut min sample." />
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

function ProfitLossLaneTable({ rows }: { rows: SignalQualityProfitLossLane[] }) {
  return (
    <div className="table-wrap">
      <table className="ops-table">
        <thead>
          <tr>
            <th>Lane</th>
            <th>Read</th>
            <th>Sample</th>
            <th>TP / SL / Open</th>
            <th>Ideal R</th>
            <th>Realistic R</th>
            <th>Penalty</th>
            <th>SL share</th>
            <th>Evidence gap</th>
            <th>Worst symbol</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={`${row.stage}-${row.timeframe}`}>
              <td>
                <div className="font-semibold">{labelFor(row.stage)}</div>
                <div className="text-xs text-slate-500">{row.timeframe}</div>
              </td>
              <td><StatusBadge value={row.realistic_read} /></td>
              <td>{row.sample_count}</td>
              <td>{row.tp_count} / {row.sl_count} / {row.open_count}</td>
              <td>{fmtSigned(row.total_r_closed)}R</td>
              <td className={Number(row.realistic_total_r_closed || 0) >= 0 ? "text-ready" : "text-stale"}>{fmtSigned(row.realistic_total_r_closed)}R</td>
              <td>{fmtSigned(row.realism_penalty_r_closed)}R</td>
              <td>{row.sl_share_pct == null ? "-" : `${fmtNumber(row.sl_share_pct)}%`}</td>
              <td>
                {row.top_evidence_gap ? (
                  <div>
                    <div className="font-semibold">{row.top_evidence_gap.label}</div>
                    <div className="text-xs text-slate-500">{fmtSigned(row.top_evidence_gap.delta_tp_minus_sl)}</div>
                  </div>
                ) : "-"}
              </td>
              <td>
                {row.top_loss_symbol ? (
                  <div>
                    <div className="font-semibold">{row.top_loss_symbol.symbol}</div>
                    <div className="text-xs text-slate-500">{fmtSigned(row.top_loss_symbol.realistic_total_r_closed)}R realistic</div>
                  </div>
                ) : "-"}
              </td>
            </tr>
          ))}
          {!rows.length && (
            <tr>
              <td colSpan={10}>
                <EmptyState title="No lane rows" detail="Belum ada Signal untuk filter ini." />
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

function RealisticDragTable({ rows }: { rows: SignalQualityRealisticDragRow[] }) {
  return (
    <div className="table-wrap">
      <table className="ops-table">
        <thead>
          <tr>
            <th>Bucket</th>
            <th>Read</th>
            <th>Sample</th>
            <th>Ideal</th>
            <th>Realistic</th>
            <th>Penalty</th>
            <th>Avg penalty</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={`${row.dimension}-${row.bucket}`}>
              <td>
                <div className="font-semibold">{labelFor(row.bucket)}</div>
                <div className="text-xs text-slate-500">{row.dimension}</div>
              </td>
              <td><StatusBadge value={row.realistic_read} /></td>
              <td>{row.sample_count}</td>
              <td>{fmtSigned(row.total_r_closed)}R</td>
              <td className={Number(row.realistic_total_r_closed || 0) >= 0 ? "text-ready" : "text-stale"}>{fmtSigned(row.realistic_total_r_closed)}R</td>
              <td>{fmtSigned(row.realism_penalty_r_closed)}R</td>
              <td>{fmtSigned(row.avg_penalty_r_closed)}R</td>
            </tr>
          ))}
          {!rows.length && (
            <tr>
              <td colSpan={7}>
                <EmptyState title="No drag rows" detail="Belum ada bucket realistic drag yang bisa dibaca." />
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

function ArchiveLink({ href, title, detail }: { href: string; title: string; detail: string }) {
  return (
    <Link className="rounded border border-line bg-field/50 p-4 text-sm hover:bg-white" href={href}>
      <div className="font-bold text-ink">{title}</div>
      <p className="mt-2 text-slate-600">{detail}</p>
    </Link>
  );
}

function MarketRegimeStudy({ data }: { data: MarketRegimeStudyResponse | null }) {
  const lanes = Object.values(data?.lanes || {});
  if (!lanes.length) {
    return (
      <EmptyState
        title="Market Regime Study belum tersedia"
        detail="Artifact regime belum ada. Jalankan run_market_regime_study_v1.py di VPS untuk mengisi hasilnya."
      />
    );
  }

  return (
    <div className="space-y-4">
      <div className="grid gap-3 p-4 md:grid-cols-2">
        {lanes.map((lane) => (
          <div key={lane.lane} className="rounded border border-line bg-field/50 p-3 text-sm">
            <div className="flex flex-wrap items-center gap-2">
              <div className="font-bold text-ink">{lane.lane}</div>
              <StatusBadge value={lane.direction === "SHORT" ? "BEARISH_CONTEXT" : "BULLISH_CONTEXT"} />
            </div>
            <div className="mt-2 grid gap-2 md:grid-cols-4">
              <Insight label="Sample" value={String(lane.sample_count)} />
              <Insight label="TP / SL" value={`${lane.baseline.tp_count ?? 0} / ${lane.baseline.sl_count ?? 0}`} />
              <Insight label="Avg R" value={`${fmtSigned(lane.baseline.avg_r_closed)}R`} />
              <Insight label="Total R" value={`${fmtSigned(lane.baseline.total_r_closed)}R`} />
            </div>
            <p className="mt-3 text-slate-600">{lane.interpretation}</p>
          </div>
        ))}
      </div>

      <section className="grid gap-4 xl:grid-cols-2">
        <div>
          <div className="px-4 pb-2 text-sm font-bold">Helpful regimes</div>
          <MarketRegimeTable rows={lanes.flatMap((lane) => lane.top_helpful_regimes.map((row) => ({ ...row, lane: lane.lane })))} />
        </div>
        <div>
          <div className="px-4 pb-2 text-sm font-bold">Harmful regimes</div>
          <MarketRegimeTable rows={lanes.flatMap((lane) => lane.top_harmful_regimes.map((row) => ({ ...row, lane: lane.lane })))} />
        </div>
      </section>
    </div>
  );
}

function MarketRegimeTable({ rows }: { rows: (MarketRegimeStudyBucket & { lane: string })[] }) {
  return (
    <div className="table-wrap">
      <table className="ops-table">
        <thead>
          <tr>
            <th>Lane</th>
            <th>Regime</th>
            <th>Verdict</th>
            <th>Sample</th>
            <th>TP / SL</th>
            <th>Avg R</th>
            <th>Delta</th>
            <th>Win Delta</th>
            <th>Catatan</th>
          </tr>
        </thead>
        <tbody>
          {rows.slice(0, 12).map((row) => (
            <tr key={`${row.lane}-${row.dimension}-${row.bucket}`}>
              <td className="font-semibold">{row.lane}</td>
              <td>
                <div className="font-semibold">{labelFor(row.bucket)}</div>
                <div className="text-xs text-slate-500">{row.dimension}</div>
              </td>
              <td><StatusBadge value={row.verdict} /></td>
              <td>{row.sample_count}</td>
              <td>{row.tp_count ?? 0} / {row.sl_count ?? 0}</td>
              <td>{fmtSigned(row.avg_r_closed)}R</td>
              <td>{fmtSigned(row.avg_r_delta_vs_baseline)}R</td>
              <td>{fmtSigned(row.winrate_delta_vs_baseline)}%</td>
              <td className="max-w-md text-sm text-slate-600">{row.note}</td>
            </tr>
          ))}
          {!rows.length && (
            <tr>
              <td colSpan={9}>
                <EmptyState title="No regime rows" detail="Belum ada bucket regime yang memenuhi sample minimum." />
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

function CalibrationLab({ data }: { data: SignalCalibrationLabResponse | null }) {
  if (!data) {
    return (
      <EmptyState
        title="Archived calibration belum tersedia"
        detail="Endpoint calibration belum mengembalikan data. Ini arsip V3/V4, bukan fokus aktif V2 sekarang."
      />
    );
  }
  const activeLanes = data.lanes.filter((lane) => lane.sample_count > 0);
  const readyCount = data.lanes.filter((lane) => lane.status === "READY_FOR_CALIBRATION").length;
  const v3CandidateCount = data.top_candidates.filter((row) => row.promotion_status === "V3_CANDIDATE").length;
  const monitorCount = data.top_candidates.filter((row) => row.promotion_status === "MONITOR_MORE").length;
  const overfitCount = data.top_candidates.filter((row) => row.promotion_status === "REJECT_OVERFIT").length;
  const priorityLanes = [
    priorityLane(data, "EARLY_LONG", "15m", "Prioritas 1", "Momentum fresh long 15m yang saat ini validation-nya paling sehat."),
    priorityLane(data, "MID_SHORT", "1h", "Prioritas 2", "Setup short 1h yang masih paling layak dipantau untuk filter lanjutan.")
  ];

  return (
    <div className="space-y-4">
      <div className="grid gap-3 p-4 md:grid-cols-5">
        <Insight label="Active lanes" value={`${activeLanes.length}/16`} />
        <Insight label="Ready lanes" value={String(readyCount)} />
        <Insight label="Archived V3 candidates" value={String(v3CandidateCount)} />
        <Insight label="Monitor more" value={String(monitorCount)} />
        <Insight label="Reject overfit" value={String(overfitCount)} />
      </div>
      <div className="grid gap-4 px-4 xl:grid-cols-2">
        {priorityLanes.map((lane) => (
          <PriorityCalibrationCard key={`${lane.stage}-${lane.timeframe}`} lane={lane} />
        ))}
      </div>
      <div className="grid gap-4 px-4 md:grid-cols-2 xl:grid-cols-4">
        {activeLanes.slice(0, 8).map((lane) => (
          <CalibrationLaneCard key={lane.lane} lane={lane} />
        ))}
      </div>
      <div className="border-t border-line">
        <div className="px-4 py-3 text-sm font-bold">Top calibration candidates</div>
        <CalibrationCandidateTable rows={data.top_candidates.slice(0, 18)} />
      </div>
    </div>
  );
}

function priorityLane(
  data: SignalCalibrationLabResponse,
  stage: string,
  timeframe: string,
  priority: string,
  reason: string
): SignalCalibrationLane & { priority: string; priorityReason: string; bestFilter?: SignalCalibrationCandidate } {
  const lane = data.lanes.find((item) => item.stage === stage && item.timeframe === timeframe);
  const fallback: SignalCalibrationLane = {
    lane: `${stage}_${timeframe}`,
    stage,
    timeframe,
    sample_count: 0,
    train_count: 0,
    validation_count: 0,
    split_method: "chronological_70_30",
    status: "NO_DATA",
    baseline_all: emptyCalibrationPerf(),
    baseline_train: emptyCalibrationPerf(),
    baseline_validation: emptyCalibrationPerf(),
    filter_candidates: []
  };
  const selected = lane || fallback;
  return {
    ...selected,
    priority,
    priorityReason: reason,
    bestFilter: bestPriorityFilter(selected)
  };
}

function emptyCalibrationPerf() {
  return {
    signals_evaluated: 0,
    open_count: 0,
    waiting_count: 0,
    tp_count: 0,
    sl_count: 0,
    both_hit_count: 0,
    closed_count: 0,
    total_r_closed: 0,
    open_unrealized_r: 0,
    total_r_with_open: 0,
    fixed_risk_return_pct_1pct_closed: 0,
    fixed_risk_return_pct_1pct_with_open: 0,
    sample_count: 0,
    top_symbol: "-",
    top_symbol_count: 0
  };
}

function bestPriorityFilter(lane: SignalCalibrationLane): SignalCalibrationCandidate | undefined {
  return [...lane.filter_candidates].sort((a, b) => {
    const promotionRank = (value: string) => ({
      V3_CANDIDATE: 4,
      MONITOR_MORE: 3,
      WEAK_FILTER: 2,
      REJECT_OVERFIT: 1
    }[value] ?? 0);
    const rank = (value: string) => ({
      VALIDATION_PROMISING: 5,
      REDUCES_DAMAGE: 4,
      NO_CLEAR_EDGE: 3,
      TRAIN_ONLY_OVERFIT: 2,
      VALIDATION_WORSE: 1,
      NEED_MORE_SAMPLE: 0
    }[value] ?? -1);
    const promotionDelta = promotionRank(b.promotion_status) - promotionRank(a.promotion_status);
    if (promotionDelta) return promotionDelta;
    const rankDelta = rank(b.verdict) - rank(a.verdict);
    if (rankDelta) return rankDelta;
    return Number(b.validation.avg_r_delta_vs_baseline || -999) - Number(a.validation.avg_r_delta_vs_baseline || -999);
  })[0];
}

function PriorityCalibrationCard({
  lane
}: {
  lane: SignalCalibrationLane & { priority: string; priorityReason: string; bestFilter?: SignalCalibrationCandidate };
}) {
  const best = lane.bestFilter;
  return (
    <div className="rounded border border-blue-200 bg-blue-50/50 p-4 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <div className="font-bold text-ink">{lane.priority}: {labelFor(lane.stage)} {lane.timeframe}</div>
        <StatusBadge value={lane.status} />
      </div>
      <p className="mt-2 text-slate-600">{lane.priorityReason}</p>
      <div className="mt-4 grid gap-2 md:grid-cols-4">
        <Insight label="Sample" value={`${lane.sample_count} total`} />
        <Insight label="Train / validation" value={`${lane.train_count} / ${lane.validation_count}`} />
        <Insight label="Baseline total" value={`${fmtSigned(lane.baseline_all.total_r_closed)}R`} />
        <Insight label="Validation avg" value={`${fmtSigned(lane.baseline_validation.avg_r_closed)}R`} />
      </div>
      <div className="mt-4 rounded border border-line bg-white p-3">
        <div className="flex flex-wrap items-center gap-2">
          <div className="font-semibold">Archived filter read</div>
          <StatusBadge value={best?.verdict || "NO_FILTER"} />
          {best ? <StatusBadge value={best.promotion_status} /> : null}
        </div>
        {best ? (
          <div className="mt-2 grid gap-2 md:grid-cols-[1.4fr_.8fr_1fr_1fr_1.2fr]">
            <Insight label="Filter" value={best.label} />
            <Insight label="Promotion score" value={`${best.promotion_score}/7`} />
            <Insight label="Validation closed" value={`${best.validation.closed_count} rows`} />
            <Insight label="Validation delta" value={`${fmtSigned(best.validation.avg_r_delta_vs_baseline)}R avg`} />
            <Insight label="Top symbol" value={`${best.validation.top_symbol} (${fmtNumber(best.validation.top_symbol_share_pct)}%)`} />
          </div>
        ) : (
          <p className="mt-2 text-slate-600">Belum ada filter yang bisa dibaca untuk lane ini.</p>
        )}
        {best?.promotion_reasons?.length ? (
          <ul className="mt-3 list-disc space-y-1 pl-5 text-slate-600">
            {best.promotion_reasons.slice(0, 3).map((reason) => (
              <li key={reason}>{reason}</li>
            ))}
          </ul>
        ) : null}
        <p className="mt-3 text-slate-600">
          Archive read: {promotionAction(best?.promotion_status)}
        </p>
      </div>
    </div>
  );
}

function CalibrationLaneCard({ lane }: { lane: SignalCalibrationLane }) {
  return (
    <div className="rounded border border-line bg-field/50 p-3 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <div className="font-bold text-ink">{labelFor(lane.stage)} {lane.timeframe}</div>
        <StatusBadge value={lane.status} />
      </div>
      <div className="mt-3 grid gap-2">
        <Insight label="Train / validation" value={`${lane.train_count} / ${lane.validation_count}`} />
        <Insight label="Baseline all" value={`${fmtSigned(lane.baseline_all.total_r_closed)}R`} />
        <Insight label="Validation avg R" value={`${fmtSigned(lane.baseline_validation.avg_r_closed)}R`} />
      </div>
    </div>
  );
}

function CalibrationCandidateTable({ rows }: { rows: SignalCalibrationCandidate[] }) {
  return (
    <div className="table-wrap">
      <table className="ops-table">
        <thead>
          <tr>
            <th>Setup</th>
            <th>Filter</th>
            <th>Promotion</th>
            <th>Verdict</th>
            <th>Train</th>
            <th>Train delta</th>
            <th>Validation</th>
            <th>Validation delta</th>
            <th>SL share delta</th>
            <th>Top symbol</th>
            <th>Catatan</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={`${row.stage}-${row.timeframe}-${row.filter_id}`}>
              <td>
                <div className="font-semibold">{labelFor(row.stage || "-")}</div>
                <div className="text-xs text-slate-500">{row.timeframe}</div>
              </td>
              <td>
                <div className="font-semibold">{row.label}</div>
                <div className="text-xs text-slate-500">{row.expression}</div>
              </td>
              <td>
                <StatusBadge value={row.promotion_status} />
                <div className="mt-1 text-xs text-slate-500">Score {row.promotion_score}/7</div>
              </td>
              <td><StatusBadge value={row.verdict} /></td>
              <td>{row.train.closed_count} closed, {fmtSigned(row.train.total_r_closed)}R</td>
              <td>{fmtSigned(row.train.avg_r_delta_vs_baseline)}R avg</td>
              <td>{row.validation.closed_count} closed, {fmtSigned(row.validation.total_r_closed)}R</td>
              <td>{fmtSigned(row.validation.avg_r_delta_vs_baseline)}R avg</td>
              <td>{fmtSigned(row.validation.sl_share_delta_vs_baseline)}%</td>
              <td>{row.validation.top_symbol} ({fmtNumber(row.validation.top_symbol_share_pct)}%)</td>
              <td className="max-w-md text-sm text-slate-600">
                <div>{row.note}</div>
                {row.promotion_reasons?.length ? (
                  <div className="mt-1 text-xs">{row.promotion_reasons.slice(0, 2).join(" ")}</div>
                ) : null}
              </td>
            </tr>
          ))}
          {!rows.length && (
            <tr>
              <td colSpan={11}>
                <EmptyState title="No calibration candidates" detail="Belum ada closed sample cukup untuk train/validation." />
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

function promotionAction(status?: string) {
  if (status === "V3_CANDIDATE") {
    return "arsip V3 pernah menandai ini sebagai kandidat riset, tetapi fokus aktif sekarang tetap V2 realistic research.";
  }
  if (status === "MONITOR_MORE") {
    return "pantau lagi. Ada bagian yang menarik, tapi sample atau separation belum cukup untuk dipromosikan.";
  }
  if (status === "REJECT_OVERFIT") {
    return "jangan dipakai. Filter bagus di train tapi gagal bertahan di validation.";
  }
  if (status === "WEAK_FILTER") {
    return "lemah untuk saat ini. Jangan dipromosikan sampai validation membaik.";
  }
  return "belum ada filter yang layak dibaca untuk lane ini.";
}

function FilterStudyTable({ rows }: { rows: SignalFilterStudyRow[] }) {
  return (
    <div className="table-wrap">
      <table className="ops-table">
        <thead>
          <tr>
            <th>Filter</th>
            <th>Verdict</th>
            <th>Sample</th>
            <th>TP / SL / Open</th>
            <th>Winrate</th>
            <th>Total R</th>
            <th>Avg R Δ</th>
            <th>SL share Δ</th>
            <th>Max DD</th>
            <th>Top symbol</th>
            <th>Catatan</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.filter_id}>
              <td>
                <div className="font-semibold">{row.label}</div>
                <div className="text-xs text-slate-500">{row.expression}</div>
              </td>
              <td><StatusBadge value={row.verdict} /></td>
              <td>{row.sample_count} / {row.source_count} ({fmtNumber(row.sample_retention_pct)}%)</td>
              <td>{row.tp_count} / {row.sl_count} / {row.open_count}</td>
              <td>{row.winrate_pct == null ? "-" : `${fmtNumber(row.winrate_pct)}%`}</td>
              <td>{fmtSigned(row.total_r_closed)}R</td>
              <td>{fmtSigned(row.avg_r_delta_vs_baseline)}R</td>
              <td>{fmtSigned(row.sl_share_delta_vs_baseline)}%</td>
              <td>{fmtSigned(row.max_drawdown_r)}R</td>
              <td>{row.top_symbol} ({fmtNumber(row.top_symbol_share_pct)}%)</td>
              <td className="max-w-md text-sm text-slate-600">{row.note}</td>
            </tr>
          ))}
          {!rows.length && (
            <tr>
              <td colSpan={11}>
                <EmptyState title="No filter study rows" detail="Belum ada Signal sesuai target filter study." />
              </td>
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
            <th>Evidence field</th>
            <th>Flag</th>
            <th>Available</th>
            <th>TP / SL</th>
            <th>TP median</th>
            <th>SL median</th>
            <th>Delta</th>
            <th>TP q1/q3</th>
            <th>SL q1/q3</th>
            <th>Open median</th>
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
              <td>{row.available_count} / miss {row.missing_count} ({fmtNumber(row.available_pct)}%)</td>
              <td>{row.tp_count} / {row.sl_count}</td>
              <td>{fmtNumber(row.tp_median)}</td>
              <td>{fmtNumber(row.sl_median)}</td>
              <td>{fmtSigned(row.delta_tp_minus_sl)}</td>
              <td>{fmtNumber(row.tp_q1)} / {fmtNumber(row.tp_q3)}</td>
              <td>{fmtNumber(row.sl_q1)} / {fmtNumber(row.sl_q3)}</td>
              <td>{fmtNumber(row.open_median)}</td>
            </tr>
          ))}
          {!rows.length && (
            <tr>
              <td colSpan={10}>
                <EmptyState title="No evidence rows" detail="Belum ada signal/evidence sesuai filter ini." />
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

function BucketTable({ rows, compact = false }: { rows: SignalQualityBucket[]; compact?: boolean }) {
  return (
    <div className="table-wrap">
      <table className="ops-table">
        <thead>
          <tr>
            <th>Bucket</th>
            <th>Flag</th>
            <th>Sample</th>
            <th>TP / SL / Open</th>
            <th>Winrate</th>
            <th>Total R</th>
            <th>Median R</th>
            {!compact && <th>MFE / MAE</th>}
            <th>Top Symbol</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.bucket}>
              <td className="font-semibold">{labelFor(row.bucket)}</td>
              <td><StatusBadge value={row.quality_flag} /></td>
              <td>{row.signals_evaluated}</td>
              <td>{row.tp_count} / {row.sl_count} / {row.open_count}</td>
              <td>{row.winrate_pct == null ? "-" : `${fmtNumber(row.winrate_pct)}%`}</td>
              <td>{fmtSigned(row.total_r_closed)}R</td>
              <td>{fmtSigned(row.median_r_closed)}R</td>
              {!compact && <td>{fmtSigned(row.median_mfe_r)} / {fmtSigned(row.median_mae_r)}</td>}
              <td>{row.top_symbol} ({fmtNumber(row.top_symbol_share_pct)}%)</td>
            </tr>
          ))}
          {!rows.length && (
            <tr>
              <td colSpan={compact ? 8 : 9}>
                <EmptyState title="No quality rows" detail="Belum ada signal sesuai filter ini." />
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

function VolumeRankTable({ rows }: { rows: SignalQualityVolumeRankBucket[] }) {
  return (
    <div className="table-wrap">
      <table className="ops-table">
        <thead>
          <tr>
            <th>Volume bucket</th>
            <th>Flag</th>
            <th>Scope</th>
            <th>Sample</th>
            <th>TP / SL / Open</th>
            <th>Winrate</th>
            <th>Total R</th>
            <th>Median R</th>
            <th>MFE / MAE</th>
            <th>Top symbol</th>
            <th>Missing rank</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.bucket}>
              <td className="font-semibold">{row.label || labelFor(row.bucket)}</td>
              <td><StatusBadge value={row.quality_flag} /></td>
              <td className="text-sm text-slate-600">{row.rank_scope}</td>
              <td>{row.signals_evaluated}</td>
              <td>{row.tp_count} / {row.sl_count} / {row.open_count}</td>
              <td>{row.winrate_pct == null ? "-" : `${fmtNumber(row.winrate_pct)}%`}</td>
              <td>{fmtSigned(row.total_r_closed)}R</td>
              <td>{fmtSigned(row.median_r_closed)}R</td>
              <td>{fmtSigned(row.median_mfe_r)} / {fmtSigned(row.median_mae_r)}</td>
              <td>{row.top_symbol} ({fmtNumber(row.top_symbol_share_pct)}%)</td>
              <td>{row.missing_rank_count}</td>
            </tr>
          ))}
          {!rows.length && (
            <tr>
              <td colSpan={11}>
                <EmptyState title="No volume rank rows" detail="Belum ada Signal yang bisa dipetakan ke rank volume." />
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

function SignalTable({ rows }: { rows: SignalPerformanceItem[] }) {
  return (
    <div className="table-wrap">
      <table className="ops-table">
        <thead>
          <tr>
            <th>Time WIB</th>
            <th>Symbol</th>
            <th>TF</th>
            <th>Stage</th>
            <th>Dir</th>
            <th>Status</th>
            <th>R</th>
            <th>MFE / MAE</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.signal_id}>
              <td>{row.signal_time_wib || fmtTime(row.signal_timestamp)}</td>
              <td className="font-semibold">{row.symbol}</td>
              <td>{row.timeframe}</td>
              <td>{labelFor(row.stage)}</td>
              <td><StatusBadge value={row.direction} /></td>
              <td><StatusBadge value={row.result_status} /></td>
              <td>{row.realized_r != null ? `${fmtSigned(row.realized_r)}R` : row.unrealized_r != null ? `${fmtSigned(row.unrealized_r)}R open` : "-"}</td>
              <td>{fmtSigned(row.mfe_r)} / {fmtSigned(row.mae_r)}</td>
            </tr>
          ))}
          {!rows.length && (
            <tr>
              <td colSpan={8}><EmptyState title="No signals" detail="Belum ada signal dalam kategori ini." /></td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

function Insight({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded border border-line bg-field/50 p-3">
      <div className="text-xs font-semibold uppercase text-slate-500">{label}</div>
      <div className="mt-1 font-bold text-ink">{value}</div>
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
  return `${num >= 0 ? "+" : ""}${new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 }).format(num)}`;
}
