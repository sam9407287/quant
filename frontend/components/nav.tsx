import Link from "next/link";

import { AuthButton } from "@/components/auth/sign-in";
import { PendingBadge } from "@/components/strategies/pending-badge";

const links: { href: string; label: string; badge?: boolean }[] = [
  { href: "/", label: "Dashboard" },
  { href: "/coverage", label: "Coverage" },
  { href: "/chart", label: "Chart" },
  { href: "/research", label: "Research" },
  { href: "/research/experiments", label: "Experiments" },
  { href: "/research/backtest", label: "Backtest" },
  { href: "/research/strategies", label: "Strategies", badge: true },
  { href: "/research/signal-test", label: "Signal Test" },
];

export function Nav() {
  return (
    <header className="border-b border-border bg-bg-panel">
      <div className="mx-auto flex max-w-7xl items-center justify-between px-6 py-4">
        <Link href="/" className="font-mono text-lg font-semibold tracking-tight">
          quant<span className="text-accent-blue">.futures</span>
        </Link>
        <nav className="flex gap-1 text-sm">
          {links.map((l) => (
            <Link
              key={l.href}
              href={l.href}
              className="flex items-center rounded-md px-3 py-1.5 text-zinc-400 transition hover:bg-bg-hover hover:text-zinc-100"
            >
              {l.label}
              {l.badge && <PendingBadge />}
            </Link>
          ))}
        </nav>
        <AuthButton />
      </div>
    </header>
  );
}
