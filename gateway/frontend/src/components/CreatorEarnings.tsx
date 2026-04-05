"use client";

import React, { useEffect, useState } from "react";

interface Balance {
  available_cents: number;
  pending_cents: number;
}

interface Payout {
  id: string;
  amount_cents: number;
  status: "paid" | "pending" | "in_transit" | "canceled" | "failed";
  arrival_date: number;
  description: string;
}

interface CreatorEarningsProps {
  connectedAccountId?: string;
}

const STATUS_COLORS: Record<string, string> = {
  paid:       "text-green-400 bg-green-400/10 border-green-400/20",
  in_transit: "text-yellow-400 bg-yellow-400/10 border-yellow-400/20",
  pending:    "text-blue-400 bg-blue-400/10 border-blue-400/20",
  canceled:   "text-red-400 bg-red-400/10 border-red-400/20",
  failed:     "text-red-400 bg-red-400/10 border-red-400/20",
};

function formatUSD(cents: number): string {
  return (cents / 100).toLocaleString("en-US", { style: "currency", currency: "USD" });
}

function formatDate(unix: number): string {
  return new Date(unix * 1000).toLocaleDateString("en-US", {
    month: "short", day: "numeric", year: "numeric",
  });
}

export default function CreatorEarnings({ connectedAccountId }: CreatorEarningsProps) {
  const [balance, setBalance] = useState<Balance | null>(null);
  const [payouts, setPayouts] = useState<Payout[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [connecting, setConnecting] = useState(false);

  useEffect(() => {
    if (!connectedAccountId) {
      setLoading(false);
      return;
    }
    Promise.all([
      fetch("/api/v1/payments/connect/balance", { credentials: "include" })
        .then((r) => r.json()),
      fetch("/api/v1/payments/connect/payouts", { credentials: "include" })
        .then((r) => r.json()),
    ])
      .then(([bal, pays]) => {
        if (bal.error) throw new Error(bal.error);
        setBalance(bal);
        setPayouts(Array.isArray(pays) ? pays : []);
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [connectedAccountId]);

  const handleConnect = async () => {
    setConnecting(true);
    try {
      const res = await fetch("/api/v1/payments/connect/create-account", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
      });
      const data = await res.json();
      if (data.onboarding_url) {
        window.location.href = data.onboarding_url;
      } else {
        setError(data.error || "Failed to create Connect account");
      }
    } catch {
      setError("Network error — please try again");
    } finally {
      setConnecting(false);
    }
  };

  // ── Not yet connected ────────────────────────────────────────────────────
  if (!connectedAccountId) {
    return (
      <div className="rounded-2xl border border-white/[0.08] bg-[#0c1d35]/50 p-8 text-center">
        <div className="mb-4 text-4xl">💰</div>
        <h2 className="mb-2 text-xl font-bold text-[#f4f4f5]">Connect your Stripe account</h2>
        <p className="mb-6 text-sm text-[#a1a1aa]">
          Connect a Stripe account to receive 80% of every agent sale automatically.
        </p>
        <div className="mb-6 inline-flex items-center gap-2 rounded-full border border-[#F9C40E]/30 bg-[#F9C40E]/10 px-4 py-2 text-sm font-semibold text-[#F9C40E]">
          You earn 80% · DingDawg retains 20% platform fee
        </div>
        <div>
          <button
            onClick={handleConnect}
            disabled={connecting}
            className="rounded-xl bg-[#F9C40E] px-6 py-3 text-sm font-bold text-black transition-colors hover:bg-[#FFD23A] disabled:opacity-60"
          >
            {connecting ? "Connecting…" : "Connect Stripe Account →"}
          </button>
        </div>
        {error && <p className="mt-4 text-sm text-red-400">{error}</p>}
      </div>
    );
  }

  // ── Loading ──────────────────────────────────────────────────────────────
  if (loading) {
    return (
      <div className="rounded-2xl border border-white/[0.08] bg-[#0c1d35]/50 p-8 text-center text-sm text-[#71717a]">
        Loading earnings…
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-2xl border border-red-400/20 bg-red-400/5 p-6 text-center text-sm text-red-400">
        {error}
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      {/* Revenue share reminder */}
      <div className="flex items-center gap-3 rounded-xl border border-[#F9C40E]/20 bg-[#F9C40E]/5 px-4 py-3 text-sm text-[#F9C40E]">
        <span className="text-lg">💡</span>
        <span>
          You earn <strong>80%</strong> of every sale. DingDawg retains{" "}
          <strong>20%</strong> as the platform fee. Payouts are automatic via Stripe.
        </span>
      </div>

      {/* Balance cards */}
      {balance && (
        <div className="grid grid-cols-2 gap-4">
          <div className="rounded-2xl border border-green-400/20 bg-green-400/5 p-5">
            <p className="mb-1 text-xs font-medium text-[#71717a]">Available</p>
            <p className="text-2xl font-black text-green-400">
              {formatUSD(balance.available_cents)}
            </p>
            <p className="mt-1 text-xs text-[#71717a]">Ready for payout</p>
          </div>
          <div className="rounded-2xl border border-yellow-400/20 bg-yellow-400/5 p-5">
            <p className="mb-1 text-xs font-medium text-[#71717a]">Pending</p>
            <p className="text-2xl font-black text-yellow-400">
              {formatUSD(balance.pending_cents)}
            </p>
            <p className="mt-1 text-xs text-[#71717a]">Processing (2-7 days)</p>
          </div>
        </div>
      )}

      {/* Payouts table */}
      <div className="rounded-2xl border border-white/[0.08] bg-[#0c1d35]/50 overflow-hidden">
        <div className="border-b border-white/[0.06] px-5 py-4">
          <h3 className="text-sm font-semibold text-[#f4f4f5]">Recent Payouts</h3>
        </div>
        {payouts.length === 0 ? (
          <p className="px-5 py-8 text-center text-sm text-[#71717a]">
            No payouts yet. Payouts appear once you have available balance.
          </p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-white/[0.06] text-xs text-[#71717a]">
                <th className="px-5 py-3 text-left font-medium">Date</th>
                <th className="px-5 py-3 text-left font-medium">Description</th>
                <th className="px-5 py-3 text-left font-medium">Status</th>
                <th className="px-5 py-3 text-right font-medium">Amount</th>
              </tr>
            </thead>
            <tbody>
              {payouts.map((payout) => (
                <tr
                  key={payout.id}
                  className="border-b border-white/[0.04] transition-colors last:border-0 hover:bg-white/[0.02]"
                >
                  <td className="px-5 py-3 text-[#a1a1aa]">
                    {formatDate(payout.arrival_date)}
                  </td>
                  <td className="px-5 py-3 text-[#a1a1aa]">
                    {payout.description || "Automatic payout"}
                  </td>
                  <td className="px-5 py-3">
                    <span
                      className={`inline-flex rounded-full border px-2 py-0.5 text-xs font-semibold capitalize ${
                        STATUS_COLORS[payout.status] ?? "text-[#a1a1aa]"
                      }`}
                    >
                      {payout.status.replace("_", " ")}
                    </span>
                  </td>
                  <td className="px-5 py-3 text-right font-semibold text-[#f4f4f5]">
                    {formatUSD(payout.amount_cents)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
