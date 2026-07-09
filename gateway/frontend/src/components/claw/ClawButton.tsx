//##LLM:FILE: PRODUCT=dingdawg-platform SYSTEM=claw ENTRY=yes PART_OF=src/components/claw CONNECTS_TO=src/app/api/v1/claw/run/route.ts,src/app/api/v1/claw/approve/route.ts,src/store/authStore.ts BACK_REF=yes
"use client";

import { useState, useCallback, useRef } from "react";
import { Zap, CheckCircle, AlertCircle, Loader2, ChevronDown, ChevronUp } from "lucide-react";
import { cn } from "@/lib/utils";
import { useAuthStore } from "@/store/authStore";

// ─── Types ─────────────────────────────────────────────────────────────────

interface ClawProposal {
  type: string;
  to: string;
  toName: string;
  subject: string;
  body: string;
  daysSilent: number;
}

interface ClawProposalEvent {
  action: string;
  proposals: ClawProposal[];
  token: string;
  expires_at: number;
  requested_by: string | null;
}

type ClawState =
  | "idle"
  | "running"
  | "awaiting_approval"
  | "approving"
  | "approved"
  | "tier_locked"
  | "error";

export interface ClawButtonProps {
  workflow: string;
  label?: string;
  className?: string;
}

// ─── Component ─────────────────────────────────────────────────────────────

export function ClawButton({ workflow, label = "Run CLAW", className }: ClawButtonProps) {
  const user = useAuthStore((s) => s.user);

  const [state, setState] = useState<ClawState>("idle");
  const [thinkingSteps, setThinkingSteps] = useState<string[]>([]);
  const [proposalData, setProposalData] = useState<ClawProposalEvent | null>(null);
  const [receipt, setReceipt] = useState<Record<string, string> | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  const runWorkflow = useCallback(async () => {
    if (state === "running" || state === "approving") return;
    setState("running");
    setThinkingSteps([]);
    setProposalData(null);
    setReceipt(null);
    setErrorMsg(null);
    setExpanded(true);

    abortRef.current = new AbortController();

    try {
      const res = await fetch("/api/v1/claw/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ workflow, userId: user?.id ?? null }),
        signal: abortRef.current.signal,
      });

      if (!res.ok) {
        const body = await res.json().catch(() => ({})) as { code?: string; error?: string };
        if (res.status === 402 || body?.code === "TIER_REQUIRED") {
          setState("tier_locked");
          return;
        }
        throw new Error(body?.error ?? `HTTP ${res.status}`);
      }

      const reader = res.body?.getReader();
      if (!reader) throw new Error("No response stream");

      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        const parts = buffer.split("\n\n");
        buffer = parts.pop() ?? "";

        for (const part of parts) {
          const eventMatch = part.match(/^event: (\w+)\ndata: (.+)$/);
          if (!eventMatch) continue;
          const [, event, dataStr] = eventMatch;
          const data = JSON.parse(dataStr) as Record<string, unknown>;

          if (event === "thinking") {
            setThinkingSteps((prev) => [...prev, data.step as string]);
          } else if (event === "proposal") {
            setProposalData(data as unknown as ClawProposalEvent);
            setState("awaiting_approval");
          } else if (event === "error") {
            setErrorMsg((data.message as string) ?? "Unknown error");
            setState("error");
          } else if (event === "done") {
            if ((data.status as string) === "awaiting_approval") {
              setState("awaiting_approval");
            }
          }
        }
      }
    } catch (e: unknown) {
      if ((e as Error)?.name === "AbortError") return;
      setErrorMsg((e as Error)?.message ?? "Unknown error");
      setState("error");
    }
  }, [workflow, user?.id, state]);

  const approve = useCallback(async () => {
    if (!proposalData?.token) return;
    setState("approving");
    try {
      const res = await fetch("/api/v1/claw/approve", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token: proposalData.token, userId: user?.id ?? null }),
      });
      const body = await res.json() as { ok: boolean; error?: string; receipt?: Record<string, string> };
      if (!body.ok) throw new Error(body.error ?? "Approval failed");
      setReceipt(body.receipt ?? {});
      setState("approved");
    } catch (e: unknown) {
      setErrorMsg((e as Error)?.message ?? "Approval failed");
      setState("error");
    }
  }, [proposalData, user?.id]);

  const reset = useCallback(() => {
    abortRef.current?.abort();
    setState("idle");
    setThinkingSteps([]);
    setProposalData(null);
    setReceipt(null);
    setErrorMsg(null);
    setExpanded(false);
  }, []);

  const isRunning = state === "running";
  const isLocked = state === "tier_locked";

  return (
    <div className={cn("flex flex-col gap-3", className)}>
      {/* ── Trigger row ─────────────────────────────────────────────── */}
      <div className="flex items-center gap-2">
        <button
          onClick={state === "idle" || state === "error" ? runWorkflow : reset}
          disabled={isRunning || state === "approving"}
          aria-label={isRunning ? "CLAW running…" : label}
          className={cn(
            "inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-semibold transition-all",
            "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--gold-500)]",
            isRunning || state === "approving"
              ? "opacity-50 cursor-not-allowed bg-[var(--stroke)] text-[var(--color-muted)]"
              : state === "approved"
              ? "bg-emerald-600/20 text-emerald-400 border border-emerald-600/30 hover:bg-emerald-600/30"
              : isLocked
              ? "bg-[var(--stroke)] text-[var(--color-muted)] border border-[var(--stroke)]"
              : "bg-[var(--gold-500)] text-[var(--ink-950)] hover:bg-[var(--gold-600)] active:scale-[0.98]"
          )}
        >
          {isRunning ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : state === "approved" ? (
            <CheckCircle className="h-4 w-4" />
          ) : state === "error" ? (
            <AlertCircle className="h-4 w-4" />
          ) : (
            <Zap className="h-4 w-4" />
          )}
          {isRunning
            ? "Running…"
            : state === "approved"
            ? "Approved"
            : state === "error"
            ? "Retry"
            : isLocked
            ? "Pro Required"
            : label}
        </button>

        {state !== "idle" && (
          <button
            onClick={() => setExpanded((v) => !v)}
            aria-label={expanded ? "Collapse" : "Expand"}
            className="p-1 rounded text-[var(--color-muted)] hover:text-[var(--foreground)] transition-colors"
          >
            {expanded ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
          </button>
        )}
      </div>

      {/* ── Tier locked ─────────────────────────────────────────────── */}
      {isLocked && (
        <div className="rounded-lg border border-[var(--gold-500)]/30 bg-[var(--gold-500)]/5 px-4 py-3 text-sm">
          <p className="text-[var(--foreground)] font-medium mb-1">Pro plan required</p>
          <p className="text-[var(--color-muted)] mb-3">
            CLAW agentic workflows are available on Pro and above.
          </p>
          <a
            href="/pricing"
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold
                       bg-[var(--gold-500)] text-[var(--ink-950)] hover:bg-[var(--gold-600)] transition-colors"
          >
            Upgrade to Pro
          </a>
        </div>
      )}

      {/* ── Expandable panel ─────────────────────────────────────────── */}
      {expanded && state !== "idle" && state !== "tier_locked" && (
        <div className="rounded-lg border border-[var(--stroke)] bg-white/[0.03] overflow-hidden">

          {/* Thinking steps — only while running, cleared when proposals arrive */}
          {thinkingSteps.length > 0 && state === "running" && (
            <div className="px-4 py-3 border-b border-[var(--stroke)]">
              <p className="text-[10px] uppercase tracking-[0.18em] text-[var(--color-muted)] mb-2 font-medium">
                Thinking
              </p>
              <ul className="space-y-1">
                {thinkingSteps.map((step, i) => (
                  <li key={i} className="flex items-center gap-2 text-sm text-[var(--color-muted)]">
                    <span className="h-1.5 w-1.5 rounded-full bg-[var(--gold-500)]/60 shrink-0" />
                    {step}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Proposals — approval gate. Conversion Freeze: no animation in this section */}
          {proposalData && (state === "awaiting_approval" || state === "approving") && (
            <div className="px-4 py-3">
              <p className="text-[10px] uppercase tracking-[0.18em] text-[var(--color-muted)] mb-3 font-medium">
                Proposals — {proposalData.proposals.length} action
                {proposalData.proposals.length !== 1 ? "s" : ""}
              </p>
              <ul className="space-y-2 mb-4">
                {proposalData.proposals.map((p, i) => (
                  <li
                    key={i}
                    className="rounded-md border border-[var(--stroke)] bg-white/[0.02] px-3 py-2.5"
                  >
                    <div className="flex items-start justify-between gap-2 mb-1">
                      <span className="text-sm font-medium text-[var(--foreground)]">{p.toName}</span>
                      <span className="text-[10px] text-[var(--color-muted)] whitespace-nowrap mt-0.5">
                        {p.daysSilent}d silent
                      </span>
                    </div>
                    <p className="text-xs text-[var(--color-muted)] truncate">{p.subject}</p>
                  </li>
                ))}
              </ul>

              <div className="flex items-center gap-2">
                <button
                  onClick={approve}
                  disabled={state === "approving"}
                  className={cn(
                    "inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-semibold transition-all",
                    "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--gold-500)]",
                    state === "approving"
                      ? "opacity-50 cursor-not-allowed bg-[var(--stroke)] text-[var(--color-muted)]"
                      : "bg-[var(--gold-500)] text-[var(--ink-950)] hover:bg-[var(--gold-600)] active:scale-[0.98]"
                  )}
                >
                  {state === "approving" && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                  {state === "approving" ? "Approving…" : "Approve & Execute"}
                </button>
                <button
                  onClick={reset}
                  className="px-3 py-2 rounded-lg text-sm text-[var(--color-muted)] border border-[var(--stroke)]
                             hover:border-white/20 hover:text-[var(--foreground)] transition-colors"
                >
                  Cancel
                </button>
              </div>
            </div>
          )}

          {/* Receipt */}
          {state === "approved" && receipt && (
            <div className="px-4 py-3">
              <div className="flex items-center gap-2 mb-2">
                <CheckCircle className="h-4 w-4 text-emerald-400" />
                <p className="text-sm font-medium text-[var(--foreground)]">Executed</p>
              </div>
              <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
                {Object.entries(receipt).map(([k, v]) => [
                  <dt key={`k-${k}`} className="text-[var(--color-muted)] capitalize">
                    {k.replace(/_/g, " ")}
                  </dt>,
                  <dd key={`v-${k}`} className="text-[var(--foreground)] font-mono truncate">
                    {v}
                  </dd>,
                ])}
              </dl>
              <button
                onClick={reset}
                className="mt-3 text-xs text-[var(--color-muted)] hover:text-[var(--foreground)] transition-colors"
              >
                Run again
              </button>
            </div>
          )}

          {/* Error */}
          {state === "error" && errorMsg && (
            <div className="px-4 py-3 flex items-start gap-2">
              <AlertCircle className="h-4 w-4 text-red-400 mt-0.5 shrink-0" />
              <p className="text-sm text-red-400">{errorMsg}</p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
