import Link from "next/link";

const links = [
  { href: "/", label: "Overview" },
  { href: "/scanner", label: "Signals" },
  { href: "/strategy-arena", label: "Strategy Test" },
  { href: "/data-health", label: "System Health" },
  { href: "/universe", label: "Universe" },
  { href: "/collectors", label: "Developer" }
];

export function Nav() {
  return (
    <header className="sticky top-0 z-20 border-b border-line bg-white/95 backdrop-blur">
      <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-5 px-4 py-3 md:px-6">
        <Link href="/" className="text-lg font-bold tracking-normal text-ink">
          MarketLab
        </Link>
        <nav className="flex flex-wrap gap-2 text-sm">
          {links.map((link) => (
            <Link
              key={link.href}
              href={link.href}
              className="rounded border border-line px-3 py-1.5 text-ink hover:bg-field"
            >
              {link.label}
            </Link>
          ))}
        </nav>
      </div>
    </header>
  );
}
