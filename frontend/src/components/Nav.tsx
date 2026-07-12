import Link from "next/link";

const mainLinks = [
  { href: "/", label: "Overview" },
  { href: "/scanner", label: "Radar" },
  { href: "/signal-performance", label: "Signal History" },
  { href: "/signal-quality-lab", label: "Quality Lab" },
  { href: "/data-health", label: "System Health" },
  { href: "/universe", label: "Universe" }
];

const researchLinks = [
  { href: "/patch-notes", label: "Patch Notes" },
  { href: "/signal-quality-lab", label: "V2 Quality Lab" },
  { href: "/shadow-forward-log", label: "MID_SHORT Shadow Log" },
  { href: "/mid-short-failure-anatomy", label: "MID_SHORT Failure Anatomy" },
  { href: "/signal-1h-review", label: "1h Review" },
  { href: "/strategy-optimization-lab", label: "Strategy Optimization Lab" },
  { href: "/signal-factory", label: "Signal Factory Raw" },
  { href: "/v3-forward-log", label: "Archive: V3 Forward Log" },
  { href: "/collectors", label: "Advanced" }
];

export function Nav() {
  return (
    <header className="sticky top-0 z-20 border-b border-line bg-white/95 backdrop-blur">
      <div className="flex w-full flex-wrap items-center gap-5 px-3 py-3 md:px-4 xl:px-5">
        <Link href="/" className="text-lg font-bold tracking-normal text-ink">
          MarketLab
        </Link>
        <nav className="flex flex-wrap items-center gap-2 text-sm">
          {mainLinks.map((link) => (
            <Link
              key={link.href}
              href={link.href}
              className="rounded border border-line px-3 py-1.5 text-ink hover:bg-field"
            >
              {link.label}
            </Link>
          ))}
          <details className="group relative">
            <summary className="cursor-pointer list-none rounded border border-line px-3 py-1.5 text-ink hover:bg-field">
              Research / Advanced
            </summary>
            <div className="absolute left-0 top-9 z-30 grid min-w-56 gap-1 rounded border border-line bg-white p-2 shadow-lg">
              {researchLinks.map((link) => (
                <Link
                  key={link.href}
                  href={link.href}
                  className="rounded px-3 py-2 text-ink hover:bg-field"
                >
                  {link.label}
                </Link>
              ))}
            </div>
          </details>
        </nav>
      </div>
    </header>
  );
}
