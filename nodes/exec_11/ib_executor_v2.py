"""
QuantForce Apex — IB Executor v2 (runs on .11 Dell)
Receives signals via ZMQ PULL, submits bracket orders to IB Gateway.
clientId=20 | port=4002 | paper account DUP375010
"""
import os, sys, time, logging, json, asyncio
import zmq
from ib_insync import IB, Stock, Option, Forex, Future, Crypto, Order, util

sys.path.insert(0, os.path.expanduser("~/quantforce-apex"))

from core.interfaces import Signal, Fill, Side, ProductType, Order as QFOrder
from core.db          import write_execution, db_cursor
from core.notifier    import notify_fill

util.logToConsole(logging.WARNING)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("IBExecutor")

# ── Config ────────────────────────────────────────────────────────
IB_HOST    = os.getenv("IB_HOST",      "127.0.0.1")
IB_PORT    = int(os.getenv("IB_PORT",  "4002"))
CLIENT_ID  = int(os.getenv("IB_CLIENT_ID", "20"))
ZMQ_PORT   = int(os.getenv("QF_ZMQ_PORT",  "5558"))
IDEMPOTENT_TTL = 300   # seconds — ignore duplicate signal_id within this window

# ── IB contract factory ───────────────────────────────────────────
def make_contract(signal_dict: dict):
    sym     = signal_dict["symbol"]
    product = signal_dict.get("product", "stock")
    if product in ("stock", "etf"):
        return Stock(sym, "SMART", "USD")
    elif product == "option":
        # Options need expiry/strike/right from meta
        meta   = signal_dict.get("meta", {})
        return Option(sym, meta.get("expiry",""), meta.get("strike",0),
                      meta.get("right","C"), "SMART")
    elif product == "forex":
        return Forex(sym)   # e.g. "EURUSD"
    elif product == "futures":
        return Future(sym, exchange="CME")
    elif product == "crypto":
        return Crypto(sym, "PAXOS", "USD")
    else:
        return Stock(sym, "SMART", "USD")


class IBExecutor:
    def __init__(self):
        self.ib          = IB()
        self._seen_ids   = {}    # signal_id -> timestamp (idempotency)
        self._connected  = False

    def connect(self):
        try:
            self.ib.connect(IB_HOST, IB_PORT, clientId=CLIENT_ID, timeout=15)
            self._connected = True
            logger.info(f"IB connected: {IB_HOST}:{IB_PORT} clientId={CLIENT_ID}")
            logger.info(f"Account: {self.ib.managedAccounts()}")
        except Exception as e:
            logger.error(f"IB connect failed: {e}")
            self._connected = False

    def disconnect(self):
        if self._connected:
            self.ib.disconnect()

    def _is_duplicate(self, signal_id: str) -> bool:
        now = time.time()
        # Clean old entries
        self._seen_ids = {k: v for k, v in self._seen_ids.items()
                          if now - v < IDEMPOTENT_TTL}
        if signal_id in self._seen_ids:
            return True
        self._seen_ids[signal_id] = now
        return False

    def execute(self, signal_dict: dict) -> bool:
        signal_id = signal_dict.get("signal_id", "")
        symbol    = signal_dict["symbol"]
        side      = signal_dict["side"]          # "BUY" or "SELL"
        qty       = float(signal_dict.get("size", 0))
        entry     = float(signal_dict.get("entry_price", 0))
        sl        = float(signal_dict.get("stop_loss",   0))
        tp        = float(signal_dict.get("take_profit", 0))
        shadow    = signal_dict.get("shadow", False)

        # ── Idempotency check ─────────────────────────────────────
        if self._is_duplicate(signal_id):
            logger.warning(f"Duplicate signal_id {signal_id} — skipping")
            return False

        # ── Qty validation ────────────────────────────────────────
        if qty < 1:
            # Recalculate from size field (notional / price)
            notional = float(signal_dict.get("size", 0))
            qty = max(1, int(notional / entry)) if entry > 0 else 1

        logger.info(f"Executing: {symbol} {side} qty={qty:.0f} "
                    f"@{entry:.2f} SL={sl:.2f} TP={tp:.2f} shadow={shadow}")

        if shadow:
            logger.info(f"[SHADOW] Would place: {symbol} {side} {qty:.0f} shares")
            return True

        if not self._connected:
            self.connect()
            if not self._connected:
                logger.error("Not connected to IB — cannot execute")
                return False

        try:
            contract = make_contract(signal_dict)
            self.ib.qualifyContracts(contract)

            # ── Bracket order ─────────────────────────────────────
            action = "BUY" if side == "BUY" else "SELL"
            qty_int = int(qty)

            parent = Order(
                action        = action,
                totalQuantity = qty_int,
                orderType     = "MKT",
                transmit      = False,   # Hold until children attached
            )

            take_profit_order = Order(
                action        = "SELL" if action == "BUY" else "BUY",
                totalQuantity = qty_int,
                orderType     = "LMT",
                lmtPrice      = round(tp, 2),
                transmit      = False,
            )

            stop_loss_order = Order(
                action        = "SELL" if action == "BUY" else "BUY",
                totalQuantity = qty_int,
                orderType     = "STP",
                auxPrice      = round(sl, 2),
                transmit      = True,    # Transmit all together
            )

            bracket = self.ib.bracketOrder(
                action, qty_int,
                limitPrice     = round(entry * 1.005, 2),   # 0.5% slippage buffer
                takeProfitPrice= round(tp, 2),
                stopLossPrice  = round(sl, 2),
            )

            trades = []
            for order in bracket:
                trade = self.ib.placeOrder(contract, order)
                trades.append(trade)
                self.ib.sleep(0.1)

            logger.info(f"Bracket order placed: {symbol} {action} "
                        f"qty={qty_int} TP={tp:.2f} SL={sl:.2f}")

            # ── Wait for parent fill (up to 30s) ──────────────────
            parent_trade = trades[0]
            for _ in range(30):
                self.ib.sleep(1)
                if parent_trade.orderStatus.status in ("Filled", "Cancelled"):
                    break

            fill_price = parent_trade.orderStatus.avgFillPrice or entry
            filled_qty = parent_trade.orderStatus.filled or qty_int

            # ── Write execution to PG ─────────────────────────────
            fill = Fill(
                order_id    = str(parent_trade.order.orderId),
                symbol      = symbol,
                side        = Side.BUY if action == "BUY" else Side.SELL,
                qty         = filled_qty,
                fill_price  = fill_price,
                commission  = max(1.0, filled_qty * 0.005),
                product     = ProductType(signal_dict.get("product", "stock")),
                signal_id   = signal_id,
                strategy_id = signal_dict.get("strategy_id", ""),
            )
            write_execution(fill)
            notify_fill(fill)

            logger.info(f"✅ Filled: {symbol} {action} "
                        f"{filled_qty}@{fill_price:.2f}")
            return True

        except Exception as e:
            logger.error(f"Execute error for {symbol}: {e}", exc_info=True)
            return False


def run():
    # ── Clear ZMQ port conflicts ──────────────────────────────────
    os.system(f"fuser -k {ZMQ_PORT}/tcp 2>/dev/null || true")
    time.sleep(1)

    executor = IBExecutor()
    executor.connect()

    ctx    = zmq.Context()
    socket = ctx.socket(zmq.PULL)
    socket.bind(f"tcp://*:{ZMQ_PORT}")
    socket.setsockopt(zmq.RCVTIMEO, 5000)   # 5s timeout
    logger.info(f"ZMQ PULL bound on port {ZMQ_PORT}")

    logger.info("IB Executor ready — waiting for signals...")

    while True:
        try:
            # Keep IB connection alive
            if executor._connected:
                executor.ib.sleep(0)

            try:
                msg = socket.recv_json()
            except zmq.Again:
                continue   # Timeout — loop back

            logger.info(f"Received signal: {msg.get('symbol')} "
                        f"{msg.get('side')} strategy={msg.get('strategy_id')}")
            executor.execute(msg)

        except KeyboardInterrupt:
            logger.info("Executor stopped by user")
            break
        except Exception as e:
            logger.error(f"Executor loop error: {e}", exc_info=True)
            time.sleep(5)
            # Attempt reconnect
            if not executor._connected:
                logger.info("Attempting IB reconnect...")
                executor.connect()

    socket.close()
    ctx.term()
    executor.disconnect()


if __name__ == "__main__":
    run()
