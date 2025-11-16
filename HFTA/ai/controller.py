# HFTA/ai/controller.py

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Mapping, Optional

try:
    from openai import OpenAI  # type: ignore
except ImportError:  # graceful degrade if SDK not installed
    OpenAI = None  # type: ignore

logger = logging.getLogger(__name__)


class AIController:
    """
    ChatGPT-based controller that periodically:
      - Observes current PnL, positions, strategy & risk params.
      - Asks a GPT model for JSON suggestions.
      - Applies safe numeric tweaks live to strategies & risk config.
      - Logs any code/logic-change ideas for you to review manually.

    It is intentionally conservative: it only changes attributes that
    already exist and are numeric, and it clamps changes to a sane range.
    """

    def __init__(
        self,
        model: str,
        interval_loops: int = 12,
        temperature: float = 0.2,
        max_output_tokens: int = 512,
        enabled: bool = True,
    ) -> None:
        self.model = model
        self.interval_loops = max(1, int(interval_loops))
        self.temperature = float(temperature)
        self.max_output_tokens = int(max_output_tokens)
        self.enabled = bool(enabled) and OpenAI is not None

        if not self.enabled:
            if OpenAI is None:
                logger.warning(
                    "AIController disabled: openai package not installed."
                )
            else:
                logger.info("AIController disabled via config.")
            self.client = None
        else:
            self.client = OpenAI()
            logger.info(
                "AIController initialized with model=%s, interval_loops=%d",
                self.model,
                self.interval_loops,
            )

        self._loop_counter = 0

    # ------------------------------------------------------------------ #
    # Public entry point from Engine
    # ------------------------------------------------------------------ #

    def on_loop(
        self,
        strategies: List[Any],
        risk_config: Any,
        tracker: Any,
    ) -> None:
        if not self.enabled or self.client is None:
            return

        self._loop_counter += 1
        if self._loop_counter % self.interval_loops != 0:
            return

        try:
            state = self._build_state(strategies, risk_config, tracker)
            suggestions = self._ask_model(state)
            if suggestions:
                self._apply_suggestions(suggestions, strategies, risk_config)
        except Exception as e:
            logger.warning("AIController error: %s", e)

    # ------------------------------------------------------------------ #
    # State building
    # ------------------------------------------------------------------ #

    def _build_state(
        self,
        strategies: List[Any],
        risk_config: Any,
        tracker: Any,
    ) -> Dict[str, Any]:
        # PnL & positions from ExecutionTracker
        positions_state: Mapping[str, Any] = {}
        realized_total = 0.0
        if tracker is not None:
            for sym, pos in tracker.summary().items():
                positions_state[sym] = {
                    "quantity": float(getattr(pos, "quantity", 0.0)),
                    "avg_price": float(getattr(pos, "avg_price", 0.0)),
                    "realized_pnl": float(getattr(pos, "realized_pnl", 0.0)),
                }
                realized_total += float(getattr(pos, "realized_pnl", 0.0))

        # Strategy params (only simple numeric fields for now)
        strategies_state: List[Dict[str, Any]] = []
        for s in strategies:
            s_state: Dict[str, Any] = {
                "name": getattr(s, "name", "unknown"),
                "type": s.__class__.__name__,
            }
            for attr in ["spread", "max_inventory", "order_quantity",
                         "short_window", "long_window",
                         "trend_threshold", "max_position"]:
                if hasattr(s, attr):
                    val = getattr(s, attr)
                    if isinstance(val, (int, float)):
                        s_state[attr] = val
            strategies_state.append(s_state)

        risk_state = {
            "max_notional_per_order": float(
                getattr(risk_config, "max_notional_per_order", 0.0)
            ),
            "max_cash_utilization": float(
                getattr(risk_config, "max_cash_utilization", 0.0)
            ),
            "allow_short_selling": bool(
                getattr(risk_config, "allow_short_selling", False)
            ),
        }

        return {
            "realized_pnl_total": realized_total,
            "positions": positions_state,
            "risk": risk_state,
            "strategies": strategies_state,
        }

    # ------------------------------------------------------------------ #
    # OpenAI call
    # ------------------------------------------------------------------ #

    def _ask_model(self, state: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Ask the GPT model for JSON suggestions using structured outputs.
        Expected JSON schema:

        {
          "strategy_updates": [
            {"name": "mm_AAPL", "params": {"spread": 0.04, "max_inventory": 3}}
          ],
          "risk_updates": {"max_notional_per_order": 1200.0},
          "code_change_ideas": "text..."
        }
        """
        prompt = (
            "You are an AI trading-parameter tuner for a small HFT-like "
            "system running in paper trading mode.\n"
            "You will receive the current state (PnL, positions, risk "
            "config, strategy parameters) as JSON.\n\n"
            "Goals:\n"
            "1) Improve expected risk-adjusted returns while keeping risk "
            "reasonable.\n"
            "2) Only propose small, incremental changes to numeric parameters.\n"
            "3) NEVER enable short selling (keep allow_short_selling=false).\n"
            "4) If you have ideas for code or logic changes that go beyond\n"
            "   parameter tweaks, describe them in text.\n\n"
            "Return a single JSON object with keys:\n"
            "- strategy_updates: list of {name, params} with numeric values.\n"
            "- risk_updates: object with optional numeric fields.\n"
            "- code_change_ideas: short markdown text with any deeper ideas.\n"
        )

        messages = [
            {"role": "system", "content": "You are a cautious trading-parameter assistant."},
            {"role": "user", "content": prompt},
            {
                "role": "user",
                "content": "Current state JSON:\n" + json.dumps(state, indent=2),
            },
        ]

        resp = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=self.temperature,
            max_tokens=self.max_output_tokens,
            response_format={"type": "json_object"},
        )

        content = resp.choices[0].message.content
        try:
            data = json.loads(content or "{}")
        except json.JSONDecodeError:
            logger.warning("AIController: non-JSON response: %s", content)
            return None
        return data

    # ------------------------------------------------------------------ #
    # Applying suggestions
    # ------------------------------------------------------------------ #

    def _apply_suggestions(
        self,
        suggestions: Dict[str, Any],
        strategies: List[Any],
        risk_config: Any,
    ) -> None:
        strategy_updates = suggestions.get("strategy_updates") or []
        risk_updates = suggestions.get("risk_updates") or {}
        code_ideas = suggestions.get("code_change_ideas")

        if strategy_updates:
            self._apply_strategy_updates(strategy_updates, strategies)

        if risk_updates:
            self._apply_risk_updates(risk_updates, risk_config)

        if code_ideas:
            logger.info("AI code/logic suggestions:\n%s", code_ideas)

    def _apply_strategy_updates(
        self,
        updates: List[Dict[str, Any]],
        strategies: List[Any],
    ) -> None:
        strat_by_name = {getattr(s, "name", ""): s for s in strategies}

        for upd in updates:
            name = upd.get("name")
            params = upd.get("params") or {}
            strat = strat_by_name.get(name)
            if strat is None:
                continue

            for key, val in params.items():
                if not isinstance(val, (int, float)):
                    continue
                if not hasattr(strat, key):
                    continue

                old = getattr(strat, key)
                if not isinstance(old, (int, float)):
                    continue

                # Clamp to a safe range: at most 2x change at once
                if old != 0:
                    ratio = abs(val / old)
                    if ratio > 2.0:
                        val = old * (2.0 if val > 0 else -2.0)

                setattr(strat, key, val)
                logger.info(
                    "AI updated strategy %s: %s %.4f -> %.4f",
                    name,
                    key,
                    old,
                    val,
                )

    def _apply_risk_updates(
        self,
        updates: Mapping[str, Any],
        risk_config: Any,
    ) -> None:
        for key in ["max_notional_per_order", "max_cash_utilization"]:
            if key not in updates:
                continue
            val = updates[key]
            if not isinstance(val, (int, float)):
                continue

            old = getattr(risk_config, key, None)
            if not isinstance(old, (int, float)):
                continue

            # Same 2x-change clamp
            if old != 0:
                ratio = abs(val / old)
                if ratio > 2.0:
                    val = old * (2.0 if val > 0 else -2.0)

            setattr(risk_config, key, val)
            logger.info(
                "AI updated risk_config: %s %.4f -> %.4f", key, old, val
            )

        # Never allow shorts even if model suggests it
        if getattr(risk_config, "allow_short_selling", False):
            setattr(risk_config, "allow_short_selling", False)
            logger.info(
                "AIController enforced allow_short_selling=False for safety."
            )
