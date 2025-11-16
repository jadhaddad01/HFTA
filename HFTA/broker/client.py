# HFTA/broker/client.py

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional, List

import getpass

from HFTA.wealthsimple_v2 import WealthsimpleV2

logger = logging.getLogger(__name__)


@dataclass
class Quote:
    symbol: str
    security_id: str
    bid: Optional[float]
    ask: Optional[float]
    last: Optional[float]
    bid_size: Optional[float]
    ask_size: Optional[float]
    timestamp: Optional[str]


@dataclass
class PortfolioSnapshot:
    account_id: str
    currency: str
    net_worth: float
    cash_available: float


@dataclass
class Holding:
    symbol: str
    quantity: float
    avg_price: Optional[float]
    security_id: Optional[str] = None


def _to_float(val: Any) -> Optional[float]:
    """
    Safely convert Wealthsimple values to float.
    Handles:
      - None
      - strings like "123.45"
      - dicts like {"amount": "123.45", "currency": "CAD"}
    """
    if val is None:
        return None

    if isinstance(val, dict) and "amount" in val:
        val = val["amount"]

    try:
        return float(val)
    except (TypeError, ValueError):
        return None


class WealthsimpleClient:
    """
    Thin wrapper around WealthsimpleV2 for the HFTA engine.

    Behaviour:
    - If account_id is provided: use that exact account (or error if not found).
    - If account_id is omitted: automatically use the account whose
      name == 'HFTA'. If no such account exists, raise an error.
    """

    TARGET_ACCOUNT_NAME = "HFTA"

    def __init__(
        self,
        account_id: Optional[str] = None,
        currency: str = "CAD",
        ws: Optional[WealthsimpleV2] = None,
    ) -> None:
        # Underlying API client (its __init__ already tries keyring/env creds)
        self.ws = ws or WealthsimpleV2()
        self.currency = currency
        self._security_cache: Dict[str, str] = {}

        # Make sure we actually have an access token; if not, prompt user
        self._ensure_login()

        # After login we can safely fetch accounts and pick one
        self._account_id = self._select_account(account_id)
        logger.info("WealthsimpleClient initialized for account %s", self._account_id)

    # ------------------------------------------------------------------ #
    # Login handling
    # ------------------------------------------------------------------ #

    def _ensure_login(self) -> None:
        """
        If the WealthsimpleV2 client has no access_token, do an interactive login.
        """
        if getattr(self.ws, "access_token", None):
            logger.info("Wealthsimple session already authenticated.")
            return

        print("No active Wealthsimple session found. Please log in.")

        username = input("Wealthsimple email/username: ").strip()
        password = getpass.getpass("Wealthsimple password: ").strip()
        otp = input("OTP (press Enter if not required): ").strip() or None

        self.ws.authenticate(username, password, otp)

        save_fn = getattr(self.ws, "_save_tokens_to_keyring", None)
        if callable(save_fn):
            try:
                save_fn(username=username)
            except Exception as e:
                logger.warning("Failed to save tokens to keyring: %s", e)

        logger.info("Wealthsimple login successful.")

    # ------------------------------------------------------------------ #
    # Account helpers
    # ------------------------------------------------------------------ #

    def _select_account(self, account_id: Optional[str]) -> str:
        """
        Choose which account to use.

        Priority:
        1) Explicit account_id if provided and exists.
        2) Account whose name == 'HFTA' (exact match, case-sensitive).
           If not found, raise a RuntimeError.
        """
        accounts = self.ws.get_accounts()
        if not accounts:
            raise RuntimeError("No accounts returned from Wealthsimple API.")

        # 1) Explicit account_id
        if account_id is not None:
            for acc in accounts:
                if acc.get("id") == account_id:
                    logger.info("Using explicit account_id=%s", account_id)
                    return account_id
            raise ValueError(f"account_id={account_id!r} not found in Wealthsimple accounts.")

        # 2) Default: account with name == 'HFTA'
        for acc in accounts:
            name = acc.get("name") or acc.get("nickname") or acc.get("accountNickname")
            if isinstance(name, str) and name == self.TARGET_ACCOUNT_NAME:
                logger.info(
                    "Using default account with name='%s': id=%s",
                    self.TARGET_ACCOUNT_NAME,
                    acc.get("id"),
                )
                return acc["id"]

        # If we get here, the HFTA account doesn't exist: hard error
        details = [
            (a.get("id"), a.get("name") or a.get("nickname") or a.get("accountNickname"))
            for a in accounts
        ]
        raise RuntimeError(
            f"No Wealthsimple account found with name='{self.TARGET_ACCOUNT_NAME}'. "
            f"Available accounts (id, name): {details}"
        )

    @property
    def account_id(self) -> str:
        return self._account_id

    # ------------------------------------------------------------------ #
    # Security resolution + quotes
    # ------------------------------------------------------------------ #

    def resolve_security_id(self, symbol: str, exchange: Optional[str] = None) -> str:
        key = symbol.upper() if not exchange else f"{symbol.upper()}:{exchange}"
        if key in self._security_cache:
            return self._security_cache[key]

        # Try helper first
        try:
            sec_id = self.ws.get_ticker_id(symbol, exchange=exchange)
        except Exception:
            # Fallback search
            results = self.ws.search_securities(symbol)
            cand_id = None
            for r in results:
                stock = r.get("stock", {})
                if stock.get("symbol", "").upper() == symbol.upper():
                    if not exchange or stock.get("primaryExchange") == exchange:
                        cand_id = r["id"]
                        break
            if not cand_id and results:
                cand_id = results[0]["id"]
            if not cand_id:
                raise ValueError(f"Could not resolve security_id for {symbol}")
            sec_id = cand_id

        self._security_cache[key] = sec_id
        return sec_id

    def get_quote(self, symbol: str, exchange: Optional[str] = None) -> Quote:
        """
        Returns a Quote with numeric bid/ask/last (floats or None).
        """
        sec_id = self.resolve_security_id(symbol, exchange)
        q = self.ws.get_security_quote(sec_id, currency=self.currency)

        bid = _to_float(q.get("bid") or q.get("bid_price") or q.get("bidPrice"))
        ask = _to_float(q.get("ask") or q.get("ask_price") or q.get("askPrice"))
        last = _to_float(q.get("price") or q.get("last") or q.get("lastPrice"))
        bid_size = _to_float(q.get("bidSize") or q.get("bid_size"))
        ask_size = _to_float(q.get("askSize") or q.get("ask_size"))

        return Quote(
            symbol=symbol.upper(),
            security_id=sec_id,
            bid=bid,
            ask=ask,
            last=last,
            bid_size=bid_size,
            ask_size=ask_size,
            timestamp=q.get("timestamp"),
        )

    # ------------------------------------------------------------------ #
    # Portfolio snapshot + holdings
    # ------------------------------------------------------------------ #

    def get_portfolio_snapshot(self) -> PortfolioSnapshot:
        """
        Basic snapshot with net worth and cash.
        """
        fin_raw = self.ws.get_account_financials([self._account_id], currency=self.currency)

        if isinstance(fin_raw, dict) and "financials" in fin_raw:
            fin = fin_raw["financials"][0]
        elif isinstance(fin_raw, list):
            fin = fin_raw[0]
        else:
            fin = fin_raw

        net_worth = _to_float(fin.get("netWorth"))
        cash_available = _to_float(fin.get("buyingPower"))

        return PortfolioSnapshot(
            account_id=self._account_id,
            currency=self.currency,
            net_worth=net_worth or 0.0,
            cash_available=cash_available or 0.0,
        )

    def get_equity_positions(self) -> Dict[str, Holding]:
        """
        Return current equity holdings for this account as a mapping:
            { 'AAPL': Holding(...), ... }

        This is deliberately defensive on field names. If parsing fails,
        it returns an empty dict (which causes risk logic to block sells).
        """
        try:
            positions: List[Dict[str, Any]] = self.ws.get_positions(
                account_ids=[self._account_id],
                security_type="EQUITY",
                include_security=True,
                aggregated=False,
            )
        except Exception as e:
            logger.warning("get_equity_positions failed: %s", e)
            return {}

        result: Dict[str, Holding] = {}
        for p in positions:
            security = p.get("security") or {}
            symbol = (security.get("symbol") or p.get("symbol") or "").upper()
            if not symbol:
                continue

            qty = _to_float(
                p.get("quantity")
                or p.get("netQuantity")
                or p.get("units")
            )
            if qty is None:
                qty = 0.0

            avg_price = _to_float(
                p.get("averagePrice")
                or p.get("bookPrice")
                or p.get("book_value")
            )

            sec_id = security.get("id")
            result[symbol] = Holding(
                symbol=symbol,
                quantity=qty,
                avg_price=avg_price,
                security_id=sec_id,
            )

        return result

    # ------------------------------------------------------------------ #
    # Equity orders (basic)
    # ------------------------------------------------------------------ #

    def place_equity_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        order_type: str = "limit",
        limit_price: Optional[float] = None,
    ) -> Dict[str, Any]:
        account_id = self._account_id
        sec_id = self.resolve_security_id(symbol)

        side = side.lower()
        order_type = order_type.lower()

        if side not in {"buy", "sell"}:
            raise ValueError("side must be 'buy' or 'sell'")

        logger.info(
            "Placing %s %s: %s x %s @ %s (account=%s)",
            side,
            order_type,
            quantity,
            symbol,
            limit_price,
            account_id,
        )

        if order_type == "market":
            if side == "buy":
                return self.ws.market_buy(account_id, sec_id, quantity)
            else:
                return self.ws.market_sell(account_id, sec_id, quantity)

        if order_type == "limit":
            if limit_price is None:
                raise ValueError("limit_price required for limit orders")
            if side == "buy":
                return self.ws.limit_buy(account_id, sec_id, quantity, limit_price)
            else:
                return self.ws.limit_sell(account_id, sec_id, quantity, limit_price)

        raise ValueError(f"Unsupported order_type: {order_type}")
