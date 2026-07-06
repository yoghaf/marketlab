import { PageHeader } from "@/components/PageHeader";
import Link from "next/link";

import { SignalPerformanceClient } from "./SignalPerformanceClient";

export const dynamic = "force-dynamic";

export default function SignalPerformancePage() {
  return (
    <div className="space-y-5">
      <PageHeader
        title="Signal Candidate History"
        badge="PAPER LIVE - BUKAN EXECUTION"
        subtitle="Arsip hasil Signal Candidate yang sudah dilog: entry futures, SL, TP, status TP/SL/open, dan total R paper-live. Bukan radar live dan bukan daftar kandidat terbaru."
      />
      <div className="flex flex-wrap gap-2 text-sm">
        <Link className="rounded border border-line bg-white px-3 py-2 font-semibold hover:bg-field" href="/signal-quality-lab">Open Signal Quality Lab</Link>
        <Link className="rounded border border-line bg-white px-3 py-2 font-semibold hover:bg-field" href="/scanner">Open Radar</Link>
      </div>
      <SignalPerformanceClient />
    </div>
  );
}
