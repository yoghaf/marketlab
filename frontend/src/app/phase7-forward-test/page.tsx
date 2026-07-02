import { DecisionBanner } from "@/components/DecisionBanner";
import { EmptyState } from "@/components/EmptyState";
import { MetricCard } from "@/components/MetricCard";
import { PageHeader } from "@/components/PageHeader";
import { SectionCard } from "@/components/SectionCard";
import { StatusBadge } from "@/components/StatusBadge";
import {
  Phase7ForwardEventsResponse,
  Phase7ForwardResultsResponse,
  Phase7ForwardStatus,
  Phase7ForwardSummary,
  fetchJson,
  fmtNumber,
  fmtTime
} from "@/lib/api";
import { labelFor } from "@/lib/labels";

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

  const activeEvents = (events?.events || []).filter((event) => ["WAITING_OUTCOME", "UNKNOWN_FORWARD_DATA"].includes(event.status));
  const completedResults = (results?.results || []).filter((result) =>
    ["TP_HIT", "SL_HIT", "BOTH_HIT_SAME_CANDLE", "EXPIRED", "CANNOT_EVALUATE"].includes(result.result_status)
  );

  return (
    <div className="space-y-5">
      <PageHeader
        title="Phase 7 Shadow Forward-Test"
        badge="READ-ONLY - bukan sinyal entry live"
        subtitle="Melacak kandidat yang sudah approved Phase 6 sebagai simulasi forward-test. Tidak ada order, eksekusi, atau instruksi trading."
        updatedAt={fmtTime(status?.generated_at || summary?.generated_at)}
      />

      {error ? (
        <div className="rounded border border-stale bg-red-50 p-4 text-sm text-stale">{error}</div>
      ) : (
        <>
          <DecisionBanner
            title="Status Phase 7"
            status={status?.mode}
            tone={status?.mode === "ACTIVE_FORWARD_TEST" ? "info" : status?.mode === "INPUT_ARTIFACT_MISSING" ? "bad" : "warn"}
            description={status?.reason || "Menunggu artifact Phase 7."}
          />

          <section className="grid gap-3 md:grid-cols-3 xl:grid-cols-6">
            <MetricCard label="Approved" value={status?.approved_candidate_count ?? 0} helper="Dari Phase 6 gate" tone="info" />
            <MetricCard label="Active Events" value={status?.active_event_count ?? 0} helper="Menunggu candle forward" tone={status?.active_event_count ? "info" : "neutral"} />
            <MetricCard label="Completed" value={summary?.completed_events ?? 0} helper="Sudah punya outcome" tone="good" />
            <MetricCard label="TP Hit" value={summary?.tp_hit ?? 0} helper="Referensi shadow" tone="good" />
            <MetricCard label="SL Hit" value={summary?.sl_hit ?? 0} helper="Referensi shadow" tone="bad" />
            <MetricCard label="Avg R" value={fmtR(summary?.average_realized_R)} helper="Read-only tracking" />
          </section>

          <SectionCard title="Current shadow events" description="Event dibuat deterministik dari approved candidate. Level TP/SL adalah referensi simulasi, bukan order.">
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Symbol</th>
                    <th>Setup</th>
                    <th>Arah</th>
                    <th>Status</th>
                    <th>Entry</th>
                    <th>Reference levels</th>
                    <th>Expiry</th>
                    <th>Guardrail</th>
                  </tr>
                </thead>
                <tbody>
                  {activeEvents.map((event) => (
                    <tr key={event.event_id}>
                      <td className="font-semibold">{event.symbol}</td>
                      <td>{labelFor(event.setup)}</td>
                      <td><StatusBadge value={event.direction} /></td>
                      <td><StatusBadge value={event.status} /></td>
                      <td>
                        <div>{fmtNumber(event.entry_reference_price)}</div>
                        <div className="text-xs text-slate-500">{fmtTime(event.entry_reference_time || event.observation_timestamp)}</div>
                      </td>
                      <td className="text-sm">
                        <div>TP ref: {fmtNumber(event.take_profit_reference_price)}</div>
                        <div>SL ref: {fmtNumber(event.stop_reference_price)}</div>
                        <div>ATR {event.atr_reference_timeframe}: {fmtNumber(event.atr_reference_value)}</div>
                      </td>
                      <td>{fmtTime(event.expiry_time)}</td>
                      <td className="text-xs font-semibold text-slate-600">not_live_signal=true</td>
                    </tr>
                  ))}
                  {!activeEvents.length && (
                    <tr>
                      <td colSpan={8}>
                        <EmptyState title="Tidak ada active shadow event" detail={status?.next_action || "Menunggu kandidat Phase 6 approved."} />
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </SectionCard>

          <SectionCard title="Completed results" description="Outcome dihitung dari closed futures 15m candle setelah observation timestamp.">
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Symbol</th>
                    <th>Setup</th>
                    <th>Arah</th>
                    <th>Result</th>
                    <th>Hit time</th>
                    <th>R</th>
                    <th>MFE / MAE</th>
                    <th>Ambiguous</th>
                  </tr>
                </thead>
                <tbody>
                  {completedResults.slice(0, 100).map((result) => (
                    <tr key={result.event_id}>
                      <td className="font-semibold">{result.symbol}</td>
                      <td>{labelFor(result.setup)}</td>
                      <td><StatusBadge value={result.direction} /></td>
                      <td><StatusBadge value={result.result_status} /></td>
                      <td>{fmtTime(result.hit_time)}</td>
                      <td>{fmtR(result.realized_R)}</td>
                      <td>{fmtR(result.max_favorable_excursion_R)} / {fmtR(result.max_adverse_excursion_R)}</td>
                      <td>{result.ambiguous_same_candle ? "Ya" : "Tidak"}</td>
                    </tr>
                  ))}
                  {!completedResults.length && (
                    <tr>
                      <td colSpan={8}>
                        <EmptyState title="Belum ada completed result" detail="Shadow event akan selesai setelah target referensi, stop referensi, atau expiry terhitung dari closed candle." />
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </SectionCard>

          <SectionCard title="Read-only rules" description="Halaman ini tidak menjalankan trading dan tidak mengubah rule classifier.">
            <div className="grid gap-3 p-4 text-sm text-slate-700 md:grid-cols-3">
              <div>Event hanya dibuat dari kandidat Phase 6 dengan verdict <strong>PHASE7_READY</strong>.</div>
              <div>Entry reference memakai close candle candidate dan ATR closed sebelum atau pada observation time.</div>
              <div>Frontend hanya membaca artifact. Tidak ada tombol rerun, order, atau eksekusi.</div>
            </div>
          </SectionCard>
        </>
      )}
    </div>
  );
}

function fmtR(value?: number | null): string {
  if (value === null || value === undefined) return "-";
  return `${fmtNumber(value)}R`;
}
