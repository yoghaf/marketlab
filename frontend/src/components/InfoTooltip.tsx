export function InfoTooltip({ text }: { text: string }) {
  return (
    <span className="group relative inline-flex">
      <span className="inline-flex h-5 w-5 items-center justify-center rounded-full border border-line text-xs font-bold text-slate-500">i</span>
      <span className="pointer-events-none absolute left-0 top-7 z-10 hidden w-64 rounded border border-line bg-white p-2 text-xs leading-5 text-slate-700 shadow-sm group-hover:block">
        {text}
      </span>
    </span>
  );
}
