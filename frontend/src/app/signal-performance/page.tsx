import { PageHeader } from "@/components/PageHeader";

import { SignalPerformanceClient } from "./SignalPerformanceClient";

export const dynamic = "force-dynamic";

export default function SignalPerformancePage() {
  return (
    <div className="space-y-5">
      <PageHeader
        title="Signal Performance"
        badge="PAPER LIVE - BUKAN EXECUTION"
        subtitle="Performa Signal Candidate dari log live MarketLab. Hitungan dibaca langsung dari DB dan candle futures terbaru; entry, SL, dan TP tetap read-only."
      />
      <SignalPerformanceClient />
    </div>
  );
}
