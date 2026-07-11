import Link from "next/link";

import { EmptyState } from "@/components/EmptyState";
import { MetricCard } from "@/components/MetricCard";
import { PageHeader } from "@/components/PageHeader";
import { SectionCard } from "@/components/SectionCard";
import { StatusBadge } from "@/components/StatusBadge";
import {
  SignalForwardIntegrityResponse,
  SignalPerformanceBucket,
  SignalPerformanceItem,
  SignalPerformanceResponse,
  fetchJson,
  fmtNumber,
  fmtPrice,
  fmtTime
} from "@/lib/api";
import { labelFor } from "@/lib/labels";

export const dynamic = "force-dynamic";

type GroupRow = {
  key: string;
  count: number;
  tp: number;
  sl: number;
  open: number;
  totalR: number;
  realisticR: number;
  medianR: number | null;
  bestR: number | null;
  worstR: number | null;
  topSymbol?: string;
};

export default async function Signal1hReviewPage() {
  const performanceQuery = new URLSearchParams({
    include_watch_only: "false",
    position_lock: "true",
    result_status: "closed",
    timeframe: "1h",
    limit: "500"
  });
  const forwardQuery = new URLSearchParams({
    include_watch_only: "false",
    position_lock: "true",
    timeframe: "1h",
    limit: "100"
  });

  let performance: SignalPerformanceResponse | null = null;
  let forward: SignalForwardIntegrityResponse | null = null;
  let error: string | null = null;
  try {
    [performance, forward] = await Promise.all([
      fetchJson<SignalPerformanceResponse>(`/api/signal-candidates/performance/live?${performanceQuery.toString()}`, { revalidateSeconds: 20 }),
      fetchJson<SignalForwardIntegrityResponse>(`/api/signals/forward-integrity?${forwardQuery.toString()}`, { revalidateSeconds: 20 })
    ]);
  } catch (err) {
    error = err instanceof Error ? err.message : "1h Signal Review API failed";
  }

  const aggregate = performance?.aggregate;
  const closedItems = performance?.items || [];
  const openItems = forward?.items?.filter((item) => item.result_status === "OPEN") || [];
  const byStage = groupRows(closedItems, (item) => item.stage);
  const bySymbol = groupRows(closedItems, (item) => item.symbol);
  const bestStage = byStage[0];
  const worstStage = [...byStage].sort((a, b) => a.realisticR - b.realisticR)[0];
  const read = buildRead(aggregate, bestStage, worstStage, forward);

  return (
    <div className="space-y-5">
      <PageHeader
        title="1h Signal Review"
        badge="READ-ONLY 1H MODE"
        subtitle="Halaman fokus untuk membaca Signal timeframe 1h saja. Tujuannya memisahkan signal yang lebih serius dari noise 15m, tanpa mengubah rule atau execution."
        updatedAt={fmtTime(performance?.snapshot?.generated_at_utc || performance?.generated_at_utc)}
      />

      <div className="flex flex-wrap gap-2 text-sm">
        <Link className="rounded border border-line bg-white px-3 py-2 font-semibold hover:bg-field" href="/scanner?tier=SIGNAL_CANDIDATE">Open Radar</Link>
        <Link className="rounded border border-line bg-white px-3 py-2 font-semibold hover:bg-field" href="/signal-performance">Open Signal History</Link>
        <Link className="rounded border border-line bg-white px-3 py-2 font-semibold hover:bg-field" href="/signal-quality-lab?timeframe=1h">Open Quality Lab 1h</Link>
      </div>

      {error ? (
        <div className="rounded border border-stale bg-red-50 p-4 text-sm text-stale">{error}</div>
      ) : (
        <>
          <section className="grid gap-3 md:grid-cols-2 xl:grid-cols-6">
            <MetricCard label="1h evaluated" value={aggregate?.signals_evaluated ?? 0} helper={`${aggregate?.signals_skipped ?? 0} skipped by lock`} />
            <MetricCard label="Ideal R" value={`${fmtSigned(aggregate?.total_r_closed)}R`} helper="Closed TP/SL/BOTH" tone={Number(aggregate?.total_r_closed || 0) >= 0 ? "good" : "bad"} />
            <MetricCard label="Realistic R" value={`${fmtSigned(aggregate?.realistic_total_r_closed)}R`} helper="Fee + spread + slippage" tone={Number(aggregate?.realistic_total_r_closed || 0) >= 0 ? "good" : "bad"} />
            <MetricCard label="TP / SL" value={`${aggregate?.tp_count ?? 0} / ${aggregate?.sl_count ?? 0}`} helper={`${aggregate?.closed_count ?? 0} closed`} />
            <MetricCard label="Winrate" value={aggregate?.winrate_pct == null ? "-" : `${fmtNumber(aggregate.winrate_pct)}%`} helper="TP / (TP + SL)" tone="info" />
            <MetricCard label="Open 1h" value={forward?.summary?.fresh_open_count ?? 0} helper={`${fmtSigned(sumOpenR(openItems))}R active`} tone="warn" />
          </section>

          <SectionCard title="1h decision read" description="Ini bukan keputusan trading. Ini ringkasan apakah timeframe 1h layak jadi fokus riset utama.">
            <div className="grid gap-3 p-4 md:grid-cols-[1.3fr_1fr_1fr]">
              <div className="rounded border border-line bg-field/50 p-3">
                <div className="text-xs font-semibold uppercase text-slate-500">Verdict sementara</div>
                <div className="mt-2 text-xl font-bold text-ink">{read.verdict}</div>
                <p className="mt-2 text-sm text-slate-600">{read.reason}</p>
              </div>
              <Insight label="Stage paling membantu" value={bestStage ? `${labelFor(bestStage.key)} (${fmtSigned(bestStage.realisticR)}R realistic)` : "-"} />
              <Insight label="Stage paling merusak" value={worstStage ? `${labelFor(worstStage.key)} (${fmtSigned(worstStage.realisticR)}R realistic)` : "-"} />
            </div>
          </SectionCard>

          <section className="grid gap-4 xl:grid-cols-2">
            <SectionCard title="1h stage performance" description="MID_LONG dan MID_SHORT 1h dibaca terpisah supaya tidak tercampur noise 15m.">
              <GroupTable rows={byStage} label="Stage" />
            </SectionCard>
            <SectionCard title="1h open integrity" description="Posisi 1h yang masih aktif. Current R valid kalau symbol candle masih fresh.">
              <OpenSignalTable rows={openItems.slice(0, 12)} />
            </SectionCard>
          </section>

          <SectionCard title="1h symbol quality" description="Symbol yang paling membantu atau paling merusak hasil 1h. Gunakan ini untuk mencari token yang noisy.">
            <GroupTable rows={bySymbol.slice(0, 18)} label="Symbol" />
          </SectionCard>

          <SectionCard title="Latest closed 1h signals" description="Arsip signal 1h yang sudah close TP/SL/BOTH. Entry tetap futures; spot/rich hanya evidence.">
            <SignalTable rows={closedItems.slice(0, 30)} />
          </SectionCard>
        </>
      )}
    </div>
  );
}

function buildRead(
  aggregate?: SignalPerformanceBucket,
  bestStage?: GroupRow,
  worstStage?: GroupRow,
  forward?: SignalForwardIntegrityResponse | null
) {
  const realisticR = Number(aggregate?.realistic_total_r_closed || 0);
  const closed = Number(aggregate?.closed_count || 0);
  const stale = Number(forward?.summary?.stale_forward_count || 0);
  if (!closed) {
    return { verdict: "Belum cukup closed 1h", reason: "Belum ada hasil closed 1h sesuai filter default." };
  }
  if (stale > 0) {
    return { verdict: "Cek freshness dulu", reason: `${stale} signal 1h stale. Current R tidak boleh dipercaya penuh sebelum candle fresh.` };
  }
  if (realisticR > 0 && bestStage && (!worstStage || bestStage.realisticR > Math.abs(worstStage.realisticR))) {
    return { verdict: "1h layak jadi fokus riset", reason: "Realistic R 1h positif dan ada stage yang membantu. Tetap perlu filter kualitas, bukan langsung execution." };
  }
  if (realisticR > 0) {
    return { verdict: "1h positif tapi masih campur", reason: "Total realistic R positif, tetapi pemisahan stage belum bersih. Lanjut bedah symbol dan stage." };
  }
  return { verdict: "1h masih perlu filter", reason: "Realistic R 1h belum positif. Fokus berikutnya mencari filter yang mengurangi SL dan drawdown." };
}

function groupRows(items: SignalPerformanceItem[], keyFn: (item: SignalPerformanceItem) => string): GroupRow[] {
  const map = new Map<string, SignalPerformanceItem[]>();
  for (const item of items) {
    const key = keyFn(item) || "UNKNOWN";
    map.set(key, [...(map.get(key) || []), item]);
  }
  return [...map.entries()]
    .map(([key, rows]) => {
      const closedR = rows.map((item) => toNumber(item.realistic_realized_r ?? item.realized_r)).filter((value) => value !== null) as number[];
      const symbols = new Map<string, number>();
      for (const row of rows) symbols.set(row.symbol, (symbols.get(row.symbol) || 0) + 1);
      const topSymbol = [...symbols.entries()].sort((a, b) => b[1] - a[1])[0]?.[0];
      return {
        key,
        count: rows.length,
        tp: rows.filter((item) => item.result_status === "TP_HIT").length,
        sl: rows.filter((item) => item.result_status === "SL_HIT").length,
        open: rows.filter((item) => item.result_status === "OPEN").length,
        totalR: sum(rows.map((item) => toNumber(item.realized_r))),
        realisticR: sum(rows.map((item) => toNumber(item.realistic_realized_r ?? item.realized_r))),
        medianR: median(closedR),
        bestR: closedR.length ? Math.max(...closedR) : null,
        worstR: closedR.length ? Math.min(...closedR) : null,
        topSymbol
      };
    })
    .sort((a, b) => b.realisticR - a.realisticR);
}

function GroupTable({ rows, label }: { rows: GroupRow[]; label: string }) {
  return (
    <div className="overflow-hidden">
      <table className="ops-table">
        <thead>
          <tr>
            <th>{label}</th>
            <th>Rows</th>
            <th>TP / SL</th>
            <th>Winrate</th>
            <th>Realistic R</th>
            <th>Median R</th>
            <th>Best / Worst</th>
            <th>Top Symbol</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.key}>
              <td className="font-semibold">{label === "Stage" ? labelFor(row.key) : row.key}</td>
              <td>{row.count}</td>
              <td>{row.tp} / {row.sl}</td>
              <td>{row.tp + row.sl ? fmtNumber((row.tp / (row.tp + row.sl)) * 100) : "-"}%</td>
              <td className={row.realisticR >= 0 ? "text-ready" : "text-stale"}>{fmtSigned(row.realisticR)}R</td>
              <td>{row.medianR == null ? "-" : `${fmtSigned(row.medianR)}R`}</td>
              <td>{row.bestR == null ? "-" : `${fmtSigned(row.bestR)} / ${fmtSigned(row.worstR)}R`}</td>
              <td>{row.topSymbol || "-"}</td>
            </tr>
          ))}
          {!rows.length && (
            <tr>
              <td colSpan={8}>
                <EmptyState title="Belum ada data 1h" detail="Tunggu signal 1h close bertambah atau cek filter position lock." />
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

function OpenSignalTable({ rows }: { rows: SignalPerformanceItem[] }) {
  return (
    <div className="overflow-hidden">
      <table className="ops-table">
        <thead>
          <tr>
            <th>Time WIB</th>
            <th>Symbol</th>
            <th>Stage</th>
            <th>Dir</th>
            <th>Current R</th>
            <th>Entry / SL / TP</th>
            <th>Fresh</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((item) => (
            <tr key={item.signal_id}>
              <td>{item.signal_time_wib || fmtTime(item.signal_timestamp)}</td>
              <td className="font-semibold">
                <Link className="text-blue-700 hover:underline" href={`/signals/${encodeURIComponent(item.symbol)}?signal_id=${encodeURIComponent(item.signal_id)}`}>
                  {item.symbol}
                </Link>
              </td>
              <td>{labelFor(item.stage)}</td>
              <td><StatusBadge value={item.direction} /></td>
              <td>{fmtSigned(item.realistic_unrealized_r ?? item.unrealized_r)}R</td>
              <td className="text-sm">
                <div>Entry {fmtPrice(item.entry)}</div>
                <div>SL {fmtPrice(item.stop_loss)}</div>
                <div>TP {fmtPrice(item.take_profit)}</div>
              </td>
              <td>{item.stale_forward_data ? <StatusBadge value="STALE" /> : <StatusBadge value="FRESH" />}</td>
            </tr>
          ))}
          {!rows.length && (
            <tr>
              <td colSpan={7}>
                <EmptyState title="Tidak ada open 1h" detail="Semua signal 1h sudah close atau belum ada posisi paper aktif." />
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

function SignalTable({ rows }: { rows: SignalPerformanceItem[] }) {
  return (
    <div className="overflow-hidden">
      <table className="ops-table">
        <thead>
          <tr>
            <th>Time WIB</th>
            <th>Symbol</th>
            <th>Stage</th>
            <th>Dir</th>
            <th>Status</th>
            <th>Entry</th>
            <th>SL</th>
            <th>TP</th>
            <th>Realistic R</th>
            <th>Result WIB</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((item) => (
            <tr key={item.signal_id}>
              <td>{item.signal_time_wib || fmtTime(item.signal_timestamp)}</td>
              <td className="font-semibold">
                <Link className="text-blue-700 hover:underline" href={`/signals/${encodeURIComponent(item.symbol)}?signal_id=${encodeURIComponent(item.signal_id)}`}>
                  {item.symbol}
                </Link>
              </td>
              <td>{labelFor(item.stage)}</td>
              <td><StatusBadge value={item.direction} /></td>
              <td><StatusBadge value={item.result_status} /></td>
              <td>{fmtPrice(item.entry)}</td>
              <td>{fmtPrice(item.stop_loss)}</td>
              <td>{fmtPrice(item.take_profit)}</td>
              <td>{fmtSigned(item.realistic_realized_r ?? item.realized_r)}R</td>
              <td>{item.result_time_wib || fmtTime(item.result_time_utc)}</td>
            </tr>
          ))}
          {!rows.length && (
            <tr>
              <td colSpan={10}>
                <EmptyState title="Belum ada closed 1h" detail="Signal 1h belum punya hasil closed sesuai filter default." />
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

function Insight({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded border border-line bg-white p-3 text-sm">
      <div className="text-xs font-semibold uppercase text-slate-500">{label}</div>
      <div className="mt-1 font-bold text-ink">{value}</div>
    </div>
  );
}

function sumOpenR(items: SignalPerformanceItem[]): number {
  return sum(items.map((item) => toNumber(item.realistic_unrealized_r ?? item.unrealized_r)));
}

function sum(values: (number | null)[]): number {
  return values.reduce<number>((total, value) => total + (value ?? 0), 0);
}

function median(values: number[]): number | null {
  if (!values.length) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const middle = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2;
}

function toNumber(value?: string | number | null): number | null {
  if (value === null || value === undefined || value === "") return null;
  const num = typeof value === "number" ? value : Number(value);
  return Number.isFinite(num) ? num : null;
}

function fmtSigned(value?: string | number | null): string {
  const num = toNumber(value);
  if (num === null) return "-";
  const abs = Math.abs(num);
  const text = abs >= 100 ? num.toFixed(0) : abs >= 10 ? num.toFixed(1) : num.toFixed(2);
  return `${num >= 0 ? "+" : ""}${text}`;
}
