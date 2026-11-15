//+------------------------------------------------------------------+
//|                                                    AeternaEA.mq5 |
//|                                AETERNA Quant Institutional Engine|
//|                        Copyright 2026, AETERNA Quant Project     |
//|                                                                  |
//|  *** FROZEN GOLDEN BASELINE v1.0 — DO NOT MODIFY DIRECTLY ***     |
//|  Verified Performance (2020-2024): 813 Trades, 58.67% Win Rate,   |
//|  +$436.67 USD Net Profit, 8.16% Max DD.                          |
//|  Any future experimentation MUST be done in a separate clone!    |
//+------------------------------------------------------------------+
#property copyright "Copyright 2026, AETERNA Quant Project"
#property link      "https://aeterna-quant.internal"
#property version   "1.00"
#property strict

#include <Trade\Trade.mqh>
#include "Include\Invariants.mqh"
#include "Include\RiskManager.mqh"
#include "Include\StateMachine.mqh"
#include "Include\CalendarFilter.mqh"
#include "Include\ExitManager.mqh"
#include "Include\RegimeDetector.mqh"
#include "Include\StrategyBreakout.mqh"
#include "Include\StrategyMomentum.mqh"
#include "Include\StrategyAsianRange.mqh"

//--- Inputs
input group "=== AETERNA OPERATIONAL PROFILE ==="
input ENUM_STRATEGY_PROFILE InpProfile             = PROFILE_DAY_TRADING;   // Active Strategy Profile
input bool                  InpDryRun              = false;                 // Dry-Run Mode (Simulation Log Only)
input bool                  InpEnforceNewsFilter   = true;                  // Enforce News State Machine Gating
input int                   InpSlippageTolerancePts= 50;                    // Slippage Tolerance (Points)
input ulong                 InpMagicNumber         = MAGIC_AETERNA_DAY;     // EA Magic Identifier

input group "=== STRATEGY PARAMETERS (SWEEP / GENETIC OPTIMIZATION) ==="
input int                   InpDonchianPeriod      = 24;                    // Donchian Breakout Channel Period (Bars)
input double                InpAtrMultiplier       = 1.6;                   // ATR Stop Loss Multiplier
input double                InpRewardRiskRatio     = 2.6;                   // Reward-to-Risk Ratio (R:R >= 2.0)

//--- Engine Components
CRiskManager        *g_risk;
CSpreadStateMachine *g_state_machine;
CCalendarFilter     *g_calendar;
CExitManager        *g_exit_manager;
CRegimeDetector     *g_regime_detector;
CStrategyBreakout   *g_breakout;
CStrategyMomentum   *g_momentum;
CStrategyAsianRange *g_asian_range;
CTrade               g_trade;

//--- State tracking
datetime             g_last_bar_time = 0;
ENUM_TIMEFRAMES      g_active_tf;

//+------------------------------------------------------------------+
//| Expert initialization function                                   |
//+------------------------------------------------------------------+
int OnInit()
{
   Print("================================================================================");
   Print("AETERNA QUANT EXPERT ADVISOR -- INITIALIZING MQL5 ENGINE");
   Print("================================================================================");

   // Configure active timeframe based on selected profile
   if(InpProfile == PROFILE_SESSION_MOMENTUM || InpProfile == PROFILE_ASIAN_RANGE)
      g_active_tf = PERIOD_M5;
   else
      g_active_tf = PERIOD_M15;

   PrintFormat("[INIT] Selected Profile: %s, Active Timeframe: %s, Symbol: %s",
               EnumToString(InpProfile), EnumToString(g_active_tf), _Symbol);

   // Check account details
   double equity = AccountInfoDouble(ACCOUNT_EQUITY);
   PrintFormat("[INIT] Account Equity: %.2f USD, Leverage: 1:%d, Server: %s",
               equity, (int)AccountInfoInteger(ACCOUNT_LEVERAGE), AccountInfoString(ACCOUNT_SERVER));

   if(equity < 1000.0)
   {
      PrintFormat("[WARNING] Account Equity (%.2f USD) is below recommended $1,000 USD floor.", equity);
   }

   // Initialize components
   g_risk            = new CRiskManager(InpMagicNumber, _Symbol);
   g_state_machine   = new CSpreadStateMachine(_Symbol, EWMA_ALPHA, 30);
   g_calendar        = new CCalendarFilter(InpEnforceNewsFilter);
   g_exit_manager    = new CExitManager(InpMagicNumber, _Symbol, InpSlippageTolerancePts);
   g_regime_detector = new CRegimeDetector(_Symbol);
   g_breakout        = new CStrategyBreakout(_Symbol, InpDonchianPeriod, InpAtrMultiplier, InpRewardRiskRatio);
   g_momentum        = new CStrategyMomentum(_Symbol, 10, 1.5);
   g_asian_range     = new CStrategyAsianRange(_Symbol, 350.0);

   g_risk.Init();
   g_state_machine.Init();
   g_calendar.Init();

   if(!g_regime_detector.Init())
   {
      Print("[FATAL] Failed to initialize RegimeDetector. Aborting.");
      return INIT_FAILED;
   }

   if((InpProfile == PROFILE_DAY_TRADING || InpProfile == PROFILE_MULTI_SESSION_HYBRID) && !g_breakout.Init())
   {
      Print("[FATAL] Failed to initialize StrategyBreakout. Aborting.");
      return INIT_FAILED;
   }

   if(InpProfile == PROFILE_SESSION_MOMENTUM && !g_momentum.Init())
   {
      Print("[FATAL] Failed to initialize StrategyMomentum. Aborting.");
      return INIT_FAILED;
   }

   if((InpProfile == PROFILE_ASIAN_RANGE || InpProfile == PROFILE_MULTI_SESSION_HYBRID) && !g_asian_range.Init())
   {
      Print("[FATAL] Failed to initialize StrategyAsianRange. Aborting.");
      return INIT_FAILED;
   }

   g_trade.SetExpertMagicNumber(InpMagicNumber);
   g_trade.SetDeviationInPoints(InpSlippageTolerancePts);
   g_trade.SetTypeFilling(ORDER_FILLING_IOC);

   g_last_bar_time = 0;
   Print("[INIT] AeternaEA initialized successfully. State Machine active.");
   return INIT_SUCCEEDED;
}

//+------------------------------------------------------------------+
//| Expert deinitialization function                                 |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   PrintFormat("[DEINIT] AeternaEA deinitializing. Reason: %d", reason);

   if(CheckPointer(g_asian_range) == POINTER_DYNAMIC)     { g_asian_range.Deinit(); delete g_asian_range; }
   if(CheckPointer(g_breakout) == POINTER_DYNAMIC)        { g_breakout.Deinit(); delete g_breakout; }
   if(CheckPointer(g_momentum) == POINTER_DYNAMIC)        { g_momentum.Deinit(); delete g_momentum; }
   if(CheckPointer(g_regime_detector) == POINTER_DYNAMIC) { g_regime_detector.Deinit(); delete g_regime_detector; }
   if(CheckPointer(g_exit_manager) == POINTER_DYNAMIC)    delete g_exit_manager;
   if(CheckPointer(g_calendar) == POINTER_DYNAMIC)        delete g_calendar;
   if(CheckPointer(g_state_machine) == POINTER_DYNAMIC)   delete g_state_machine;
   if(CheckPointer(g_risk) == POINTER_DYNAMIC)            delete g_risk;
}

//+------------------------------------------------------------------+
//| Expert tick function                                             |
//+------------------------------------------------------------------+
void OnTick()
{
   datetime now = TimeCurrent();

   // 1. Tick Data and Spread Calculation
   double spread_pts = (double)SymbolInfoInteger(_Symbol, SYMBOL_SPREAD);
   bool in_news_blackout = g_calendar.IsInNewsBlackout(now);

   // Update Spread EWMA State Machine
   ENUM_SYSTEM_STATE sys_state = g_state_machine.Update(spread_pts, now, in_news_blackout);

   // 2. Classify Current H4 Regime
   ENUM_MARKET_REGIME current_regime = g_regime_detector.ClassifyCurrentRegime();

   // 3. Active 5-Layer Exit Management on Every Tick
   g_exit_manager.MonitorActivePositions(now, g_active_tf, current_regime, false);

   // 4. Bar-Close Gate: Strategy evaluates strictly on newly completed bar
   datetime current_bar_time = iTime(_Symbol, g_active_tf, 0);
   if(current_bar_time == g_last_bar_time)
      return; // Already processed this bar, wait for next close

   g_last_bar_time = current_bar_time;

   // 5. Pre-Trade Gate 1: Check System State Machine
   if(sys_state != STATE_NORMAL)
   {
      PrintFormat("[GATE] Entry Blocked: State is %s (Spread Z-score: %.2f)",
                  EnumToString(sys_state), g_state_machine.GetZScore());
      return;
   }

   // 6. Pre-Trade Gate 2: Check Pre-News Blackout Window
   if(g_calendar.IsInPreNewsWindow(now))
   {
      Print("[GATE] Entry Blocked: In Scheduled Pre-News Window (T-10m).");
      return;
   }

   // 7. Pre-Trade Gate 3: Check Financial Risk Limits
   string block_reason = "";
   if(!g_risk.CanOpenNewPosition(now, block_reason))
   {
      PrintFormat("[GATE] Entry Blocked by Risk Gate: %s", block_reason);
      return;
   }

   // 8. Strategy Evaluation
   double sl_pts = 0.0, tp_pts = 0.0;
   string setup_reason = "";
   ENUM_TRADE_DIRECTION dir = DIR_NONE;

   if(InpProfile == PROFILE_DAY_TRADING)
   {
      dir = g_breakout.Evaluate(now, current_regime, sl_pts, tp_pts, setup_reason);
   }
   else if(InpProfile == PROFILE_SESSION_MOMENTUM)
   {
      dir = g_momentum.Evaluate(now, current_regime, sl_pts, tp_pts, setup_reason);
   }
   else if(InpProfile == PROFILE_ASIAN_RANGE)
   {
      dir = g_asian_range.Evaluate(now, spread_pts, current_regime, sl_pts, tp_pts, setup_reason);
   }
   else if(InpProfile == PROFILE_MULTI_SESSION_HYBRID)
   {
      // Check Post-Rollover Asian Range Window (01:15 - 03:45 Server Time)
      if(g_asian_range.IsInAsianWindow(now))
      {
         dir = g_asian_range.Evaluate(now, spread_pts, current_regime, sl_pts, tp_pts, setup_reason);
      }
      else
      {
         // London / NY Hours: Trend Breakout
         dir = g_breakout.Evaluate(now, current_regime, sl_pts, tp_pts, setup_reason);
      }
   }

   if(dir == DIR_NONE)
      return; // No setup on this bar

   // 9. Pre-Trade Gate 4: Dynamic Lot Sizing & Invariant Verification
   double lot = g_risk.CalculateLotSize(sl_pts, false);
   if(lot <= 0.0)
   {
      PrintFormat("[GATE] Entry Blocked: Calculated Lot (%.4f) below minimum or 0.5%% risk budget exceeded.", lot);
      return;
   }

   // Calculate Price Geometry with strict server-side SL/TP
   double point = SymbolInfoDouble(_Symbol, SYMBOL_POINT);
   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);

   double entry_price = 0.0;
   double sl_price = 0.0;
   double tp_price = 0.0;

   if(dir == DIR_BUY)
   {
      entry_price = ask;
      sl_price = NormalizeDouble(entry_price - (sl_pts * point), _Digits);
      tp_price = NormalizeDouble(entry_price + (tp_pts * point), _Digits);
   }
   else if(dir == DIR_SELL)
   {
      entry_price = bid;
      sl_price = NormalizeDouble(entry_price + (sl_pts * point), _Digits);
      tp_price = NormalizeDouble(entry_price - (tp_pts * point), _Digits);
   }

   // Validate R:R Invariant (>= 2.0)
   double actual_rr = (MathAbs(entry_price - tp_price) / MathAbs(entry_price - sl_price));
   if(actual_rr < (MIN_REWARD_RISK_RATIO - 0.01))
   {
      PrintFormat("[GATE] Entry Blocked: R:R ratio %.2f < 2.0 invariant.", actual_rr);
      return;
   }

   PrintFormat("[SIGNAL APPROVED] %s %s on %s | Lot: %.2f | Entry: %.2f | SL: %.2f | TP: %.2f | R:R: %.2f | Reason: %s",
               EnumToString(InpProfile), (dir == DIR_BUY ? "BUY" : "SELL"), _Symbol,
               lot, entry_price, sl_price, tp_price, actual_rr, setup_reason);

   // 10. Broker Execution Bridge
   if(InpDryRun)
   {
      PrintFormat("[DRY-RUN] Order simulation only. No live market order sent to broker.");
      g_risk.IncrementTradeCount();
      return;
   }

   bool success = false;
   if(dir == DIR_BUY)
   {
      success = g_trade.Buy(lot, _Symbol, entry_price, sl_price, tp_price, "Aeterna [DAY]");
   }
   else if(dir == DIR_SELL)
   {
      success = g_trade.Sell(lot, _Symbol, entry_price, sl_price, tp_price, "Aeterna [DAY]");
   }

   if(success)
   {
      g_risk.IncrementTradeCount();
      PrintFormat("[EXECUTION] Order Successfully Executed. Ticket: %d", (int)g_trade.ResultOrder());
   }
   else
   {
      PrintFormat("[EXECUTION ERROR] OrderSend Failed: Retcode=%d (%s)",
                  g_trade.ResultRetcode(), g_trade.ResultRetcodeDescription());
   }
}

//+------------------------------------------------------------------+
//| Tester custom optimization criterion function                    |
//+------------------------------------------------------------------+
double OnTester()
{
   double profit = TesterStatistics(STAT_PROFIT);
   double max_dd = TesterStatistics(STAT_EQUITY_DDREL_PERCENT);
   if(max_dd <= 0.0) return 0.0;
   return (profit / max_dd); // Calmar-like proxy: Net Profit divided by Max Equity DD %
}
