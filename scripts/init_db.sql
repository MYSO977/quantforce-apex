-- QuantForce Apex — Database Schema
-- Run: psql -h 192.168.0.18 -U heng -d quantforce -f scripts/init_db.sql

-- ── universe_whitelist ────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS universe_whitelist (
    symbol          VARCHAR(20) PRIMARY KEY,
    name            VARCHAR(100),
    sector          VARCHAR(50),
    avg_volume_30d  BIGINT      DEFAULT 0,
    price_last      NUMERIC(12,4) DEFAULT 0,
    market_cap      BIGINT      DEFAULT 0,
    active          BOOLEAN     DEFAULT true,
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_universe_active ON universe_whitelist(active, avg_volume_30d DESC);

-- ── market_events (5-min bars from market_feed) ───────────────────
CREATE TABLE IF NOT EXISTS market_events (
    id              BIGSERIAL   PRIMARY KEY,
    symbol          VARCHAR(20) NOT NULL,
    ts              TIMESTAMPTZ NOT NULL,
    open            NUMERIC(12,4),
    high            NUMERIC(12,4),
    low             NUMERIC(12,4),
    close           NUMERIC(12,4),
    volume          BIGINT,
    rvol            NUMERIC(8,3) DEFAULT 1.0,
    vwap            NUMERIC(12,4) DEFAULT 0,
    atr             NUMERIC(10,4) DEFAULT 0,
    atr_move        NUMERIC(8,3) DEFAULT 0,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_market_events_symbol_ts ON market_events(symbol, ts DESC);
CREATE INDEX IF NOT EXISTS idx_market_events_ts ON market_events(ts DESC);
CREATE INDEX IF NOT EXISTS idx_market_events_rvol ON market_events(rvol DESC) WHERE rvol >= 1.5;

-- ── signals_raw ───────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS signals_raw (
    signal_id       VARCHAR(50) PRIMARY KEY,
    symbol          VARCHAR(20) NOT NULL,
    side            VARCHAR(10) NOT NULL,
    strategy_id     VARCHAR(50) NOT NULL,
    product         VARCHAR(20) DEFAULT 'stock',
    confidence      NUMERIC(5,3) DEFAULT 0,
    entry_price     NUMERIC(12,4) DEFAULT 0,
    stop_loss       NUMERIC(12,4) DEFAULT 0,
    take_profit     NUMERIC(12,4) DEFAULT 0,
    size            NUMERIC(12,2) DEFAULT 0,
    news_score      NUMERIC(5,2) DEFAULT 0,
    rvol            NUMERIC(8,3) DEFAULT 0,
    atr             NUMERIC(10,4) DEFAULT 0,
    status          VARCHAR(20) DEFAULT 'raw',
    shadow          BOOLEAN DEFAULT false,
    meta            JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_signals_raw_symbol ON signals_raw(symbol, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_signals_raw_strategy ON signals_raw(strategy_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_signals_raw_updated ON signals_raw(updated_at DESC);

-- ── signals_final (passed all gates) ─────────────────────────────
CREATE TABLE IF NOT EXISTS signals_final (
    signal_id       VARCHAR(50) PRIMARY KEY REFERENCES signals_raw(signal_id),
    symbol          VARCHAR(20) NOT NULL,
    side            VARCHAR(10) NOT NULL,
    strategy_id     VARCHAR(50) NOT NULL,
    approved_at     TIMESTAMPTZ DEFAULT NOW(),
    pushed_to_zmq   BOOLEAN DEFAULT false,
    meta            JSONB DEFAULT '{}'
);

-- ── executions ────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS executions (
    id              BIGSERIAL   PRIMARY KEY,
    order_id        VARCHAR(50) UNIQUE NOT NULL,
    signal_id       VARCHAR(50),
    symbol          VARCHAR(20) NOT NULL,
    side            VARCHAR(10) NOT NULL,
    qty             NUMERIC(12,4) NOT NULL,
    fill_price      NUMERIC(12,4) NOT NULL,
    commission      NUMERIC(8,4) DEFAULT 0,
    product         VARCHAR(20) DEFAULT 'stock',
    strategy_id     VARCHAR(50) DEFAULT '',
    confidence      NUMERIC(5,3) DEFAULT 0,
    phi3_note       TEXT,
    filled_at       TIMESTAMPTZ DEFAULT NOW(),
    meta            JSONB DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_executions_symbol ON executions(symbol, filled_at DESC);
CREATE INDEX IF NOT EXISTS idx_executions_filled ON executions(filled_at DESC);

-- ── account_state ─────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS account_state (
    id                  BIGSERIAL   PRIMARY KEY,
    total_balance       NUMERIC(12,2),
    settled_balance     NUMERIC(12,2),
    pending_settlement  NUMERIC(12,2) DEFAULT 0,
    unrealized_pnl      NUMERIC(12,2) DEFAULT 0,
    realized_pnl_today  NUMERIC(12,2) DEFAULT 0,
    open_positions      JSONB DEFAULT '{}',
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

-- ── daily_reports ─────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS daily_reports (
    id              BIGSERIAL   PRIMARY KEY,
    report_date     DATE        UNIQUE NOT NULL,
    trades          INT DEFAULT 0,
    wins            INT DEFAULT 0,
    losses          INT DEFAULT 0,
    realized_pnl    NUMERIC(12,2) DEFAULT 0,
    max_drawdown    NUMERIC(12,2) DEFAULT 0,
    end_balance     NUMERIC(12,2) DEFAULT 0,
    win_rate        NUMERIC(5,3) DEFAULT 0,
    signals_fired   INT DEFAULT 0,
    signals_rejected INT DEFAULT 0,
    report_json     JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- ── Useful views ──────────────────────────────────────────────────
CREATE OR REPLACE VIEW v_today_signals AS
SELECT signal_id, symbol, side, strategy_id, product,
       confidence, entry_price, stop_loss, take_profit,
       news_score, rvol, status, shadow, created_at
FROM signals_raw
WHERE created_at >= CURRENT_DATE
ORDER BY created_at DESC;

CREATE OR REPLACE VIEW v_today_executions AS
SELECT e.order_id, e.symbol, e.side, e.qty, e.fill_price,
       e.commission, e.strategy_id, e.filled_at,
       (e.qty * e.fill_price) AS gross_value
FROM executions e
WHERE e.filled_at >= CURRENT_DATE
ORDER BY e.filled_at DESC;

CREATE OR REPLACE VIEW v_active_candidates AS
SELECT DISTINCT m.symbol, MAX(m.rvol) as max_rvol,
       MAX(m.close) as last_price, MAX(m.ts) as last_seen
FROM market_events m
JOIN universe_whitelist u ON u.symbol = m.symbol AND u.active = true
WHERE m.ts >= NOW() - INTERVAL '2 hours'
  AND m.rvol >= 1.5
GROUP BY m.symbol
ORDER BY max_rvol DESC;

SELECT 'Schema initialized successfully' AS status;
