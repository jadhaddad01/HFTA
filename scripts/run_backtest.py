# scripts/run_backtest.py

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import List, Optional

from HFTA.broker.client import Quote
from HFTA.core.risk_manager import RiskConfig
from HFTA.sim.backtester import BacktestConfig, BacktestEngine
from HFTA.strategies.base import Strategy
from HFTA.strategies.micro_market_maker import MicroMarketMaker
from HFTA.strategies.micro_trend_scalper import MicroTrendScalper


STRATEGY_REGISTRY = {
    "micro_market_maker": MicroMarketMaker,
    "micro_trend_scalper": MicroTrendScalper,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def load_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def build_risk_config(cfg: dict) -> RiskConfig:
    risk = cfg.get("risk", {})
    return RiskConfig(
        max_notional_per_order=risk.get("max_notional_per_order", 100.0),
        max_cash_utilization=risk.get("max_cash_utilization", 0.1),
        allow_short_selling=risk.get("allow_short_selling", False),
    )


def build_strategies(cfg: dict) -> List[Strategy]:
    """
    Expected config shape:

    "strategies": [
      {
        "type": "micro_market_maker",
        "name": "mm_AAPL",
        "config": { ... }
      },
      ...
    ]
    """
    out: List[Strategy] = []
    for strat_cfg in cfg.get("strategies", []):
        type_key = strat_cfg["type"]
        name = strat_cfg["name"]
        strat_cls = STRATEGY_REGISTRY[type_key]
        strat_config = strat_cfg.get("config", {})
        out.append(strat_cls(name=name, config=strat_config))
    return out


def export_equity_csv(path: Path, result) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp", "equity"])
        for ts, eq in zip(result.timestamps, result.equity_curve):
            ts_str = ts.isoformat() if hasattr(ts, "isoformat") else str(ts)
            writer.writerow([ts_str, f"{eq:.4f}"])


def export_fills_csv(path: Path, engine: BacktestEngine) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["symbol", "side", "quantity", "price", "timestamp"])
        for fl in engine.tracker.fills:
            writer.writerow(
                [
                    fl.symbol,
                    fl.side,
                    f"{fl.quantity:.4f}",
                    f"{fl.price:.4f}",
                    fl.timestamp or "",
                ]
            )


def _maybe_float(row: dict, key: str) -> Optional[float]:
    val = row.get(key)
    if val is None:
        return None
    val = val.strip()
    if not val:
        return None
    try:
        return float(val)
    except ValueError:
        return None


def load_quotes_from_csv(path: str, symbol: str) -> List[Quote]:
    """
    Load historical quotes from a CSV file.

    Expected columns (header names):

        timestamp,bid,ask,last[,bid_size,ask_size]

    - timestamp: ISO8601 string (e.g. 2024-01-02T09:30:00)
    - bid/ask/last: numeric
    - bid_size/ask_size: optional numeric

    Any missing numeric cell is interpreted as None. If bid/ask are
    missing but we have a last price, we synthesise a tight spread
    around last so spread-based strategies can run.
    """
    quotes: List[Quote] = []
    with open(path, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            ts = row.get("timestamp") or row.get("time") or row.get("datetime")

            bid = _maybe_float(row, "bid")
            ask = _maybe_float(row, "ask")
            last = (
                _maybe_float(row, "last")
                or _maybe_float(row, "close")
                or _maybe_float(row, "price")
            )
            bid_size = _maybe_float(row, "bid_size")
            ask_size = _maybe_float(row, "ask_size")

            # If we have neither last nor a full bid/ask, skip this row.
            if last is None and (bid is None or ask is None):
                continue

            # If last is missing but both bid and ask exist, infer last as mid.
            if last is None and bid is not None and ask is not None:
                last = (bid + ask) / 2.0

            # If bid/ask are missing but we do have a last price,
            # create a synthetic spread around last.
            if last is not None and (bid is None or ask is None):
                half_spread = 0.01  # 1 cent each side
                bid = last - half_spread
                ask = last + half_spread

            quotes.append(
                Quote(
                    symbol=symbol.upper(),
                    security_id=f"HIST-{symbol.upper()}",
                    bid=bid,
                    ask=ask,
                    last=last,
                    bid_size=bid_size,
                    ask_size=ask_size,
                    timestamp=ts,
                )
            )
    return quotes


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run HFTA strategies in offline backtest mode."
    )
    parser.add_argument(
        "--config",
        default="configs/paper_aapl.json",
        help="Path to JSON config file (default: configs/paper_aapl.json)",
    )
    parser.add_argument(
        "--steps",
        type=int,
        default=2000,
        help=(
            "Number of synthetic quote steps to simulate (default: 2000). "
            "Ignored if --quotes-csv is provided."
        ),
    )
    parser.add_argument(
        "--quotes-csv",
        type=str,
        default=None,
        help=(
            "Optional path to CSV of historical quotes "
            "(timestamp,bid,ask,last[,bid_size,ask_size]). "
            "If provided, these quotes are used instead of synthetic random walk."
        ),
    )
    parser.add_argument(
        "--equity-csv",
        type=str,
        default=None,
        help="Optional path to write equity curve CSV.",
    )
    parser.add_argument(
        "--fills-csv",
        type=str,
        default=None,
        help="Optional path to write fill blotter CSV.",
    )

    args = parser.parse_args()

    cfg_json = load_json(args.config)
    risk_cfg = build_risk_config(cfg_json)
    strategies = build_strategies(cfg_json)

    symbols = cfg_json.get("symbols") or ["AAPL"]
    symbol = symbols[0].upper()

    paper_cash = float(cfg_json.get("paper_cash", 100_000.0))
    poll_interval = int(cfg_json.get("poll_interval", 5))
    starting_price = float(cfg_json.get("starting_price", 40.0))
    volatility_annual = float(cfg_json.get("volatility_annual", 0.4))
    spread_cents = float(cfg_json.get("spread_cents", 0.10))

    bt_cfg = BacktestConfig(
        symbol=symbol,
        starting_price=starting_price,
        starting_cash=paper_cash,
        steps=args.steps,
        step_seconds=poll_interval,
        volatility_annual=volatility_annual,
        spread_cents=spread_cents,
        risk_config=risk_cfg,
    )

    quotes: Optional[List[Quote]] = None
    if args.quotes_csv:
        quotes = load_quotes_from_csv(args.quotes_csv, symbol=symbol)

    engine = BacktestEngine(strategies=strategies, config=bt_cfg, quotes=quotes)
    result = engine.run()

    # ------------------------------------------------------------------ #
    # Summary
    # ------------------------------------------------------------------ #

    print("=== BACKTEST SUMMARY ===")
    print(f"Symbol: {result.symbol}")
    print(f"Starting cash: {result.starting_cash:,.2f}")
    print(f"Final cash: {result.final_cash:,.2f}")
    print(f"Final equity: {result.final_equity:,.2f}")
    print(f"Realized PnL: {result.realized_pnl:,.2f}")
    print(f"Max drawdown: {result.max_drawdown:.2%}")
    print(f"Steps simulated: {len(result.equity_curve)}")

    print()
    print("Trade stats:")
    print(f"  Trades: {result.num_trades}")
    print(f"  Wins:   {result.num_winning_trades}")
    print(f"  Losses: {result.num_losing_trades}")
    print(f"  Best trade PnL:  {result.best_trade_pnl:,.2f}")
    print(f"  Worst trade PnL: {result.worst_trade_pnl:,.2f}")
    print(f"  Avg trade PnL:   {result.avg_trade_pnl:,.2f}")
    print(f"  Sharpe-like (per-step): {result.sharpe_like:.3f}")

    print()
    print("Open positions at end:")
    for sym, pos in result.positions_summary.items():
        print(
            f"  {sym}: qty={pos.quantity:.2f}, "
            f"avg_price={pos.avg_price:.2f}, "
            f"realized_pnl={pos.realized_pnl:.2f}"
        )

    # ------------------------------------------------------------------ #
    # Optional CSV exports
    # ------------------------------------------------------------------ #

    if args.equity_csv:
        export_equity_csv(Path(args.equity_csv), result)
        print(f"\nEquity curve written to {args.equity_csv}")

    if args.fills_csv:
        export_fills_csv(Path(args.fills_csv), engine)
        print(f"Fills blotter written to {args.fills_csv}")


if __name__ == "__main__":
    main()
