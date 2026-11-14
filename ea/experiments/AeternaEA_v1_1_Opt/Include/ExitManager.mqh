//+------------------------------------------------------------------+
//|                                                  ExitManager.mqh |
//|                     AETERNA Quant 5-Layer Active Exit Controller  |
//|                        Copyright 2026, AETERNA Quant Project     |
//+------------------------------------------------------------------+
#property copyright "Copyright 2026, AETERNA Quant Project"
#property link      "https://aeterna-quant.internal"
#property strict

#include <Trade\Trade.mqh>
#include <Trade\PositionInfo.mqh>
#include "Invariants.mqh"

class CExitManager
{
private:
   CTrade            m_trade;
   ulong             m_magic;
   string            m_symbol;
   int               m_max_slippage_points;

   // Tracking for active position
   ulong             m_active_ticket;
   double            m_r0_pts;
   double            m_mfe_price;
   bool              m_partial_done;

public:
   CExitManager(ulong magic, string symbol, int max_slippage_points = 50)
      : m_magic(magic),
        m_symbol(symbol),
        m_max_slippage_points(max_slippage_points),
        m_active_ticket(0),
        m_r0_pts(300.0),
        m_mfe_price(0.0),
        m_partial_done(false)
   {
      m_trade.SetExpertMagicNumber(m_magic);
      m_trade.SetDeviationInPoints(m_max_slippage_points);
      m_trade.SetTypeFilling(ORDER_FILLING_IOC);
   }

   //--- Active position monitoring on every tick
   void MonitorActivePositions(datetime current_time,
                               ENUM_TIMEFRAMES tf,
                               ENUM_MARKET_REGIME current_regime,
                               bool force_session_close)
   {
      int total_pos = PositionsTotal();
      if(total_pos == 0)
      {
         m_active_ticket = 0;
         m_r0_pts = 300.0;
         m_mfe_price = 0.0;
         m_partial_done = false;
         return;
      }

      for(int i = total_pos - 1; i >= 0; i--)
      {
         ulong ticket = PositionGetTicket(i);
         if(ticket <= 0) continue;

         if(PositionGetString(POSITION_SYMBOL) != m_symbol ||
            PositionGetInteger(POSITION_MAGIC) != m_magic)
            continue;

         ENUM_POSITION_TYPE pos_type = (ENUM_POSITION_TYPE)PositionGetInteger(POSITION_TYPE);
         double open_price = PositionGetDouble(POSITION_PRICE_OPEN);
         double current_sl = PositionGetDouble(POSITION_SL);
         double current_tp = PositionGetDouble(POSITION_TP);
         double volume     = PositionGetDouble(POSITION_VOLUME);
         datetime open_time = (datetime)PositionGetInteger(POSITION_TIME);
         string comment    = PositionGetString(POSITION_COMMENT);

         double bid = SymbolInfoDouble(m_symbol, SYMBOL_BID);
         double ask = SymbolInfoDouble(m_symbol, SYMBOL_ASK);
         double current_price = (pos_type == POSITION_TYPE_BUY) ? bid : ask;
         double point = SymbolInfoDouble(m_symbol, SYMBOL_POINT);

         // Initialize tracking for newly detected position
         if(ticket != m_active_ticket)
         {
            m_active_ticket = ticket;
            if(current_sl > 0)
               m_r0_pts = MathAbs(open_price - current_sl) / point;
            else if(current_tp > 0)
               m_r0_pts = (MathAbs(current_tp - open_price) / point) / 2.5;
            else
               m_r0_pts = 350.0;

            m_mfe_price = (pos_type == POSITION_TYPE_BUY) ? bid : ask;
            m_partial_done = (StringFind(comment, "[P]") >= 0);
         }

         // Update MFE (Peak favorable price excursion)
         if(pos_type == POSITION_TYPE_BUY)
         {
            if(bid > m_mfe_price) m_mfe_price = bid;
         }
         else
         {
            if(ask < m_mfe_price || m_mfe_price == 0.0) m_mfe_price = ask;
         }

         // Fixed immutable R0 calculation
         double sl_dist_pts = (m_r0_pts > 0) ? m_r0_pts : 350.0;
         double float_pnl_pts = (pos_type == POSITION_TYPE_BUY) ?
                                ((current_price - open_price) / point) :
                                ((open_price - current_price) / point);

         double r_multiple = float_pnl_pts / sl_dist_pts;

         //------------------------------------------------------------
         // Lapis 5: Rollover Force Close (15m before bank break) & Session Shutdown
         //------------------------------------------------------------
         MqlDateTime dt;
         TimeToStruct(current_time, dt);
         bool is_rollover_window = (dt.hour == 20 && dt.min >= 44) || (dt.hour == 21 && dt.min >= 44);

         if(force_session_close || is_rollover_window)
         {
            PrintFormat("[EXIT L5] Force Closing Position #%d due to Rollover/Session End. Floating R: %.2f", ticket, r_multiple);
            m_trade.PositionClose(ticket);
            continue;
         }

         //------------------------------------------------------------
         // Lapis 5: Regime Invalidation (H4 Regime flipped contrary)
         //------------------------------------------------------------
         bool regime_flip = false;
         if(pos_type == POSITION_TYPE_BUY && current_regime == REGIME_BEARISH_TRENDING)
            regime_flip = true;
         else if(pos_type == POSITION_TYPE_SELL && current_regime == REGIME_BULLISH_TRENDING)
            regime_flip = true;

         if(regime_flip)
         {
            PrintFormat("[EXIT L5] Force Closing Position #%d due to H4 Regime Reversal. Floating R: %.2f", ticket, r_multiple);
            m_trade.PositionClose(ticket);
            continue;
         }

         //------------------------------------------------------------
         // Lapis 4: Time Invalidation (16 closed bars, e.g. 4 hours on M15)
         //------------------------------------------------------------
         int bar_seconds = PeriodSeconds(tf);
         if(bar_seconds > 0)
         {
            int elapsed_bars = (int)((current_time - open_time) / bar_seconds);
            if(elapsed_bars >= 16 && r_multiple < 0.3)
            {
               PrintFormat("[EXIT L4] Time Invalidation Triggered (%d bars elapsed). Closing #%d at Market. R: %.2f",
                           elapsed_bars, ticket, r_multiple);
               m_trade.PositionClose(ticket);
               continue;
            }
         }

         //------------------------------------------------------------
         // Lapis 2: Dynamic ATR Ratchet Trailing Stop
         // Let winners run: trail 0.75R behind MFE peak
         //------------------------------------------------------------
         if(r_multiple >= 1.2)
         {
            double lock_profit_r = 0.5; // Guarantee at least +0.5R in the bank
            double cand_sl = 0.0;

            if(pos_type == POSITION_TYPE_BUY)
            {
               double ratchet_sl = m_mfe_price - (0.75 * sl_dist_pts * point);
               double floor_sl   = open_price + (lock_profit_r * sl_dist_pts * point);
               cand_sl = NormalizeDouble(MathMax(floor_sl, ratchet_sl), _Digits);

               if(cand_sl > (current_sl + 15 * point))
               {
                  PrintFormat("[EXIT L2 RATCHET] #%d Buy Ratchet SL -> %.2f (MFE: %.2f, Current R: %.2f)",
                              ticket, cand_sl, m_mfe_price, r_multiple);
                  m_trade.PositionModify(ticket, cand_sl, current_tp);
               }
            }
            else // POSITION_TYPE_SELL
            {
               double ratchet_sl = m_mfe_price + (0.75 * sl_dist_pts * point);
               double floor_sl   = open_price - (lock_profit_r * sl_dist_pts * point);
               cand_sl = NormalizeDouble(MathMin(floor_sl, ratchet_sl), _Digits);

               if(cand_sl < (current_sl - 15 * point) || current_sl == 0.0)
               {
                  PrintFormat("[EXIT L2 RATCHET] #%d Sell Ratchet SL -> %.2f (MFE: %.2f, Current R: %.2f)",
                              ticket, cand_sl, m_mfe_price, r_multiple);
                  m_trade.PositionModify(ticket, cand_sl, current_tp);
               }
            }

            // Layer 3: Partial Scale-Out (50%) at +1.5R (only if lot >= 0.02)
            if(r_multiple >= 1.5 && !m_partial_done && volume >= 0.02)
            {
               double close_vol = NormalizeDouble(volume * 0.5, 2);
               PrintFormat("[EXIT L3] Reached +1.5R. Closing 50%% volume (%.2f of %.2f lots) for ticket #%d", close_vol, volume, ticket);
               if(m_trade.PositionClosePartial(ticket, close_vol))
               {
                  m_partial_done = true;
               }
            }
         }
      }
   }

   //--- Force close all positions immediately (e.g. manual emergency or shutdown)
   void CloseAllPositions(string reason)
   {
      for(int i = PositionsTotal() - 1; i >= 0; i--)
      {
         ulong ticket = PositionGetTicket(i);
         if(ticket <= 0) continue;

         if(PositionGetString(POSITION_SYMBOL) == m_symbol &&
            PositionGetInteger(POSITION_MAGIC) == m_magic)
         {
            PrintFormat("[EXIT FORCE] Closing #%d Reason: %s", ticket, reason);
            m_trade.PositionClose(ticket);
         }
      }
   }
};
