use aeterna_backtest::{
    calculate_margin, calculate_pnl, calculate_pnl_with_spread, calculate_spread_cost,
    BacktestConfig, Direction, PnlError,
};

const EPSILON: f64 = 1e-4;

/// Test 1: Skenario Normal LONG 0.05 Lot (GATE-M2-HUMAN Golden Worksheet)
/// Entry: $2,740.20, Exit: $2,745.00, Lot: 0.05, Leverage: 200.0
/// Wajib gross_pnl_usd == 24.00
/// Wajib pnl_pips == 48.0
/// Wajib margin_required_usd == 68.505 (toleransi rounding cent: 68.51)
#[test]
fn test_scenario_normal_long() -> Result<(), PnlError> {
    let config = BacktestConfig {
        leverage: 200.0,
        ..BacktestConfig::default()
    };

    let result = calculate_pnl(Direction::Long, 2740.20, 2745.00, 0.05, &config)?;

    assert!(
        (result.gross_pnl_usd - 24.00).abs() < EPSILON,
        "Expected gross_pnl_usd == 24.00, got {}",
        result.gross_pnl_usd
    );

    assert!(
        (result.pnl_pips - 48.0).abs() < EPSILON,
        "Expected pnl_pips == 48.0, got {}",
        result.pnl_pips
    );

    let margin_exact_match = (result.margin_required_usd - 68.505).abs() < EPSILON;
    let margin_cent_round_match = (result.margin_required_usd - 68.51).abs() < EPSILON;
    assert!(
        margin_exact_match || margin_cent_round_match,
        "Expected margin_required_usd == 68.505 (toleransi rounding cent: 68.51), got {}",
        result.margin_required_usd
    );

    assert!(
        (result.spread_cost_usd - 0.0).abs() < EPSILON,
        "Expected spread_cost_usd == 0.0, got {}",
        result.spread_cost_usd
    );

    assert!(
        (result.net_pnl_usd - 24.00).abs() < EPSILON,
        "Expected net_pnl_usd == 24.00, got {}",
        result.net_pnl_usd
    );

    Ok(())
}

/// Test 2: Skenario Loss SHORT 0.08 Lot (GATE-M2-HUMAN Golden Worksheet)
/// Entry: $2,742.00, Exit: $2,751.50, Lot: 0.08, Leverage: 200.0
/// Wajib gross_pnl_usd == -76.00
/// Wajib pnl_pips == -95.0
#[test]
fn test_scenario_loss_short() -> Result<(), PnlError> {
    let config = BacktestConfig {
        leverage: 200.0,
        ..BacktestConfig::default()
    };

    let result = calculate_pnl(Direction::Short, 2742.00, 2751.50, 0.08, &config)?;

    assert!(
        (result.gross_pnl_usd - (-76.00)).abs() < EPSILON,
        "Expected gross_pnl_usd == -76.00, got {}",
        result.gross_pnl_usd
    );

    assert!(
        (result.pnl_pips - (-95.0)).abs() < EPSILON,
        "Expected pnl_pips == -95.0, got {}",
        result.pnl_pips
    );

    Ok(())
}

/// Test 3: Validasi Parameter Ekstrem
/// Lot size <= 0.0 -> Return Err(PnlError::InvalidLotSize)
/// Leverage <= 0.0 -> Return Err(PnlError::InvalidLeverage)
/// Entry price <= 0.0 atau Exit price <= 0.0 -> Return Err(PnlError::InvalidPrice)
#[test]
fn test_extreme_parameters_validation() {
    let config = BacktestConfig::default();

    // Lot size <= 0.0
    assert_eq!(
        calculate_pnl(Direction::Long, 2740.0, 2745.0, 0.0, &config),
        Err(PnlError::InvalidLotSize)
    );
    assert_eq!(
        calculate_pnl(Direction::Long, 2740.0, 2745.0, -0.05, &config),
        Err(PnlError::InvalidLotSize)
    );
    assert_eq!(
        calculate_pnl(Direction::Long, 2740.0, 2745.0, f64::NAN, &config),
        Err(PnlError::InvalidLotSize)
    );

    // Leverage <= 0.0
    let zero_lev_config = BacktestConfig {
        leverage: 0.0,
        ..config
    };
    assert_eq!(
        calculate_pnl(Direction::Long, 2740.0, 2745.0, 0.05, &zero_lev_config),
        Err(PnlError::InvalidLeverage)
    );
    let neg_lev_config = BacktestConfig {
        leverage: -100.0,
        ..config
    };
    assert_eq!(
        calculate_pnl(Direction::Long, 2740.0, 2745.0, 0.05, &neg_lev_config),
        Err(PnlError::InvalidLeverage)
    );

    // Entry price <= 0.0
    assert_eq!(
        calculate_pnl(Direction::Long, 0.0, 2745.0, 0.05, &config),
        Err(PnlError::InvalidPrice)
    );
    assert_eq!(
        calculate_pnl(Direction::Long, -2740.0, 2745.0, 0.05, &config),
        Err(PnlError::InvalidPrice)
    );

    // Exit price <= 0.0
    assert_eq!(
        calculate_pnl(Direction::Long, 2740.0, 0.0, 0.05, &config),
        Err(PnlError::InvalidPrice)
    );
    assert_eq!(
        calculate_pnl(Direction::Long, 2740.0, -10.0, 0.05, &config),
        Err(PnlError::InvalidPrice)
    );
}

#[test]
fn test_margin_and_spread_isolated_functions() -> Result<(), PnlError> {
    let config = BacktestConfig::default();

    // calculate_margin(0.05, 2740.20, config)
    let margin = calculate_margin(0.05, 2740.20, &config)?;
    assert!((margin - 68.505).abs() < EPSILON);

    // calculate_spread_cost(0.05, 0.15, config)
    // 0.15 USD * 0.05 lot * 100 contract_size = 0.75 USD
    let spread = calculate_spread_cost(0.05, 0.15, &config)?;
    assert!((spread - 0.75).abs() < EPSILON);

    // calculate_pnl_with_spread
    let res = calculate_pnl_with_spread(Direction::Long, 2740.20, 2745.00, 0.05, 0.15, &config)?;
    assert!((res.gross_pnl_usd - 24.00).abs() < EPSILON);
    assert!((res.spread_cost_usd - 0.75).abs() < EPSILON);
    assert!((res.net_pnl_usd - (24.00 - 0.75)).abs() < EPSILON);

    Ok(())
}
