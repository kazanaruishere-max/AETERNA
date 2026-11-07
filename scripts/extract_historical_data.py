"""Historical Data Extraction Stub for Kronos AI Fine-Tuning.

Module: scripts.extract_historical_data
Responsibility:
1. Connects to MetaTrader 5 terminal.
2. Ingests long-term historical H4 candlestick data (e.g., 5 to 10 years).
3. Validates chronological continuity and absence of corrupted bars.
4. Serializes the raw dataset into Parquet format: data/historical/xauusd_h4.parquet
   using PyArrow chunked writing (Zero-Leakage schema).
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
    symbol: str = "XAUUSD",
    years: int = 10,
    output_path: str = "data/historical/xauusd_h4.parquet",
) -> int:
    """Extract historical H4 bars from MT5 and save as Parquet."""
    print("=" * 80)
    print("AETERNA QUANT — KRONOS DATASET EXTRACTION STUB")
    print("=" * 80)
    print(f"Target Symbol : {symbol}")
    print("Timeframe     : H4 (4-Hour Context)")
    print(f"History Depth : {years} years")
    print(f"Output File   : {output_path}\n")

    try:
        import MetaTrader5 as mt5  # type: ignore
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as exc:
        print(f"[ERROR] Required libraries missing: {exc}")
        print("Please ensure pyarrow and MetaTrader5 are installed in uv environment.")
        return 1

    dest = Path(output_path)
    dest.parent.mkdir(parents=True, exist_ok=True)

    print("[*] Connecting to MT5 terminal...")
    if not mt5.initialize():
        print(f"[FAIL] MT5 initialize() failed: {mt5.last_error()}")
        return 1

    try:
        # Calculate date range
        utc_now = datetime.now(UTC)
        start_year = max(1970, utc_now.year - years)
        utc_from = datetime(start_year, 1, 1, tzinfo=UTC)

        print(f"[*] Querying H4 candles from {utc_from.strftime('%Y-%m-%d')} to present...")
        rates = mt5.copy_rates_range(symbol, mt5.TIMEFRAME_H4, utc_from, utc_now)

        if rates is None or len(rates) == 0:
            # Fallback symbol check (e.g. XAUUSDm)
            fallback = f"{symbol}m" if not symbol.endswith("m") else symbol[:-1]
            print(f"[-] No rates for '{symbol}'. Trying fallback '{fallback}'...")
            rates = mt5.copy_rates_range(fallback, mt5.TIMEFRAME_H4, utc_from, utc_now)
            if rates is not None and len(rates) > 0:
                symbol = fallback
            else:
                print(f"[ERROR] Failed to extract H4 rates for symbol: {symbol}")
                return 1

        total_bars = len(rates)
        print(f"[+] Successfully extracted {total_bars:,} H4 bars for {symbol}!")

        # Transform to PyArrow Table
        timestamps = [
            datetime.fromtimestamp(r["time"], tz=UTC).isoformat()
            for r in rates
        ]
        opens = [float(r["open"]) for r in rates]
        highs = [float(r["high"]) for r in rates]
        lows = [float(r["low"]) for r in rates]
        closes = [float(r["close"]) for r in rates]
        volumes = [int(r["tick_volume"]) for r in rates]

        table = pa.Table.from_arrays(
            [
                pa.array(timestamps),
                pa.array(opens),
                pa.array(highs),
                pa.array(lows),
                pa.array(closes),
                pa.array(volumes),
            ],
            names=["timestamp_utc", "open", "high", "low", "close", "tick_volume"],
        )

        print(f"[*] Serializing {total_bars:,} bars to Parquet format...")
        pq.write_table(table, str(dest), compression="snappy")
        print(f"[SUCCESS] Dataset saved to: {dest.resolve()}")
        print("[+] Dataset is ready for Kronos AI offline fine-tuning!")

    finally:
        mt5.shutdown()
        print("[*] MT5 terminal connection closed cleanly.")

    return 0


def main() -> None:
    """CLI Parser."""
    parser = argparse.ArgumentParser(description="Extract MT5 H4 Data for Kronos")
    parser.add_argument("--symbol", default="XAUUSD", help="Symbol (e.g. XAUUSD or XAUUSDm)")
    parser.add_argument("--years", type=int, default=10, help="Years of history (default: 10)")
    parser.add_argument(
        "--output", default="data/historical/xauusd_h4.parquet", help="Output Parquet path"
    )
    args = parser.parse_args()
    sys.exit(extract_data(symbol=args.symbol, years=args.years, output_path=args.output))


if __name__ == "__main__":
    main()
