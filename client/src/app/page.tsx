export default function Home() {
  return (
    <section className="space-y-8">
      <header className="space-y-2">
        <h1 className="text-3xl font-semibold tracking-tight">
          HFTA Dashboard
        </h1>
        <p className="max-w-2xl text-sm text-zinc-400">
          Monitor your engine, run simulations, and explore market data. This is
          just the shell for now – the real metrics will be wired in later.
        </p>
      </header>

      <div className="grid gap-6 md:grid-cols-3">
        <div className="rounded-xl border border-zinc-800 bg-zinc-950 p-4">
          <div className="text-xs font-medium text-zinc-500">Status</div>
          <div className="mt-2 text-lg font-semibold text-emerald-400">
            Engine: TODO
          </div>
          <p className="mt-1 text-xs text-zinc-500">
            Later we’ll show whether DRY-RUN / live engine is running and last
            heartbeat.
          </p>
        </div>

        <div className="rounded-xl border border-zinc-800 bg-zinc-950 p-4">
          <div className="text-xs font-medium text-zinc-500">
            Latest Backtest
          </div>
          <div className="mt-2 text-lg font-semibold text-zinc-100">
            TODO: Strategy / PnL
          </div>
          <p className="mt-1 text-xs text-zinc-500">
            This card will show basic stats from the most recent backtest run
            (PnL, max DD, Sharpe, etc.).
          </p>
        </div>

        <div className="rounded-xl border border-zinc-800 bg-zinc-950 p-4">
          <div className="text-xs font-medium text-zinc-500">Data</div>
          <div className="mt-2 text-lg font-semibold text-zinc-100">
            Quotes captured: TODO
          </div>
          <p className="mt-1 text-xs text-zinc-500">
            Later we’ll query Postgres and show how many quote rows you’ve
            recorded for your universe.
          </p>
        </div>
      </div>

      <div className="grid gap-6 md:grid-cols-2">
        <div className="rounded-xl border border-zinc-800 bg-zinc-950 p-4">
          <h2 className="text-sm font-semibold text-zinc-100">
            Live Engine (DRY-RUN)
          </h2>
          <p className="mt-2 text-xs text-zinc-500">
            TODO: show current positions, unrealized PnL, and recent trades from{" "}
            <code className="rounded bg-zinc-900 px-1 py-0.5 text-[10px]">
              ExecutionTracker
            </code>
            .
          </p>
        </div>

        <div className="rounded-xl border border-zinc-800 bg-zinc-950 p-4">
          <h2 className="text-sm font-semibold text-zinc-100">
            Strategy Sandbox
          </h2>
          <p className="mt-2 text-xs text-zinc-500">
            TODO: a quick selector to choose strategy configs (market maker,
            scalper, etc.) before running backtests.
          </p>
        </div>
      </div>
    </section>
  );
}
