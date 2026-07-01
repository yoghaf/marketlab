import { Nav } from "@/components/Nav";

export function AppShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen bg-[#f5f7fa]">
      <Nav />
      <main className="mx-auto max-w-7xl px-4 py-5 md:px-6 md:py-6">{children}</main>
    </div>
  );
}
