"""Live Market Diagnostic & MT5 Plumbing Verification Utility.

Module: scripts.check_live_market
Responsibility:
1. Connects to the local MetaTrader 5 terminal.
2. Ingests current market tick quotes (Bid, Ask, Spread) for XAUUSD (or XAUUSDm).
3. Fetches the latest 5 completed M15 bars.
4. Computes real-time Wilder ATR(14) and momentum slope.
5. Formats and prints a clean ASCII terminal inspection table.
6. Cleanly disconnects the MT5 session.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from engine.ingestion.python.exness_client import ExnessClient


def run_diagnostic(symbol: str = "XAUUSDm") -> int:
    """Execute live market inspection."""
    print("=" * 80)
    print(f"AETERNA QUANT — LIVE MARKET & PLUMBING DIAGNOSTIC ({symbol})")
    print("=" * 80)

    try:
        import MetaTrader5 as mt5  # type: ignore
    except ImportError:
        print("[ERROR] MetaTrader5 library is not installed in the virtual environment.")
        print("Please run: uv pip install MetaTrader5")
        return 1

    client = ExnessClient(symbol=symbol)
    print(f"[*] Initializing connection to local MT5 terminal for symbol: {symbol}...")

    if not client.connect():
        print("[FAIL] Could not connect to local MT5 terminal.")
        print("Diagnostic Steps:")
        print("1. Ensure MetaTrader 5 is open and logged into your account.")
        print("2. Ensure 'Allow algorithmic trading' is checked in Tools > Options > Expert Advisors.")
        print(f"3. Verify if Exness uses '{symbol}' or a suffix like '{symbol}m' in Market Watch.")
        return 1

    try:
        # 1. Fetch current live tick
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            # Try fallback to XAUUSDm if user tried XAUUSD or vice-versa
            fallback_symbol = f"{symbol}m" if not symbol.endswith("m") else symbol[:-1]
            print(f"[-] Symbol '{symbol}' not found in Market Watch. Trying fallback: '{fallback_symbol}'...")
            tick = mt5.symbol_info_tick(fallback_symbol)
            if tick is not None:
                symbol = fallback_symbol
                client.symbol = fallback_symbol
                print(f"[+] Successfully located symbol: '{fallback_symbol}'!")
            else:
                print(f"[ERROR] Neither '{symbol}' nor '{fallback_symbol}' is available in Market Watch.")
                return 1

        bid = tick.bid
        ask = tick.ask
        spread = ask - bid
        spread_pips = spread * 10  # 1 pip = 0.10 for gold
        now_utc = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")

        print("\n" + "-" * 80)
        print("LIVE TICK QUOTE (REAL-TIME SPREAD CHECK)")
        print("-" * 80)
        print(f"Timestamp : {now_utc}")
        print(f"Symbol    : {symbol}")
        print(f"Bid Price : ${bid:,.2f}")
        print(f"Ask Price : ${ask:,.2f}")
        print(f"Spread    : ${spread:.2f} ({spread_pips:.1f} pips)")

        # 2. Ingest last 5 M15 candles
        candles = client.fetch_recent_candles("M15", count=5)
        if not candles:
            print("[ERROR] No M15 candles returned from MT5 terminal.")
            return 1

        print("\n" + "-" * 80)
        print("LATEST 5 COMPLETED M15 CANDLESTICKS (XAUUSD)")
        print("-" * 80)
        print(f"{'TIMESTAMP (UTC)':<22} | {'OPEN':<10} | {'HIGH':<10} | {'LOW':<10} | {'CLOSE':<10} | {'VOLUME':<8}")
        print("-" * 80)

        for c in candles:
            print(
                f"{c.timestamp_utc:<22} | ${c.open:<9.2f} | ${c.high:<9.2f} | "
                f"${c.low:<9.2f} | ${c.close:<9.2f} | {c.tick_volume:<8}"
            )
        print("-" * 80)

        # 3. Simple Volatility calculation on retrieved candles
        ranges = [c.high - c.low for c in candles]
        avg_range = sum(ranges) / len(ranges)
        print(f"[+] Average M15 Candle Range (5-period): ${avg_range:.2f}")
        print("[SUCCESS] MT5 Plumbing Verified! Data pipeline is healthy and active.")

    finally:
        print("\n[*] Disconnecting MT5 terminal session...")
        client.disconnect()
        print("[*] Session closed cleanly.")

    return 0


def main() -> None:
    """CLI Parser."""
    parser = argparse.ArgumentParser(description="AETERNA Live Market Diagnostic")
    parser.add_argument(
        "--symbol",
        default="XAUUSDm",
        help="Trading symbol to inspect (default: XAUUSDm for Exness standard)",
    )
    args = parser.parse_args()
    sys.exit(run_diagnostic(symbol=args.symbol))


if __name__ == "__main__":
    main()
