//+------------------------------------------------------------------+
//|                                             StrategyBreakout.mqh |
//|        AETERNA Quant Strategy 1: Trend Pullback & Breakout Engine |
//|                        Copyright 2026, AETERNA Quant Project     |
//+------------------------------------------------------------------+
#property copyright "Copyright 2026, AETERNA Quant Project"
#property link      "https://aeterna-quant.internal"
#property strict

#include "Invariants.mqh"

class CStrategyBreakout
{
private:
   string            m_symbol;
   int               m_donchian_period;
   int               m_atr_handle;
   int               m_ema20_handle;
   int               m_ema50_handle;
   int               m_rsi_handle;

public:
   CStrategyBreakout(string symbol, int donchian_period = 20)
      : m_symbol(symbol),
        m_donchian_period(donchian_period),
        m_atr_handle(INVALID_HANDLE),
        m_ema20_handle(INVALID_HANDLE),
        m_ema50_handle(INVALID_HANDLE),
        m_rsi_handle(INVALID_HANDLE)
   {
   }

   bool Init()
   {
      m_atr_handle   = iATR(m_symbol, PERIOD_M15, ATR_PERIOD);
      m_ema20_handle = iMA(m_symbol, PERIOD_M15, 20, 0, MODE_EMA, PRICE_CLOSE);
      m_ema50_handle = iMA(m_symbol, PERIOD_M15, 50, 0, MODE_EMA, PRICE_CLOSE);
      m_rsi_handle   = iRSI(m_symbol, PERIOD_M15, 14, PRICE_CLOSE);

      if(m_atr_handle == INVALID_HANDLE || m_ema20_handle == INVALID_HANDLE ||
         m_ema50_handle == INVALID_HANDLE || m_rsi_handle == INVALID_HANDLE)
      {
         PrintFormat("[STRATEGY BREAKOUT] Error creating indicator handles: %d", GetLastError());
         return false;
      }
      return true;
   }

   void Deinit()
   {
      if(m_atr_handle != INVALID_HANDLE)   IndicatorRelease(m_atr_handle);
      if(m_ema20_handle != INVALID_HANDLE) IndicatorRelease(m_ema20_handle);
      if(m_ema50_handle != INVALID_HANDLE) IndicatorRelease(m_ema50_handle);
      if(m_rsi_handle != INVALID_HANDLE)   IndicatorRelease(m_rsi_handle);
   }

   //--- Verify whether current time is within high-liquidity London or NY session
   bool IsInActiveSession(datetime current_time)
   {
      MqlDateTime dt;
      TimeToStruct(current_time, dt);

      int current_mins = dt.hour * 60 + dt.min;

      // Active London & New York Continuous Corridor: 07:00 - 17:00 UTC (14:00 - 00:00 WIB)
      int session_start = 7 * 60 + 0;   // 07:00 UTC
      int session_end   = 17 * 60 + 0;  // 17:00 UTC

      return (current_mins >= session_start && current_mins < session_end);
   }

   //--- Evaluate latest closed M15 bar for Trend Continuation & Breakout
   ENUM_TRADE_DIRECTION Evaluate(datetime current_time, ENUM_MARKET_REGIME h4_regime, double &sl_points, double &tp_points, string &reason)
   {
      sl_points = 0.0;
      tp_points = 0.0;

      // 1. Session Timing Filter: Must be in active London or NY session
      if(!IsInActiveSession(current_time))
      {
         reason = "OUTSIDE_ACTIVE_SESSION";
         return DIR_NONE;
      }

      // 2. Regime Filter Gate: Must be strongly trending on H4
      if(h4_regime != REGIME_BULLISH_TRENDING && h4_regime != REGIME_BEARISH_TRENDING)
      {
         reason = "H4_REGIME_NOT_TRENDING";
         return DIR_NONE;
      }

      // 3. Fetch price data for previous closed M15 bars
      MqlRates rates[];
      ArraySetAsSeries(rates, true);
      if(CopyRates(m_symbol, PERIOD_M15, 1, m_donchian_period + 2, rates) < (m_donchian_period + 2))
      {
         reason = "INSUFFICIENT_M15_RATES";
         return DIR_NONE;
      }

      // 4. Fetch indicators
      double atr_buf[1], ema20_buf[1], ema50_buf[1], rsi_buf[1];
      if(CopyBuffer(m_atr_handle, 0, 1, 1, atr_buf) < 1 ||
         CopyBuffer(m_ema20_handle, 0, 1, 1, ema20_buf) < 1 ||
         CopyBuffer(m_ema50_handle, 0, 1, 1, ema50_buf) < 1 ||
         CopyBuffer(m_rsi_handle, 0, 1, 1, rsi_buf) < 1)
      {
         reason = "INSUFFICIENT_INDICATOR_BUFFERS";
         return DIR_NONE;
      }

      double current_atr = atr_buf[0];
      double ema20 = ema20_buf[0];
      double ema50 = ema50_buf[0];
      double rsi   = rsi_buf[0];
      double point = SymbolInfoDouble(m_symbol, SYMBOL_POINT);

      // Distance calculation: SL = 1.5 * ATR(14), floored at $2.50
      double calculated_sl_distance = current_atr * ATR_SL_MULTIPLIER;
      double min_sl_distance = MIN_SL_DISTANCE_DOLLARS;
      double final_sl_distance = MathMax(calculated_sl_distance, min_sl_distance);
      double final_sl_pts = final_sl_distance / point;
      double final_tp_pts = final_sl_pts * 2.5; // Asymmetric 2.5:1 reward

      // 5. Calculate Donchian Channel on bars 2 to 21
      double donchian_high = -1.0;
      double donchian_low  = 999999.0;
      for(int i = 1; i <= m_donchian_period; i++)
      {
         if(rates[i].high > donchian_high) donchian_high = rates[i].high;
         if(rates[i].low < donchian_low)   donchian_low  = rates[i].low;
      }

      double bar1_close = rates[0].close;
      double bar1_open  = rates[0].open;
      double bar1_low   = rates[0].low;
      double bar1_high  = rates[0].high;
      double bar2_low   = rates[1].low;
      double bar2_high  = rates[1].high;

      // Extension filter: Prevent chasing tops/bottoms when stretched > 1.5 ATR from EMA20
      bool overextended_bull = (bar1_close - ema20) > (1.5 * current_atr);
      bool overextended_bear = (ema20 - bar1_close) > (1.5 * current_atr);

      // Volume confirmation: Avoid dry-volume false moves
      long sum_vol = 0;
      for(int i = 0; i < 20; i++)
         sum_vol += rates[i].tick_volume;
      double avg_vol = (double)sum_vol / 20.0;
      bool vol_confirmed = (rates[0].tick_volume >= (avg_vol * 1.05));

      // Bullish Trend Check: H4 Bullish & M15 EMA20 > EMA50 & RSI >= 50 & Not Overextended
      if(h4_regime == REGIME_BULLISH_TRENDING && ema20 > ema50 && rsi >= 50.0 && !overextended_bull)
      {
         // Confluence A: Donchian 20 Breakout with Volume Surge
         bool breakout_buy = (bar1_close > donchian_high && bar1_close > bar1_open && rates[0].tick_volume >= (avg_vol * 1.15));

         // Confluence B: Confirmed Pullback Turnaround (Dip touched EMA20 zone, then closed above bar 2 high with volume)
         bool pullback_buy = (bar2_low <= ema20 && bar1_close > bar2_high && bar1_close > bar1_open && vol_confirmed);

         if(breakout_buy || pullback_buy)
         {
            // For pullback, tighter structural SL under swing low allows faster compounding
            if(pullback_buy)
            {
               double swing_dist = (bar1_close - bar2_low) + (0.2 * current_atr);
               double p_sl = MathMin(MathMax(swing_dist, MIN_SL_DISTANCE_DOLLARS), 3.50);
               sl_points = p_sl / point;
               tp_points = sl_points * 2.5;
            }
            else
            {
               sl_points = final_sl_pts;
               tp_points = final_tp_pts;
            }
            reason = breakout_buy ? "BULLISH_DONCHIAN_BREAKOUT" : "BULLISH_CONFIRMED_PULLBACK";
            return DIR_BUY;
         }
      }

      // Bearish Trend Check: H4 Bearish & M15 EMA20 < EMA50 & RSI <= 50 & Not Overextended
      if(h4_regime == REGIME_BEARISH_TRENDING && ema20 < ema50 && rsi <= 50.0 && !overextended_bear)
      {
         // Confluence A: Donchian 20 Breakdown with Volume Surge
         bool breakout_sell = (bar1_close < donchian_low && bar1_close < bar1_open && rates[0].tick_volume >= (avg_vol * 1.15));

         // Confluence B: Confirmed Pullback Turnaround (Rally touched EMA20 zone, then closed below bar 2 low with volume)
         bool pullback_sell = (bar2_high >= ema20 && bar1_close < bar2_low && bar1_close < bar1_open && vol_confirmed);

         if(breakout_sell || pullback_sell)
         {
            if(pullback_sell)
            {
               double swing_dist = (bar2_high - bar1_close) + (0.2 * current_atr);
               double p_sl = MathMin(MathMax(swing_dist, MIN_SL_DISTANCE_DOLLARS), 3.50);
               sl_points = p_sl / point;
               tp_points = sl_points * 2.5;
            }
            else
            {
               sl_points = final_sl_pts;
               tp_points = final_tp_pts;
            }
            reason = breakout_sell ? "BEARISH_DONCHIAN_BREAKOUT" : "BEARISH_CONFIRMED_PULLBACK";
            return DIR_SELL;
         }
      }

      reason = "NO_TREND_CONFLUENCE";
      return DIR_NONE;
   }
};
