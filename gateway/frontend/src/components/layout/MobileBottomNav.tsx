"use client";

/**
 * MobileBottomNav — fixed bottom navigation bar, mobile only.
 *
 * Visible only below the `md` breakpoint (hidden on desktop — desktop keeps
 * the sidebar). Provides thumb-reachable access to the 5 key sections without
 * requiring the user to open the hamburger drawer.
 *
 * Safe-area padding handles notched / home-indicator phones (iOS + Android).
 */

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  LayoutDashboard,
  Compass,
  Briefcase,
  ClipboardList,
  Settings,
} from "lucide-react";

/* ────────────────────────────────────────────────────────────────────────── */
/*  Nav config — 5 distinct destinations, mirrors Sidebar NAV_ITEMS          */
/* ────────────────────────────────────────────────────────────────────────── */

const BOTTOM_NAV_ITEMS = [
  { label: "Home", icon: LayoutDashboard, path: "/dashboard" },
  { label: "Explore", icon: Compass, path: "/explore" },
  { label: "Work", icon: Briefcase, path: "/operations" },
  { label: "Tasks", icon: ClipboardList, path: "/tasks" },
  { label: "Settings", icon: Settings, path: "/settings" },
] as const;

/* ────────────────────────────────────────────────────────────────────────── */
/*  Component                                                                 */
/* ────────────────────────────────────────────────────────────────────────── */

export function MobileBottomNav() {
  const pathname = usePathname();

  return (
    /*
     * md:hidden — completely removed from the DOM on desktop so it never
     * interferes with the sidebar layout or keyboard focus order.
     *
     * fixed bottom-0 — sits above all page content.
     * z-40 — below the mobile drawer backdrop (z-40) and drawer (z-50) so
     *         the drawer overlays cleanly.
     * safe-area padding — env(safe-area-inset-bottom) prevents the bar from
     *         being obscured by the iOS home indicator or Android gesture bar.
     */
    <nav
      className="md:hidden fixed bottom-0 inset-x-0 z-30 flex items-stretch border-t border-[var(--stroke)] bg-[var(--ink-950)]/95 backdrop-blur-md"
      style={{ paddingBottom: "env(safe-area-inset-bottom, 0px)" }}
      aria-label="Mobile navigation"
    >
      {BOTTOM_NAV_ITEMS.map((item) => {
        const active =
          item.path === "/operations"
            ? pathname.startsWith("/operations")
            : pathname === item.path;

        return (
          <Link
            key={`${item.label}-${item.path}`}
            href={item.path}
            className={`relative flex flex-1 flex-col items-center justify-center gap-0.5 min-h-[56px] px-1 transition-colors ${
              active
                ? "text-[var(--gold-500)]"
                : "text-[var(--color-muted)] hover:text-[var(--foreground)]"
            }`}
            aria-label={item.label}
            aria-current={active ? "page" : undefined}
          >
            {/* Active indicator — thin gold line at top of nav item */}
            <span
              className={`absolute top-0 left-1/2 -translate-x-1/2 h-[2px] w-8 rounded-full transition-opacity ${
                active ? "bg-[var(--gold-500)] opacity-100" : "opacity-0"
              }`}
              aria-hidden="true"
            />

            <item.icon
              size={22}
              className={`shrink-0 transition-transform ${
                active ? "scale-110" : "scale-100"
              }`}
              strokeWidth={active ? 2.5 : 1.75}
            />
            <span className="text-[10px] font-medium leading-none tracking-wide">
              {item.label}
            </span>
          </Link>
        );
      })}
    </nav>
  );
}
