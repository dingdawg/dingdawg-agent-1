"use client";

/**
 * LayoutEditor — dev-only visual positioning tool.
 *
 * Shows a floating toolbar (top-right). When "Edit" is on:
 *   • Hovering any element highlights it with a cyan outline
 *   • Click-drag moves it. Movement is stored as an (x, y) translate delta.
 *   • Each moved element gets a unique data-dd-editor-id stamped on it so we
 *     can restore position across reloads.
 * When "Edit" is off the page is completely untouched.
 *
 * Persistence: localStorage["dd-layout-editor-v1"] = {
 *   [elementId]: { x: number, y: number, selector: string }
 * }
 *
 * Export: "Export" button copies JSON to clipboard AND prints the diff to the
 * console as a CSS-ready snippet you can paste into the source.
 *
 * Dev-gate: renders only when NEXT_PUBLIC_DEV_BYPASS_AUTH=1 (same flag that
 * already unlocks the UI) OR NODE_ENV !== production. Never ships in prod.
 */

import { useEffect, useRef, useState, useCallback } from "react";

const STORAGE_KEY = "dd-layout-editor-v1";

type Position = { x: number; y: number; selector: string };
type PositionMap = Record<string, Position>;

function loadPositions(): PositionMap {
  if (typeof window === "undefined") return {};
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    return raw ? (JSON.parse(raw) as PositionMap) : {};
  } catch {
    return {};
  }
}

function savePositions(map: PositionMap) {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(map));
  } catch {
    /* ignore */
  }
}

// Build a stable selector for a given element. The random data-dd-editor-id
// is NOT used here (it doesn't survive reloads). Prefer real id, then a
// tag+first-class+nth-child path walked up to body. This selector must be
// findable on a fresh page load so the editor can re-apply the transform.
function selectorFor(el: HTMLElement): string {
  if (el.id) return `#${CSS.escape(el.id)}`;
  const path: string[] = [];
  let cur: HTMLElement | null = el;
  while (cur && cur !== document.body && path.length < 8) {
    let part = cur.tagName.toLowerCase();
    if (cur.className && typeof cur.className === "string") {
      // First non-Tailwind-variant class is the stablest anchor.
      const firstClass = cur.className
        .split(/\s+/)
        .filter(Boolean)
        .find((c) => !c.includes(":") && !/^[a-z-]+\[/.test(c));
      if (firstClass) {
        try {
          part += "." + CSS.escape(firstClass);
        } catch {
          /* bad class, skip */
        }
      }
    }
    const parent = cur.parentElement;
    if (parent) {
      const siblings = Array.from(parent.children);
      const ix = siblings.indexOf(cur);
      if (ix >= 0) part += `:nth-child(${ix + 1})`;
    }
    path.unshift(part);
    cur = cur.parentElement;
  }
  return path.join(" > ");
}

// Stamp a persistent editor ID on an element so we can find it again later.
function stampId(el: HTMLElement): string {
  if (!el.dataset.ddEditorId) {
    el.dataset.ddEditorId = `dd-${Math.random().toString(36).slice(2, 10)}`;
  }
  return el.dataset.ddEditorId;
}

function applyTransform(el: HTMLElement, x: number, y: number) {
  el.style.transform = `translate(${x}px, ${y}px)`;
  el.style.willChange = "transform";
  el.dataset.ddEditorMoved = "true";
}

function clearTransform(el: HTMLElement) {
  el.style.transform = "";
  el.style.willChange = "";
  delete el.dataset.ddEditorMoved;
}

export function LayoutEditor() {
  const [editMode, setEditMode] = useState(false);
  const [hoverEl, setHoverEl] = useState<HTMLElement | null>(null);
  const [positions, setPositions] = useState<PositionMap>({});
  const draggingRef = useRef<{
    el: HTMLElement;
    id: string;
    startX: number;
    startY: number;
    baseX: number;
    baseY: number;
  } | null>(null);

  // Dev gate — only show in development with bypass flag.
  const isDev =
    process.env.NODE_ENV === "development" &&
    process.env.NEXT_PUBLIC_DEV_BYPASS_AUTH === "1";

  // ── restore positions on mount ──
  useEffect(() => {
    if (!isDev) return;
    const saved = loadPositions();
    setPositions(saved);
    // Apply after a tick so hydration is done. We look up the element by:
    //   1. its previously stamped data-dd-editor-id  (only works if the DOM
    //      still has the stamp — will NOT after a hard reload).
    //   2. fallback to the stored CSS selector we captured at save time.
    // If found via selector we RE-STAMP with the original ID so subsequent
    // drags and exports refer to the same persistent identity.
    const reapply = () => {
      for (const [id, pos] of Object.entries(saved)) {
        let node = document.querySelector<HTMLElement>(
          `[data-dd-editor-id="${id}"]`
        );
        if (!node && pos.selector) {
          try {
            node = document.querySelector<HTMLElement>(pos.selector);
          } catch {
            /* ignore bad selectors */
          }
        }
        if (node) {
          // Re-stamp so drags and exports use the same id.
          if (!node.dataset.ddEditorId) {
            node.dataset.ddEditorId = id;
          }
          applyTransform(node, pos.x, pos.y);
        }
      }
    };
    // Two passes: immediately (cheap) + after layout settles (catches late mounts)
    requestAnimationFrame(reapply);
    const t = setTimeout(reapply, 1500);
    return () => clearTimeout(t);
  }, [isDev]);

  // ── highlight on hover while in edit mode ──
  useEffect(() => {
    if (!isDev || !editMode) {
      setHoverEl(null);
      return;
    }
    const onMove = (e: MouseEvent) => {
      if (draggingRef.current) return;
      const target = e.target as HTMLElement | null;
      if (!target) return;
      if (target.closest("[data-dd-editor-toolbar]")) return;
      setHoverEl(target);
    };
    document.addEventListener("mousemove", onMove);
    return () => document.removeEventListener("mousemove", onMove);
  }, [isDev, editMode]);

  // ── pointer-down on any element starts a drag ──
  useEffect(() => {
    if (!isDev || !editMode) return;

    const onDown = (e: PointerEvent) => {
      const target = e.target as HTMLElement | null;
      if (!target) return;
      if (target.closest("[data-dd-editor-toolbar]")) return;
      e.preventDefault();
      e.stopPropagation();

      // Compute stable selector BEFORE stamping — otherwise selectorFor would
      // short-circuit to the ephemeral ID and nothing survives reloads.
      const selector = selectorFor(target);
      const id = stampId(target);
      // Stale saved state may key on the ID OR on the selector. Merge both.
      const stored = loadPositions();
      const existing = stored[id] ?? stored[selector];
      draggingRef.current = {
        el: target,
        id,
        startX: e.clientX,
        startY: e.clientY,
        baseX: existing?.x ?? 0,
        baseY: existing?.y ?? 0,
      };
      // Cache the computed selector on the element so onUp can write it.
      target.dataset.ddEditorSelector = selector;
      target.setPointerCapture(e.pointerId);
    };

    const onMove = (e: PointerEvent) => {
      const drag = draggingRef.current;
      if (!drag) return;
      e.preventDefault();
      const dx = e.clientX - drag.startX + drag.baseX;
      const dy = e.clientY - drag.startY + drag.baseY;
      applyTransform(drag.el, dx, dy);
    };

    const onUp = (e: PointerEvent) => {
      const drag = draggingRef.current;
      if (!drag) return;
      drag.el.releasePointerCapture(e.pointerId);
      const finalX = e.clientX - drag.startX + drag.baseX;
      const finalY = e.clientY - drag.startY + drag.baseY;
      // Use the selector captured in onDown — that one was computed BEFORE
      // the stamp, so it's the stable path-based selector.
      const storedSelector =
        drag.el.dataset.ddEditorSelector || selectorFor(drag.el);
      const updated: PositionMap = {
        ...loadPositions(),
        [drag.id]: {
          x: finalX,
          y: finalY,
          selector: storedSelector,
        },
      };
      savePositions(updated);
      setPositions(updated);
      draggingRef.current = null;
    };

    document.addEventListener("pointerdown", onDown, true);
    document.addEventListener("pointermove", onMove, true);
    document.addEventListener("pointerup", onUp, true);
    return () => {
      document.removeEventListener("pointerdown", onDown, true);
      document.removeEventListener("pointermove", onMove, true);
      document.removeEventListener("pointerup", onUp, true);
    };
  }, [isDev, editMode]);

  // ── export / reset helpers ──
  const handleExport = useCallback(() => {
    const data = loadPositions();
    const pretty = JSON.stringify(data, null, 2);
    try {
      navigator.clipboard.writeText(pretty);
    } catch {
      /* clipboard may fail in some webviews; console is the fallback */
    }
    // Also dump a CSS snippet for quick copy/paste into source.
    const lines: string[] = [];
    for (const [id, pos] of Object.entries(data)) {
      lines.push(
        `/* ${pos.selector} */`,
        `[data-dd-editor-id="${id}"] {`,
        `  transform: translate(${pos.x}px, ${pos.y}px);`,
        `}`,
        ``
      );
    }
    console.group("[LayoutEditor] Exported positions");
    console.log(pretty);
    console.log("--- CSS snippet ---");
    console.log(lines.join("\n"));
    console.groupEnd();
    alert(
      `Copied ${Object.keys(data).length} positions to clipboard.\n\nAlso dumped CSS snippet to console.`
    );
  }, []);

  const handleReset = useCallback(() => {
    if (!confirm("Reset all layout edits? This removes every saved position.")) return;
    const data = loadPositions();
    for (const id of Object.keys(data)) {
      const node = document.querySelector<HTMLElement>(
        `[data-dd-editor-id="${id}"]`
      );
      if (node) clearTransform(node);
    }
    window.localStorage.removeItem(STORAGE_KEY);
    setPositions({});
  }, []);

  if (!isDev) return null;

  const count = Object.keys(positions).length;

  return (
    <>
      {/* Hover outline */}
      {editMode && hoverEl && <HoverOutline el={hoverEl} />}

      {/* Toolbar */}
      <div
        data-dd-editor-toolbar="true"
        style={{
          position: "fixed",
          top: 12,
          right: 12,
          zIndex: 2147483647, // always on top
          display: "flex",
          gap: 6,
          alignItems: "center",
          background: "rgba(10,12,18,0.92)",
          backdropFilter: "blur(6px)",
          border: "1px solid rgba(245,184,0,0.3)",
          borderRadius: 8,
          padding: "6px 8px",
          color: "#fff",
          fontFamily:
            "ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, sans-serif",
          fontSize: 12,
          boxShadow: "0 8px 24px rgba(0,0,0,0.4)",
          pointerEvents: "auto",
        }}
      >
        <span style={{ opacity: 0.7, paddingRight: 4 }}>
          🎯 Layout Editor
        </span>
        <button
          type="button"
          onClick={() => setEditMode((v) => !v)}
          style={toolbarBtnStyle(editMode ? "#f5b800" : "transparent", editMode ? "#0a0c12" : "#fff")}
        >
          {editMode ? "Editing… (click to stop)" : "Enable edit mode"}
        </button>
        <button
          type="button"
          onClick={handleExport}
          style={toolbarBtnStyle("transparent", "#fff")}
          disabled={count === 0}
        >
          Export ({count})
        </button>
        <button
          type="button"
          onClick={handleReset}
          style={toolbarBtnStyle("transparent", "#fca5a5")}
          disabled={count === 0}
        >
          Reset
        </button>
      </div>

      {/* Edit-mode global cursor + disable anchor/button clicks so drag works */}
      {editMode && (
        <style>{`
          body { cursor: move !important; }
          [data-dd-editor-toolbar] { cursor: auto !important; }
          [data-dd-editor-toolbar] button { cursor: pointer !important; }
          /* Prevent link navigation / button clicks while editing */
          a, button:not([data-dd-editor-toolbar] button) {
            pointer-events: none !important;
          }
          /* Allow drag interception on everything */
          * { user-select: none !important; }
        `}</style>
      )}
    </>
  );
}

function HoverOutline({ el }: { el: HTMLElement }) {
  const [rect, setRect] = useState<DOMRect | null>(null);
  useEffect(() => {
    setRect(el.getBoundingClientRect());
  }, [el]);
  if (!rect) return null;
  return (
    <div
      style={{
        position: "fixed",
        top: rect.top,
        left: rect.left,
        width: rect.width,
        height: rect.height,
        outline: "2px solid #22d3ee",
        outlineOffset: -2,
        pointerEvents: "none",
        zIndex: 2147483646,
        background: "rgba(34, 211, 238, 0.07)",
      }}
    />
  );
}

function toolbarBtnStyle(bg: string, color: string): React.CSSProperties {
  return {
    background: bg,
    color,
    border: "1px solid rgba(255,255,255,0.15)",
    borderRadius: 6,
    padding: "4px 8px",
    fontSize: 12,
    fontWeight: 600,
    cursor: "pointer",
  };
}
