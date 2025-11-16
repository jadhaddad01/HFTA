# HFTA/core/engine.py

from __future__ import annotations

import logging
import time
from typing import List, Optional

from HFTA.broker.client import WealthsimpleClient, PortfolioSnapshot
from HFTA.core.order_manager import OrderManager
from HFTA.strategies.base import Strategy

logger = logging.getLogger(__name__)


class Engine:
    """
    Very simple polling engine:
    - Polls quotes for a list of symbols
    - Feeds them into all strategies
    - Passes the resulting orders to OrderManager

    If `paper_cash` is set and OrderManager.live is False, the engine
    simulates a paper account with that cash amount, regardless of the
    real Wealthsimple cash balance.
    """

    def __init__(
        self,
        client: WealthsimpleClient,
        strategies: List[Strategy],
        symbols: List[str],
        order_manager: OrderManager,
        poll_interval: float = 2.0,
        paper_cash: Optional[float] = None,
    ) -> None:
        self.client = client
        self.strategies = strategies
        self.symbols = [s.upper() for s in symbols]
        self.order_manager = order_manager
        self.poll_interval = poll_interval
        self.paper_cash = paper_cash

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #

    def _make_sim_snapshot(self, snapshot: PortfolioSnapshot) -> PortfolioSnapshot:
        """
        For DRY-RUN mode, optionally override cash/net worth with `paper_cash`.
        For live mode or when paper_cash is None, just return the real snapshot.
        """
        if self.order_manager.live or self.paper_cash is None:
            return snapshot

        return PortfolioSnapshot(
            account_id=snapshot.account_id,
            currency=snapshot.currency,
            net_worth=self.paper_cash,
            cash_available=self.paper_cash,
        )

    # ------------------------------------------------------------------ #
    # Main loop
    # ------------------------------------------------------------------ #

    def run_forever(self) -> None:
        """
        Main loop. Gracefully stops on KeyboardInterrupt (Ctrl+C).
        """
        logger.info(
            "Engine loop starting (live=%s, paper_cash=%s)",
            self.order_manager.live,
            self.paper_cash,
        )
        try:
            while True:
                # Real snapshot + current holdings from Wealthsimple
                real_snapshot = self.client.get_portfolio_snapshot()
                positions = self.client.get_equity_positions()

                # Seed execution tracker from holdings once
                tracker = getattr(self.order_manager, "execution_tracker", None)
                if tracker is not None:
                    tracker.seed_from_positions(positions)

                # Snapshot actually used for risk checks (may be paper-cash)
                snapshot = self._make_sim_snapshot(real_snapshot)

                for sym in self.symbols:
                    quote = self.client.get_quote(sym)
                    logger.debug("Quote: %s", quote)

                    for strat in self.strategies:
                        intents = strat.on_quote(quote)
                        for oi in intents:
                            self.order_manager.process_order(oi, quote, snapshot, positions)

                # Engine-level PnL summary
                if tracker is not None:
                    tracker.log_summary()

                time.sleep(self.poll_interval)
        except KeyboardInterrupt:
            logger.info("Engine stopped by user (KeyboardInterrupt).")
