import Link from "next/link";

import { StatusBadge } from "@/components/StatusBadge";
import { UniverseItem, fetchJson, fmtNumber, fmtTime } from "@/lib/api";

type UniverseResponse = {
  count: number;
  active_universe_count: number;
  universe_count: number;
  full_active_count: number;
  signal_eligible_count: number;
  items: UniverseItem[];
};

export default async function UniversePage() {
  const data = await fetchJson<UniverseResponse>("/api/universe/active");
  return (
    <div className="space-y-4">
      <div className="flex items-end justify-between gap-4">
        <h1 className="text-2xl font-bold tracking-normal">Universe</h1>
        <div className="text-sm text-slate-600">
          {data.active_universe_count ?? data.universe_count ?? data.count} active, {data.full_active_count ?? 0} full active
        </div>
      </div>
      <div className="overflow-x-auto border border-line bg-white">
        <table>
          <thead>
            <tr>
              <th>Rank</th>
              <th>Symbol</th>
              <th>Tier</th>
              <th>Quote Volume</th>
              <th>24h %</th>
              <th>Last Price</th>
              <th>Trades</th>
              <th>Entered</th>
              <th>Last Seen</th>
            </tr>
          </thead>
          <tbody>
            {data.items.map((item) => (
              <tr key={item.symbol}>
                <td>{item.rank}</td>
                <td>
                  <Link className="font-semibold text-blue-700 hover:underline" href={`/tokens/${item.symbol}`}>
                    {item.symbol}
                  </Link>
                </td>
                <td><StatusBadge value={item.collection_tier} /></td>
                <td>{fmtNumber(item.quote_volume)}</td>
                <td>{fmtNumber(item.price_change_percent)}</td>
                <td>{fmtNumber(item.last_price)}</td>
                <td>{fmtNumber(item.trade_count_24h)}</td>
                <td>{fmtTime(item.entered_at)}</td>
                <td>{fmtTime(item.last_seen_at)}</td>
              </tr>
            ))}
            {!data.items.length && (
              <tr>
                <td colSpan={9}>No active universe yet. Run the collector.</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
