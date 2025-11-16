# HFTA/core/risk_manager.py

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional, Dict, Any

from HFTA.broker.client import Quote, PortfolioSnapshot, Holding
from HFTA.strategies.base import OrderIntent

logger = logging.getLogger(__name__)


@dataclass
class RiskConfig:
    """
    Very simple risk configuration.

    - max_notional_per_order: absolute cap per order (e.g. 100.0 = $100)
    - max_cash_utilization: fraction of current cash that a single BUY can use
      (e.g. 0.1 = 10% of available cash)
    - allow_short_selling: if False, SELL quantity may not exceed current
      long position (no opening new shorts).
    """
    max_notional_per_order: float = 100.0
    max_cash_utilization: float = 0.1
    allow_short_selling: bool = False


class RiskManager:
    """
    Stateless per-order risk checks.
    """

    def __init__(self, config: RiskConfig) -> None:
        self.config = config

    def _infer_price(self, oi: OrderIntent, quote: Quote) -> Optional[float]:
        # Prefer explicit limit, otherwise use last/ask/bid in that order
        if oi.limit_price is not None:
            return float(oi.limit_price)
        if quote.last is not None:
            return float(quote.last)
        if oi.side.lower() == "buy" and quote.ask is not None:
            return float(quote.ask)
        if oi.side.lower() == "sell" and quote.bid is not None:
            return float(quote.bid)
        return None

    def _holding_qty(self, symbol: str, positions: Dict[str, Holding]) -> float:
        h: Holding | Any | None = positions.get(symbol.upper())
        if h is None:
            return 0.0
        qty = getattr(h, "quantity", None)
        if qty is None:
            return 0.0
        try:
            return float(qty)
        except (TypeError, ValueError):
            return 0.0

    def approve(
        self,
        oi: OrderIntent,
        quote: Quote,
        snapshot: PortfolioSnapshot,
        positions: Dict[str, Holding],
    ) -> bool:
        price = self._infer_price(oi, quote)
        if price is None:
            logger.info("Risk: rejecting %s (no usable price)", oi)
            return False

        notional = price * oi.quantity

        # Hard cap per order
        if notional > self.config.max_notional_per_order:
            logger.info(
                "Risk: rejecting %s (notional %.2f > max_notional_per_order %.2f)",
                oi, notional, self.config.max_notional_per_order,
            )
            return False

        side = oi.side.lower()

        # Simple cash check for BUYs
        if side == "buy":
            max_allowed = snapshot.cash_available * self.config.max_cash_utilization
            if notional > max_allowed:
                logger.info(
                    "Risk: rejecting %s (notional %.2f > cash_allowed %.2f)",
                    oi, notional, max_allowed,
                )
                return False

        # SELLs: prevent opening shorts unless allowed
        if side == "sell" and not self.config.allow_short_selling:
            held_qty = self._holding_qty(oi.symbol, positions)
            if held_qty <= 0 or oi.quantity > held_qty:
                logger.info(
                    "Risk: rejecting %s (sell qty %.2f > holdings %.2f)",
                    oi, oi.quantity, held_qty,
                )
                return False

        return True
