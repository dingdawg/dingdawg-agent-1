"use client";

/**
 * OnboardingChatStream — Guided setup wizard styled as a chat conversation.
 *
 * Feels like texting a friend: agent messages appear on the left with a gold
 * accent border; user selections bubble in on the right. Each step is 1–2
 * taps, minimal typing.
 *
 * Steps (9 total):
 *   1. Welcome        — business name text input
 *   2. Industry       — 8 clickable industry cards
 *   3. Template       — filtered template grid (click to select)
 *   4. Stripe         — one-click OAuth connect button
 *   5. SMS / Phone    — toggle + phone number input (skippable)
 *   6. Email          — toggle + email input (skippable)
 *   7. Security       — Face ID / Passkey enrollment (skippable)
 *   8. Configure      — business hours, auto-reply, personality
 *   9. Go Live        — big Launch button
 *
 * Design tokens follow the Agent 1 dark-glass theme (globals.css).
 * All interactive elements meet the 44 px minimum touch target.
 */

import { useState, useEffect, useRef, useCallback } from "react";

// ─── Types ────────────────────────────────────────────────────────────────────

type StepId =
  | "welcome"
  | "industry"
  | "template"
  | "stripe"
  | "sms"
  | "email"
  | "security"
  | "configure"
  | "golive";

interface Industry {
  id: string;
  label: string;
  icon: string;
}

interface Template {
  id: string;
  name: string;
  icon: string;
  caps: string[];
  popular?: boolean;
}

interface HourRange {
  open: string;
  close: string;
}

interface BusinessHours {
  mon: HourRange;
  tue: HourRange;
  wed: HourRange;
  thu: HourRange;
  fri: HourRange;
  sat: HourRange;
  sun: HourRange;
}

interface WizardState {
  businessName: string;
  industry: string | null;
  templateId: string | null;
  stripeConnected: boolean;
  smsEnabled: boolean;
  phone: string;
  emailEnabled: boolean;
  email: string;
  passkeyEnrolled: boolean;
  autoReply: boolean;
  personality: number; // 0 = formal, 100 = casual
  hours: BusinessHours;
  hoursEnabled: boolean;
}

// ─── Constants ────────────────────────────────────────────────────────────────

const TOTAL_STEPS = 9;

const STEP_ORDER: StepId[] = [
  "welcome",
  "industry",
  "template",
  "stripe",
  "sms",
  "email",
  "security",
  "configure",
  "golive",
];

const OPTIONAL_STEPS: StepId[] = ["sms", "email", "security"];

const INDUSTRIES: Industry[] = [
  { id: "restaurant", label: "Restaurant", icon: "🍽️" },
  { id: "salon", label: "Salon", icon: "💇" },
  { id: "autoshop", label: "Auto Shop", icon: "🔧" },
  { id: "fitness", label: "Fitness", icon: "💪" },
  { id: "retail", label: "Retail", icon: "🛍️" },
  { id: "gaming", label: "Gaming", icon: "🎮" },
  { id: "services", label: "Services", icon: "🛠️" },
  { id: "custom", label: "Custom", icon: "✨" },
];

/** Demo templates — in production these would be fetched from /api/v1/templates */
const TEMPLATES_BY_INDUSTRY: Record<string, Template[]> = {
  restaurant: [
    { id: "r1", name: "Full-Service Dining", icon: "🍴", caps: ["Reservations", "Menu AI", "Reviews"], popular: true },
    { id: "r2", name: "Fast Casual", icon: "🍔", caps: ["Orders", "Loyalty", "SMS alerts"], popular: true },
    { id: "r3", name: "Food Truck", icon: "🚚", caps: ["Location updates", "Pre-orders"] },
    { id: "r4", name: "Catering", icon: "🥗", caps: ["Event booking", "Quotes"] },
  ],
  salon: [
    { id: "s1", name: "Hair & Beauty", icon: "💅", caps: ["Appointments", "Reminders", "Loyalty"], popular: true },
    { id: "s2", name: "Barbershop", icon: "✂️", caps: ["Walk-ins", "Queue", "Promos"], popular: true },
    { id: "s3", name: "Nail Studio", icon: "💍", caps: ["Booking", "Aftercare tips"] },
  ],
  autoshop: [
    { id: "a1", name: "General Repair", icon: "🔩", caps: ["Estimates", "Status updates", "Pickups"], popular: true },
    { id: "a2", name: "Oil & Lube", icon: "🛢️", caps: ["Quick book", "Reminders"], popular: true },
  ],
  fitness: [
    { id: "f1", name: "Gym / CrossFit", icon: "🏋️", caps: ["Class booking", "Progress", "Nutrition"], popular: true },
    { id: "f2", name: "Personal Training", icon: "🤸", caps: ["Session scheduling", "Check-ins"], popular: true },
  ],
  retail: [
    { id: "re1", name: "Boutique Shop", icon: "👗", caps: ["Inventory", "Promos", "Loyalty"], popular: true },
    { id: "re2", name: "E-commerce + Local", icon: "📦", caps: ["Order tracking", "Pickup"], popular: true },
  ],
  gaming: [
    { id: "g1", name: "Esports Lounge", icon: "🕹️", caps: ["Session booking", "Tournaments", "Leaderboards"], popular: true },
    { id: "g2", name: "Board Game Cafe", icon: "🎲", caps: ["Reservations", "Game recs"], popular: true },
  ],
  services: [
    { id: "sv1", name: "Home Services", icon: "🏠", caps: ["Quotes", "Scheduling", "Follow-ups"], popular: true },
    { id: "sv2", name: "Cleaning", icon: "🧹", caps: ["Recurring booking", "Reminders"], popular: true },
  ],
  custom: [
    { id: "c1", name: "Starter Blank", icon: "📄", caps: ["Fully customisable"], popular: true },
    { id: "c2", name: "Full AI Suite", icon: "🤖", caps: ["All features enabled"], popular: true },
  ],
};

const DEFAULT_HOURS: BusinessHours = {
  mon: { open: "09:00", close: "18:00" },
  tue: { open: "09:00", close: "18:00" },
  wed: { open: "09:00", close: "18:00" },
  thu: { open: "09:00", close: "18:00" },
  fri: { open: "09:00", close: "18:00" },
  sat: { open: "10:00", close: "16:00" },
  sun: { open: "10:00", close: "16:00" },
};

// ─── Sub-components ───────────────────────────────────────────────────────────

/** Animated chat bubble from the agent (left side). */
function AgentBubble({
  children,
  animKey,
}: {
  children: React.ReactNode;
  animKey: string | number;
}) {
  return (
    <div
      key={animKey}
      className="flex items-start gap-3 animate-in slide-in-from-left-4 fade-in duration-300"
      aria-live="polite"
    >
      {/* Avatar */}
      <div
        className="flex-shrink-0 w-8 h-8 rounded-full flex items-center justify-center text-sm font-bold border"
        style={{
          background: "rgba(246,180,0,0.12)",
          borderColor: "rgba(246,180,0,0.35)",
          color: "var(--gold-500)",
        }}
        aria-hidden="true"
      >
        DD
      </div>

      {/* Bubble */}
      <div
        className="relative max-w-[85%] px-4 py-3 rounded-2xl rounded-tl-sm text-sm leading-relaxed"
        style={{
          background: "rgba(15, 33, 51, 0.85)",
          border: "1px solid rgba(246,180,0,0.25)",
          color: "var(--foreground)",
        }}
      >
        {/* Gold left accent line */}
        <div
          className="absolute left-0 top-3 bottom-3 w-0.5 rounded-full"
          style={{ background: "var(--gold-500)", opacity: 0.7 }}
          aria-hidden="true"
        />
        <div className="pl-2">{children}</div>
      </div>
    </div>
  );
}

/** User reply bubble (right side). */
function UserBubble({
  children,
  animKey,
}: {
  children: React.ReactNode;
  animKey: string | number;
}) {
  return (
    <div
      key={animKey}
      className="flex justify-end animate-in slide-in-from-right-4 fade-in duration-300"
    >
      <div
        className="max-w-[80%] px-4 py-3 rounded-2xl rounded-tr-sm text-sm font-medium"
        style={{
          background: "rgba(246,180,0,0.18)",
          border: "1px solid rgba(246,180,0,0.3)",
          color: "var(--gold-500)",
        }}
      >
        {children}
      </div>
    </div>
  );
}

/** The floating input/action panel that appears below the chat. */
function ActionPanel({ children }: { children: React.ReactNode }) {
  return (
    <div
      className="animate-in slide-in-from-bottom-4 fade-in duration-300"
      style={{
        background: "rgba(10,16,24,0.95)",
        border: "1px solid rgba(255,255,255,0.08)",
        borderRadius: "1.25rem",
        padding: "1.25rem",
      }}
    >
      {children}
    </div>
  );
}

/** Skip button for optional steps. */
function SkipButton({ onSkip }: { onSkip: () => void }) {
  return (
    <button
      onClick={onSkip}
      className="w-full mt-2 py-2.5 text-sm transition-colors"
      style={{ color: "var(--color-muted)", opacity: 0.7 }}
      onMouseEnter={(e) => (e.currentTarget.style.opacity = "1")}
      onMouseLeave={(e) => (e.currentTarget.style.opacity = "0.7")}
    >
      Skip for now
    </button>
  );
}

/** Gold primary action button (large, touch-friendly). */
function PrimaryButton({
  onClick,
  disabled,
  isLoading,
  children,
  className = "",
}: {
  onClick: () => void;
  disabled?: boolean;
  isLoading?: boolean;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled || isLoading}
      className={`w-full flex items-center justify-center gap-2 rounded-2xl text-base font-semibold transition-all duration-200 min-h-[52px] px-6 ${className}`}
      style={{
        background: disabled ? "rgba(246,180,0,0.25)" : "var(--gold-500)",
        color: disabled ? "rgba(7,17,28,0.5)" : "#07111c",
        cursor: disabled ? "not-allowed" : "pointer",
        boxShadow: disabled ? "none" : "0 4px 24px rgba(246,180,0,0.25)",
      }}
      onMouseEnter={(e) => {
        if (!disabled) {
          e.currentTarget.style.background = "var(--gold-600, #e9a600)";
          e.currentTarget.style.boxShadow = "0 6px 32px rgba(246,180,0,0.35)";
        }
      }}
      onMouseLeave={(e) => {
        if (!disabled) {
          e.currentTarget.style.background = "var(--gold-500)";
          e.currentTarget.style.boxShadow = "0 4px 24px rgba(246,180,0,0.25)";
        }
      }}
    >
      {isLoading ? (
        <span
          className="inline-block w-5 h-5 rounded-full border-2 border-t-transparent animate-spin"
          style={{ borderColor: "rgba(7,17,28,0.4)", borderTopColor: "transparent" }}
          aria-hidden="true"
        />
      ) : (
        children
      )}
    </button>
  );
}

/** Toggle switch component. */
function Toggle({
  enabled,
  onToggle,
  label,
}: {
  enabled: boolean;
  onToggle: () => void;
  label: string;
}) {
  return (
    <button
      role="switch"
      aria-checked={enabled}
      aria-label={label}
      onClick={onToggle}
      className="relative flex-shrink-0 w-12 h-7 rounded-full transition-colors duration-200 focus-visible:outline-none focus-visible:ring-2"
      style={{
        background: enabled ? "var(--gold-500)" : "rgba(255,255,255,0.1)",
      }}
    >
      <span
        className="absolute top-0.5 left-0.5 w-6 h-6 rounded-full bg-white shadow-md transition-transform duration-200"
        style={{ transform: enabled ? "translateX(20px)" : "translateX(0)" }}
        aria-hidden="true"
      />
    </button>
  );
}

// ─── Main Component ───────────────────────────────────────────────────────────

interface OnboardingChatStreamProps {
  onComplete?: (state: WizardState) => void;
}

export default function OnboardingChatStream({
  onComplete,
}: OnboardingChatStreamProps) {
  // ── Core state ─────────────────────────────────────────────────────────────
  const [currentStepIndex, setCurrentStepIndex] = useState(0);
  const [launching, setLaunching] = useState(false);
  const [launched, setLaunched] = useState(false);

  const [wizard, setWizard] = useState<WizardState>({
    businessName: "",
    industry: null,
    templateId: null,
    stripeConnected: false,
    smsEnabled: false,
    phone: "",
    emailEnabled: false,
    email: "",
    passkeyEnrolled: false,
    autoReply: true,
    personality: 50,
    hours: DEFAULT_HOURS,
    hoursEnabled: true,
  });

  const currentStep = STEP_ORDER[currentStepIndex];
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // ── Scroll to bottom on each new step ──────────────────────────────────────
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [currentStepIndex]);

  // ── Navigation helpers ──────────────────────────────────────────────────────
  const advance = useCallback(() => {
    setCurrentStepIndex((i) => Math.min(i + 1, TOTAL_STEPS - 1));
  }, []);

  const skipStep = useCallback(() => {
    advance();
  }, [advance]);

  // ── Launch ──────────────────────────────────────────────────────────────────
  const handleLaunch = useCallback(async () => {
    setLaunching(true);
    // Simulate API call — replace with real POST /api/v1/onboarding/setup
    await new Promise((r) => setTimeout(r, 1400));
    setLaunching(false);
    setLaunched(true);
    onComplete?.(wizard);
  }, [wizard, onComplete]);

  // ── Update helpers ──────────────────────────────────────────────────────────
  const set = useCallback(
    <K extends keyof WizardState>(key: K, value: WizardState[K]) => {
      setWizard((prev) => ({ ...prev, [key]: value }));
    },
    []
  );

  // ── Derived values ──────────────────────────────────────────────────────────
  const progressPercent = Math.round(
    ((currentStepIndex + 1) / TOTAL_STEPS) * 100
  );

  const industryLabel =
    INDUSTRIES.find((i) => i.id === wizard.industry)?.label ?? "";

  const templates = wizard.industry
    ? TEMPLATES_BY_INDUSTRY[wizard.industry] ?? []
    : [];

  const selectedTemplate = templates.find((t) => t.id === wizard.templateId);

  // ── Render ──────────────────────────────────────────────────────────────────
  return (
    <div
      className="flex flex-col min-h-screen w-full max-w-lg mx-auto px-4 pb-8"
      style={{ background: "var(--background)", color: "var(--foreground)" }}
    >
      {/* ── Progress bar ───────────────────────────────────────────────────── */}
      <div className="sticky top-0 z-10 pt-4 pb-3" style={{ background: "var(--background)" }}>
        <div className="flex items-center justify-between mb-2">
          <span className="text-xs font-medium" style={{ color: "var(--gold-500)" }}>
            Step {currentStepIndex + 1} of {TOTAL_STEPS}
          </span>
          <span className="text-xs" style={{ color: "rgba(148,163,184,0.6)" }}>
            {progressPercent}% complete
          </span>
        </div>
        <div
          className="h-1.5 w-full rounded-full overflow-hidden"
          style={{ background: "rgba(255,255,255,0.06)" }}
          role="progressbar"
          aria-valuenow={progressPercent}
          aria-valuemin={0}
          aria-valuemax={100}
        >
          <div
            className="h-full rounded-full transition-all duration-500 ease-out"
            style={{
              width: `${progressPercent}%`,
              background: "linear-gradient(90deg, var(--gold-500), #ffcf40)",
              boxShadow: "0 0 8px rgba(246,180,0,0.4)",
            }}
          />
        </div>
      </div>

      {/* ── Chat messages (history) ─────────────────────────────────────────── */}
      <div className="flex flex-col gap-4 flex-1 pt-2">

        {/* ── STEP 1: Welcome ─────────────────────────────────────────────── */}
        <AgentBubble animKey="welcome-q">
          <p className="font-semibold mb-0.5">Hey! 👋 Welcome to DingDawg.</p>
          <p className="text-sm" style={{ color: "rgba(241,245,249,0.75)" }}>
            Let&apos;s get your AI agent set up in about 2 minutes. What&apos;s
            your business name?
          </p>
        </AgentBubble>

        {currentStepIndex > 0 && wizard.businessName && (
          <UserBubble animKey="welcome-a">{wizard.businessName}</UserBubble>
        )}

        {/* ── STEP 2: Industry ────────────────────────────────────────────── */}
        {currentStepIndex >= 1 && (
          <AgentBubble animKey="industry-q">
            <p>
              Nice,{" "}
              <span style={{ color: "var(--gold-500)" }} className="font-semibold">
                {wizard.businessName}
              </span>
              ! What industry are you in?
            </p>
          </AgentBubble>
        )}

        {currentStepIndex > 1 && wizard.industry && (
          <UserBubble animKey="industry-a">
            {INDUSTRIES.find((i) => i.id === wizard.industry)?.icon}{" "}
            {industryLabel}
          </UserBubble>
        )}

        {/* ── STEP 3: Template ────────────────────────────────────────────── */}
        {currentStepIndex >= 2 && (
          <AgentBubble animKey="template-q">
            <p>
              Here are some templates built for{" "}
              <span style={{ color: "var(--gold-500)" }} className="font-semibold">
                {industryLabel}
              </span>
              :
            </p>
          </AgentBubble>
        )}

        {currentStepIndex > 2 && selectedTemplate && (
          <UserBubble animKey="template-a">
            {selectedTemplate.icon} {selectedTemplate.name}
          </UserBubble>
        )}

        {/* ── STEP 4: Stripe ──────────────────────────────────────────────── */}
        {currentStepIndex >= 3 && (
          <AgentBubble animKey="stripe-q">
            <p>
              {wizard.templateId ? "Great choice! " : ""}
              Let&apos;s connect payments so you can start accepting orders.
            </p>
          </AgentBubble>
        )}

        {currentStepIndex > 3 && (
          <UserBubble animKey="stripe-a">
            {wizard.stripeConnected ? "✅ Stripe connected" : "Skipped for now"}
          </UserBubble>
        )}

        {/* ── STEP 5: SMS ─────────────────────────────────────────────────── */}
        {currentStepIndex >= 4 && (
          <AgentBubble animKey="sms-q">
            <p>Want SMS alerts? Your customers can text your agent directly.</p>
          </AgentBubble>
        )}

        {currentStepIndex > 4 && (
          <UserBubble animKey="sms-a">
            {wizard.smsEnabled && wizard.phone
              ? `📱 ${wizard.phone}`
              : "Skipped SMS"}
          </UserBubble>
        )}

        {/* ── STEP 6: Email ───────────────────────────────────────────────── */}
        {currentStepIndex >= 5 && (
          <AgentBubble animKey="email-q">
            <p>How about email notifications for new bookings and messages?</p>
          </AgentBubble>
        )}

        {currentStepIndex > 5 && (
          <UserBubble animKey="email-a">
            {wizard.emailEnabled && wizard.email
              ? `✉️ ${wizard.email}`
              : "Skipped email"}
          </UserBubble>
        )}

        {/* ── STEP 7: Security ────────────────────────────────────────────── */}
        {currentStepIndex >= 6 && (
          <AgentBubble animKey="security-q">
            <p>
              Secure your account with a passkey — faster than a password and
              works with Face ID or Touch ID.
            </p>
          </AgentBubble>
        )}

        {currentStepIndex > 6 && (
          <UserBubble animKey="security-a">
            {wizard.passkeyEnrolled ? "🔑 Passkey enrolled" : "Skipped security"}
          </UserBubble>
        )}

        {/* ── STEP 8: Configure ───────────────────────────────────────────── */}
        {currentStepIndex >= 7 && (
          <AgentBubble animKey="configure-q">
            <p>Almost done! A few last touches to personalise your agent.</p>
          </AgentBubble>
        )}

        {currentStepIndex > 7 && (
          <UserBubble animKey="configure-a">
            {`Hours ${wizard.hoursEnabled ? "on" : "off"} · Auto-reply ${wizard.autoReply ? "on" : "off"} · Personality ${wizard.personality <= 33 ? "formal" : wizard.personality <= 66 ? "balanced" : "casual"}`}
          </UserBubble>
        )}

        {/* ── STEP 9: Go Live ─────────────────────────────────────────────── */}
        {currentStepIndex >= 8 && !launched && (
          <AgentBubble animKey="golive-q">
            <p className="font-semibold">
              You&apos;re all set, {wizard.businessName}! 🎉
            </p>
            <p className="text-sm mt-1" style={{ color: "rgba(241,245,249,0.75)" }}>
              Your AI agent is ready to go live. Hit the button below when
              you&apos;re ready.
            </p>
          </AgentBubble>
        )}

        {launched && (
          <AgentBubble animKey="launched">
            <p className="font-semibold text-base">
              🚀{" "}
              <span style={{ color: "var(--gold-500)" }}>
                {wizard.businessName}
              </span>{" "}
              is live!
            </p>
            <p className="text-sm mt-1" style={{ color: "rgba(241,245,249,0.75)" }}>
              Your agent is answering customers right now. Head to your
              dashboard to see it in action.
            </p>
          </AgentBubble>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* ── Active action panel ─────────────────────────────────────────────── */}
      {!launched && (
        <div className="sticky bottom-0 pt-4" style={{ background: "var(--background)" }}>

          {/* STEP 1: Business name */}
          {currentStep === "welcome" && (
            <ActionPanel>
              <label
                htmlFor="biz-name"
                className="block text-xs font-medium mb-2"
                style={{ color: "rgba(148,163,184,0.8)" }}
              >
                Business name
              </label>
              <input
                id="biz-name"
                type="text"
                value={wizard.businessName}
                onChange={(e) => set("businessName", e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && wizard.businessName.trim().length >= 2)
                    advance();
                }}
                placeholder="e.g. Mia's Café"
                maxLength={80}
                autoFocus
                className="w-full rounded-2xl px-4 py-3.5 text-base outline-none transition-colors mb-3"
                style={{
                  background: "rgba(255,255,255,0.05)",
                  border: "1px solid rgba(255,255,255,0.1)",
                  color: "var(--foreground)",
                  caretColor: "var(--gold-500)",
                }}
                onFocus={(e) => (e.currentTarget.style.borderColor = "rgba(246,180,0,0.5)")}
                onBlur={(e) => (e.currentTarget.style.borderColor = "rgba(255,255,255,0.1)")}
              />
              <PrimaryButton
                onClick={advance}
                disabled={wizard.businessName.trim().length < 2}
              >
                Continue →
              </PrimaryButton>
            </ActionPanel>
          )}

          {/* STEP 2: Industry cards */}
          {currentStep === "industry" && (
            <ActionPanel>
              <p className="text-xs font-medium mb-3" style={{ color: "rgba(148,163,184,0.8)" }}>
                Pick your industry
              </p>
              <div className="grid grid-cols-4 gap-2 mb-3">
                {INDUSTRIES.map((ind) => {
                  const isSelected = wizard.industry === ind.id;
                  return (
                    <button
                      key={ind.id}
                      onClick={() => {
                        set("industry", ind.id);
                        set("templateId", null);
                      }}
                      className="flex flex-col items-center gap-1.5 rounded-2xl py-3 px-1 transition-all duration-150 min-h-[72px] focus-visible:outline-none focus-visible:ring-2"
                      style={{
                        background: isSelected
                          ? "rgba(246,180,0,0.15)"
                          : "rgba(255,255,255,0.04)",
                        border: isSelected
                          ? "1px solid rgba(246,180,0,0.5)"
                          : "1px solid rgba(255,255,255,0.07)",
                        boxShadow: isSelected
                          ? "0 0 0 1px rgba(246,180,0,0.3)"
                          : "none",
                      }}
                      aria-pressed={isSelected}
                    >
                      <span className="text-xl leading-none" aria-hidden="true">
                        {ind.icon}
                      </span>
                      <span
                        className="text-[11px] font-medium leading-tight text-center"
                        style={{
                          color: isSelected ? "var(--gold-500)" : "var(--foreground)",
                        }}
                      >
                        {ind.label}
                      </span>
                    </button>
                  );
                })}
              </div>
              <PrimaryButton onClick={advance} disabled={!wizard.industry}>
                Continue →
              </PrimaryButton>
            </ActionPanel>
          )}

          {/* STEP 3: Template grid */}
          {currentStep === "template" && (
            <ActionPanel>
              <p className="text-xs font-medium mb-3" style={{ color: "rgba(148,163,184,0.8)" }}>
                Choose a starting template
              </p>
              <div className="flex flex-col gap-2 max-h-56 overflow-y-auto pr-0.5 mb-3">
                {templates.length === 0 ? (
                  <p className="text-sm text-center py-6" style={{ color: "rgba(148,163,184,0.6)" }}>
                    No templates yet — a blank agent will be created.
                  </p>
                ) : (
                  templates.map((tpl) => {
                    const isSelected = wizard.templateId === tpl.id;
                    return (
                      <button
                        key={tpl.id}
                        onClick={() => set("templateId", tpl.id)}
                        className="w-full text-left px-4 py-3 rounded-2xl transition-all duration-150 focus-visible:outline-none focus-visible:ring-2 min-h-[56px]"
                        style={{
                          background: isSelected
                            ? "rgba(246,180,0,0.12)"
                            : "rgba(255,255,255,0.04)",
                          border: isSelected
                            ? "1px solid rgba(246,180,0,0.45)"
                            : "1px solid rgba(255,255,255,0.07)",
                        }}
                        aria-pressed={isSelected}
                      >
                        <div className="flex items-center gap-3">
                          <span className="text-xl leading-none flex-shrink-0" aria-hidden="true">
                            {tpl.icon}
                          </span>
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-2">
                              <span
                                className="text-sm font-semibold truncate"
                                style={{
                                  color: isSelected ? "var(--gold-500)" : "var(--foreground)",
                                }}
                              >
                                {tpl.name}
                              </span>
                              {tpl.popular && (
                                <span
                                  className="flex-shrink-0 text-[9px] font-bold px-1.5 py-0.5 rounded-full"
                                  style={{
                                    background: "rgba(246,180,0,0.15)",
                                    border: "1px solid rgba(246,180,0,0.3)",
                                    color: "var(--gold-500)",
                                  }}
                                >
                                  POPULAR
                                </span>
                              )}
                            </div>
                            <span
                              className="text-[11px] truncate"
                              style={{ color: "rgba(148,163,184,0.7)" }}
                            >
                              {tpl.caps.join(" · ")}
                            </span>
                          </div>
                          {isSelected && (
                            <svg
                              className="flex-shrink-0 h-4 w-4"
                              style={{ color: "var(--gold-500)" }}
                              fill="none"
                              viewBox="0 0 24 24"
                              stroke="currentColor"
                              strokeWidth={2.5}
                              aria-hidden="true"
                            >
                              <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                            </svg>
                          )}
                        </div>
                      </button>
                    );
                  })
                )}
              </div>
              <PrimaryButton
                onClick={advance}
                disabled={!wizard.templateId && templates.length > 0}
              >
                Continue →
              </PrimaryButton>
            </ActionPanel>
          )}

          {/* STEP 4: Stripe connect */}
          {currentStep === "stripe" && (
            <ActionPanel>
              <div
                className="flex items-center gap-3 p-4 rounded-2xl mb-4"
                style={{
                  background: "rgba(99,214,130,0.06)",
                  border: "1px solid rgba(99,214,130,0.15)",
                }}
              >
                <span className="text-2xl" aria-hidden="true">
                  💳
                </span>
                <div>
                  <p className="text-sm font-semibold" style={{ color: "var(--foreground)" }}>
                    Stripe Payments
                  </p>
                  <p className="text-xs mt-0.5" style={{ color: "rgba(148,163,184,0.7)" }}>
                    Accept cards, Apple Pay &amp; Google Pay
                  </p>
                </div>
                {wizard.stripeConnected && (
                  <span className="ml-auto text-sm" style={{ color: "#4ade80" }}>
                    ✓ Connected
                  </span>
                )}
              </div>
              {!wizard.stripeConnected ? (
                <PrimaryButton
                  onClick={() => {
                    set("stripeConnected", true);
                    // In production: window.location.href = '/api/v1/stripe/connect/oauth'
                  }}
                >
                  Connect Stripe →
                </PrimaryButton>
              ) : (
                <PrimaryButton onClick={advance}>Continue →</PrimaryButton>
              )}
              {!wizard.stripeConnected && (
                <SkipButton onSkip={skipStep} />
              )}
            </ActionPanel>
          )}

          {/* STEP 5: SMS */}
          {currentStep === "sms" && (
            <ActionPanel>
              <div className="flex items-center justify-between mb-4">
                <div>
                  <p className="text-sm font-semibold" style={{ color: "var(--foreground)" }}>
                    SMS Notifications
                  </p>
                  <p className="text-xs mt-0.5" style={{ color: "rgba(148,163,184,0.7)" }}>
                    Get texts for new bookings &amp; messages
                  </p>
                </div>
                <Toggle
                  enabled={wizard.smsEnabled}
                  onToggle={() => set("smsEnabled", !wizard.smsEnabled)}
                  label="Toggle SMS notifications"
                />
              </div>
              {wizard.smsEnabled && (
                <div className="mb-4 animate-in fade-in duration-200">
                  <label
                    htmlFor="phone-input"
                    className="block text-xs font-medium mb-2"
                    style={{ color: "rgba(148,163,184,0.8)" }}
                  >
                    Your phone number
                  </label>
                  <input
                    id="phone-input"
                    type="tel"
                    inputMode="tel"
                    value={wizard.phone}
                    onChange={(e) => set("phone", e.target.value)}
                    placeholder="+1 (555) 000-0000"
                    className="w-full rounded-2xl px-4 py-3.5 text-base outline-none transition-colors"
                    style={{
                      background: "rgba(255,255,255,0.05)",
                      border: "1px solid rgba(255,255,255,0.1)",
                      color: "var(--foreground)",
                      caretColor: "var(--gold-500)",
                    }}
                    onFocus={(e) => (e.currentTarget.style.borderColor = "rgba(246,180,0,0.5)")}
                    onBlur={(e) => (e.currentTarget.style.borderColor = "rgba(255,255,255,0.1)")}
                    autoFocus
                  />
                </div>
              )}
              <PrimaryButton
                onClick={advance}
                disabled={wizard.smsEnabled && wizard.phone.trim().length < 7}
              >
                {wizard.smsEnabled ? "Save & Continue →" : "Continue →"}
              </PrimaryButton>
              {!wizard.smsEnabled && <SkipButton onSkip={skipStep} />}
            </ActionPanel>
          )}

          {/* STEP 6: Email */}
          {currentStep === "email" && (
            <ActionPanel>
              <div className="flex items-center justify-between mb-4">
                <div>
                  <p className="text-sm font-semibold" style={{ color: "var(--foreground)" }}>
                    Email Notifications
                  </p>
                  <p className="text-xs mt-0.5" style={{ color: "rgba(148,163,184,0.7)" }}>
                    Daily summaries &amp; booking confirmations
                  </p>
                </div>
                <Toggle
                  enabled={wizard.emailEnabled}
                  onToggle={() => set("emailEnabled", !wizard.emailEnabled)}
                  label="Toggle email notifications"
                />
              </div>
              {wizard.emailEnabled && (
                <div className="mb-4 animate-in fade-in duration-200">
                  <label
                    htmlFor="email-input"
                    className="block text-xs font-medium mb-2"
                    style={{ color: "rgba(148,163,184,0.8)" }}
                  >
                    Your email address
                  </label>
                  <input
                    id="email-input"
                    type="email"
                    inputMode="email"
                    value={wizard.email}
                    onChange={(e) => set("email", e.target.value)}
                    placeholder="you@example.com"
                    className="w-full rounded-2xl px-4 py-3.5 text-base outline-none transition-colors"
                    style={{
                      background: "rgba(255,255,255,0.05)",
                      border: "1px solid rgba(255,255,255,0.1)",
                      color: "var(--foreground)",
                      caretColor: "var(--gold-500)",
                    }}
                    onFocus={(e) => (e.currentTarget.style.borderColor = "rgba(246,180,0,0.5)")}
                    onBlur={(e) => (e.currentTarget.style.borderColor = "rgba(255,255,255,0.1)")}
                    autoFocus
                  />
                </div>
              )}
              <PrimaryButton
                onClick={advance}
                disabled={
                  wizard.emailEnabled &&
                  !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(wizard.email)
                }
              >
                {wizard.emailEnabled ? "Save & Continue →" : "Continue →"}
              </PrimaryButton>
              {!wizard.emailEnabled && <SkipButton onSkip={skipStep} />}
            </ActionPanel>
          )}

          {/* STEP 7: Security / Passkey */}
          {currentStep === "security" && (
            <ActionPanel>
              <div
                className="flex items-center gap-3 p-4 rounded-2xl mb-4"
                style={{
                  background: "rgba(139,92,246,0.07)",
                  border: "1px solid rgba(139,92,246,0.18)",
                }}
              >
                <span className="text-2xl" aria-hidden="true">
                  🔑
                </span>
                <div>
                  <p className="text-sm font-semibold" style={{ color: "var(--foreground)" }}>
                    Passkey / Face ID
                  </p>
                  <p className="text-xs mt-0.5" style={{ color: "rgba(148,163,184,0.7)" }}>
                    Log in instantly with biometrics — no password needed
                  </p>
                </div>
                {wizard.passkeyEnrolled && (
                  <span className="ml-auto text-sm" style={{ color: "#4ade80" }}>
                    ✓ Enrolled
                  </span>
                )}
              </div>
              {!wizard.passkeyEnrolled ? (
                <PrimaryButton
                  onClick={() => {
                    // In production: call WebAuthn registration API
                    set("passkeyEnrolled", true);
                  }}
                >
                  Enroll Passkey →
                </PrimaryButton>
              ) : (
                <PrimaryButton onClick={advance}>Continue →</PrimaryButton>
              )}
              <SkipButton onSkip={skipStep} />
            </ActionPanel>
          )}

          {/* STEP 8: Configure */}
          {currentStep === "configure" && (
            <ActionPanel>
              {/* Business hours toggle */}
              <div className="flex items-center justify-between mb-5">
                <div>
                  <p className="text-sm font-semibold" style={{ color: "var(--foreground)" }}>
                    Business hours
                  </p>
                  <p className="text-xs mt-0.5" style={{ color: "rgba(148,163,184,0.7)" }}>
                    Only answer during open hours
                  </p>
                </div>
                <Toggle
                  enabled={wizard.hoursEnabled}
                  onToggle={() => set("hoursEnabled", !wizard.hoursEnabled)}
                  label="Toggle business hours enforcement"
                />
              </div>

              {wizard.hoursEnabled && (
                <div className="mb-5 animate-in fade-in duration-200">
                  <div className="grid grid-cols-7 gap-1 text-center mb-1">
                    {(["mon", "tue", "wed", "thu", "fri", "sat", "sun"] as const).map(
                      (day) => (
                        <div
                          key={day}
                          className="text-[10px] font-medium uppercase"
                          style={{ color: "rgba(148,163,184,0.6)" }}
                        >
                          {day}
                        </div>
                      )
                    )}
                  </div>
                  <div className="grid grid-cols-7 gap-1 text-center">
                    {(["mon", "tue", "wed", "thu", "fri", "sat", "sun"] as const).map(
                      (day) => {
                        const isWeekend = day === "sat" || day === "sun";
                        const range = wizard.hours[day];
                        return (
                          <div key={day} className="flex flex-col gap-0.5">
                            <input
                              type="time"
                              value={range.open}
                              onChange={(e) =>
                                setWizard((prev) => ({
                                  ...prev,
                                  hours: {
                                    ...prev.hours,
                                    [day]: { ...prev.hours[day], open: e.target.value },
                                  },
                                }))
                              }
                              className="w-full text-[10px] rounded-lg px-1 py-1.5 text-center outline-none"
                              style={{
                                background: "rgba(255,255,255,0.05)",
                                border: "1px solid rgba(255,255,255,0.08)",
                                color: isWeekend ? "rgba(241,245,249,0.5)" : "var(--foreground)",
                              }}
                              aria-label={`${day} open time`}
                            />
                            <input
                              type="time"
                              value={range.close}
                              onChange={(e) =>
                                setWizard((prev) => ({
                                  ...prev,
                                  hours: {
                                    ...prev.hours,
                                    [day]: { ...prev.hours[day], close: e.target.value },
                                  },
                                }))
                              }
                              className="w-full text-[10px] rounded-lg px-1 py-1.5 text-center outline-none"
                              style={{
                                background: "rgba(255,255,255,0.05)",
                                border: "1px solid rgba(255,255,255,0.08)",
                                color: isWeekend ? "rgba(241,245,249,0.5)" : "var(--foreground)",
                              }}
                              aria-label={`${day} close time`}
                            />
                          </div>
                        );
                      }
                    )}
                  </div>
                </div>
              )}

              {/* Auto-reply toggle */}
              <div className="flex items-center justify-between mb-5">
                <div>
                  <p className="text-sm font-semibold" style={{ color: "var(--foreground)" }}>
                    Auto-reply
                  </p>
                  <p className="text-xs mt-0.5" style={{ color: "rgba(148,163,184,0.7)" }}>
                    Respond instantly to every message
                  </p>
                </div>
                <Toggle
                  enabled={wizard.autoReply}
                  onToggle={() => set("autoReply", !wizard.autoReply)}
                  label="Toggle auto-reply"
                />
              </div>

              {/* Personality slider */}
              <div className="mb-5">
                <div className="flex items-center justify-between mb-2">
                  <p className="text-sm font-semibold" style={{ color: "var(--foreground)" }}>
                    Personality
                  </p>
                  <span
                    className="text-xs font-medium"
                    style={{ color: "var(--gold-500)" }}
                  >
                    {wizard.personality <= 33
                      ? "Formal"
                      : wizard.personality <= 66
                      ? "Balanced"
                      : "Casual"}
                  </span>
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-xs" style={{ color: "rgba(148,163,184,0.6)" }}>
                    Formal
                  </span>
                  <input
                    type="range"
                    min={0}
                    max={100}
                    value={wizard.personality}
                    onChange={(e) => set("personality", parseInt(e.target.value, 10))}
                    className="flex-1 h-1.5 rounded-full appearance-none cursor-pointer"
                    style={{
                      background: `linear-gradient(90deg, var(--gold-500) ${wizard.personality}%, rgba(255,255,255,0.1) ${wizard.personality}%)`,
                      accentColor: "var(--gold-500)",
                    }}
                    aria-label="Agent personality from formal to casual"
                  />
                  <span className="text-xs" style={{ color: "rgba(148,163,184,0.6)" }}>
                    Casual
                  </span>
                </div>
              </div>

              <PrimaryButton onClick={advance}>Looks good! →</PrimaryButton>
            </ActionPanel>
          )}

          {/* STEP 9: Go Live */}
          {currentStep === "golive" && !launched && (
            <ActionPanel>
              {/* Summary card */}
              <div
                className="rounded-2xl p-4 mb-4 space-y-2"
                style={{
                  background: "rgba(246,180,0,0.05)",
                  border: "1px solid rgba(246,180,0,0.15)",
                }}
              >
                <SummaryRow
                  label="Business"
                  value={wizard.businessName}
                />
                <SummaryRow
                  label="Industry"
                  value={`${INDUSTRIES.find((i) => i.id === wizard.industry)?.icon ?? ""} ${industryLabel}`}
                />
                {selectedTemplate && (
                  <SummaryRow
                    label="Template"
                    value={`${selectedTemplate.icon} ${selectedTemplate.name}`}
                  />
                )}
                <SummaryRow
                  label="Payments"
                  value={wizard.stripeConnected ? "✅ Connected" : "⏭ Skip"}
                />
                <SummaryRow
                  label="SMS"
                  value={wizard.smsEnabled && wizard.phone ? `📱 ${wizard.phone}` : "⏭ Skip"}
                />
                <SummaryRow
                  label="Email"
                  value={
                    wizard.emailEnabled && wizard.email ? `✉️ ${wizard.email}` : "⏭ Skip"
                  }
                />
                <SummaryRow
                  label="Security"
                  value={wizard.passkeyEnrolled ? "🔑 Passkey" : "⏭ Skip"}
                />
                <SummaryRow
                  label="Auto-reply"
                  value={wizard.autoReply ? "On" : "Off"}
                />
              </div>

              <PrimaryButton
                onClick={handleLaunch}
                isLoading={launching}
                className="text-lg py-4"
              >
                {launching ? "Launching…" : "🚀 Go Live"}
              </PrimaryButton>
            </ActionPanel>
          )}

          {/* Post-launch action */}
          {launched && (
            <div
              className="text-center py-4 animate-in fade-in duration-500"
              style={{ color: "rgba(148,163,184,0.7)" }}
            >
              <a
                href="/dashboard"
                className="inline-flex items-center gap-2 px-8 py-3.5 rounded-2xl font-semibold text-base transition-all duration-200"
                style={{
                  background: "var(--gold-500)",
                  color: "#07111c",
                  boxShadow: "0 4px 24px rgba(246,180,0,0.3)",
                  textDecoration: "none",
                }}
              >
                Open Dashboard →
              </a>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ─── Summary row helper ───────────────────────────────────────────────────────

function SummaryRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between text-sm">
      <span style={{ color: "rgba(148,163,184,0.7)" }}>{label}</span>
      <span style={{ color: "var(--foreground)", fontWeight: 500 }}>{value}</span>
    </div>
  );
}
