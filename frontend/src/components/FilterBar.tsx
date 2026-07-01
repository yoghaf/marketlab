export function FilterBar({ children }: { children: React.ReactNode }) {
  return (
    <form className="grid gap-3 rounded-md border border-line bg-white p-4 md:grid-cols-3 xl:grid-cols-6" method="get">
      {children}
      <div className="flex items-end">
        <button className="rounded border border-line px-4 py-2 text-sm font-semibold hover:bg-field" type="submit">
          Apply
        </button>
      </div>
    </form>
  );
}

export function SelectFilter({
  label,
  name,
  value,
  options,
  emptyLabel = "All"
}: {
  label: string;
  name: string;
  value?: string;
  options: string[];
  emptyLabel?: string;
}) {
  return (
    <label className="grid gap-1 text-sm">
      <span className="font-semibold text-slate-600">{label}</span>
      <select className="rounded border border-line bg-white px-3 py-2" name={name} defaultValue={value || ""}>
        <option value="">{emptyLabel}</option>
        {options.map((option) => (
          <option key={option} value={option}>{option}</option>
        ))}
      </select>
    </label>
  );
}
