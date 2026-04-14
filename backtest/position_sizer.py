"""
QuantForce Apex — Position Sizer
ATR-based sizing with Kelly cap and $1,200 account constraints.
Ported from fed-trading, data source replaced with PG.
"""
import math
from dataclasses import dataclass
from typing import Optional


@dataclass
class SizingResult:
    qty:          float
    notional:     float
    risk_amount:  float
    stop_distance:float
    kelly_fraction:float = 0.0


class PositionSizer:
    """
    Primary method: ATR-based fixed-risk sizing.
    risk_per_trade = account * risk_pct (default 2.5%)
    qty = floor(risk / stop_distance)
    Hard caps: notional <= max_cash_pct of available; <= max_single_pct of total
    """

    def __init__(self, cfg: dict = None):
        cfg = cfg or {}
        self.risk_pct       = cfg.get("risk_per_trade_pct", 0.025)
        self.max_cash_pct   = cfg.get("max_cash_pct",       0.70)
        self.max_single_pct = cfg.get("max_single_pct",     0.10)
        self.atr_stop_mult  = cfg.get("atr_stop_mult",      1.5)
        self.min_qty        = cfg.get("min_qty",             1.0)

    def size(self,
             entry_price:    float,
             stop_loss:      float,
             account_total:  float,
             available_cash: float,
             win_rate:       float = 0.55,
             avg_win_loss:   float = 2.0,
             size_modifier:  float = 1.0) -> SizingResult:
        """
        size_modifier: 0.5 for high-volatility (biotech), 1.0 default
        win_rate / avg_win_loss: used for Kelly fraction display only
        """
        if entry_price <= 0:
            return SizingResult(qty=0, notional=0, risk_amount=0, stop_distance=0)

        stop_distance = abs(entry_price - stop_loss)
        if stop_distance <= 0:
            stop_distance = entry_price * 0.02   # Fallback: 2% of price

        # ── Base risk amount ──────────────────────────────────────
        risk_amount = account_total * self.risk_pct * size_modifier

        # ── Raw qty from risk ─────────────────────────────────────
        raw_qty = risk_amount / stop_distance

        # ── Kelly fraction (informational) ────────────────────────
        kelly = (win_rate - (1 - win_rate) / avg_win_loss) if avg_win_loss > 0 else 0
        kelly = max(0.0, min(kelly, 0.25))   # Cap at 25%

        # ── Hard caps ─────────────────────────────────────────────
        # Cap 1: available cash * max_cash_pct
        max_by_cash = math.floor((available_cash * self.max_cash_pct) / entry_price)

        # Cap 2: total account * max_single_pct
        max_by_account = math.floor((account_total * self.max_single_pct) / entry_price)

        # Cap 3: Kelly-based (optional guard)
        max_by_kelly = math.floor((account_total * kelly) / entry_price) if kelly > 0 else 99999

        qty = min(raw_qty, max_by_cash, max_by_account, max_by_kelly)
        qty = max(self.min_qty, math.floor(qty))

        notional = qty * entry_price

        return SizingResult(
            qty           = qty,
            notional      = notional,
            risk_amount   = qty * stop_distance,
            stop_distance = stop_distance,
            kelly_fraction= kelly,
        )
