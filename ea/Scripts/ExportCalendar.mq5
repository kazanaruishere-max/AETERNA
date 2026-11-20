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
   datetime now = TimeGMT();
   if(now <= 0) now = TimeCurrent();
   datetime date_from = now - (InpDaysPast * SECONDS_PER_DAY);
   datetime date_to   = now + (InpDaysAhead * SECONDS_PER_DAY);

   MqlCalendarValue values[];
   ResetLastError();
   int total = CalendarValueHistory(values, date_from, date_to, NULL, InpCurrency);
   if(total < 0) return;

   int h = FileOpen(InpFileName, FILE_WRITE | FILE_TXT | FILE_ANSI);
   if(h == INVALID_HANDLE) return;

   FileWriteString(h, StringFormat("{\n  \"schema_version\": %d,\n  \"source\": \"%s\",\n", SCHEMA_VERSION, SOURCE_ID));
   FileWriteString(h, StringFormat("  \"exported_at_utc\": \"%s\",\n  \"events\": [\n", FormatIsoUtc(now)));

   int count = 0;
   for(int i = 0; i < total; i++)
   {
      MqlCalendarEvent ev;
      if(!CalendarEventById(values[i].event_id, ev) || ev.importance != CALENDAR_IMPORTANCE_HIGH) continue;
      if(StringCompare(InpCurrency, "", false) != 0 && StringCompare(ev.currency, InpCurrency, false) != 0) continue;

      if(count > 0) FileWriteString(h, ",\n");
      string entry = StringFormat(
         "    {\"id\": %s, \"event_id\": %s, \"name\": \"%s\", \"currency\": \"%s\", \"impact\": \"HIGH\", \"timestamp_utc\": \"%s\"}",
         IntegerToString(values[i].id), IntegerToString(values[i].event_id), JsonEscape(ev.name), ev.currency, FormatIsoUtc(values[i].time)
      );
      FileWriteString(h, entry);
      count++;
   }
   FileWriteString(h, "\n  ]\n}\n");
   FileClose(h);
   PrintFormat("[ExportCalendar] Exported %d USD HIGH events to %s", count, InpFileName);
}
//+------------------------------------------------------------------+
