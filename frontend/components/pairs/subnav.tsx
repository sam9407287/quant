"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const TABS: { href: string; label: string; hint: string }[] = [
  { href: "/research/pairs", label: "Dashboard", hint: "latest scan, live state, signals" },
  { href: "/research/pairs/analyze", label: "Analyze", hint: "one pair in depth" },
  { href: "/research/pairs/backtest", label: "Backtest", hint: "walk-forward portfolio" },
  { href: "/research/pairs/guide", label: "Guide", hint: "how to read all of this" },
];

export function PairsSubnav() {
  const path = usePathname();
  return (
    <nav className="flex flex-wrap gap-1 rounded-lg border border-border bg-bg-panel p-1 text-sm">
      {TABS.map((t) => {
        const active = t.href === "/research/pairs" ? path === t.href : path.startsWith(t.href);
        return (
          <Link
            key={t.href}
            href={t.href}
            title={t.hint}
            className={`rounded-md px-3 py-1.5 transition ${
              active ? "bg-accent-blue/20 text-accent-blue" : "text-zinc-400 hover:bg-bg-hover hover:text-zinc-100"
            }`}
          >
            {t.label}
          </Link>
        );
      })}
    </nav>
  );
}

export function PairsHeader({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="space-y-4">
      <header>
        <div className="flex items-center gap-3">
          <h1 className="text-2xl font-semibold">{title}</h1>
          <span className="rounded border border-accent-amber/40 bg-accent-amber/10 px-2 py-0.5 font-mono text-[10px] uppercase tracking-wider text-accent-amber">
            Stat-arb lab
          </span>
        </div>
        <p className="mt-2 max-w-3xl text-sm text-zinc-400">{children}</p>
      </header>
      <PairsSubnav />
    </div>
  );
}

export const SECTION = "rounded-lg border border-border bg-bg-panel p-5 space-y-4";
export const LABEL = "block text-xs font-mono uppercase tracking-wider text-zinc-500 mb-1";
export const INPUT =
  "w-full rounded-md border border-border bg-bg-hover px-3 py-2 text-sm font-mono text-zinc-100 focus:border-accent-blue focus:outline-none";
export const BTN =
  "rounded-md bg-accent-blue px-4 py-2 font-mono text-xs uppercase tracking-wider text-white transition hover:bg-accent-blue/80 disabled:cursor-not-allowed disabled:opacity-50";
export const BTN_GHOST =
  "rounded-md border border-border px-3 py-2 font-mono text-xs uppercase tracking-wider text-zinc-300 transition hover:bg-bg-hover disabled:cursor-not-allowed disabled:opacity-50";
export const TH = "px-3 py-2 text-left text-[10px] font-mono uppercase tracking-wider text-zinc-500";
export const TD = "px-3 py-2 font-mono text-xs";

export function Tile({ label, value, tone, hint }: { label: string; value: string; tone?: "pos" | "neg" | "warn"; hint?: string }) {
  const color =
    tone === "pos" ? "text-accent-green" : tone === "neg" ? "text-accent-red" : tone === "warn" ? "text-accent-amber" : "text-zinc-100";
  return (
    <div className="rounded-md border border-border bg-bg-hover p-3" title={hint}>
      <div className="text-[10px] font-mono uppercase tracking-wider text-zinc-500">{label}</div>
      <div className={`mt-1 font-mono text-lg ${color}`}>{value}</div>
    </div>
  );
}

export function ErrorBox({ error }: { error: string | null }) {
  if (!error) return null;
  return (
    <div className="whitespace-pre-wrap rounded-md border border-accent-red/40 bg-accent-red/10 p-3 font-mono text-xs text-accent-red">
      {error}
    </div>
  );
}

export function Empty({ children }: { children: React.ReactNode }) {
  return <div className="rounded-md border border-dashed border-border p-6 text-center text-sm text-zinc-500">{children}</div>;
}
