#!/usr/bin/env python3
"""
MCP Sentiment Temperature Service

Exposes the MAGS/QQQ put/call ratio -> LLM temperature mapping as an MCP tool.
The trading agent can call this to understand current market sentiment
and the system uses it to dynamically set the LLM temperature.
"""

import os
import sys
from pathlib import Path
from typing import Any, Dict

from dotenv import load_dotenv
from fastmcp import FastMCP

load_dotenv()

# Add project root to path
project_root = str(Path(__file__).resolve().parents[1])
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from tools.sentiment_temperature import (
    get_sentiment_temperature,
    pc_ratio_to_temperature,
    fetch_put_call_ratio_yahoo,
)

mcp = FastMCP("SentimentTemperature")


@mcp.tool()
def get_market_sentiment_temperature(mode: str = "trend_following") -> Dict[str, Any]:
    """Get the current market sentiment temperature derived from Magnificent 7 ETF (MAGS) put/call ratio.

    The temperature reflects institutional sentiment toward mega-cap tech stocks.
    It is used to dynamically adjust the LLM's creativity/risk-taking:
    - Low temperature (0.1-0.3): Market is fearful -> conservative, defensive decisions
    - Mid temperature (0.4-0.6): Market is neutral -> balanced decisions
    - High temperature (0.7-0.95): Market is greedy -> aggressive, exploratory decisions

    Args:
        mode: 'trend_following' (default) or 'contrarian'.
              trend_following: fear->conservative, greed->aggressive
              contrarian: fear->aggressive (buy the dip), greed->conservative (sell the top)

    Returns:
        Dictionary with temperature value, put/call ratio, sentiment label, and metadata.
    """
    use_contrarian = mode.lower() == "contrarian"
    return get_sentiment_temperature(use_contrarian=use_contrarian)


@mcp.tool()
def get_ticker_put_call_ratio(ticker: str) -> Dict[str, Any]:
    """Get the put/call ratio for any individual ticker from Yahoo Finance options data.

    Useful for checking sentiment on specific Mag 7 stocks or any optionable security.

    Args:
        ticker: Stock/ETF ticker symbol (e.g., 'MAGS', 'QQQ', 'AAPL', 'NVDA').

    Returns:
        Dictionary with put/call ratio, open interest, volume data, or error if unavailable.
    """
    result = fetch_put_call_ratio_yahoo(ticker)
    if result is None:
        return {
            "error": f"Could not fetch options data for {ticker}. Ticker may not have listed options or API is unavailable.",
            "ticker": ticker,
        }
    # Also include what temperature this would map to
    result["mapped_temperature_trend"] = pc_ratio_to_temperature(result["put_call_ratio"], invert=False)
    result["mapped_temperature_contrarian"] = pc_ratio_to_temperature(result["put_call_ratio"], invert=True)
    return result


if __name__ == "__main__":
    port = int(os.getenv("SENTIMENT_HTTP_PORT", "8006"))
    mcp.run(transport="streamable-http", port=port)
