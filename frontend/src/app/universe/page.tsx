import Link from "next/link";

import { EmptyState } from "@/components/EmptyState";
import { FilterBar, SelectFilter } from "@/components/FilterBar";
import { MetricCard } from "@/components/MetricCard";
import { PageHeader } from "@/components/PageHeader";
import { SectionCard } from "@/components/SectionCard";
import { StatusBadge } from "@/components/StatusBadge";
import { UniverseItem, fetchJson, fmtNumber, fmtTime } from "@/lib/api";

type UniverseSearchParams = Promise<Record<string, string | string[] | undefined>>;
type UniverseResponse = {
  count: number;
  active_universe_count: number;
  universe_count: number;
  full_active_count: number;
  signal_eligible_count: number;
  items: UniverseItem[];
};

export default async function UniversePage({ searchParams }: { searchParams: UniverseSearchParams }) {
  const params = await searchParams;
  const search = (firstParam(params.search) || "").toUpperCase();
  const tier = firstParam(params.tier);
  const eligible = firstParam(params.eligible);
  const sort = firstParam(params.sort) || "rank";
  const data = await fetchJson<UniverseResponse>("/api/universe/active");
  const items = sortUniverse(
    data.items
      .filter((item) => !search || item.symbol.includes(search))
      .filter((item) => !tier || item.collection_tier === tier)
      .filter((item) => !eligible || String(item.is_signal_eligible) === eligible),
    sort
  );

  return (
    <div className="space-y-5">
      <PageHeader title="Universe" subtitle="Top active futures universe yang sedang dikoleksi. Gunakan filter untuk cek symbol, tier, dan eligibility." />
      <section className="grid gap-3 md:grid-cols-4">
        <MetricCard label="Active" value={data.active_universe_count ?? data.universe_count ?? data.count} helper="Symbol yang dipantau" />
        <MetricCard label="Full Active" value={data.full_active_count ?? 0} helper="Masuk universe utama" />
        <MetricCard label="Signal Eligible" value={data.signal_eligible_count ?? 0} helper="Data dasar cukup untuk sinyal" />
        <MetricCard label="Shown" value={items.length} helper="Ditampilkan di tabel" />
      </section>
      <FilterBar>
        <label className="grid gap-1 text-sm">
          <span className="font-semibold text-slate-600">Search symbol</span>
          <input className="rounded border border-line px-3 py-2" name="search" defaultValue={search} placeholder="BTCUSDT" />
        </label>
        <SelectFilter label="Tier" name="tier" value={tier || ""} options={["FULL_ACTIVE", "LIGHT_WATCH", "NOT_ACTIVE"]} emptyLabel="All tiers" />
        <SelectFilter label="Signal Eligible" name="eligible" value={eligible || ""} options={["true", "false"]} emptyLabel="All" />
        <SelectFilter label="Sort" name="sort" value={sort} options={["rank", "volume", "change"]} emptyLabel="Rank" />
      </FilterBar>
      <SectionCard title="Universe table" description="Header sticky dan angka 24h diberi warna.">
        <div className="table-wrap max-h-[70vh]">
          <table>
            <thead className="sticky top-0 z-10">
              <tr>
                <th>Rank</th>
                <th>Symbol</th>
                <th>Tier</th>
                <th>Quote Volume</th>
                <th>24h %</th>
                <th>Last Price</th>
                <th>Trades</th>
                <th>Eligibility Reason</th>
                <th>Entered</th>
                <th>Last Seen</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <tr key={item.symbol}>
                  <td>{item.rank}</td>
                  <td>
                    <Link className="font-semibold text-blue-700 hover:underline" href={`/tokens/${item.symbol}`}>{item.symbol}</Link>
                  </td>
                  <td><StatusBadge value={item.collection_tier} /></td>
                  <td>{fmtNumber(item.quote_volume)}</td>
                  <td className={changeClass(item.price_change_percent)}>{fmtNumber(item.price_change_percent)}%</td>
                  <td>{fmtNumber(item.last_price)}</td>
                  <td>{fmtNumber(item.trade_count_24h)}</td>
                  <td>{eligibilityReason(item)}</td>
                  <td>{fmtTime(item.entered_at)}</td>
                  <td>{fmtTime(item.last_seen_at)}</td>
                </tr>
              ))}
              {!items.length && (
                <tr>
                  <td colSpan={10}><EmptyState title="Universe kosong" detail="Tidak ada symbol yang cocok dengan filter." /></td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </SectionCard>
    </div>
  );
}

function eligibilityReason(item: UniverseItem): string {
  if (!item.is_active) return "Tidak aktif";
  if (!item.is_full_active) return "Bukan universe utama";
  if (!item.is_signal_eligible) return "Data dasar belum cukup";
  return "Data dasar cukup";
}

function sortUniverse(items: UniverseItem[], sort: string): UniverseItem[] {
  return [...items].sort((a, b) => {
    if (sort === "volume") return Number(b.quote_volume || 0) - Number(a.quote_volume || 0);
    if (sort === "change") return Number(b.price_change_percent || 0) - Number(a.price_change_percent || 0);
    return (a.rank || 999) - (b.rank || 999);
  });
}

function changeClass(value?: string | number | null): string {
  const number = Number(value || 0);
  if (number > 0) return "font-semibold text-ready";
  if (number < 0) return "font-semibold text-stale";
  return "";
}

function firstParam(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}
