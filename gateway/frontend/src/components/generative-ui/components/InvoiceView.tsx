"use client";

import { FileText } from "lucide-react";
import { cn } from "@/lib/utils";
import type { InvoiceViewProps } from "../catalog";

const statusConfig = {
  draft: { label: "Draft", color: "text-[var(--color-muted)]", bg: "bg-gray-500/10" },
  pending: { label: "Pending", color: "text-yellow-400", bg: "bg-yellow-500/10" },
  paid: { label: "Paid", color: "text-green-400", bg: "bg-green-500/10" },
  overdue: { label: "Overdue", color: "text-red-400", bg: "bg-red-500/10" },
};

function formatCurrency(amount: number): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
  }).format(amount);
}

export function InvoiceView({
  invoiceNumber,
  clientName,
  items,
  subtotal,
  tax,
  total,
  status,
  dueDate,
}: InvoiceViewProps) {
  const statusStyle = statusConfig[status];

  return (
    <div className="glass-panel-gold rounded-xl p-4 space-y-4 card-enter">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div className="flex items-center gap-2">
          <FileText className="h-4 w-4 text-[var(--gold-500)]" />
          <div>
            <p className="text-sm font-heading font-semibold text-[var(--foreground)]">
              Invoice{invoiceNumber ? ` #${invoiceNumber}` : ""}
            </p>
            {clientName && (
              <p className="text-xs text-[var(--color-muted)]">{clientName}</p>
            )}
          </div>
        </div>
        <div className="flex flex-col items-end gap-1">
          <span
            className={cn(
              "text-xs font-medium px-2 py-0.5 rounded-full",
              statusStyle.color,
              statusStyle.bg
            )}
          >
            {statusStyle.label}
          </span>
          {dueDate && (
            <span className="text-xs text-[var(--color-muted)]">Due {dueDate}</span>
          )}
        </div>
      </div>

      {/* Line items */}
      <div className="space-y-1">
        <div className="grid grid-cols-12 gap-2 px-2 pb-1 border-b border-white/10">
          <span className="col-span-6 text-xs text-[var(--color-muted)] uppercase tracking-wider">
            Item
          </span>
          <span className="col-span-2 text-xs text-[var(--color-muted)] uppercase tracking-wider text-center">
            Qty
          </span>
          <span className="col-span-2 text-xs text-[var(--color-muted)] uppercase tracking-wider text-right">
            Price
          </span>
          <span className="col-span-2 text-xs text-[var(--color-muted)] uppercase tracking-wider text-right">
            Total
          </span>
        </div>
        {items.map((item, i) => (
          <div
            key={i}
            className="grid grid-cols-12 gap-2 px-2 py-1.5 bg-white/5 rounded-lg"
          >
            <span className="col-span-6 text-sm font-body text-[var(--foreground)] truncate">
              {item.description}
            </span>
            <span className="col-span-2 text-sm text-[var(--color-muted)] text-center">
              {item.quantity}
            </span>
            <span className="col-span-2 text-sm text-[var(--color-muted)] text-right">
              {formatCurrency(item.unitPrice)}
            </span>
            <span className="col-span-2 text-sm text-[var(--foreground)] text-right font-medium">
              {formatCurrency(item.total)}
            </span>
          </div>
        ))}
      </div>

      {/* Totals */}
      <div className="space-y-1 border-t border-white/10 pt-3">
        {subtotal != null && (
          <div className="flex justify-between text-sm">
            <span className="text-[var(--color-muted)]">Subtotal</span>
            <span className="text-[var(--foreground)]">{formatCurrency(subtotal)}</span>
          </div>
        )}
        {tax != null && (
          <div className="flex justify-between text-sm">
            <span className="text-[var(--color-muted)]">Tax</span>
            <span className="text-[var(--foreground)]">{formatCurrency(tax)}</span>
          </div>
        )}
        <div className="flex justify-between text-base font-heading font-bold pt-1">
          <span className="text-[var(--foreground)]">Total</span>
          <span className="text-[var(--gold-500)]">{formatCurrency(total)}</span>
        </div>
      </div>
    </div>
  );
}
