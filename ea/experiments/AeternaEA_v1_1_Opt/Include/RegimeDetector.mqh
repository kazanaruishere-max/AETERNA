//+------------------------------------------------------------------+
//|                                               RegimeDetector.mqh |
//|                 AETERNA Quant Macro H4 Regime Classifier Engine   |
//|                        Copyright 2026, AETERNA Quant Project     |
//+------------------------------------------------------------------+
#property copyright "Copyright 2026, AETERNA Quant Project"
#property link      "https://aeterna-quant.internal"
#property strict

#include "Invariants.mqh"

class CRegimeDetector
{
private:
   string            m_symbol;
   int               m_adx_handle;
   int               m_ema_fast_handle;
   int               m_ema_slow_handle;

public:
   CRegimeDetector(string symbol)
      : m_symbol(symbol),
        m_adx_handle(INVALID_HANDLE),
        m_ema_fast_handle(INVALID_HANDLE),
        m_ema_slow_handle(INVALID_HANDLE)
   {
   }

   bool Init()
   {
      m_adx_handle = iADX(m_symbol, PERIOD_H4, 14);
      m_ema_fast_handle = iMA(m_symbol, PERIOD_H4, 20, 0, MODE_EMA, PRICE_CLOSE);
      m_ema_slow_handle = iMA(m_symbol, PERIOD_H4, 50, 0, MODE_EMA, PRICE_CLOSE);

      if(m_adx_handle == INVALID_HANDLE || m_ema_fast_handle == INVALID_HANDLE || m_ema_slow_handle == INVALID_HANDLE)
      {
         PrintFormat("[REGIME] Error creating H4 indicator handles: %d", GetLastError());
         return false;
      }
      return true;
   }

   void Deinit()
   {
      if(m_adx_handle != INVALID_HANDLE)      IndicatorRelease(m_adx_handle);
      if(m_ema_fast_handle != INVALID_HANDLE) IndicatorRelease(m_ema_fast_handle);
      if(m_ema_slow_handle != INVALID_HANDLE) IndicatorRelease(m_ema_slow_handle);
   }

   //--- Classify H4 Regime deterministically matching indicators.py
   ENUM_MARKET_REGIME ClassifyCurrentRegime()
   {
      double adx_buf[1], ema_fast_buf[1], ema_slow_buf[1];

      if(CopyBuffer(m_adx_handle, 0, 1, 1, adx_buf) <= 0 ||
         CopyBuffer(m_ema_fast_handle, 0, 1, 1, ema_fast_buf) <= 0 ||
         CopyBuffer(m_ema_slow_handle, 0, 1, 1, ema_slow_buf) <= 0)
      {
         return REGIME_AMBIGUOUS;
      }

      double adx      = adx_buf[0];
      double ema_fast = ema_fast_buf[0];
      double ema_slow = ema_slow_buf[0];

      // Match indicators.py classify_h4_regime:
      // Strong trend when ADX >= 25.0
      if(adx >= 25.0)
      {
         if(ema_fast > ema_slow)
            return REGIME_BULLISH_TRENDING;
         else if(ema_fast < ema_slow)
            return REGIME_BEARISH_TRENDING;
         else
            return REGIME_AMBIGUOUS;
      }

      // Ranging when ADX < 20.0
      if(adx < 20.0)
         return REGIME_RANGING_CONFIRMED;

      // In between (20.0 <= ADX < 25.0) is ambiguous / transitioning
      return REGIME_AMBIGUOUS;
   }
};
