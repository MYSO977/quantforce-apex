"""
QuantForce Apex — Backtester
Reads real PG market_events data. Ported from fed-trading with real data source.
Usage: python3 backtest/backtester.py --symbol AAPL --days 90 --strategy momentum_swing
"""
import os, sys, argparse, logging
from dataclasses import dataclass, field
from typing import List, Dict, Optional
from datetime import datetime, timedelta

sys.path.insert(0, os.path.expanduser("~/quantforce-apex"))

from core.interfaces import Bar, Signal, Side, ProductType, SignalStatus
from core.db          import db_cursor
from core.risk_gate   import RiskGate
from core.account     import AccountManager
from backtest.position_sizer import PositionSizer
from strategies.registry     import strategy_registry

import strategies.stock.momentum_swing
import strategies.stock.news_breakout
import strategies.stock.opening_range
import strategies.etf.sector_rotation

logging.basicConfig(level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("Backtest")


@dataclass
class Trade:
    symbol:      str
    side:        str
    entry_price: float
    exit_price:  float
    qty:         float
    entry_ts:    float
    exit_ts:     float
    stop_loss:   float
    take_profit: float
    strategy_id: str
    pnl:         float = 0.0
    commission:  float = 0.0

    def __post_init__(self):
        direction = 1 if self.side == "BUY" else -1
        gross = (self.exit_price - self.entry_price) * self.qty * direction
        self.pnl = gross - self.commission


@dataclass
class BacktestStats:
    symbol:       str
    strategy_id:  str
    start_balance:float
    end_balance:  float
    trades:       List[Trade] = field(default_factory=list)

    @property
    def total_trades(self):  return len(self.trades)
    @property
    def wins(self):          return sum(1 for t in self.trades if t.pnl > 0)
    @property
    def losses(self):        return sum(1 for t in self.trades if t.pnl <= 0)
    @property
    def win_rate(self):      return self.wins / self.total_trades if self.total_trades else 0
    @property
    def total_pnl(self):     return sum(t.pnl for t in self.trades)
    @property
    def avg_win(self):
        w = [t.pnl for t in self.trades if t.pnl > 0]
        return sum(w) / len(w) if w else 0
    @property
    def avg_loss(self):
        l = [t.pnl for t in self.trades if t.pnl <= 0]
        return sum(l) / len(l) if l else 0
    @property
    def profit_factor(self):
        gross_win  = sum(t.pnl for t in self.trades if t.pnl > 0)
        gross_loss = abs(sum(t.pnl for t in self.trades if t.pnl < 0))
        return gross_win / gross_loss if gross_loss > 0 else 999
    @property
    def max_drawdown(self):
        if not self.trades:
            return 0.0
        peak, dd = self.start_balance, 0.0
        bal = self.start_balance
        for t in self.trades:
            bal += t.pnl
            peak = max(peak, bal)
            dd   = min(dd, bal - peak)
        return dd
    @property
    def sharpe(self):
        import statistics
        pnls = [t.pnl for t in self.trades]
        if len(pnls) < 2:
            return 0.0
        avg = statistics.mean(pnls)
        std = statistics.stdev(pnls)
        return (avg / std * (252 ** 0.5)) if std > 0 else 0.0


def load_bars_from_pg(symbol: str, days: int = 90) -> List[Bar]:
    """Load historical bars from market_events table."""
    bars = []
    try:
        with db_cursor(commit=False) as cur:
            cur.execute("""
                SELECT extract(epoch from ts) as ts,
                       open, high, low, close, volume, rvol, vwap, atr
                FROM market_events
                WHERE symbol = %s
                  AND ts >= NOW() - INTERVAL '%s days'
                ORDER BY ts ASC
            """, (symbol, days))
            for row in cur.fetchall():
                bars.append(Bar(
                    symbol=symbol,
                    ts    =float(row["ts"]),
                    open  =float(row["open"]   or 0),
                    high  =float(row["high"]   or 0),
                    low   =float(row["low"]    or 0),
                    close =float(row["close"]  or 0),
                    volume=float(row["volume"] or 0),
                    rvol  =float(row["rvol"]   or 1.0),
                    vwap  =float(row["vwap"]   or 0),
                    atr   =float(row["atr"]    or 0),
                ))
    except Exception as e:
        logger.error(f"load_bars error: {e}")
    return bars


def run_backtest(symbol: str, strategy_id: str,
                 days: int = 90,
                 start_balance: float = 1200.0,
                 slippage_pct: float = 0.001) -> BacktestStats:

    logger.info(f"Backtest: {symbol} | {strategy_id} | {days}d | ${start_balance}")

    bars = load_bars_from_pg(symbol, days)
    if len(bars) < 25:
        logger.warning(f"Insufficient data: {len(bars)} bars for {symbol}")
        return BacktestStats(symbol=symbol, strategy_id=strategy_id,
                             start_balance=start_balance,
                             end_balance=start_balance)

    strategy = strategy_registry._registry.get(strategy_id)
    if not strategy:
        logger.error(f"Strategy {strategy_id} not found")
        return BacktestStats(symbol=symbol, strategy_id=strategy_id,
                             start_balance=start_balance,
                             end_balance=start_balance)

    strat        = strategy()
    sizer        = PositionSizer()
    acct         = AccountManager(start_balance)
    risk_gate    = RiskGate()
    stats        = BacktestStats(symbol=symbol, strategy_id=strategy_id,
                                 start_balance=start_balance,
                                 end_balance=start_balance)
    open_trade: Optional[Trade] = None

    for i in range(25, len(bars)):
        bar     = bars[i]
        history = bars[:i+1]
        account = acct.get_state()

        # Check if open trade hit SL or TP
        if open_trade:
            hit_sl = bar.low  <= open_trade.stop_loss
            hit_tp = bar.high >= open_trade.take_profit
            if hit_sl or hit_tp:
                exit_price = open_trade.take_profit if hit_tp else open_trade.stop_loss
                exit_price *= (1 - slippage_pct)   # Slippage on exit
                open_trade.exit_price = exit_price
                open_trade.exit_ts    = bar.ts
                stats.trades.append(open_trade)
                logger.info(
                    f"  {'WIN' if hit_tp else 'LOSS'} {symbol} "
                    f"exit={exit_price:.2f} pnl=${open_trade.pnl:.2f}"
                )
                open_trade = None
            continue   # Don't enter new trade while in position

        # Risk gate check
        ctx = {"bars": {symbol: history}, "news_scores": {}}
        sig = strat.on_bar(symbol, history, ctx)
        if not sig:
            continue

        result = risk_gate.check_signal(sig, account)
        if not result.approved:
            continue

        # Size position
        sizing = sizer.size(
            entry_price   = sig.entry_price,
            stop_loss     = sig.stop_loss,
            account_total = account.total_balance,
            available_cash= account.available_cash,
        )
        if sizing.qty < 1:
            continue

        # Apply slippage to entry
        fill_price = sig.entry_price * (1 + slippage_pct)
        commission = max(1.0, sizing.qty * 0.005)

        open_trade = Trade(
            symbol      = symbol,
            side        = sig.side.value,
            entry_price = fill_price,
            exit_price  = 0.0,
            qty         = sizing.qty,
            entry_ts    = bar.ts,
            exit_ts     = 0.0,
            stop_loss   = sig.stop_loss,
            take_profit = sig.take_profit,
            strategy_id = strategy_id,
            commission  = commission,
        )
        logger.info(
            f"  ENTRY {symbol} @{fill_price:.2f} "
            f"qty={sizing.qty:.0f} SL={sig.stop_loss:.2f} TP={sig.take_profit:.2f}"
        )

    stats.end_balance = start_balance + stats.total_pnl
    return stats


def main():
    parser = argparse.ArgumentParser(description="QuantForce Apex Backtester")
    parser.add_argument("--symbol",   default="SPY")
    parser.add_argument("--strategy", default="momentum_swing")
    parser.add_argument("--days",     type=int,   default=90)
    parser.add_argument("--balance",  type=float, default=1200.0)
    args = parser.parse_args()

    stats = run_backtest(args.symbol, args.strategy, args.days, args.balance)

    print(f"\n{'='*50}")
    print(f"Backtest: {stats.symbol} | {stats.strategy_id}")
    print(f"Period: {args.days} days | Balance: ${stats.start_balance:.2f}")
    print(f"{'='*50}")
    print(f"Trades:       {stats.total_trades} "
          f"(W:{stats.wins} L:{stats.losses})")
    print(f"Win rate:     {stats.win_rate:.1%}")
    print(f"Total P&L:    ${stats.total_pnl:+.2f}")
    print(f"End balance:  ${stats.end_balance:.2f}")
    print(f"Profit factor:{stats.profit_factor:.2f}")
    print(f"Max drawdown: ${stats.max_drawdown:.2f}")
    print(f"Sharpe:       {stats.sharpe:.2f}")
    print(f"Avg win:      ${stats.avg_win:.2f}")
    print(f"Avg loss:     ${stats.avg_loss:.2f}")
    print(f"{'='*50}\n")
    return stats


if __name__ == "__main__":
    main()
