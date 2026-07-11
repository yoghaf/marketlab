import { PageHeader } from "@/components/PageHeader";
import Link from "next/link";

import { SignalPerformanceClient } from "./SignalPerformanceClient";

export const dynamic = "force-dynamic";

export default function SignalPerformancePage() {
  return (
    <div className="space-y-5">
      <PageHeader
        title="Signal History"
        badge="PAPER LIVE - BUKAN EXECUTION"
        subtitle="Arsip Signal yang sudah close TP/SL/BOTH: entry futures, SL, TP, result time, dan total R paper-live. Posisi open dilihat dari detail signal di Radar."
      />
      <div className="flex flex-wrap gap-2 text-sm">
        <Link className="rounded border border-line bg-white px-3 py-2 font-semibold hover:bg-field" href="/signal-1h-review">Open 1h Review</Link>
        <Link className="rounded border border-line bg-white px-3 py-2 font-semibold hover:bg-field" href="/signal-quality-lab">Open Signal Quality Lab</Link>
        <Link className="rounded border border-line bg-white px-3 py-2 font-semibold hover:bg-field" href="/scanner">Open Radar</Link>
      </div>
      <SignalPerformanceClient />
    </div>
  );
}
