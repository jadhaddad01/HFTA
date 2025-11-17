# scripts/run_engine.py

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Any, Dict, List

from HFTA.ai.controller import AIController
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

STRATEGY_REGISTRY = {
    "micro_market_maker": MicroMarketMaker,
    "micro_trend_scalper": MicroTrendScalper,
}


def load_config(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"Config file not found: {path}")
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def build_strategies(cfg: Dict[str, Any]) -> List[Any]:
    strategies_cfg = cfg.get("strategies", [])
    strategies: List[Any] = []

    for s in strategies_cfg:
        s_type = s["type"]
        name = s["name"]
        s_conf = s.get("config", {})

        cls = STRATEGY_REGISTRY.get(s_type)
        if cls is None:
            raise ValueError(f"Unknown strategy type in config: {s_type!r}")

        strategies.append(cls(name=name, config=s_conf))

    return strategies


def build_ai_controller(cfg: Dict[str, Any]) -> AIController | None:
    ai_cfg = cfg.get("ai") or {}
    enabled = bool(ai_cfg.get("enabled", False))
    if not enabled:
        return None

    return AIController(
        model=ai_cfg.get("model", "gpt-4.1-mini"),
        interval_loops=int(ai_cfg.get("interval_loops", 12)),
        temperature=float(ai_cfg.get("temperature", 0.2)),
        max_output_tokens=int(ai_cfg.get("max_output_tokens", 512)),
        enabled=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run HFTA engine.")
    parser.add_argument(
        "--config",
        "-c",
        default="configs/paper_aapl.json",
        help="Path to JSON config file (default: configs/paper_aapl.json)",
    )
    args = parser.parse_args()

    cfg_path = Path(args.config)
    cfg = load_config(cfg_path)

    paper_cash = float(cfg.get("paper_cash", 0.0)) or None
    poll_interval = float(cfg.get("poll_interval", 5.0))
    symbols = [s.upper() for s in cfg.get("symbols", ["AAPL"])]

    risk_cfg_raw = cfg.get("risk", {})
    risk_cfg = RiskConfig(
        max_notional_per_order=float(risk_cfg_raw.get("max_notional_per_order", 1000.0)),
        max_cash_utilization=float(risk_cfg_raw.get("max_cash_utilization", 0.10)),
        allow_short_selling=bool(risk_cfg_raw.get("allow_short_selling", False)),
    )
    risk_manager = RiskManager(risk_cfg)

    client = WealthsimpleClient()
    execution_tracker = ExecutionTracker()

    order_manager = OrderManager(
        client=client,
        risk_manager=risk_manager,
        execution_tracker=execution_tracker,
        live=False,  # still DRY-RUN; live mode comes later
    )

    strategies = build_strategies(cfg)
    ai_controller = build_ai_controller(cfg)

    engine = Engine(
        client=client,
        strategies=strategies,
        symbols=symbols,
        order_manager=order_manager,
        poll_interval=poll_interval,
        paper_cash=paper_cash,
        ai_controller=ai_controller,
    )

    print(
        f"Starting HFTA engine in DRY-RUN mode on account name='HFTA' "
        f"using config: {cfg_path}"
    )
    engine.run_forever()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped by user.")

# Testing new Org
