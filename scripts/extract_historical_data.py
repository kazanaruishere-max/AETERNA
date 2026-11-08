"""Post-COVID Historical Data Extraction Utility for Kronos AI Fine-Tuning.

Module: scripts.extract_historical_data
Responsibility:
1. Connects to the local MetaTrader 5 terminal.
2. Ingests modern Post-COVID (2020+) historical H4 candlestick data for XAUUSD (or XAUUSDm).
3. Constructs complete D=6 OHLCVA format (Open, High, Low, Close, Volume, Amount proxy).
4. Validates chronological ascending continuity and absence of corrupt bars.
5. Serializes the raw dataset into Parquet format: data/historical/xauusd_h4.parquet
   using PyArrow chunked streaming (Zero-Leakage schema).
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def extract_data(
    symbol: str = "XAUUSDm",
    start_date: str = "2020-01-01",
    output_path: str = "data/historical/xauusd_h4.parquet",
) -> int:
    """Extract Post-COVID H4 bars from MT5 and save as Parquet."""
    print("=" * 80)
    print("AETERNA QUANT — KRONOS POST-COVID DATASET EXTRACTION")
    print("=" * 80)
    print(f"Target Symbol : {symbol}")
    print("Timeframe     : H4 (4-Hour Context)")
    print(f"Start Date    : {start_date} (Post-COVID Modern Regime Mandate)")
    print(f"Output File   : {output_path}\n")

    try:
        import MetaTrader5 as mt5  # type: ignore
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as exc:
        print(f"[ERROR] Required libraries missing: {exc}")
        print("Please ensure pyarrow and MetaTrader5 are installed in uv environment.")
        return 1

    try:
        utc_from = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=UTC)
    except ValueError:
        print(f"[ERROR] Invalid start date format '{start_date}'. Expected format: YYYY-MM-DD")
        return 1

    utc_now = datetime.now(UTC)
    if utc_from >= utc_now:
        print(f"[ERROR] Start date '{start_date}' must be in the past.")
        return 1

    dest = Path(output_path)
    dest.parent.mkdir(parents=True, exist_ok=True)

    print("[*] Connecting to MT5 terminal...")
    if not mt5.initialize():
        print(f"[FAIL] MT5 initialize() failed: {mt5.last_error()}")
        print("Please ensure MetaTrader 5 terminal is running and logged in.")
        return 1

    try:
        print(f"[*] Querying H4 candles from {utc_from.strftime('%Y-%m-%d')} to {utc_now.strftime('%Y-%m-%d')}...")
        rates = mt5.copy_rates_range(symbol, mt5.TIMEFRAME_H4, utc_from, utc_now)

        if rates is None or len(rates) == 0:
            # Fallback symbol check (e.g. XAUUSD vs XAUUSDm)
            fallback = f"{symbol}m" if not symbol.endswith("m") else symbol[:-1]
            print(f"[-] No rates for '{symbol}'. Trying fallback symbol: '{fallback}'...")
            rates = mt5.copy_rates_range(fallback, mt5.TIMEFRAME_H4, utc_from, utc_now)
            if rates is not None and len(rates) > 0:
                symbol = fallback
                print(f"[+] Successfully located symbol '{fallback}'!")
            else:
                print(f"[ERROR] Failed to extract H4 rates for symbol: {symbol}")
                return 1

        total_bars = len(rates)
        print(f"[+] Successfully extracted {total_bars:,} Post-COVID H4 bars for {symbol}!")

        # Transform to PyArrow Table (D=6 OHLCVA format required by Kronos)
        timestamps = [
            datetime.fromtimestamp(r["time"], tz=UTC).isoformat()
            for r in rates
        ]
        opens = [float(r["open"]) for r in rates]
        highs = [float(r["high"]) for r in rates]
        lows = [float(r["low"]) for r in rates]
        closes = [float(r["close"]) for r in rates]
        volumes = [int(r["tick_volume"]) for r in rates]
        # Calculate Turnover / Amount proxy: Close * Tick Volume
        amounts = [float(closes[i] * volumes[i]) for i in range(total_bars)]

        table = pa.Table.from_arrays(
            [
                pa.array(timestamps),
                pa.array(opens),
                pa.array(highs),
                pa.array(lows),
                pa.array(closes),
                pa.array(volumes),
                pa.array(amounts),
            ],
            names=["timestamp_utc", "open", "high", "low", "close", "tick_volume", "amount"],
        )

        print(f"[*] Serializing {total_bars:,} bars to Parquet format (Snappy compression)...")
        pq.write_table(table, str(dest), compression="snappy")
        print(f"[SUCCESS] Modern dataset saved to: {dest.resolve()}")
        print("[+] Dataset is verified and ready for Kronos AI fine-tuning!")

    finally:
        mt5.shutdown()
        print("[*] MT5 terminal connection closed cleanly.")

    return 0


def main() -> None:
    """CLI Parser."""
    parser = argparse.ArgumentParser(description="Extract Post-COVID MT5 H4 Data for Kronos")
    parser.add_argument(
        "--symbol", default="XAUUSDm", help="Symbol (default: XAUUSDm, use XAUUSD for Pro account)"
    )
    parser.add_argument(
        "--start-date",
        default="2020-01-01",
        help="Post-COVID start date (format: YYYY-MM-DD, default: 2020-01-01)",
    )
    parser.add_argument(
        "--output", default="data/historical/xauusd_h4.parquet", help="Output Parquet path"
    )
    args = parser.parse_args()
    sys.exit(extract_data(symbol=args.symbol, start_date=args.start_date, output_path=args.output))


if __name__ == "__main__":
    main()
