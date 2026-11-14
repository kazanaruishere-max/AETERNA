//+------------------------------------------------------------------+
//|                                                   Invariants.mqh |
//|                                  AETERNA Quant Institutional SSoT |
//|                        Copyright 2026, AETERNA Quant Project     |
//+------------------------------------------------------------------+
#property copyright "Copyright 2026, AETERNA Quant Project"
#property link      "https://aeterna-quant.internal"
#property strict

//--- Hard Financial Risk Invariants (Strict 0.00% Tolerance)
#define RISK_PER_TRADE_PCT         0.005    // Exactly 0.5% of current equity per setup
#define MAX_DAILY_LOSS_PCT         0.020    // 2.0% circuit breaker harian
#define MAX_DRAWDOWN_KILLSWITCH    0.100    // 10.0% hard drawdown from peak equity
#define MAX_CONCURRENT_POSITIONS   1        // Exactly 1 open position at any time
#define MAX_TRADES_PER_DAY         5        // Maximum 5 closed/opened trades per day
#define MIN_REWARD_RISK_RATIO      2.0      // Minimum Reward-to-Risk ratio >= 2.0

//--- Microstructure Constants for XAUUSD
#define MIN_SL_DISTANCE_DOLLARS    2.50     // Minimum SL $2.50 (250 points) to avoid spread friction
#define ATR_SL_MULTIPLIER          1.5      // SL = 1.5 * ATR(14)
#define ATR_PERIOD                 14       // ATR indicator period
#define TIME_INVALIDATION_BARS     24       // 24 closed bars (6 hours on M15) to allow full session trend expansion
#define EWMA_ALPHA                 0.08     // Smoothing factor for spread baseline
#define Z_THRESHOLD_PAUSE          3.0      // Spike Z >= 3.0 halts new entries
#define Z_THRESHOLD_RESUME         1.5      // Z < 1.5 calm threshold
#define K_STABLE_READS             12       // K=12 consecutive calm readings
#define M_STABILITY_SECONDS        300      // 5 minutes stability required

//--- Magic Numbers & Identifiers
#define MAGIC_AETERNA_HYBRID       20261100
#define MAGIC_AETERNA_DAY          20261101
#define MAGIC_AETERNA_SCALP        20261102
#define MAGIC_AETERNA_ASIAN        20261103

//--- Strategy Profile Selection
enum ENUM_STRATEGY_PROFILE
{
   PROFILE_DAY_TRADING = 0,         // M15 Volatility Breakout (Donchian 20 + ATR expansion + H4 Trend)
   PROFILE_SESSION_MOMENTUM = 1,     // M5 NY/London Momentum Burst (SL >= $2.50, Compounding)
   PROFILE_ASIAN_RANGE = 2,          // M15 Post-Rollover Asian Range Scalper (01:15-03:45, Spread <= 25)
   PROFILE_MULTI_SESSION_HYBRID = 3  // Multi-Session Hybrid (All Sessions: Trend in London/NY, Range in Asia)
};

//--- Market Regime Classification
enum ENUM_MARKET_REGIME
{
   REGIME_BULLISH_TRENDING = 0,
   REGIME_BEARISH_TRENDING = 1,
   REGIME_RANGING_CONFIRMED = 2,
   REGIME_AMBIGUOUS = 3
};

//--- News and Volatility State Machine States
enum ENUM_SYSTEM_STATE
{
   STATE_NORMAL = 0,
   STATE_PRE_NEWS_WATCH = 1,
   STATE_PAUSED = 2,
   STATE_RECOVERY_CHECK = 3
};

//--- Signal Direction
enum ENUM_TRADE_DIRECTION
{
   DIR_NONE = 0,
   DIR_BUY  = 1,
   DIR_SELL = 2
};
