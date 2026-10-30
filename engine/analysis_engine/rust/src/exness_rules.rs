//! Exness Broker Execution Rules (`exness_rules.rs`).
//!
//! Implements Exness broker execution invariants:
//! 1. Minimum Stop Level validation for pending orders, SL, and TP (`REQ-BKT-003`).
//! 2. Slippage-Free Range execution (`REQ-BKT-002`).
//! 3. Weekly Market Open Gap Rule during the first 3 trading hours (`REQ-BKT-004`).

use crate::types::{BacktestConfig, BrokerRuleError, ExecutionPriceResult, Order};

const FLOAT_EPSILON: f64 = 1e-7;

/// Validates whether SL and TP distances respect the Exness minimum stop level requirement (`REQ-BKT-003`).
///
/// Distance to both `sl_price` (if present) and `tp_price` (if present) must be:
/// `distance >= config.stop_level_points * config.point_size`.
///
/// # Errors
/// Returns [`BrokerRuleError::StopLevelViolation`] if any distance is strictly less than the required minimum.
/// Returns [`BrokerRuleError::InvalidPrice`] if any price is non-positive or non-finite.
/// Returns [`BrokerRuleError::InvalidConfig`] if `stop_level_points` is negative or `point_size` is non-positive.
pub fn validate_stop_level(
    entry_price: f64,
    sl_price: Option<f64>,
    tp_price: Option<f64>,
    config: &BacktestConfig,
) -> Result<(), BrokerRuleError> {
    if !entry_price.is_finite() || entry_price <= 0.0 {
        return Err(BrokerRuleError::InvalidPrice);
    }
    if !config.point_size.is_finite() || config.point_size <= 0.0 {
        return Err(BrokerRuleError::InvalidConfig);
    }
    if !config.stop_level_points.is_finite() || config.stop_level_points < 0.0 {
        return Err(BrokerRuleError::InvalidConfig);
    }

    let min_distance = config.stop_level_points * config.point_size;

    if let Some(sl) = sl_price {
        if !sl.is_finite() || sl <= 0.0 {
            return Err(BrokerRuleError::InvalidPrice);
        }
        let sl_distance = (entry_price - sl).abs();
        if (min_distance - sl_distance) > FLOAT_EPSILON {
            return Err(BrokerRuleError::StopLevelViolation);
        }
    }

    if let Some(tp) = tp_price {
        if !tp.is_finite() || tp <= 0.0 {
            return Err(BrokerRuleError::InvalidPrice);
        }
        let tp_distance = (entry_price - tp).abs();
        if (min_distance - tp_distance) > FLOAT_EPSILON {
            return Err(BrokerRuleError::StopLevelViolation);
        }
    }

    Ok(())
}

/// Helper function to validate stop levels for an [`Order`].
///
/// # Errors
/// Returns [`BrokerRuleError`] if SL or TP violates minimum stop level or contains invalid prices.
pub fn validate_order_stop_level(
    order: &Order,
    config: &BacktestConfig,
) -> Result<(), BrokerRuleError> {
    validate_stop_level(
        order.requested_price,
        order.sl_price,
        order.tp_price,
        config,
    )
}

/// Applies Exness slippage-free range logic (`REQ-BKT-002`).
///
/// Calculates price difference in points:
/// `delta = |requested_price - market_price| / config.point_size`.
///
/// If `delta < config.slippage_free_points`:
/// Execution occurs at `requested_price` with zero slippage (`slippage_usd = 0.0`).
///
/// If `delta >= config.slippage_free_points`:
/// Slippage protection is forfeited; execution occurs at `market_price` with
/// `slippage_usd = market_price - requested_price`.
#[must_use]
pub fn apply_slippage_free_range(
    requested_price: f64,
    market_price: f64,
    config: &BacktestConfig,
) -> ExecutionPriceResult {
    let point_size = if config.point_size.is_finite() && config.point_size > 0.0 {
        config.point_size
    } else {
        0.01
    };

    let delta_points = (requested_price - market_price).abs() / point_size;

    if (config.slippage_free_points - delta_points) > FLOAT_EPSILON {
        ExecutionPriceResult {
            executed_price: requested_price,
            slippage_usd: 0.0,
            slippage_points: 0.0,
        }
    } else {
        let slippage_usd = market_price - requested_price;
        let slippage_points = slippage_usd / point_size;
        ExecutionPriceResult {
            executed_price: market_price,
            slippage_usd,
            slippage_points,
        }
    }
}

/// Applies Exness weekly market opening gap rule (`REQ-BKT-004`).
///
/// During the first 3 hours after weekly market open (`hours_since_open < 3.0`):
/// Slippage-free protection is completely disabled. Any pending order or stop triggered by
/// a market open price gap is executed at the first available market open price (`market_open_price`).
///
/// After the initial 3 hours (`hours_since_open >= 3.0`):
/// Normal slippage-free execution rules resume via [`apply_slippage_free_range`].
#[must_use]
pub fn apply_weekly_gap_rule(
    requested_price: f64,
    market_open_price: f64,
    hours_since_open: f64,
    config: &BacktestConfig,
) -> ExecutionPriceResult {
    if (3.0 - hours_since_open) > FLOAT_EPSILON {
        let point_size = if config.point_size.is_finite() && config.point_size > 0.0 {
            config.point_size
        } else {
            0.01
        };
        let slippage_usd = market_open_price - requested_price;
        let slippage_points = slippage_usd / point_size;
        ExecutionPriceResult {
            executed_price: market_open_price,
            slippage_usd,
            slippage_points,
        }
    } else {
        apply_slippage_free_range(requested_price, market_open_price, config)
    }
}
