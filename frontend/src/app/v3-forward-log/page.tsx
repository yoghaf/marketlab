import Link from "next/link";

import { EmptyState } from "@/components/EmptyState";
import { FilterBar, SelectFilter } from "@/components/FilterBar";
import { MetricCard } from "@/components/MetricCard";
import { PageHeader } from "@/components/PageHeader";
import { SectionCard } from "@/components/SectionCard";
import { StatusBadge } from "@/components/StatusBadge";
import {
  SignalPerformanceItem,
  V3FailureAnalysis,
  V3FailureBucketRow,
  V3FailureEvidenceRow,
  V3FailureLaneRow,
  V3ShadowFilterRow,
  V3ShadowForwardAudit,
  V3ShadowForwardFilterDecision,
  V3ShadowForwardLaneRow,
  V3ShadowForwardLogResponse,
  V3ShadowForwardLaneSummary,
  V3ShadowForwardStageDecision,
  fetchJson,
  fmtNumber,
  fmtPrice,
  fmtTime
} from "@/lib/api";
import { compactReason, labelFor } from "@/lib/labels";

type V3ForwardSearchParams = Promise<Record<string, string | string[] | undefined>>;

const stages = ["EARLY_LONG", "EARLY_SHORT", "MID_LONG", "MID_SHORT"];
const timeframes = ["15m", "1h", "4h", "24h"];
const higherTimeframes = ["1h", "4h", "24h"];

export const dynamic = "force-dynamic";

export default async function V3ForwardLogPage({ searchParams }: { searchParams: V3ForwardSearchParams }) {
  const params = await searchParams;
  const stage = firstParam(params.stage);
  const timeframe = firstParam(params.timeframe);
  const includeWatchOnly = firstParam(params.include_watch_only) === "true";
  const positionLockParam = firstParam(params.position_lock);
  const positionLock = positionLockParam === undefined ? false : positionLockParam !== "false";
  const minSample = normalizeNumber(firstParam(params.min_sample), 5, 1, 100);
  const limit = normalizeNumber(firstParam(params.limit), 50, 10, 200);
  const query = new URLSearchParams({
    include_watch_only: String(includeWatchOnly),
    position_lock: String(positionLock),
    min_sample: String(minSample),
    limit: String(limit)
  });
  if (stage) query.set("stage", stage);
  if (timeframe) query.set("timeframe", timeframe);

  let data: V3ShadowForwardLogResponse | null = null;
  let error: string | null = null;
  try {
    data = await fetchJson<V3ShadowForwardLogResponse>(`/api/v3-shadow/forward-log?${query.toString()}`, { revalidateSeconds: 20 });
  } catch (err) {
    error = err instanceof Error ? err.message : "V3 Shadow Forward API failed";
  }

  const v2 = data?.summary.v2_live;
  const v3 = data?.summary.v3_shadow_signal;
  const v2Perf = v2?.performance;
  const v3Perf = v3?.performance;
  const laneRows = data?.by_stage_timeframe || [];
  const higherTfRows = laneRows.filter((row) => higherTimeframes.includes(row.timeframe));

  return (
    <div className="space-y-5">
      <PageHeader
        title="V3 Shadow Forward Log"
        badge="READ-ONLY SHADOW LANE"
        subtitle="Pantauan paper-live V3. Fokus riset utama adalah 1h ke atas; 15m tetap ditampilkan sebagai pembanding/noise lane. Ini bukan execution dan belum mengganti rule live."
        updatedAt={fmtTime(data?.generated_at_utc)}
      />

      <div className="flex flex-wrap gap-2 text-sm">
        <Link className="rounded border border-line bg-white px-3 py-2 font-semibold hover:bg-field" href="/signal-performance">Signal History</Link>
        <Link className="rounded border border-line bg-white px-3 py-2 font-semibold hover:bg-field" href="/scanner?tier=SIGNAL_CANDIDATE&limit=75">Radar Signal</Link>
        <Link className="rounded border border-line bg-white px-3 py-2 font-semibold hover:bg-field" href="/v3-forward-log?position_lock=false&limit=100">1h+ overview</Link>
        <Link className="rounded border border-line bg-white px-3 py-2 font-semibold hover:bg-field" href="/v3-forward-log?timeframe=1h&position_lock=false&limit=100">1h</Link>
        <Link className="rounded border border-line bg-white px-3 py-2 font-semibold hover:bg-field" href="/v3-forward-log?timeframe=4h&position_lock=false&limit=100">4h</Link>
        <Link className="rounded border border-line bg-white px-3 py-2 font-semibold hover:bg-field" href="/v3-forward-log?timeframe=24h&position_lock=false&limit=100">24h</Link>
        <Link className="rounded border border-line bg-white px-3 py-2 font-semibold hover:bg-field" href="/v3-forward-log?timeframe=15m&position_lock=false&limit=100">15m compare</Link>
      </div>

      {error ? (
        <div className="rounded border border-stale bg-red-50 p-4 text-sm text-stale">{error}</div>
      ) : (
        <>
          <section className="grid gap-3 md:grid-cols-2 xl:grid-cols-6">
            <MetricCard label="V2 live R" value={`${fmtSigned(v2Perf?.total_r_closed)}R`} helper={`${v2Perf?.signals_evaluated ?? 0} evaluated`} tone={Number(v2Perf?.total_r_closed || 0) >= 0 ? "good" : "bad"} />
            <MetricCard label="V3 shadow R" value={`${fmtSigned(v3Perf?.total_r_closed)}R`} helper={`${data?.summary.v3_shadow_signal_count ?? 0} shadow signals`} tone={Number(v3Perf?.total_r_closed || 0) >= 0 ? "good" : "bad"} />
            <MetricCard label="Retention" value={`${fmtNumber(data?.summary.v3_sample_retention_pct)}%`} helper="V3 pass / V2 evaluated" tone="info" />
            <MetricCard label="V3 open" value={data?.summary.v3_shadow_open_count ?? 0} helper={`${fmtSigned(v3Perf?.open_unrealized_r)}R unrealized`} tone="warn" />
            <MetricCard label="Drawdown delta" value={`${fmtSigned(data?.summary.max_drawdown_delta_v3_vs_v2)}R`} helper="lebih tinggi berarti DD lebih kecil" tone={Number(data?.summary.max_drawdown_delta_v3_vs_v2 || 0) >= 0 ? "good" : "bad"} />
            <MetricCard label="Read" value={labelFor(data?.summary.read || "-")} helper="shadow-only verdict" tone={data?.summary.read === "V3_FORWARD_HEALTHY_SHADOW" ? "good" : "warn"} />
          </section>

          <SectionCard title="Forward controls" description="Filter ini hanya mengubah tampilan. Default position lock halaman ini off agar 1h/4h/24h tidak ketutup oleh 15m saat membandingkan lane. Nyalakan lock hanya untuk simulasi live-like satu posisi per symbol.">
            <FilterBar>
              <SelectFilter label="Stage" name="stage" value={stage || ""} options={stages} emptyLabel="All stage" />
              <SelectFilter label="Timeframe" name="timeframe" value={timeframe || ""} options={timeframes} emptyLabel="All timeframe" />
              <label className="grid gap-1 text-sm">
                <span className="font-semibold text-slate-600">Min sample</span>
                <input className="rounded border border-line px-3 py-2" min={1} max={100} name="min_sample" type="number" defaultValue={minSample} />
              </label>
              <label className="grid gap-1 text-sm">
                <span className="font-semibold text-slate-600">Rows</span>
                <input className="rounded border border-line px-3 py-2" min={10} max={200} name="limit" type="number" defaultValue={limit} />
              </label>
              <SelectFilter label="Position lock" name="position_lock" value={String(positionLock)} options={["true", "false"]} emptyLabel="Default true" />
              <label className="flex items-end gap-2 pb-2 text-sm font-semibold text-slate-600">
                <input name="include_watch_only" type="checkbox" value="true" defaultChecked={includeWatchOnly} />
                Include WATCH_ONLY
              </label>
            </FilterBar>
          </SectionCard>

          <SectionCard title="Main research read: 1h ke atas" description="Bagian ini memisahkan 1h, 4h, dan 24h dari 15m. Jadi V3 tidak lagi terbaca seolah-olah cuma 15m. Jika 4h/24h masih kosong, berarti lane itu belum punya V3 pass/sample yang cukup.">
            <HigherTimeframePanel rows={higherTfRows} />
          </SectionCard>

          <section className="grid gap-4 xl:grid-cols-2">
            <SectionCard title="V2 live signal lane" description="Semua signal live V2 sesuai filter halaman.">
              <ForwardSummary summary={v2} />
            </SectionCard>
            <SectionCard title="V3 shadow signal lane" description="Hanya signal V2 yang lolos V3 shadow filter.">
              <ForwardSummary summary={v3} />
            </SectionCard>
          </section>

          {data?.audit ? <V3AuditPanel audit={data.audit} /> : null}

          {data?.failure_analysis ? <V3FailurePanel analysis={data.failure_analysis} /> : null}

          <SectionCard title="Lane comparison" description="Baca ini untuk melihat apakah MID_LONG/MID_SHORT V3 benar-benar lebih bersih daripada baseline V2.">
            <LaneTable rows={laneRows} />
          </SectionCard>

          <SectionCard title="Filter contribution" description="Filter V3 mana yang menghasilkan shadow signal dan bagaimana hasilnya.">
            <FilterTable rows={data?.by_filter || []} />
          </SectionCard>

          <section className="grid gap-4 xl:grid-cols-2">
            <SectionCard title="Open V3 shadow signals" description="Posisi paper-live yang masih aktif. Current R bergerak saat candle futures baru masuk.">
              <SignalTable rows={data?.latest_v3_open_signals || []} empty="Tidak ada V3 shadow signal yang masih open." />
            </SectionCard>
            <SectionCard title="Closed V3 shadow signals" description="Riwayat V3 shadow yang sudah kena TP/SL/BOTH.">
              <SignalTable rows={data?.latest_v3_closed_signals || []} empty="Belum ada V3 shadow signal closed." />
            </SectionCard>
          </section>

          <SectionCard title="Guardrails">
            <div className="grid gap-3 p-4 text-sm md:grid-cols-2 xl:grid-cols-4">
              {(data?.guardrails || []).map((item) => (
                <div className="rounded border border-line bg-field/40 p-3 font-semibold text-slate-700" key={item}>{item}</div>
              ))}
            </div>
          </SectionCard>
        </>
      )}
    </div>
  );
}

function HigherTimeframePanel({ rows }: { rows: V3ShadowForwardLaneRow[] }) {
  const grouped = higherTimeframes.map((timeframe) => {
    const laneRows = rows.filter((row) => row.timeframe === timeframe);
    const v3Count = laneRows.reduce((sum, row) => sum + Number(row.v3_shadow_signal_count || 0), 0);
    const closed = laneRows.reduce((sum, row) => sum + Number(row.v3_shadow_signal.performance.closed_count || 0), 0);
    const tp = laneRows.reduce((sum, row) => sum + Number(row.v3_shadow_signal.performance.tp_count || 0), 0);
    const sl = laneRows.reduce((sum, row) => sum + Number(row.v3_shadow_signal.performance.sl_count || 0), 0);
    const totalR = laneRows.reduce((sum, row) => sum + num(row.v3_shadow_signal.performance.total_r_closed), 0);
    const realisticR = laneRows.reduce((sum, row) => sum + num(row.v3_shadow_signal.performance.realistic_total_r_closed), 0);
    const activeStages = laneRows.filter((row) => Number(row.v3_shadow_signal_count || 0) > 0).map((row) => labelFor(row.stage));
    return { timeframe, laneRows, v3Count, closed, tp, sl, totalR, realisticR, activeStages };
  });

  return (
    <div className="grid gap-3 p-4 lg:grid-cols-3">
      {grouped.map((row) => (
        <div className="rounded border border-line bg-field/40 p-4" key={row.timeframe}>
          <div className="flex items-center justify-between gap-3">
            <div>
              <div className="text-xs font-semibold uppercase text-slate-500">Timeframe</div>
              <div className="text-2xl font-bold text-ink">{row.timeframe}</div>
            </div>
            <StatusBadge value={row.v3Count > 0 ? "HAS_V3_SAMPLE" : "WAITING_SAMPLE"} />
          </div>
          <div className="mt-4 grid gap-2 text-sm">
            <ReadRow label="V3 pass" value={row.v3Count} />
            <ReadRow label="Closed TP/SL" value={`${row.closed} closed, ${row.tp}/${row.sl}`} />
            <ReadRow label="Ideal R" value={`${fmtSigned(row.totalR)}R`} />
            <ReadRow label="Realistic R" value={`${fmtSigned(row.realisticR)}R`} />
            <ReadRow label="Active stage" value={row.activeStages.length ? row.activeStages.join(", ") : "Belum ada V3 pass"} />
          </div>
        </div>
      ))}
    </div>
  );
}

function ReadRow({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="flex justify-between gap-3 border-t border-line pt-2">
      <span className="text-slate-500">{label}</span>
      <span className="text-right font-semibold text-ink">{value}</span>
    </div>
  );
}

function V3AuditPanel({ audit }: { audit: V3ShadowForwardAudit }) {
  return (
    <SectionCard title="V3/V4 decision audit" description="Ringkasan apakah V3 layak dipantau sebagai kandidat kalibrasi berikutnya. Tetap read-only, bukan pengganti rule live.">
      <div className="grid gap-3 p-4 md:grid-cols-2 xl:grid-cols-4">
        <Insight label="Verdict" value={labelFor(audit.executive_verdict)} />
        <Insight label="Readiness" value={labelFor(audit.promotion_readiness)} />
        <Insight label="Stage kandidat" value={`${audit.promising_stage_count} kandidat / ${audit.monitor_stage_count} monitor`} />
        <Insight label="Filter kandidat" value={audit.promising_filter_count} />
      </div>
      <div className="grid gap-4 border-t border-line p-4 xl:grid-cols-[1fr_1fr]">
        <div>
          <h3 className="text-sm font-bold text-ink">Temuan utama</h3>
          <ul className="mt-2 grid gap-2 text-sm text-slate-700">
            {audit.main_findings.map((finding) => (
              <li className="rounded border border-line bg-field/40 p-3" key={finding}>{finding}</li>
            ))}
          </ul>
          <div className="mt-3 rounded border border-line bg-yellow-50 p-3 text-sm font-semibold text-slate-700">
            {audit.next_recommendation}
          </div>
        </div>
        <div>
          <h3 className="text-sm font-bold text-ink">Risk flags</h3>
          <div className="mt-2 grid gap-2 text-sm">
            {audit.risk_flags.length ? audit.risk_flags.map((flag) => (
              <div className="rounded border border-line bg-white p-3" key={`${flag.flag}-${flag.detail}`}>
                <div className="flex flex-wrap items-center gap-2">
                  <StatusBadge value={flag.severity} />
                  <span className="font-semibold">{labelFor(flag.flag)}</span>
                </div>
                <p className="mt-1 text-slate-600">{flag.detail}</p>
              </div>
            )) : <EmptyState title="Tidak ada risk flag utama" />}
          </div>
        </div>
      </div>
      <div className="border-t border-line">
        <h3 className="px-4 pt-4 text-sm font-bold text-ink">Stage/timeframe decision</h3>
        <StageDecisionTable rows={audit.stage_decisions} />
      </div>
      <div className="border-t border-line">
        <h3 className="px-4 pt-4 text-sm font-bold text-ink">Filter decision</h3>
        <FilterDecisionTable rows={audit.filter_decisions} />
      </div>
      <div className="grid gap-3 border-t border-line p-4 text-sm md:grid-cols-3">
        {audit.guardrails.map((item) => (
          <div className="rounded border border-line bg-field/40 p-3 font-semibold text-slate-700" key={item}>{item}</div>
        ))}
      </div>
    </SectionCard>
  );
}

function V3FailurePanel({ analysis }: { analysis: V3FailureAnalysis }) {
  const summary = analysis.summary;
  return (
    <SectionCard title="V3 failure analysis" description="Membedah V3_SHADOW_PASS yang sudah closed: mana yang TP, mana yang SL, dan evidence angka apa yang paling membedakan. Ini dasar riset sebelum ada V4 baru.">
      <div className="grid gap-3 p-4 md:grid-cols-2 xl:grid-cols-6">
        <Insight label="V3 verdict" value={labelFor(analysis.readiness_verdict)} />
        <Insight label="V3 TP / SL" value={`${summary.v3_tp_count} / ${summary.v3_sl_count}`} />
        <Insight label="V3 closed" value={summary.v3_closed_count} />
        <Insight label="Realistic R" value={`${fmtSigned(summary.v3_realistic_total_r_closed)}R`} />
        <Insight label="SL share" value={summary.v3_sl_share_pct == null ? "-" : `${fmtNumber(summary.v3_sl_share_pct)}%`} />
        <Insight label="Retention closed" value={summary.v3_retention_closed_pct == null ? "-" : `${fmtNumber(summary.v3_retention_closed_pct)}%`} />
      </div>
      <div className="border-t border-line p-4">
        <div className="rounded border border-line bg-yellow-50 p-3 text-sm font-semibold text-slate-700">
          {analysis.failure_read}
        </div>
      </div>
      <section className="grid gap-4 border-t border-line p-4 xl:grid-cols-2">
        <div>
          <h3 className="mb-2 text-sm font-bold text-ink">Evidence TP vs SL</h3>
          <V3EvidenceTable rows={analysis.top_evidence_gaps.length ? analysis.top_evidence_gaps : analysis.evidence_tp_vs_sl.slice(0, 12)} />
        </div>
        <div>
          <h3 className="mb-2 text-sm font-bold text-ink">Loss by filter</h3>
          <V3FailureBucketTable rows={analysis.loss_by_filter.slice(0, 12)} label="Filter" />
        </div>
      </section>
      <section className="grid gap-4 border-t border-line p-4 xl:grid-cols-2">
        <div>
          <h3 className="mb-2 text-sm font-bold text-ink">Loss by symbol</h3>
          <V3FailureBucketTable rows={analysis.loss_by_symbol.slice(0, 12)} label="Symbol" />
        </div>
        <div>
          <h3 className="mb-2 text-sm font-bold text-ink">Loss by lane</h3>
          <V3FailureLaneTable rows={analysis.loss_by_lane} />
        </div>
      </section>
      <section className="grid gap-4 border-t border-line p-4 xl:grid-cols-2">
        <div>
          <h3 className="mb-2 text-sm font-bold text-ink">Latest V3 SL</h3>
          <SignalTable rows={analysis.latest_v3_sl_signals.slice(0, 10)} empty="Belum ada V3 SL signal." />
        </div>
        <div>
          <h3 className="mb-2 text-sm font-bold text-ink">Latest V3 TP</h3>
          <SignalTable rows={analysis.latest_v3_tp_signals.slice(0, 10)} empty="Belum ada V3 TP signal." />
        </div>
      </section>
      <div className="grid gap-3 border-t border-line p-4 text-sm md:grid-cols-3">
        {analysis.guardrails.map((item) => (
          <div className="rounded border border-line bg-field/40 p-3 font-semibold text-slate-700" key={item}>{item}</div>
        ))}
      </div>
    </SectionCard>
  );
}

function V3EvidenceTable({ rows }: { rows: V3FailureEvidenceRow[] }) {
  return (
    <TableShell>
      <thead>
        <tr>
          <th>Evidence</th>
          <th>Flag</th>
          <th>Available</th>
          <th>TP median</th>
          <th>SL median</th>
          <th>Delta</th>
          <th>TP/SL sample</th>
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
            <td>{fmtNumber(row.tp_median)}</td>
            <td>{fmtNumber(row.sl_median)}</td>
            <td className={Number(row.delta_tp_minus_sl || 0) >= 0 ? "text-ready" : "text-stale"}>{fmtSigned(row.delta_tp_minus_sl)}</td>
            <td>{row.tp_count} / {row.sl_count}</td>
          </tr>
        ))}
        {!rows.length && <EmptyRow colSpan={7} title="Belum ada evidence gap V3" />}
      </tbody>
    </TableShell>
  );
}

function V3FailureBucketTable({ rows, label }: { rows: V3FailureBucketRow[]; label: string }) {
  return (
    <TableShell>
      <thead>
        <tr>
          <th>{label}</th>
          <th>Read</th>
          <th>Sample</th>
          <th>TP / SL / Open</th>
          <th>Realistic R</th>
          <th>SL share</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr key={`${label}-${row.bucket}`}>
            <td>
              <div className="font-semibold">{row.label}</div>
              {row.expression ? <div className="text-xs text-slate-500">{compactReason(row.expression, 90)}</div> : null}
            </td>
            <td><StatusBadge value={row.read} /></td>
            <td>{row.sample_count}</td>
            <td>{row.tp_count} / {row.sl_count} / {row.open_count}</td>
            <td className={Number(row.realistic_total_r_closed || 0) >= 0 ? "text-ready" : "text-stale"}>{fmtSigned(row.realistic_total_r_closed)}R</td>
            <td>{row.sl_share_pct == null ? "-" : `${fmtNumber(row.sl_share_pct)}%`}</td>
          </tr>
        ))}
        {!rows.length && <EmptyRow colSpan={6} title={`Belum ada ${label.toLowerCase()} row`} />}
      </tbody>
    </TableShell>
  );
}

function V3FailureLaneTable({ rows }: { rows: V3FailureLaneRow[] }) {
  return (
    <TableShell>
      <thead>
        <tr>
          <th>Lane</th>
          <th>Read</th>
          <th>Sample</th>
          <th>TP / SL / Open</th>
          <th>Realistic R</th>
          <th>SL share</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr key={`${row.stage}-${row.timeframe}-failure`}>
            <td>
              <div className="font-semibold">{labelFor(row.stage)}</div>
              <div className="text-xs text-slate-500">{row.timeframe}</div>
            </td>
            <td><StatusBadge value={row.read} /></td>
            <td>{row.sample_count}</td>
            <td>{row.tp_count} / {row.sl_count} / {row.open_count}</td>
            <td className={Number(row.realistic_total_r_closed || 0) >= 0 ? "text-ready" : "text-stale"}>{fmtSigned(row.realistic_total_r_closed)}R</td>
            <td>{row.sl_share_pct == null ? "-" : `${fmtNumber(row.sl_share_pct)}%`}</td>
          </tr>
        ))}
        {!rows.length && <EmptyRow colSpan={6} title="Belum ada lane V3" />}
      </tbody>
    </TableShell>
  );
}

function ForwardSummary({ summary }: { summary?: V3ShadowForwardLaneSummary }) {
  const perf = summary?.performance;
  const drawdown = summary?.drawdown;
  const quality = summary?.quality;
  return (
    <div className="grid gap-3 p-4 text-sm md:grid-cols-3">
      <Insight label="Evaluated" value={perf?.signals_evaluated ?? 0} />
      <Insight label="TP / SL / Open" value={`${perf?.tp_count ?? 0} / ${perf?.sl_count ?? 0} / ${perf?.open_count ?? 0}`} />
      <Insight label="Total R" value={`${fmtSigned(perf?.total_r_closed)}R`} />
      <Insight label="With Open" value={`${fmtSigned(perf?.total_r_with_open)}R`} />
      <Insight label="Winrate" value={perf?.winrate_pct == null ? "-" : `${fmtNumber(perf.winrate_pct)}%`} />
      <Insight label="Avg R" value={`${fmtSigned(perf?.avg_r_closed)}R`} />
      <Insight label="Max DD" value={`${fmtSigned(drawdown?.max_drawdown_r)}R`} />
      <Insight label="Median R" value={`${fmtSigned(quality?.median_r_closed)}R`} />
      <Insight label="Top symbol" value={`${quality?.top_symbol || "-"} ${quality?.top_symbol_share_pct == null ? "" : `(${fmtNumber(quality.top_symbol_share_pct)}%)`}`} />
    </div>
  );
}

function StageDecisionTable({ rows }: { rows: V3ShadowForwardStageDecision[] }) {
  return (
    <TableShell>
      <thead>
        <tr>
          <th>Lane</th>
          <th>Decision</th>
          <th>V3 sample</th>
          <th>Ideal R</th>
          <th>Realistic R</th>
          <th>Avg delta</th>
          <th>DD delta</th>
          <th>Top symbol</th>
          <th>Reason</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr key={`${row.stage}-${row.timeframe}-audit`}>
            <td>
              <div className="font-semibold">{labelFor(row.stage)}</div>
              <div className="text-xs text-slate-500">{row.timeframe}</div>
            </td>
            <td><StatusBadge value={row.decision} /></td>
            <td>{row.v3_signal_count} / closed {row.v3_closed_count}</td>
            <td>{fmtSigned(row.v3_total_r_closed)}R</td>
            <td>{fmtSigned(row.v3_realistic_total_r_closed)}R</td>
            <td>{fmtSigned(row.avg_r_delta_vs_v2)}R</td>
            <td>{fmtSigned(row.max_drawdown_delta_vs_v2)}R</td>
            <td>{row.v3_top_symbol || "-"} {row.v3_top_symbol_share_pct == null ? "" : `(${fmtNumber(row.v3_top_symbol_share_pct)}%)`}</td>
            <td className="max-w-[28rem] text-xs text-slate-600">{row.reason}</td>
          </tr>
        ))}
        {!rows.length && <EmptyRow colSpan={9} title="Belum ada stage decision" />}
      </tbody>
    </TableShell>
  );
}

function FilterDecisionTable({ rows }: { rows: V3ShadowForwardFilterDecision[] }) {
  return (
    <TableShell>
      <thead>
        <tr>
          <th>Filter</th>
          <th>Decision</th>
          <th>Sample</th>
          <th>TP / SL / Open</th>
          <th>Ideal R</th>
          <th>Realistic R</th>
          <th>Avg delta</th>
          <th>SL delta</th>
          <th>Reason</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr key={`${row.filter_id}-decision`}>
            <td>
              <div className="font-semibold">{row.filter_label}</div>
              <div className="text-xs text-slate-500">{compactReason(row.expression || "-", 100)}</div>
            </td>
            <td><StatusBadge value={row.decision} /></td>
            <td>{row.sample_count} / closed {row.closed_count}</td>
            <td>{row.tp_count} / {row.sl_count} / {row.open_count}</td>
            <td>{fmtSigned(row.total_r_closed)}R</td>
            <td>{fmtSigned(row.realistic_total_r_closed)}R</td>
            <td>{fmtSigned(row.avg_r_delta_vs_v2)}R</td>
            <td>{fmtSigned(row.sl_share_delta_vs_v2)}%</td>
            <td className="max-w-[28rem] text-xs text-slate-600">{row.reason}</td>
          </tr>
        ))}
        {!rows.length && <EmptyRow colSpan={9} title="Belum ada filter decision" />}
      </tbody>
    </TableShell>
  );
}

function LaneTable({ rows }: { rows: V3ShadowForwardLaneRow[] }) {
  return (
    <TableShell>
      <thead>
        <tr>
          <th>Lane</th>
          <th>V2 sample</th>
          <th>V2 R</th>
          <th>V2 DD</th>
          <th>V3 sample</th>
          <th>Retain</th>
          <th>V3 R</th>
          <th>V3 DD</th>
          <th>Avg delta</th>
          <th>Win delta</th>
          <th>Read</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr key={`${row.stage}-${row.timeframe}`}>
            <td>
              <div className="font-semibold">{labelFor(row.stage)}</div>
              <div className="text-xs text-slate-500">{row.timeframe}</div>
            </td>
            <td>{row.v2_live.performance.signals_evaluated}</td>
            <td>{fmtSigned(row.v2_live.performance.total_r_closed)}R</td>
            <td>{fmtSigned(row.v2_live.drawdown.max_drawdown_r)}R</td>
            <td>{row.v3_shadow_signal_count}</td>
            <td>{fmtNumber(row.v3_sample_retention_pct)}%</td>
            <td>{fmtSigned(row.v3_shadow_signal.performance.total_r_closed)}R</td>
            <td>{fmtSigned(row.v3_shadow_signal.drawdown.max_drawdown_r)}R</td>
            <td>{fmtSigned(row.avg_r_delta_v3_vs_v2)}R</td>
            <td>{fmtSigned(row.winrate_delta_v3_vs_v2)}%</td>
            <td><StatusBadge value={row.read} /></td>
          </tr>
        ))}
        {!rows.length && <EmptyRow colSpan={11} title="No lane rows" />}
      </tbody>
    </TableShell>
  );
}

function FilterTable({ rows }: { rows: V3ShadowFilterRow[] }) {
  return (
    <TableShell>
      <thead>
        <tr>
          <th>Filter</th>
          <th>Sample</th>
          <th>TP / SL / Open</th>
          <th>Total R</th>
          <th>Avg R</th>
          <th>Winrate</th>
          <th>SL delta</th>
          <th>Verdict</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr key={row.filter_id}>
            <td>
              <div className="font-semibold">{row.label}</div>
              <div className="text-xs text-slate-500">{compactReason(row.expression || "-", 110)}</div>
            </td>
            <td>{row.sample_count}</td>
            <td>{row.tp_count} / {row.sl_count} / {row.open_count}</td>
            <td>{fmtSigned(row.total_r_closed)}R</td>
            <td>{fmtSigned(row.avg_r_closed)}R</td>
            <td>{row.winrate_pct == null ? "-" : `${fmtNumber(row.winrate_pct)}%`}</td>
            <td>{fmtSigned(row.sl_share_delta_vs_v2)}%</td>
            <td><StatusBadge value={row.verdict} /></td>
          </tr>
        ))}
        {!rows.length && <EmptyRow colSpan={8} title="No filter rows" />}
      </tbody>
    </TableShell>
  );
}

function SignalTable({ rows, empty }: { rows: SignalPerformanceItem[]; empty: string }) {
  return (
    <TableShell>
      <thead>
        <tr>
          <th>Time WIB</th>
          <th>Symbol</th>
          <th>TF</th>
          <th>Stage</th>
          <th>Result</th>
          <th>R</th>
          <th>MFE / MAE</th>
          <th>Entry / SL / TP</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((item) => (
          <tr key={item.signal_id}>
            <td>{item.signal_time_wib || fmtTime(item.signal_timestamp)}</td>
            <td className="font-semibold">
              <Link className="text-blue-700 hover:underline" href={`/signals/${encodeURIComponent(item.symbol)}?signal_id=${encodeURIComponent(item.signal_id)}`}>{item.symbol}</Link>
            </td>
            <td>{item.timeframe}</td>
            <td>{labelFor(item.stage)}</td>
            <td><StatusBadge value={item.result_status} /></td>
            <td>{fmtSigned(item.result_status === "OPEN" || item.result_status === "STALE_FORWARD_DATA" ? item.unrealized_r : item.realized_r)}R</td>
            <td>{fmtSigned(item.mfe_r)} / {fmtSigned(item.mae_r)}</td>
            <td className="text-xs">
              <div>Entry {fmtPrice(item.entry)}</div>
              <div>SL {fmtPrice(item.stop_loss)}</div>
              <div>TP {fmtPrice(item.take_profit)}</div>
            </td>
          </tr>
        ))}
        {!rows.length && <EmptyRow colSpan={8} title={empty} />}
      </tbody>
    </TableShell>
  );
}

function TableShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="table-wrap">
      <table className="ops-table text-sm">
        {children}
      </table>
    </div>
  );
}

function EmptyRow({ colSpan, title }: { colSpan: number; title: string }) {
  return (
    <tr>
      <td colSpan={colSpan}><EmptyState title={title} /></td>
    </tr>
  );
}

function Insight({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded border border-line bg-field/40 p-3">
      <div className="text-xs font-semibold uppercase text-slate-500">{label}</div>
      <div className="mt-1 break-words text-lg font-bold text-ink">{value}</div>
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

function num(value?: string | number | null): number {
  const parsed = Number(value ?? 0);
  return Number.isFinite(parsed) ? parsed : 0;
}

function fmtSigned(value?: string | number | null): string {
  if (value === null || value === undefined || value === "") return "-";
  const num = Number(value);
  if (!Number.isFinite(num)) return String(value);
  return `${num >= 0 ? "+" : ""}${new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 }).format(num)}`;
}
