//! Integration & Unit Tests for Core Backtest Engine & Monte Carlo (`test_engine.rs`).
//!
//! Validates:
//! 1. Simple backtest loop with 10 synthetic M1 candles and 2 orders (1 TP win, 1 SL loss).
//! 2. Stop Loss execution with realized slippage on gap-down bar.
//! 3. Monte Carlo deterministic trade sequence shuffling (1,000 iterations, seed = 42).
//! 4. Extreme parameter validation (invalid candle high < low, empty trades history).

use aeterna_backtest::{
    run_backtest, run_monte_carlo, BacktestConfig, Candle, Direction, EngineError, ExecutionType,
    Order, PnlResult,
};

const EPSILON: f64 = 1e-6;

fn make_candle(
    timestamp: &str,
    open: f64,
    high: f64,
    low: f64,
    close: f64,
    tick_volume: u64,
) -> Candle {
    Candle {
        timestamp_utc: timestamp.to_string(),
        open,
        high,
        low,
        close,
        tick_volume,
    }
}

/// Test 1: Test Backtest Loop Sederhana
/// - 10 candle sintetis M1 XAUUSD.
/// - 2 order (1 kena TP profit, 1 kena SL loss).
/// - Assert summary.total_trades == 2, summary.win_trades == 1, summary.loss_trades == 1.
/// - Assert summary.net_pnl_usd persis sama dengan jumlah net_pnl_usd kedua trade.
#[test]
fn test_backtest_loop_sederhana() -> Result<(), EngineError> {
    let config = BacktestConfig::default();

    let candles = vec![
        make_candle(
            "2026-01-01T00:00:00Z",
            2740.00,
            2742.00,
            2739.00,
            2740.50,
            100,
        ), // bar 0: opens Order 1
        make_candle(
            "2026-01-01T00:01:00Z",
            2741.00,
            2746.00,
            2740.50,
            2745.50,
            120,
        ), // bar 1: Order 1 hits TP 2745.00
        make_candle(
            "2026-01-01T00:02:00Z",
            2745.00,
            2746.00,
            2744.00,
            2745.00,
            90,
        ), // bar 2: opens Order 2
        make_candle(
            "2026-01-01T00:03:00Z",
            2745.00,
            2745.50,
            2739.00,
            2739.50,
            150,
        ), // bar 3: Order 2 hits SL 2740.00
        make_candle(
            "2026-01-01T00:04:00Z",
            2740.00,
            2741.00,
            2739.00,
            2740.00,
            80,
        ),
        make_candle(
            "2026-01-01T00:05:00Z",
            2740.00,
            2741.50,
            2739.50,
            2741.00,
            85,
        ),
        make_candle(
            "2026-01-01T00:06:00Z",
            2741.00,
            2742.00,
            2740.00,
            2741.50,
            70,
        ),
        make_candle(
            "2026-01-01T00:07:00Z",
            2741.50,
            2742.50,
            2740.50,
            2742.00,
            75,
        ),
        make_candle(
            "2026-01-01T00:08:00Z",
            2742.00,
            2743.00,
            2741.00,
            2742.50,
            95,
        ),
        make_candle(
            "2026-01-01T00:09:00Z",
            2742.50,
            2743.50,
            2741.50,
            2743.00,
            110,
        ),
    ];

    let orders = vec![
        Order {
            id: "order-tp-win".to_string(),
            direction: Direction::Long,
            execution_type: ExecutionType::Market,
            requested_price: 2740.00,
            lot_size: 0.05,
            sl_price: Some(2735.00),
            tp_price: Some(2745.00),
        },
        Order {
            id: "order-sl-loss".to_string(),
            direction: Direction::Long,
            execution_type: ExecutionType::Market,
            requested_price: 2745.00,
            lot_size: 0.05,
            sl_price: Some(2740.00),
            tp_price: Some(2755.00),
        },
    ];

    let initial_balance = 10_000.0;
    let (summary, audit_records) = run_backtest(&candles, &orders, &config, initial_balance)?;

    assert_eq!(summary.total_trades, 2, "Expected exactly 2 total trades");
    assert_eq!(summary.win_trades, 1, "Expected exactly 1 win trade");
    assert_eq!(summary.loss_trades, 1, "Expected exactly 1 loss trade");

    let sum_net_pnl: f64 = audit_records.iter().map(|r| r.net_pnl_usd).sum();
    assert!(
        (summary.net_pnl_usd - sum_net_pnl).abs() < EPSILON,
        "Expected summary.net_pnl_usd ({}) == sum of audit net_pnl_usd ({})",
        summary.net_pnl_usd,
        sum_net_pnl
    );

    // Verify first trade was profitable (entry 2740, exit 2745 -> +$25.00)
    assert!(audit_records[0].net_pnl_usd > 0.0);
    assert!((audit_records[0].executed_exit - 2745.00).abs() < EPSILON);

    // Verify second trade was a loss (entry 2745, exit 2740 -> -$25.00)
    assert!(audit_records[1].net_pnl_usd < 0.0);
    assert!((audit_records[1].executed_exit - 2740.00).abs() < EPSILON);

    Ok(())
}

/// Test 2: Test Stop Loss Hit dengan Slippage
/// - Long entry $2,740.00, SL $2,735.00.
/// - Candle berikutnya gap down dengan High $2,734.00, Low $2,730.00 (melompati SL 100 points > 15 points).
/// - Assert posisi ditutup di harga pasar $2,734.00 (slippage realized).
#[test]
fn test_stop_loss_hit_with_slippage() -> Result<(), EngineError> {
    let config = BacktestConfig::default(); // slippage_free_points: 15.0 ($0.15)

    let candles = vec![
        make_candle(
            "2026-01-01T00:00:00Z",
            2740.00,
            2741.00,
            2739.00,
            2740.00,
            100,
        ), // Bar 0: Long entry @ 2740.00
        make_candle(
            "2026-01-01T00:01:00Z",
            2733.00,
            2734.00,
            2730.00,
            2731.00,
            200,
        ), // Bar 1: Gap down, High 2734.00, Low 2730.00
    ];

    let orders = vec![Order {
        id: "order-gap-down-sl".to_string(),
        direction: Direction::Long,
        execution_type: ExecutionType::Market,
        requested_price: 2740.00,
        lot_size: 0.05,
        sl_price: Some(2735.00),
        tp_price: Some(2750.00),
    }];

    let initial_balance = 10_000.0;
    let (summary, audit_records) = run_backtest(&candles, &orders, &config, initial_balance)?;

    assert_eq!(summary.total_trades, 1, "Expected 1 closed trade");
    assert_eq!(audit_records.len(), 1, "Expected 1 audit record");

    let record = &audit_records[0];

    // Assert that position closed at the market price ($2,734.00) rather than SL ($2,735.00)
    assert!(
        (record.executed_exit - 2734.00).abs() < EPSILON,
        "Expected executed_exit == 2734.00, got {}",
        record.executed_exit
    );

    // Slippage in USD: 2734.00 - 2735.00 = -1.00 USD (-100 points)
    assert!(
        (record.slippage_exit_usd - (-1.00)).abs() < EPSILON,
        "Expected slippage_exit_usd == -1.00, got {}",
        record.slippage_exit_usd
    );

    Ok(())
}

/// Test 3: Test Monte Carlo Deterministic Reproducibility
/// - Buat 20 transaksi PnlResult sintetis (campuran win & loss).
/// - Jalankan run_monte_carlo dengan seed = Some(42) dan iterations = 1000.
/// - Jalankan sekali lagi dengan seed yang sama, assert percentile_95_max_dd_pct dan median_max_dd_pct identik 100%.
/// - Assert risk_of_ruin_10pct_dd berada pada rentang valid 0.0 <= x <= 1.0.
#[test]
fn test_monte_carlo_deterministic_reproducibility() -> Result<(), EngineError> {
    let mut trades = Vec::with_capacity(20);
    for i in 0..20 {
        let net = if i % 2 == 0 { 60.0 } else { -40.0 };
        trades.push(PnlResult {
            gross_pnl_usd: net,
            pnl_pips: net / 10.0,
            spread_cost_usd: 0.0,
            net_pnl_usd: net,
            margin_required_usd: 68.5,
        });
    }

    let initial_equity = 10_000.0;
    let iterations = 1000;
    let seed = Some(42);

    let run1 = run_monte_carlo(&trades, initial_equity, iterations, seed)?;
    let run2 = run_monte_carlo(&trades, initial_equity, iterations, seed)?;

    // 100% Deterministic audit reproducibility
    assert_eq!(
        run1.iterations, run2.iterations,
        "Iterations must be identical"
    );
    assert!(
        (run1.median_max_dd_pct - run2.median_max_dd_pct).abs() < EPSILON,
        "Median Max DD must be 100% identical between seeded runs"
    );
    assert!(
        (run1.percentile_95_max_dd_pct - run2.percentile_95_max_dd_pct).abs() < EPSILON,
        "95th percentile Max DD must be 100% identical between seeded runs"
    );
    assert!(
        (run1.percentile_99_max_dd_pct - run2.percentile_99_max_dd_pct).abs() < EPSILON,
        "99th percentile Max DD must be 100% identical between seeded runs"
    );
    assert!(
        (run1.risk_of_ruin_10pct_dd - run2.risk_of_ruin_10pct_dd).abs() < EPSILON,
        "Risk of ruin 10% DD must be 100% identical between seeded runs"
    );

    // Valid probability range
    assert!(
        run1.risk_of_ruin_10pct_dd >= 0.0 && run1.risk_of_ruin_10pct_dd <= 1.0,
        "Risk of ruin must be between 0.0 and 1.0, got {}",
        run1.risk_of_ruin_10pct_dd
    );

    Ok(())
}

/// Test 4: Test Parameter Ekstrem
/// - Candle dengan high < low -> assert Err(EngineError::InvalidCandleData).
/// - Monte Carlo dengan slice kosong -> assert Err(EngineError::EmptyTradeHistory).
#[test]
fn test_extreme_parameters() {
    let config = BacktestConfig::default();

    // 1. Invalid candle: high < low
    let invalid_candle = make_candle(
        "2026-01-01T00:00:00Z",
        2740.00,
        2730.00, // High < Low!
        2740.00,
        2735.00,
        100,
    );
    let orders = vec![Order {
        id: "order-1".to_string(),
        direction: Direction::Long,
        execution_type: ExecutionType::Market,
        requested_price: 2740.00,
        lot_size: 0.05,
        sl_price: Some(2735.00),
        tp_price: Some(2745.00),
    }];

    let res = run_backtest(&[invalid_candle], &orders, &config, 10_000.0);
    assert!(
        matches!(res, Err(EngineError::InvalidCandleData)),
        "Expected InvalidCandleData for high < low, got {:?}",
        res
    );

    // 2. Monte Carlo with empty trade history
    let empty_trades: Vec<PnlResult> = Vec::new();
    let mc_res = run_monte_carlo(&empty_trades, 10_000.0, 1000, Some(42));
    assert!(
        matches!(mc_res, Err(EngineError::EmptyTradeHistory)),
        "Expected EmptyTradeHistory for empty trades slice, got {:?}",
        mc_res
    );

    // 3. Monte Carlo with non-positive initial equity
    let single_trade = vec![PnlResult {
        gross_pnl_usd: 10.0,
        pnl_pips: 1.0,
        spread_cost_usd: 0.0,
        net_pnl_usd: 10.0,
        margin_required_usd: 68.5,
    }];
    let mc_zero_equity = run_monte_carlo(&single_trade, 0.0, 1000, Some(42));
    assert!(
        matches!(mc_zero_equity, Err(EngineError::EmptyTradeHistory)),
        "Expected EmptyTradeHistory for initial_equity <= 0.0, got {:?}",
        mc_zero_equity
    );
}
