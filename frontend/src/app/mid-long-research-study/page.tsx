import Link from "next/link";

import { EmptyState } from "@/components/EmptyState";
import { MetricCard } from "@/components/MetricCard";
import { PageHeader } from "@/components/PageHeader";
import { SectionCard } from "@/components/SectionCard";
import { StatusBadge } from "@/components/StatusBadge";
import {
  MidLongLab62Response,
  MidLongLab63Policy,
  MidLongLab63Response,
  MidLongLab64Field,
  MidLongLab64Response,
  MidLongLab65Cause,
  MidLongLab65Example,
  MidLongLab65Response,
  SignalFilterStudyResponse,
  SignalFilterStudyRow,
  SignalPerformanceItem,
  SignalQualityEvidenceField,
  SignalQualityLabResponse,
  SignalQualityProfitLossLane,
  StrategyOptimizationArtifactResponse,
  StrategyOptimizationResponse,
  StrategyOptimizationRow,
  StrategyRegimeSplitResponse,
  StrategyRegimeSplitRow,
  fetchJson,
  fmtNumber,
  fmtPrice,
  fmtTime
} from "@/lib/api";
import { labelFor } from "@/lib/labels";

type SearchParams = Promise<Record<string, string | string[] | undefined>>;

export const dynamic = "force-dynamic";

export default async function MidLongResearchStudyPage({ searchParams }: { searchParams: SearchParams }) {
  const params = await searchParams;
  const positionLock = true;
  const minSample = normalizeNumber(firstParam(params.min_sample), 20, 1, 100);
  const limit = normalizeNumber(firstParam(params.limit), 50, 10, 150);

  const labQuery = new URLSearchParams({
    min_sample: String(minSample),
    limit: String(limit)
  });
  let lab62: MidLongLab62Response | null = null;
  let lab63: MidLongLab63Response | null = null;
  let lab64: MidLongLab64Response | null = null;
  let lab65: MidLongLab65Response | null = null;
  let quality: SignalQualityLabResponse | null = null;
  let filterStudy: SignalFilterStudyResponse | null = null;
  let optimization: StrategyOptimizationResponse | null = null;
  let regimeStudy: StrategyRegimeSplitResponse | null = null;
  let error: string | null = null;
  let filterError: string | null = null;
  let optimizationError: string | null = null;
  let regimeError: string | null = null;
  let lab63Error: string | null = null;
  let lab64Error: string | null = null;
  let lab65Error: string | null = null;

  const [labResult, artifactResult, lab63Result, lab64Result, lab65Result] = await Promise.allSettled([
    fetchJson<MidLongLab62Response>(`/api/signal-candidates/mid-long-1h-lab62?${labQuery.toString()}`, { revalidateSeconds: 120 }),
    fetchJson<StrategyOptimizationArtifactResponse>("/api/strategy-optimization-artifacts", { revalidateSeconds: 300 }),
    fetchJson<MidLongLab63Response>("/api/signal-candidates/mid-long-1h-lab63", { revalidateSeconds: 300 }),
    fetchJson<MidLongLab64Response>("/api/signal-candidates/mid-long-1h-lab64", { revalidateSeconds: 300 }),
    fetchJson<MidLongLab65Response>("/api/signal-candidates/mid-long-1h-lab65", { revalidateSeconds: 300 })
  ]);

  if (labResult.status === "fulfilled") {
    lab62 = labResult.value;
    quality = lab62.quality;
    filterStudy = lab62.filter_study;
  } else {
    error = labResult.reason instanceof Error ? labResult.reason.message : "MID_LONG LAB-62 API failed";
    filterError = error;
  }

  if (lab63Result.status === "fulfilled") {
    lab63 = lab63Result.value;
  } else {
    lab63Error = lab63Result.reason instanceof Error ? lab63Result.reason.message : "MID_LONG LAB-63 API failed";
  }

  if (lab64Result.status === "fulfilled") {
    lab64 = lab64Result.value;
  } else {
    lab64Error = lab64Result.reason instanceof Error ? lab64Result.reason.message : "MID_LONG LAB-64 API failed";
  }

  if (lab65Result.status === "fulfilled") {
    lab65 = lab65Result.value;
  } else {
    lab65Error = lab65Result.reason instanceof Error ? lab65Result.reason.message : "MID_LONG LAB-65 API failed";
  }

  if (artifactResult.status === "fulfilled") {
    const artifacts = artifactResult.value;
    optimization = artifacts.optimization_by_lane?.["MID_LONG:1h"] || null;
    regimeStudy = artifacts.regime_by_lane?.["MID_LONG:1h"] || null;
    if (!optimization) optimizationError = "Artifact geometry MID_LONG 1h belum tersedia";
    if (!regimeStudy) regimeError = "Artifact regime MID_LONG 1h belum tersedia";
  } else {
    optimizationError = artifactResult.reason instanceof Error ? artifactResult.reason.message : "MID_LONG Optimization Artifact API failed";
    regimeError = optimizationError;
  }

  const aggregate = quality?.aggregate;
  const lane = quality?.profit_loss_research?.lane_rows?.find((row) => row.stage === "MID_LONG" && row.timeframe === "1h") || null;
  const topFilters = filterStudy?.rows || [];
  const promising = topFilters.filter((row) => ["PROMISING_FILTER", "REDUCES_DAMAGE"].includes(row.verdict)).slice(0, 6);
  const bestGeometry = optimization?.summary.best_row || optimization?.rows?.[0] || null;
  const dominantCause = lab65?.cause_rows?.[0] || null;

  return (
    <div className="space-y-5">
      <PageHeader
        title="MID_LONG 1h V2.1 Research"
        badge="LAB-65 - FAILURE ANATOMY"
        subtitle="Cohort dan geometry tetap 0.75 ATR / 1R / 120m. LAB-65 membedah loss realistis: salah arah langsung, reversal, structure/regime conflict, timeout, dan cost drag."
        updatedAt={fmtTime(lab65?.generated_at_utc || lab64?.generated_at_utc || lab63?.generated_at_utc || lab62?.generated_at_utc || optimization?.generated_at_utc || quality?.generated_at_utc)}
      />

      <div className="flex flex-wrap gap-2 text-sm">
        <Link className="rounded border border-line bg-white px-3 py-2 font-semibold hover:bg-field" href={`/signal-quality-lab?stage=MID_LONG&timeframe=1h&position_lock=${positionLock}`}>Open Quality Lab filtered</Link>
        <Link className="rounded border border-line bg-white px-3 py-2 font-semibold hover:bg-field" href="/scanner">Open Radar</Link>
        <Link className="rounded border border-line bg-white px-3 py-2 font-semibold hover:bg-field" href={`/signal-performance?stage=MID_LONG&timeframe=1h&position_lock=${positionLock}`}>Open Signal History</Link>
        <Link className="rounded border border-line bg-white px-3 py-2 font-semibold hover:bg-field" href={`/signal-misidentification-audit?stages=MID_LONG&timeframe=1h&position_lock=${positionLock}`}>Open Misidentification Audit</Link>
        <Link className="rounded border border-line bg-white px-3 py-2 font-semibold hover:bg-field" href={`/strategy-optimization-lab?stage=MID_LONG&timeframe=1h&position_lock=${positionLock}`}>Open Geometry Archive</Link>
      </div>

      {lab62 && (
        <div className={`rounded border p-3 text-sm ${lab62.snapshot_coverage.is_truncated ? "border-amber-300 bg-amber-50 text-amber-900" : "border-emerald-300 bg-emerald-50 text-emerald-900"}`}>
          Snapshot 1h: {lab62.snapshot_coverage.source_1h_rows} / {lab62.snapshot_coverage.source_1h_total} rows, MID_LONG 1h {lab62.snapshot_coverage.mid_long_1h_rows} closed.
          {lab62.snapshot_coverage.is_truncated
            ? " Snapshot masih terpotong; tunggu research loop menghasilkan artifact LAB-62 penuh sebelum mengambil keputusan."
            : " Snapshot penuh dan aman dipakai sebagai baseline LAB-62."}
        </div>
      )}

      {error ? (
        <div className="rounded border border-stale bg-red-50 p-4 text-sm text-stale">{error}</div>
      ) : (
        <>
          <section className="grid gap-3 md:grid-cols-2 xl:grid-cols-6">
            <MetricCard label="Sample" value={lane?.sample_count ?? aggregate?.signals_evaluated ?? 0} helper="MID_LONG 1h signal" />
            <MetricCard label="Closed TP / SL" value={`${aggregate?.tp_count ?? lane?.tp_count ?? 0} / ${aggregate?.sl_count ?? lane?.sl_count ?? 0}`} helper={`${aggregate?.closed_count ?? lane?.closed_count ?? 0} closed`} />
            <MetricCard label="Ideal R" value={`${fmtSigned(aggregate?.total_r_closed ?? lane?.total_r_closed)}R`} helper="Candle high/low ideal" tone={Number(aggregate?.total_r_closed ?? lane?.total_r_closed ?? 0) >= 0 ? "good" : "bad"} />
            <MetricCard label="Realistic R" value={`${fmtSigned(lane?.realistic_total_r_closed ?? aggregate?.realistic_total_r_closed)}R`} helper="Fee + spread + slippage" tone={Number(lane?.realistic_total_r_closed ?? aggregate?.realistic_total_r_closed ?? 0) >= 0 ? "good" : "bad"} />
            <MetricCard label="SL share" value={lane?.sl_share_pct == null ? "-" : `${fmtNumber(lane.sl_share_pct)}%`} helper="SL / closed" tone="warn" />
            <MetricCard label="Read" value={labelFor(lane?.realistic_read)} helper={lane?.top_evidence_gap?.label || "No evidence gap"} />
          </section>

          <SectionCard title="LAB-62 baseline and geometry starting point" description="Pertanyaan pertama: apakah masalah MID_LONG 1h berasal dari definisi arah, entry yang terlambat, atau geometry posisi yang terlalu lama/lebar?">
            <div className="grid gap-3 p-4 md:grid-cols-2 xl:grid-cols-6">
              <Info label="V2 control" value={`${fmtSigned(lane?.realistic_total_r_closed ?? aggregate?.realistic_total_r_closed)}R realistic`} />
              <Info label="Best geometry" value={bestGeometry ? `${fmtNumber(bestGeometry.atr_mult)} ATR / ${fmtNumber(bestGeometry.rr)}R / ${bestGeometry.timeout_minutes}m` : "Belum tersedia"} />
              <Info label="Geometry ideal R" value={bestGeometry?.total_r == null ? "-" : `${fmtSigned(bestGeometry.total_r)}R`} />
              <Info label="Geometry sample" value={bestGeometry ? `${bestGeometry.closed_count} closed / ${bestGeometry.sample_count} sample` : "-"} />
              <Info label="Geometry lock" value={optimization ? (optimization.filters.position_lock ? "Position lock ON" : "Position lock OFF") : "-"} />
              <Info label="LAB-62 decision" value={lab62Decision(lane, bestGeometry)} />
            </div>
            <div className="grid gap-3 border-t border-line p-4 text-sm md:grid-cols-2 xl:grid-cols-4">
              <ResearchStep status="COMPLETE" title="LAB-62" detail="Baseline V2 dan geometry ideal sudah dibekukan sebagai titik awal." />
              <ResearchStep status="COMPLETE" title="LAB-63" detail="120m paling sedikit merusak validation, tetapi seluruh policy tetap negatif setelah biaya." />
              <ResearchStep status="COMPLETE" title="LAB-64" detail="Tidak ada single evidence separator yang cukup stabil untuk langsung menjadi filter." />
              <ResearchStep status="ACTIVE" title="LAB-65" detail="Partisi loss berdasarkan path, structure, regime, timeout, dan biaya sebelum menguji kombinasi filter." />
            </div>
            <div className="border-t border-line bg-amber-50 p-4 text-sm text-amber-900">
              Angka geometry masih ideal dan dipilih dari grid. Angka itu tidak boleh dibandingkan langsung dengan V2 realistic R serta belum boleh menjadi rule Signal.
            </div>
          </SectionCard>

          <SectionCard
            title="LAB-63 realistic timeout policy comparison"
            description="Semua baris memakai entry dan ATR yang sama. Hanya batas waktu posisi yang berubah; 4h adalah reference resmi."
          >
            {lab63Error ? (
              <div className="p-4 text-sm text-stale">{lab63Error}</div>
            ) : lab63 ? (
              <>
                <div className="grid gap-3 p-4 md:grid-cols-2 xl:grid-cols-6">
                  <Info label="Fixed geometry" value={`${fmtNumber(lab63.geometry.atr_multiplier)} ATR / ${fmtNumber(lab63.geometry.reward_risk)}R`} />
                  <Info label="Reference" value={policyLabel(lab63.reference_policy)} />
                  <Info label="Source" value={`${lab63.split.source_signal_count} Signal`} />
                  <Info label="Train / validation" value={`${lab63.split.train_source_count} / ${lab63.split.validation_source_count}`} />
                  <Info label="Best observed" value={lab63.best_observed_policy?.policy_label || "Belum cukup validation"} />
                  <Info label="Position lock" value={lab63.filters.position_lock ? "ON" : "OFF"} />
                </div>
                <Lab63PolicyTable rows={lab63.policies} referencePolicy={lab63.reference_policy} />
                <div className="border-t border-line bg-blue-50 p-4 text-sm text-blue-950">
                  Tanpa timeout tidak memakai harga candle terakhir sebagai hasil closed. Posisi yang belum menyentuh target atau stop tetap <b>OPEN</b>, R-nya hanya unrealized, dan Signal berikutnya pada simbol yang sama terkena position lock.
                </div>
              </>
            ) : (
              <div className="p-4"><EmptyState title="LAB-63 belum tersedia" detail="Tunggu artifact research cycle pertama." /></div>
            )}
          </SectionCard>

          <SectionCard
            title="LAB-64 TP vs SL evidence separation"
            description="Outcome dikunci ke 0.75 ATR / 1R / 120m. AUC menunjukkan peluang nilai evidence pada TP lebih tinggi daripada SL; 50% berarti tidak ada separation."
          >
            {lab64Error ? (
              <div className="p-4 text-sm text-stale">{lab64Error}</div>
            ) : lab64 ? (
              <>
                <div className="grid gap-3 p-4 md:grid-cols-2 xl:grid-cols-6">
                  <Info label="Fixed cohort" value={`${lab64.split.source_signal_count} Signal`} />
                  <Info label="Validation TP / SL" value={`${lab64.outcome_summary.validation.tp_count} / ${lab64.outcome_summary.validation.sl_count}`} />
                  <Info label="Stable fields" value={`${lab64.field_summary.stable_field_count} / ${lab64.field_summary.field_count}`} />
                  <Info label="Moderate / weak" value={`${lab64.field_summary.moderate_field_count} / ${lab64.field_summary.weak_field_count}`} />
                  <Info label="Direction flipped" value={lab64.field_summary.direction_flip_count} />
                  <Info label="Verdict" value={labelFor(lab64.verdict)} />
                </div>
                {lab64.best_observed_field && (
                  <div className="border-t border-line bg-blue-50 p-4 text-sm text-blue-950">
                    Evidence observasi teratas: <b>{lab64.best_observed_field.label}</b>. {lab64.best_observed_field.research_read}
                    Ini belum menjadi threshold atau filter Signal.
                  </div>
                )}
                <Lab64EvidenceTable rows={lab64.field_rows} />
                <div className="border-t border-line bg-amber-50 p-4 text-sm text-amber-950">
                  Median mentah tidak dipakai untuk meranking lintas field karena unitnya berbeda. Prioritas ditentukan dari AUC, kecukupan sample, dan arah yang tetap sama pada chronological train/validation.
                </div>
              </>
            ) : (
              <div className="p-4"><EmptyState title="LAB-64 belum tersedia" detail="Tunggu research artifact cycle berikutnya." /></div>
            )}
          </SectionCard>

          <SectionCard
            title="LAB-65 MID_LONG 1h failure anatomy"
            description="Setiap loss realistis masuk tepat satu primary cause. Contributor boleh tumpang tindih untuk menunjukkan faktor tambahan tanpa menghitung loss dua kali."
          >
            {lab65Error ? (
              <div className="p-4 text-sm text-stale">{lab65Error}</div>
            ) : lab65 ? (
              <>
                <div className="grid gap-3 p-4 md:grid-cols-2 xl:grid-cols-6">
                  <Info label="Fixed cohort" value={`${lab65.split.source_signal_count} Signal`} />
                  <Info label="Realistic losses" value={lab65.failure_summary.all.count} />
                  <Info label="Validation losses" value={lab65.failure_summary.validation.count} />
                  <Info label="Loss damage" value={`${fmtSigned(lab65.failure_summary.all.total_realistic_r)}R`} />
                  <Info label="Dominant cause" value={dominantCause?.label || "Belum tersedia"} />
                  <Info label="Verdict" value={labelFor(lab65.verdict)} />
                </div>
                {dominantCause && (
                  <div className="border-t border-line bg-blue-50 p-4 text-sm text-blue-950">
                    Penyebab terbesar saat ini: <b>{dominantCause.label}</b> pada {fmtNumber(dominantCause.all.share_pct)}% loss
                    ({dominantCause.all.count} kasus). Validation memuat {dominantCause.validation.count} kasus.
                    Ini diagnosis outcome, bukan filter Signal baru.
                  </div>
                )}
                <Lab65CauseTable rows={lab65.cause_rows} />
                <div className="grid gap-4 border-t border-line p-4 xl:grid-cols-2">
                  <div>
                    <h3 className="mb-2 text-sm font-semibold">Contributor overlap</h3>
                    <div className="space-y-2">
                      {lab65.contributor_rows.slice(0, 10).map((row) => (
                        <div key={row.contributor} className="flex items-center justify-between gap-3 rounded border border-line bg-field px-3 py-2 text-sm">
                          <span>{labelFor(row.contributor)}</span>
                          <span className="shrink-0 font-semibold">{row.all_count} ({fmtNumber(row.all_share_pct)}%)</span>
                        </div>
                      ))}
                      {!lab65.contributor_rows.length && <EmptyState title="No contributor rows" detail="Belum ada loss contributor." />}
                    </div>
                  </div>
                  <div>
                    <h3 className="mb-2 text-sm font-semibold">Batas interpretasi</h3>
                    <div className="space-y-2 text-sm text-slate-700">
                      {lab65.guardrails.slice(0, 5).map((guardrail) => (
                        <div key={guardrail} className="rounded border border-line bg-white px-3 py-2">{guardrail}</div>
                      ))}
                    </div>
                  </div>
                </div>
                <Lab65FailureExamples rows={lab65.latest_failure_examples} />
              </>
            ) : (
              <div className="p-4"><EmptyState title="LAB-65 belum tersedia" detail="Tunggu research artifact cycle berikutnya." /></div>
            )}
          </SectionCard>

          <SectionCard title="Research verdict" description="Kesimpulan praktis dari kondisi MID_LONG 1h saat ini.">
            <div className="grid gap-3 p-4 md:grid-cols-2 xl:grid-cols-4">
              <Info label="Current read" value={midLongVerdict(lane)} />
              <Info label="Problem utama" value={mainProblem(lane)} />
              <Info label="Evidence gap utama" value={lane?.top_evidence_gap ? `${lane.top_evidence_gap.label}: ${labelFor(lane.top_evidence_gap.quality_flag)}` : "-"} />
              <Info label="Top loss symbol" value={lane?.top_loss_symbol ? `${lane.top_loss_symbol.symbol} ${fmtSigned(lane.top_loss_symbol.realistic_total_r_closed)}R` : "-"} />
            </div>
            <div className="border-t border-line p-4 text-sm text-slate-700">
              MID_LONG 1h layak diteliti karena sample besar, tetapi belum layak dipromosikan. Fokus risetnya: cari kondisi ketika long 1h tidak telat masuk, cost tidak terlalu berat, dan price return sebelum entry tidak overextended.
            </div>
          </SectionCard>

          <SectionCard title="Geometry candidates" description="ATR, RR, dan timeout terbaik dari replay futures MID_LONG 1h. Ini adalah kandidat eksperimen, bukan parameter final.">
            {optimizationError ? (
              <div className="p-4 text-sm text-stale">{optimizationError}</div>
            ) : (
              <GeometryTable rows={optimization?.rows?.slice(0, 12) || []} />
            )}
          </SectionCard>

          <section className="grid gap-4 xl:grid-cols-2">
            <SectionCard title="Helpful market context" description="Regime yang membaik pada geometry terbaik. Masih in-sample dan belum menjadi gate.">
              {regimeError ? (
                <div className="p-4 text-sm text-stale">{regimeError}</div>
              ) : (
                <RegimeTable rows={regimeStudy?.summary.top_helpful_regimes || []} />
              )}
            </SectionCard>
            <SectionCard title="Harmful market context" description="Regime yang merusak geometry terbaik. Dipakai untuk mencari penyebab late/crowded long.">
              {regimeError ? (
                <div className="p-4 text-sm text-stale">{regimeError}</div>
              ) : (
                <RegimeTable rows={regimeStudy?.summary.top_harmful_regimes || []} />
              )}
            </SectionCard>
          </section>

          <section className="grid gap-4 xl:grid-cols-2">
            <SectionCard title="Logged V2 evidence archive (LAB-62)" description="Median lama dari outcome V2 logged. Gunakan LAB-64 di atas untuk chronological separation pada geometry tetap.">
              <EvidenceTable rows={quality?.evidence_fields || []} />
            </SectionCard>
            <SectionCard title="Legacy in-sample filter candidates" description="Hipotesis lama terhadap baseline V2; belum dianggap valid sampai diretest pada fixed cohort setelah LAB-64.">
              {filterError ? (
                <div className="p-4 text-sm text-stale">{filterError}</div>
              ) : (
                <FilterTable rows={promising.length ? promising : topFilters.slice(0, 10)} />
              )}
            </SectionCard>
          </section>

          <SectionCard title="Legacy full filter ranking" description="Arsip eksplorasi in-sample LAB-62. Baris ini bukan hasil LAB-64 dan tidak dipromosikan.">
            {filterError ? (
              <div className="p-4 text-sm text-stale">{filterError}</div>
            ) : (
              <FilterTable rows={topFilters} />
            )}
          </SectionCard>

          <SectionCard
            title="Walk-forward validation"
            description="Validasi train/validation tetap penting, tapi endpoint ini berat. Dibuka terpisah supaya halaman MID_LONG tetap ringan."
          >
            <div className="grid gap-3 p-4 md:grid-cols-3">
              <Info label="Current read" value="Belum promosi rule" />
              <Info label="Why" value="Filter ideal perlu lolos validation, bukan cuma bagus di semua sample." />
              <Info label="Action" value="Buka 1h Review untuk walk-forward detail." />
            </div>
            <div className="border-t border-line p-4 text-sm text-slate-700">
              Cek walk-forward MID_LONG 1h di halaman 1h Review. Kalau validation tetap negatif atau hanya damage reduction, filter belum boleh dipromosikan.
              <div className="mt-3">
                <Link className="rounded-md border border-line bg-white px-3 py-2 font-semibold hover:bg-field" href="/signal-1h-review">
                  Open 1h Review
                </Link>
              </div>
            </div>
          </SectionCard>

          <section className="grid gap-4 xl:grid-cols-3">
            <SectionCard title="Best MID_LONG 1h signals" description="Signal closed terbaik menurut realized R.">
              <SignalTable items={quality?.best_signals || []} />
            </SectionCard>
            <SectionCard title="Worst MID_LONG 1h signals" description="Signal closed terburuk untuk mencari pola SL.">
              <SignalTable items={quality?.worst_signals || []} />
            </SectionCard>
            <SectionCard title="Open MID_LONG 1h signals" description="Signal yang masih aktif saat data dibaca.">
              <SignalTable items={quality?.open_signals || []} />
            </SectionCard>
          </section>

          <SectionCard title="Guardrail" description="Batas interpretasi halaman ini.">
            <ul className="grid gap-2 p-4 text-sm text-slate-700 md:grid-cols-2">
              <li className="rounded border border-line bg-field/40 p-3">Halaman ini hanya membaca log V2 MID_LONG 1h dan candle futures lokal.</li>
              <li className="rounded border border-line bg-field/40 p-3">Filter candidate belum menjadi rule live dan tidak mengubah scanner.</li>
              <li className="rounded border border-line bg-field/40 p-3">Realistic R memakai fee/spread/slippage model, bukan order real.</li>
              <li className="rounded border border-line bg-field/40 p-3">Jika filter terlihat bagus, tahap berikutnya adalah shadow monitoring, bukan execution.</li>
            </ul>
          </SectionCard>
        </>
      )}
    </div>
  );
}

function Info({ label, value }: { label: string; value?: string | number | null }) {
  return (
    <div className="rounded border border-line bg-field/40 p-3 text-sm">
      <div className="text-xs font-semibold uppercase text-slate-500">{label}</div>
      <div className="mt-1 font-bold text-ink">{value == null || value === "" ? "-" : value}</div>
    </div>
  );
}

function ResearchStep({ status, title, detail }: { status: string; title: string; detail: string }) {
  return (
    <div className="rounded border border-line bg-field/40 p-3">
      <div className="flex items-center gap-2">
        <StatusBadge value={status} />
        <span className="font-bold text-ink">{title}</span>
      </div>
      <p className="mt-2 text-slate-600">{detail}</p>
    </div>
  );
}

function GeometryTable({ rows }: { rows: StrategyOptimizationRow[] }) {
  return (
    <div className="table-wrap">
      <table className="ops-table">
        <thead>
          <tr>
            <th>Verdict</th>
            <th>ATR / RR / Timeout</th>
            <th>Sample</th>
            <th>TP / SL / Both</th>
            <th>Timeout</th>
            <th>Total R</th>
            <th>Avg / Median R</th>
            <th>Max DD</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={`${row.atr_mult}-${row.rr}-${row.timeout_minutes}`}>
              <td><StatusBadge value={row.verdict} /></td>
              <td>
                <div className="font-semibold">{fmtNumber(row.atr_mult)} ATR / {fmtNumber(row.rr)}R</div>
                <div className="text-xs text-slate-500">timeout {row.timeout_minutes}m</div>
              </td>
              <td>{row.closed_count} / {row.sample_count}</td>
              <td>{row.tp_count} / {row.sl_count} / {row.both_hit_count}</td>
              <td>
                <div>{row.timeout_count}</div>
                <div className="text-xs text-slate-500">+{row.positive_timeout_count} / -{row.negative_timeout_count}</div>
              </td>
              <td className={Number(row.total_r || 0) >= 0 ? "text-ready" : "text-stale"}>{fmtSigned(row.total_r)}R</td>
              <td>{fmtSigned(row.avg_r)}R / {fmtSigned(row.median_r)}R</td>
              <td>{fmtSigned(row.max_drawdown_r)}R</td>
            </tr>
          ))}
          {!rows.length && (
            <tr>
              <td colSpan={8}><EmptyState title="No geometry rows" detail="Artifact geometry MID_LONG 1h belum tersedia atau sedang dihitung." /></td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

function Lab63PolicyTable({ rows, referencePolicy }: { rows: MidLongLab63Policy[]; referencePolicy: string }) {
  return (
    <div className="table-wrap border-t border-line">
      <table className="ops-table">
        <thead>
          <tr>
            <th>Policy</th>
            <th>All evaluated</th>
            <th>All TP / SL / timeout</th>
            <th>All realistic R</th>
            <th>Validation</th>
            <th>Validation realistic R</th>
            <th>Delta avg vs 4h</th>
            <th>Validation DD</th>
            <th>Verdict</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.policy_id}>
              <td>
                <div className="font-semibold">{row.policy_label}</div>
                <div className="mt-1 flex flex-wrap gap-1 text-xs">
                  {row.policy_id === referencePolicy && <StatusBadge value="REFERENCE" />}
                  {row.policy_id === "NO_TIMEOUT" && <StatusBadge value="OPEN_UNTIL_TP_SL" />}
                </div>
              </td>
              <td>
                <div>{row.all.evaluated_count} evaluated / {row.all.closed_count} closed</div>
                <div className="text-xs text-slate-500">{row.all.open_count} open / {row.all.skipped_count} lock skip</div>
              </td>
              <td>
                <div>{row.all.tp_count} / {row.all.sl_count} / {row.all.timeout_count}</div>
                <div className="text-xs text-slate-500">both {row.all.both_hit_count}, incomplete {row.all.incomplete_count}</div>
              </td>
              <td className={Number(row.all.realistic_total_r_closed || 0) >= 0 ? "text-ready" : "text-stale"}>
                <div>{fmtSigned(row.all.realistic_total_r_closed)}R</div>
                <div className="text-xs">avg {fmtSigned(row.all.realistic_avg_r_closed)}R / med {fmtSigned(row.all.realistic_median_r_closed)}R</div>
              </td>
              <td>
                <div>{row.validation.closed_count} closed / {row.validation.evaluated_count} evaluated</div>
                <div className="text-xs text-slate-500">{row.validation.open_count} open / {row.validation.skipped_count} lock skip</div>
              </td>
              <td className={Number(row.validation.realistic_total_r_closed || 0) >= 0 ? "text-ready" : "text-stale"}>
                <div>{fmtSigned(row.validation.realistic_total_r_closed)}R</div>
                <div className="text-xs">avg {fmtSigned(row.validation.realistic_avg_r_closed)}R / med {fmtSigned(row.validation.realistic_median_r_closed)}R</div>
              </td>
              <td>{fmtOptionalSigned(row.validation.realistic_avg_r_delta_vs_4h)}R</td>
              <td>{fmtSigned(row.validation.max_realistic_drawdown_r)}R</td>
              <td><StatusBadge value={row.verdict} /></td>
            </tr>
          ))}
          {!rows.length && (
            <tr><td colSpan={9}><EmptyState title="No timeout policy rows" detail="Artifact LAB-63 belum berisi hasil." /></td></tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

function Lab64EvidenceTable({ rows }: { rows: MidLongLab64Field[] }) {
  return (
    <div className="table-wrap border-t border-line">
      <table className="ops-table">
        <thead>
          <tr>
            <th>Evidence</th>
            <th>Availability</th>
            <th>All TP / SL median</th>
            <th>Train AUC</th>
            <th>Validation TP / SL median</th>
            <th>Validation AUC</th>
            <th>Consistency</th>
            <th>Research read</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.field}>
              <td>
                <div className="font-semibold">{row.label}</div>
                <div className="text-xs text-slate-500">{row.field}</div>
              </td>
              <td>
                <div>{row.validation.available_count} / {row.validation.source_count}</div>
                <div className="text-xs text-slate-500">{fmtNumber(row.validation.available_pct)}% validation</div>
              </td>
              <td>
                <div>{fmtNumber(row.all.tp_median)} / {fmtNumber(row.all.sl_median)}</div>
                <div className="text-xs text-slate-500">n {row.all.tp_count} / {row.all.sl_count}</div>
              </td>
              <td>
                <div>{fmtAuc(row.train.auc_tp_above_sl)}</div>
                <div className="text-xs text-slate-500">{labelFor(row.train_direction)}</div>
              </td>
              <td>
                <div>{fmtNumber(row.validation.tp_median)} / {fmtNumber(row.validation.sl_median)}</div>
                <div className="text-xs text-slate-500">n {row.validation.tp_count} / {row.validation.sl_count}</div>
              </td>
              <td>
                <div>{fmtAuc(row.validation.auc_tp_above_sl)}</div>
                <div className="text-xs text-slate-500">strength {fmtPercentRatio(row.validation.separation_strength)}</div>
              </td>
              <td>
                <StatusBadge value={row.verdict} />
                <div className="mt-1 text-xs text-slate-500">
                  {row.direction_consistent == null ? "Belum dapat dinilai" : row.direction_consistent ? "Arah konsisten" : "Arah berubah"}
                </div>
              </td>
              <td className="max-w-md text-sm text-slate-600">{row.research_read}</td>
            </tr>
          ))}
          {!rows.length && (
            <tr><td colSpan={8}><EmptyState title="No evidence rows" detail="Artifact LAB-64 belum berisi field evidence." /></td></tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

function Lab65CauseTable({ rows }: { rows: MidLongLab65Cause[] }) {
  return (
    <div className="table-wrap border-t border-line">
      <table className="ops-table">
        <thead>
          <tr>
            <th>Primary cause</th>
            <th>All loss</th>
            <th>Validation</th>
            <th>Path median</th>
            <th>Context conflicts</th>
            <th>Damage</th>
            <th>Research action</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.cause}>
              <td className="max-w-xs">
                <div className="font-semibold">{row.label}</div>
                <div className="text-xs text-slate-500">{row.definition}</div>
              </td>
              <td>
                <div>{row.all.count} ({fmtNumber(row.all.share_pct)}%)</div>
                <div className="text-xs text-slate-500">train {row.train.count}</div>
              </td>
              <td>
                <div>{row.validation.count} ({fmtNumber(row.validation.share_pct)}%)</div>
                <div className="text-xs text-slate-500">top {row.validation.top_symbol || "-"}</div>
              </td>
              <td>
                <div>MFE {fmtSigned(row.all.median_mfe_before_result_r)}R</div>
                <div className="text-xs text-slate-500">15m {fmtSigned(row.all.median_first_15m_close_r)}R / {fmtNumber(row.all.median_time_to_result_minutes)}m</div>
              </td>
              <td>
                <div>Zone {row.all.structure_conflict_count || 0}</div>
                <div className="text-xs text-slate-500">BTC/ETH {row.all.regime_conflict_count || 0}</div>
              </td>
              <td className="text-stale">
                <div>{fmtSigned(row.all.total_realistic_r)}R</div>
                <div className="text-xs">avg {fmtSigned(row.all.avg_realistic_r)}R</div>
              </td>
              <td className="max-w-sm text-sm text-slate-600">{row.research_action}</td>
            </tr>
          ))}
          {!rows.length && (
            <tr><td colSpan={7}><EmptyState title="No failure causes" detail="Tidak ada realistic loss pada cohort ini." /></td></tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

function Lab65FailureExamples({ rows }: { rows: MidLongLab65Example[] }) {
  return (
    <div className="table-wrap border-t border-line">
      <div className="px-4 py-3 text-sm font-semibold">Latest audited loss examples</div>
      <table className="ops-table">
        <thead>
          <tr>
            <th>Signal WIB</th>
            <th>Symbol</th>
            <th>Result</th>
            <th>Primary cause</th>
            <th>Forward path</th>
            <th>Pre-entry context</th>
            <th>Contributors</th>
          </tr>
        </thead>
        <tbody>
          {rows.slice(0, 15).map((row) => (
            <tr key={row.signal_id}>
              <td>{fmtTime(row.signal_timestamp)}</td>
              <td>
                <Link className="font-semibold text-blue-700 hover:underline" href={`/signals/${row.symbol}?signal_id=${row.signal_id}`}>{row.symbol}</Link>
              </td>
              <td>
                <StatusBadge value={row.result_status} />
                <div className="mt-1 text-xs">{fmtSigned(row.realistic_realized_r)}R</div>
              </td>
              <td><StatusBadge value={row.failure_primary_cause} /></td>
              <td>
                <div>MFE {fmtSigned(row.mfe_before_result_r)}R / MAE {fmtSigned(row.mae_before_result_r)}R</div>
                <div className="text-xs text-slate-500">15m {fmtSigned(row.first_15m_close_r)}R / result {fmtNumber(row.time_to_result_minutes)}m</div>
              </td>
              <td>
                <div>{labelFor(row.structure_status)}</div>
                <div className="text-xs text-slate-500">Regime conflict {row.regime_conflict ? "yes" : "no"}</div>
              </td>
              <td className="max-w-sm text-xs text-slate-600">
                {(row.failure_contributors || []).map((item) => labelFor(item)).join(", ") || "No additional contributor"}
              </td>
            </tr>
          ))}
          {!rows.length && (
            <tr><td colSpan={7}><EmptyState title="No failure examples" detail="Belum ada realistic loss untuk diaudit." /></td></tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

function RegimeTable({ rows }: { rows: StrategyRegimeSplitRow[] }) {
  return (
    <div className="table-wrap">
      <table className="ops-table">
        <thead>
          <tr>
            <th>Regime</th>
            <th>Sample</th>
            <th>TP / SL</th>
            <th>Total R</th>
            <th>Avg / Median</th>
            <th>Delta</th>
          </tr>
        </thead>
        <tbody>
          {rows.slice(0, 8).map((row) => (
            <tr key={`${row.dimension}-${row.bucket}`}>
              <td>
                <div className="font-semibold">{labelFor(row.bucket)}</div>
                <div className="text-xs text-slate-500">{labelFor(row.dimension)}</div>
              </td>
              <td>{row.closed_count} / {row.sample_count}</td>
              <td>{row.tp_count} / {row.sl_count}</td>
              <td className={Number(row.total_r || 0) >= 0 ? "text-ready" : "text-stale"}>{fmtSigned(row.total_r)}R</td>
              <td>{fmtSigned(row.avg_r)}R / {fmtSigned(row.median_r)}R</td>
              <td>{fmtSigned(row.avg_r_delta_vs_baseline)}R</td>
            </tr>
          ))}
          {!rows.length && (
            <tr>
              <td colSpan={6}><EmptyState title="No regime rows" detail="Regime split untuk geometry terpilih belum tersedia." /></td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

function EvidenceTable({ rows }: { rows: SignalQualityEvidenceField[] }) {
  const selected = rows
    .filter((row) => row.available_count > 0)
    .sort((a, b) => Math.abs(Number(b.delta_tp_minus_sl || 0)) - Math.abs(Number(a.delta_tp_minus_sl || 0)))
    .slice(0, 12);
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
          {selected.map((row) => (
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
          {!selected.length && (
            <tr>
              <td colSpan={7}><EmptyState title="No evidence rows" detail="Belum ada evidence dengan sample cukup." /></td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

function FilterTable({ rows }: { rows: SignalFilterStudyRow[] }) {
  return (
    <div className="table-wrap">
      <table className="ops-table">
        <thead>
          <tr>
            <th>Verdict</th>
            <th>Filter</th>
            <th>Sample</th>
            <th>TP / SL / Open</th>
            <th>Total R</th>
            <th>Avg delta</th>
            <th>SL share</th>
            <th>SL delta</th>
            <th>Top symbol</th>
            <th>Note</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.filter_id}>
              <td><StatusBadge value={row.verdict} /></td>
              <td>
                <div className="font-semibold">{row.label}</div>
                <div className="text-xs text-slate-500">{row.expression}</div>
              </td>
              <td>
                <div>{row.sample_count} / {row.source_count}</div>
                <div className="text-xs text-slate-500">keep {fmtNumber(row.sample_retention_pct)}%, miss {fmtNumber(row.missing_data_pct)}%</div>
              </td>
              <td>{row.tp_count ?? 0} / {row.sl_count ?? 0} / {row.open_count ?? 0}</td>
              <td className={Number(row.total_r_closed || 0) >= 0 ? "text-ready" : "text-stale"}>{fmtSigned(row.total_r_closed)}R</td>
              <td>{fmtSigned(row.avg_r_delta_vs_baseline)}R</td>
              <td>{row.sl_share_pct == null ? "-" : `${fmtNumber(row.sl_share_pct)}%`}</td>
              <td>{fmtSigned(row.sl_share_delta_vs_baseline)}%</td>
              <td>{row.top_symbol} ({fmtNumber(row.top_symbol_share_pct)}%)</td>
              <td className="max-w-md text-sm text-slate-600">{row.note}</td>
            </tr>
          ))}
          {!rows.length && (
            <tr>
              <td colSpan={10}><EmptyState title="No filter rows" detail="Belum ada filter candidate untuk sample ini." /></td>
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
            <th>R</th>
            <th>Realistic</th>
            <th>Entry / SL / TP</th>
          </tr>
        </thead>
        <tbody>
          {items.slice(0, 12).map((item) => (
            <tr key={item.signal_id}>
              <td>{item.signal_time_wib || fmtTime(item.signal_timestamp)}</td>
              <td>
                <Link className="font-semibold text-blue-700 hover:underline" href={`/signals/${item.symbol}?signal_id=${item.signal_id}`}>{item.symbol}</Link>
              </td>
              <td><StatusBadge value={item.result_status} /></td>
              <td>{item.realized_r != null ? `${fmtSigned(item.realized_r)}R` : `${fmtSigned(item.unrealized_r)}R open`}</td>
              <td>{item.realistic_realized_r != null ? `${fmtSigned(item.realistic_realized_r)}R` : `${fmtSigned(item.realistic_unrealized_r)}R open`}</td>
              <td>
                <div>Entry {fmtPrice(item.entry)}</div>
                <div className="text-xs text-slate-500">SL {fmtPrice(item.stop_loss)} / TP {fmtPrice(item.take_profit)}</div>
              </td>
            </tr>
          ))}
          {!items.length && (
            <tr>
              <td colSpan={6}><EmptyState title="No signals" detail="Belum ada sample untuk kategori ini." /></td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

function midLongVerdict(lane: SignalQualityProfitLossLane | null) {
  if (!lane) return "Belum ada lane row";
  const realistic = Number(lane.realistic_total_r_closed || 0);
  const slShare = Number(lane.sl_share_pct || 0);
  if (realistic > 0 && slShare < 55) return "Layak shadow study";
  if (realistic > -20) return "Dekat, perlu filter ketat";
  return "Layak diteliti, belum layak promosi";
}

function mainProblem(lane: SignalQualityProfitLossLane | null) {
  if (!lane) return "-";
  const ideal = Number(lane.total_r_closed || 0);
  const realistic = Number(lane.realistic_total_r_closed || 0);
  if (ideal > 0 && realistic < 0) return "Cost/spread/slippage menghabiskan edge";
  if (Number(lane.sl_share_pct || 0) > 60) return "SL share terlalu tinggi";
  if (realistic < 0) return "Realistic R masih negatif";
  return "Perlu cek stability filter";
}

function lab62Decision(lane: SignalQualityProfitLossLane | null, bestGeometry: StrategyOptimizationRow | null) {
  const baselineRealistic = Number(lane?.realistic_total_r_closed || 0);
  const geometryIdeal = Number(bestGeometry?.total_r || 0);
  if (baselineRealistic < 0 && geometryIdeal > 0) return "Geometry shadow candidate";
  if (baselineRealistic < 0) return "V2 rejected, cari geometry";
  return "Baseline perlu validation";
}

function firstParam(value: string | string[] | undefined) {
  return Array.isArray(value) ? value[0] : value;
}

function normalizeNumber(raw: string | undefined, fallback: number, min: number, max: number) {
  const parsed = Number(raw);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.min(max, Math.max(min, Math.floor(parsed)));
}

function fmtSigned(value?: string | number | null) {
  if (value === null || value === undefined || value === "") return "-";
  const n = Number(value);
  if (!Number.isFinite(n)) return String(value);
  if (Math.abs(n) < 0.005) return "0";
  return `${n > 0 ? "+" : ""}${fmtNumber(n)}`;
}

function fmtOptionalSigned(value?: string | number | null) {
  if (value === null || value === undefined || value === "") return "-";
  return fmtSigned(value);
}

function fmtAuc(value?: string | number | null) {
  if (value === null || value === undefined || value === "") return "-";
  const parsed = Number(value);
  return Number.isFinite(parsed) ? `${(parsed * 100).toFixed(1)}%` : String(value);
}

function fmtPercentRatio(value?: string | number | null) {
  if (value === null || value === undefined || value === "") return "-";
  const parsed = Number(value);
  return Number.isFinite(parsed) ? `${(parsed * 100).toFixed(1)}%` : String(value);
}

function policyLabel(policyId?: string | null) {
  const labels: Record<string, string> = {
    TIMEOUT_60M: "Timeout 60 menit",
    TIMEOUT_120M: "Timeout 120 menit",
    TIMEOUT_4H: "Timeout 4 jam",
    NO_TIMEOUT: "Tanpa timeout"
  };
  return policyId ? labels[policyId] || labelFor(policyId) : "-";
}
