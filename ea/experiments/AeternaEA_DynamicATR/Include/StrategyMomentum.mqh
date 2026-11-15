//+------------------------------------------------------------------+
//|                                             StrategyMomentum.mqh |
//|        AETERNA Quant Strategy 2: M5 Session Momentum Engine       |
//|                        Copyright 2026, AETERNA Quant Project     |
//+------------------------------------------------------------------+
#property copyright "Copyright 2026, AETERNA Quant Project"
#property link      "https://aeterna-quant.internal"
#property strict

#include "Invariants.mqh"

class CStrategyMomentum
{
private:
   string            m_symbol;
   int               m_lookback_bars;
   int               m_atr_handle;
   int               m_ema_h1_handle;
   double            m_volume_mult;
   int               m_start_hour_utc;
   int               m_start_min_utc;
   int               m_end_hour_utc;
   int               m_end_min_utc;

public:
   CStrategyMomentum(string symbol, int lookback_bars = 10, double volume_mult = 1.5)
      : m_symbol(symbol),
        m_lookback_bars(lookback_bars),
        m_volume_mult(volume_mult),
        m_atr_handle(INVALID_HANDLE),
        m_ema_h1_handle(INVALID_HANDLE),
        m_start_hour_utc(12), // 12:30 UTC = 19:30 WIB (NY Open crossover)
        m_start_min_utc(30),
        m_end_hour_utc(16),   // 16:00 UTC = 23:00 WIB
        m_end_min_utc(0)
   {
   }

   bool Init()
   {
      m_atr_handle = iATR(m_symbol, PERIOD_M5, ATR_PERIOD);
      m_ema_h1_handle = iMA(m_symbol, PERIOD_H1, 50, 0, MODE_EMA, PRICE_CLOSE);
      if(m_atr_handle == INVALID_HANDLE || m_ema_h1_handle == INVALID_HANDLE)
      {
         PrintFormat("[STRATEGY MOMENTUM] Error creating M5 ATR or H1 EMA handle: %d", GetLastError());
         return false;
      }
      return true;
   }

   void Deinit()
   {
      if(m_atr_handle != INVALID_HANDLE)
         IndicatorRelease(m_atr_handle);
      if(m_ema_h1_handle != INVALID_HANDLE)
         IndicatorRelease(m_ema_h1_handle);
   }

   //--- Verify whether current time is within active London or NY session burst window
   bool IsInActiveSession(datetime current_time)
   {
      MqlDateTime dt;
      TimeToStruct(current_time, dt);

      int current_mins = dt.hour * 60 + dt.min;

      // London Open Window: 07:00 - 10:30 UTC (14:00 - 17:30 WIB)
      int london_start = 7 * 60 + 0;
      int london_end   = 10 * 60 + 30;

      // New York Prime Window: 12:30 - 16:30 UTC (19:30 - 23:30 WIB)
      int ny_start = 12 * 60 + 30;
      int ny_end   = 16 * 60 + 30;

      return ((current_mins >= london_start && current_mins < london_end) ||
              (current_mins >= ny_start && current_mins < ny_end));
   }

   //--- Evaluate latest closed M5 bar for momentum impulse setup
   ENUM_TRADE_DIRECTION Evaluate(datetime current_time, ENUM_MARKET_REGIME h4_regime, double &sl_points, double &tp_points, string &reason)
   {
      sl_points = 0.0;
      tp_points = 0.0;

      // 1. Session Timing Filter: Must be in active session
      if(!IsInActiveSession(current_time))
      {
         reason = "OUTSIDE_NY_SESSION_WINDOW";
         return DIR_NONE;
      }

      // 2. Fetch price data for previous closed M5 bars
      MqlRates rates[];
      ArraySetAsSeries(rates, true);
      int fetch_count = m_lookback_bars + 21;
      if(CopyRates(m_symbol, PERIOD_M5, 1, fetch_count, rates) < fetch_count)
      {
         reason = "INSUFFICIENT_M5_RATES";
         return DIR_NONE;
      }

      // 3. Tick Volume Spike Filter: Bar 1 volume > 1.5 * SMA(Volume, 20)
      long sum_vol = 0;
      for(int i = 0; i < 20; i++)
         sum_vol += rates[i].tick_volume;
      double avg_vol = (double)sum_vol / 20.0;

      bool volume_spike = (rates[0].tick_volume >= (avg_vol * m_volume_mult));
      if(!volume_spike)
      {
         reason = "VOLUME_NOT_EXPANDED";
         return DIR_NONE;
      }

      // 4. Bar Range Expansion: (High - Low) on bar 1 > 1.3 * SMA(Range, 20)
      double sum_range = 0.0;
      for(int i = 0; i < 20; i++)
         sum_range += (rates[i].high - rates[i].low);
      double avg_range = sum_range / 20.0;
      double bar1_range = rates[0].high - rates[0].low;

      if(bar1_range < (avg_range * 1.3))
      {
         reason = "RANGE_NOT_EXPANDED";
         return DIR_NONE;
      }

      // 5. Breakout of local N-bar swing channel
      double local_high = -1.0;
      double local_low  = 999999.0;
      for(int i = 1; i <= m_lookback_bars; i++)
      {
         if(rates[i].high > local_high) local_high = rates[i].high;
         if(rates[i].low < local_low)   local_low  = rates[i].low;
      }

      // 6. Fetch M5 ATR for SL calculation
      double atr_buf[1];
      if(CopyBuffer(m_atr_handle, 0, 1, 1, atr_buf) < 1)
      {
         reason = "INSUFFICIENT_M5_ATR";
         return DIR_NONE;
      }
      double current_atr = atr_buf[0];
      double point = SymbolInfoDouble(m_symbol, SYMBOL_POINT);

      double calculated_sl_distance = current_atr * ATR_SL_MULTIPLIER;
      double final_sl_distance = MathMax(calculated_sl_distance, MIN_SL_DISTANCE_DOLLARS);
      double final_sl_pts = final_sl_distance / point;
      double final_tp_pts = final_sl_pts * 2.5; // Asymmetric 2.5:1 reward for momentum expansion

      // 7. Fetch H1 EMA 50 trend filter
      double ema_h1_buf[1];
      if(CopyBuffer(m_ema_h1_handle, 0, 1, 1, ema_h1_buf) < 1)
      {
         reason = "INSUFFICIENT_H1_EMA";
         return DIR_NONE;
      }
      double h1_ema = ema_h1_buf[0];

      // Bullish Impulse (Strong Close near high, Close > local_high, Close > H1 EMA 50)
      bool strong_bull_body = (rates[0].close > rates[0].open) &&
                              ((rates[0].close - rates[0].open) >= (bar1_range * 0.6));
      if(rates[0].close > local_high && strong_bull_body && rates[0].close > h1_ema && h4_regime != REGIME_BEARISH_TRENDING)
      {
         sl_points = final_sl_pts;
         tp_points = final_tp_pts;
         reason = StringFormat("BULLISH_MOMENTUM_M5: Close(%.2f) > High(%.2f) & EMA_H1(%.2f)",
                               rates[0].close, local_high, h1_ema);
         return DIR_BUY;
      }

      // Bearish Impulse (Strong Close near low, Close < local_low, Close < H1 EMA 50)
      bool strong_bear_body = (rates[0].close < rates[0].open) &&
                              ((rates[0].open - rates[0].close) >= (bar1_range * 0.6));
      if(rates[0].close < local_low && strong_bear_body && rates[0].close < h1_ema && h4_regime != REGIME_BULLISH_TRENDING)
      {
         sl_points = final_sl_pts;
         tp_points = final_tp_pts;
         reason = StringFormat("BEARISH_MOMENTUM_M5: Close(%.2f) < Low(%.2f) & EMA_H1(%.2f)",
                               rates[0].close, local_low, h1_ema);
         return DIR_SELL;
      }

      reason = "NO_MOMENTUM_CONFLUENCE";
      return DIR_NONE;
   }
};
