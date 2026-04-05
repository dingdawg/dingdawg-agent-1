/**
 * Automotive industry landing page — SSR, no "use client".
 * Targets: AI agent for auto dealerships, service appointment scheduling AI, automotive chatbot.
 */

import type { Metadata } from "next";
import Link from "next/link";
import Image from "next/image";
import {
  ArrowRight,
  Calendar,
  Shield,
  CheckCircle,
  Clock,
  TrendingUp,
  Car,
  Wrench,
  Phone,
  Bell,
  MessageSquare,
  FileText,
} from "lucide-react";

// ─── SEO metadata ──────────────────────────────────────────────────────────────

export const metadata: Metadata = {
  title: "AI Agent for Automotive | DingDawg",
  description:
    "Book service appointments, schedule test drives, answer parts inquiries, and send recall notifications automatically with an AI agent built for auto dealerships and shops.",
  openGraph: {
    title: "AI Agent for Automotive | DingDawg",
    description:
      "Automate service scheduling, test drive bookings, and recall notifications. DingDawg is the AI agent every auto dealership and shop needs.",
    type: "website",
  },
  keywords: [
    "AI agent for auto dealerships",
    "automotive chatbot",
    "service appointment scheduling AI",
    "test drive booking automation",
    "parts inquiry AI",
    "auto dealer automation",
    "recall notification system",
  ],
};

// ─── Sub-components ───────────────────────────────────────────────────────────

function UseCaseCard({
  icon,
  title,
  description,
}: {
  icon: React.ReactNode;
  title: string;
  description: string;
}) {
  return (
    <div className="glass-panel p-5 flex flex-col gap-2.5 hover:border-[var(--gold-500)]/30 transition-all duration-200 group relative overflow-hidden">
      <div className="absolute left-0 top-0 bottom-0 w-[2px] bg-[var(--gold-500)] rounded-l-[22px] opacity-0 group-hover:opacity-100 transition-opacity duration-200" />
      <div className="flex items-center gap-3">
        <div className="flex-shrink-0 flex items-center justify-center w-9 h-9 rounded-lg bg-[var(--gold-500)]/10 border border-[var(--gold-500)]/20 group-hover:bg-[var(--gold-500)]/15 transition-colors duration-200">
          {icon}
        </div>
        <h3 className="font-heading text-[15px] font-semibold text-[var(--foreground)] leading-tight">
          {title}
        </h3>
      </div>
      <p className="text-xs text-[var(--color-muted)] leading-relaxed pl-0.5">
        {description}
      </p>
    </div>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function AutomotivePage() {
  return (
    <div className="min-h-screen">
      {/* ── Nav ──────────────────────────────────────────────────────────── */}
      <nav
        className="flex items-center justify-between px-6 py-4 max-w-5xl mx-auto"
        style={{ paddingTop: "calc(env(safe-area-inset-top, 0px) + 16px)" }}
      >
        <div className="flex items-center gap-2">
          <Image src="/icons/logo.png" alt="DingDawg" width={40} height={32} priority />
          <span className="font-heading font-bold text-[var(--foreground)] text-lg tracking-tight">
            DingDawg
          </span>
        </div>
        <div className="flex items-center gap-4">
          <Link href="/explore" className="text-sm text-[var(--color-muted)] hover:text-[var(--foreground)] transition-colors hidden sm:inline">
            Explore
          </Link>
          <Link href="/billing" className="text-sm text-[var(--color-muted)] hover:text-[var(--foreground)] transition-colors hidden sm:inline">
            Pricing
          </Link>
          <Link href="/login" className="text-sm text-[var(--color-muted)] hover:text-[var(--foreground)] transition-colors">
            Sign In
          </Link>
          <Link href="/claim" className="text-sm px-4 py-2 rounded-lg bg-[var(--gold-500)] text-[#07111c] font-semibold hover:bg-[var(--gold-600)] transition-colors">
            Get Started
          </Link>
        </div>
      </nav>

      {/* ── Hero ─────────────────────────────────────────────────────────── */}
      <section className="px-6 pt-16 pb-12 max-w-5xl mx-auto text-center">
        <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full border border-[var(--gold-500)]/30 bg-[var(--gold-500)]/8 mb-8">
          <Car className="h-3.5 w-3.5 text-[var(--gold-500)]" />
          <span className="text-xs font-medium text-[var(--gold-500)]">
            Built for Automotive
          </span>
        </div>

        <h1 className="font-heading text-4xl sm:text-5xl md:text-6xl font-bold text-[var(--foreground)] leading-[1.1] tracking-tight mb-6 heading-depth">
          Your dealership deserves
          <br />
          <span className="text-gradient-gold">an AI that drives results.</span>
        </h1>

        <p className="text-lg sm:text-xl text-[var(--color-muted)] max-w-2xl mx-auto leading-relaxed mb-4">
          DingDawg schedules service appointments, books test drives, answers parts
          inquiries, and sends recall notifications — keeping your bays full and your
          customers informed without adding headcount to your BDC.
        </p>

        <p className="text-sm text-[var(--color-muted)] mb-10">
          50 free actions. No credit card. Set up in 60 seconds.
        </p>

        <div className="flex flex-col sm:flex-row items-center justify-center gap-4 mb-6">
          <Link
            href="/claim"
            className="inline-flex items-center gap-2 px-8 py-4 rounded-xl bg-[var(--gold-500)] text-[#07111c] font-semibold text-base hover:bg-[var(--gold-600)] hover:scale-[1.02] active:scale-[0.98] transition-all duration-200 shadow-[0_0_20px_rgba(246,180,0,0.20)]"
          >
            Get Started Free
            <ArrowRight className="h-4 w-4" />
          </Link>
          <Link
            href="/explore"
            className="inline-flex items-center gap-2 px-7 py-3.5 rounded-xl border border-[var(--stroke2)] text-[var(--foreground)] font-medium text-base hover:border-white/22 hover:bg-white/4 transition-all duration-200"
          >
            See Live Agents
          </Link>
        </div>

        <div className="flex flex-wrap items-center justify-center gap-x-6 gap-y-2 text-xs text-[var(--color-muted)]">
          <span className="flex items-center gap-1.5">
            <Shield className="h-3.5 w-3.5 text-green-400" />
            Enterprise-grade security
          </span>
          <span className="flex items-center gap-1.5">
            <CheckCircle className="h-3.5 w-3.5 text-green-400" />
            No credit card required
          </span>
          <span className="flex items-center gap-1.5">
            <Clock className="h-3.5 w-3.5 text-green-400" />
            60-second setup
          </span>
        </div>
      </section>

      {/* ── Use Cases ────────────────────────────────────────────────────── */}
      <section className="px-6 pb-20 max-w-5xl mx-auto">
        <h2 className="font-heading text-2xl sm:text-3xl font-bold text-[var(--foreground)] text-center mb-3">
          Keep your bays full. Keep your customers happy.
        </h2>
        <p className="text-center text-sm text-[var(--color-muted)] mb-10 max-w-xl mx-auto">
          From service drive to sales floor — your AI agent handles scheduling,
          follow-ups, and inquiries so your team closes and wrench-turns.
        </p>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          <UseCaseCard
            icon={<Wrench className="h-4 w-4 text-[var(--gold-500)]" />}
            title="Service Appointments"
            description="Let customers book oil changes, tire rotations, and major repairs online 24/7. Automated reminders reduce no-shows and same-day cancellations."
          />
          <UseCaseCard
            icon={<Car className="h-4 w-4 text-[var(--gold-500)]" />}
            title="Test Drive Scheduling"
            description="Convert website visitors to showroom appointments automatically. Capture vehicle interest and buyer readiness during the booking conversation."
          />
          <UseCaseCard
            icon={<FileText className="h-4 w-4 text-[var(--gold-500)]" />}
            title="Parts Inquiries"
            description="Answer questions about OEM vs aftermarket parts, pricing, availability, and lead times — 24/7 without tying up your parts counter."
          />
          <UseCaseCard
            icon={<Bell className="h-4 w-4 text-[var(--gold-500)]" />}
            title="Recall Notifications"
            description="Proactively notify customers about open recalls on their VIN and schedule service automatically. Improve safety and CSI scores simultaneously."
          />
          <UseCaseCard
            icon={<MessageSquare className="h-4 w-4 text-[var(--gold-500)]" />}
            title="Service Status Updates"
            description="Keep customers informed on vehicle status without them calling the service desk. Send automated updates when the car is ready."
          />
          <UseCaseCard
            icon={<Phone className="h-4 w-4 text-[var(--gold-500)]" />}
            title="Unsold Lead Follow-Up"
            description="Re-engage unsold showroom visitors and online leads with personalized follow-up messages. Recover deals that slipped through the cracks."
          />
        </div>
      </section>

      {/* ── Pricing ──────────────────────────────────────────────────────── */}
      <section className="px-6 pb-20 max-w-5xl mx-auto">
        <h2 className="font-heading text-2xl sm:text-3xl font-bold text-[var(--foreground)] text-center mb-3">
          Simple, honest pricing
        </h2>
        <p className="text-center text-sm text-[var(--color-muted)] mb-10">
          Pay only for what your agent does. No hidden fees. No contracts.
        </p>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 max-w-4xl mx-auto">
          <div className="glass-panel p-6 text-center">
            <p className="text-sm font-semibold text-[var(--color-muted)] mb-1">Free</p>
            <p className="font-heading text-3xl font-bold text-[var(--foreground)]">$0</p>
            <p className="text-xs text-[var(--color-muted)] mt-1 mb-4">50 actions/month</p>
            <Link href="/claim" className="inline-flex items-center justify-center w-full px-4 py-2.5 rounded-lg border border-[var(--stroke2)] text-sm font-medium text-[var(--foreground)] hover:bg-white/5 transition-colors">
              Start Free
            </Link>
          </div>
          <div className="glass-panel p-6 text-center">
            <p className="text-sm font-semibold text-[var(--color-muted)] mb-1">Starter</p>
            <p className="font-heading text-3xl font-bold text-[var(--foreground)]">$49.99</p>
            <p className="text-xs text-[var(--color-muted)] mt-1 mb-4">500 actions/month</p>
            <Link href="/claim" className="inline-flex items-center justify-center w-full px-4 py-2.5 rounded-lg border border-[var(--stroke2)] text-sm font-medium text-[var(--foreground)] hover:bg-white/5 transition-colors">
              Get Started
            </Link>
          </div>
          <div className="glass-panel-gold p-6 text-center relative">
            <div className="absolute -top-3 left-1/2 -translate-x-1/2 px-3 py-0.5 rounded-full bg-[var(--gold-500)] text-[#07111c] text-xs font-bold">
              Most Popular
            </div>
            <p className="text-sm font-semibold text-[var(--gold-500)] mb-1">Pro</p>
            <p className="font-heading text-3xl font-bold text-[var(--foreground)]">$79.99</p>
            <p className="text-xs text-[var(--color-muted)] mt-1 mb-4">2,000 actions/month</p>
            <Link href="/claim" className="inline-flex items-center justify-center w-full px-4 py-2.5 rounded-lg bg-[var(--gold-500)] text-[#07111c] text-sm font-semibold hover:bg-[var(--gold-600)] transition-colors">
              Get Started
            </Link>
          </div>
          <div className="glass-panel p-6 text-center">
            <p className="text-sm font-semibold text-[var(--color-muted)] mb-1">Enterprise</p>
            <p className="font-heading text-3xl font-bold text-[var(--foreground)]">$199.99</p>
            <p className="text-xs text-[var(--color-muted)] mt-1 mb-4">Unlimited actions</p>
            <Link href="/claim" className="inline-flex items-center justify-center w-full px-4 py-2.5 rounded-lg border border-[var(--stroke2)] text-sm font-medium text-[var(--foreground)] hover:bg-white/5 transition-colors">
              Contact Sales
            </Link>
          </div>
        </div>
      </section>

      {/* ── Bottom CTA ───────────────────────────────────────────────────── */}
      <section className="px-6 pb-24 max-w-5xl mx-auto text-center">
        <div className="glass-panel-gold cta-gradient-border p-10 sm:p-14">
          <h2 className="font-heading text-2xl sm:text-3xl font-bold text-[var(--foreground)] mb-4 heading-depth">
            Your service lane is full.
            <br />
            <span className="text-gradient-gold">Your AI can keep it that way.</span>
          </h2>
          <p className="text-[var(--color-muted)] mb-8 max-w-md mx-auto leading-relaxed">
            50 free actions. 60-second setup. No credit card.
            <br />
            Your automotive AI agent is ready.
          </p>
          <Link
            href="/claim"
            className="inline-flex items-center gap-2 px-8 py-4 rounded-xl bg-[var(--gold-500)] text-[#07111c] font-semibold text-base hover:bg-[var(--gold-600)] hover:scale-[1.02] active:scale-[0.98] transition-all duration-200 shadow-[0_0_24px_rgba(246,180,0,0.20)]"
          >
            Get Started Free
            <ArrowRight className="h-4 w-4" />
          </Link>
          <p className="text-xs text-[var(--color-muted)] mt-4 flex items-center justify-center gap-1.5">
            <TrendingUp className="h-3.5 w-3.5" />
            Start free — upgrade anytime
          </p>
        </div>
      </section>

      {/* ── Footer ───────────────────────────────────────────────────────── */}
      <footer className="px-6 pb-14 max-w-5xl mx-auto border-t border-[var(--stroke)]/60 pt-10">
        <div className="flex flex-col sm:flex-row items-center justify-between gap-6">
          <div className="flex items-center gap-2">
            <Image src="/icons/logo.png" alt="DingDawg" width={28} height={22} />
            <span className="text-sm text-[var(--color-muted)]">
              DingDawg &mdash; AI Agent for Small Business
            </span>
          </div>
          <div className="flex flex-wrap items-center justify-center gap-x-6 gap-y-2 text-sm text-[var(--color-muted)]">
            <Link href="/explore" className="hover:text-[var(--foreground)] transition-colors">Explore</Link>
            <Link href="/billing" className="hover:text-[var(--foreground)] transition-colors">Pricing</Link>
            <Link href="/privacy" className="hover:text-[var(--foreground)] transition-colors">Privacy</Link>
            <Link href="/terms" className="hover:text-[var(--foreground)] transition-colors">Terms</Link>
          </div>
        </div>
        <p className="text-center text-xs text-[var(--color-muted)] mt-8">
          &copy; 2026 Innovative Systems Global LLC. All rights reserved.
        </p>
      </footer>
    </div>
  );
}
