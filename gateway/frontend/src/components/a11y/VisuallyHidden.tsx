"use client";

/**
 * VisuallyHidden.tsx — Screen-reader-only content wrapper.
 *
 * Renders children in the DOM (accessible to screen readers and other
 * assistive technology) but hides them from sighted users using the
 * standard sr-only CSS technique.
 *
 * Use this component to provide additional context that is visible only
 * to assistive technology, such as:
 *   - Icon button labels: <VisuallyHidden>Close dialog</VisuallyHidden>
 *   - Form hints: <VisuallyHidden>Required field</VisuallyHidden>
 *   - Status prefixes: <VisuallyHidden>Error:</VisuallyHidden>
 *
 * WCAG 1.1.1 — Non-text Content
 * WCAG 1.3.1 — Info and Relationships
 * WCAG 4.1.2 — Name, Role, Value
 */

import type { ReactNode, ElementType, CSSProperties } from "react";

interface VisuallyHiddenProps {
  children: ReactNode;
  /**
   * The HTML element to render. Default: "span" (inline, safe inside buttons
   * and other interactive elements).
   */
  as?: ElementType;
  /** Additional class names to merge (e.g. for layout overrides). */
  className?: string;
}

/**
 * Standard sr-only CSS technique (from Tailwind CSS source):
 *   position: absolute;
 *   width: 1px;
 *   height: 1px;
 *   padding: 0;
 *   margin: -1px;
 *   overflow: hidden;
 *   clip: rect(0 0 0 0);
 *   white-space: nowrap;
 *   border-width: 0;
 *
 * This technique keeps the element in the accessibility tree while removing
 * it from the visual flow. display:none and visibility:hidden both remove
 * elements from the accessibility tree — this does not.
 */
const SR_ONLY_STYLE: CSSProperties = {
  position: "absolute",
  width: "1px",
  height: "1px",
  padding: 0,
  margin: "-1px",
  overflow: "hidden",
  clip: "rect(0 0 0 0)",
  clipPath: "inset(50%)",
  whiteSpace: "nowrap",
  borderWidth: 0,
};

export function VisuallyHidden({
  children,
  as: Component = "span",
  className,
}: VisuallyHiddenProps) {
  return (
    <Component
      className={className ? `sr-only ${className}` : "sr-only"}
      style={SR_ONLY_STYLE}
    >
      {children}
    </Component>
  );
}
