# -*- coding: utf-8 -*-
"""
cost_model.py — deterministic transaction-cost model shared by the paper trader
and the walk-forward backtester.

Defaults (override via env or constructor):
  commission: 5 bps of notional, minimum 1.00 (account currency)   LUMINA_COMMISSION_BPS / LUMINA_COMMISSION_MIN
  slippage:   5 bps adverse to the trade side                       LUMINA_SLIPPAGE_BPS
These are assumptions, not broker quotes; they are labelled as such in reports.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, asdict
from typing import Dict


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class CostModel:
    commission_bps: float = 5.0
    commission_min: float = 1.0
    slippage_bps: float = 5.0

    @classmethod
    def from_env(cls) -> "CostModel":
        return cls(
            commission_bps=_env_float("LUMINA_COMMISSION_BPS", 5.0),
            commission_min=_env_float("LUMINA_COMMISSION_MIN", 1.0),
            slippage_bps=_env_float("LUMINA_SLIPPAGE_BPS", 5.0),
        )

    def fill_price(self, quote: float, side: str) -> float:
        """Execution price after adverse slippage: buys pay up, sells receive less."""
        s = self.slippage_bps / 10_000.0
        side = side.upper()
        if side == "BUY":
            return quote * (1.0 + s)
        if side == "SELL":
            return quote * (1.0 - s)
        raise ValueError(f"unknown side {side!r}")

    def commission(self, notional: float) -> float:
        if notional <= 0:
            return 0.0
        return max(self.commission_min, abs(notional) * self.commission_bps / 10_000.0)

    def execute(self, quote: float, quantity: int, side: str) -> Dict[str, float]:
        """Return fill price, gross notional, commission, slippage cost and net cash flow
        (negative = cash out for buys, positive = cash in for sells)."""
        if quote <= 0 or quantity <= 0:
            raise ValueError("quote and quantity must be positive")
        px = self.fill_price(quote, side)
        gross = px * quantity
        fee = self.commission(gross)
        slip_cost = abs(px - quote) * quantity
        net = -(gross + fee) if side.upper() == "BUY" else (gross - fee)
        return {
            "quote_price": quote,
            "fill_price": px,
            "gross_notional": gross,
            "commission": fee,
            "slippage_cost": slip_cost,
            "net_cash_flow": net,
        }

    def round_trip_return(self, entry_quote: float, exit_quote: float) -> float:
        """Net return of a 1-unit-of-capital long round trip, using bps costs only
        (minimum commission ignored because it depends on position size)."""
        s = self.slippage_bps / 10_000.0
        c = self.commission_bps / 10_000.0
        buy = entry_quote * (1 + s) * (1 + c)
        sell = exit_quote * (1 - s) * (1 - c)
        return sell / buy - 1.0

    def as_dict(self) -> Dict[str, float]:
        return asdict(self)
