"use client";

/**
 * CalendarCard — date/time picker embedded in the chat stream.
 *
 * Renders a month grid view. If availableSlots is provided, only those
 * dates are selectable. After a date is selected, a time picker dropdown
 * appears (when times are available for that date). onSelect is called
 * with the final Date object (date + time combined).
 *
 * No external calendar library dependency — pure React + Tailwind.
 */

import { useState, useMemo, useCallback } from "react";
import { ChevronLeft, ChevronRight, Clock } from "lucide-react";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface DateSlot {
  date: Date;
  times: string[];
}

interface CalendarCardProps {
  availableSlots?: DateSlot[];
  onSelect: (date: Date) => void;
  minDate?: Date;
  maxDate?: Date;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const DAY_NAMES = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const MONTH_NAMES = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function isSameDay(a: Date, b: Date): boolean {
  return (
    a.getFullYear() === b.getFullYear() &&
    a.getMonth() === b.getMonth() &&
    a.getDate() === b.getDate()
  );
}

function dateKey(d: Date): string {
  return `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`;
}

function zeroed(d: Date): Date {
  const copy = new Date(d);
  copy.setHours(0, 0, 0, 0);
  return copy;
}

function parseTimeString(date: Date, timeStr: string): Date {
  // Parse "10:00 AM" / "2:30 PM" format
  const result = new Date(date);
  const match = timeStr.match(/^(\d{1,2}):(\d{2})\s*(AM|PM)?$/i);
  if (!match) return result;

  let hours = parseInt(match[1], 10);
  const minutes = parseInt(match[2], 10);
  const meridiem = match[3]?.toUpperCase();

  if (meridiem === "PM" && hours < 12) hours += 12;
  if (meridiem === "AM" && hours === 12) hours = 0;

  result.setHours(hours, minutes, 0, 0);
  return result;
}

/** Returns an array of Date objects for all days in the given month/year. */
function buildMonthGrid(year: number, month: number): (Date | null)[] {
  const firstDay = new Date(year, month, 1).getDay(); // 0=Sun
  const daysInMonth = new Date(year, month + 1, 0).getDate();
  const grid: (Date | null)[] = [];

  // Leading nulls for alignment
  for (let i = 0; i < firstDay; i++) grid.push(null);
  for (let d = 1; d <= daysInMonth; d++) grid.push(new Date(year, month, d));

  return grid;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function CalendarCard({
  availableSlots,
  onSelect,
  minDate,
  maxDate,
}: CalendarCardProps) {
  const todayZero = useMemo(() => zeroed(new Date()), []);
  const [viewYear, setViewYear] = useState(todayZero.getFullYear());
  const [viewMonth, setViewMonth] = useState(todayZero.getMonth());
  const [selectedDate, setSelectedDate] = useState<Date | null>(null);
  const [selectedTime, setSelectedTime] = useState<string>("");

  // Build slot map for O(1) lookup
  const slotMap = useMemo<Map<string, string[]>>(() => {
    if (!availableSlots) return new Map();
    const m = new Map<string, string[]>();
    for (const s of availableSlots) {
      m.set(dateKey(zeroed(s.date)), s.times);
    }
    return m;
  }, [availableSlots]);

  const grid = useMemo(
    () => buildMonthGrid(viewYear, viewMonth),
    [viewYear, viewMonth]
  );

  const isDateEnabled = useCallback(
    (d: Date): boolean => {
      const dz = zeroed(d);
      if (minDate && dz < zeroed(minDate)) return false;
      if (maxDate && dz > zeroed(maxDate)) return false;
      if (availableSlots) return slotMap.has(dateKey(dz));
      return true;
    },
    [availableSlots, slotMap, minDate, maxDate]
  );

  const handleDayClick = useCallback(
    (d: Date) => {
      if (!isDateEnabled(d)) return;
      setSelectedDate(d);
      setSelectedTime("");

      // If no slot times, call onSelect immediately with date (midnight)
      if (!availableSlots) {
        onSelect(d);
      }
    },
    [isDateEnabled, availableSlots, onSelect]
  );

  const handleTimeSelect = useCallback(
    (timeStr: string) => {
      if (!selectedDate) return;
      setSelectedTime(timeStr);
      const full = parseTimeString(selectedDate, timeStr);
      onSelect(full);
    },
    [selectedDate, onSelect]
  );

  const goToPrevMonth = useCallback(() => {
    setViewMonth((m) => {
      if (m === 0) {
        setViewYear((y) => y - 1);
        return 11;
      }
      return m - 1;
    });
  }, []);

  const goToNextMonth = useCallback(() => {
    setViewMonth((m) => {
      if (m === 11) {
        setViewYear((y) => y + 1);
        return 0;
      }
      return m + 1;
    });
  }, []);

  const timesForSelected = selectedDate
    ? slotMap.get(dateKey(zeroed(selectedDate))) ?? []
    : [];

  return (
    <div className="glass-panel-gold p-4 card-enter">
      {/* Month navigation */}
      <div className="flex items-center justify-between mb-3">
        <button
          onClick={goToPrevMonth}
          aria-label="Previous month"
          className="h-8 w-8 rounded-lg flex items-center justify-center bg-white/5 hover:bg-white/10 transition-colors text-[var(--foreground)]"
        >
          <ChevronLeft className="h-4 w-4" />
        </button>

        <span className="text-sm font-heading font-semibold text-[var(--foreground)]">
          {MONTH_NAMES[viewMonth]} {viewYear}
        </span>

        <button
          onClick={goToNextMonth}
          aria-label="Next month"
          className="h-8 w-8 rounded-lg flex items-center justify-center bg-white/5 hover:bg-white/10 transition-colors text-[var(--foreground)]"
        >
          <ChevronRight className="h-4 w-4" />
        </button>
      </div>

      {/* Day-of-week headers */}
      <div className="grid grid-cols-7 mb-1">
        {DAY_NAMES.map((day) => (
          <div
            key={day}
            className="text-center text-xs font-medium text-[var(--color-muted)] py-1"
          >
            {day}
          </div>
        ))}
      </div>

      {/* Date grid */}
      <div className="grid grid-cols-7 gap-0.5">
        {grid.map((day, i) => {
          if (!day) {
            return <div key={`empty-${i}`} />;
          }

          const enabled = isDateEnabled(day);
          const isToday = isSameDay(day, todayZero);
          const isSelected = selectedDate ? isSameDay(day, selectedDate) : false;

          return (
            <button
              key={day.toISOString()}
              onClick={() => handleDayClick(day)}
              disabled={!enabled}
              aria-disabled={!enabled}
              aria-current={isToday ? "date" : undefined}
              data-today={isToday ? "true" : undefined}
              className={[
                "h-9 w-full rounded-lg text-sm transition-colors",
                isSelected
                  ? "bg-[var(--gold-500)] text-[#07111c] font-semibold"
                  : enabled
                  ? "text-[var(--foreground)] hover:bg-white/10"
                  : "text-[var(--color-muted)] opacity-30 cursor-not-allowed",
                isToday && !isSelected
                  ? "ring-1 ring-[var(--gold-500)]/50"
                  : "",
              ]
                .filter(Boolean)
                .join(" ")}
            >
              {day.getDate()}
            </button>
          );
        })}
      </div>

      {/* Time selection — shown after date is selected and times exist */}
      {selectedDate && timesForSelected.length > 0 && (
        <div className="mt-4 pt-4 border-t border-[var(--color-gold-stroke)]">
          <div className="flex items-center gap-1.5 mb-2">
            <Clock className="h-3.5 w-3.5 text-[var(--color-muted)]" />
            <span className="text-xs font-medium text-[var(--color-muted)]">
              Select a time
            </span>
          </div>
          <div className="flex flex-wrap gap-2">
            {timesForSelected.map((t) => (
              <button
                key={t}
                onClick={() => handleTimeSelect(t)}
                data-time-slot={t}
                className={[
                  "px-3 py-2 rounded-lg text-sm font-medium border transition-colors min-h-[40px]",
                  selectedTime === t
                    ? "bg-[var(--gold-500)] text-[#07111c] border-[var(--gold-500)]"
                    : "bg-white/5 text-[var(--foreground)] border-[var(--color-gold-stroke)] hover:bg-white/10",
                ].join(" ")}
              >
                {t}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
