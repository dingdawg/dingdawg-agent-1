"use client";

/**
 * Public agent profile page — /agents/[handle]
 *
 * - Public page (no auth required)
 * - Fetches real agent data from GET /api/v1/public/agents/{handle}
 * - Shows name, @handle, industry, description, greeting, capabilities
 * - Embed code snippet (copyable)
 * - QR code display
 * - "Chat with agent" CTA
 * - Loading / error / 404 states
 * - Mobile responsive
 */

import { use, useState, useEffect, useCallback } from "react";
import Link from "next/link";
import {
  Store,
  Zap,
  CheckCircle,
  MessageCircle,
  ArrowLeft,
  User,
  Code2,
  QrCode,
  Copy,
  Check,
  RefreshCw,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { get } from "@/services/api/client";

// ─── Types ────────────────────────────────────────────────────────────────────

interface PublicAgentProfile {
  handle: string;
  name: string;
  industry: string;
  description: string;
  agent_type: string;
  avatar_url: string;
  primary_color: string;
  greeting: string;
  created_at: string;
  capabilities: string[];
  card_url: string;
  chat_url: string;
  qr_url: string;
  widget_embed_code: string;
}

// ─── Props ────────────────────────────────────────────────────────────────────

interface PageProps {
  params: Promise<{ handle: string }>;
}

// ─── Copy button ──────────────────────────────────────────────────────────────

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);

  async function handleCopy() {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // clipboard API may be unavailable in some contexts
    }
  }

  return (
    <button
      onClick={handleCopy}
      className="inline-flex items-center gap-1 text-xs text-[var(--color-muted)] hover:text-[var(--foreground)] transition-colors"
      title="Copy to clipboard"
    >
      {copied ? (
        <>
          <Check className="h-3.5 w-3.5 text-green-400" />
          <span className="text-green-400">Copied!</span>
        </>
      ) : (
        <>
          <Copy className="h-3.5 w-3.5" />
          Copy
        </>
      )}
    </button>
  );
}

// ─── Loading skeleton ─────────────────────────────────────────────────────────

function ProfileSkeleton() {
  return (
    <div className="min-h-screen px-4 pt-6 pb-24 max-w-lg mx-auto animate-pulse">
      <div className="h-4 w-28 rounded bg-white/10 mb-6" />
      {/* Card skeleton */}
      <div className="glass-panel p-5 mb-4">
        <div className="flex items-start gap-4">
          <div className="h-16 w-16 rounded-2xl bg-white/10 flex-shrink-0" />
          <div className="flex-1 space-y-2">
            <div className="h-5 w-2/3 rounded bg-white/10" />
            <div className="h-3 w-1/3 rounded bg-white/10" />
            <div className="h-3 w-1/2 rounded bg-white/10" />
          </div>
        </div>
        <div className="mt-4 space-y-2">
          <div className="h-3 w-full rounded bg-white/10" />
          <div className="h-3 w-5/6 rounded bg-white/10" />
          <div className="h-3 w-4/5 rounded bg-white/10" />
        </div>
      </div>
      {/* Capabilities skeleton */}
      <div className="glass-panel p-4 mb-4 space-y-2">
        <div className="h-4 w-40 rounded bg-white/10 mb-3" />
        {[1, 2, 3].map((i) => (
          <div key={i} className="h-3 w-full rounded bg-white/10" />
        ))}
      </div>
    </div>
  );
}

// ─── Profile content ──────────────────────────────────────────────────────────

function ProfileContent({ profile }: { profile: PublicAgentProfile }) {
  const accentColor = profile.primary_color || "#7C3AED";
  const isBusinessAgent = profile.agent_type === "business";
  const [showDeveloper, setShowDeveloper] = useState(false);

  return (
    <div className="min-h-screen flex flex-col items-center justify-center px-4 py-12">
      <div className="w-full max-w-md">
        {/* Back link */}
        <Link
          href="/explore"
          className="inline-flex items-center gap-1 text-sm text-[var(--color-muted)] hover:text-[var(--foreground)] mb-8 transition-colors"
        >
          <ArrowLeft className="h-4 w-4" />
          Browse agents
        </Link>

        {/* Agent card — centered, clean, one focus */}
        <div className="glass-panel p-6 text-center mb-6">
          {/* Avatar */}
          <div className="flex justify-center mb-4">
            {profile.avatar_url ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={profile.avatar_url}
                alt={profile.name}
                className="h-20 w-20 rounded-2xl object-cover"
              />
            ) : (
              <div
                className="h-20 w-20 rounded-2xl flex items-center justify-center"
                style={{ backgroundColor: `${accentColor}26` }}
              >
                {isBusinessAgent ? (
                  <Store className="h-10 w-10" style={{ color: accentColor }} />
                ) : (
                  <User className="h-10 w-10" style={{ color: accentColor }} />
                )}
              </div>
            )}
          </div>

          {/* Name + status */}
          <h1 className="text-2xl font-bold text-[var(--foreground)] leading-tight mb-1">
            {profile.name}
          </h1>
          {profile.industry && (
            <p className="text-sm text-[var(--color-muted)] mb-2">
              {profile.industry}
            </p>
          )}
          <div className="inline-flex items-center gap-1.5 text-xs text-green-400 mb-4">
            <span className="h-1.5 w-1.5 rounded-full bg-green-400 animate-pulse" />
            Online now — ready to help
          </div>

          {/* Greeting / description */}
          {(profile.description || profile.greeting) && (
            <p className="text-sm text-[var(--color-muted)] leading-relaxed mb-6 max-w-sm mx-auto">
              {profile.description || profile.greeting}
            </p>
          )}

          {/* PRIMARY CTA — the one thing we want them to do */}
          {profile.chat_url ? (
            <a href={profile.chat_url} target="_blank" rel="noopener noreferrer" className="block">
              <Button variant="gold" className="w-full text-base py-3">
                <MessageCircle className="h-5 w-5" />
                Start a conversation
              </Button>
            </a>
          ) : (
            <Link href="/login" className="block">
              <Button variant="gold" className="w-full text-base py-3">
                <MessageCircle className="h-5 w-5" />
                Start a conversation
              </Button>
            </Link>
          )}
        </div>

        {/* Capabilities — what can this agent do for ME */}
        {profile.capabilities && profile.capabilities.length > 0 && (
          <div className="glass-panel p-5 mb-6">
            <h2 className="text-sm font-semibold text-[var(--foreground)] mb-3">
              How {profile.name} can help you
            </h2>
            <ul className="flex flex-col gap-2.5">
              {profile.capabilities.map((cap, i) => (
                <li
                  key={i}
                  className="flex items-start gap-2.5 text-sm text-[var(--color-muted)]"
                >
                  <CheckCircle className="h-4 w-4 text-green-400 flex-shrink-0 mt-0.5" />
                  {cap}
                </li>
              ))}
            </ul>
          </div>
        )}

        {/* QR code — useful for in-store / print */}
        {profile.qr_url && (
          <div className="glass-panel p-5 mb-6">
            <div className="flex items-center gap-4">
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={profile.qr_url}
                alt={`QR code for ${profile.name}`}
                className="w-20 h-20 rounded-lg border border-[var(--stroke)] bg-white p-1.5 flex-shrink-0"
                onError={(e) => {
                  (e.currentTarget.closest(".glass-panel") as HTMLElement | null)?.setAttribute("style", "display:none");
                }}
              />
              <div>
                <p className="text-sm font-medium text-[var(--foreground)] mb-1">Scan to chat</p>
                <p className="text-xs text-[var(--color-muted)] leading-relaxed">
                  Point your phone camera at this code to start chatting with {profile.name} instantly.
                </p>
              </div>
            </div>
          </div>
        )}

        {/* Developer tools — hidden by default, only for business owners */}
        {profile.widget_embed_code && (
          <div className="mb-6">
            <button
              onClick={() => setShowDeveloper(!showDeveloper)}
              className="text-xs text-[var(--color-muted)] hover:text-[var(--foreground)] transition-colors flex items-center gap-1.5 mx-auto"
            >
              <Code2 className="h-3.5 w-3.5" />
              {showDeveloper ? "Hide" : "Show"} embed code for website owners
            </button>
            {showDeveloper && (
              <div className="glass-panel p-4 mt-3">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-xs font-medium text-[var(--foreground)]">
                    Add to your website
                  </span>
                  <CopyButton text={profile.widget_embed_code} />
                </div>
                <pre className="bg-black/30 border border-[var(--stroke)] rounded-lg p-3 text-xs text-[var(--foreground)]/80 overflow-x-auto whitespace-pre-wrap break-all leading-relaxed font-mono">
                  {profile.widget_embed_code}
                </pre>
                <p className="text-xs text-[var(--color-muted)] mt-2">
                  Paste before the closing <code className="font-mono">&lt;/body&gt;</code> tag.
                </p>
              </div>
            )}
          </div>
        )}

        {/* Secondary actions */}
        <div className="flex flex-col gap-2">
          <Link href="/explore">
            <Button variant="outline" className="w-full">
              Browse more agents
            </Button>
          </Link>
          <Link href="/claim">
            <Button variant="ghost" className="w-full text-xs">
              Want an AI agent for your business? Get started free
            </Button>
          </Link>
        </div>

        {/* Powered by */}
        <div className="flex items-center justify-center gap-1.5 mt-8">
          <Zap className="h-3.5 w-3.5 text-[var(--gold-500)]" />
          <p className="text-xs text-[var(--color-muted)]">
            Powered by{" "}
            <Link href="/" className="text-[var(--gold-500)] font-medium hover:underline">DingDawg</Link>
          </p>
        </div>
      </div>
    </div>
  );
}

// ─── 404 state ────────────────────────────────────────────────────────────────

function NotFound({ handle }: { handle: string }) {
  return (
    <div className="min-h-screen px-4 pt-6 pb-24 max-w-lg mx-auto">
      <Link
        href="/explore"
        className="inline-flex items-center gap-1 text-sm text-[var(--color-muted)] hover:text-[var(--foreground)] mb-6 transition-colors"
      >
        <ArrowLeft className="h-4 w-4" />
        Back to Explore
      </Link>
      <div className="glass-panel p-10 text-center">
        <Store className="h-12 w-12 text-[var(--color-muted)] mx-auto mb-4 opacity-40" />
        <h1 className="text-lg font-bold text-[var(--foreground)] mb-2">
          Agent not found
        </h1>
        <p className="text-sm text-[var(--color-muted)] mb-6">
          <span className="text-[var(--gold-500)] font-medium">@{handle}</span>{" "}
          doesn&apos;t exist yet or isn&apos;t active.
        </p>
        <div className="flex flex-col gap-2">
          <Link href="/claim">
            <Button variant="gold" className="w-full">
              Claim @{handle}
            </Button>
          </Link>
          <Link href="/explore">
            <Button variant="outline" className="w-full">
              Browse agents
            </Button>
          </Link>
        </div>
      </div>
    </div>
  );
}

// ─── Error state ──────────────────────────────────────────────────────────────

function ErrorState({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div className="min-h-screen px-4 pt-6 pb-24 max-w-lg mx-auto">
      <Link
        href="/explore"
        className="inline-flex items-center gap-1 text-sm text-[var(--color-muted)] hover:text-[var(--foreground)] mb-6 transition-colors"
      >
        <ArrowLeft className="h-4 w-4" />
        Back to Explore
      </Link>
      <div className="glass-panel p-10 text-center">
        <p className="text-sm text-red-400 mb-4">{message}</p>
        <button
          onClick={onRetry}
          className="inline-flex items-center gap-1.5 text-xs text-[var(--gold-500)] hover:underline"
        >
          <RefreshCw className="h-3.5 w-3.5" />
          Try again
        </button>
      </div>
    </div>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function AgentProfilePage({ params }: PageProps) {
  const { handle } = use(params);

  const [profile, setProfile] = useState<PublicAgentProfile | null>(null);
  const [loading, setLoading] = useState(true);
  const [notFound, setNotFound] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchProfile = useCallback(async () => {
    setLoading(true);
    setNotFound(false);
    setError(null);
    try {
      const data = await get<PublicAgentProfile>(
        `/api/v1/public/agents/${encodeURIComponent(handle)}`
      );
      setProfile(data);
    } catch (err: unknown) {
      // Axios wraps HTTP errors; check the response status
      const axiosErr = err as { response?: { status: number }; message?: string };
      if (axiosErr?.response?.status === 404) {
        setNotFound(true);
      } else {
        setError(axiosErr?.message ?? "Failed to load agent profile");
      }
    } finally {
      setLoading(false);
    }
  }, [handle]);

  useEffect(() => {
    fetchProfile();
  }, [fetchProfile]);

  if (loading) return <ProfileSkeleton />;
  if (notFound) return <NotFound handle={handle} />;
  if (error) return <ErrorState message={error} onRetry={fetchProfile} />;
  if (!profile) return <NotFound handle={handle} />;

  return <ProfileContent profile={profile} />;
}
