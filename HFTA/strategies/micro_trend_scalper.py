# HFTA/strategies/micro_trend_scalper.py

from __future__ import annotations

from typing import Any, Dict, List, Optional

from HFTA.broker.client import Quote
from HFTA.strategies.base import OrderIntent, Strategy


class MicroTrendScalper(Strategy):
    """
    Very small, short-term trend-following scalper.

    Idea:
    - Maintain a short and long moving average of the mid price.
    - If short MA > long MA by `trend_threshold` => uptrend -> propose a BUY.
    - If short MA < long MA by `trend_threshold` => downtrend -> propose a SELL.
    - Only emit a new order when the signal flips (to avoid spamming).

    Actual execution / size is still constrained by the RiskManager
    (notional caps, no shorts, etc.).
    """

    def __init__(self, name: str, config: Dict[str, Any]) -> None:
        # Base Strategy needs both name and config
        super().__init__(name, config)

        self.symbol = config["symbol"].upper()
        self.order_quantity: float = float(config.get("order_quantity", 1.0))
        self.short_window: int = int(config.get("short_window", 5))
        self.long_window: int = int(config.get("long_window", 20))
        self.trend_threshold: float = float(config.get("trend_threshold", 0.0005))
        self.max_position: float = float(config.get("max_position", 5.0))

        if self.short_window <= 0 or self.long_window <= 0:
            raise ValueError("short_window and long_window must be > 0")
        if self.short_window >= self.long_window:
            raise ValueError("short_window must be < long_window")

        self._price_buffer: List[float] = []
        self._last_signal: Optional[str] = None  # "up", "down", or None

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #

    def _mid_price(self, q: Quote) -> Optional[float]:
        vals = [v for v in (q.bid, q.ask) if v is not None]
        if not vals:
            return None
        return sum(vals) / len(vals)

    # ------------------------------------------------------------------ #
    # Strategy interface
    # ------------------------------------------------------------------ #

    def on_quote(self, quote: Quote) -> List[OrderIntent]:
        # Only act on our configured symbol
        if quote.symbol.upper() != self.symbol:
            return []

        mid = self._mid_price(quote)
        if mid is None:
            return []

        self._price_buffer.append(mid)
        if len(self._price_buffer) > self.long_window:
            self._price_buffer = self._price_buffer[-self.long_window :]

        # Wait until we have enough history
        if len(self._price_buffer) < self.long_window:
            return []

        short = sum(self._price_buffer[-self.short_window :]) / self.short_window
        long = sum(self._price_buffer) / len(self._price_buffer)
        if long == 0:
            return []

        rel = (short - long) / long

        signal: Optional[str]
        if rel > self.trend_threshold:
            signal = "up"
        elif rel < -self.trend_threshold:
            signal = "down"
        else:
            signal = None

        intents: List[OrderIntent] = []

        # Only emit when signal changes to avoid hammering the API
        if signal is None or signal == self._last_signal:
            self._last_signal = signal
            return intents

        self._last_signal = signal

        if signal == "up":
            # Bias to increase long exposure (RiskManager will clip by cash etc.)
            intents.append(
                OrderIntent(
                    symbol=self.symbol,
                    side="buy",
                    quantity=min(self.order_quantity, self.max_position),
                    order_type="limit",
                    limit_price=mid,
                    meta={"strategy": self.name, "signal": "trend_up"},
                )
            )
        elif signal == "down":
            # Bias to reduce / exit long exposure (no new shorts; RiskManager enforces)
            intents.append(
                OrderIntent(
                    symbol=self.symbol,
                    side="sell",
                    quantity=self.order_quantity,
                    order_type="limit",
                    limit_price=mid,
                    meta={"strategy": self.name, "signal": "trend_down"},
                )
            )

        return intents
