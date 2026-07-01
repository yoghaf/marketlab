export function MetricCard({
  label,
  value,
  helper,
  tone = "neutral"
}: {
  label: string;
  value: string | number;
  helper?: string;
  tone?: "neutral" | "good" | "warn" | "bad" | "info";
}) {
  const toneClass = {
    neutral: "border-line bg-white",
    good: "border-emerald-200 bg-emerald-50",
    warn: "border-amber-200 bg-amber-50",
    bad: "border-red-200 bg-red-50",
    info: "border-blue-200 bg-blue-50"
  }[tone];
  return (
    <div className={`min-w-0 rounded-md border p-4 ${toneClass}`}>
      <div className="text-xs font-semibold uppercase text-slate-500">{label}</div>
      <div className="mt-2 truncate text-2xl font-bold text-ink" title={String(value)}>{value}</div>
      {helper && <div className="mt-1 line-clamp-2 text-xs leading-5 text-slate-600">{helper}</div>}
    </div>
  );
}
