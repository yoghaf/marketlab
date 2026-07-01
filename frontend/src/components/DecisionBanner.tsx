import { StatusBadge } from "@/components/StatusBadge";

export function DecisionBanner({
  title,
  status,
  description,
  tone = "info"
}: {
  title: string;
  status?: string;
  description: string;
  tone?: "info" | "good" | "warn" | "bad";
}) {
  const toneClass = {
    info: "border-blue-200 bg-blue-50",
    good: "border-emerald-200 bg-emerald-50",
    warn: "border-amber-200 bg-amber-50",
    bad: "border-red-200 bg-red-50"
  }[tone];
  return (
    <section className={`rounded-md border p-4 ${toneClass}`}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-bold text-ink">{title}</h2>
          <p className="mt-1 max-w-4xl text-sm leading-6 text-slate-700">{description}</p>
        </div>
        {status && <StatusBadge value={status} />}
      </div>
    </section>
  );
}
