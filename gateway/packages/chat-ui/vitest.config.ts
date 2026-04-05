/**
 * Vitest configuration for @dingdawg/chat-ui
 *
 * Uses jsdom environment to simulate browser DOM for React component tests.
 * setupFiles loads @testing-library/jest-dom matchers globally.
 */

import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./vitest.setup.ts"],
    include: ["src/__tests__/**/*.{test,spec}.{ts,tsx}"],
    coverage: {
      provider: "v8",
      reporter: ["text", "lcov"],
      include: ["src/**/*.{ts,tsx}"],
      exclude: ["src/__tests__/**", "src/types/**", "src/index.ts"],
    },
  },
});
