"use client";

/**
 * Settings page — agent configuration, profile info, and danger zone.
 *
 * Uses existing backend endpoints:
 *   PATCH /api/v1/agents/{id}   — update agent (name, status, config_json, branding_json)
 *   DELETE /api/v1/agents/{id}  — delete agent
 *
 * Transformed into a tabbed interface via AgentConfigurator:
 *   General | Personality | Skills | Branding | Danger
 */

import { useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import { Save, Trash2, AlertTriangle, CheckCircle, Shield } from "lucide-react";
import { useAuthStore } from "@/store/authStore";
import { useAgentStore } from "@/store/agentStore";
import { deleteAgent, isAgentActive } from "@/services/api/platformService";
import { setAccessToken } from "@/services/api/client";
import { ProtectedRoute } from "@/components/auth/ProtectedRoute";
import { AppShell } from "@/components/layout/AppShell";
import { PageHeader } from "@/components/layout/PageHeader";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { AgentConfigurator } from "@/components/settings/AgentConfigurator";
import { PasskeyManager } from "@/components/settings/PasskeyManager";
import dynamic from "next/dynamic";

const MfaSetupPanel = dynamic(
  () => import("@/components/settings/MfaSetupPanel").then((m) => m.MfaSetupPanel),
  { ssr: false }
);

export default function SettingsPage() {
  return (
    <ProtectedRoute>
      <AppShell>
        <SettingsContent />
      </AppShell>
    </ProtectedRoute>
  );
}

function SettingsContent() {
  const router = useRouter();
  const { user, logout } = useAuthStore();
  const { currentAgent, agents, isLoading, fetchAgents, reset: resetAgents } = useAgentStore();

  // ── General tab state ──────────────────────────────────────────────────────
  const [name, setName] = useState("");
  const [industry, setIndustry] = useState("");
  const [isActive, setIsActive] = useState(true);
  const [greeting, setGreeting] = useState("");
  const [description, setDescription] = useState("");
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // ── Danger zone state ──────────────────────────────────────────────────────
  const [deleteConfirm, setDeleteConfirm] = useState(false);
  const [deleting, setDeleting] = useState(false);

  useEffect(() => {
    fetchAgents();
  }, [fetchAgents]);

  // Redirect to /claim if no agents
  useEffect(() => {
    if (!isLoading && agents.length === 0) {
      router.replace("/claim");
    }
  }, [isLoading, agents.length, router]);

  // Populate form from current agent
  useEffect(() => {
    if (currentAgent) {
      setName(currentAgent.name);
      setIndustry(currentAgent.industry_type ?? "");
      setIsActive(isAgentActive(currentAgent));

      // Read greeting + description from config_json if present
      const rawConfig = (currentAgent as typeof currentAgent & { config_json?: unknown })
        .config_json;
      if (rawConfig && typeof rawConfig === "object" && rawConfig !== null) {
        const cfg = rawConfig as Record<string, unknown>;
        setGreeting((cfg.greeting as string) ?? "");
        setDescription((cfg.description as string) ?? "");
      } else if (typeof rawConfig === "string") {
        try {
          const cfg = JSON.parse(rawConfig) as Record<string, unknown>;
          setGreeting((cfg.greeting as string) ?? "");
          setDescription((cfg.description as string) ?? "");
        } catch {
          // malformed json — ignore
        }
      }
    }
  }, [currentAgent]);

  const handleSave = useCallback(async () => {
    if (!currentAgent) return;
    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      // Merge greeting + description into config_json
      const existingConfig = (() => {
        const raw = (currentAgent as typeof currentAgent & { config_json?: unknown }).config_json;
        if (!raw) return {};
        if (typeof raw === "object" && raw !== null) return raw as Record<string, unknown>;
        if (typeof raw === "string") {
          try { return JSON.parse(raw) as Record<string, unknown>; } catch { return {}; }
        }
        return {};
      })();

      const updatedConfig = {
        ...existingConfig,
        greeting: greeting.trim(),
        description: description.trim(),
      };

      // Use raw apiClient so we can send config_json alongside standard fields
      const apiClient = (await import("@/services/api/client")).default;
      await apiClient.patch(`/api/v1/agents/${currentAgent.id}`, {
        name: name.trim(),
        industry_type: industry.trim() || undefined,
        status: isActive ? "active" : "suspended",
        config_json: updatedConfig,
      });

      setSaved(true);
      await fetchAgents();
      setTimeout(() => setSaved(false), 3000);
    } catch (err: unknown) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail ?? "Failed to save settings";
      setError(detail);
    } finally {
      setSaving(false);
    }
  }, [currentAgent, name, industry, isActive, greeting, description, fetchAgents]);

  const handleDelete = useCallback(async () => {
    if (!currentAgent) return;
    setDeleting(true);
    try {
      await deleteAgent(currentAgent.id);
      // Clear all auth state and in-memory agent state before navigating.
      // This prevents the agents.length === 0 useEffect from racing to /claim
      // and ensures localStorage tokens are wiped so ProtectedRoute stays clean.
      logout();
      setAccessToken(null);
      resetAgents();
      router.replace("/login");
    } catch (err: unknown) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail ?? "Failed to delete agent";
      setError(detail);
      setDeleting(false);
    }
  }, [currentAgent, logout, resetAgents, router]);

  if (isLoading && agents.length === 0) {
    return (
      <div className="flex items-center justify-center h-full">
        <span className="spinner text-[var(--gold-500)]" />
      </div>
    );
  }

  if (!currentAgent) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-4 px-6 text-center">
        <div className="h-14 w-14 rounded-2xl bg-[var(--gold-500)]/10 flex items-center justify-center">
          <Shield className="h-7 w-7 text-[var(--gold-500)]" />
        </div>
        <div>
          <h2 className="text-lg font-bold text-[var(--foreground)] mb-1">
            No agent yet
          </h2>
          <p className="text-sm text-[var(--color-muted)]">
            Claim an agent to configure settings.
          </p>
        </div>
        <button
          onClick={() => router.replace("/claim")}
          className="px-5 py-2.5 rounded-xl bg-[var(--gold-500)] text-[#07111c] text-sm font-semibold hover:bg-[var(--gold-600)] transition-colors"
        >
          Claim your agent
        </button>
      </div>
    );
  }

  // ── General tab content (passed into AgentConfigurator) ───────────────────

  const generalTabContent = (
    <div className="space-y-4">
      {/* Success */}
      {saved && (
        <div className="p-3 rounded-xl bg-green-500/10 border border-green-500/20 text-green-400 text-sm flex items-center gap-2 card-enter">
          <CheckCircle className="h-4 w-4 flex-shrink-0" />
          Settings saved successfully
        </div>
      )}

      {/* Error */}
      {error && (
        <div className="p-3 rounded-xl bg-red-500/10 border border-red-500/20 text-red-400 text-sm flex items-center gap-2">
          <AlertTriangle className="h-4 w-4 flex-shrink-0" />
          {error}
          <button
            onClick={() => setError(null)}
            className="ml-auto text-xs underline"
          >
            dismiss
          </button>
        </div>
      )}

      {/* ── Account (read-only) ──────────────────────────────────────────── */}
      <section className="glass-panel p-5">
        <h2 className="text-sm font-heading font-semibold text-[var(--foreground)] mb-4 flex items-center gap-2">
          <Shield className="h-4 w-4 text-[var(--gold-500)]" />
          Account
        </h2>
        <div className="space-y-3">
          <div>
            <label className="block text-xs font-medium text-[var(--color-muted)] mb-1.5">
              Email
            </label>
            <Input value={user?.email ?? ""} disabled />
          </div>
          <div>
            <label className="block text-xs font-medium text-[var(--color-muted)] mb-1.5">
              @Handle
            </label>
            <Input value={`@${currentAgent.handle}`} disabled />
            <p className="text-xs text-[var(--color-muted)] mt-1">
              Handles cannot be changed after creation
            </p>
          </div>
          <div>
            <label className="block text-xs font-medium text-[var(--color-muted)] mb-1.5">
              Agent Type
            </label>
            <Input
              value={currentAgent.agent_type === "personal" ? "Personal" : "Business"}
              disabled
            />
          </div>
        </div>
      </section>

      {/* ── Agent Profile ────────────────────────────────────────────────── */}
      <section className="glass-panel p-5">
        <h2 className="text-sm font-heading font-semibold text-[var(--foreground)] mb-4">
          Agent Profile
        </h2>
        <div className="space-y-3">
          <div>
            <label className="block text-xs font-medium text-[var(--color-muted)] mb-1.5">
              Name
            </label>
            <Input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="My Agent"
              maxLength={100}
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-[var(--color-muted)] mb-1.5">
              Industry
            </label>
            <Input
              value={industry}
              onChange={(e) => setIndustry(e.target.value)}
              placeholder="e.g. Restaurant, Salon, Fitness"
              maxLength={100}
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-[var(--color-muted)] mb-1.5">
              Description
              <span className="text-[var(--color-muted)] font-normal ml-1">
                (shown on public profile)
              </span>
            </label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Tell visitors what your agent does and how it can help them..."
              rows={3}
              maxLength={500}
              className="w-full rounded-2xl px-4 py-2.5 text-[15px] bg-white/5 border border-[var(--stroke2)] text-[var(--foreground)] placeholder:text-[var(--color-muted)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--gold-500)] resize-none leading-relaxed"
            />
            <p className="text-xs text-[var(--color-muted)] mt-1">
              {description.length}/500
            </p>
          </div>
          <div>
            <label className="block text-xs font-medium text-[var(--color-muted)] mb-1.5">
              Greeting Message
              <span className="text-[var(--color-muted)] font-normal ml-1">
                (first thing your agent says)
              </span>
            </label>
            <textarea
              value={greeting}
              onChange={(e) => setGreeting(e.target.value)}
              placeholder="Hello! I'm your AI assistant. How can I help you today?"
              rows={2}
              maxLength={280}
              className="w-full rounded-2xl px-4 py-2.5 text-[15px] bg-white/5 border border-[var(--stroke2)] text-[var(--foreground)] placeholder:text-[var(--color-muted)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--gold-500)] resize-none leading-relaxed"
            />
            <p className="text-xs text-[var(--color-muted)] mt-1">
              {greeting.length}/280
            </p>
          </div>

          {/* Status toggle */}
          <div className="flex items-center justify-between py-2">
            <div>
              <p className="text-sm text-[var(--foreground)]">Agent Active</p>
              <p className="text-xs text-[var(--color-muted)]">
                When disabled, your agent won&apos;t respond to messages
              </p>
            </div>
            <button
              onClick={() => setIsActive(!isActive)}
              className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
                isActive ? "bg-[var(--gold-500)]" : "bg-white/10"
              }`}
              role="switch"
              aria-checked={isActive}
              aria-label="Toggle agent active status"
            >
              <span
                className={`inline-block h-4 w-4 rounded-full bg-white transition-transform ${
                  isActive ? "translate-x-6" : "translate-x-1"
                }`}
              />
            </button>
          </div>
        </div>

        <Button
          variant="gold"
          onClick={handleSave}
          isLoading={saving}
          disabled={!name.trim()}
          className="w-full mt-4"
        >
          <Save className="h-4 w-4" />
          Save Changes
        </Button>
      </section>

      {/* ── Security ─────────────────────────────────────────────────────── */}
      <PasskeyManager />

      {/* ── Two-Factor Authentication ─────────────────────────────────────── */}
      <MfaSetupPanel />

      {/* ── Danger Zone ──────────────────────────────────────────────────── */}
      <section className="glass-panel p-5 border-red-500/20">
        <h2 className="text-sm font-heading font-semibold text-red-400 mb-2 flex items-center gap-2">
          <AlertTriangle className="h-4 w-4" />
          Danger Zone
        </h2>
        <p className="text-xs text-[var(--color-muted)] mb-4">
          Permanently delete this agent and all associated data. This action
          cannot be undone.
        </p>

        {deleteConfirm ? (
          <div className="flex items-center gap-2">
            <Button
              variant="destructive"
              size="sm"
              onClick={handleDelete}
              isLoading={deleting}
            >
              <Trash2 className="h-3.5 w-3.5" />
              Confirm Delete
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setDeleteConfirm(false)}
            >
              Cancel
            </Button>
          </div>
        ) : (
          <Button
            variant="outline"
            size="sm"
            onClick={() => setDeleteConfirm(true)}
            className="text-red-400 border-red-500/20 hover:bg-red-500/10"
          >
            <Trash2 className="h-3.5 w-3.5" />
            Delete Agent
          </Button>
        )}
      </section>
    </div>
  );

  return (
    <div className="h-full overflow-y-auto scrollbar-thin">
      <div className="max-w-2xl mx-auto px-4 py-6 pb-6">
        <PageHeader title="Settings" />
        <h1 className="text-xl font-heading font-bold text-[var(--foreground)] mb-1">
          Settings
        </h1>
        <p className="text-[15px] text-[var(--color-muted)] mb-6">
          Manage your agent configuration
        </p>

        <AgentConfigurator
          agent={currentAgent}
          generalTabContent={generalTabContent}
        />
      </div>
    </div>
  );
}
