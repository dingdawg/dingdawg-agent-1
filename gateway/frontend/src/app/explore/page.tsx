"use client";

/**
 * Explore page — browse business agents by category/industry.
 *
 * - Public page (no auth required)
 * - Category filter chips
 * - Agent cards with name, @handle, industry, description
 * - Click card → /agents/[handle]
 * - Fetches real data from GET /api/v1/public/agents
 */

import { useState, useMemo, useEffect, useCallback } from "react";
import Link from "next/link";
import { Search, Store, Zap, RefreshCw, ChevronLeft } from "lucide-react";
import { useAuthStore } from "@/store/authStore";
import { AppShell } from "@/components/layout/AppShell";
import { PageHeader } from "@/components/layout/PageHeader";
import { Input } from "@/components/ui/input";
import { get } from "@/services/api/client";

// ─── Types ────────────────────────────────────────────────────────────────────

interface PublicAgent {
  handle: string;
  name: string;
  industry: string;
  description: string;
  agent_type: string;
  avatar_url: string;
  primary_color: string;
  greeting: string;
  created_at: string;
  // derived client-side for filter chip matching
  category: string;
}

interface ListAgentsResponse {
  agents: Omit<PublicAgent, "category">[];
  total: number;
  limit: number;
  offset: number;
}

// ─── Category config ──────────────────────────────────────────────────────────

const CATEGORIES = [
  { label: "All", value: "all" },
  { label: "Restaurant", value: "restaurant" },
  { label: "Salon", value: "salon" },
  { label: "Tutor", value: "tutor" },
  { label: "Home Service", value: "home_service" },
  { label: "Fitness", value: "fitness" },
] as const;

type Category = (typeof CATEGORIES)[number]["value"];

// Derive a category slug from the industry string returned by the API.
// Keeps the filter chips working without backend changes.
function industryToCategory(industry: string): string {
  const lower = industry.toLowerCase();
  if (lower.includes("restaurant") || lower.includes("food") || lower.includes("cafe") || lower.includes("bar") || lower.includes("pizza") || lower.includes("taco") || lower.includes("sushi") || lower.includes("burger")) return "restaurant";
  if (lower.includes("salon") || lower.includes("beauty") || lower.includes("nail") || lower.includes("hair") || lower.includes("spa") || lower.includes("lash") || lower.includes("wax")) return "salon";
  if (lower.includes("tutor") || lower.includes("school") || lower.includes("education") || lower.includes("math") || lower.includes("teacher")) return "tutor";
  if (lower.includes("home") || lower.includes("plumb") || lower.includes("electric") || lower.includes("paint") || lower.includes("handyman") || lower.includes("repair")) return "home_service";
  if (lower.includes("fitness") || lower.includes("gym") || lower.includes("coach") || lower.includes("personal train") || lower.includes("yoga") || lower.includes("sport")) return "fitness";
  return "other";
}

// ─── Loading skeleton ─────────────────────────────────────────────────────────

function AgentCardSkeleton() {
  return (
    <div className="glass-panel p-4 h-full animate-pulse">
      <div className="flex items-start justify-between gap-2 mb-3">
        <div className="h-10 w-10 rounded-xl bg-white/10" />
        <div className="h-5 w-20 rounded-full bg-white/10" />
      </div>
      <div className="h-4 w-3/4 rounded bg-white/10 mb-2" />
      <div className="h-3 w-1/3 rounded bg-white/10 mb-2" />
      <div className="h-3 w-full rounded bg-white/10 mb-1" />
      <div className="h-3 w-5/6 rounded bg-white/10 mb-1" />
      <div className="h-3 w-2/3 rounded bg-white/10 mt-3" />
    </div>
  );
}

// ─── Agent card ───────────────────────────────────────────────────────────────

function AgentCard({ agent }: { agent: PublicAgent }) {
  const accentColor = agent.primary_color || "var(--gold-500)";

  return (
    <Link href={`/agents/${agent.handle}`} className="block group min-w-0">
      <div className="glass-panel p-4 h-full transition-all duration-150 group-hover:border-white/20 overflow-hidden min-w-0">
        {/* Avatar + category badge */}
        <div className="flex items-start justify-between gap-2 mb-3">
          {agent.avatar_url ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={agent.avatar_url}
              alt={agent.name}
              className="h-10 w-10 rounded-xl object-cover flex-shrink-0"
            />
          ) : (
            <div
              className="h-10 w-10 rounded-xl flex items-center justify-center flex-shrink-0"
              style={{ backgroundColor: `${accentColor}1A` }}
            >
              <Store className="h-5 w-5" style={{ color: accentColor }} />
            </div>
          )}
          <span className="text-xs px-2 py-0.5 rounded-full bg-white/8 border border-[var(--stroke)] text-[var(--color-muted)] capitalize">
            {agent.category.replace(/_/g, " ")}
          </span>
        </div>

        {/* Name + handle */}
        <h3 className="font-semibold text-[var(--foreground)] text-[15px] leading-tight mb-0.5 truncate">
          {agent.name}
        </h3>
        <p className="text-xs font-medium mb-1 truncate" style={{ color: accentColor }}>
          @{agent.handle}
        </p>
        <p className="text-xs text-[var(--color-muted)] mb-3 line-clamp-2 leading-relaxed">
          {agent.industry}
        </p>

        {/* Description or greeting fallback */}
        <p className="text-xs text-[var(--foreground)]/70 line-clamp-3 leading-relaxed">
          {agent.description || agent.greeting}
        </p>

        {/* CTA hint */}
        <p className="text-xs mt-3 group-hover:underline" style={{ color: accentColor }}>
          View agent →
        </p>
      </div>
    </Link>
  );
}

// ─── Main page ────────────────────────────────────────────────────────────────

export default function ExplorePage() {
  const { isAuthenticated } = useAuthStore();

  if (isAuthenticated) {
    return (
      <AppShell>
        <ExploreContent />
      </AppShell>
    );
  }

  return <ExploreContent />;
}

function ExploreContent() {
  const { isAuthenticated } = useAuthStore();
  const [agents, setAgents] = useState<PublicAgent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [activeCategory, setActiveCategory] = useState<Category>("all");

  const fetchAgents = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await get<ListAgentsResponse>("/api/v1/public/agents?limit=100");
      const withCategory: PublicAgent[] = (data.agents ?? []).map((a) => ({
        ...a,
        category: industryToCategory(a.industry || ""),
      }));
      setAgents(withCategory);
    } catch (err: unknown) {
      const message =
        err instanceof Error ? err.message : "Failed to load agents";
      setError(message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchAgents();
  }, [fetchAgents]);

  const filteredAgents = useMemo(() => {
    let result = agents;

    if (activeCategory !== "all") {
      result = result.filter((a) => a.category === activeCategory);
    }

    if (query.trim()) {
      const q = query.toLowerCase();
      result = result.filter(
        (a) =>
          a.name.toLowerCase().includes(q) ||
          a.handle.toLowerCase().includes(q) ||
          a.industry.toLowerCase().includes(q) ||
          a.description.toLowerCase().includes(q)
      );
    }

    return result;
  }, [agents, query, activeCategory]);

  return (
    <div className="h-full overflow-y-auto overflow-x-hidden scrollbar-thin px-4 pb-6 max-w-3xl mx-auto w-full min-w-0" style={{ paddingTop: "calc(env(safe-area-inset-top, 0px) + 24px)" }}>
      {/* Back navigation */}
      {isAuthenticated ? (
        <PageHeader title="Explore" />
      ) : (
        <Link href="/" className="flex items-center gap-1 text-sm text-[var(--color-muted)] hover:text-[var(--foreground)] mb-4"><ChevronLeft className="h-4 w-4" />Home</Link>
      )}

      {/* Header */}
      <div className="mb-6">
        <div className="flex items-center gap-2 mb-1">
          <Zap className="h-5 w-5 text-[var(--gold-500)]" />
          <h1 className="text-xl font-bold text-[var(--foreground)]">
            Explore Agents
          </h1>
        </div>
        <p className="text-[15px] text-[var(--color-muted)]">
          Discover AI agents for local businesses
        </p>
      </div>

      {/* Search */}
      <div className="relative mb-4">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-[var(--color-muted)]" />
        <Input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search by name, industry, or @handle…"
          className="pl-10"
        />
      </div>

      {/* Category chips */}
      <div className="flex gap-2 mb-6 overflow-x-auto pb-1 scrollbar-thin">
        {CATEGORIES.map((cat) => (
          <button
            key={cat.value}
            onClick={() => setActiveCategory(cat.value)}
            className={`flex-shrink-0 px-3 py-1.5 rounded-full text-xs font-medium transition-all duration-150 border ${
              activeCategory === cat.value
                ? "bg-[var(--gold-500)] text-[#07111c] border-[var(--gold-500)]"
                : "bg-white/5 text-[var(--color-muted)] border-[var(--stroke)] hover:border-white/20"
            }`}
          >
            {cat.label}
          </button>
        ))}
      </div>

      {/* Loading state — 3 skeleton cards */}
      {loading && (
        <div className="grid grid-cols-1 gap-3 min-w-0">
          <AgentCardSkeleton />
          <AgentCardSkeleton />
          <AgentCardSkeleton />
        </div>
      )}

      {/* Error state */}
      {!loading && error && (
        <div className="glass-panel p-8 text-center">
          <p className="text-sm text-red-400 mb-3">{error}</p>
          <button
            onClick={fetchAgents}
            className="inline-flex items-center gap-1.5 text-xs text-[var(--gold-500)] hover:underline"
          >
            <RefreshCw className="h-3.5 w-3.5" />
            Try again
          </button>
        </div>
      )}

      {/* Results */}
      {!loading && !error && (
        <>
          {/* Results count */}
          <p className="text-xs text-[var(--color-muted)] mb-3">
            {filteredAgents.length} agent{filteredAgents.length !== 1 ? "s" : ""}
            {activeCategory !== "all" && ` in ${activeCategory.replace(/_/g, " ")}`}
            {query && ` matching "${query}"`}
          </p>

          {/* Agent grid or empty states */}
          {filteredAgents.length === 0 && agents.length === 0 ? (
            // No agents in DB at all
            <div className="glass-panel p-10 text-center">
              <Zap className="h-10 w-10 text-[var(--gold-500)] mx-auto mb-3 opacity-60" />
              <p className="text-sm font-medium text-[var(--foreground)] mb-1">
                No agents yet
              </p>
              <p className="text-xs text-[var(--color-muted)] mb-4">
                Be the first to claim yours!
              </p>
              <Link
                href="/claim"
                className="text-xs text-[var(--gold-500)] hover:underline font-medium"
              >
                Claim your agent at /claim →
              </Link>
            </div>
          ) : filteredAgents.length === 0 ? (
            // Agents exist but none match filters
            <div className="glass-panel p-8 text-center">
              <Search className="h-10 w-10 text-[var(--color-muted)] mx-auto mb-3" />
              <p className="text-sm text-[var(--color-muted)]">No agents found</p>
              <button
                onClick={() => {
                  setQuery("");
                  setActiveCategory("all");
                }}
                className="text-xs text-[var(--gold-500)] hover:underline mt-2 inline-block"
              >
                Clear filters
              </button>
            </div>
          ) : (
            <div className="grid grid-cols-1 gap-3 min-w-0">
              {filteredAgents.map((agent) => (
                <AgentCard key={agent.handle} agent={agent} />
              ))}
            </div>
          )}
        </>
      )}

      {/* Claim CTA */}
      {!loading && (
        <p className="text-center text-xs text-[var(--color-muted)] mt-6">
          Want your own agent?{" "}
          <Link href="/claim" className="text-[var(--gold-500)] hover:underline">
            Claim yours at /claim
          </Link>
        </p>
      )}
    </div>
  );
}
