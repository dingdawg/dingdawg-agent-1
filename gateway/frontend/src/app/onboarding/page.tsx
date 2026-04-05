"use client";

/**
 * Onboarding page — Tiered 6-step guided wizard.
 *
 * STOA Research applied (Figma/Notion/Vercel patterns):
 *  - Binary intent gate first (Notion pattern: personal vs. team)
 *  - Sector narrows context before pricing (Vercel: context before commitment)
 *  - Live demo BEFORE pricing — "wow moment" first, upgrade feels earned
 *  - Pricing shown as natural outcome after value is demonstrated
 *  - Max 6 steps, time-to-value < 2 min, skip always visible
 *  - Personalization gates: 35% retention lift from role-based branching
 *
 * Step 1: "Business or Personal?" — binary intent gate
 * Step 2: Sector selection (Restaurant / Retail / Service / Other for Business;
 *           Personal / Side Hustle for Personal)
 * Step 3: Tier selection with pricing (contextual to sector/intent)
 * Step 4: Live demo (tier-aware, shows unlocked capabilities)
 * Step 5: Agent setup — name + @handle
 * Step 6: Activation — Free → dashboard, Paid → Stripe checkout → dashboard
 *
 * Design: DingDawg dark-glass theme (Tailwind v4, CSS variables from globals.css)
 *   --gold-500: #F6B400   primary accent
 *   --ink-950:  #07111c   card background
 *   --foreground: #f1f5f9 text
 *   --color-muted: #94a3b8 secondary text
 *   --stroke: rgba(255,255,255,0.08) borders
 *
 * Rules:
 *   - No NEXT_PUBLIC_API_URL — relative paths only
 *   - ProtectedRoute wraps the flow
 *   - Production quality: typed, accessible, mobile-first
 *   - Zero regressions on existing /claim flow
 */

import { useState, useEffect, useCallback, useRef } from "react";
import { useRouter } from "next/navigation";
import Image from "next/image";
import {
  ChevronRight,
  ChevronLeft,
  Sparkles,
  CheckCircle,
  ArrowRight,
  Zap,
  Crown,
  Building2,
  User,
  Lock,
  Unlock,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card } from "@/components/ui/card";
import { OnboardingProgress } from "@/components/onboarding/OnboardingProgress";
import { StepHandle, type HandleStatus } from "@/components/onboarding/StepHandle";
import { ProtectedRoute } from "@/components/auth/ProtectedRoute";
import { useAuthStore } from "@/store/authStore";
import { get, post } from "@/services/api/client";

// ─── Constants ────────────────────────────────────────────────────────────────

const STEP_LABELS = ["Intent", "Sector", "Plan", "Demo", "Setup", "Launch"] as const;
const TOTAL_STEPS = 6;
const STORAGE_KEY = "dd_onboarding_done";

// ─── Types ────────────────────────────────────────────────────────────────────

type Intent = "business" | "personal";

interface Sector {
  id: string;
  label: string;
  icon: string;
  tagline: string;
  forIntent: Intent[];
  demoMessages: DemoMessage[];
  quickReplies: string[];
}

interface DemoMessage {
  role: "agent" | "customer";
  text: string;
  delay: number;
}

type TierId = "free" | "growth" | "pro";

interface Tier {
  id: TierId;
  name: string;
  price: string;
  period: string;
  badge?: string;
  tagline: string;
  features: string[];
  lockedFeatures: string[];
  cta: string;
  highlighted: boolean;
}

// ─── Sector data ──────────────────────────────────────────────────────────────

const SECTORS: Sector[] = [
  {
    id: "restaurant",
    label: "Restaurant",
    icon: "🍽️",
    tagline: "Reservations, orders, hours — automated",
    forIntent: ["business"],
    demoMessages: [
      { role: "customer", text: "Hi! Do you have a table for 4 tonight at 7pm?", delay: 0 },
      {
        role: "agent",
        text: "Yes! We have availability at 7:00 PM for 4 guests. Shall I reserve a table under your name? Any dietary restrictions I should note?",
        delay: 900,
      },
      { role: "customer", text: "Perfect! No restrictions. Book it please.", delay: 1800 },
      {
        role: "agent",
        text: "Done! Table for 4 booked tonight at 7:00 PM. You'll receive a confirmation SMS shortly. We look forward to seeing you!",
        delay: 2700,
      },
    ],
    quickReplies: ["What are your hours?", "Do you have vegan options?", "Cancel my reservation"],
  },
  {
    id: "retail",
    label: "Retail",
    icon: "🛍️",
    tagline: "Product questions, orders, returns — handled",
    forIntent: ["business"],
    demoMessages: [
      { role: "customer", text: "Is the black hoodie in stock in XL?", delay: 0 },
      {
        role: "agent",
        text: "Yes! The Classic Black Hoodie is in stock in XL. It's on sale today — $45 (was $65). Want me to add it to your cart?",
        delay: 900,
      },
      { role: "customer", text: "Yes, add it. How long is shipping?", delay: 1800 },
      {
        role: "agent",
        text: "Added! Standard shipping is 3–5 days (free over $35). Express 2-day is $8.99. Which do you prefer?",
        delay: 2700,
      },
    ],
    quickReplies: ["Track my order", "Return policy?", "What's on sale?"],
  },
  {
    id: "service",
    label: "Service Business",
    icon: "🔧",
    tagline: "Appointments, reminders, follow-ups — on autopilot",
    forIntent: ["business"],
    demoMessages: [
      { role: "customer", text: "I need to schedule a haircut this week.", delay: 0 },
      {
        role: "agent",
        text: "I'd love to get you in! We have openings Thursday at 2 PM or Friday at 11 AM. Which works better for you?",
        delay: 900,
      },
      { role: "customer", text: "Friday at 11 works.", delay: 1800 },
      {
        role: "agent",
        text: "Booked! Friday at 11:00 AM with Alex. I'll send a reminder 24 hours before. See you then!",
        delay: 2700,
      },
    ],
    quickReplies: ["Reschedule appointment", "What services do you offer?", "Price list?"],
  },
  {
    id: "other",
    label: "Other / Custom",
    icon: "✨",
    tagline: "Fully customizable for any business type",
    forIntent: ["business"],
    demoMessages: [
      { role: "customer", text: "What can your AI agent actually do for my business?", delay: 0 },
      {
        role: "agent",
        text: "I handle customer questions 24/7, book appointments, take orders, manage FAQs, send follow-up messages — all automatically. Zero missed customers.",
        delay: 900,
      },
      { role: "customer", text: "Can it learn my specific business?", delay: 1800 },
      {
        role: "agent",
        text: "Absolutely. I'm trained on YOUR business — products, policies, hours, tone. The more you tell me, the smarter I get.",
        delay: 2700,
      },
    ],
    quickReplies: ["How does it learn?", "What integrations exist?", "Pricing?"],
  },
  {
    id: "personal",
    label: "Personal Assistant",
    icon: "🧠",
    tagline: "Your private AI for tasks, research, reminders",
    forIntent: ["personal"],
    demoMessages: [
      { role: "customer", text: "Summarize my week and remind me about my dentist at 3pm.", delay: 0 },
      {
        role: "agent",
        text: "On it! This week: you have 3 meetings, 2 pending tasks, and your dentist is at 3 PM Friday. I'll send a reminder at 2:45 PM — want me to also block your calendar?",
        delay: 900,
      },
      { role: "customer", text: "Yes, block it. Also draft a thank-you email to Sarah.", delay: 1800 },
      {
        role: "agent",
        text: "Calendar blocked. Here's a draft email to Sarah: 'Hi Sarah, I wanted to say thank you for...' — Want me to customize the tone or add specifics?",
        delay: 2700,
      },
    ],
    quickReplies: ["Set a reminder", "Research a topic", "Draft an email"],
  },
  {
    id: "sidehustle",
    label: "Side Hustle",
    icon: "💼",
    tagline: "Run your side business while you sleep",
    forIntent: ["personal"],
    demoMessages: [
      { role: "customer", text: "How much does the logo design package cost?", delay: 0 },
      {
        role: "agent",
        text: "Logo packages start at $150 for the basic (3 concepts) and $299 for the premium (unlimited revisions + brand kit). Which fits your needs?",
        delay: 900,
      },
      { role: "customer", text: "Premium. Can I pay in installments?", delay: 1800 },
      {
        role: "agent",
        text: "Yes! I can split it into 2 payments of $149.50. I'll send you an invoice link. Anything else you'd like to know before booking?",
        delay: 2700,
      },
    ],
    quickReplies: ["See portfolio", "Turnaround time?", "Book a call"],
  },
];

// ─── Tier data (contextual per intent) ────────────────────────────────────────

const BUSINESS_TIERS: Tier[] = [
  {
    id: "free",
    name: "Starter",
    price: "$0",
    period: "forever",
    tagline: "Try it risk-free",
    features: [
      "50 customer conversations/mo",
      "1 AI agent",
      "Basic Q&A automation",
      "Chat widget embed",
    ],
    lockedFeatures: [
      "Unlimited conversations",
      "SMS + Email automation",
      "CRM integration",
      "Priority support",
    ],
    cta: "Start Free",
    highlighted: false,
  },
  {
    id: "growth",
    name: "Growth",
    price: "$49",
    period: "/mo",
    badge: "MOST POPULAR",
    tagline: "For growing businesses",
    features: [
      "2,000 conversations/mo",
      "3 AI agents",
      "SMS + Email automation",
      "Appointment booking",
      "Basic CRM",
      "Analytics dashboard",
    ],
    lockedFeatures: [
      "Unlimited agents",
      "White-label",
      "API access",
    ],
    cta: "Start Growth",
    highlighted: true,
  },
  {
    id: "pro",
    name: "Pro",
    price: "$149",
    period: "/mo",
    badge: "FULL POWER",
    tagline: "Unlimited, white-label, API",
    features: [
      "Unlimited conversations",
      "Unlimited AI agents",
      "White-label branding",
      "Full API access",
      "Priority 24/7 support",
      "Custom integrations",
      "Advanced analytics",
    ],
    lockedFeatures: [],
    cta: "Start Pro",
    highlighted: false,
  },
];

const PERSONAL_TIERS: Tier[] = [
  {
    id: "free",
    name: "Free",
    price: "$0",
    period: "forever",
    tagline: "Personal use, always free",
    features: [
      "50 tasks/mo",
      "1 personal agent",
      "Basic task automation",
      "Chat interface",
    ],
    lockedFeatures: [
      "Unlimited tasks",
      "Voice commands",
      "Calendar sync",
      "Email drafting",
    ],
    cta: "Start Free",
    highlighted: false,
  },
  {
    id: "growth",
    name: "Plus",
    price: "$19",
    period: "/mo",
    badge: "BEST VALUE",
    tagline: "Everything you need",
    features: [
      "500 tasks/mo",
      "3 agents",
      "Voice commands",
      "Calendar + email sync",
      "Research mode",
      "File analysis",
    ],
    lockedFeatures: [
      "Unlimited tasks",
      "API access",
      "Team sharing",
    ],
    cta: "Start Plus",
    highlighted: true,
  },
  {
    id: "pro",
    name: "Power",
    price: "$39",
    period: "/mo",
    badge: "UNLIMITED",
    tagline: "No limits. Full control.",
    features: [
      "Unlimited tasks",
      "Unlimited agents",
      "API access",
      "Team sharing",
      "Priority model routing",
      "Custom workflows",
    ],
    lockedFeatures: [],
    cta: "Start Power",
    highlighted: false,
  },
];

// ─── Exported page ────────────────────────────────────────────────────────────

export default function OnboardingPage() {
  return (
    <ProtectedRoute>
      <OnboardingFlow />
    </ProtectedRoute>
  );
}

// ─── Main wizard ──────────────────────────────────────────────────────────────

function OnboardingFlow() {
  const router = useRouter();
  const { user } = useAuthStore();

  // Skip if already completed
  useEffect(() => {
    try {
      if (localStorage.getItem(STORAGE_KEY) === "1") {
        router.replace("/dashboard");
      }
    } catch {
      // localStorage unavailable — proceed normally
    }
  }, [router]);

  // Wizard state
  const [step, setStep] = useState(0);
  const [intent, setIntent] = useState<Intent | null>(null);
  const [selectedSector, setSelectedSector] = useState<Sector | null>(null);
  const [selectedTier, setSelectedTier] = useState<TierId | null>(null);
  const [demoComplete, setDemoComplete] = useState(false);
  const [agentName, setAgentName] = useState("");
  const [handle, setHandle] = useState("");
  const [handleTouched, setHandleTouched] = useState(false);
  const [handleStatus, setHandleStatus] = useState<HandleStatus>("idle");
  const [handleReason, setHandleReason] = useState<string | null>(null);
  const [activating, setActivating] = useState(false);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Derive sectors for selected intent
  const availableSectors = intent
    ? SECTORS.filter((s) => s.forIntent.includes(intent))
    : [];

  // Derive tiers for selected intent
  const availableTiers = intent === "personal" ? PERSONAL_TIERS : BUSINESS_TIERS;

  // Derive first name for greeting
  const firstName = user?.email?.split("@")[0]?.split(".")[0] ?? null;
  const greeting = firstName
    ? `${firstName.charAt(0).toUpperCase() + firstName.slice(1)}, let's build your agent.`
    : "Let's build your agent.";

  // Mark complete
  const markComplete = useCallback(() => {
    try {
      localStorage.setItem(STORAGE_KEY, "1");
    } catch {
      // ignore
    }
  }, []);

  const handleSkip = useCallback(() => {
    markComplete();
    router.push("/dashboard");
  }, [markComplete, router]);

  // Handle availability check (debounced 300 ms)
  const onHandleChange = useCallback((v: string) => {
    setHandle(v);
    setHandleTouched(true);
    setHandleStatus("idle");
    setHandleReason(null);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    if (v.length < 3) return;
    debounceRef.current = setTimeout(async () => {
      setHandleStatus("checking");
      try {
        const res = await get<{
          handle: string;
          available: boolean;
          reason?: string | null;
        }>(`/api/v1/onboarding/check-handle/${encodeURIComponent(v)}`);
        if (res.available) {
          setHandleStatus("available");
          setHandleReason(null);
        } else if (res.reason) {
          setHandleStatus("invalid");
          setHandleReason(res.reason);
        } else {
          setHandleStatus("taken");
          setHandleReason(null);
        }
      } catch {
        setHandleStatus("idle");
      }
    }, 300);
  }, []);

  // Activation — Free: create agent + go to dashboard; Paid: Stripe checkout
  const handleActivate = useCallback(async () => {
    if (!selectedSector || !selectedTier || !handle || !agentName || activating) return;
    setActivating(true);
    try {
      if (selectedTier === "free") {
        // Create agent via claim endpoint, redirect to dashboard
        await post("/api/v1/onboarding/claim", {
          handle,
          name: agentName.trim(),
          agent_type: intent === "personal" ? "personal" : "business",
          template_id: null,
          industry_type: selectedSector.id,
        });
        markComplete();
        router.push(`/dashboard?agent=${encodeURIComponent(handle)}`);
      } else {
        // Paid: create pending agent record, redirect to billing/checkout
        await post("/api/v1/onboarding/claim", {
          handle,
          name: agentName.trim(),
          agent_type: intent === "personal" ? "personal" : "business",
          template_id: null,
          industry_type: selectedSector.id,
          tier: selectedTier,
        });
        markComplete();
        // Redirect to billing page with upgrade context
        router.push(
          `/billing?upgrade=${selectedTier}&agent=${encodeURIComponent(handle)}&ref=onboarding`
        );
      }
    } catch {
      setActivating(false);
    }
  }, [selectedSector, selectedTier, handle, agentName, activating, intent, markComplete, router]);

  // Can proceed logic per step
  const canProceed = (() => {
    if (step === 0) return intent !== null;
    if (step === 1) return selectedSector !== null;
    if (step === 2) return selectedTier !== null;
    if (step === 3) return demoComplete;
    if (step === 4)
      return (
        agentName.trim().length >= 2 &&
        handle.length >= 3 &&
        handleStatus === "available"
      );
    return true;
  })();

  const onNext = () => {
    if (canProceed && step < TOTAL_STEPS - 1) setStep((s) => s + 1);
  };

  const onBack = () => {
    if (step > 0) setStep((s) => s - 1);
  };

  // Step 0 label (intent gate) — show greeting; step 5 — show activation
  const headerTitle = (() => {
    if (step === 0) return greeting;
    if (step === 5) return "You're ready to launch!";
    return "DingDawg Agent";
  })();

  const headerSub = (() => {
    if (step === 0) return "Takes under 2 minutes. Skip anytime.";
    if (step === 1) return "Pick your industry so we can personalize everything.";
    if (step === 2) return "Choose the plan that fits — upgrade or downgrade anytime.";
    if (step === 3) return "Watch your agent handle a real conversation — right now.";
    if (step === 4) return "Name your agent and claim your @handle.";
    if (step === 5) return selectedTier === "free"
      ? "Your agent goes live the moment you activate."
      : "One step to unlock your full plan.";
    return "";
  })();

  return (
    <div
      className="flex items-start justify-center min-h-dvh px-4"
      style={{
        paddingTop: "calc(env(safe-area-inset-top, 0px) + 28px)",
        paddingBottom: "calc(env(safe-area-inset-bottom, 0px) + 80px)",
      }}
    >
      <div className="w-full max-w-md">
        {/* ── Header ─────────────────────────────────────────────────────── */}
        <div className="flex flex-col items-center gap-1.5 mb-5">
          <Image
            src="/icons/logo.png"
            alt="DingDawg"
            width={56}
            height={46}
            priority
          />
          <h1 className="text-xl font-bold text-[var(--foreground)] font-heading text-center">
            {headerTitle}
          </h1>
          <p className="text-xs text-[var(--color-muted)] text-center max-w-xs">
            {headerSub}
          </p>
        </div>

        {/* ── Progress ──────────────────────────────────────────────────── */}
        <OnboardingProgress
          currentStep={step}
          totalSteps={TOTAL_STEPS}
          labels={STEP_LABELS as unknown as string[]}
        />

        {/* ── Step card ─────────────────────────────────────────────────── */}
        <Card className="flex flex-col gap-4 overflow-y-auto max-h-[calc(100dvh-260px)]">

          {/* ── STEP 0: Business or Personal? ─────────────────────────── */}
          {step === 0 && (
            <StepIntent selected={intent} onSelect={(v) => {
              setIntent(v);
              // Reset downstream on intent change
              setSelectedSector(null);
              setSelectedTier(null);
              setDemoComplete(false);
            }} />
          )}

          {/* ── STEP 1: Sector selection ───────────────────────────────── */}
          {step === 1 && intent && (
            <StepSector
              sectors={availableSectors}
              selected={selectedSector}
              onSelect={(s) => {
                setSelectedSector(s);
                setDemoComplete(false); // reset demo if sector changes
              }}
            />
          )}

          {/* ── STEP 2: Tier / pricing selection ──────────────────────── */}
          {step === 2 && (
            <StepTier
              tiers={availableTiers}
              selected={selectedTier}
              onSelect={setSelectedTier}
              intent={intent ?? "business"}
            />
          )}

          {/* ── STEP 3: Live demo ─────────────────────────────────────── */}
          {step === 3 && selectedSector && selectedTier && (
            <StepDemo
              sector={selectedSector}
              agentName={agentName || "Your Agent"}
              tier={selectedTier}
              onComplete={() => setDemoComplete(true)}
            />
          )}

          {/* ── STEP 4: Agent setup — name + handle ───────────────────── */}
          {step === 4 && (
            <StepSetup
              agentName={agentName}
              onAgentNameChange={setAgentName}
              handle={handle}
              onHandleChange={onHandleChange}
              handleStatus={handleStatus}
              handleReason={handleReason}
              handleTouched={handleTouched}
              sector={selectedSector}
            />
          )}

          {/* ── STEP 5: Activation ────────────────────────────────────── */}
          {step === 5 && (
            <StepActivation
              agentName={agentName}
              handle={handle}
              sector={selectedSector}
              tier={selectedTier}
              tiers={availableTiers}
              activating={activating}
              onActivate={handleActivate}
              onChangeTier={(t) => {
                setSelectedTier(t);
              }}
            />
          )}

          {/* ── Navigation — hidden on final step (activation manages it) */}
          {step < TOTAL_STEPS - 1 && (
            <div className="flex gap-2.5 mt-1">
              {step > 0 && (
                <Button
                  variant="outline"
                  onClick={onBack}
                  className="flex-shrink-0 min-w-[80px]"
                  aria-label="Go back"
                >
                  <ChevronLeft className="h-4 w-4 mr-1" />
                  Back
                </Button>
              )}
              <Button
                variant="gold"
                disabled={!canProceed}
                onClick={onNext}
                className="flex-1"
                aria-label={step === 3 && !demoComplete ? "Watch demo first" : "Continue"}
              >
                {step === 3 && !demoComplete ? "Watch the demo first" : "Continue"}
                {(step !== 3 || demoComplete) && (
                  <ChevronRight className="h-4 w-4 ml-1" />
                )}
              </Button>
            </div>
          )}
        </Card>

        {/* ── Skip link ─────────────────────────────────────────────────── */}
        {step < TOTAL_STEPS - 1 && (
          <div className="flex justify-center mt-4">
            <button
              onClick={handleSkip}
              className="text-xs text-[var(--color-muted)] hover:text-[var(--foreground)] underline underline-offset-2 transition-colors"
            >
              Skip to dashboard
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

// ─── Step 0: Intent Gate — Business or Personal? ──────────────────────────────

interface StepIntentProps {
  selected: Intent | null;
  onSelect: (intent: Intent) => void;
}

function StepIntent({ selected, onSelect }: StepIntentProps) {
  const choices: Array<{
    id: Intent;
    icon: React.ReactNode;
    label: string;
    tagline: string;
    examples: string;
  }> = [
    {
      id: "business",
      icon: <Building2 className="h-8 w-8" />,
      label: "Business",
      tagline: "AI agent for your customers",
      examples: "Restaurant · Retail · Service · Any business",
    },
    {
      id: "personal",
      icon: <User className="h-8 w-8" />,
      label: "Personal",
      tagline: "Your private AI assistant",
      examples: "Tasks · Research · Side hustle",
    },
  ];

  return (
    <>
      <div>
        <h2 className="text-base font-semibold text-[var(--foreground)]">
          What are you building?
        </h2>
        <p className="text-xs text-[var(--color-muted)] mt-0.5">
          This personalizes your entire setup — takes 2 seconds.
        </p>
      </div>

      <div className="grid grid-cols-2 gap-3">
        {choices.map((c) => {
          const isSelected = selected === c.id;
          return (
            <button
              key={c.id}
              onClick={() => onSelect(c.id)}
              className={[
                "relative flex flex-col items-center gap-3 px-4 py-6 rounded-2xl border",
                "text-center transition-all duration-150",
                "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--gold-500)]",
                isSelected
                  ? "border-[var(--gold-500)] bg-[var(--gold-500)]/10 shadow-[0_0_0_1px_var(--gold-500)]"
                  : "border-[var(--stroke)] bg-white/3 hover:border-white/25 hover:bg-white/5 active:scale-95",
              ].join(" ")}
              aria-pressed={isSelected}
              aria-label={`Select ${c.label}`}
            >
              <span
                className={`transition-colors ${
                  isSelected ? "text-[var(--gold-500)]" : "text-[var(--color-muted)]"
                }`}
              >
                {c.icon}
              </span>
              <div>
                <p
                  className={`text-sm font-bold ${
                    isSelected ? "text-[var(--gold-500)]" : "text-[var(--foreground)]"
                  }`}
                >
                  {c.label}
                </p>
                <p className="text-[11px] text-[var(--color-muted)] mt-0.5 leading-tight">
                  {c.tagline}
                </p>
              </div>
              <p className="text-[10px] text-[var(--color-muted)] opacity-60 leading-tight">
                {c.examples}
              </p>
            </button>
          );
        })}
      </div>

      {/* Social proof line */}
      <p className="text-center text-[11px] text-[var(--color-muted)] opacity-70">
        Join 2,400+ businesses and creators already using DingDawg
      </p>
    </>
  );
}

// ─── Step 1: Sector selection ─────────────────────────────────────────────────

interface StepSectorProps {
  sectors: Sector[];
  selected: Sector | null;
  onSelect: (sector: Sector) => void;
}

function StepSector({ sectors, selected, onSelect }: StepSectorProps) {
  return (
    <>
      <div>
        <h2 className="text-base font-semibold text-[var(--foreground)]">
          What best describes you?
        </h2>
        <p className="text-xs text-[var(--color-muted)] mt-0.5">
          We'll personalize the demo and setup for your industry.
        </p>
      </div>

      <div className="grid grid-cols-2 gap-2.5">
        {sectors.map((s) => {
          const isSelected = selected?.id === s.id;
          return (
            <button
              key={s.id}
              onClick={() => onSelect(s)}
              className={[
                "relative flex flex-col items-center gap-2 p-3 sm:p-4 rounded-2xl border",
                "text-center transition-all duration-150 min-h-[88px]",
                "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--gold-500)]",
                isSelected
                  ? "border-[var(--gold-500)] bg-[var(--gold-500)]/10 shadow-[0_0_0_1px_var(--gold-500)]"
                  : "border-[var(--stroke)] bg-white/3 hover:border-white/25 hover:bg-white/5 active:scale-95",
              ].join(" ")}
              aria-pressed={isSelected}
              aria-label={`Select ${s.label}`}
            >
              <span className="text-3xl leading-none" role="img" aria-hidden="true">
                {s.icon}
              </span>
              <p
                className={`text-sm font-semibold leading-tight ${
                  isSelected ? "text-[var(--gold-500)]" : "text-[var(--foreground)]"
                }`}
              >
                {s.label}
              </p>
              <p className="text-[10px] text-[var(--color-muted)] leading-tight">
                {s.tagline}
              </p>
            </button>
          );
        })}
      </div>
    </>
  );
}

// ─── Step 2: Tier selection with pricing ─────────────────────────────────────

interface StepTierProps {
  tiers: Tier[];
  selected: TierId | null;
  onSelect: (id: TierId) => void;
  intent: Intent;
}

function StepTier({ tiers, selected, onSelect, intent }: StepTierProps) {
  return (
    <>
      <div>
        <h2 className="text-base font-semibold text-[var(--foreground)]">
          Choose your plan
        </h2>
        <p className="text-xs text-[var(--color-muted)] mt-0.5">
          Start free and upgrade anytime. No credit card required to start.
        </p>
      </div>

      <div className="flex flex-col gap-2.5">
        {tiers.map((tier) => {
          const isSelected = selected === tier.id;
          return (
            <button
              key={tier.id}
              onClick={() => onSelect(tier.id)}
              className={[
                "relative w-full text-left p-4 rounded-2xl border transition-all duration-150",
                "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--gold-500)]",
                isSelected
                  ? "border-[var(--gold-500)] bg-[var(--gold-500)]/8 shadow-[0_0_0_1px_var(--gold-500)]"
                  : tier.highlighted
                  ? "border-[var(--gold-500)]/30 bg-[var(--gold-500)]/4 hover:border-[var(--gold-500)]/60"
                  : "border-[var(--stroke)] bg-white/3 hover:border-white/25 hover:bg-white/5",
                "active:scale-[0.99]",
              ].join(" ")}
              aria-pressed={isSelected}
              aria-label={`Select ${tier.name} plan at ${tier.price}${tier.period}`}
            >
              {/* Badge */}
              {tier.badge && (
                <span className="absolute -top-2 right-3 px-2 py-0.5 rounded-full bg-[var(--gold-500)] text-black text-[9px] font-bold tracking-wider">
                  {tier.badge}
                </span>
              )}

              {/* Header row */}
              <div className="flex items-center justify-between mb-2">
                <div className="flex items-center gap-2">
                  {isSelected && (
                    <CheckCircle className="h-4 w-4 text-[var(--gold-500)] flex-shrink-0" />
                  )}
                  {!isSelected && tier.id === "free" && (
                    <Zap className="h-4 w-4 text-[var(--color-muted)] flex-shrink-0" />
                  )}
                  {!isSelected && tier.id === "growth" && (
                    <Sparkles className="h-4 w-4 text-[var(--gold-500)]/60 flex-shrink-0" />
                  )}
                  {!isSelected && tier.id === "pro" && (
                    <Crown className="h-4 w-4 text-[var(--color-muted)] flex-shrink-0" />
                  )}
                  <p
                    className={`text-sm font-bold ${
                      isSelected ? "text-[var(--gold-500)]" : "text-[var(--foreground)]"
                    }`}
                  >
                    {tier.name}
                  </p>
                </div>
                <div className="text-right">
                  <span
                    className={`text-base font-bold ${
                      isSelected ? "text-[var(--gold-500)]" : "text-[var(--foreground)]"
                    }`}
                  >
                    {tier.price}
                  </span>
                  <span className="text-[11px] text-[var(--color-muted)]">
                    {tier.period}
                  </span>
                </div>
              </div>

              {/* Tagline */}
              <p className="text-[11px] text-[var(--color-muted)] mb-2">{tier.tagline}</p>

              {/* Features */}
              <div className="flex flex-col gap-1">
                {tier.features.map((f) => (
                  <div key={f} className="flex items-center gap-1.5">
                    <Unlock className="h-3 w-3 text-green-400 flex-shrink-0" />
                    <span className="text-[11px] text-[var(--foreground)]">{f}</span>
                  </div>
                ))}
                {tier.lockedFeatures.map((f) => (
                  <div key={f} className="flex items-center gap-1.5 opacity-40">
                    <Lock className="h-3 w-3 text-[var(--color-muted)] flex-shrink-0" />
                    <span className="text-[11px] text-[var(--color-muted)]">{f}</span>
                  </div>
                ))}
              </div>
            </button>
          );
        })}
      </div>

      <p className="text-center text-[11px] text-[var(--color-muted)] opacity-70">
        {intent === "business"
          ? "Average business sees 340+ hours saved per year"
          : "Upgrade unlocks voice, calendar sync, and more"}
      </p>
    </>
  );
}

// ─── Step 3: Live Demo (tier-aware) ──────────────────────────────────────────

interface StepDemoProps {
  sector: Sector;
  agentName: string;
  tier: TierId;
  onComplete: () => void;
}

interface RenderedMessage {
  role: "agent" | "customer";
  text: string;
}

function StepDemo({ sector, agentName, tier, onComplete }: StepDemoProps) {
  const [rendered, setRendered] = useState<RenderedMessage[]>([]);
  const [isTyping, setIsTyping] = useState(false);
  const [doneFlag, setDoneFlag] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement | null>(null);

  // Play demo sequence on mount
  useEffect(() => {
    setRendered([]);
    setDoneFlag(false);
    let cancelled = false;

    async function playMessages() {
      for (let i = 0; i < sector.demoMessages.length; i++) {
        const msg = sector.demoMessages[i];
        await new Promise<void>((res) =>
          setTimeout(res, i === 0 ? 400 : msg.delay - (sector.demoMessages[i - 1]?.delay ?? 0))
        );
        if (cancelled) return;
        if (msg.role === "agent") {
          setIsTyping(true);
          await new Promise<void>((res) => setTimeout(res, 700));
          if (cancelled) return;
          setIsTyping(false);
        }
        setRendered((prev) => [...prev, { role: msg.role, text: msg.text }]);
      }
      if (!cancelled) {
        setDoneFlag(true);
        onComplete();
      }
    }

    playMessages();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sector.id]);

  // Auto-scroll
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [rendered, isTyping]);

  const displayName = agentName.trim() || "Your Agent";

  // Tier-aware capability banner
  const tierBanner = (() => {
    if (tier === "free")
      return { text: "50 conversations/mo included on Starter", color: "text-[var(--color-muted)]" };
    if (tier === "growth")
      return { text: "SMS alerts and appointment booking unlocked on your plan", color: "text-green-400" };
    return { text: "Unlimited conversations + full API access on Pro", color: "text-[var(--gold-500)]" };
  })();

  return (
    <>
      <div>
        <h2 className="text-base font-semibold text-[var(--foreground)]">
          {sector.icon} Watch it work
        </h2>
        <p className="text-xs text-[var(--color-muted)] mt-0.5">
          <span className="text-[var(--foreground)]">{displayName}</span> handling a real{" "}
          {sector.label.toLowerCase()} conversation — live.
        </p>
      </div>

      {/* Tier capability banner */}
      <div className="flex items-center gap-1.5 px-3 py-2 rounded-xl bg-white/4 border border-[var(--stroke)]">
        {tier === "free" ? (
          <Lock className="h-3 w-3 text-[var(--color-muted)] flex-shrink-0" />
        ) : (
          <Unlock className="h-3 w-3 text-green-400 flex-shrink-0" />
        )}
        <p className={`text-[11px] ${tierBanner.color}`}>{tierBanner.text}</p>
      </div>

      {/* Chat window */}
      <div className="rounded-2xl border border-[var(--stroke)] bg-white/3 overflow-hidden">
        {/* Chat header */}
        <div className="flex items-center gap-2.5 px-3.5 py-2.5 border-b border-[var(--stroke)] bg-white/3">
          <div className="h-7 w-7 rounded-full bg-[var(--gold-500)]/20 flex items-center justify-center flex-shrink-0">
            <Sparkles className="h-3.5 w-3.5 text-[var(--gold-500)]" />
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-xs font-semibold text-[var(--foreground)] truncate">{displayName}</p>
            <p className="text-[10px] text-green-400 flex items-center gap-1">
              <span className="inline-block h-1.5 w-1.5 rounded-full bg-green-400" />
              Online · AI Agent
            </p>
          </div>
        </div>

        {/* Messages */}
        <div
          className="flex flex-col gap-2.5 p-3.5 overflow-y-auto"
          style={{ minHeight: "clamp(120px, 28vh, 190px)", maxHeight: "clamp(150px, 33vh, 260px)" }}
        >
          {rendered.map((msg, i) => (
            <div
              key={i}
              className={`flex ${msg.role === "customer" ? "justify-end" : "justify-start"}`}
            >
              <div
                className={[
                  "max-w-[78%] px-3.5 py-2.5 rounded-2xl text-sm leading-relaxed",
                  msg.role === "agent"
                    ? "bg-white/6 border border-[var(--stroke)] text-[var(--foreground)] rounded-tl-sm"
                    : "bg-[var(--gold-500)]/15 border border-[var(--gold-500)]/25 text-[var(--foreground)] rounded-tr-sm",
                ].join(" ")}
              >
                {msg.text}
              </div>
            </div>
          ))}

          {/* Typing indicator */}
          {isTyping && (
            <div className="flex justify-start">
              <div className="px-3.5 py-2.5 rounded-2xl rounded-tl-sm bg-white/6 border border-[var(--stroke)] flex items-center gap-1">
                {[0, 150, 300].map((delay) => (
                  <span
                    key={delay}
                    className="inline-block h-1.5 w-1.5 rounded-full bg-[var(--color-muted)] animate-bounce"
                    style={{ animationDelay: `${delay}ms` }}
                  />
                ))}
              </div>
            </div>
          )}
          <div ref={messagesEndRef} />
        </div>

        {/* Quick replies — after demo completes */}
        {doneFlag && (
          <div className="px-3.5 pb-3.5 border-t border-[var(--stroke)] pt-3">
            <p className="text-[10px] text-[var(--color-muted)] uppercase tracking-wider mb-2">
              Try asking
            </p>
            <div className="flex flex-wrap gap-1.5">
              {sector.quickReplies.map((reply) => (
                <span
                  key={reply}
                  className="px-2.5 py-1.5 rounded-full text-xs border border-[var(--gold-500)]/30 text-[var(--gold-500)] bg-[var(--gold-500)]/5"
                >
                  {reply}
                </span>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Completion badge */}
      {doneFlag && (
        <div className="flex items-center gap-2 p-3 rounded-xl bg-green-500/8 border border-green-500/20">
          <CheckCircle className="h-4 w-4 text-green-400 flex-shrink-0" />
          <p className="text-sm text-[var(--foreground)]">
            <span className="font-semibold">That&apos;s your agent.</span>{" "}
            <span className="text-[var(--color-muted)]">Ready to name it? Hit Continue.</span>
          </p>
        </div>
      )}
    </>
  );
}

// ─── Step 4: Agent setup — name + @handle ─────────────────────────────────────

interface StepSetupProps {
  agentName: string;
  onAgentNameChange: (v: string) => void;
  handle: string;
  onHandleChange: (v: string) => void;
  handleStatus: HandleStatus;
  handleReason: string | null;
  handleTouched: boolean;
  sector: Sector | null;
}

function StepSetup({
  agentName,
  onAgentNameChange,
  handle,
  onHandleChange,
  handleStatus,
  handleReason,
  handleTouched,
  sector,
}: StepSetupProps) {
  const defaultNamePlaceholder = sector
    ? `My ${sector.label} Agent`
    : "My AI Agent";

  return (
    <>
      <div>
        <h2 className="text-base font-semibold text-[var(--foreground)]">
          Name your agent
        </h2>
        <p className="text-xs text-[var(--color-muted)] mt-0.5">
          Give your agent a name and claim its unique @handle.
        </p>
      </div>

      {/* Agent name */}
      <div>
        <label
          htmlFor="agent-name-input"
          className="block text-xs font-medium text-[var(--color-muted)] mb-1.5"
        >
          Agent display name
        </label>
        <Input
          id="agent-name-input"
          value={agentName}
          onChange={(e) => onAgentNameChange(e.target.value)}
          placeholder={defaultNamePlaceholder}
          maxLength={60}
          autoFocus
          className="text-sm"
        />
        <p className="mt-1 text-[11px] text-[var(--color-muted)] opacity-60">
          Shown to customers when they chat with your agent.
        </p>
      </div>

      {/* Preview bubble */}
      {agentName.trim().length >= 2 && (
        <div className="p-3 rounded-2xl bg-[var(--gold-500)]/8 border border-[var(--gold-500)]/20">
          <p className="text-[11px] text-[var(--gold-500)] uppercase tracking-wider font-semibold mb-1.5">
            Preview
          </p>
          <div className="flex items-start gap-2">
            <div className="h-7 w-7 rounded-full bg-[var(--gold-500)]/20 flex items-center justify-center flex-shrink-0">
              <Sparkles className="h-3.5 w-3.5 text-[var(--gold-500)]" />
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-[11px] font-semibold text-[var(--gold-500)] mb-0.5">
                {agentName.trim()}
              </p>
              <p className="text-sm text-[var(--foreground)] leading-relaxed">
                Hi! I&apos;m {agentName.trim()}. How can I help you today?
              </p>
            </div>
          </div>
        </div>
      )}

      {/* @handle */}
      <div>
        <label
          htmlFor="handle"
          className="block text-xs font-medium text-[var(--color-muted)] mb-1.5"
        >
          Your @handle — unique public identity
        </label>
        <StepHandle
          value={handle}
          onChange={onHandleChange}
          status={handleStatus}
          reason={handleReason}
          touched={handleTouched}
        />
        <p className="mt-1 text-[11px] text-[var(--color-muted)] opacity-60">
          Permanent once claimed. Choose carefully.
        </p>
      </div>
    </>
  );
}

// ─── Step 5: Activation ───────────────────────────────────────────────────────

interface StepActivationProps {
  agentName: string;
  handle: string;
  sector: Sector | null;
  tier: TierId | null;
  tiers: Tier[];
  activating: boolean;
  onActivate: () => void;
  onChangeTier: (t: TierId) => void;
}

function StepActivation({
  agentName,
  handle,
  sector,
  tier,
  tiers,
  activating,
  onActivate,
  onChangeTier,
}: StepActivationProps) {
  const displayName = agentName.trim() || "Your Agent";
  const currentTier = tiers.find((t) => t.id === tier);
  const isFree = tier === "free";

  // Success pulse animation on mount (emotional peak — Slack/Notion/Figma pattern)
  const [mounted, setMounted] = useState(false);
  useEffect(() => {
    const t = setTimeout(() => setMounted(true), 50);
    return () => clearTimeout(t);
  }, []);

  return (
    <>
      {/* Agent identity ring — with entrance scale animation */}
      <div className="flex flex-col items-center gap-2 py-1">
        <div
          className={`relative transition-transform duration-700 ease-out ${
            mounted ? "scale-100 opacity-100" : "scale-75 opacity-0"
          }`}
        >
          <div className="h-20 w-20 rounded-full bg-[var(--gold-500)]/10 border-2 border-[var(--gold-500)]/30 flex items-center justify-center">
            <div className="h-14 w-14 rounded-full bg-[var(--gold-500)]/20 flex items-center justify-center">
              <Sparkles className="h-7 w-7 text-[var(--gold-500)]" />
            </div>
          </div>
          <div className="absolute inset-0 rounded-full border-2 border-[var(--gold-500)]/30 animate-ping" />
          {/* Second ping ring — staggered for depth */}
          <div className="absolute -inset-3 rounded-full border border-[var(--gold-500)]/10 animate-ping [animation-delay:500ms]" />
        </div>
        <div className="text-center">
          <p className="text-lg font-bold text-[var(--foreground)]">{displayName}</p>
          <p className="text-xs text-[var(--gold-500)] font-medium">@{handle}</p>
          {sector && (
            <p className="text-xs text-[var(--color-muted)] mt-0.5">
              {sector.icon} {sector.label} Agent
            </p>
          )}
        </div>
      </div>

      {/* Plan summary */}
      {currentTier && (
        <div className="p-3.5 rounded-2xl border border-[var(--gold-500)]/20 bg-[var(--gold-500)]/5">
          <div className="flex items-center justify-between mb-2">
            <p className="text-sm font-semibold text-[var(--foreground)]">
              {currentTier.name} plan
            </p>
            <p className="text-sm font-bold text-[var(--gold-500)]">
              {currentTier.price}
              <span className="text-[11px] font-normal text-[var(--color-muted)]">
                {currentTier.period}
              </span>
            </p>
          </div>
          <div className="flex flex-col gap-1">
            {currentTier.features.slice(0, 3).map((f) => (
              <div key={f} className="flex items-center gap-1.5">
                <CheckCircle className="h-3 w-3 text-green-400 flex-shrink-0" />
                <span className="text-[11px] text-[var(--foreground)]">{f}</span>
              </div>
            ))}
          </div>
          {/* Change tier link */}
          <div className="flex gap-2 mt-2.5 pt-2.5 border-t border-white/8">
            {tiers
              .filter((t) => t.id !== tier)
              .map((t) => (
                <button
                  key={t.id}
                  onClick={() => onChangeTier(t.id)}
                  className="text-[11px] text-[var(--gold-500)] hover:underline underline-offset-2"
                >
                  Switch to {t.name}
                </button>
              ))}
          </div>
        </div>
      )}

      {/* Activation CTA */}
      <Button
        variant="gold"
        size="lg"
        onClick={onActivate}
        isLoading={activating}
        disabled={activating}
        className="mt-1"
        aria-label={isFree ? "Activate your agent" : "Continue to checkout"}
      >
        {activating
          ? "Activating…"
          : isFree
          ? "Activate Free Agent"
          : `Continue to Checkout`}
        {!activating && <ArrowRight className="h-4 w-4 ml-1" />}
      </Button>

      {/* Trust line */}
      <p className="text-center text-[11px] text-[var(--color-muted)]">
        {isFree
          ? "No credit card required · Upgrade anytime"
          : "Secure checkout · Cancel anytime · Grandfather pricing locked in"}
      </p>
    </>
  );
}
