"use client";

/**
 * Top navigation bar with branding, page links, and user controls.
 *
 * Links shown when authenticated:
 *   Dashboard  /dashboard
 *   Tasks      /tasks
 *   Explore    /explore  (always visible)
 *
 * "Claim Agent" link shown when authenticated but user has no agents yet.
 */

import Link from "next/link";
import Image from "next/image";
import { usePathname } from "next/navigation";
import { Menu, LogOut, LayoutDashboard, ClipboardList, Compass, Sparkles, BarChart3 } from "lucide-react";
import { useAuthStore } from "@/store/authStore";
import { useAgentStore } from "@/store/agentStore";
import { cn } from "@/lib/utils";

interface NavbarProps {
  onToggleSidebar?: () => void;
}

// ─── Nav link ─────────────────────────────────────────────────────────────────

function NavLink({
  href,
  icon,
  label,
  active,
}: {
  href: string;
  icon: React.ReactNode;
  label: string;
  active: boolean;
}) {
  return (
    <Link
      href={href}
      className={cn(
        "flex items-center gap-1.5 px-2.5 py-1.5 rounded-md text-sm transition-colors",
        active
          ? "text-[var(--gold-500)] bg-[var(--gold-500)]/10"
          : "text-[var(--color-muted)] hover:text-[var(--foreground)] hover:bg-white/5"
      )}
    >
      {icon}
      <span className="hidden sm:inline">{label}</span>
    </Link>
  );
}

// ─── Navbar ───────────────────────────────────────────────────────────────────

export function Navbar({ onToggleSidebar }: NavbarProps) {
  const { user, logout, isAuthenticated } = useAuthStore();
  const { agents } = useAgentStore();
  const pathname = usePathname();

  const hasAgents = agents.length > 0;

  return (
    <nav className="flex items-center justify-between min-h-14 px-4 border-b border-[var(--stroke)] bg-[var(--ink-950)] lg:bg-[var(--glass)] lg:backdrop-blur-lg sticky top-0 z-30" style={{ paddingTop: "env(safe-area-inset-top, 0px)" }}>
      {/* Left: hamburger + logo */}
      <div className="flex items-center gap-3">
        {onToggleSidebar && (
          <button
            onClick={onToggleSidebar}
            className="lg:hidden p-1.5 rounded-md hover:bg-white/5 text-[var(--color-muted)]"
            aria-label="Toggle sidebar"
          >
            <Menu className="h-5 w-5" />
          </button>
        )}

        <Link href="/" className="flex items-center gap-2">
          <Image
            src="/icons/logo.png"
            alt="DingDawg mascot"
            width={32}
            height={26}
          />
          <span className="font-semibold text-[var(--foreground)]">
            DingDawg
          </span>
          <span className="text-xs text-[var(--color-muted)] hidden sm:inline">
            Agent
          </span>
        </Link>
      </div>

      {/* Center: navigation links */}
      <div className="flex items-center gap-1">
        {/* Explore is always visible */}
        <NavLink
          href="/explore"
          icon={<Compass className="h-4 w-4" />}
          label="Explore"
          active={pathname === "/explore"}
        />

        {isAuthenticated && hasAgents && (
          <>
            <NavLink
              href="/dashboard"
              icon={<LayoutDashboard className="h-4 w-4" />}
              label="Dashboard"
              active={pathname === "/dashboard"}
            />
            <NavLink
              href="/dashboard/ceo"
              icon={<BarChart3 className="h-4 w-4" />}
              label="Business"
              active={pathname === "/dashboard/ceo"}
            />
            <NavLink
              href="/tasks"
              icon={<ClipboardList className="h-4 w-4" />}
              label="Tasks"
              active={pathname === "/tasks"}
            />
          </>
        )}

        {isAuthenticated && !hasAgents && (
          <NavLink
            href="/claim"
            icon={<Sparkles className="h-4 w-4" />}
            label="Claim Agent"
            active={pathname === "/claim"}
          />
        )}
      </div>

      {/* Right: user info + logout */}
      {user ? (
        <div className="flex items-center gap-3">
          <span className="text-sm text-[var(--color-muted)] hidden md:inline truncate max-w-36">
            {user.email}
          </span>
          <button
            onClick={logout}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm text-[var(--color-muted)] hover:text-red-400 hover:bg-red-400/5 transition-colors"
            aria-label="Log out"
          >
            <LogOut className="h-4 w-4" />
            <span className="hidden sm:inline">Logout</span>
          </button>
        </div>
      ) : (
        <Link
          href="/login"
          className="text-sm text-[var(--gold-500)] hover:underline font-medium"
        >
          Sign in
        </Link>
      )}
    </nav>
  );
}
