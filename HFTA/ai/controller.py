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

    def maybe_run(
        self,
        risk_config: Any,
        strategies: List[Any],
        execution_tracker: Any,
    ) -> None:
        """
        Called from the engine loop.

        Every `interval_loops` calls, this will:
          - Build a JSON snapshot of current state (PnL, positions,
            risk_config, strategies).
          - Call the model.
          - Apply updates to strategies and risk_config.
        """
        if not self.enabled or self.client is None:
            return

        self._loop_counter += 1
        if self._loop_counter % self.interval_loops != 0:
            return

        try:
            state_json = self._build_state_json(risk_config, strategies, execution_tracker)
            logger.debug("AIController state JSON: %s", state_json)

            response = self._call_model(state_json)
            logger.debug("AIController raw response: %s", response)

            self._apply_response(response, risk_config, strategies)

        except Exception as exc:
            logger.warning("AIController error: %s", exc, exc_info=True)

    # ------------------------------------------------------------------ #
    # State snapshot
    # ------------------------------------------------------------------ #

    def _build_state_json(
        self,
        risk_config: Any,
        strategies: List[Any],
        execution_tracker: Any,
    ) -> str:
        """
        Build a compact JSON string describing:
          - total realized PnL
          - per-symbol positions (quantity, avg_price, realized_pnl)
          - current risk_config (whitelisted fields)
          - strategy configs (whitelisted numeric fields)
        """
        state: Dict[str, Any] = {}

        # Realized PnL
        realized_pnl_total = 0.0
        positions_dict: Dict[str, Any] = {}

        try:
            # Assume execution_tracker has attributes:
            #   positions: dict[symbol] -> position_obj
            #   realized_pnl_per_symbol: optional dict
            positions = getattr(execution_tracker, "positions", {})
            realized_per_symbol = getattr(
                execution_tracker, "realized_pnl_per_symbol", {}
            )

            for symbol, pos in positions.items():
                qty = float(getattr(pos, "quantity", 0.0))
                avg_price = float(getattr(pos, "avg_price", 0.0))
                realized = float(realized_per_symbol.get(symbol, 0.0))
                realized_pnl_total += realized

                positions_dict[symbol] = {
                    "quantity": qty,
                    "avg_price": avg_price,
                    "realized_pnl": realized,
                }
        except Exception as exc:
            logger.debug(
                "AIController failed to extract positions from ExecutionTracker: %s",
                exc,
                exc_info=True,
            )

        state["realized_pnl_total"] = realized_pnl_total
        state["positions"] = positions_dict

        # Risk config: whitelist simple numeric fields
        risk_info: Dict[str, Any] = {}
        for key in ("max_notional_per_order", "max_cash_utilization", "allow_short_selling"):
            if hasattr(risk_config, key):
                val = getattr(risk_config, key)
                # Allow bool for allow_short_selling
                if isinstance(val, (int, float, bool)):
                    risk_info[key] = val

        state["risk"] = risk_info

        # Strategies: capture a few key numeric parameters
        strat_list: List[Dict[str, Any]] = []
        for strat in strategies:
            strat_info: Dict[str, Any] = {}
            name = getattr(strat, "name", None)
            stype = strat.__class__.__name__
            strat_info["name"] = name
            strat_info["type"] = stype

            # Generic numeric fields we care about if present
            numeric_fields = [
                "spread",
                "max_inventory",
                "order_quantity",
                "short_window",
                "long_window",
                "trend_threshold",
                "max_position",
                "trailing_stop_pct",
                "take_profit_pct",
            ]
            for field in numeric_fields:
                if hasattr(strat, field):
                    val = getattr(strat, field)
                    if isinstance(val, (int, float)):
                        strat_info[field] = float(val)

            strat_list.append(strat_info)

        state["strategies"] = strat_list

        return json.dumps(state, sort_keys=True)

    # ------------------------------------------------------------------ #
    # Model call
    # ------------------------------------------------------------------ #

    def _call_model(self, state_json: str) -> Mapping[str, Any]:
        """
        Call the GPT model with the current state and return parsed JSON.

        Expected response JSON shape:

        {
          "strategy_updates": [
            {"name": "mm_AAPL", "params": {"spread": 0.06, "max_inventory": 3}},
            {"name": "scalper_AAPL", "params": {"trend_threshold": 0.0007}}
          ],
          "risk_updates": {
            "max_notional_per_order": 2000,
            "max_cash_utilization": 0.15
          },
          "code_change_ideas": "text..."
        }
        """
        if self.client is None:
            raise RuntimeError("AIController client not initialized")

        system_prompt = (
            "You are a cautious trading-parameter assistant."
        )

        user_prompt = (
            "You are an AI trading-parameter tuner for a small HFT-like "
            "system running in paper trading mode.\n"
            "You will receive the current state (PnL, positions, risk "
            "config, strategy parameters) as JSON.\n\n"
            "Goals:\n"
            "1) Improve expected risk-adjusted returns while keeping risk reasonable.\n"
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
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
            {"role": "user", "content": f"Current state JSON:\n{state_json}"},
        ]

        # NOTE: For gpt-5-mini and similar models, we must use
        #       max_completion_tokens instead of max_tokens.
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=self.temperature,
            max_completion_tokens=self.max_output_tokens,
            response_format={"type": "json_object"},
        )

        # OpenAI client v1.x: resp.choices[0].message.content
        content = resp.choices[0].message.content
        if not content:
            raise RuntimeError("AIController: empty content in model response")

        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"AIController: model returned non-JSON content: {content!r}"
            ) from exc

        if not isinstance(parsed, dict):
            raise RuntimeError(
                f"AIController: model JSON must be an object, got: {type(parsed)}"
            )

        return parsed

    # ------------------------------------------------------------------ #
    # Apply response
    # ------------------------------------------------------------------ #

    def _apply_response(
        self,
        response: Mapping[str, Any],
        risk_config: Any,
        strategies: List[Any],
    ) -> None:
        """
        Apply strategy_updates and risk_updates to in-memory objects.
        """
        strategy_updates = response.get("strategy_updates") or []
        risk_updates = response.get("risk_updates") or {}
        code_ideas = response.get("code_change_ideas")

        if code_ideas:
            logger.info("AI suggested code/logic ideas:\n%s", code_ideas)

        if strategy_updates:
            logger.info("AI suggested strategy_updates: %s", strategy_updates)
            self._apply_strategy_updates(strategy_updates, strategies)

        if risk_updates:
            logger.info("AI suggested risk_updates: %s", risk_updates)
            self._apply_risk_updates(risk_updates, risk_config)

    def _apply_strategy_updates(
        self,
        updates: List[Mapping[str, Any]],
        strategies: List[Any],
    ) -> None:
        """
        For each update:
          {"name": "mm_AAPL", "params": {"spread": 0.06, "max_inventory": 3}}

        find the matching strategy by .name and apply numeric changes.
        """
        strategies_by_name: Dict[Optional[str], Any] = {
            getattr(s, "name", None): s for s in strategies
        }

        for upd in updates:
            name = upd.get("name")
            params = upd.get("params") or {}
            strat = strategies_by_name.get(name)
            if strat is None:
                logger.debug(
                    "AIController: no strategy found with name=%r; skipping", name
                )
                continue

            for key, val in params.items():
                if not hasattr(strat, key):
                    logger.debug(
                        "AIController: strategy %s has no attr %r; skipping",
                        name,
                        key,
                    )
                    continue

                old = getattr(strat, key)
                if not isinstance(old, (int, float)):
                    logger.debug(
                        "AIController: strategy %s attr %r not numeric; skipping",
                        name,
                        key,
                    )
                    continue

                if not isinstance(val, (int, float)):
                    logger.debug(
                        "AIController: suggested value for %s.%s is not numeric; skipping",
                        name,
                        key,
                    )
                    continue

                val = float(val)

                # Clamp change magnitude: avoid huge jumps
                if old != 0:
                    ratio = abs(val / old)
                    if ratio > 3.0:
                        val = old * (3.0 if val > 0 else -3.0)

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
        """
        Apply numeric changes to risk_config. Example:

          "risk_updates": {
            "max_notional_per_order": 2000,
            "max_cash_utilization": 0.15
          }
        """
        for key, val in updates.items():
            if not hasattr(risk_config, key):
                logger.debug(
                    "AIController: risk_config has no attr %r; skipping", key
                )
                continue

            old = getattr(risk_config, key)
            if not isinstance(old, (int, float, bool)):
                logger.debug(
                    "AIController: risk_config attr %r not numeric/bool; skipping",
                    key,
                )
                continue

            if not isinstance(val, (int, float, bool)):
                logger.debug(
                    "AIController: suggested value for risk_config.%s is not numeric/bool; skipping",
                    key,
                )
                continue

            # Convert bool to float for clamping
            if isinstance(old, bool):
                setattr(risk_config, key, bool(val))
                logger.info(
                    "AI updated risk_config bool: %s %r -> %r", key, old, bool(val)
                )
                continue

            val = float(val)

            # Clamp magnitude
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
