#!/usr/bin/env node
/**
 * generate-screenshots.js
 *
 * Generates PWA store-listing screenshots for Google Play TWA and Apple App Store.
 * - home-mobile.png   : 390×844 narrow/mobile (homepage)
 * - dashboard-mobile.png : 1280×720 wide/desktop (homepage at desktop size)
 *
 * Strategy:
 *  1. Try the production site first (https://app.dingdawg.com)
 *  2. On failure / non-200 / timeout → fall back to rendering a static HTML mockup
 *     that accurately represents the DingDawg visual design.
 *
 * Idempotent: safe to re-run; overwrites existing files.
 */

const { chromium } = require('playwright');
const path = require('path');
const fs = require('fs');

const PROD_URL = 'https://app.dingdawg.com';
const OUT_DIR = path.join(__dirname, '../public/screenshots');

// Ensure output directory exists
fs.mkdirSync(OUT_DIR, { recursive: true });

// ─── Static fallback HTML ────────────────────────────────────────────────────
// Full-fidelity dark-theme mockup that represents the actual app visually.
const FALLBACK_HTML = `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>DingDawg — Your AI Agent Platform</title>
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

    :root {
      --bg: #07111c;
      --surface: #0d1f30;
      --surface2: #112236;
      --gold: #F6B400;
      --gold-dim: rgba(246,180,0,0.15);
      --gold-border: rgba(246,180,0,0.25);
      --text: #e8f0f7;
      --text-muted: #7a9ab5;
      --radius: 16px;
    }

    html, body {
      background: var(--bg);
      color: var(--text);
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
      min-height: 100vh;
      width: 100%;
      overflow-x: hidden;
    }

    /* ── NAV ── */
    nav {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 18px 24px;
      background: rgba(13,31,48,0.92);
      backdrop-filter: blur(12px);
      border-bottom: 1px solid var(--gold-border);
      position: sticky;
      top: 0;
      z-index: 10;
    }
    .logo {
      display: flex;
      align-items: center;
      gap: 10px;
    }
    .logo-icon {
      width: 36px;
      height: 36px;
      background: var(--gold);
      border-radius: 8px;
      display: flex;
      align-items: center;
      justify-content: center;
      font-weight: 900;
      font-size: 18px;
      color: var(--bg);
      letter-spacing: -1px;
    }
    .logo-text {
      font-size: 20px;
      font-weight: 700;
      color: var(--text);
      letter-spacing: -0.3px;
    }
    .nav-actions {
      display: flex;
      gap: 10px;
      align-items: center;
    }
    .btn-ghost {
      background: transparent;
      border: 1px solid var(--gold-border);
      color: var(--text-muted);
      padding: 8px 16px;
      border-radius: 8px;
      font-size: 14px;
      cursor: pointer;
    }
    .btn-primary {
      background: var(--gold);
      border: none;
      color: var(--bg);
      padding: 8px 18px;
      border-radius: 8px;
      font-size: 14px;
      font-weight: 700;
      cursor: pointer;
    }

    /* ── HERO ── */
    .hero {
      text-align: center;
      padding: 60px 24px 48px;
      position: relative;
    }
    .hero::before {
      content: '';
      position: absolute;
      top: -40px; left: 50%; transform: translateX(-50%);
      width: 600px; height: 400px;
      background: radial-gradient(ellipse, rgba(246,180,0,0.08) 0%, transparent 70%);
      pointer-events: none;
    }
    .badge {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      background: var(--gold-dim);
      border: 1px solid var(--gold-border);
      color: var(--gold);
      font-size: 12px;
      font-weight: 600;
      padding: 5px 14px;
      border-radius: 999px;
      margin-bottom: 24px;
      letter-spacing: 0.5px;
      text-transform: uppercase;
    }
    .hero h1 {
      font-size: clamp(28px, 6vw, 52px);
      font-weight: 800;
      line-height: 1.15;
      letter-spacing: -1px;
      margin-bottom: 16px;
    }
    .hero h1 span { color: var(--gold); }
    .hero p {
      font-size: 16px;
      color: var(--text-muted);
      max-width: 480px;
      margin: 0 auto 32px;
      line-height: 1.6;
    }
    .hero-actions {
      display: flex;
      gap: 12px;
      justify-content: center;
      flex-wrap: wrap;
    }
    .btn-lg {
      padding: 14px 28px;
      border-radius: 12px;
      font-size: 16px;
      font-weight: 700;
      cursor: pointer;
      border: none;
    }
    .btn-lg.primary { background: var(--gold); color: var(--bg); }
    .btn-lg.outline {
      background: transparent;
      border: 1px solid var(--gold-border);
      color: var(--text);
    }

    /* ── STATS BAR ── */
    .stats {
      display: flex;
      justify-content: center;
      gap: 32px;
      padding: 24px;
      border-top: 1px solid var(--gold-border);
      border-bottom: 1px solid var(--gold-border);
      margin: 0 24px;
      flex-wrap: wrap;
    }
    .stat { text-align: center; }
    .stat .value { font-size: 22px; font-weight: 800; color: var(--gold); }
    .stat .label { font-size: 12px; color: var(--text-muted); margin-top: 2px; }

    /* ── FEATURES GRID ── */
    .section { padding: 48px 24px; }
    .section-title {
      font-size: 22px;
      font-weight: 700;
      text-align: center;
      margin-bottom: 28px;
    }
    .section-title span { color: var(--gold); }
    .grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
      gap: 16px;
      max-width: 900px;
      margin: 0 auto;
    }
    .card {
      background: var(--surface);
      border: 1px solid var(--gold-border);
      border-radius: var(--radius);
      padding: 20px;
      position: relative;
      overflow: hidden;
    }
    .card::after {
      content: '';
      position: absolute;
      top: 0; left: 0; right: 0;
      height: 2px;
      background: linear-gradient(90deg, transparent, var(--gold), transparent);
      opacity: 0.4;
    }
    .card-icon {
      width: 40px; height: 40px;
      background: var(--gold-dim);
      border-radius: 10px;
      display: flex; align-items: center; justify-content: center;
      font-size: 20px;
      margin-bottom: 12px;
    }
    .card h3 { font-size: 15px; font-weight: 700; margin-bottom: 6px; }
    .card p { font-size: 13px; color: var(--text-muted); line-height: 1.5; }

    /* ── AGENT DEMO PANEL ── */
    .demo-panel {
      background: var(--surface);
      border: 1px solid var(--gold-border);
      border-radius: var(--radius);
      margin: 0 auto;
      max-width: 500px;
      overflow: hidden;
      box-shadow: 0 20px 60px rgba(0,0,0,0.5), 0 0 0 1px var(--gold-border);
    }
    .demo-header {
      background: var(--surface2);
      padding: 14px 18px;
      display: flex;
      align-items: center;
      gap: 10px;
      border-bottom: 1px solid var(--gold-border);
    }
    .demo-avatar {
      width: 32px; height: 32px;
      background: var(--gold);
      border-radius: 50%;
      display: flex; align-items: center; justify-content: center;
      font-weight: 900; font-size: 14px;
      color: var(--bg);
    }
    .demo-info h4 { font-size: 14px; font-weight: 700; }
    .demo-info span { font-size: 12px; color: var(--gold); }
    .demo-body { padding: 18px; display: flex; flex-direction: column; gap: 12px; }
    .msg {
      max-width: 80%;
      padding: 10px 14px;
      border-radius: 12px;
      font-size: 13px;
      line-height: 1.5;
    }
    .msg.agent {
      background: var(--surface2);
      border: 1px solid var(--gold-border);
      align-self: flex-start;
    }
    .msg.user {
      background: var(--gold);
      color: var(--bg);
      align-self: flex-end;
    }
    .demo-input {
      margin: 8px 18px 18px;
      display: flex;
      gap: 8px;
      background: var(--surface2);
      border: 1px solid var(--gold-border);
      border-radius: 10px;
      padding: 10px 14px;
      align-items: center;
    }
    .demo-input span { flex: 1; font-size: 13px; color: var(--text-muted); }
    .send-btn {
      width: 30px; height: 30px;
      background: var(--gold);
      border-radius: 8px;
      display: flex; align-items: center; justify-content: center;
      font-size: 14px;
    }

    /* ── FOOTER ── */
    footer {
      text-align: center;
      padding: 32px 24px;
      border-top: 1px solid var(--gold-border);
      color: var(--text-muted);
      font-size: 13px;
    }
    footer .footer-logo { font-size: 18px; font-weight: 800; color: var(--gold); margin-bottom: 8px; }
  </style>
</head>
<body>

  <nav>
    <div class="logo">
      <div class="logo-icon">DD</div>
      <span class="logo-text">DingDawg</span>
    </div>
    <div class="nav-actions">
      <button class="btn-ghost">Sign In</button>
      <button class="btn-primary">Claim Handle</button>
    </div>
  </nav>

  <section class="hero">
    <div class="badge">✦ Universal AI Agent Platform</div>
    <h1>Your AI Agent,<br/><span>Working For You</span></h1>
    <p>Claim your @handle and deploy an AI agent that handles bookings, answers customers, and grows your business — 24/7.</p>
    <div class="hero-actions">
      <button class="btn-lg primary">Claim Your @Handle</button>
      <button class="btn-lg outline">Explore Agents</button>
    </div>
  </section>

  <div class="stats">
    <div class="stat">
      <div class="value">28+</div>
      <div class="label">Agent Templates</div>
    </div>
    <div class="stat">
      <div class="value">$1</div>
      <div class="label">Per Action</div>
    </div>
    <div class="stat">
      <div class="value">8</div>
      <div class="label">Industry Sectors</div>
    </div>
    <div class="stat">
      <div class="value">24/7</div>
      <div class="label">Always On</div>
    </div>
  </div>

  <section class="section">
    <h2 class="section-title">Meet Your <span>AI Agent</span></h2>
    <div class="demo-panel">
      <div class="demo-header">
        <div class="demo-avatar">D</div>
        <div class="demo-info">
          <h4>@yourbiz</h4>
          <span>● Online — AI Agent Active</span>
        </div>
      </div>
      <div class="demo-body">
        <div class="msg agent">Hi! I'm your DingDawg AI agent. I can book appointments, answer questions, and handle your customers 24/7. How can I help?</div>
        <div class="msg user">Can you book me in for Thursday at 3pm?</div>
        <div class="msg agent">Absolutely! I've checked Thursday and 3pm is available. Shall I confirm the booking and send a reminder?</div>
      </div>
      <div class="demo-input">
        <span>Type a message...</span>
        <div class="send-btn">➤</div>
      </div>
    </div>
  </section>

  <section class="section">
    <h2 class="section-title">Everything Your Business <span>Needs</span></h2>
    <div class="grid">
      <div class="card">
        <div class="card-icon">📅</div>
        <h3>Smart Scheduling</h3>
        <p>Google Calendar sync, automatic booking confirmation, reminders.</p>
      </div>
      <div class="card">
        <div class="card-icon">💬</div>
        <h3>Multi-Channel</h3>
        <p>Chat widget, Discord, Telegram, WebSocket — one agent, every channel.</p>
      </div>
      <div class="card">
        <div class="card-icon">🏪</div>
        <h3>Marketplace</h3>
        <p>Browse 28+ industry templates. Deploy in minutes, not weeks.</p>
      </div>
      <div class="card">
        <div class="card-icon">🔒</div>
        <h3>Enterprise Security</h3>
        <p>Prompt armor, extraction defense, 4-layer auth. Your data is safe.</p>
      </div>
    </div>
  </section>

  <footer>
    <div class="footer-logo">DingDawg</div>
    <div>Universal AI Agent Platform &nbsp;·&nbsp; Yeah! We've Got An Agent For That!</div>
  </footer>

</body>
</html>`;

async function tryProductionScreenshot(browser, url, viewport, outputPath) {
  const context = await browser.newContext({ viewport });
  const page = await context.newPage();
  try {
    console.log(`  → Navigating to ${url} at ${viewport.width}×${viewport.height}...`);
    const response = await page.goto(url, {
      waitUntil: 'networkidle',
      timeout: 20000,
    });
    if (!response || !response.ok()) {
      throw new Error(`Non-OK response: ${response ? response.status() : 'no response'}`);
    }
    // Wait an extra second for fonts/images to settle
    await page.waitForTimeout(1500);
    await page.screenshot({ path: outputPath, fullPage: false });
    console.log(`  ✓ Saved production screenshot → ${path.basename(outputPath)}`);
    return true;
  } catch (err) {
    console.log(`  ✗ Production screenshot failed: ${err.message}`);
    return false;
  } finally {
    await context.close();
  }
}

async function takeFallbackScreenshot(browser, html, viewport, outputPath) {
  const context = await browser.newContext({ viewport });
  const page = await context.newPage();
  try {
    console.log(`  → Rendering static fallback at ${viewport.width}×${viewport.height}...`);
    await page.setContent(html, { waitUntil: 'networkidle' });
    await page.waitForTimeout(500);
    await page.screenshot({ path: outputPath, fullPage: false });
    console.log(`  ✓ Saved fallback screenshot → ${path.basename(outputPath)}`);
  } finally {
    await context.close();
  }
}

async function main() {
  console.log('\n=== DingDawg PWA Screenshot Generator ===\n');

  const browser = await chromium.launch({ headless: true });

  try {
    // ── Screenshot 1: home-mobile.png (390×844, narrow/mobile) ──────────────
    const homePath = path.join(OUT_DIR, 'home-mobile.png');
    const mobileViewport = { width: 390, height: 844 };

    console.log('[1/2] home-mobile.png (390×844)');
    const homeProd = await tryProductionScreenshot(browser, PROD_URL, mobileViewport, homePath);
    if (!homeProd) {
      await takeFallbackScreenshot(browser, FALLBACK_HTML, mobileViewport, homePath);
    }

    // ── Screenshot 2: dashboard-mobile.png (1280×720, wide/desktop) ─────────
    const dashPath = path.join(OUT_DIR, 'dashboard-mobile.png');
    const desktopViewport = { width: 1280, height: 720 };

    console.log('\n[2/2] dashboard-mobile.png (1280×720)');
    const dashProd = await tryProductionScreenshot(browser, PROD_URL, desktopViewport, dashPath);
    if (!dashProd) {
      await takeFallbackScreenshot(browser, FALLBACK_HTML, desktopViewport, dashPath);
    }

    // ── Verify output ────────────────────────────────────────────────────────
    console.log('\n=== Verification ===');
    for (const [label, filePath] of [
      ['home-mobile.png', homePath],
      ['dashboard-mobile.png', dashPath],
    ]) {
      const stats = fs.statSync(filePath);
      console.log(`  ${label}: ${(stats.size / 1024).toFixed(1)} KB`);
      if (stats.size < 1024) {
        console.error(`  ✗ WARNING: ${label} is suspiciously small!`);
        process.exit(1);
      }
    }
    console.log('\n✓ All screenshots generated successfully.\n');
  } finally {
    await browser.close();
  }
}

main().catch((err) => {
  console.error('Fatal error:', err);
  process.exit(1);
});
