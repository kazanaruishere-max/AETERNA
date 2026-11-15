//+------------------------------------------------------------------+
//|                                                  RiskManager.mqh |
//|                                  AETERNA Quant Risk Gate Engine  |
//|                        Copyright 2026, AETERNA Quant Project     |
//+------------------------------------------------------------------+
#property copyright "Copyright 2026, AETERNA Quant Project"
#property link      "https://aeterna-quant.internal"
#property strict

#include "Invariants.mqh"

class CRiskManager
{
private:
   double            m_peak_equity;
   double            m_start_day_equity;
   datetime          m_current_day;
   int               m_daily_trade_count;
   ulong             m_magic;
   string            m_symbol;
   bool              m_killswitch_active;
   bool              m_daily_breaker_active;

   //--- Update daily state tracking
   void CheckDayRollover(datetime current_time)
   {
      MqlDateTime dt;
      TimeToStruct(current_time, dt);
      datetime today_midnight = StringToTime(StringFormat("%04d.%02d.%02d 00:00", dt.year, dt.mon, dt.day));

      if(today_midnight != m_current_day)
      {
         m_current_day = today_midnight;
         m_start_day_equity = AccountInfoDouble(ACCOUNT_EQUITY);
         m_daily_trade_count = 0;
         m_daily_breaker_active = false;
         PrintFormat("[RISK] New Trading Day Initialized. Starting Equity: %.2f USD", m_start_day_equity);
      }
   }

public:
   CRiskManager(ulong magic, string symbol)
      : m_magic(magic),
        m_symbol(symbol),
        m_peak_equity(0.0),
        m_start_day_equity(0.0),
        m_current_day(0),
        m_daily_trade_count(0),
        m_killswitch_active(false),
        m_daily_breaker_active(false)
   {
   }

   void Init()
   {
      double equity = AccountInfoDouble(ACCOUNT_EQUITY);
      m_peak_equity = equity;
      m_start_day_equity = equity;
      m_current_day = 0;
      m_daily_trade_count = 0;
      m_killswitch_active = false;
      m_daily_breaker_active = false;
      CheckDayRollover(TimeCurrent());
   }

   //--- Evaluate Financial Risk Gates before any order placement
   bool CanOpenNewPosition(datetime current_time, string &block_reason)
   {
      CheckDayRollover(current_time);

      double equity = AccountInfoDouble(ACCOUNT_EQUITY);

      // 1. Hard Peak Drawdown Killswitch (10.0%)
      if(equity > m_peak_equity)
         m_peak_equity = equity;

      double drawdown_pct = (m_peak_equity > 0) ? (m_peak_equity - equity) / m_peak_equity : 0.0;
      if(drawdown_pct >= MAX_DRAWDOWN_KILLSWITCH || m_killswitch_active)
      {
         m_killswitch_active = true;
         block_reason = StringFormat("KILLSWITCH_TRIGGERED: Drawdown %.2f%% >= 10.0%%", drawdown_pct * 100.0);
         return false;
      }

      // 2. Max Daily Loss Circuit Breaker (2.0%)
      double daily_loss_pct = (m_start_day_equity > 0) ? (m_start_day_equity - equity) / m_start_day_equity : 0.0;
      if(daily_loss_pct >= MAX_DAILY_LOSS_PCT || m_daily_breaker_active)
      {
         m_daily_breaker_active = true;
         block_reason = StringFormat("DAILY_CIRCUIT_BREAKER: Loss %.2f%% >= 2.0%%", daily_loss_pct * 100.0);
         return false;
      }

      // 3. Max Concurrent Positions (Strictly 1 position)
      int open_count = 0;
      for(int i = PositionsTotal() - 1; i >= 0; i--)
      {
         ulong ticket = PositionGetTicket(i);
         if(ticket > 0)
         {
            if(PositionGetString(POSITION_SYMBOL) == m_symbol && PositionGetInteger(POSITION_MAGIC) == m_magic)
               open_count++;
         }
      }

      if(open_count >= MAX_CONCURRENT_POSITIONS)
      {
         block_reason = StringFormat("CONCURRENT_POSITION_LIMIT: %d >= %d open", open_count, MAX_CONCURRENT_POSITIONS);
         return false;
      }

      // 4. Max Trades Per Day (Strictly 5 trades)
      UpdateDailyTradeCount();
      if(m_daily_trade_count >= MAX_TRADES_PER_DAY)
      {
         block_reason = StringFormat("DAILY_TRADES_LIMIT: %d >= %d trades today", m_daily_trade_count, MAX_TRADES_PER_DAY);
         return false;
      }

      return true;
   }

   //--- Calculate Lot Size dynamically based on exactly 0.5% risk
   double CalculateLotSize(double sl_distance_points, bool thin_liquidity = false)
   {
      if(sl_distance_points <= 0)
         return 0.0;

      double equity = AccountInfoDouble(ACCOUNT_EQUITY);

      // Multi-Tier Dynamic Drawdown Throttling
      double drawdown_pct = (m_peak_equity > 0) ? (m_peak_equity - equity) / m_peak_equity : 0.0;
      double risk_scale = 1.0;
      if(drawdown_pct >= 0.050)
         risk_scale = 0.50; // Halve risk to 0.25% during moderate drawdown to protect 10% limit

      double base_risk = thin_liquidity ? (RISK_PER_TRADE_PCT * 0.5) : RISK_PER_TRADE_PCT;
      double risk_pct = base_risk * risk_scale;
      double risk_amount_usd = equity * risk_pct;

      // In MT5 for XAUUSD:
      // Point = 0.01 (or 0.001)
      // TickValue = value in deposit currency of 1 tick of TickSize
      double tick_size = SymbolInfoDouble(m_symbol, SYMBOL_TRADE_TICK_SIZE);
      double tick_value = SymbolInfoDouble(m_symbol, SYMBOL_TRADE_TICK_VALUE);
      double point = SymbolInfoDouble(m_symbol, SYMBOL_POINT);

      if(tick_size <= 0 || tick_value <= 0 || point <= 0)
         return 0.0;

      // Risk per 1.0 standard lot:
      double sl_ticks = (sl_distance_points * point) / tick_size;
      double risk_per_lot_usd = sl_ticks * tick_value;

      if(risk_per_lot_usd <= 0)
         return 0.0;

      double raw_lot = risk_amount_usd / risk_per_lot_usd;

      // Scale-before-floor using broker step and volume limits
      double vol_min  = SymbolInfoDouble(m_symbol, SYMBOL_VOLUME_MIN);
      double vol_max  = SymbolInfoDouble(m_symbol, SYMBOL_VOLUME_MAX);
      double vol_step = SymbolInfoDouble(m_symbol, SYMBOL_VOLUME_STEP);

      if(vol_step <= 0)
         vol_step = 0.01;

      // Strict scale-before-floor (floor to step)
      double floored_lot = MathFloor(raw_lot / vol_step) * vol_step;

      // Enforce 0.00% risk tolerance: if floored_lot < vol_min, do NOT force round up to vol_min!
      if(floored_lot < vol_min)
      {
         PrintFormat("[RISK] Floored lot %.4f is below broker min %.2f (Equity: %.2f USD). Blocked.",
                     floored_lot, vol_min, equity);
         return 0.0; // Blocked due to min lot floor
      }

      if(floored_lot > vol_max)
         floored_lot = vol_max;

      return NormalizeDouble(floored_lot, 2);
   }

   //--- Read closed trades for today from MT5 history
   void UpdateDailyTradeCount()
   {
      HistorySelect(m_current_day, TimeCurrent());
      int total_deals = HistoryDealsTotal();
      int count = 0;
      for(int i = 0; i < total_deals; i++)
      {
         ulong ticket = HistoryDealGetTicket(i);
         if(ticket > 0)
         {
            if(HistoryDealGetString(ticket, DEAL_SYMBOL) == m_symbol &&
               HistoryDealGetInteger(ticket, DEAL_MAGIC) == m_magic)
            {
               long entry_type = HistoryDealGetInteger(ticket, DEAL_ENTRY);
               if(entry_type == DEAL_ENTRY_IN)
                  count++;
            }
         }
      }
      m_daily_trade_count = count;
   }

   void IncrementTradeCount()
   {
      m_daily_trade_count++;
   }

   bool IsKillswitchActive()   const { return m_killswitch_active; }
   bool IsDailyBreakerActive() const { return m_daily_breaker_active; }
   int  GetDailyTradeCount()   const { return m_daily_trade_count; }
   double GetPeakEquity()      const { return m_peak_equity; }
   double GetStartDayEquity()  const { return m_start_day_equity; }
};
