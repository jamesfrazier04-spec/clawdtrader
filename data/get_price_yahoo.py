#!/usr/bin/env python3
"""
Fetch current price data from Yahoo Finance (FREE, no API key needed)
Fetches hourly data for NASDAQ 100 stocks + QQQ benchmark

Usage:
    python get_price_yahoo.py              # Fetch all stocks
    python get_price_yahoo.py AAPL MSFT    # Fetch specific stocks
"""

import os
import sys
import json
from datetime import datetime, timedelta

try:
    import yfinance as yf
except ImportError:
    print("Installing yfinance...")
    os.system(f"{sys.executable} -m pip install yfinance")
    import yfinance as yf

# NASDAQ 100 symbols
ALL_NASDAQ_100_SYMBOLS = [
    "NVDA", "MSFT", "AAPL", "GOOG", "GOOGL", "AMZN", "META", "AVGO", "TSLA", "NFLX",
    "PLTR", "COST", "ASML", "AMD", "CSCO", "AZN", "TMUS", "MU", "LIN", "PEP",
    "SHOP", "APP", "INTU", "AMAT", "LRCX", "PDD", "QCOM", "ARM", "INTC", "BKNG",
    "AMGN", "TXN", "ISRG", "GILD", "KLAC", "PANW", "ADBE", "HON", "CRWD", "CEG",
    "ADI", "ADP", "DASH", "CMCSA", "VRTX", "MELI", "SBUX", "CDNS", "ORLY", "SNPS",
    "MSTR", "MDLZ", "ABNB", "MRVL", "CTAS", "TRI", "MAR", "MNST", "CSX", "ADSK",
    "PYPL", "FTNT", "AEP", "WDAY", "REGN", "ROP", "NXPI", "DDOG", "AXON", "ROST",
    "IDXX", "EA", "PCAR", "FAST", "EXC", "TTWO", "XEL", "ZS", "PAYX", "WBD",
    "BKR", "CPRT", "CCEP", "FANG", "TEAM", "CHTR", "KDP", "MCHP", "GEHC", "VRSK",
    "CTSH", "CSGP", "KHC", "ODFL", "DXCM", "TTD", "ON", "BIIB", "LULU", "CDW", "GFS",
    "QQQ"  # Benchmark
]


def fetch_hourly_data(symbol: str, days: int = 30) -> dict:
    """Fetch hourly price data for a symbol."""
    try:
        ticker = yf.Ticker(symbol)

        # Fetch hourly data (1h interval, max 730 days for hourly)
        df = ticker.history(period=f"{days}d", interval="1h")

        if df.empty:
            print(f"  Warning: No data for {symbol}")
            return None

        # Convert to Alpha Vantage format for compatibility
        time_series = {}
        for idx, row in df.iterrows():
            # Format timestamp as "YYYY-MM-DD HH:MM:SS"
            timestamp = idx.strftime("%Y-%m-%d %H:%M:%S")
            time_series[timestamp] = {
                "1. open": str(round(row["Open"], 4)),
                "2. high": str(round(row["High"], 4)),
                "3. low": str(round(row["Low"], 4)),
                "4. close": str(round(row["Close"], 4)),
                "5. volume": str(int(row["Volume"]))
            }

        data = {
            "Meta Data": {
                "1. Information": "Intraday (60min) prices from Yahoo Finance",
                "2. Symbol": symbol,
                "3. Last Refreshed": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "4. Interval": "60min",
                "5. Output Size": "Full size",
                "6. Time Zone": "US/Eastern"
            },
            "Time Series (60min)": time_series
        }

        return data

    except Exception as e:
        print(f"  Error fetching {symbol}: {e}")
        return None


def save_price_data(data: dict, symbol: str):
    """Save price data to JSON file, merging with existing data."""
    file_path = f"daily_prices_{symbol}.json"

    try:
        # Load existing data if file exists
        if os.path.exists(file_path):
            with open(file_path, 'r', encoding='utf-8') as f:
                old_data = json.load(f)

            # Merge time series (new data overwrites old for same timestamps)
            old_ts = old_data.get("Time Series (60min)", {})
            new_ts = data.get("Time Series (60min)", {})
            merged_ts = {**old_ts, **new_ts}

            data["Time Series (60min)"] = merged_ts

        # Save merged data
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        # Special handling for QQQ benchmark
        if symbol == "QQQ":
            qqq_path = f"Adaily_prices_{symbol}.json"
            with open(qqq_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

    except Exception as e:
        print(f"  Error saving {symbol}: {e}")


def main():
    print("=" * 60)
    print("Yahoo Finance Price Data Fetcher")
    print("=" * 60)

    # Get symbols from command line or use all
    if len(sys.argv) > 1:
        symbols = sys.argv[1:]
    else:
        symbols = ALL_NASDAQ_100_SYMBOLS

    print(f"Fetching {len(symbols)} symbols...")
    print()

    success = 0
    failed = 0

    for i, symbol in enumerate(symbols, 1):
        print(f"[{i}/{len(symbols)}] Fetching {symbol}...", end=" ")

        data = fetch_hourly_data(symbol, days=60)

        if data:
            save_price_data(data, symbol)
            count = len(data.get("Time Series (60min)", {}))
            print(f"OK ({count} data points)")
            success += 1
        else:
            print("FAILED")
            failed += 1

    print()
    print("=" * 60)
    print(f"Complete! Success: {success}, Failed: {failed}")
    print("=" * 60)

    # Create merged.jsonl for the agent
    print("\nCreating merged.jsonl...")
    create_merged_jsonl()


def create_merged_jsonl():
    """Create merged.jsonl from all price files."""
    merged_path = "merged.jsonl"
    count = 0

    with open(merged_path, 'w', encoding='utf-8') as out:
        for symbol in ALL_NASDAQ_100_SYMBOLS:
            file_path = f"daily_prices_{symbol}.json"
            if os.path.exists(file_path):
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                out.write(json.dumps(data) + "\n")
                count += 1

    print(f"Created merged.jsonl with {count} symbols")


if __name__ == "__main__":
    main()
