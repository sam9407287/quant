import Image from "next/image";
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
  { href: "/research/pairs", label: "Pairs" },
];

export function Nav() {
  return (
    <header className="border-b border-border bg-bg-panel">
      <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-y-2 px-4 py-3 sm:px-6 sm:py-4">
        <Link href="/" className="flex items-center gap-2.5 font-mono text-lg font-semibold tracking-tight">
          <Image
            src="/logo-mark.png"
            alt=""
            width={28}
            height={28}
            priority
            className="h-7 w-7"
          />
          quant<span className="text-accent-blue">.futures</span>
        </Link>
        {/* On a phone the nine links do not fit: let the row scroll sideways
            instead of wrapping into three lines or overflowing the viewport. */}
        <nav className="order-last -mx-4 flex w-[calc(100%+2rem)] gap-1 overflow-x-auto whitespace-nowrap px-4 text-sm sm:order-none sm:mx-0 sm:w-auto sm:px-0">
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
