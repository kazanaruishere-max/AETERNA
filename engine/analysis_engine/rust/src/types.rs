use serde::{Deserialize, Serialize};
use thiserror::Error;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub enum Direction {
    Long,
    Short,
}

impl Direction {
    #[inline]
    #[must_use]
    pub const fn multiplier(self) -> f64 {
        match self {
            Self::Long => 1.0,
            Self::Short => -1.0,
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize)]
pub struct BacktestConfig {
    pub contract_size: f64,
    pub point_size: f64,
    pub pip_size: f64,
    pub leverage: f64,
    pub stop_level_points: f64,
    pub slippage_free_points: f64,
}

impl Default for BacktestConfig {
    fn default() -> Self {
        Self {
            contract_size: 100.0,
            point_size: 0.01,
            pip_size: 0.10,
            leverage: 200.0,
            stop_level_points: 300.0,
            slippage_free_points: 15.0,
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize)]
pub struct PnlResult {
    pub gross_pnl_usd: f64,
    pub pnl_pips: f64,
    pub spread_cost_usd: f64,
    pub net_pnl_usd: f64,
    pub margin_required_usd: f64,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Error)]
pub enum PnlError {
    #[error("Invalid lot size: lot size must be strictly positive and finite")]
    InvalidLotSize,
    #[error("Invalid price: price must be strictly positive and finite")]
    InvalidPrice,
    #[error("Invalid leverage: leverage must be strictly positive and finite")]
    InvalidLeverage,
    #[error("Invalid spread: spread must be non-negative and finite")]
    InvalidSpread,
    #[error(
        "Invalid configuration: contract size and pip size must be strictly positive and finite"
    )]
    InvalidConfig,
}

/// Execution / order type for trading simulation.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub enum ExecutionType {
    Market,
    Limit,
    Stop,
}

/// Order representation for broker execution rules and backtest simulation.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct Order {
    pub id: String,
    pub direction: Direction,
    pub execution_type: ExecutionType,
    pub requested_price: f64,
    pub lot_size: f64,
    pub sl_price: Option<f64>,
    pub tp_price: Option<f64>,
}

/// Result of applying broker execution rules (slippage, gap rule).
#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize)]
pub struct ExecutionPriceResult {
    pub executed_price: f64,
    pub slippage_usd: f64,
    pub slippage_points: f64,
}

/// Deterministic execution audit record for hand-calc cross-verification (`GATE-M2-HUMAN`).
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ExecutionAuditRecord {
    pub trade_id: String,
    pub direction: Direction,
    pub lot_size: f64,
    pub requested_entry: f64,
    pub executed_entry: f64,
    pub slippage_entry_usd: f64,
    pub requested_exit: f64,
    pub executed_exit: f64,
    pub slippage_exit_usd: f64,
    pub gross_pnl_usd: f64,
    pub pnl_pips: f64,
    pub spread_cost_usd: f64,
    pub net_pnl_usd: f64,
    pub margin_required_usd: f64,
    pub stop_level_checked: bool,
    pub gap_rule_applied: bool,
}

/// Error variants encountered during broker execution rules validation or calculation.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Error)]
pub enum BrokerRuleError {
    #[error(
        "Stop level violation: distance to SL or TP must be >= stop_level_points * point_size"
    )]
    StopLevelViolation,
    #[error("Invalid price: price must be strictly positive and finite")]
    InvalidPrice,
    #[error(
        "Invalid configuration: configuration parameters must be strictly positive and finite"
    )]
    InvalidConfig,
    #[error("Invalid parameter: parameter must be finite and within valid range")]
    InvalidParameter,
    #[error("PnL computation error: {0}")]
    PnlCalculationError(#[from] PnlError),
}
