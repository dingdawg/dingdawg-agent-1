"use client";

/**
 * AgentConfigurator — Tabbed configuration container for agent settings.
 *
 * Tabs:
 *   General     — name, industry, status, greeting, description
 *   Personality — system prompt, tone, language, response length
 *   Skills      — toggle 16 backend skills on/off
 *   Branding    — color, avatar, business name, widget greeting
 *   Danger Zone — delete agent
 *
 * Each tab has its own save button. Changes are local until saved.
 * PATCH /api/v1/agents/{id} accepts config_json and branding_json fields.
 */

import { useState, useCallback } from "react";
import {
  Settings,
  Sparkles,
  Zap,
  Palette,
  AlertTriangle,
  CheckCircle,
} from "lucide-react";
import { PromptEditor, type PersonalityConfig } from "./PromptEditor";
import { SkillToggles, type SkillsConfig } from "./SkillToggles";
import { BrandingEditor, type BrandingConfig } from "./BrandingEditor";
import { type AgentResponse } from "@/services/api/platformService";
import { useAgentStore } from "@/store/agentStore";

// ─── Types ────────────────────────────────────────────────────────────────────

type TabId = "general" | "personality" | "skills" | "branding" | "danger";

interface Tab {
  id: TabId;
  label: string;
  icon: React.ReactNode;
}

interface AgentConfiguratorProps {
  agent: AgentResponse;
  /** Rendered content for the General tab (passed from parent SettingsContent) */
  generalTabContent: React.ReactNode;
}

// ─── Tab definitions ──────────────────────────────────────────────────────────

const TABS: Tab[] = [
  {
    id: "general",
    label: "General",
    icon: <Settings className="h-3.5 w-3.5" />,
  },
  {
    id: "personality",
    label: "Personality",
    icon: <Sparkles className="h-3.5 w-3.5" />,
  },
  {
    id: "skills",
    label: "Skills",
    icon: <Zap className="h-3.5 w-3.5" />,
  },
  {
    id: "branding",
    label: "Branding",
    icon: <Palette className="h-3.5 w-3.5" />,
  },
  {
    id: "danger",
    label: "Danger",
    icon: <AlertTriangle className="h-3.5 w-3.5" />,
  },
];

// ─── JSON parsers — safe, never throw ─────────────────────────────────────────

function parseConfigJson(raw: unknown): Record<string, unknown> {
  if (!raw) return {};
  if (typeof raw === "object" && raw !== null) return raw as Record<string, unknown>;
  if (typeof raw === "string") {
    try {
      return JSON.parse(raw) as Record<string, unknown>;
    } catch {
      return {};
    }
  }
  return {};
}

function parseBrandingJson(raw: unknown): Record<string, unknown> {
  return parseConfigJson(raw);
}

// ─── Component ────────────────────────────────────────────────────────────────

export function AgentConfigurator({
  agent,
  generalTabContent,
}: AgentConfiguratorProps) {
  const [activeTab, setActiveTab] = useState<TabId>("general");
  const [saving, setSaving] = useState(false);
  const [saveSuccess, setSaveSuccess] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const { fetchAgents } = useAgentStore();

  // Pull stored JSON blobs — the AgentResponse may not have these fields typed
  // since the backend type definition doesn't include them yet. We access via
  // type assertion.
  const rawAgent = agent as AgentResponse & {
    config_json?: unknown;
    branding_json?: unknown;
  };
  const configJson = parseConfigJson(rawAgent.config_json);
  const brandingJson = parseBrandingJson(rawAgent.branding_json);

  // ── Shared save helper ─────────────────────────────────────────────────────

  const showSuccess = (msg: string) => {
    setSaveSuccess(msg);
    setTimeout(() => setSaveSuccess(null), 3500);
  };

  const runSave = useCallback(
    async (payload: Record<string, unknown>, successMsg: string) => {
      setSaving(true);
      setSaveError(null);
      try {
        // We need to send config_json / branding_json which are not in the
        // typed UpdateAgentPayload. Use the raw apiClient to allow extra fields.
        const apiClient = (await import("@/services/api/client")).default;
        await apiClient.patch(`/api/v1/agents/${agent.id}`, payload);
        await fetchAgents();
        showSuccess(successMsg);
      } catch (err: unknown) {
        const detail =
          (err as { response?: { data?: { detail?: string } } })?.response?.data
            ?.detail ?? "Failed to save";
        setSaveError(detail);
      } finally {
        setSaving(false);
      }
    },
    [agent.id, fetchAgents]
  );

  // ── Tab save handlers ──────────────────────────────────────────────────────

  const handleSavePersonality = async (config: PersonalityConfig) => {
    const merged = { ...configJson, ...config };
    await runSave({ config_json: JSON.stringify(merged) }, "Personality saved");
  };

  const handleSaveSkills = async (config: SkillsConfig) => {
    const merged = { ...configJson, ...config };
    await runSave({ config_json: JSON.stringify(merged) }, "Skills saved");
  };

  const handleSaveBranding = async (config: BrandingConfig) => {
    await runSave({ branding_json: JSON.stringify(config) }, "Branding saved");
  };

  // ── Derived initial values ─────────────────────────────────────────────────

  const personalityConfig = {
    system_prompt: configJson.system_prompt as string | undefined,
    tone: configJson.tone as PersonalityConfig["tone"] | undefined,
    language: configJson.language as PersonalityConfig["language"] | undefined,
    response_length: configJson.response_length as
      | PersonalityConfig["response_length"]
      | undefined,
  };

  const skillsConfig = {
    enabled_skills: configJson.enabled_skills as string[] | undefined,
  };

  const brandingConfig = {
    primary_color: brandingJson.primary_color as string | undefined,
    avatar_url: brandingJson.avatar_url as string | undefined,
    business_name: brandingJson.business_name as string | undefined,
    widget_greeting: brandingJson.widget_greeting as string | undefined,
  };

  return (
    <div>
      {/* ── Toast notifications ────────────────────────────────────────────── */}
      {saveSuccess && (
        <div className="mb-4 p-3 rounded-xl bg-green-500/10 border border-green-500/20 text-green-400 text-sm flex items-center gap-2 card-enter">
          <CheckCircle className="h-4 w-4 flex-shrink-0" />
          {saveSuccess}
        </div>
      )}
      {saveError && (
        <div className="mb-4 p-3 rounded-xl bg-red-500/10 border border-red-500/20 text-red-400 text-sm flex items-center gap-2">
          <AlertTriangle className="h-4 w-4 flex-shrink-0" />
          {saveError}
          <button
            onClick={() => setSaveError(null)}
            className="ml-auto text-xs underline"
          >
            dismiss
          </button>
        </div>
      )}

      {/* ── Tab bar ────────────────────────────────────────────────────────── */}
      <div className="mb-5 overflow-x-auto scrollbar-thin">
        <div className="flex gap-1 min-w-max">
          {TABS.map((tab) => {
            const isActive = activeTab === tab.id;
            const isDanger = tab.id === "danger";
            return (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={`flex items-center gap-1.5 px-3 py-2 rounded-full text-xs font-medium whitespace-nowrap transition-all ${
                  isActive
                    ? isDanger
                      ? "bg-red-500/15 text-red-400 border border-red-500/30"
                      : "bg-[var(--gold-500)]/15 text-[var(--gold-500)] border border-[var(--gold-500)]/30"
                    : isDanger
                    ? "text-red-400/60 hover:text-red-400 hover:bg-red-500/10"
                    : "text-[var(--color-muted)] hover:text-[var(--foreground)] hover:bg-white/5"
                }`}
              >
                {tab.icon}
                {tab.label}
              </button>
            );
          })}
        </div>
      </div>

      {/* ── Tab content ────────────────────────────────────────────────────── */}

      {activeTab === "general" && <div>{generalTabContent}</div>}

      {activeTab === "personality" && (
        <PromptEditor
          initialConfig={personalityConfig}
          agentName={agent.name}
          onSave={handleSavePersonality}
          saving={saving}
        />
      )}

      {activeTab === "skills" && (
        <SkillToggles
          initialConfig={skillsConfig}
          agentType={agent.agent_type}
          onSave={handleSaveSkills}
          saving={saving}
        />
      )}

      {activeTab === "branding" && (
        <BrandingEditor
          initialConfig={brandingConfig}
          agentName={agent.name}
          agentHandle={agent.handle}
          onSave={handleSaveBranding}
          saving={saving}
        />
      )}

      {activeTab === "danger" && (
        <div className="glass-panel p-5 border-red-500/20">
          <h2 className="text-sm font-heading font-semibold text-red-400 mb-2 flex items-center gap-2">
            <AlertTriangle className="h-4 w-4" />
            Danger Zone
          </h2>
          <p className="text-xs text-[var(--color-muted)] mb-1">
            This section is available in the General tab&apos;s Danger Zone panel.
          </p>
          <p className="text-xs text-[var(--color-muted)]">
            Scroll down in General to permanently delete this agent and all
            associated data.
          </p>
          <button
            onClick={() => setActiveTab("general")}
            className="mt-3 text-xs text-[var(--gold-500)] underline underline-offset-2 hover:text-[var(--gold-600)]"
          >
            Go to General tab
          </button>
        </div>
      )}
    </div>
  );
}
