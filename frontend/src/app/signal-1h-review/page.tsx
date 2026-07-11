import Link from "next/link";

import { EmptyState } from "@/components/EmptyState";
import { MetricCard } from "@/components/MetricCard";
import { PageHeader } from "@/components/PageHeader";
import { SectionCard } from "@/components/SectionCard";
import { StatusBadge } from "@/components/StatusBadge";
import {
  SignalForwardIntegrityResponse,
  OneHourFilterCandidateRow,
  OneHourFilterCandidateStudyResponse,
  OneHourV4ShadowItem,
  OneHourV4ShadowResponse,
  OneHourWalkForwardCandidate,
  OneHourWalkForwardResponse,
  SignalPerformanceBucket,
  SignalPerformanceItem,
  SignalPerformanceResponse,
  fetchJson,
  fmtNumber,
  fmtPrice,
  fmtTime
} from "@/lib/api";
import { labelFor } from "@/lib/labels";

export const dynamic = "force-dynamic";

type GroupRow = {
  key: string;
  count: number;
  tp: number;
  sl: number;
  open: number;
  totalR: number;
  realisticR: number;
  medianR: number | null;
  bestR: number | null;
  worstR: number | null;
  topSymbol?: string;
};

type EvidenceCauseRow = {
  key: string;
  label: string;
  available: number;
  missing: number;
  tpCount: number;
  slCount: number;
  tpMedian: number | null;
  slMedian: number | null;
  delta: number | null;
  formatter: EvidenceFormatter;
};

type EvidenceFormatter = "raw" | "pct" | "ratio" | "score";

const EVIDENCE_FIELDS: { key: string; label: string; formatter: EvidenceFormatter }[] = [
  { key: "price_return", label: "Price return", formatter: "pct" },
  { key: "one_hour_return_pct", label: "1h return", formatter: "pct" },
  { key: "volume_ratio_vs_lookback", label: "Volume vs avg", formatter: "ratio" },
  { key: "range_ratio_vs_atr", label: "Range / ATR", formatter: "ratio" },
  { key: "atr_extension_normalized", label: "ATR extension", formatter: "ratio" },
  { key: "price_atr_multiple", label: "Price / ATR", formatter: "ratio" },
  { key: "kline_taker_buy_ratio", label: "Taker buy", formatter: "pct" },
  { key: "kline_taker_sell_ratio", label: "Taker sell", formatter: "pct" },
  { key: "oi_change_pct", label: "OI change", formatter: "pct" },
  { key: "oi_zscore", label: "OI z-score", formatter: "raw" },
  { key: "funding_percentile_30d", label: "Funding percentile", formatter: "pct" },
  { key: "futures_spread_pct", label: "Futures spread", formatter: "pct" },
  { key: "spot_spread_pct", label: "Spot spread", formatter: "pct" },
  { key: "global_long_short_ratio", label: "Global L/S", formatter: "raw" },
  { key: "top_trader_position_ratio", label: "Top position", formatter: "raw" },
  { key: "top_trader_account_ratio", label: "Top account", formatter: "raw" },
  { key: "core_score", label: "Core score", formatter: "score" },
  { key: "evidence_score", label: "Evidence score", formatter: "score" },
  { key: "evidence_data_completeness", label: "Evidence completeness", formatter: "score" }
];

export default async function Signal1hReviewPage() {
  const performanceQuery = new URLSearchParams({
    include_watch_only: "false",
    position_lock: "true",
    result_status: "closed",
    timeframe: "1h",
    limit: "500"
  });
  const forwardQuery = new URLSearchParams({
    include_watch_only: "false",
    position_lock: "true",
    timeframe: "1h",
    limit: "100"
  });

  let performance: SignalPerformanceResponse | null = null;
  let forward: SignalForwardIntegrityResponse | null = null;
  let filterStudy: OneHourFilterCandidateStudyResponse | null = null;
  let walkForward: OneHourWalkForwardResponse | null = null;
  let v4Shadow: OneHourV4ShadowResponse | null = null;
  let error: string | null = null;
  let filterStudyError: string | null = null;
  let walkForwardError: string | null = null;
  let v4ShadowError: string | null = null;
  try {
    [performance, forward] = await Promise.all([
      fetchJson<SignalPerformanceResponse>(`/api/signal-candidates/performance/live?${performanceQuery.toString()}`, { revalidateSeconds: 20 }),
      fetchJson<SignalForwardIntegrityResponse>(`/api/signals/forward-integrity?${forwardQuery.toString()}`, { revalidateSeconds: 20 })
    ]);
  } catch (err) {
    error = err instanceof Error ? err.message : "1h Signal Review API failed";
  }
  try {
    filterStudy = await fetchJson<OneHourFilterCandidateStudyResponse>("/api/signal-candidates/one-hour-filter-study?min_sample=20&limit=12", { revalidateSeconds: 30 });
  } catch (err) {
    filterStudyError = err instanceof Error ? err.message : "1h filter candidate API failed";
  }
  try {
    walkForward = await fetchJson<OneHourWalkForwardResponse>("/api/signal-candidates/one-hour-walk-forward?min_sample=20&limit=12", { revalidateSeconds: 30 });
  } catch (err) {
    walkForwardError = err instanceof Error ? err.message : "1h walk-forward API failed";
  }
  try {
    v4Shadow = await fetchJson<OneHourV4ShadowResponse>("/api/signal-candidates/one-hour-v4-shadow?min_sample=20&limit=20", { revalidateSeconds: 30 });
  } catch (err) {
    v4ShadowError = err instanceof Error ? err.message : "1h V4 shadow API failed";
  }

  const aggregate = performance?.aggregate;
  const closedItems = performance?.items || [];
  const openItems = forward?.items?.filter((item) => item.result_status === "OPEN") || [];
  const byStage = groupRows(closedItems, (item) => item.stage);
  const bySymbol = groupRows(closedItems, (item) => item.symbol);
  const byDirection = groupRows(closedItems, (item) => item.direction);
  const byStageDirection = groupRows(closedItems, (item) => `${item.stage}|${item.direction}`);
  const topSlSymbols = [...bySymbol].filter((row) => row.sl > 0).sort((a, b) => b.sl - a.sl || a.realisticR - b.realisticR).slice(0, 12);
  const evidenceCauseRows = buildEvidenceCauseRows(closedItems);
  const bestStage = byStage[0];
  const worstStage = [...byStage].sort((a, b) => a.realisticR - b.realisticR)[0];
  const read = buildRead(aggregate, bestStage, worstStage, forward);
  const worstDirection = [...byDirection].sort((a, b) => a.realisticR - b.realisticR)[0];
  const worstStageDirection = [...byStageDirection].sort((a, b) => a.realisticR - b.realisticR)[0];
  const largestEvidenceGap = evidenceCauseRows.find((row) => row.delta !== null);

  return (
    <div className="space-y-5">
      <PageHeader
        title="1h Signal Review"
        badge="READ-ONLY 1H MODE"
        subtitle="Halaman fokus untuk membaca Signal timeframe 1h saja. Tujuannya memisahkan signal yang lebih serius dari noise 15m, tanpa mengubah rule atau execution."
        updatedAt={fmtTime(performance?.snapshot?.generated_at_utc || performance?.generated_at_utc)}
      />

      <div className="flex flex-wrap gap-2 text-sm">
        <Link className="rounded border border-line bg-white px-3 py-2 font-semibold hover:bg-field" href="/scanner?tier=SIGNAL_CANDIDATE">Open Radar</Link>
        <Link className="rounded border border-line bg-white px-3 py-2 font-semibold hover:bg-field" href="/signal-performance">Open Signal History</Link>
        <Link className="rounded border border-line bg-white px-3 py-2 font-semibold hover:bg-field" href="/signal-quality-lab?timeframe=1h">Open Quality Lab 1h</Link>
      </div>

      {error ? (
        <div className="rounded border border-stale bg-red-50 p-4 text-sm text-stale">{error}</div>
      ) : (
        <>
          <section className="grid gap-3 md:grid-cols-2 xl:grid-cols-6">
            <MetricCard label="1h evaluated" value={aggregate?.signals_evaluated ?? 0} helper={`${aggregate?.signals_skipped ?? 0} skipped by lock`} />
            <MetricCard label="Ideal R" value={`${fmtSigned(aggregate?.total_r_closed)}R`} helper="Closed TP/SL/BOTH" tone={Number(aggregate?.total_r_closed || 0) >= 0 ? "good" : "bad"} />
            <MetricCard label="Realistic R" value={`${fmtSigned(aggregate?.realistic_total_r_closed)}R`} helper="Fee + spread + slippage" tone={Number(aggregate?.realistic_total_r_closed || 0) >= 0 ? "good" : "bad"} />
            <MetricCard label="TP / SL" value={`${aggregate?.tp_count ?? 0} / ${aggregate?.sl_count ?? 0}`} helper={`${aggregate?.closed_count ?? 0} closed`} />
            <MetricCard label="Winrate" value={aggregate?.winrate_pct == null ? "-" : `${fmtNumber(aggregate.winrate_pct)}%`} helper="TP / (TP + SL)" tone="info" />
            <MetricCard label="Open 1h" value={forward?.summary?.fresh_open_count ?? 0} helper={`${fmtSigned(sumOpenR(openItems))}R active`} tone="warn" />
          </section>

          <SectionCard title="1h decision read" description="Ini bukan keputusan trading. Ini ringkasan apakah timeframe 1h layak jadi fokus riset utama.">
            <div className="grid gap-3 p-4 md:grid-cols-[1.3fr_1fr_1fr]">
              <div className="rounded border border-line bg-field/50 p-3">
                <div className="text-xs font-semibold uppercase text-slate-500">Verdict sementara</div>
                <div className="mt-2 text-xl font-bold text-ink">{read.verdict}</div>
                <p className="mt-2 text-sm text-slate-600">{read.reason}</p>
              </div>
              <Insight label="Stage paling membantu" value={bestStage ? `${labelFor(bestStage.key)} (${fmtSigned(bestStage.realisticR)}R realistic)` : "-"} />
              <Insight label="Stage paling merusak" value={worstStage ? `${labelFor(worstStage.key)} (${fmtSigned(worstStage.realisticR)}R realistic)` : "-"} />
            </div>
          </SectionCard>

          <SectionCard title="Penyebab TP/SL 1h" description="Membandingkan hasil 1h yang kena target referensi vs stop referensi dari sisi arah, stage, symbol, dan evidence angka. Ini audit kualitas, bukan rule baru.">
            <div className="grid gap-3 border-b border-line p-4 md:grid-cols-4">
              <Insight label="Arah paling lemah" value={worstDirection ? `${labelFor(worstDirection.key)} (${worstDirection.sl} SL, ${fmtSigned(worstDirection.realisticR)}R)` : "-"} />
              <Insight label="Stage + arah terlemah" value={worstStageDirection ? `${formatCauseKey(worstStageDirection.key)} (${fmtSigned(worstStageDirection.realisticR)}R)` : "-"} />
              <Insight label="Evidence gap terbesar" value={largestEvidenceGap ? `${largestEvidenceGap.label}: ${formatEvidenceValue(largestEvidenceGap.delta, largestEvidenceGap.formatter, true)}` : "-"} />
              <Insight label="Symbol SL terbanyak" value={topSlSymbols[0] ? `${topSlSymbols[0].key} (${topSlSymbols[0].sl} SL)` : "-"} />
            </div>
            <section className="grid gap-4 p-4 xl:grid-cols-2">
              <div>
                <h3 className="mb-2 text-sm font-bold text-ink">Long vs Short</h3>
                <CauseGroupTable rows={byDirection} label="Direction" />
              </div>
              <div>
                <h3 className="mb-2 text-sm font-bold text-ink">Stage + arah</h3>
                <CauseGroupTable rows={byStageDirection} label="Stage direction" />
              </div>
            </section>
            <section className="grid gap-4 border-t border-line p-4 xl:grid-cols-[1.5fr_1fr]">
              <div>
                <h3 className="mb-2 text-sm font-bold text-ink">Evidence TP vs SL</h3>
                <EvidenceCauseTable rows={evidenceCauseRows.slice(0, 16)} />
              </div>
              <div>
                <h3 className="mb-2 text-sm font-bold text-ink">Top SL contributors</h3>
                <CauseGroupTable rows={topSlSymbols} label="Symbol" compact />
              </div>
            </section>
          </SectionCard>

          <SectionCard title="1h filter candidate study" description="Filter yang mungkin mengurangi SL 1h atau memperbaiki R. Status di sini hanya riset: belum mengubah rule live dan belum execution.">
            {filterStudyError ? (
              <div className="p-4 text-sm text-stale">{filterStudyError}</div>
            ) : (
              <>
                <div className="grid gap-3 border-b border-line p-4 md:grid-cols-4">
                  <Insight label="Lanes checked" value={`${filterStudy?.lanes.length ?? 0} lane`} />
                  <Insight label="Top candidates" value={`${filterStudy?.top_candidates.length ?? 0} filter`} />
                  <Insight label="Promote shadow" value={`${filterStudy?.top_candidates.filter((row) => row.action === "PROMOTE_TO_SHADOW").length ?? 0} filter`} />
                  <Insight label="Latest candle" value={fmtTime(filterStudy?.latest_futures_15m_close_time)} />
                </div>
                <div className="grid gap-4 p-4 xl:grid-cols-2">
                  {(filterStudy?.lanes || []).map((lane) => (
                    <div key={lane.lane} className="rounded border border-line bg-white">
                      <div className="border-b border-line p-3">
                        <div className="flex flex-wrap items-center gap-2">
                          <h3 className="text-sm font-bold text-ink">{labelFor(lane.stage)} 1h</h3>
                          <StatusBadge value={lane.lane_status} />
                        </div>
                        <p className="mt-1 text-sm text-slate-600">{lane.lane_note}</p>
                      </div>
                      <div className="grid gap-2 p-3 text-sm md:grid-cols-3">
                        <Insight label="Baseline sample" value={String(lane.baseline.sample_count)} />
                        <Insight label="Baseline TP/SL" value={`${lane.baseline.tp_count} / ${lane.baseline.sl_count}`} />
                        <Insight label="Baseline R" value={`${fmtSigned(lane.baseline.total_r_closed)}R`} />
                      </div>
                    </div>
                  ))}
                </div>
                <FilterCandidateTable rows={filterStudy?.top_candidates || []} />
              </>
            )}
          </SectionCard>

          <SectionCard title="Walk-forward optimization 1h" description="Train 70% data lama, validation 30% data terbaru. Filter yang bagus di train tapi gagal di validation dianggap overfit. Ini read-only.">
            {walkForwardError ? (
              <div className="p-4 text-sm text-stale">{walkForwardError}</div>
            ) : (
              <>
                <div className="grid gap-3 border-b border-line p-4 md:grid-cols-4">
                  <Insight label="Source" value={walkForward?.source || "-"} />
                  <Insight label="Promising" value={`${walkForward?.top_candidates.filter((row) => row.verdict === "WF_PROMISING").length ?? 0} filter`} />
                  <Insight label="Damage reduction" value={`${walkForward?.top_candidates.filter((row) => row.verdict === "WF_REDUCES_DAMAGE").length ?? 0} filter`} />
                  <Insight label="Latest candle" value={fmtTime(walkForward?.latest_futures_15m_close_time)} />
                </div>
                <div className="grid gap-4 p-4 xl:grid-cols-2">
                  {(walkForward?.lanes || []).map((lane) => (
                    <div key={lane.lane} className="rounded border border-line bg-white">
                      <div className="border-b border-line p-3">
                        <div className="flex flex-wrap items-center gap-2">
                          <h3 className="text-sm font-bold text-ink">{labelFor(lane.stage)} walk-forward</h3>
                          <StatusBadge value={lane.lane_status} />
                        </div>
                        <p className="mt-1 text-sm text-slate-600">{lane.lane_note}</p>
                      </div>
                      <div className="grid gap-2 p-3 text-sm md:grid-cols-3">
                        <Insight label="Train / validation" value={`${lane.train_count} / ${lane.validation_count}`} />
                        <Insight label="Train realistic R" value={`${fmtSigned(lane.baseline_train.realistic_total_r_closed)}R`} />
                        <Insight label="Validation realistic R" value={`${fmtSigned(lane.baseline_validation.realistic_total_r_closed)}R`} />
                      </div>
                    </div>
                  ))}
                </div>
                <WalkForwardTable rows={walkForward?.top_candidates || []} />
              </>
            )}
          </SectionCard>

          <SectionCard title="V4 shadow forward monitor" description="Menerapkan filter walk-forward 1h sebagai label bayangan V4. Ini hanya audit: rule live, scanner, TP/SL, dan execution tidak berubah.">
            {v4ShadowError ? (
              <div className="p-4 text-sm text-stale">{v4ShadowError}</div>
            ) : (
              <>
                <div className="grid gap-3 border-b border-line p-4 md:grid-cols-5">
                  <Insight label="Source" value={v4Shadow?.source || "-"} />
                  <Insight label="Selected filter" value={`${v4Shadow?.selected_filters.length ?? 0} filter`} />
                  <Insight label="V4 pass" value={`${v4Shadow?.summary?.v4_shadow_pass_count ?? 0} signal`} />
                  <Insight label="Retention" value={v4Shadow?.summary?.sample_retention_pct == null ? "-" : `${fmtNumber(v4Shadow.summary.sample_retention_pct)}%`} />
                  <Insight label="Read" value={labelFor(v4Shadow?.summary?.read || "-")} />
                </div>
                <div className="grid gap-4 p-4 xl:grid-cols-2">
                  {(v4Shadow?.by_stage || []).map((row) => (
                    <div key={row.stage} className="rounded border border-line bg-white">
                      <div className="border-b border-line p-3">
                        <div className="flex flex-wrap items-center gap-2">
                          <h3 className="text-sm font-bold text-ink">{labelFor(row.stage)} V4 shadow</h3>
                          <StatusBadge value={row.read} />
                        </div>
                        <p className="mt-1 text-sm text-slate-600">Pass {row.v4_shadow_pass_count}, fail {row.v4_shadow_fail_count}, unavailable {row.v4_shadow_unavailable_count}.</p>
                      </div>
                      <div className="grid gap-2 p-3 text-sm md:grid-cols-3">
                        <Insight label="Baseline realistic R" value={`${fmtSigned(row.v2_baseline.realistic_total_r_closed)}R`} />
                        <Insight label="V4 pass realistic R" value={`${fmtSigned(row.v4_shadow_pass.realistic_total_r_closed)}R`} />
                        <Insight label="Avg delta" value={`${fmtSigned(row.v4_shadow_pass.realistic_avg_r_delta_vs_baseline)}R`} />
                      </div>
                    </div>
                  ))}
                </div>
                <V4SelectedFiltersTable rows={v4Shadow?.selected_filters || []} />
                <V4ShadowSignalsTable rows={v4Shadow?.latest_v4_pass_signals || []} />
              </>
            )}
          </SectionCard>

          <section className="grid gap-4 xl:grid-cols-2">
            <SectionCard title="1h stage performance" description="MID_LONG dan MID_SHORT 1h dibaca terpisah supaya tidak tercampur noise 15m.">
              <GroupTable rows={byStage} label="Stage" />
            </SectionCard>
            <SectionCard title="1h open integrity" description="Posisi 1h yang masih aktif. Current R valid kalau symbol candle masih fresh.">
              <OpenSignalTable rows={openItems.slice(0, 12)} />
            </SectionCard>
          </section>

          <SectionCard title="1h symbol quality" description="Symbol yang paling membantu atau paling merusak hasil 1h. Gunakan ini untuk mencari token yang noisy.">
            <GroupTable rows={bySymbol.slice(0, 18)} label="Symbol" />
          </SectionCard>

          <SectionCard title="Latest closed 1h signals" description="Arsip signal 1h yang sudah close TP/SL/BOTH. Entry tetap futures; spot/rich hanya evidence.">
            <SignalTable rows={closedItems.slice(0, 30)} />
          </SectionCard>
        </>
      )}
    </div>
  );
}

function buildRead(
  aggregate?: SignalPerformanceBucket,
  bestStage?: GroupRow,
  worstStage?: GroupRow,
  forward?: SignalForwardIntegrityResponse | null
) {
  const realisticR = Number(aggregate?.realistic_total_r_closed || 0);
  const closed = Number(aggregate?.closed_count || 0);
  const stale = Number(forward?.summary?.stale_forward_count || 0);
  if (!closed) {
    return { verdict: "Belum cukup closed 1h", reason: "Belum ada hasil closed 1h sesuai filter default." };
  }
  if (stale > 0) {
    return { verdict: "Cek freshness dulu", reason: `${stale} signal 1h stale. Current R tidak boleh dipercaya penuh sebelum candle fresh.` };
  }
  if (realisticR > 0 && bestStage && (!worstStage || bestStage.realisticR > Math.abs(worstStage.realisticR))) {
    return { verdict: "1h layak jadi fokus riset", reason: "Realistic R 1h positif dan ada stage yang membantu. Tetap perlu filter kualitas, bukan langsung execution." };
  }
  if (realisticR > 0) {
    return { verdict: "1h positif tapi masih campur", reason: "Total realistic R positif, tetapi pemisahan stage belum bersih. Lanjut bedah symbol dan stage." };
  }
  return { verdict: "1h masih perlu filter", reason: "Realistic R 1h belum positif. Fokus berikutnya mencari filter yang mengurangi SL dan drawdown." };
}

function groupRows(items: SignalPerformanceItem[], keyFn: (item: SignalPerformanceItem) => string): GroupRow[] {
  const map = new Map<string, SignalPerformanceItem[]>();
  for (const item of items) {
    const key = keyFn(item) || "UNKNOWN";
    map.set(key, [...(map.get(key) || []), item]);
  }
  return [...map.entries()]
    .map(([key, rows]) => {
      const closedR = rows.map((item) => toNumber(item.realistic_realized_r ?? item.realized_r)).filter((value) => value !== null) as number[];
      const symbols = new Map<string, number>();
      for (const row of rows) symbols.set(row.symbol, (symbols.get(row.symbol) || 0) + 1);
      const topSymbol = [...symbols.entries()].sort((a, b) => b[1] - a[1])[0]?.[0];
      return {
        key,
        count: rows.length,
        tp: rows.filter((item) => item.result_status === "TP_HIT").length,
        sl: rows.filter((item) => item.result_status === "SL_HIT").length,
        open: rows.filter((item) => item.result_status === "OPEN").length,
        totalR: sum(rows.map((item) => toNumber(item.realized_r))),
        realisticR: sum(rows.map((item) => toNumber(item.realistic_realized_r ?? item.realized_r))),
        medianR: median(closedR),
        bestR: closedR.length ? Math.max(...closedR) : null,
        worstR: closedR.length ? Math.min(...closedR) : null,
        topSymbol
      };
    })
    .sort((a, b) => b.realisticR - a.realisticR);
}

function buildEvidenceCauseRows(items: SignalPerformanceItem[]): EvidenceCauseRow[] {
  const tpRows = items.filter((item) => item.result_status === "TP_HIT");
  const slRows = items.filter((item) => item.result_status === "SL_HIT");
  return EVIDENCE_FIELDS.map((field) => {
    const allValues = items.map((item) => evidenceValue(item, field.key));
    const tpValues = tpRows.map((item) => evidenceValue(item, field.key)).filter((value) => value !== null) as number[];
    const slValues = slRows.map((item) => evidenceValue(item, field.key)).filter((value) => value !== null) as number[];
    const tpMedian = median(tpValues);
    const slMedian = median(slValues);
    const delta = tpMedian !== null && slMedian !== null ? tpMedian - slMedian : null;
    const available = allValues.filter((value) => value !== null).length;
    return {
      ...field,
      available,
      missing: items.length - available,
      tpCount: tpValues.length,
      slCount: slValues.length,
      tpMedian,
      slMedian,
      delta
    };
  }).sort((a, b) => {
    const aScore = a.delta === null ? -1 : Math.abs(a.delta);
    const bScore = b.delta === null ? -1 : Math.abs(b.delta);
    return bScore - aScore || b.available - a.available;
  });
}

function evidenceValue(item: SignalPerformanceItem, key: string): number | null {
  const evidence = item.evidence_snapshot || {};
  if (key in evidence) return toNumber(evidence[key]);
  const direct = item[key as keyof SignalPerformanceItem];
  return typeof direct === "string" || typeof direct === "number" || direct === null || direct === undefined ? toNumber(direct) : null;
}

function CauseGroupTable({ rows, label, compact = false }: { rows: GroupRow[]; label: string; compact?: boolean }) {
  return (
    <div className="overflow-hidden rounded border border-line">
      <table className="ops-table">
        <thead>
          <tr>
            <th>{label}</th>
            <th>Rows</th>
            <th>TP / SL</th>
            <th>SL share</th>
            {!compact ? <th>Realistic R</th> : null}
            <th>Median R</th>
            <th>Top Symbol</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const closed = row.tp + row.sl;
            const slShare = closed ? (row.sl / closed) * 100 : null;
            return (
              <tr key={`${label}-${row.key}`}>
                <td className="font-semibold">{label === "Symbol" ? row.key : formatCauseKey(row.key)}</td>
                <td>{row.count}</td>
                <td>{row.tp} / {row.sl}</td>
                <td>{slShare == null ? "-" : `${fmtNumber(slShare)}%`}</td>
                {!compact ? <td className={row.realisticR >= 0 ? "text-ready" : "text-stale"}>{fmtSigned(row.realisticR)}R</td> : null}
                <td>{row.medianR == null ? "-" : `${fmtSigned(row.medianR)}R`}</td>
                <td>{row.topSymbol || "-"}</td>
              </tr>
            );
          })}
          {!rows.length && (
            <tr>
              <td colSpan={compact ? 6 : 7}>
                <EmptyState title="Belum ada sample" detail="Belum ada closed 1h yang cukup untuk breakdown ini." />
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

function EvidenceCauseTable({ rows }: { rows: EvidenceCauseRow[] }) {
  return (
    <div className="overflow-hidden rounded border border-line">
      <table className="ops-table">
        <thead>
          <tr>
            <th>Evidence</th>
            <th>Available</th>
            <th>TP median</th>
            <th>SL median</th>
            <th>Delta TP-SL</th>
            <th>TP/SL samples</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.key}>
              <td>
                <div className="font-semibold">{row.label}</div>
                <div className="text-xs text-slate-500">{row.key}</div>
              </td>
              <td>{row.available} / miss {row.missing}</td>
              <td>{formatEvidenceValue(row.tpMedian, row.formatter)}</td>
              <td>{formatEvidenceValue(row.slMedian, row.formatter)}</td>
              <td className={row.delta == null ? "" : row.delta >= 0 ? "text-ready" : "text-stale"}>{formatEvidenceValue(row.delta, row.formatter, true)}</td>
              <td>{row.tpCount} / {row.slCount}</td>
            </tr>
          ))}
          {!rows.length && (
            <tr>
              <td colSpan={6}>
                <EmptyState title="Evidence belum tersedia" detail="Closed 1h belum punya evidence snapshot yang bisa dibandingkan." />
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

function FilterCandidateTable({ rows }: { rows: OneHourFilterCandidateRow[] }) {
  return (
    <div className="table-wrap border-t border-line">
      <table className="ops-table">
        <thead>
          <tr>
            <th>Lane</th>
            <th>Action</th>
            <th>Filter</th>
            <th>Sample</th>
            <th>TP / SL</th>
            <th>R delta</th>
            <th>SL share delta</th>
            <th>Top symbol</th>
            <th>Reason</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={`${row.stage}-${row.filter_id}`}>
              <td>
                <div className="font-semibold">{labelFor(row.stage)}</div>
                <div className="text-xs text-slate-500">{labelFor(row.direction)} / {row.timeframe}</div>
              </td>
              <td><StatusBadge value={row.action} /></td>
              <td>
                <div className="font-semibold">{row.label}</div>
                <div className="text-xs text-slate-500">{row.expression}</div>
              </td>
              <td>{row.sample_count} / {row.source_count} ({fmtNumber(row.sample_retention_pct)}%)</td>
              <td>{row.tp_count} / {row.sl_count}</td>
              <td className={Number(row.avg_r_delta_vs_baseline || 0) >= 0 ? "text-ready" : "text-stale"}>{fmtSigned(row.avg_r_delta_vs_baseline)}R</td>
              <td className={Number(row.sl_share_delta_vs_baseline || 0) <= 0 ? "text-ready" : "text-stale"}>{fmtSigned(row.sl_share_delta_vs_baseline)}%</td>
              <td>{row.top_symbol} ({fmtNumber(row.top_symbol_share_pct)}%)</td>
              <td className="max-w-md text-sm text-slate-600">
                <div>{row.action_reason}</div>
                {row.risk_notes.length ? <div className="mt-1 text-xs text-stale">{row.risk_notes.join(" ")}</div> : null}
              </td>
            </tr>
          ))}
          {!rows.length && (
            <tr>
              <td colSpan={9}>
                <EmptyState title="Belum ada filter 1h yang layak dipantau" detail="Sample 1h belum cukup atau semua filter masih lebih buruk/noisy dari baseline." />
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

function WalkForwardTable({ rows }: { rows: OneHourWalkForwardCandidate[] }) {
  return (
    <div className="table-wrap border-t border-line">
      <table className="ops-table">
        <thead>
          <tr>
            <th>Lane</th>
            <th>Verdict</th>
            <th>Filter</th>
            <th>Train</th>
            <th>Validation</th>
            <th>Validation delta</th>
            <th>SL share delta</th>
            <th>Score</th>
            <th>Read</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={`${row.stage}-${row.filter_id}`}>
              <td>
                <div className="font-semibold">{labelFor(row.stage)}</div>
                <div className="text-xs text-slate-500">{labelFor(row.direction)} / {row.timeframe}</div>
              </td>
              <td><StatusBadge value={row.verdict} /></td>
              <td>
                <div className="font-semibold">{row.label}</div>
                <div className="text-xs text-slate-500">{row.expression}</div>
              </td>
              <td>
                <div>{row.train.closed_count} closed</div>
                <div className={Number(row.train.realistic_total_r_closed || 0) >= 0 ? "text-ready" : "text-stale"}>{fmtSigned(row.train.realistic_total_r_closed)}R</div>
              </td>
              <td>
                <div>{row.validation.closed_count} closed</div>
                <div className={Number(row.validation.realistic_total_r_closed || 0) >= 0 ? "text-ready" : "text-stale"}>{fmtSigned(row.validation.realistic_total_r_closed)}R</div>
              </td>
              <td className={Number(row.validation.realistic_avg_r_delta_vs_baseline || 0) >= 0 ? "text-ready" : "text-stale"}>{fmtSigned(row.validation.realistic_avg_r_delta_vs_baseline)}R avg</td>
              <td className={Number(row.validation.sl_share_delta_vs_baseline || 0) <= 0 ? "text-ready" : "text-stale"}>{fmtSigned(row.validation.sl_share_delta_vs_baseline)}%</td>
              <td>{row.score}/7</td>
              <td className="max-w-md text-sm text-slate-600">
                <div>{row.note}</div>
                {row.risk_notes.length ? <div className="mt-1 text-xs text-stale">{row.risk_notes.join(" ")}</div> : null}
              </td>
            </tr>
          ))}
          {!rows.length && (
            <tr>
              <td colSpan={9}>
                <EmptyState title="Belum ada walk-forward candidate" detail="Filter 1h belum lolos train/validation atau sample validation belum cukup." />
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

function V4SelectedFiltersTable({ rows }: { rows: OneHourV4ShadowResponse["selected_filters"] }) {
  return (
    <div className="table-wrap border-t border-line">
      <table className="ops-table">
        <thead>
          <tr>
            <th>Lane</th>
            <th>Filter</th>
            <th>WF verdict</th>
            <th>Validation</th>
            <th>Delta</th>
            <th>Risk notes</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={`${row.stage}-${row.filter_id}`}>
              <td>
                <div className="font-semibold">{labelFor(row.stage)}</div>
                <div className="text-xs text-slate-500">{labelFor(row.direction)} / {row.timeframe}</div>
              </td>
              <td>
                <div className="font-semibold">{row.label}</div>
                <div className="text-xs text-slate-500">{row.expression}</div>
              </td>
              <td>
                <StatusBadge value={row.walk_forward_verdict} />
                <div className="mt-1 text-xs text-slate-500">Score {row.walk_forward_score}/7</div>
              </td>
              <td>
                <div>{row.validation.closed_count} closed</div>
                <div className={Number(row.validation.realistic_total_r_closed || 0) >= 0 ? "text-ready" : "text-stale"}>{fmtSigned(row.validation.realistic_total_r_closed)}R</div>
              </td>
              <td>
                <div>Avg {fmtSigned(row.validation.realistic_avg_r_delta_vs_baseline)}R</div>
                <div>SL {fmtSigned(row.validation.sl_share_delta_vs_baseline)}%</div>
              </td>
              <td className="max-w-md text-sm text-slate-600">{row.risk_notes.length ? row.risk_notes.join(" ") : "No major validation warning."}</td>
            </tr>
          ))}
          {!rows.length && (
            <tr>
              <td colSpan={6}>
                <EmptyState title="Belum ada filter V4 shadow" detail="Walk-forward belum memilih filter yang layak dipantau sebagai V4 shadow." />
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

function V4ShadowSignalsTable({ rows }: { rows: OneHourV4ShadowItem[] }) {
  return (
    <div className="table-wrap border-t border-line">
      <table className="ops-table">
        <thead>
          <tr>
            <th>Time WIB</th>
            <th>Symbol</th>
            <th>Stage</th>
            <th>Filter</th>
            <th>Status</th>
            <th>Realistic R</th>
            <th>Entry / SL / TP</th>
            <th>Reason</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((item) => (
            <tr key={item.signal_id}>
              <td>{item.signal_time_wib || fmtTime(item.signal_timestamp)}</td>
              <td className="font-semibold">
                <Link className="text-blue-700 hover:underline" href={`/signals/${encodeURIComponent(item.symbol)}?signal_id=${encodeURIComponent(item.signal_id)}`}>
                  {item.symbol}
                </Link>
              </td>
              <td>{labelFor(item.stage)}</td>
              <td>
                <div className="font-semibold">{item.v4_filter_label || "-"}</div>
                <div className="text-xs text-slate-500">{item.v4_filter_expression || "-"}</div>
              </td>
              <td><StatusBadge value={item.result_status} /></td>
              <td className={Number(item.realistic_realized_r ?? item.realized_r ?? 0) >= 0 ? "text-ready" : "text-stale"}>{fmtSigned(item.realistic_realized_r ?? item.realized_r)}R</td>
              <td className="text-sm">
                <div>Entry {fmtPrice(item.entry)}</div>
                <div>SL {fmtPrice(item.stop_loss)}</div>
                <div>TP {fmtPrice(item.take_profit)}</div>
              </td>
              <td className="max-w-md text-sm text-slate-600">{item.v4_shadow_reason || "-"}</td>
            </tr>
          ))}
          {!rows.length && (
            <tr>
              <td colSpan={8}>
                <EmptyState title="Belum ada signal V4 shadow pass" detail="Filter walk-forward belum cocok ke signal 1h terbaru, atau sample belum cukup." />
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

function formatCauseKey(key: string): string {
  const [stage, direction] = key.split("|");
  if (!direction) return labelFor(key);
  return `${labelFor(stage)} / ${labelFor(direction)}`;
}

function GroupTable({ rows, label }: { rows: GroupRow[]; label: string }) {
  return (
    <div className="overflow-hidden">
      <table className="ops-table">
        <thead>
          <tr>
            <th>{label}</th>
            <th>Rows</th>
            <th>TP / SL</th>
            <th>Winrate</th>
            <th>Realistic R</th>
            <th>Median R</th>
            <th>Best / Worst</th>
            <th>Top Symbol</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.key}>
              <td className="font-semibold">{label === "Stage" ? labelFor(row.key) : row.key}</td>
              <td>{row.count}</td>
              <td>{row.tp} / {row.sl}</td>
              <td>{row.tp + row.sl ? fmtNumber((row.tp / (row.tp + row.sl)) * 100) : "-"}%</td>
              <td className={row.realisticR >= 0 ? "text-ready" : "text-stale"}>{fmtSigned(row.realisticR)}R</td>
              <td>{row.medianR == null ? "-" : `${fmtSigned(row.medianR)}R`}</td>
              <td>{row.bestR == null ? "-" : `${fmtSigned(row.bestR)} / ${fmtSigned(row.worstR)}R`}</td>
              <td>{row.topSymbol || "-"}</td>
            </tr>
          ))}
          {!rows.length && (
            <tr>
              <td colSpan={8}>
                <EmptyState title="Belum ada data 1h" detail="Tunggu signal 1h close bertambah atau cek filter position lock." />
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

function OpenSignalTable({ rows }: { rows: SignalPerformanceItem[] }) {
  return (
    <div className="overflow-hidden">
      <table className="ops-table">
        <thead>
          <tr>
            <th>Time WIB</th>
            <th>Symbol</th>
            <th>Stage</th>
            <th>Dir</th>
            <th>Current R</th>
            <th>Entry / SL / TP</th>
            <th>Fresh</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((item) => (
            <tr key={item.signal_id}>
              <td>{item.signal_time_wib || fmtTime(item.signal_timestamp)}</td>
              <td className="font-semibold">
                <Link className="text-blue-700 hover:underline" href={`/signals/${encodeURIComponent(item.symbol)}?signal_id=${encodeURIComponent(item.signal_id)}`}>
                  {item.symbol}
                </Link>
              </td>
              <td>{labelFor(item.stage)}</td>
              <td><StatusBadge value={item.direction} /></td>
              <td>{fmtSigned(item.realistic_unrealized_r ?? item.unrealized_r)}R</td>
              <td className="text-sm">
                <div>Entry {fmtPrice(item.entry)}</div>
                <div>SL {fmtPrice(item.stop_loss)}</div>
                <div>TP {fmtPrice(item.take_profit)}</div>
              </td>
              <td>{item.stale_forward_data ? <StatusBadge value="STALE" /> : <StatusBadge value="FRESH" />}</td>
            </tr>
          ))}
          {!rows.length && (
            <tr>
              <td colSpan={7}>
                <EmptyState title="Tidak ada open 1h" detail="Semua signal 1h sudah close atau belum ada posisi paper aktif." />
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
    <div className="overflow-hidden">
      <table className="ops-table">
        <thead>
          <tr>
            <th>Time WIB</th>
            <th>Symbol</th>
            <th>Stage</th>
            <th>Dir</th>
            <th>Status</th>
            <th>Entry</th>
            <th>SL</th>
            <th>TP</th>
            <th>Realistic R</th>
            <th>Result WIB</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((item) => (
            <tr key={item.signal_id}>
              <td>{item.signal_time_wib || fmtTime(item.signal_timestamp)}</td>
              <td className="font-semibold">
                <Link className="text-blue-700 hover:underline" href={`/signals/${encodeURIComponent(item.symbol)}?signal_id=${encodeURIComponent(item.signal_id)}`}>
                  {item.symbol}
                </Link>
              </td>
              <td>{labelFor(item.stage)}</td>
              <td><StatusBadge value={item.direction} /></td>
              <td><StatusBadge value={item.result_status} /></td>
              <td>{fmtPrice(item.entry)}</td>
              <td>{fmtPrice(item.stop_loss)}</td>
              <td>{fmtPrice(item.take_profit)}</td>
              <td>{fmtSigned(item.realistic_realized_r ?? item.realized_r)}R</td>
              <td>{item.result_time_wib || fmtTime(item.result_time_utc)}</td>
            </tr>
          ))}
          {!rows.length && (
            <tr>
              <td colSpan={10}>
                <EmptyState title="Belum ada closed 1h" detail="Signal 1h belum punya hasil closed sesuai filter default." />
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

function Insight({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded border border-line bg-white p-3 text-sm">
      <div className="text-xs font-semibold uppercase text-slate-500">{label}</div>
      <div className="mt-1 font-bold text-ink">{value}</div>
    </div>
  );
}

function sumOpenR(items: SignalPerformanceItem[]): number {
  return sum(items.map((item) => toNumber(item.realistic_unrealized_r ?? item.unrealized_r)));
}

function sum(values: (number | null)[]): number {
  return values.reduce<number>((total, value) => total + (value ?? 0), 0);
}

function median(values: number[]): number | null {
  if (!values.length) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const middle = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2;
}

function toNumber(value?: string | number | null): number | null {
  if (value === null || value === undefined || value === "") return null;
  const num = typeof value === "number" ? value : Number(value);
  return Number.isFinite(num) ? num : null;
}

function fmtSigned(value?: string | number | null): string {
  const num = toNumber(value);
  if (num === null) return "-";
  const abs = Math.abs(num);
  const text = abs >= 100 ? num.toFixed(0) : abs >= 10 ? num.toFixed(1) : num.toFixed(2);
  return `${num >= 0 ? "+" : ""}${text}`;
}

function formatEvidenceValue(value: number | null, formatter: EvidenceFormatter, signed = false): string {
  if (value === null) return "-";
  const prefix = signed && value > 0 ? "+" : "";
  if (formatter === "pct") return `${prefix}${fmtNumber(value)}%`;
  if (formatter === "ratio") return `${prefix}${fmtNumber(value)}x`;
  if (formatter === "score") return `${prefix}${fmtNumber(value)}`;
  return `${prefix}${fmtNumber(value)}`;
}
