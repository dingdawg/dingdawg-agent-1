"use client";

/**
 * Staff & Resources (Cap 5).
 *
 * - Utilization report (business-level)
 * - Per-staff member schedule viewer
 * - Assignment form (staff → appointment)
 * - Schedule upsert form
 */

import { useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import {
  CalendarDays,
  AlertCircle,
  RefreshCw,
  ChevronLeft,
  CheckCircle,
  Users,
  Clock,
} from "lucide-react";
import Link from "next/link";
import { cn } from "@/lib/utils";
import { useAgentStore } from "@/store/agentStore";
import { ProtectedRoute } from "@/components/auth/ProtectedRoute";
import { AppShell } from "@/components/layout/AppShell";
import {
  getUtilizationReport,
  assignStaff,
  getStaffSchedule,
  setStaffSchedule,
  type UtilizationReportResponse,
  type StaffScheduleResponse,
} from "@/services/api/businessOpsService";

// ─── Helpers ──────────────────────────────────────────────────────────────────

function utilizationColor(pct: number) {
  if (pct >= 90) return "bg-red-400";
  if (pct >= 70) return "bg-yellow-400";
  return "bg-green-400";
}

// ─── Page shell ───────────────────────────────────────────────────────────────

export default function StaffPage() {
  return (
    <ProtectedRoute>
      <AppShell>
        <StaffContent />
      </AppShell>
    </ProtectedRoute>
  );
}

// ─── Content ──────────────────────────────────────────────────────────────────

function StaffContent() {
  const router = useRouter();
  const { currentAgent, agents, isLoading: agentsLoading, fetchAgents } = useAgentStore();

  const [utilization, setUtilization] = useState<UtilizationReportResponse | null>(null);
  const [schedule, setSchedule] = useState<StaffScheduleResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [toast, setToast] = useState<{ type: "success" | "error"; message: string } | null>(null);

  // Assign form
  const [assignForm, setAssignForm] = useState({ staff_id: "", appointment_id: "" });
  const [assigning, setAssigning] = useState(false);

  // Schedule lookup
  const [scheduleStaffId, setScheduleStaffId] = useState("");
  const [loadingSchedule, setLoadingSchedule] = useState(false);

  // Schedule upsert
  const [scheduleForm, setScheduleForm] = useState({
    staff_id: "",
    day_of_week: "1",
    start_time: "09:00",
    end_time: "17:00",
  });
  const [settingSchedule, setSettingSchedule] = useState(false);

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
      const report = await getUtilizationReport(currentAgent.id, 7);
      setUtilization(report);
    } catch (err) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })
          ?.response?.data?.detail ?? "Failed to load utilization";
      setError(detail);
    } finally {
      setLoading(false);
    }
  }, [currentAgent]);

  useEffect(() => { load(); }, [load]);

  const handleAssign = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!currentAgent || !assignForm.staff_id || !assignForm.appointment_id) {
      setToast({ type: "error", message: "Staff ID and Appointment ID are required." });
      return;
    }
    setAssigning(true);
    try {
      await assignStaff(currentAgent.id, {
        staff_id: assignForm.staff_id,
        appointment_id: assignForm.appointment_id,
      });
      setAssignForm({ staff_id: "", appointment_id: "" });
      setToast({ type: "success", message: "Staff assigned successfully." });
    } catch (err) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })
          ?.response?.data?.detail ?? "Failed to assign staff";
      setToast({ type: "error", message: detail });
    } finally {
      setAssigning(false);
    }
  };

  const handleLoadSchedule = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!currentAgent || !scheduleStaffId) {
      setToast({ type: "error", message: "Staff ID is required." });
      return;
    }
    setLoadingSchedule(true);
    try {
      const data = await getStaffSchedule(currentAgent.id, scheduleStaffId);
      setSchedule(data);
    } catch (err) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })
          ?.response?.data?.detail ?? "Failed to load schedule";
      setToast({ type: "error", message: detail });
    } finally {
      setLoadingSchedule(false);
    }
  };

  const handleSetSchedule = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!currentAgent || !scheduleForm.staff_id) {
      setToast({ type: "error", message: "Staff ID is required." });
      return;
    }
    setSettingSchedule(true);
    try {
      await setStaffSchedule(currentAgent.id, scheduleForm.staff_id, {
        day_of_week: parseInt(scheduleForm.day_of_week, 10),
        start_time: scheduleForm.start_time,
        end_time: scheduleForm.end_time,
      });
      setToast({ type: "success", message: "Schedule updated." });
    } catch (err) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })
          ?.response?.data?.detail ?? "Failed to update schedule";
      setToast({ type: "error", message: detail });
    } finally {
      setSettingSchedule(false);
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

  const staffList = (
    (utilization as Record<string, unknown> | null)?.staff as Array<Record<string, unknown>>
  ) ?? [];

  const scheduleEntries = (
    (schedule as Record<string, unknown> | null)?.schedule as Array<Record<string, unknown>>
  ) ?? [];

  const DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

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
                <CalendarDays className="h-5 w-5 text-[var(--gold-500)]" />
                Staff &amp; Resources
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

        {/* Utilization overview */}
        <section className="glass-panel p-5">
          <h2 className="text-sm font-semibold text-[var(--foreground)] mb-4 flex items-center gap-2">
            <Users className="h-4 w-4 text-[var(--gold-500)]" />
            Utilization Report (7 days)
          </h2>
          {loading ? (
            <div className="flex items-center justify-center py-6">
              <span className="spinner text-[var(--color-muted)]" />
            </div>
          ) : staffList.length === 0 ? (
            <p className="text-sm text-[var(--color-muted)] text-center py-4">No staff data yet.</p>
          ) : (
            <div className="divide-y divide-[var(--stroke)]">
              {staffList.map((member, i) => {
                const pct = Math.min(100, Math.max(0, Number(member.utilization_pct ?? member.utilization ?? 0)));
                return (
                  <div key={String(member.staff_id ?? member.id ?? i)} className="py-3 first:pt-0 last:pb-0">
                    <div className="flex items-center gap-3">
                      <div className="h-8 w-8 rounded-lg bg-[var(--gold-500)]/10 flex items-center justify-center flex-shrink-0">
                        <Users className="h-3.5 w-3.5 text-[var(--gold-500)]" />
                      </div>
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-medium text-[var(--foreground)] truncate">
                          {String(member.name ?? member.staff_name ?? member.staff_id ?? "Staff " + (i + 1))}
                        </p>
                        {!!member.role && (
                          <p className="text-xs text-[var(--color-muted)]">{String(member.role)}</p>
                        )}
                      </div>
                      <span className={cn(
                        "text-sm font-bold tabular-nums",
                        pct >= 90 ? "text-red-400" : pct >= 70 ? "text-yellow-400" : "text-green-400"
                      )}>
                        {pct}%
                      </span>
                    </div>
                    <div className="mt-2 w-full h-1.5 rounded-full bg-white/10 overflow-hidden">
                      <div
                        className={cn("h-full rounded-full", utilizationColor(pct))}
                        style={{ width: `${pct}%` }}
                      />
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </section>

        {/* Assign staff form */}
        <section className="glass-panel p-5">
          <h2 className="text-sm font-semibold text-[var(--foreground)] mb-4">Assign Staff to Appointment</h2>
          <form onSubmit={handleAssign} className="space-y-3">
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div>
                <label className="text-xs text-[var(--color-muted)] mb-1 block">Staff ID</label>
                <input
                  type="text"
                  value={assignForm.staff_id}
                  onChange={(e) => setAssignForm((f) => ({ ...f, staff_id: e.target.value }))}
                  placeholder="staff_abc123"
                  className="w-full px-3 py-2 rounded-lg bg-white/5 border border-[var(--stroke)] text-sm text-[var(--foreground)] placeholder:text-[var(--color-muted)] focus:outline-none focus:border-[var(--gold-500)]/50 transition-colors"
                />
              </div>
              <div>
                <label className="text-xs text-[var(--color-muted)] mb-1 block">Appointment ID</label>
                <input
                  type="text"
                  value={assignForm.appointment_id}
                  onChange={(e) => setAssignForm((f) => ({ ...f, appointment_id: e.target.value }))}
                  placeholder="appt_xyz789"
                  className="w-full px-3 py-2 rounded-lg bg-white/5 border border-[var(--stroke)] text-sm text-[var(--foreground)] placeholder:text-[var(--color-muted)] focus:outline-none focus:border-[var(--gold-500)]/50 transition-colors"
                />
              </div>
            </div>
            <button
              type="submit"
              disabled={assigning}
              className="w-full py-2.5 rounded-xl bg-[var(--gold-500)] text-[#07111c] font-semibold text-sm hover:opacity-90 transition-opacity disabled:opacity-50"
            >
              {assigning ? <span className="flex items-center justify-center gap-2"><span className="spinner h-3.5 w-3.5" />Assigning…</span> : "Assign Staff"}
            </button>
          </form>
        </section>

        {/* View staff schedule */}
        <section className="glass-panel p-5">
          <h2 className="text-sm font-semibold text-[var(--foreground)] mb-4 flex items-center gap-2">
            <Clock className="h-4 w-4 text-[var(--gold-500)]" />
            View Staff Schedule
          </h2>
          <form onSubmit={handleLoadSchedule} className="flex gap-2 mb-4">
            <input
              type="text"
              value={scheduleStaffId}
              onChange={(e) => setScheduleStaffId(e.target.value)}
              placeholder="staff_abc123"
              className="flex-1 px-3 py-2 rounded-lg bg-white/5 border border-[var(--stroke)] text-sm text-[var(--foreground)] placeholder:text-[var(--color-muted)] focus:outline-none focus:border-[var(--gold-500)]/50 transition-colors"
            />
            <button
              type="submit"
              disabled={loadingSchedule}
              className="px-4 py-2 rounded-lg bg-white/8 border border-[var(--stroke)] text-sm font-medium text-[var(--foreground)] hover:bg-white/12 transition-colors disabled:opacity-50"
            >
              {loadingSchedule ? "Loading…" : "Load"}
            </button>
          </form>
          {schedule && (
            scheduleEntries.length === 0 ? (
              <p className="text-sm text-[var(--color-muted)] text-center py-2">No schedule entries found.</p>
            ) : (
              <div className="divide-y divide-[var(--stroke)]">
                {scheduleEntries.map((entry, i) => (
                  <div key={i} className="py-2 first:pt-0 last:pb-0 flex items-center gap-3 text-sm">
                    <span className="w-10 text-[var(--color-muted)] flex-shrink-0">
                      {DAYS[Number(entry.day_of_week ?? 0)] ?? "?"}
                    </span>
                    <span className="text-[var(--foreground)]">
                      {String(entry.start_time ?? "—")} – {String(entry.end_time ?? "—")}
                    </span>
                  </div>
                ))}
              </div>
            )
          )}
        </section>

        {/* Upsert schedule */}
        <section className="glass-panel p-5">
          <h2 className="text-sm font-semibold text-[var(--foreground)] mb-4">Update Schedule Entry</h2>
          <form onSubmit={handleSetSchedule} className="space-y-3">
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div>
                <label className="text-xs text-[var(--color-muted)] mb-1 block">Staff ID</label>
                <input
                  type="text"
                  value={scheduleForm.staff_id}
                  onChange={(e) => setScheduleForm((f) => ({ ...f, staff_id: e.target.value }))}
                  placeholder="staff_abc123"
                  className="w-full px-3 py-2 rounded-lg bg-white/5 border border-[var(--stroke)] text-sm text-[var(--foreground)] placeholder:text-[var(--color-muted)] focus:outline-none focus:border-[var(--gold-500)]/50 transition-colors"
                />
              </div>
              <div>
                <label className="text-xs text-[var(--color-muted)] mb-1 block">Day of Week</label>
                <select
                  value={scheduleForm.day_of_week}
                  onChange={(e) => setScheduleForm((f) => ({ ...f, day_of_week: e.target.value }))}
                  className="w-full px-3 py-2 rounded-lg bg-white/5 border border-[var(--stroke)] text-sm text-[var(--foreground)] focus:outline-none focus:border-[var(--gold-500)]/50 transition-colors"
                >
                  {DAYS.map((d, idx) => (
                    <option key={d} value={String(idx)}>{d}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="text-xs text-[var(--color-muted)] mb-1 block">Start Time</label>
                <input
                  type="time"
                  value={scheduleForm.start_time}
                  onChange={(e) => setScheduleForm((f) => ({ ...f, start_time: e.target.value }))}
                  className="w-full px-3 py-2 rounded-lg bg-white/5 border border-[var(--stroke)] text-sm text-[var(--foreground)] focus:outline-none focus:border-[var(--gold-500)]/50 transition-colors"
                />
              </div>
              <div>
                <label className="text-xs text-[var(--color-muted)] mb-1 block">End Time</label>
                <input
                  type="time"
                  value={scheduleForm.end_time}
                  onChange={(e) => setScheduleForm((f) => ({ ...f, end_time: e.target.value }))}
                  className="w-full px-3 py-2 rounded-lg bg-white/5 border border-[var(--stroke)] text-sm text-[var(--foreground)] focus:outline-none focus:border-[var(--gold-500)]/50 transition-colors"
                />
              </div>
            </div>
            <button
              type="submit"
              disabled={settingSchedule}
              className="w-full py-2.5 rounded-xl bg-[var(--gold-500)] text-[#07111c] font-semibold text-sm hover:opacity-90 transition-opacity disabled:opacity-50"
            >
              {settingSchedule ? <span className="flex items-center justify-center gap-2"><span className="spinner h-3.5 w-3.5" />Saving…</span> : "Save Schedule"}
            </button>
          </form>
        </section>

      </div>
    </div>
  );
}
