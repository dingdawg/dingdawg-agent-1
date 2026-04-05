"use client";

/**
 * OnboardingCards — interactive inline modules for chat-based onboarding.
 *
 * Research-backed design (2026 best practices):
 * - ONE clear action per card
 * - Quick reply buttons > typing
 * - Progressive disclosure (one step at a time)
 * - Visual + familiar (social login, emoji icons, progress bars)
 * - 3-5 steps max for full onboarding
 *
 * Color scheme: DingDawg dark theme
 *   --gold-500: #F6B400 (primary accent)
 *   --ink-950: #07111c (background)
 *   --foreground: #f1f5f9 (text)
 *   --color-muted: #94a3b8 (secondary text)
 *   --stroke: rgba(255,255,255,0.08) (borders)
 */

import { useState } from "react";
import {
  CheckCircle,
  ChevronRight,
  Loader2,
  ArrowRight,
} from "lucide-react";
import { cn } from "@/lib/utils";

// ─── 1. Welcome Card ──────────────────────────────────────────────────────────
// Avatar + greeting + quick action pills. First thing user sees.

export interface WelcomeCardProps {
  agentName: string;
  userName?: string;
  quickActions: string[];
  onAction: (action: string) => void;
}

export function WelcomeCard({
  agentName,
  userName,
  quickActions,
  onAction,
}: WelcomeCardProps) {
  const greeting = userName
    ? `Hi ${userName}! I'm ${agentName}, your AI agent.`
    : `Hi! I'm ${agentName}, your AI agent.`;

  return (
    <div className="glass-panel p-5 max-w-sm">
      <p className="text-sm text-[var(--foreground)] leading-relaxed mb-4">
        {greeting} What would you like to do?
      </p>
      <div className="flex flex-wrap gap-2">
        {quickActions.map((action) => (
          <button
            key={action}
            onClick={() => onAction(action)}
            className="px-4 py-2.5 rounded-full text-sm font-medium border border-[var(--gold-500)]/30 text-[var(--gold-500)] hover:bg-[var(--gold-500)]/10 hover:border-[var(--gold-500)]/50 transition-colors min-h-[44px]"
          >
            {action}
          </button>
        ))}
      </div>
    </div>
  );
}

// ─── 2. Selection Card ────────────────────────────────────────────────────────
// Pick from a list of options with emoji icons. One tap.

export interface SelectionOption {
  id: string;
  label: string;
  emoji: string;
  description?: string;
}

export interface SelectionCardProps {
  title: string;
  subtitle?: string;
  options: SelectionOption[];
  onSelect: (optionId: string) => void;
  columns?: 2 | 3;
}

export function SelectionCard({
  title,
  subtitle,
  options,
  onSelect,
  columns = 2,
}: SelectionCardProps) {
  const [selectedId, setSelectedId] = useState<string | null>(null);

  function handleSelect(id: string) {
    setSelectedId(id);
    // Small delay for visual feedback before callback
    setTimeout(() => onSelect(id), 200);
  }

  return (
    <div className="glass-panel p-5 max-w-md">
      <p className="text-sm font-semibold text-[var(--foreground)] mb-1">
        {title}
      </p>
      {subtitle && (
        <p className="text-xs text-[var(--color-muted)] mb-4">{subtitle}</p>
      )}
      <div
        className={cn(
          "grid gap-2",
          columns === 3 ? "grid-cols-3" : "grid-cols-2"
        )}
      >
        {options.map((opt) => (
          <button
            key={opt.id}
            onClick={() => handleSelect(opt.id)}
            className={cn(
              "flex flex-col items-center gap-1.5 p-3 rounded-xl border transition-all min-h-[44px]",
              selectedId === opt.id
                ? "bg-[var(--gold-500)]/15 border-[var(--gold-500)]/40 scale-[0.97]"
                : "bg-white/3 border-[var(--stroke)] hover:border-[var(--gold-500)]/30 hover:bg-white/5"
            )}
          >
            <span className="text-2xl">{opt.emoji}</span>
            <span className="text-xs font-medium text-[var(--foreground)] text-center leading-tight">
              {opt.label}
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}

// ─── 3. Input Card ────────────────────────────────────────────────────────────
// Single-field inline form. Business name, phone, email, etc.

export interface InputCardProps {
  title: string;
  placeholder: string;
  type?: "text" | "tel" | "email" | "url";
  submitLabel?: string;
  onSubmit: (value: string) => void;
  icon?: string;
}

export function InputCard({
  title,
  placeholder,
  type = "text",
  submitLabel = "Continue",
  onSubmit,
  icon,
}: InputCardProps) {
  const [value, setValue] = useState("");
  const [submitted, setSubmitted] = useState(false);

  function handleSubmit() {
    if (!value.trim()) return;
    setSubmitted(true);
    onSubmit(value.trim());
  }

  if (submitted) {
    return (
      <div className="glass-panel p-4 max-w-sm">
        <div className="flex items-center gap-2">
          <CheckCircle className="h-4 w-4 text-green-400" />
          <span className="text-sm text-[var(--foreground)]">{value}</span>
        </div>
      </div>
    );
  }

  return (
    <div className="glass-panel p-5 max-w-sm">
      <p className="text-sm font-medium text-[var(--foreground)] mb-3">
        {icon && <span className="mr-1.5">{icon}</span>}
        {title}
      </p>
      <div className="flex gap-2">
        <input
          type={type}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleSubmit()}
          placeholder={placeholder}
          className="flex-1 px-3 py-2.5 rounded-lg text-sm bg-white/5 border border-[var(--stroke)] text-[var(--foreground)] placeholder:text-[var(--color-muted)] focus:outline-none focus:ring-2 focus:ring-[var(--gold-500)] min-h-[44px]"
          autoFocus
        />
        <button
          onClick={handleSubmit}
          disabled={!value.trim()}
          className="px-4 py-2.5 rounded-lg text-sm font-semibold bg-[var(--gold-500)] text-[#07111c] hover:bg-[var(--gold-600)] hover:brightness-110 disabled:opacity-40 transition-colors min-h-[44px] flex items-center gap-1.5"
        >
          {submitLabel}
          <ArrowRight className="h-3.5 w-3.5" />
        </button>
      </div>
    </div>
  );
}

// ─── 4. OAuth Card ────────────────────────────────────────────────────────────
// Branded social login buttons inline in chat.

export interface OAuthProvider {
  id: string;
  label: string;
  icon: string;
  color: string;
  bgColor: string;
}

const DEFAULT_PROVIDERS: OAuthProvider[] = [
  { id: "google", label: "Continue with Google", icon: "🔵", color: "#fff", bgColor: "#4285F4" },
  { id: "microsoft", label: "Continue with Microsoft", icon: "🟦", color: "#fff", bgColor: "#00A4EF" },
  { id: "apple", label: "Continue with Apple", icon: "🍎", color: "#fff", bgColor: "#333" },
];

export interface OAuthCardProps {
  title?: string;
  providers?: OAuthProvider[];
  onSelect: (providerId: string) => void;
  showEmailOption?: boolean;
  onEmailSelect?: () => void;
}

export function OAuthCard({
  title = "Connect your account",
  providers = DEFAULT_PROVIDERS,
  onSelect,
  showEmailOption = false,
  onEmailSelect,
}: OAuthCardProps) {
  const [connecting, setConnecting] = useState<string | null>(null);

  async function handleSelect(id: string) {
    setConnecting(id);
    onSelect(id);
  }

  return (
    <div className="glass-panel p-5 max-w-sm">
      <p className="text-sm font-medium text-[var(--foreground)] mb-4">
        {title}
      </p>
      <div className="flex flex-col gap-2.5">
        {providers.map((p) => (
          <button
            key={p.id}
            onClick={() => handleSelect(p.id)}
            disabled={connecting !== null}
            className="w-full flex items-center justify-center gap-2.5 px-4 py-3 rounded-xl text-sm font-semibold transition-all min-h-[48px] hover:brightness-110 disabled:opacity-60"
            style={{ backgroundColor: p.bgColor, color: p.color }}
          >
            {connecting === p.id ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <span className="text-base">{p.icon}</span>
            )}
            {p.label}
          </button>
        ))}
        {showEmailOption && (
          <button
            onClick={onEmailSelect}
            className="w-full flex items-center justify-center gap-2 px-4 py-3 rounded-xl text-sm font-medium border border-[var(--stroke2)] text-[var(--foreground)] hover:bg-white/5 transition-colors min-h-[48px]"
          >
            ✉️ Continue with email
          </button>
        )}
      </div>
    </div>
  );
}

// ─── 5. Progress Card ─────────────────────────────────────────────────────────
// "Step 2 of 4" with visual progress bar. Lightweight.

export interface StepProgressCardProps {
  currentStep: number;
  totalSteps: number;
  stepLabel: string;
  subtitle?: string;
}

export function StepProgressCard({
  currentStep,
  totalSteps,
  stepLabel,
  subtitle,
}: StepProgressCardProps) {
  const pct = Math.round((currentStep / totalSteps) * 100);

  return (
    <div className="glass-panel p-4 max-w-sm">
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs font-medium text-[var(--gold-500)]">
          Step {currentStep} of {totalSteps}
        </span>
        <span className="text-xs text-[var(--color-muted)]">{pct}%</span>
      </div>
      <div className="h-1.5 rounded-full bg-white/10 overflow-hidden mb-3">
        <div
          className="h-full rounded-full bg-[var(--gold-500)] transition-all duration-500"
          style={{ width: `${pct}%` }}
        />
      </div>
      <p className="text-sm font-medium text-[var(--foreground)]">
        {stepLabel}
      </p>
      {subtitle && (
        <p className="text-xs text-[var(--color-muted)] mt-0.5">{subtitle}</p>
      )}
    </div>
  );
}

// ─── 6. Confirm Card ──────────────────────────────────────────────────────────
// Summary of what user entered + "Looks good!" / "Change something"

export interface ConfirmItem {
  label: string;
  value: string;
  emoji?: string;
}

export interface ConfirmSummaryCardProps {
  title?: string;
  items: ConfirmItem[];
  confirmLabel?: string;
  changeLabel?: string;
  onConfirm: () => void;
  onChange: () => void;
}

export function ConfirmSummaryCard({
  title = "Here's what I have:",
  items,
  confirmLabel = "Looks good!",
  changeLabel = "Change something",
  onConfirm,
  onChange,
}: ConfirmSummaryCardProps) {
  return (
    <div className="glass-panel p-5 max-w-sm">
      <p className="text-sm font-medium text-[var(--foreground)] mb-3">
        {title}
      </p>
      <div className="flex flex-col gap-2 mb-4">
        {items.map((item, i) => (
          <div
            key={i}
            className="flex items-center gap-2.5 px-3 py-2 rounded-lg bg-white/3 border border-[var(--stroke)]"
          >
            {item.emoji && <span className="text-base">{item.emoji}</span>}
            <div className="flex-1 min-w-0">
              <span className="text-[10px] text-[var(--color-muted)] uppercase tracking-wider">
                {item.label}
              </span>
              <p className="text-sm text-[var(--foreground)] truncate">
                {item.value}
              </p>
            </div>
          </div>
        ))}
      </div>
      <div className="flex gap-2">
        <button
          onClick={onConfirm}
          className="flex-1 px-4 py-2.5 rounded-xl text-sm font-semibold bg-[var(--gold-500)] text-[#07111c] hover:bg-[var(--gold-600)] hover:brightness-110 transition-colors min-h-[44px] flex items-center justify-center gap-1.5"
        >
          <CheckCircle className="h-4 w-4" />
          {confirmLabel}
        </button>
        <button
          onClick={onChange}
          className="px-4 py-2.5 rounded-xl text-sm font-medium border border-[var(--stroke2)] text-[var(--color-muted)] hover:text-[var(--foreground)] hover:bg-white/5 transition-colors min-h-[44px]"
        >
          {changeLabel}
        </button>
      </div>
    </div>
  );
}

// ─── 7. Success Card ──────────────────────────────────────────────────────────
// Checkmark animation + "You're all set!" with next action.

export interface SuccessCardProps {
  title?: string;
  message?: string;
  nextAction?: string;
  onNextAction?: () => void;
}

export function SuccessCard({
  title = "You're all set!",
  message,
  nextAction,
  onNextAction,
}: SuccessCardProps) {
  return (
    <div className="glass-panel p-6 max-w-sm text-center">
      <div className="h-14 w-14 rounded-full bg-green-500/15 border border-green-500/30 flex items-center justify-center mx-auto mb-3 animate-[scale-in_0.4s_ease-out]">
        <CheckCircle className="h-7 w-7 text-green-400" />
      </div>
      <p className="text-base font-semibold text-[var(--foreground)] mb-1">
        {title}
      </p>
      {message && (
        <p className="text-sm text-[var(--color-muted)] mb-4">{message}</p>
      )}
      {nextAction && onNextAction && (
        <button
          onClick={onNextAction}
          className="px-6 py-2.5 rounded-xl text-sm font-semibold bg-[var(--gold-500)] text-[#07111c] hover:bg-[var(--gold-600)] hover:brightness-110 transition-colors min-h-[44px] inline-flex items-center gap-1.5"
        >
          {nextAction}
          <ChevronRight className="h-4 w-4" />
        </button>
      )}
    </div>
  );
}

// ─── 8. Checklist Card ────────────────────────────────────────────────────────
// Setup progress checklist. Shows what's done + what's next.

export interface ChecklistItem {
  id: string;
  label: string;
  done: boolean;
  emoji?: string;
}

export interface ChecklistCardProps {
  title?: string;
  items: ChecklistItem[];
  onItemClick: (itemId: string) => void;
}

export function ChecklistCard({
  title = "Get your agent ready",
  items,
  onItemClick,
}: ChecklistCardProps) {
  const completed = items.filter((i) => i.done).length;

  return (
    <div className="glass-panel p-5 max-w-sm">
      <div className="flex items-center justify-between mb-3">
        <p className="text-sm font-semibold text-[var(--foreground)]">
          {title}
        </p>
        <span className="text-xs text-[var(--gold-500)] font-medium">
          {completed}/{items.length}
        </span>
      </div>
      <div className="h-1 rounded-full bg-white/10 overflow-hidden mb-4">
        <div
          className="h-full rounded-full bg-[var(--gold-500)] transition-all duration-500"
          style={{ width: `${(completed / items.length) * 100}%` }}
        />
      </div>
      <div className="flex flex-col gap-1.5">
        {items.map((item) => (
          <button
            key={item.id}
            onClick={() => !item.done && onItemClick(item.id)}
            disabled={item.done}
            className={cn(
              "flex items-center gap-2.5 px-3 py-2.5 rounded-lg text-left transition-colors min-h-[44px]",
              item.done
                ? "bg-green-500/5 border border-green-500/10"
                : "bg-white/3 border border-[var(--stroke)] hover:border-[var(--gold-500)]/30 hover:bg-white/5"
            )}
          >
            {item.done ? (
              <CheckCircle className="h-4 w-4 text-green-400 flex-shrink-0" />
            ) : (
              <div className="h-4 w-4 rounded-full border-2 border-[var(--color-muted)] flex-shrink-0" />
            )}
            <span
              className={cn(
                "text-sm flex-1",
                item.done
                  ? "text-[var(--color-muted)] line-through"
                  : "text-[var(--foreground)]"
              )}
            >
              {item.emoji && <span className="mr-1.5">{item.emoji}</span>}
              {item.label}
            </span>
            {!item.done && (
              <ChevronRight className="h-3.5 w-3.5 text-[var(--color-muted)] flex-shrink-0" />
            )}
          </button>
        ))}
      </div>
    </div>
  );
}
