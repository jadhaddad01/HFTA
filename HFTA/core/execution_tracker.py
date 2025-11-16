# HFTA/core/execution_tracker.py

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, List, Optional

from HFTA.strategies.base import OrderIntent

logger = logging.getLogger(__name__)


@dataclass
class Fill:
    symbol: str
    side: str
    quantity: float
    price: float
    timestamp: Optional[str]


@dataclass
class PositionState:
    quantity: float = 0.0      # >0 = long, <0 = short
    avg_price: float = 0.0     # average entry price of current position
    realized_pnl: float = 0.0  # closed PnL


class ExecutionTracker:
    """
    Tracks fills, per-symbol positions, and realized PnL.
    Used both in DRY-RUN (paper fills) and live mode (approx fills).
    """

    def __init__(self) -> None:
        self.positions: Dict[str, PositionState] = {}
        self.fills: List[Fill] = []
        self._loop_counter: int = 0

    # ------------------------------------------------------------------ #
    # Recording fills
    # ------------------------------------------------------------------ #

    def record_fill(
        self,
        oi: OrderIntent,
        price: float,
        timestamp: Optional[str],
    ) -> None:
        symbol = oi.symbol.upper()
        side = oi.side.lower()
        qty = float(oi.quantity)

        self.fills.append(Fill(symbol=symbol, side=side, quantity=qty, price=price, timestamp=timestamp))

        pos = self.positions.get(symbol)
        if pos is None:
            pos = PositionState()
            self.positions[symbol] = pos

        self._update_position(pos, side, qty, price)

    def _update_position(
        self,
        pos: PositionState,
        side: str,
        qty: float,
        price: float,
    ) -> None:
        """
        Update position and realized PnL for a single fill.
        Handles both long and short, though in practice your account is non-margin.
        """

        if side == "buy":
            if pos.quantity >= 0:
                # Increasing / opening long
                new_qty = pos.quantity + qty
                if new_qty > 0:
                    pos.avg_price = (pos.avg_price * pos.quantity + price * qty) / new_qty
                pos.quantity = new_qty
            else:
                # Closing (part of) a short
                closing = min(qty, -pos.quantity)
                pos.realized_pnl += (pos.avg_price - price) * closing
                pos.quantity += closing  # less negative

                remaining = qty - closing
                if remaining > 0:
                    # Short fully closed, now open new long with remaining
                    new_qty = remaining
                    pos.avg_price = price
                    pos.quantity = new_qty

        elif side == "sell":
            if pos.quantity <= 0:
                # Increasing / opening short
                new_qty = pos.quantity - qty
                abs_old = -pos.quantity
                abs_new = abs_old + qty
                if abs_new > 0:
                    pos.avg_price = (pos.avg_price * abs_old + price * qty) / abs_new
                pos.quantity = new_qty
            else:
                # Closing (part of) a long
                closing = min(qty, pos.quantity)
                pos.realized_pnl += (price - pos.avg_price) * closing
                pos.quantity -= closing

                remaining = qty - closing
                if pos.quantity == 0 and remaining == 0:
                    pos.avg_price = 0.0

                if remaining > 0:
                    # Long fully closed, now open new short
                    new_qty = -remaining
                    pos.avg_price = price
                    pos.quantity = new_qty

    # ------------------------------------------------------------------ #
    # Reporting
    # ------------------------------------------------------------------ #

    def summary(self) -> Dict[str, PositionState]:
        return self.positions

    def log_summary(self, every_n_loops: int = 12) -> None:
        """
        Log a compact PnL/position summary every `every_n_loops` engine loops.
        With poll_interval=5s and every_n_loops=12, this is ~1 minute.
        """
        self._loop_counter += 1
        if every_n_loops <= 0 or self._loop_counter % every_n_loops != 0:
            return

        if not self.positions:
            logger.info("PnL summary: no positions yet.")
            return

        parts = []
        total_realized = 0.0
        for sym, pos in self.positions.items():
            parts.append(
                f"{sym}: pos={pos.quantity:.2f}, avg={pos.avg_price:.2f}, realized={pos.realized_pnl:.2f}"
            )
            total_realized += pos.realized_pnl

        logger.info("PnL summary: %s | total_realized=%.2f", " | ".join(parts), total_realized)
