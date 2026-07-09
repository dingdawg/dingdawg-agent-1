"use client";

import React, { useState, useRef, useEffect } from "react";
import Link from "next/link";
import {
  LayoutDashboard,
  Settings2,
  Store,
  GitBranch,
  Gem,
  Lock,
  Shield,
  LayoutGrid,
  Plug,
  BarChart3,
  ClipboardList,
  Bot,
  Terminal,
  Users,
  Plus,
  Search,
  ChevronDown,
  ChevronRight,
  ChevronLeft,
  MessageCircle,
  LogOut,
  User,
  Receipt,
  Trash2,
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

export interface SidebarAgent {
  id: string;
  name: string;
  handle: string;
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
  /** Optional: agent @handle shown under name. Derived from agentName if omitted. */
  agentHandle?: string;
  currentPath: string;
  onLogout: () => void;
  isCollapsed: boolean;
  onCollapseToggle: () => void;
  /** Dynamic badge count overrides — falls back to screenshot defaults */
  navCounts?: { tasks?: number; integrations?: number };
  /** Multi-agent switcher */
  agents?: SidebarAgent[];
  currentAgentId?: string | null;
  onSelectAgent?: (id: string) => void;
  onNewAgent?: () => void;
}

/* ────────────────────────────────────────────────────────────────────────── */
/*  Helpers                                                                  */
/* ────────────────────────────────────────────────────────────────────────── */

function relativeTime(iso: string): string {
  if (!iso) return "";
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

/* ────────────────────────────────────────────────────────────────────────── */
/*  NavRow                                                                   */
/* ────────────────────────────────────────────────────────────────────────── */

function NavRow({
  icon: Icon,
  label,
  badge,
  soon,
  active,
  collapsed,
  href,
  onClick,
}: {
  icon: React.ElementType;
  label: string;
  badge?: number | null;
  soon?: boolean;
  active?: boolean;
  collapsed: boolean;
  href: string;
  onClick?: () => void;
}) {
  const cls = `group relative w-full flex items-center gap-3 rounded-lg px-2.5 py-2 text-[13px] transition-colors ${
    collapsed ? "justify-center" : "justify-start"
  } ${
    active
      ? "bg-[var(--gold-500)]/10 text-[var(--gold-500)]"
      : soon
      ? "text-white/40 cursor-default"
      : "text-white/65 hover:text-white hover:bg-white/[0.04]"
  }`;

  const inner = (
    <>
      {active && !collapsed && (
        <span className="absolute left-0 top-1.5 bottom-1.5 w-[2px] rounded-r bg-[var(--gold-500)]" />
      )}
      <Icon size={16} strokeWidth={1.7} className="shrink-0" />
      {!collapsed && (
        <>
          <span className="flex-1 text-left tracking-[-0.005em] truncate">{label}</span>
          {soon && (
            <span className="font-mono text-[9px] tracking-[0.1em] text-white/40 uppercase">
              soon
            </span>
          )}
          {badge != null && !soon && (
            <span className="font-mono text-[10px] text-white/60">{badge}</span>
          )}
        </>
      )}
    </>
  );

  if (soon) {
    return (
      <div className={cls} aria-disabled="true" role="menuitem" title={collapsed ? label : undefined}>
        {inner}
      </div>
    );
  }

  return (
    <Link href={href} onClick={onClick} className={cls} title={collapsed ? label : undefined}>
      {inner}
    </Link>
  );
}

/* ────────────────────────────────────────────────────────────────────────── */
/*  CollapsibleGroup                                                         */
/* ────────────────────────────────────────────────────────────────────────── */

function CollapsibleGroup({
  label,
  defaultOpen = true,
  collapsed,
  children,
}: {
  label: string;
  defaultOpen?: boolean;
  collapsed: boolean;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);

  if (collapsed) {
    return (
      <>
        <div className="h-px bg-white/[0.05] my-3 mx-3" />
        <div>{children}</div>
      </>
    );
  }

  return (
    <div className="mt-3">
      <div className="px-3 mb-1">
        <button
          onClick={() => setOpen((p) => !p)}
          className="flex items-center gap-1.5 select-none group"
        >
          {open ? (
            <ChevronDown size={10} className="text-white/55 group-hover:text-white/70 transition-colors" />
          ) : (
            <ChevronRight size={10} className="text-white/55 group-hover:text-white/70 transition-colors" />
          )}
          <span className="font-mono text-[10px] uppercase tracking-[0.14em] text-white/55">
            {label}
          </span>
        </button>
      </div>
      {open && <div className="space-y-0.5">{children}</div>}
    </div>
  );
}

/* ────────────────────────────────────────────────────────────────────────── */
/*  RecentChatItem                                                           */
/* ────────────────────────────────────────────────────────────────────────── */

function RecentChatItem({
  session,
  active,
  collapsed,
  onClick,
  onDelete,
}: {
  session: SidebarSession;
  active: boolean;
  collapsed: boolean;
  onClick: () => void;
  onDelete?: (e: React.MouseEvent) => void;
}) {
  if (collapsed) {
    return (
      <div className="flex justify-center py-1.5">
        <div
          className={`h-1.5 w-1.5 rounded-full transition-colors ${
            active ? "bg-[var(--gold-500)]" : "bg-white/20"
          }`}
        />
      </div>
    );
  }

  return (
    <button
      onClick={onClick}
      className={`group w-full flex items-start gap-2.5 px-2.5 py-2 rounded-lg text-left transition-colors min-h-[44px] ${
        active ? "bg-white/[0.05]" : "hover:bg-white/[0.03]"
      }`}
    >
      <MessageCircle
        size={13}
        strokeWidth={1.6}
        className={`mt-0.5 shrink-0 ${
          active ? "text-[var(--gold-500)]" : "text-white/55"
        }`}
      />
      <div className="min-w-0 flex-1">
        <div
          className={`text-[12.5px] truncate tracking-[-0.005em] ${
            active ? "text-white" : "text-white/70"
          }`}
        >
          {session.title}
        </div>
        <div className="font-mono text-[10px] text-white/45 mt-0.5">
          {session.id.slice(0, 8)} · {relativeTime(session.updatedAt)}
        </div>
      </div>
      {onDelete && (
        <button
          onClick={onDelete}
          className="opacity-0 group-hover:opacity-100 h-5 w-5 rounded hover:bg-white/10 flex items-center justify-center text-white/40 hover:text-red-400 transition-opacity shrink-0"
          aria-label={`Delete ${session.title}`}
        >
          <Trash2 size={11} />
        </button>
      )}
    </button>
  );
}

/* ────────────────────────────────────────────────────────────────────────── */
/*  AccountFooter                                                            */
/* ────────────────────────────────────────────────────────────────────────── */

function AccountFooter({
  user,
  collapsed,
  onLogout,
}: {
  user: { email: string; user_id: string } | null;
  collapsed: boolean;
  onLogout: () => void;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const initials = user?.email ? user.email.slice(0, 2).toUpperCase() : "??";

  useEffect(() => {
    if (!open) return;
    function handle(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", handle);
    return () => document.removeEventListener("mousedown", handle);
  }, [open]);

  return (
    <div
      ref={ref}
      className="relative border-t border-[var(--stroke)] flex-shrink-0"
      style={{ padding: collapsed ? "10px" : "10px" }}
    >
      {open && !collapsed && (
        <div className="absolute bottom-full left-2 right-2 mb-1 rounded-xl border border-[var(--stroke)] bg-[var(--ink-900)] py-1.5 shadow-xl z-50">
          <Link
            href="/settings"
            onClick={() => setOpen(false)}
            className="flex w-full items-center gap-3 px-4 py-2.5 text-[13px] text-white/80 hover:bg-white/5 min-h-[44px] transition-colors"
          >
            <User size={15} className="text-white/55 shrink-0" />
            Profile
          </Link>
          <Link
            href="/billing"
            onClick={() => setOpen(false)}
            className="flex w-full items-center gap-3 px-4 py-2.5 text-[13px] text-white/80 hover:bg-white/5 min-h-[44px] transition-colors"
          >
            <Receipt size={15} className="text-white/55 shrink-0" />
            Billing
          </Link>
          <div className="my-1 border-t border-[var(--stroke)]" />
          <button
            onClick={() => { setOpen(false); onLogout(); }}
            className="flex w-full items-center gap-3 px-4 py-2.5 text-[13px] text-red-400 hover:bg-white/5 min-h-[44px] transition-colors"
          >
            <LogOut size={15} className="shrink-0" />
            Logout
          </button>
        </div>
      )}

      {collapsed ? (
        <button
          onClick={() => setOpen((p) => !p)}
          className="flex justify-center w-full"
          title={user?.email ?? "Guest"}
        >
          <div className="h-7 w-7 rounded-full bg-gradient-to-br from-amber-300 to-amber-600 flex items-center justify-center text-[#0A1220] font-semibold text-[11px]">
            {initials}
          </div>
        </button>
      ) : (
        <button
          onClick={() => setOpen((p) => !p)}
          className="w-full flex items-center gap-2.5 px-2 py-2 rounded-lg hover:bg-white/[0.04] transition-colors"
        >
          <div className="h-7 w-7 rounded-full bg-gradient-to-br from-amber-300 to-amber-600 flex items-center justify-center text-[#0A1220] font-semibold text-[11px] shrink-0">
            {initials}
          </div>
          <div className="min-w-0 flex-1 text-left">
            <div className="text-[12px] truncate text-white/85">
              {user?.email ?? "Guest"}
            </div>
            <div className="font-mono text-[9.5px] text-white/65">Pro · 14k credits</div>
          </div>
          <ChevronDown size={12} className="text-white/65 shrink-0" />
        </button>
      )}
    </div>
  );
}

/* ────────────────────────────────────────────────────────────────────────── */
/*  SidebarInner — single component for both collapsed and expanded          */
/* ────────────────────────────────────────────────────────────────────────── */

interface SidebarInnerProps {
  collapsed: boolean;
  onCollapseToggle: () => void;
  sessions: SidebarSession[];
  activeSessionId: string | null;
  onNewSession: () => void;
  onSwitchSession: (id: string) => void;
  onDeleteSession: (id: string) => void;
  user: { email: string; user_id: string } | null;
  agentName: string;
  agentHandle?: string;
  currentPath: string;
  onLogout: () => void;
  navCounts?: SidebarProps["navCounts"];
  agents?: SidebarAgent[];
  currentAgentId?: string | null;
  onSelectAgent?: (id: string) => void;
  onNewAgent?: () => void;
}

function SidebarInner({
  collapsed,
  onCollapseToggle,
  sessions,
  activeSessionId,
  onNewSession,
  onSwitchSession,
  onDeleteSession,
  user,
  agentName,
  agentHandle,
  currentPath,
  onLogout,
  navCounts,
  agents,
  currentAgentId,
  onSelectAgent,
  onNewAgent,
}: SidebarInnerProps) {
  const [searchQuery, setSearchQuery] = useState("");
  const [switcherOpen, setSwitcherOpen] = useState(false);
  const switcherRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!switcherOpen) return;
    function onOutside(e: MouseEvent) {
      if (switcherRef.current && !switcherRef.current.contains(e.target as Node)) {
        setSwitcherOpen(false);
      }
    }
    document.addEventListener("mousedown", onOutside);
    return () => document.removeEventListener("mousedown", onOutside);
  }, [switcherOpen]);

  const handle =
    agentHandle || agentName.toLowerCase().replace(/\s+/g, "").slice(0, 12);

  const taskBadge = navCounts?.tasks ?? 3;
  const integBadge = navCounts?.integrations ?? 14;

  const workspaceNav = [
    { label: "Dashboard", icon: LayoutDashboard, path: "/dashboard", badge: null as number | null, soon: false },
    { label: "Operations", icon: Settings2, path: "/operations", badge: null, soon: true },
    { label: "Marketplace", icon: Store, path: "/marketplace", badge: 68, soon: false },
    { label: "Workflow Studio", icon: GitBranch, path: "/workflow-studio", badge: 20, soon: false },
    { label: "Partner Program", icon: Gem, path: "/partner-program", badge: 147, soon: false },
    { label: "Equity Charter", icon: Lock, path: "/equity-charter", badge: null, soon: false },
    { label: "Trust Boundary", icon: Shield, path: "/trust-boundary", badge: 8, soon: false },
    { label: "Module Library", icon: LayoutGrid, path: "/module-library", badge: 12, soon: false },
    { label: "Integrations", icon: Plug, path: "/integrations", badge: integBadge, soon: false },
    { label: "Analytics", icon: BarChart3, path: "/analytics", badge: null, soon: true },
    { label: "Tasks", icon: ClipboardList, path: "/tasks", badge: taskBadge, soon: false },
  ];

  const superAppNav = [
    { label: "Agents", icon: Bot, path: "/agents", badge: 6 as number | null, soon: false },
    { label: "CLI Access", icon: Terminal, path: "/cli", badge: null, soon: false },
    { label: "CRM", icon: Users, path: "/crm", badge: 208, soon: false },
  ];

  const filteredSessions = searchQuery
    ? sessions.filter((s) =>
        s.title.toLowerCase().includes(searchQuery.toLowerCase())
      )
    : sessions;

  return (
    <aside className="relative flex flex-col h-full w-full bg-[var(--ink-950)] border-r border-[var(--stroke)]">
      {/* ── Header ────────────────────────────────────────────────── */}
      <div
        className="flex items-center justify-between px-3 flex-shrink-0"
        style={{
          paddingTop: "calc(env(safe-area-inset-top, 0px) + 14px)",
          paddingBottom: "12px",
        }}
      >
        {!collapsed ? (
          <div ref={switcherRef} className="relative flex-1 min-w-0 mr-2">
            <button
              onClick={() => setSwitcherOpen((p) => !p)}
              className="flex items-center gap-2 min-w-0 w-full rounded-lg hover:bg-white/[0.04] px-1 py-1 -mx-1 -my-1 transition-colors"
              aria-label="Switch agent"
              aria-expanded={switcherOpen}
            >
              <div className="h-7 w-7 rounded-md bg-[var(--gold-500)] flex items-center justify-center text-[#0A1220] font-bold text-[12px] shrink-0">
                {agentName.charAt(0).toUpperCase()}
              </div>
              <div className="leading-tight min-w-0 flex-1">
                <div className="text-[13px] font-semibold tracking-[-0.01em] text-[var(--foreground)] truncate">
                  {agentName}
                </div>
                <div className="font-mono text-[9.5px] text-[var(--gold-500)]">
                  @{handle}
                </div>
              </div>
              <ChevronDown
                size={12}
                className={`text-white/50 shrink-0 transition-transform duration-200 ${switcherOpen ? "rotate-180" : ""}`}
              />
            </button>

            {switcherOpen && (
              <div className="absolute top-full left-0 right-0 mt-1.5 rounded-xl border border-[var(--stroke)] bg-[var(--ink-900)] py-1.5 shadow-xl z-50 min-w-[180px]">
                {agents && agents.length > 0 && (
                  <>
                    {agents.map((agent) => (
                      <button
                        key={agent.id}
                        onClick={() => { onSelectAgent?.(agent.id); setSwitcherOpen(false); }}
                        className={`flex items-center gap-2.5 w-full px-3 py-2 text-left transition-colors hover:bg-white/[0.05] min-h-[40px] ${
                          agent.id === currentAgentId ? "text-[var(--gold-500)]" : "text-white/80"
                        }`}
                      >
                        <div className={`h-6 w-6 rounded-md flex items-center justify-center text-[#0A1220] font-bold text-[11px] shrink-0 ${
                          agent.id === currentAgentId ? "bg-[var(--gold-500)]" : "bg-white/20"
                        }`}>
                          {agent.name.charAt(0).toUpperCase()}
                        </div>
                        <div className="min-w-0 flex-1">
                          <div className="text-[12.5px] font-medium truncate">{agent.name}</div>
                          <div className="font-mono text-[9px] text-white/45 truncate">@{agent.handle}</div>
                        </div>
                        {agent.id === currentAgentId && (
                          <span className="h-1.5 w-1.5 rounded-full bg-[var(--gold-500)] shrink-0" />
                        )}
                      </button>
                    ))}
                    <div className="my-1 border-t border-[var(--stroke)]" />
                  </>
                )}
                <button
                  onClick={() => { onNewAgent?.(); setSwitcherOpen(false); }}
                  className="flex items-center gap-2.5 w-full px-3 py-2 text-left text-white/65 hover:text-white hover:bg-white/[0.05] transition-colors min-h-[40px]"
                >
                  <div className="h-6 w-6 rounded-md border border-dashed border-white/25 flex items-center justify-center shrink-0">
                    <Plus size={11} />
                  </div>
                  <span className="text-[12.5px] font-medium">New Agent</span>
                </button>
              </div>
            )}
          </div>
        ) : (
          <div className="h-7 w-7 mx-auto rounded-md bg-[var(--gold-500)] flex items-center justify-center text-[#0A1220] font-bold text-[12px]">
            {agentName.charAt(0).toUpperCase()}
          </div>
        )}
        {!collapsed && (
          <button
            onClick={onCollapseToggle}
            className="h-7 w-7 rounded-md hover:bg-white/[0.06] flex items-center justify-center text-white/50 hover:text-white transition-colors shrink-0"
            aria-label="Collapse sidebar"
          >
            <ChevronLeft size={14} />
          </button>
        )}
      </div>

      {/* ── New Chat ──────────────────────────────────────────────── */}
      <div className="px-3 pb-2 flex-shrink-0">
        <button
          onClick={onNewSession}
          className="w-full flex items-center justify-center gap-2 rounded-lg bg-[var(--gold-500)] hover:brightness-110 text-[#0A1220] font-semibold text-[13px] py-2.5 px-3 transition shadow-[0_6px_20px_-8px_rgba(245,184,0,0.4)]"
        >
          <Plus size={15} strokeWidth={2.2} className="shrink-0" />
          {!collapsed && <span>New Chat</span>}
        </button>
      </div>

      {/* ── Scrollable body ───────────────────────────────────────── */}
      <div className="flex-1 min-h-0 overflow-y-auto overscroll-contain">
        {/* WORKSPACES */}
        <CollapsibleGroup label="Workspaces" collapsed={collapsed} defaultOpen>
          <div className="px-2 space-y-0.5">
            {workspaceNav.map((item) => {
              const active =
                !item.soon &&
                (item.path === "/dashboard"
                  ? currentPath === item.path
                  : currentPath.startsWith(item.path));
              return (
                <NavRow
                  key={item.path}
                  icon={item.icon}
                  label={item.label}
                  badge={item.badge}
                  soon={item.soon}
                  active={active}
                  collapsed={collapsed}
                  href={item.path}
                />
              );
            })}
          </div>
        </CollapsibleGroup>

        {/* SUPER APP */}
        <CollapsibleGroup label="Super App" collapsed={collapsed} defaultOpen={false}>
          <div className="px-2 space-y-0.5">
            {superAppNav.map((item) => {
              const active = currentPath.startsWith(item.path);
              return (
                <NavRow
                  key={item.path}
                  icon={item.icon}
                  label={item.label}
                  badge={item.badge}
                  active={active}
                  collapsed={collapsed}
                  href={item.path}
                />
              );
            })}
          </div>
        </CollapsibleGroup>

        {/* RECENT CHATS — full view */}
        {!collapsed && (
          <div className="mt-1 pb-2">
            <div className="flex items-center justify-between px-3 mt-4 mb-1.5">
              <span className="font-mono text-[10px] uppercase tracking-[0.14em] text-white/55">
                Recent Chats
              </span>
              <button className="h-5 w-5 rounded hover:bg-white/[0.06] flex items-center justify-center text-white/65 transition-colors">
                <Search size={12} />
              </button>
            </div>
            <div className="px-3 mb-1.5">
              <div className="flex items-center gap-1.5 rounded-md bg-white/[0.04] border border-white/[0.06] px-2 py-1.5">
                <Search size={12} className="text-white/65 shrink-0" />
                <input
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  placeholder="Search chats…"
                  className="flex-1 bg-transparent outline-none text-[12px] text-white placeholder:text-white/45 min-w-0"
                />
                <span className="font-mono text-[9.5px] text-white/45 px-1 py-0.5 rounded border border-white/[0.08] shrink-0">
                  ⌘K
                </span>
              </div>
            </div>
            <div className="px-2 space-y-0.5">
              {filteredSessions.length === 0 && (
                <p className="py-4 text-[12px] text-white/40 text-center">No chats yet</p>
              )}
              {filteredSessions.map((session) => (
                <RecentChatItem
                  key={session.id}
                  session={session}
                  active={session.id === activeSessionId}
                  collapsed={false}
                  onClick={() => onSwitchSession(session.id)}
                  onDelete={(e) => {
                    e.stopPropagation();
                    onDeleteSession(session.id);
                  }}
                />
              ))}
            </div>
          </div>
        )}

        {/* RECENT CHATS — collapsed dots */}
        {collapsed && sessions.slice(0, 8).map((session) => (
          <RecentChatItem
            key={session.id}
            session={session}
            active={session.id === activeSessionId}
            collapsed
            onClick={() => onSwitchSession(session.id)}
          />
        ))}

        <div className="h-4" />
      </div>

      {/* ── Account footer ────────────────────────────────────────── */}
      <AccountFooter
        user={user}
        collapsed={collapsed}
        onLogout={onLogout}
      />

      {/* ── Floating expand handle (collapsed only) ───────────────── */}
      {collapsed && (
        <button
          onClick={onCollapseToggle}
          className="absolute -right-3 top-20 h-6 w-6 rounded-full bg-[var(--ink-900)] border border-[var(--stroke)] flex items-center justify-center text-white/60 hover:text-white hover:bg-[var(--ink-800)] z-10 transition-colors"
          aria-label="Expand sidebar"
        >
          <ChevronRight size={12} />
        </button>
      )}
    </aside>
  );
}

/* ────────────────────────────────────────────────────────────────────────── */
/*  Main Sidebar export                                                      */
/* ────────────────────────────────────────────────────────────────────────── */

export default function Sidebar({
  isOpen,
  onToggle,
  sessions,
  activeSessionId,
  onNewSession,
  onSwitchSession,
  onDeleteSession,
  user,
  agentName,
  agentHandle,
  currentPath,
  onLogout,
  isCollapsed,
  onCollapseToggle,
  navCounts,
  agents,
  currentAgentId,
  onSelectAgent,
  onNewAgent,
}: SidebarProps) {
  return (
    <>
      {/* ── Mobile overlay drawer ─────────────────────────────────── */}
      <div className="md:hidden">
        {isOpen && (
          <div
            className="fixed inset-0 z-40 bg-black/50 backdrop-blur-sm"
            onClick={onToggle}
            aria-hidden="true"
          />
        )}
        <aside
          className={`fixed inset-y-0 left-0 z-50 w-[248px] sidebar-transition ${
            isOpen ? "translate-x-0" : "-translate-x-full"
          }`}
          aria-hidden={!isOpen}
        >
          <SidebarInner
            collapsed={false}
            onCollapseToggle={onToggle}
            sessions={sessions}
            activeSessionId={activeSessionId}
            onNewSession={() => { onNewSession(); onToggle(); }}
            onSwitchSession={(id) => { onSwitchSession(id); onToggle(); }}
            onDeleteSession={onDeleteSession}
            user={user}
            agentName={agentName}
            agentHandle={agentHandle}
            currentPath={currentPath}
            onLogout={onLogout}
            navCounts={navCounts}
            agents={agents}
            currentAgentId={currentAgentId}
            onSelectAgent={onSelectAgent}
            onNewAgent={onNewAgent}
          />
        </aside>
      </div>

      {/* ── Desktop collapsible inline sidebar ───────────────────── */}
      <aside
        className={`hidden md:flex shrink-0 sidebar-width-transition ${
          isCollapsed ? "w-16" : "w-[248px]"
        }`}
        style={{ height: "100dvh" }}
      >
        <SidebarInner
          collapsed={isCollapsed}
          onCollapseToggle={onCollapseToggle}
          sessions={sessions}
          activeSessionId={activeSessionId}
          onNewSession={onNewSession}
          onSwitchSession={onSwitchSession}
          onDeleteSession={onDeleteSession}
          user={user}
          agentName={agentName}
          agentHandle={agentHandle}
          currentPath={currentPath}
          onLogout={onLogout}
          navCounts={navCounts}
          agents={agents}
          currentAgentId={currentAgentId}
          onSelectAgent={onSelectAgent}
          onNewAgent={onNewAgent}
        />
      </aside>
    </>
  );
}
