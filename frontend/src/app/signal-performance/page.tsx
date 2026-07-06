import { PageHeader } from "@/components/PageHeader";

import { SignalPerformanceClient } from "./SignalPerformanceClient";

export const dynamic = "force-dynamic";

export default function SignalPerformancePage() {
  return (
    <div className="space-y-5">
      <PageHeader
        title="Signal Candidate History"
        badge="PAPER LIVE - BUKAN EXECUTION"
        subtitle="Riwayat Signal Candidate yang sudah dilog: entry futures, SL, TP, status TP/SL/open, dan total R paper-live. Ini bukan order dan bukan auto execution."
      />
      <SignalPerformanceClient />
    </div>
  );
}
