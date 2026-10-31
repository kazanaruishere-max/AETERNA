//! Core Backtest Engine Simulation Loop (`engine.rs`).
//!
//! Provides step-by-step chronological simulation per M1 candle, managing active
//! positions, checking SL/TP with broker slippage rules, and aggregating performance metrics.

use crate::audit::create_audit_record;
use crate::exness_rules::{apply_slippage_free_range, validate_order_stop_level};
use crate::pnl::calculate_margin;
use crate::types::{
    BacktestConfig, BacktestSummary, Candle, Direction, EngineError, ExecutionAuditRecord,
    ExecutionPriceResult, Order,
};

/// Internal tracking state for an open position during simulation.
#[derive(Debug, Clone, PartialEq)]
struct ActivePosition {
    order: Order,
    entry_exec: ExecutionPriceResult,
}

/// Validates whether a [`Candle`] satisfies price consistency and positive/finite rules.
fn validate_candle(candle: &Candle) -> Result<(), EngineError> {
    if !candle.open.is_finite()
        || candle.open <= 0.0
        || !candle.high.is_finite()
        || candle.high <= 0.0
        || !candle.low.is_finite()
        || candle.low <= 0.0
        || !candle.close.is_finite()
        || candle.close <= 0.0
        || candle.high < candle.low
        || candle.high < candle.open
        || candle.high < candle.close
        || candle.low > candle.open
        || candle.low > candle.close
    {
        return Err(EngineError::InvalidCandleData);
    }
    Ok(())
}

/// Runs a deterministic backtest simulation loop over chronological M1 candles.
///
/// # Simulation Flow (Per Candle)
/// 1. If an active position exists:
///    - Evaluates SL and TP touches against `candle.high` and `candle.low`.
///    - If both SL and TP are touched in the same bar, SL is treated as touched first
///      for conservative risk management.
///    - Applies Exness broker execution rules (slippage-free range) to determine executed exit price.
///    - If closed, records [`ExecutionAuditRecord`] and updates balance curve.
/// 2. If no position is active and pending orders remain:
///    - Validates order minimum stop level requirement.
///    - Validates margin requirement against `current_balance`.
///    - Opens new active position with execution price of the current candle.
/// 3. Computes final performance metrics into [`BacktestSummary`].
///
/// # Errors
/// Returns [`EngineError`] if candle data is invalid, initial balance is invalid,
/// or broker calculation errors occur.
pub fn run_backtest(
    candles: &[Candle],
    orders: &[Order],
    config: &BacktestConfig,
    initial_balance: f64,
) -> Result<(BacktestSummary, Vec<ExecutionAuditRecord>), EngineError> {
    if !initial_balance.is_finite() || initial_balance <= 0.0 {
        return Err(EngineError::CalculationError(
            "Initial balance must be positive and finite".to_string(),
        ));
    }

    // 1. Validate all candles first
    for candle in candles {
        validate_candle(candle)?;
    }

    let mut current_balance = initial_balance;
    let mut peak_balance = initial_balance;
    let mut max_drawdown_usd = 0.0;
    let mut max_drawdown_pct = 0.0;

    let mut active_position: Option<ActivePosition> = None;
    let mut order_idx = 0;
    let mut audit_records: Vec<ExecutionAuditRecord> = Vec::new();

    let mut win_trades = 0;
    let mut loss_trades = 0;
    let mut gross_profit_usd = 0.0;
    let mut gross_loss_usd = 0.0;
    let mut total_spread_cost_usd = 0.0;
    let mut total_slippage_cost_usd = 0.0;

    for candle in candles {
        let mut position_closed_this_bar = false;
        // Step 1 & 2: Check SL and TP for active position
        if let Some(pos) = active_position.take() {
            let mut closed = false;
            let mut requested_exit = 0.0;
            let mut exit_exec = ExecutionPriceResult {
                executed_price: 0.0,
                slippage_usd: 0.0,
                slippage_points: 0.0,
            };

            match pos.order.direction {
                Direction::Long => {
                    let sl_hit = pos.order.sl_price.is_some_and(|sl| candle.low <= sl);
                    let tp_hit = pos.order.tp_price.is_some_and(|tp| candle.high >= tp);

                    // Conservative assumption: if both SL and TP are hit, SL is evaluated first
                    if sl_hit {
                        let sl = pos.order.sl_price.unwrap_or(0.0);
                        let market_price = if candle.high < sl { candle.high } else { sl };
                        requested_exit = sl;
                        exit_exec = apply_slippage_free_range(sl, market_price, config);
                        closed = true;
                    } else if tp_hit {
                        let tp = pos.order.tp_price.unwrap_or(0.0);
                        let market_price = if candle.low > tp { candle.low } else { tp };
                        requested_exit = tp;
                        exit_exec = apply_slippage_free_range(tp, market_price, config);
                        closed = true;
                    }
                }
                Direction::Short => {
                    let sl_hit = pos.order.sl_price.is_some_and(|sl| candle.high >= sl);
                    let tp_hit = pos.order.tp_price.is_some_and(|tp| candle.low <= tp);

                    // Conservative assumption: if both SL and TP are hit, SL is evaluated first
                    if sl_hit {
                        let sl = pos.order.sl_price.unwrap_or(0.0);
                        let market_price = if candle.low > sl { candle.low } else { sl };
                        requested_exit = sl;
                        exit_exec = apply_slippage_free_range(sl, market_price, config);
                        closed = true;
                    } else if tp_hit {
                        let tp = pos.order.tp_price.unwrap_or(0.0);
                        let market_price = if candle.high < tp { candle.high } else { tp };
                        requested_exit = tp;
                        exit_exec = apply_slippage_free_range(tp, market_price, config);
                        closed = true;
                    }
                }
            }

            if closed {
                // Zero commission Exness Standard: spread is already reflected in executed market prices
                let spread_usd = 0.0;
                let stop_level_checked = true;
                let gap_rule_applied = false;

                let record = create_audit_record(
                    pos.order.id.clone(),
                    pos.order.direction,
                    pos.order.lot_size,
                    pos.order.requested_price,
                    pos.entry_exec,
                    requested_exit,
                    exit_exec,
                    spread_usd,
                    stop_level_checked,
                    gap_rule_applied,
                    config,
                )?;

                current_balance += record.net_pnl_usd;
                if current_balance > peak_balance {
                    peak_balance = current_balance;
                }
                let dd_usd = peak_balance - current_balance;
                if dd_usd > max_drawdown_usd {
                    max_drawdown_usd = dd_usd;
                }
                let dd_pct = if peak_balance > 0.0 {
                    (peak_balance - current_balance) / peak_balance * 100.0
                } else {
                    0.0
                };
                if dd_pct > max_drawdown_pct {
                    max_drawdown_pct = dd_pct;
                }

                if record.net_pnl_usd > 0.0 {
                    win_trades += 1;
                    gross_profit_usd += record.net_pnl_usd;
                } else if record.net_pnl_usd < 0.0 {
                    loss_trades += 1;
                    gross_loss_usd += record.net_pnl_usd.abs();
                }

                total_spread_cost_usd += record.spread_cost_usd;
                let slippage_cost = (record.slippage_entry_usd.abs()
                    + record.slippage_exit_usd.abs())
                    * record.lot_size
                    * config.contract_size;
                total_slippage_cost_usd += slippage_cost;

                audit_records.push(record);
                position_closed_this_bar = true;
            } else {
                active_position = Some(pos);
            }
        }

        // Step 4: Open new order from queue if no active position
        if !position_closed_this_bar && active_position.is_none() && order_idx < orders.len() {
            let order = &orders[order_idx];
            validate_order_stop_level(order, config)?;

            let entry_exec = apply_slippage_free_range(order.requested_price, candle.open, config);
            let margin_required =
                calculate_margin(order.lot_size, entry_exec.executed_price, config)?;

            if current_balance >= margin_required {
                active_position = Some(ActivePosition {
                    order: order.clone(),
                    entry_exec,
                });
                order_idx += 1;
            }
        }
    }

    let total_trades = audit_records.len();
    let net_pnl_usd = audit_records
        .iter()
        .map(|record| record.net_pnl_usd)
        .sum::<f64>();

    let profit_factor = if gross_loss_usd > 0.0 {
        gross_profit_usd / gross_loss_usd
    } else if gross_profit_usd > 0.0 {
        f64::INFINITY
    } else {
        0.0
    };

    let summary = BacktestSummary {
        total_trades,
        win_trades,
        loss_trades,
        gross_profit_usd,
        gross_loss_usd,
        net_pnl_usd,
        profit_factor,
        max_drawdown_usd,
        max_drawdown_pct,
        total_spread_cost_usd,
        total_slippage_cost_usd,
    };

    Ok((summary, audit_records))
}
