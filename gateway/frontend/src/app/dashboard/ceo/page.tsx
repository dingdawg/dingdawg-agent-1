'use client';

import { useState, useEffect, useCallback } from 'react';

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */
type RevenuePeriod = 'mrr' | 'today' | 'week' | 'month';

interface NpmDownloads {
  downloads: number;
  package: string;
}

interface Product {
  name: string;
  slug: string;
  version: string;
  status: 'live' | 'beta' | 'down';
  downloads: number;
}

interface Activity {
  id: string;
  avatar: string;
  text: string;
  time: string;
}

/* ------------------------------------------------------------------ */
/*  Sparkline SVG (30-day mini chart)                                  */
/* ------------------------------------------------------------------ */
function Sparkline({ data, color }: { data: number[]; color: string }) {
  const max = Math.max(...data, 1);
  const w = 200;
  const h = 40;
  const points = data
    .map((v, i) => `${(i / (data.length - 1)) * w},${h - (v / max) * h}`)
    .join(' ');
  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="w-full h-10 mt-2">
      <polyline
        fill="none"
        stroke={color}
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        points={points}
      />
    </svg>
  );
}

/* ------------------------------------------------------------------ */
/*  Gauge (CPU / RAM mini ring)                                        */
/* ------------------------------------------------------------------ */
function Gauge({ value, label }: { value: number; label: string }) {
  const r = 28;
  const circ = 2 * Math.PI * r;
  const offset = circ - (value / 100) * circ;
  const color = value > 80 ? '#f87171' : value > 50 ? '#fbbf24' : '#4ade80';
  return (
    <div className="flex flex-col items-center gap-1">
      <svg width="64" height="64" className="-rotate-90">
        <circle cx="32" cy="32" r={r} fill="none" stroke="#1f2937" strokeWidth="6" />
        <circle
          cx="32"
          cy="32"
          r={r}
          fill="none"
          stroke={color}
          strokeWidth="6"
          strokeDasharray={circ}
          strokeDashoffset={offset}
          strokeLinecap="round"
          className="transition-all duration-700"
        />
      </svg>
      <span className="text-xs text-gray-500 uppercase tracking-wider">{label}</span>
      <span className="text-sm font-bold" style={{ color }}>{value}%</span>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Main CEO Dashboard                                                 */
/* ------------------------------------------------------------------ */
export default function CEODashboard() {
  const [period, setPeriod] = useState<RevenuePeriod>('mrr');
  const [products, setProducts] = useState<Product[]>([
    { name: 'Compliance', slug: 'dingdawg-compliance', version: '1.0.0', status: 'live', downloads: 0 },
    { name: 'Shield', slug: 'dingdawg-shield', version: '1.0.0', status: 'live', downloads: 0 },
    { name: 'Governance', slug: 'dingdawg-governance', version: '1.0.0', status: 'live', downloads: 0 },
    { name: 'Create-Agent', slug: 'create-dingdawg-agent', version: '1.0.0', status: 'live', downloads: 0 },
  ]);
  const [expandedProduct, setExpandedProduct] = useState<string | null>(null);
  const [totalDownloads, setTotalDownloads] = useState(0);
  const [sparkData] = useState(() =>
    Array.from({ length: 30 }, () => Math.floor(Math.random() * 20)),
  );
  const [activities] = useState<Activity[]>([
    { id: '1', avatar: '🔍', text: 'Someone ran quick_check', time: '2m ago' },
    { id: '2', avatar: '📦', text: 'npm install dingdawg-compliance', time: '8m ago' },
    { id: '3', avatar: '🛡️', text: 'Shield scan completed — 0 issues', time: '15m ago' },
    { id: '4', avatar: '💳', text: 'New lead viewed pricing page', time: '22m ago' },
    { id: '5', avatar: '🚀', text: 'Governance policy validated', time: '31m ago' },
  ]);
  const [emailsSent] = useState(0);
  const [outreachExpanded, setOutreachExpanded] = useState(false);

  /* Fetch npm downloads for each product */
  const fetchDownloads = useCallback(async () => {
    const updated = await Promise.all(
      products.map(async (p) => {
        try {
          const res = await fetch(
            `https://api.npmjs.org/downloads/point/last-day/${p.slug}`,
          );
          if (!res.ok) return p;
          const data: NpmDownloads = await res.json();
          return { ...p, downloads: data.downloads ?? 0 };
        } catch {
          return p;
        }
      }),
    );
    setProducts(updated);
    setTotalDownloads(updated.reduce((s, p) => s + p.downloads, 0));
  }, []);

  useEffect(() => {
    fetchDownloads();
  }, [fetchDownloads]);

  /* Revenue figures (placeholder — will wire to Stripe) */
  const revenueMap: Record<RevenuePeriod, string> = {
    mrr: '$0',
    today: '$0',
    week: '$0',
    month: '$0',
  };

  const revenueColor = '#4ade80'; // green — will flip dynamically later

  const paymentLinks = [
    { name: 'Starter', ok: true },
    { name: 'Pro', ok: true },
    { name: 'Enterprise', ok: true },
    { name: 'Custom', ok: true },
  ];

  /* ---- Render ---- */
  return (
    <div className="min-h-screen bg-[#0a0a0f] text-white p-4 md:p-8 pb-28 max-w-6xl mx-auto space-y-6">
      {/* ---------- REVENUE PULSE ---------- */}
      <section className="bg-gray-900/50 border border-gray-800 rounded-xl p-6 hover:border-gray-700 transition-all duration-300">
        <p className="text-xs text-gray-500 uppercase tracking-wider mb-1">Revenue Pulse</p>
        <p className="text-5xl font-bold" style={{ color: revenueColor }}>
          {revenueMap[period]}
        </p>
        <Sparkline data={sparkData} color={revenueColor} />
        <div className="flex gap-2 mt-4">
          {(['mrr', 'today', 'week', 'month'] as RevenuePeriod[]).map((t) => (
            <button
              key={t}
              onClick={() => setPeriod(t)}
              className={`px-3 py-1 rounded-lg text-xs font-medium uppercase tracking-wider transition-all duration-200 ${
                period === t
                  ? 'bg-green-400/20 text-green-400'
                  : 'bg-gray-800 text-gray-500 hover:text-gray-300'
              }`}
            >
              {t === 'mrr' ? 'MRR' : t === 'today' ? 'Today' : t === 'week' ? 'Week' : 'Month'}
            </button>
          ))}
        </div>
      </section>

      {/* ---------- PRODUCTS LIVE ---------- */}
      <section>
        <p className="text-xs text-gray-500 uppercase tracking-wider mb-3">Products Live</p>
        <div className="flex gap-4 overflow-x-auto pb-2 -mx-1 px-1 snap-x">
          {products.map((p) => (
            <div
              key={p.slug}
              onClick={() => setExpandedProduct(expandedProduct === p.slug ? null : p.slug)}
              className="flex-shrink-0 w-56 bg-gray-900/50 border border-gray-800 rounded-xl p-4 cursor-pointer
                         hover:border-gray-600 hover:scale-[1.02] transition-all duration-300 snap-start select-none"
            >
              <div className="flex items-center justify-between mb-2">
                <span className="font-semibold text-sm">{p.name}</span>
                <span
                  className={`w-2.5 h-2.5 rounded-full ${
                    p.status === 'live' ? 'bg-green-400 shadow-green-400/50 shadow-sm' :
                    p.status === 'beta' ? 'bg-amber-400' : 'bg-red-400'
                  }`}
                />
              </div>
              <p className="text-2xl font-bold text-white">{p.downloads}</p>
              <p className="text-xs text-gray-500">downloads / day</p>
              <p className="text-xs text-gray-600 mt-1">v{p.version}</p>

              {expandedProduct === p.slug && (
                <div className="mt-3 pt-3 border-t border-gray-800 animate-in fade-in slide-in-from-top-2 duration-200">
                  <code className="block text-xs bg-gray-950 text-green-400 px-3 py-2 rounded-lg break-all">
                    npm i {p.slug}
                  </code>
                </div>
              )}
            </div>
          ))}
        </div>
      </section>

      {/* ---------- MARKETPLACE HEALTH ---------- */}
      <section className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {/* Payment Links */}
        <div className="bg-gray-900/50 border border-gray-800 rounded-xl p-5 hover:border-gray-700 transition-all duration-300">
          <p className="text-xs text-gray-500 uppercase tracking-wider mb-3">Payment Links</p>
          <div className="flex gap-2">
            {paymentLinks.map((l) => (
              <div key={l.name} className="flex flex-col items-center gap-1">
                <span
                  className={`w-4 h-4 rounded-full ${
                    l.ok ? 'bg-green-400 shadow-green-400/40 shadow-sm' : 'bg-red-400'
                  }`}
                />
                <span className="text-[10px] text-gray-600">{l.name}</span>
              </div>
            ))}
          </div>
        </div>

        {/* npm Downloads */}
        <div className="bg-gray-900/50 border border-gray-800 rounded-xl p-5 hover:border-gray-700 transition-all duration-300">
          <p className="text-xs text-gray-500 uppercase tracking-wider mb-2">npm Downloads</p>
          <div className="flex items-baseline gap-2">
            <span className="text-3xl font-bold">{totalDownloads}</span>
            <span className="text-green-400 text-sm">&#9650;</span>
          </div>
          <p className="text-xs text-gray-600 mt-1">today, all packages</p>
        </div>

        {/* System Load */}
        <div className="bg-gray-900/50 border border-gray-800 rounded-xl p-5 hover:border-gray-700 transition-all duration-300">
          <p className="text-xs text-gray-500 uppercase tracking-wider mb-3">System Load</p>
          <div className="flex justify-around">
            <Gauge value={12} label="CPU" />
            <Gauge value={34} label="RAM" />
          </div>
        </div>
      </section>

      {/* ---------- CUSTOMER ACTIVITY ---------- */}
      <section className="bg-gray-900/50 border border-gray-800 rounded-xl p-5">
        <p className="text-xs text-gray-500 uppercase tracking-wider mb-4">Customer Activity</p>
        <div className="space-y-3 max-h-64 overflow-y-auto">
          {activities.map((a, i) => (
            <div
              key={a.id}
              className="flex items-center gap-3 bg-gray-950/60 rounded-lg px-4 py-3
                         hover:bg-gray-800/40 transition-all duration-200"
              style={{ animationDelay: `${i * 60}ms` }}
            >
              <span className="text-xl">{a.avatar}</span>
              <span className="text-sm text-gray-300 flex-1">{a.text}</span>
              <span className="text-xs text-gray-600 whitespace-nowrap">{a.time}</span>
            </div>
          ))}
        </div>
      </section>

      {/* ---------- OUTREACH TRACKER ---------- */}
      <section
        className="bg-gray-900/50 border border-gray-800 rounded-xl p-5 cursor-pointer hover:border-gray-700 transition-all duration-300"
        onClick={() => setOutreachExpanded(!outreachExpanded)}
      >
        <p className="text-xs text-gray-500 uppercase tracking-wider mb-3">Outreach Tracker</p>
        <div className="flex items-center gap-4 mb-2">
          <span className="text-sm text-gray-400">Emails Sent</span>
          <span className="text-lg font-bold">{emailsSent}/10</span>
        </div>
        {/* Progress bar */}
        <div className="w-full h-2 bg-gray-800 rounded-full overflow-hidden">
          <div
            className="h-full bg-blue-400 rounded-full transition-all duration-500"
            style={{ width: `${(emailsSent / 10) * 100}%` }}
          />
        </div>
        <div className="flex gap-6 mt-3">
          {[
            { label: 'Responses', val: 0 },
            { label: 'Demos', val: 0 },
            { label: 'Sales', val: 0 },
          ].map((m) => (
            <div key={m.label} className="text-center">
              <p className="text-xl font-bold">{m.val}</p>
              <p className="text-xs text-gray-500">{m.label}</p>
            </div>
          ))}
        </div>

        {outreachExpanded && (
          <div className="mt-4 pt-4 border-t border-gray-800 text-sm text-gray-500">
            No outreach emails sent yet. Use <span className="text-blue-400">Send Outreach</span> below.
          </div>
        )}
      </section>

      {/* ---------- QUICK ACTIONS (sticky bottom) ---------- */}
      <div className="fixed bottom-0 left-0 right-0 bg-gray-950/90 backdrop-blur-md border-t border-gray-800 p-3 z-50">
        <div className="max-w-6xl mx-auto flex gap-3 overflow-x-auto">
          {[
            { label: '📧 Send Outreach', url: 'mailto:?subject=DingDawg%20-%20Enterprise%20Compliance' },
            { label: '💳 View Stripe', url: 'https://dashboard.stripe.com' },
            { label: '📊 npm Stats', url: 'https://www.npmjs.com/package/dingdawg-compliance' },
            { label: '🚀 Deploy', url: 'https://vercel.com/dashboard' },
          ].map((a) => (
            <a
              key={a.label}
              href={a.url}
              target="_blank"
              rel="noopener noreferrer"
              className="flex-shrink-0 px-4 py-2 bg-gray-800 hover:bg-gray-700 rounded-lg text-sm font-medium
                         transition-all duration-200 hover:scale-[1.03] active:scale-95 whitespace-nowrap"
            >
              {a.label}
            </a>
          ))}
        </div>
      </div>
    </div>
  );
}
