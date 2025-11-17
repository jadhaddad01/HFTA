# HFTA/strategies/micro_market_maker.py

from __future__ import annotations

import math
from typing import Any, Dict, List

from HFTA.strategies.base import Strategy, OrderIntent
from HFTA.broker.client import Quote


class MicroMarketMaker(Strategy):
    """Simple single-symbol market maker with dynamic spread.

    Behaviour:
    - Posts bid and ask around current mid price.
    - Adjusts spread based on recent realized volatility.
    - Keeps inventory within +/- max_inventory (as seen by update_position()).
    """

    def __init__(self, name: str, config: Dict[str, Any]) -> None:
        super().__init__(name, config)

        self.symbol = config["symbol"].upper()
        self.max_inventory: float = float(config.get("max_inventory", 5))

        # Base (target) spread in absolute price units (e.g. 0.05 = 5 cents)
        self.base_spread: float = float(config.get("spread", 0.05))
        self.order_quantity: float = float(config.get("order_quantity", 1.0))

        # Dynamic spread controls
        self.min_spread: float = float(
            config.get("min_spread", self.base_spread / 2.0)
        )
        self.max_spread: float = float(
            config.get("max_spread", self.base_spread * 2.0)
        )
        self.vol_window: int = int(config.get("vol_window", 50))
        self.vol_to_spread: float = float(config.get("vol_to_spread", 1.0))

        # Strategy's view of current position (updated externally)
        self.position: float = 0.0

        # History of recent mid prices for volatility estimation
        self._mid_history: List[float] = []

        # Expose current effective spread as a public attribute so the AI
        # controller and logging can inspect it.
        self.spread: float = self.base_spread

    def update_position(self, new_position: float) -> None:
        """Called by the engine / execution layer to sync inventory."""
        self.position = float(new_position)

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    def _update_spread_from_vol(self, mid: float) -> float:
        """Update internal volatility estimate and return effective spread.

        We compute a simple relative volatility measure from recent mids and
        scale the base spread accordingly, clamped between min_spread and
        max_spread.
        """
        if mid <= 0:
            self.spread = self.base_spread
            return self.spread

        self._mid_history.append(mid)
        if self.vol_window > 1 and len(self._mid_history) > self.vol_window:
            self._mid_history = self._mid_history[-self.vol_window :]

        if len(self._mid_history) < 2 or self.vol_window <= 1:
            eff_spread = self.base_spread
        else:
            vals = self._mid_history
            n = len(vals)
            avg = sum(vals) / n
            if avg <= 0:
                eff_spread = self.base_spread
            else:
                var = sum((x - avg) ** 2 for x in vals) / n
                std = math.sqrt(var)
                # Dimensionless relative volatility
                rel_vol = std / avg if avg > 0 else 0.0

                # Scale base spread by (1 + k * rel_vol)
                scale = 1.0 + self.vol_to_spread * rel_vol
                eff_spread = self.base_spread * scale

        # Clamp and expose
        eff_spread = max(self.min_spread, min(self.max_spread, eff_spread))
        self.spread = eff_spread
        return eff_spread

    # ------------------------------------------------------------------ #
    # Strategy interface
    # ------------------------------------------------------------------ #

    def on_quote(self, quote: Quote) -> List[OrderIntent]:
        # Only handle our symbol
        if quote.symbol.upper() != self.symbol:
            return []

        if quote.bid is None or quote.ask is None:
            return []

        # quote.bid and quote.ask are floats thanks to the broker wrapper
        mid = (quote.bid + quote.ask) / 2.0

        # Dynamic spread based on recent volatility
        eff_spread = self._update_spread_from_vol(mid)

        bid_price = max(0.01, round(mid - eff_spread, 2))
        ask_price = max(0.01, round(mid + eff_spread, 2))

        intents: List[OrderIntent] = []

        # Buy side if inventory below max
        if self.position < self.max_inventory:
            intents.append(
                OrderIntent(
                    symbol=self.symbol,
                    side="buy",
                    quantity=self.order_quantity,
                    order_type="limit",
                    limit_price=bid_price,
                    meta={"strategy": self.name},
                )
            )

        # Sell side if inventory above -max
        if self.position > -self.max_inventory:
            intents.append(
                OrderIntent(
                    symbol=self.symbol,
                    side="sell",
                    quantity=self.order_quantity,
                    order_type="limit",
                    limit_price=ask_price,
                    meta={"strategy": self.name},
                )
            )

        return intents
