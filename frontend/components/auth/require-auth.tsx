"use client";

// Gate for pages whose actions require a signed-in user. When auth is
// not configured at all (no NEXT_PUBLIC_GOOGLE_CLIENT_ID, e.g. local
// dev), the gate stands aside — the backend still enforces access.

import { GOOGLE_CLIENT_ID, useAuth } from "@/lib/auth";

export function RequireAuth({ children }: { children: React.ReactNode }) {
  const { user, ready } = useAuth();

  if (!GOOGLE_CLIENT_ID) return <>{children}</>;
  if (!ready) return null;
  if (user) return <>{children}</>;

  return (
    <div className="rounded-lg border border-border bg-bg-panel p-10 text-center">
      <p className="text-sm text-zinc-300">
        Sign in with Google (top right) to use this page.
      </p>
      <p className="mt-2 text-xs text-zinc-500">
        Your strategies and backtests are private to your account.
      </p>
    </div>
  );
}
