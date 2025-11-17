# HFTA – High-Frequency Trading Framework (Wealthsimple DRY-RUN)

HFTA is a personal intraday / high-frequency trading framework in Python.

It lets you:

- Design strategies (e.g. micro market maker, micro trend scalper).
- Run them in:
  - Offline backtests on historical or synthetic data.
  - A live **DRY-RUN** engine that talks to a Wealthsimple client, so you can test end-to-end without risking real capital.

> Note: Live trading integration is under active development. The current engine is intended for DRY-RUN / paper trading only.

---

## Project structure

```text
HFTA/
  broker/
    client.py          # Wealthsimple client abstraction (login, quotes, orders)
  core/
    engine.py          # Main engine loop (live / DRY-RUN)
    order_manager.py   # Accepts OrderIntent, runs risk checks, records fills
    risk_manager.py    # Risk limits (notional, cash utilisation, shorting)
    execution_tracker.py  # Positions, fills, realized PnL, equity
  sim/
    backtester.py      # BacktestEngine + BacktestConfig
  strategies/
    micro_market_maker.py  # Single-symbol market maker
    micro_trend_scalper.py # Short-term trend-following scalper
  ai/
    controller.py      # Optional AI controller for parameter suggestions
  logging_utils.py     # Shared logging setup (setup_logging, parse_log_level)

configs/
  paper_aapl.json      # Example config: AAPL, paper cash, MM + scalper

scripts/
  run_backtest.py      # Offline backtesting CLI
  run_engine.py        # DRY-RUN engine CLI
  download_aapl_yfinance.py  # Helper to fetch AAPL 1m data into CSV
  plot_equity_curve.py # Analyse / plot equity curve from CSV

tests/
  ...                  # (future) pytest-based tests
