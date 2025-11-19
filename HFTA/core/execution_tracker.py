# HFTA/core/execution_tracker.py

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional

from HFTA.strategies.base import OrderIntent

logger = logging.getLogger(__name__)


@dataclass
class Fill:
    symbol: str
    side: str
    quantity: float
    price: float
    timestamp: Optional[str]
    strategy_name: Optional[str] = None


@dataclass
class PositionState:
    quantity: float = 0.0      # >0 = long, <0 = short
    avg_price: float = 0.0     # average entry price of current position
    realized_pnl: float = 0.0  # closed PnL for this symbol


@dataclass
class StrategySymbolStats:
    """
    Aggregated stats per (strategy, symbol), derived incrementally from fills.
    """
    strategy_name: str
    symbol: str
    trade_count: int = 0
    realized_pnl: float = 0.0

    @property
    def avg_pnl_per_trade(self) -> float:
        if self.trade_count <= 0:
            return 0.0
        return self.realized_pnl / self.trade_count


class ExecutionTracker:
    """
    Tracks fills, per-symbol positions, realized PnL, and per-strategy/per-symbol
    stats.

    Used both in DRY-RUN (paper fills) and live mode (approx fills).
    """

    def __init__(self) -> None:
        self.positions: Dict[str, PositionState] = {}
        self.fills: List[Fill] = []
        # Nested mapping: strategy_name -> symbol -> StrategySymbolStats
        self.strategy_symbol_stats: Dict[str, Dict[str, StrategySymbolStats]] = {}
        self._loop_counter: int = 0
        self._seeded: bool = False

    # ------------------------------------------------------------------ #
    # Seeding from live holdings
    # ------------------------------------------------------------------ #

    def seed_from_positions(self, positions: Mapping[str, Any]) -> None:
        """
        Initialize positions from a holdings mapping:
            { 'AAPL': Holding(...), ... }

        Only runs once; later calls are ignored.
        """
        if self._seeded:
            return

        for sym, h in positions.items():
            qty = getattr(h, "quantity", 0.0)
            avg = getattr(h, "avg_price", 0.0) or 0.0
            try:
                qty_f = float(qty)
            except (TypeError, ValueError):
                qty_f = 0.0
            try:
                avg_f = float(avg)
            except (TypeError, ValueError):
                avg_f = 0.0

            if qty_f == 0.0:
                continue

            symbol = sym.upper()
            self.positions[symbol] = PositionState(
                quantity=qty_f,
                avg_price=avg_f,
                realized_pnl=0.0,
            )

        self._seeded = True

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
        strategy_name = getattr(oi, "strategy_name", None)

        fill = Fill(
            symbol=symbol,
            side=side,
            quantity=qty,
            price=price,
            timestamp=timestamp,
            strategy_name=strategy_name,
        )
        self.fills.append(fill)

        pos = self.positions.get(symbol)
        if pos is None:
            pos = PositionState()
            self.positions[symbol] = pos

        # Track realized PnL delta so we can attribute to a strategy.
        prev_realized = pos.realized_pnl
        self._update_position(pos, side, qty, price)
        realized_delta = pos.realized_pnl - prev_realized

        if strategy_name:
            strat_stats = self.strategy_symbol_stats.setdefault(strategy_name, {})
            stats = strat_stats.get(symbol)
            if stats is None:
                stats = StrategySymbolStats(strategy_name=strategy_name, symbol=symbol)
                strat_stats[symbol] = stats
            stats.trade_count += 1
            stats.realized_pnl += realized_delta

    def _update_position(
        self,
        pos: PositionState,
        side: str,
        qty: float,
        price: float,
    ) -> None:
        """
        Update position and realized PnL for a single fill.

        Handles both long and short for completeness, though the account is
        expected to be non-margin by default.
        """
        if side == "buy":
            # Buying into or adding to a long; or reducing / flipping a short.
            if pos.quantity >= 0:
                new_qty = pos.quantity + qty
                if new_qty > 0:
                    pos.avg_price = (pos.avg_price * pos.quantity + price * qty) / new_qty
                pos.quantity = new_qty
            else:
                # Closing a short position
                closing = min(qty, -pos.quantity)
                pos.realized_pnl += (pos.avg_price - price) * closing
                pos.quantity += closing

                remaining = qty - closing
                if remaining > 0:
                    # Flip to long with remaining qty
                    pos.quantity = remaining
                    pos.avg_price = price

        elif side == "sell":
            # Selling into or adding to a short; or reducing / flipping a long.
            if pos.quantity <= 0:
                new_qty = pos.quantity - qty
                abs_old = -pos.quantity
                abs_new = abs_old + qty
                if abs_new > 0:
                    pos.avg_price = (pos.avg_price * abs_old + price * qty) / abs_new
                pos.quantity = new_qty
            else:
                # Closing a long position
                closing = min(qty, pos.quantity)
                pos.realized_pnl += (price - pos.avg_price) * closing
                pos.quantity -= closing

                remaining = qty - closing
                if pos.quantity == 0 and remaining == 0:
                    pos.avg_price = 0.0

        else:
            logger.warning("Unknown side in _update_position: %r", side)

    # ------------------------------------------------------------------ #
    # Aggregate views
    # ------------------------------------------------------------------ #

    def summary(self) -> Dict[str, PositionState]:
        """
        Minimal view used by the risk manager: mapping symbol -> PositionState.
        """
        return self.positions

    def per_strategy_symbol_summary(self) -> Dict[str, Dict[str, Dict[str, float]]]:
        """
        Returns a nested mapping suitable for logging / AI:

            {
              "strategy_name": {
                 "AAPL": {"trade_count": 10, "realized_pnl": 12.34, "avg_pnl_per_trade": 1.234},
                 ...
              },
              ...
            }
        """
        out: Dict[str, Dict[str, Dict[str, float]]] = {}
        for strat_name, sym_map in self.strategy_symbol_stats.items():
            inner: Dict[str, Dict[str, float]] = {}
            for symbol, stats in sym_map.items():
                inner[symbol] = {
                    "trade_count": stats.trade_count,
                    "realized_pnl": stats.realized_pnl,
                    "avg_pnl_per_trade": stats.avg_pnl_per_trade,
                }
            out[strat_name] = inner
        return out

    # ------------------------------------------------------------------ #
    # Periodic logging helpers
    # ------------------------------------------------------------------ #

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
