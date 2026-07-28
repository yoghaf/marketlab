import Link from "next/link";

import { EmptyState } from "@/components/EmptyState";
import { MetricCard } from "@/components/MetricCard";
import { PageHeader } from "@/components/PageHeader";
import { SectionCard } from "@/components/SectionCard";
import { StatusBadge } from "@/components/StatusBadge";
import {
  MidLongAblationRow,
  MidLongAxisAuditRow,
  MidLongAxisCrossRow,
  MidLongBaselineResponse,
  MidLongBreakoutAcceptedDeepDive,
  MidLongBreakoutCauseRow,
  MidLongBreakoutCauseOverlapRow,
  MidLongBreakoutDraftRow,
  MidLongBreakoutFieldAvailabilityRow,
  MidLongBreakoutFilterRow,
  MidLongBreakoutInteractionRow,
  MidLongBreakoutLabelPurityRow,
  MidLongBreakoutMechanismRow,
  MidLongBreakoutObservablePathRow,
  MidLongBreakoutShadowArmRow,
  MidLongDefinitionLayerRow,
  MidLongDefinitionResetLab,
  MidLongDraftPreviewRow,
  MidLongDamageExperimentRow,
  MidLongEconomicRow,
  MidLongEvidenceComparisonRow,
  MidLongFirstHourActionSimulation,
  MidLongFirstHourDelayedEntryRow,
  MidLongFirstHourEarlyExitRow,
  MidLongFirstHourCheckpointRow,
  MidLongFirstHourFamilyStateRow,
  MidLongFirstHourResponseAudit,
  MidLongFirstHourSampleRow,
  MidLongFirstHourStateRow,
  MidLongGeometryThresholdRow,
  MidLongIntegrityAudit,
  MidLongPathDecisionRow,
  MidLongReverseShadowAudit,
  MidLongReverseShadowRow,
  MidLongResetCohortRow,
  MidLongResetDecisionRow,
  MidLongResetFamilyModifierRow,
  MidLongResetModifierRow,
  MidLongResetPrimaryRow,
  MidLongSlAnatomyV2,
  MidLongSlCauseRow,
  MidLongSlPathCauseRow,
  MidLongSlPathRow,
  MidLongSubsetDimensionRow,
  MidLongSubSetupSplitLab,
  MidLongSubSetupRow,
  MidLongTaxonomyDimensionRow,
  MidLongTaxonomyPathCrossRow,
  MidLongTaxonomyPathRow,
  MidLongTaxonomyStudy,
  SignalPerformanceItem,
  fetchJson,
  fmtNumber,
  fmtPrice,
  fmtTime
} from "@/lib/api";

type SearchParams = Promise<Record<string, string | string[] | undefined>>;

export const dynamic = "force-dynamic";

export default async function MidLongDefinitionAuditPage({ searchParams }: { searchParams: SearchParams }) {
  const params = await searchParams;
  const limit = normalizeNumber(firstParam(params.limit), 50, 10, 100);
  let payload: MidLongBaselineResponse | null = null;
  let error: string | null = null;

  try {
    payload = await fetchJson<MidLongBaselineResponse>(
      `/api/signal-candidates/mid-long-1h-baseline?limit=${limit}`,
      { revalidateSeconds: 120 }
    );
  } catch (reason) {
    error = reason instanceof Error ? reason.message : "MID_LONG 1h definition audit API failed";
  }

  const audit = payload?.definition_audit;
  const aggregate = payload?.aggregate;
  const coverage = payload?.snapshot_coverage;
  const summary = payload?.research_summary;
  const verdict = audit?.verdict;
  const taxonomy = audit?.taxonomy_study;

  return (
    <div className="space-y-5">
      <PageHeader
        title="MID_LONG 1h Definition Audit"
        badge="READ-ONLY - BELUM RULE V2.1"
        subtitle="Halaman ini membedah fundamental MID_LONG 1h: apakah loss berasal dari definisi entry, structure, flow, crowding, geometry TP/SL, atau biaya realistis. Semua signal tetap masuk sampel; flag belum menjadi gate live."
        updatedAt={fmtTime(payload?.generated_at_utc)}
      />

      <div className="flex flex-wrap gap-2 text-sm">
        <Link className="rounded-md border border-line bg-white px-3 py-2 font-semibold hover:bg-field" href="/signal-performance?stage=MID_LONG&timeframe=1h&position_lock=true">
          Open closed signal history
        </Link>
        <Link className="rounded-md border border-line bg-white px-3 py-2 font-semibold hover:bg-field" href="/scanner?tier=SIGNAL_CANDIDATE">
          Open live radar
        </Link>
        <Link className="rounded-md border border-line bg-white px-3 py-2 font-semibold hover:bg-field" href="/signal-quality-lab?stage=MID_LONG&timeframe=1h">
          Open quality lab
        </Link>
      </div>

      {error ? (
        <div className="rounded-md border border-stale bg-red-50 p-4 text-sm text-stale">{error}</div>
      ) : payload && audit && aggregate && coverage ? (
        <>
          <SectionCard
            title="Cara baca halaman ini"
            description="Ini lab pondasi MID_LONG 1h. Jangan baca flag sebagai rule. Kita mencari penyebab TP/SL dulu sebelum bicara Optuna, RR, atau V2.1 shadow."
          >
            <div className="grid gap-3 p-4 md:grid-cols-2 xl:grid-cols-4">
              <Info label="Scope" value="MID_LONG 1h only" helper={`${coverage.mid_long_1h_rows} row dari snapshot 1h`} />
              <Info label="Metode" value="Flag-first audit" helper="Semua signal tetap masuk; EXT/STR/FLW/CRD cuma penanda damage." />
              <Info label="Target jawaban" value={humanFlag(verdict?.primary || "WAITING")} helper={verdict?.reasons?.[0] || "Tunggu snapshot audit."} />
              <Info label="Tidak disentuh" value="Rule live" helper="Tidak mengubah Signal Factory, scanner, SL/TP, atau execution." />
            </div>
          </SectionCard>

          <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-8">
            <MetricCard label="Sample" value={aggregate.signals_evaluated} helper="MID_LONG 1h closed" />
            <MetricCard label="TP / SL" value={`${aggregate.tp_count} / ${aggregate.sl_count}`} helper={`${aggregate.closed_count} closed`} tone={Number(aggregate.tp_count) >= Number(aggregate.sl_count) ? "good" : "bad"} />
            <MetricCard label="Winrate" value={formatPct(aggregate.winrate_pct)} helper="TP / (TP + SL)" />
            <MetricCard label="Ideal R" value={`${fmtSigned(aggregate.total_r_closed)}R`} helper="Sebelum realism cost" tone={toneFor(aggregate.total_r_closed)} />
            <MetricCard label="Realistic R" value={`${fmtSigned(aggregate.realistic_total_r_closed)}R`} helper="Fee + spread + slippage" tone={toneFor(aggregate.realistic_total_r_closed)} />
            <MetricCard label="Avg realistic" value={`${fmtSigned(aggregate.realistic_avg_r_closed)}R`} helper="Per signal" tone={toneFor(aggregate.realistic_avg_r_closed)} />
            <MetricCard label="Median realistic" value={`${fmtSigned(summary?.median_realistic_r_closed)}R`} helper="Tengah distribusi" tone={toneFor(summary?.median_realistic_r_closed)} />
            <MetricCard label="Max DD" value={`${fmtSigned(summary?.max_realistic_drawdown_r)}R`} helper="Drawdown realistic" tone="warn" />
          </section>

          {verdict && (
            <SectionCard title="Definition verdict sementara" description="Verdict ini hanya membaca audit. Ini bukan promosi rule, cuma peta masalah utama.">
              <div className="grid gap-3 p-4 lg:grid-cols-[0.8fr_1.2fr]">
                <div className="rounded-md border border-amber-300 bg-amber-50 p-4">
                  <div className="text-xs font-semibold uppercase text-amber-800">Primary read</div>
                  <div className="mt-1 text-2xl font-black text-ink">{humanFlag(verdict.primary)}</div>
                  <div className="mt-2 flex flex-wrap gap-2">
                    {verdict.labels.map((label) => <StatusBadge key={label} value={humanFlag(label)} />)}
                  </div>
                </div>
                <div className="rounded-md border border-line bg-white p-4">
                  <div className="text-xs font-semibold uppercase text-slate-500">Reasons</div>
                  <ul className="mt-2 grid gap-2 text-sm leading-6 text-slate-700">
                    {verdict.reasons.map((reason) => <li key={reason}>- {reason}</li>)}
                  </ul>
                  <div className="mt-3 rounded-md border border-line bg-field/50 p-3 text-sm font-semibold text-ink">
                    {verdict.recommended_next_step}
                  </div>
                </div>
              </div>
            </SectionCard>
          )}

          {audit.integrity_audit && (
            <SectionCard
              title="0. Integrity audit"
              description="Tahap kecil sebelum Damage Isolation: cek apakah label path/taxonomy ekonominya masuk akal. Kalau anomali masih ada, jangan buru-buru membuat protection rule."
            >
              <IntegrityAuditPanel audit={audit.integrity_audit} />
            </SectionCard>
          )}

          {audit.definition_reset_lab && (
            <SectionCard
              title="1. Definition Reset v1"
              description="Taxonomy baru: primary family mutually exclusive, modifier boleh overlap, dan derived decision hanya untuk riset. Ini menjawab apakah MID_LONG V2 terlalu campur."
            >
              <DefinitionResetPanel lab={audit.definition_reset_lab} />
            </SectionCard>
          )}

          {payload?.reverse_shadow_audit && (
            <SectionCard
              title="2. Reverse Shadow Audit"
              description="Audit penasaran: kalau entry MID_LONG 1h yang sama dibaca sebagai short proxy, apakah hasilnya membaik. Ini bukan rule dan belum replay candle final."
            >
              <ReverseShadowAuditPanel audit={payload.reverse_shadow_audit} />
            </SectionCard>
          )}

          {audit.sl_anatomy_v2 && (
            <SectionCard
              title="3. SL Anatomy v2"
              description="Peta penyebab SL: bucket jalur gagal, cause pre-entry yang menempel, dan simulasi retained cohort kalau cause itu dihindari. Semua masih diagnostic-only."
            >
              <SlAnatomyPanel anatomy={audit.sl_anatomy_v2} />
            </SectionCard>
          )}

          {audit.first_hour_response_audit && (
            <SectionCard
              title="4. First-Hour Response Audit"
              description="Audit reaksi 1 jam pertama setelah entry MID_LONG 1h. Ini menjawab apakah signal langsung confirm, diam, berbalik, atau gagal struktur secara proxy. Belum menjadi gate live."
            >
              <FirstHourResponsePanel audit={audit.first_hour_response_audit} />
            </SectionCard>
          )}

          {audit.first_hour_action_simulation && (
            <SectionCard
              title="5. First-Hour Action Simulation"
              description="Simulasi read-only dari hasil audit 1 jam pertama: apakah lebih baik menunggu konfirmasi 1h, atau exit cepat saat 1h pertama sudah berbalik. Ini proxy, bukan replay entry baru."
            >
              <FirstHourActionSimulationPanel simulation={audit.first_hour_action_simulation} />
            </SectionCard>
          )}

          {audit.sub_setup_split_lab && (
            <SectionCard
              title="6. Legacy Sub-Setup Split Lab"
              description="MID_LONG 1h dipecah menjadi sub-label: breakout proxy, retest, support bounce, mid-range invalid, dan unclassified. Tujuannya mencari bagian yang masih layak hidup."
            >
              <SubSetupSplitPanel lab={audit.sub_setup_split_lab} />
            </SectionCard>
          )}

          {audit.breakout_accepted_deep_dive && (
            <SectionCard
              title="7. Breakout-State Diagnostics"
              description="Audit khusus BREAKOUT_PROXY_CANDIDATE. Fokusnya pre-entry zone: penetrasi close, body terhadap zona, wick, umur zona, jarak entry, dan ruang ke resistance berikutnya."
            >
              <BreakoutDeepDivePanel lab={audit.breakout_accepted_deep_dive} />
            </SectionCard>
          )}

          {audit.damage_isolation && (
            <SectionCard
              title="8. Damage Isolation"
              description="DI-00 sampai DI-05 membandingkan retained cohort vs removed damage. Ini masih read-only dan belum menjadi Signal Factory gate."
            >
              <DamageIsolationPanel damage={audit.damage_isolation} />
            </SectionCard>
          )}

          {taxonomy && (
            <>
              <SectionCard
                title="9. Taxonomy v1"
                description="MID_LONG 1h sekarang dibedah sebagai banyak flag sekaligus: setup, breakout/retest, flow, crowding, room, cost, dan path setelah entry. Ini belum mengubah rule."
              >
                <TaxonomyOverview taxonomy={taxonomy} />
              </SectionCard>

              <SectionCard
                title="10. Pre-entry dimensions"
                description="Bucket ini dibuat dari data sebelum entry. Tujuannya mencari bagian definisi MID_LONG yang paling sering membawa TP atau SL."
              >
                <TaxonomyDimensionPanels taxonomy={taxonomy} />
              </SectionCard>

              <SectionCard
                title="11. Path sequencing +0.5R"
                description="Path ini menjawab apakah signal langsung salah arah, cuma wick profit, close diterima lalu gagal, atau continuation bersih. Acceptance canonical sementara: close profit +0.5R."
              >
                <TaxonomyPathTable rows={taxonomy.path_sequence_rows} />
              </SectionCard>

              <div className="grid gap-4 2xl:grid-cols-2">
                <SectionCard title="12A. Setup x path" description="Cek setup family mana yang paling sering jatuh ke instant SL, wick fail, atau clean continuation.">
                  <TaxonomyCrossTable rows={taxonomy.taxonomy_path_cross_tables.setup_family_x_path || []} />
                </SectionCard>
                <SectionCard title="12B. Flow x path" description="Cek apakah flow sebelum entry punya hubungan jelas dengan path setelah entry.">
                  <TaxonomyCrossTable rows={taxonomy.taxonomy_path_cross_tables.flow_x_path || []} />
                </SectionCard>
              </div>

              <SectionCard
                title="13. Draft V2.1 preview"
                description="Empat skenario ini hanya preview riset. Retained/discarded dibandingkan untuk tahu apakah hygiene, breakout, retest, atau crowding interaction layak diteliti lanjut."
              >
                <DraftPreviewTable rows={taxonomy.draft_v21_previews} />
              </SectionCard>
            </>
          )}

          <SectionCard
            title="14. Layer decomposition"
            description="Pisahkan dulu apakah masalahnya sudah ada di ideal R, atau baru rusak setelah fee/spread/slippage. EXECUTION_VALID cuma strata audit, bukan filter live."
          >
            <LayerTable rows={audit.layer_decomposition} />
          </SectionCard>

          <SectionCard
            title="15. Path anatomy legacy"
            description="Ini pemisah utama: instant SL mengarah ke problem definisi entry; sempat +1R lalu SL mengarah ke problem geometry/exit."
          >
            <PathDecisionTable rows={audit.path_decision_summary.rows} read={audit.path_decision_summary.read} />
          </SectionCard>

          <SectionCard
            title="16. 4-axis definition flags legacy"
            description="EXT, STR, FLW, dan CRD adalah flag kandidat, bukan gate. Kolom negative R share menunjukkan bucket mana yang menyumbang kerusakan terbesar."
          >
            <AxisAuditTable rows={audit.axis_rows} />
          </SectionCard>

          <div className="grid gap-4 2xl:grid-cols-2">
            <SectionCard title="17A. EXT x STR" description="Cek apakah damage terkonsentrasi pada entry extended yang dekat resistance atau mid-range.">
              <CrossTable rows={audit.cross_tables.EXTxSTR || []} />
            </SectionCard>
            <SectionCard title="17B. FLW x CRD" description="Cek apakah flow lemah dan crowding menjelaskan SL atau cuma noise.">
              <CrossTable rows={audit.cross_tables.FLWxCRD || []} />
            </SectionCard>
          </div>

          <SectionCard
            title="18. Geometry diagnostic"
            description="Kalau banyak signal pernah +0.5R/+1R tapi gagal TP, problemnya bukan hanya definisi, tapi cara panen target/stop."
          >
            <GeometryTable rows={audit.geometry_diagnostic.mfe_threshold_rows} read={audit.geometry_diagnostic.read} quantiles={audit.geometry_diagnostic} />
          </SectionCard>

          <SectionCard
            title="19. Ablation preview"
            description="Simulasi read-only: jika flag tertentu dibuang, survivor membaik atau tidak. Ini belum rule, baru calon hipotesis."
          >
            <AblationTable rows={audit.ablation_preview} />
          </SectionCard>

          <SectionCard
            title="20. TP vs SL evidence"
            description="Median dan kuartil angka aktual. Ini menjawab data mana yang beda antara signal yang kena target dan stop."
          >
            <EvidenceTable rows={(payload.evidence_comparison || []).slice(0, 18)} sampleTotal={coverage.mid_long_1h_rows} />
          </SectionCard>

          <SectionCard
            title="21. Recent closed MID_LONG 1h"
            description="Sample sinyal terbaru untuk dibuka ke detail chart. Gunakan ini untuk validasi visual bucket yang terlihat merusak."
          >
            <BaselineSignalTable rows={payload.items} />
          </SectionCard>

          <SectionCard title="Guardrails" description="Batas riset update ini.">
            <div className="grid gap-2 p-4 text-sm text-slate-700 md:grid-cols-2">
              {audit.guardrails.concat(payload.guardrails || []).map((guardrail) => (
                <div key={guardrail} className="rounded-md border border-line bg-field/40 p-3">- {guardrail}</div>
              ))}
            </div>
          </SectionCard>
        </>
      ) : (
        <EmptyState title="Definition audit belum tersedia" detail="Tunggu snapshot Signal Performance 1h dibuat oleh research loop." />
      )}
    </div>
  );
}

function DefinitionResetPanel({ lab }: { lab: MidLongDefinitionResetLab }) {
  return (
    <div>
      <div className="grid gap-3 border-b border-line p-4 lg:grid-cols-2">
        <div className="rounded-md border border-blue-200 bg-blue-50 p-4">
          <div className="text-xs font-semibold uppercase text-blue-700">Legacy retained</div>
          <div className="mt-1 text-xl font-black text-ink">{lab.legacy_definition?.label || "MID_LONG_V2_LEGACY"}</div>
          <div className="mt-2 text-sm leading-6 text-slate-700">{lab.legacy_definition?.read || "Legacy rows stay as control."}</div>
          <div className="mt-2 text-xs leading-5 text-slate-500">{lab.legacy_definition?.entry_basis}</div>
        </div>
        <div className="rounded-md border border-emerald-200 bg-emerald-50 p-4">
          <div className="text-xs font-semibold uppercase text-emerald-700">Shadow definition</div>
          <div className="mt-1 text-xl font-black text-ink">{lab.structure_first_draft?.label || "MID_LONG_STRUCTURE_FIRST_DRAFT"}</div>
          <div className="mt-2 text-sm leading-6 text-slate-700">{lab.structure_first_draft?.read || "Structure-first draft is read-only."}</div>
          <div className="mt-2"><StatusBadge value={humanFlag(lab.structure_first_draft?.promotion_state || "SHADOW_RESEARCH_ONLY")} /></div>
        </div>
      </div>

      <div className="grid gap-3 border-b border-line p-4 md:grid-cols-2 xl:grid-cols-6">
        <Info label="Taxonomy" value={lab.taxonomy_version} helper="Read-only, belum rule live." />
        <Info label="Coverage" value={formatPct(lab.coverage.classification_coverage_pct)} helper={`${lab.coverage.classified_rows}/${lab.coverage.total_rows} classified`} />
        <Info label="Unclassified" value={`${lab.coverage.unclassified_rows}`} helper={formatPct(lab.coverage.unclassified_pct)} />
        <Info label="Multi modifier" value={`${lab.coverage.multi_modifier_rows}`} helper={formatPct(lab.coverage.multi_modifier_pct)} />
        <Info label="Positive family" value={`${lab.summary.positive_candidate_family_count}`} helper="Primary candidate family with positive read." />
        <Info label="Read" value={humanFlag(lab.summary.read)} helper={lab.summary.next_action} />
      </div>

      <div className="grid gap-3 border-b border-line p-4 lg:grid-cols-2">
        <ResetSummaryCard title="Best candidate family" row={lab.summary.best_candidate_family} />
        <ResetSummaryCard title="Worst reject decision" row={lab.summary.worst_reject_decision} />
      </div>

      {(lab.cohort_comparison_rows || []).length > 0 && (
        <div className="border-b border-line">
          <div className="border-b border-line p-4">
            <div className="text-sm font-bold text-ink">Legacy V2 vs Structure-first draft</div>
            <div className="mt-1 text-sm leading-6 text-slate-600">
              Tabel ini menjawab apakah data lama dihapus atau diganti: tidak. Legacy V2 tetap control; draft baru hanya memberi label struktur di atas baris yang sama.
            </div>
          </div>
          <ResetCohortTable rows={lab.cohort_comparison_rows || []} />
        </div>
      )}

      <div className="border-b border-line p-4">
        <div className="text-sm font-bold text-ink">Primary family, modifier, decision</div>
        <div className="mt-1 text-sm leading-6 text-slate-600">
          Primary family harus satu saja per signal. Modifier boleh overlap. Derived decision cuma triage riset, bukan gate Signal Factory.
        </div>
      </div>

      <ResetPrimaryTable rows={lab.primary_family_rows} />

      <div className="grid gap-4 border-t border-line p-4 2xl:grid-cols-2">
        <div className="rounded-md border border-line bg-white">
          <div className="border-b border-line p-3">
            <div className="font-bold">Derived decision rows</div>
            <div className="text-sm text-slate-600">ELIGIBLE/REJECT/WAIT draft. Semua masih read-only.</div>
          </div>
          <ResetDecisionTable rows={lab.derived_decision_rows} />
        </div>
        <div className="rounded-md border border-line bg-white">
          <div className="border-b border-line p-3">
            <div className="font-bold">Modifier rows</div>
            <div className="text-sm text-slate-600">Modifier adalah tag risiko overlap, bukan subtype utama.</div>
          </div>
          <ResetModifierTable rows={lab.modifier_rows} />
        </div>
      </div>

      <div className="border-t border-line">
        <div className="border-b border-line p-4">
          <div className="font-bold">Family x modifier damage map</div>
          <div className="text-sm leading-6 text-slate-600">Sel ini menjawab modifier mana yang merusak family tertentu. Prioritaskan readable row dan sample cukup.</div>
        </div>
        <ResetFamilyModifierTable rows={lab.family_modifier_rows} />
      </div>

      <div className="grid gap-2 border-t border-line p-4 text-sm text-slate-700 md:grid-cols-2">
        {(lab.data_retention_policy || []).concat(lab.guardrails).map((guardrail) => (
          <div key={guardrail} className="rounded-md border border-line bg-field/40 p-3">- {guardrail}</div>
        ))}
      </div>
    </div>
  );
}

function ReverseShadowAuditPanel({ audit }: { audit: MidLongReverseShadowAudit }) {
  const best = audit.summary.best_row;
  const rows = audit.rows || [];
  const promisingRows = rows.filter((row) => row.read === "REVERSE_PROMISING_PROXY" || row.read === "REVERSE_POSITIVE_BUT_THIN");
  return (
    <div>
      <div className="grid gap-3 border-b border-line p-4 md:grid-cols-2 xl:grid-cols-6">
        <Info label="Read" value={humanFlag(audit.summary.read)} helper={audit.summary.next_action} />
        <Info label="Direction" value={humanFlag(audit.reverse_direction)} helper="Proxy dari MID_LONG menjadi short." />
        <Info label="RR tested" value={audit.rr_values.join(", ")} helper="RR reverse proxy." />
        <Info label="Readable rows" value={`${audit.summary.readable_row_count}`} helper={`Min sample ${audit.summary.min_sample}`} />
        <Info label="Promising rows" value={`${audit.summary.promising_row_count}`} helper="Masih harus replay candle." />
        <Info label="Ambiguous rows" value={`${audit.summary.ambiguous_row_count}`} helper="Butuh order candle." />
      </div>

      {best && (
        <div className="grid gap-3 border-b border-line p-4 lg:grid-cols-3">
          <div className="rounded-md border border-amber-300 bg-amber-50 p-4">
            <div className="text-xs font-semibold uppercase text-amber-800">Best reverse proxy</div>
            <div className="mt-1 text-xl font-black text-ink">{humanFlag(best.cohort_id || "-")}</div>
            <div className="mt-2 text-sm text-slate-700">RR {best.rr} | sample {best.sample_count} | TP/SL {best.tp_count}/{best.sl_count}</div>
          </div>
          <div className="rounded-md border border-line bg-white p-4">
            <div className="text-xs font-semibold uppercase text-slate-500">Realistic result</div>
            <div className={`mt-1 text-2xl font-black ${toneClass(best.realistic_total_r)}`}>{fmtSigned(best.realistic_total_r)}R</div>
            <div className="mt-2 text-sm text-slate-600">Avg {fmtSigned(best.realistic_avg_r)}R | {humanFlag(best.read || "-")}</div>
          </div>
          <div className="rounded-md border border-line bg-white p-4">
            <div className="text-xs font-semibold uppercase text-slate-500">Top concentration</div>
            <div className="mt-1 text-2xl font-black text-ink">{best.top_symbol || "-"}</div>
            <div className="mt-2 text-sm text-slate-600">{formatPct(best.top_symbol_share_pct)} of sample</div>
          </div>
        </div>
      )}

      {promisingRows.length > 0 && (
        <div className="border-b border-line p-4">
          <div className="rounded-md border border-emerald-200 bg-emerald-50 p-4 text-sm leading-6 text-emerald-900">
            Ada reverse proxy yang positif. Ini belum berarti kita balik signal; artinya cohort tersebut layak direplay candle order supaya TP/SL sequence-nya tidak cuma tebak dari MFE/MAE.
          </div>
        </div>
      )}

      <ReverseShadowTable rows={rows} />

      <div className="grid gap-2 border-t border-line p-4 text-sm text-slate-700 md:grid-cols-2">
        {audit.guardrails.map((guardrail) => (
          <div key={guardrail} className="rounded-md border border-line bg-field/40 p-3">- {guardrail}</div>
        ))}
      </div>
    </div>
  );
}

function ReverseShadowTable({ rows }: { rows: MidLongReverseShadowRow[] }) {
  if (!rows.length) return <div className="p-4"><EmptyState title="Reverse audit kosong" detail="Snapshot belum memuat reverse shadow audit." /></div>;
  return (
    <div className="table-wrap">
      <table className="ops-table">
        <thead>
          <tr>
            <th>Cohort</th>
            <th>RR</th>
            <th>N</th>
            <th>TP / SL / Both / Neither</th>
            <th>Realistic R</th>
            <th>Avg / Median</th>
            <th>Reverse path</th>
            <th>Top symbol</th>
            <th>Read</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={`${row.cohort_id}-${row.rr}`}>
              <td className="min-w-96">
                <div className="font-bold">{humanFlag(row.cohort_id)}</div>
                <div className="mt-1 text-xs text-slate-500">{humanFlag(row.definition_version)}</div>
                <div className="mt-1 text-xs leading-5 text-slate-500">{row.description}</div>
              </td>
              <td className="font-bold">{row.rr}R</td>
              <td>{row.sample_count}</td>
              <td>
                <div>{row.tp_count} / {row.sl_count} / {row.both_hit_count} / {row.neither_count}</div>
                <div className="text-xs text-slate-500">TP {formatPct(row.tp_share_pct)} | SL {formatPct(row.sl_share_pct)}</div>
              </td>
              <td className={toneClass(row.realistic_total_r)}>{fmtSigned(row.realistic_total_r)}R</td>
              <td>
                <div>{fmtSigned(row.realistic_avg_r)}R avg</div>
                <div className="text-xs text-slate-500">{fmtSigned(row.median_realistic_r)}R median</div>
              </td>
              <td>
                <div>MFE {fmtSigned(row.median_reverse_mfe_r)}R</div>
                <div className="text-xs text-slate-500">MAE {fmtSigned(row.median_reverse_mae_r)}R</div>
              </td>
              <td>{row.top_symbol || "-"} ({formatPct(row.top_symbol_share_pct)})</td>
              <td className="max-w-80"><StatusBadge value={humanFlag(row.read)} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function SlAnatomyPanel({ anatomy }: { anatomy: MidLongSlAnatomyV2 }) {
  const summary = anatomy.summary;
  const largest = summary.largest_sl_path;
  const best = summary.best_damage_tag;
  return (
    <div>
      <div className="grid gap-3 border-b border-line p-4 md:grid-cols-2 xl:grid-cols-6">
        <Info label="Read" value={humanFlag(summary.read)} helper={summary.next_action} />
        <Info label="SL sample" value={`${anatomy.sl_count}`} helper={`TP ${anatomy.tp_count} | SL share ${formatPct(anatomy.sl_share_pct)}`} />
        <Info label="Largest SL path" value={humanFlag(largest?.id || "-")} helper={`${largest?.sl_count || 0} SL`} />
        <Info label="Best damage tag" value={humanFlag(best?.id || "-")} helper={`${fmtSigned(best?.retained_realistic_total_r_delta_vs_baseline)}R retained delta`} />
        <Info label="Instant SL" value={`${summary.instant_sl_count}`} helper={formatPct(summary.instant_sl_share_pct)} />
        <Info label="Deep fail" value={`${summary.deep_fail_count}`} helper={formatPct(summary.deep_fail_share_pct)} />
      </div>

      <div className="grid gap-4 border-b border-line p-4 2xl:grid-cols-2">
        <div className="rounded-md border border-line bg-white">
          <div className="border-b border-line p-3">
            <div className="font-bold">SL path buckets</div>
            <div className="text-sm leading-6 text-slate-600">Jalur SL: langsung gagal, follow-through lemah, sempat profit lalu gagal, atau deep fail.</div>
          </div>
          <SlPathTable rows={anatomy.path_rows} />
        </div>
        <div className="rounded-md border border-line bg-white">
          <div className="border-b border-line p-3">
            <div className="font-bold">Path x cause overlap</div>
            <div className="text-sm leading-6 text-slate-600">Peta cause mana yang paling banyak muncul di tiap bucket SL.</div>
          </div>
          <SlPathCauseMatrix rows={anatomy.path_cause_matrix} />
        </div>
      </div>

      <div className="border-b border-line p-4">
        <div className="rounded-md border border-blue-200 bg-blue-50 p-4 text-sm leading-6 text-blue-950">
          Cause row bersifat overlap. Kolom “retained R” adalah simulasi diagnostik: hasil jika row dengan cause itu dibuang dari pembacaan, bukan rule live.
        </div>
      </div>

      <SlCauseTable rows={anatomy.cause_rows} />

      <div className="grid gap-2 border-t border-line p-4 text-sm text-slate-700 md:grid-cols-2">
        {anatomy.guardrails.map((guardrail) => (
          <div key={guardrail} className="rounded-md border border-line bg-field/40 p-3">- {guardrail}</div>
        ))}
      </div>
    </div>
  );
}

function SlPathTable({ rows }: { rows: MidLongSlPathRow[] }) {
  if (!rows.length) return <div className="p-4"><EmptyState title="SL path kosong" detail="Belum ada SL path untuk audit ini." /></div>;
  return (
    <div className="table-wrap">
      <table className="ops-table">
        <thead>
          <tr>
            <th>Path</th>
            <th>SL</th>
            <th>Realistic R</th>
            <th>MFE / MAE</th>
            <th>Cost / decay</th>
            <th>Family / flow</th>
            <th>Modifiers</th>
            <th>Read</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.path_bucket}>
              <td className="min-w-72">
                <div className="font-bold">{humanFlag(row.path_bucket)}</div>
                <div className="mt-1 text-xs leading-5 text-slate-500">{row.expression}</div>
              </td>
              <td>
                <div className="font-bold">{row.sl_count}</div>
                <div className="text-xs text-slate-500">{formatPct(row.sl_share_of_all_sl_pct)} of SL</div>
              </td>
              <td className={toneClass(row.realistic_total_r_closed)}>{fmtSigned(row.realistic_total_r_closed)}R</td>
              <td>
                <div>MFE {fmtSigned(row.median_mfe_r)}R</div>
                <div className="text-xs text-slate-500">MAE {fmtSigned(row.median_mae_r)}R</div>
              </td>
              <td>
                <div>Cost {fmtNumber(row.median_cost_r)}R</div>
                <div className="text-xs text-slate-500">Decay {fmtSigned(row.median_wick_decay_r)}R | 1h {fmtSigned(row.median_followthrough_1h_r)}R</div>
              </td>
              <td className="max-w-80 text-xs leading-5 text-slate-600">
                <div>{pathMixSummary(row.primary_family_mix)}</div>
                <div className="mt-1">{pathMixSummary(row.flow_mix)}</div>
              </td>
              <td className="max-w-80 text-xs leading-5 text-slate-600">{pathMixSummary(row.modifier_mix)}</td>
              <td><StatusBadge value={humanFlag(row.read)} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function SlCauseTable({ rows }: { rows: MidLongSlCauseRow[] }) {
  if (!rows.length) return <div className="p-4"><EmptyState title="SL cause kosong" detail="Belum ada cause map untuk audit ini." /></div>;
  return (
    <div className="table-wrap">
      <table className="ops-table">
        <thead>
          <tr>
            <th>Cause</th>
            <th>Matched</th>
            <th>Matched TP / SL</th>
            <th>SL capture / TP sacrificed</th>
            <th>Matched R</th>
            <th>Retained TP / SL</th>
            <th>Retained R / delta</th>
            <th>Top symbol</th>
            <th>Path / family mix</th>
            <th>Read</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.cause_id}>
              <td className="min-w-96">
                <div className="font-bold">{humanFlag(row.cause_id)}</div>
                <div className="mt-1 text-xs leading-5 text-slate-500">{row.definition}</div>
                <div className="mt-1 text-xs leading-5 text-slate-500">{row.expression}</div>
              </td>
              <td>
                <div className="font-bold">{row.matched_count}</div>
                <div className="text-xs text-slate-500">{formatPct(row.matched_share_pct)} sample</div>
              </td>
              <td>{row.matched_tp_count} / {row.matched_sl_count}</td>
              <td>
                <div>SL {formatPct(row.matched_sl_capture_pct)}</div>
                <div className="text-xs text-slate-500">TP {formatPct(row.matched_tp_sacrifice_pct)} | ratio {fmtNumber(row.sl_to_tp_capture_ratio)}</div>
              </td>
              <td className={toneClass(row.matched_realistic_total_r_closed)}>
                <div>{fmtSigned(row.matched_realistic_total_r_closed)}R</div>
                <div className="text-xs text-slate-500">{fmtSigned(row.matched_realistic_avg_r_closed)}R avg</div>
              </td>
              <td>{row.retained_tp_count || 0} / {row.retained_sl_count || 0}</td>
              <td>
                <div className={toneClass(row.retained_realistic_total_r_closed)}>{fmtSigned(row.retained_realistic_total_r_closed)}R</div>
                <div className={`text-xs ${toneClass(row.retained_realistic_total_r_delta_vs_baseline)}`}>{fmtSigned(row.retained_realistic_total_r_delta_vs_baseline)}R delta</div>
              </td>
              <td>{row.top_symbol || "-"} ({formatPct(row.top_symbol_share_pct)})</td>
              <td className="max-w-96 text-xs leading-5 text-slate-600">
                <div>{pathMixSummary(row.matched_sl_path_mix)}</div>
                <div className="mt-1">{pathMixSummary(row.matched_primary_family_mix)}</div>
                <div className="mt-1">{pathMixSummary(row.matched_flow_mix)}</div>
              </td>
              <td><StatusBadge value={humanFlag(row.read)} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function SlPathCauseMatrix({ rows }: { rows: MidLongSlPathCauseRow[] }) {
  const visible = rows.filter((row) => Number(row.count || 0) > 0).slice(0, 24);
  if (!visible.length) return <div className="p-4"><EmptyState title="Overlap kosong" detail="Belum ada cause overlap yang terdeteksi." /></div>;
  return (
    <div className="table-wrap">
      <table className="ops-table">
        <thead>
          <tr>
            <th>SL path</th>
            <th>Cause</th>
            <th>Count</th>
            <th>Share in path</th>
          </tr>
        </thead>
        <tbody>
          {visible.map((row) => (
            <tr key={`${row.path_bucket}-${row.cause_id}`}>
              <td><StatusBadge value={humanFlag(row.path_bucket)} /></td>
              <td className="max-w-80 text-sm leading-5 text-slate-700">{humanFlag(row.cause_id)}</td>
              <td className="font-bold">{row.count} / {row.path_count}</td>
              <td>{formatPct(row.path_share_pct)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function FirstHourResponsePanel({ audit }: { audit: MidLongFirstHourResponseAudit }) {
  const summary = audit.summary;
  return (
    <div>
      <div className="grid gap-3 border-b border-line p-4 md:grid-cols-2 xl:grid-cols-6">
        <Info label="Read" value={humanFlag(summary.read)} helper={summary.next_action} />
        <Info label="Dominant state" value={humanFlag(summary.dominant_state || "-")} helper={`${summary.dominant_state_count || 0} signal`} />
        <Info label="Confirmed" value={`${summary.confirmed_count || 0}`} helper="Close 1h >= +0.25R" />
        <Info label="Stalled" value={`${summary.stalled_count || 0}`} helper="-0.10R sampai +0.25R" />
        <Info label="Reversed" value={`${summary.price_reversed_count || 0}`} helper="Close 1h < -0.10R" />
        <Info label="Structure fail proxy" value={`${summary.structure_failed_count || 0}`} helper="Structured setup <= -0.50R" />
      </div>

      <div className="border-b border-line p-4">
        <div className="rounded-md border border-amber-300 bg-amber-50 p-4 text-sm leading-6 text-amber-950">
          Model ini diagnostic-only. State 60m boleh dipakai untuk memahami path setelah entry, tapi belum boleh menjadi gate live tanpa simulasi delayed-entry atau early-exit terpisah.
        </div>
      </div>

      <div className="grid gap-4 border-b border-line p-4 2xl:grid-cols-[1fr_0.75fr]">
        <div className="rounded-md border border-line bg-white">
          <div className="border-b border-line px-4 py-3">
            <div className="font-bold">State performance</div>
            <div className="mt-1 text-xs leading-5 text-slate-500">TP/SL dan R realistis per reaksi 1 jam pertama.</div>
          </div>
          <FirstHourStateTable rows={audit.state_rows} />
        </div>
        <div className="rounded-md border border-line bg-white">
          <div className="border-b border-line px-4 py-3">
            <div className="font-bold">Checkpoint availability</div>
            <div className="mt-1 text-xs leading-5 text-slate-500">Kalau 15m/30m kosong, itu berarti field belum dilog, bukan dianggap netral.</div>
          </div>
          <FirstHourCheckpointTable rows={audit.checkpoint_rows} />
        </div>
      </div>

      <div className="border-b border-line">
        <div className="px-4 py-3">
          <div className="font-bold">Family x first-hour state</div>
          <div className="mt-1 text-xs leading-5 text-slate-500">Membedakan apakah breakout/retest/pullback punya respons awal yang berbeda.</div>
        </div>
        <FirstHourFamilyStateTable rows={audit.family_state_rows} />
      </div>

      <div className="border-b border-line">
        <div className="px-4 py-3">
          <div className="font-bold">Recent examples by state</div>
          <div className="mt-1 text-xs leading-5 text-slate-500">Contoh terbaru agar bisa dibuka silang dengan chart signal detail.</div>
        </div>
        <FirstHourSampleTable rows={audit.sample_rows} />
      </div>

      <div className="grid gap-2 border-t border-line p-4 text-sm text-slate-700 md:grid-cols-2">
        {audit.guardrails.map((guardrail) => (
          <div key={guardrail} className="rounded-md border border-line bg-field/40 p-3">- {guardrail}</div>
        ))}
      </div>
    </div>
  );
}

function FirstHourActionSimulationPanel({ simulation }: { simulation: MidLongFirstHourActionSimulation }) {
  const summary = simulation.summary;
  const bestDelayed = summary.best_delayed_entry;
  const bestExit = summary.best_early_exit;
  return (
    <div>
      <div className="grid gap-3 border-b border-line p-4 md:grid-cols-2 xl:grid-cols-5">
        <Info label="Read" value={humanFlag(summary.read)} helper={summary.next_action} />
        <Info label="Baseline R" value={`${fmtSigned(summary.baseline_realistic_total_r_closed)}R`} helper="MID_LONG 1h V2 current control" />
        <Info
          label="Best delayed"
          value={bestDelayed?.label || "-"}
          helper={`Delta ${fmtSigned(bestDelayed?.delta_r)}R | kept ${bestDelayed?.retained_count || 0}`}
        />
        <Info
          label="Best early exit"
          value={bestExit?.label || "-"}
          helper={`Delta ${fmtSigned(bestExit?.delta_r)}R | action ${bestExit?.action_count || 0}`}
        />
        <Info label="Model" value={simulation.model} helper="Proxy only, not exact replay" />
      </div>

      <div className="border-b border-line p-4">
        <div className="rounded-md border border-amber-300 bg-amber-50 p-4 text-sm leading-6 text-amber-950">
          Simulasi ini belum mereprice delayed entry dan belum mengeksekusi intrabar. Gunanya memilih cabang riset berikutnya: exact delayed-entry replay atau exact early-exit replay.
        </div>
      </div>

      <div className="border-b border-line">
        <div className="px-4 py-3">
          <div className="font-bold">Delayed-entry proxy</div>
          <div className="mt-1 text-xs leading-5 text-slate-500">Retained cohort kalau sinyal baru dianggap setelah respons 1h tertentu. Entry/SL/TP belum dihitung ulang.</div>
        </div>
        <FirstHourDelayedEntryTable rows={simulation.delayed_entry_rows} />
      </div>

      <div className="border-b border-line">
        <div className="px-4 py-3">
          <div className="font-bold">Early-exit proxy</div>
          <div className="mt-1 text-xs leading-5 text-slate-500">Untuk baris yang terkena kondisi, final R diganti dengan close-followthrough 1h. Ini menjawab apakah exit cepat berpotensi mengurangi damage.</div>
        </div>
        <FirstHourEarlyExitTable rows={simulation.early_exit_rows} />
      </div>

      <div className="grid gap-2 border-t border-line p-4 text-sm text-slate-700 md:grid-cols-2">
        {simulation.guardrails.map((guardrail) => (
          <div key={guardrail} className="rounded-md border border-line bg-field/40 p-3">- {guardrail}</div>
        ))}
      </div>
    </div>
  );
}

function FirstHourDelayedEntryTable({ rows }: { rows: MidLongFirstHourDelayedEntryRow[] }) {
  if (!rows.length) return <div className="p-4"><EmptyState title="Delayed-entry simulation kosong" detail="Snapshot belum memuat simulation rows." /></div>;
  return (
    <div className="table-wrap">
      <table className="ops-table">
        <thead>
          <tr>
            <th>Variant</th>
            <th>Kept / skipped</th>
            <th>TP / SL kept</th>
            <th>Kept R / delta</th>
            <th>Skipped damage</th>
            <th>State mix</th>
            <th>Read</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.filter_id}>
              <td className="min-w-96">
                <div className="font-bold">{row.label}</div>
                <div className="mt-1 text-xs leading-5 text-slate-500">{row.expression}</div>
              </td>
              <td>
                <div className="font-bold">{row.retained_count} / {row.skipped_count}</div>
                <div className="text-xs text-slate-500">source {row.source_count} | unavailable excl {row.excluded_unavailable_count || 0}</div>
              </td>
              <td>{row.tp_count} / {row.sl_count}</td>
              <td className={toneClass(row.realistic_total_r_closed)}>
                <div>{fmtSigned(row.realistic_total_r_closed)}R</div>
                <div className="text-xs text-slate-500">delta {fmtSigned(row.realistic_total_r_delta_vs_baseline)}R | avg {fmtSigned(row.realistic_avg_r_closed)}R</div>
              </td>
              <td className={toneClass(row.skipped_realistic_total_r_closed)}>
                <div>{fmtSigned(row.skipped_realistic_total_r_closed)}R</div>
                <div className="text-xs text-slate-500">TP/SL {row.skipped_tp_count || 0}/{row.skipped_sl_count || 0}</div>
              </td>
              <td className="max-w-96 text-xs leading-5 text-slate-600">
                <div>Kept: {pathMixSummary(row.retained_state_mix)}</div>
                <div className="mt-1">Skipped: {pathMixSummary(row.skipped_state_mix)}</div>
              </td>
              <td><StatusBadge value={humanFlag(row.read)} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function FirstHourEarlyExitTable({ rows }: { rows: MidLongFirstHourEarlyExitRow[] }) {
  if (!rows.length) return <div className="p-4"><EmptyState title="Early-exit simulation kosong" detail="Snapshot belum memuat early-exit rows." /></div>;
  return (
    <div className="table-wrap">
      <table className="ops-table">
        <thead>
          <tr>
            <th>Variant</th>
            <th>Action</th>
            <th>Original TP/SL cut</th>
            <th>Proxy R / delta</th>
            <th>Saved / sacrificed</th>
            <th>Drawdown</th>
            <th>State mix</th>
            <th>Read</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.filter_id}>
              <td className="min-w-96">
                <div className="font-bold">{row.label}</div>
                <div className="mt-1 text-xs leading-5 text-slate-500">{row.expression}</div>
              </td>
              <td>
                <div className="font-bold">{row.action_count} / {row.sample_count}</div>
                <div className="text-xs text-slate-500">missing 1h {row.missing_followthrough_count}</div>
              </td>
              <td>
                <div>TP cut {row.tp_cut_count}</div>
                <div className="text-xs text-slate-500">SL reduced {row.sl_reduced_count} | original action TP/SL {row.original_action_tp_count}/{row.original_action_sl_count}</div>
              </td>
              <td className={toneClass(row.proxy_realistic_total_r_closed)}>
                <div>{fmtSigned(row.proxy_realistic_total_r_closed)}R</div>
                <div className="text-xs text-slate-500">delta {fmtSigned(row.proxy_realistic_total_r_delta_vs_baseline)}R | avg {fmtSigned(row.proxy_realistic_avg_r_closed)}R</div>
              </td>
              <td className={toneClass(row.net_saved_r)}>
                <div>net {fmtSigned(row.net_saved_r)}R</div>
                <div className="text-xs text-slate-500">saved {fmtSigned(row.r_saved)}R / cut {fmtSigned(row.r_sacrificed)}R</div>
              </td>
              <td>
                <div>{fmtSigned(row.proxy_max_drawdown_r)}R</div>
                <div className="text-xs text-slate-500">delta {fmtSigned(row.proxy_max_drawdown_delta_vs_baseline)}R</div>
              </td>
              <td className="max-w-80 text-xs leading-5 text-slate-600">{pathMixSummary(row.action_state_mix)}</td>
              <td><StatusBadge value={humanFlag(row.read)} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function FirstHourStateTable({ rows }: { rows: MidLongFirstHourStateRow[] }) {
  if (!rows.length) return <div className="p-4"><EmptyState title="First-hour state kosong" detail="Snapshot belum memuat first-hour audit." /></div>;
  return (
    <div className="table-wrap">
      <table className="ops-table">
        <thead>
          <tr>
            <th>State</th>
            <th>N</th>
            <th>TP / SL</th>
            <th>Realistic R</th>
            <th>1h close / MFE / MAE</th>
            <th>Family / flow</th>
            <th>Path mix</th>
            <th>Read</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.state}>
              <td className="min-w-80">
                <div className="font-bold">{humanFlag(row.state)}</div>
                <div className="mt-1 text-xs leading-5 text-slate-500">{row.definition}</div>
              </td>
              <td>
                <div className="font-bold">{row.closed_count}</div>
                <div className="text-xs text-slate-500">60m {row.available_60m_count || 0} ({formatPct(row.available_60m_pct)})</div>
              </td>
              <td>{row.tp_count} / {row.sl_count}</td>
              <td className={toneClass(row.realistic_total_r_closed)}>
                <div>{fmtSigned(row.realistic_total_r_closed)}R</div>
                <div className="text-xs text-slate-500">{fmtSigned(row.realistic_avg_r_closed)}R avg</div>
              </td>
              <td>
                <div>1h {fmtSigned(row.median_close_followthrough_1h_r)}R</div>
                <div className="text-xs text-slate-500">MFE {fmtSigned(row.median_mfe_r)}R / MAE {fmtSigned(row.median_mae_r)}R</div>
              </td>
              <td className="max-w-96 text-xs leading-5 text-slate-600">
                <div>{pathMixSummary(row.primary_family_mix)}</div>
                <div className="mt-1">{pathMixSummary(row.flow_mix)}</div>
              </td>
              <td className="max-w-80 text-xs leading-5 text-slate-600">{pathMixSummary(row.path_mix)}</td>
              <td><StatusBadge value={humanFlag(row.read)} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function FirstHourCheckpointTable({ rows }: { rows: MidLongFirstHourCheckpointRow[] }) {
  if (!rows.length) return <div className="p-4"><EmptyState title="Checkpoint kosong" detail="Belum ada checkpoint audit." /></div>;
  return (
    <div className="table-wrap">
      <table className="ops-table">
        <thead>
          <tr>
            <th>Checkpoint</th>
            <th>Available</th>
            <th>Median / Q1-Q3</th>
            <th>Fields</th>
            <th>Read</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.checkpoint}>
              <td>
                <div className="font-bold">{row.checkpoint}</div>
                <div className="text-xs text-slate-500">{row.label}</div>
              </td>
              <td>{row.available_count} / miss {row.missing_count} ({formatPct(row.available_pct)})</td>
              <td>
                <div>{fmtSigned(row.median_close_r)}R</div>
                <div className="text-xs text-slate-500">{fmtSigned(row.q25_close_r)}R / {fmtSigned(row.q75_close_r)}R</div>
              </td>
              <td className="max-w-80 text-xs leading-5 text-slate-600">{row.candidate_fields.join(", ")}</td>
              <td><StatusBadge value={humanFlag(row.read)} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function FirstHourFamilyStateTable({ rows }: { rows: MidLongFirstHourFamilyStateRow[] }) {
  if (!rows.length) return <div className="p-4"><EmptyState title="Family x state kosong" detail="Belum ada kombinasi family dan first-hour state." /></div>;
  return (
    <div className="table-wrap">
      <table className="ops-table">
        <thead>
          <tr>
            <th>Family x state</th>
            <th>Readable</th>
            <th>N</th>
            <th>TP / SL</th>
            <th>Realistic R</th>
            <th>1h / MFE / MAE</th>
            <th>Path / flow</th>
            <th>Read</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.filter_id}>
              <td className="min-w-96">
                <div className="font-bold">{humanFlag(row.primary_family)}</div>
                <div className="text-xs text-slate-500">{humanFlag(row.state)}</div>
              </td>
              <td><StatusBadge value={row.is_readable ? "Readable" : "Small sample"} /></td>
              <td>{row.closed_count}</td>
              <td>{row.tp_count} / {row.sl_count}</td>
              <td className={toneClass(row.realistic_total_r_closed)}>{fmtSigned(row.realistic_total_r_closed)}R</td>
              <td>
                <div>{fmtSigned(row.median_close_followthrough_1h_r)}R</div>
                <div className="text-xs text-slate-500">{fmtSigned(row.median_mfe_r)}R / {fmtSigned(row.median_mae_r)}R</div>
              </td>
              <td className="max-w-96 text-xs leading-5 text-slate-600">
                <div>{pathMixSummary(row.path_mix)}</div>
                <div className="mt-1">{pathMixSummary(row.flow_mix)}</div>
              </td>
              <td><StatusBadge value={humanFlag(row.read)} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function FirstHourSampleTable({ rows }: { rows: MidLongFirstHourSampleRow[] }) {
  if (!rows.length) return <div className="p-4"><EmptyState title="Sample kosong" detail="Belum ada contoh first-hour response." /></div>;
  return (
    <div className="table-wrap">
      <table className="ops-table">
        <thead>
          <tr>
            <th>Time</th>
            <th>Symbol</th>
            <th>State</th>
            <th>Result</th>
            <th>Family / path</th>
            <th>1h / MFE / MAE</th>
            <th>Entry / SL / TP</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, idx) => (
            <tr key={`${row.state}-${row.signal_id || idx}`}>
              <td className="min-w-44">{fmtTime(row.signal_timestamp)}</td>
              <td className="font-bold">{row.symbol || "-"}</td>
              <td><StatusBadge value={humanFlag(row.state)} /></td>
              <td>
                <div><StatusBadge value={humanFlag(row.result_status || "-")} /></div>
                <div className={`mt-1 text-xs ${toneClass(row.realistic_realized_r)}`}>{fmtSigned(row.realistic_realized_r)}R</div>
              </td>
              <td className="max-w-72 text-xs leading-5 text-slate-600">
                <div>{humanFlag(row.primary_family || "-")}</div>
                <div>{humanFlag(row.path_bucket || row.path_label_050 || "-")}</div>
                <div>{humanFlag(row.flow_state || "-")}</div>
              </td>
              <td>
                <div>1h {fmtSigned(row.close_followthrough_1h_r)}R</div>
                <div className="text-xs text-slate-500">MFE {fmtSigned(row.mfe_r)}R / MAE {fmtSigned(row.mae_r)}R</div>
              </td>
              <td className="text-xs leading-5">
                <div>Entry {fmtPrice(row.price_at_signal)}</div>
                <div>SL {fmtPrice(row.sl_ref)}</div>
                <div>TP {fmtPrice(row.tp_ref)}</div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ResetSummaryCard({ title, row }: { title: string; row?: Record<string, string | number | null | undefined> | null }) {
  if (!row) {
    return <div className="rounded-md border border-line bg-white p-4"><Info label={title} value="-" helper="Belum tersedia" /></div>;
  }
  const label = row.primary_family || row.decision || "-";
  return (
    <div className="rounded-md border border-line bg-white p-4">
      <div className="text-xs font-semibold uppercase text-slate-500">{title}</div>
      <div className="mt-1 text-xl font-black text-ink">{humanFlag(String(label))}</div>
      <div className="mt-2 grid gap-2 text-sm sm:grid-cols-4">
        <div>N <b>{row.closed_count || 0}</b></div>
        <div>TP/SL <b>{row.tp_count || 0}/{row.sl_count || 0}</b></div>
        <div className={toneClass(row.realistic_total_r_closed)}>R <b>{fmtSigned(row.realistic_total_r_closed)}R</b></div>
        <div>Top <b>{row.top_symbol || "-"}</b></div>
      </div>
    </div>
  );
}

function ResetPrimaryTable({ rows }: { rows: MidLongResetPrimaryRow[] }) {
  if (!rows.length) return <div className="p-4"><EmptyState title="Primary family kosong" detail="Definition Reset belum tersedia." /></div>;
  return (
    <div className="table-wrap">
      <table className="ops-table">
        <thead>
          <tr>
            <th>Primary family</th>
            <th>Role</th>
            <th>N</th>
            <th>TP / SL</th>
            <th>Realistic R</th>
            <th>Avg delta</th>
            <th>Modifiers</th>
            <th>Decisions</th>
            <th>Read</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.filter_id}>
              <td className="min-w-96">
                <div className="font-bold">{humanFlag(row.primary_family)}</div>
                <div className="mt-1 text-xs leading-5 text-slate-500">{row.definition}</div>
              </td>
              <td><StatusBadge value={humanFlag(row.family_role)} /></td>
              <td className="font-bold">{row.closed_count}</td>
              <td>{row.tp_count} / {row.sl_count}</td>
              <td className={toneClass(row.realistic_total_r_closed)}>{fmtSigned(row.realistic_total_r_closed)}R</td>
              <td className={toneClass(row.realistic_avg_r_delta_vs_baseline)}>{fmtSigned(row.realistic_avg_r_delta_vs_baseline)}R</td>
              <td className="max-w-80 text-xs leading-5 text-slate-600">{pathMixSummary(row.modifier_mix)}</td>
              <td className="max-w-80 text-xs leading-5 text-slate-600">{pathMixSummary(row.decision_mix)}</td>
              <td className="max-w-96 text-sm leading-5 text-slate-700">{row.read}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ResetCohortTable({ rows }: { rows: MidLongResetCohortRow[] }) {
  if (!rows.length) return <div className="p-4"><EmptyState title="Cohort comparison kosong" detail="Snapshot belum memuat Definition Reset v2." /></div>;
  return (
    <div className="table-wrap">
      <table className="ops-table">
        <thead>
          <tr>
            <th>Cohort</th>
            <th>Version</th>
            <th>N</th>
            <th>TP / SL</th>
            <th>Realistic R</th>
            <th>Avg delta</th>
            <th>Family mix</th>
            <th>Decision mix</th>
            <th>Read</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.cohort_id}>
              <td className="min-w-80">
                <div className="font-bold">{humanFlag(row.cohort_id)}</div>
                <div className="mt-1 text-xs leading-5 text-slate-500">{row.description}</div>
              </td>
              <td><StatusBadge value={humanFlag(row.definition_version)} /></td>
              <td className="font-bold">{row.closed_count}</td>
              <td>{row.tp_count} / {row.sl_count}</td>
              <td className={toneClass(row.realistic_total_r_closed)}>{fmtSigned(row.realistic_total_r_closed)}R</td>
              <td className={toneClass(row.realistic_avg_r_delta_vs_baseline)}>{fmtSigned(row.realistic_avg_r_delta_vs_baseline)}R</td>
              <td className="max-w-80 text-xs leading-5 text-slate-600">{pathMixSummary(row.primary_family_mix)}</td>
              <td className="max-w-80 text-xs leading-5 text-slate-600">{pathMixSummary(row.decision_mix)}</td>
              <td className="max-w-96 text-sm leading-5 text-slate-700">{row.read}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ResetDecisionTable({ rows }: { rows: MidLongResetDecisionRow[] }) {
  return (
    <div className="table-wrap">
      <table className="ops-table">
        <thead>
          <tr>
            <th>Decision</th>
            <th>N</th>
            <th>TP / SL</th>
            <th>Realistic R</th>
            <th>Family mix</th>
            <th>Read</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.filter_id}>
              <td className="min-w-72 font-bold">{humanFlag(row.decision)}</td>
              <td>{row.closed_count}</td>
              <td>{row.tp_count} / {row.sl_count}</td>
              <td className={toneClass(row.realistic_total_r_closed)}>{fmtSigned(row.realistic_total_r_closed)}R</td>
              <td className="max-w-72 text-xs leading-5 text-slate-600">{pathMixSummary(row.primary_family_mix)}</td>
              <td className="max-w-96 text-sm leading-5 text-slate-700">{row.read}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ResetModifierTable({ rows }: { rows: MidLongResetModifierRow[] }) {
  return (
    <div className="table-wrap">
      <table className="ops-table">
        <thead>
          <tr>
            <th>Modifier</th>
            <th>N</th>
            <th>TP / SL</th>
            <th>Realistic R</th>
            <th>Family mix</th>
            <th>Read</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.filter_id}>
              <td className="min-w-72">
                <div className="font-bold">{humanFlag(row.modifier)}</div>
                <div className="mt-1 text-xs leading-5 text-slate-500">{row.definition}</div>
              </td>
              <td>{row.closed_count}</td>
              <td>{row.tp_count} / {row.sl_count}</td>
              <td className={toneClass(row.realistic_total_r_closed)}>{fmtSigned(row.realistic_total_r_closed)}R</td>
              <td className="max-w-72 text-xs leading-5 text-slate-600">{pathMixSummary(row.primary_family_mix)}</td>
              <td className="max-w-96 text-sm leading-5 text-slate-700">{row.read}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ResetFamilyModifierTable({ rows }: { rows: MidLongResetFamilyModifierRow[] }) {
  if (!rows.length) return <div className="p-4"><EmptyState title="Family x modifier kosong" detail="Belum ada overlap modifier." /></div>;
  return (
    <div className="table-wrap">
      <table className="ops-table">
        <thead>
          <tr>
            <th>Family x modifier</th>
            <th>Readable</th>
            <th>N</th>
            <th>TP / SL</th>
            <th>Realistic R</th>
            <th>Avg R</th>
            <th>Path mix</th>
            <th>Top symbol</th>
          </tr>
        </thead>
        <tbody>
          {rows.slice(0, 24).map((row) => (
            <tr key={row.filter_id}>
              <td className="min-w-96">
                <div className="font-bold">{humanFlag(row.primary_family)}</div>
                <div className="text-xs text-slate-500">{humanFlag(row.modifier)}</div>
              </td>
              <td><StatusBadge value={row.is_readable ? "Readable" : "Small sample"} /></td>
              <td>{row.closed_count}</td>
              <td>{row.tp_count} / {row.sl_count}</td>
              <td className={toneClass(row.realistic_total_r_closed)}>{fmtSigned(row.realistic_total_r_closed)}R</td>
              <td>{fmtSigned(row.realistic_avg_r_closed)}R</td>
              <td className="max-w-80 text-xs leading-5 text-slate-600">{pathMixSummary(row.path_mix)}</td>
              <td>{row.top_symbol || "-"} ({formatPct(row.top_symbol_share_pct)})</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function SubSetupSplitPanel({ lab }: { lab: MidLongSubSetupSplitLab }) {
  const summary = lab.summary || { status_counts: {}, read: "WAITING" };
  return (
    <div>
      <div className="grid gap-3 border-b border-line p-4 md:grid-cols-2 xl:grid-cols-5">
        <Info label="Read" value={humanFlag(summary.read)} helper="Apakah ada sub-setup yang masih layak diteliti." />
        <Info label="Sub-setup rows" value={lab.rows.length.toString()} helper="Mutually exclusive buckets." />
        <Info label="Candidate/watch" value={(lab.candidate_rows?.length || 0).toString()} helper="Belum rule; hanya riset." />
        <Info label="Reject/wait" value={(lab.reject_rows?.length || 0).toString()} helper="Bucket yang merusak atau butuh data." />
        <Info label="Status mix" value={Object.keys(summary.status_counts || {}).length.toString()} helper={statusMixSummary(summary.status_counts)} />
      </div>

      <div className="grid gap-3 border-b border-line p-4 lg:grid-cols-2">
        <SubSetupSummaryCard title="Best sub-setup sementara" row={summary.best_sub_setup} />
        <SubSetupSummaryCard title="Worst damage sub-setup" row={summary.worst_sub_setup} />
      </div>

      <SubSetupTable rows={lab.rows} />

      <div className="grid gap-2 border-t border-line p-4 text-sm text-slate-700 md:grid-cols-3">
        {lab.guardrails.map((guardrail) => (
          <div key={guardrail} className="rounded-md border border-line bg-field/40 p-3">- {guardrail}</div>
        ))}
      </div>
    </div>
  );
}

function SubSetupSummaryCard({ title, row }: { title: string; row?: MidLongSubSetupSplitLab["summary"]["best_sub_setup"] }) {
  if (!row) {
    return <div className="rounded-md border border-line bg-white p-4"><Info label={title} value="-" helper="Belum tersedia" /></div>;
  }
  return (
    <div className="rounded-md border border-line bg-white p-4">
      <div className="text-xs font-semibold uppercase text-slate-500">{title}</div>
      <div className="mt-1 text-xl font-black text-ink">{humanFlag(row.sub_setup || "-")}</div>
      <div className="mt-2 flex flex-wrap gap-2">
        <StatusBadge value={humanFlag(row.research_status || "-")} />
        <StatusBadge value={`${row.closed_count || 0} rows`} />
      </div>
      <div className="mt-3 grid gap-2 text-sm sm:grid-cols-3">
        <div>TP/SL <b>{row.tp_count || 0}/{row.sl_count || 0}</b></div>
        <div className={toneClass(row.realistic_total_r_closed)}>R <b>{fmtSigned(row.realistic_total_r_closed)}R</b></div>
        <div className={toneClass(row.realistic_avg_r_delta_vs_baseline)}>Delta <b>{fmtSigned(row.realistic_avg_r_delta_vs_baseline)}R</b></div>
      </div>
    </div>
  );
}

function SubSetupTable({ rows }: { rows: MidLongSubSetupRow[] }) {
  if (!rows.length) return <div className="p-4"><EmptyState title="Sub-setup kosong" detail="Belum ada split MID_LONG." /></div>;
  return (
    <div className="table-wrap">
      <table className="ops-table">
        <thead>
          <tr>
            <th>Sub-setup</th>
            <th>Status</th>
            <th>N</th>
            <th>TP / SL</th>
            <th>Realistic R</th>
            <th>Avg delta</th>
            <th>Path / flow</th>
            <th>Cost / stop</th>
            <th>Acceptance</th>
            <th>Action</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.filter_id}>
              <td className="min-w-96">
                <div className="font-bold">{humanFlag(row.sub_setup)}</div>
                <div className="mt-1 text-xs leading-5 text-slate-500">{row.definition}</div>
                <div className="mt-1 text-xs text-slate-500">{humanFlag(row.sub_setup_family)}</div>
              </td>
              <td><StatusBadge value={humanFlag(row.research_status)} /></td>
              <td className="font-bold">{row.closed_count}</td>
              <td>{row.tp_count} / {row.sl_count}</td>
              <td className={toneClass(row.realistic_total_r_closed)}>{fmtSigned(row.realistic_total_r_closed)}R</td>
              <td className={toneClass(row.realistic_avg_r_delta_vs_baseline)}>{fmtSigned(row.realistic_avg_r_delta_vs_baseline)}R</td>
              <td className="max-w-96 text-xs leading-5 text-slate-600">
                <div><b>Path:</b> {humanFlag(row.dominant_path || "-")}</div>
                <div><b>Flow:</b> {humanFlag(row.dominant_flow || "-")}</div>
                <div>{pathMixSummary(row.path_mix)}</div>
              </td>
              <td>
                <div>{fmtNumber(row.median_cost_r)}R cost</div>
                <div className="text-xs text-slate-500">{fmtNumber(row.median_stop_pct)}% stop</div>
              </td>
              <td>
                <div>{row.close_050_count || 0}/{row.touch_050_count || 0}</div>
                <div className="text-xs text-slate-500">{formatPct(row.close_acceptance_conversion_pct)}</div>
              </td>
              <td className="max-w-96 text-sm leading-5 text-slate-700">{row.recommended_action}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function BreakoutDeepDivePanel({ lab }: { lab: MidLongBreakoutAcceptedDeepDive }) {
  const summary = lab.summary;
  return (
    <div>
      <div className="grid gap-3 border-b border-line p-4 md:grid-cols-2 xl:grid-cols-6">
        <Info label="Read" value={humanFlag(summary.read)} helper="Apakah proxy breakout sudah punya angka zona untuk dibedah." />
        <Info label="Zone purity" value={humanFlag(summary.label_purity_read)} helper={`${summary.precise_zone_fields_missing_count} field kosong, ${summary.label_purity_failed_count || 0} purity fail.`} />
        <Info label="Control sample" value={String(lab.control.closed_count || 0)} helper={`${lab.control.tp_count || 0} TP / ${lab.control.sl_count || 0} SL`} />
        <Info label="Control R" value={`${fmtSigned(lab.control.realistic_total_r_closed)}R`} helper={`${fmtSigned(lab.control.realistic_avg_r_closed)}R avg`} />
        <BreakoutSummaryCard title="Best filter" row={summary.best_filter} />
        <BreakoutSummaryCard title="Best shadow arm" row={summary.best_shadow_arm} />
      </div>

      <div className="grid gap-4 border-b border-line p-4 2xl:grid-cols-[0.8fr_1.2fr]">
        <div className="rounded-md border border-line bg-white">
          <div className="border-b border-line px-4 py-3">
            <div className="font-bold">Label purity / leakage audit</div>
            <div className="mt-1 text-xs leading-5 text-slate-500">Membuktikan zona dan close-acceptance tersedia sebelum signal. Jika gagal, breakout tetap proxy.</div>
          </div>
          <BreakoutLabelPurityTable rows={lab.label_purity_rows || []} />
        </div>
        <div className="rounded-md border border-line bg-white">
          <div className="border-b border-line px-4 py-3">
            <div className="font-bold">Observable path, bukan sebab tunggal</div>
            <div className="mt-1 text-xs leading-5 text-slate-500">Path ini terjadi setelah entry. Dipakai untuk membedah, bukan untuk memilih entry sejak awal.</div>
          </div>
          <BreakoutObservablePathTable rows={lab.observable_path_rows || []} />
        </div>
      </div>

      <div className="grid gap-4 border-b border-line p-4 2xl:grid-cols-[0.9fr_1.1fr]">
        <div className="rounded-md border border-line bg-white">
          <div className="border-b border-line px-4 py-3">
            <div className="font-bold">Pre-entry zone fields</div>
            <div className="mt-1 text-xs leading-5 text-slate-500">Field zona dihitung dari candle yang sudah close sebelum entry, bukan candle masa depan.</div>
          </div>
          <BreakoutFieldAvailabilityTable rows={lab.field_availability_rows} />
        </div>
        <div className="rounded-md border border-line bg-white">
          <div className="border-b border-line px-4 py-3">
            <div className="font-bold">Mechanism split</div>
            <div className="mt-1 text-xs leading-5 text-slate-500">Loss/win tidak disamaratakan: false breakout candidate, failed continuation, atau pullback winner.</div>
          </div>
          <BreakoutMechanismTable rows={lab.mechanism_rows} />
        </div>
      </div>

      <div className="border-b border-line">
        <div className="px-4 py-3">
          <div className="font-bold">Pre-entry hypothesized causes</div>
          <div className="mt-1 text-xs leading-5 text-slate-500">Satu signal bisa kena beberapa flag. Ini hipotesis sebelum entry, bukan klaim penyebab final.</div>
        </div>
        <BreakoutCauseTable rows={lab.pre_entry_cause_rows || []} />
      </div>

      <div className="grid gap-4 border-b border-line p-4 2xl:grid-cols-[0.95fr_1.05fr]">
        <div className="rounded-md border border-line bg-white">
          <div className="border-b border-line px-4 py-3">
            <div className="font-bold">Cause overlap matrix</div>
            <div className="mt-1 text-xs leading-5 text-slate-500">Mengecek apakah damage flag saling menumpuk. Jangan baca cause sebagai kontribusi marginal sebelum lihat overlap.</div>
          </div>
          <BreakoutCauseOverlapTable rows={lab.cause_overlap_rows || []} />
        </div>
        <div className="rounded-md border border-line bg-white">
          <div className="border-b border-line px-4 py-3">
            <div className="font-bold">V2.1 shadow arms preview</div>
            <div className="mt-1 text-xs leading-5 text-slate-500">Arm ini draft read-only. FLOW+ROOM dipisah dari tradability dan crowding agar kontribusinya terbaca bersih.</div>
          </div>
          <BreakoutShadowArmTable rows={lab.shadow_arm_rows || []} />
        </div>
      </div>

      <div className="border-b border-line">
        <div className="px-4 py-3">
          <div className="font-bold">Single damage filters</div>
          <div className="mt-1 text-xs leading-5 text-slate-500">Semua masih read-only. Filter post-entry hanya bukti perilaku, bukan calon gate live.</div>
        </div>
        <BreakoutFilterTable rows={lab.single_filter_rows} />
      </div>

      <div className="grid gap-4 border-b border-line p-4 2xl:grid-cols-2">
        <div className="rounded-md border border-line bg-white">
          <div className="border-b border-line px-4 py-3">
            <div className="font-bold">Interaction clusters</div>
            <div className="mt-1 text-xs leading-5 text-slate-500">Cluster risiko yang bisa menjelaskan kenapa breakout proxy tetap gagal.</div>
          </div>
          <BreakoutInteractionTable rows={lab.interaction_rows} />
        </div>
        <div className="rounded-md border border-line bg-white">
          <div className="border-b border-line px-4 py-3">
            <div className="font-bold">Draft cohorts</div>
            <div className="mt-1 text-xs leading-5 text-slate-500">Draft proxy untuk nanti divalidasi waktu. Belum rule V2.1.</div>
          </div>
          <BreakoutDraftTable rows={lab.draft_cohort_rows} />
        </div>
      </div>

      <BreakoutCrossPanels tables={lab.evidence_path_tables} />
      <BreakoutCrossPanels
        title="Pre-entry geometry x observable path"
        description="Cross-table ini menjawab apakah path buruk terkonsentrasi pada acceptance tipis, wick besar, late chase, jarak entry, atau room rendah."
        tables={lab.pre_entry_geometry_path_tables || {}}
      />

      <div className="grid gap-2 border-t border-line p-4 text-sm text-slate-700 md:grid-cols-2">
        {lab.guardrails.map((guardrail) => (
          <div key={guardrail} className="rounded-md border border-line bg-field/40 p-3">- {guardrail}</div>
        ))}
      </div>
    </div>
  );
}

function BreakoutSummaryCard({
  title,
  row
}: {
  title: string;
  row?: MidLongBreakoutAcceptedDeepDive["summary"]["best_filter"];
}) {
  return (
    <div className="rounded-md border border-line bg-field/40 p-3">
      <div className="text-xs font-semibold uppercase text-slate-500">{title}</div>
      {row ? (
        <>
          <div className="mt-1 break-words font-bold text-ink">{humanFlag(row.label || "-")}</div>
          <div className="mt-1 text-xs leading-5 text-slate-600">
            {row.closed_count || 0} rows | {row.tp_count || 0}/{row.sl_count || 0} TP/SL
          </div>
          <div className={`mt-1 text-xs ${toneClass(row.realistic_total_r_closed)}`}>
            {fmtSigned(row.realistic_total_r_closed)}R total | {fmtSigned(row.realistic_avg_r_delta_vs_baseline)}R delta
          </div>
        </>
      ) : (
        <div className="mt-1 text-sm text-slate-500">Belum tersedia</div>
      )}
    </div>
  );
}

function BreakoutLabelPurityTable({ rows }: { rows: MidLongBreakoutLabelPurityRow[] }) {
  if (!rows.length) return <div className="p-4"><EmptyState title="Purity audit kosong" detail="Belum ada purity check untuk breakout proxy." /></div>;
  return (
    <div className="table-wrap">
      <table className="ops-table">
        <thead>
          <tr>
            <th>Check</th>
            <th>Pass / fail</th>
            <th>Status</th>
            <th>Read</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.check_id}>
              <td className="min-w-80">
                <div className="font-bold">{row.label}</div>
                <div className="mt-1 text-xs leading-5 text-slate-500">{row.expression}</div>
              </td>
              <td>
                <div>{row.pass_count} / {row.fail_count}</div>
                <div className="text-xs text-slate-500">{formatPct(row.pass_pct)} pass</div>
              </td>
              <td><StatusBadge value={humanFlag(row.status)} /></td>
              <td className="max-w-96 text-sm leading-5 text-slate-700">{row.read}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function BreakoutFieldAvailabilityTable({ rows }: { rows: MidLongBreakoutFieldAvailabilityRow[] }) {
  if (!rows.length) return <div className="p-4"><EmptyState title="Field audit kosong" detail="Belum ada field untuk diaudit." /></div>;
  return (
    <div className="table-wrap max-h-[34rem] overflow-y-auto">
      <table className="ops-table">
        <thead>
          <tr>
            <th>Field</th>
            <th>Source</th>
            <th>Available</th>
            <th>Read</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.field}>
              <td>
                <div className="font-bold">{row.label}</div>
                <div className="text-xs text-slate-500">{row.field}</div>
              </td>
              <td>{humanFlag(row.source)}</td>
              <td>{row.available_count} / miss {row.missing_count} ({formatPct(row.available_pct)})</td>
              <td><StatusBadge value={humanFlag(row.read)} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function BreakoutObservablePathTable({ rows }: { rows: MidLongBreakoutObservablePathRow[] }) {
  if (!rows.length) return <div className="p-4"><EmptyState title="Path kosong" detail="Belum ada observable path untuk breakout proxy." /></div>;
  return (
    <div className="table-wrap">
      <table className="ops-table">
        <thead>
          <tr>
            <th>Observable path</th>
            <th>N</th>
            <th>TP / SL</th>
            <th>Realistic R</th>
            <th>MFE / MAE</th>
            <th>Wick decay</th>
            <th>Read</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.filter_id}>
              <td className="min-w-72"><StatusBadge value={humanFlag(row.observable_path)} /></td>
              <td className="font-bold">{row.closed_count}</td>
              <td>{row.tp_count} / {row.sl_count}</td>
              <td className={toneClass(row.realistic_total_r_closed)}>{fmtSigned(row.realistic_total_r_closed)}R</td>
              <td>{fmtSigned(row.median_mfe_r)}R / {fmtSigned(row.median_mae_r)}R</td>
              <td>{fmtSigned(row.median_wick_decay_r)}R</td>
              <td className="max-w-96 text-sm leading-5 text-slate-700">{row.path_read}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function BreakoutMechanismTable({ rows }: { rows: MidLongBreakoutMechanismRow[] }) {
  if (!rows.length) return <div className="p-4"><EmptyState title="Mechanism kosong" detail="Belum ada breakout proxy sample." /></div>;
  return (
    <div className="table-wrap">
      <table className="ops-table">
        <thead>
          <tr>
            <th>Mechanism</th>
            <th>N</th>
            <th>TP / SL</th>
            <th>Realistic R</th>
            <th>Avg / median</th>
            <th>MFE / MAE</th>
            <th>Path mix</th>
            <th>Read</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.filter_id}>
              <td className="min-w-72"><StatusBadge value={humanFlag(row.mechanism)} /></td>
              <td className="font-bold">{row.closed_count}</td>
              <td>{row.tp_count} / {row.sl_count}</td>
              <td className={toneClass(row.realistic_total_r_closed)}>{fmtSigned(row.realistic_total_r_closed)}R</td>
              <td>{fmtSigned(row.realistic_avg_r_closed)}R / {fmtSigned(row.median_realistic_r_closed)}R</td>
              <td>{fmtSigned(row.median_mfe_r)}R / {fmtSigned(row.median_mae_r)}R</td>
              <td className="max-w-80 text-xs leading-5 text-slate-600">{pathMixSummary(row.path_mix)}</td>
              <td className="max-w-96 text-sm leading-5 text-slate-700">{row.mechanism_read}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function BreakoutCauseTable({ rows }: { rows: MidLongBreakoutCauseRow[] }) {
  if (!rows.length) return <div className="p-4"><EmptyState title="Cause audit kosong" detail="Belum ada pre-entry cause flag." /></div>;
  return (
    <div className="table-wrap">
      <table className="ops-table">
        <thead>
          <tr>
            <th>Cause flag</th>
            <th>N</th>
            <th>TP / SL</th>
            <th>Realistic R</th>
            <th>Avg delta</th>
            <th>Observable path mix</th>
            <th>Read</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.cause_id}>
              <td className="min-w-80">
                <div className="font-bold">{humanFlag(row.cause_label)}</div>
                <div className="mt-1 text-xs leading-5 text-slate-500">{row.expression}</div>
              </td>
              <td className="font-bold">{row.closed_count}</td>
              <td>{row.tp_count} / {row.sl_count}</td>
              <td className={toneClass(row.realistic_total_r_closed)}>{fmtSigned(row.realistic_total_r_closed)}R</td>
              <td className={toneClass(row.realistic_avg_r_delta_vs_baseline)}>{fmtSigned(row.realistic_avg_r_delta_vs_baseline)}R</td>
              <td className="max-w-80 text-xs leading-5 text-slate-600">{pathMixSummary(row.observable_path_mix)}</td>
              <td className="max-w-96 text-sm leading-5 text-slate-700">{row.cause_read}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function BreakoutCauseOverlapTable({ rows }: { rows: MidLongBreakoutCauseOverlapRow[] }) {
  if (!rows.length) return <div className="p-4"><EmptyState title="Overlap kosong" detail="Belum ada overlap antar-cause." /></div>;
  return (
    <div className="table-wrap max-h-[34rem] overflow-y-auto">
      <table className="ops-table">
        <thead>
          <tr>
            <th>Overlap</th>
            <th>N</th>
            <th>TP / SL</th>
            <th>Realistic R</th>
            <th>Share</th>
            <th>Path mix</th>
            <th>Read</th>
          </tr>
        </thead>
        <tbody>
          {rows.slice(0, 18).map((row) => (
            <tr key={row.filter_id}>
              <td className="min-w-72">
                <div className="font-bold">{humanFlag(row.left_cause)}</div>
                <div className="text-xs text-slate-500">x {humanFlag(row.right_cause)}</div>
              </td>
              <td className="font-bold">{row.overlap_count}</td>
              <td>{row.tp_count} / {row.sl_count}</td>
              <td className={toneClass(row.realistic_total_r_closed)}>{fmtSigned(row.realistic_total_r_closed)}R</td>
              <td>
                <div>{formatPct(row.overlap_pct_of_left)} of left</div>
                <div className="text-xs text-slate-500">{formatPct(row.overlap_pct_of_right)} of right</div>
              </td>
              <td className="max-w-72 text-xs leading-5 text-slate-600">{pathMixSummary(row.observable_path_mix)}</td>
              <td className="max-w-80 text-sm leading-5 text-slate-700">{row.read}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function BreakoutShadowArmTable({ rows }: { rows: MidLongBreakoutShadowArmRow[] }) {
  if (!rows.length) return <div className="p-4"><EmptyState title="Shadow arm kosong" detail="Belum ada arm V2.1 preview." /></div>;
  return (
    <div className="table-wrap max-h-[34rem] overflow-y-auto">
      <table className="ops-table">
        <thead>
          <tr>
            <th>Arm</th>
            <th>Retained / rejected / wait</th>
            <th>TP / SL</th>
            <th>Realistic R</th>
            <th>TP kept / SL rejected</th>
            <th>Rejected R</th>
            <th>Rejected path</th>
            <th>Read</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.arm_id}>
              <td className="min-w-80">
                <div className="font-bold">{humanFlag(row.arm_id)}</div>
                <div className="mt-1 text-xs leading-5 text-slate-500">{row.expression}</div>
                <div className="mt-1"><StatusBadge value={humanFlag(row.arm_status)} /></div>
              </td>
              <td>{row.retained_count} / {row.rejected_count} / {row.waiting_count}</td>
              <td>{row.tp_count} / {row.sl_count}</td>
              <td className={toneClass(row.realistic_total_r_closed)}>{fmtSigned(row.realistic_total_r_closed)}R</td>
              <td>
                <div>{formatPct(row.tp_retention_pct)} TP kept</div>
                <div className="text-xs text-slate-500">{formatPct(row.sl_rejection_pct)} SL rejected</div>
              </td>
              <td>
                <div className={toneClass(row.rejected_realistic_total_r_closed)}>{fmtSigned(row.rejected_realistic_total_r_closed)}R</div>
                {row.waiting_count > 0 && <div className="text-xs text-slate-500">wait {fmtSigned(row.waiting_realistic_total_r_closed)}R</div>}
              </td>
              <td className="max-w-72 text-xs leading-5 text-slate-600">{pathMixSummary(row.rejected_observable_path_mix)}</td>
              <td className="max-w-96 text-sm leading-5 text-slate-700">{row.arm_read}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function BreakoutFilterTable({ rows }: { rows: MidLongBreakoutFilterRow[] }) {
  if (!rows.length) return <div className="p-4"><EmptyState title="Filter kosong" detail="Belum ada single-filter breakout row." /></div>;
  return (
    <div className="table-wrap">
      <table className="ops-table">
        <thead>
          <tr>
            <th>Filter</th>
            <th>Class</th>
            <th>Retained / removed</th>
            <th>TP / SL</th>
            <th>Retained R</th>
            <th>Avg delta</th>
            <th>Removed R</th>
            <th>Removed mechanism</th>
            <th>Read</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.filter_id}>
              <td className="min-w-80">
                <div className="font-bold">{row.label}</div>
                <div className="mt-1 text-xs leading-5 text-slate-500">{row.expression}</div>
              </td>
              <td><StatusBadge value={humanFlag(row.filter_class)} /></td>
              <td>{row.retained_count} / {row.removed_count}</td>
              <td>{row.tp_count} / {row.sl_count}</td>
              <td className={toneClass(row.realistic_total_r_closed)}>{fmtSigned(row.realistic_total_r_closed)}R</td>
              <td className={toneClass(row.realistic_avg_r_delta_vs_baseline)}>{fmtSigned(row.realistic_avg_r_delta_vs_baseline)}R</td>
              <td className={toneClass(row.removed_realistic_total_r_closed)}>{fmtSigned(row.removed_realistic_total_r_closed)}R</td>
              <td className="max-w-80 text-xs leading-5 text-slate-600">{pathMixSummary(row.removed_mechanism_mix)}</td>
              <td className="max-w-96 text-sm leading-5 text-slate-700">{row.filter_read}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function BreakoutInteractionTable({ rows }: { rows: MidLongBreakoutInteractionRow[] }) {
  if (!rows.length) return <div className="p-4"><EmptyState title="Interaction kosong" detail="Belum ada cluster interaction." /></div>;
  return (
    <div className="table-wrap">
      <table className="ops-table">
        <thead>
          <tr>
            <th>Cluster</th>
            <th>N</th>
            <th>TP / SL</th>
            <th>R</th>
            <th>Avg delta</th>
            <th>Mechanism</th>
            <th>Read</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.interaction_id}>
              <td className="min-w-72">
                <div className="font-bold">{row.label}</div>
                <div className="text-xs text-slate-500">{row.expression}</div>
              </td>
              <td>{row.closed_count}</td>
              <td>{row.tp_count} / {row.sl_count}</td>
              <td className={toneClass(row.realistic_total_r_closed)}>{fmtSigned(row.realistic_total_r_closed)}R</td>
              <td className={toneClass(row.realistic_avg_r_delta_vs_baseline)}>{fmtSigned(row.realistic_avg_r_delta_vs_baseline)}R</td>
              <td className="max-w-72 text-xs leading-5 text-slate-600">{pathMixSummary(row.mechanism_mix)}</td>
              <td className="max-w-96 text-sm leading-5 text-slate-700">{row.interaction_read}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function BreakoutDraftTable({ rows }: { rows: MidLongBreakoutDraftRow[] }) {
  if (!rows.length) return <div className="p-4"><EmptyState title="Draft kosong" detail="Belum ada draft cohort breakout." /></div>;
  return (
    <div className="table-wrap">
      <table className="ops-table">
        <thead>
          <tr>
            <th>Draft</th>
            <th>Status</th>
            <th>Retained</th>
            <th>TP / SL</th>
            <th>R</th>
            <th>Avg delta</th>
            <th>Discarded</th>
            <th>Read</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.draft_id}>
              <td className="min-w-80">
                <div className="font-bold">{humanFlag(row.label)}</div>
                <div className="text-xs leading-5 text-slate-500">{row.expression}</div>
              </td>
              <td><StatusBadge value={humanFlag(row.draft_status)} /></td>
              <td>{row.closed_count}</td>
              <td>{row.tp_count} / {row.sl_count}</td>
              <td className={toneClass(row.realistic_total_r_closed)}>{fmtSigned(row.realistic_total_r_closed)}R</td>
              <td className={toneClass(row.realistic_avg_r_delta_vs_baseline)}>{fmtSigned(row.realistic_avg_r_delta_vs_baseline)}R</td>
              <td>
                <div>{row.discarded_count} rows</div>
                <div className="text-xs text-slate-500">{row.discarded_tp_count}/{row.discarded_sl_count} TP/SL</div>
                <div className={toneClass(row.discarded_realistic_total_r_closed)}>{fmtSigned(row.discarded_realistic_total_r_closed)}R</div>
              </td>
              <td className="max-w-96 text-sm leading-5 text-slate-700">{row.draft_read}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function BreakoutCrossPanels({
  tables,
  title = "Evidence x observable path",
  description = "Path cross untuk breakout proxy cohort."
}: {
  tables: Record<string, MidLongTaxonomyPathCrossRow[]>;
  title?: string;
  description?: string;
}) {
  const entries = Object.entries(tables);
  if (!entries.length) return null;
  return (
    <div className="border-b border-line">
      <div className="px-4 py-3">
        <div className="font-bold">{title}</div>
        <div className="mt-1 text-xs leading-5 text-slate-500">{description}</div>
      </div>
      <div className="grid gap-4 p-4 2xl:grid-cols-2">
      {entries.slice(0, 6).map(([key, rows]) => (
        <div key={key} className="rounded-md border border-line bg-white">
          <div className="border-b border-line px-4 py-3">
            <div className="font-bold">{humanFlag(key)}</div>
            <div className="mt-1 text-xs text-slate-500">Bucket x observable path.</div>
          </div>
          <TaxonomyCrossTable rows={rows.slice(0, 10)} />
        </div>
      ))}
      </div>
    </div>
  );
}

function IntegrityAuditPanel({ audit }: { audit: MidLongIntegrityAudit }) {
  const flags = audit.anomaly_flags || [];
  return (
    <div>
      <div className="grid gap-3 border-b border-line p-4 md:grid-cols-2 xl:grid-cols-5">
        <Info label="Read" value={humanFlag(audit.read)} helper="Kalau ada warning, baca dulu sebelum damage filter." />
        <Info label="Path rows" value={audit.path_economics_rows.length.toString()} helper="Path economics + cost drag." />
        <Info label="Flow rows" value={audit.flow_economics_rows.length.toString()} helper="Flow vs realistic economics." />
        <Info label="Room rows" value={audit.room_quality_rows.length.toString()} helper="Coverage dan non-monotonic risk." />
        <Info label="Flags" value={flags.length.toString()} helper="Anomali yang harus diaudit." />
      </div>

      {flags.length > 0 && (
        <div className="grid gap-3 border-b border-line p-4 lg:grid-cols-2">
          {flags.map((flag) => (
            <div key={flag.flag_id} className="rounded-md border border-amber-300 bg-amber-50 p-4">
              <div className="flex flex-wrap items-center gap-2">
                <StatusBadge value={flag.severity} />
                <div className="font-bold">{humanFlag(flag.flag_id)}</div>
              </div>
              <div className="mt-2 text-sm leading-6 text-slate-700">{flag.read}</div>
              <div className="mt-2 grid gap-2 text-xs text-slate-600 sm:grid-cols-2">
                {flag.sample_count !== undefined && <div>Sample: <b>{flag.sample_count}</b></div>}
                {flag.sample_retention_pct !== undefined && <div>Share: <b>{formatPct(flag.sample_retention_pct)}</b></div>}
                {flag.realistic_avg_r_closed !== undefined && <div>Avg R: <b>{fmtSigned(flag.realistic_avg_r_closed)}R</b></div>}
                {flag.execution_drag_avg_r !== undefined && <div>Drag avg: <b>{fmtSigned(flag.execution_drag_avg_r)}R</b></div>}
              </div>
              {flag.next_check && <div className="mt-2 text-xs font-semibold text-slate-700">Next: {flag.next_check}</div>}
            </div>
          ))}
        </div>
      )}

      <div className="grid gap-4 p-4 2xl:grid-cols-2">
        <div className="rounded-md border border-line bg-white">
          <div className="border-b border-line px-4 py-3">
            <div className="font-bold">Path economics</div>
            <div className="mt-1 text-xs text-slate-500">Ideal vs realistic, cost drag, stop distance, dan acceptance conversion per path.</div>
          </div>
          <EconomicTable rows={audit.path_economics_rows} />
        </div>
        <div className="rounded-md border border-line bg-white">
          <div className="border-b border-line px-4 py-3">
            <div className="font-bold">Flow economics</div>
            <div className="mt-1 text-xs text-slate-500">Flow confirmed/weak/mixed dibaca bersama drag dan conversion, bukan winrate saja.</div>
          </div>
          <EconomicTable rows={audit.flow_economics_rows} />
        </div>
        <div className="rounded-md border border-line bg-white">
          <div className="border-b border-line px-4 py-3">
            <div className="font-bold">Room quality</div>
            <div className="mt-1 text-xs text-slate-500">Room masih descriptive sampai coverage dan zone anchor lebih stabil.</div>
          </div>
          <EconomicTable rows={audit.room_quality_rows} />
        </div>
        <div className="rounded-md border border-line bg-white">
          <div className="border-b border-line px-4 py-3">
            <div className="font-bold">Cost economics</div>
            <div className="mt-1 text-xs text-slate-500">Biaya dalam R bisa membuat arah benar tetap tidak ekonomis.</div>
          </div>
          <EconomicTable rows={audit.cost_economics_rows} />
        </div>
      </div>
    </div>
  );
}

function DamageIsolationPanel({ damage }: { damage: NonNullable<MidLongBaselineResponse["definition_audit"]>["damage_isolation"] }) {
  if (!damage) return null;
  return (
    <div>
      <div className="grid gap-3 border-b border-line p-4 md:grid-cols-2 xl:grid-cols-4">
        <Info label="Read" value={damage.read} helper="Filter paling kuat sementara, read-only." />
        <Info label="Experiments" value={damage.experiment_rows.length.toString()} helper="DI-00 sampai DI-05." />
        <Info label="MID_RANGE cross" value={Object.keys(damage.mid_range_interactions || {}).length.toString()} helper="Cari subset tersembunyi." />
        <Info label="CONFIRMED cross" value={Object.keys(damage.confirmed_flow_interactions || {}).length.toString()} helper="Flow benar gagal di struktur apa." />
      </div>

      <DamageExperimentTable rows={damage.experiment_rows} />

      <div className="grid gap-4 border-t border-line p-4 2xl:grid-cols-2">
        <div className="rounded-md border border-line bg-white">
          <div className="border-b border-line px-4 py-3">
            <div className="font-bold">MID_RANGE interactions</div>
            <div className="mt-1 text-xs text-slate-500">Pertanyaan: apakah ada subset MID_RANGE yang masih punya anchor tersembunyi?</div>
          </div>
          <SubsetInteractionTables tables={damage.mid_range_interactions || {}} />
        </div>
        <div className="rounded-md border border-line bg-white">
          <div className="border-b border-line px-4 py-3">
            <div className="font-bold">CONFIRMED flow interactions</div>
            <div className="mt-1 text-xs text-slate-500">Pertanyaan: flow sudah benar, tapi gagal karena setup, room, crowding, extension, atau cost?</div>
          </div>
          <SubsetInteractionTables tables={damage.confirmed_flow_interactions || {}} />
        </div>
      </div>
    </div>
  );
}

function EconomicTable({ rows }: { rows: MidLongEconomicRow[] }) {
  if (!rows.length) return <div className="p-4"><EmptyState title="Economics kosong" detail="Belum ada row untuk audit ini." /></div>;
  return (
    <div className="table-wrap">
      <table className="ops-table">
        <thead>
          <tr>
            <th>Bucket</th>
            <th>N</th>
            <th>TP / SL</th>
            <th>Ideal / realistic</th>
            <th>Avg ideal / real</th>
            <th>Drag</th>
            <th>Cost / stop</th>
            <th>Accept +0.5R</th>
          </tr>
        </thead>
        <tbody>
          {rows.slice(0, 16).map((row) => (
            <tr key={row.filter_id}>
              <td className="min-w-64">
                <StatusBadge value={humanFlag(row.label)} />
                {row.path_read && <div className="mt-1 text-xs leading-5 text-slate-500">{row.path_read}</div>}
              </td>
              <td className="font-bold">{row.closed_count}</td>
              <td>{row.tp_count} / {row.sl_count}</td>
              <td>
                <div>{fmtSigned(row.ideal_total_r_closed)}R ideal</div>
                <div className={toneClass(row.realistic_total_r_closed)}>{fmtSigned(row.realistic_total_r_closed)}R real</div>
              </td>
              <td>{fmtSigned(row.ideal_avg_r_closed)}R / {fmtSigned(row.realistic_avg_r_closed)}R</td>
              <td>
                <div>{fmtSigned(row.execution_drag_r)}R</div>
                <div className="text-xs text-slate-500">{fmtSigned(row.execution_drag_avg_r)}R avg</div>
              </td>
              <td>
                <div>{fmtNumber(row.median_cost_r)}R cost</div>
                <div className="text-xs text-slate-500">{fmtNumber(row.median_stop_pct)}% stop</div>
              </td>
              <td>
                <div>{row.close_050_count || 0}/{row.touch_050_count || 0}</div>
                <div className="text-xs text-slate-500">{formatPct(row.close_acceptance_conversion_pct)}</div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function DamageExperimentTable({ rows }: { rows: MidLongDamageExperimentRow[] }) {
  if (!rows.length) return <div className="p-4"><EmptyState title="Damage isolation kosong" detail="Belum ada eksperimen DI." /></div>;
  return (
    <div className="table-wrap">
      <table className="ops-table">
        <thead>
          <tr>
            <th>Experiment</th>
            <th>Retained / removed</th>
            <th>Retained TP/SL</th>
            <th>Retained R</th>
            <th>Avg delta</th>
            <th>Removed R</th>
            <th>Damage removed</th>
            <th>Winner cost</th>
            <th>Read</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.experiment_id}>
              <td className="min-w-80">
                <div className="font-bold">{row.experiment_id} - {row.label}</div>
                <div className="mt-1 text-xs leading-5 text-slate-500">{row.expression}</div>
              </td>
              <td>{row.retained_count} / {row.removed_count}</td>
              <td>{row.tp_count} / {row.sl_count}</td>
              <td className={toneClass(row.realistic_total_r_closed)}>{fmtSigned(row.realistic_total_r_closed)}R</td>
              <td className={toneClass(row.realistic_avg_r_delta_vs_baseline)}>{fmtSigned(row.realistic_avg_r_delta_vs_baseline)}R</td>
              <td className={toneClass(row.removed_realistic_total_r_closed)}>{fmtSigned(row.removed_realistic_total_r_closed)}R</td>
              <td>
                <div>Close fail {row.close_profit_then_fail_removed_count} ({formatPct(row.close_profit_then_fail_removed_pct)})</div>
                <div className="text-xs text-slate-500">Instant SL {row.instant_sl_removed_count} ({formatPct(row.instant_sl_removed_pct)})</div>
              </td>
              <td>Pullback TP removed {row.pullback_tp_removed_count} ({formatPct(row.pullback_tp_removed_pct)})</td>
              <td className="max-w-96 text-sm leading-5 text-slate-700">{row.damage_read}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function SubsetInteractionTables({ tables }: { tables: Record<string, MidLongSubsetDimensionRow[]> }) {
  const entries = Object.entries(tables);
  if (!entries.length) return <div className="p-4"><EmptyState title="Interaction kosong" detail="Belum ada interaction table." /></div>;
  return (
    <div className="grid gap-4 p-4">
      {entries.map(([key, rows]) => (
        <div key={key} className="rounded-md border border-line bg-field/30">
          <div className="border-b border-line px-3 py-2 text-sm font-bold">{humanFlag(key)}</div>
          <SubsetInteractionTable rows={rows.slice(0, 8)} />
        </div>
      ))}
    </div>
  );
}

function SubsetInteractionTable({ rows }: { rows: MidLongSubsetDimensionRow[] }) {
  if (!rows.length) return <div className="p-3 text-sm text-slate-500">No rows.</div>;
  return (
    <div className="table-wrap">
      <table className="ops-table">
        <thead>
          <tr>
            <th>State</th>
            <th>N</th>
            <th>Share</th>
            <th>TP / SL</th>
            <th>R</th>
            <th>Avg</th>
            <th>Path mix</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.filter_id}>
              <td><StatusBadge value={humanFlag(row.state)} /></td>
              <td className="font-bold">{row.closed_count}</td>
              <td>{formatPct(row.anchor_retention_pct)}</td>
              <td>{row.tp_count} / {row.sl_count}</td>
              <td className={toneClass(row.realistic_total_r_closed)}>{fmtSigned(row.realistic_total_r_closed)}R</td>
              <td>{fmtSigned(row.realistic_avg_r_closed)}R</td>
              <td className="max-w-80 text-xs leading-5 text-slate-600">{pathMixSummary(row.path_mix)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function TaxonomyOverview({ taxonomy }: { taxonomy: MidLongTaxonomyStudy }) {
  return (
    <div>
      <div className="grid gap-3 border-b border-line p-4 md:grid-cols-2 xl:grid-cols-5">
        <Info label="Scope" value={taxonomy.scope} />
        <Info label="Acceptance" value={`+${fmtNumber(taxonomy.canonical_acceptance_threshold_r)}R close`} helper="Profit dianggap diterima kalau close sudah minimal +0.5R." />
        <Info label="Extension q25" value={`${fmtNumber(taxonomy.extension_quantiles.q25)}x`} helper="Bucket low extension." />
        <Info label="Extension q75/q90" value={`${fmtNumber(taxonomy.extension_quantiles.q75)}x / ${fmtNumber(taxonomy.extension_quantiles.q90)}x`} helper="High dan extreme extension." />
        <Info label="Mode" value="Read-only taxonomy" helper="Flag belum jadi gate live." />
      </div>
      <div className="grid gap-2 p-4 text-sm text-slate-700 md:grid-cols-2">
        {taxonomy.raw_feature_notes.map((note) => (
          <div key={note} className="rounded-md border border-line bg-field/40 p-3">- {note}</div>
        ))}
      </div>
    </div>
  );
}

function TaxonomyDimensionPanels({ taxonomy }: { taxonomy: MidLongTaxonomyStudy }) {
  const panels: { key: string; title: string; description: string }[] = [
    { key: "setup_family", title: "Setup family", description: "Breakout, retest, support bounce, mid-range, atau belum terklasifikasi." },
    { key: "breakout_state_pre_entry", title: "Breakout state", description: "Apakah breakout cuma wick atau sudah close accepted." },
    { key: "retest_quality_pre_entry", title: "Retest quality", description: "Apakah retest hold kuat, hold dalam zona, gagal, atau tidak ada retest." },
    { key: "entry_timing_bucket", title: "Entry timing", description: "Early/normal/late chase berbasis extension quantile." },
    { key: "flow_state_provisional", title: "Flow state", description: "Flow buy/weak/mixed berbasis price, OI, dan taker buy." },
    { key: "crowding_bucket", title: "Crowding", description: "Funding, OI z-score, global/top-trader long ratio." },
    { key: "room_to_resistance_bucket", title: "Room to resistance", description: "Jarak ATR ke resistance terdekat dari structure zone." },
    { key: "projected_cost_bucket", title: "Projected cost", description: "Estimasi fee + spread + slippage dalam R." }
  ];

  return (
    <div className="grid gap-4 p-4 2xl:grid-cols-2">
      {panels.map((panel) => (
        <div key={panel.key} className="rounded-md border border-line bg-white">
          <div className="border-b border-line px-4 py-3">
            <div className="font-bold">{panel.title}</div>
            <div className="mt-1 text-xs leading-5 text-slate-500">{panel.description}</div>
          </div>
          <TaxonomyDimensionTable rows={(taxonomy.dimension_rows[panel.key] || []).slice(0, 8)} />
        </div>
      ))}
    </div>
  );
}

function TaxonomyDimensionTable({ rows }: { rows: MidLongTaxonomyDimensionRow[] }) {
  if (!rows.length) return <div className="p-4"><EmptyState title="Bucket kosong" detail="Belum ada row untuk dimensi ini." /></div>;
  return (
    <div className="table-wrap">
      <table className="ops-table">
        <thead>
          <tr>
            <th>State</th>
            <th>N</th>
            <th>TP / SL</th>
            <th>Realistic R</th>
            <th>Avg / median</th>
            <th>Cost / room</th>
            <th>Path mix</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.filter_id}>
              <td>
                <StatusBadge value={humanFlag(row.state)} />
                <div className="mt-1 text-xs text-slate-500">{humanFlag(row.verdict)}</div>
              </td>
              <td className="font-bold">{row.closed_count}</td>
              <td>{row.tp_count} / {row.sl_count}</td>
              <td className={toneClass(row.realistic_total_r_closed)}>{fmtSigned(row.realistic_total_r_closed)}R</td>
              <td>{fmtSigned(row.realistic_avg_r_closed)}R / {fmtSigned(row.median_realistic_r_closed)}R</td>
              <td>
                <div>{fmtNumber(row.median_cost_r)}R cost</div>
                <div className="text-xs text-slate-500">{fmtNumber(row.median_room_to_resistance_atr)} ATR room</div>
              </td>
              <td className="max-w-80 text-xs leading-5 text-slate-600">{pathMixSummary(row.path_mix)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function TaxonomyPathTable({ rows }: { rows: MidLongTaxonomyPathRow[] }) {
  if (!rows.length) return <div className="p-4"><EmptyState title="Path sequencing kosong" detail="Snapshot perlu direfresh agar path +0.5R tersedia." /></div>;
  return (
    <div className="table-wrap">
      <table className="ops-table">
        <thead>
          <tr>
            <th>Path label</th>
            <th>N</th>
            <th>TP / SL</th>
            <th>Realistic R</th>
            <th>Avg / median</th>
            <th>Wick decay</th>
            <th>1h followthrough</th>
            <th>Read</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.filter_id}>
              <td><StatusBadge value={humanFlag(row.path_label)} /></td>
              <td className="font-bold">{row.closed_count}</td>
              <td>{row.tp_count} / {row.sl_count}</td>
              <td className={toneClass(row.realistic_total_r_closed)}>{fmtSigned(row.realistic_total_r_closed)}R</td>
              <td>{fmtSigned(row.realistic_avg_r_closed)}R / {fmtSigned(row.median_realistic_r_closed)}R</td>
              <td>{fmtSigned(row.median_wick_decay_r)}R</td>
              <td>{fmtSigned(row.median_followthrough_1h_r)}R</td>
              <td className="max-w-96 text-sm leading-5 text-slate-700">{row.path_read}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function TaxonomyCrossTable({ rows }: { rows: MidLongTaxonomyPathCrossRow[] }) {
  if (!rows.length) return <div className="p-4"><EmptyState title="Cross path kosong" detail="Belum ada kombinasi taxonomy x path." /></div>;
  return (
    <div className="table-wrap">
      <table className="ops-table">
        <thead>
          <tr>
            <th>Cell</th>
            <th>N</th>
            <th>TP / SL</th>
            <th>Realistic R</th>
            <th>Avg</th>
            <th>Top symbol</th>
            <th>Readable</th>
          </tr>
        </thead>
        <tbody>
          {rows.slice(0, 18).map((row) => (
            <tr key={row.filter_id}>
              <td className="min-w-72 font-semibold">{humanFlag(row.cell)}</td>
              <td>{row.closed_count}</td>
              <td>{row.tp_count} / {row.sl_count}</td>
              <td className={toneClass(row.realistic_total_r_closed)}>{fmtSigned(row.realistic_total_r_closed)}R</td>
              <td>{fmtSigned(row.realistic_avg_r_closed)}R</td>
              <td>{row.top_symbol || "-"} ({formatPct(row.top_symbol_share_pct)})</td>
              <td><StatusBadge value={row.is_readable ? "Readable" : "Small sample"} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function DraftPreviewTable({ rows }: { rows: MidLongDraftPreviewRow[] }) {
  if (!rows.length) return <div className="p-4"><EmptyState title="Draft preview kosong" detail="Belum ada skenario draft V2.1." /></div>;
  return (
    <div className="table-wrap">
      <table className="ops-table">
        <thead>
          <tr>
            <th>Preview</th>
            <th>Retained N</th>
            <th>Retained TP/SL</th>
            <th>Retained R</th>
            <th>Avg delta</th>
            <th>Discarded</th>
            <th>Retained path mix</th>
            <th>Read</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.preview_id}>
              <td className="min-w-80">
                <div className="font-bold">{row.preview_id}</div>
                <div className="mt-1 text-xs leading-5 text-slate-500">{row.label}</div>
                {row.note && <div className="mt-1 text-xs leading-5 text-slate-500">{row.note}</div>}
              </td>
              <td className="font-bold">{row.closed_count}</td>
              <td>{row.tp_count} / {row.sl_count}</td>
              <td className={toneClass(row.realistic_total_r_closed)}>{fmtSigned(row.realistic_total_r_closed)}R</td>
              <td className={toneClass(row.realistic_avg_r_delta_vs_baseline)}>{fmtSigned(row.realistic_avg_r_delta_vs_baseline)}R</td>
              <td>
                <div>{row.discarded_count} rows</div>
                <div className="text-xs text-slate-500">{row.discarded_tp_count} TP / {row.discarded_sl_count} SL</div>
                <div className={toneClass(row.discarded_realistic_total_r_closed)}>{fmtSigned(row.discarded_realistic_total_r_closed)}R</div>
              </td>
              <td className="max-w-72 text-xs leading-5 text-slate-600">{pathMixSummary(row.retained_path_mix)}</td>
              <td className="max-w-96 text-sm leading-5 text-slate-700">{row.preview_read}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function LayerTable({ rows }: { rows: MidLongDefinitionLayerRow[] }) {
  return (
    <div className="table-wrap">
      <table className="ops-table">
        <thead>
          <tr>
            <th>Layer</th>
            <th>Sample</th>
            <th>TP / SL</th>
            <th>Ideal R</th>
            <th>Realistic R</th>
            <th>Cost gap</th>
            <th>Avg / median realistic</th>
            <th>Median cost</th>
            <th>Read</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.filter_id}>
              <td>
                <div className="font-bold">{row.label}</div>
                <div className="text-xs text-slate-500">{row.expression}</div>
              </td>
              <td>{row.closed_count}</td>
              <td>{row.tp_count} / {row.sl_count}</td>
              <td className={toneClass(row.ideal_total_r_closed)}>{fmtSigned(row.ideal_total_r_closed)}R</td>
              <td className={toneClass(row.realistic_total_r_closed)}>{fmtSigned(row.realistic_total_r_closed)}R</td>
              <td>{fmtSigned(row.ideal_realistic_gap_r)}R</td>
              <td>{fmtSigned(row.realistic_avg_r_closed)}R / {fmtSigned(row.median_realistic_r_closed)}R</td>
              <td>{fmtNumber(row.median_cost_r)}R</td>
              <td className="max-w-96 text-sm leading-5 text-slate-700">{row.note}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function PathDecisionTable({ rows, read }: { rows: MidLongPathDecisionRow[]; read: string }) {
  return (
    <div>
      <div className="border-b border-line bg-field/40 px-4 py-3 text-sm">
        Current path read: <span className="font-bold">{humanFlag(read)}</span>
      </div>
      <div className="table-wrap">
        <table className="ops-table">
          <thead>
            <tr>
              <th>Path</th>
              <th>Definition</th>
              <th>Count</th>
              <th>Share</th>
              <th>Realistic R</th>
              <th>Median MFE</th>
              <th>Median MAE</th>
              <th>Interpretasi</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.bucket}>
                <td><StatusBadge value={humanFlag(row.label)} /></td>
                <td className="max-w-80 text-sm text-slate-600">{row.definition}</td>
                <td className="font-bold">{row.count}</td>
                <td>{formatPct(row.share_pct)}</td>
                <td className={toneClass(row.realistic_total_r_closed)}>{fmtSigned(row.realistic_total_r_closed)}R</td>
                <td>{fmtSigned(row.median_mfe_r)}R</td>
                <td>{fmtSigned(row.median_mae_r)}R</td>
                <td className="max-w-96 text-sm text-slate-700">{pathInterpretation(row.bucket)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function AxisAuditTable({ rows }: { rows: MidLongAxisAuditRow[] }) {
  if (!rows.length) return <div className="p-4"><EmptyState title="Axis audit kosong" detail="Belum ada row axis." /></div>;
  return (
    <div className="table-wrap">
      <table className="ops-table">
        <thead>
          <tr>
            <th>Axis</th>
            <th>State</th>
            <th>Sample</th>
            <th>TP / SL</th>
            <th>Realistic R</th>
            <th>Avg / median</th>
            <th>Negative R share</th>
            <th>Top3 symbol</th>
            <th>Read</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={`${row.axis}-${row.state}`}>
              <td>
                <div className="font-bold">{row.axis}</div>
                <div className="text-xs text-slate-500">{row.axis_label}</div>
              </td>
              <td><StatusBadge value={humanFlag(row.state)} /></td>
              <td>
                <div className="font-bold">{row.closed_count}</div>
                <div className="text-xs text-slate-500">{formatPct(row.sample_retention_pct)} sample</div>
              </td>
              <td>{row.tp_count} / {row.sl_count}</td>
              <td className={toneClass(row.realistic_total_r_closed)}>{fmtSigned(row.realistic_total_r_closed)}R</td>
              <td>{fmtSigned(row.realistic_avg_r_closed)}R / {fmtSigned(row.median_realistic_r_closed)}R</td>
              <td>
                <div className={Number(row.negative_r_share_pct || 0) >= 20 ? "font-bold text-stale" : ""}>{formatPct(row.negative_r_share_pct)}</div>
                <div className="text-xs text-slate-500">{fmtNumber(row.negative_r_abs)}R loss</div>
              </td>
              <td>{formatPct(row.top3_symbol_share_pct)}</td>
              <td className="max-w-96 text-sm leading-5 text-slate-700">{row.read}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function CrossTable({ rows }: { rows: MidLongAxisCrossRow[] }) {
  if (!rows.length) return <div className="p-4"><EmptyState title="Cross table kosong" detail="Belum ada kombinasi axis." /></div>;
  return (
    <div className="table-wrap">
      <table className="ops-table">
        <thead>
          <tr>
            <th>Cell</th>
            <th>N</th>
            <th>TP / SL</th>
            <th>Realistic R</th>
            <th>Avg</th>
            <th>Negative R share</th>
            <th>Readable</th>
          </tr>
        </thead>
        <tbody>
          {rows.slice(0, 18).map((row) => (
            <tr key={row.filter_id}>
              <td className="font-semibold">{humanFlag(row.cell)}</td>
              <td>{row.closed_count}</td>
              <td>{row.tp_count} / {row.sl_count}</td>
              <td className={toneClass(row.realistic_total_r_closed)}>{fmtSigned(row.realistic_total_r_closed)}R</td>
              <td>{fmtSigned(row.realistic_avg_r_closed)}R</td>
              <td>{formatPct(row.negative_r_share_pct)}</td>
              <td><StatusBadge value={row.is_readable ? "Readable" : "Small sample"} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function GeometryTable({
  rows,
  read,
  quantiles
}: {
  rows: MidLongGeometryThresholdRow[];
  read: string;
  quantiles: {
    winner_mae_quantiles: Record<string, string | number | null>;
    loser_mfe_quantiles: Record<string, string | number | null>;
  };
}) {
  return (
    <div>
      <div className="grid gap-3 border-b border-line bg-field/40 p-4 md:grid-cols-3">
        <Info label="Geometry read" value={humanFlag(read)} />
        <Info
          label="Winner MAE q50/q90"
          value={`${fmtSigned(quantiles.winner_mae_quantiles.q50)}R / ${fmtSigned(quantiles.winner_mae_quantiles.q90)}R`}
          helper="Seberapa dalam winner biasanya sempat turun."
        />
        <Info
          label="Loser MFE q50/q90"
          value={`${fmtSigned(quantiles.loser_mfe_quantiles.q50)}R / ${fmtSigned(quantiles.loser_mfe_quantiles.q90)}R`}
          helper="Seberapa jauh loser sempat benar sebelum gagal."
        />
      </div>
      <div className="table-wrap">
        <table className="ops-table">
          <thead>
            <tr>
              <th>MFE threshold</th>
              <th>Touched</th>
              <th>Touched share</th>
              <th>TP after touch</th>
              <th>SL after touch</th>
              <th>P(TP | touched)</th>
              <th>P(SL | touched)</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={String(row.threshold_r)}>
                <td className="font-bold">+{fmtNumber(row.threshold_r)}R</td>
                <td>{row.touched_count}</td>
                <td>{formatPct(row.touched_share_pct)}</td>
                <td>{row.tp_after_count}</td>
                <td>{row.sl_after_count}</td>
                <td>{formatPct(row.tp_given_touch_pct)}</td>
                <td>{formatPct(row.sl_given_touch_pct)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function AblationTable({ rows }: { rows: MidLongAblationRow[] }) {
  if (!rows.length) return <div className="p-4"><EmptyState title="Ablation kosong" detail="Belum ada scenario ablation." /></div>;
  return (
    <div className="table-wrap">
      <table className="ops-table">
        <thead>
          <tr>
            <th>Scenario</th>
            <th>Survivor N</th>
            <th>Survivor TP/SL</th>
            <th>Survivor R</th>
            <th>Avg delta</th>
            <th>Discarded N</th>
            <th>Discarded TP/SL</th>
            <th>Discarded R</th>
            <th>Read</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.filter_id}>
              <td className="min-w-72">
                <div className="font-bold">{row.label}</div>
                <div className="text-xs leading-5 text-slate-500">{row.expression}</div>
              </td>
              <td>{row.closed_count}</td>
              <td>{row.tp_count} / {row.sl_count}</td>
              <td className={toneClass(row.realistic_total_r_closed)}>{fmtSigned(row.realistic_total_r_closed)}R</td>
              <td className={toneClass(row.realistic_avg_r_delta_vs_baseline)}>{fmtSigned(row.realistic_avg_r_delta_vs_baseline)}R</td>
              <td>{row.discarded_count}</td>
              <td>{row.discarded_tp_count} / {row.discarded_sl_count}</td>
              <td className={toneClass(row.discarded_realistic_total_r_closed)}>{fmtSigned(row.discarded_realistic_total_r_closed)}R</td>
              <td className="max-w-96 text-sm leading-5 text-slate-700">{row.ablation_read}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function EvidenceTable({ rows, sampleTotal }: { rows: MidLongEvidenceComparisonRow[]; sampleTotal: number }) {
  if (!rows.length) return <div className="p-4"><EmptyState title="Evidence belum tersedia" detail="Snapshot belum berisi evidence comparison." /></div>;
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

function BaselineSignalTable({ rows }: { rows: SignalPerformanceItem[] }) {
  if (!rows.length) return <div className="p-4"><EmptyState title="Belum ada closed signal" detail="Cohort MID_LONG 1h baseline masih kosong." /></div>;
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

function pathMixSummary(pathMix?: Record<string, number>): string {
  if (!pathMix || !Object.keys(pathMix).length) return "-";
  return Object.entries(pathMix)
    .sort((left, right) => right[1] - left[1])
    .slice(0, 4)
    .map(([label, count]) => `${humanFlag(label)} ${count}`)
    .join(" | ");
}

function statusMixSummary(statusCounts?: Record<string, number>): string {
  if (!statusCounts || !Object.keys(statusCounts).length) return "Belum ada status.";
  return Object.entries(statusCounts)
    .sort((left, right) => right[1] - left[1])
    .map(([status, count]) => `${humanFlag(status)} ${count}`)
    .join(" | ");
}

function humanFlag(value: string): string {
  return value
    .replace(/_/g, " ")
    .replace(/\s*x\s*/gi, " x ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase())
    .replace(/\bV2\b/g, "V2")
    .replace(/\bV21\b/g, "V2.1")
    .replace(/\bTp\b/g, "TP")
    .replace(/\bSl\b/g, "SL")
    .replace(/\bRr\b/g, "RR")
    .replace(/\bAtr\b/g, "ATR")
    .replace(/\bOi\b/g, "OI");
}

function pathInterpretation(bucket: string): string {
  const map: Record<string, string> = {
    INSTANT_SL: "Definisi entry patut dicurigai: signal hampir tidak pernah bergerak benar.",
    PARTIAL_FAIL: "Ada follow-through kecil, tapi belum cukup. Cek flow/structure dan timeout.",
    DEEP_FAIL: "Arah awal benar; geometry/exit lebih dicurigai daripada definisi.",
    CLEAN_TP: "Profil winner paling penting untuk ditiru oleh rule V2.1.",
    PULLBACK_TP: "Winner butuh ruang; stop terlalu sempit bisa memotong TP.",
    BOTH_SAME_CANDLE: "Butuh resolusi candle lebih kecil atau asumsi konservatif.",
    OTHER: "Tidak masuk TP/SL/BOTH utama."
  };
  return map[bucket] || "Path audit row.";
}
