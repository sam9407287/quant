"use client";

/**
 * Strategy sharing panel.
 *
 * Incoming requests are the notification surface: opening this page marks
 * them seen, which is what clears the nav badge, while the requests
 * themselves stay pending until the owner actually decides.
 */

import { useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";

import {
  decideAccess,
  fetchAccess,
  markAccessSeen,
  requestAccess,
  type AccessOverview,
  type AccessRow,
  type AccessStatus,
} from "@/lib/strategies";

const STATUS_TONE: Record<AccessStatus, string> = {
  pending: "bg-amber-400/10 text-amber-300 ring-amber-400/30",
  granted: "bg-emerald-400/10 text-emerald-300 ring-emerald-400/30",
  denied: "bg-accent-red/10 text-accent-red ring-accent-red/30",
  revoked: "bg-zinc-500/10 text-zinc-400 ring-zinc-500/30",
};

function StatusChip({ status }: { status: AccessStatus }) {
  return (
    <span
      className={`rounded px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wider ring-1 ring-inset ${STATUS_TONE[status]}`}
    >
      {status}
    </span>
  );
}

function Person({ row }: { row: AccessRow }) {
  return (
    <span className="flex min-w-0 items-center gap-2">
      {row.counterparty_picture ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={row.counterparty_picture} alt="" className="h-6 w-6 shrink-0 rounded-full" />
      ) : (
        <span className="grid h-6 w-6 shrink-0 place-items-center rounded-full bg-bg-hover font-mono text-[10px] text-zinc-400">
          {row.counterparty_email.slice(0, 2).toUpperCase()}
        </span>
      )}
      <span className="truncate text-zinc-200">{row.counterparty_email}</span>
    </span>
  );
}

const BTN = "rounded px-2 py-1 font-mono text-[11px] transition";

export function SharingPanel({ onChanged }: { onChanged: () => void }) {
  const [data, setData] = useState<AccessOverview | null>(null);
  const [email, setEmail] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const next = await fetchAccess();
      setData(next);
      // Seeing the list is what clears the badge; the requests stay pending.
      if (next.pending_count > 0) {
        await markAccessSeen();
        onChanged();
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [onChanged]);

  useEffect(() => {
    void load();
  }, [load]);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await requestAccess(email.trim(), message.trim() || null);
      setNotice(`Request sent to ${email.trim()}.`);
      setEmail("");
      setMessage("");
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function decide(id: string, status: "granted" | "denied" | "revoked") {
    setBusy(true);
    setError(null);
    try {
      await decideAccess(id, status);
      await load();
      onChanged(); // granting changes which strategies are visible
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  const incoming = data?.incoming ?? [];
  const outgoing = data?.outgoing ?? [];
  const pending = incoming.filter((r) => r.status === "pending");

  return (
    <section className="space-y-4 rounded-lg border border-border bg-bg-panel p-5">
      <div>
        <h2 className="text-sm font-semibold text-zinc-200">Shared access</h2>
        <p className="mt-1 text-xs text-zinc-500">
          Someone you grant can open, back-test and copy your strategies. They can
          never edit or delete them.
        </p>
      </div>

      {pending.length > 0 && (
        <div className="rounded-md border border-amber-400/40 bg-amber-400/10 px-3 py-2 text-xs text-amber-200">
          {pending.length} {pending.length === 1 ? "person is" : "people are"} waiting
          on your decision.
        </div>
      )}

      {/* Incoming — the notification surface */}
      <div>
        <h3 className="mb-2 font-mono text-[10px] uppercase tracking-wider text-zinc-600">
          Requests for my strategies
        </h3>
        {incoming.length === 0 ? (
          <p className="text-xs text-zinc-600">Nobody has asked yet.</p>
        ) : (
          <ul className="divide-y divide-border">
            {incoming.map((row) => (
              <li key={row.id} className="flex flex-wrap items-center gap-3 py-2 text-xs">
                <Person row={row} />
                <StatusChip status={row.status} />
                {row.message && (
                  <span className="truncate text-zinc-500">“{row.message}”</span>
                )}
                <span className="ml-auto flex gap-1">
                  {row.status === "pending" && (
                    <>
                      <button
                        type="button"
                        disabled={busy}
                        onClick={() => void decide(row.id, "granted")}
                        className={`${BTN} bg-emerald-400/15 text-emerald-300 hover:bg-emerald-400/25`}
                      >
                        Approve
                      </button>
                      <button
                        type="button"
                        disabled={busy}
                        onClick={() => void decide(row.id, "denied")}
                        className={`${BTN} bg-bg-hover text-zinc-400 hover:text-zinc-100`}
                      >
                        Deny
                      </button>
                    </>
                  )}
                  {row.status === "granted" && (
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => void decide(row.id, "revoked")}
                      className={`${BTN} bg-bg-hover text-accent-red hover:bg-accent-red/20`}
                    >
                      Revoke
                    </button>
                  )}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* Outgoing */}
      <div>
        <h3 className="mb-2 font-mono text-[10px] uppercase tracking-wider text-zinc-600">
          My requests to others
        </h3>
        {outgoing.length === 0 ? (
          <p className="text-xs text-zinc-600">You have not asked anyone yet.</p>
        ) : (
          <ul className="divide-y divide-border">
            {outgoing.map((row) => (
              <li key={row.id} className="flex flex-wrap items-center gap-3 py-2 text-xs">
                <Person row={row} />
                <StatusChip status={row.status} />
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* Ask */}
      <form onSubmit={submit} className="flex flex-wrap items-end gap-2 border-t border-border pt-4">
        <label className="flex-1">
          <span className="mb-1 block font-mono text-[10px] uppercase tracking-wider text-zinc-600">
            Request access to a Google account
          </span>
          <input
            type="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="someone@gmail.com"
            className="w-full rounded-md border border-border bg-bg-hover px-3 py-2 font-mono text-xs text-zinc-100 placeholder:text-zinc-600 focus:border-accent-blue focus:outline-none"
          />
        </label>
        <label className="flex-1">
          <span className="mb-1 block font-mono text-[10px] uppercase tracking-wider text-zinc-600">
            Note (optional)
          </span>
          <input
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            maxLength={280}
            placeholder="Why you would like to see them"
            className="w-full rounded-md border border-border bg-bg-hover px-3 py-2 text-xs text-zinc-100 placeholder:text-zinc-600 focus:border-accent-blue focus:outline-none"
          />
        </label>
        <button
          type="submit"
          disabled={busy || !email.trim()}
          className="rounded-md bg-accent-blue px-4 py-2 text-xs font-semibold text-white transition hover:bg-accent-blue/80 disabled:opacity-40"
        >
          Request
        </button>
      </form>

      {notice && <p className="text-xs text-emerald-300">{notice}</p>}
      {error && (
        <pre className="whitespace-pre-wrap rounded-md border border-accent-red/40 bg-accent-red/10 p-3 text-[11px] text-accent-red">
          {error}
        </pre>
      )}
    </section>
  );
}
