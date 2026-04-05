"use client";

/**
 * MessageSkeleton — animated placeholder shown while waiting for an
 * assistant response. Matches the assistant bubble layout in MessageBubble.
 */

export function MessageSkeleton() {
  return (
    <div className="flex flex-col gap-1 mb-4 items-start" aria-hidden="true">
      <div className="flex items-start gap-2">
        {/* Avatar circle */}
        <div className="h-7 w-7 rounded-full bg-white/10 animate-pulse flex-shrink-0 mt-0.5" />

        {/* Skeleton lines inside an assistant-styled bubble */}
        <div className="dd-chat-bubble assistant flex flex-col gap-2 min-w-[180px]">
          <div className="h-3 w-3/4 rounded-full bg-white/10 animate-pulse" />
          <div className="h-3 w-1/2 rounded-full bg-white/10 animate-pulse" />
          <div className="h-3 w-2/3 rounded-full bg-white/10 animate-pulse" />
        </div>
      </div>
    </div>
  );
}
