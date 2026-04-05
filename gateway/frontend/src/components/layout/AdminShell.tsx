"use client";

/**
 * AdminShell — authenticated admin layout wrapper.
 *
 * Mobile (<lg): AdminHeader + scrollable content + AdminTabBar (fixed bottom)
 * Desktop (>=lg): sidebar nav + AdminHeader + scrollable content
 *
 * Safe-area insets applied for iPhone notch/home indicator.
 * Fetches stripeMode and stores it in adminStore on mount.
 */

import { useEffect } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { cn } from "@/lib/utils";
import { useAdminStore } from "@/store/adminStore";
import { useAuthStore } from "@/store/authStore";
import AdminTabBar from "@/components/layout/AdminTabBar";
import AdminHeader from "@/components/admin/AdminHeader";
import { initErrorReporter } from "@/services/errorReporter";

interface SidebarItem {
  href: string;
  label: string;
  icon: string;
}

const SIDEBAR_ITEMS: SidebarItem[] = [
  { href: "/admin",           label: "Overview",    icon: "##" },
  { href: "/admin/ops",       label: "Ops",         icon: ">_" },
  { href: "/admin/revenue",   label: "Revenue",     icon: "$"  },
  { href: "/admin/mila",      label: "MiLA",        icon: "AI" },
  { href: "/admin/marketing", label: "Marketing",   icon: "M"  },
  { href: "/admin/contacts",  label: "Contacts",    icon: "@"  },
  { href: "/admin/alerts",    label: "Alerts",      icon: "!"  },
  { href: "/admin/system",    label: "System",      icon: "+-" },
  { href: "/admin/more",      label: "More",        icon: "..."  },
];

interface AdminShellProps {
  children: React.ReactNode;
}

export default function AdminShell({ children }: AdminShellProps) {
  const pathname = usePathname();
  const router = useRouter();
  const { fetchStripeStatus } = useAdminStore();
  const { logout } = useAuthStore();

  useEffect(() => {
    void fetchStripeStatus();
  }, [fetchStripeStatus]);

  useEffect(() => {
    // Install global JS error + unhandledrejection capture for the admin shell.
    // Returns a cleanup function that removes event listeners on unmount.
    const cleanup = initErrorReporter();
    return cleanup;
  }, []);

  function handleRefresh() {
    router.refresh();
  }

  function handleLogout() {
    logout();
    router.push("/login");
  }

  return (
    <div
      className="flex bg-[var(--ink-950)] overflow-hidden"
      style={{ height: "100dvh" }}
    >
      {/* ── Desktop sidebar ──────────────────────────────────────────── */}
      <aside className="hidden lg:flex flex-col w-52 bg-[#080f18] border-r border-[#1a2a3d] flex-shrink-0">
        {/* Logo area */}
        <div className="h-14 flex items-center px-4 border-b border-[#1a2a3d]">
          <span className="font-heading font-bold text-[var(--gold-400)] text-sm tracking-wide">
            Command Center
          </span>
        </div>

        {/* Nav items */}
        <nav className="flex-1 p-3 flex flex-col gap-0.5 overflow-y-auto">
          {SIDEBAR_ITEMS.map((item) => {
            const isActive =
              item.href === "/admin"
                ? pathname === "/admin"
                : pathname.startsWith(item.href);

            return (
              <Link
                key={item.href}
                href={item.href}
                className={cn(
                  "flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm transition-colors duration-150",
                  isActive
                    ? "bg-[var(--gold-400)]/10 text-[var(--gold-400)] font-medium"
                    : "text-gray-400 hover:text-white hover:bg-white/5"
                )}
                aria-current={isActive ? "page" : undefined}
              >
                <span className="w-5 text-center font-mono text-xs opacity-70 flex-shrink-0">
                  {item.icon}
                </span>
                {item.label}
              </Link>
            );
          })}
        </nav>

        {/* Logout */}
        <div className="p-3 border-t border-[#1a2a3d]">
          <button
            onClick={handleLogout}
            className="w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm text-gray-500 hover:text-red-400 hover:bg-red-400/5 transition-colors"
          >
            <span className="w-5 text-center font-mono text-xs opacity-70">
              X
            </span>
            Logout
          </button>
        </div>
      </aside>

      {/* ── Main column ───────────────────────────────────────────────── */}
      <div className="flex-1 flex flex-col min-w-0">
        <AdminHeader onRefresh={handleRefresh} />

        {/* Scrollable content — bottom padding reserves space for tab bar on mobile */}
        <main
          className="flex-1 overflow-y-auto"
          style={{
            paddingBottom: "calc(56px + env(safe-area-inset-bottom))",
          }}
        >
          <div className="lg:pb-0">{children}</div>
        </main>
      </div>

      {/* ── Mobile bottom tab bar ─────────────────────────────────────── */}
      <AdminTabBar />
    </div>
  );
}
