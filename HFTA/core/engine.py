# HFTA/core/engine.py

from __future__ import annotations

import logging
import time
from typing import List, Optional, Mapping, Any

from HFTA.broker.client import WealthsimpleClient, PortfolioSnapshot
from HFTA.core.order_manager import OrderManager
from HFTA.strategies.base import Strategy

logger = logging.getLogger(__name__)


class Engine:
    """
    Engine with optional AI controller.

    If `paper_cash` is set and OrderManager.live is False, the engine
    simulates a paper account with that cash amount.

    In DRY-RUN mode, risk checks are done against the paper positions
    maintained by ExecutionTracker, not against live WS holdings.
    """

    def __init__(
        self,
        client: WealthsimpleClient,
        strategies: List[Strategy],
        symbols: List[str],
        order_manager: OrderManager,
        poll_interval: float = 2.0,
        paper_cash: Optional[float] = None,
        ai_controller: Optional[Any] = None,
    ) -> None:
        self.client = client
        self.strategies = strategies
        self.symbols = [s.upper() for s in symbols]
        self.order_manager = order_manager
        self.poll_interval = poll_interval
        self.paper_cash = paper_cash
        self.ai_controller = ai_controller

    # ------------------------------------------------------------------ #

    def _make_sim_snapshot(self, snapshot: PortfolioSnapshot) -> PortfolioSnapshot:
        if self.order_manager.live or self.paper_cash is None:
            return snapshot

        return PortfolioSnapshot(
            account_id=snapshot.account_id,
            currency=snapshot.currency,
            net_worth=self.paper_cash,
            cash_available=self.paper_cash,
        )

    def _positions_for_risk(self, ws_positions: Mapping[str, Any]) -> Mapping[str, Any]:
        tracker = getattr(self.order_manager, "execution_tracker", None)
        if self.order_manager.live or tracker is None:
            return ws_positions
        return tracker.summary()

    # ------------------------------------------------------------------ #

    def run_forever(self) -> None:
        logger.info(
            "Engine loop starting (live=%s, paper_cash=%s)",
            self.order_manager.live,
            self.paper_cash,
        )
        loop_idx = 0
        try:
            while True:
                loop_idx += 1

                real_snapshot = self.client.get_portfolio_snapshot()
                ws_positions = self.client.get_equity_positions()

                tracker = getattr(self.order_manager, "execution_tracker", None)
                if tracker is not None:
                    tracker.seed_from_positions(ws_positions)

                snapshot = self._make_sim_snapshot(real_snapshot)
                positions_for_risk = self._positions_for_risk(ws_positions)

                for sym in self.symbols:
                    quote = self.client.get_quote(sym)
                    logger.debug("Quote: %s", quote)

                    for strat in self.strategies:
                        intents = strat.on_quote(quote)
                        for oi in intents:
                            self.order_manager.process_order(
                                oi, quote, snapshot, positions_for_risk
                            )

                # AI controller gets full view of current state and can tweak
                if self.ai_controller is not None and tracker is not None:
                    self.ai_controller.on_loop(
                        strategies=self.strategies,
                        risk_config=self.order_manager.risk_manager.config,
                        tracker=tracker,
                    )

                if tracker is not None:
                    tracker.log_summary()

                time.sleep(self.poll_interval)
        except KeyboardInterrupt:
            logger.info("Engine stopped by user (KeyboardInterrupt).")
