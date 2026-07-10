import Link from "next/link";

import { AutoRefresh } from "@/components/AutoRefresh";
import { MetricCard } from "@/components/MetricCard";
import { PageHeader } from "@/components/PageHeader";
import { SectionCard } from "@/components/SectionCard";
import { StatusBadge } from "@/components/StatusBadge";
import { SignalDetailResponse, fetchJson, fmtNumber, fmtPrice, fmtTime } from "@/lib/api";
import { labelFor } from "@/lib/labels";

type SignalDetailParams = Promise<{ symbol: string }>;
type SignalDetailSearchParams = Promise<Record<string, string | string[] | undefined>>;

const evidenceRows = [
  ["price_return", "Price return"],
  ["volume_ratio_vs_lookback", "Volume vs avg"],
  ["range_ratio_vs_atr", "Range / ATR"],
  ["atr_extension_normalized", "ATR extension"],
  ["price_atr_multiple", "Price / ATR"],
  ["kline_taker_buy_ratio", "Taker buy"],
  ["kline_taker_sell_ratio", "Taker sell"],
  ["oi_change_pct", "OI change"],
  ["oi_zscore", "OI z-score"],
  ["funding_percentile_30d", "Funding percentile"],
  ["futures_spread_pct", "Futures spread"],
  ["spot_spread_pct", "Spot spread"],
  ["global_long_short_ratio", "Global L/S"],
  ["top_trader_position_ratio", "Top trader position"],
  ["top_trader_account_ratio", "Top trader account"],
  ["core_score", "Core score"],
  ["evidence_score", "Evidence score"],
  ["evidence_data_completeness", "Evidence completeness"]
];

export default async function SignalDetailPage({
  params,
  searchParams
}: {
  params: SignalDetailParams;
  searchParams: SignalDetailSearchParams;
}) {
  const { symbol } = await params;
  const queryParams = await searchParams;
  const timeframe = firstParam(queryParams.timeframe) || "";
  const signalId = firstParam(queryParams.signal_id) || "";
  const query = new URLSearchParams();
  if (signalId) query.set("signal_id", signalId);
  else query.set("symbol", decodeURIComponent(symbol).toUpperCase());
  if (timeframe) query.set("timeframe", timeframe);

  let data: SignalDetailResponse | null = null;
  let error: string | null = null;
  try {
    data = await fetchJson<SignalDetailResponse>(`/api/signals/detail?${query.toString()}`);
  } catch (err) {
    error = err instanceof Error ? err.message : "Signal detail gagal dimuat";
  }

  if (error || !data) {
    return (
      <div className="space-y-5">
        <PageHeader
          title={`${decodeURIComponent(symbol).toUpperCase()} Signal Detail`}
          badge="READ-ONLY"
          subtitle="Detail signal tidak tersedia untuk filter ini."
        />
        <div className="rounded border border-stale bg-red-50 p-4 text-sm text-stale">{error || "Signal not found"}</div>
        <Link className="rounded border border-line bg-white px-3 py-2 text-sm font-semibold hover:bg-field" href="/scanner">Back to Radar</Link>
      </div>
    );
  }

  const item = data.item;
  const snapshot = item.evidence_snapshot || {};
  const rawEvidence = evidenceRoot(data.evidence);
  const rValue = item.result_status === "OPEN" || item.result_status === "STALE_FORWARD_DATA" ? item.unrealized_r : item.realized_r;
  const numericR = Number(rValue ?? 0);
  const isOpen = item.result_status === "OPEN";
  const isStale = item.result_status === "STALE_FORWARD_DATA";
  const isTp = item.result_status === "TP_HIT";
  const isSl = item.result_status === "SL_HIT";
  const resultTone = isStale ? "bad" : isOpen ? (numericR >= 0 ? "good" : "warn") : isTp ? "good" : isSl ? "bad" : "warn";

  return (
    <div className="space-y-5">
      <AutoRefresh intervalSeconds={30} />
      <PageHeader
        title={`${item.symbol} Signal Detail`}
        badge="READ-ONLY - BUKAN EXECUTION"
        subtitle="Halaman ini membaca satu signal futures: entry, SL, TP, status paper-live, current/final R, dan evidence lengkap. Spot/rich hanya evidence; entry tetap futures."
        updatedAt={fmtTime(data.latest_evaluation_candle_time)}
      />

      <div className="flex flex-wrap gap-2 text-sm">
        <Link className="rounded border border-line bg-white px-3 py-2 font-semibold hover:bg-field" href="/scanner">Back to Radar</Link>
        <Link className="rounded border border-line bg-white px-3 py-2 font-semibold hover:bg-field" href="/signal-performance">Open Signal History</Link>
      </div>

      <section className="grid gap-3 md:grid-cols-2 xl:grid-cols-6">
        <MetricCard label="Position state" value={labelFor(item.result_status)} helper={positionText(item.result_status, rValue)} tone={resultTone} />
        <MetricCard label={isOpen || isStale ? "Current R" : "Final R"} value={`${fmtSigned(rValue)}R`} helper={isStale ? item.stale_reason || "Data symbol tertinggal dari market lokal terbaru" : isOpen ? "Masih aktif sampai TP/SL tersentuh" : "Sudah closed"} tone={resultTone} />
        <MetricCard label="Entry futures" value={fmtPrice(item.entry)} helper={fmtTime(item.signal_timestamp)} />
        <MetricCard label="SL reference" value={fmtPrice(item.stop_loss)} helper={`Risk ${fmtPrice(item.risk)}`} tone="bad" />
        <MetricCard label="TP reference" value={fmtPrice(item.take_profit)} helper={`RR ${fmtNumber(item.rr)}R`} tone="good" />
        <MetricCard label={isOpen ? "Latest eval price" : "Result price"} value={fmtPrice(item.exit_price)} helper={fmtTime(item.result_time_utc)} />
      </section>

      <section className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        <MetricCard label="Forward data" value={freshnessLabel(item.result_status)} helper={item.stale_reason || "Candle futures lokal dipakai untuk TP/SL paper-live"} tone={freshnessTone(item.result_status)} />
        <MetricCard label="Latest symbol candle" value={item.latest_symbol_candle_time_wib || fmtTime(item.latest_symbol_candle_time)} helper="Candle terakhir untuk symbol ini" />
        <MetricCard label="Global latest candle" value={fmtTime(item.global_latest_evaluation_candle_time)} helper="Candle terbaru di database futures" tone="info" />
        <MetricCard label="Freshness gap" value={fmtGap(item.freshness_gap_minutes ?? item.stale_gap_minutes)} helper={`Stale jika lebih dari 30 menit`} tone={isStale ? "bad" : "good"} />
      </section>

      <section className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        <MetricCard label="Live strategy" value={shortStrategy(item.strategy_version)} helper="Rule yang menghasilkan signal ini" tone="info" />
        <MetricCard label="Shadow strategy" value="V3 shadow" helper="Calibration candidate, read-only" tone="warn" />
        <MetricCard label="V3 shadow status" value={labelFor(item.v3_shadow_status || "UNKNOWN")} helper={item.v3_shadow_filter_label || item.v3_shadow_reason || "-"} tone={item.v3_shadow_status === "V3_SHADOW_PASS" ? "good" : "warn"} />
        <MetricCard label="V3 filter score" value={item.v3_shadow_promotion_score == null ? "-" : `${item.v3_shadow_promotion_score}/7`} helper={item.v3_shadow_filter_id || "No matched filter"} />
      </section>

      <SectionCard title="Signal plan" description="Informasi inti signal. Semua angka entry/SL/TP memakai futures reference, bukan spot entry.">
        <div className="grid gap-3 p-4 md:grid-cols-2 xl:grid-cols-4">
          <DetailItem label="Signal ID" value={item.signal_id} />
          <DetailItem label="Symbol" value={item.symbol} />
          <DetailItem label="Timeframe" value={item.timeframe} />
          <DetailItem label="Stage" value={labelFor(item.stage)} />
          <DetailItem label="Direction" value={labelFor(item.direction)} />
          <DetailItem label="Confidence" value={labelFor(item.confidence_tier || "-")} />
          <DetailItem label="Candidate status" value={item.candidate_status} />
          <DetailItem label="Execution flag" value={item.execution_flag || "-"} />
          <DetailItem label="Strategy version" value={item.strategy_version || "-"} />
          <DetailItem label="V3 shadow" value={item.v3_shadow_status || "-"} />
          <DetailItem label="Signal time WIB" value={item.signal_time_wib || fmtTime(item.signal_timestamp)} />
          <DetailItem label="Window open" value={fmtTime(data.raw_signal.window_open_time)} />
          <DetailItem label="Window close" value={fmtTime(data.raw_signal.window_close_time)} />
          <DetailItem label="Evaluation candle" value={data.evaluation_candle_interval || "-"} />
          <DetailItem label="Latest symbol candle" value={item.latest_symbol_candle_time_wib || fmtTime(item.latest_symbol_candle_time)} />
          <DetailItem label="Global latest candle" value={fmtTime(item.global_latest_evaluation_candle_time)} />
          <DetailItem label="Stale reason" value={item.stale_reason || "-"} />
        </div>
      </SectionCard>

      <section className="grid gap-4 xl:grid-cols-[1fr_22rem]">
        <SectionCard title="Evidence angka" description="Angka yang dipakai untuk membaca alasan signal. Missing berarti field tidak tersedia di log signal ini.">
          <div className="table-wrap">
            <table className="ops-table">
              <thead>
                <tr>
                  <th>Evidence</th>
                  <th>Value</th>
                  <th>Raw field</th>
                </tr>
              </thead>
              <tbody>
                {evidenceRows.map(([field, label]) => (
                  <tr key={field}>
                    <td className="font-semibold">{label}</td>
                    <td>{formatEvidenceValue(field, snapshot[field])}</td>
                    <td className="text-xs text-slate-500">{field}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </SectionCard>

        <SectionCard title="Position read">
          <div className="space-y-3 p-4 text-sm">
            <div className="rounded border border-line bg-field/40 p-3">
              <div className="text-xs font-semibold uppercase text-slate-500">Current status</div>
              <div className="mt-1 text-lg font-bold">{positionText(item.result_status, rValue)}</div>
            </div>
            <DetailItem label="MFE R" value={`${fmtSigned(item.mfe_r)}R`} />
            <DetailItem label="MAE R" value={`${fmtSigned(item.mae_r)}R`} />
            <DetailItem label="Candles seen" value={String(item.candles_seen ?? "-")} />
            <DetailItem label="Not live signal" value={String(item.not_live_signal)} />
            <DetailItem label="Not execution instruction" value={String(item.not_execution_instruction)} />
          </div>
        </SectionCard>
      </section>

      <SectionCard title="Reasons and raw evidence" description="Bagian ini untuk audit definisi signal. Tidak ada order otomatis dari data ini.">
        <div className="grid gap-4 p-4 xl:grid-cols-2">
          <div className="space-y-3">
            <DetailItem label="Core reasons" value={formatList(rawEvidence.core_reasons)} />
            <DetailItem label="Evidence reasons" value={formatList(rawEvidence.evidence_reasons)} />
            <DetailItem label="Risk reasons" value={formatList(rawEvidence.execution_risk_reasons)} />
            <DetailItem label="Evidence flags" value={formatList(rawEvidence.evidence_flags)} />
            <DetailItem label="Missing data fields" value={formatList(rawEvidence.missing_data_fields)} />
          </div>
          <pre className="max-h-[28rem] overflow-auto rounded border border-line bg-field/40 p-3 text-xs leading-5 text-slate-700">
            {JSON.stringify(data.evidence, null, 2)}
          </pre>
        </div>
      </SectionCard>
    </div>
  );
}

function DetailItem({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-[0.68rem] font-semibold uppercase text-slate-500">{label}</div>
      <div className="mt-0.5 break-words text-sm font-semibold text-ink">{value || "-"}</div>
    </div>
  );
}

function positionText(status: string, rValue?: string | number | null): string {
  if (status === "OPEN") return `Aktif, sedang ${fmtSigned(rValue)}R`;
  if (status === "TP_HIT") return `Closed TP, hasil ${fmtSigned(rValue)}R`;
  if (status === "SL_HIT") return `Closed SL, hasil ${fmtSigned(rValue)}R`;
  if (status === "BOTH_HIT_SAME_CANDLE") return "Closed, TP dan SL satu candle";
  if (status === "WAITING_DATA") return "Menunggu candle futures berikutnya";
  if (status === "STALE_FORWARD_DATA") return `Data stale, R terakhir ${fmtSigned(rValue)}R`;
  return labelFor(status);
}

function freshnessLabel(status: string): string {
  if (status === "STALE_FORWARD_DATA") return "Stale";
  if (status === "WAITING_DATA") return "Waiting data";
  return "Fresh";
}

function freshnessTone(status: string): "neutral" | "good" | "warn" | "bad" | "info" {
  if (status === "STALE_FORWARD_DATA") return "bad";
  if (status === "WAITING_DATA") return "warn";
  return "good";
}

function formatEvidenceValue(field: string, value?: string | number | null): string {
  if (value === null || value === undefined || value === "") return "-";
  if (field.includes("ratio") || field.includes("multiple") || field.includes("extension")) return `${fmtNumber(value)}x`;
  if (field.includes("percentile")) return `${fmtNumber(value)}%`;
  if (field.includes("return") || field.includes("change") || field.includes("spread")) return `${fmtSigned(value)}%`;
  return fmtNumber(value);
}

function fmtSigned(value?: string | number | null): string {
  if (value === null || value === undefined || value === "") return "-";
  const num = Number(value);
  if (!Number.isFinite(num)) return String(value);
  return `${num >= 0 ? "+" : ""}${new Intl.NumberFormat("en-US", { maximumFractionDigits: 3 }).format(num)}`;
}

function fmtGap(value?: string | number | null): string {
  if (value === null || value === undefined || value === "") return "-";
  const num = Number(value);
  if (!Number.isFinite(num)) return String(value);
  if (Math.abs(num) < 1) return "<1m";
  return `${new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 }).format(num)}m`;
}

function shortStrategy(value?: string | null): string {
  if (!value) return "V2_LIVE";
  if (value.includes("V2") || value.includes("v2")) return "V2_LIVE";
  if (value.includes("V3") || value.includes("v3")) return "V3";
  return value.replace("SIGNAL_FACTORY_", "").replace("_LAYERED_SCORING_2026_07", "");
}

function evidenceRoot(value: Record<string, unknown>): Record<string, unknown> {
  const nested = value.evidence;
  if (nested && typeof nested === "object" && !Array.isArray(nested)) return nested as Record<string, unknown>;
  return value;
}

function formatList(value: unknown): string {
  if (Array.isArray(value)) return value.length ? value.map((item) => String(item)).join(", ") : "-";
  if (typeof value === "string" && value) return value;
  return "-";
}

function firstParam(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}
