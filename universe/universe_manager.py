"""
QuantForce Apex — Universe Manager
3-tier filtering: Whitelist -> Liquidity -> Daily Active Candidates
"""
import logging
import psycopg2
from typing import List, Dict, Optional
from datetime import datetime

from core.db import db_cursor

logger = logging.getLogger("UniverseManager")

# ── Liquidity filter constants ────────────────────────────────────
MIN_AVG_VOLUME   = 500_000   # 30-day avg daily volume
MIN_PRICE        = 3.0
MAX_PRICE        = 80.0
MIN_RVOL_ACTIVE  = 1.5       # To enter daily candidate pool
MIN_ATR_MOVE     = 1.0       # ATR moves to qualify as active


class UniverseManager:
    """
    Manages the 3-tier stock universe:
      Tier 1: universe_whitelist (all Russell 2000, ~2000 symbols)
      Tier 2: liquidity_pool    (30-day volume + price filter, ~300-500)
      Tier 3: daily_candidates  (today's RVOL/ATR active stocks, ~30-80)
    """

    def __init__(self):
        self._liquidity_pool:  List[str] = []
        self._daily_candidates:List[str] = []
        self._blacklist:       set       = set()
        self._last_refresh:    Optional[str] = None

    # ── Public API ────────────────────────────────────────────────

    def get_candidates(self) -> List[str]:
        """Return today's active candidate symbols."""
        return list(self._daily_candidates)

    def get_liquidity_pool(self) -> List[str]:
        return list(self._liquidity_pool)

    def refresh_daily(self) -> int:
        """
        Called at 09:00 ET each day.
        Loads liquidity pool from PG, then filters to active candidates.
        Returns count of candidates.
        """
        today = datetime.utcnow().strftime("%Y-%m-%d")
        if self._last_refresh == today and self._daily_candidates:
            return len(self._daily_candidates)

        self._load_liquidity_pool()
        self._load_blacklist()
        self._refresh_candidates_from_market_events()
        self._last_refresh = today

        logger.info(
            f"Universe refresh: whitelist=? "
            f"liquidity={len(self._liquidity_pool)} "
            f"candidates={len(self._daily_candidates)}"
        )
        return len(self._daily_candidates)

    def is_tradeable(self, symbol: str) -> bool:
        return (symbol in self._daily_candidates and
                symbol not in self._blacklist)

    def add_to_blacklist(self, symbol: str, reason: str = ""):
        self._blacklist.add(symbol)
        if symbol in self._daily_candidates:
            self._daily_candidates.remove(symbol)
        logger.warning(f"Blacklisted: {symbol} — {reason}")

    # ── Private loaders ───────────────────────────────────────────

    def _load_liquidity_pool(self):
        """Load pre-filtered Russell 2000 symbols from PG."""
        try:
            with db_cursor(commit=False) as cur:
                cur.execute("""
                    SELECT symbol FROM universe_whitelist
                    WHERE avg_volume_30d >= %s
                      AND price_last >= %s
                      AND price_last <= %s
                      AND active = true
                    ORDER BY avg_volume_30d DESC
                """, (MIN_AVG_VOLUME, MIN_PRICE, MAX_PRICE))
                rows = cur.fetchall()
                self._liquidity_pool = [r["symbol"] for r in rows]
        except Exception as e:
            logger.error(f"Failed to load liquidity pool: {e}")
            self._liquidity_pool = []

    def _refresh_candidates_from_market_events(self):
        """
        Query today's market_events for symbols with RVOL >= threshold.
        This is the real-time active filter.
        """
        if not self._liquidity_pool:
            return
        try:
            with db_cursor(commit=False) as cur:
                cur.execute("""
                    SELECT DISTINCT symbol
                    FROM market_events
                    WHERE ts >= NOW() - INTERVAL '2 hours'
                      AND (rvol >= %s OR atr_move >= %s)
                      AND symbol = ANY(%s)
                    ORDER BY symbol
                """, (MIN_RVOL_ACTIVE, MIN_ATR_MOVE, self._liquidity_pool))
                rows = cur.fetchall()
                candidates = [r["symbol"] for r in rows
                              if r["symbol"] not in self._blacklist]
                self._daily_candidates = candidates
        except Exception as e:
            logger.error(f"Failed to refresh candidates: {e}")
            # Fallback: use full liquidity pool (will be filtered by strategies)
            self._daily_candidates = [s for s in self._liquidity_pool
                                      if s not in self._blacklist][:200]

    def _load_blacklist(self):
        """Load blacklist from PG or config."""
        try:
            import yaml, os
            bl_path = os.path.join(os.path.dirname(__file__), "../config/blacklist.yaml")
            if os.path.exists(bl_path):
                with open(bl_path) as f:
                    data = yaml.safe_load(f) or {}
                    self._blacklist = set(data.get("symbols", []))
        except Exception:
            pass


# Global singleton
universe = UniverseManager()
