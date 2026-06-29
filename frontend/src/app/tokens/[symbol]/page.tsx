import { StatusBadge } from "@/components/StatusBadge";
import { fetchJson, fmtNumber, fmtTime } from "@/lib/api";

type TokenResponse = {
  symbol: string;
  universe: {
    rank: number;
    quote_volume: string;
    collection_tier: string;
    is_signal_eligible: boolean;
    is_active: boolean;
    entered_at: string;
    last_seen_at: string;
  };
  health?: { status: string; reason?: string | null } | null;
  latest: Record<string, Record<string, string | number | null> | null>;
};

export default async function TokenPage({ params }: { params: Promise<{ symbol: string }> }) {
  const { symbol } = await params;
  const data = await fetchJson<TokenResponse>(`/api/tokens/${symbol}`);
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-bold tracking-normal">{data.symbol}</h1>
        <div className="flex gap-2">
          <StatusBadge value={data.universe.collection_tier} />
          <StatusBadge value={data.health?.status} />
        </div>
      </div>
      <section className="grid gap-3 md:grid-cols-4">
        <div className="border border-line bg-white p-4">
          <div className="text-xs font-semibold uppercase text-slate-500">Rank</div>
          <div className="mt-2 text-2xl font-bold">{data.universe.rank}</div>
        </div>
        <div className="border border-line bg-white p-4">
          <div className="text-xs font-semibold uppercase text-slate-500">Quote Volume</div>
          <div className="mt-2 text-2xl font-bold">{fmtNumber(data.universe.quote_volume)}</div>
        </div>
        <div className="border border-line bg-white p-4">
          <div className="text-xs font-semibold uppercase text-slate-500">Entered</div>
          <div className="mt-2 text-sm font-semibold">{fmtTime(data.universe.entered_at)}</div>
        </div>
        <div className="border border-line bg-white p-4">
          <div className="text-xs font-semibold uppercase text-slate-500">Last Seen</div>
          <div className="mt-2 text-sm font-semibold">{fmtTime(data.universe.last_seen_at)}</div>
        </div>
      </section>
      <section className="border border-line bg-white">
        <h2 className="border-b border-line px-4 py-3 text-base font-semibold">Latest Rows</h2>
        <div className="overflow-x-auto">
          <table>
            <thead>
              <tr>
                <th>Dataset</th>
                <th>Time</th>
                <th>Close / Mark / Bid</th>
                <th>Volume / OI / Ask</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(data.latest).map(([name, row]) => (
                <tr key={name}>
                  <td>{name.replaceAll("_", " ")}</td>
                  <td>{fmtTime((row?.close_time || row?.event_time) as string | undefined)}</td>
                  <td>{fmtNumber((row?.close_price || row?.mark_price || row?.bid_price) as string | undefined)}</td>
                  <td>{fmtNumber((row?.volume || row?.open_interest || row?.ask_price) as string | undefined)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
      <section className="border border-line bg-white p-4 text-sm">
        <div className="font-semibold">Health reason</div>
        <div>{data.health?.reason || "-"}</div>
      </section>
    </div>
  );
}
