//! Deterministic Audit Tracer (`audit.rs`).
//!
//! Provides deterministic audit records and ledger for hand-calc cross-verification (`GATE-M2-HUMAN`).
//! Guarantees mathematical parity with the core PnL engine (`pnl.rs`) while tracking slippage and rule flags.

use serde::{Deserialize, Serialize};

use crate::pnl::calculate_pnl_with_spread;
use crate::types::{BacktestConfig, BrokerRuleError, Direction, ExecutionPriceResult};

/// Re-export [`ExecutionAuditRecord`] for direct module consumer usage.
pub use crate::types::ExecutionAuditRecord;
/// Creates a new deterministic execution audit record.
///
/// Computes gross PnL, PnL in pips, spread cost, net PnL, and required margin via `pnl.rs`.
///
/// # Errors
/// Returns [`BrokerRuleError`] if any price, lot size, spread, or configuration parameter is invalid.
#[allow(clippy::too_many_arguments)]
pub fn create_audit_record(
    trade_id: impl Into<String>,
    direction: Direction,
    lot_size: f64,
    requested_entry: f64,
    entry_exec: ExecutionPriceResult,
    requested_exit: f64,
    exit_exec: ExecutionPriceResult,
    spread_usd: f64,
    exit_reason: &str,
    stop_level_checked: bool,
    gap_rule_applied: bool,
    config: &BacktestConfig,
) -> Result<ExecutionAuditRecord, BrokerRuleError> {
    let pnl_result = calculate_pnl_with_spread(
        direction,
        entry_exec.executed_price,
        exit_exec.executed_price,
        lot_size,
        spread_usd,
        config,
    )?;

    Ok(ExecutionAuditRecord {
        trade_id: trade_id.into(),
        direction,
        lot_size,
        requested_entry,
        executed_entry: entry_exec.executed_price,
        slippage_entry_usd: entry_exec.slippage_usd,
        requested_exit,
        executed_exit: exit_exec.executed_price,
        slippage_exit_usd: exit_exec.slippage_usd,
        gross_pnl_usd: pnl_result.gross_pnl_usd,
        pnl_pips: pnl_result.pnl_pips,
        spread_cost_usd: pnl_result.spread_cost_usd,
        net_pnl_usd: pnl_result.net_pnl_usd,
        margin_required_usd: pnl_result.margin_required_usd,
        stop_level_checked,
        gap_rule_applied,
        exit_reason: exit_reason.to_string(),
    })
}

/// Helper function to create an audit record directly from individual execution prices and slippages.
///
/// # Errors
/// Returns [`BrokerRuleError`] if inputs or configuration fail validation.
#[allow(clippy::too_many_arguments)]
pub fn create_audit_record_from_prices(
    trade_id: impl Into<String>,
    direction: Direction,
    lot_size: f64,
    requested_entry: f64,
    executed_entry: f64,
    slippage_entry_usd: f64,
    requested_exit: f64,
    executed_exit: f64,
    slippage_exit_usd: f64,
    spread_usd: f64,
    exit_reason: &str,
    stop_level_checked: bool,
    gap_rule_applied: bool,
    config: &BacktestConfig,
) -> Result<ExecutionAuditRecord, BrokerRuleError> {
    let point_size = if config.point_size.is_finite() && config.point_size > 0.0 {
        config.point_size
    } else {
        0.01
    };

    let entry_exec = ExecutionPriceResult {
        executed_price: executed_entry,
        slippage_usd: slippage_entry_usd,
        slippage_points: slippage_entry_usd / point_size,
    };
    let exit_exec = ExecutionPriceResult {
        executed_price: executed_exit,
        slippage_usd: slippage_exit_usd,
        slippage_points: slippage_exit_usd / point_size,
    };

    create_audit_record(
        trade_id,
        direction,
        lot_size,
        requested_entry,
        entry_exec,
        requested_exit,
        exit_exec,
        spread_usd,
        exit_reason,
        stop_level_checked,
        gap_rule_applied,
        config,
    )
}

/// Deterministic in-memory audit ledger tracking backtest trade records.
#[derive(Debug, Default, Clone, PartialEq, Serialize, Deserialize)]
pub struct AuditLedger {
    records: Vec<ExecutionAuditRecord>,
}

impl AuditLedger {
    /// Creates an empty audit ledger.
    #[must_use]
    pub const fn new() -> Self {
        Self {
            records: Vec::new(),
        }
    }

    /// Appends an execution audit record to the ledger.
    pub fn record(&mut self, record: ExecutionAuditRecord) {
        self.records.push(record);
    }

    /// Returns a slice of all recorded audit records.
    #[must_use]
    pub fn records(&self) -> &[ExecutionAuditRecord] {
        &self.records
    }

    /// Returns the number of records in the ledger.
    #[must_use]
    pub fn len(&self) -> usize {
        self.records.len()
    }

    /// Returns true if the ledger is empty.
    #[must_use]
    pub fn is_empty(&self) -> bool {
        self.records.is_empty()
    }

    /// Clears all records from the ledger.
    pub fn clear(&mut self) {
        self.records.clear();
    }

    /// Computes the sum of net PnL across all recorded trades.
    #[must_use]
    pub fn total_net_pnl(&self) -> f64 {
        self.records.iter().map(|r| r.net_pnl_usd).sum()
    }

    /// Computes the sum of gross PnL across all recorded trades.
    #[must_use]
    pub fn total_gross_pnl(&self) -> f64 {
        self.records.iter().map(|r| r.gross_pnl_usd).sum()
    }

    /// Computes the total spread cost incurred across all recorded trades.
    #[must_use]
    pub fn total_spread_cost(&self) -> f64 {
        self.records.iter().map(|r| r.spread_cost_usd).sum()
    }

    /// Computes total realized slippage in USD (entry slippage + exit slippage).
    #[must_use]
    pub fn total_slippage_usd(&self) -> f64 {
        self.records
            .iter()
            .map(|r| r.slippage_entry_usd + r.slippage_exit_usd)
            .sum()
    }
}
