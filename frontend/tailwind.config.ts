import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{js,ts,jsx,tsx,mdx}"],
  theme: {
    extend: {
      colors: {
        ink: "#17212f",
        field: "#f4f7f9",
        line: "#d8e0e7",
        ready: "#13795b",
        warmup: "#9a6700",
        stale: "#b42318",
        missing: "#6b7280"
      }
    }
  },
  plugins: []
};

export default config;
