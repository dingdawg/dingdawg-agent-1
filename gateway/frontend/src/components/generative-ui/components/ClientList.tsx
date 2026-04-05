"use client";

import { Users, Circle } from "lucide-react";
import { cn } from "@/lib/utils";
import type { ClientListProps } from "../catalog";

const statusConfig = {
  active: { label: "Active", color: "text-green-400", dot: "bg-green-400" },
  inactive: { label: "Inactive", color: "text-[var(--color-muted)]", dot: "bg-gray-500" },
  pending: { label: "Pending", color: "text-yellow-400", dot: "bg-yellow-400" },
};

export function ClientList({ clients, title = "Clients" }: ClientListProps) {
  return (
    <div className="glass-panel-gold rounded-xl p-4 space-y-3 card-enter">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Users className="h-4 w-4 text-[var(--gold-500)]" />
          <span className="text-sm font-heading font-semibold text-[var(--foreground)]">
            {title}
          </span>
        </div>
        <span className="text-xs text-[var(--color-muted)]">{clients.length} total</span>
      </div>

      <div className="space-y-2">
        {clients.slice(0, 6).map((client) => {
          const status = statusConfig[client.status];
          return (
            <div
              key={client.id}
              className="flex items-center justify-between bg-white/5 rounded-lg px-3 py-2"
            >
              <div className="flex flex-col gap-0.5 min-w-0">
                <span className="text-sm font-body text-[var(--foreground)] truncate">
                  {client.name}
                </span>
                {client.email && (
                  <span className="text-xs text-[var(--color-muted)] truncate">
                    {client.email}
                  </span>
                )}
              </div>
              <div className="flex flex-col items-end gap-1 shrink-0 ml-3">
                <div className={cn("flex items-center gap-1 text-xs", status.color)}>
                  <span className={cn("h-1.5 w-1.5 rounded-full", status.dot)} />
                  {status.label}
                </div>
                {client.lastVisit && (
                  <span className="text-xs text-[var(--color-muted)]">
                    {client.lastVisit}
                  </span>
                )}
              </div>
            </div>
          );
        })}
        {clients.length > 6 && (
          <p className="text-xs text-center text-[var(--color-muted)] py-1">
            +{clients.length - 6} more clients
          </p>
        )}
      </div>
    </div>
  );
}
