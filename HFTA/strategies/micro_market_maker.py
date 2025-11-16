# HFTA/strategies/micro_market_maker.py

from __future__ import annotations
from typing import Any, Dict, List

from HFTA.strategies.base import Strategy, OrderIntent
from HFTA.broker.client import Quote


class MicroMarketMaker(Strategy):
    """
    Simple single-symbol market maker:
    - Posts bid and ask around current mid
    - Keeps inventory within +/- max_inventory
    """

    def __init__(self, name: str, config: Dict[str, Any]) -> None:
        super().__init__(name, config)
        self.symbol = config["symbol"].upper()
        self.max_inventory = config.get("max_inventory", 5)
        # absolute price distance around mid (e.g. 0.05 = 5 cents)
        self.spread = config.get("spread", 0.05)
        self.order_quantity = config.get("order_quantity", 1)
        self.position = 0.0  # strategy's view of current position

    def update_position(self, new_position: float) -> None:
        self.position = new_position

    def on_quote(self, quote: Quote) -> List[OrderIntent]:
        # Only handle our symbol
        if quote.symbol.upper() != self.symbol:
            return []

        if quote.bid is None or quote.ask is None:
            return []

        # quote.bid and quote.ask are floats thanks to the broker wrapper
        mid = (quote.bid + quote.ask) / 2.0

        bid_price = round(mid - self.spread, 2)
        ask_price = round(mid + self.spread, 2)

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
