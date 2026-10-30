//! Aeterna Backtest Engine - Pure Mathematical PnL Engine & Exness Broker Rules.
//!
//! Provides pure safe mathematical calculations for PnL, Pips, Margin, Spread cost,
//! Exness broker execution rules, and deterministic audit tracing for XAUUSD.

#![forbid(unsafe_code)]

pub mod audit;
pub mod exness_rules;
pub mod pnl;
pub mod types;

pub use audit::{
    create_audit_record, create_audit_record_from_prices, AuditLedger, ExecutionAuditRecord,
};
pub use exness_rules::{
    apply_slippage_free_range, apply_weekly_gap_rule, validate_order_stop_level,
    validate_stop_level,
};
pub use pnl::{calculate_margin, calculate_pnl, calculate_pnl_with_spread, calculate_spread_cost};
pub use types::{
    BacktestConfig, BrokerRuleError, Direction, ExecutionPriceResult, ExecutionType, Order,
    PnlError, PnlResult,
};
