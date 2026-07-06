import type { NextConfig } from "next";

const apiBase =
  process.env.SERVER_API_BASE_URL ||
  process.env.INTERNAL_API_BASE_URL ||
  "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${apiBase}/api/:path*`
      }
    ];
  }
};

export default nextConfig;
