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
  MidLongDefinitionLayerRow,
  MidLongDraftPreviewRow,
  MidLongEvidenceComparisonRow,
  MidLongGeometryThresholdRow,
  MidLongPathDecisionRow,
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

          {taxonomy && (
            <>
              <SectionCard
                title="1. Taxonomy v1"
                description="MID_LONG 1h sekarang dibedah sebagai banyak flag sekaligus: setup, breakout/retest, flow, crowding, room, cost, dan path setelah entry. Ini belum mengubah rule."
              >
                <TaxonomyOverview taxonomy={taxonomy} />
              </SectionCard>

              <SectionCard
                title="2. Pre-entry dimensions"
                description="Bucket ini dibuat dari data sebelum entry. Tujuannya mencari bagian definisi MID_LONG yang paling sering membawa TP atau SL."
              >
                <TaxonomyDimensionPanels taxonomy={taxonomy} />
              </SectionCard>

              <SectionCard
                title="3. Path sequencing +0.5R"
                description="Path ini menjawab apakah signal langsung salah arah, cuma wick profit, close diterima lalu gagal, atau continuation bersih. Acceptance canonical sementara: close profit +0.5R."
              >
                <TaxonomyPathTable rows={taxonomy.path_sequence_rows} />
              </SectionCard>

              <div className="grid gap-4 2xl:grid-cols-2">
                <SectionCard title="4A. Setup x path" description="Cek setup family mana yang paling sering jatuh ke instant SL, wick fail, atau clean continuation.">
                  <TaxonomyCrossTable rows={taxonomy.taxonomy_path_cross_tables.setup_family_x_path || []} />
                </SectionCard>
                <SectionCard title="4B. Flow x path" description="Cek apakah flow sebelum entry punya hubungan jelas dengan path setelah entry.">
                  <TaxonomyCrossTable rows={taxonomy.taxonomy_path_cross_tables.flow_x_path || []} />
                </SectionCard>
              </div>

              <SectionCard
                title="5. Draft V2.1 preview"
                description="Empat skenario ini hanya preview riset. Retained/discarded dibandingkan untuk tahu apakah hygiene, breakout, retest, atau crowding interaction layak diteliti lanjut."
              >
                <DraftPreviewTable rows={taxonomy.draft_v21_previews} />
              </SectionCard>
            </>
          )}

          <SectionCard
            title="6. Layer decomposition"
            description="Pisahkan dulu apakah masalahnya sudah ada di ideal R, atau baru rusak setelah fee/spread/slippage. EXECUTION_VALID cuma strata audit, bukan filter live."
          >
            <LayerTable rows={audit.layer_decomposition} />
          </SectionCard>

          <SectionCard
            title="7. Path anatomy legacy"
            description="Ini pemisah utama: instant SL mengarah ke problem definisi entry; sempat +1R lalu SL mengarah ke problem geometry/exit."
          >
            <PathDecisionTable rows={audit.path_decision_summary.rows} read={audit.path_decision_summary.read} />
          </SectionCard>

          <SectionCard
            title="8. 4-axis definition flags legacy"
            description="EXT, STR, FLW, dan CRD adalah flag kandidat, bukan gate. Kolom negative R share menunjukkan bucket mana yang menyumbang kerusakan terbesar."
          >
            <AxisAuditTable rows={audit.axis_rows} />
          </SectionCard>

          <div className="grid gap-4 2xl:grid-cols-2">
            <SectionCard title="9A. EXT x STR" description="Cek apakah damage terkonsentrasi pada entry extended yang dekat resistance atau mid-range.">
              <CrossTable rows={audit.cross_tables.EXTxSTR || []} />
            </SectionCard>
            <SectionCard title="9B. FLW x CRD" description="Cek apakah flow lemah dan crowding menjelaskan SL atau cuma noise.">
              <CrossTable rows={audit.cross_tables.FLWxCRD || []} />
            </SectionCard>
          </div>

          <SectionCard
            title="10. Geometry diagnostic"
            description="Kalau banyak signal pernah +0.5R/+1R tapi gagal TP, problemnya bukan hanya definisi, tapi cara panen target/stop."
          >
            <GeometryTable rows={audit.geometry_diagnostic.mfe_threshold_rows} read={audit.geometry_diagnostic.read} quantiles={audit.geometry_diagnostic} />
          </SectionCard>

          <SectionCard
            title="11. Ablation preview"
            description="Simulasi read-only: jika flag tertentu dibuang, survivor membaik atau tidak. Ini belum rule, baru calon hipotesis."
          >
            <AblationTable rows={audit.ablation_preview} />
          </SectionCard>

          <SectionCard
            title="12. TP vs SL evidence"
            description="Median dan kuartil angka aktual. Ini menjawab data mana yang beda antara signal yang kena target dan stop."
          >
            <EvidenceTable rows={(payload.evidence_comparison || []).slice(0, 18)} sampleTotal={coverage.mid_long_1h_rows} />
          </SectionCard>

          <SectionCard
            title="13. Recent closed MID_LONG 1h"
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
