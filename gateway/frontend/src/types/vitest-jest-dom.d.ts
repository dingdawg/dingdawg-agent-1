/**
 * Augments Vitest's Assertion interface with @testing-library/jest-dom matchers.
 *
 * This file is picked up automatically by tsconfig (include: ["**\/*.ts"]).
 * It makes matchers like toHaveAttribute, toBeDisabled, toBeInTheDocument etc.
 * available on every `expect(...)` call in test files without requiring a
 * triple-slash reference in each file.
 *
 * The @testing-library/jest-dom package ships a ready-made vitest augmentation
 * at `@testing-library/jest-dom/types/vitest.d.ts` — we re-export it here so
 * tsconfig can see it even though vitest.setup.ts is excluded from compilation.
 */

import "@testing-library/jest-dom/vitest";
