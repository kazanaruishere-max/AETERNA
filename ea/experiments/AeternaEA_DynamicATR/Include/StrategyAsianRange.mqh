//+------------------------------------------------------------------+
//|                                           StrategyAsianRange.mqh |
//|        AETERNA Quant Strategy 3: Post-Rollover Asian Range Scalp |
//|                        Copyright 2026, AETERNA Quant Project     |
//+------------------------------------------------------------------+
#property copyright "Copyright 2026, AETERNA Quant Project"
#property link      "https://aeterna-quant.internal"
#property strict

#include "Invariants.mqh"

class CStrategyAsianRange
{
private:
   string            m_symbol;
   int               m_bb_handle;
   int               m_rsi_handle;
   int               m_atr_handle;
   int               m_start_hour;
   int               m_start_min;
   int               m_end_hour;
   int               m_end_min;
   double            m_max_spread_pts;

public:
   CStrategyAsianRange(string symbol, double max_spread_pts = 350.0)
      : m_symbol(symbol),
        m_max_spread_pts(max_spread_pts),
        m_bb_handle(INVALID_HANDLE),
        m_rsi_handle(INVALID_HANDLE),
        m_atr_handle(INVALID_HANDLE),
        m_start_hour(0),   // 00:30 Server Time (after rollover spread peak)
        m_start_min(30),
        m_end_hour(4),     // 04:00 Server Time
        m_end_min(0)
   {
   }

   bool Init()
   {
      m_bb_handle  = iBands(m_symbol, PERIOD_M5, 20, 0, 2.0, PRICE_CLOSE);
      m_rsi_handle = iRSI(m_symbol, PERIOD_M5, 14, PRICE_CLOSE);
      m_atr_handle = iATR(m_symbol, PERIOD_M5, ATR_PERIOD);

      if(m_bb_handle == INVALID_HANDLE || m_rsi_handle == INVALID_HANDLE || m_atr_handle == INVALID_HANDLE)
      {
         PrintFormat("[STRATEGY ASIAN] M5 indicator handle creation failed: %d", GetLastError());
         return false;
      }
      return true;
   }

   void Deinit()
   {
      if(m_bb_handle != INVALID_HANDLE)  IndicatorRelease(m_bb_handle);
      if(m_rsi_handle != INVALID_HANDLE) IndicatorRelease(m_rsi_handle);
      if(m_atr_handle != INVALID_HANDLE) IndicatorRelease(m_atr_handle);
   }

   //--- Verify whether current time is within safe Asian night range window
   bool IsInAsianWindow(datetime current_time)
   {
      MqlDateTime dt;
      TimeToStruct(current_time, dt);

      int current_mins = dt.hour * 60 + dt.min;
      int start_mins   = m_start_hour * 60 + m_start_min;
      int end_mins     = m_end_hour * 60 + m_end_min;

      return (current_mins >= start_mins && current_mins < end_mins);
   }

   //--- Evaluate latest closed M5 bar for Asian Range Mean-Reversion
   ENUM_TRADE_DIRECTION Evaluate(datetime current_time,
                                 double current_spread_pts,
                                 ENUM_MARKET_REGIME h4_regime,
                                 double &sl_points,
                                 double &tp_points,
                                 string &reason)
   {
      sl_points = 0.0;
      tp_points = 0.0;

      // 1. Session Timing Filter: 00:30 to 04:00 Server Time
      if(!IsInAsianWindow(current_time))
      {
         reason = "OUTSIDE_ASIAN_WINDOW";
         return DIR_NONE;
      }

      // 2. Hard Spread Cut-Off Filter: Maximum 350 points ($0.35)
      if(current_spread_pts > m_max_spread_pts)
      {
         reason = StringFormat("SPREAD_TOO_HIGH: %.1f > %.1f pts", current_spread_pts, m_max_spread_pts);
         return DIR_NONE;
      }

      // 3. Fetch Indicator Buffers on closed bar 1
      double bb_mid[1], bb_up[1], bb_low[1], rsi_val[1], atr_val[1];

      if(CopyBuffer(m_bb_handle, 0, 1, 1, bb_mid) <= 0 ||
         CopyBuffer(m_bb_handle, 1, 1, 1, bb_up)  <= 0 ||
         CopyBuffer(m_bb_handle, 2, 1, 1, bb_low) <= 0 ||
         CopyBuffer(m_rsi_handle, 0, 1, 1, rsi_val) <= 0 ||
         CopyBuffer(m_atr_handle, 0, 1, 1, atr_val) <= 0)
      {
         reason = "INSUFFICIENT_INDICATOR_DATA";
         return DIR_NONE;
      }

      // 4. Fetch closed bar 1 rate
      MqlRates rates[1];
      if(CopyRates(m_symbol, PERIOD_M5, 1, 1, rates) < 1)
      {
         reason = "INSUFFICIENT_M5_RATE";
         return DIR_NONE;
      }

      double close_px = rates[0].close;
      double low_px   = rates[0].low;
      double high_px  = rates[0].high;
      double rsi      = rsi_val[0];
      double atr      = atr_val[0];
      double point    = SymbolInfoDouble(m_symbol, SYMBOL_POINT);

      double final_sl_distance = MathMax(atr * ATR_SL_MULTIPLIER, MIN_SL_DISTANCE_DOLLARS);
      double final_sl_pts      = final_sl_distance / point;
      double final_tp_pts      = final_sl_pts * 2.0; // R:R >= 2.0

      // Oversold Mean-Reversion (Low touches lower band and RSI <= 40)
      if((low_px <= bb_low[0] || close_px <= bb_low[0]) && rsi <= 40.0 && h4_regime != REGIME_BEARISH_TRENDING)
      {
         sl_points = final_sl_pts;
         tp_points = final_tp_pts;
         reason = StringFormat("ASIAN_OVERSOLD_REBOUND: Low(%.2f) <= BB_Low(%.2f), RSI=%.1f <= 40",
                               low_px, bb_low[0], rsi);
         return DIR_BUY;
      }

      // Overbought Mean-Reversion (High touches upper band and RSI >= 60)
      if((high_px >= bb_up[0] || close_px >= bb_up[0]) && rsi >= 60.0 && h4_regime != REGIME_BULLISH_TRENDING)
      {
         sl_points = final_sl_pts;
         tp_points = final_tp_pts;
         reason = StringFormat("ASIAN_OVERBOUGHT_REBOUND: High(%.2f) >= BB_Up(%.2f), RSI=%.1f >= 60",
                               high_px, bb_up[0], rsi);
         return DIR_SELL;
      }

      reason = "NO_ASIAN_SETUP";
      return DIR_NONE;
   }
};
