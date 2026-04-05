/**
 * Real Estate industry landing page — SSR, no "use client".
 * Targets: AI agent for real estate, real estate chatbot, lead capture AI.
 */

import type { Metadata } from "next";
import Link from "next/link";
import Image from "next/image";
import {
  ArrowRight,
  Bot,
  Calendar,
  MessageSquare,
  Shield,
  CheckCircle,
  Clock,
  Home,
  Phone,
  Users,
  FileText,
  TrendingUp,
  MapPin,
  Zap,
} from "lucide-react";

// ─── SEO metadata ──────────────────────────────────────────────────────────────

export const metadata: Metadata = {
  title: "AI Agent for Real Estate | DingDawg",
  description:
    "Capture leads 24/7, answer property inquiries, schedule showings, and automate follow-ups with an AI agent built for real estate agents and brokerages.",
  openGraph: {
    title: "AI Agent for Real Estate | DingDawg",
    description:
      "Never miss a lead again. DingDawg handles property inquiries, showing scheduling, and buyer follow-ups automatically.",
    type: "website",
  },
  keywords: [
    "AI agent for real estate",
    "real estate chatbot",
    "lead capture AI real estate",
    "property inquiry automation",
    "showing scheduling AI",
    "real estate lead follow-up",
    "real estate agent automation",
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

export default function RealEstatePage() {
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
          <Home className="h-3.5 w-3.5 text-[var(--gold-500)]" />
          <span className="text-xs font-medium text-[var(--gold-500)]">
            Built for Real Estate
          </span>
        </div>

        <h1 className="font-heading text-4xl sm:text-5xl md:text-6xl font-bold text-[var(--foreground)] leading-[1.1] tracking-tight mb-6 heading-depth">
          Never miss a lead.
          <br />
          <span className="text-gradient-gold">Your AI agent closes while you sleep.</span>
        </h1>

        <p className="text-lg sm:text-xl text-[var(--color-muted)] max-w-2xl mx-auto leading-relaxed mb-4">
          DingDawg captures buyer and seller leads around the clock, answers property
          questions instantly, schedules showings, and nurtures prospects with
          automated follow-ups — so you close more deals without more hours.
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
          Close more deals with less manual work
        </h2>
        <p className="text-center text-sm text-[var(--color-muted)] mb-10 max-w-xl mx-auto">
          Your AI agent works every lead from first contact to scheduled showing —
          automatically and professionally.
        </p>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          <UseCaseCard
            icon={<Users className="h-4 w-4 text-[var(--gold-500)]" />}
            title="Lead Capture"
            description="Engage website visitors instantly. Qualify buyers and sellers with smart intake questions and route hot leads to you immediately."
          />
          <UseCaseCard
            icon={<Home className="h-4 w-4 text-[var(--gold-500)]" />}
            title="Property Inquiries"
            description="Answer questions about listings — price, square footage, schools, neighborhood stats — 24/7 without picking up the phone."
          />
          <UseCaseCard
            icon={<Calendar className="h-4 w-4 text-[var(--gold-500)]" />}
            title="Showing Scheduling"
            description="Let prospects book private showings directly through chat. Sync to your calendar and send automated confirmation and reminder messages."
          />
          <UseCaseCard
            icon={<MessageSquare className="h-4 w-4 text-[var(--gold-500)]" />}
            title="Automated Follow-Ups"
            description="Send personalized follow-up messages after showings, open houses, and inquiries. Stay top of mind without manual outreach."
          />
          <UseCaseCard
            icon={<FileText className="h-4 w-4 text-[var(--gold-500)]" />}
            title="Document Requests"
            description="Collect pre-qualification info, preferred neighborhoods, and budget ranges before the first call. Walk in prepared every time."
          />
          <UseCaseCard
            icon={<MapPin className="h-4 w-4 text-[var(--gold-500)]" />}
            title="Market Updates"
            description="Send automated market reports and new listing alerts to your database. Keep your pipeline warm without lifting a finger."
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
            Every lead deserves a fast response.
            <br />
            <span className="text-gradient-gold">Yours will get one.</span>
          </h2>
          <p className="text-[var(--color-muted)] mb-8 max-w-md mx-auto leading-relaxed">
            50 free actions. 60-second setup. No credit card.
            <br />
            Your real estate AI agent is ready.
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
