/**
 * Vitest global setup — loads @testing-library/jest-dom matchers
 * and provides browser API stubs required by jsdom.
 */

import "@testing-library/jest-dom";
import { vi } from "vitest";

// ── matchMedia stub ──────────────────────────────────────────────────────────
// jsdom does not implement window.matchMedia. Components and hooks that call
// window.matchMedia() (e.g. useReducedMotion in useA11y) will throw without
// this stub.  The mock returns a minimal MediaQueryList-shaped object.
Object.defineProperty(window, "matchMedia", {
  writable: true,
  value: vi.fn().mockImplementation((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })),
});
