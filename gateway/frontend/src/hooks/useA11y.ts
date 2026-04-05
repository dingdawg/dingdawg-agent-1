/**
 * useA11y.ts — React hooks for WCAG 2.1 AA accessibility patterns
 *
 * All hooks are tree-shakeable named exports with zero side effects
 * when not called. No new npm dependencies.
 *
 * WCAG criteria addressed:
 *   2.1.1  Keyboard — useFocusTrap, useArrowNavigation
 *   2.4.1  Bypass Blocks — useRouteAnnounce
 *   2.4.2  Page Titled — useRouteAnnounce
 *   2.4.3  Focus Order — useFocusTrap
 *   2.3.3  Animation from Interactions — useReducedMotion
 *   4.1.3  Status Messages — useAnnounce, useRouteAnnounce
 */

import {
  useEffect,
  useRef,
  useState,
  useCallback,
  type RefObject,
} from "react";
import {
  trapFocus,
  announce,
  prefersReducedMotion,
  onMotionPreferenceChange,
  handleArrowKeys,
  createLiveRegion,
} from "../lib/a11y";

// Re-export the a11y utilities so consumers can import from one place.
export { trapFocus, announce, prefersReducedMotion, createLiveRegion };

// ---------------------------------------------------------------------------
// useFocusTrap — WCAG 2.1.1, 2.4.3
// ---------------------------------------------------------------------------

interface FocusTrapOptions {
  /** Called when Escape is pressed while the trap is active. */
  onDeactivate?: () => void;
}

/**
 * Trap keyboard focus inside an element (modal/dialog pattern).
 *
 * When `active` is true:
 *   - Tab and Shift+Tab cycle through the container's focusable children.
 *   - Pressing Escape calls `onDeactivate` if provided.
 *
 * The trap is automatically removed when `active` becomes false or the
 * component unmounts.
 *
 * Usage:
 *   const ref = useRef<HTMLDivElement>(null);
 *   useFocusTrap(ref, isOpen, { onDeactivate: () => setIsOpen(false) });
 *
 * WCAG 2.1.1 — Keyboard, 2.4.3 — Focus Order
 */
export function useFocusTrap(
  ref: RefObject<HTMLElement>,
  active: boolean = true,
  options: FocusTrapOptions = {}
): void {
  const { onDeactivate } = options;
  const cleanupRef = useRef<(() => void) | null>(null);
  // Save the element that was focused before the trap activated so we can
  // restore it when the trap deactivates.
  const previouslyFocusedRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!active || !ref.current) return;

    // Save current focus
    previouslyFocusedRef.current = document.activeElement as HTMLElement;

    // Activate the trap
    cleanupRef.current = trapFocus(ref.current);

    // Handle Escape key
    function handleEscape(event: KeyboardEvent): void {
      if (event.key === "Escape" && onDeactivate) {
        onDeactivate();
      }
    }

    document.addEventListener("keydown", handleEscape);

    return () => {
      // Clean up the focus trap event listener
      if (cleanupRef.current) {
        cleanupRef.current();
        cleanupRef.current = null;
      }

      document.removeEventListener("keydown", handleEscape);

      // Restore focus to the previously focused element
      if (previouslyFocusedRef.current) {
        try {
          previouslyFocusedRef.current.focus();
        } catch {
          // Element may have been removed from DOM — fail silently.
        }
      }
    };
  }, [active, ref, onDeactivate]);
}

// ---------------------------------------------------------------------------
// useAnnounce — WCAG 4.1.3
// ---------------------------------------------------------------------------

/**
 * Returns an `announce` function that broadcasts a message to screen readers
 * via an `aria-live` region.
 *
 * The returned function is stable across renders (memoized with useCallback).
 *
 * Usage:
 *   const announce = useAnnounce();
 *   announce("Item saved", "polite");
 *   announce("Error: required field missing", "assertive");
 *
 * WCAG 4.1.3 — Status Messages
 */
export function useAnnounce(): (
  message: string,
  priority?: "polite" | "assertive"
) => void {
  return useCallback(
    (message: string, priority: "polite" | "assertive" = "polite") => {
      announce(message, priority);
    },
    [] // No deps — announce() is a pure function
  );
}

// ---------------------------------------------------------------------------
// useReducedMotion — WCAG 2.3.3
// ---------------------------------------------------------------------------

/**
 * Returns true if the user has enabled "reduce motion" in their OS settings.
 * Reactively updates when the preference changes (e.g., toggled in System Prefs).
 *
 * Usage:
 *   const reduced = useReducedMotion();
 *   const duration = reduced ? 0 : 0.3;
 *
 * WCAG 2.3.3 — Animation from Interactions (AAA, but widely expected at AA)
 */
export function useReducedMotion(): boolean {
  const [prefersReduced, setPrefersReduced] = useState<boolean>(() =>
    prefersReducedMotion()
  );

  useEffect(() => {
    const cleanup = onMotionPreferenceChange((prefers) => {
      setPrefersReduced(prefers);
    });
    return cleanup;
  }, []);

  return prefersReduced;
}

// ---------------------------------------------------------------------------
// useArrowNavigation — WCAG 2.1.1
// ---------------------------------------------------------------------------

interface ArrowNavOptions {
  /**
   * CSS selector to find navigable items within the container.
   * Default: "button, a[href], [tabindex]:not([tabindex='-1'])"
   */
  selector?: string;
  /** Axis for arrow key navigation. Default: "vertical" */
  orientation?: "horizontal" | "vertical" | "both";
  /** Wrap from last to first and vice versa. Default: false */
  wrap?: boolean;
}

/**
 * Manage arrow-key navigation within a list or menu container.
 *
 * Attaches a keydown listener to the container ref and tracks the active
 * index. Consumer is responsible for applying aria-activedescendant or
 * focus management to match the activeIndex.
 *
 * Usage:
 *   const ref = useRef<HTMLUListElement>(null);
 *   const { activeIndex } = useArrowNavigation(ref, {
 *     selector: "li[role='option']",
 *     orientation: "vertical",
 *     wrap: true,
 *   });
 *
 * WCAG 2.1.1 — Keyboard
 */
export function useArrowNavigation(
  ref: RefObject<HTMLElement>,
  options: ArrowNavOptions = {}
): { activeIndex: number; setActiveIndex: (i: number) => void } {
  const {
    selector = "button, a[href], [tabindex]:not([tabindex='-1'])",
    orientation = "vertical",
    wrap = false,
  } = options;

  const [activeIndex, setActiveIndex] = useState(0);
  // Keep a ref to activeIndex so the event handler closure always has
  // the current value without needing to be re-created every render.
  const activeIndexRef = useRef(activeIndex);
  activeIndexRef.current = activeIndex;

  useEffect(() => {
    const container = ref.current;
    if (!container) return;

    function handleKeyDown(event: KeyboardEvent): void {
      const el = ref.current;
      if (!el) return;

      const items = Array.from(el.querySelectorAll<HTMLElement>(selector));
      if (items.length === 0) return;

      // Invoke the shared arrow-key handler — it calls .focus() on the
      // target item, updating document.activeElement.
      handleArrowKeys(event, items, { orientation, wrap });

      // Sync our index state to match whatever element received focus.
      const newActive = document.activeElement as HTMLElement;
      const newIndex = items.indexOf(newActive);
      if (newIndex !== -1 && newIndex !== activeIndexRef.current) {
        setActiveIndex(newIndex);
      }
    }

    container.addEventListener("keydown", handleKeyDown);
    return () => container.removeEventListener("keydown", handleKeyDown);
    // Intentionally exclude activeIndex from deps — we read it via ref.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ref, selector, orientation, wrap]);

  return { activeIndex, setActiveIndex };
}

// ---------------------------------------------------------------------------
// useRouteAnnounce — WCAG 2.4.2, 4.1.3
// ---------------------------------------------------------------------------

/**
 * Announce the page title to screen readers whenever it changes.
 *
 * Place this hook in your root layout or per-page component:
 *   useRouteAnnounce("Dashboard | DingDawg");
 *
 * On the initial render nothing is announced (the user is already on the page).
 * On subsequent renders (route changes), the new title is announced politely.
 *
 * WCAG 2.4.2 — Page Titled, 4.1.3 — Status Messages
 */
export function useRouteAnnounce(title: string): void {
  const isFirstRender = useRef(true);

  useEffect(() => {
    if (isFirstRender.current) {
      // Skip initial render — the page title is already visible.
      isFirstRender.current = false;

      // Pre-create the live region so it's in the DOM for future
      // announcements. Screen readers observe regions that exist on page load
      // more reliably than dynamically-injected ones.
      createLiveRegion("a11y-announcer-polite", "polite");
      return;
    }

    // Announce the new page title after navigation.
    announce(`Navigated to ${title}`, "polite");
  }, [title]);
}
