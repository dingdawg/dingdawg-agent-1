import React from "react";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Base skeleton primitive
// ---------------------------------------------------------------------------

interface SkeletonProps extends React.HTMLAttributes<HTMLDivElement> {
  /** Additional Tailwind classes to merge in. */
  className?: string;
}

/**
 * Skeleton renders an animated placeholder block used while content is
 * loading.  It uses Tailwind's `animate-pulse` and inherits the app's
 * design token colours so it blends naturally with dark/light themes.
 */
export function Skeleton({ className, ...props }: SkeletonProps) {
  return (
    <div
      className={cn(
        "animate-pulse rounded-md bg-white/10",
        className
      )}
      aria-hidden="true"
      {...props}
    />
  );
}

// ---------------------------------------------------------------------------
// SkeletonText — one or more lines of placeholder text
// ---------------------------------------------------------------------------

interface SkeletonTextProps {
  /** Number of lines to render. Defaults to 3. */
  lines?: number;
  /** Width of the last line (shorter to look natural). Defaults to "60%". */
  lastLineWidth?: string;
  className?: string;
}

/**
 * SkeletonText renders a block of placeholder text lines.
 * The last line is narrower by default to mimic real paragraph endings.
 */
export function SkeletonText({
  lines = 3,
  lastLineWidth = "60%",
  className,
}: SkeletonTextProps) {
  return (
    <div className={cn("space-y-2", className)}>
      {Array.from({ length: lines }).map((_, i) => (
        <Skeleton
          key={i}
          className="h-4 rounded"
          style={{
            width: i === lines - 1 ? lastLineWidth : "100%",
          }}
        />
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// SkeletonCard — a full card-shaped loading placeholder
// ---------------------------------------------------------------------------

interface SkeletonCardProps {
  /** Show an avatar/icon placeholder at the top. Defaults to false. */
  showAvatar?: boolean;
  className?: string;
}

/**
 * SkeletonCard renders a card-shaped loading placeholder with an optional
 * avatar row and a few lines of body text.
 */
export function SkeletonCard({ showAvatar = false, className }: SkeletonCardProps) {
  return (
    <div
      className={cn(
        "rounded-xl border border-[var(--stroke2)] bg-[var(--surface1)] p-5 space-y-4",
        className
      )}
    >
      {showAvatar && (
        <div className="flex items-center gap-3">
          <SkeletonAvatar />
          <div className="flex-1 space-y-2">
            <Skeleton className="h-4 w-1/2" />
            <Skeleton className="h-3 w-1/3" />
          </div>
        </div>
      )}
      {/* Title line */}
      <Skeleton className="h-5 w-3/4" />
      {/* Body lines */}
      <SkeletonText lines={3} />
      {/* Action bar */}
      <div className="flex gap-2 pt-1">
        <Skeleton className="h-9 w-24 rounded-lg" />
        <Skeleton className="h-9 w-16 rounded-lg" />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// SkeletonAvatar — a circular avatar placeholder
// ---------------------------------------------------------------------------

interface SkeletonAvatarProps {
  /** Diameter in Tailwind sizing units. Defaults to 10 (40 px). */
  size?: number;
  className?: string;
}

/**
 * SkeletonAvatar renders a circular placeholder used for user avatars or
 * icon containers.
 */
export function SkeletonAvatar({ size = 10, className }: SkeletonAvatarProps) {
  return (
    <Skeleton
      className={cn("rounded-full shrink-0", className)}
      style={{
        width: `${size * 4}px`,
        height: `${size * 4}px`,
      }}
    />
  );
}

// ---------------------------------------------------------------------------
// Default export for convenience
// ---------------------------------------------------------------------------

export default Skeleton;
