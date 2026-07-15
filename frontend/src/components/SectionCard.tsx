export function SectionCard({
  title,
  description,
  children,
  actions
}: {
  title?: string;
  description?: string;
  children: React.ReactNode;
  actions?: React.ReactNode;
}) {
  return (
    <section className="overflow-hidden rounded-lg border border-line bg-white shadow-sm">
      {(title || description || actions) && (
        <div className="flex flex-wrap items-start justify-between gap-3 border-b border-line bg-white px-4 py-3">
          <div>
            {title && <h2 className="text-base font-bold text-ink">{title}</h2>}
            {description && <p className="mt-1 text-sm text-slate-600">{description}</p>}
          </div>
          {actions}
        </div>
      )}
      {children}
    </section>
  );
}
