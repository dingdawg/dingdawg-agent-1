#!/usr/bin/env bash
# =============================================================================
# DingDawg Agent 1 — Icon Generator
# Requires: ImageMagick (convert) or Inkscape for SVG rasterization
#
# Usage:
#   chmod +x scripts/generate-icons.sh
#   ./scripts/generate-icons.sh
#
# Input:  public/icons/icon.svg
# Output: public/icons/icon-{size}.png  (all manifest sizes)
#         public/icons/icon-{size}-maskable.png  (maskable variants with padding)
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ICONS_DIR="$SCRIPT_DIR/../public/icons"
SOURCE_SVG="$ICONS_DIR/icon.svg"

# Check dependencies
if ! command -v convert &>/dev/null && ! command -v inkscape &>/dev/null; then
  echo "ERROR: ImageMagick (convert) or Inkscape is required."
  echo "  Ubuntu/Debian: sudo apt-get install imagemagick"
  echo "  macOS:         brew install imagemagick"
  exit 1
fi

# Sizes required by manifest.json
SIZES=(72 96 128 144 152 192 384 512)

# Maskable sizes (these get extra padding — 20% safe zone per spec)
MASKABLE_SIZES=(192 512)

echo "Generating standard icons from $SOURCE_SVG..."

for SIZE in "${SIZES[@]}"; do
  OUTPUT="$ICONS_DIR/icon-${SIZE}.png"
  if command -v inkscape &>/dev/null; then
    inkscape \
      --export-type=png \
      --export-filename="$OUTPUT" \
      --export-width="$SIZE" \
      --export-height="$SIZE" \
      "$SOURCE_SVG" 2>/dev/null
  else
    # ImageMagick — render SVG at 2x then scale down for quality
    convert \
      -background none \
      -density 288 \
      "$SOURCE_SVG" \
      -resize "${SIZE}x${SIZE}" \
      -strip \
      "$OUTPUT"
  fi
  echo "  Generated: icon-${SIZE}.png"
done

echo ""
echo "Generating maskable icons (20% safe-zone padding)..."

# Maskable icons: content must fit within 80% of the canvas
# We render the icon at 80% of target size and center on dark background
for SIZE in "${MASKABLE_SIZES[@]}"; do
  OUTPUT="$ICONS_DIR/icon-${SIZE}-maskable.png"
  INNER_SIZE=$(echo "$SIZE * 0.80 / 1" | bc)

  if command -v inkscape &>/dev/null; then
    # Render inner icon
    TEMP_PNG="/tmp/dd_icon_inner_${SIZE}.png"
    inkscape \
      --export-type=png \
      --export-filename="$TEMP_PNG" \
      --export-width="$INNER_SIZE" \
      --export-height="$INNER_SIZE" \
      "$SOURCE_SVG" 2>/dev/null

    # Composite onto dark background with centering
    convert \
      -size "${SIZE}x${SIZE}" \
      xc:"#07111c" \
      "$TEMP_PNG" \
      -gravity center \
      -composite \
      "$OUTPUT"
    rm -f "$TEMP_PNG"
  else
    PADDING=$(echo "($SIZE - $SIZE * 80 / 100) / 2" | bc)
    convert \
      -background "#07111c" \
      -density 288 \
      "$SOURCE_SVG" \
      -resize "${INNER_SIZE}x${INNER_SIZE}" \
      -gravity center \
      -extent "${SIZE}x${SIZE}" \
      -strip \
      "$OUTPUT"
  fi
  echo "  Generated: icon-${SIZE}-maskable.png"
done

# Generate apple-touch-icon (180x180, no transparency)
echo ""
echo "Generating apple-touch-icon-180.png..."
OUTPUT_APPLE="$ICONS_DIR/apple-touch-icon-180.png"
if command -v inkscape &>/dev/null; then
  TEMP_PNG="/tmp/dd_icon_apple.png"
  inkscape \
    --export-type=png \
    --export-filename="$TEMP_PNG" \
    --export-width=160 \
    --export-height=160 \
    "$SOURCE_SVG" 2>/dev/null
  convert \
    -size 180x180 \
    xc:"#07111c" \
    "$TEMP_PNG" \
    -gravity center \
    -composite \
    "$OUTPUT_APPLE"
  rm -f "$TEMP_PNG"
else
  convert \
    -background "#07111c" \
    -density 288 \
    "$SOURCE_SVG" \
    -resize "160x160" \
    -gravity center \
    -extent "180x180" \
    -strip \
    "$OUTPUT_APPLE"
fi
echo "  Generated: apple-touch-icon-180.png"

echo ""
echo "Done! All icons generated in $ICONS_DIR"
echo ""
echo "Icon manifest sizes: ${SIZES[*]}"
echo "Maskable sizes:      ${MASKABLE_SIZES[*]}"
echo ""
echo "Next steps:"
echo "  1. Verify icons look correct in public/icons/"
echo "  2. Run: npx playwright test e2e/pwa.spec.ts"
