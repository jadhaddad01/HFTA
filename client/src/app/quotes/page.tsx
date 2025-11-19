export default function QuotesPage() {
  return (
    <section className="space-y-8">
      <header className="space-y-2">
        <h1 className="text-3xl font-semibold tracking-tight">
          Quotes &amp; Data (TODO)
        </h1>
        <p className="max-w-2xl text-sm text-zinc-400">
          This will show what your engine has been saving into Postgres
          (quotebar table) – per-symbol history, daily aggregates, etc.
        </p>
      </header>

      <div className="rounded-xl border border-zinc-800 bg-zinc-950 p-4">
        <h2 className="text-sm font-semibold text-zinc-100">
          Recent Quotes (placeholder)
        </h2>
        <p className="mt-2 text-xs text-zinc-500">
          Later: fetch from a Python API endpoint that queries Postgres and
          returns quote snapshots for a chosen symbol over a timeframe.
        </p>
      </div>
    </section>
  );
}
