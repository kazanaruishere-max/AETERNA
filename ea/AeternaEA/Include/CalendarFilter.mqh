//+------------------------------------------------------------------+
//|                                               CalendarFilter.mqh |
//|                     AETERNA Quant Macro Blackout Calendar Engine  |
//|                        Copyright 2026, AETERNA Quant Project     |
//+------------------------------------------------------------------+
#property copyright "Copyright 2026, AETERNA Quant Project"
#property link      "https://aeterna-quant.internal"
#property strict

#include "Invariants.mqh"

class CCalendarFilter
{
private:
   datetime          m_events[];
   int               m_event_count;
   bool              m_use_calendar;

public:
   CCalendarFilter(bool enable = true)
      : m_use_calendar(enable),
        m_event_count(0)
   {
   }

   void Init()
   {
      ArrayResize(m_events, 0);
      m_event_count = 0;
   }

   //--- Register a known high-impact news event timestamp (UTC)
   void AddEvent(datetime event_utc)
   {
      m_event_count++;
      ArrayResize(m_events, m_event_count);
      m_events[m_event_count - 1] = event_utc;
   }

   //--- Check if current time is within T-10m before scheduled release
   bool IsInPreNewsWindow(datetime current_time)
   {
      if(!m_use_calendar) return false;

      for(int i = 0; i < m_event_count; i++)
      {
         datetime event_t = m_events[i];
         if(current_time >= (event_t - 600) && current_time < event_t)
            return true;
      }
      return false;
   }

   //--- Check if current time is within [T, T + 15m] blackout release window
   bool IsInNewsBlackout(datetime current_time)
   {
      if(!m_use_calendar) return false;

      for(int i = 0; i < m_event_count; i++)
      {
         datetime event_t = m_events[i];
         if(current_time >= event_t && current_time <= (event_t + 900))
            return true;
      }
      return false;
   }

   void SetEnabled(bool enable) { m_use_calendar = enable; }
   bool IsEnabled() const       { return m_use_calendar; }
};
