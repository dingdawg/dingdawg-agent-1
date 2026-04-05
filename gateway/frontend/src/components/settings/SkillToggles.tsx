"use client";

/**
 * SkillToggles — Skills management tab.
 *
 * Shows a grid of skill cards with toggle switches.
 * Enabled skills stored in config_json: { enabled_skills: string[] }
 *
 * Matches the 16 backend skills (12 universal + 4 gaming).
 * Tier-gated: FREE / STARTER / PRO / ENTERPRISE.
 */

import { useState, useEffect, useCallback } from "react";
import { Save } from "lucide-react";
import { Button } from "@/components/ui/button";

// ─── Tier helpers ──────────────────────────────────────────────────────────────

type TierName = "starter" | "pro" | "enterprise";

const TIER_ORDER: Record<TierName | "free", number> = {
  free: 0,
  starter: 1,
  pro: 2,
  enterprise: 3,
};

const TIER_LABEL: Record<TierName, string> = {
  starter: "STARTER",
  pro: "PRO",
  enterprise: "ENTERPRISE",
};

const TIER_PRICE: Record<TierName, string> = {
  starter: "$49.99/mo",
  pro: "$79.99/mo",
  enterprise: "$199.99/mo",
};

function parseTier(plan: string | null | undefined): TierName | "free" {
  switch ((plan ?? "").toLowerCase()) {
    case "starter":    return "starter";
    case "pro":        return "pro";
    case "enterprise": return "enterprise";
    default:           return "free";
  }
}

function tierUnlocked(
  userTier: TierName | "free",
  required: TierName | "free"
): boolean {
  return TIER_ORDER[userTier] >= TIER_ORDER[required];
}

// ─── Types ────────────────────────────────────────────────────────────────────

export interface SkillsConfig {
  enabled_skills: string[];
}

interface SkillTogglesProps {
  initialConfig: Partial<SkillsConfig>;
  agentType: "personal" | "business";
  onSave: (config: SkillsConfig) => Promise<void>;
  saving: boolean;
}

interface SkillDef {
  id: string;
  name: string;
  icon: string;
  description: string;
  category: "universal" | "gaming";
  /** Minimum tier required — "free" means always available */
  requiredTier: TierName | "free";
  /** If true, can never be disabled (core feature) */
  core?: boolean;
}

// ─── Skill Definitions ────────────────────────────────────────────────────────

const ALL_SKILLS: SkillDef[] = [
  // ── FREE ──────────────────────────────────────────────────────────────────
  {
    id: "chat",
    name: "Chat",
    icon: "💬",
    description: "Core conversational AI — always on, always available to your customers. This is what your agent is built on.",
    category: "universal",
    requiredTier: "free",
    core: true,
  },
  {
    id: "faq",
    name: "FAQ",
    icon: "❓",
    description: "Answers your customers' most common questions instantly — no wait, no staff needed.",
    category: "universal",
    requiredTier: "free",
  },

  // ── STARTER ───────────────────────────────────────────────────────────────
  {
    id: "appointments",
    name: "Booking",
    icon: "📅",
    description: "Takes bookings 24/7 — customers book themselves while you focus on the job.",
    category: "universal",
    requiredTier: "starter",
  },
  {
    id: "forms",
    name: "Forms",
    icon: "📝",
    description: "Gathers info from customers in a natural conversation — no paper, no back-and-forth emails.",
    category: "universal",
    requiredTier: "starter",
  },
  {
    id: "notifications",
    name: "Notifications",
    icon: "🔔",
    description: "Automatically reminds customers about their appointments via SMS and email — slash no-shows overnight.",
    category: "universal",
    requiredTier: "starter",
  },
  {
    id: "data_store",
    name: "Data Store",
    icon: "💾",
    description: "Your agent's memory bank — store your menu, FAQ, policies, or prices so it always has the right answer.",
    category: "universal",
    requiredTier: "starter",
  },

  // ── PRO ───────────────────────────────────────────────────────────────────
  {
    id: "vapi",
    name: "AI Phone",
    icon: "📞",
    description: "Your agent picks up the phone — handles calls, qualifies leads, and books appointments without you.",
    category: "universal",
    requiredTier: "pro",
  },
  {
    id: "payments",
    name: "Payments",
    icon: "💰",
    description: "Sends invoices the moment a job is done and collects payment in-chat — gets you paid faster, no chasing.",
    category: "universal",
    requiredTier: "pro",
  },
  {
    id: "review_manager",
    name: "Review Manager",
    icon: "⭐",
    description: "Catches bad reviews before they go public and asks happy customers to leave one — protect your reputation.",
    category: "universal",
    requiredTier: "pro",
  },
  {
    id: "analytics",
    name: "Analytics",
    icon: "📊",
    description: "Tracks every lead, conversation, and conversion — know exactly what your agent is doing for your business.",
    category: "universal",
    requiredTier: "pro",
  },
  {
    id: "menu",
    name: "Menu",
    icon: "🍽️",
    description: "Lets customers browse your full menu, customize orders, and ask questions — built for restaurants and cafés.",
    category: "universal",
    requiredTier: "pro",
  },

  // ── ENTERPRISE ────────────────────────────────────────────────────────────
  {
    id: "a2a",
    name: "Agent-to-Agent",
    icon: "🤖",
    description: "Your agents collaborate — hand off tasks, share context, and escalate between specialized agents automatically.",
    category: "universal",
    requiredTier: "enterprise",
  },
  {
    id: "custom_actions",
    name: "Custom Actions",
    icon: "⚡",
    description: "Build any custom workflow your business needs — call internal APIs, trigger automations, run custom logic.",
    category: "universal",
    requiredTier: "enterprise",
  },

  // ── ENTERPRISE — Gaming ────────────────────────────────────────────────────
  {
    id: "guild",
    name: "Guilds",
    icon: "🛡️",
    description: "Manages your gaming guilds — membership, ranks, events, and internal comms handled by your agent.",
    category: "gaming",
    requiredTier: "enterprise",
  },
  {
    id: "matchmaking",
    name: "Matchmaking",
    icon: "🎮",
    description: "Pairs players by skill level and availability — fills lobbies automatically so no one waits.",
    category: "gaming",
    requiredTier: "enterprise",
  },
  {
    id: "tournaments",
    name: "Tournaments",
    icon: "🏆",
    description: "Runs your entire tournament — brackets, rounds, standings, and announcements — all hands-free.",
    category: "gaming",
    requiredTier: "enterprise",
  },
  {
    id: "coaching",
    name: "Coaching",
    icon: "🎯",
    description: "Tracks player performance and delivers personalized improvement tips — your AI gaming coach.",
    category: "gaming",
    requiredTier: "enterprise",
  },
];

// ─── Toast ────────────────────────────────────────────────────────────────────

interface ToastMessage {
  id: number;
  text: string;
}

function Toast({ messages }: { messages: ToastMessage[] }) {
  if (messages.length === 0) return null;
  return (
    <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-50 flex flex-col gap-2 items-center pointer-events-none">
      {messages.map((m) => (
        <div
          key={m.id}
          className="px-4 py-2.5 rounded-xl bg-[var(--gold-500)] text-black text-xs font-semibold shadow-lg animate-fade-in-up"
        >
          {m.text}
        </div>
      ))}
    </div>
  );
}

// ─── Toggle Switch ─────────────────────────────────────────────────────────────

function ToggleSwitch({
  enabled,
  onChange,
  label,
  disabled,
}: {
  enabled: boolean;
  onChange: (v: boolean) => void;
  label: string;
  disabled?: boolean;
}) {
  return (
    <button
      role="switch"
      aria-checked={enabled}
      aria-label={label}
      onClick={() => !disabled && onChange(!enabled)}
      disabled={disabled}
      className={`relative inline-flex h-5 w-9 flex-shrink-0 items-center rounded-full transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--gold-500)] ${
        disabled
          ? "cursor-not-allowed opacity-40 bg-white/10"
          : enabled
          ? "bg-[var(--gold-500)]"
          : "bg-white/15"
      }`}
    >
      <span
        className={`inline-block h-3.5 w-3.5 rounded-full bg-white shadow transition-transform ${
          enabled ? "translate-x-[18px]" : "translate-x-[3px]"
        }`}
      />
    </button>
  );
}

// ─── Skill Card ───────────────────────────────────────────────────────────────

function SkillCard({
  skill,
  enabled,
  onToggle,
  onLockedClick,
  isLocked,
}: {
  skill: SkillDef;
  enabled: boolean;
  onToggle: (id: string, v: boolean) => void;
  onLockedClick: (skill: SkillDef) => void;
  isLocked: boolean;
}) {
  const isCore = Boolean(skill.core);

  const handleToggleClick = (v: boolean) => {
    if (isLocked) {
      onLockedClick(skill);
      return;
    }
    if (isCore) return; // core skills cannot be disabled
    onToggle(skill.id, v);
  };

  return (
    <div
      className={`relative p-3.5 rounded-xl border transition-all ${
        isLocked
          ? "opacity-50 border-[var(--stroke2)] bg-white/[0.02] cursor-pointer hover:opacity-60"
          : enabled
          ? "border-[var(--gold-500)]/40 bg-[var(--gold-500)]/5"
          : "border-[var(--stroke2)] bg-white/[0.02] hover:bg-white/[0.04]"
      }`}
      onClick={isLocked ? () => onLockedClick(skill) : undefined}
    >
      {/* Tier badge — top-right corner */}
      {isLocked && skill.requiredTier !== "free" && (
        <span className="absolute top-2 right-2 text-[10px] font-bold tracking-wide px-1.5 py-0.5 rounded-full bg-[var(--gold-500)]/20 text-[var(--gold-500)] border border-[var(--gold-500)]/30 z-10">
          {TIER_LABEL[skill.requiredTier as TierName]}
        </span>
      )}

      {/* Core badge */}
      {isCore && !isLocked && (
        <span className="absolute top-2 right-2 text-[10px] font-bold tracking-wide px-1.5 py-0.5 rounded-full bg-green-500/20 text-green-400 border border-green-500/30 z-10">
          CORE
        </span>
      )}

      <div className="flex items-start gap-2.5">
        <span className="text-xl leading-none mt-0.5 flex-shrink-0">
          {skill.icon}
        </span>
        <div className="flex-1 min-w-0">
          <div className="flex items-center justify-between gap-2">
            <p
              className={`text-xs font-semibold truncate ${
                isLocked
                  ? "text-[var(--color-muted)]"
                  : enabled
                  ? "text-[var(--foreground)]"
                  : "text-[var(--color-muted)]"
              }`}
            >
              {skill.name}
            </p>
            <ToggleSwitch
              enabled={enabled && !isLocked}
              onChange={handleToggleClick}
              label={isLocked ? `Upgrade to unlock ${skill.name}` : `Toggle ${skill.name}`}
              disabled={isLocked || isCore}
            />
          </div>
          <p className="text-xs text-[var(--color-muted)] mt-0.5 leading-relaxed line-clamp-2">
            {skill.description}
          </p>
          {isLocked && skill.requiredTier !== "free" && (
            <p className="text-[10px] text-[var(--gold-500)] mt-1 font-medium">
              Upgrade to {TIER_LABEL[skill.requiredTier as TierName]} ({TIER_PRICE[skill.requiredTier as TierName]}) to unlock
            </p>
          )}
        </div>
      </div>
    </div>
  );
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

/** All skill IDs — used as the default when no explicit config exists. */
const ALL_SKILL_IDS = ALL_SKILLS.map((s) => s.id);

/**
 * Resolve the initial enabled-skills set.
 *
 * If the agent has never had skills explicitly configured (null / undefined /
 * empty array), ALL skills are enabled by default.  This matches the backend
 * runtime which injects every registered skill into the LLM prompt when no
 * per-agent filter is present.
 */
function resolveInitialSkills(raw: string[] | undefined | null): string[] {
  if (!raw || raw.length === 0) return ALL_SKILL_IDS;
  return raw;
}

// ─── Main Component ────────────────────────────────────────────────────────────

export function SkillToggles({
  initialConfig,
  agentType,
  onSave,
  saving,
}: SkillTogglesProps) {
  const resolved = resolveInitialSkills(initialConfig.enabled_skills);
  const [enabledSkills, setEnabledSkills] = useState<Set<string>>(
    new Set(resolved)
  );
  const [dirty, setDirty] = useState(false);
  const [toasts, setToasts] = useState<ToastMessage[]>([]);

  // Read user plan from localStorage — same pattern as integrations page
  const userTier: TierName | "free" =
    typeof window !== "undefined"
      ? parseTier(localStorage.getItem("user_plan"))
      : "free";

  const origSet = new Set(resolved);

  useEffect(() => {
    const isDiff =
      enabledSkills.size !== origSet.size ||
      [...enabledSkills].some((s) => !origSet.has(s));
    setDirty(isDiff);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabledSkills]);

  const showToast = useCallback((text: string) => {
    const id = Date.now();
    setToasts((prev) => [...prev, { id, text }]);
    setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id));
    }, 3500);
  }, []);

  const handleToggle = (id: string, value: boolean) => {
    setEnabledSkills((prev) => {
      const next = new Set(prev);
      if (value) next.add(id);
      else next.delete(id);
      return next;
    });
  };

  const handleLockedClick = useCallback(
    (skill: SkillDef) => {
      if (skill.requiredTier === "free") return;
      const tier = skill.requiredTier as TierName;
      showToast(
        `Upgrade to ${TIER_LABEL[tier]} (${TIER_PRICE[tier]}) to unlock ${skill.name}`
      );
    },
    [showToast]
  );

  const handleSave = async () => {
    await onSave({ enabled_skills: [...enabledSkills] });
    setDirty(false);
  };

  const universalSkills = ALL_SKILLS.filter((s) => s.category === "universal");
  const gamingSkills = ALL_SKILLS.filter((s) => s.category === "gaming");
  const activeCount = enabledSkills.size;

  return (
    <div className="space-y-5">
      <Toast messages={toasts} />

      {/* Unsaved indicator */}
      {dirty && (
        <div className="px-3 py-2 rounded-lg bg-[var(--gold-500)]/10 border border-[var(--gold-500)]/20 text-[var(--gold-500)] text-xs font-medium">
          Unsaved changes
        </div>
      )}

      {/* Stats bar */}
      <div className="glass-panel p-4 flex items-center justify-between">
        <div>
          <p className="text-sm font-semibold text-[var(--foreground)]">
            {activeCount} skill{activeCount !== 1 ? "s" : ""} active
          </p>
          <p className="text-xs text-[var(--color-muted)] mt-0.5">
            Turn on what your business needs — turn off what it doesn&apos;t
          </p>
        </div>
        <div className="flex gap-1">
          {ALL_SKILLS.slice(0, 6).map((s) => (
            <span
              key={s.id}
              className={`text-base transition-opacity ${
                enabledSkills.has(s.id) ? "opacity-100" : "opacity-20"
              }`}
            >
              {s.icon}
            </span>
          ))}
        </div>
      </div>

      {/* Universal Skills */}
      <div>
        <h3 className="text-xs font-semibold text-[var(--color-muted)] uppercase tracking-wider mb-3 px-0.5">
          Core Skills — works for any business
        </h3>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
          {universalSkills.map((skill) => {
            const isLocked =
              skill.requiredTier !== "free" &&
              !tierUnlocked(userTier, skill.requiredTier as TierName);
            return (
              <SkillCard
                key={skill.id}
                skill={skill}
                enabled={enabledSkills.has(skill.id)}
                onToggle={handleToggle}
                onLockedClick={handleLockedClick}
                isLocked={isLocked}
              />
            );
          })}
        </div>
      </div>

      {/* Gaming Skills */}
      <div>
        <div className="flex items-center gap-2 mb-3">
          <h3 className="text-xs font-semibold text-[var(--color-muted)] uppercase tracking-wider px-0.5">
            Gaming Skills — for gaming venues and communities
          </h3>
          <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-purple-500/20 text-purple-300 border border-purple-500/30 font-medium">
            GAMING SECTOR
          </span>
          {agentType === "personal" && (
            <span className="text-[10px] text-[var(--color-muted)]">
              · available for personal agents
            </span>
          )}
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
          {gamingSkills.map((skill) => {
            const isLocked =
              skill.requiredTier !== "free" &&
              !tierUnlocked(userTier, skill.requiredTier as TierName);
            return (
              <SkillCard
                key={skill.id}
                skill={skill}
                enabled={enabledSkills.has(skill.id)}
                onToggle={handleToggle}
                onLockedClick={handleLockedClick}
                isLocked={isLocked}
              />
            );
          })}
        </div>
      </div>

      {/* Save */}
      <Button
        variant="gold"
        onClick={handleSave}
        isLoading={saving}
        disabled={!dirty}
        className="w-full"
      >
        <Save className="h-4 w-4" />
        Save Skills
      </Button>
    </div>
  );
}
