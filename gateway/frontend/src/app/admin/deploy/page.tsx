"use client";

/**
 * Admin Deploy page — Agent Deployment Center.
 *
 * - Deploy Marketing Agent section with status indicator
 * - Template Gallery grid with sector colors/icons
 * - Quick Deploy section (select template + handle input)
 * - Deployment History table (timestamp, handle, template, status)
 * - Mobile responsive with 48px touch targets
 * - No HTML entities in JSX
 */

import { useEffect, useState, useCallback } from "react";
import {
  Rocket,
  RefreshCw,
  AlertCircle,
  CheckCircle2,
  Clock,
  ChevronDown,
  Megaphone,
  Zap,
  ShoppingBag,
  Calendar,
  BarChart3,
  MessageSquare,
  Users,
  Globe,
} from "lucide-react";
import { cn } from "@/lib/utils";
import {
  getAdminTemplates,
  getMarketingAgentStatus,
  deployMarketingAgent,
  deployAgent,
  getDeploymentHistory,
  type AdminTemplate,
  type MarketingAgentStatus,
  type DeploymentRecord,
  type DeploymentStatus,
} from "@/services/api/adminService";

// ─── Helpers ──────────────────────────────────────────────────────────────────

function formatTimestamp(iso: string): string {
  try {
    return new Date(iso).toLocaleDateString("en-US", {
      month: "short",
      day: "numeric",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

// ─── Sector icon map ──────────────────────────────────────────────────────────

const SECTOR_ICONS: Record<string, React.ComponentType<{ className?: string }>> = {
  marketing: Megaphone,
  ecommerce: ShoppingBag,
  scheduling: Calendar,
  analytics: BarChart3,
  support: MessageSquare,
  hr: Users,
  sales: BarChart3,
  social: Globe,
  default: Zap,
};

const SECTOR_COLORS: Record<string, string> = {
  marketing: "text-pink-400 bg-pink-500/10 border-pink-500/20",
  ecommerce: "text-green-400 bg-green-500/10 border-green-500/20",
  scheduling: "text-blue-400 bg-blue-500/10 border-blue-500/20",
  analytics: "text-purple-400 bg-purple-500/10 border-purple-500/20",
  support: "text-orange-400 bg-orange-500/10 border-orange-500/20",
  hr: "text-teal-400 bg-teal-500/10 border-teal-500/20",
  sales: "text-yellow-400 bg-yellow-500/10 border-yellow-500/20",
  social: "text-cyan-400 bg-cyan-500/10 border-cyan-500/20",
  default: "text-[var(--gold-400)] bg-[var(--gold-400)]/10 border-[var(--gold-400)]/20",
};

function getSectorIcon(sector: string): React.ComponentType<{ className?: string }> {
  const key = sector.toLowerCase();
  return SECTOR_ICONS[key] ?? SECTOR_ICONS.default;
}

function getSectorColor(sector: string): string {
  const key = sector.toLowerCase();
  return SECTOR_COLORS[key] ?? SECTOR_COLORS.default;
}

// ─── Status badge ─────────────────────────────────────────────────────────────

function StatusBadge({ status }: { status: DeploymentStatus }) {
  const config = {
    success: { label: "Success", className: "text-green-400 bg-green-500/10 border-green-500/20" },
    pending: { label: "Pending", className: "text-yellow-400 bg-yellow-500/10 border-yellow-500/20" },
    failed: { label: "Failed", className: "text-red-400 bg-red-500/10 border-red-500/20" },
  };
  const cfg = config[status] ?? config.pending;
  return (
    <span className={cn("px-2 py-0.5 rounded-full text-xs font-medium border", cfg.className)}>
      {cfg.label}
    </span>
  );
}

// ─── Marketing Agent Card ─────────────────────────────────────────────────────

function MarketingAgentCard() {
  const [status, setStatus] = useState<MarketingAgentStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [deploying, setDeploying] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadStatus = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const s = await getMarketingAgentStatus();
      setStatus(s);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to load status";
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadStatus();
  }, [loadStatus]);

  const handleDeploy = async () => {
    setDeploying(true);
    setError(null);
    try {
      const s = await deployMarketingAgent();
      setStatus(s);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Deploy failed";
      setError(msg);
    } finally {
      setDeploying(false);
    }
  };

  return (
    <div className="bg-[#0d1926] border border-[#1a2a3d] rounded-xl p-5">
      <div className="flex items-start justify-between gap-3 mb-3">
        <div className="flex items-center gap-3">
          <div className="h-10 w-10 rounded-xl bg-pink-500/10 border border-pink-500/20 flex items-center justify-center flex-shrink-0">
            <Megaphone className="h-5 w-5 text-pink-400" />
          </div>
          <div>
            <h3 className="text-sm font-semibold text-white">
              Marketing Agent
            </h3>
            <p className="text-xs text-gray-400">@dingdawg-marketing</p>
          </div>
        </div>
        {loading ? (
          <div className="h-5 w-16 rounded-full bg-white/5 animate-pulse" />
        ) : status?.deployed ? (
          <div className="flex items-center gap-1.5">
            <span className="h-2 w-2 rounded-full bg-green-400" />
            <span className="text-xs text-green-400 font-medium">Deployed</span>
          </div>
        ) : (
          <div className="flex items-center gap-1.5">
            <span className="h-2 w-2 rounded-full bg-gray-500" />
            <span className="text-xs text-gray-400 font-medium">Not deployed</span>
          </div>
        )}
      </div>

      <p className="text-xs text-gray-400 mb-4 leading-relaxed">
        The DingDawg marketing agent autonomously runs email campaigns, social
        posts, and lead follow-ups. Deploy it to start generating inbound leads
        and re-engaging inactive users.
      </p>

      {error && (
        <div className="flex items-center gap-2 text-xs text-red-400 bg-red-500/10 border border-red-500/20 rounded-lg px-3 py-2 mb-3">
          <AlertCircle className="h-3.5 w-3.5 flex-shrink-0" />
          {error}
        </div>
      )}

      {status?.deployed && status.deployed_at && (
        <p className="text-xs text-gray-500 mb-3">
          Deployed {formatTimestamp(status.deployed_at)}
        </p>
      )}

      <button
        onClick={handleDeploy}
        disabled={deploying || loading}
        className={cn(
          "w-full flex items-center justify-center gap-2 px-4 py-3 rounded-xl text-sm font-semibold transition-all min-h-[48px]",
          status?.deployed
            ? "bg-white/5 border border-[#1a2a3d] text-gray-300 hover:bg-white/10"
            : "bg-[var(--gold-400)] text-[#07111c] hover:opacity-90"
        )}
      >
        <Rocket className="h-4 w-4" />
        {deploying
          ? "Deploying..."
          : status?.deployed
          ? "Redeploy @dingdawg-marketing"
          : "Deploy @dingdawg-marketing"}
      </button>
    </div>
  );
}

// ─── Template Card ────────────────────────────────────────────────────────────

function TemplateCard({ template }: { template: AdminTemplate }) {
  const Icon = getSectorIcon(template.sector);
  const colorClass = getSectorColor(template.sector);

  return (
    <div className="bg-[#0d1926] border border-[#1a2a3d] rounded-xl p-4 flex flex-col gap-3">
      <div className="flex items-center gap-3">
        <div className={cn("h-9 w-9 rounded-lg border flex items-center justify-center flex-shrink-0", colorClass)}>
          <Icon className="h-4.5 w-4.5" />
        </div>
        <div className="flex-1 min-w-0">
          <p className="text-sm font-semibold text-white truncate">{template.name}</p>
          <p className="text-xs text-gray-400 capitalize">{template.sector}</p>
        </div>
      </div>
      <p className="text-xs text-gray-400 leading-relaxed line-clamp-2">
        {template.description}
      </p>
      <div className="flex items-center justify-between">
        <span className="text-xs text-gray-500">
          {template.agent_count} agent{template.agent_count !== 1 ? "s" : ""} using this
        </span>
      </div>
    </div>
  );
}

// ─── Quick Deploy ─────────────────────────────────────────────────────────────

function QuickDeploy({
  templates,
  onDeployed,
}: {
  templates: AdminTemplate[];
  onDeployed: () => void;
}) {
  const [selectedId, setSelectedId] = useState("");
  const [handle, setHandle] = useState("");
  const [deploying, setDeploying] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const handleDeploy = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedId || !handle.trim()) return;
    setDeploying(true);
    setError(null);
    setSuccess(null);
    try {
      await deployAgent({ template_id: selectedId, handle: handle.trim() });
      setHandle("");
      setSelectedId("");
      setSuccess(`@${handle.trim()} deployed successfully`);
      setTimeout(() => setSuccess(null), 5000);
      onDeployed();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Deploy failed";
      setError(msg);
    } finally {
      setDeploying(false);
    }
  };

  return (
    <form
      onSubmit={handleDeploy}
      className="bg-[#0d1926] border border-[#1a2a3d] rounded-xl p-4 flex flex-col gap-3"
    >
      <h3 className="text-sm font-semibold text-white">Quick Deploy</h3>

      {error && (
        <div className="flex items-center gap-2 text-xs text-red-400 bg-red-500/10 border border-red-500/20 rounded-lg px-3 py-2">
          <AlertCircle className="h-3.5 w-3.5 flex-shrink-0" />
          {error}
        </div>
      )}
      {success && (
        <div className="flex items-center gap-2 text-xs text-green-400 bg-green-500/10 border border-green-500/20 rounded-lg px-3 py-2">
          <CheckCircle2 className="h-3.5 w-3.5 flex-shrink-0" />
          {success}
        </div>
      )}

      <div className="relative">
        <select
          value={selectedId}
          onChange={(e) => setSelectedId(e.target.value)}
          className="w-full appearance-none px-3 py-2.5 pr-8 rounded-lg bg-[#0d1926] border border-[#1a2a3d] text-sm text-white focus:outline-none focus:border-[var(--gold-400)]/50 min-h-[44px]"
          required
        >
          <option value="">Select template...</option>
          {templates.map((t) => (
            <option key={t.id} value={t.id}>
              {t.name} ({t.sector})
            </option>
          ))}
        </select>
        <ChevronDown className="absolute right-2.5 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-500 pointer-events-none" />
      </div>

      <div className="flex items-center gap-2">
        <span className="text-sm text-gray-400 flex-shrink-0">@</span>
        <input
          type="text"
          value={handle}
          onChange={(e) =>
            setHandle(e.target.value.toLowerCase().replace(/[^a-z0-9-_]/g, ""))
          }
          placeholder="agent-handle"
          className="flex-1 px-3 py-2.5 rounded-lg bg-white/5 border border-[#1a2a3d] text-sm text-white placeholder-gray-500 focus:outline-none focus:border-[var(--gold-400)]/50 min-h-[44px]"
          required
          minLength={2}
          maxLength={32}
        />
      </div>

      <button
        type="submit"
        disabled={deploying || !selectedId || !handle.trim()}
        className="flex items-center justify-center gap-2 px-4 py-3 rounded-xl bg-[var(--gold-400)] text-[#07111c] text-sm font-semibold hover:opacity-90 transition-opacity disabled:opacity-40 min-h-[48px]"
      >
        <Rocket className="h-4 w-4" />
        {deploying ? "Deploying..." : "Deploy Agent"}
      </button>
    </form>
  );
}

// ─── Deployment History ───────────────────────────────────────────────────────

function DeploymentHistory({
  records,
  loading,
}: {
  records: DeploymentRecord[];
  loading: boolean;
}) {
  if (loading && records.length === 0) {
    return (
      <div className="flex flex-col gap-2">
        {[1, 2, 3].map((i) => (
          <div
            key={i}
            className="h-12 rounded-lg bg-white/3 animate-pulse border border-[#1a2a3d]"
          />
        ))}
      </div>
    );
  }

  if (records.length === 0) {
    return (
      <p className="text-sm text-gray-500 text-center py-6">
        No deployments yet
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-0 divide-y divide-[#1a2a3d]">
      {records.map((rec) => (
        <div
          key={rec.id}
          className="flex items-center gap-3 py-3 first:pt-0 last:pb-0"
        >
          <div className="flex-1 min-w-0">
            <p className="text-sm font-medium text-white">@{rec.handle}</p>
            <p className="text-xs text-gray-400">{rec.template_name}</p>
          </div>
          <div className="flex flex-col items-end gap-1 flex-shrink-0">
            <StatusBadge status={rec.status} />
            <div className="flex items-center gap-1 text-xs text-gray-500">
              <Clock className="h-3 w-3" />
              {formatTimestamp(rec.deployed_at)}
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

// ─── Main page ────────────────────────────────────────────────────────────────

export default function DeployPage() {
  return <DeployContent />;
}

function DeployContent() {
  const [templates, setTemplates] = useState<AdminTemplate[]>([]);
  const [history, setHistory] = useState<DeploymentRecord[]>([]);
  const [templatesLoading, setTemplatesLoading] = useState(false);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadTemplates = useCallback(async () => {
    setTemplatesLoading(true);
    try {
      const data = await getAdminTemplates();
      setTemplates(data);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to load templates";
      setError(msg);
    } finally {
      setTemplatesLoading(false);
    }
  }, []);

  const loadHistory = useCallback(async () => {
    setHistoryLoading(true);
    try {
      const data = await getDeploymentHistory();
      setHistory(data);
    } catch {
      // History is non-critical — fail silently
    } finally {
      setHistoryLoading(false);
    }
  }, []);

  useEffect(() => {
    loadTemplates();
    loadHistory();
  }, [loadTemplates, loadHistory]);

  const handleDeployed = useCallback(() => {
    loadHistory();
  }, [loadHistory]);

  return (
    <div className="h-full overflow-y-auto scrollbar-thin px-4 pt-6 pb-20 lg:pb-8 max-w-3xl mx-auto">
      {/* Page header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-xl font-bold text-white">Deploy</h1>
          <p className="text-xs text-gray-400 mt-0.5">
            Agent Deployment Center
          </p>
        </div>
        <button
          onClick={() => { loadTemplates(); loadHistory(); }}
          disabled={templatesLoading}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs text-gray-400 hover:text-white hover:bg-white/5 transition-colors disabled:opacity-50 min-h-[44px]"
        >
          <RefreshCw
            className={cn("h-3.5 w-3.5", templatesLoading && "animate-spin")}
          />
          Refresh
        </button>
      </div>

      {error && (
        <div className="mb-5 p-3 rounded-lg bg-red-500/10 border border-red-500/20 text-red-400 text-sm flex items-center gap-2">
          <AlertCircle className="h-4 w-4 flex-shrink-0" />
          {error}
          <button
            onClick={() => { loadTemplates(); loadHistory(); }}
            className="ml-auto text-xs underline"
          >
            retry
          </button>
        </div>
      )}

      {/* Marketing Agent */}
      <div className="mb-6">
        <h2 className="text-sm font-semibold text-white mb-3 flex items-center gap-2">
          <Rocket className="h-4 w-4 text-[var(--gold-400)]" />
          Deploy Marketing Agent
        </h2>
        <MarketingAgentCard />
      </div>

      {/* Template Gallery */}
      <div className="mb-6">
        <h2 className="text-sm font-semibold text-white mb-3 flex items-center gap-2">
          <Zap className="h-4 w-4 text-[var(--gold-400)]" />
          Template Gallery
        </h2>
        {templatesLoading && templates.length === 0 ? (
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            {[1, 2, 3, 4].map((i) => (
              <div
                key={i}
                className="h-32 rounded-xl bg-[#0d1926] border border-[#1a2a3d] animate-pulse"
              />
            ))}
          </div>
        ) : templates.length === 0 ? (
          <p className="text-sm text-gray-500 text-center py-6 bg-[#0d1926] border border-[#1a2a3d] rounded-xl">
            No templates available
          </p>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            {templates.map((t) => (
              <TemplateCard key={t.id} template={t} />
            ))}
          </div>
        )}
      </div>

      {/* Quick Deploy + History side by side on desktop */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <QuickDeploy templates={templates} onDeployed={handleDeployed} />

        <div className="bg-[#0d1926] border border-[#1a2a3d] rounded-xl p-4">
          <h3 className="text-sm font-semibold text-white mb-4">
            Deployment History
          </h3>
          <DeploymentHistory records={history} loading={historyLoading} />
        </div>
      </div>
    </div>
  );
}
