import { EarlyBacktestLabClient } from "./EarlyBacktestLabClient";

import {
  EarlyBacktestEventsResponse,
  EarlyBacktestSummaryResponse,
  fetchJson
} from "@/lib/api";

export default async function EarlyBacktestLabPage() {
  let summary: EarlyBacktestSummaryResponse | null = null;
  let eventsByHorizon: Record<string, EarlyBacktestEventsResponse | null> = {
    "15m": null,
    "1h": null,
    "4h": null,
    "24h": null
  };
  let error: string | null = null;

  try {
    const [summaryResponse, events15m, events1h, events4h, events24h] = await Promise.all([
      fetchJson<EarlyBacktestSummaryResponse>("/api/backtests/early-lab/summary", { revalidateSeconds: 30 }),
      fetchJson<EarlyBacktestEventsResponse>("/api/backtests/early-lab/events?horizon=15m&limit=1000", { revalidateSeconds: 30 }),
      fetchJson<EarlyBacktestEventsResponse>("/api/backtests/early-lab/events?horizon=1h&limit=1000", { revalidateSeconds: 30 }),
      fetchJson<EarlyBacktestEventsResponse>("/api/backtests/early-lab/events?horizon=4h&limit=1000", { revalidateSeconds: 30 }),
      fetchJson<EarlyBacktestEventsResponse>("/api/backtests/early-lab/events?horizon=24h&limit=1000", { revalidateSeconds: 30 })
    ]);
    summary = summaryResponse;
    eventsByHorizon = {
      "15m": events15m,
      "1h": events1h,
      "4h": events4h,
      "24h": events24h
    };
  } catch (err) {
    error = err instanceof Error ? err.message : "Early Backtest Lab artifact belum tersedia";
  }

  return <EarlyBacktestLabClient initialSummary={summary} initialEventsByHorizon={eventsByHorizon} initialError={error} />;
}
