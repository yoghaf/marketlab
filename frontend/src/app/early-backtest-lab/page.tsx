import { EarlyBacktestLabClient } from "./EarlyBacktestLabClient";

import {
  EarlyBacktestEventsResponse,
  EarlyBacktestSummaryResponse,
  fetchJson
} from "@/lib/api";

export default async function EarlyBacktestLabPage() {
  let summary: EarlyBacktestSummaryResponse | null = null;
  let events: EarlyBacktestEventsResponse | null = null;
  let error: string | null = null;

  try {
    [summary, events] = await Promise.all([
      fetchJson<EarlyBacktestSummaryResponse>("/api/backtests/early-lab/summary", { revalidateSeconds: 30 }),
      fetchJson<EarlyBacktestEventsResponse>("/api/backtests/early-lab/events?horizon=1h&limit=1000", { revalidateSeconds: 30 })
    ]);
  } catch (err) {
    error = err instanceof Error ? err.message : "Early Backtest Lab artifact belum tersedia";
  }

  return <EarlyBacktestLabClient initialSummary={summary} initialEvents={events} initialError={error} />;
}
