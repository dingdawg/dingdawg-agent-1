// ##LLM:FILE: PRODUCT=DingDawg-Platform BLOCK=RightSidebar SEQ=1 PART_OF=dashboard-layout CONNECTS_TO=dashboard/page.tsx
"use client";

import { useState } from "react";
import {
  Zap,
  Calendar,
  Mail,
  BarChart3,
  Code2,
  GitBranch,
  Gem,
  MessageSquare,
  Share2,
  FileText,
  Play,
  Settings,
  MoreHorizontal,
  ChevronDown,
  ChevronRight,
  ChevronLeft,
  Plus,
  X,
} from "lucide-react";

export interface RightSidebarProps {
  onCliCommand?: (cmd: string) => void;
  onAction?: (message: string) => void;
}

// ── Types & Persistence ───────────────────────────────────────────────────────

interface WorkflowDraft {
  id: string;
  name: string;
  trigger: "manual" | "webhook" | "schedule";
  tools: string[];
}

const LS_KEY = "ddw_workflows";

function loadSaved(): WorkflowDraft[] {
  try {
    const raw = typeof window !== "undefined" ? localStorage.getItem(LS_KEY) : null;
    if (!raw) return [];
    const parsed = JSON.parse(raw) as unknown;
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(
      (item): item is WorkflowDraft =>
        typeof item === "object" &&
        item !== null &&
        typeof (item as WorkflowDraft).id === "string" &&
        typeof (item as WorkflowDraft).name === "string"
    );
  } catch {
    return [];
  }
}

function saveDrafts(drafts: WorkflowDraft[]) {
  try {
    localStorage.setItem(LS_KEY, JSON.stringify(drafts));
  } catch {
    // storage full or unavailable — fail silently
  }
}

const TOOL_PALETTE: Record<string, readonly string[]> = {
  CLI:    ["ddw run", "ddw crm sync", "ddw deploy", "ddw monitor"],
  Models: ["claude-sonnet-4-6", "claude-opus-4-7", "gpt-4o", "gemini-2.0-flash"],
  CU:     ["screen-capture", "browser-navigate", "form-fill", "data-extract"],
  MCP:    ["gmail-read", "calendar-book", "hubspot-sync", "stripe-report"],
};

// ── Agent Status ──────────────────────────────────────────────────────────────

function AgentStatus() {
  return (
    <div className="px-3 pt-3 pb-3 border-b border-[var(--stroke)]">
      <div className="flex items-center gap-2.5">
        <div className="relative shrink-0">
          <div className="h-9 w-9 rounded-md bg-[var(--gold-500)] flex items-center justify-center text-[#07111c] font-bold text-[13px]">
            J
          </div>
          <span className="absolute -bottom-0.5 -right-0.5 h-2.5 w-2.5 rounded-full bg-[#22c55e] ring-2 ring-[var(--ink-950)]" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5">
            <span className="text-[13px] font-semibold tracking-[-0.01em] text-white">
              JC Agent
            </span>
            <span className="inline-flex items-center gap-1 font-mono text-[9px] text-[#22c55e]">
              <span className="h-1 w-1 rounded-full bg-[#22c55e]" />
              active
            </span>
          </div>
          <div className="font-mono text-[10px] text-white/65 mt-0.5">
            16 skills · 4 conversations
          </div>
        </div>
      </div>

      <div className="mt-3 grid grid-cols-3 gap-1.5">
        {([
          { v: "94%",  l: "uptime",   c: "#22c55e"          },
          { v: "1.2s", l: "p95 lat",  c: "var(--gold-500)"  },
          { v: "12",   l: "in queue", c: "#3b82f6"           },
        ] as const).map((s) => (
          <div
            key={s.l}
            className="rounded-md bg-white/[0.025] border border-white/[0.05] px-2 py-1.5"
          >
            <div className="text-[12px] font-semibold" style={{ color: s.c }}>
              {s.v}
            </div>
            <div className="font-mono text-[9px] text-white/65 uppercase tracking-[0.06em]">
              {s.l}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Action Tile ───────────────────────────────────────────────────────────────

function ActionTile({
  Icon,
  label,
  soon,
  accent,
  onClick,
}: {
  Icon: React.ElementType;
  label: string;
  soon?: boolean;
  accent?: boolean;
  onClick?: () => void;
}) {
  const [fired, setFired] = useState(false);

  const handleClick = () => {
    if (soon) return;
    setFired(true);
    setTimeout(() => setFired(false), 150);
    onClick?.();
  };

  return (
    <button
      type="button"
      onClick={handleClick}
      disabled={soon}
      className={[
        "group relative flex flex-col items-start gap-1.5 rounded-lg border px-2.5 py-2.5 text-left transition-all w-full",
        fired
          ? "ring-1 ring-[var(--gold-500)]/70 border-[var(--gold-500)]/50 bg-[var(--gold-500)]/15"
          : accent
          ? "border-[var(--gold-500)]/35 bg-[var(--gold-500)]/10 hover:bg-[var(--gold-500)]/20"
          : soon
          ? "border-white/[0.06] bg-white/[0.02] cursor-not-allowed"
          : "border-white/[0.08] bg-white/[0.025] hover:bg-white/[0.05] hover:border-white/[0.15]",
      ].join(" ")}
    >
      <div className="flex items-center justify-between w-full">
        <span
          className={[
            "inline-flex h-6 w-6 items-center justify-center rounded-md transition-colors",
            accent
              ? "bg-[var(--gold-500)]/20 text-[var(--gold-500)]"
              : soon
              ? "bg-white/5 text-white/40"
              : "bg-white/5 text-white/70 group-hover:text-white",
          ].join(" ")}
        >
          <Icon size={13} strokeWidth={1.7} />
        </span>
        {soon && (
          <span className="font-mono text-[8.5px] uppercase tracking-[0.12em] text-white/40">
            soon
          </span>
        )}
      </div>
      <span
        className={[
          "text-[12px] font-medium leading-tight",
          accent
            ? "text-[var(--gold-500)]"
            : soon
            ? "text-white/40"
            : "text-white/85",
        ].join(" ")}
      >
        {label}
      </span>
    </button>
  );
}

// ── Workflow Row ──────────────────────────────────────────────────────────────

const WORKFLOW_DOT: Record<string, string> = {
  amber:  "var(--gold-500)",
  blue:   "#3b82f6",
  green:  "#22c55e",
  red:    "#ef4444",
  purple: "#a78bfa",
};

function WorkflowRow({
  Icon,
  name,
  meta,
  color = "amber",
  running,
  onRun,
  deletable,
  onDelete,
}: {
  Icon: React.ElementType;
  name: string;
  meta: string;
  color?: keyof typeof WORKFLOW_DOT;
  running?: boolean;
  onRun?: () => void;
  deletable?: boolean;
  onDelete?: () => void;
}) {
  const [fired, setFired] = useState(false);
  const dot = WORKFLOW_DOT[color] ?? WORKFLOW_DOT.amber;

  const handleRun = (e: React.MouseEvent) => {
    e.stopPropagation();
    setFired(true);
    setTimeout(() => setFired(false), 150);
    onRun?.();
  };

  return (
    <div
      className={[
        "group flex items-center gap-2.5 rounded-lg border px-2.5 py-2 transition-all cursor-pointer",
        fired
          ? "border-[var(--gold-500)]/35 bg-[var(--gold-500)]/10 ring-1 ring-[var(--gold-500)]/25"
          : "border-white/[0.06] bg-white/[0.02] hover:bg-white/[0.045] hover:border-white/[0.1]",
      ].join(" ")}
    >
      {/* drag handle — visible on hover */}
      <div className="flex flex-col gap-[3px] opacity-0 group-hover:opacity-40 transition-opacity shrink-0">
        <span className="block h-[3px] w-[3px] rounded-full bg-white" />
        <span className="block h-[3px] w-[3px] rounded-full bg-white" />
        <span className="block h-[3px] w-[3px] rounded-full bg-white" />
      </div>

      <span
        className={[
          "h-6 w-6 shrink-0 rounded-md flex items-center justify-center text-white/80",
          color === "amber" ? "bg-[var(--gold-500)]/15" : "bg-white/[0.06]",
        ].join(" ")}
      >
        <Icon size={13} strokeWidth={1.7} />
      </span>

      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1.5">
          <span className="text-[12px] text-white/90 truncate tracking-[-0.005em]">
            {name}
          </span>
          {running && (
            <span className="inline-flex items-center gap-1 font-mono text-[9px] text-[var(--gold-500)] shrink-0">
              <span className="h-1 w-1 rounded-full bg-[var(--gold-500)] animate-pulse" />
              running
            </span>
          )}
        </div>
        <div className="font-mono text-[9.5px] text-white/55 mt-0.5 truncate flex items-center gap-1.5">
          <span className="h-[5px] w-[5px] rounded-full shrink-0" style={{ background: dot }} />
          {meta}
        </div>
      </div>

      {/* action buttons — hover only */}
      <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-all shrink-0">
        {deletable && (
          <button
            type="button"
            onClick={(e) => { e.stopPropagation(); onDelete?.(); }}
            className="h-6 w-6 rounded-md bg-white/[0.04] text-white/40 flex items-center justify-center hover:text-[#ef4444] hover:bg-[#ef4444]/10 transition-all"
            aria-label={`Delete ${name}`}
          >
            <X size={10} strokeWidth={2.2} />
          </button>
        )}
        <button
          type="button"
          onClick={handleRun}
          className="h-6 w-6 rounded-md bg-[var(--gold-500)] text-[#07111c] flex items-center justify-center hover:brightness-110 transition-all"
          aria-label={`Run ${name}`}
        >
          <Play size={10} strokeWidth={2.2} />
        </button>
      </div>
    </div>
  );
}

// ── Flow Wizard ───────────────────────────────────────────────────────────────

function FlowWizard({
  onSave,
  onClose,
}: {
  onSave: (draft: WorkflowDraft) => void;
  onClose: () => void;
}) {
  const [step, setStep] = useState(0);
  const [name, setName] = useState("");
  const [trigger, setTrigger] = useState<WorkflowDraft["trigger"]>("manual");
  const [tools, setTools] = useState<string[]>([]);

  const toggleTool = (tool: string) =>
    setTools((prev) =>
      prev.includes(tool) ? prev.filter((t) => t !== tool) : [...prev, tool]
    );

  const handleSave = () => {
    onSave({
      id: `ddw_${Date.now()}`,
      name: name.trim(),
      trigger,
      tools,
    });
  };

  const STEPS = ["Name & Trigger", "Tools", "Preview"] as const;

  return (
    <div className="rounded-lg border border-[var(--gold-500)]/30 bg-[var(--gold-500)]/5 p-3 space-y-3">
      {/* header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="font-mono text-[9.5px] uppercase tracking-[0.14em] text-[var(--gold-500)]">
            New Workflow
          </span>
          <span className="font-mono text-[9px] text-white/40">
            {step + 1}/{STEPS.length}
          </span>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="h-5 w-5 rounded flex items-center justify-center text-white/40 hover:text-white hover:bg-white/[0.06] transition-colors"
          aria-label="Close wizard"
        >
          <X size={11} />
        </button>
      </div>

      {/* progress dots */}
      <div className="flex items-center gap-1.5">
        {STEPS.map((label, i) => (
          <div
            key={label}
            className={[
              "h-1.5 rounded-full transition-all",
              i === step
                ? "w-5 bg-[var(--gold-500)]"
                : i < step
                ? "w-1.5 bg-[var(--gold-500)]/50"
                : "w-1.5 bg-white/15",
            ].join(" ")}
          />
        ))}
      </div>

      {/* step 0 — name + trigger */}
      {step === 0 && (
        <div className="space-y-2.5">
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Workflow name…"
            className="w-full bg-black/30 border border-white/[0.1] rounded-md px-2.5 py-1.5 text-[12px] text-white placeholder:text-white/30 outline-none focus:border-[var(--gold-500)]/50 transition-colors"
            autoFocus
          />
          <div className="flex gap-1.5">
            {(["manual", "webhook", "schedule"] as const).map((t) => (
              <button
                key={t}
                type="button"
                onClick={() => setTrigger(t)}
                className={[
                  "flex-1 rounded-md px-2 py-1.5 font-mono text-[9.5px] uppercase tracking-[0.1em] border transition-all",
                  trigger === t
                    ? "border-[var(--gold-500)]/50 bg-[var(--gold-500)]/15 text-[var(--gold-500)]"
                    : "border-white/[0.08] bg-white/[0.02] text-white/50 hover:text-white/70",
                ].join(" ")}
              >
                {t}
              </button>
            ))}
          </div>
          <button
            type="button"
            disabled={!name.trim()}
            onClick={() => setStep(1)}
            className="w-full rounded-md bg-[var(--gold-500)] text-[#07111c] font-semibold text-[12px] py-1.5 disabled:opacity-40 disabled:cursor-not-allowed hover:brightness-110 transition-all"
          >
            Next — Add Tools
          </button>
        </div>
      )}

      {/* step 1 — tool palette */}
      {step === 1 && (
        <div className="space-y-2.5">
          <div
            className="space-y-2 max-h-[196px] overflow-y-auto pr-0.5"
            style={{ scrollbarWidth: "thin", scrollbarColor: "rgba(255,255,255,0.08) transparent" }}
          >
            {Object.entries(TOOL_PALETTE).map(([category, items]) => (
              <div key={category}>
                <div className="font-mono text-[9px] uppercase tracking-[0.14em] text-white/40 mb-1.5">
                  {category}
                </div>
                <div className="flex flex-wrap gap-1">
                  {items.map((tool) => (
                    <button
                      key={tool}
                      type="button"
                      onClick={() => toggleTool(tool)}
                      className={[
                        "rounded-md px-2 py-1 font-mono text-[10px] border transition-all",
                        tools.includes(tool)
                          ? "border-[var(--gold-500)]/50 bg-[var(--gold-500)]/15 text-[var(--gold-500)]"
                          : "border-white/[0.08] bg-white/[0.02] text-white/55 hover:text-white/80 hover:border-white/[0.15]",
                      ].join(" ")}
                    >
                      {tool}
                    </button>
                  ))}
                </div>
              </div>
            ))}
          </div>
          <div className="flex gap-1.5">
            <button
              type="button"
              onClick={() => setStep(0)}
              className="flex-1 rounded-md border border-white/[0.1] bg-white/[0.02] text-white/60 text-[12px] font-medium py-1.5 hover:bg-white/[0.04] transition-all"
            >
              Back
            </button>
            <button
              type="button"
              onClick={() => setStep(2)}
              className="flex-[2] rounded-md bg-[var(--gold-500)] text-[#07111c] font-semibold text-[12px] py-1.5 hover:brightness-110 transition-all"
            >
              Preview
            </button>
          </div>
        </div>
      )}

      {/* step 2 — preview + save */}
      {step === 2 && (
        <div className="space-y-2.5">
          <div className="rounded-md bg-black/30 border border-white/[0.08] p-2.5 space-y-1.5">
            <div className="flex items-center justify-between">
              <span className="text-[12px] font-semibold text-white truncate pr-2">
                {name}
              </span>
              <span className="font-mono text-[9px] uppercase tracking-[0.1em] px-1.5 py-0.5 rounded bg-[var(--gold-500)]/15 text-[var(--gold-500)] shrink-0">
                {trigger}
              </span>
            </div>
            {tools.length > 0 ? (
              <div className="flex flex-wrap gap-1 mt-1">
                {tools.map((t) => (
                  <span
                    key={t}
                    className="font-mono text-[9px] px-1.5 py-0.5 rounded bg-white/[0.05] border border-white/[0.08] text-white/60"
                  >
                    {t}
                  </span>
                ))}
              </div>
            ) : (
              <div className="font-mono text-[9.5px] text-white/40 italic">
                no tools selected
              </div>
            )}
          </div>
          <div className="flex gap-1.5">
            <button
              type="button"
              onClick={() => setStep(1)}
              className="flex-1 rounded-md border border-white/[0.1] bg-white/[0.02] text-white/60 text-[12px] font-medium py-1.5 hover:bg-white/[0.04] transition-all"
            >
              Back
            </button>
            <button
              type="button"
              onClick={handleSave}
              className="flex-[2] rounded-md bg-[var(--gold-500)] text-[#07111c] font-bold text-[12px] py-1.5 hover:brightness-110 transition-all"
            >
              Save Workflow
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Collapsible Section ───────────────────────────────────────────────────────

function Section({
  label,
  count,
  children,
  defaultOpen = true,
  action,
}: {
  label: string;
  count?: number | string;
  children: React.ReactNode;
  defaultOpen?: boolean;
  action?: React.ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="px-3 pb-1">
      <div className="w-full flex items-center justify-between py-2">
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          className="flex items-center gap-1.5 cursor-pointer select-none min-w-0"
        >
          {open ? (
            <ChevronDown size={11} className="text-white/50 shrink-0" />
          ) : (
            <ChevronRight size={11} className="text-white/50 shrink-0" />
          )}
          <span className="font-mono text-[10px] uppercase tracking-[0.14em] text-white/60">
            {label}
          </span>
          {count !== undefined && (
            <span className="font-mono text-[10px] text-white/40">{count}</span>
          )}
        </button>
        {action}
      </div>
      {open && <div className="pb-2 space-y-1.5">{children}</div>}
    </div>
  );
}

// ── CLI Line ──────────────────────────────────────────────────────────────────

function CliLine({ cmd, onRun }: { cmd: string; onRun?: () => void }) {
  return (
    <button
      type="button"
      onClick={onRun}
      className="w-full flex items-center gap-2 px-2 py-1 rounded hover:bg-white/[0.04] text-left transition-colors group"
    >
      <span className="text-[var(--gold-500)] shrink-0">$</span>
      <span className="text-white/80 group-hover:text-white truncate text-[10.5px] font-mono">
        {cmd}
      </span>
      <Play
        size={9}
        className="ml-auto opacity-0 group-hover:opacity-60 text-[var(--gold-500)] shrink-0 transition-opacity"
      />
    </button>
  );
}

// ── Integration Row ───────────────────────────────────────────────────────────

function IntegrationRow({
  name,
  color,
  status,
}: {
  name: string;
  color: string;
  status: string;
}) {
  return (
    <div className="flex items-center justify-between rounded-md bg-white/[0.02] border border-white/[0.05] hover:bg-white/[0.045] hover:border-white/[0.1] px-2.5 py-1.5 transition-all cursor-default">
      <span className="text-[12px] text-white/80">{name}</span>
      <span
        className="inline-flex items-center gap-1.5 font-mono text-[9.5px] shrink-0"
        style={{ color }}
      >
        <span
          className="h-[5px] w-[5px] rounded-full shrink-0"
          style={{ background: color }}
        />
        {status}
      </span>
    </div>
  );
}

// ── Collapsed Rail ────────────────────────────────────────────────────────────

const RAIL_ICONS = [Zap, Calendar, Mail, BarChart3, Code2, GitBranch] as const;

function CollapsedRail({ onExpand }: { onExpand: () => void }) {
  return (
    <aside
      className="relative shrink-0 h-full bg-[var(--ink-950)] border-l border-[var(--stroke)] flex flex-col"
      style={{ width: 56 }}
    >
      {/* expand handle */}
      <button
        type="button"
        onClick={onExpand}
        className="absolute -left-3 top-20 h-6 w-6 rounded-full bg-[var(--ink-900)] border border-[var(--stroke)] flex items-center justify-center text-white/50 hover:text-white hover:bg-[var(--ink-800)] z-10 transition-colors"
        aria-label="Expand right sidebar"
      >
        <ChevronLeft size={12} />
      </button>

      {/* agent avatar */}
      <div className="px-2 pt-3 pb-2 flex justify-center">
        <div className="relative">
          <div className="h-9 w-9 rounded-md bg-[var(--gold-500)] flex items-center justify-center text-[#07111c] font-bold text-[13px]">
            J
          </div>
          <span className="absolute -bottom-0.5 -right-0.5 h-2.5 w-2.5 rounded-full bg-[#22c55e] ring-2 ring-[var(--ink-950)]" />
        </div>
      </div>

      {/* icon shortcuts */}
      <div className="flex-1 px-2 py-2 flex flex-col items-center gap-1.5">
        {RAIL_ICONS.map((Icon, i) => (
          <button
            key={i}
            type="button"
            className="h-9 w-9 rounded-md hover:bg-white/[0.05] text-white/40 hover:text-white/80 flex items-center justify-center transition-colors"
          >
            <Icon size={15} />
          </button>
        ))}
      </div>
    </aside>
  );
}

// ── RightSidebar ──────────────────────────────────────────────────────────────

export function RightSidebar({ onCliCommand, onAction }: RightSidebarProps) {
  const [isCollapsed, setIsCollapsed] = useState(false);
  const [wizardOpen, setWizardOpen] = useState(false);
  const [savedWorkflows, setSavedWorkflows] = useState<WorkflowDraft[]>(() => loadSaved());

  const handleWizardSave = (draft: WorkflowDraft) => {
    const updated = [draft, ...savedWorkflows];
    setSavedWorkflows(updated);
    saveDrafts(updated);
    setWizardOpen(false);
  };

  if (isCollapsed) {
    return <CollapsedRail onExpand={() => setIsCollapsed(false)} />;
  }

  return (
    <aside
      className="relative shrink-0 h-full bg-[var(--ink-950)] border-l border-[var(--stroke)] flex flex-col overflow-hidden"
      style={{ width: 304 }}
    >
      {/* ── Header ── */}
      <div className="flex items-center justify-between px-3 pt-3.5 pb-2 shrink-0">
        <div className="flex items-center gap-2">
          <Zap size={14} className="text-[var(--gold-500)] shrink-0" />
          <span className="text-[13px] font-semibold tracking-[-0.01em] text-white">
            Quick Actions
          </span>
        </div>
        <button
          type="button"
          onClick={() => setIsCollapsed(true)}
          className="h-7 w-7 rounded-md hover:bg-white/[0.06] flex items-center justify-center text-white/40 hover:text-white transition-colors shrink-0"
          aria-label="Collapse right sidebar"
        >
          <ChevronRight size={14} />
        </button>
      </div>

      {/* ── Agent card ── */}
      <AgentStatus />

      {/* ── Scrollable body ── */}
      <div
        className="flex-1 min-h-0 overflow-y-auto"
        style={{
          scrollbarWidth: "thin",
          scrollbarColor: "rgba(255,255,255,0.08) transparent",
        }}
      >
        {/* Agent Actions 2×3 */}
        <Section
          label="Agent Actions"
          count={6}
          action={
            <button
              type="button"
              className="font-mono text-[9.5px] text-white/40 hover:text-white/70 transition-colors"
            >
              edit
            </button>
          }
        >
          <div className="grid grid-cols-2 gap-1.5">
            <ActionTile Icon={Calendar}      label="Schedule"    accent onClick={() => onAction?.("Schedule an appointment for me")} />
            <ActionTile Icon={Mail}          label="Email Draft" onClick={() => onAction?.("Draft an email for me")} />
            <ActionTile Icon={MessageSquare} label="SMS Blast"   soon />
            <ActionTile Icon={Share2}        label="Social"      soon />
            <ActionTile Icon={FileText}      label="Files"       soon />
            <ActionTile Icon={BarChart3}     label="Analytics"   onClick={() => onAction?.("Show me today's analytics summary")} />
          </div>
        </Section>

        {/* Custom Workflows */}
        <Section
          label="Custom Workflows"
          count={5 + savedWorkflows.length}
          action={
            <button
              type="button"
              onClick={() => setWizardOpen(true)}
              className="font-mono text-[9.5px] text-[var(--gold-500)] hover:brightness-110 inline-flex items-center gap-1 transition-all"
            >
              <Plus size={10} strokeWidth={2.4} />
              new
            </button>
          }
        >
          {wizardOpen && (
            <FlowWizard
              onSave={handleWizardSave}
              onClose={() => setWizardOpen(false)}
            />
          )}
          {savedWorkflows.map((wf) => (
            <WorkflowRow
              key={wf.id}
              Icon={Zap}
              name={wf.name}
              meta={`${wf.trigger} · ${wf.tools.length} tool${wf.tools.length !== 1 ? "s" : ""}`}
              color="amber"
              deletable
              onDelete={() => {
                const updated = savedWorkflows.filter((w) => w.id !== wf.id);
                setSavedWorkflows(updated);
                saveDrafts(updated);
              }}
              onRun={() =>
                onAction?.(
                  wf.tools.length > 0
                    ? `Run the "${wf.name}" workflow using: ${wf.tools.join(", ")}`
                    : `Run the "${wf.name}" workflow now`
                )
              }
            />
          ))}
          <WorkflowRow
            Icon={Zap}
            name="Morning Pulse"
            meta="08:00 daily · last ran 2h ago"
            color="amber"
            onRun={() => onAction?.("Run the Morning Pulse workflow now")}
          />
          <WorkflowRow
            Icon={Gem}
            name="Lead Enrichment + ICP Score"
            meta="webhook · 412 runs"
            color="blue"
            running
            onRun={() => onAction?.("Check Lead Enrichment status and show latest results")}
          />
          <WorkflowRow
            Icon={Mail}
            name="Inbox triage → CRM"
            meta="every 15m · 18 today"
            color="green"
            onRun={() => onAction?.("Run inbox triage and sync to CRM now")}
          />
          <WorkflowRow
            Icon={GitBranch}
            name="Stripe → QuickBooks sync"
            meta="hourly · paused"
            color="red"
            onRun={() => onAction?.("Check Stripe to QuickBooks sync status")}
          />
          <WorkflowRow
            Icon={Code2}
            name="Deploy preview reviewer"
            meta="on PR · 7 reviews"
            color="purple"
            onRun={() => onAction?.("Review the latest deploy preview")}
          />
        </Section>

        {/* CLI */}
        <Section label="CLI" count={3} defaultOpen={false}>
          <div className="rounded-lg bg-black/40 border border-white/[0.06] p-1 space-y-0.5">
            {(["ddw run pulse", "ddw crm sync", "ddw deploy --preview"] as const).map(
              (cmd) => (
                <CliLine
                  key={cmd}
                  cmd={cmd}
                  onRun={() => onCliCommand?.(cmd)}
                />
              )
            )}
          </div>
        </Section>

        {/* Integrations */}
        <Section label="Integrations" count={14} defaultOpen={false}>
          <div className="space-y-1">
            {(
              [
                { name: "Stripe",  color: "#22c55e",         status: "ok"      },
                { name: "Gmail",   color: "#22c55e",         status: "ok"      },
                { name: "HubSpot", color: "var(--gold-500)", status: "syncing" },
                { name: "Slack",   color: "#22c55e",         status: "ok"      },
                { name: "Twilio",  color: "#ef4444",         status: "error"   },
              ] as const
            ).map((integ) => (
              <IntegrationRow key={integ.name} {...integ} />
            ))}
          </div>
        </Section>

        {/* bottom breathing room */}
        <div className="h-3" />
      </div>

      {/* ── Footer ── */}
      <div className="shrink-0 border-t border-[var(--stroke)] px-3 py-2.5 flex items-center justify-between">
        <span className="font-mono text-[9.5px] text-white/40">
          v2.4.1 · ddw-core
        </span>
        <div className="flex items-center gap-1">
          <button
            type="button"
            className="h-6 w-6 rounded hover:bg-white/[0.06] text-white/40 hover:text-white/80 flex items-center justify-center transition-colors"
            aria-label="Settings"
          >
            <Settings size={12} />
          </button>
          <button
            type="button"
            className="h-6 w-6 rounded hover:bg-white/[0.06] text-white/40 hover:text-white/80 flex items-center justify-center transition-colors"
            aria-label="More options"
          >
            <MoreHorizontal size={12} />
          </button>
        </div>
      </div>
    </aside>
  );
}
