# HFTA/strategies/micro_trend_scalper.py

from __future__ import annotations

from typing import Any, Dict, List, Optional

from HFTA.broker.client import Quote
from HFTA.strategies.base import OrderIntent, Strategy


class MicroTrendScalper(Strategy):
    """Very small, short-term trend-following scalper with exits.

    Idea:
    - Maintain a short and long moving average of the mid price.
    - If short MA > long MA by `trend_threshold` => uptrend -> propose a BUY.
    - If short MA < long MA by `trend_threshold` => downtrend -> propose a SELL.
    - Only enter/exit on signal flips and manage an internal long position
      using take-profit and trailing-stop logic.

    Actual execution / size is still constrained by RiskManager
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

        # New: exit / risk management parameters
        self.trailing_stop_pct: float = float(config.get("trailing_stop_pct", 0.0))
        self.take_profit_pct: float = float(config.get("take_profit_pct", 0.0))

        # Internal price buffer for MA computation
        self._price_buffer: List[float] = []
        # Last raw trend signal ("up", "down", or None)
        self._last_signal: Optional[str] = None

        # Internal view of the position this strategy is running.
        # We track a single long exposure and assume fills are quick.
        self._position_side: Optional[str] = None  # "long" or None
        self._entry_price: Optional[float] = None
        self._peak_price: Optional[float] = None

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    def _reset_position_state(self) -> None:
        self._position_side = None
        self._entry_price = None
        self._peak_price = None

    # ------------------------------------------------------------------ #
    # Strategy interface
    # ------------------------------------------------------------------ #

    def on_quote(self, quote: Quote) -> List[OrderIntent]:
        # Only act on our symbol
        if quote.symbol.upper() != self.symbol:
            return []

        if quote.bid is None or quote.ask is None:
            return []

        mid = (quote.bid + quote.ask) / 2.0

        # Update price buffer
        self._price_buffer.append(mid)
        if len(self._price_buffer) > self.long_window:
            self._price_buffer = self._price_buffer[-self.long_window :]

        # MA-based trend signal (may be None if not enough history)
        if len(self._price_buffer) < self.long_window:
            signal: Optional[str] = None
        else:
            short = sum(self._price_buffer[-self.short_window :]) / self.short_window
            long = sum(self._price_buffer) / len(self._price_buffer)
            if long == 0:
                signal = None
            else:
                rel = (short - long) / long
                if rel > self.trend_threshold:
                    signal = "up"
                elif rel < -self.trend_threshold:
                    signal = "down"
                else:
                    signal = None

        intents: List[OrderIntent] = []

        # ------------------------------------------------------------------
        # 1) Manage existing position: take profit / trailing stop
        # ------------------------------------------------------------------
        if self._position_side == "long" and self._entry_price is not None:
            entry = self._entry_price
            if entry > 0:
                unrealized_pct = (mid - entry) / entry
            else:
                unrealized_pct = 0.0

            # Track the highest price since entry
            if self._peak_price is None or mid > self._peak_price:
                self._peak_price = mid

            closed_this_bar = False

            # Take-profit: lock gains when unrealized PnL exceeds threshold
            if self.take_profit_pct > 0.0 and unrealized_pct >= self.take_profit_pct:
                qty = min(self.order_quantity, self.max_position)
                if qty > 0:
                    intents.append(
                        OrderIntent(
                            symbol=self.symbol,
                            side="sell",
                            quantity=qty,
                            order_type="limit",
                            limit_price=mid,
                            meta={
                                "strategy": self.name,
                                "reason": "take_profit",
                            },
                        )
                    )
                    self._reset_position_state()
                    closed_this_bar = True

            # Trailing stop: after price has moved up, tolerate only a limited
            # drawdown from the peak.
            if (
                not closed_this_bar
                and self.trailing_stop_pct > 0.0
                and self._peak_price is not None
                and self._peak_price > 0.0
            ):
                drawdown_pct = (self._peak_price - mid) / self._peak_price
                if drawdown_pct >= self.trailing_stop_pct:
                    qty = min(self.order_quantity, self.max_position)
                    if qty > 0:
                        intents.append(
                            OrderIntent(
                                symbol=self.symbol,
                                side="sell",
                                quantity=qty,
                                order_type="limit",
                                limit_price=mid,
                                meta={
                                    "strategy": self.name,
                                    "reason": "trailing_stop",
                                },
                            )
                        )
                        self._reset_position_state()

        # ------------------------------------------------------------------
        # 2) Trend-based entries / exits
        # ------------------------------------------------------------------
        # Only act on fresh signal flips to avoid hammering the API.

        # Enter on uptrend if we are flat and signal flipped to "up"
        if signal == "up" and self._position_side is None:
            if self._last_signal != "up":
                qty = min(self.order_quantity, self.max_position)
                if qty > 0:
                    intents.append(
                        OrderIntent(
                            symbol=self.symbol,
                            side="buy",
                            quantity=qty,
                            order_type="limit",
                            limit_price=mid,
                            meta={"strategy": self.name, "signal": "trend_up"},
                        )
                    )
                    self._position_side = "long"
                    self._entry_price = mid
                    self._peak_price = mid

        # Exit on clear trend reversal from up to down
        elif signal == "down" and self._position_side == "long":
            if self._last_signal != "down":
                qty = min(self.order_quantity, self.max_position)
                if qty > 0:
                    intents.append(
                        OrderIntent(
                            symbol=self.symbol,
                            side="sell",
                            quantity=qty,
                            order_type="limit",
                            limit_price=mid,
                            meta={"strategy": self.name, "signal": "trend_down"},
                        )
                    )
                    self._reset_position_state()

        # Update last signal for next tick
        self._last_signal = signal

        return intents
