//! Monte Carlo Trade Sequence Shuffling (`monte_carlo.rs`).
//!
//! Provides deterministic trade sequence shuffling over 1,000 iterations to evaluate
//! drawdown percentiles and risk of ruin against the 10.0% project killswitch threshold.
//!
//! Uses audited `rand_xoshiro::Xoshiro256StarStar` with `rand::seq::SliceRandom`
//! (unbiased Lemire reduction algorithm) to eliminate any modulo bias (ASUMSI-M2-06).

use rand::seq::SliceRandom;
use rand::SeedableRng;
use rand_xoshiro::Xoshiro256StarStar;

use crate::types::{EngineError, MonteCarloResult, PnlResult};

/// Default deterministic seed for reproducible Monte Carlo simulation.
pub const DEFAULT_MC_SEED: u64 = 0x4D59_5354_4943_5F31;

/// Runs a deterministic Trade Sequence Shuffling Monte Carlo analysis.
///
/// # Arguments
/// * `trades` - Slice of completed trade PnL results.
/// * `initial_equity` - Starting equity for each simulated permutation.
/// * `iterations` - Number of shuffle iterations (typically 1,000).
/// * `seed` - Optional deterministic seed for 100% reproducible audit.
///
/// # Errors
/// Returns [`EngineError::EmptyTradeHistory`] if `trades` is empty or `initial_equity <= 0.0`.
/// Returns [`EngineError::CalculationError`] if `iterations == 0`.
pub fn run_monte_carlo(
    trades: &[PnlResult],
    initial_equity: f64,
    iterations: usize,
    seed: Option<u64>,
) -> Result<MonteCarloResult, EngineError> {
    if trades.is_empty() || !initial_equity.is_finite() || initial_equity <= 0.0 {
        return Err(EngineError::EmptyTradeHistory);
    }
    if iterations == 0 {
        return Err(EngineError::CalculationError(
            "Iterations must be greater than zero".to_string(),
        ));
    }

    let seed_val = seed.unwrap_or(DEFAULT_MC_SEED);
    let mut rng = Xoshiro256StarStar::seed_from_u64(seed_val);

    let mut max_dd_list = Vec::with_capacity(iterations);

    for _ in 0..iterations {
        let mut shuffled = trades.to_vec();
        shuffled.shuffle(&mut rng);

        // Simulate equity curve
        let mut equity = initial_equity;
        let mut peak = initial_equity;
        let mut max_dd_pct = 0.0;

        for trade in &shuffled {
            equity += trade.net_pnl_usd;
            if equity > peak {
                peak = equity;
            }
            let dd = if peak > 0.0 {
                (peak - equity) / peak * 100.0
            } else {
                0.0
            };
            if dd > max_dd_pct {
                max_dd_pct = dd;
            }
        }

        max_dd_list.push(max_dd_pct);
    }

    // Sort drawdowns in ascending order
    max_dd_list.sort_by(|a, b| match a.partial_cmp(b) {
        Some(ord) => ord,
        None => std::cmp::Ordering::Equal,
    });

    let n = max_dd_list.len();
    let median_idx = ((n as f64) * 0.50).floor() as usize;
    let p95_idx = ((n as f64) * 0.95).floor() as usize;
    let p99_idx = ((n as f64) * 0.99).floor() as usize;

    let median_max_dd_pct = max_dd_list[median_idx.min(n - 1)];
    let percentile_95_max_dd_pct = max_dd_list[p95_idx.min(n - 1)];
    let percentile_99_max_dd_pct = max_dd_list[p99_idx.min(n - 1)];

    let ruin_count = max_dd_list.iter().filter(|&&dd| dd >= 10.0).count();
    let risk_of_ruin_10pct_dd = ruin_count as f64 / n as f64;

    Ok(MonteCarloResult {
        iterations,
        median_max_dd_pct,
        percentile_95_max_dd_pct,
        percentile_99_max_dd_pct,
        risk_of_ruin_10pct_dd,
    })
}
