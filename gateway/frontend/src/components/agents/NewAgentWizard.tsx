// ##LLM:FILE: PRODUCT=DingDawg-Platform BLOCK=NewAgentWizard SEQ=1 PART_OF=agent-management CONNECTS_TO=Sidebar.tsx,agentStore.ts,platformService.ts
"use client";

import { useState, useEffect, useRef } from "react";
import { X, Bot, Clock, Webhook, Zap, CheckCircle } from "lucide-react";
import { useAgentStore } from "@/store/agentStore";
import { checkHandle } from "@/services/api/platformService";

// ── Constants ─────────────────────────────────────────────────────────────────

const INDUSTRIES = [
  { id: "restaurant",  label: "Restaurant" },
  { id: "retail",      label: "Retail" },
  { id: "service",     label: "Service" },
  { id: "real_estate", label: "Real Estate" },
  { id: "legal",       label: "Legal" },
  { id: "healthcare",  label: "Healthcare" },
  { id: "ecommerce",   label: "E-commerce" },
  { id: "other",       label: "Other" },
] as const;

const TRIGGER_OPTIONS = [
  { id: "manual"   as const, Icon: Zap,     label: "Manual",    desc: "User triggers from the dashboard" },
  { id: "schedule" as const, Icon: Clock,   label: "Scheduled", desc: "Runs on a recurring cron schedule" },
  { id: "webhook"  as const, Icon: Webhook, label: "Webhook",   desc: "Triggered via API, Slack, or Zapier" },
] as const;

type TriggerType = "manual" | "schedule" | "webhook";

const STEPS = ["Identity", "Industry", "Trigger", "Launch"] as const;

export const LS_TRIGGER_KEY = (id: string) => `dd_agent_trigger_${id}`;

// ── Props ─────────────────────────────────────────────────────────────────────

interface NewAgentWizardProps {
  onClose: () => void;
}

// ── Component ─────────────────────────────────────────────────────────────────

export function NewAgentWizard({ onClose }: NewAgentWizardProps) {
  const { createAgent, isLoading } = useAgentStore();

  const [step, setStep]           = useState(0);
  const [name, setName]           = useState("");
  const [handle, setHandle]       = useState("");
  const [handleOk, setHandleOk]   = useState<boolean | null>(null);
  const [industry, setIndustry]   = useState("service");
  const [agentType, setAgentType] = useState<"business" | "personal">("business");
  const [trigger, setTrigger]     = useState<TriggerType>("manual");
  const [schedule, setSchedule]   = useState("0 8 * * 1");
  const [error, setError]         = useState("");

  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (!handle || handle.length < 2) { setHandleOk(null); return; }
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(async () => {
      try {
        const res = await checkHandle(handle);
        setHandleOk(res.available);
      } catch {
        setHandleOk(null);
      }
    }, 400);
    return () => { if (timerRef.current) clearTimeout(timerRef.current); };
  }, [handle]);

  const deriveHandle = (v: string) =>
    v.toLowerCase().replace(/[^a-z0-9]/g, "").slice(0, 12);

  const handleNameChange = (v: string) => {
    setName(v);
    setHandle(deriveHandle(v));
  };

  const canAdvance = (): boolean => {
    if (step === 0) return name.trim().length >= 2 && handle.length >= 2 && handleOk !== false;
    if (step === 1) return !!industry;
    return true;
  };

  const handleCreate = async () => {
    try {
      setError("");
      const agent = await createAgent({
        name:          name.trim(),
        handle:        handle.trim(),
        agent_type:    agentType,
        industry_type: industry,
      });
      try {
        localStorage.setItem(
          LS_TRIGGER_KEY(agent.id),
          JSON.stringify({ trigger, schedule: trigger === "schedule" ? schedule : null })
        );
      } catch { /* storage full — non-fatal */ }
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create agent");
    }
  };

  const backdropRef = useRef<HTMLDivElement>(null);
  const onBackdrop  = (e: React.MouseEvent) => { if (e.target === backdropRef.current) onClose(); };

  return (
    <div
      ref={backdropRef}
      onClick={onBackdrop}
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4"
    >
      <div className="relative w-full max-w-md rounded-2xl border border-[var(--stroke)] bg-[var(--ink-950)] shadow-2xl overflow-hidden">

        {/* Header */}
        <div className="flex items-center justify-between px-5 pt-5 pb-3 border-b border-[var(--stroke)]">
          <div className="flex items-center gap-2.5">
            <div className="h-7 w-7 rounded-lg bg-[var(--gold-500)]/15 flex items-center justify-center shrink-0">
              <Bot size={14} className="text-[var(--gold-500)]" />
            </div>
            <div>
              <div className="text-[13px] font-semibold text-white tracking-[-0.01em]">New Agent</div>
              <div className="font-mono text-[9.5px] text-white/50">{step + 1}/{STEPS.length} — {STEPS[step]}</div>
            </div>
          </div>
          <button type="button" onClick={onClose} aria-label="Close"
            className="h-7 w-7 rounded-md flex items-center justify-center text-white/40 hover:text-white hover:bg-white/[0.06] transition-colors">
            <X size={13} />
          </button>
        </div>

        {/* Progress bar */}
        <div className="h-[2px] bg-white/[0.05]">
          <div className="h-full bg-[var(--gold-500)] transition-all duration-300 ease-out"
            style={{ width: `${((step + 1) / STEPS.length) * 100}%` }} />
        </div>

        {/* Body */}
        <div className="px-5 py-5 min-h-[260px]">

          {/* Step 0 — Identity */}
          {step === 0 && (
            <div className="space-y-3.5">
              <div>
                <label className="font-mono text-[9.5px] uppercase tracking-[0.14em] text-white/55 block mb-1.5">Agent Name</label>
                <input autoFocus value={name} onChange={(e) => handleNameChange(e.target.value)}
                  placeholder="e.g. Sales Closer, Support Bot"
                  className="w-full rounded-lg border border-[var(--stroke)] bg-white/[0.03] px-3 py-2.5 text-[13px] text-white placeholder:text-white/30 outline-none focus:border-[var(--gold-500)]/60 focus:bg-white/[0.05] transition-all" />
              </div>
              <div>
                <label className="font-mono text-[9.5px] uppercase tracking-[0.14em] text-white/55 block mb-1.5">Handle</label>
                <div className={["flex items-center rounded-lg border bg-white/[0.03] overflow-hidden transition-all",
                  handleOk === false ? "border-red-500/50" : handleOk === true ? "border-[#22c55e]/50" : "border-[var(--stroke)] focus-within:border-[var(--gold-500)]/60",
                ].join(" ")}>
                  <span className="pl-3 text-[var(--gold-500)] font-mono text-[13px] shrink-0">@</span>
                  <input value={handle} onChange={(e) => setHandle(deriveHandle(e.target.value))} placeholder="salesbot"
                    className="flex-1 bg-transparent px-2 py-2.5 text-[13px] text-white placeholder:text-white/30 outline-none" />
                  {handleOk === true  && <CheckCircle size={13} className="mr-2.5 text-[#22c55e] shrink-0" />}
                  {handleOk === false && <X           size={13} className="mr-2.5 text-red-400 shrink-0" />}
                </div>
                {handleOk === false && (
                  <p className="font-mono text-[9px] text-red-400 mt-1">@{handle} is taken — try another</p>
                )}
              </div>
              <div>
                <label className="font-mono text-[9.5px] uppercase tracking-[0.14em] text-white/55 block mb-1.5">Type</label>
                <div className="grid grid-cols-2 gap-1.5">
                  {(["business", "personal"] as const).map((t) => (
                    <button key={t} type="button" onClick={() => setAgentType(t)}
                      className={["rounded-lg border px-3 py-2 text-[12px] font-medium capitalize transition-all",
                        agentType === t
                          ? "border-[var(--gold-500)]/50 bg-[var(--gold-500)]/10 text-[var(--gold-500)]"
                          : "border-white/[0.08] bg-white/[0.02] text-white/65 hover:bg-white/[0.05]",
                      ].join(" ")}>{t}</button>
                  ))}
                </div>
              </div>
            </div>
          )}

          {/* Step 1 — Industry */}
          {step === 1 && (
            <div>
              <div className="font-mono text-[9.5px] uppercase tracking-[0.14em] text-white/55 mb-2.5">Industry</div>
              <div className="grid grid-cols-2 gap-1.5">
                {INDUSTRIES.map((ind) => (
                  <button key={ind.id} type="button" onClick={() => setIndustry(ind.id)}
                    className={["rounded-lg border px-3 py-2.5 text-[12px] font-medium text-left transition-all",
                      industry === ind.id
                        ? "border-[var(--gold-500)]/50 bg-[var(--gold-500)]/10 text-[var(--gold-500)]"
                        : "border-white/[0.08] bg-white/[0.02] text-white/70 hover:bg-white/[0.05] hover:border-white/[0.15]",
                    ].join(" ")}>{ind.label}</button>
                ))}
              </div>
            </div>
          )}

          {/* Step 2 — Trigger */}
          {step === 2 && (
            <div className="space-y-2">
              <div className="font-mono text-[9.5px] uppercase tracking-[0.14em] text-white/55 mb-2.5">How does this agent activate?</div>
              {TRIGGER_OPTIONS.map(({ id, Icon, label, desc }) => (
                <button key={id} type="button" onClick={() => setTrigger(id)}
                  className={["w-full rounded-lg border px-3 py-3 text-left flex items-center gap-3 transition-all",
                    trigger === id
                      ? "border-[var(--gold-500)]/50 bg-[var(--gold-500)]/10"
                      : "border-white/[0.08] bg-white/[0.02] hover:bg-white/[0.05] hover:border-white/[0.15]",
                  ].join(" ")}>
                  <div className={["h-8 w-8 rounded-md flex items-center justify-center shrink-0",
                    trigger === id ? "bg-[var(--gold-500)]/20 text-[var(--gold-500)]" : "bg-white/[0.05] text-white/50",
                  ].join(" ")}><Icon size={14} strokeWidth={1.7} /></div>
                  <div className="min-w-0">
                    <div className={["text-[12.5px] font-medium", trigger === id ? "text-[var(--gold-500)]" : "text-white/85"].join(" ")}>{label}</div>
                    <div className="font-mono text-[9.5px] text-white/50 mt-0.5 truncate">{desc}</div>
                  </div>
                </button>
              ))}
              {trigger === "schedule" && (
                <div className="pt-1">
                  <label className="font-mono text-[9.5px] uppercase tracking-[0.14em] text-white/55 block mb-1.5">Cron expression</label>
                  <input value={schedule} onChange={(e) => setSchedule(e.target.value)} placeholder="0 8 * * 1"
                    className="w-full rounded-lg border border-[var(--stroke)] bg-white/[0.03] px-3 py-2 text-[12px] font-mono text-white placeholder:text-white/30 outline-none focus:border-[var(--gold-500)]/60 transition-all" />
                  <div className="font-mono text-[9px] text-white/40 mt-1">e.g. 0 8 * * 1 = every Monday at 8 AM</div>
                </div>
              )}
              {trigger === "webhook" && (
                <div className="rounded-lg border border-[var(--gold-500)]/20 bg-[var(--gold-500)]/5 px-3 py-2.5 mt-1">
                  <div className="font-mono text-[9.5px] text-[var(--gold-500)]">Webhook URL generated after creation</div>
                  <div className="font-mono text-[9px] text-white/50 mt-0.5">Trigger via POST from Slack, Zapier, or any HTTP client</div>
                </div>
              )}
            </div>
          )}

          {/* Step 3 — Launch preview */}
          {step === 3 && (
            <div className="space-y-3">
              <div className="rounded-xl border border-[var(--stroke)] bg-white/[0.02] p-4 space-y-3">
                <div className="flex items-center gap-3">
                  <div className="h-10 w-10 rounded-lg bg-[var(--gold-500)] flex items-center justify-center text-[#07111c] font-bold text-[16px] shrink-0">
                    {name.charAt(0).toUpperCase() || "?"}
                  </div>
                  <div className="min-w-0">
                    <div className="text-[14px] font-semibold text-white truncate">{name}</div>
                    <div className="font-mono text-[10px] text-[var(--gold-500)]">@{handle}</div>
                  </div>
                </div>
                <div className="grid grid-cols-3 gap-1.5">
                  {[
                    { label: "Type",     value: agentType },
                    { label: "Industry", value: industry.replace("_", " ") },
                    { label: "Trigger",  value: trigger },
                  ].map(({ label, value }) => (
                    <div key={label} className="rounded-lg bg-white/[0.03] border border-white/[0.06] px-2 py-2">
                      <div className="font-mono text-[8.5px] uppercase tracking-[0.12em] text-white/40 mb-0.5">{label}</div>
                      <div className="text-[11px] text-white/80 capitalize truncate">{value}</div>
                    </div>
                  ))}
                </div>
                {trigger === "schedule" && (
                  <div className="flex items-center gap-1.5 font-mono text-[9px] text-white/45">
                    <Clock size={10} className="shrink-0" />{schedule}
                  </div>
                )}
              </div>
              {error && (
                <div className="rounded-lg bg-red-500/10 border border-red-500/20 px-3 py-2 text-[12px] text-red-400">{error}</div>
              )}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center gap-2 px-5 py-4 border-t border-[var(--stroke)]">
          {step > 0 && (
            <button type="button" onClick={() => setStep((s) => s - 1)} disabled={isLoading}
              className="flex-1 rounded-lg border border-white/[0.1] bg-white/[0.02] text-white/60 text-[12.5px] font-medium py-2.5 hover:bg-white/[0.04] disabled:opacity-40 transition-all">
              Back
            </button>
          )}
          {step < STEPS.length - 1 ? (
            <button type="button" onClick={() => setStep((s) => s + 1)} disabled={!canAdvance()}
              className="flex-[2] rounded-lg bg-[var(--gold-500)] text-[#07111c] font-bold text-[12.5px] py-2.5 hover:brightness-110 disabled:opacity-40 disabled:cursor-not-allowed transition-all">
              Continue
            </button>
          ) : (
            <button type="button" onClick={handleCreate} disabled={isLoading}
              className="flex-[2] rounded-lg bg-[var(--gold-500)] text-[#07111c] font-bold text-[12.5px] py-2.5 hover:brightness-110 disabled:opacity-40 disabled:cursor-not-allowed transition-all">
              {isLoading ? "Launching…" : "Launch Agent"}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
