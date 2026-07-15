import { Nav } from "@/components/Nav";

export function AppShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen bg-[#f3f6f9]">
      <Nav />
      <main className="w-full px-4 py-5 md:px-5 md:py-6 xl:px-6">{children}</main>
    </div>
  );
}
