"use client";

/**
 * Admin Scheduler page — calendar event timeline with key dates.
 *
 * - Vertical timeline of upcoming events (deadline/appointment/policy/reminder)
 * - Today separator line in the timeline
 * - Quick Add Event form (title, date, type)
 * - Key Dates section (Colorado AI Act, trademark, renewals)
 * - Manual refresh only — calendar data rarely changes
 * - Mobile responsive with 48px touch targets
 * - No HTML entities in JSX
 */

import { useEffect, useState, useCallback } from "react";
import {
  Calendar,
  Clock,
  AlertTriangle,
  RefreshCw,
  Plus,
  AlertCircle,
  CheckCircle2,
  Bell,
  FileText,
} from "lucide-react";
import { cn } from "@/lib/utils";
import {
  getEvents,
  createEvent,
  type AdminEvent,
  type EventType,
} from "@/services/api/adminService";

// ─── Helpers ──────────────────────────────────────────────────────────────────

function formatEventDate(iso: string): string {
  try {
    return new Date(iso).toLocaleDateString("en-US", {
      weekday: "short",
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

function formatShortDate(iso: string): string {
  try {
    return new Date(iso).toLocaleDateString("en-US", {
      month: "short",
      day: "numeric",
      year: "numeric",
    });
  } catch {
    return iso;
  }
}

function isToday(iso: string): boolean {
  const d = new Date(iso);
  const now = new Date();
  return (
    d.getFullYear() === now.getFullYear() &&
    d.getMonth() === now.getMonth() &&
    d.getDate() === now.getDate()
  );
}

function isPast(iso: string): boolean {
  return new Date(iso) < new Date();
}

// ─── Event type config ────────────────────────────────────────────────────────

const EVENT_TYPE_CONFIG: Record<
  EventType,
  { label: string; color: string; bgColor: string; icon: React.ComponentType<{ className?: string }> }
> = {
  deadline: {
    label: "Deadline",
    color: "text-red-400",
    bgColor: "bg-red-500/10 border-red-500/20",
    icon: AlertTriangle,
  },
  appointment: {
    label: "Appointment",
    color: "text-blue-400",
    bgColor: "bg-blue-500/10 border-blue-500/20",
    icon: Calendar,
  },
  policy: {
    label: "Policy",
    color: "text-[var(--gold-400)]",
    bgColor: "bg-[var(--gold-400)]/10 border-[var(--gold-400)]/20",
    icon: FileText,
  },
  reminder: {
    label: "Reminder",
    color: "text-gray-400",
    bgColor: "bg-gray-500/10 border-gray-500/20",
    icon: Bell,
  },
};

// ─── Key dates (hardcoded business-critical dates) ────────────────────────────

const KEY_DATES: Array<{ title: string; date: string; note: string; urgency: "high" | "medium" | "low" }> = [
  {
    title: "Colorado AI Act Deadline",
    date: "June 30, 2026",
    note: "SB 205 — high-risk AI system compliance required",
    urgency: "high",
  },
  {
    title: "USPTO Trademark Review",
    date: "~Sept 2026",
    note: "Serial #99693655 — 4 classes filed 2026-03-11",
    urgency: "medium",
  },
  {
    title: "Stripe Test Mode Cutover",
    date: "Before first revenue",
    note: "DD Main + Agent 1 both in test mode — must flip to live",
    urgency: "high",
  },
  {
    title: "CAIA Conference",
    date: "June 30, 2026",
    note: "Target launch window for agent-to-agent commerce demo",
    urgency: "medium",
  },
];

// ─── Sub-components ───────────────────────────────────────────────────────────

function EventTypeBadge({ type }: { type: EventType }) {
  const cfg = EVENT_TYPE_CONFIG[type];
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium border",
        cfg.bgColor,
        cfg.color
      )}
    >
      <cfg.icon className="h-3 w-3" />
      {cfg.label}
    </span>
  );
}

function TimelineEvent({
  event,
  isFirst,
  showTodaySeparator,
}: {
  event: AdminEvent;
  isFirst: boolean;
  showTodaySeparator: boolean;
}) {
  const cfg = EVENT_TYPE_CONFIG[event.type];
  const past = isPast(event.date);
  const today = isToday(event.date);

  return (
    <>
      {showTodaySeparator && (
        <div className="flex items-center gap-3 my-2">
          <div className="flex-1 h-px bg-[var(--gold-400)]/40" />
          <span className="text-xs font-semibold text-[var(--gold-400)] px-2 py-0.5 rounded-full bg-[var(--gold-400)]/10 border border-[var(--gold-400)]/20">
            TODAY
          </span>
          <div className="flex-1 h-px bg-[var(--gold-400)]/40" />
        </div>
      )}
      <div className={cn("flex gap-3", !isFirst && "mt-0")}>
        {/* Timeline dot + line */}
        <div className="flex flex-col items-center flex-shrink-0">
          <div
            className={cn(
              "h-3 w-3 rounded-full border-2 flex-shrink-0 mt-1",
              past && !today
                ? "border-gray-600 bg-gray-700"
                : today
                ? "border-[var(--gold-400)] bg-[var(--gold-400)]"
                : `border-current ${cfg.color} bg-transparent`
            )}
          />
          <div className="w-px flex-1 bg-[#1a2a3d] mt-1" />
        </div>

        {/* Event card */}
        <div
          className={cn(
            "flex-1 mb-3 p-3 rounded-xl border",
            past && !today
              ? "bg-[#0d1926]/50 border-[#1a2a3d]/50 opacity-60"
              : "bg-[#0d1926] border-[#1a2a3d]"
          )}
        >
          <div className="flex items-start justify-between gap-2 mb-1">
            <p
              className={cn(
                "text-sm font-semibold",
                past && !today ? "text-gray-500" : "text-white"
              )}
            >
              {event.title}
            </p>
            <EventTypeBadge type={event.type} />
          </div>
          <div className="flex items-center gap-1.5 text-xs text-gray-400">
            <Clock className="h-3 w-3 flex-shrink-0" />
            {formatEventDate(event.date)}
          </div>
          {event.description && (
            <p className="mt-1.5 text-xs text-gray-400 leading-relaxed">
              {event.description}
            </p>
          )}
        </div>
      </div>
    </>
  );
}

function AddEventForm({
  onAdd,
}: {
  onAdd: (title: string, date: string, type: EventType) => Promise<void>;
}) {
  const [title, setTitle] = useState("");
  const [date, setDate] = useState("");
  const [type, setType] = useState<EventType>("reminder");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!title.trim() || !date) return;
    setSaving(true);
    setError(null);
    setSuccess(false);
    try {
      await onAdd(title.trim(), date, type);
      setTitle("");
      setDate("");
      setType("reminder");
      setSuccess(true);
      setTimeout(() => setSuccess(false), 3000);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to add event";
      setError(msg);
    } finally {
      setSaving(false);
    }
  };

  return (
    <form
      onSubmit={handleSubmit}
      className="bg-[#0d1926] border border-[#1a2a3d] rounded-xl p-4 flex flex-col gap-3"
    >
      <h3 className="text-sm font-semibold text-white">Quick Add Event</h3>

      {error && (
        <div className="flex items-center gap-2 text-xs text-red-400 bg-red-500/10 border border-red-500/20 rounded-lg px-3 py-2">
          <AlertCircle className="h-3.5 w-3.5 flex-shrink-0" />
          {error}
        </div>
      )}
      {success && (
        <div className="flex items-center gap-2 text-xs text-green-400 bg-green-500/10 border border-green-500/20 rounded-lg px-3 py-2">
          <CheckCircle2 className="h-3.5 w-3.5 flex-shrink-0" />
          Event added
        </div>
      )}

      <input
        type="text"
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        placeholder="Event title"
        className="w-full px-3 py-2.5 rounded-lg bg-white/5 border border-[#1a2a3d] text-sm text-white placeholder-gray-500 focus:outline-none focus:border-[var(--gold-400)]/50 min-h-[44px]"
        required
      />

      <div className="grid grid-cols-2 gap-2">
        <input
          type="datetime-local"
          value={date}
          onChange={(e) => setDate(e.target.value)}
          className="px-3 py-2.5 rounded-lg bg-white/5 border border-[#1a2a3d] text-sm text-white focus:outline-none focus:border-[var(--gold-400)]/50 min-h-[44px] col-span-2 sm:col-span-1"
          required
        />

        <select
          value={type}
          onChange={(e) => setType(e.target.value as EventType)}
          className="px-3 py-2.5 rounded-lg bg-[#0d1926] border border-[#1a2a3d] text-sm text-white focus:outline-none focus:border-[var(--gold-400)]/50 min-h-[44px] col-span-2 sm:col-span-1"
        >
          <option value="reminder">Reminder</option>
          <option value="deadline">Deadline</option>
          <option value="appointment">Appointment</option>
          <option value="policy">Policy</option>
        </select>
      </div>

      <button
        type="submit"
        disabled={saving || !title.trim() || !date}
        className="flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl bg-[var(--gold-400)] text-[#07111c] text-sm font-semibold hover:opacity-90 transition-opacity disabled:opacity-40 min-h-[44px]"
      >
        <Plus className="h-4 w-4" />
        {saving ? "Adding..." : "Add Event"}
      </button>
    </form>
  );
}

// ─── Main page ────────────────────────────────────────────────────────────────

export default function SchedulerPage() {
  return <SchedulerContent />;
}

function SchedulerContent() {
  const [events, setEvents] = useState<AdminEvent[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadEvents = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await getEvents();
      // Sort ascending by date
      const sorted = [...data].sort(
        (a, b) => new Date(a.date).getTime() - new Date(b.date).getTime()
      );
      setEvents(sorted);
    } catch (err: unknown) {
      const msg =
        err instanceof Error ? err.message : "Failed to load events";
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadEvents();
  }, [loadEvents]);

  const handleAddEvent = useCallback(
    async (title: string, date: string, type: EventType) => {
      const created = await createEvent({ title, date, type });
      setEvents((prev) => {
        const next = [...prev, created].sort(
          (a, b) => new Date(a.date).getTime() - new Date(b.date).getTime()
        );
        return next;
      });
    },
    []
  );

  // Compute which event index should show the "TODAY" separator
  // (insert before the first future event)
  const todaySeparatorIndex = (() => {
    const now = new Date();
    for (let i = 0; i < events.length; i++) {
      if (new Date(events[i].date) >= now && !isPast(events[i].date)) {
        return i;
      }
    }
    return -1;
  })();

  return (
    <div className="h-full overflow-y-auto scrollbar-thin px-4 pt-6 pb-20 lg:pb-8 max-w-2xl mx-auto">
      {/* Page header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-xl font-bold text-white">Scheduler</h1>
          <p className="text-xs text-gray-400 mt-0.5">Key dates and events</p>
        </div>
        <button
          onClick={loadEvents}
          disabled={loading}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs text-gray-400 hover:text-white hover:bg-white/5 transition-colors disabled:opacity-50 min-h-[44px]"
        >
          <RefreshCw
            className={cn("h-3.5 w-3.5", loading && "animate-spin")}
          />
          Refresh
        </button>
      </div>

      {/* Error banner */}
      {error && (
        <div className="mb-5 p-3 rounded-lg bg-red-500/10 border border-red-500/20 text-red-400 text-sm flex items-center gap-2">
          <AlertCircle className="h-4 w-4 flex-shrink-0" />
          {error}
          <button onClick={loadEvents} className="ml-auto text-xs underline">
            retry
          </button>
        </div>
      )}

      {/* Key Dates section */}
      <div className="mb-6 bg-[#0d1926] border border-[#1a2a3d] rounded-xl p-4">
        <h2 className="text-sm font-semibold text-white mb-3 flex items-center gap-2">
          <AlertTriangle className="h-4 w-4 text-[var(--gold-400)]" />
          Key Dates
        </h2>
        <div className="flex flex-col gap-2">
          {KEY_DATES.map((kd) => (
            <div
              key={kd.title}
              className={cn(
                "flex items-start gap-3 p-3 rounded-lg border",
                kd.urgency === "high"
                  ? "bg-red-500/5 border-red-500/15"
                  : "bg-white/3 border-[#1a2a3d]"
              )}
            >
              <div
                className={cn(
                  "h-2 w-2 rounded-full mt-1.5 flex-shrink-0",
                  kd.urgency === "high"
                    ? "bg-red-400"
                    : kd.urgency === "medium"
                    ? "bg-[var(--gold-400)]"
                    : "bg-gray-500"
                )}
              />
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-white">{kd.title}</p>
                <p className="text-xs text-[var(--gold-400)] font-medium mt-0.5">
                  {kd.date}
                </p>
                <p className="text-xs text-gray-400 mt-0.5">{kd.note}</p>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Event timeline */}
      <div className="mb-6">
        <h2 className="text-sm font-semibold text-white mb-4 flex items-center gap-2">
          <Calendar className="h-4 w-4 text-[var(--gold-400)]" />
          Upcoming Events
        </h2>

        {loading && events.length === 0 ? (
          <div className="flex flex-col gap-3">
            {[1, 2, 3].map((i) => (
              <div key={i} className="flex gap-3">
                <div className="flex flex-col items-center flex-shrink-0">
                  <div className="h-3 w-3 rounded-full bg-white/10 animate-pulse mt-1" />
                  <div className="w-px flex-1 bg-[#1a2a3d] mt-1" />
                </div>
                <div className="flex-1 mb-3 p-3 rounded-xl border border-[#1a2a3d] bg-[#0d1926] animate-pulse">
                  <div className="h-4 bg-white/5 rounded w-3/4 mb-2" />
                  <div className="h-3 bg-white/5 rounded w-1/2" />
                </div>
              </div>
            ))}
          </div>
        ) : events.length === 0 ? (
          <div className="flex flex-col items-center gap-3 py-10 text-center">
            <Calendar className="h-10 w-10 text-gray-600" />
            <p className="text-sm font-medium text-gray-400">No events yet</p>
            <p className="text-xs text-gray-500">
              Add an event below to start tracking
            </p>
          </div>
        ) : (
          <div>
            {events.map((event, idx) => (
              <TimelineEvent
                key={event.id}
                event={event}
                isFirst={idx === 0}
                showTodaySeparator={idx === todaySeparatorIndex}
              />
            ))}
          </div>
        )}
      </div>

      {/* Quick add form */}
      <AddEventForm onAdd={handleAddEvent} />
    </div>
  );
}
