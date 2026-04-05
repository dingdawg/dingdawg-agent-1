"use client";

import { Calendar, CheckCircle2, Clock } from "lucide-react";
import type { BookingSummaryProps } from "../catalog";

export function BookingSummary({ total, completed, upcoming }: BookingSummaryProps) {
  const completionRate = total > 0 ? Math.round((completed / total) * 100) : 0;

  return (
    <div className="glass-panel-gold rounded-xl p-4 space-y-4 card-enter">
      {/* Header row */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Calendar className="h-4 w-4 text-[var(--gold-500)]" />
          <span className="text-sm font-heading font-semibold text-[var(--foreground)]">
            Booking Summary
          </span>
        </div>
        <span className="text-xs text-[var(--color-muted)] bg-white/5 px-2 py-0.5 rounded-full">
          {completionRate}% complete
        </span>
      </div>

      {/* Stats row */}
      <div className="flex gap-4">
        <div className="flex-1 text-center">
          <p className="text-2xl font-heading font-bold text-[var(--foreground)]">{total}</p>
          <p className="text-xs text-[var(--color-muted)]">Total</p>
        </div>
        <div className="w-px bg-white/10" />
        <div className="flex-1 text-center">
          <p className="text-2xl font-heading font-bold text-green-400">{completed}</p>
          <p className="text-xs text-[var(--color-muted)]">Completed</p>
        </div>
        <div className="w-px bg-white/10" />
        <div className="flex-1 text-center">
          <p className="text-2xl font-heading font-bold text-[var(--gold-500)]">
            {upcoming.length}
          </p>
          <p className="text-xs text-[var(--color-muted)]">Upcoming</p>
        </div>
      </div>

      {/* Upcoming list */}
      {upcoming.length > 0 && (
        <div className="space-y-2">
          <p className="text-xs font-medium text-[var(--color-muted)] uppercase tracking-wider">
            Upcoming
          </p>
          {upcoming.slice(0, 4).map((booking) => (
            <div
              key={booking.id}
              className="flex items-start justify-between bg-white/5 rounded-lg px-3 py-2"
            >
              <div className="flex flex-col gap-0.5">
                <span className="text-sm font-body text-[var(--foreground)]">
                  {booking.clientName}
                </span>
                <span className="text-xs text-[var(--color-muted)]">{booking.service}</span>
              </div>
              <div className="flex flex-col items-end gap-0.5">
                <span className="text-xs text-[var(--foreground)]">{booking.date}</span>
                <div className="flex items-center gap-1 text-xs text-[var(--color-muted)]">
                  <Clock className="h-3 w-3" />
                  {booking.time}
                </div>
              </div>
            </div>
          ))}
          {upcoming.length > 4 && (
            <p className="text-xs text-center text-[var(--color-muted)]">
              +{upcoming.length - 4} more bookings
            </p>
          )}
        </div>
      )}

      {upcoming.length === 0 && completed === total && total > 0 && (
        <div className="flex items-center justify-center gap-2 py-2 text-green-400">
          <CheckCircle2 className="h-4 w-4" />
          <span className="text-sm font-body">All bookings completed</span>
        </div>
      )}
    </div>
  );
}
