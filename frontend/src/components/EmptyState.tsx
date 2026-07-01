export function EmptyState({ title, detail }: { title: string; detail?: string }) {
  return (
    <div className="p-6 text-center text-sm text-slate-600">
      <div className="font-semibold text-ink">{title}</div>
      {detail && <div className="mt-1">{detail}</div>}
    </div>
  );
}
