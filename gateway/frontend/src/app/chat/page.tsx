"use client";

/**
 * Chat page — redirects to /dashboard (chat-first dashboard is the primary experience).
 */

import { useEffect } from "react";
import { useRouter } from "next/navigation";

export default function ChatPage() {
  const router = useRouter();

  useEffect(() => {
    router.replace("/dashboard");
  }, [router]);

  return null;
}
