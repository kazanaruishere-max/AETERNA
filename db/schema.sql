-- ====================================================================
-- AETERNA Quant Project - Canonical SQLite WAL Schema (v1.0)
-- Shared IPC Contract between Python Engine and Go Watchdog Daemon
-- ====================================================================

-- --------------------------------------------------------------------
-- 1. Model Registry
-- Menyimpan metadata model inferensi, parameter, dan status aktivasi.
-- --------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS model_registry (
    model_version TEXT PRIMARY KEY,
    training_date_utc TEXT NOT NULL,
    data_range TEXT NOT NULL,
    hyperparameters TEXT NOT NULL,
    backtest_metrics TEXT NOT NULL,
    forward_test_metrics TEXT,
    deployed_at_utc TEXT,
    status TEXT NOT NULL CHECK (status IN ('candidate', 'active', 'archived', 'rejected'))
);

-- --------------------------------------------------------------------
-- 2. Trades Execution Ledger
-- Audit trail lengkap setiap transaksi yang dieksekusi di broker.
-- --------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS trades (
    trade_id TEXT PRIMARY KEY,
    timestamp_entry_utc TEXT NOT NULL,
    timestamp_exit_utc TEXT,
    pair TEXT NOT NULL DEFAULT 'XAUUSD',
    direction TEXT NOT NULL CHECK (direction IN ('LONG', 'SHORT')),
    data_tag TEXT NOT NULL CHECK (data_tag IN ('training', 'validation', 'forward_test', 'live_production')),
    state_machine_state TEXT NOT NULL CHECK (state_machine_state IN ('NORMAL', 'PRE_NEWS_WATCH', 'PAUSED', 'RECOVERY_CHECK', 'MANUAL_OVERRIDE')),
    regime_detected TEXT NOT NULL,
    strategy_selected TEXT NOT NULL,
    confidence_score REAL NOT NULL CHECK (confidence_score >= 0.0 AND confidence_score <= 100.0),
    hypothesis TEXT NOT NULL,
    entry_price REAL NOT NULL,
    exit_price REAL,
    sl REAL NOT NULL,
    tp REAL NOT NULL,
    lot_size REAL NOT NULL CHECK (lot_size >= 0.01),
    exit_reason TEXT CHECK (exit_reason IS NULL OR exit_reason IN (
        'sl_hit', 'tp_hit', 'trailing_hit', 'partial_close', 
        'time_invalidation', 'regime_invalidation', 'pre_rollover_force', 'manual_emergency'
    )),
    pnl_usd REAL,
    pnl_pips REAL,
    spread_at_entry REAL NOT NULL,
    slippage_realized REAL,
    model_version_id TEXT NOT NULL,
    FOREIGN KEY (model_version_id) REFERENCES model_registry(model_version) ON UPDATE CASCADE ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_trades_timestamp ON trades(timestamp_entry_utc);
CREATE INDEX IF NOT EXISTS idx_trades_tag ON trades(data_tag);

-- --------------------------------------------------------------------
-- 3. Blocked Signals Audit
-- Rekaman seluruh sinyal yang dibatalkan oleh risk gate atau news filter.
-- --------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS blocked_signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp_utc TEXT NOT NULL,
    pair TEXT NOT NULL DEFAULT 'XAUUSD',
    direction TEXT NOT NULL CHECK (direction IN ('LONG', 'SHORT')),
    strategy_selected TEXT NOT NULL,
    reason_blocked TEXT NOT NULL CHECK (reason_blocked IN (
        'risk_gate_daily_loss', 'risk_gate_max_dd', 
        'state_machine_paused', 'state_machine_pre_news', 
        'low_liquidity_extreme', 'max_concurrent_exceeded',
        'stale_signal_expired'
    )),
    confidence_at_time REAL NOT NULL,
    would_be_entry_price REAL NOT NULL,
    current_spread REAL NOT NULL,
    details TEXT
);

CREATE INDEX IF NOT EXISTS idx_blocked_signals_timestamp ON blocked_signals(timestamp_utc);

-- --------------------------------------------------------------------
-- 4. Market Candles
-- Wadah time-series M1/M15/H1/H4 dengan Composite Primary Key per source.
-- --------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS market_candles (
    pair TEXT NOT NULL DEFAULT 'XAUUSD',
    timeframe TEXT NOT NULL CHECK (timeframe IN ('M1', 'M15', 'H1', 'H4')),
    timestamp_utc TEXT NOT NULL,
    source TEXT NOT NULL CHECK (source IN ('exness_mt5', 'oanda_v20')),
    open REAL NOT NULL,
    high REAL NOT NULL,
    low REAL NOT NULL,
    close REAL NOT NULL,
    tick_volume INTEGER NOT NULL,
    PRIMARY KEY (pair, timeframe, timestamp_utc, source)
);

CREATE INDEX IF NOT EXISTS idx_candles_lookup ON market_candles(pair, timeframe, source, timestamp_utc DESC);

-- --------------------------------------------------------------------
-- 5. System State IPC Singleton
-- Tabel 1-baris penampung state machine real-time untuk Go Watchdog & Python.
-- --------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS system_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    state TEXT NOT NULL CHECK (state IN ('NORMAL', 'PRE_NEWS_WATCH', 'PAUSED', 'RECOVERY_CHECK', 'MANUAL_OVERRIDE')),
    current_spread REAL NOT NULL,
    spread_baseline REAL NOT NULL,
    spread_z_score REAL NOT NULL,
    active_positions_count INTEGER NOT NULL CHECK (active_positions_count IN (0, 1)),
    equity_usd REAL NOT NULL,
    daily_pnl_usd REAL NOT NULL,
    trades_today_count INTEGER NOT NULL CHECK (trades_today_count >= 0 AND trades_today_count <= 5),
    last_news_event TEXT,
    last_updated_utc TEXT NOT NULL
);
