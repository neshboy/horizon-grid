import path from "path";
import { defineConfig } from "vitest/config";

// Minimal vitest config: only lib/api.ts's pure functions are covered so
// far, which need nothing beyond Node + the "@/*" path alias already
// defined in tsconfig.json (no jsdom/React rendering required).
export default defineConfig({
  test: {
    environment: "node",
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "."),
    },
  },
});
