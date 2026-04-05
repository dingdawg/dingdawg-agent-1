"use client";

/**
 * AppShell — unified authenticated layout.
 *
 * Desktop: collapsible sidebar (260px full / 64px icon-only) + header + content
 * Mobile:  overlay drawer sidebar + header with hamburger + content
 *
 * Sidebar state persists in localStorage.
 * All protected pages wrap: <ProtectedRoute><AppShell>{children}</AppShell></ProtectedRoute>
 */

import { useEffect, useRef, useState, useCallback } from "react";
import { usePathname, useRouter } from "next/navigation";
import { AnimatePresence, motion } from "framer-motion";
import { Menu, ChevronRight } from "lucide-react";
import { useAuthStore } from "@/store/authStore";
import { useAgentStore } from "@/store/agentStore";
import { useSessionStore } from "@/store/sessionStore";
import LanguageSwitcher from "@/components/ui/LanguageSwitcher";
import { AgenticAssistant } from "@/components/assistant/AgenticAssistant";
import Sidebar from "./Sidebar";
import { MobileBottomNav } from "./MobileBottomNav";

const LS_COLLAPSED_KEY = "dd_sidebar_collapsed";

interface AppShellProps {
  children: React.ReactNode;
}

export function AppShell({ children }: AppShellProps) {
  const pathname = usePathname();
  const router = useRouter();
  const { user, logout } = useAuthStore();
  const { currentAgent, agents, fetchAgents, isLoading, error } = useAgentStore();
  const { sessions, activeSessionId } = useSessionStore();

  // Mobile: drawer open/closed (always starts closed on mobile)
  const [mobileOpen, setMobileOpen] = useState(false);

  // Desktop: icon-only collapsed state — persisted in localStorage
  const [desktopCollapsed, setDesktopCollapsed] = useState<boolean>(() => {
    if (typeof window === "undefined") return false;
    try {
      return localStorage.getItem(LS_COLLAPSED_KEY) === "true";
    } catch {
      return false;
    }
  });

  const toggleDesktopCollapsed = useCallback(() => {
    setDesktopCollapsed((prev) => {
      const next = !prev;
      try {
        localStorage.setItem(LS_COLLAPSED_KEY, String(next));
      } catch { /* ignore */ }
      return next;
    });
  }, []);

  const openMobile = useCallback(() => setMobileOpen(true), []);
  const closeMobile = useCallback(() => setMobileOpen(false), []);
  const toggleMobile = useCallback(() => setMobileOpen((p) => !p), []);

  useEffect(() => {
    fetchAgents();
  }, [fetchAgents]);

  // Close mobile drawer on route change — desktop sidebar is unaffected
  const prevPathRef = useRef(pathname);
  useEffect(() => {
    if (prevPathRef.current !== pathname) {
      setMobileOpen(false);
      prevPathRef.current = pathname;
    }
  }, [pathname]);

  // Show loading skeleton while agents are loading (prevents content flash)
  if (isLoading && agents.length === 0) {
    return (
      <div className="flex overflow-hidden bg-[var(--background)]" style={{ height: "100dvh" }}>
        <div className="hidden md:block w-[260px] bg-[var(--ink-950)] border-r border-[var(--stroke)] flex-shrink-0">
          <div className="p-3 mt-4">
            <div className="h-10 w-full rounded-lg bg-[var(--ink-800)] animate-pulse mb-4" />
            <div className="h-10 w-full rounded-lg bg-[var(--ink-800)] animate-pulse mb-2" />
            <div className="h-10 w-full rounded-lg bg-[var(--ink-800)] animate-pulse mb-2" />
          </div>
        </div>
        <div className="flex-1 flex flex-col">
          <div className="h-12 bg-[var(--ink-950)] border-b border-[var(--stroke)]" />
          <div className="flex-1 p-6">
            <div className="h-8 w-48 bg-[var(--ink-800)] rounded animate-pulse mb-4" />
            <div className="h-4 w-96 bg-[var(--ink-800)] rounded animate-pulse mb-2" />
            <div className="h-4 w-72 bg-[var(--ink-800)] rounded animate-pulse" />
          </div>
        </div>
      </div>
    );
  }

  // Show error state if agent fetch failed
  if (error && !isLoading && agents.length === 0) {
    return (
      <div className="flex items-center justify-center min-h-screen bg-[var(--background)]">
        <div className="text-center p-8 max-w-md">
          <p className="text-[var(--ink-400)] mb-4">Unable to connect to the server</p>
          <button
            onClick={() => fetchAgents()}
            className="px-4 py-2 bg-[var(--gold-500)] text-[var(--ink-950)] rounded-lg font-medium hover:bg-[var(--gold-400)] transition-colors"
          >
            Try Again
          </button>
        </div>
      </div>
    );
  }

  const handleLogout = () => {
    logout();
    router.push("/login");
  };

  return (
    <div className="flex overflow-hidden bg-[var(--background)]" style={{ height: "100dvh" }}>
      {/* ── Sidebar ─────────────────────────────────────────────────── */}
      <Sidebar
        /* Mobile drawer props */
        isOpen={mobileOpen}
        onToggle={toggleMobile}
        /* Desktop collapse props */
        isCollapsed={desktopCollapsed}
        onCollapseToggle={toggleDesktopCollapsed}
        /* Data props */
        sessions={sessions.map((s) => ({
          id: s.session_id,
          title: `Session ${s.session_id.slice(0, 8)}`,
          messageCount: s.message_count ?? 0,
          updatedAt: s.created_at ?? "",
        }))}
        activeSessionId={activeSessionId ?? null}
        onNewSession={() => { router.push("/dashboard"); }}
        onSwitchSession={(id: string) => { router.push(`/dashboard?session=${id}`); }}
        onDeleteSession={() => { router.push("/dashboard"); }}
        onSearch={() => {}}
        user={user ? { email: user.email, user_id: user.id } : null}
        agentName={currentAgent?.name ?? "DingDawg"}
        currentPath={pathname}
        onLogout={handleLogout}
      />

      {/* ── Main column ──────────────────────────────────────────────── */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Header */}
        <header
          className="flex items-center justify-between min-h-12 px-4 border-b border-[var(--stroke)]/50 flex-shrink-0"
          style={{ paddingTop: "calc(env(safe-area-inset-top, 0px) + 8px)" }}
        >
          {/* Mobile: hamburger to open drawer */}
          <button
            onClick={openMobile}
            className="md:hidden flex items-center justify-center h-9 w-9 min-h-[44px] min-w-[44px] rounded-lg text-[var(--color-muted)] hover:text-[var(--foreground)] hover:bg-white/5 transition-colors"
            aria-label="Open sidebar"
          >
            <Menu className="h-5 w-5" />
          </button>

          {/* Desktop: expand button shown only when sidebar is collapsed */}
          {desktopCollapsed && (
            <button
              onClick={toggleDesktopCollapsed}
              className="hidden md:flex items-center justify-center h-9 w-9 min-h-[44px] min-w-[44px] rounded-lg text-[var(--color-muted)] hover:text-[var(--foreground)] hover:bg-white/5 transition-colors"
              aria-label="Expand sidebar"
              title="Expand sidebar"
            >
              <ChevronRight className="h-5 w-5" />
            </button>
          )}

          {/* Spacer when sidebar is expanded on desktop */}
          {!desktopCollapsed && <div className="hidden md:block" />}

          {/* Agent name center */}
          {currentAgent && (
            <div className="flex items-center gap-2">
              <span className="h-2 w-2 rounded-full bg-[var(--color-success)]" />
              <span className="text-sm font-medium text-[var(--foreground)]">
                {currentAgent.name}
              </span>
            </div>
          )}

          {/* Right: language switcher */}
          <div className="flex items-center gap-2">
            <LanguageSwitcher />
          </div>
        </header>

        {/* Content — AnimatePresence gives each route a fade-in */}
        {/*
         * pb-[56px] md:pb-0 — reserves space for the mobile bottom nav bar
         * (56px tall) so page content is never obscured by it on mobile.
         * On desktop the bottom nav is hidden so no padding is needed.
         */}
        <main className="flex-1 overflow-hidden pb-[56px] md:pb-0">
          <AnimatePresence mode="wait" initial={false}>
            <motion.div
              key={pathname}
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.15 }}
              style={{ height: "100%", display: "flex", flexDirection: "column" }}
            >
              {children}
            </motion.div>
          </AnimatePresence>
        </main>
      </div>

      {/* ── Mobile bottom navigation bar (hidden md+) ────────────────── */}
      <MobileBottomNav />

      {/* ── Floating agentic assistant (non-dashboard pages only) ────── */}
      <AgenticAssistant />
    </div>
  );
}
