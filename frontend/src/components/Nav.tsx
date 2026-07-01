import Link from "next/link";

const links = [
  { href: "/", label: "Dashboard" },
  { href: "/scanner", label: "Scanner" },
  { href: "/signal-factory", label: "Signal Factory" },
  { href: "/strategy-arena", label: "Strategy Arena" },
  { href: "/universe", label: "Universe" },
  { href: "/data-health", label: "Data Health" },
  { href: "/collectors", label: "Collectors" }
];

export function Nav() {
  return (
    <header className="border-b border-line bg-white">
      <div className="mx-auto flex max-w-7xl items-center gap-6 px-5 py-4">
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
