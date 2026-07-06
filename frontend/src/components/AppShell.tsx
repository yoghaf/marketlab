import { Nav } from "@/components/Nav";

export function AppShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen bg-[#f5f7fa]">
      <Nav />
      <main className="w-full px-3 py-4 md:px-4 md:py-5 xl:px-5">{children}</main>
    </div>
  );
}
