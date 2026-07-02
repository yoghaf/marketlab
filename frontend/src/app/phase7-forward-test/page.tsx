import { DecisionBanner } from "@/components/DecisionBanner";
import { EmptyState } from "@/components/EmptyState";
import { MetricCard } from "@/components/MetricCard";
import { PageHeader } from "@/components/PageHeader";
import { SectionCard } from "@/components/SectionCard";
import { StatusBadge } from "@/components/StatusBadge";
import {
  Phase7ForwardEvent,
  Phase7ForwardEventsResponse,
  Phase7ForwardResult,
  Phase7ForwardResultsResponse,
  Phase7ForwardStatus,
  Phase7ForwardSummary,
  Phase7LaneSummary,
  fetchJson,
  fmtNumber
} from "@/lib/api";
import { labelFor } from "@/lib/labels";
import { formatLocalDateTime, formatRelativeTime, formatTimeWithUtcDetail } from "@/lib/time";

export default async function Phase7ForwardTestPage() {
  let status: Phase7ForwardStatus | null = null;
  let events: Phase7ForwardEventsResponse | null = null;
  let results: Phase7ForwardResultsResponse | null = null;
  let summary: Phase7ForwardSummary | null = null;
  let error: string | null = null;

  try {
    [status, events, results, summary] = await Promise.all([
      fetchJson<Phase7ForwardStatus>("/api/phase7/status"),
      fetchJson<Phase7ForwardEventsResponse>("/api/phase7/events"),
      fetchJson<Phase7ForwardResultsResponse>("/api/phase7/results"),
      fetchJson<Phase7ForwardSummary>("/api/phase7/summary")
    ]);
  } catch (err) {
    error = err instanceof Error ? err.message : "Phase 7 artifact belum tersedia";
  }

  const allEvents = events?.events || [];
  const allResults = results?.results || [];
  const approvedEvents = allEvents.filter((event) => event.lane === "APPROVED_SHADOW");
  const labEvents = allEvents.filter((event) => event.lane === "LAB_SHADOW");
  const approvedResults = allResults.filter((result) => result.lane === "APPROVED_SHADOW");
  const labResults = allResults.filter((result) => result.lane === "LAB_SHADOW");
  const latestEventTime = latestTime(allEvents.map((event) => event.observation_timestamp_utc || event.observation_timestamp));
  const latestResultTime = latestTime(allResults.map((result) => result.hit_time_utc || result.evaluated_at_utc));
  const lastRun = status?.last_run_at_utc || status?.generated_at_utc || summary?.generated_at_utc || status?.generated_at;
  const isStale = Boolean(status?.is_stale);

  return (
    <div className="space-y-5">
      <PageHeader
        title="Phase 7 Shadow Forward-Test"
        badge="READ-ONLY - bukan sinyal entry live"
        subtitle="Dual-lane shadow tracking: strict approved candidates dan near-miss lab candidates. Tidak ada order, eksekusi, atau instruksi trading."
        updatedAt={timeLine(lastRun)}
      />

      {error ? (
        <div className="rounded border border-stale bg-red-50 p-4 text-sm text-stale">{error}</div>
      ) : (
        <>
          <DecisionBanner
            title={isStale ? "Phase 7 belum diperbarui sesuai jadwal" : status?.mode === "ACTIVE_LAB_SHADOW" ? "Phase 7 Lab Shadow aktif" : status?.mode === "ACTIVE_APPROVED_SHADOW" ? "Phase 7 Approved Shadow aktif" : "Status Phase 7"}
            status={isStale ? "STALE" : status?.mode}
            tone={isStale ? "warn" : status?.mode === "ERROR" ? "bad" : status?.mode === "ACTIVE_APPROVED_SHADOW" ? "good" : status?.mode === "ACTIVE_LAB_SHADOW" ? "info" : "warn"}
            description={
              isStale
                ? "Phase 7 belum diperbarui sesuai jadwal. Data terakhir lebih dari 20 menit lalu."
                : status?.mode === "ACTIVE_LAB_SHADOW"
                ? "Belum ada approved signal, tapi near-miss candidates sedang dikumpulkan untuk forward-test learning. LAB_SHADOW bukan live signal."
                : status?.reason || "Menunggu artifact Phase 7."
            }
          />

          <section className="grid gap-3 md:grid-cols-3 xl:grid-cols-6">
            <MetricCard label="Approved Shadow" value={status?.approved_shadow_event_count ?? 0} helper="Strict Phase 6 gate" tone={(status?.approved_shadow_event_count || 0) > 0 ? "good" : "neutral"} />
            <MetricCard label="Lab Shadow" value={status?.lab_shadow_event_count ?? 0} helper="Near-miss learning only" tone={(status?.lab_shadow_event_count || 0) > 0 ? "info" : "neutral"} />
            <MetricCard label="Active Events" value={status?.active_event_count ?? 0} helper="Menunggu candle forward" tone={status?.active_event_count ? "info" : "neutral"} />
            <MetricCard label="Completed" value={summary?.completed_events ?? 0} helper="Sudah punya outcome" tone="good" />
            <MetricCard label="Last Run" value={formatLocalDateTime(lastRun)} helper={formatRelativeTime(lastRun)} />
            <MetricCard label="Latest Event" value={formatLocalDateTime(latestEventTime)} helper={formatRelativeTime(latestEventTime)} />
          </section>

          <section className="grid gap-3 md:grid-cols-3">
            <MetricCard label="Latest Result" value={formatLocalDateTime(latestResultTime)} helper={formatRelativeTime(latestResultTime)} />
            <MetricCard label="Approved Avg R" value={fmtR(summary?.approved_shadow_summary?.avg_R ?? summary?.approved_shadow_summary?.average_realized_R)} helper="Read-only shadow metric" />
            <MetricCard label="Lab Avg R" value={fmtR(summary?.lab_shadow_summary?.avg_R ?? summary?.lab_shadow_summary?.average_realized_R)} helper="LAB ONLY - bukan sinyal live" tone="info" />
          </section>

          <LaneSection
            title="Approved Shadow"
            subtitle="Kandidat strict yang sudah lolos Phase 6."
            laneBadge="APPROVED_SHADOW"
            events={approvedEvents}
            results={approvedResults}
            summary={summary?.approved_shadow_summary}
          />

          <LaneSection
            title="Lab Shadow"
            subtitle="Near-miss candidates untuk riset forward-test. Bukan live signal."
            laneBadge="LAB_SHADOW"
            events={labEvents}
            results={labResults}
            summary={summary?.lab_shadow_summary}
            labOnly
          />

          <SectionCard title="Read-only rules" description="Halaman ini tidak menjalankan trading dan tidak mengubah rule classifier.">
            <div className="grid gap-3 p-4 text-sm text-slate-700 md:grid-cols-3">
              <div>APPROVED_SHADOW hanya dibuat dari kandidat Phase 6 dengan verdict <strong>PHASE7_READY</strong>.</div>
              <div>LAB_SHADOW hanya near-miss untuk forward-test learning dan tidak dipakai sebagai live signal.</div>
              <div>Semua waktu utama tampil lokal; UTC tetap tersedia di detail teknis.</div>
            </div>
          </SectionCard>
        </>
      )}
    </div>
  );
}

function LaneSection({
  title,
  subtitle,
  laneBadge,
  events,
  results,
  summary,
  labOnly = false
}: {
  title: string;
  subtitle: string;
  laneBadge: string;
  events: Phase7ForwardEvent[];
  results: Phase7ForwardResult[];
  summary?: Phase7LaneSummary;
  labOnly?: boolean;
}) {
  const activeEvents = events.filter((event) => ["WAITING_OUTCOME", "UNKNOWN_FORWARD_DATA"].includes(event.status));
  const completedResults = results.filter((result) => ["TP_HIT", "SL_HIT", "BOTH_HIT_SAME_CANDLE", "EXPIRED", "CANNOT_EVALUATE"].includes(result.result_status));
  return (
    <SectionCard
      title={title}
      description={subtitle}
      actions={
        <div className="flex flex-wrap gap-2">
          <StatusBadge value={laneBadge} />
          {labOnly && <span className="rounded border border-blue-700 bg-blue-50 px-2 py-1 text-xs font-bold text-blue-700">LAB ONLY - bukan sinyal live</span>}
        </div>
      }
    >
      <div className="grid gap-3 border-b border-line p-4 md:grid-cols-5">
        <MiniStat label="Total" value={summary?.total_events ?? events.length} />
        <MiniStat label="Active" value={summary?.active_events ?? activeEvents.length} />
        <MiniStat label="Completed" value={summary?.completed_events ?? completedResults.length} />
        <MiniStat label="TP / SL ref" value={`${summary?.tp_hit ?? 0} / ${summary?.sl_hit ?? 0}`} />
        <MiniStat label="Avg R" value={fmtR(summary?.avg_R ?? summary?.average_realized_R)} />
      </div>
      <div className="space-y-4 p-4">
        <EventTable events={activeEvents} emptyDetail={labOnly ? "Belum ada near-miss lab event aktif." : "Belum ada approved shadow event aktif."} />
        <ResultTable results={completedResults} />
      </div>
    </SectionCard>
  );
}

function EventTable({ events, emptyDetail }: { events: Phase7ForwardEvent[]; emptyDetail: string }) {
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Symbol</th>
            <th>Setup</th>
            <th>Arah</th>
            <th>Status</th>
            <th>Observation Time</th>
            <th>Entry Ref</th>
            <th>Expiry</th>
            <th>Created At</th>
          </tr>
        </thead>
        <tbody>
          {events.map((event) => (
            <tr key={event.event_id}>
              <td className="font-semibold">{event.symbol}</td>
              <td>{labelFor(event.setup)}</td>
              <td><StatusBadge value={event.direction} /></td>
              <td><StatusBadge value={event.status} /></td>
              <td><TimeCell value={event.observation_timestamp_utc || event.observation_timestamp} /></td>
              <td>
                <div>{fmtNumber(event.entry_reference_price)}</div>
                <TimeCell value={event.entry_reference_time_utc || event.entry_reference_time} compact />
              </td>
              <td><TimeCell value={event.expiry_time_utc || event.expiry_time} /></td>
              <td><TimeCell value={event.event_created_at_utc} /></td>
            </tr>
          ))}
          {!events.length && (
            <tr>
              <td colSpan={8}><EmptyState title="Tidak ada active shadow event" detail={emptyDetail} /></td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

function ResultTable({ results }: { results: Phase7ForwardResult[] }) {
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Symbol</th>
            <th>Setup</th>
            <th>Arah</th>
            <th>Result</th>
            <th>Hit Time</th>
            <th>Evaluated At</th>
            <th>Expiry Time</th>
            <th>R / MFE / MAE</th>
          </tr>
        </thead>
        <tbody>
          {results.slice(0, 100).map((result) => (
            <tr key={result.event_id}>
              <td className="font-semibold">{result.symbol}</td>
              <td>{labelFor(result.setup)}</td>
              <td><StatusBadge value={result.direction} /></td>
              <td><StatusBadge value={result.result_status} /></td>
              <td><TimeCell value={result.hit_time_utc || result.hit_time} /></td>
              <td><TimeCell value={result.evaluated_at_utc} /></td>
              <td><TimeCell value={result.expiry_time_utc || result.expiry_time} /></td>
              <td>{fmtR(result.realized_R)} / {fmtR(result.max_favorable_excursion_R)} / {fmtR(result.max_adverse_excursion_R)}</td>
            </tr>
          ))}
          {!results.length && (
            <tr>
              <td colSpan={8}><EmptyState title="Belum ada completed result" detail="Outcome akan muncul setelah target referensi, stop referensi, atau expiry terhitung dari closed candle." /></td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

function TimeCell({ value, compact = false }: { value?: string | null; compact?: boolean }) {
  const detail = formatTimeWithUtcDetail(value);
  return (
    <div>
      <div>{detail.local}</div>
      {!compact && <div className="text-xs text-slate-500">{detail.relative}</div>}
      <details className="mt-1 text-xs text-slate-500">
        <summary className="cursor-pointer font-semibold">UTC detail</summary>
        <div className="mt-1">Local time: {detail.local}</div>
        <div>UTC: {detail.utc}</div>
      </details>
    </div>
  );
}

function MiniStat({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded border border-line p-3">
      <div className="text-xs font-semibold uppercase text-slate-500">{label}</div>
      <div className="mt-1 font-bold text-ink">{value}</div>
    </div>
  );
}

function latestTime(values: Array<string | null | undefined>): string | null {
  const dates = values
    .filter(Boolean)
    .map((value) => new Date(value as string))
    .filter((value) => !Number.isNaN(value.getTime()))
    .sort((a, b) => b.getTime() - a.getTime());
  return dates[0]?.toISOString() || null;
}

function timeLine(value?: string | null): string {
  const local = formatLocalDateTime(value);
  const relative = formatRelativeTime(value);
  return local === "-" ? "-" : `${local}, ${relative}`;
}

function fmtR(value?: number | null): string {
  if (value === null || value === undefined) return "-";
  return `${fmtNumber(value)}R`;
}
