"use client";

import { useState } from "react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { post } from "@/services/api/client";

type EventType =
  | "user_data_access"
  | "user_data_deletion"
  | "model_output_logging"
  | "high_risk_decision"
  | "pii_processing"
  | "cross_border_transfer"
  | "agent_capability_change"
  | "financial_transaction";

interface EventOption {
  value: EventType;
  question: string;
}

const EVENT_OPTIONS: EventOption[] = [
  { value: "user_data_access", question: "Does it look up or view customer data?" },
  { value: "user_data_deletion", question: "Does it delete customer data?" },
  { value: "model_output_logging", question: "Is its output logged or stored for review?" },
  { value: "high_risk_decision", question: "Does it decide something that significantly affects a person (approve/deny, etc.)?" },
  { value: "pii_processing", question: "Does it process personal info (names, emails, health data)?" },
  { value: "cross_border_transfer", question: "Does it send data across country borders?" },
  { value: "agent_capability_change", question: "Do its permissions change based on user actions?" },
  { value: "financial_transaction", question: "Does it handle payments or financial transactions?" },
];

interface FilingReadyEntry {
  clause?: string;
  category?: string;
  status: string;
  evidence_required: string[];
}

interface ClassifyResult {
  event_type: EventType;
  agent_id: string;
  regulations_triggered: Array<{
    regulation: string;
    article: string;
    description: string;
    severity: "low" | "medium" | "high" | string;
    action_required: string;
  }>;
  pre_clearance_status: string;
  highest_severity: string;
  actions_required: string[];
  filing_ready: Record<string, FilingReadyEntry>;
  classified_at: string;
}

function getOrCreateDemoAgentId(): string {
  if (typeof window === "undefined") return "demo-agent";
  const key = "dingdawg_demo_agent_id";
  let id = localStorage.getItem(key);
  if (!id) {
    id = `demo-${crypto.randomUUID()}`;
    localStorage.setItem(key, id);
  }
  return id;
}

function severityColor(severity: string): string {
  switch (severity) {
    case "high":
      return "text-[var(--color-danger)]";
    case "medium":
      return "text-[var(--gold-500)]";
    default:
      return "text-[var(--color-success)]";
  }
}

export default function ComplianceCheckPage() {
  const [selected, setSelected] = useState<EventType | null>(null);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<ClassifyResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function handleSelect(eventType: EventType) {
    setSelected(eventType);
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const agentId = getOrCreateDemoAgentId();
      const data = await post<ClassifyResult>("/api/v1/compliance/classify", {
        event_type: eventType,
        agent_id: agentId,
      });
      setResult(data);
    } catch {
      setError("Couldn't reach the compliance check right now — try again in a moment.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="min-h-screen bg-[var(--ink-950)] text-[var(--foreground)] px-6 py-16 sm:py-24">
      <div className="mx-auto max-w-2xl">
        <p className="text-xs uppercase tracking-widest text-[var(--gold-500)] mb-3">
          Free compliance check
        </p>
        <h1 className="text-3xl sm:text-4xl font-semibold mb-4 text-balance">
          What does your AI agent do?
        </h1>
        <p className="text-[var(--color-muted)] mb-10 max-w-prose">
          Pick the closest match. We&apos;ll tell you which regulations apply — no
          signup, no jargon.
        </p>

        <div className="grid gap-3 sm:grid-cols-2 mb-10">
          {EVENT_OPTIONS.map((opt) => (
            <button
              key={opt.value}
              onClick={() => handleSelect(opt.value)}
              disabled={loading}
              className={`text-left rounded-xl border px-5 py-4 transition-all duration-200 cursor-pointer
                hover:border-white/20 hover:bg-white/5 disabled:pointer-events-none disabled:opacity-50
                focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--gold-500)]
                ${
                  selected === opt.value
                    ? "border-[var(--gold-500)] bg-white/5"
                    : "border-[var(--stroke)]"
                }`}
            >
              <span className="text-sm">{opt.question}</span>
            </button>
          ))}
        </div>

        {loading && (
          <Card className="text-center text-[var(--color-muted)]">
            Checking against current regulations…
          </Card>
        )}

        {error && (
          <Card className="border border-[var(--color-danger)]/40">
            <p className="text-[var(--color-danger)] text-sm">{error}</p>
          </Card>
        )}

        {result && !loading && (
          <Card>
            <div className="flex items-center justify-between mb-6">
              <span className="text-sm text-[var(--color-muted)]">
                Pre-clearance status
              </span>
              <span
                className={`text-sm font-semibold ${
                  result.pre_clearance_status === "APPROVED"
                    ? "text-[var(--color-success)]"
                    : severityColor(result.highest_severity)
                }`}
              >
                {result.pre_clearance_status}
              </span>
            </div>

            <h2 className="text-xs uppercase tracking-wide text-[var(--color-muted)] mb-3">
              Regulations that apply
            </h2>
            <ul className="space-y-3 mb-8">
              {result.regulations_triggered.map((reg, i) => (
                <li
                  key={i}
                  className="border border-[var(--stroke)] rounded-lg px-4 py-3"
                >
                  <div className="flex items-center justify-between mb-1">
                    <span className="font-medium">
                      {reg.regulation} {reg.article}
                    </span>
                    <span className={`text-xs uppercase ${severityColor(reg.severity)}`}>
                      {reg.severity}
                    </span>
                  </div>
                  <p className="text-sm text-[var(--color-muted)]">
                    {reg.description}
                  </p>
                </li>
              ))}
            </ul>

            <h2 className="text-xs uppercase tracking-wide text-[var(--color-muted)] mb-3">
              What you need on file
            </h2>
            <div className="grid gap-3 sm:grid-cols-2 mb-8">
              {Object.entries(result.filing_ready).map(([framework, entry]) => (
                <div
                  key={framework}
                  className="border border-[var(--stroke)] rounded-lg px-4 py-3"
                >
                  <p className="font-medium uppercase text-xs tracking-wide mb-1">
                    {framework.replace(/_/g, " ")}
                  </p>
                  <p className="text-sm text-[var(--color-muted)] mb-2">
                    {entry.status.replace(/_/g, " ")}
                  </p>
                  <ul className="text-xs text-[var(--color-muted)] list-disc list-inside">
                    {entry.evidence_required.map((e) => (
                      <li key={e}>{e.replace(/_/g, " ")}</li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>

            <div className="border-t border-[var(--stroke)] pt-6 flex flex-col sm:flex-row gap-3">
              <Button
                variant="gold"
                size="lg"
                onClick={() => (window.location.href = "/pricing")}
              >
                See ongoing monitoring plans
              </Button>
              <Button
                variant="outline"
                size="lg"
                onClick={() => {
                  setResult(null);
                  setSelected(null);
                }}
              >
                Check a different action
              </Button>
            </div>
          </Card>
        )}
      </div>
    </main>
  );
}
