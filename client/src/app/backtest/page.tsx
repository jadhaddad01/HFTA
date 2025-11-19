export default function BacktestPage() {
  return (
    <section className="space-y-8">
      <header className="space-y-2">
        <h1 className="text-3xl font-semibold tracking-tight">
          Backtest Lab
        </h1>
        <p className="max-w-2xl text-sm text-zinc-400">
          This is where we&apos;ll hook into the Python backtester. For now,
          it&apos;s just a structured TODO.
        </p>
      </header>

      <div className="grid gap-6 lg:grid-cols-3">
        <div className="rounded-xl border border-zinc-800 bg-zinc-950 p-4 lg:col-span-1">
          <h2 className="text-sm font-semibold text-zinc-100">
            Configuration (TODO)
          </h2>
          <p className="mt-2 text-xs text-zinc-500">
            Later: select config file, number of steps, symbol universe,
            strategy params, etc.
          </p>
          <ul className="mt-3 list-disc space-y-1 pl-4 text-xs text-zinc-500">
            <li>Dropdown for config JSON</li>
            <li>Number input for steps</li>
            <li>Strategy selector / toggles</li>
          </ul>
        </div>

        <div className="space-y-6 lg:col-span-2">
          <div className="rounded-xl border border-zinc-800 bg-zinc-950 p-4">
            <h2 className="text-sm font-semibold text-zinc-100">
              Run Backtest (TODO)
            </h2>
            <p className="mt-2 text-xs text-zinc-500">
              This will trigger a call to a FastAPI endpoint that runs{" "}
              <code className="rounded bg-zinc-900 px-1 py-0.5 text-[10px]">
                BacktestEngine
              </code>{" "}
              and returns summary stats + equity curve.
            </p>
            <button
              className="mt-4 inline-flex items-center rounded-lg bg-zinc-800 px-4 py-2 text-xs font-semibold text-zinc-100 opacity-50"
              disabled
            >
              Run simulation (disabled – API not wired yet)
            </button>
          </div>

          <div className="rounded-xl border border-zinc-800 bg-zinc-950 p-4">
            <h2 className="text-sm font-semibold text-zinc-100">
              Results (TODO)
            </h2>
            <p className="mt-2 text-xs text-zinc-500">
              Here we&apos;ll show equity curve chart, summary metrics (PnL,
              max drawdown, Sharpe) and a table of trades. For now it&apos;s a
              placeholder.
            </p>
          </div>
        </div>
      </div>
    </section>
  );
}
