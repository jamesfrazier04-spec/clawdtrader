# Clawdbot Trader - Development Notes

## Project Summary

Clawdbot Trader is an autonomous AI trading system that uses LLM models (GPT-4o, Claude, DeepSeek, and others) to make real-time stock trading decisions via Alpaca's paper trading API. Features persistent memory, sentiment-driven temperature, and multi-market backtesting.

## Key Files

| File | Purpose |
|------|---------|
| `live_trader_gui.py` | Main GUI app with START/PAUSE/STOP controls + sentiment indicator |
| `live_trader.py` | Command-line version (no GUI) |
| `strategy_chat.py` | Chat interface for strategy upgrades |
| `main.py` | Backtesting entry point (all markets) |
| `START_TRADER.bat` | Windows launcher script |
| `START_STRATEGY_CHAT.bat` | Launch strategy chat |
| `.env` | API keys (OpenAI, Alpaca, etc.) |
| `data/get_price_yahoo.py` | Fetches prices from Yahoo Finance |

## Memory System Files

| File | Purpose |
|------|---------|
| `tools/memory_tools.py` | Core memory functions (save/load insights) |
| `tools/performance_tracker.py` | Track trade outcomes and win rates |
| `data/memory/strategy_insights.jsonl` | Stored strategy learnings |
| `data/memory/trade_outcomes.jsonl` | Historical trade results |
| `data/memory/conversations.jsonl` | Saved strategy conversations |

## Sentiment Temperature Files

| File | Purpose |
|------|---------|
| `tools/sentiment_temperature.py` | Core module: fetches MAGS/QQQ P/C ratio, converts to LLM temperature |
| `agent_tools/tool_sentiment_temperature.py` | MCP service (port 8006) exposing sentiment tools |
| `data/sentiment/temperature_cache.json` | Cached P/C ratio + temperature (60 min TTL) |

### How Sentiment Temperature Works

1. On agent `initialize()`, fetches options data for MAGS ETF (Magnificent 7) via `yfinance`
2. Aggregates put/call ratio across 4 nearest expiration dates (volume-based preferred, OI fallback)
3. Maps P/C ratio through a sigmoid curve to temperature range 0.1 - 0.95
4. Passes `temperature=X` to `ChatOpenAI()` constructor
5. Also available as MCP tool for the agent to query during trading sessions

### Sentiment Config in `agent_config`

```json
{
  "sentiment_mode": "trend_following",
  "fixed_temperature": null
}
```

- `sentiment_mode`: `"trend_following"` | `"contrarian"` | `null` (disable)
- `fixed_temperature`: override with specific float (0.0-1.0)

### P/C Ratio to Temperature Mapping

```
P/C 0.3  (extreme greed)  -> Trend: 0.948  Contrarian: 0.102
P/C 0.5  (greed)          -> Trend: 0.926  Contrarian: 0.124
P/C 0.7  (neutral)        -> Trend: 0.630  Contrarian: 0.420
P/C 0.85 (fear)           -> Trend: 0.312  Contrarian: 0.738
P/C 1.0  (fear)           -> Trend: 0.146  Contrarian: 0.904
P/C 1.3+ (extreme fear)   -> Trend: 0.102  Contrarian: 0.948
```

### Data Source Priority

1. `yfinance` library (handles Yahoo's auth/crumb automatically)
2. Raw Yahoo Finance HTTP API (`query2` then `query1`)
3. Default fallback: temperature 0.5 (neutral)

### Testing Sentiment Module Standalone

```bash
python tools/sentiment_temperature.py
```

## MCP Services

| Port | Service | Script | Tools |
|------|---------|--------|-------|
| 8000 | Math | `tool_math.py` | Basic math operations |
| 8001 | Search/News | `tool_alphavantage_news.py` | News sentiment via Alpha Vantage |
| 8002 | Trade | `tool_trade.py` | buy(), sell() for stocks |
| 8003 | Price | `tool_get_price_local.py` | get_price_local() OHLCV data |
| 8004 | Indicators | `tool_indicators.py` | RSI, VWAP, Bollinger Bands, Momentum Score |
| 8005 | Crypto Trade | `tool_crypto_trade.py` | buy_crypto(), sell_crypto() |
| 8006 | Sentiment | `tool_sentiment_temperature.py` | get_market_sentiment_temperature(), get_ticker_put_call_ratio() |

Start all services: `python agent_tools/start_mcp_services.py`

## API Configuration

```env
OPENAI_API_BASE=""
OPENAI_API_KEY=sk-...
ALPACA_API_KEY=PK...
ALPACA_SECRET_KEY=...
ALPACA_BASE_URL=https://paper-api.alpaca.markets
ALPHAADVANTAGE_API_KEY=...

# MCP service ports
MATH_HTTP_PORT=8000
SEARCH_HTTP_PORT=8001
TRADE_HTTP_PORT=8002
GETPRICE_HTTP_PORT=8003
INDICATORS_HTTP_PORT=8004
CRYPTO_HTTP_PORT=8005
SENTIMENT_HTTP_PORT=8006
```

## Agent Classes

| Agent | Market | Symbols | Frequency | Special Rules |
|-------|--------|---------|-----------|---------------|
| `BaseAgent` | US Stocks | NASDAQ 100 | Daily | Standard |
| `BaseAgent_Hour` | US Stocks | NASDAQ 100 | Hourly | Intraday candles |
| `BaseAgentAStock` | China A-Shares | SSE 50 | Daily | T+1, 100-share lots |
| `BaseAgentAStock_Hour` | China A-Shares | SSE 50 | Hourly | T+1, 100-share lots |
| `BaseAgentCrypto` | Crypto | Bitwise 10 | Daily 24/7 | Fractional amounts |

All agents support `sentiment_mode` and `fixed_temperature` constructor params.

## Trading Logic

1. Check if market is open
2. Fetch current prices for tracked symbols
3. Get portfolio status (cash, positions, P/L)
4. Fetch sentiment temperature (MAGS P/C ratio -> LLM temperature)
5. Send data to LLM with temperature set by sentiment, ask for BUY/SELL/HOLD
6. Execute trade via Alpaca API (live) or MCP tool (backtest)
7. Wait interval, repeat

## GUI Components

- **Title bar**: CLAWDBOT LIVE TRADER
- **Status bar**: Running/Paused/Stopped status + Portfolio value + Cash
- **P&L bar**: Daily P/L (color-coded) + Win rate
- **Sentiment bar**: Sentiment label + Temperature value + P/C ratio + visual gauge bar
- **AI Provider selector**: Dropdown to switch models
- **Controls**: START / PAUSE / STOP buttons + trade count
- **Trading tab**: Scrolled console with color-coded log output
- **Strategy Chat tab**: Interactive AI chat with memory integration

## GUI Controls

- **START**: Begin trading loop
- **PAUSE/RESUME**: Pause AI decisions without selling
- **STOP**: Stop trading AND liquidate all positions

## Windows Compatibility Fixes Applied

1. UTF-8 encoding for console output
2. Cross-platform file locking (msvcrt instead of fcntl)
3. Path sanitization (colons replaced with dashes)

## Dependencies

```
alpaca-trade-api
openai
python-dotenv
yfinance
langchain
langchain-openai
langchain-mcp-adapters
fastmcp
requests
pandas
tkinter (built-in)
```

## Quick Commands

```bash
# Run GUI trader
python live_trader_gui.py

# Run CLI trader
python -u live_trader.py

# Strategy chat (discuss and improve strategies)
python strategy_chat.py

# Quick save a strategy insight
python strategy_chat.py --insight "Buy tech dips on Mondays"

# Check memory stats
python strategy_chat.py --stats

# Fetch fresh price data
cd data && python get_price_yahoo.py

# Run backtesting simulation
python main.py configs/default_day_config.json

# Test sentiment temperature
python tools/sentiment_temperature.py

# Start MCP services
python agent_tools/start_mcp_services.py
```

## Memory System

Clawdbot has persistent memory for learning and strategy improvement:

### Strategy Chat
Chat with Clawdbot to discuss and improve strategies. Insights are automatically saved.

```bash
python strategy_chat.py
START_STRATEGY_CHAT.bat
python strategy_chat.py --insight "Never hold NVDA through earnings"
python strategy_chat.py --stats
```

### Chat Commands
- `quit` - Exit chat
- `stats` - Show memory statistics
- `insights` - Show current strategy insights
- `performance` - Show trading performance
- `save` - Save conversation to memory

### How Memory Works
1. **Strategy Insights** - Saved when you discuss strategies in chat
2. **Trade Outcomes** - Automatically tracked from live trading
3. **Performance Learning** - Big wins/losses generate automatic insights
4. **Prompt Injection** - Memory is injected into AI prompts for context

### Memory Storage
All memory is stored in `data/memory/` as JSONL files:
- `strategy_insights.jsonl` - Your strategy rules and learnings
- `trade_outcomes.jsonl` - Trade history with outcomes
- `conversations.jsonl` - Saved chat conversations

## Alpaca Paper Trading

- Endpoint: `https://paper-api.alpaca.markets`
- Free account with $100,000 fake money
- Real-time market prices
- Sign up: https://app.alpaca.markets/signup

## Key Architecture Decisions

- **MCP over direct function calls**: Tools run as separate HTTP services for modularity and language-agnostic potential
- **JSONL over databases**: Append-only logs, easy to inspect, no DB dependency
- **Sentiment as temperature**: Maps market fear/greed directly to LLM creativity parameter
- **yfinance over raw Yahoo API**: Yahoo Finance requires auth cookies/crumbs; yfinance handles this automatically
- **Sigmoid normalization**: Smooth temperature curve that saturates at extremes rather than linear mapping
- **MAGS over QQQ**: MAGS ETF holds exclusively Magnificent 7 stocks for a pure signal; QQQ dilutes across ~100 stocks
