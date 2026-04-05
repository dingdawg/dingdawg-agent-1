"use client";

/**
 * PullToRefresh — touch-based pull-to-refresh for PWA standalone mode.
 *
 * iOS Safari in standalone mode disables the native pull-to-refresh,
 * so we implement it manually using touch events.
 *
 * Threshold: 80px pull distance triggers refresh.
 * Spinner appears during pull and while onRefresh is pending.
 */

import { useRef, useState, useCallback } from "react";
import { cn } from "@/lib/utils";

interface PullToRefreshProps {
  onRefresh: () => void | Promise<void>;
  children: React.ReactNode;
  threshold?: number;
  className?: string;
}

const THRESHOLD = 80;
const MAX_PULL = 120;

export default function PullToRefresh({
  onRefresh,
  children,
  threshold = THRESHOLD,
  className,
}: PullToRefreshProps) {
  const [pullY, setPullY] = useState(0);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const startYRef = useRef<number | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  const handleTouchStart = useCallback((e: React.TouchEvent) => {
    // Only activate at the very top of the scroll container
    const el = containerRef.current;
    if (!el) return;
    if (el.scrollTop > 0) return;
    startYRef.current = e.touches[0].clientY;
  }, []);

  const handleTouchMove = useCallback(
    (e: React.TouchEvent) => {
      if (startYRef.current === null || isRefreshing) return;
      const el = containerRef.current;
      if (!el || el.scrollTop > 0) {
        startYRef.current = null;
        return;
      }
      const delta = e.touches[0].clientY - startYRef.current;
      if (delta <= 0) return;
      // Clamp with resistance curve
      const clamped = Math.min(MAX_PULL, delta * 0.55);
      setPullY(clamped);
    },
    [isRefreshing]
  );

  const handleTouchEnd = useCallback(async () => {
    if (startYRef.current === null) return;
    startYRef.current = null;

    if (pullY >= threshold) {
      setIsRefreshing(true);
      setPullY(threshold * 0.6);
      try {
        await onRefresh();
      } finally {
        setIsRefreshing(false);
        setPullY(0);
      }
    } else {
      setPullY(0);
    }
  }, [pullY, threshold, onRefresh]);

  const progress = Math.min(1, pullY / threshold);
  const spinnerOpacity = isRefreshing ? 1 : progress;
  const showIndicator = pullY > 8 || isRefreshing;

  return (
    <div
      ref={containerRef}
      className={cn("relative overflow-y-auto", className)}
      onTouchStart={handleTouchStart}
      onTouchMove={handleTouchMove}
      onTouchEnd={handleTouchEnd}
      style={{ WebkitOverflowScrolling: "touch" }}
    >
      {/* Pull indicator */}
      <div
        aria-hidden="true"
        className="absolute top-0 left-0 right-0 flex items-center justify-center pointer-events-none z-10 transition-all duration-200"
        style={{
          height: `${pullY}px`,
          opacity: showIndicator ? 1 : 0,
        }}
      >
        <div
          className="w-8 h-8 rounded-full bg-[#0d1926] border border-[#1a2a3d] flex items-center justify-center shadow-lg"
          style={{ opacity: spinnerOpacity }}
        >
          <div
            className={cn(
              "w-4 h-4 border-2 border-[var(--gold-400)] border-t-transparent rounded-full",
              isRefreshing ? "animate-spin" : ""
            )}
            style={
              !isRefreshing
                ? { transform: `rotate(${progress * 270}deg)`, transition: "none" }
                : undefined
            }
          />
        </div>
      </div>

      {/* Content offset during pull */}
      <div
        style={{
          transform: `translateY(${pullY}px)`,
          transition: pullY === 0 ? "transform 0.2s ease-out" : "none",
        }}
      >
        {children}
      </div>
    </div>
  );
}
