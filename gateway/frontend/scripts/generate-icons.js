#!/usr/bin/env node
/**
 * DingDawg Agent 1 — PNG Icon Generator
 *
 * Uses `sharp` (already in node_modules) which bundles libvips + rsvg for
 * SVG rasterization — no ImageMagick or Inkscape required.
 *
 * Usage (from the `frontend/` directory):
 *   node scripts/generate-icons.js
 *
 * Input:  public/icons/icon.svg
 * Output: public/icons/*.png  (all 12 manifest sizes + maskable variants)
 *
 * Idempotent — safe to rerun at any time.
 */

'use strict';

const path = require('path');
const fs   = require('fs');

// Resolve sharp from the frontend node_modules so this script can be run
// from any cwd as long as Node can find the module relative to this file.
const frontendDir = path.resolve(__dirname, '..');
const sharpPath   = path.join(frontendDir, 'node_modules', 'sharp');
const sharp       = require(sharpPath);

const ICONS_DIR  = path.join(frontendDir, 'public', 'icons');
const SOURCE_SVG = path.join(ICONS_DIR, 'icon.svg');

// Background colour for all opaque icons (maskable + apple-touch)
const BG_COLOUR = '#07111c';

// ---------------------------------------------------------------------------
// Icon spec
// ---------------------------------------------------------------------------
// Standard icons — rendered straight from SVG at exact size
const STANDARD_SIZES = [32, 72, 96, 128, 144, 152, 192, 384, 512];

// Maskable icons — icon content in inner 80% (20% padding on each side)
// background is BG_COLOUR so Android crop-circles look correct
const MASKABLE_SIZES = [192, 512];

// Apple Touch Icon — 180 × 180, opaque, no corner radius strip needed
// (iOS handles the rounding itself)
const APPLE_SIZE = 180;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Render the source SVG to a PNG buffer at `size x size`.
 */
async function svgToPngBuffer(size) {
  return sharp(SOURCE_SVG)
    .resize(size, size, { fit: 'contain', background: { r: 0, g: 0, b: 0, alpha: 0 } })
    .png()
    .toBuffer();
}

/**
 * Build a flat #07111c canvas of `canvasSize x canvasSize` and composite
 * the icon (rendered at `innerSize x innerSize`) centred on it.
 */
async function buildMaskable(canvasSize, innerSize) {
  // 1. Render the SVG at the inner (smaller) size
  const iconBuffer = await sharp(SOURCE_SVG)
    .resize(innerSize, innerSize, { fit: 'contain', background: { r: 0, g: 0, b: 0, alpha: 0 } })
    .png()
    .toBuffer();

  // 2. Create the background canvas
  const padding = Math.round((canvasSize - innerSize) / 2);
  const canvas  = sharp({
    create: {
      width:      canvasSize,
      height:     canvasSize,
      channels:   4,
      background: { r: 7, g: 17, b: 28, alpha: 255 }, // #07111c
    },
  });

  // 3. Composite icon centred
  return canvas
    .composite([{
      input:     iconBuffer,
      gravity:   'center',
      left:      padding,
      top:       padding,
    }])
    .png()
    .toBuffer();
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

async function main() {
  if (!fs.existsSync(SOURCE_SVG)) {
    console.error(`ERROR: Source SVG not found: ${SOURCE_SVG}`);
    process.exit(1);
  }

  fs.mkdirSync(ICONS_DIR, { recursive: true });

  console.log(`Source: ${SOURCE_SVG}`);
  console.log(`Output: ${ICONS_DIR}`);
  console.log('');

  // --- Standard icons ---
  console.log('Generating standard icons…');
  for (const size of STANDARD_SIZES) {
    const outPath = path.join(ICONS_DIR, `icon-${size}.png`);
    const buf = await svgToPngBuffer(size);
    fs.writeFileSync(outPath, buf);
    const stat = fs.statSync(outPath);
    console.log(`  icon-${size}.png  (${stat.size} bytes)`);
  }

  // --- Maskable icons ---
  console.log('');
  console.log('Generating maskable icons (20 % safe-zone padding)…');
  for (const size of MASKABLE_SIZES) {
    const innerSize = Math.round(size * 0.8);
    const outPath   = path.join(ICONS_DIR, `icon-${size}-maskable.png`);
    const buf       = await buildMaskable(size, innerSize);
    fs.writeFileSync(outPath, buf);
    const stat = fs.statSync(outPath);
    console.log(`  icon-${size}-maskable.png  (canvas=${size}, inner=${innerSize}, ${stat.size} bytes)`);
  }

  // --- Apple Touch Icon ---
  console.log('');
  console.log('Generating apple-touch-icon-180.png…');
  {
    // Apple touch icons should be opaque — render on BG_COLOUR background
    const innerSize = Math.round(APPLE_SIZE * 0.8); // 144 — gives a little breathing room
    const outPath   = path.join(ICONS_DIR, 'apple-touch-icon-180.png');
    const buf       = await buildMaskable(APPLE_SIZE, innerSize);
    fs.writeFileSync(outPath, buf);
    const stat = fs.statSync(outPath);
    console.log(`  apple-touch-icon-180.png  (${stat.size} bytes)`);
  }

  // --- Verify all expected files ---
  console.log('');
  console.log('Verifying all expected files…');
  const expected = [
    'icon-32.png',
    'icon-72.png',
    'icon-96.png',
    'icon-128.png',
    'icon-144.png',
    'icon-152.png',
    'icon-192.png',
    'icon-192-maskable.png',
    'icon-384.png',
    'icon-512.png',
    'icon-512-maskable.png',
    'apple-touch-icon-180.png',
  ];

  let allOk = true;
  for (const name of expected) {
    const p    = path.join(ICONS_DIR, name);
    const ok   = fs.existsSync(p) && fs.statSync(p).size > 0;
    const mark = ok ? '[OK]' : '[MISSING]';
    console.log(`  ${mark}  ${name}`);
    if (!ok) allOk = false;
  }

  console.log('');
  if (allOk) {
    console.log('All 12 icon files generated successfully.');
  } else {
    console.error('Some files are missing! Check errors above.');
    process.exit(1);
  }
}

main().catch((err) => {
  console.error('FATAL:', err.message || err);
  process.exit(1);
});
