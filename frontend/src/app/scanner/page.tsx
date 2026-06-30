import { Metric } from "@/components/Metric";
import { StatusBadge } from "@/components/StatusBadge";
import { LiveScannerResponse, fetchJson, fmtTime } from "@/lib/api";

type ScannerSearchParams = Promise<Record<string, string | string[] | undefined>>;

const tierOptions = [
  "WATCHLIST_CONTEXT",
  "RADAR_ONLY",
  "RISK_CONTEXT",
  "BASELINE_CONTEXT",
  "BLOCKED"
];

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
  const limit = normalizeLimit(firstParam(params.limit));
  const apiPath = scannerApiPath({ tier, candidateType, includeBlocked, includeInactive, limit });

  let data: LiveScannerResponse | null = null;
  let error: string | null = null;
  try {
    data = await fetchJson<LiveScannerResponse>(apiPath);
  } catch (err) {
    error = err instanceof Error ? err.message : "Scanner API failed";
  }

  const tierCounts = data?.tier_counts || {};

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold tracking-normal">Live Candidate Scanner</h1>
          <div className="mt-2 inline-flex rounded border border-blue-700 bg-blue-50 px-3 py-1 text-xs font-bold text-blue-700">
            READ-ONLY / NOT ENTRY SIGNAL
          </div>
        </div>
      </div>

      <form className="grid gap-3 border border-line bg-white p-4 md:grid-cols-[1fr_1fr_120px_150px_150px_auto]" method="get">
        <label className="grid gap-1 text-sm">
          <span className="font-semibold text-slate-600">Tier</span>
          <select className="border border-line bg-white px-3 py-2" name="tier" defaultValue={tier || ""}>
            <option value="">All tiers</option>
            {tierOptions.map((option) => (
              <option key={option} value={option}>{option}</option>
            ))}
          </select>
        </label>
        <label className="grid gap-1 text-sm">
          <span className="font-semibold text-slate-600">Candidate Type</span>
          <select className="border border-line bg-white px-3 py-2" name="candidate_type" defaultValue={candidateType || ""}>
            <option value="">All types</option>
            {candidateTypeOptions.map((option) => (
              <option key={option} value={option}>{option}</option>
            ))}
          </select>
        </label>
        <label className="grid gap-1 text-sm">
          <span className="font-semibold text-slate-600">Limit</span>
          <input className="border border-line px-3 py-2" min={1} max={500} name="limit" type="number" defaultValue={limit} />
        </label>
        <label className="flex items-end gap-2 pb-2 text-sm font-semibold text-slate-600">
          <input name="include_blocked" type="checkbox" value="true" defaultChecked={includeBlocked} />
          Include blocked
        </label>
        <label className="flex items-end gap-2 pb-2 text-sm font-semibold text-slate-600">
          <input name="include_inactive" type="checkbox" value="true" defaultChecked={includeInactive} />
          Include inactive
        </label>
        <div className="flex items-end">
          <button className="border border-line px-4 py-2 text-sm font-semibold hover:bg-field" type="submit">
            Apply
          </button>
        </div>
      </form>

      {error ? (
        <div className="border border-stale bg-red-50 p-4 text-sm text-stale">
          {error}
        </div>
      ) : (
        <>
          <section className="grid gap-3 md:grid-cols-5">
            <Metric label="Rows" value={data?.count ?? 0} />
            <Metric label="Watchlist" value={tierCounts.WATCHLIST_CONTEXT || 0} />
            <Metric label="Radar" value={tierCounts.RADAR_ONLY || 0} />
            <Metric label="Risk Context" value={tierCounts.RISK_CONTEXT || 0} />
            <Metric label="Baseline" value={tierCounts.BASELINE_CONTEXT || 0} />
          </section>

          <div className="overflow-x-auto border border-line bg-white">
            <table>
              <thead>
                <tr>
                  <th>Symbol</th>
                  <th>Active</th>
                  <th>Universe Tier</th>
                  <th>Tier</th>
                  <th>Candidate Type</th>
                  <th>Direction</th>
                  <th>Confidence</th>
                  <th>Reason</th>
                  <th>Warning</th>
                  <th>Latest Outcome Status</th>
                  <th>Updated At</th>
                  <th>Read Only</th>
                </tr>
              </thead>
              <tbody>
                {data?.items.map((item) => (
                  <tr key={`${item.symbol}-${item.window_open_time}`}>
                    <td className="font-semibold">{item.symbol}</td>
                    <td><StatusBadge value={item.is_active ? "ACTIVE" : "NOT_ACTIVE"} /></td>
                    <td>
                      <div className="space-y-1">
                        <StatusBadge value={item.collection_tier} />
                        <div className="text-xs text-slate-500">Rank {item.universe_rank ?? "-"}</div>
                      </div>
                    </td>
                    <td><StatusBadge value={item.scanner_tier} /></td>
                    <td>{item.candidate_type}</td>
                    <td><StatusBadge value={item.candidate_direction} /></td>
                    <td>{item.confidence}{item.confidence_score ? ` (${item.confidence_score})` : ""}</td>
                    <td className="min-w-64">
                      <div>{item.tier_reason}</div>
                      {item.using_fallback_usable_row && (
                        <div className="mt-1 inline-flex rounded border border-amber-600 bg-amber-50 px-2 py-1 text-xs font-bold text-amber-700">
                          Previous usable context
                        </div>
                      )}
                      <div className="mt-1 text-xs text-slate-500">{item.scanner_visibility_reason}</div>
                      {item.latest_actual_status && (
                        <div className="mt-1 text-xs text-slate-500">
                          Latest actual: {item.latest_actual_status} at {fmtTime(item.latest_actual_observation_timestamp)}
                        </div>
                      )}
                    </td>
                    <td className="min-w-64">
                      <div>{item.warning_reason || "No scanner warning"}</div>
                      {item.fallback_reason && <div className="mt-1 text-xs font-semibold text-amber-700">{item.fallback_reason}</div>}
                      {item.inactive_warning && <div className="mt-1 text-xs font-semibold text-stale">{item.inactive_warning}</div>}
                    </td>
                    <td><StatusBadge value={item.latest_outcome_status} /></td>
                    <td>{fmtTime(item.latest_outcome_update || item.observation_time)}</td>
                    <td>
                      <span className="inline-flex min-w-32 justify-center rounded border border-blue-700 bg-blue-50 px-2 py-1 text-xs font-bold text-blue-700">
                        {item.not_entry_signal ? "READ-ONLY / NOT ENTRY SIGNAL" : "READ-ONLY"}
                      </span>
                    </td>
                  </tr>
                ))}
                {!data?.items.length && (
                  <tr>
                    <td colSpan={12}>No scanner rows match the selected filters.</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}

function firstParam(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

function normalizeLimit(value: string | undefined): number {
  const parsed = Number(value || 100);
  if (!Number.isFinite(parsed)) return 100;
  return Math.min(Math.max(Math.trunc(parsed), 1), 500);
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
