"use client";

/**
 * Unseen strategy-access requests, shown on the Strategies nav link.
 *
 * Polling is deliberate and slow: this is a "someone is waiting on you"
 * hint, not a live feed, and the count is one indexed COUNT(*). The sharing
 * panel fires `ACCESS_SEEN_EVENT` when it marks requests seen so the badge
 * clears immediately instead of waiting for the next poll.
 */

import { useCallback, useEffect, useState } from "react";

import { useAuth } from "@/lib/auth";
import { fetchAccess } from "@/lib/strategies";

export const ACCESS_SEEN_EVENT = "quant:access-seen";

const POLL_MS = 120_000;

export function PendingBadge() {
  const { user, ready } = useAuth();
  const [count, setCount] = useState(0);

  const refresh = useCallback(async () => {
    if (!user) {
      setCount(0);
      return;
    }
    try {
      setCount((await fetchAccess()).pending_count);
    } catch {
      // A badge must never surface an error; absence is the failure mode.
      setCount(0);
    }
  }, [user]);

  useEffect(() => {
    if (!ready) return;
    void refresh();
    const timer = window.setInterval(() => void refresh(), POLL_MS);
    const onSeen = () => setCount(0);
    window.addEventListener(ACCESS_SEEN_EVENT, onSeen);
    return () => {
      window.clearInterval(timer);
      window.removeEventListener(ACCESS_SEEN_EVENT, onSeen);
    };
  }, [ready, refresh]);

  if (count <= 0) return null;
  return (
    <span
      title={`${count} pending access ${count === 1 ? "request" : "requests"}`}
      className="ml-1 inline-grid h-4 min-w-4 place-items-center rounded-full bg-accent-red px-1 font-mono text-[10px] font-semibold leading-none text-white"
    >
      {count > 9 ? "9+" : count}
    </span>
  );
}
