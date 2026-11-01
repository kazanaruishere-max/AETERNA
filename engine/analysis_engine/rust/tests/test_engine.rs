//! Integration & Unit Tests for Core Backtest Engine & Monte Carlo (`test_engine.rs`).
//!
//! Validates:
//! 1. Simple backtest loop with 10 synthetic M1 candles and 2 orders (1 TP win, 1 SL loss).
//! 2. Stop Loss execution with realized slippage on gap-down bar.
//! 3. Monte Carlo deterministic trade sequence shuffling (1,000 iterations, seed = 42).
//! 4. Extreme parameter validation (invalid candle high < low, empty trades history).

use aeterna_backtest::{
    hours_since_weekly_open, run_backtest, run_monte_carlo, BacktestConfig, Candle, Direction,
    EngineError, ExecutionType, Order, PnlResult,
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
            signal_timestamp_utc: "2026-01-01T00:00:00Z".to_string(),
            validity_window_seconds: 900,
        },
        Order {
            id: "order-sl-loss".to_string(),
            direction: Direction::Long,
            execution_type: ExecutionType::Market,
            requested_price: 2745.00,
            lot_size: 0.05,
            sl_price: Some(2740.00),
            tp_price: Some(2755.00),
            signal_timestamp_utc: "2026-01-01T00:02:00Z".to_string(),
            validity_window_seconds: 900,
        },
    ];

    let initial_balance = 10_000.0;
    let (summary, audit_records, _) = run_backtest(&candles, &orders, &config, initial_balance)?;

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
            2734.00,
            2734.00,
            2730.00,
            2731.00,
            200,
        ), // Bar 1: Gap down, Open 2734.00, High 2734.00, Low 2730.00
    ];

    let orders = vec![Order {
        id: "order-gap-down-sl".to_string(),
        direction: Direction::Long,
        execution_type: ExecutionType::Market,
        requested_price: 2740.00,
        lot_size: 0.05,
        sl_price: Some(2735.00),
        tp_price: Some(2750.00),
        signal_timestamp_utc: "2026-01-01T00:00:00Z".to_string(),
        validity_window_seconds: 900,
    }];

    let initial_balance = 10_000.0;
    let (summary, audit_records, _) = run_backtest(&candles, &orders, &config, initial_balance)?;

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
        signal_timestamp_utc: "2026-01-01T00:00:00Z".to_string(),
        validity_window_seconds: 900,
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

/// Test 5: Integration Test Weekly Market Open Gap Rule Wired in Simulation Loop (`REQ-BKT-004`)
/// - Sunday open at 22:00 UTC (2026-01-04T22:00:00Z).
/// - Within first 3 hours (Sunday 22:15 UTC, hours = 0.25 < 3.0):
///   Slippage-free range (15 points) is disabled.
///   SL hit at 2734.90 (gap down by only 10 points below 2735.00 SL)
///   MUST execute at market price 2734.90, NOT protected at 2735.00.
///   record.gap_rule_applied MUST be true.
#[test]
fn test_weekly_market_open_gap_rule_wired_in_engine() -> Result<(), EngineError> {
    use aeterna_backtest::hours_since_weekly_open;

    // 1. Validate hours_since_weekly_open calculation
    let hours_sun_open = hours_since_weekly_open("2026-01-04T22:15:00Z")?; // Sunday 22:15 UTC
    assert!((hours_sun_open - 0.25).abs() < 1e-4);

    let hours_mon_early = hours_since_weekly_open("2026-01-05T00:30:00Z")?; // Monday 00:30 UTC = 2.5 hours
    assert!((hours_mon_early - 2.5).abs() < 1e-4);

    let hours_mon_late = hours_since_weekly_open("2026-01-05T02:00:00Z")?; // Monday 02:00 UTC = 4.0 hours (> 3.0)
    assert!((hours_mon_late - 4.0).abs() < 1e-4);

    let config = BacktestConfig {
        slippage_free_points: 15.0, // $0.15 protection outside gap window
        default_spread_points: 0.0, // isolate slippage from spread in this test
        ..BacktestConfig::default()
    };

    // 2. Bar sequence during Sunday open:
    // Bar 0: Sunday 22:05 UTC (hours = 0.083 < 3.0). Opens Long @ 2740.00.
    // Bar 1: Sunday 22:15 UTC (hours = 0.25 < 3.0). Gap down on open: Open 2734.90, High 2734.90, Low 2734.80.
    // The drop below SL 2735.00 is only $0.10 (10 points < 15 points threshold).
    // Outside gap window, 10 points would be protected by slippage-free range (exec @ 2735.00).
    // BUT in weekly gap window, protection is disabled -> MUST execute @ 2734.90 (market open price)!
    let gap_candles = vec![
        make_candle(
            "2026-01-04T22:05:00Z",
            2740.00,
            2741.00,
            2739.50,
            2740.00,
            100,
        ),
        make_candle(
            "2026-01-04T22:15:00Z",
            2734.90,
            2734.90,
            2734.80,
            2734.90,
            250,
        ),
    ];

    let orders = vec![Order {
        id: "order-gap-window-sl".to_string(),
        direction: Direction::Long,
        execution_type: ExecutionType::Market,
        requested_price: 2740.00,
        lot_size: 0.05,
        sl_price: Some(2735.00),
        tp_price: Some(2750.00),
        signal_timestamp_utc: "2026-01-04T22:00:00Z".to_string(),
        validity_window_seconds: 900,
    }];

    let (_summary, audit_records, _) = run_backtest(&gap_candles, &orders, &config, 10_000.0)?;
    assert_eq!(audit_records.len(), 1);

    let record = &audit_records[0];

    // Assert that gap rule was actively flagged
    assert!(
        record.gap_rule_applied,
        "Expected gap_rule_applied == true during Sunday opening window (< 3.0h)"
    );

    // Assert execution happened at market price (2734.90), proving slippage-free range was disabled
    assert!(
        (record.executed_exit - 2734.90).abs() < 1e-4,
        "Expected execution at 2734.90 under gap rule, but got {}",
        record.executed_exit
    );

    // Assert slippage was recorded as -0.10 USD
    assert!(
        (record.slippage_exit_usd - (-0.10)).abs() < 1e-4,
        "Expected slippage_exit_usd == -0.10, but got {}",
        record.slippage_exit_usd
    );

    Ok(())
}

/// Test 6: Spread Modeling & Telemetry Tracking in BacktestSummary (ASUMSI-M2-07)
/// - Validates that Long orders enter at Ask (Open + Spread).
/// - Validates that total_spread_cost_usd in BacktestSummary is strictly > 0.0
///   and exactly equals the sum of spread_cost_usd across all executed trades.
#[test]
fn test_spread_telemetry_and_ask_entry_tracking() -> Result<(), EngineError> {
    let config = BacktestConfig {
        default_spread_points: 20.0, // 0.20 USD = 2.0 pips
        ..BacktestConfig::default()
    };
    let spread_usd = 20.0 * 0.01; // 0.20 USD

    let candles = vec![
        make_candle(
            "2026-01-07T10:00:00Z", // Wednesday (midweek, no gap rule)
            2740.00,
            2741.00,
            2739.00,
            2740.50,
            100,
        ),
        make_candle(
            "2026-01-07T10:01:00Z",
            2741.00,
            2746.00,
            2740.50,
            2745.50,
            120,
        ), // Hits TP 2745.00
    ];

    let orders = vec![Order {
        id: "order-spread-tracking".to_string(),
        direction: Direction::Long,
        execution_type: ExecutionType::Market,
        requested_price: 2740.20,
        lot_size: 0.10,
        sl_price: Some(2730.00),
        tp_price: Some(2745.00),
        signal_timestamp_utc: "2026-01-07T10:00:00Z".to_string(),
        validity_window_seconds: 900,
    }];

    let (summary, audit_records, _) = run_backtest(&candles, &orders, &config, 10_000.0)?;
    assert_eq!(summary.total_trades, 1);
    assert_eq!(audit_records.len(), 1);

    let record = &audit_records[0];

    // Long entry entered at Ask: candle.open (2740.00) + spread (0.20) = 2740.20
    assert!(
        (record.executed_entry - (2740.00 + spread_usd)).abs() < 1e-4,
        "Long must execute at Ask price (2740.20), got {}",
        record.executed_entry
    );

    // Spread cost for 0.10 lot * 0.20 USD * 100 contract_size = $2.00 USD
    assert!(
        (record.spread_cost_usd - 2.00).abs() < 1e-4,
        "Expected trade spread_cost_usd == 2.00, got {}",
        record.spread_cost_usd
    );

    // Summary must report total_spread_cost_usd == 2.00 USD (strictly > 0.0)
    assert!(
        (summary.total_spread_cost_usd - 2.00).abs() < 1e-4,
        "Expected summary.total_spread_cost_usd == 2.00, got {}",
        summary.total_spread_cost_usd
    );

    // Net PnL must equal gross PnL (no double-counting, spread already in Ask entry):
    // PnL = (2745.00 - 2740.20) * 0.10 * 100 = $48.00 USD
    assert!(
        (summary.net_pnl_usd - 48.00).abs() < 1e-4,
        "Expected net_pnl_usd == 48.00, got {}",
        summary.net_pnl_usd
    );

    Ok(())
}

/// Test 7: Short Trade Spread Deduction & Mathematical Symmetry vs Zero-Spread
/// - Validates that Short trades exit at Ask price (Buyback = Bid + spread_usd).
/// - Validates that net_pnl_usd with spread is strictly LESS than without spread (win trade pays spread).
/// - Validates that net_pnl_usd with spread is strictly MORE NEGATIVE on loss trade.
/// - Validates exact mathematical symmetry: profit reduction == record.spread_cost_usd ($2.00).
#[test]
fn test_short_trade_spread_deduction_and_symmetry() -> Result<(), EngineError> {
    let config_with_spread = BacktestConfig {
        default_spread_points: 20.0, // 0.20 USD = 20 points
        ..BacktestConfig::default()
    };
    let config_zero_spread = BacktestConfig {
        default_spread_points: 0.0,
        ..BacktestConfig::default()
    };

    let candles_win = vec![
        make_candle(
            "2026-01-07T10:00:00Z", // Wednesday (midweek)
            2740.00,
            2741.00,
            2739.00,
            2740.50,
            100,
        ), // Opens Short at Bid = 2740.00
        make_candle(
            "2026-01-07T10:01:00Z",
            2739.00,
            2739.50,
            2728.00,
            2729.00,
            120,
        ), // Hits TP 2730.00
    ];

    let short_order_win = vec![Order {
        id: "short-win-1".to_string(),
        direction: Direction::Short,
        execution_type: ExecutionType::Market,
        requested_price: 2740.00,
        lot_size: 0.10,
        sl_price: Some(2750.00),
        tp_price: Some(2730.00),
        signal_timestamp_utc: "2026-01-07T10:00:00Z".to_string(),
        validity_window_seconds: 900,
    }];

    // Run A: With Spread (0.20 USD)
    let (summary_with_spread, records_with_spread, _) = run_backtest(
        &candles_win,
        &short_order_win,
        &config_with_spread,
        10_000.0,
    )?;
    assert_eq!(summary_with_spread.total_trades, 1);
    let record_win = &records_with_spread[0];

    // Short entry at Bid = 2740.00
    assert!(
        (record_win.executed_entry - 2740.00).abs() < 1e-4,
        "Short entry must execute at Bid price 2740.00, got {}",
        record_win.executed_entry
    );

    // Short exit buyback at Ask = 2730.00 + 0.20 = 2730.20
    assert!(
        (record_win.executed_exit - 2730.20).abs() < 1e-4,
        "Short exit buyback must execute at Ask price 2730.20, got {}",
        record_win.executed_exit
    );

    // Spread cost = 0.10 lot * 0.20 USD * 100 contract_size = $2.00 USD
    assert!(
        (record_win.spread_cost_usd - 2.00).abs() < 1e-4,
        "Expected spread_cost_usd == 2.00, got {}",
        record_win.spread_cost_usd
    );

    // Run B: Zero Spread baseline
    let (summary_zero_spread, records_zero_spread, _) = run_backtest(
        &candles_win,
        &short_order_win,
        &config_zero_spread,
        10_000.0,
    )?;
    let record_zero = &records_zero_spread[0];
    assert!(
        (record_zero.executed_exit - 2730.00).abs() < 1e-4,
        "Zero-spread Short exit must be 2730.00, got {}",
        record_zero.executed_exit
    );

    // CRITICAL ASSERTION: Net PnL with spread MUST be strictly less than without spread!
    assert!(
        summary_with_spread.net_pnl_usd < summary_zero_spread.net_pnl_usd,
        "Short trade with spread ({}) must be less profitable than without spread ({})",
        summary_with_spread.net_pnl_usd,
        summary_zero_spread.net_pnl_usd
    );

    // Exact numbers:
    // With spread: (2740.00 - 2730.20) * 0.10 * 100 = $98.00 USD
    // Zero spread: (2740.00 - 2730.00) * 0.10 * 100 = $100.00 USD
    // Difference is exactly $2.00 USD (= spread_cost_usd)
    assert!(
        (summary_with_spread.net_pnl_usd - 98.00).abs() < 1e-4,
        "Expected net_pnl_usd == 98.00 with spread, got {}",
        summary_with_spread.net_pnl_usd
    );
    assert!(
        (summary_zero_spread.net_pnl_usd - 100.00).abs() < 1e-4,
        "Expected net_pnl_usd == 100.00 zero-spread, got {}",
        summary_zero_spread.net_pnl_usd
    );
    assert!(
        ((summary_zero_spread.net_pnl_usd - summary_with_spread.net_pnl_usd) - 2.00).abs() < 1e-4,
        "Expected PnL deduction exactly equals $2.00 spread cost"
    );

    // Now test Short SL Loss scenario:
    let candles_loss = vec![
        make_candle(
            "2026-01-07T10:00:00Z",
            2740.00,
            2741.00,
            2739.00,
            2740.50,
            100,
        ), // Opens Short at Bid = 2740.00
        make_candle(
            "2026-01-07T10:01:00Z",
            2741.00,
            2752.00,
            2740.50,
            2751.00,
            150,
        ), // Hits SL 2750.00
    ];

    let short_order_loss = vec![Order {
        id: "short-loss-1".to_string(),
        direction: Direction::Short,
        execution_type: ExecutionType::Market,
        requested_price: 2740.00,
        lot_size: 0.10,
        sl_price: Some(2750.00),
        tp_price: Some(2730.00),
        signal_timestamp_utc: "2026-01-07T10:00:00Z".to_string(),
        validity_window_seconds: 900,
    }];

    let (loss_summary_with_spread, loss_records_with_spread, _) = run_backtest(
        &candles_loss,
        &short_order_loss,
        &config_with_spread,
        10_000.0,
    )?;
    let (loss_summary_zero_spread, _, _) = run_backtest(
        &candles_loss,
        &short_order_loss,
        &config_zero_spread,
        10_000.0,
    )?;

    // With spread: exit Ask = 2750.20 -> PnL = (2740.00 - 2750.20) * 0.10 * 100 = -$102.00 USD
    // Zero spread: exit Bid = 2750.00 -> PnL = (2740.00 - 2750.00) * 0.10 * 100 = -$100.00 USD
    assert!(
        (loss_records_with_spread[0].executed_exit - 2750.20).abs() < 1e-4,
        "Short SL exit must execute at Ask price 2750.20, got {}",
        loss_records_with_spread[0].executed_exit
    );
    assert!(
        (loss_summary_with_spread.net_pnl_usd - (-102.00)).abs() < 1e-4,
        "Expected loss net_pnl_usd == -102.00 with spread, got {}",
        loss_summary_with_spread.net_pnl_usd
    );
    assert!(
        (loss_summary_zero_spread.net_pnl_usd - (-100.00)).abs() < 1e-4,
        "Expected loss net_pnl_usd == -100.00 zero spread, got {}",
        loss_summary_zero_spread.net_pnl_usd
    );
    assert!(
        loss_summary_with_spread.net_pnl_usd < loss_summary_zero_spread.net_pnl_usd,
        "Loss with spread must be more negative than loss without spread"
    );

    Ok(())
}

/// Test 8: Dynamic US DST Weekly Market Open Hours (Summer 21:00 UTC vs Winter 22:00 UTC)
/// - Validates Summer open (US Daylight Saving Time / EDT): Sunday 21:00 UTC.
/// - Validates Winter open (US Standard Time / EST): Sunday 22:00 UTC.
/// - Validates 3-hour gap rule window across both seasons.
#[test]
fn test_weekly_open_dst_summer_and_winter() -> Result<(), EngineError> {
    // 1. Summer Season: July 2026 (US EDT active)
    // Sunday July 12, 2026: Market opens at 21:00 UTC
    let summer_pre_open = hours_since_weekly_open("2026-07-12T20:59:00Z")?;
    assert!(
        summer_pre_open.abs() < 1e-4,
        "Summer before 21:00 UTC must return 0.0, got {summer_pre_open}"
    );

    let summer_at_open = hours_since_weekly_open("2026-07-12T21:00:00Z")?;
    assert!(
        summer_at_open.abs() < 1e-4,
        "Summer at 21:00 UTC must return 0.0, got {summer_at_open}"
    );

    let summer_1h_in = hours_since_weekly_open("2026-07-12T22:00:00Z")?;
    assert!(
        (summer_1h_in - 1.0).abs() < 1e-4,
        "Summer at 22:00 UTC must return 1.0 hour, got {summer_1h_in}"
    );

    // Monday 00:00 UTC in summer is exactly 3.0 hours (end of gap rule window: 21:00..24:00 = 3h)
    let summer_monday_midnight = hours_since_weekly_open("2026-07-13T00:00:00Z")?;
    assert!(
        (summer_monday_midnight - 3.0).abs() < 1e-4,
        "Summer Monday 00:00 UTC must be exactly 3.0 hours, got {summer_monday_midnight}"
    );

    // 2. Winter Season: January 2026 (US EST active)
    // Sunday January 11, 2026: Market opens at 22:00 UTC
    let winter_pre_open = hours_since_weekly_open("2026-01-11T21:59:00Z")?;
    assert!(
        winter_pre_open.abs() < 1e-4,
        "Winter before 22:00 UTC must return 0.0, got {winter_pre_open}"
    );

    let winter_at_open = hours_since_weekly_open("2026-01-11T22:00:00Z")?;
    assert!(
        winter_at_open.abs() < 1e-4,
        "Winter at 22:00 UTC must return 0.0, got {winter_at_open}"
    );

    let winter_1h_in = hours_since_weekly_open("2026-01-11T23:00:00Z")?;
    assert!(
        (winter_1h_in - 1.0).abs() < 1e-4,
        "Winter at 23:00 UTC must return 1.0 hour, got {winter_1h_in}"
    );

    // Monday 00:00 UTC in winter is 2.0 hours (22:00..24:00 = 2h)
    let winter_monday_midnight = hours_since_weekly_open("2026-01-12T00:00:00Z")?;
    assert!(
        (winter_monday_midnight - 2.0).abs() < 1e-4,
        "Winter Monday 00:00 UTC must be exactly 2.0 hours, got {winter_monday_midnight}"
    );

    // Monday 01:00 UTC in winter is exactly 3.0 hours (end of gap rule window: 22:00..01:00 = 3h)
    let winter_monday_1am = hours_since_weekly_open("2026-01-12T01:00:00Z")?;
    assert!(
        (winter_monday_1am - 3.0).abs() < 1e-4,
        "Winter Monday 01:00 UTC must be exactly 3.0 hours, got {winter_monday_1am}"
    );

    // 3. DST Boundary Transitions in 2026
    // March 2026 transition: 2nd Sunday is March 8, 2026.
    // Before 07:00 UTC on March 8 is Winter (EST), after 07:00 UTC is Summer (EDT).
    // March 8, 2026 21:00 UTC is Summer -> opens at 21:00 UTC -> hours = 0.0
    let march_open = hours_since_weekly_open("2026-03-08T21:00:00Z")?;
    assert!(
        march_open.abs() < 1e-4,
        "March 8, 2026 21:00 UTC (Summer open) must be 0.0, got {march_open}"
    );

    // November 2026 transition: 1st Sunday is Nov 1, 2026.
    // After 06:00 UTC on Nov 1 is Winter (EST).
    // Nov 1, 2026 22:00 UTC is Winter -> opens at 22:00 UTC -> hours = 0.0
    let nov_open = hours_since_weekly_open("2026-11-01T22:00:00Z")?;
    assert!(
        nov_open.abs() < 1e-4,
        "Nov 1, 2026 22:00 UTC (Winter open) must be 0.0, got {nov_open}"
    );

    Ok(())
}

/// Test 9: Orders out-of-chronological order fails fast with calculation error.
#[test]
fn test_orders_out_of_chronological_order_fails_fast() {
    let config = BacktestConfig::default();
    let candles = vec![make_candle(
        "2026-01-01T10:00:00Z",
        2740.0,
        2745.0,
        2735.0,
        2742.0,
        100,
    )];
    let orders = vec![
        Order {
            id: "order-1".to_string(),
            direction: Direction::Long,
            execution_type: ExecutionType::Market,
            requested_price: 2740.0,
            lot_size: 0.1,
            sl_price: Some(2730.0),
            tp_price: Some(2750.0),
            signal_timestamp_utc: "2026-01-01T10:15:00Z".to_string(),
            validity_window_seconds: 900,
        },
        Order {
            id: "order-2".to_string(),
            direction: Direction::Long,
            execution_type: ExecutionType::Market,
            requested_price: 2740.0,
            lot_size: 0.1,
            sl_price: Some(2730.0),
            tp_price: Some(2750.0),
            signal_timestamp_utc: "2026-01-01T10:00:00Z".to_string(),
            validity_window_seconds: 900,
        },
    ];

    let result = run_backtest(&candles, &orders, &config, 10_000.0);
    assert!(result.is_err(), "Expected error for out-of-order orders");
    match result {
        Err(EngineError::CalculationError(msg)) => {
            assert!(
                msg.contains("Orders must be strictly ordered ascending by signal_timestamp_utc"),
                "Expected ascending order error message, got: {msg}"
            );
        }
        other => panic!("Expected EngineError::CalculationError, got: {other:?}"),
    }
}

/// Test 10: Stale order is discarded and queue continues to execute next fresh order on same candle.
#[test]
fn test_queue_continue_stale_discarded_next_fresh_executed() -> Result<(), EngineError> {
    let config = BacktestConfig::default();
    let candles = vec![
        make_candle(
            "2026-01-01T10:30:00Z",
            2740.0,
            2746.0,
            2739.0,
            2745.0,
            100,
        ),
        make_candle(
            "2026-01-01T10:31:00Z",
            2745.0,
            2755.0,
            2744.0,
            2752.0,
            100,
        ), // Hits TP 2750
    ];
    let orders = vec![
        Order {
            id: "order-stale".to_string(),
            direction: Direction::Long,
            execution_type: ExecutionType::Market,
            requested_price: 2740.0,
            lot_size: 0.1,
            sl_price: Some(2730.0),
            tp_price: Some(2750.0),
            signal_timestamp_utc: "2026-01-01T10:00:00Z".to_string(), // 1800s elapsed > 900s
            validity_window_seconds: 900,
        },
        Order {
            id: "order-fresh".to_string(),
            direction: Direction::Long,
            execution_type: ExecutionType::Market,
            requested_price: 2740.0,
            lot_size: 0.1,
            sl_price: Some(2730.0),
            tp_price: Some(2750.0),
            signal_timestamp_utc: "2026-01-01T10:25:00Z".to_string(), // 300s elapsed <= 900s
            validity_window_seconds: 900,
        },
    ];

    let (_summary, audit_records, discarded_orders) =
        run_backtest(&candles, &orders, &config, 10_000.0)?;

    assert_eq!(discarded_orders.len(), 1, "Expected 1 discarded stale order");
    assert_eq!(discarded_orders[0].order_id, "order-stale");
    assert_eq!(discarded_orders[0].reason, "stale_signal_expired");
    assert_eq!(discarded_orders[0].elapsed_seconds, 1800);

    assert_eq!(audit_records.len(), 1, "Expected 1 executed trade from fresh order");
    assert_eq!(audit_records[0].trade_id, "order-fresh");

    Ok(())
}

/// Test 11: Order executed exactly at the validity window boundary (elapsed == 900s).
#[test]
fn test_order_executed_exactly_at_validity_boundary() -> Result<(), EngineError> {
    let config = BacktestConfig::default();
    let candles = vec![
        make_candle(
            "2026-01-01T10:15:00Z",
            2740.0,
            2746.0,
            2739.0,
            2745.0,
            100,
        ),
        make_candle(
            "2026-01-01T10:16:00Z",
            2745.0,
            2755.0,
            2744.0,
            2752.0,
            100,
        ),
    ];
    let orders = vec![Order {
        id: "order-boundary".to_string(),
        direction: Direction::Long,
        execution_type: ExecutionType::Market,
        requested_price: 2740.0,
        lot_size: 0.1,
        sl_price: Some(2730.0),
        tp_price: Some(2750.0),
        signal_timestamp_utc: "2026-01-01T10:00:00Z".to_string(), // 10:15 - 10:00 = 900s exactly == 900s
        validity_window_seconds: 900,
    }];

    let (_summary, audit_records, discarded_orders) =
        run_backtest(&candles, &orders, &config, 10_000.0)?;

    assert_eq!(discarded_orders.len(), 0, "Boundary order must NOT be discarded");
    assert_eq!(audit_records.len(), 1, "Boundary order must be executed");
    assert_eq!(audit_records[0].trade_id, "order-boundary");

    Ok(())
}

/// Test 12: Candle before signal time skips order without discarding; executed when candle reaches signal.
#[test]
fn test_order_not_executed_before_signal_time() -> Result<(), EngineError> {
    let config = BacktestConfig::default();
    let candles = vec![
        make_candle(
            "2026-01-01T09:45:00Z", // Candle before signal (elapsed = -900s)
            2740.0,
            2742.0,
            2738.0,
            2741.0,
            100,
        ),
        make_candle(
            "2026-01-01T10:00:00Z", // Candle at signal (elapsed = 0s) -> opens order
            2740.0,
            2742.0,
            2739.0,
            2741.0,
            100,
        ),
        make_candle(
            "2026-01-01T10:01:00Z", // Candle hits TP 2750
            2741.0,
            2755.0,
            2740.0,
            2752.0,
            100,
        ),
    ];
    let orders = vec![Order {
        id: "order-future".to_string(),
        direction: Direction::Long,
        execution_type: ExecutionType::Market,
        requested_price: 2740.0,
        lot_size: 0.1,
        sl_price: Some(2730.0),
        tp_price: Some(2750.0),
        signal_timestamp_utc: "2026-01-01T10:00:00Z".to_string(),
        validity_window_seconds: 900,
    }];

    let (_summary, audit_records, discarded_orders) =
        run_backtest(&candles, &orders, &config, 10_000.0)?;

    assert!(discarded_orders.is_empty(), "Future order must not be discarded");
    assert_eq!(audit_records.len(), 1, "Order should be executed when candle reached signal time");
    assert_eq!(audit_records[0].trade_id, "order-future");

    Ok(())
}
