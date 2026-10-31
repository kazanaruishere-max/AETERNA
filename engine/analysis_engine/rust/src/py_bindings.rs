//! Module: engine.analysis_engine.rust.src.py_bindings
//! Responsibility: PyO3 FFI bindings and serialization between Python and Rust.
//! Owner: aeterna-backtest
//! Tier: B

#![allow(clippy::useless_conversion)]

use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyList};

use crate::engine::{hours_since_weekly_open, run_backtest};
use crate::monte_carlo::run_monte_carlo;
use crate::pnl::calculate_pnl;
use crate::types::{
    BacktestConfig, BacktestSummary, Candle, Direction, ExecutionAuditRecord, ExecutionType,
    MonteCarloResult, Order, PnlResult,
};

fn parse_direction(val: &str) -> PyResult<Direction> {
    match val.to_ascii_uppercase().as_str() {
        "LONG" => Ok(Direction::Long),
        "SHORT" => Ok(Direction::Short),
        other => Err(PyValueError::new_err(format!(
            "Invalid direction: '{other}'. Expected 'LONG' or 'SHORT'"
        ))),
    }
}

fn parse_config(dict_opt: Option<&Bound<'_, PyDict>>) -> PyResult<BacktestConfig> {
    let mut cfg = BacktestConfig::default();
    let Some(dict) = dict_opt else {
        return Ok(cfg);
    };

    if let Some(item) = dict.get_item("contract_size")? {
        cfg.contract_size = item.extract::<f64>()?;
    }
    if let Some(item) = dict.get_item("point_size")? {
        cfg.point_size = item.extract::<f64>()?;
    }
    if let Some(item) = dict.get_item("pip_size")? {
        cfg.pip_size = item.extract::<f64>()?;
    }
    if let Some(item) = dict.get_item("leverage")? {
        cfg.leverage = item.extract::<f64>()?;
    }
    if let Some(item) = dict.get_item("stop_level_points")? {
        cfg.stop_level_points = item.extract::<f64>()?;
    }
    if let Some(item) = dict.get_item("slippage_free_points")? {
        cfg.slippage_free_points = item.extract::<f64>()?;
    }
    if let Some(item) = dict.get_item("default_spread_points")? {
        cfg.default_spread_points = item.extract::<f64>()?;
    }
    Ok(cfg)
}

fn parse_candle(dict: &Bound<'_, PyDict>) -> PyResult<Candle> {
    let ts_item = dict
        .get_item("timestamp_utc")?
        .ok_or_else(|| PyValueError::new_err("Candle missing 'timestamp_utc'"))?;
    let timestamp_utc = ts_item.extract::<String>()?;

    let open = dict
        .get_item("open")?
        .ok_or_else(|| PyValueError::new_err("Candle missing 'open'"))?
        .extract::<f64>()?;
    let high = dict
        .get_item("high")?
        .ok_or_else(|| PyValueError::new_err("Candle missing 'high'"))?
        .extract::<f64>()?;
    let low = dict
        .get_item("low")?
        .ok_or_else(|| PyValueError::new_err("Candle missing 'low'"))?
        .extract::<f64>()?;
    let close = dict
        .get_item("close")?
        .ok_or_else(|| PyValueError::new_err("Candle missing 'close'"))?
        .extract::<f64>()?;
    let tick_volume = dict
        .get_item("tick_volume")?
        .ok_or_else(|| PyValueError::new_err("Candle missing 'tick_volume'"))?
        .extract::<u64>()?;

    if !open.is_finite()
        || open <= 0.0
        || !high.is_finite()
        || high <= 0.0
        || !low.is_finite()
        || low <= 0.0
        || !close.is_finite()
        || close <= 0.0
        || high < low
    {
        return Err(PyValueError::new_err(
            "Invalid candle data: high must be >= low, and prices must be positive and finite",
        ));
    }

    Ok(Candle {
        timestamp_utc,
        open,
        high,
        low,
        close,
        tick_volume,
    })
}

fn parse_order(dict: &Bound<'_, PyDict>) -> PyResult<Order> {
    let id_item = dict
        .get_item("id")?
        .ok_or_else(|| PyValueError::new_err("Order missing 'id'"))?;
    let id = id_item.extract::<String>()?;

    let dir_item = dict
        .get_item("direction")?
        .ok_or_else(|| PyValueError::new_err("Order missing 'direction'"))?;
    let direction_str = dir_item.extract::<String>()?;
    let direction = parse_direction(&direction_str)?;

    let requested_price = dict
        .get_item("requested_price")?
        .ok_or_else(|| PyValueError::new_err("Order missing 'requested_price'"))?
        .extract::<f64>()?;
    let lot_size = dict
        .get_item("lot_size")?
        .ok_or_else(|| PyValueError::new_err("Order missing 'lot_size'"))?
        .extract::<f64>()?;

    let sl_price = match dict.get_item("sl_price")? {
        Some(item) => item.extract::<Option<f64>>()?,
        None => None,
    };
    let tp_price = match dict.get_item("tp_price")? {
        Some(item) => item.extract::<Option<f64>>()?,
        None => None,
    };

    let execution_type = match dict.get_item("execution_type")? {
        Some(item) => {
            let s = item.extract::<String>()?;
            match s.to_ascii_uppercase().as_str() {
                "MARKET" => ExecutionType::Market,
                "LIMIT" => ExecutionType::Limit,
                "STOP" => ExecutionType::Stop,
                other => {
                    return Err(PyValueError::new_err(format!(
                        "Invalid execution_type: '{other}'"
                    )))
                }
            }
        }
        None => ExecutionType::Market,
    };

    Ok(Order {
        id,
        direction,
        execution_type,
        requested_price,
        lot_size,
        sl_price,
        tp_price,
    })
}

fn summary_to_py(py: Python<'_>, s: &BacktestSummary) -> PyResult<PyObject> {
    let dict = PyDict::new_bound(py);
    dict.set_item("total_trades", s.total_trades)?;
    dict.set_item("win_trades", s.win_trades)?;
    dict.set_item("loss_trades", s.loss_trades)?;
    dict.set_item("gross_profit_usd", s.gross_profit_usd)?;
    dict.set_item("gross_loss_usd", s.gross_loss_usd)?;
    dict.set_item("net_pnl_usd", s.net_pnl_usd)?;
    dict.set_item("profit_factor", s.profit_factor)?;
    dict.set_item("max_drawdown_usd", s.max_drawdown_usd)?;
    dict.set_item("max_drawdown_pct", s.max_drawdown_pct)?;
    dict.set_item("total_spread_cost_usd", s.total_spread_cost_usd)?;
    dict.set_item("total_slippage_cost_usd", s.total_slippage_cost_usd)?;
    Ok(dict.into())
}

fn audit_record_to_py(py: Python<'_>, a: &ExecutionAuditRecord) -> PyResult<PyObject> {
    let dict = PyDict::new_bound(py);
    dict.set_item("trade_id", &a.trade_id)?;
    dict.set_item(
        "direction",
        match a.direction {
            Direction::Long => "LONG",
            Direction::Short => "SHORT",
        },
    )?;
    dict.set_item("lot_size", a.lot_size)?;
    dict.set_item("requested_entry", a.requested_entry)?;
    dict.set_item("executed_entry", a.executed_entry)?;
    dict.set_item("slippage_entry_usd", a.slippage_entry_usd)?;
    dict.set_item("requested_exit", a.requested_exit)?;
    dict.set_item("executed_exit", a.executed_exit)?;
    dict.set_item("slippage_exit_usd", a.slippage_exit_usd)?;
    dict.set_item("gross_pnl_usd", a.gross_pnl_usd)?;
    dict.set_item("pnl_pips", a.pnl_pips)?;
    dict.set_item("spread_cost_usd", a.spread_cost_usd)?;
    dict.set_item("net_pnl_usd", a.net_pnl_usd)?;
    dict.set_item("margin_required_usd", a.margin_required_usd)?;
    dict.set_item("stop_level_checked", a.stop_level_checked)?;
    dict.set_item("gap_rule_applied", a.gap_rule_applied)?;
    Ok(dict.into())
}

fn monte_carlo_to_py(py: Python<'_>, mc: &MonteCarloResult) -> PyResult<PyObject> {
    let check_finite = |val: f64, name: &'static str| -> PyResult<f64> {
        if val.is_nan() || val.is_infinite() {
            Err(PyValueError::new_err(format!(
                "Monte Carlo calculation produced non-finite value in '{name}': {val}"
            )))
        } else {
            Ok(val)
        }
    };
    let dict = PyDict::new_bound(py);
    dict.set_item("iterations", mc.iterations)?;
    dict.set_item(
        "median_max_dd_pct",
        check_finite(mc.median_max_dd_pct, "median_max_dd_pct")?,
    )?;
    dict.set_item(
        "percentile_95_max_dd_pct",
        check_finite(mc.percentile_95_max_dd_pct, "percentile_95_max_dd_pct")?,
    )?;
    dict.set_item(
        "percentile_99_max_dd_pct",
        check_finite(mc.percentile_99_max_dd_pct, "percentile_99_max_dd_pct")?,
    )?;
    dict.set_item(
        "risk_of_ruin_10pct_dd",
        check_finite(mc.risk_of_ruin_10pct_dd, "risk_of_ruin_10pct_dd")?,
    )?;
    Ok(dict.into())
}

fn pnl_result_to_py(py: Python<'_>, pnl: &PnlResult) -> PyResult<PyObject> {
    let dict = PyDict::new_bound(py);
    dict.set_item("gross_pnl_usd", pnl.gross_pnl_usd)?;
    dict.set_item("pnl_pips", pnl.pnl_pips)?;
    dict.set_item("spread_cost_usd", pnl.spread_cost_usd)?;
    dict.set_item("net_pnl_usd", pnl.net_pnl_usd)?;
    dict.set_item("margin_required_usd", pnl.margin_required_usd)?;
    Ok(dict.into())
}

#[pyfunction]
#[pyo3(signature = (candles, orders, config=None, initial_balance=10000.0))]
pub fn py_run_backtest(
    py: Python<'_>,
    candles: &Bound<'_, PyList>,
    orders: &Bound<'_, PyList>,
    config: Option<&Bound<'_, PyDict>>,
    initial_balance: f64,
) -> PyResult<(PyObject, PyObject)> {
    if !initial_balance.is_finite() || initial_balance <= 0.0 {
        return Err(PyValueError::new_err(
            "Initial balance must be positive and finite",
        ));
    }
    let cfg = parse_config(config)?;
    let parsed_candles = candles
        .iter()
        .map(|item| parse_candle(item.downcast::<PyDict>()?))
        .collect::<PyResult<Vec<Candle>>>()?;
    let parsed_orders = orders
        .iter()
        .map(|item| parse_order(item.downcast::<PyDict>()?))
        .collect::<PyResult<Vec<Order>>>()?;

    let (summary, audit_records) = py
        .allow_threads(|| run_backtest(&parsed_candles, &parsed_orders, &cfg, initial_balance))
        .map_err(|e| PyValueError::new_err(e.to_string()))?;

    let py_summary = summary_to_py(py, &summary)?;
    let py_audit_list = PyList::empty_bound(py);
    for record in &audit_records {
        let py_rec = audit_record_to_py(py, record)?;
        py_audit_list.append(py_rec)?;
    }

    Ok((py_summary, py_audit_list.into()))
}

#[pyfunction]
#[pyo3(signature = (trades, num_simulations=1000, seed=None, initial_equity=10000.0))]
pub fn py_run_monte_carlo(
    py: Python<'_>,
    trades: &Bound<'_, PyList>,
    num_simulations: usize,
    seed: Option<u64>,
    initial_equity: f64,
) -> PyResult<PyObject> {
    if !initial_equity.is_finite() || initial_equity <= 0.0 {
        return Err(PyValueError::new_err(
            "Initial equity must be positive and finite",
        ));
    }
    let mut parsed_trades = Vec::with_capacity(trades.len());
    for item in trades.iter() {
        let dict = item.downcast::<PyDict>()?;
        let net_pnl = dict
            .get_item("net_pnl_usd")?
            .ok_or_else(|| PyValueError::new_err("Trade record missing 'net_pnl_usd'"))?
            .extract::<f64>()?;
        if !net_pnl.is_finite() {
            return Err(PyValueError::new_err("net_pnl_usd must be finite"));
        }
        let gross_pnl = match dict.get_item("gross_pnl_usd")? {
            Some(val) => val.extract::<f64>()?,
            None => net_pnl,
        };
        let pnl_pips = match dict.get_item("pnl_pips")? {
            Some(val) => val.extract::<f64>()?,
            None => 0.0,
        };
        let spread_cost = match dict.get_item("spread_cost_usd")? {
            Some(val) => val.extract::<f64>()?,
            None => 0.0,
        };
        let margin_req = match dict.get_item("margin_required_usd")? {
            Some(val) => val.extract::<f64>()?,
            None => 0.0,
        };
        parsed_trades.push(PnlResult {
            gross_pnl_usd: gross_pnl,
            pnl_pips,
            spread_cost_usd: spread_cost,
            net_pnl_usd: net_pnl,
            margin_required_usd: margin_req,
        });
    }

    let mc_res = py
        .allow_threads(|| run_monte_carlo(&parsed_trades, initial_equity, num_simulations, seed))
        .map_err(|e| PyValueError::new_err(e.to_string()))?;

    monte_carlo_to_py(py, &mc_res)
}

#[pyfunction]
pub fn py_hours_since_weekly_open(timestamp_utc: &str) -> PyResult<f64> {
    hours_since_weekly_open(timestamp_utc).map_err(|e| PyValueError::new_err(e.to_string()))
}

#[pyfunction]
#[pyo3(signature = (direction, entry_price, exit_price, lot_size, config=None))]
pub fn py_calculate_pnl(
    py: Python<'_>,
    direction: &str,
    entry_price: f64,
    exit_price: f64,
    lot_size: f64,
    config: Option<&Bound<'_, PyDict>>,
) -> PyResult<PyObject> {
    let dir = parse_direction(direction)?;
    let cfg = parse_config(config)?;
    let pnl = calculate_pnl(dir, entry_price, exit_price, lot_size, &cfg)
        .map_err(|e| PyValueError::new_err(e.to_string()))?;
    pnl_result_to_py(py, &pnl)
}

pub fn register_bindings(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(py_run_backtest, m)?)?;
    m.add_function(wrap_pyfunction!(py_run_monte_carlo, m)?)?;
    m.add_function(wrap_pyfunction!(py_hours_since_weekly_open, m)?)?;
    m.add_function(wrap_pyfunction!(py_calculate_pnl, m)?)?;
    Ok(())
}
