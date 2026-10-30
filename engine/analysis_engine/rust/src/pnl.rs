use crate::types::{BacktestConfig, Direction, PnlError, PnlResult};

/// Calculates gross PnL, PnL in pips, spread cost, net PnL, and required margin for a trade.
///
/// # Errors
/// Returns [`PnlError`] if input parameters or configuration values are non-positive or non-finite.
pub fn calculate_pnl(
    direction: Direction,
    entry_price: f64,
    exit_price: f64,
    lot_size: f64,
    config: &BacktestConfig,
) -> Result<PnlResult, PnlError> {
    calculate_pnl_with_spread(direction, entry_price, exit_price, lot_size, 0.0, config)
}

/// Calculates PnL including spread cost.
///
/// # Errors
/// Returns [`PnlError`] if input parameters, spread, or configuration values are invalid.
pub fn calculate_pnl_with_spread(
    direction: Direction,
    entry_price: f64,
    exit_price: f64,
    lot_size: f64,
    spread_usd: f64,
    config: &BacktestConfig,
) -> Result<PnlResult, PnlError> {
    if !lot_size.is_finite() || lot_size <= 0.0 {
        return Err(PnlError::InvalidLotSize);
    }
    if !entry_price.is_finite() || entry_price <= 0.0 {
        return Err(PnlError::InvalidPrice);
    }
    if !exit_price.is_finite() || exit_price <= 0.0 {
        return Err(PnlError::InvalidPrice);
    }
    if !config.leverage.is_finite() || config.leverage <= 0.0 {
        return Err(PnlError::InvalidLeverage);
    }
    if !config.contract_size.is_finite()
        || config.contract_size <= 0.0
        || !config.pip_size.is_finite()
        || config.pip_size <= 0.0
    {
        return Err(PnlError::InvalidConfig);
    }
    if !spread_usd.is_finite() || spread_usd < 0.0 {
        return Err(PnlError::InvalidSpread);
    }

    let margin_required_usd = calculate_margin(lot_size, entry_price, config)?;
    let spread_cost_usd = calculate_spread_cost(lot_size, spread_usd, config)?;

    let price_diff = direction.multiplier() * (exit_price - entry_price);
    let gross_pnl_usd = price_diff * lot_size * config.contract_size;
    let pnl_pips = price_diff / config.pip_size;
    let net_pnl_usd = gross_pnl_usd - spread_cost_usd;

    Ok(PnlResult {
        gross_pnl_usd,
        pnl_pips,
        spread_cost_usd,
        net_pnl_usd,
        margin_required_usd,
    })
}

/// Calculates required margin in USD.
/// Formula: `(Lot Size * Contract Size * Entry Price) / Leverage`
///
/// # Errors
/// Returns [`PnlError`] if inputs or configuration values are non-positive or non-finite.
pub fn calculate_margin(
    lot_size: f64,
    entry_price: f64,
    config: &BacktestConfig,
) -> Result<f64, PnlError> {
    if !lot_size.is_finite() || lot_size <= 0.0 {
        return Err(PnlError::InvalidLotSize);
    }
    if !entry_price.is_finite() || entry_price <= 0.0 {
        return Err(PnlError::InvalidPrice);
    }
    if !config.leverage.is_finite() || config.leverage <= 0.0 {
        return Err(PnlError::InvalidLeverage);
    }
    if !config.contract_size.is_finite() || config.contract_size <= 0.0 {
        return Err(PnlError::InvalidConfig);
    }

    Ok((lot_size * config.contract_size * entry_price) / config.leverage)
}

/// Calculates spread cost in USD.
/// Formula: `Spread USD * Lot Size * Contract Size`
///
/// # Errors
/// Returns [`PnlError`] if lot size, spread, or configuration values are invalid.
pub fn calculate_spread_cost(
    lot_size: f64,
    spread_usd: f64,
    config: &BacktestConfig,
) -> Result<f64, PnlError> {
    if !lot_size.is_finite() || lot_size <= 0.0 {
        return Err(PnlError::InvalidLotSize);
    }
    if !spread_usd.is_finite() || spread_usd < 0.0 {
        return Err(PnlError::InvalidSpread);
    }
    if !config.contract_size.is_finite() || config.contract_size <= 0.0 {
        return Err(PnlError::InvalidConfig);
    }

    Ok(spread_usd * lot_size * config.contract_size)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_spread_cost_calculation() -> Result<(), PnlError> {
        let config = BacktestConfig::default();
        // 0.10 USD spread per oz * 0.05 lot * 100 contract_size = 0.50 USD
        let cost = calculate_spread_cost(0.05, 0.10, &config)?;
        assert!((cost - 0.50).abs() < 1e-6);
        Ok(())
    }

    #[test]
    fn test_zero_spread_cost() -> Result<(), PnlError> {
        let config = BacktestConfig::default();
        let cost = calculate_spread_cost(1.0, 0.0, &config)?;
        assert!((cost - 0.0).abs() < 1e-6);
        Ok(())
    }
}
