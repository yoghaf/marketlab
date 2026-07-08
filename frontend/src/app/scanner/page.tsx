import Link from "next/link";

import { AutoRefresh } from "@/components/AutoRefresh";
import { EmptyState } from "@/components/EmptyState";
import { FilterBar, SelectFilter } from "@/components/FilterBar";
import { MetricCard } from "@/components/MetricCard";
import { PageHeader } from "@/components/PageHeader";
import { SectionCard } from "@/components/SectionCard";
import { StatusBadge } from "@/components/StatusBadge";
import { LiveScannerItem, LiveScannerResponse, fetchJson, fmtNumber, fmtPrice, fmtTime } from "@/lib/api";
import { compactReason, labelFor } from "@/lib/labels";

type ScannerSearchParams = Promise<Record<string, string | string[] | undefined>>;

const tierOptions = ["SIGNAL_CANDIDATE", "WATCHLIST_CONTEXT", "RADAR_ONLY", "RISK_CONTEXT", "BASELINE_CONTEXT", "BLOCKED"];
const candidateTypeOptions = [
  "MID_SHORT_CONTEXT_READONLY",
  "MID_LONG_CONTEXT_READONLY",
  "EARLY_LONG_CANDIDATE_READONLY",
  "EARLY_SHORT_CANDIDATE_READONLY",
  "SQUEEZE_RISK_CONTEXT_READONLY",
  "TRAP_RISK_CONTEXT_READONLY",
  "NO_SIGNAL_CONTEXT",
  "DATA_BLOCKED"
];

export default async function ScannerPage({ searchParams }: { searchParams: ScannerSearchParams }) {
  const params = await searchParams;
  const tier = firstParam(params.tier) || "SIGNAL_CANDIDATE";
  const candidateType = firstParam(params.candidate_type);
  const includeBlocked = firstParam(params.include_blocked) === "true";
  const includeInactive = firstParam(params.include_inactive) === "true";
  const showBaseline = firstParam(params.show_baseline) === "true";
  const limit = normalizeLimit(firstParam(params.limit));
  const apiPath = scannerApiPath({ tier, candidateType, includeBlocked, includeInactive, limit });

  let data: LiveScannerResponse | null = null;
  let error: string | null = null;
  try {
    data = await fetchJson<LiveScannerResponse>(apiPath);
  } catch (err) {
    error = err instanceof Error ? err.message : "Scanner API failed";
  }

  const visibleItems = (data?.items || []).filter((item) => showBaseline || (item.scanner_tier !== "BASELINE_CONTEXT" && item.candidate_type !== "NO_SIGNAL_CONTEXT"));
  const tierCounts = countTiers(visibleItems);
  const latestTime = latestScannerTime(visibleItems);

  return (
    <div className="space-y-5">
      <AutoRefresh intervalSeconds={30} />
      <PageHeader
        title="Live Radar"
        badge="CURRENT SNAPSHOT - READ ONLY"
        subtitle="Snapshot terbaru per symbol. Halaman ini menjawab: token apa yang sedang masuk Radar, Candidate, atau Signal sekarang."
        updatedAt={fmtTime(latestTime)}
      />

      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-5">
        <MetricCard label="Signal" value={tierCounts.SIGNAL_CANDIDATE || 0} helper="Final read-only" tone={(tierCounts.SIGNAL_CANDIDATE || 0) > 0 ? "good" : "warn"} />
        <MetricCard label="Candidate" value={tierCounts.WATCHLIST_CONTEXT || 0} helper="Pantau konteks" tone="info" />
        <MetricCard label="Radar" value={tierCounts.RADAR_ONLY || 0} helper="Aktivitas awal" />
        <MetricCard label="Risk Context" value={tierCounts.RISK_CONTEXT || 0} helper="Campuran/risiko" tone="warn" />
        <MetricCard label="Rows" value={visibleItems.length} helper={tier === "SIGNAL_CANDIDATE" ? "Signal only" : "Sesuai filter aktif"} />
      </div>

      <SectionCard
        title="Fungsi halaman Radar"
        description="Radar bukan halaman performance. Ini hanya menampilkan kondisi terakhir dari scanner supaya mudah memilih token yang perlu dibaca."
        actions={<Link className="rounded border border-line px-3 py-2 text-sm font-semibold hover:bg-field" href="/signal-performance">Open Signal History</Link>}
      >
        <div className="grid gap-4 p-4 md:grid-cols-3">
          <div>
            <div className="text-sm font-semibold text-ink">Radar</div>
            <p className="mt-1 text-sm text-slate-600">Aktivitas awal atau konteks yang perlu dipantau, belum final sebagai Signal.</p>
          </div>
          <div>
            <div className="text-sm font-semibold text-ink">Candidate</div>
            <p className="mt-1 text-sm text-slate-600">Konteks lebih kuat dari radar, tetapi masih perlu validasi evidence, risk, atau conflict.</p>
          </div>
          <div>
            <div className="text-sm font-semibold text-ink">Signal</div>
            <p className="mt-1 text-sm text-slate-600">Final read-only signal yang punya entry futures reference, SL, TP, RR, dan alasan numerik.</p>
          </div>
        </div>
      </SectionCard>

      <SectionCard title="Scanner controls" description="Default sekarang Signal only. Filter lain hanya untuk audit, bukan fokus monitoring.">
        <div className="space-y-4 p-4">
          <div className="flex flex-wrap gap-2 text-sm">
            <QuickLink href="/scanner?tier=SIGNAL_CANDIDATE&limit=75" label="Signal" active={tier === "SIGNAL_CANDIDATE"} />
            <QuickLink href="/scanner?tier=WATCHLIST_CONTEXT&limit=75" label="Candidate" active={tier === "WATCHLIST_CONTEXT"} />
            <QuickLink href="/scanner?tier=RADAR_ONLY&limit=75" label="Radar" active={tier === "RADAR_ONLY"} />
            <QuickLink href="/scanner?tier=RISK_CONTEXT&limit=75" label="Risk Context" active={tier === "RISK_CONTEXT"} />
            <QuickLink href="/signal-factory" label="Signal Factory raw" />
          </div>

          <FilterBar>
            <SelectFilter label="Tier" name="tier" value={tier || ""} options={tierOptions} emptyLabel="All tiers" />
            <SelectFilter label="Candidate Type" name="candidate_type" value={candidateType || ""} options={candidateTypeOptions} emptyLabel="All types" />
            <label className="grid gap-1 text-sm">
              <span className="font-semibold text-slate-600">Limit</span>
              <input className="rounded border border-line px-3 py-2" min={1} max={200} name="limit" type="number" defaultValue={limit} />
            </label>
            <label className="flex items-end gap-2 pb-2 text-sm font-semibold text-slate-600">
              <input name="include_blocked" type="checkbox" value="true" defaultChecked={includeBlocked} />
              Include blocked
            </label>
            <label className="flex items-end gap-2 pb-2 text-sm font-semibold text-slate-600">
              <input name="include_inactive" type="checkbox" value="true" defaultChecked={includeInactive} />
              Include inactive
            </label>
            <label className="flex items-end gap-2 pb-2 text-sm font-semibold text-slate-600">
              <input name="show_baseline" type="checkbox" value="true" defaultChecked={showBaseline} />
              Show baseline/control rows
            </label>
          </FilterBar>
        </div>
      </SectionCard>

      {error ? (
        <div className="rounded border border-stale bg-red-50 p-4 text-sm text-stale">{error}</div>
      ) : (
        <SectionCard title="Scanner table" description="Klik Detail untuk membuka halaman signal lengkap: posisi aktif, current R, evidence, entry, SL, dan TP.">
          <div className="table-wrap">
            <table className="ops-table scanner-table">
              <thead>
                <tr>
                  <th>Symbol</th>
                  <th>TF</th>
                  <th>Tier</th>
                  <th>Label</th>
                  <th>Arah</th>
                  <th>Confidence</th>
                  <th>Evidence singkat</th>
                  <th>Risk ref</th>
                  <th>Read-only</th>
                  <th>Update WIB</th>
                  <th>Detail</th>
                </tr>
              </thead>
              <tbody>
                {visibleItems.map((item) => <ScannerRow key={`${item.symbol}-${item.window_open_time}-${item.scanner_tier}`} item={item} />)}
                {!visibleItems.length && (
                  <tr>
                    <td colSpan={11}>
                      <EmptyState title="Belum ada row sesuai filter" detail="Cek filter Candidate/Radar/Risk untuk konteks non-final, atau buka Signal History untuk arsip hasil signal lama." />
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </SectionCard>
      )}
    </div>
  );
}

function ScannerRow({ item }: { item: LiveScannerItem }) {
  return (
    <tr>
      <td className="font-semibold">
        <Link className="text-blue-700 hover:underline" href={`/tokens/${item.symbol}`}>{item.symbol}</Link>
        {!item.is_active && <div className="mt-1"><StatusBadge value="NOT_ACTIVE" /></div>}
      </td>
      <td><StatusBadge value={item.timeframe || String(item.evidence_summary.timeframe || "15m")} /></td>
      <td><StatusBadge value={item.scanner_tier} /></td>
      <td className="max-w-56">{labelFor(item.candidate_type)}</td>
      <td><StatusBadge value={item.candidate_direction} /></td>
      <td>{labelFor(item.confidence)}</td>
      <td className="min-w-72 text-xs leading-5 text-slate-600">
        <EvidenceStrip item={item} />
        <div className="mt-1">{compactReason(userReason(item), 130)}</div>
        {item.using_fallback_usable_row && (
          <div className="mt-1 inline-flex rounded border border-amber-600 bg-amber-50 px-2 py-1 text-xs font-bold text-amber-700">
            Previous usable context
          </div>
        )}
      </td>
      <td className="min-w-48">
        {item.signal_status === "SIGNAL_CANDIDATE" ? (
          <div className="space-y-1 text-xs">
            <div className="font-semibold">Futures: {fmtPrice(item.entry_price)}</div>
            <div>SL: {fmtPrice(item.stop_loss_reference)}</div>
            <div>TP: {fmtPrice(item.take_profit_reference)}</div>
            <div>RR: {fmtNumber(item.rr)}R / Timeout: {item.timeout_minutes ?? "-"}m</div>
          </div>
        ) : (
          <span className="text-xs text-slate-400">Belum final</span>
        )}
      </td>
      <td>
        <div className="space-y-1 text-xs">
          <StatusBadge value={item.not_entry_signal ? "READ_ONLY" : "INFO"} />
          <div className="font-semibold text-slate-600">NOT ENTRY SIGNAL</div>
          {item.quality_score !== null && item.quality_score !== undefined && (
            <div>Quality {item.quality_score}/10 {item.quality_bucket || ""}</div>
          )}
        </div>
      </td>
      <td>{fmtTime(item.latest_outcome_update || item.observation_time)}</td>
      <td>
        <Link
          className="rounded border border-line px-3 py-2 text-xs font-semibold hover:bg-field"
          href={`/signals/${encodeURIComponent(item.symbol)}?timeframe=${encodeURIComponent(String(item.timeframe || item.evidence_summary.timeframe || "15m"))}`}
        >
          Detail
        </Link>
      </td>
    </tr>
  );
}

function EvidenceStrip({ item }: { item: LiveScannerItem }) {
  return (
    <div className="grid min-w-72 grid-cols-2 gap-x-3 gap-y-1">
      <span>Price {fmtSignedPercent(evidenceNumber(item, "price_return", "price_return_pct_15m"))}</span>
      <span>Vol {fmtRatioX(evidenceNumber(item, "volume_ratio_vs_lookback"))}</span>
      <span>Buy {fmtRatioPercent(evidenceNumber(item, "kline_taker_buy_ratio", "futures_taker_buy_ratio_15m"))}</span>
      <span>Sell {fmtRatioPercent(evidenceNumber(item, "kline_taker_sell_ratio"))}</span>
      <span>OI {fmtSignedPercent(evidenceNumber(item, "oi_change_pct", "oi_change_pct_15m"))}</span>
      <span>z {fmtNumber(evidenceNumber(item, "oi_zscore"))}</span>
      <span>Core {fmtNumber(evidenceNumber(item, "core_score"))}/{fmtNumber(evidenceNumber(item, "core_score_max"))}</span>
      <span>Ev {fmtNumber(evidenceNumber(item, "evidence_data_completeness"))}/4</span>
    </div>
  );
}

function DetailPanel({ item }: { item: LiveScannerItem }) {
  return (
    <div className="mt-2 min-w-[32rem] space-y-3">
      <div className="grid gap-2 rounded border border-line bg-field/40 p-3 md:grid-cols-2">
        <DetailItem label="Raw type" value={item.candidate_type} />
        <DetailItem label="Raw status" value={item.classifier_status} />
        <DetailItem label="Raw direction" value={item.candidate_direction} />
        <DetailItem label="Signal status" value={item.signal_status || "-"} />
        <DetailItem label="Signal reason" value={item.signal_reason || "-"} />
        <DetailItem label="Universe" value={`${item.collection_tier} rank ${item.universe_rank ?? "-"}`} />
      </div>

      <div className="rounded border border-line bg-white p-3">
        <div className="mb-2 font-semibold text-ink">Evidence angka</div>
        <div className="grid gap-2 md:grid-cols-2">
          <DetailItem label="Price 15m" value={fmtSignedPercent(evidenceNumber(item, "price_return", "price_return_pct_15m"))} />
          <DetailItem label="Close position" value={fmtRatioPercent(evidenceNumber(item, "close_position_in_range", "close_position_15m"))} />
          <DetailItem label="Volume vs avg" value={fmtRatioX(evidenceNumber(item, "volume_ratio_vs_lookback"))} />
          <DetailItem label="Volume baseline" value={String(item.evidence_summary.timeframe || "15m") === "15m" ? "30 candle terakhir" : "Lookback TF aktif"} />
          <DetailItem label="Taker buy" value={fmtRatioPercent(evidenceNumber(item, "kline_taker_buy_ratio", "futures_taker_buy_ratio_15m"))} />
          <DetailItem label="Taker sell" value={fmtRatioPercent(evidenceNumber(item, "kline_taker_sell_ratio"))} />
          <DetailItem label="OI change" value={fmtSignedPercent(evidenceNumber(item, "oi_change_pct", "oi_change_pct_15m"))} />
          <DetailItem label="OI z-score" value={fmtNumber(evidenceNumber(item, "oi_zscore"))} />
          <DetailItem label="Range vs ATR" value={fmtRatioX(evidenceNumber(item, "range_ratio_vs_atr"))} />
          <DetailItem label="ATR extension" value={fmtRatioX(evidenceNumber(item, "atr_extension_normalized"))} />
          <DetailItem label="Price / ATR" value={fmtRatioX(evidenceNumber(item, "price_atr_multiple"))} />
          <DetailItem label="1h return" value={fmtSignedPercent(evidenceNumber(item, "one_hour_return_pct", "price_return_pct_1h"))} />
          <DetailItem label="Funding rate" value={fmtDecimalRatePercent(evidenceNumber(item, "funding_rate"))} />
          <DetailItem label="Funding percentile" value={fmtRatioPercentFromPercent(evidenceNumber(item, "funding_percentile_30d"))} />
          <DetailItem label="Global L/S" value={fmtNumber(evidenceNumber(item, "global_long_short_ratio", "global_long_short_ratio_15m"))} />
          <DetailItem label="Top position" value={fmtNumber(evidenceNumber(item, "top_trader_position_ratio", "top_trader_position_ratio_15m"))} />
          <DetailItem label="Top account" value={fmtNumber(evidenceNumber(item, "top_trader_account_ratio", "top_trader_account_ratio_15m"))} />
          <DetailItem label="Rich status" value={String(item.evidence_summary.rich_alignment_status ?? "-")} />
          <DetailItem label="Futures spread" value={fmtSignedPercent(evidenceNumber(item, "futures_spread_pct"))} />
          <DetailItem label="Spot spread" value={fmtSignedPercent(evidenceNumber(item, "spot_spread_pct"))} />
        </div>
      </div>

      <div className="grid gap-2 rounded border border-line bg-field/40 p-3 md:grid-cols-2">
        <DetailItem label="Core score" value={`${fmtNumber(evidenceNumber(item, "core_score"))}/${fmtNumber(evidenceNumber(item, "core_score_max"))}`} />
        <DetailItem label="Evidence score" value={fmtNumber(evidenceNumber(item, "evidence_score"))} />
        <DetailItem label="Evidence completeness" value={`${fmtNumber(evidenceNumber(item, "evidence_data_completeness"))}/4`} />
        <DetailItem label="Risk status" value={String(item.evidence_summary.execution_risk_status ?? "-")} />
        <DetailItem label="Core reasons" value={formatList(item.evidence_summary.core_reasons)} wide />
        <DetailItem label="Evidence reasons" value={formatList(item.evidence_summary.evidence_reasons)} wide />
        <DetailItem label="Risk reasons" value={formatList(item.evidence_summary.execution_risk_reasons)} wide />
        <DetailItem label="Evidence flags" value={formatList(item.evidence_summary.evidence_flags)} wide />
      </div>

      <div className="grid gap-2 rounded border border-line bg-white p-3 md:grid-cols-2">
        <DetailItem label="Entry source" value={item.entry_price_source || "-"} />
        <DetailItem label="ATR ref" value={`${item.atr_reference_timeframe || "-"} ${fmtNumber(item.atr_reference_value)}`} />
        <DetailItem label="Position lock" value={item.position_lock_mode || "-"} />
        <DetailItem label="Not auto execution" value={String(item.not_execution_instruction ?? true)} />
        <DetailItem label="Visibility" value={item.scanner_visibility_reason} wide />
        <DetailItem label="Warning" value={item.warning_reason || "No scanner warning"} wide />
        <DetailItem label="Latest actual" value={`${item.latest_actual_status || "-"} at ${fmtTime(item.latest_actual_observation_timestamp)}`} wide />
        <DetailItem label="Fallback" value={item.fallback_reason || "-"} wide />
      </div>
    </div>
  );
}

function DetailItem({ label, value, wide = false }: { label: string; value: string; wide?: boolean }) {
  return (
    <div className={wide ? "md:col-span-2" : ""}>
      <div className="text-[0.68rem] font-semibold uppercase text-slate-500">{label}</div>
      <div className="mt-0.5 break-words text-xs text-ink">{value}</div>
    </div>
  );
}

function QuickLink({ href, label, active = false }: { href: string; label: string; active?: boolean }) {
  return (
    <Link
      href={href}
      className={`rounded border px-3 py-2 font-semibold ${active ? "border-blue-700 bg-blue-50 text-blue-700" : "border-line bg-white text-ink hover:bg-field"}`}
    >
      {label}
    </Link>
  );
}

function userReason(item: LiveScannerItem): string {
  const text = `${item.tier_reason || ""} ${item.warning_reason || ""} ${item.scanner_visibility_reason || ""}`.toLowerCase();
  if (item.scanner_tier === "RISK_CONTEXT") return "Konteks risiko, belum layak entry";
  if (item.scanner_tier === "BASELINE_CONTEXT" || item.candidate_type === "NO_SIGNAL_CONTEXT") return "Baseline pembanding, bukan setup";
  if (item.scanner_tier === "BLOCKED" || item.classifier_status.includes("BLOCKED")) return "Data belum cukup";
  if (text.includes("partial")) return "Data belum lengkap";
  if (text.includes("missing atr")) return "ATR belum tersedia";
  if (text.includes("conflict")) return "Sinyal campuran";
  return item.warning_reason || item.tier_reason || "No scanner warning";
}

function countTiers(items: LiveScannerItem[]): Record<string, number> {
  return items.reduce<Record<string, number>>((acc, item) => {
    acc[item.scanner_tier] = (acc[item.scanner_tier] || 0) + 1;
    return acc;
  }, {});
}

function latestScannerTime(items: LiveScannerItem[]): string | null {
  const times = items
    .map((item) => item.latest_outcome_update || item.observation_time || item.window_close_time || item.window_open_time)
    .filter((value): value is string => Boolean(value))
    .sort();
  return times.at(-1) || null;
}

function firstParam(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

function normalizeLimit(value: string | undefined): number {
  const parsed = Number(value || 50);
  if (!Number.isFinite(parsed)) return 50;
  return Math.min(Math.max(Math.trunc(parsed), 1), 200);
}

function evidenceNumber(item: LiveScannerItem, ...keys: string[]): number | null {
  for (const key of keys) {
    const value = item.evidence_summary[key];
    if (typeof value === "number" && Number.isFinite(value)) return value;
    if (typeof value === "string" && value !== "") {
      const parsed = Number(value);
      if (Number.isFinite(parsed)) return parsed;
    }
  }
  return null;
}

function fmtSignedPercent(value: number | null): string {
  if (value === null) return "-";
  const sign = value > 0 ? "+" : "";
  return `${sign}${new Intl.NumberFormat("en-US", { maximumFractionDigits: 3 }).format(value)}%`;
}

function fmtRatioPercent(value: number | null): string {
  if (value === null) return "-";
  return `${new Intl.NumberFormat("en-US", { maximumFractionDigits: 1 }).format(value * 100)}%`;
}

function fmtRatioPercentFromPercent(value: number | null): string {
  if (value === null) return "-";
  return `${new Intl.NumberFormat("en-US", { maximumFractionDigits: 1 }).format(value)}%`;
}

function fmtDecimalRatePercent(value: number | null): string {
  if (value === null) return "-";
  const pct = value * 100;
  const sign = pct > 0 ? "+" : "";
  return `${sign}${new Intl.NumberFormat("en-US", { maximumFractionDigits: 4 }).format(pct)}%`;
}

function fmtRatioX(value: number | null): string {
  if (value === null) return "-";
  return `${new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 }).format(value)}x`;
}

function fmtSigned(value?: string | number | null): string {
  if (value === null || value === undefined || value === "") return "-";
  const num = Number(value);
  if (!Number.isFinite(num)) return String(value);
  return `${num >= 0 ? "+" : ""}${new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 }).format(num)}`;
}

function formatList(value: unknown): string {
  if (Array.isArray(value)) return value.length ? value.join(", ") : "-";
  if (typeof value === "string" && value) return value;
  return "-";
}

function scannerApiPath({
  tier,
  candidateType,
  includeBlocked,
  includeInactive,
  limit
}: {
  tier?: string;
  candidateType?: string;
  includeBlocked: boolean;
  includeInactive: boolean;
  limit: number;
}): string {
  const query = new URLSearchParams({ limit: String(limit) });
  if (tier) query.set("tier", tier);
  if (candidateType) query.set("candidate_type", candidateType);
  if (includeBlocked) query.set("include_blocked", "true");
  if (includeInactive) query.set("include_inactive", "true");
  return `/api/scanner/live?${query.toString()}`;
}
