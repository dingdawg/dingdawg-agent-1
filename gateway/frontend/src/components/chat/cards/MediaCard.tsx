"use client";

/**
 * MediaCard — gallery/video/audio media display in the chat stream.
 *
 * Layouts:
 *   single   — full-width single media item
 *   grid     — 2-column responsive grid
 *   carousel — horizontal scroll with CSS snap
 *
 * All images include lazy loading and alt text.
 * Video and audio elements include native browser controls.
 */

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface MediaItem {
  type: "image" | "video" | "audio";
  src: string;
  alt?: string;
  thumbnail?: string;
}

interface MediaCardProps {
  items: MediaItem[];
  layout: "single" | "grid" | "carousel";
}

// ---------------------------------------------------------------------------
// Sub-renderers
// ---------------------------------------------------------------------------

function renderItem(item: MediaItem, key: string | number) {
  if (item.type === "image") {
    return (
      // eslint-disable-next-line @next/next/no-img-element
      <img
        key={key}
        src={item.src}
        alt={item.alt ?? ""}
        loading="lazy"
        className="w-full h-full object-cover rounded-xl"
        draggable={false}
      />
    );
  }

  if (item.type === "video") {
    return (
      <video
        key={key}
        src={item.src}
        controls
        poster={item.thumbnail}
        className="w-full rounded-xl bg-black"
        preload="metadata"
      >
        Your browser does not support video playback.
      </video>
    );
  }

  if (item.type === "audio") {
    return (
      <div key={key} className="w-full">
        <audio
          src={item.src}
          controls
          className="w-full"
          preload="metadata"
        >
          Your browser does not support audio playback.
        </audio>
      </div>
    );
  }

  return null;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function MediaCard({ items, layout }: MediaCardProps) {
  if (items.length === 0) return null;

  if (layout === "single") {
    return (
      <div className="glass-panel-gold overflow-hidden card-enter">
        {renderItem(items[0], 0)}
      </div>
    );
  }

  if (layout === "grid") {
    return (
      <div className="glass-panel-gold p-2 card-enter">
        <div
          className={[
            "grid gap-2",
            items.length === 1
              ? "grid-cols-1"
              : items.length === 2
              ? "grid-cols-2"
              : "grid-cols-2 sm:grid-cols-3",
          ].join(" ")}
        >
          {items.map((item, i) => (
            <div
              key={`${item.src}-${i}`}
              className="overflow-hidden rounded-xl aspect-square bg-white/5"
            >
              {renderItem(item, i)}
            </div>
          ))}
        </div>
      </div>
    );
  }

  // carousel
  return (
    <div className="glass-panel-gold p-2 card-enter">
      <div
        className="flex gap-2 overflow-x-auto snap-x snap-mandatory scrollbar-thin pb-1"
        style={{ scrollBehavior: "smooth" }}
      >
        {items.map((item, i) => (
          <div
            key={`${item.src}-${i}`}
            className="flex-shrink-0 w-56 sm:w-64 snap-start overflow-hidden rounded-xl bg-white/5"
          >
            {renderItem(item, i)}
          </div>
        ))}
      </div>
    </div>
  );
}
