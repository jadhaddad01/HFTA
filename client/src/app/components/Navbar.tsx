import Link from "next/link";

export function Navbar() {
  return (
    <header className="sticky top-0 z-20 border-b border-zinc-800 bg-black/80 backdrop-blur">
      <nav className="mx-auto flex max-w-6xl items-center justify-between px-4 py-3">
        <div className="flex items-center gap-2">
          <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-zinc-900 text-xs font-semibold text-zinc-100">
            H
          </div>
          <div className="text-sm font-medium text-zinc-300">
            HFTA <span className="text-zinc-500">/ High-Frequency Trading Assistant</span>
          </div>
        </div>

        <div className="flex items-center gap-4 text-sm text-zinc-400">
          <Link href="/" className="hover:text-zinc-100">
            Dashboard
          </Link>
          <Link href="/backtest" className="hover:text-zinc-100">
            Backtest
          </Link>
          <Link href="/quotes" className="hover:text-zinc-100">
            Quotes (TODO)
          </Link>
        </div>
      </nav>
    </header>
  );
}
