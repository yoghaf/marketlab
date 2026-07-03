import Link from "next/link";

import { EmptyState } from "@/components/EmptyState";
import { FilterBar, SelectFilter } from "@/components/FilterBar";
import { MetricCard } from "@/components/MetricCard";
import { PageHeader } from "@/components/PageHeader";
import { SectionCard } from "@/components/SectionCard";
import { StatusBadge } from "@/components/StatusBadge";
import { LiveScannerItem, LiveScannerResponse, fetchJson, fmtNumber, fmtTime } from "@/lib/api";
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
  const tier = firstParam(params.tier);
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

  return (
    <div className="space-y-5">
      <PageHeader
        title="Radar Market"
        badge="READ-ONLY - bukan auto execution"
        subtitle="Alur baca: Radar -> Candidate -> Signal Candidate. Semuanya read-only, tidak ada order otomatis."
      />
      <div className="flex flex-wrap gap-2 text-sm">
        <Link className="rounded border border-line bg-white px-3 py-2 font-semibold hover:bg-field" href="/scanner">Radar Market</Link>
        <Link className="rounded border border-line bg-white px-3 py-2 font-semibold hover:bg-field" href="/signal-factory">Signal Factory</Link>
      </div>

      <section className="grid gap-3 md:grid-cols-4">
        <MetricCard label="Signal Candidate" value={tierCounts.SIGNAL_CANDIDATE || 0} helper="Final read-only" tone="good" />
        <MetricCard label="Candidate" value={tierCounts.WATCHLIST_CONTEXT || 0} helper="Perlu dipantau, belum final" tone="info" />
        <MetricCard label="Risk Context" value={tierCounts.RISK_CONTEXT || 0} helper="Ada risiko/campuran" tone="warn" />
        <MetricCard label="Radar" value={tierCounts.RADAR_ONLY || 0} helper="Aktivitas awal" />
      </section>

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

      {error ? (
        <div className="rounded border border-stale bg-red-50 p-4 text-sm text-stale">{error}</div>
      ) : (
        <SectionCard title="Radar table" description="Default: active universe, non-blocked, dan baseline/control disembunyikan.">
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Symbol</th>
                  <th>Status</th>
                  <th>Setup</th>
                  <th>Arah</th>
                  <th>Confidence</th>
                  <th>Entry/Risk</th>
                  <th>Quality</th>
                  <th>Alasan</th>
                  <th>Update</th>
                  <th>Detail</th>
                </tr>
              </thead>
              <tbody>
                {visibleItems.map((item) => <ScannerRow key={`${item.symbol}-${item.window_open_time}-${item.scanner_tier}`} item={item} />)}
                {!visibleItems.length && (
                  <tr>
                    <td colSpan={10}>
                      <EmptyState title="Belum ada radar yang lolos" detail="Data 4h/24h belum cukup dan edge masih lemah." />
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
      <td><StatusBadge value={item.scanner_tier} /></td>
      <td className="max-w-56">{labelFor(item.candidate_type)}</td>
      <td><StatusBadge value={item.candidate_direction} /></td>
      <td>{labelFor(item.confidence)}</td>
      <td className="min-w-56">
        {item.signal_status === "SIGNAL_CANDIDATE" ? (
          <div className="space-y-1 text-xs">
            <div className="font-semibold">Futures: {fmtNumber(item.entry_price)}</div>
            <div>SL: {fmtNumber(item.stop_loss_reference)}</div>
            <div>TP: {fmtNumber(item.take_profit_reference)}</div>
            <div>RR: {fmtNumber(item.rr)}R / Timeout: {item.timeout_minutes ?? "-"}m</div>
          </div>
        ) : (
          <span className="text-xs text-slate-400">Belum final</span>
        )}
      </td>
      <td>
        {item.quality_score !== null && item.quality_score !== undefined ? (
          <div className="space-y-1 text-xs">
            <StatusBadge value={item.quality_bucket || "QUALITY"} />
            <div className="font-semibold">{item.quality_score}/10</div>
          </div>
        ) : (
          <span className="text-xs text-slate-400">-</span>
        )}
      </td>
      <td className="min-w-72">
        <div>{compactReason(userReason(item))}</div>
        {item.using_fallback_usable_row && (
          <div className="mt-1 inline-flex rounded border border-amber-600 bg-amber-50 px-2 py-1 text-xs font-bold text-amber-700">
            Previous usable context
          </div>
        )}
      </td>
      <td>{fmtTime(item.latest_outcome_update || item.observation_time)}</td>
      <td>
        <details className="text-xs text-slate-500">
          <summary className="cursor-pointer font-semibold">Detail</summary>
          <div className="mt-2 min-w-64 space-y-1">
            <div>Raw type: {item.candidate_type}</div>
            <div>Raw status: {item.classifier_status}</div>
            <div>Raw direction: {item.candidate_direction}</div>
            <div>Signal status: {item.signal_status || "-"}</div>
            <div>Signal reason: {item.signal_reason || "-"}</div>
            <div className="mt-2 rounded border border-line bg-field/40 p-2">
              <div className="mb-1 font-semibold text-ink">Evidence angka</div>
              <div>Price 15m: {fmtSignedPercent(evidenceNumber(item, "price_return", "price_return_pct_15m"))}</div>
              <div>OI change: {fmtSignedPercent(evidenceNumber(item, "oi_change_pct", "oi_change_pct_15m"))}</div>
              <div>OI z-score: {fmtNumber(evidenceNumber(item, "oi_zscore"))}</div>
              <div>Volume vs avg: {fmtRatioX(evidenceNumber(item, "volume_ratio_vs_lookback"))}</div>
              <div>Range vs ATR: {fmtRatioX(evidenceNumber(item, "range_ratio_vs_atr"))}</div>
              <div>Taker buy: {fmtRatioPercent(evidenceNumber(item, "kline_taker_buy_ratio", "futures_taker_buy_ratio_15m"))}</div>
              <div>Taker sell: {fmtRatioPercent(evidenceNumber(item, "kline_taker_sell_ratio"))}</div>
              <div>Close position: {fmtRatioPercent(evidenceNumber(item, "close_position_in_range", "close_position_15m"))}</div>
              <div>1h return: {fmtSignedPercent(evidenceNumber(item, "one_hour_return_pct", "price_return_pct_1h"))}</div>
              <div>Funding percentile: {fmtRatioPercentFromPercent(evidenceNumber(item, "funding_percentile_30d"))}</div>
              <div>Global L/S: {fmtNumber(evidenceNumber(item, "global_long_short_ratio", "global_long_short_ratio_15m"))}</div>
              <div>Top trader position: {fmtNumber(evidenceNumber(item, "top_trader_position_ratio", "top_trader_position_ratio_15m"))}</div>
              <div>Futures spread: {fmtSignedPercent(evidenceNumber(item, "futures_spread_pct"))}</div>
              <div>Core score: {fmtNumber(evidenceNumber(item, "core_score"))}/{fmtNumber(evidenceNumber(item, "core_score_max"))}</div>
              <div>Evidence score: {fmtNumber(evidenceNumber(item, "evidence_score"))}</div>
              <div>Evidence completeness: {fmtNumber(evidenceNumber(item, "evidence_data_completeness"))}/4</div>
              <div>Evidence flags: {formatList(item.evidence_summary.evidence_flags)}</div>
              <div>Futures led: {String(item.evidence_summary.futures_led_flag ?? "-")}</div>
              <div>Spot led/support: {String(item.evidence_summary.spot_led_flag ?? item.evidence_summary.spot_support_status_15m ?? "-")}</div>
            </div>
            <div>Entry source: {item.entry_price_source || "-"}</div>
            <div>ATR ref: {item.atr_reference_timeframe || "-"} {fmtNumber(item.atr_reference_value)}</div>
            <div>Position lock: {item.position_lock_mode || "-"}</div>
            <div>Not auto execution: {String(item.not_execution_instruction ?? true)}</div>
            <div>Visibility: {item.scanner_visibility_reason}</div>
            <div>Warning: {item.warning_reason || "No scanner warning"}</div>
            <div>Latest actual: {item.latest_actual_status || "-"} at {fmtTime(item.latest_actual_observation_timestamp)}</div>
            <div>Fallback: {item.fallback_reason || "-"}</div>
            <div>Universe: {item.collection_tier} rank {item.universe_rank ?? "-"}</div>
          </div>
        </details>
      </td>
    </tr>
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

function fmtRatioX(value: number | null): string {
  if (value === null) return "-";
  return `${new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 }).format(value)}x`;
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
