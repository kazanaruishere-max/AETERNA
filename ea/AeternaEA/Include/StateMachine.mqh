//+------------------------------------------------------------------+
//|                                                 StateMachine.mqh |
//|                     AETERNA Quant EWMA Spread Z-Score State Engine|
//|                        Copyright 2026, AETERNA Quant Project     |
//+------------------------------------------------------------------+
#property copyright "Copyright 2026, AETERNA Quant Project"
#property link      "https://aeterna-quant.internal"
#property strict

#include "Invariants.mqh"

class CSpreadStateMachine
{
private:
   string            m_symbol;
   double            m_alpha;
   double            m_baseline;
   double            m_variance;
   int               m_read_count;
   int               m_warmup_reads;
   ENUM_SYSTEM_STATE m_state;
   int               m_k_counter;
   datetime          m_recovery_start_time;
   double            m_last_spread;
   double            m_last_z_score;

public:
   CSpreadStateMachine(string symbol, double alpha = EWMA_ALPHA, int warmup_reads = 30)
      : m_symbol(symbol),
        m_alpha(alpha),
        m_baseline(0.0),
        m_variance(0.0),
        m_read_count(0),
        m_warmup_reads(warmup_reads),
        m_state(STATE_NORMAL),
        m_k_counter(0),
        m_recovery_start_time(0),
        m_last_spread(0.0),
        m_last_z_score(0.0)
   {
   }

   void Init()
   {
      m_baseline = 0.0;
      m_variance = 0.0;
      m_read_count = 0;
      m_state = STATE_NORMAL;
      m_k_counter = 0;
      m_recovery_start_time = 0;
      m_last_spread = 0.0;
      m_last_z_score = 0.0;
   }

   //--- Update spread reading and transition state machine
   ENUM_SYSTEM_STATE Update(double current_spread_points, datetime current_time, bool is_in_news_blackout)
   {
      m_last_spread = current_spread_points;
      m_read_count++;

      // 1. EWMA baseline and variance update
      if(m_read_count == 1)
      {
         m_baseline = current_spread_points;
         m_variance = 0.01; // Small initial floor
      }
      else
      {
         double prev_baseline = m_baseline;
         m_baseline = m_alpha * current_spread_points + (1.0 - m_alpha) * prev_baseline;
         double diff = current_spread_points - prev_baseline;
         m_variance = (1.0 - m_alpha) * (m_variance + m_alpha * diff * diff);
      }

      double std_dev = MathSqrt(MathMax(m_variance, 0.0001));
      m_last_z_score = (current_spread_points - m_baseline) / std_dev;

      // During warmup, remain in NORMAL if not in news blackout
      if(m_read_count < m_warmup_reads)
      {
         if(is_in_news_blackout)
            m_state = STATE_PAUSED;
         else
            m_state = STATE_NORMAL;
         return m_state;
      }

      // 2. State Machine Transitions
      bool spread_spike = (m_last_z_score >= Z_THRESHOLD_PAUSE);
      bool is_calm      = (m_last_z_score < Z_THRESHOLD_RESUME);

      switch(m_state)
      {
         case STATE_NORMAL:
         case STATE_PRE_NEWS_WATCH:
            if(is_in_news_blackout || spread_spike)
            {
               m_state = STATE_PAUSED;
               m_k_counter = 0;
               m_recovery_start_time = 0;
               PrintFormat("[STATE] Transitioned to PAUSED. Z-score: %.2f, Spread: %.1f pts, News: %s",
                           m_last_z_score, current_spread_points, is_in_news_blackout ? "YES" : "NO");
            }
            break;

         case STATE_PAUSED:
            // Must not be in news blackout, and spread must be calm (Z < 1.5)
            if(!is_in_news_blackout && is_calm)
            {
               m_k_counter++;
               if(m_k_counter >= K_STABLE_READS)
               {
                  m_state = STATE_RECOVERY_CHECK;
                  m_recovery_start_time = current_time;
                  PrintFormat("[STATE] Transitioned to RECOVERY_CHECK. K=%d stable reads achieved.", m_k_counter);
               }
            }
            else
            {
               m_k_counter = 0; // Reset counter on any elevated reading
            }
            break;

         case STATE_RECOVERY_CHECK:
            // If anomaly recurs during recovery period, immediately abort to PAUSED
            if(is_in_news_blackout || !is_calm)
            {
               m_state = STATE_PAUSED;
               m_k_counter = 0;
               m_recovery_start_time = 0;
               PrintFormat("[STATE] Anomaly in RECOVERY_CHECK! Reverted to PAUSED. Z-score: %.2f", m_last_z_score);
            }
            else
            {
               // Check if stability sustained for M=300 seconds (5 minutes)
               if(current_time - m_recovery_start_time >= M_STABILITY_SECONDS)
               {
                  m_state = STATE_NORMAL;
                  m_k_counter = 0;
                  m_recovery_start_time = 0;
                  PrintFormat("[STATE] Stability confirmed (5 min). State restored to NORMAL.");
               }
            }
            break;
      }

      return m_state;
   }

   ENUM_SYSTEM_STATE GetState()    const { return m_state; }
   double GetBaseline()            const { return m_baseline; }
   double GetZScore()              const { return m_last_z_score; }
   double GetLastSpread()          const { return m_last_spread; }
   bool   IsNormal()               const { return (m_state == STATE_NORMAL); }
};
