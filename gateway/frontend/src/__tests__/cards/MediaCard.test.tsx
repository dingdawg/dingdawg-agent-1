/**
 * MediaCard.test.tsx — Gallery/media display card tests (TDD RED phase)
 *
 * 8 tests covering image, video, audio rendering across single/grid/carousel layouts.
 *
 * Run: npx vitest run src/__tests__/cards/MediaCard.test.tsx
 */

import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { MediaCard } from "../../components/chat/cards/MediaCard";
import type { MediaItem } from "../../components/chat/cards/MediaCard";

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const singleImage: MediaItem[] = [
  { type: "image", src: "https://example.com/photo1.jpg", alt: "A sunset" },
];

const multipleImages: MediaItem[] = [
  { type: "image", src: "https://example.com/photo1.jpg", alt: "Photo 1" },
  { type: "image", src: "https://example.com/photo2.jpg", alt: "Photo 2" },
  { type: "image", src: "https://example.com/photo3.jpg", alt: "Photo 3" },
];

const videoItem: MediaItem[] = [
  {
    type: "video",
    src: "https://example.com/clip.mp4",
    thumbnail: "https://example.com/thumb.jpg",
  },
];

const audioItem: MediaItem[] = [
  { type: "audio", src: "https://example.com/track.mp3" },
];

const mixedItems: MediaItem[] = [
  { type: "image", src: "https://example.com/img.jpg", alt: "Mixed image" },
  { type: "video", src: "https://example.com/vid.mp4" },
  { type: "audio", src: "https://example.com/aud.mp3" },
];

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("MediaCard", () => {
  it("renders a single image with src attribute", () => {
    const { container } = render(
      <MediaCard items={singleImage} layout="single" />
    );

    const img = container.querySelector("img");
    expect(img).not.toBeNull();
    expect(img!.getAttribute("src")).toBe("https://example.com/photo1.jpg");
  });

  it("renders multiple images in grid layout", () => {
    const { container } = render(
      <MediaCard items={multipleImages} layout="grid" />
    );

    const images = container.querySelectorAll("img");
    expect(images.length).toBe(3);

    // Grid layout should use a grid or flex container
    const gridEl =
      container.querySelector("[class*='grid']") ||
      container.querySelector("[class*='columns']") ||
      container.querySelector("[class*='flex']");
    expect(gridEl).not.toBeNull();
  });

  it("renders carousel layout with horizontal scroll container", () => {
    const { container } = render(
      <MediaCard items={multipleImages} layout="carousel" />
    );

    // Carousel should have overflow-x-auto and snap
    const carousel =
      container.querySelector("[class*='overflow-x']") ||
      container.querySelector("[class*='scroll']") ||
      container.querySelector("[class*='carousel']");

    expect(carousel).not.toBeNull();
  });

  it("renders video element with controls attribute", () => {
    const { container } = render(
      <MediaCard items={videoItem} layout="single" />
    );

    const video = container.querySelector("video");
    expect(video).not.toBeNull();
    expect(video!.hasAttribute("controls")).toBe(true);
  });

  it("renders audio element with controls attribute", () => {
    const { container } = render(
      <MediaCard items={audioItem} layout="single" />
    );

    const audio = container.querySelector("audio");
    expect(audio).not.toBeNull();
    expect(audio!.hasAttribute("controls")).toBe(true);
  });

  it("applies alt text to all image elements", () => {
    const { container } = render(
      <MediaCard items={multipleImages} layout="grid" />
    );

    const images = container.querySelectorAll("img");
    images.forEach((img, i) => {
      expect(img.getAttribute("alt")).toBe(multipleImages[i].alt);
    });
  });

  it("applies lazy loading attribute to images", () => {
    const { container } = render(
      <MediaCard items={multipleImages} layout="grid" />
    );

    const images = container.querySelectorAll("img");
    images.forEach((img) => {
      expect(img.getAttribute("loading")).toBe("lazy");
    });
  });

  it("renders mixed media types (image + video + audio) without errors", () => {
    const { container } = render(
      <MediaCard items={mixedItems} layout="grid" />
    );

    const img = container.querySelector("img");
    const video = container.querySelector("video");
    const audio = container.querySelector("audio");

    expect(img).not.toBeNull();
    expect(video).not.toBeNull();
    expect(audio).not.toBeNull();
  });
});
