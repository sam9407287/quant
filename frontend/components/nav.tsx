import Link from "next/link";

const links = [
  { href: "/", label: "Dashboard" },
  { href: "/coverage", label: "Coverage" },
  { href: "/chart", label: "Chart" },
  { href: "/research", label: "Research" },
  { href: "/research/experiments", label: "Experiments" },
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
              className="rounded-md px-3 py-1.5 text-zinc-400 transition hover:bg-bg-hover hover:text-zinc-100"
            >
              {l.label}
            </Link>
          ))}
        </nav>
      </div>
    </header>
  );
}
