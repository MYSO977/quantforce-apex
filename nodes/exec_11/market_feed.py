"""
QuantForce Apex — Market Feed (runs on .11 Dell)
IB reqRealTimeBars -> BarAggregator(60x5s=5min) -> PG market_events
clientId=13
"""
import os, sys, time, logging
from collections import defaultdict
from ib_insync import IB, Stock, RealTimeBar, util

sys.path.insert(0, os.path.expanduser("~/quantforce-apex"))
from core.db import db_cursor

util.logToConsole(logging.WARNING)
logging.basicConfig(level=logging.INFO, force=True,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s")
logger = logging.getLogger("MarketFeed")

IB_HOST   = os.getenv("IB_HOST", "127.0.0.1")
IB_PORT   = int(os.getenv("IB_PORT", "4002"))
CLIENT_ID = 13

# L1 screening thresholds
RVOL_MIN  = 1.5
VWAP_DEV  = 0.005   # 0.5%
ATR_MULT  = 1.0


class BarAggregator:
    """Accumulate 60x5-second bars into synthetic 5-minute bars."""
    def __init__(self, symbol: str):
        self.symbol = symbol
        self.bars_5s: list = []
        self.sma20_closes: list = []   # For RVOL baseline

    def add(self, bar: RealTimeBar):
        self.bars_5s.append(bar)
        if len(self.bars_5s) >= 60:
            self._flush()

    def _flush(self):
        bars = self.bars_5s[:60]
        self.bars_5s = self.bars_5s[60:]

        o = bars[0].open
        h = max(b.high   for b in bars)
        l = min(b.low    for b in bars)
        c = bars[-1].close
        v = sum(b.volume for b in bars)

        # VWAP approximation
        vwap = sum(b.close * b.volume for b in bars) / max(v, 1)

        # ATR (high-low of this bar as proxy)
        atr = h - l

        # RVOL: current bar volume vs 20-bar average
        self.sma20_closes.append(v)
        if len(self.sma20_closes) > 20:
            self.sma20_closes.pop(0)
        avg_vol = sum(self.sma20_closes) / len(self.sma20_closes)
        rvol    = v / avg_vol if avg_vol > 0 else 1.0

        # ATR move in ATR units
        atr_move = (h - l) / atr if atr > 0 else 0

        # L1 screening
        vwap_dev = abs(c - vwap) / vwap if vwap > 0 else 0
        passes = True  # DEBUG

        if passes:
            self._write_to_pg(
                ts=bars[-1].time, o=o, h=h, l=l, c=c,
                volume=v, rvol=rvol, vwap=vwap, atr=atr, atr_move=atr_move
            )

    def _write_to_pg(self, **kw):
        try:
            with db_cursor() as cur:
                cur.execute("""
                    INSERT INTO market_events
                        (symbol, ts, open, high, low, close,
                         volume, rvol, vwap, atr, atr_move)
                    VALUES (%s, to_timestamp(%s), %s, %s, %s, %s,
                            %s, %s, %s, %s, %s)
                """, (self.symbol, kw["ts"].timestamp(),
                      kw["o"], kw["h"], kw["l"], kw["c"],
                      kw["volume"], round(kw["rvol"],3),
                      kw["vwap"], kw["atr"], kw["atr_move"]))
            logger.debug(f"{self.symbol} bar written: "
                         f"c={kw['c']:.2f} rvol={kw['rvol']:.2f}")
        except Exception as e:
            logger.error(f"PG write error {self.symbol}: {e}")


def run(symbols: list):
    ib = IB()
    ib.connect(IB_HOST, IB_PORT, clientId=CLIENT_ID)
    logger.info(f"Market feed connected: {len(symbols)} symbols")

    aggregators = {sym: BarAggregator(sym) for sym in symbols}

    def on_bar(bars, has_new):
        if not has_new:
            return
        bar = bars[-1]
        sym = bar.contract.symbol if hasattr(bar, 'contract') else None
        # Match to aggregator via subscription
        for s, agg in aggregators.items():
            agg.add(bar)
            break   # ib_insync passes contract-bound bar

    # Subscribe all symbols
    contracts = [Stock(sym, "SMART", "USD") for sym in symbols]
    ib.qualifyContracts(*contracts)

    bar_lists = {}
    for contract in contracts:
        bl = ib.reqRealTimeBars(contract, 5, "TRADES", False)
        sym = contract.symbol
        # Bind aggregator to this bar list
        agg = aggregators[sym]
        bl.updateEvent += lambda bars, has_new, a=agg: (
            a.add(bars[-1]) if has_new and bars else None
        )
        bar_lists[sym] = bl
        logger.info(f"Subscribed: {sym}")

    logger.info("Market feed running...")
    ib.run()


if __name__ == "__main__":
    # Load candidate symbols from PG universe
    try:
        with db_cursor(commit=False) as cur:
            cur.execute("""
                SELECT symbol FROM universe_whitelist
                WHERE active=true AND avg_volume_30d >= 500000
                ORDER BY avg_volume_30d DESC LIMIT 150
            """)
            syms = [r["symbol"] for r in cur.fetchall()]
    except Exception as e:
        logger.error(f"DB load error: {e}")
        # Fallback: ETF universe always monitored
        syms = ["SPY","QQQ","IWM","XLK","XLV","XLF","XLE","XLI",
                "XLY","XLP","XLB","XLU","XLRE","XLC"]

    if not syms:
        syms = ["SPY","QQQ","IWM"]

    logger.info(f"Starting market feed for {len(syms)} symbols")
    run(syms)
