//! Aeterna Backtest Engine - Pure Mathematical PnL Engine & Exness Broker Rules.
//!
//! Provides pure safe mathematical calculations for PnL, Pips, Margin, Spread cost,
//! Exness broker execution rules, and deterministic audit tracing for XAUUSD.

#![forbid(unsafe_code)]

pub mod audit;
pub mod engine;
pub mod exness_rules;
pub mod monte_carlo;
pub mod pnl;
pub mod types;

pub use audit::{
    create_audit_record, create_audit_record_from_prices, AuditLedger, ExecutionAuditRecord,
};
pub use engine::{hours_since_weekly_open, run_backtest};
pub use exness_rules::{
    apply_slippage_free_range, apply_weekly_gap_rule, validate_order_stop_level,
    validate_stop_level,
};
pub use monte_carlo::run_monte_carlo;
pub use pnl::{calculate_margin, calculate_pnl, calculate_pnl_with_spread, calculate_spread_cost};
pub use types::{
    BacktestConfig, BacktestSummary, BrokerRuleError, Candle, Direction, EngineError,
    ExecutionPriceResult, ExecutionType, MonteCarloResult, Order, PnlError, PnlResult,
    StrategySignal,
};
