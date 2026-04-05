#!/usr/bin/env node
/**
 * generate-splash.js
 *
 * Generates Apple iOS/iPadOS PWA splash screen PNGs using `sharp`.
 * Each splash screen is a dark-themed branded image matching the DingDawg
 * visual identity: bg #07111c, centered gold "DD" monogram, "DingDawg" text.
 *
 * Output files:
 *   public/splash/iphone14.png     1170×2532
 *   public/splash/iphone15plus.png 1290×2796
 *   public/splash/iphonese.png      750×1334
 *   public/splash/ipad.png         1640×2360
 *
 * Idempotent: safe to re-run; overwrites existing files.
 *
 * Requires: sharp (already in node_modules)
 */

const sharp = require('/home/joe-rangel/Desktop/DingDawg-Agent-1/gateway/frontend/node_modules/sharp');
const path = require('path');
const fs = require('fs');

const OUT_DIR = path.join(__dirname, '../public/splash');
fs.mkdirSync(OUT_DIR, { recursive: true });

// Brand colors
const BG = '#07111c';
const GOLD = '#F6B400';
const GOLD_DIM = 'rgba(246,180,0,0.18)';
const GOLD_BORDER = 'rgba(246,180,0,0.28)';
const WHITE = '#FFFFFF';

// Splash screen specs
const SCREENS = [
  { name: 'iphone14.png',     width: 1170, height: 2532 },
  { name: 'iphone15plus.png', width: 1290, height: 2796 },
  { name: 'iphonese.png',     width: 750,  height: 1334 },
  { name: 'ipad.png',         width: 1640, height: 2360 },
];

/**
 * Build a full SVG splash screen at the given dimensions.
 * Uses inline SVG rendering so sharp can rasterise it directly.
 */
function buildSplashSVG(width, height) {
  const cx = width / 2;
  const cy = height / 2;

  // Scale the icon relative to the shorter dimension
  const short = Math.min(width, height);
  const iconSize = Math.round(short * 0.28);   // icon bounding box
  const iconR = Math.round(iconSize * 0.22);   // corner radius

  // Pulsing glow circle behind icon
  const glowR = Math.round(iconSize * 0.75);

  // "DingDawg" text — positioned below the icon
  const textY = cy + iconSize / 2 + Math.round(short * 0.07);
  const fontSize = Math.round(short * 0.058);
  const tagFontSize = Math.round(short * 0.026);
  const tagY = textY + Math.round(fontSize * 1.3);

  // Icon geometry (scaled DD monogram inside a rounded square)
  const ix = cx - iconSize / 2;
  const iy = cy - iconSize / 2;
  const s = iconSize;

  // Proportional path coordinates for DD letterforms (mirrors icon.svg logic)
  // We scale the original 512-unit paths to `s` units
  const scale = s / 512;

  // Helper: scale a number from 512-space to s-space, offset by ix/iy
  const sx = (v) => (ix + v * scale).toFixed(2);
  const sy = (v) => (iy + v * scale).toFixed(2);
  const sc = (v) => (v * scale).toFixed(2);

  return `<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}">
  <defs>
    <radialGradient id="glow" cx="50%" cy="50%" r="50%">
      <stop offset="0%"   stop-color="${GOLD}" stop-opacity="0.12"/>
      <stop offset="100%" stop-color="${GOLD}" stop-opacity="0"/>
    </radialGradient>
    <radialGradient id="bgGrad" cx="50%" cy="40%" r="60%">
      <stop offset="0%"  stop-color="#0d2035"/>
      <stop offset="100%" stop-color="#07111c"/>
    </radialGradient>
  </defs>

  <!-- Background -->
  <rect width="${width}" height="${height}" fill="url(#bgGrad)"/>

  <!-- Subtle radial glow behind icon -->
  <circle cx="${cx}" cy="${cy}" r="${glowR}" fill="url(#glow)"/>

  <!-- Icon rounded square background -->
  <rect
    x="${ix}" y="${iy}"
    width="${s}" height="${s}"
    rx="${iconR}" ry="${iconR}"
    fill="#07111c"
    stroke="${GOLD_BORDER}"
    stroke-width="${Math.max(2, sc(8))}"
  />

  <!-- Inner accent ring -->
  <rect
    x="${(ix + s * 0.025).toFixed(2)}"
    y="${(iy + s * 0.025).toFixed(2)}"
    width="${(s * 0.95).toFixed(2)}"
    height="${(s * 0.95).toFixed(2)}"
    rx="${(iconR * 0.85).toFixed(2)}"
    ry="${(iconR * 0.85).toFixed(2)}"
    fill="none"
    stroke="${GOLD}"
    stroke-width="${Math.max(1, sc(8))}"
    opacity="0.18"
  />

  <!-- First D — gold -->
  <path
    d="M ${sx(112)} ${sy(152)}
       h ${sc(48)}
       c ${sc(52)} 0 ${sc(88)} ${sc(36)} ${sc(88)} ${sc(104)}
       s ${sc(-36)} ${sc(104)} ${sc(-88)} ${sc(104)}
       h ${sc(-48)} z
       M ${sx(152)} ${sy(212)}
       v ${sc(88)}
       c ${sc(24)} 0 ${sc(44)} ${sc(-18)} ${sc(44)} ${sc(-44)}
       s ${sc(-20)} ${sc(-44)} ${sc(-44)} ${sc(-44)} z"
    fill="${GOLD}"
  />

  <!-- Second D — white -->
  <path
    d="M ${sx(272)} ${sy(152)}
       h ${sc(48)}
       c ${sc(52)} 0 ${sc(88)} ${sc(36)} ${sc(88)} ${sc(104)}
       s ${sc(-36)} ${sc(104)} ${sc(-88)} ${sc(104)}
       h ${sc(-48)} z
       M ${sx(312)} ${sy(212)}
       v ${sc(88)}
       c ${sc(24)} 0 ${sc(44)} ${sc(-18)} ${sc(44)} ${sc(-44)}
       s ${sc(-20)} ${sc(-44)} ${sc(-44)} ${sc(-44)} z"
    fill="${WHITE}"
  />

  <!-- Paw-print accent dots (brand marker) -->
  <circle cx="${sx(256)}" cy="${sy(416)}" r="${sc(10)}" fill="${GOLD}" opacity="0.6"/>
  <circle cx="${sx(228)}" cy="${sy(406)}" r="${sc(7)}"  fill="${GOLD}" opacity="0.4"/>
  <circle cx="${sx(284)}" cy="${sy(406)}" r="${sc(7)}"  fill="${GOLD}" opacity="0.4"/>

  <!-- "DingDawg" wordmark -->
  <text
    x="${cx}"
    y="${textY}"
    text-anchor="middle"
    dominant-baseline="auto"
    font-family="-apple-system, BlinkMacSystemFont, 'Helvetica Neue', sans-serif"
    font-size="${fontSize}"
    font-weight="800"
    letter-spacing="${(fontSize * -0.02).toFixed(1)}"
    fill="${WHITE}"
  >DingDawg</text>

  <!-- Tagline -->
  <text
    x="${cx}"
    y="${tagY}"
    text-anchor="middle"
    dominant-baseline="auto"
    font-family="-apple-system, BlinkMacSystemFont, 'Helvetica Neue', sans-serif"
    font-size="${tagFontSize}"
    font-weight="500"
    letter-spacing="2"
    fill="${GOLD}"
    opacity="0.75"
  >YOUR AI AGENT PLATFORM</text>
</svg>`;
}

async function generateSplash({ name, width, height }) {
  const svgBuffer = Buffer.from(buildSplashSVG(width, height));
  const outputPath = path.join(OUT_DIR, name);

  await sharp(svgBuffer)
    .resize(width, height)   // ensure exact pixel dimensions
    .png({ compressionLevel: 9, adaptiveFiltering: true })
    .toFile(outputPath);

  const stats = fs.statSync(outputPath);
  console.log(`  ✓ ${name.padEnd(20)} ${width}×${height}  (${(stats.size / 1024).toFixed(1)} KB)`);

  if (stats.size < 10 * 1024) {
    console.error(`  ✗ WARNING: ${name} is suspiciously small (${stats.size} bytes)!`);
    process.exit(1);
  }
}

async function main() {
  console.log('\n=== DingDawg Apple Splash Screen Generator ===\n');

  for (const spec of SCREENS) {
    await generateSplash(spec);
  }

  console.log('\n✓ All splash screens generated successfully.\n');
  console.log('Output directory:', OUT_DIR, '\n');
}

main().catch((err) => {
  console.error('Fatal error:', err);
  process.exit(1);
});
