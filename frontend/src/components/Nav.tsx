"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const mainLinks = [
  { href: "/", label: "Overview", helper: "Ringkasan" },
  { href: "/scanner", label: "Live Radar", helper: "Signal aktif" },
  { href: "/signal-performance", label: "Signal History", helper: "TP/SL closed" },
  { href: "/signal-quality-lab", label: "Quality Lab", helper: "Riset kualitas" },
  { href: "/data-health", label: "System Health", helper: "Data & loop" },
  { href: "/universe", label: "Universe", helper: "Top token" }
];

const labGroups = [
  {
    title: "Research Fokus",
    links: [
      { href: "/mid-short-filter-combination-study", label: "MID_SHORT V2.1 Decision", helper: "Filter kandidat promosi" },
      { href: "/mid-long-research-study", label: "MID_LONG 1h Baseline", helper: "V2 control only" },
      { href: "/signal-misidentification-audit", label: "Misidentification Audit", helper: "Salah arah atau risk" },
      { href: "/signal-quality-lab", label: "Signal Quality Lab", helper: "Kenapa TP/SL" },
      { href: "/signal-1h-review", label: "1h Review", helper: "Long/short 1h" },
      { href: "/shadow-forward-log", label: "Shadow Log", helper: "Forward sample" }
    ]
  },
  {
    title: "Deep Dive",
    links: [
      { href: "/mid-short-failure-anatomy", label: "Failure Anatomy", helper: "Path SL/TP" },
      { href: "/mid-short-structure-zone-study", label: "Structure Zones", helper: "Support/resistance 1h" },
      { href: "/mid-short-entry-confirmation-study", label: "Entry Confirmation", helper: "Tunggu candle 15m" },
      { href: "/mid-short-wrong-direction-deep-dive", label: "Wrong Direction", helper: "Salah arah" },
      { href: "/mid-short-taker-sell-deep-dive", label: "Taker Sell", helper: "Dominasi sell" },
      { href: "/mid-short-volume-safe-shadow", label: "Volume Safe", helper: "Volume tidak telat" },
      { href: "/mid-short-second-filter-shadow", label: "Second Filter", helper: "Filter tambahan" }
    ]
  },
  {
    title: "Raw & Ops",
    links: [
      { href: "/patch-notes", label: "Patch Notes", helper: "History update" },
      { href: "/signal-factory", label: "Signal Factory Raw", helper: "Payload mentah" },
      { href: "/strategy-optimization-lab", label: "Strategy Optimization", helper: "Lab archived" },
      { href: "/v3-forward-log", label: "V3 Archive", helper: "Shadow lama" },
      { href: "/collectors", label: "Collector Advanced", helper: "Ops detail" }
    ]
  }
];

export function Nav() {
  const pathname = usePathname();

  return (
    <header className="sticky top-0 z-20 border-b border-line bg-white/95 shadow-sm backdrop-blur">
      <div className="flex w-full items-center gap-3 px-3 py-2.5 sm:px-4 lg:gap-4 lg:py-3 xl:px-6">
        <Link href="/" className="mr-1 flex min-w-0 shrink-0 items-center gap-2 text-lg font-black tracking-normal text-ink">
          <span className="inline-flex h-8 w-8 items-center justify-center rounded-md bg-ink text-sm font-black text-white">ML</span>
          <span>MarketLab</span>
        </Link>

        <nav className="hidden flex-1 flex-wrap items-center gap-2 text-sm lg:flex">
          {mainLinks.map((link) => (
            <Link
              key={link.href}
              href={link.href}
              className={`group rounded-md border px-3 py-2 text-ink transition hover:border-blue-300 hover:bg-blue-50 ${isActive(pathname, link.href) ? "border-blue-300 bg-blue-50" : "border-line bg-white"}`}
            >
              <span className="block font-semibold leading-4">{link.label}</span>
              <span className="hidden text-[11px] leading-4 text-slate-500 xl:block">{link.helper}</span>
            </Link>
          ))}
          <details className="group relative ml-auto">
            <summary className="cursor-pointer list-none rounded-md border border-line bg-white px-3 py-2 font-semibold text-ink transition hover:border-blue-300 hover:bg-blue-50">
              Research Lab
            </summary>
            <div className="absolute right-0 top-12 z-30 grid w-[min(920px,calc(100vw-2rem))] gap-4 rounded-lg border border-line bg-white p-4 shadow-xl md:grid-cols-3">
              {labGroups.map((group) => (
                <div key={group.title} className="min-w-0">
                  <div className="px-2 pb-2 text-xs font-bold uppercase text-slate-500">{group.title}</div>
                  <div className="grid gap-1">
                    {group.links.map((link) => (
                      <Link
                        key={link.href}
                        href={link.href}
                        className="rounded-md px-3 py-2 text-ink hover:bg-field"
                      >
                        <span className="block font-semibold">{link.label}</span>
                        <span className="block text-xs leading-5 text-slate-500">{link.helper}</span>
                      </Link>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </details>
        </nav>

        <details className="group relative ml-auto lg:hidden">
          <summary className="flex min-h-10 cursor-pointer list-none items-center gap-2 rounded-md border border-line bg-white px-3 py-2 text-sm font-bold text-ink [&::-webkit-details-marker]:hidden">
            <span className="grid w-4 gap-1" aria-hidden="true">
              <span className="h-0.5 bg-current" />
              <span className="h-0.5 bg-current" />
              <span className="h-0.5 bg-current" />
            </span>
            Menu
          </summary>
          <div className="absolute right-0 top-12 z-40 max-h-[calc(100vh-5rem)] w-[min(23rem,calc(100vw-1.5rem))] overflow-y-auto overscroll-contain rounded-lg border border-line bg-white p-3 shadow-xl">
            <div className="grid grid-cols-2 gap-2">
              {mainLinks.map((link) => (
                <Link
                  key={link.href}
                  href={link.href}
                  className={`min-w-0 rounded-md border p-3 text-ink ${isActive(pathname, link.href) ? "border-blue-300 bg-blue-50" : "border-line bg-white"}`}
                >
                  <span className="block text-sm font-bold leading-5">{link.label}</span>
                  <span className="block text-xs leading-5 text-slate-500">{link.helper}</span>
                </Link>
              ))}
            </div>

            <div className="my-3 border-t border-line" />
            <div className="space-y-3">
              {labGroups.map((group) => (
                <details key={group.title} className="rounded-md border border-line">
                  <summary className="cursor-pointer list-none px-3 py-2.5 text-sm font-bold text-ink [&::-webkit-details-marker]:hidden">
                    {group.title}
                  </summary>
                  <div className="grid gap-1 border-t border-line p-2">
                    {group.links.map((link) => (
                      <Link key={link.href} href={link.href} className="rounded-md px-3 py-2 hover:bg-field">
                        <span className="block text-sm font-semibold text-ink">{link.label}</span>
                        <span className="block text-xs leading-5 text-slate-500">{link.helper}</span>
                      </Link>
                    ))}
                  </div>
                </details>
              ))}
            </div>
          </div>
        </details>
      </div>
    </header>
  );
}

function isActive(pathname: string, href: string): boolean {
  if (href === "/") return pathname === href;
  return pathname === href || pathname.startsWith(`${href}/`);
}
