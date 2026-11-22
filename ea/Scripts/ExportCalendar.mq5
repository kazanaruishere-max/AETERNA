//+------------------------------------------------------------------+
//|                                               ExportCalendar.mq5 |
//|                     AETERNA Quant Economic Calendar Snapshot Exporter |
//|                        Copyright 2026, AETERNA Quant Project     |
//+------------------------------------------------------------------+
#property copyright "Copyright 2026, AETERNA Quant Project"
#property link      "https://aeterna-quant.internal"
#property version   "1.00"
#property script_show_inputs
#property strict

#define SCHEMA_VERSION       1
#define SOURCE_ID            "MQL5_CALENDAR"
#define SOURCE_TIMEZONE      "TRADE_SERVER"
#define SECONDS_PER_DAY      86400

input string InpCurrency  = "USD";                    // Target Currency
input int    InpDaysPast  = 1;                        // Historical Days
input int    InpDaysAhead = 7;                        // Future Days
input string InpFileName  = "calendar_snapshot.json"; // Output JSON filename

string FormatIsoUtc(datetime dt)
{
   MqlDateTime m;
   TimeToStruct(dt, m);
   return StringFormat("%04d-%02d-%02dT%02d:%02d:%02dZ", m.year, m.mon, m.day, m.hour, m.min, m.sec);
}

string JsonEscape(string text)
{
   string res = text;
   StringReplace(res, "\\", "\\\\");
   StringReplace(res, "\"", "\\\"");
   StringReplace(res, "\r", "");
   StringReplace(res, "\n", " ");
   return res;
}

void OnStart()
{
   datetime now_gmt = TimeGMT();
   if(now_gmt <= 0) now_gmt = TimeCurrent();
   datetime now_server = TimeTradeServer();
   if(now_server <= 0) now_server = TimeCurrent();
   int offset_seconds = (int)(now_server - now_gmt);

   datetime date_from = now_server - (InpDaysPast * SECONDS_PER_DAY);
   datetime date_to   = now_server + (InpDaysAhead * SECONDS_PER_DAY);

   MqlCalendarValue values[];
   ResetLastError();
   int total = CalendarValueHistory(values, date_from, date_to, NULL, InpCurrency);
   if(total < 0) return;

   int h = FileOpen(InpFileName, FILE_WRITE | FILE_TXT | FILE_ANSI);
   if(h == INVALID_HANDLE) return;

   FileWriteString(h, StringFormat("{\n  \"schema_version\": %d,\n  \"source\": \"%s\",\n", SCHEMA_VERSION, SOURCE_ID));
   FileWriteString(h, StringFormat("  \"source_timezone\": \"%s\",\n", SOURCE_TIMEZONE));
   FileWriteString(h, StringFormat("  \"exported_at_utc\": \"%s\",\n  \"events\": [\n", FormatIsoUtc(now_gmt)));

   int count = 0;
   for(int i = 0; i < total; i++)
   {
      MqlCalendarEvent ev;
      if(!CalendarEventById(values[i].event_id, ev) || ev.importance != CALENDAR_IMPORTANCE_HIGH) continue;

      datetime ts_utc = values[i].time - offset_seconds;

      if(count > 0) FileWriteString(h, ",\n");
      string entry = StringFormat(
         "    {\"id\": %s, \"event_id\": %s, \"name\": \"%s\", \"currency\": \"%s\", \"impact\": \"HIGH\", \"timestamp_utc\": \"%s\"}",
         IntegerToString(values[i].id), IntegerToString(values[i].event_id), JsonEscape(ev.name), InpCurrency, FormatIsoUtc(ts_utc)
      );
      FileWriteString(h, entry);
      count++;
   }
   FileWriteString(h, "\n  ]\n}\n");
   FileClose(h);
   PrintFormat("[ExportCalendar] Exported %d USD HIGH events to %s (offset=%d s)", count, InpFileName, offset_seconds);
}
//+------------------------------------------------------------------+
