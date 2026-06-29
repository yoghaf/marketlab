export function Metric({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="border border-line bg-white p-4">
      <div className="text-xs font-semibold uppercase text-slate-500">{label}</div>
      <div className="mt-2 text-2xl font-bold text-ink">{value}</div>
    </div>
  );
}
