import Link from "next/link";

import { MetricCard } from "@/components/MetricCard";
import { PageHeader } from "@/components/PageHeader";
import { SectionCard } from "@/components/SectionCard";
import { StatusBadge } from "@/components/StatusBadge";
import {
  MidShortFailureAnatomyResponse,
  MidShortFailureBucketRow,
  MidShortFailureImprovementCandidate,
  MidShortCounterfactualRow,
  MidShortSlFailureCauseRow,
  MidShortStructureBlockedCase,
  MidShortStructureClearanceStatusRow,
  MidShortStructureExitVariantRow,
  MidShortTargetDistanceCase,
  MidShortTargetDistanceMetricRow,
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
  const baseFilter = firstParam(params.base_filter) || "TAKER_SELL_GE_52";
  const minSample = normalizeNumber(firstParam(params.min_sample), 20, 1, 100);
  const limit = normalizeNumber(firstParam(params.limit), 50, 10, 150);
  const query = new URLSearchParams({
    include_watch_only: String(includeWatchOnly),
    position_lock: String(positionLock),
    shadow_status: shadowStatus,
    base_filter: baseFilter,
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
  const structureStudy = data?.structure_clearance_study;
  const targetStudy = data?.target_distance_study;

  return (
    <div className="space-y-5">
      <PageHeader
        title="MID_SHORT 1h Direction Failure Lab"
        badge="READ-ONLY RESEARCH"
        subtitle="Mengklasifikasikan setiap SL sebagai salah arah, entry terlambat, stop terlalu dekat, target terlalu jauh, konflik regime, atau tidak ada follow-through. Diagnosis memakai jalur candle futures nyata dan tidak mengubah rule live."
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
            <MetricCard label="Scope sample" value={summary?.source_count ?? 0} helper={`${summary?.closed_count ?? 0} closed / ${summary?.source_before_base_filter_count ?? 0} before base filter`} />
            <MetricCard label="TP / SL" value={`${summary?.tp_count ?? 0} / ${summary?.sl_count ?? 0}`} helper={`${summary?.open_count ?? 0} open`} />
            <MetricCard
              label="Penyebab dominan"
              value={labelFor(summary?.dominant_failure_cause || "MIXED_UNRESOLVED")}
              helper={`${summary?.dominant_failure_count ?? 0} SL / ${fmtNumber(summary?.dominant_failure_share_pct)}%`}
              tone="warn"
            />
            <MetricCard
              label="SL terklasifikasi"
              value={`${summary?.classified_sl_count ?? 0}/${summary?.sl_count ?? 0}`}
              helper={`${summary?.unresolved_sl_count ?? 0} belum jelas`}
            />
            <MetricCard label="Salah arah 1h" value={summary?.wrong_direction_1h_count ?? 0} helper={`${summary?.correct_direction_1h_count ?? 0} benar arah`} tone="bad" />
            <MetricCard label="Realistic R" value={`${fmtSigned(data?.baseline.realistic_total_r_closed)}R`} helper={labelFor(summary?.read || "-")} tone={Number(data?.baseline.realistic_total_r_closed || 0) >= 0 ? "good" : "bad"} />
          </section>

          <SectionCard title="Failure controls" description="Filter ini hanya mengubah audit. Tidak mengubah Signal Factory atau scanner.">
            <form className="grid gap-3 p-4 text-sm md:grid-cols-3 xl:grid-cols-6">
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
                <span className="font-semibold text-slate-600">Base research scope</span>
                <select className="rounded border border-line px-3 py-2" name="base_filter" defaultValue={baseFilter}>
                  <option value="TAKER_SELL_GE_52">Taker sell &gt;= 52%</option>
                  <option value="ALL">All selected shadow rows</option>
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

          <SectionCard
            title="SL root-cause classification"
            description="Setiap SL mendapat satu primary cause agar total tidak dihitung ganda. Contributor tambahan tetap disimpan pada detail signal. Label ini hipotesis riset, bukan bukti kausal final."
          >
            <CauseTable rows={data?.sl_failure_cause_rows || []} />
          </SectionCard>

          <section className="grid gap-3 md:grid-cols-2 xl:grid-cols-5">
            <MetricCard
              label="Structure context"
              value={`${structureStudy?.summary.context_available_count ?? 0}/${structureStudy?.summary.source_count ?? 0}`}
              helper={`${structureStudy?.summary.structure_unavailable_count ?? 0} unavailable`}
            />
            <MetricCard
              label="Structure clear"
              value={structureStudy?.summary.structure_clear_count ?? 0}
              helper="Support tidak menghalangi target"
              tone="good"
            />
            <MetricCard
              label="Structure blocked"
              value={structureStudy?.summary.structure_blocked_count ?? 0}
              helper="Support berada sebelum target"
              tone="bad"
            />
            <MetricCard
              label="Validation closed"
              value={`${structureStudy?.summary.clear_validation_closed_count ?? 0} / ${structureStudy?.summary.blocked_validation_closed_count ?? 0}`}
              helper="Clear / blocked"
            />
            <MetricCard
              label="LAB-53 verdict"
              value={labelFor(structureStudy?.summary.verdict || "-")}
              helper="Shadow only"
              tone="warn"
            />
          </section>

          <SectionCard
            title="LAB-53 Structure Clearance Shadow"
            description="Menguji apakah MID_SHORT 1h lebih sehat ketika support 1h closed tidak berada di antara entry dan target. Signal live dan TP/SL tidak diubah."
          >
            <StructureStatusTable rows={structureStudy?.status_rows || []} />
            <div className="border-t border-line p-4 text-sm text-slate-700">
              <span className="font-semibold">Action: </span>
              {structureStudy?.summary.recommended_action || "Belum tersedia."}
            </div>
          </SectionCard>

          <SectionCard
            title="Structure-clear exit variants"
            description="Exit alternatif diuji hanya pada fixed cohort STRUCTURE_CLEAR. Kolom blocked validation menjadi pembanding, bukan signal baru."
          >
            <StructureExitTable rows={structureStudy?.exit_variant_rows || []} />
          </SectionCard>

          <SectionCard
            title="Full STRUCTURE_BLOCKED ledger"
            description="Semua signal dalam scope aktif yang support proxy 1h-nya berada di jalur menuju target short."
          >
            <StructureBlockedTable rows={structureStudy?.blocked_case_rows || []} />
          </SectionCard>

          <SectionCard title="LAB-53 limitations" description={structureStudy?.method || "Metode belum tersedia."}>
            <ul className="grid gap-2 p-4 text-sm text-slate-700 md:grid-cols-2">
              {(structureStudy?.limitations || []).map((item) => <li key={item} className="rounded border border-line bg-field/40 p-3">{item}</li>)}
            </ul>
          </SectionCard>

          <section className="grid gap-3 md:grid-cols-2 xl:grid-cols-6">
            <MetricCard label="Target too far" value={targetStudy?.summary.target_too_far_count ?? 0} helper={`${targetStudy?.summary.unique_symbol_count ?? 0} unique symbols`} tone="warn" />
            <MetricCard label="TP control" value={targetStudy?.summary.tp_control_count ?? 0} helper="Pembanding cohort yang sama" />
            <MetricCard label="Context lengkap" value={`${targetStudy?.summary.complete_context_count ?? 0}/${targetStudy?.summary.target_too_far_count ?? 0}`} helper="ATR + structure + flow + OI" />
            <MetricCard label="Hipotesis dominan" value={labelFor(targetStudy?.summary.dominant_hypothesis || "-")} helper={`${targetStudy?.summary.dominant_hypothesis_count ?? 0} primary cases`} tone="warn" />
            <MetricCard label="Exit variants" value={targetStudy?.counterfactual_rows.length ?? 0} helper="Fixed cohort, horizon 4h" />
            <MetricCard label="LAB-52 verdict" value={labelFor(targetStudy?.summary.verdict || "-")} helper="Read-only, bukan rule live" tone="warn" />
          </section>

          <SectionCard
            title="LAB-52 Target distance decomposition"
            description="Membedah apakah target gagal karena ATR membesar, entry terlambat, range menyusut, momentum melemah, support menghalangi, atau murni geometri RR. Threshold berasal dari kuartil TP control pada cohort yang sama."
          >
            <HypothesisTable rows={targetStudy?.hypothesis_rows || []} />
          </SectionCard>

          <SectionCard
            title="TARGET_TOO_FAR vs TP control"
            description="Angka sebelum entry dan outcome diagnostics ditampilkan terpisah. Forward range, taker, volume, dan OI tidak boleh dipakai sebagai input signal karena baru diketahui setelah entry."
          >
            <TargetMetricTable rows={targetStudy?.metric_comparison_rows || []} />
          </SectionCard>

          <SectionCard
            title="Exit geometry counterfactual"
            description="Signal cohort tetap, futures candle nyata, biaya realistis, horizon 4h, dan same-candle dihitung konservatif. Validation harus membaik sebelum sebuah variasi layak dipantau lebih jauh."
          >
            <CounterfactualTable rows={targetStudy?.counterfactual_rows || []} />
          </SectionCard>

          <SectionCard
            title="Full TARGET_TOO_FAR case ledger"
            description="Seluruh kasus dalam scope aktif, bukan contoh terpilih. Waktu WIB dan angka aktual dapat dibuka ke chart signal masing-masing."
          >
            <TargetCaseLedger rows={targetStudy?.case_rows || []} />
          </SectionCard>

          <SectionCard title="LAB-52 limitations" description={targetStudy?.method || "Metode belum tersedia."}>
            <ul className="grid gap-2 p-4 text-sm text-slate-700 md:grid-cols-2">
              {(targetStudy?.limitations || []).map((item) => <li key={item} className="rounded border border-line bg-field/40 p-3">{item}</li>)}
            </ul>
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
            <SectionCard title="Latest SL diagnostics" description="Primary cause, contributor, dan chart Entry/SL/TP tersedia pada detail signal.">
              <SignalTable items={data?.latest_sl_signals || []} showFailureCause />
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

function StructureStatusTable({ rows }: { rows: MidShortStructureClearanceStatusRow[] }) {
  return (
    <div className="table-wrap">
      <table className="ops-table">
        <thead>
          <tr>
            <th>Structure status</th>
            <th>All cohort</th>
            <th>Train</th>
            <th>Validation</th>
            <th>Validation delta</th>
            <th>Interpretation</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.status}>
              <td>
                <StatusBadge value={row.status} />
                <div className="mt-1 text-xs text-slate-500">{fmtNumber(row.sample_retention_pct)}% retained</div>
              </td>
              <td><StructurePerfCell value={row.all} /></td>
              <td><StructurePerfCell value={row.train} /></td>
              <td><StructurePerfCell value={row.validation} /></td>
              <td className="text-xs">
                <div>Avg {fmtSigned(row.validation.realistic_avg_r_delta_vs_baseline)}R</div>
                <div>SL {fmtSigned(row.validation.sl_share_delta_vs_baseline)} pp</div>
                <div>DD {fmtSigned(row.validation.max_drawdown_delta_vs_baseline)}R</div>
              </td>
              <td className="max-w-md text-slate-600">{row.read}</td>
            </tr>
          ))}
          {!rows.length && <tr><td colSpan={6} className="py-8 text-center text-sm text-slate-500">Structure study belum tersedia.</td></tr>}
        </tbody>
      </table>
    </div>
  );
}

function StructurePerfCell({ value }: { value: MidShortStructureClearanceStatusRow["all"] }) {
  return (
    <div className="min-w-32 text-xs">
      <div className="font-semibold">n {value.sample_count} / closed {value.closed_count}</div>
      <div>TP {value.tp_count} / SL {value.sl_count} / open {value.open_count}</div>
      <div>{fmtSigned(value.realistic_total_r_closed)}R / avg {fmtSigned(value.realistic_avg_r_closed)}R</div>
      <div>DD {fmtSigned(value.max_realistic_drawdown_r)}R</div>
    </div>
  );
}

function StructureExitTable({ rows }: { rows: MidShortStructureExitVariantRow[] }) {
  return (
    <div className="table-wrap">
      <table className="ops-table">
        <thead>
          <tr>
            <th>Exit variant</th>
            <th>Clear all</th>
            <th>Clear train</th>
            <th>Clear validation</th>
            <th>Blocked validation</th>
            <th>Validation delta</th>
            <th>Verdict</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.config_id}>
              <td className="max-w-xs">
                <div className="font-semibold">{row.label}</div>
                <div className="text-xs text-slate-500">Risk {fmtNumber(row.risk_scale)}x</div>
              </td>
              <td><CounterfactualPerfCell value={row.clear_all} /></td>
              <td><CounterfactualPerfCell value={row.clear_train} /></td>
              <td><CounterfactualPerfCell value={row.clear_validation} /></td>
              <td><CounterfactualPerfCell value={row.blocked_validation} /></td>
              <td className="text-xs">
                <div>vs logged {fmtSigned(row.clear_validation_avg_delta_vs_logged)}R</div>
                <div>vs blocked {fmtSigned(row.clear_validation_avg_delta_vs_blocked)}R</div>
              </td>
              <td><StatusBadge value={row.verdict} /></td>
            </tr>
          ))}
          {!rows.length && <tr><td colSpan={7} className="py-8 text-center text-sm text-slate-500">Exit variant belum tersedia.</td></tr>}
        </tbody>
      </table>
    </div>
  );
}

function StructureBlockedTable({ rows }: { rows: MidShortStructureBlockedCase[] }) {
  return (
    <div className="table-wrap">
      <table className="ops-table">
        <thead>
          <tr>
            <th>Signal WIB</th>
            <th>Symbol</th>
            <th>Entry / support / target</th>
            <th>Support geometry</th>
            <th>Outcome</th>
            <th>Failure read</th>
            <th>Detail</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.signal_id}>
              <td className="whitespace-nowrap text-xs">{row.signal_time_wib || fmtTime(row.signal_timestamp)}</td>
              <td className="font-semibold text-blue-700">{row.symbol}</td>
              <td className="text-xs">
                <div>{fmtPrice(row.entry)} / {fmtPrice(row.support_price_proxy)} / {fmtPrice(row.take_profit)}</div>
                <div className="text-slate-500">SL {fmtPrice(row.stop_loss)}</div>
              </td>
              <td className="text-xs">
                <div>{fmtNumber(row.support_distance_r)}R from entry</div>
                <div>{fmtNumber(row.support_clearance_to_target_r)}R before target</div>
                <div className="text-slate-500">{labelFor(row.support_method)}</div>
              </td>
              <td>
                <StatusBadge value={row.result_status} />
                <div className="mt-1 text-xs font-semibold">{fmtSigned(row.realistic_r)}R</div>
              </td>
              <td><StatusBadge value={row.failure_primary_cause || "UNAVAILABLE"} /></td>
              <td>
                <Link
                  className="font-semibold text-blue-700 hover:underline"
                  href={`/signals/${encodeURIComponent(row.symbol)}?timeframe=1h&signal_id=${encodeURIComponent(row.signal_id)}`}
                >
                  Open chart
                </Link>
              </td>
            </tr>
          ))}
          {!rows.length && <tr><td colSpan={7} className="py-8 text-center text-sm text-slate-500">Tidak ada STRUCTURE_BLOCKED dalam scope ini.</td></tr>}
        </tbody>
      </table>
    </div>
  );
}

function HypothesisTable({ rows }: { rows: MidShortFailureAnatomyResponse["target_distance_study"]["hypothesis_rows"] }) {
  return (
    <div className="table-wrap">
      <table className="ops-table">
        <thead>
          <tr>
            <th>Primary hypothesis</th>
            <th>Primary cases</th>
            <th>Multi-label cases</th>
            <th>Interpretation</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.hypothesis}>
              <td><StatusBadge value={row.hypothesis} /></td>
              <td className="font-semibold">{row.primary_count} / {fmtNumber(row.primary_share_pct)}%</td>
              <td>{row.multi_label_count} / {fmtNumber(row.multi_label_share_pct)}%</td>
              <td className="max-w-3xl text-slate-600">{row.read}</td>
            </tr>
          ))}
          {!rows.length && <tr><td colSpan={4} className="py-8 text-center text-sm text-slate-500">Belum ada TARGET_TOO_FAR pada filter ini.</td></tr>}
        </tbody>
      </table>
    </div>
  );
}

function TargetMetricTable({ rows }: { rows: MidShortTargetDistanceMetricRow[] }) {
  return (
    <div className="table-wrap">
      <table className="ops-table">
        <thead>
          <tr>
            <th>Metric</th>
            <th>TARGET_TOO_FAR Q1 / median / Q3</th>
            <th>TP control Q1 / median / Q3</th>
            <th>Other SL Q1 / median / Q3</th>
            <th>Median delta vs TP</th>
            <th>Coverage target</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.field}>
              <td>
                <div className="font-semibold">{row.label}</div>
                <div className="text-xs text-slate-500">{row.field}</div>
              </td>
              <td>{distributionText(row.target_too_far)}</td>
              <td>{distributionText(row.tp_control)}</td>
              <td>{distributionText(row.other_sl)}</td>
              <td className="font-semibold">{fmtSigned(row.median_delta_vs_tp)}</td>
              <td>{row.target_too_far.available_count}/{row.target_too_far.sample_count}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function CounterfactualTable({ rows }: { rows: MidShortCounterfactualRow[] }) {
  return (
    <div className="table-wrap">
      <table className="ops-table">
        <thead>
          <tr>
            <th>Exit variant</th>
            <th>All cohort</th>
            <th>Train</th>
            <th>Validation</th>
            <th>Validation delta</th>
            <th>Target subset</th>
            <th>Max DD / concentration</th>
            <th>Verdict</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.config_id}>
              <td className="max-w-xs">
                <div className="font-semibold">{row.label}</div>
                <div className="text-xs text-slate-500">{row.evaluation_horizon}</div>
              </td>
              <td><CounterfactualPerfCell value={row.all} /></td>
              <td><CounterfactualPerfCell value={row.train} /></td>
              <td><CounterfactualPerfCell value={row.validation} /></td>
              <td className="font-semibold">{fmtSigned(row.validation_avg_r_delta_vs_control)}R avg</td>
              <td><CounterfactualPerfCell value={row.target_too_far_subset} /></td>
              <td className="text-xs">
                <div>{fmtSigned(row.all.max_drawdown_r)}R DD</div>
                <div>{row.all.top_symbol || "-"} {fmtNumber(row.all.top_symbol_share_pct)}%</div>
              </td>
              <td><StatusBadge value={row.verdict} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function CounterfactualPerfCell({ value }: { value: MidShortCounterfactualRow["all"] }) {
  return (
    <div className="min-w-36 text-xs">
      <div className="font-semibold">n {value.sample_count} / {fmtSigned(value.total_realistic_r)}R</div>
      <div>TP {value.tp_count} / SL {value.sl_count} / BE {value.breakeven_count}</div>
      <div>Both {value.both_count} / Neither {value.neither_count}</div>
      <div>Avg {fmtSigned(value.avg_realistic_r)}R</div>
    </div>
  );
}

function TargetCaseLedger({ rows }: { rows: MidShortTargetDistanceCase[] }) {
  return (
    <div className="grid gap-3 p-4 xl:grid-cols-2">
      {rows.map((row) => (
        <article className="rounded border border-line bg-white p-4" key={row.signal_id}>
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <div className="text-base font-bold text-blue-700">{row.symbol}</div>
              <div className="text-xs text-slate-500">{row.signal_time_wib || fmtTime(row.signal_timestamp)}</div>
            </div>
            <div className="flex flex-wrap gap-2">
              <StatusBadge value={row.target_distance_primary_hypothesis || "RR_GEOMETRY_MISMATCH"} />
              <StatusBadge value={row.target_distance_context_status || "CONTEXT_PARTIAL"} />
            </div>
          </div>

          <div className="mt-4 grid gap-3 text-sm sm:grid-cols-2 lg:grid-cols-4">
            <CaseMetric label="Entry / SL / TP" value={`${fmtPrice(row.entry)} / ${fmtPrice(row.stop_loss)} / ${fmtPrice(row.take_profit)}`} />
            <CaseMetric label="ATR 1h / risk" value={`${fmtPrice(row.atr_1h_at_entry)} / ${fmtNumber(row.logged_risk_atr_ratio)}x`} helper={`${fmtNumber(row.atr_pct_entry)}% of entry`} />
            <CaseMetric label="ATR vs history" value={`${fmtNumber(row.atr_vs_30_median)}x`} helper={`signal/prior ${fmtNumber(row.atr_signal_inflation_ratio)}x`} />
            <CaseMetric label="Signal TR / ATR" value={`${fmtNumber(row.signal_true_range_atr)}x`} helper={`RR ${fmtNumber(row.rr)}R`} />
            <CaseMetric label="Pre-entry move" value={`1h ${fmtSigned(row.pre_entry_1h_move_atr)} / 4h ${fmtSigned(row.pre_entry_4h_move_atr)} ATR`} />
            <CaseMetric label="Path before SL" value={`MFE ${fmtSigned(row.mfe_before_first_hit_r)}R`} helper={`MAE ${fmtSigned(row.mae_before_first_hit_r)}R / candle ${fmtNumber(row.first_hit_candle_index)}`} />
            <CaseMetric label="Forward 1h range" value={`${fmtNumber(row.forward_1h_realized_range_atr)} ATR`} helper={`Volume ${fmtNumber(row.forward_1h_volume_vs_pre30)}x`} />
            <CaseMetric label="Taker sell" value={`${fmtFractionPct(row.entry_taker_sell_ratio)} -> ${fmtFractionPct(row.forward_1h_taker_sell_ratio)}`} helper={`delta ${fmtSigned(row.taker_sell_delta_1h)}`} />
            <CaseMetric label="Forward OI" value={`${fmtSigned(row.forward_1h_oi_change_pct)}%`} />
            <CaseMetric label="Support proxy" value={`${fmtNumber(row.support_distance_r)}R`} helper={row.support_before_target ? "Support berada sebelum target" : "Tidak berada sebelum target"} />
          </div>

          <div className="mt-3 flex flex-wrap items-center justify-between gap-2 border-t border-line pt-3 text-xs text-slate-600">
            <div>{(row.target_distance_hypotheses || []).map((value) => labelFor(value)).join("; ") || "No hypothesis"}</div>
            <Link
              className="font-semibold text-blue-700 hover:underline"
              href={`/signals/${encodeURIComponent(row.symbol)}?timeframe=1h&signal_id=${encodeURIComponent(row.signal_id)}`}
            >
              Open evidence chart
            </Link>
          </div>
        </article>
      ))}
      {!rows.length && <div className="py-8 text-center text-sm text-slate-500 xl:col-span-2">Belum ada case dalam scope aktif.</div>}
    </div>
  );
}

function CaseMetric({ label, value, helper }: { label: string; value: string; helper?: string }) {
  return (
    <div>
      <div className="text-xs font-semibold uppercase text-slate-500">{label}</div>
      <div className="mt-1 font-semibold text-ink">{value}</div>
      {helper ? <div className="mt-1 text-xs text-slate-500">{helper}</div> : null}
    </div>
  );
}

function distributionText(value: MidShortTargetDistanceMetricRow["target_too_far"]): string {
  return `${fmtNumber(value.q1)} / ${fmtNumber(value.median)} / ${fmtNumber(value.q3)}`;
}

function fmtFractionPct(value?: string | number | null): string {
  if (value === null || value === undefined || value === "") return "-";
  const number = Number(value);
  return Number.isFinite(number) ? `${fmtNumber(number * 100)}%` : String(value);
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

function CauseTable({ rows }: { rows: MidShortSlFailureCauseRow[] }) {
  return (
    <div className="table-wrap">
      <table className="ops-table">
        <thead>
          <tr>
            <th>Primary cause</th>
            <th>SL / share</th>
            <th>MFE / MAE before SL</th>
            <th>Median hit candle</th>
            <th>Path evidence</th>
            <th>Supporting flags</th>
            <th>Next shadow research</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.cause}>
              <td><StatusBadge value={row.cause} /></td>
              <td className="font-semibold">{row.sl_count} / {fmtNumber(row.sl_share_pct)}%</td>
              <td>{fmtSigned(row.median_mfe_before_sl_r)}R / {fmtSigned(row.median_mae_before_sl_r)}R</td>
              <td>{fmtNumber(row.median_first_hit_candle_index)}</td>
              <td>
                <StatusBadge value={row.evidence_strength} />
                <div className="mt-1 text-xs text-slate-500">
                  After-SL TP {row.after_sl_target_within_4h_count}; near-TP {row.tp_near_before_sl_count}
                </div>
              </td>
              <td className="text-xs text-slate-600">
                <div>Reverse clean: {row.reverse_clean_count}</div>
                <div>Regime conflict: {row.regime_conflict_count}</div>
                <div>Overextended: {row.overextended_count}</div>
              </td>
              <td className="max-w-lg text-sm text-slate-600">{row.research_action || "-"}</td>
            </tr>
          ))}
          {!rows.length && (
            <tr>
              <td colSpan={7} className="py-8 text-center text-sm text-slate-500">Belum ada SL untuk diklasifikasikan.</td>
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

function SignalTable({ items, showFailureCause = false }: { items: SignalPerformanceItem[]; showFailureCause?: boolean }) {
  return (
    <div className="table-wrap">
      <table className="ops-table">
        <thead>
          <tr>
            <th>Time WIB</th>
            <th>Symbol</th>
            <th>{showFailureCause ? "Diagnosis" : "Path"}</th>
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
                <td className="max-w-md">
                  {showFailureCause ? (
                    <>
                      <StatusBadge value={String(item.failure_primary_cause || "MIXED_UNRESOLVED")} />
                      <div className="mt-1 text-xs text-slate-600">{String(item.failure_cause_reason || "-")}</div>
                      <div className="mt-1 text-xs text-slate-500">Path: {labelFor(String(item.path_type || "-"))}</div>
                      {Array.isArray(item.failure_contributors) && item.failure_contributors.length ? (
                        <div className="mt-1 text-xs text-slate-500">
                          Contributors: {item.failure_contributors.map((value) => labelFor(String(value))).join(", ")}
                        </div>
                      ) : null}
                    </>
                  ) : <StatusBadge value={String(item.path_type || "-")} />}
                </td>
                <td><StatusBadge value={raw.result_status} /></td>
                <td>{fmtSigned(raw.realistic_realized_r ?? raw.realistic_unrealized_r)}R</td>
                <td>{fmtSigned(raw.mfe_r)} / {fmtSigned(raw.mae_r)}</td>
                <td className="text-xs">
                  <div>Entry {fmtPrice(raw.entry)}</div>
                  <div>SL {fmtPrice(raw.stop_loss)}</div>
                  <div>TP {fmtPrice(raw.take_profit)}</div>
                </td>
                <td>
                  <Link
                    className="font-semibold text-blue-700 hover:underline"
                    href={`/signals/${encodeURIComponent(raw.symbol)}?timeframe=${encodeURIComponent(raw.timeframe)}&signal_id=${encodeURIComponent(raw.signal_id)}`}
                  >
                    Open chart
                  </Link>
                </td>
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
