# HFTA/symbol_selection/picker.py

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Set, Tuple

from HFTA.core.execution_tracker import ExecutionTracker
from HFTA.market.intraday_stats import IntradayStatsTracker
from HFTA.strategies.base import Strategy

# Optional: if you have MarketUniverse wired from Polygon; if not, you can
# safely ignore it and pass None when building SymbolSelector.
try:
    from HFTA.market.universe import MarketUniverse  # type: ignore
except Exception:  # pragma: no cover - optional
    MarketUniverse = None  # type: ignore

try:
    from openai import OpenAI  # type: ignore
except Exception:  # optional dependency
    OpenAI = None  # type: ignore

logger = logging.getLogger(__name__)


@dataclass
class SymbolScore:
    symbol: str
    trade_count: int
    realized_pnl: float
    avg_pnl_per_trade: float
    liquidity_score: float
    day_change_pct: float
    intraday_return: float
    intraday_volatility: float
    intraday_range_pct: float


class SymbolSelector:
    """
    Symbol picker that uses:

      - trading experience (ExecutionTracker per-strategy/per-symbol PnL)
      - market-level metrics (if a MarketUniverse is provided)
      - intraday stats derived from the quotes the engine sees

    Modes:
      - heuristic: PnL + liquidity + intraday stats only.
      - gpt:      GPT-only (falls back to heuristic on failure).
      - hybrid:   GPT first, heuristic fills any gaps.
    """

    def __init__(
        self,
        market_universe: Optional[Any] = None,  # MarketUniverse or None
        interval_loops: int = 60,
        min_trades: int = 3,
        enabled: bool = True,
        mode: str = "hybrid",  # 'heuristic', 'gpt', or 'hybrid'
        model: str = "gpt-5-mini",
    ) -> None:
        self.market_universe = market_universe
        self.interval_loops = max(1, int(interval_loops))
        self.min_trades = max(1, int(min_trades))
        self.enabled = enabled
        self.mode = mode.lower().strip()
        self.model = model

        self._loop_counter = 0

        self.client: Optional[Any] = None
        self._gpt_enabled: bool = False
        self._init_client_if_needed()

        logger.info(
            "SymbolSelector initialized (enabled=%s, interval_loops=%d, "
            "min_trades=%d, mode=%s, gpt_enabled=%s)",
            self.enabled,
            self.interval_loops,
            self.min_trades,
            self.mode,
            self._gpt_enabled,
        )

    # ------------------------------------------------------------------ #
    # GPT client
    # ------------------------------------------------------------------ #

    def _init_client_if_needed(self) -> None:
        if self.mode not in {"gpt", "hybrid"}:
            self.client = None
            self._gpt_enabled = False
            return

        if OpenAI is None:
            logger.warning(
                "SymbolSelector: openai package is not installed; "
                "falling back to heuristic mode."
            )
            self.client = None
            self._gpt_enabled = False
            return

        api_key = (
            os.getenv("HFTA_OPENAI_API_KEY")
            or os.getenv("OPENAI_API_KEY")
            or os.getenv("openai_api_key")
        )
        if not api_key:
            logger.warning(
                "SymbolSelector: no OpenAI API key found; "
                "falling back to heuristic mode."
            )
            self.client = None
            self._gpt_enabled = False
            return

        try:
            self.client = OpenAI(api_key=api_key)
            self._gpt_enabled = True
        except Exception as exc:
            logger.warning(
                "SymbolSelector: failed to initialize OpenAI client: %s; "
                "falling back to heuristic mode.",
                exc,
                exc_info=True,
            )
            self.client = None
            self._gpt_enabled = False

    # ------------------------------------------------------------------ #
    # Engine entry point
    # ------------------------------------------------------------------ #

    def on_loop(
        self,
        *,
        strategies: List[Strategy],
        tracker: Optional[ExecutionTracker],
        intraday_stats: Optional[IntradayStatsTracker] = None,
    ) -> None:
        """
        Called once per engine loop. Only runs every `interval_loops`.
        """
        if not self.enabled:
            return

        self._loop_counter += 1
        if self._loop_counter % self.interval_loops != 0:
            return

        if tracker is None:
            logger.debug("SymbolSelector: no ExecutionTracker; skipping.")
            return

        per_strat_stats = tracker.per_strategy_symbol_summary()
        if not per_strat_stats:
            logger.debug("SymbolSelector: no per-strategy stats yet; skipping.")
            return

        # Market universe (if any)
        if self.market_universe is not None and getattr(
            self.market_universe, "symbols", None
        ):
            symbol_universe: Set[str] = {
                s.upper() for s in self.market_universe.symbols
            }
            market_metrics: Mapping[str, Mapping[str, float]] = getattr(
                self.market_universe, "metrics_by_symbol", {}
            )
        else:
            # Fallback universe: symbols we have traded or strategies currently use.
            symbol_universe = self._collect_fallback_universe(
                per_strat_stats, strategies
            )
            market_metrics = {}

        intraday_metrics: Mapping[str, Mapping[str, float]] = {}
        if intraday_stats is not None:
            intraday_metrics = intraday_stats.summary()

        if not symbol_universe:
            logger.debug("SymbolSelector: empty symbol universe; skipping.")
            return

        decisions: Dict[str, str] = {}

        # GPT first (if enabled)
        use_gpt = self._gpt_enabled and self.mode in {"gpt", "hybrid"}
        if use_gpt:
            try:
                decisions = self._pick_via_gpt(
                    per_strat_stats=per_strat_stats,
                    symbol_universe=symbol_universe,
                    strategies=strategies,
                    market_metrics=market_metrics,
                    intraday_metrics=intraday_metrics,
                )
            except Exception:
                logger.exception("SymbolSelector: GPT-based selection failed")

        # Heuristic fallback / complement
        if not decisions or self.mode in {"heuristic", "hybrid"}:
            heuristic_decisions = self._pick_heuristic(
                per_strat_stats=per_strat_stats,
                symbol_universe=symbol_universe,
                strategies=strategies,
                market_metrics=market_metrics,
                intraday_metrics=intraday_metrics,
            )
            for sname, sym in heuristic_decisions.items():
                decisions.setdefault(sname, sym)

        if not decisions:
            logger.debug("SymbolSelector: no symbol decisions made; skipping.")
            return

        # Apply
        for strat in strategies:
            target_symbol = decisions.get(strat.name)
            if not target_symbol:
                continue

            current_symbol = getattr(strat, "symbol", None)
            target_symbol_u = target_symbol.upper()

            if current_symbol is not None and current_symbol.upper() == target_symbol_u:
                continue

            logger.info(
                "SymbolSelector: reassigning strategy '%s' from %s to %s",
                strat.name,
                current_symbol,
                target_symbol_u,
            )
            setattr(strat, "symbol", target_symbol_u)

    # ------------------------------------------------------------------ #
    # Universe helpers
    # ------------------------------------------------------------------ #

    def _collect_fallback_universe(
        self,
        per_strat_stats: Mapping[str, Mapping[str, Mapping[str, float]]],
        strategies: List[Strategy],
    ) -> Set[str]:
        symbols: Set[str] = set()
        for sym_map in per_strat_stats.values():
            for sym in sym_map.keys():
                symbols.add(sym.upper())
        for strat in strategies:
            sym = getattr(strat, "symbol", None)
            if sym:
                symbols.add(strat.symbol.upper())
        return symbols

    # ------------------------------------------------------------------ #
    # Heuristic selection
    # ------------------------------------------------------------------ #

    def _compute_symbol_scores(
        self,
        per_strat_stats: Mapping[str, Mapping[str, Mapping[str, float]]],
        symbol_universe: Set[str],
        market_metrics: Mapping[str, Mapping[str, float]],
        intraday_metrics: Mapping[str, Mapping[str, float]],
    ) -> Dict[str, SymbolScore]:
        """
        Blend:
          - experience (PnL, trade_count)
          - baseline liquidity (if available)
          - intraday volatility / range / return
        """
        # Aggregate experience across strategies
        agg_tc: Dict[str, int] = {}
        agg_pnl: Dict[str, float] = {}

        for sym_map in per_strat_stats.values():
            for symbol, stats in sym_map.items():
                symbol_u = symbol.upper()
                if symbol_u not in symbol_universe:
                    continue
                tc = int(stats.get("trade_count", 0))
                pnl = float(stats.get("realized_pnl", 0.0))
                if tc <= 0:
                    continue
                agg_tc[symbol_u] = agg_tc.get(symbol_u, 0) + tc
                agg_pnl[symbol_u] = agg_pnl.get(symbol_u, 0.0) + pnl

        scores: Dict[str, SymbolScore] = {}
        for symbol_u in symbol_universe:
            tc = agg_tc.get(symbol_u, 0)
            pnl = agg_pnl.get(symbol_u, 0.0)
            if tc < self.min_trades:
                pnl = 0.0
            avg = pnl / tc if tc > 0 else 0.0

            m = market_metrics.get(symbol_u, {})
            dollar_vol = float(m.get("dollar_volume", 0.0))
            day_chg = float(m.get("day_change_pct", 0.0))

            if dollar_vol > 0.0:
                import math

                liq = math.log10(dollar_vol + 1.0)
            else:
                liq = 0.0

            i = intraday_metrics.get(symbol_u, {})
            i_ret = float(i.get("intraday_return", 0.0))
            i_vol = float(i.get("volatility", 0.0))
            i_range = float(i.get("range_pct", 0.0))

            scores[symbol_u] = SymbolScore(
                symbol=symbol_u,
                trade_count=tc,
                realized_pnl=pnl,
                avg_pnl_per_trade=avg,
                liquidity_score=liq,
                day_change_pct=day_chg,
                intraday_return=i_ret,
                intraday_volatility=i_vol,
                intraday_range_pct=i_range,
            )

        return scores

    def _pick_heuristic(
        self,
        per_strat_stats: Mapping[str, Mapping[str, Mapping[str, float]]],
        symbol_universe: Set[str],
        strategies: List[Strategy],
        market_metrics: Mapping[str, Mapping[str, float]],
        intraday_metrics: Mapping[str, Mapping[str, float]],
    ) -> Dict[str, str]:
        """
        Heuristic scoring:

          total_score =
              3.0 * realized_pnl
            + 2.0 * avg_pnl_per_trade
            + 1.0 * liquidity_score
            + 0.5 * day_change_pct
            + 1.5 * intraday_range_pct
            + 1.0 * intraday_volatility
            + 1.0 * intraday_return

        Then, for now, we pick the same best symbol for all strategies.
        """
        scores = self._compute_symbol_scores(
            per_strat_stats=per_strat_stats,
            symbol_universe=symbol_universe,
            market_metrics=market_metrics,
            intraday_metrics=intraday_metrics,
        )
        if not scores:
            return {}

        def total_score(s: SymbolScore) -> float:
            return (
                3.0 * s.realized_pnl
                + 2.0 * s.avg_pnl_per_trade
                + 1.0 * s.liquidity_score
                + 0.5 * s.day_change_pct
                + 1.5 * s.intraday_range_pct
                + 1.0 * s.intraday_volatility
                + 1.0 * s.intraday_return
            )

        ranked = sorted(scores.values(), key=total_score, reverse=True)
        best_symbol = ranked[0].symbol

        decisions: Dict[str, str] = {}
        for strat in strategies:
            decisions[strat.name] = best_symbol

        return decisions

    # ------------------------------------------------------------------ #
    # GPT-based selection
    # ------------------------------------------------------------------ #

    def _build_state_json(
        self,
        per_strat_stats: Mapping[str, Mapping[str, Mapping[str, float]]],
        symbol_universe: Set[str],
        strategies: List[Strategy],
        market_metrics: Mapping[str, Mapping[str, float]],
        intraday_metrics: Mapping[str, Mapping[str, float]],
    ) -> str:
        state: Dict[str, Any] = {
            "symbol_universe": sorted(list(symbol_universe)),
            "strategies": [],
            "per_strategy_symbol_stats": per_strat_stats,
            "market_metrics": market_metrics,
            "intraday_metrics": intraday_metrics,
        }

        for strat in strategies:
            state["strategies"].append(
                {
                    "name": strat.name,
                    "current_symbol": getattr(strat, "symbol", None),
                    "config": getattr(strat, "config", {}),
                }
            )

        return json.dumps(state, separators=(",", ":"), sort_keys=True)

    def _call_model(self, state_json: str) -> Mapping[str, Any]:
        if self.client is None:
            raise RuntimeError("SymbolSelector client not initialized")

        system_prompt = (
            "You are an expert intraday symbol allocator for a small trading "
            "system. You must pick the single best equity symbol for each "
            "strategy based on trading experience and live market conditions."
        )

        user_prompt = (
            "You will receive JSON describing:\n"
            "- symbol_universe: list of allowed tickers\n"
            "- strategies: list of {name, current_symbol, config}\n"
            "- per_strategy_symbol_stats: realized PnL and trade counts\n"
            "- market_metrics: price, dollar_volume, day_change_pct per symbol\n"
            "- intraday_metrics: intraday_return, range_pct, volatility per symbol\n\n"
            "Goals:\n"
            "1) For each strategy, pick the single symbol it should trade to "
            "   maximize expected risk-adjusted profit.\n"
            "2) Favor symbols with strong realized PnL, high liquidity, and "
            "   healthy intraday volatility / range.\n"
            "3) Avoid switching symbols unless the new choice is clearly better.\n"
            "4) Only use symbols from symbol_universe.\n\n"
            "Return ONLY a JSON object with the following structure:\n"
            "{\n"
            '  \"decisions\": [\n'
            '    {\"strategy_name\": \"mm_AAPL\", \"target_symbol\": \"AAPL\"},\n'
            '    {\"strategy_name\": \"trend_AAPL\", \"target_symbol\": \"MSFT\"}\n'
            "  ]\n"
            "}\n"
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
            {
                "role": "user",
                "content": f"Current state JSON (stringified):\n{state_json}",
            },
        ]

        try:
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
            )
        except Exception as exc:
            logger.warning(
                "SymbolSelector: OpenAI request failed: %s", exc, exc_info=True
            )
            return {}

        msg = resp.choices[0].message
        raw_content = getattr(msg, "content", None)

        if isinstance(raw_content, list):
            parts: List[str] = []
            for part in raw_content:
                if isinstance(part, dict) and part.get("type") == "text":
                    text_obj = part.get("text")
                    if isinstance(text_obj, dict):
                        value = text_obj.get("value")
                        if isinstance(value, str):
                            parts.append(value)
                    elif isinstance(text_obj, str):
                        parts.append(text_obj)
                elif isinstance(part, str):
                    parts.append(part)
                else:
                    parts.append(str(part))
            content_str = "\n".join(parts).strip()
        elif isinstance(raw_content, str):
            content_str = raw_content.strip()
        else:
            content_str = ("" if raw_content is None else str(raw_content)).strip()

        if not content_str:
            logger.warning(
                "SymbolSelector: empty content in model response; raw message=%r",
                msg,
            )
            return {}

        def _parse_json(text: str) -> Optional[Mapping[str, Any]]:
            try:
                obj = json.loads(text)
            except json.JSONDecodeError:
                start = text.find("{")
                end = text.rfind("}")
                if start == -1 or end <= start:
                    return None
                try:
                    obj = json.loads(text[start : end + 1])
                except json.JSONDecodeError:
                    return None
            if not isinstance(obj, Mapping):
                return None
            return obj

        parsed = _parse_json(content_str)
        if parsed is None:
            logger.warning(
                "SymbolSelector: model returned non-JSON or badly formatted JSON: %r",
                content_str,
            )
            return {}

        return parsed

    def _pick_via_gpt(
        self,
        per_strat_stats: Mapping[str, Mapping[str, Mapping[str, float]]],
        symbol_universe: Set[str],
        strategies: List[Strategy],
        market_metrics: Mapping[str, Mapping[str, float]],
        intraday_metrics: Mapping[str, Mapping[str, float]],
    ) -> Dict[str, str]:
        state_json = self._build_state_json(
            per_strat_stats=per_strat_stats,
            symbol_universe=symbol_universe,
            strategies=strategies,
            market_metrics=market_metrics,
            intraday_metrics=intraday_metrics,
        )
        logger.debug("SymbolSelector: sending state to GPT: %s", state_json)

        resp = self._call_model(state_json)
        if not resp:
            return {}

        raw_decisions = resp.get("decisions", [])
        if not isinstance(raw_decisions, list):
            logger.warning(
                "SymbolSelector: 'decisions' field not a list; got %r",
                raw_decisions,
            )
            return {}

        decisions: Dict[str, str] = {}
        allowed = {s.upper() for s in symbol_universe}

        for item in raw_decisions:
            if not isinstance(item, Mapping):
                continue
            sname = item.get("strategy_name") or item.get("strategy")
            sym = item.get("target_symbol") or item.get("symbol")
            if not sname or not sym:
                continue
            sym_u = str(sym).upper()
            if sym_u not in allowed:
                logger.debug(
                    "SymbolSelector: ignoring GPT suggestion %s -> %s (not in universe)",
                    sname,
                    sym_u,
                )
                continue
            decisions[str(sname)] = sym_u

        return decisions
