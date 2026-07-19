import Link from "next/link";

import { EmptyState } from "@/components/EmptyState";
import { MetricCard } from "@/components/MetricCard";
import { PageHeader } from "@/components/PageHeader";
import { SectionCard } from "@/components/SectionCard";
import { StatusBadge } from "@/components/StatusBadge";
import {
  MidLongLab62Response,
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
  let quality: SignalQualityLabResponse | null = null;
  let filterStudy: SignalFilterStudyResponse | null = null;
  let optimization: StrategyOptimizationResponse | null = null;
  let regimeStudy: StrategyRegimeSplitResponse | null = null;
  let error: string | null = null;
  let filterError: string | null = null;
  let optimizationError: string | null = null;
  let regimeError: string | null = null;

  const [labResult, artifactResult] = await Promise.allSettled([
    fetchJson<MidLongLab62Response>(`/api/signal-candidates/mid-long-1h-lab62?${labQuery.toString()}`, { revalidateSeconds: 120 }),
    fetchJson<StrategyOptimizationArtifactResponse>("/api/strategy-optimization-artifacts", { revalidateSeconds: 300 })
  ]);

  if (labResult.status === "fulfilled") {
    lab62 = labResult.value;
    quality = lab62.quality;
    filterStudy = lab62.filter_study;
  } else {
    error = labResult.reason instanceof Error ? labResult.reason.message : "MID_LONG LAB-62 API failed";
    filterError = error;
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

  return (
    <div className="space-y-5">
      <PageHeader
        title="MID_LONG 1h V2.1 Research"
        badge="LAB-62 - READ-ONLY STARTING POINT"
        subtitle="Jalur riset khusus MID_LONG 1h. Baseline V2, evidence TP/SL, geometry ATR/RR/timeout, dan regime dibaca terpisah dari MID_SHORT. Tidak mengubah Signal Factory, scanner, TP/SL, atau execution."
        updatedAt={fmtTime(lab62?.generated_at_utc || optimization?.generated_at_utc || quality?.generated_at_utc)}
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
            <div className="grid gap-3 border-t border-line p-4 text-sm md:grid-cols-3">
              <ResearchStep status="ACTIVE" title="LAB-62" detail="Bekukan baseline V2, ukur evidence TP/SL, lalu pilih geometry shadow untuk diuji secara realistis." />
              <ResearchStep status="NEXT" title="LAB-63" detail="Replay geometry terpilih dengan fee, spread, slippage, position lock, dan chronological validation." />
              <ResearchStep status="PENDING" title="LAB-64+" detail="Failure anatomy, fixed cohort, combination filter, structure, lalu forward shadow jika validation bertahan." />
            </div>
            <div className="border-t border-line bg-amber-50 p-4 text-sm text-amber-900">
              Angka geometry masih ideal dan dipilih dari grid. Angka itu tidak boleh dibandingkan langsung dengan V2 realistic R serta belum boleh menjadi rule Signal.
            </div>
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
            <SectionCard title="TP vs SL evidence" description="Field yang paling membedakan TP dari SL untuk MID_LONG 1h.">
              <EvidenceTable rows={quality?.evidence_fields || []} />
            </SectionCard>
            <SectionCard title="Filter candidates" description="Filter read-only yang diuji terhadap baseline MID_LONG 1h.">
              {filterError ? (
                <div className="p-4 text-sm text-stale">{filterError}</div>
              ) : (
                <FilterTable rows={promising.length ? promising : topFilters.slice(0, 10)} />
              )}
            </SectionCard>
          </section>

          <SectionCard title="Full filter ranking" description="Cari filter dengan sample cukup, R membaik, SL share turun, dan concentration tidak terlalu tinggi.">
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
