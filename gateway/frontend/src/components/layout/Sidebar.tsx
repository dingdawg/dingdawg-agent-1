"use client";

import React, { useState, useRef, useEffect, useCallback } from "react";
import Link from "next/link";
import {
  ChevronLeft,
  ChevronRight,
  ChevronUp,
  Search,
  Plus,
  LayoutDashboard,
  Compass,
  Plug,
  BarChart3,
  ClipboardList,
  MessageSquare,
  Trash2,
  User,
  Receipt,
  LogOut,
  Briefcase,
} from "lucide-react";

/* ────────────────────────────────────────────────────────────────────────── */
/*  Types                                                                    */
/* ────────────────────────────────────────────────────────────────────────── */

export interface SidebarSession {
  id: string;
  title: string;
  messageCount: number;
  updatedAt: string;
}

export interface SidebarProps {
  isOpen: boolean;
  onToggle: () => void;
  sessions: SidebarSession[];
  activeSessionId: string | null;
  onNewSession: () => void;
  onSwitchSession: (id: string) => void;
  onDeleteSession: (id: string) => void;
  onSearch: (query: string) => void;
  user: { email: string; user_id: string } | null;
  agentName: string;
  currentPath: string;
  onLogout: () => void;
  /** Desktop icon-only collapsed state, separate from isOpen (mobile drawer) */
  isCollapsed: boolean;
  onCollapseToggle: () => void;
}

/* ────────────────────────────────────────────────────────────────────────── */
/*  Nav config                                                               */
/* ────────────────────────────────────────────────────────────────────────── */

const NAV_ITEMS = [
  { label: "Dashboard", icon: LayoutDashboard, path: "/dashboard" },
  { label: "Operations", icon: Briefcase, path: "/operations" },
  { label: "Explore", icon: Compass, path: "/explore" },
  { label: "Integrations", icon: Plug, path: "/integrations" },
  { label: "Analytics", icon: BarChart3, path: "/analytics" },
  { label: "Tasks", icon: ClipboardList, path: "/tasks" },
] as const;

/* ────────────────────────────────────────────────────────────────────────── */
/*  Helpers                                                                  */
/* ────────────────────────────────────────────────────────────────────────── */

function relativeTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60_000);
  if (mins < 1) return "now";
  if (mins < 60) return `${mins}m`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h`;
  const days = Math.floor(hrs / 24);
  if (days < 30) return `${days}d`;
  return `${Math.floor(days / 30)}mo`;
}

function userInitial(email: string | undefined): string {
  if (!email) return "?";
  return email.charAt(0).toUpperCase();
}

/* ────────────────────────────────────────────────────────────────────────── */
/*  User Profile Dropdown                                                    */
/* ────────────────────────────────────────────────────────────────────────── */

interface ProfileDropdownProps {
  isOpen: boolean;
  onClose: () => void;
  onLogout: () => void;
}

const PROFILE_ITEMS = [
  { label: "Profile", icon: User, href: "/settings" },
  { label: "Billing", icon: Receipt, href: "/billing" },
] as const;

function ProfileDropdown({ isOpen, onClose, onLogout }: ProfileDropdownProps) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!isOpen) return;
    function handleClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        onClose();
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  return (
    <div
      ref={ref}
      className="absolute bottom-full left-3 right-3 mb-2 rounded-xl border border-[var(--stroke)] bg-[var(--ink-900)] py-1.5 shadow-xl z-50"
      role="menu"
    >
      {PROFILE_ITEMS.map((item) => (
        <Link
          key={item.label}
          href={item.href}
          role="menuitem"
          className="flex w-full items-center gap-3 px-4 py-3 text-[15px] text-[var(--foreground)] hover:bg-white/5 min-h-[44px]"
          onClick={onClose}
        >
          <item.icon size={18} className="text-[var(--color-muted)]" />
          {item.label}
        </Link>
      ))}
      <div className="my-1 border-t border-[var(--stroke)]" />
      <button
        role="menuitem"
        className="flex w-full items-center gap-3 px-4 py-3 text-[15px] text-red-400 hover:bg-white/5 min-h-[44px]"
        onClick={() => {
          onClose();
          onLogout();
        }}
      >
        <LogOut size={18} />
        Logout
      </button>
    </div>
  );
}

/* ────────────────────────────────────────────────────────────────────────── */
/*  Desktop Sidebar Content (full or icon-only)                             */
/* ────────────────────────────────────────────────────────────────────────── */

interface DesktopSidebarContentProps {
  isCollapsed: boolean;
  onCollapseToggle: () => void;
  sessions: SidebarSession[];
  activeSessionId: string | null;
  onNewSession: () => void;
  onSwitchSession: (id: string) => void;
  onDeleteSession: (id: string) => void;
  onSearch: (query: string) => void;
  user: { email: string; user_id: string } | null;
  agentName: string;
  currentPath: string;
  onLogout: () => void;
}

function DesktopSidebarContent({
  isCollapsed,
  onCollapseToggle,
  sessions,
  activeSessionId,
  onNewSession,
  onSwitchSession,
  onDeleteSession,
  user,
  agentName,
  currentPath,
  onLogout,
}: DesktopSidebarContentProps) {
  const [profileOpen, setProfileOpen] = useState(false);

  const toggleProfile = useCallback(() => {
    if (!isCollapsed) setProfileOpen((p) => !p);
  }, [isCollapsed]);

  const closeProfile = useCallback(() => setProfileOpen(false), []);

  // Close profile when collapsing
  useEffect(() => {
    if (isCollapsed) setProfileOpen(false);
  }, [isCollapsed]);

  return (
    <div className="flex h-full flex-col bg-[var(--ink-950)] border-r border-[var(--stroke)] overflow-hidden">
      {/* A) Header */}
      <div
        className="flex items-center px-3 flex-shrink-0"
        style={{
          paddingTop: "calc(env(safe-area-inset-top, 0px) + 12px)",
          paddingBottom: "8px",
          justifyContent: isCollapsed ? "center" : "space-between",
        }}
      >
        {!isCollapsed && (
          <span className="font-heading text-lg font-bold text-[var(--foreground)] truncate">
            {agentName || "DingDawg"}
          </span>
        )}
        <button
          onClick={onCollapseToggle}
          className="flex h-9 w-9 items-center justify-center rounded-lg text-[var(--color-muted)] hover:bg-white/5 hover:text-[var(--foreground)] transition-colors flex-shrink-0"
          aria-label={isCollapsed ? "Expand sidebar" : "Collapse sidebar"}
          title={isCollapsed ? "Expand sidebar" : "Collapse sidebar"}
        >
          {isCollapsed ? <ChevronRight size={20} /> : <ChevronLeft size={20} />}
        </button>
      </div>

      {/* B) New Chat button */}
      <div className={`flex-shrink-0 ${isCollapsed ? "px-2 mt-1 mb-2" : "px-3 mt-1 mb-2"}`}>
        {isCollapsed ? (
          <button
            onClick={onNewSession}
            className="flex h-10 w-full items-center justify-center rounded-xl bg-[var(--gold-500)] text-[#07111c] hover:bg-[var(--gold-600)] transition-colors"
            aria-label="New chat"
            title="New chat"
          >
            <Plus size={18} />
          </button>
        ) : (
          <button
            onClick={onNewSession}
            className="flex h-11 w-full items-center justify-center gap-2 rounded-xl bg-[var(--gold-500)] text-sm font-semibold text-[#07111c] hover:bg-[var(--gold-600)] transition-colors"
          >
            <Plus size={18} />
            New Chat
          </button>
        )}
      </div>

      {/* C) Nav Items */}
      <nav className={`flex-shrink-0 ${isCollapsed ? "px-2" : "px-3"} mt-1`}>
        {NAV_ITEMS.map((item) => {
          const active =
            item.path === "/operations"
              ? currentPath.startsWith("/operations")
              : currentPath === item.path;
          return (
            <Link
              key={item.path}
              href={item.path}
              className={`flex h-11 items-center rounded-xl transition-colors mb-0.5 ${
                isCollapsed ? "justify-center px-2" : "gap-3 px-3"
              } ${
                active
                  ? "bg-[var(--gold-500)]/10 text-[var(--gold-500)]"
                  : "text-[var(--foreground)] hover:bg-white/5"
              }`}
              title={isCollapsed ? item.label : undefined}
            >
              <item.icon size={20} className="shrink-0" />
              {!isCollapsed && (
                <span className="text-base truncate">{item.label}</span>
              )}
            </Link>
          );
        })}
      </nav>

      {/* D) Chat History section — hidden when icon-only */}
      {!isCollapsed && (
        <>
          <div className="flex items-center justify-between px-4 mt-3 mb-1 flex-shrink-0">
            <span className="text-sm font-semibold text-[var(--foreground)]">
              Chat history
            </span>
            <button
              onClick={() => { window.location.href = "/dashboard"; }}
              className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-white/5 text-xs text-[var(--color-muted)] hover:bg-white/10 transition-colors"
            >
              <Search size={12} />
              Search
            </button>
          </div>

          {/* E) Session List */}
          <div className="flex-1 overflow-y-auto px-3 native-scroll scrollbar-thin min-h-0">
            {sessions.length === 0 && (
              <p className="py-6 text-sm text-[var(--color-muted)] text-center">
                No chats yet
              </p>
            )}
            {sessions.map((session) => {
              const active = session.id === activeSessionId;
              return (
                <div
                  key={session.id}
                  className={`group flex min-h-[44px] cursor-pointer items-center gap-3 rounded-xl px-3 py-2 transition-colors mb-0.5 ${
                    active ? "bg-white/[0.08]" : "hover:bg-white/5"
                  }`}
                  onClick={() => onSwitchSession(session.id)}
                  role="button"
                  tabIndex={0}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      onSwitchSession(session.id);
                    }
                  }}
                >
                  <MessageSquare
                    size={16}
                    className="shrink-0 text-[var(--color-muted)]"
                  />
                  <span className="flex-1 truncate text-[15px] text-[var(--foreground)]">
                    {session.title}
                  </span>
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      onDeleteSession(session.id);
                    }}
                    className="shrink-0 rounded-lg p-2 text-[var(--color-muted)] opacity-0 transition-opacity hover:bg-white/10 hover:text-red-400 group-hover:opacity-100 min-h-[44px] min-w-[44px] flex items-center justify-center"
                    aria-label={`Delete ${session.title}`}
                  >
                    <Trash2 size={16} />
                  </button>
                </div>
              );
            })}
          </div>
        </>
      )}

      {/* Spacer when collapsed so profile sticks to bottom */}
      {isCollapsed && <div className="flex-1" />}

      {/* F) User Profile */}
      <div
        className={`relative border-t border-[var(--stroke)] flex-shrink-0 ${isCollapsed ? "p-2" : "p-3"}`}
        style={{ paddingBottom: "calc(env(safe-area-inset-bottom, 0px) + 12px)" }}
      >
        {!isCollapsed && (
          <ProfileDropdown
            isOpen={profileOpen}
            onClose={closeProfile}
            onLogout={onLogout}
          />
        )}
        <button
          onClick={toggleProfile}
          className={`flex w-full items-center rounded-xl hover:bg-white/5 min-h-[44px] transition-colors ${
            isCollapsed ? "justify-center p-2" : "gap-3 p-2"
          }`}
          title={isCollapsed ? (user?.email ?? "Guest") : undefined}
        >
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-[var(--gold-500)]/20 text-sm font-semibold text-[var(--gold-500)]">
            {userInitial(user?.email)}
          </div>
          {!isCollapsed && (
            <>
              <span className="flex-1 truncate text-left text-sm text-[var(--foreground)]">
                {user?.email ?? "Guest"}
              </span>
              <ChevronUp
                size={16}
                className={`shrink-0 text-[var(--color-muted)] transition-transform ${
                  profileOpen ? "" : "rotate-180"
                }`}
              />
            </>
          )}
        </button>
      </div>
    </div>
  );
}

/* ────────────────────────────────────────────────────────────────────────── */
/*  Mobile Sidebar Content (always full-width drawer)                       */
/* ────────────────────────────────────────────────────────────────────────── */

interface MobileSidebarContentProps {
  onClose: () => void;
  sessions: SidebarSession[];
  activeSessionId: string | null;
  onNewSession: () => void;
  onSwitchSession: (id: string) => void;
  onDeleteSession: (id: string) => void;
  user: { email: string; user_id: string } | null;
  agentName: string;
  currentPath: string;
  onLogout: () => void;
}

function MobileSidebarContent({
  onClose,
  sessions,
  activeSessionId,
  onNewSession,
  onSwitchSession,
  onDeleteSession,
  user,
  agentName,
  currentPath,
  onLogout,
}: MobileSidebarContentProps) {
  const [profileOpen, setProfileOpen] = useState(false);
  const toggleProfile = useCallback(() => setProfileOpen((p) => !p), []);
  const closeProfile = useCallback(() => setProfileOpen(false), []);

  return (
    <div className="flex h-full flex-col bg-[var(--ink-950)] border-r border-[var(--stroke)]">
      {/* Header */}
      <div
        className="flex items-center justify-between px-4 flex-shrink-0"
        style={{
          paddingTop: "calc(env(safe-area-inset-top, 0px) + 12px)",
          paddingBottom: "8px",
        }}
      >
        <span className="font-heading text-lg font-bold text-[var(--foreground)]">
          {agentName || "DingDawg"}
        </span>
        <button
          onClick={onClose}
          className="flex h-9 w-9 items-center justify-center rounded-lg text-[var(--color-muted)] hover:bg-white/5 hover:text-[var(--foreground)] transition-colors"
          aria-label="Close sidebar"
        >
          <ChevronLeft size={20} />
        </button>
      </div>

      {/* New Chat */}
      <div className="px-3 mt-1 mb-2 flex-shrink-0">
        <button
          onClick={() => { onNewSession(); onClose(); }}
          className="flex h-11 w-full items-center justify-center gap-2 rounded-xl bg-[var(--gold-500)] text-sm font-semibold text-[#07111c] hover:bg-[var(--gold-600)] transition-colors"
        >
          <Plus size={18} />
          New Chat
        </button>
      </div>

      {/* Nav Items */}
      <nav className="px-3 mt-1 flex-shrink-0">
        {NAV_ITEMS.map((item) => {
          const active =
            item.path === "/operations"
              ? currentPath.startsWith("/operations")
              : currentPath === item.path;
          return (
            <Link
              key={item.path}
              href={item.path}
              onClick={onClose}
              className={`flex h-12 items-center gap-3 rounded-xl px-3 text-base transition-colors mb-0.5 ${
                active
                  ? "bg-[var(--gold-500)]/10 text-[var(--gold-500)]"
                  : "text-[var(--foreground)] hover:bg-white/5"
              }`}
            >
              <item.icon size={20} />
              {item.label}
            </Link>
          );
        })}
      </nav>

      {/* Chat History label */}
      <div className="flex items-center justify-between px-4 mt-3 mb-1 flex-shrink-0">
        <span className="text-sm font-semibold text-[var(--foreground)]">
          Chat history
        </span>
        <button
          onClick={() => { window.location.href = "/dashboard"; onClose(); }}
          className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-white/5 text-xs text-[var(--color-muted)] hover:bg-white/10 transition-colors"
        >
          <Search size={12} />
          Search
        </button>
      </div>

      {/* Session List */}
      <div className="flex-1 overflow-y-auto px-3 native-scroll scrollbar-thin min-h-0">
        {sessions.length === 0 && (
          <p className="py-6 text-sm text-[var(--color-muted)] text-center">
            No chats yet
          </p>
        )}
        {sessions.map((session) => {
          const active = session.id === activeSessionId;
          return (
            <div
              key={session.id}
              className={`group flex min-h-[44px] cursor-pointer items-center gap-3 rounded-xl px-3 py-2 transition-colors mb-0.5 ${
                active ? "bg-white/[0.08]" : "hover:bg-white/5"
              }`}
              onClick={() => { onSwitchSession(session.id); onClose(); }}
              role="button"
              tabIndex={0}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  onSwitchSession(session.id);
                  onClose();
                }
              }}
            >
              <MessageSquare size={16} className="shrink-0 text-[var(--color-muted)]" />
              <span className="flex-1 truncate text-[15px] text-[var(--foreground)]">
                {session.title}
              </span>
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  onDeleteSession(session.id);
                }}
                className="shrink-0 rounded-lg p-2 text-[var(--color-muted)] opacity-0 transition-opacity hover:bg-white/10 hover:text-red-400 group-hover:opacity-100 min-h-[44px] min-w-[44px] flex items-center justify-center"
                aria-label={`Delete ${session.title}`}
              >
                <Trash2 size={16} />
              </button>
            </div>
          );
        })}
      </div>

      {/* Profile */}
      <div
        className="relative border-t border-[var(--stroke)] p-3 flex-shrink-0"
        style={{ paddingBottom: "calc(env(safe-area-inset-bottom, 0px) + 12px)" }}
      >
        <ProfileDropdown
          isOpen={profileOpen}
          onClose={closeProfile}
          onLogout={onLogout}
        />
        <button
          onClick={toggleProfile}
          className="flex w-full items-center gap-3 rounded-xl p-2 hover:bg-white/5 min-h-[44px] transition-colors"
        >
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-[var(--gold-500)]/20 text-sm font-semibold text-[var(--gold-500)]">
            {userInitial(user?.email)}
          </div>
          <span className="flex-1 truncate text-left text-sm text-[var(--foreground)]">
            {user?.email ?? "Guest"}
          </span>
          <ChevronUp
            size={16}
            className={`shrink-0 text-[var(--color-muted)] transition-transform ${
              profileOpen ? "" : "rotate-180"
            }`}
          />
        </button>
      </div>
    </div>
  );
}

/* ────────────────────────────────────────────────────────────────────────── */
/*  Main Sidebar Component                                                   */
/* ────────────────────────────────────────────────────────────────────────── */

export default function Sidebar({
  isOpen,
  onToggle,
  sessions,
  activeSessionId,
  onNewSession,
  onSwitchSession,
  onDeleteSession,
  onSearch,
  user,
  agentName,
  currentPath,
  onLogout,
  isCollapsed,
  onCollapseToggle,
}: SidebarProps) {
  return (
    <>
      {/* ── Mobile: overlay drawer ──────────────────────────────────────── */}
      <div className="md:hidden">
        {/* Backdrop — click to close */}
        {isOpen && (
          <div
            className="fixed inset-0 z-40 bg-black/50 backdrop-blur-sm"
            onClick={onToggle}
            aria-hidden="true"
          />
        )}
        {/* Drawer panel */}
        <aside
          className={`fixed inset-y-0 left-0 z-50 w-[260px] sidebar-transition ${
            isOpen ? "translate-x-0" : "-translate-x-full"
          }`}
          aria-hidden={!isOpen}
        >
          <MobileSidebarContent
            onClose={onToggle}
            sessions={sessions}
            activeSessionId={activeSessionId}
            onNewSession={onNewSession}
            onSwitchSession={onSwitchSession}
            onDeleteSession={onDeleteSession}
            user={user}
            agentName={agentName}
            currentPath={currentPath}
            onLogout={onLogout}
          />
        </aside>
      </div>

      {/* ── Desktop: collapsible inline sidebar ─────────────────────────── */}
      {/*
        Width animates between 260px (expanded) and 64px (icon-only).
        We never go to 0 on desktop — icon mode keeps the sidebar visible.
        The sidebar-width-transition class handles the CSS transition.
      */}
      <aside
        className={`hidden md:block shrink-0 sidebar-width-transition ${
          isCollapsed ? "w-16" : "w-[260px]"
        }`}
        style={{ height: "100dvh" }}
      >
        <DesktopSidebarContent
          isCollapsed={isCollapsed}
          onCollapseToggle={onCollapseToggle}
          sessions={sessions}
          activeSessionId={activeSessionId}
          onNewSession={onNewSession}
          onSwitchSession={onSwitchSession}
          onDeleteSession={onDeleteSession}
          onSearch={onSearch}
          user={user}
          agentName={agentName}
          currentPath={currentPath}
          onLogout={onLogout}
        />
      </aside>
    </>
  );
}
