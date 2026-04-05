"use client";

/**
 * SkipLink.tsx — "Skip to main content" link for keyboard users.
 *
 * Visually hidden until focused via Tab key. When focused it slides into
 * view at the top of the viewport. Activating it scrolls and focuses the
 * target element, bypassing repeated navigation blocks.
 *
 * Usage (insert as first child of <body> or root layout):
 *   <SkipLink targetId="main-content" />
 *   <header>...</header>
 *   <main id="main-content">...</main>
 *
 * WCAG 2.4.1 — Bypass Blocks
 * WCAG 2.4.3 — Focus Order
 */

interface SkipLinkProps {
  /** The id of the element to skip to. Must exist in the DOM. */
  targetId: string;
  /** Link label. Default: "Skip to main content" */
  label?: string;
}

export function SkipLink({
  targetId,
  label = "Skip to main content",
}: SkipLinkProps) {
  return (
    <a
      href={`#${targetId}`}
      className="skip-link"
      /**
       * Inline styles implement the standard sr-only + focus-visible pattern.
       * The `skip-link` className allows the consumer to override via CSS.
       * Tailwind utility equivalent:
       *   sr-only focus:not-sr-only focus:fixed focus:top-4 focus:left-4
       *   focus:z-[9999] focus:px-4 focus:py-2
       */
      style={{
        position: "absolute",
        top: 0,
        left: 0,
        width: "1px",
        height: "1px",
        padding: 0,
        margin: "-1px",
        overflow: "hidden",
        clip: "rect(0 0 0 0)",
        clipPath: "inset(50%)",
        whiteSpace: "nowrap",
        border: 0,
        zIndex: 9999,
      }}
      onFocus={(e) => {
        const el = e.currentTarget;
        // Reveal the link when focused
        el.style.width = "auto";
        el.style.height = "auto";
        el.style.padding = "0.625rem 1.25rem";
        el.style.margin = "0.5rem";
        el.style.overflow = "visible";
        el.style.clip = "auto";
        el.style.clipPath = "none";
        el.style.whiteSpace = "normal";
        el.style.borderRadius = "0.375rem";
        el.style.background = "var(--gold-500, #f6b400)";
        el.style.color = "var(--ink-950, #07111c)";
        el.style.fontWeight = "700";
        el.style.fontSize = "0.875rem";
        el.style.textDecoration = "none";
        el.style.boxShadow = "0 0 0 3px var(--gold-500, #f6b400)";
      }}
      onBlur={(e) => {
        const el = e.currentTarget;
        // Hide again when focus leaves
        el.style.width = "1px";
        el.style.height = "1px";
        el.style.padding = "0";
        el.style.margin = "-1px";
        el.style.overflow = "hidden";
        el.style.clip = "rect(0 0 0 0)";
        el.style.clipPath = "inset(50%)";
        el.style.whiteSpace = "nowrap";
        el.style.border = "0";
        el.style.borderRadius = "0";
        el.style.background = "";
        el.style.color = "";
        el.style.fontWeight = "";
        el.style.fontSize = "";
        el.style.textDecoration = "";
        el.style.boxShadow = "";
      }}
      onClick={(e) => {
        e.preventDefault();
        const target = document.getElementById(targetId);
        if (target) {
          // Make target focusable if it isn't already
          if (!target.getAttribute("tabindex")) {
            target.setAttribute("tabindex", "-1");
          }
          target.focus();
          target.scrollIntoView({ behavior: "smooth", block: "start" });
        }
      }}
    >
      {label}
    </a>
  );
}
