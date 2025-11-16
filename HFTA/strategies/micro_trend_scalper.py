# HFTA/strategies/micro_trend_scalper.py

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List

from HFTA.broker.client import Quote
from HFTA.strategies.base import OrderIntent, Strategy


@dataclass
class MicroTrendScalperConfig:
    symbol: str
    order_quantity: float = 1.0
    short_window: int = 5
    long_window: int = 20
    trend_threshold: float = 0.0005  # 5 bps of divergence between short & long MA
    max_position: float = 5.0        # cap intended directional size


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
        super().__init__(name)

        cfg = MicroTrendScalperConfig(
            symbol=config["symbol"],
            order_quantity=float(config.get("order_quantity", 1.0)),
            short_window=int(config.get("short_window", 5)),
            long_window=int(config.get("long_window", 20)),
            trend_threshold=float(config.get("trend_threshold", 0.0005)),
            max_position=float(config.get("max_position", 5.0)),
        )

        if cfg.short_window <= 0 or cfg.long_window <= 0:
            raise ValueError("short_window and long_window must be > 0")
        if cfg.short_window >= cfg.long_window:
            raise ValueError("short_window must be < long_window")

        self.cfg = cfg
        self.symbol = cfg.symbol.upper()
        self._price_buffer: List[float] = []
        self._last_signal: str | None = None  # "up", "down", or None

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #

    def _mid_price(self, q: Quote) -> float | None:
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
        if len(self._price_buffer) > self.cfg.long_window:
            self._price_buffer = self._price_buffer[-self.cfg.long_window :]

        # Wait until we have enough history
        if len(self._price_buffer) < self.cfg.long_window:
            return []

        short = sum(self._price_buffer[-self.cfg.short_window :]) / self.cfg.short_window
        long = sum(self._price_buffer) / len(self._price_buffer)
        if long == 0:
            return []

        rel = (short - long) / long

        signal: str | None
        if rel > self.cfg.trend_threshold:
            signal = "up"
        elif rel < -self.cfg.trend_threshold:
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
                    quantity=min(self.cfg.order_quantity, self.cfg.max_position),
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
                    quantity=self.cfg.order_quantity,
                    order_type="limit",
                    limit_price=mid,
                    meta={"strategy": self.name, "signal": "trend_down"},
                )
            )

        return intents
