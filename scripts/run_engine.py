# scripts/run_engine.py

from __future__ import annotations

import logging

from HFTA.broker.client import WealthsimpleClient
from HFTA.core.engine import Engine
from HFTA.core.execution_tracker import ExecutionTracker
from HFTA.core.order_manager import OrderManager
from HFTA.core.risk_manager import RiskConfig, RiskManager
from HFTA.strategies.micro_market_maker import MicroMarketMaker
from HFTA.strategies.micro_trend_scalper import MicroTrendScalper

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)


def main() -> None:
    # Uses the HFTA account by default (name == 'HFTA')
    client = WealthsimpleClient()

    # Strategy 1: micro market maker around the mid
    mm = MicroMarketMaker(
        name="mm_AAPL",
        config={
            "symbol": "AAPL",
            "max_inventory": 2,
            "spread": 0.05,
            "order_quantity": 1,
        },
    )

    # Strategy 2: micro trend-following scalper
    scalper = MicroTrendScalper(
        name="scalper_AAPL",
        config={
            "symbol": "AAPL",
            "order_quantity": 1,
            "short_window": 5,
            "long_window": 20,
            "trend_threshold": 0.0005,  # ~5 bps divergence
            "max_position": 5,
        },
    )

    # Risk configuration tuned for paper trading:
    # - Higher per-order cap so the bot can trade
    # - 10% of (paper) cash per order
    risk_cfg = RiskConfig(
        max_notional_per_order=1000.0,  # was 50.0
        max_cash_utilization=0.10,
        allow_short_selling=False,
    )
    risk_manager = RiskManager(risk_cfg)

    execution_tracker = ExecutionTracker()

    order_manager = OrderManager(
        client=client,
        risk_manager=risk_manager,
        execution_tracker=execution_tracker,
        live=False,  # still DRY-RUN: no live orders
    )

    engine = Engine(
        client=client,
        strategies=[mm, scalper],
        symbols=["AAPL"],
        order_manager=order_manager,
        poll_interval=5.0,
        paper_cash=100_000.0,  # your 100k starting capital in paper mode
    )

    print(
        "Starting HFTA engine in DRY-RUN mode on account name='HFTA' "
        "with strategies: mm_AAPL + scalper_AAPL, paper_cash=100000. Ctrl+C to stop."
    )
    engine.run_forever()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped by user.")
