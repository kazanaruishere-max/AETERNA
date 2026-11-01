//! Core Backtest Engine Simulation Loop (`engine.rs`).
//!
//! Provides step-by-step chronological simulation per M1 candle, managing active
//! positions, checking SL/TP with broker slippage rules, and aggregating performance metrics.

use chrono::{DateTime, Datelike, NaiveDate, Timelike, Utc, Weekday};

use crate::audit::create_audit_record;
use crate::exness_rules::{
    apply_slippage_free_range, apply_weekly_gap_rule, validate_order_stop_level,
};
use crate::pnl::calculate_margin;
use crate::types::{
    BacktestConfig, BacktestSummary, Candle, Direction, DiscardedOrderRecord, EngineError,
    ExecutionAuditRecord, ExecutionPriceResult, Order,
};

/// Helper to parse ISO-8601 / RFC3339 UTC timestamp.
fn parse_utc_timestamp(timestamp_utc: &str) -> Result<DateTime<Utc>, EngineError> {
    if let Ok(dt) = DateTime::parse_from_rfc3339(timestamp_utc) {
        return Ok(dt.with_timezone(&Utc));
    }
    if let Ok(dt) = DateTime::parse_from_str(timestamp_utc, "%Y-%m-%dT%H:%M:%SZ") {
        return Ok(dt.with_timezone(&Utc));
    }
    if let Ok(naive) = chrono::NaiveDateTime::parse_from_str(timestamp_utc, "%Y-%m-%dT%H:%M:%S") {
        return Ok(DateTime::<Utc>::from_naive_utc_and_offset(naive, Utc));
    }
    if let Ok(naive) = chrono::NaiveDateTime::parse_from_str(timestamp_utc, "%Y-%m-%d %H:%M:%S") {
        return Ok(DateTime::<Utc>::from_naive_utc_and_offset(naive, Utc));
    }
    Err(EngineError::CalculationError(format!(
        "Invalid timestamp format: {timestamp_utc}"
    )))
}
/// Internal tracking state for an open position during simulation.
#[derive(Debug, Clone, PartialEq)]
struct ActivePosition {
    order: Order,
    entry_exec: ExecutionPriceResult,
    spread_usd: f64,
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

/// Helper function to find the day of the month for the N-th Sunday (1-based index).
fn find_nth_sunday(year: i32, month: u32, n: u32) -> u32 {
    let mut count = 0;
    for day in 1..=31 {
        if let Some(date) = NaiveDate::from_ymd_opt(year, month, day) {
            if date.weekday() == Weekday::Sun {
                count += 1;
                if count == n {
                    return day;
                }
            }
        }
    }
    if n == 1 {
        1
    } else {
        8
    }
}

/// Determines whether a given UTC timestamp falls within US Daylight Saving Time (EDT, UTC-4).
///
/// Under the US Energy Policy Act of 2005:
/// - Starts: Second Sunday in March at 02:00 EST (07:00 UTC).
/// - Ends: First Sunday in November at 02:00 EDT (06:00 UTC).
pub fn is_us_daylight_saving(dt: &chrono::DateTime<chrono::FixedOffset>) -> bool {
    let year = dt.year();
    let month = dt.month();

    if !(3..=11).contains(&month) {
        return false;
    }
    if (4..=10).contains(&month) {
        return true;
    }

    if month == 3 {
        let second_sunday_day = find_nth_sunday(year, 3, 2);
        if let Some(trans_date) = NaiveDate::from_ymd_opt(year, 3, second_sunday_day) {
            if let Some(trans_dt) = trans_date.and_hms_opt(7, 0, 0) {
                return dt.naive_utc() >= trans_dt;
            }
        }
        false
    } else {
        // month == 11
        let first_sunday_day = find_nth_sunday(year, 11, 1);
        if let Some(trans_date) = NaiveDate::from_ymd_opt(year, 11, first_sunday_day) {
            if let Some(trans_dt) = trans_date.and_hms_opt(6, 0, 0) {
                return dt.naive_utc() < trans_dt;
            }
        }
        false
    }
}

/// Calculates hours elapsed since the weekly market open with dynamic US DST adjustment.
///
/// Exness market opens on Sunday afternoon:
/// - Summer (US Daylight Saving Time / EDT): Sunday 21:00 UTC
/// - Winter (US Standard Time / EST): Sunday 22:00 UTC
///
/// Returns elapsed hours since weekly open.
pub fn hours_since_weekly_open(timestamp_utc: &str) -> Result<f64, EngineError> {
    let dt = chrono::DateTime::parse_from_rfc3339(timestamp_utc)
        .or_else(|_| chrono::DateTime::parse_from_str(timestamp_utc, "%Y-%m-%dT%H:%M:%SZ"))
        .map_err(|e| EngineError::CalculationError(format!("Invalid timestamp format: {e}")))?;

    let is_summer = is_us_daylight_saving(&dt);
    let open_hour = if is_summer { 21 } else { 22 };
    let sunday_hours = (24 - open_hour) as f64; // Summer: 3.0h (21..24), Winter: 2.0h (22..24)

    let weekday = dt.weekday();
    let hour = dt.hour();
    let minute = dt.minute();
    let second = dt.second();
    let time_fraction = (minute as f64 * 60.0 + second as f64) / 3600.0;

    match weekday {
        Weekday::Sun => {
            if hour >= open_hour {
                Ok((hour - open_hour) as f64 + time_fraction)
            } else {
                Ok(0.0)
            }
        }
        Weekday::Mon => Ok(sunday_hours + (hour as f64) + time_fraction),
        Weekday::Tue => Ok(sunday_hours + 24.0 + (hour as f64) + time_fraction),
        Weekday::Wed => Ok(sunday_hours + 48.0 + (hour as f64) + time_fraction),
        Weekday::Thu => Ok(sunday_hours + 72.0 + (hour as f64) + time_fraction),
        Weekday::Fri => Ok(sunday_hours + 96.0 + (hour as f64) + time_fraction),
        Weekday::Sat => Ok(sunday_hours + 120.0 + (hour as f64) + time_fraction),
    }
}

/// Runs a deterministic backtest simulation loop over chronological M1 candles.
///
/// # Simulation Flow (Per Candle)
/// 1. If an active position exists:
///    - Evaluates SL and TP touches against `candle.high` and `candle.low`.
///    - If both SL and TP are touched in the same bar, SL is treated as touched first
///      for conservative risk management.
///    - Evaluates weekly open gap rule (`hours_since_open < 3.0`) vs normal slippage-free range.
///    - If closed, records [`ExecutionAuditRecord`] and updates balance curve.
/// 2. If no position is active and pending orders remain:
///    - Validates order minimum stop level requirement.
///    - Applies spread approximation: Long enters at Ask (`open + spread`), Short enters at Bid (`open`).
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
) -> Result<(BacktestSummary, Vec<ExecutionAuditRecord>, Vec<DiscardedOrderRecord>), EngineError> {
    if !initial_balance.is_finite() || initial_balance <= 0.0 {
        return Err(EngineError::CalculationError(
            "Initial balance must be positive and finite".to_string(),
        ));
    }

    // 1. Validate all candles first
    for candle in candles {
        validate_candle(candle)?;
    }
    for w in candles.windows(2) {
        let prev_dt = parse_utc_timestamp(&w[0].timestamp_utc)?;
        let curr_dt = parse_utc_timestamp(&w[1].timestamp_utc)?;
        if curr_dt < prev_dt {
            return Err(EngineError::CalculationError(format!(
                "Candles must be strictly non-decreasing in time: {} < {}",
                w[1].timestamp_utc, w[0].timestamp_utc
            )));
        }
    }

    // 2. Validate ascending orders
    for order in orders {
        parse_utc_timestamp(&order.signal_timestamp_utc)?;
    }
    for w in orders.windows(2) {
        let prev_dt = parse_utc_timestamp(&w[0].signal_timestamp_utc)?;
        let curr_dt = parse_utc_timestamp(&w[1].signal_timestamp_utc)?;
        if curr_dt < prev_dt {
            return Err(EngineError::CalculationError(format!(
                "Orders must be strictly ordered ascending by signal_timestamp_utc: {} < {}",
                w[1].signal_timestamp_utc, w[0].signal_timestamp_utc
            )));
        }
    }
    let mut current_balance = initial_balance;
    let mut peak_balance = initial_balance;
    let mut max_drawdown_usd = 0.0;
    let mut max_drawdown_pct = 0.0;

    let mut active_position: Option<ActivePosition> = None;
    let mut order_idx = 0;
    let mut audit_records: Vec<ExecutionAuditRecord> = Vec::new();
    let mut discarded_orders: Vec<DiscardedOrderRecord> = Vec::new();

    let mut win_trades = 0;
    let mut loss_trades = 0;
    let mut gross_profit_usd = 0.0;
    let mut gross_loss_usd = 0.0;
    let mut total_spread_cost_usd = 0.0;
    let mut total_slippage_cost_usd = 0.0;

    let spread_usd = config.default_spread_points * config.point_size;

    for candle in candles {
        let candle_dt = parse_utc_timestamp(&candle.timestamp_utc)?;
        let mut position_closed_this_bar = false;
        let hours_since_open = hours_since_weekly_open(&candle.timestamp_utc)?;
        let in_gap_window = hours_since_open < 3.0;

        // Step 1 & 2: Check SL and TP for active position
        if let Some(pos) = active_position.take() {
            let mut closed = false;
            let mut requested_exit = 0.0;
            let mut exit_exec = ExecutionPriceResult {
                executed_price: 0.0,
                slippage_usd: 0.0,
                slippage_points: 0.0,
            };
            let mut gap_rule_applied = false;

            match pos.order.direction {
                Direction::Long => {
                    let sl_hit = pos.order.sl_price.is_some_and(|sl| candle.low <= sl);
                    let tp_hit = pos.order.tp_price.is_some_and(|tp| candle.high >= tp);

                    // Conservative assumption: if both SL and TP are hit, SL is evaluated first
                    if sl_hit {
                        let sl = pos.order.sl_price.unwrap_or(0.0);
                        requested_exit = sl;
                        // Gap occurs if bar opened below SL; otherwise filled at SL in continuous trading
                        if candle.open < sl {
                            let is_gap = (sl - candle.open).abs() > 1e-7;
                            if in_gap_window && is_gap {
                                exit_exec = apply_weekly_gap_rule(
                                    sl,
                                    candle.open,
                                    hours_since_open,
                                    config,
                                );
                                gap_rule_applied = true;
                            } else {
                                exit_exec = apply_slippage_free_range(sl, candle.open, config);
                            }
                        } else {
                            exit_exec = ExecutionPriceResult {
                                executed_price: sl,
                                slippage_usd: 0.0,
                                slippage_points: 0.0,
                            };
                        }
                        closed = true;
                    } else if tp_hit {
                        let tp = pos.order.tp_price.unwrap_or(0.0);
                        requested_exit = tp;
                        // Gap occurs if bar opened above TP; otherwise filled at TP in continuous trading
                        if candle.open > tp {
                            let is_gap = (candle.open - tp).abs() > 1e-7;
                            if in_gap_window && is_gap {
                                exit_exec = apply_weekly_gap_rule(
                                    tp,
                                    candle.open,
                                    hours_since_open,
                                    config,
                                );
                                gap_rule_applied = true;
                            } else {
                                exit_exec = apply_slippage_free_range(tp, candle.open, config);
                            }
                        } else {
                            exit_exec = ExecutionPriceResult {
                                executed_price: tp,
                                slippage_usd: 0.0,
                                slippage_points: 0.0,
                            };
                        }
                        closed = true;
                    }
                }
                Direction::Short => {
                    let sl_hit = pos.order.sl_price.is_some_and(|sl| candle.high >= sl);
                    let tp_hit = pos.order.tp_price.is_some_and(|tp| candle.low <= tp);

                    // Conservative assumption: if both SL and TP are hit, SL is evaluated first
                    if sl_hit {
                        let sl = pos.order.sl_price.unwrap_or(0.0);
                        // Short exits by buying back at Ask price (market_exit = candle.open + spread_usd).
                        // Target exit price at Ask is sl + spread_usd.
                        let target_exit = sl + spread_usd;
                        let market_exit = candle.open + spread_usd;
                        requested_exit = target_exit;

                        // Gap occurs if bar opened above SL (candle.open > sl); otherwise filled at target_exit in continuous trading
                        if candle.open > sl {
                            let is_gap = (candle.open - sl).abs() > 1e-7;
                            if in_gap_window && is_gap {
                                exit_exec = apply_weekly_gap_rule(
                                    target_exit,
                                    market_exit,
                                    hours_since_open,
                                    config,
                                );
                                gap_rule_applied = true;
                            } else {
                                exit_exec =
                                    apply_slippage_free_range(target_exit, market_exit, config);
                            }
                        } else {
                            exit_exec = ExecutionPriceResult {
                                executed_price: target_exit,
                                slippage_usd: 0.0,
                                slippage_points: 0.0,
                            };
                        }
                        closed = true;
                    } else if tp_hit {
                        let tp = pos.order.tp_price.unwrap_or(0.0);
                        // Short exits by buying back at Ask price (market_exit = candle.open + spread_usd).
                        // Target exit price at Ask is tp + spread_usd.
                        let target_exit = tp + spread_usd;
                        let market_exit = candle.open + spread_usd;
                        requested_exit = target_exit;

                        // Gap occurs if bar opened below TP (candle.open < tp); otherwise filled at target_exit in continuous trading
                        if candle.open < tp {
                            let is_gap = (tp - candle.open).abs() > 1e-7;
                            if in_gap_window && is_gap {
                                exit_exec = apply_weekly_gap_rule(
                                    target_exit,
                                    market_exit,
                                    hours_since_open,
                                    config,
                                );
                                gap_rule_applied = true;
                            } else {
                                exit_exec =
                                    apply_slippage_free_range(target_exit, market_exit, config);
                            }
                        } else {
                            exit_exec = ExecutionPriceResult {
                                executed_price: target_exit,
                                slippage_usd: 0.0,
                                slippage_points: 0.0,
                            };
                        }
                        closed = true;
                    }
                }
            }

            if closed {
                let stop_level_checked = true;

                let record = create_audit_record(
                    pos.order.id.clone(),
                    pos.order.direction,
                    pos.order.lot_size,
                    pos.order.requested_price,
                    pos.entry_exec,
                    requested_exit,
                    exit_exec,
                    pos.spread_usd,
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
        if !position_closed_this_bar && active_position.is_none() {
            while order_idx < orders.len() {
                let order = &orders[order_idx];
                let signal_dt = parse_utc_timestamp(&order.signal_timestamp_utc)?;
                let elapsed_seconds = candle_dt.signed_duration_since(signal_dt).num_seconds();

                if elapsed_seconds < 0 {
                    // Skenario 1: Candle occurs BEFORE signal (warm-up / future order)
                    break;
                } else if elapsed_seconds > order.validity_window_seconds as i64 {
                    // Skenario 2: Stale signal expired
                    discarded_orders.push(DiscardedOrderRecord {
                        order_id: order.id.clone(),
                        direction: order.direction,
                        signal_timestamp_utc: order.signal_timestamp_utc.clone(),
                        candle_timestamp_utc: candle.timestamp_utc.clone(),
                        elapsed_seconds,
                        validity_window_seconds: order.validity_window_seconds,
                        requested_price: order.requested_price,
                        reason: "stale_signal_expired".to_string(),
                    });
                    order_idx += 1;
                    continue;
                } else {
                    // Skenario 3: Fresh signal (0 <= elapsed_seconds <= validity_window_seconds)
                    validate_order_stop_level(order, config)?;

                    // Spread modeling (ASUMSI-M2-07):
                    // Long enters at Ask (open + spread_usd), Short enters at Bid (open)
                    let market_entry = match order.direction {
                        Direction::Long => candle.open + spread_usd,
                        Direction::Short => candle.open,
                    };

                    let entry_exec = if in_gap_window {
                        apply_weekly_gap_rule(
                            order.requested_price,
                            market_entry,
                            hours_since_open,
                            config,
                        )
                    } else {
                        apply_slippage_free_range(order.requested_price, market_entry, config)
                    };

                    let margin_required =
                        calculate_margin(order.lot_size, entry_exec.executed_price, config)?;

                    if current_balance >= margin_required {
                        active_position = Some(ActivePosition {
                            order: order.clone(),
                            entry_exec,
                            spread_usd,
                        });
                        order_idx += 1;
                        break;
                    } else {
                        break;
                    }
                }
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

    Ok((summary, audit_records, discarded_orders))
}
