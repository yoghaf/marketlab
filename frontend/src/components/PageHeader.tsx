export function PageHeader({
  title,
  subtitle,
  badge,
  updatedAt
}: {
  title: string;
  subtitle?: string;
  badge?: string;
  updatedAt?: string;
}) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-4">
      <div className="min-w-0">
        <h1 className="text-2xl font-bold tracking-normal text-ink">{title}</h1>
        {badge && (
          <div className="mt-2 inline-flex rounded border border-blue-700 bg-blue-50 px-3 py-1 text-xs font-bold text-blue-700">
            {badge}
          </div>
        )}
        {subtitle && <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-600">{subtitle}</p>}
      </div>
      <div className="flex flex-col items-end gap-2">
        {updatedAt && <div className="text-right text-xs text-slate-500">Terakhir diperbarui: {updatedAt}</div>}
        <a className="rounded border border-line px-3 py-1.5 text-sm font-semibold hover:bg-field" href="">
          Refresh
        </a>
      </div>
    </div>
  );
}
