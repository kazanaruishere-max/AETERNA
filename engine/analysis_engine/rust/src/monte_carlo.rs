//! Monte Carlo Trade Sequence Shuffling (`monte_carlo.rs`).
//!
//! Provides deterministic trade sequence shuffling over 1,000 iterations to evaluate
//! drawdown percentiles and risk of ruin against the 10.0% project killswitch threshold.

use crate::types::{EngineError, MonteCarloResult, PnlResult};

/// Deterministic 64-bit Xorshift64* PRNG for reproducible Monte Carlo trade sequence shuffling.
struct Xorshift64Star {
    state: u64,
}

impl Xorshift64Star {
    fn new(seed: u64) -> Self {
        // Guarantee non-zero internal state
        let state = if seed == 0 {
            0x4D59_5354_4943_5F31
        } else {
            seed
        };
        Self { state }
    }

    fn next_u64(&mut self) -> u64 {
        let mut x = self.state;
        x ^= x << 13;
        x ^= x >> 7;
        x ^= x << 17;
        self.state = x;
        x.wrapping_mul(0x2545_F491_4F6C_DD1D)
    }

    fn next_usize(&mut self, bound: usize) -> usize {
        if bound <= 1 {
            return 0;
        }
        (self.next_u64() % (bound as u64)) as usize
    }
}

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

    let seed_val = seed.unwrap_or(0x4D59_5354_4943_5F31);
    let mut rng = Xorshift64Star::new(seed_val);

    let mut max_dd_list = Vec::with_capacity(iterations);

    for _ in 0..iterations {
        let mut shuffled = trades.to_vec();

        // Fisher-Yates shuffle
        for i in (1..shuffled.len()).rev() {
            let j = rng.next_usize(i + 1);
            shuffled.swap(i, j);
        }

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
