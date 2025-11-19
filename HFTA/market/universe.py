# HFTA/market/universe.py

from __future__ import annotations

import dataclasses
import datetime as dt
import logging
from dataclasses import dataclass
from typing import Dict, List, Optional

import requests

logger = logging.getLogger(__name__)


@dataclass
class MarketUniverseConfig:
    """Configuration for dynamic symbol universe via Polygon."""

    max_symbols: int = 50
    min_price: float = 5.0
    max_price: float = 500.0
    min_dollar_volume: float = 20_000_000.0
    lookback_days: int = 3  # number of past days (including yesterday) to aggregate


class MarketUniverse:
    """Builds a dynamic universe of liquid US stocks from Polygon.io.

    Logic:
      - Use /v2/aggs/grouped/locale/us/market/stocks/{date} for each day.
      - Start from *yesterday* and go back `lookback_days - 1` days.
      - Aggregate dollar volume (close * volume) per symbol across the window.
      - Filter by price bounds and min_dollar_volume.
      - Keep top `max_symbols` by aggregated dollar volume.

    Attributes:
      - symbols: final list of tickers (uppercased) to trade.
      - metrics_by_symbol: dict with basic liquidity metrics.
    """

    BASE_URL = "https://api.polygon.io/v2/aggs/grouped/locale/us/market/stocks"

    def __init__(
        self,
        config: MarketUniverseConfig,
        api_key: str,
    ) -> None:
        self.config = config
        self.api_key = api_key
        self.symbols: List[str] = []
        self.metrics_by_symbol: Dict[str, Dict[str, float]] = {}

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def refresh(self) -> None:
        """Fetch fresh data from Polygon and rebuild the universe."""
        logger.info("Refreshing MarketUniverse from Polygon with config=%s", self.config)

        # Use yesterday as the most recent day to avoid "today" / 403 issues.
        today = dt.date.today()
        end_date = today - dt.timedelta(days=1)
        start_date = end_date - dt.timedelta(days=max(self.config.lookback_days - 1, 0))

        agg: Dict[str, Dict[str, float]] = {}

        for i in range(self.config.lookback_days):
            day = end_date - dt.timedelta(days=i)
            if day < start_date:
                break
            self._fetch_and_accumulate_for_day(day, agg)

        if not agg:
            logger.warning("MarketUniverse.refresh: no data accumulated from Polygon.")
            self.symbols = []
            self.metrics_by_symbol = {}
            return

        # Build metrics and sort by aggregated dollar volume.
        metrics: Dict[str, Dict[str, float]] = {}
        for sym, vals in agg.items():
            dv_sum = vals.get("dollar_volume_sum", 0.0)
            vol_sum = vals.get("volume_sum", 0.0)
            last_close = vals.get("last_close", 0.0)

            if last_close <= 0.0:
                continue

            metrics[sym] = {
                "avg_dollar_volume": dv_sum / max(self.config.lookback_days, 1),
                "total_dollar_volume": dv_sum,
                "total_volume": vol_sum,
                "last_close": last_close,
            }

        # Apply filters
        filtered: List[tuple[str, Dict[str, float]]] = []
        for sym, m in metrics.items():
            price = m["last_close"]
            dv = m["avg_dollar_volume"]
            if price < self.config.min_price or price > self.config.max_price:
                continue
            if dv < self.config.min_dollar_volume:
                continue
            filtered.append((sym, m))

        # Sort by total dollar volume (descending) and keep top N
        filtered.sort(key=lambda kv: kv[1]["total_dollar_volume"], reverse=True)
        if self.config.max_symbols > 0:
            filtered = filtered[: self.config.max_symbols]

        self.symbols = [sym for sym, _ in filtered]
        self.metrics_by_symbol = {sym: m for sym, m in filtered}

        logger.info(
            "MarketUniverse.refresh: built universe of %d symbols (from %d candidates).",
            len(self.symbols),
            len(metrics),
        )
        logger.debug("MarketUniverse symbols: %s", self.symbols)

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    def _fetch_and_accumulate_for_day(
        self,
        day: dt.date,
        agg: Dict[str, Dict[str, float]],
    ) -> None:
        """Fetch grouped aggregates for a single day and accumulate stats."""
        date_str = day.isoformat()
        url = f"{self.BASE_URL}/{date_str}"
        params = {"adjusted": "true", "apiKey": self.api_key}

        logger.info("MarketUniverse: requesting Polygon grouped data for %s", date_str)
        try:
            resp = requests.get(url, params=params, timeout=5.0)
            resp.raise_for_status()
        except Exception as exc:
            logger.exception(
                "MarketUniverse: request failed for %s: %s", date_str, exc
            )
            return

        data = resp.json()
        results = data.get("results") or []
        if not isinstance(results, list):
            logger.warning(
                "MarketUniverse: unexpected results type for %s: %r",
                date_str,
                type(results),
            )
            return

        for row in results:
            try:
                sym = str(row.get("T") or "").upper()
                if not sym:
                    continue
                close = float(row.get("c") or 0.0)
                vol = float(row.get("v") or 0.0)
            except Exception:
                continue

            if close <= 0.0 or vol <= 0.0:
                continue

            dv = close * vol  # dollar volume

            state = agg.get(sym)
            if state is None:
                state = {
                    "dollar_volume_sum": 0.0,
                    "volume_sum": 0.0,
                    "last_close": close,
                }
                agg[sym] = state

            state["dollar_volume_sum"] += dv
            state["volume_sum"] += vol
            # last_close will just be overwritten with the most recent day's close
            state["last_close"] = close
