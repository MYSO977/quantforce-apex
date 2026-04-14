"""
QuantForce Apex — PostgreSQL Connection Factory (Layer 0)
"""
import os
import logging
import psycopg2
import psycopg2.extras
from contextlib import contextmanager

logger = logging.getLogger("DB")

# Connection defaults (override via environment variables)
DB_CONFIG = {
    "host":     os.getenv("QF_PG_HOST",     "192.168.0.18"),
    "port":     int(os.getenv("QF_PG_PORT", "5432")),
    "dbname":   os.getenv("QF_PG_DB",       "quantforce"),
    "user":     os.getenv("QF_PG_USER",     "heng"),
    "password": os.getenv("QF_PG_PASS",     "newpassword123"),
    "connect_timeout": 5,
}


def get_conn():
    """Return a new psycopg2 connection. Caller must close."""
    return psycopg2.connect(**DB_CONFIG)


@contextmanager
def db_cursor(commit: bool = True):
    """Context manager: yields cursor, auto-commits or rolls back."""
    conn = get_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            yield cur
        if commit:
            conn.commit()
    except Exception as e:
        conn.rollback()
        logger.error(f"DB error: {e}")
        raise
    finally:
        conn.close()


def write_signal(signal) -> bool:
    """Write a Signal to signals_raw table."""
    sql = """
        INSERT INTO signals_raw
            (signal_id, symbol, side, strategy_id, product, confidence,
             entry_price, stop_loss, take_profit, size, news_score, rvol,
             status, shadow, created_at, updated_at, meta)
        VALUES
            (%(signal_id)s, %(symbol)s, %(side)s, %(strategy_id)s, %(product)s,
             %(confidence)s, %(entry_price)s, %(stop_loss)s, %(take_profit)s,
             %(size)s, %(news_score)s, %(rvol)s, %(status)s, %(shadow)s,
             to_timestamp(%(created_at)s), to_timestamp(%(updated_at)s), %(meta)s)
        ON CONFLICT (signal_id) DO UPDATE SET
            status=EXCLUDED.status, updated_at=EXCLUDED.updated_at
    """
    import json
    try:
        with db_cursor() as cur:
            cur.execute(sql, {**signal.__dict__,
                              "side": signal.side.value,
                              "product": signal.product.value,
                              "status": signal.status.value,
                              "meta": json.dumps(signal.meta)})
        return True
    except Exception as e:
        logger.error(f"write_signal error: {e}")
        return False


def write_execution(fill) -> bool:
    """Write a Fill to executions table."""
    sql = """
        INSERT INTO executions
            (order_id, signal_id, symbol, side, qty, fill_price,
             commission, product, strategy_id, filled_at, meta)
        VALUES
            (%(order_id)s, %(signal_id)s, %(symbol)s, %(side)s, %(qty)s,
             %(fill_price)s, %(commission)s, %(product)s, %(strategy_id)s,
             to_timestamp(%(filled_at)s), %(meta)s)
    """
    import json
    try:
        with db_cursor() as cur:
            cur.execute(sql, {**fill.__dict__,
                              "side": fill.side.value,
                              "product": fill.product.value,
                              "meta": json.dumps(fill.meta)})
        return True
    except Exception as e:
        logger.error(f"write_execution error: {e}")
        return False
