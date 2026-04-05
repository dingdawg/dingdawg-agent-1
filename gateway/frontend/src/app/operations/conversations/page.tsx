"use client";

/**
 * Conversations (Cap 3).
 *
 * - Inbound messages list
 * - Smart reply suggestions
 * - Missed conversations alerts
 * - Send reply action
 */

import { useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import {
  MessageSquare,
  AlertCircle,
  RefreshCw,
  ChevronLeft,
  CheckCircle,
  Zap,
  Send,
} from "lucide-react";
import Link from "next/link";
import { cn } from "@/lib/utils";
import { useAgentStore } from "@/store/agentStore";
import { ProtectedRoute } from "@/components/auth/ProtectedRoute";
import { AppShell } from "@/components/layout/AppShell";
import {
  getMissedConversations,
  handleInbound,
  getSmartReply,
  sendReply,
  type MissedConversationsResponse,
  type HandleInboundResponse,
  type SmartReplyResponse,
} from "@/services/api/businessOpsService";

// ─── Helpers ──────────────────────────────────────────────────────────────────

function channelBadge(channel: string) {
  const map: Record<string, string> = {
    sms: "bg-green-500/10 text-green-400 border-green-500/20",
    email: "bg-blue-500/10 text-blue-400 border-blue-500/20",
    whatsapp: "bg-emerald-500/10 text-emerald-400 border-emerald-500/20",
    voice: "bg-purple-500/10 text-purple-400 border-purple-500/20",
    chat: "bg-[var(--gold-500)]/10 text-[var(--gold-500)] border-[var(--gold-500)]/20",
  };
  return map[channel] ?? "bg-white/5 text-[var(--color-muted)] border-[var(--stroke)]";
}

// ─── Page shell ───────────────────────────────────────────────────────────────

export default function ConversationsPage() {
  return (
    <ProtectedRoute>
      <AppShell>
        <ConversationsContent />
      </AppShell>
    </ProtectedRoute>
  );
}

// ─── Content ──────────────────────────────────────────────────────────────────

function ConversationsContent() {
  const router = useRouter();
  const { currentAgent, agents, isLoading: agentsLoading, fetchAgents } = useAgentStore();

  const [missed, setMissed] = useState<MissedConversationsResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [toast, setToast] = useState<{ type: "success" | "error"; message: string } | null>(null);

  // Inbound form
  const [inboundForm, setInboundForm] = useState({ client_id: "", channel: "sms", content: "" });
  const [inboundResult, setInboundResult] = useState<HandleInboundResponse | null>(null);
  const [submittingInbound, setSubmittingInbound] = useState(false);

  // Smart reply
  const [smartReplyForm, setSmartReplyForm] = useState({ thread_id: "", inbound_content: "" });
  const [smartReply, setSmartReply] = useState<SmartReplyResponse | null>(null);
  const [gettingSmartReply, setGettingSmartReply] = useState(false);

  // Send reply
  const [replyForm, setReplyForm] = useState({ thread_id: "", content: "" });
  const [sendingReply, setSendingReply] = useState(false);

  useEffect(() => { fetchAgents(); }, [fetchAgents]);

  useEffect(() => {
    if (!agentsLoading && agents.length === 0) router.replace("/claim");
  }, [agentsLoading, agents.length, router]);

  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(null), 4000);
    return () => clearTimeout(t);
  }, [toast]);

  const load = useCallback(async () => {
    if (!currentAgent) return;
    setLoading(true);
    setError(null);
    try {
      const data = await getMissedConversations(currentAgent.id, 24);
      setMissed(data);
    } catch (err) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })
          ?.response?.data?.detail ?? "Failed to load missed conversations";
      setError(detail);
    } finally {
      setLoading(false);
    }
  }, [currentAgent]);

  useEffect(() => { load(); }, [load]);

  const handleInboundSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!currentAgent || !inboundForm.client_id || !inboundForm.content) {
      setToast({ type: "error", message: "Client ID and message content are required." });
      return;
    }
    setSubmittingInbound(true);
    try {
      const res = await handleInbound(currentAgent.id, {
        client_id: inboundForm.client_id,
        channel: inboundForm.channel,
        content: inboundForm.content,
      });
      setInboundResult(res);
      if (res.thread_id) {
        setSmartReplyForm((f) => ({ ...f, thread_id: String(res.thread_id), inbound_content: inboundForm.content }));
        setReplyForm((f) => ({ ...f, thread_id: String(res.thread_id) }));
      }
      setToast({ type: "success", message: "Inbound message recorded." });
    } catch (err) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })
          ?.response?.data?.detail ?? "Failed to record inbound message";
      setToast({ type: "error", message: detail });
    } finally {
      setSubmittingInbound(false);
    }
  };

  const handleGetSmartReply = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!currentAgent || !smartReplyForm.thread_id || !smartReplyForm.inbound_content) {
      setToast({ type: "error", message: "Thread ID and inbound content are required." });
      return;
    }
    setGettingSmartReply(true);
    try {
      const res = await getSmartReply(currentAgent.id, {
        thread_id: smartReplyForm.thread_id,
        inbound_content: smartReplyForm.inbound_content,
      });
      setSmartReply(res);
      if (res.suggestion) {
        setReplyForm((f) => ({ ...f, content: String(res.suggestion), thread_id: smartReplyForm.thread_id }));
      }
    } catch (err) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })
          ?.response?.data?.detail ?? "Failed to get smart reply";
      setToast({ type: "error", message: detail });
    } finally {
      setGettingSmartReply(false);
    }
  };

  const handleSendReply = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!currentAgent || !replyForm.thread_id || !replyForm.content) {
      setToast({ type: "error", message: "Thread ID and reply content are required." });
      return;
    }
    setSendingReply(true);
    try {
      await sendReply(currentAgent.id, {
        thread_id: replyForm.thread_id,
        content: replyForm.content,
      });
      setReplyForm((f) => ({ ...f, content: "" }));
      setSmartReply(null);
      setToast({ type: "success", message: "Reply sent!" });
    } catch (err) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })
          ?.response?.data?.detail ?? "Failed to send reply";
      setToast({ type: "error", message: detail });
    } finally {
      setSendingReply(false);
    }
  };

  if (agentsLoading && agents.length === 0) {
    return (
      <div className="flex items-center justify-center h-full">
        <span className="spinner text-[var(--gold-500)]" />
      </div>
    );
  }
  if (!currentAgent) return null;

  const missedThreads = (missed?.threads as Array<Record<string, unknown>>) ?? [];

  return (
    <div className="h-full overflow-y-auto scrollbar-thin">
      <div className="max-w-3xl mx-auto px-4 py-6 pb-6 space-y-5">

        {/* Header */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Link href="/operations" className="text-[var(--color-muted)] hover:text-[var(--foreground)] transition-colors">
              <ChevronLeft className="h-5 w-5" />
            </Link>
            <div>
              <h1 className="text-xl font-bold text-[var(--foreground)] flex items-center gap-2">
                <MessageSquare className="h-5 w-5 text-[var(--gold-500)]" />
                Conversations
              </h1>
              <p className="text-xs text-[var(--color-muted)] mt-0.5">@{currentAgent.handle}</p>
            </div>
          </div>
          <button
            onClick={load}
            disabled={loading}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs text-[var(--color-muted)] hover:text-[var(--foreground)] hover:bg-white/5 transition-colors disabled:opacity-50"
          >
            <RefreshCw className={cn("h-3.5 w-3.5", loading && "animate-spin")} />
            Refresh
          </button>
        </div>

        {/* Toast */}
        {toast && (
          <div className={cn("p-3 rounded-xl text-sm flex items-center gap-2 border", toast.type === "success" ? "bg-green-500/10 border-green-500/20 text-green-400" : "bg-red-500/10 border-red-500/20 text-red-400")}>
            {toast.type === "success" ? <CheckCircle className="h-4 w-4 flex-shrink-0" /> : <AlertCircle className="h-4 w-4 flex-shrink-0" />}
            {toast.message}
            <button onClick={() => setToast(null)} className="ml-auto text-xs underline opacity-70">dismiss</button>
          </div>
        )}

        {/* Error */}
        {error && (
          <div className="p-3 rounded-lg bg-red-500/10 border border-red-500/20 text-red-400 text-sm flex items-center gap-2">
            <AlertCircle className="h-4 w-4 flex-shrink-0" />
            {error}
            <button onClick={load} className="ml-auto text-xs underline">retry</button>
          </div>
        )}

        {/* Missed conversations */}
        <section className="glass-panel p-5">
          <h2 className="text-sm font-semibold text-[var(--foreground)] mb-4 flex items-center gap-2">
            <AlertCircle className="h-4 w-4 text-red-400" />
            Missed Conversations (last 24h)
          </h2>
          {loading ? (
            <div className="flex items-center justify-center py-6">
              <span className="spinner text-[var(--color-muted)]" />
            </div>
          ) : missedThreads.length === 0 ? (
            <div className="text-center py-6 flex flex-col items-center gap-2">
              <CheckCircle className="h-8 w-8 text-green-400" />
              <p className="text-sm text-[var(--color-muted)]">No missed conversations.</p>
            </div>
          ) : (
            <div className="divide-y divide-[var(--stroke)]">
              {missedThreads.slice(0, 10).map((thread, i) => (
                <div key={String(thread.thread_id ?? thread.id ?? i)} className="py-3 first:pt-0 last:pb-0 flex items-start gap-3">
                  <div className="h-8 w-8 rounded-lg bg-red-500/10 flex items-center justify-center flex-shrink-0">
                    <MessageSquare className="h-3.5 w-3.5 text-red-400" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <p className="text-sm font-medium text-[var(--foreground)] truncate">
                        {String(thread.client_name ?? thread.from ?? "Unknown")}
                      </p>
                      {!!thread.channel && (
                        <span className={cn("text-[10px] font-semibold px-1.5 py-0.5 rounded border", channelBadge(String(thread.channel)))}>
                          {String(thread.channel)}
                        </span>
                      )}
                    </div>
                    <p className="text-xs text-[var(--color-muted)] truncate mt-0.5">
                      {String(thread.last_message ?? thread.preview ?? "No preview")}
                    </p>
                  </div>
                  <button
                    onClick={() => {
                      const tid = String(thread.thread_id ?? thread.id ?? "");
                      setReplyForm({ thread_id: tid, content: "" });
                      setSmartReplyForm((f) => ({ ...f, thread_id: tid }));
                    }}
                    className="flex-shrink-0 text-xs text-[var(--gold-500)] hover:underline"
                  >
                    Reply
                  </button>
                </div>
              ))}
            </div>
          )}
        </section>

        {/* Record inbound message */}
        <section className="glass-panel p-5">
          <h2 className="text-sm font-semibold text-[var(--foreground)] mb-4">Record Inbound Message</h2>
          <form onSubmit={handleInboundSubmit} className="space-y-3">
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div>
                <label className="text-xs text-[var(--color-muted)] mb-1 block">Client ID</label>
                <input
                  type="text"
                  value={inboundForm.client_id}
                  onChange={(e) => setInboundForm((f) => ({ ...f, client_id: e.target.value }))}
                  placeholder="client_abc123"
                  className="w-full px-3 py-2 rounded-lg bg-white/5 border border-[var(--stroke)] text-sm text-[var(--foreground)] placeholder:text-[var(--color-muted)] focus:outline-none focus:border-[var(--gold-500)]/50 transition-colors"
                />
              </div>
              <div>
                <label className="text-xs text-[var(--color-muted)] mb-1 block">Channel</label>
                <select
                  value={inboundForm.channel}
                  onChange={(e) => setInboundForm((f) => ({ ...f, channel: e.target.value }))}
                  className="w-full px-3 py-2 rounded-lg bg-white/5 border border-[var(--stroke)] text-sm text-[var(--foreground)] focus:outline-none focus:border-[var(--gold-500)]/50 transition-colors"
                >
                  {["sms", "email", "whatsapp", "voice", "chat"].map((ch) => (
                    <option key={ch} value={ch}>{ch}</option>
                  ))}
                </select>
              </div>
            </div>
            <div>
              <label className="text-xs text-[var(--color-muted)] mb-1 block">Message</label>
              <textarea
                value={inboundForm.content}
                onChange={(e) => setInboundForm((f) => ({ ...f, content: e.target.value }))}
                placeholder="Hi, I'd like to book an appointment…"
                rows={3}
                className="w-full px-3 py-2 rounded-lg bg-white/5 border border-[var(--stroke)] text-sm text-[var(--foreground)] placeholder:text-[var(--color-muted)] focus:outline-none focus:border-[var(--gold-500)]/50 transition-colors resize-none"
              />
            </div>
            <button
              type="submit"
              disabled={submittingInbound}
              className="w-full py-2.5 rounded-xl bg-[var(--gold-500)] text-[#07111c] font-semibold text-sm hover:opacity-90 transition-opacity disabled:opacity-50"
            >
              {submittingInbound ? <span className="flex items-center justify-center gap-2"><span className="spinner h-3.5 w-3.5" />Recording…</span> : "Record Message"}
            </button>
          </form>
          {inboundResult?.thread_id && (
            <div className="mt-3 p-2.5 rounded-lg bg-green-500/10 border border-green-500/20 text-green-400 text-xs">
              Thread ID: <span className="font-mono font-semibold">{String(inboundResult.thread_id)}</span>
            </div>
          )}
        </section>

        {/* Smart reply */}
        <section className="glass-panel p-5">
          <h2 className="text-sm font-semibold text-[var(--foreground)] mb-4 flex items-center gap-2">
            <Zap className="h-4 w-4 text-[var(--gold-500)]" />
            Smart Reply Suggestion
          </h2>
          <form onSubmit={handleGetSmartReply} className="space-y-3">
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div>
                <label className="text-xs text-[var(--color-muted)] mb-1 block">Thread ID</label>
                <input
                  type="text"
                  value={smartReplyForm.thread_id}
                  onChange={(e) => setSmartReplyForm((f) => ({ ...f, thread_id: e.target.value }))}
                  placeholder="thread_abc123"
                  className="w-full px-3 py-2 rounded-lg bg-white/5 border border-[var(--stroke)] text-sm text-[var(--foreground)] placeholder:text-[var(--color-muted)] focus:outline-none focus:border-[var(--gold-500)]/50 transition-colors"
                />
              </div>
              <div>
                <label className="text-xs text-[var(--color-muted)] mb-1 block">Inbound Content</label>
                <input
                  type="text"
                  value={smartReplyForm.inbound_content}
                  onChange={(e) => setSmartReplyForm((f) => ({ ...f, inbound_content: e.target.value }))}
                  placeholder="What the client said…"
                  className="w-full px-3 py-2 rounded-lg bg-white/5 border border-[var(--stroke)] text-sm text-[var(--foreground)] placeholder:text-[var(--color-muted)] focus:outline-none focus:border-[var(--gold-500)]/50 transition-colors"
                />
              </div>
            </div>
            <button
              type="submit"
              disabled={gettingSmartReply}
              className="w-full py-2 rounded-xl bg-white/8 border border-[var(--stroke)] text-sm font-medium text-[var(--foreground)] hover:bg-white/12 transition-colors disabled:opacity-50"
            >
              {gettingSmartReply ? <span className="flex items-center justify-center gap-2"><span className="spinner h-3.5 w-3.5" />Thinking…</span> : "Suggest Reply"}
            </button>
          </form>
          {smartReply?.suggestion && (
            <div className="mt-3 p-3 rounded-lg bg-[var(--gold-500)]/5 border border-[var(--gold-500)]/20 text-sm text-[var(--foreground)]">
              <p className="text-xs text-[var(--gold-500)] font-semibold mb-1">Suggested reply</p>
              {String(smartReply.suggestion)}
            </div>
          )}
        </section>

        {/* Send reply */}
        <section className="glass-panel p-5">
          <h2 className="text-sm font-semibold text-[var(--foreground)] mb-4 flex items-center gap-2">
            <Send className="h-4 w-4 text-[var(--gold-500)]" />
            Send Reply
          </h2>
          <form onSubmit={handleSendReply} className="space-y-3">
            <div>
              <label className="text-xs text-[var(--color-muted)] mb-1 block">Thread ID</label>
              <input
                type="text"
                value={replyForm.thread_id}
                onChange={(e) => setReplyForm((f) => ({ ...f, thread_id: e.target.value }))}
                placeholder="thread_abc123"
                className="w-full px-3 py-2 rounded-lg bg-white/5 border border-[var(--stroke)] text-sm text-[var(--foreground)] placeholder:text-[var(--color-muted)] focus:outline-none focus:border-[var(--gold-500)]/50 transition-colors"
              />
            </div>
            <div>
              <label className="text-xs text-[var(--color-muted)] mb-1 block">Reply</label>
              <textarea
                value={replyForm.content}
                onChange={(e) => setReplyForm((f) => ({ ...f, content: e.target.value }))}
                placeholder="Type your reply…"
                rows={3}
                className="w-full px-3 py-2 rounded-lg bg-white/5 border border-[var(--stroke)] text-sm text-[var(--foreground)] placeholder:text-[var(--color-muted)] focus:outline-none focus:border-[var(--gold-500)]/50 transition-colors resize-none"
              />
            </div>
            <button
              type="submit"
              disabled={sendingReply}
              className="w-full py-2.5 rounded-xl bg-[var(--gold-500)] text-[#07111c] font-semibold text-sm hover:opacity-90 transition-opacity disabled:opacity-50"
            >
              {sendingReply ? <span className="flex items-center justify-center gap-2"><span className="spinner h-3.5 w-3.5" />Sending…</span> : "Send Reply"}
            </button>
          </form>
        </section>

      </div>
    </div>
  );
}
