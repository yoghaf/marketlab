export default function LoadingSkeleton() {
  return (
    <div className="space-y-4">
      <div className="h-8 w-64 animate-pulse rounded bg-slate-200" />
      <div className="grid gap-3 md:grid-cols-4">
        {Array.from({ length: 4 }).map((_, index) => (
          <div key={index} className="h-24 animate-pulse rounded-md border border-line bg-white" />
        ))}
      </div>
      <div className="h-80 animate-pulse rounded-md border border-line bg-white" />
    </div>
  );
}
