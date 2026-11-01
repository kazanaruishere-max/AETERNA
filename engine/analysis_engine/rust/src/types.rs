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
    /// Default broker spread in points (e.g. 20.0 points = $0.20 USD = 2.0 pips baseline for Exness Standard XAUUSD).
    /// Used when per-candle spread is unavailable (ASUMSI-M2-07).
    pub default_spread_points: f64,
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
            default_spread_points: 20.0,
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
    pub signal_timestamp_utc: String,
    pub validity_window_seconds: u64,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct DiscardedOrderRecord {
    pub order_id: String,
    pub direction: Direction,
    pub signal_timestamp_utc: String,
    pub candle_timestamp_utc: String,
    pub elapsed_seconds: i64,
    pub validity_window_seconds: u64,
    pub requested_price: f64,
    pub reason: String,
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

/// M1 Candle representation for backtest simulation.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct Candle {
    pub timestamp_utc: String,
    pub open: f64,
    pub high: f64,
    pub low: f64,
    pub close: f64,
    pub tick_volume: u64,
}

/// Strategy signal emitted by a trading strategy for backtest execution.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct StrategySignal {
    pub timestamp_utc: String,
    pub order: Order,
}

/// Aggregated performance summary of a backtest simulation run.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct BacktestSummary {
    pub total_trades: usize,
    pub win_trades: usize,
    pub loss_trades: usize,
    pub gross_profit_usd: f64,
    pub gross_loss_usd: f64,
    pub net_pnl_usd: f64,
    pub profit_factor: f64,
    pub max_drawdown_usd: f64,
    pub max_drawdown_pct: f64,
    pub total_spread_cost_usd: f64,
    pub total_slippage_cost_usd: f64,
}

/// Results of a Trade Sequence Shuffling Monte Carlo analysis.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct MonteCarloResult {
    pub iterations: usize,
    pub median_max_dd_pct: f64,
    pub percentile_95_max_dd_pct: f64,
    pub percentile_99_max_dd_pct: f64,
    pub risk_of_ruin_10pct_dd: f64,
}

/// Top-level error enum for the simulation and analysis engine.
#[derive(Debug, Clone, PartialEq, Eq, Error)]
pub enum EngineError {
    #[error("Broker rule error: {0}")]
    BrokerError(#[from] BrokerRuleError),
    #[error("PnL calculation error: {0}")]
    PnlError(#[from] PnlError),
    #[error("Invalid candle data: high must be >= low, and prices must be positive and finite")]
    InvalidCandleData,
    #[error("Empty trade history: backtest produced zero trades for Monte Carlo analysis")]
    EmptyTradeHistory,
    #[error("Simulation calculation error: {0}")]
    CalculationError(String),
}
