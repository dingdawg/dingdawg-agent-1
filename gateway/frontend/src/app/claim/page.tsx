"use client";

/**
 * Claim page — "Claim Your DingDawg Agent" 3-step onboarding wizard.
 *
 * Step 1: Choose Your Sector (8 sectors: Personal, Business, B2B, A2A,
 *          Compliance, Enterprise, Health, Gaming)
 * Step 2: Pick Your Template (filtered by selected sector)
 * Step 3: Claim Your @handle (real-time availability check + agent name)
 *
 * On success: agent is created via POST /api/v1/onboarding/claim
 *             → redirect to /dashboard
 *
 * Design principles:
 *  - Mobile-first: 2-column sector grid, large touch targets, thumb-friendly CTA
 *  - Dark theme: black bg, white text, gold accent (#F0B429)
 *  - No scroll per step — all content fits one screen
 *  - Smooth slide transitions between steps
 */

import { useState, useEffect, useRef, useCallback } from "react";
import { useRouter } from "next/navigation";
import Image from "next/image";
import { ChevronRight, ChevronLeft, AlertCircle } from "lucide-react";
import { useAgentStore } from "@/store/agentStore";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card } from "@/components/ui/card";
import { ProtectedRoute } from "@/components/auth/ProtectedRoute";
import { OnboardingProgress } from "@/components/onboarding/OnboardingProgress";
import { StepSector, type SectorItem } from "@/components/onboarding/StepSector";
import { StepTemplate, type TemplateItem } from "@/components/onboarding/StepTemplate";
import { StepHandle, type HandleStatus } from "@/components/onboarding/StepHandle";
import { get, post } from "@/services/api/client";

// ─── Constants ────────────────────────────────────────────────────────────────

const STEP_LABELS = ["Sector", "Template", "@Handle"] as const;
const TOTAL_STEPS = 3;

// Fallback sectors if the API is unavailable (matches the backend _SECTORS list)
const FALLBACK_SECTORS: SectorItem[] = [
  { id: "personal",   name: "Personal",   agent_type: "personal",   icon: "👤", description: "Your private AI assistant.", popular: false },
  { id: "business",   name: "Business",   agent_type: "business",   icon: "🏪", description: "AI agent for your business.", popular: true },
  { id: "b2b",        name: "B2B",        agent_type: "b2b",        icon: "🤝", description: "Business-to-business workflows.", popular: false },
  { id: "a2a",        name: "A2A",        agent_type: "a2a",        icon: "🔗", description: "Agent-to-agent coordination.", popular: false },
  { id: "compliance", name: "Compliance", agent_type: "compliance", icon: "🛡️", description: "Governance-first for regulated industries.", popular: false },
  { id: "enterprise", name: "Enterprise", agent_type: "enterprise", icon: "🏢", description: "Multi-location and enterprise ops.", popular: false },
  { id: "health",     name: "Health",     agent_type: "health",     icon: "🏥", description: "Patient scheduling and wellness.", popular: false },
  { id: "gaming",     name: "Gaming",     agent_type: "business",   icon: "🎮", description: "Game coaching and guild management.", popular: true },
];

// ─── Exported page ────────────────────────────────────────────────────────────

export default function ClaimPage() {
  return (
    <ProtectedRoute>
      <ClaimFlow />
    </ProtectedRoute>
  );
}

// ─── Main wizard component ────────────────────────────────────────────────────

function ClaimFlow() {
  const router = useRouter();
  const { agents, isLoading: agentsLoading, fetchAgents, error, clearError } = useAgentStore();
  const [submitting, setSubmitting] = useState(false);

  // ── Guard: redirect users who already have agents to dashboard ──────────
  useEffect(() => {
    fetchAgents();
  }, [fetchAgents]);

  useEffect(() => {
    // Skip guard during/after submission — handleSubmit manages its own redirect
    if (!submitting && !agentsLoading && agents.length > 0) {
      router.replace("/dashboard");
    }
  }, [submitting, agentsLoading, agents.length, router]);

  // ── Wizard state ──────────────────────────────────────────────────────────
  const [step, setStep] = useState(0);

  // Step 1: sector
  const [sectors, setSectors] = useState<SectorItem[]>([]);
  const [sectorsLoading, setSectorsLoading] = useState(true);
  const [selectedSector, setSelectedSector] = useState<SectorItem | null>(null);

  // Step 2: template
  const [allTemplates, setAllTemplates] = useState<TemplateItem[]>([]);
  const [templatesLoading, setTemplatesLoading] = useState(false);
  const [selectedTemplate, setSelectedTemplate] = useState<TemplateItem | null>(null);

  // Step 3: handle
  const [handle, setHandle] = useState("");
  const [handleTouched, setHandleTouched] = useState(false);
  const [handleStatus, setHandleStatus] = useState<HandleStatus>("idle");
  const [handleReason, setHandleReason] = useState<string | null>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Step 3b: agent name (part of the submit card)
  const [agentName, setAgentName] = useState("");

  // ── Data fetching ─────────────────────────────────────────────────────────

  // Load sectors from backend (fallback to static list if unavailable)
  useEffect(() => {
    setSectorsLoading(true);
    get<{ sectors: SectorItem[]; count: number }>("/api/v1/onboarding/sectors")
      .then((data) => setSectors(data.sectors))
      .catch(() => setSectors(FALLBACK_SECTORS))
      .finally(() => setSectorsLoading(false));
  }, []);

  // Load templates once (all of them) — filter client-side by sector
  useEffect(() => {
    setTemplatesLoading(true);
    get<{ templates: TemplateItem[]; count: number }>("/api/v1/templates")
      .then((data) => setAllTemplates(data.templates ?? []))
      .catch(() => setAllTemplates([]))
      .finally(() => setTemplatesLoading(false));
  }, []);

  // ── Filtered templates ────────────────────────────────────────────────────

  const filteredTemplates: TemplateItem[] = selectedSector
    ? allTemplates.filter((t) => {
        // Gaming sector: show business templates with gaming-adjacent industries
        if (selectedSector.id === "gaming") {
          return (
            t.agent_type === "business" &&
            (!t.industry_type || ["gaming", "entertainment"].includes(t.industry_type ?? ""))
          ) || t.agent_type === "business";
        }
        return t.agent_type === selectedSector.agent_type;
      })
    : allTemplates;

  // ── Handle availability check (debounced 300ms) ───────────────────────────

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
          // Has a reason → format validation failure
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

  // ── Step navigation ───────────────────────────────────────────────────────

  const canProceed = (() => {
    if (step === 0) return selectedSector !== null;
    if (step === 1) return selectedTemplate !== null;
    if (step === 2)
      return (
        handle.length >= 3 &&
        handleStatus === "available" &&
        agentName.trim().length >= 2
      );
    return false;
  })();

  const onNext = () => {
    if (canProceed && step < TOTAL_STEPS - 1) setStep((s) => s + 1);
  };

  const onBack = () => {
    if (step > 0) setStep((s) => s - 1);
  };

  // ── Submit ────────────────────────────────────────────────────────────────

  const handleSubmit = async () => {
    if (!selectedSector || !selectedTemplate || !handle || !agentName || submitting) return;
    clearError();
    setSubmitting(true);
    try {
      await post("/api/v1/onboarding/claim", {
        handle,
        name: agentName.trim(),
        agent_type: selectedSector.agent_type,
        template_id: selectedTemplate.id,
        industry_type: selectedTemplate.industry_type ?? null,
      });
      // Re-fetch agents so the dashboard sees the new agent immediately
      await fetchAgents();
      // Redirect with handle param so dashboard auto-selects the new agent
      router.push(`/dashboard?agent=${encodeURIComponent(handle)}`);
    } catch (err: unknown) {
      setSubmitting(false);
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail ?? "Failed to claim agent. Please try again.";
      console.error("Claim failed:", detail);
    }
  };

  return (
    <div className="flex items-start justify-center min-h-screen px-4 pb-28" style={{ paddingTop: "calc(env(safe-area-inset-top, 0px) + 32px)" }}>
      <div className="w-full max-w-md">
        {/* ── Header ────────────────────────────────────────────────────── */}
        <div className="flex flex-col items-center gap-2 mb-6">
          <Image
            src="/icons/logo.png"
            alt="DingDawg mascot"
            width={72}
            height={58}
            priority
          />
          <h1 className="text-2xl font-bold text-[var(--foreground)] font-heading">
            Claim Your Agent
          </h1>
          <p className="text-sm text-[var(--color-muted)] text-center max-w-xs">
            Set up your DingDawg AI agent in 3 steps. Under 2 minutes.
          </p>
          <p className="text-xs text-[var(--color-muted)] text-center">
            Free to start · 50 actions/mo ·{" "}
            <a
              href="https://dingdawg.com/pricing"
              target="_blank"
              rel="noopener noreferrer"
              className="text-[var(--gold-500)] underline underline-offset-2 hover:opacity-80"
            >
              Plans from $49.99/mo
            </a>
          </p>
        </div>

        {/* ── Progress ──────────────────────────────────────────────────── */}
        <OnboardingProgress
          currentStep={step}
          totalSteps={TOTAL_STEPS}
          labels={STEP_LABELS as unknown as string[]}
        />

        {/* ── Error banner ──────────────────────────────────────────────── */}
        {error && (
          <div className="mb-4 p-3 rounded-xl bg-red-500/10 border border-red-500/20 text-red-400 text-sm flex items-center gap-2">
            <AlertCircle className="h-4 w-4 flex-shrink-0" />
            <span className="flex-1">{error}</span>
            <button
              onClick={clearError}
              className="underline text-xs opacity-70 hover:opacity-100"
            >
              dismiss
            </button>
          </div>
        )}

        {/* ── Step card ─────────────────────────────────────────────────── */}
        <Card className="flex flex-col gap-4">
          {/* ── STEP 0: Sector selection ─────────────────────────────── */}
          {step === 0 && (
            <>
              <div>
                <h2 className="text-base font-semibold text-[var(--foreground)]">
                  Choose your sector
                </h2>
                <p className="text-xs text-[var(--color-muted)] mt-0.5">
                  Select the type of agent that fits your needs.
                </p>
              </div>
              <StepSector
                sectors={sectors.length > 0 ? sectors : FALLBACK_SECTORS}
                selectedSectorId={selectedSector?.id ?? null}
                onSelect={(sector) => {
                  setSelectedSector(sector);
                  // Clear downstream state when sector changes
                  setSelectedTemplate(null);
                }}
                isLoading={sectorsLoading}
              />
            </>
          )}

          {/* ── STEP 1: Template selection ───────────────────────────── */}
          {step === 1 && (
            <>
              <div>
                <h2 className="text-base font-semibold text-[var(--foreground)]">
                  Pick a starting template
                </h2>
                <p className="text-xs text-[var(--color-muted)] mt-0.5">
                  For{" "}
                  <span className="text-[var(--foreground)]">
                    {selectedSector?.icon} {selectedSector?.name}
                  </span>{" "}
                  — choose the template that best fits your use case.
                </p>
              </div>
              <StepTemplate
                templates={filteredTemplates}
                selectedTemplateId={selectedTemplate?.id ?? null}
                onSelect={setSelectedTemplate}
                isLoading={templatesLoading}
                sectorName={selectedSector?.name}
              />
            </>
          )}

          {/* ── STEP 2: Handle + name ────────────────────────────────── */}
          {step === 2 && (
            <>
              <div>
                <h2 className="text-base font-semibold text-[var(--foreground)]">
                  Claim your @handle
                </h2>
                <p className="text-xs text-[var(--color-muted)] mt-0.5">
                  Your handle is your agent&apos;s unique public identity.
                  Choose wisely — it&apos;s permanent.
                </p>
              </div>

              <StepHandle
                value={handle}
                onChange={onHandleChange}
                status={handleStatus}
                reason={handleReason}
                touched={handleTouched}
              />

              {/* Agent name — same step to reduce total steps */}
              <div className="pt-1">
                <label
                  htmlFor="agent-name"
                  className="block text-xs font-medium text-[var(--color-muted)] mb-1.5"
                >
                  Agent display name
                </label>
                <Input
                  id="agent-name"
                  value={agentName}
                  onChange={(e) => setAgentName(e.target.value)}
                  placeholder={
                    selectedSector?.id === "personal"
                      ? "My Personal Assistant"
                      : selectedSector?.id === "gaming"
                      ? "My Gaming Coach"
                      : "My Business Agent"
                  }
                  maxLength={60}
                />
                <p className="mt-1 text-[11px] text-[var(--color-muted)] opacity-60">
                  Shown to users who interact with your agent.
                </p>
              </div>

              {/* Summary review */}
              <div className="p-3 rounded-xl bg-white/4 border border-[var(--stroke)] space-y-1 text-xs">
                <div className="flex items-center justify-between">
                  <span className="text-[var(--color-muted)]">Sector</span>
                  <span className="text-[var(--foreground)] flex items-center gap-1">
                    <span aria-hidden="true">{selectedSector?.icon}</span>
                    {selectedSector?.name}
                  </span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-[var(--color-muted)]">Template</span>
                  <span className="text-[var(--foreground)] truncate max-w-[55%] text-right">
                    {selectedTemplate?.name ?? "—"}
                  </span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-[var(--color-muted)]">Handle</span>
                  <span className="text-[var(--gold-500)] font-medium">
                    {handle ? `@${handle}` : "—"}
                  </span>
                </div>
              </div>
            </>
          )}

          {/* ── Navigation buttons ───────────────────────────────────────── */}
          <div className="flex gap-2.5 mt-1">
            {step > 0 && (
              <Button
                variant="outline"
                onClick={onBack}
                className="flex-shrink-0 min-w-[80px]"
                aria-label="Go back to previous step"
              >
                <ChevronLeft className="h-4 w-4 mr-1" />
                Back
              </Button>
            )}

            {step < TOTAL_STEPS - 1 ? (
              <Button
                variant="gold"
                disabled={!canProceed}
                onClick={onNext}
                className="flex-1"
                aria-label={`Continue to ${STEP_LABELS[step + 1]}`}
              >
                Continue
                <ChevronRight className="h-4 w-4 ml-1" />
              </Button>
            ) : (
              <Button
                variant="gold"
                disabled={!canProceed || submitting}
                isLoading={submitting}
                onClick={handleSubmit}
                className="flex-1"
                aria-label="Claim your agent"
              >
                {submitting ? "Claiming…" : "Claim Agent"}
              </Button>
            )}
          </div>
        </Card>
      </div>
    </div>
  );
}
