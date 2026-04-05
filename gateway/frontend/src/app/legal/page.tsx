/**
 * Legal industry landing page — SSR, no "use client".
 * Targets: AI agent for law firms, legal client intake AI, consultation scheduling automation.
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
  FileText,
  Users,
  TrendingUp,
  Scale,
  MessageSquare,
  Briefcase,
  Phone,
} from "lucide-react";

// ─── SEO metadata ──────────────────────────────────────────────────────────────

export const metadata: Metadata = {
  title: "AI Agent for Law Firms | DingDawg",
  description:
    "Streamline client intake, schedule consultations, answer case status questions, and manage document requests with an AI agent built for law firms and attorneys.",
  openGraph: {
    title: "AI Agent for Law Firms | DingDawg",
    description:
      "Automate client intake, consultation scheduling, and case status updates. DingDawg is the AI paralegal your firm needs.",
    type: "website",
  },
  keywords: [
    "AI agent for law firms",
    "legal client intake AI",
    "law firm chatbot",
    "consultation scheduling automation",
    "legal automation software",
    "attorney AI assistant",
    "case status update automation",
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

export default function LegalPage() {
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
          <Scale className="h-3.5 w-3.5 text-[var(--gold-500)]" />
          <span className="text-xs font-medium text-[var(--gold-500)]">
            Built for Law Firms
          </span>
        </div>

        <h1 className="font-heading text-4xl sm:text-5xl md:text-6xl font-bold text-[var(--foreground)] leading-[1.1] tracking-tight mb-6 heading-depth">
          Your firm deserves
          <br />
          <span className="text-gradient-gold">an AI that works after hours.</span>
        </h1>

        <p className="text-lg sm:text-xl text-[var(--color-muted)] max-w-2xl mx-auto leading-relaxed mb-4">
          DingDawg handles new client intake, consultation scheduling, case status
          updates, and document collection requests — so your attorneys spend time
          practicing law, not answering routine client calls.
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
          Turn intake into revenue. Automatically.
        </h2>
        <p className="text-center text-sm text-[var(--color-muted)] mb-10 max-w-xl mx-auto">
          Every potential client who contacts your firm after hours is a billable case.
          Your AI agent captures them all.
        </p>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          <UseCaseCard
            icon={<Users className="h-4 w-4 text-[var(--gold-500)]" />}
            title="Client Intake"
            description="Collect matter type, opposing parties, urgency, and contact details through a structured AI conversation before a human ever gets involved."
          />
          <UseCaseCard
            icon={<Calendar className="h-4 w-4 text-[var(--gold-500)]" />}
            title="Consultation Scheduling"
            description="Let prospects book initial consultations directly from your website or a shared link — synced to your calendar with automated confirmations."
          />
          <UseCaseCard
            icon={<MessageSquare className="h-4 w-4 text-[var(--gold-500)]" />}
            title="Case Status Updates"
            description="Clients can ask for status updates via chat and get instant responses based on the latest notes — reducing check-in calls by 60%."
          />
          <UseCaseCard
            icon={<FileText className="h-4 w-4 text-[var(--gold-500)]" />}
            title="Document Requests"
            description="Automate requests for discovery documents, signed retainers, and supporting materials. Track what has and hasn't been received."
          />
          <UseCaseCard
            icon={<Phone className="h-4 w-4 text-[var(--gold-500)]" />}
            title="After-Hours Intake"
            description="Capture emergency and after-hours inquiries with triage questions. Route urgent matters to on-call staff immediately."
          />
          <UseCaseCard
            icon={<Briefcase className="h-4 w-4 text-[var(--gold-500)]" />}
            title="Billing Reminders"
            description="Send automated invoice reminders and outstanding balance notifications. Reduce collections time and awkward conversations."
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
            Every unanswered inquiry is a lost case.
            <br />
            <span className="text-gradient-gold">Stop leaving fees on the table.</span>
          </h2>
          <p className="text-[var(--color-muted)] mb-8 max-w-md mx-auto leading-relaxed">
            50 free actions. 60-second setup. No credit card.
            <br />
            Your legal AI agent is ready to work.
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
