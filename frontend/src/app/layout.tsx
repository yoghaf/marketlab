import type { Metadata } from "next";

import { Nav } from "@/components/Nav";
import "./globals.css";

export const metadata: Metadata = {
  title: "MarketLab",
  description: "MarketLab data collector health console"
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>
        <Nav />
        <main className="mx-auto max-w-7xl px-5 py-6">{children}</main>
      </body>
    </html>
  );
}
