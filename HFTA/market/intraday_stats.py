# HFTA/market/intraday_stats.py

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, Any


@dataclass
class SymbolIntradayStats:
    """
    Simple intraday stats for a single symbol, computed only from the quotes
    the engine already sees.

    We track:
      - first_price: first quote price seen this session
      - last_price: latest price
      - high / low: session high/low
      - count: number of quotes seen
      - sum_log_returns / sum_sq_log_returns: for a rough intraday volatility
    """
    symbol: str
    first_price: float = 0.0
    last_price: float = 0.0
    high: float = 0.0
    low: float = 0.0
    count: int = 0
    sum_log_returns: float = 0.0
    sum_sq_log_returns: float = 0.0

    def update(self, price: float) -> None:
        if price is None or price <= 0.0:
            return

        if self.count == 0:
            # First tick of the session
            self.first_price = price
            self.high = price
            self.low = price
            self.last_price = price
            self.count = 1
            return

        # Update high/low
        if price > self.high:
            self.high = price
        if price < self.low:
            self.low = price

        # Log return from last price
        if self.last_price > 0.0:
            r = math.log(price / self.last_price)
        else:
            r = 0.0

        self.sum_log_returns += r
        self.sum_sq_log_returns += r * r

        self.last_price = price
        self.count += 1

    def as_dict(self) -> Dict[str, float]:
        """
        Export a compact metrics dict for scoring / AI.
        """
        if self.count <= 1 or self.first_price <= 0.0:
            intraday_return = 0.0
        else:
            intraday_return = (self.last_price - self.first_price) / self.first_price

        if self.count <= 2:
            vol = 0.0
        else:
            # n-1 log returns
            n_ret = self.count - 1
            mean_r = self.sum_log_returns / n_ret
            var_r = max(self.sum_sq_log_returns / n_ret - mean_r * mean_r, 0.0)
            # This is a rough, unitless intraday volatility proxy
            vol = math.sqrt(var_r) * math.sqrt(n_ret)

        if self.low > 0.0:
            range_pct = (self.high - self.low) / self.low
        else:
            range_pct = 0.0

        return {
            "last_price": self.last_price,
            "intraday_return": intraday_return,
            "volatility": vol,
            "range_pct": range_pct,
            "high": self.high,
            "low": self.low,
            "count": float(self.count),
        }


class IntradayStatsTracker:
    """
    Tracks intraday stats for all symbols seen by the engine.

    Usage:
      - Engine calls .on_quote(symbol, price) on each quote
      - SymbolSelector calls .summary() to get a snapshot of metrics
    """

    def __init__(self) -> None:
        self._by_symbol: Dict[str, SymbolIntradayStats] = {}

    def on_quote(self, symbol: str, price: float) -> None:
        sym_u = symbol.upper()
        stats = self._by_symbol.get(sym_u)
        if stats is None:
            stats = SymbolIntradayStats(symbol=sym_u)
            self._by_symbol[sym_u] = stats
        stats.update(price)

    def summary(self) -> Dict[str, Dict[str, float]]:
        return {s: st.as_dict() for s, st in self._by_symbol.items()}
