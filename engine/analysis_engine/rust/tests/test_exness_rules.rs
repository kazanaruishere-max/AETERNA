use aeterna_backtest::{
    apply_slippage_free_range, apply_weekly_gap_rule, calculate_pnl_with_spread,
    create_audit_record, validate_order_stop_level, validate_stop_level, AuditLedger,
    BacktestConfig, BrokerRuleError, Direction, ExecutionPriceResult, ExecutionType, Order,
};

const EPSILON: f64 = 1e-4;

/// Test 1: Stop Level Rejection & Acceptance (`REQ-BKT-003`).
/// - Entry $2,740.00, SL $2,738.00 (distance $2.00 / 200 points) -> Wajib Err(BrokerRuleError::StopLevelViolation).
/// - Entry $2,740.00, SL $2,736.00 (distance $4.00 / 400 points) -> Wajib Ok(()).
/// - Dynamic config injection test: custom stop_level_points.
#[test]
fn test_stop_level_validation() -> Result<(), BrokerRuleError> {
    let config = BacktestConfig::default(); // default stop_level_points: 300.0, point_size: 0.01 ($3.00)

    // Rejection: distance $2.00 (200 points) < 300 points
    let res_reject = validate_stop_level(2740.00, Some(2738.00), None, &config);
    assert_eq!(
        res_reject,
        Err(BrokerRuleError::StopLevelViolation),
        "Expected StopLevelViolation for SL distance of 200 points"
    );

    // Acceptance: distance $4.00 (400 points) >= 300 points
    validate_stop_level(2740.00, Some(2736.00), None, &config)?;

    // TP rejection: distance $2.00 (200 points) < 300 points
    let res_tp_reject = validate_stop_level(2740.00, None, Some(2742.00), &config);
    assert_eq!(
        res_tp_reject,
        Err(BrokerRuleError::StopLevelViolation),
        "Expected StopLevelViolation for TP distance of 200 points"
    );

    // TP acceptance: distance $5.00 (500 points) >= 300 points
    validate_stop_level(2740.00, None, Some(2745.00), &config)?;

    // Both SL and TP valid
    validate_stop_level(2740.00, Some(2735.00), Some(2745.00), &config)?;

    // Dynamic config injection: relax stop_level_points to 100.0 ($1.00)
    let relaxed_config = BacktestConfig {
        stop_level_points: 100.0,
        ..BacktestConfig::default()
    };
    validate_stop_level(2740.00, Some(2738.00), None, &relaxed_config)?;

    // Invalid prices validation
    assert_eq!(
        validate_stop_level(0.0, Some(2738.00), None, &config),
        Err(BrokerRuleError::InvalidPrice)
    );
    assert_eq!(
        validate_stop_level(2740.00, Some(-10.0), None, &config),
        Err(BrokerRuleError::InvalidPrice)
    );

    Ok(())
}

/// Test 2: Slippage-Free Range Execution (`REQ-BKT-002`).
/// - Request $2,740.00, Market $2,740.10 (diff 10 points < 15 points) -> Executed: $2,740.00 (Zero slippage).
/// - Request $2,740.00, Market $2,740.25 (diff 25 points >= 15 points) -> Executed: $2,740.25 (Slippage +$0.25).
/// - Dynamic config injection: custom slippage_free_points.
#[test]
fn test_slippage_free_range() {
    let config = BacktestConfig::default(); // slippage_free_points: 15.0 ($0.15), point_size: 0.01

    // Within slippage-free range: 10 points < 15 points
    let res1 = apply_slippage_free_range(2740.00, 2740.10, &config);
    assert!(
        (res1.executed_price - 2740.00).abs() < EPSILON,
        "Expected executed_price == 2740.00, got {}",
        res1.executed_price
    );
    assert!(
        res1.slippage_usd.abs() < EPSILON,
        "Expected zero slippage_usd, got {}",
        res1.slippage_usd
    );
    assert!(
        res1.slippage_points.abs() < EPSILON,
        "Expected zero slippage_points, got {}",
        res1.slippage_points
    );

    // Beyond slippage-free range (positive slippage): 25 points >= 15 points
    let res2 = apply_slippage_free_range(2740.00, 2740.25, &config);
    assert!(
        (res2.executed_price - 2740.25).abs() < EPSILON,
        "Expected executed_price == 2740.25, got {}",
        res2.executed_price
    );
    assert!(
        (res2.slippage_usd - 0.25).abs() < EPSILON,
        "Expected slippage_usd == 0.25, got {}",
        res2.slippage_usd
    );
    assert!(
        (res2.slippage_points - 25.0).abs() < EPSILON,
        "Expected slippage_points == 25.0, got {}",
        res2.slippage_points
    );

    // Beyond slippage-free range (negative slippage): Market drops to 2739.75 (diff 25 points)
    let res3 = apply_slippage_free_range(2740.00, 2739.75, &config);
    assert!(
        (res3.executed_price - 2739.75).abs() < EPSILON,
        "Expected executed_price == 2739.75, got {}",
        res3.executed_price
    );
    assert!(
        (res3.slippage_usd - (-0.25)).abs() < EPSILON,
        "Expected slippage_usd == -0.25, got {}",
        res3.slippage_usd
    );

    // Dynamic config injection: widen slippage_free_points to 30.0
    let wide_config = BacktestConfig {
        slippage_free_points: 30.0,
        ..BacktestConfig::default()
    };
    let res_wide = apply_slippage_free_range(2740.00, 2740.25, &wide_config);
    assert!(
        (res_wide.executed_price - 2740.00).abs() < EPSILON,
        "Expected zero slippage with slippage_free_points = 30.0, got {}",
        res_wide.executed_price
    );
    assert!(
        res_wide.slippage_usd.abs() < EPSILON,
        "Expected zero slippage_usd with slippage_free_points = 30.0, got {}",
        res_wide.slippage_usd
    );
}

/// Test 3: Weekly Market Open Gap Rule (`REQ-BKT-004`).
/// - Pending Buy $2,735.00, Market buka di $2,742.00 (jam ke-1.5 pasca buka) -> Executed di $2,742.00.
/// - During first 3 hours (< 3.0), slippage-free protection is disabled.
/// - After 3 hours (>= 3.0), slippage-free protection resumes.
#[test]
fn test_gap_rule() {
    let config = BacktestConfig::default();

    // Case 1: Gap skip at hour 1.5 (< 3.0) -> executed at market_open_price $2,742.00
    let res_gap = apply_weekly_gap_rule(2735.00, 2742.00, 1.5, &config);
    assert!(
        (res_gap.executed_price - 2742.00).abs() < EPSILON,
        "Expected executed_price == 2742.00, got {}",
        res_gap.executed_price
    );
    assert!(
        (res_gap.slippage_usd - 7.00).abs() < EPSILON,
        "Expected slippage_usd == 7.00, got {}",
        res_gap.slippage_usd
    );
    assert!(
        (res_gap.slippage_points - 700.0).abs() < EPSILON,
        "Expected slippage_points == 700.0, got {}",
        res_gap.slippage_points
    );

    // Case 2: Small difference at hour 1.0 (< 3.0) where slippage-free is disabled
    let res_small_gap = apply_weekly_gap_rule(2740.00, 2740.10, 1.0, &config);
    assert!(
        (res_small_gap.executed_price - 2740.10).abs() < EPSILON,
        "Expected executed_price == 2740.10 because slippage-free is disabled during gap window, got {}",
        res_small_gap.executed_price
    );
    assert!(
        (res_small_gap.slippage_usd - 0.10).abs() < EPSILON,
        "Expected slippage_usd == 0.10, got {}",
        res_small_gap.slippage_usd
    );

    // Case 3: Hour 3.5 (>= 3.0) -> Normal slippage-free rules resume
    let res_normal = apply_weekly_gap_rule(2740.00, 2740.10, 3.5, &config);
    assert!(
        (res_normal.executed_price - 2740.00).abs() < EPSILON,
        "Expected executed_price == 2740.00 after 3.0 hours (zero slippage), got {}",
        res_normal.executed_price
    );
    assert!(
        res_normal.slippage_usd.abs() < EPSILON,
        "Expected slippage_usd == 0.0 after 3.0 hours, got {}",
        res_normal.slippage_usd
    );
}

/// Test 4: Audit Record Generator & Ledger (`GATE-M2-HUMAN` & `audit.rs`).
/// - Verifikasi pembentukan ExecutionAuditRecord memuat nilai PnL dan Margin yang konsisten dengan modul pnl.rs.
#[test]
fn test_audit_record_generator_and_ledger() -> Result<(), BrokerRuleError> {
    let config = BacktestConfig {
        leverage: 200.0,
        ..BacktestConfig::default()
    };

    // Calculate baseline directly with pnl.rs
    let expected_pnl =
        calculate_pnl_with_spread(Direction::Long, 2740.20, 2745.00, 0.05, 0.0, &config)?;

    // Execution with slippage: requested 2740.00, executed 2740.20
    let entry_exec = ExecutionPriceResult {
        executed_price: 2740.20,
        slippage_usd: 0.20,
        slippage_points: 20.0,
    };
    let exit_exec = ExecutionPriceResult {
        executed_price: 2745.00,
        slippage_usd: 0.0,
        slippage_points: 0.0,
    };

    let record = create_audit_record(
        "TRADE-XAUUSD-001",
        Direction::Long,
        0.05,
        2740.00,
        entry_exec,
        2745.00,
        exit_exec,
        0.0,
        true,
        false,
        &config,
    )?;

    // Mathematical parity verification with pnl.rs
    assert!(
        (record.gross_pnl_usd - expected_pnl.gross_pnl_usd).abs() < EPSILON,
        "Expected gross_pnl_usd == {}, got {}",
        expected_pnl.gross_pnl_usd,
        record.gross_pnl_usd
    );
    assert!(
        (record.pnl_pips - expected_pnl.pnl_pips).abs() < EPSILON,
        "Expected pnl_pips == {}, got {}",
        expected_pnl.pnl_pips,
        record.pnl_pips
    );
    assert!(
        (record.margin_required_usd - expected_pnl.margin_required_usd).abs() < EPSILON,
        "Expected margin_required_usd == {}, got {}",
        expected_pnl.margin_required_usd,
        record.margin_required_usd
    );
    assert!(
        (record.spread_cost_usd - expected_pnl.spread_cost_usd).abs() < EPSILON,
        "Expected spread_cost_usd == {}, got {}",
        expected_pnl.spread_cost_usd,
        record.spread_cost_usd
    );
    assert!(
        (record.net_pnl_usd - expected_pnl.net_pnl_usd).abs() < EPSILON,
        "Expected net_pnl_usd == {}, got {}",
        expected_pnl.net_pnl_usd,
        record.net_pnl_usd
    );

    // Audit trace fields verification
    assert_eq!(record.trade_id, "TRADE-XAUUSD-001");
    assert_eq!(record.direction, Direction::Long);
    assert!((record.requested_entry - 2740.00).abs() < EPSILON);
    assert!((record.executed_entry - 2740.20).abs() < EPSILON);
    assert!((record.slippage_entry_usd - 0.20).abs() < EPSILON);
    assert!((record.requested_exit - 2745.00).abs() < EPSILON);
    assert!((record.executed_exit - 2745.00).abs() < EPSILON);
    assert!(record.slippage_exit_usd.abs() < EPSILON);
    assert!(record.stop_level_checked);
    assert!(!record.gap_rule_applied);

    // AuditLedger tracking verification
    let mut ledger = AuditLedger::new();
    assert!(ledger.is_empty());
    assert_eq!(ledger.len(), 0);

    ledger.record(record.clone());
    assert_eq!(ledger.len(), 1);
    assert!(!ledger.is_empty());

    assert!(
        (ledger.total_net_pnl() - record.net_pnl_usd).abs() < EPSILON,
        "Expected total net PnL {}, got {}",
        record.net_pnl_usd,
        ledger.total_net_pnl()
    );
    assert!(
        (ledger.total_slippage_usd() - 0.20).abs() < EPSILON,
        "Expected total slippage 0.20, got {}",
        ledger.total_slippage_usd()
    );

    Ok(())
}

/// Test 5: Order struct and validate_order_stop_level helper.
#[test]
fn test_order_and_stop_level_helper() -> Result<(), BrokerRuleError> {
    let config = BacktestConfig::default();

    let valid_order = Order {
        id: "ORD-001".to_string(),
        direction: Direction::Long,
        execution_type: ExecutionType::Market,
        requested_price: 2740.00,
        lot_size: 0.10,
        sl_price: Some(2735.00),
        tp_price: Some(2750.00),
    };
    validate_order_stop_level(&valid_order, &config)?;

    let invalid_order = Order {
        id: "ORD-002".to_string(),
        direction: Direction::Long,
        execution_type: ExecutionType::Limit,
        requested_price: 2740.00,
        lot_size: 0.10,
        sl_price: Some(2739.00), // distance $1.00 < $3.00
        tp_price: Some(2750.00),
    };
    assert_eq!(
        validate_order_stop_level(&invalid_order, &config),
        Err(BrokerRuleError::StopLevelViolation)
    );

    Ok(())
}
