# Clawdbot Trader

An autonomous AI-powered trading system that uses LLM models (GPT-4o, Claude, DeepSeek, and others) to make trading decisions across US stocks, Chinese A-shares, and cryptocurrencies. Supports both real-time paper trading via Alpaca and historical backtesting with simulated execution.

---

## Overview

Clawdbot Trader connects artificial intelligence with market data to automatically analyze assets and execute trades. The AI evaluates current prices, portfolio positions, strategy memory, and market conditions to decide whether to buy, sell, or hold.

**Key Features:**
- Real-time paper trading with Alpaca (fake money, real prices)
- Historical backtesting with simulated trade execution
- Multi-model support: GPT-4o, Claude, DeepSeek, Qwen, Gemini, and more
- Multi-market support: US stocks (NASDAQ 100), Chinese A-shares (SSE 50), Crypto (Bitwise 10)
- Persistent strategy memory system that learns from past trades
- MCP (Model Context Protocol) tool architecture for modular trade execution
- **Sentiment-driven LLM temperature**: MAGS/QQQ put/call ratio dynamically controls AI risk-taking
- GUI interface with live console output and real-time sentiment indicator
- Interactive strategy chat for refining trading rules

---

## How It Works

### System Architecture

```
┌────────────────────────────────────────────────────────────────────┐
│                         ENTRY POINTS                               │
│                                                                    │
│  main.py              live_trader.py         strategy_chat.py      │
│  (Backtesting)        (Live Paper Trading)   (Strategy Learning)   │
│  Simulated execution  Alpaca API execution   Chat-based insights   │
└────────┬──────────────────────┬──────────────────────┬─────────────┘
         │                      │                      │
         ▼                      ▼                      ▼
┌────────────────────────────────────────────────────────────────────┐
│                     STRATEGY MEMORY LAYER                          │
│                                                                    │
│  data/memory/strategy_insights.jsonl   (Learned trading rules)     │
│  data/memory/trade_outcomes.jsonl      (Trade history + P/L)       │
│  data/memory/conversations.jsonl       (Strategy discussions)      │
│                                                                    │
│  Memory is injected into LLM prompts to inform decisions           │
└────────┬──────────────────────┬──────────────────────┬─────────────┘
         │                      │                      │
         ▼                      ▼                      ▼
┌────────────────────────────────────────────────────────────────────┐
│                        LLM DECISION ENGINE                         │
│                                                                    │
│  System Prompt (positions + prices + memory + market rules)        │
│       ↓                                                            │
│  LLM (GPT-4o / Claude / DeepSeek / Qwen / Gemini)                 │
│       ↓                                                            │
│  Tool Calls: buy(), sell(), get_price_local()                      │
│       ↓                                                            │
│  Validation → Execution → Updated Positions → Loop or STOP        │
└────────────────────────────────────────────────────────────────────┘
         │                      │
         ▼                      ▼
┌──────────────────┐   ┌──────────────────┐
│  MCP Services    │   │   Alpaca API     │
│  (Backtesting)   │   │   (Live Trading) │
│                  │   │                  │
│  Port 8000: Math │   │  submit_order()  │
│  Port 8001: News │   │  get_account()   │
│  Port 8002: Trade│   │  list_positions()│
│  Port 8003: Price│   │  get_latest_bars()│
│  Port 8004: Ind. │   └──────────────────┘
│  Port 8006: Sent.│
└──────────────────┘
```

### Supported Markets and Agents

| Agent | Market | Symbols | Trading Frequency | Notes |
|-------|--------|---------|-------------------|-------|
| `BaseAgent` | US Stocks | NASDAQ 100 | Daily | Main stock trading agent |
| `BaseAgent_Hour` | US Stocks | NASDAQ 100 | Hourly | Intraday candlestick trading |
| `BaseAgentAStock` | China A-Shares | SSE 50 | Daily | T+1 rules, 100-share lot sizes |
| `BaseAgentAStock_Hour` | China A-Shares | SSE 50 | Hourly (10:30/11:30/14:00/15:00) | Intraday A-share trading |
| `BaseAgentCrypto` | Crypto | Bitwise 10 | Daily (24/7) | Fractional amounts, USDT pairs |

---

## Trade Execution

The system has two distinct execution paths depending on whether you are backtesting or live trading.

### Path 1: Backtesting (via `main.py`)

Trades are executed through an **LLM agentic loop** using LangChain and MCP tools. No real broker is involved; positions are tracked in local JSONL files.

**Execution flow:**

```
1. Load config (agent type, model, date range, initial cash)
2. Initialize MCP client (connects to services on ports 8000-8006)
3. Create LangChain agent with LLM model
4. Register agent with initial position: {CASH: 10000, all stocks: 0}
5. For each trading day in date range:
   │
   ├─ Build system prompt:
   │   - Current positions and cash balance
   │   - Yesterday's close prices
   │   - Today's open/buy prices
   │   - Strategy memory (learned insights + performance stats)
   │
   ├─ Agentic loop (up to max_steps iterations):
   │   │
   │   ├─ LLM analyzes market data and memory
   │   ├─ LLM calls tools:
   │   │   ├─ get_price_local(symbol, date) → OHLCV data
   │   │   ├─ buy(symbol, amount) → validates + updates position
   │   │   └─ sell(symbol, amount) → validates + updates position
   │   ├─ LLM receives updated positions
   │   └─ LLM continues reasoning or emits <FINISH_SIGNAL>
   │
   └─ Log all messages to data/{signature}/log/{date}/log.jsonl
```

**Trade validation in `agent_tools/tool_trade.py`:**

When the LLM calls `buy()` or `sell()`, the MCP tool:

1. Validates the symbol exists in the tracked universe
2. Checks market-specific rules (see table below)
3. Verifies sufficient cash balance: `CASH >= price * amount`
4. Reads the current position from `data/{signature}/position/position.jsonl`
5. Updates positions atomically using file locking
6. Returns the updated position dict to the LLM

| Market | Validation Rules |
|--------|-----------------|
| US Stocks | Positive integer share amounts, cash balance check |
| A-Shares (China) | Must be multiples of 100 shares, T+1 (cannot sell same-day purchases) |
| Crypto | Float amounts allowed (e.g., 0.05 BTC), no lot size or T+1 restrictions |

**Position storage format** (`position.jsonl`, one JSON object per line):

```json
{
  "date": "2026-01-21",
  "id": 3,
  "this_action": {"action": "buy", "symbol": "AAPL", "amount": 10},
  "positions": {"AAPL": 10, "MSFT": 5, "CASH": 7652.00}
}
```

### Path 2: Live Paper Trading (via `live_trader.py`)

Trades are executed against the **Alpaca paper trading API** using real market prices and simulated money.

**Execution flow:**

```
1. Connect to Alpaca paper trading API
2. Load strategy memory (if enabled)
3. Poll market every 60 seconds:
   │
   ├─ Check if market is open (9:30 AM - 4:00 PM EST)
   ├─ Fetch current prices from Alpaca for tracked symbols
   ├─ Get portfolio status (cash, positions, P/L)
   ├─ Build prompt with market data + strategy memory
   ├─ Send to OpenAI API for decision
   ├─ Parse JSON response: {action, symbol, quantity, reason}
   │
   ├─ If BUY or SELL:
   │   ├─ alpaca.submit_order(symbol, qty, side, type="market", time_in_force="day")
   │   └─ PerformanceTracker.record_trade(symbol, action, amount, price, reasoning)
   │
   └─ Wait 60 seconds, repeat
```

**Tracked symbols for live trading:**
AAPL, MSFT, NVDA, GOOGL, AMZN, META, TSLA

**The AI receives this data each cycle:**

```
ACCOUNT STATUS:
- Cash: $79,564.43
- Portfolio Value: $100,002.43
- Buying Power: $79,564.43

CURRENT POSITIONS:
- AAPL: 10 shares @ $250.00 (P/L: $45.00 / 1.8%)
- MSFT: 10 shares @ $470.00 (P/L: $28.00 / 0.6%)

CURRENT MARKET PRICES:
- AAPL: $254.50 (Today: +0.5%)
- MSFT: $472.80 (Today: -0.2%)
- NVDA: $186.30 (Today: +1.2%)

STRATEGY MEMORY (Apply these learnings!):
## LEARNED STRATEGY INSIGHTS:
1. Position sizing: Max 5-10% per stock [position-sizing, risk]
2. Enter only if RSI below 30 and rebounds [entry, technical]
3. ALWAYS close before earnings [exit, earnings, critical]

## TRADING PERFORMANCE:
- Win rate: 65.0% | Wins: 13, Losses: 7

## RECENT LOSSES TO LEARN FROM:
- TSLA: -4.1% loss - Entered on hype without confirmation
```

**The AI responds with:**

```json
{
  "action": "BUY",
  "symbol": "NVDA",
  "quantity": 5,
  "reason": "Strong momentum, diversifying portfolio"
}
```

### Risk Management

- Maximum 20% of portfolio in any single stock (live trading)
- Only trades tracked symbols (no penny stocks)
- Uses market orders for immediate execution
- Paper trading only (no real money at risk)
- Strategy memory enforces learned rules (position sizing, stop-losses, etc.)

---

## Strategy Memory System

Clawdbot has a persistent memory system that allows it to learn from past trades and strategy discussions. Memory is stored as JSONL files and injected into LLM prompts to inform trading decisions.

### How Memory Gets Created

There are three sources of strategy memory:

#### 1. Manual / Chat Input (`strategy_chat.py`)

Users discuss trading strategies in an interactive chat interface. The AI identifies valuable insights and marks them with `<SAVE_INSIGHT>` tags for automatic saving.

```bash
# Interactive strategy chat
python strategy_chat.py

# Quick-save a single insight
python strategy_chat.py --insight "Never hold NVDA through earnings"

# Check memory stats
python strategy_chat.py --stats
```

**Chat commands:** `quit`, `stats`, `insights`, `performance`, `save`

#### 2. Automatic from Trade Outcomes

The `PerformanceTracker` records every buy/sell trade with entry/exit prices. When a completed trade produces a significant result, an insight is auto-generated:

- **Big win (>= 5% gain):** `"Successful NVDA trade (+7.2%) - bought because: AI sector momentum"` — tagged `[win, nvda]`
- **Big loss (<= -5% loss):** `"Loss on TSLA (-6.1%) - avoid: Entered on hype without confirmation"` — tagged `[loss, tsla, lesson]`

**Performance thresholds:**

| Threshold | Value | Classification |
|-----------|-------|---------------|
| Win | >= 2% gain | Counted as win in stats |
| Loss | <= -2% loss | Counted as loss in stats |
| Big Win (auto-insight) | >= 5% gain | Generates automatic strategy insight |
| Big Loss (auto-insight) | <= -5% loss | Generates automatic strategy insight |

#### 3. Trade Outcome Tracking

Every trade is logged to `data/memory/trade_outcomes.jsonl`:

```json
{
  "id": 1,
  "timestamp": "2026-01-27T14:40:39.176324",
  "symbol": "NVDA",
  "action": "buy",
  "amount": 52,
  "entry_price": 189.05,
  "exit_price": null,
  "profit_pct": null,
  "reasoning": "Prioritize AI stock per strategy 9 and 10",
  "outcome": "pending"
}
```

When the matching sell completes, the entry is evaluated: `profit_pct = ((exit_price - entry_price) / entry_price) * 100`, and the outcome is set to `"win"`, `"loss"`, or `"neutral"`.

### Memory Storage Format

Insights are stored in `data/memory/strategy_insights.jsonl`, one JSON object per line:

```json
{
  "id": 1,
  "timestamp": "2026-01-27T14:30:14.423996",
  "insight": "Position sizing: Max 5-10% per stock",
  "context": {},
  "source": "manual",
  "tags": ["position-sizing", "risk"],
  "active": true
}
```

**Source types:** `"manual"`, `"chat"`, `"performance"`, `"backtest"`

Insights can be deactivated (without deleting) via `deactivate_insight(id, reason)` if they are proven wrong.

### How Memory Is Injected Into Prompts

The function `get_memory_context_for_prompt()` in `tools/memory_tools.py` assembles three sections and returns a formatted string:

1. **Up to 10 most recent active insights** — numbered, with tags and source
2. **Trading performance stats** — win rate, total trades, wins vs losses
3. **Last 3 losing trades** — symbol, loss %, and the reasoning that led to the loss

This string is inserted into the system prompt via a `{memory_section}` placeholder. The prompt explicitly instructs the LLM: *"Apply your learned strategy insights when making decisions."*

**Example of what the LLM sees:**

```
## LEARNED STRATEGY INSIGHTS:
1. Daily rebalancing for momentum/seasonality plays [timeframe, core] (from manual)
2. Position sizing: Max 5-10% per stock [position-sizing, risk] (from manual)
3. Use stop-loss at 2-5% below entry, take profits at 5-10% [risk, exits] (from manual)
4. Enter only if RSI below 30 and rebounds above it [entry, technical] (from manual)
5. ALWAYS close positions before earnings release [exit, earnings, critical] (from manual)

## TRADING PERFORMANCE:
- Win rate: 65.0%
- Total trades analyzed: 20
- Wins: 13, Losses: 7

## RECENT LOSSES TO LEARN FROM:
- AAPL: -3.2% loss - Held too long despite negative signals
- TSLA: -4.1% loss - Entered on hype without technical confirmation
```

### Memory Loading Frequency

| Mode | When Memory Is Loaded |
|------|----------------------|
| BaseAgent (backtesting) | Once at the start of each trading session |
| LiveTrader (live paper trading) | Every 60-second decision cycle (fresh reload) |
| Crypto / A-Stock agents | Not currently integrated (prompts lack `{memory_section}`) |

### The Feedback Loop

```
Save insight (chat / manual / auto from trade)
    → data/memory/strategy_insights.jsonl
        → get_memory_context_for_prompt()
            → Injected into LLM system prompt
                → LLM applies rules when trading
                    → Trade outcome recorded to trade_outcomes.jsonl
                        → Big win/loss auto-generates new insight
                            → Loop repeats
```

### Example Strategy Insights

These are real examples of the types of insights the system stores:

| Category | Example Insight | Tags |
|----------|----------------|------|
| Timing | Daily rebalancing for momentum/seasonality plays; midday focus 11:30 AM - 2:00 PM ET | `[timeframe, core]` |
| Position Sizing | Allocate no more than 5-10% of portfolio to any single Mag 7 stock | `[position-sizing, risk]` |
| Entry Signal | Enter only if RSI below 30 (oversold) and rebounds above it | `[entry, technical]` |
| Day Trade | Confirm with VWAP crossover or Bollinger Band squeeze for breakout potential | `[entry, technical, daytrade]` |
| Earnings | Buy 2-5 days before earnings if stock shows consistent pre-earnings run-ups | `[entry, earnings]` |
| Valuation | Prioritize stocks with PEG ratio < 1, especially after pullbacks | `[entry, valuation]` |
| Exit Rule | ALWAYS close positions before earnings release to avoid negative surprises | `[exit, earnings, critical]` |
| Risk | Limit to maximum 6 trades per day to prevent overtrading | `[risk, limits]` |
| Macro | Watch for AI hype fades, regulatory changes, or interest rate shifts | `[risk, macro]` |

---

## Sentiment Temperature

Clawdbot dynamically adjusts the LLM's **temperature** parameter based on real-time market sentiment, using the put/call ratio from the **MAGS ETF** (Roundhill Magnificent Seven ETF) as the signal.

### Concept

The LLM temperature controls how creative or conservative the AI's responses are. This system maps institutional options sentiment directly to that parameter:

| MAGS Put/Call Ratio | Market Sentiment | LLM Temperature | Trading Behavior |
|---------------------|-----------------|-----------------|------------------|
| > 1.1 | Extreme Fear | 0.1 (low) | Conservative, defensive |
| 0.85 - 1.1 | Fear | 0.2 - 0.4 | Risk-averse |
| 0.6 - 0.85 | Neutral | 0.4 - 0.6 | Balanced |
| 0.45 - 0.6 | Greed | 0.6 - 0.8 | Aggressive |
| < 0.45 | Extreme Greed | 0.9+ (high) | Highly exploratory |

### Two Modes

- **Trend-following** (default): Fear produces low temperature (play it safe), greed produces high temperature (ride the wave)
- **Contrarian**: Fear produces high temperature (look for buying opportunities), greed produces low temperature (be cautious at tops)

### Data Source

The system uses the **MAGS** ETF as primary signal because it holds exclusively the Magnificent 7 stocks (AAPL, MSFT, GOOGL, AMZN, NVDA, META, TSLA). Falls back to **QQQ** if MAGS options liquidity is too thin.

Options data is fetched via `yfinance`, aggregating put/call volume and open interest across the nearest 4 expiration dates for a robust signal.

### GUI Indicator

The live trader GUI includes a sentiment bar showing:
- Current sentiment label (color-coded from red to green)
- Temperature value
- Raw put/call ratio
- Visual temperature gauge bar
- Data source ticker and cache status

The indicator refreshes every 60 seconds during trading.

### Configuration

In any backtesting config JSON (`configs/*.json`):

```json
{
  "agent_config": {
    "sentiment_mode": "trend_following",
    "fixed_temperature": null
  }
}
```

| Parameter | Values | Description |
|-----------|--------|-------------|
| `sentiment_mode` | `"trend_following"`, `"contrarian"`, `null` | How to map P/C ratio to temperature. `null` disables sentiment (uses LLM default) |
| `fixed_temperature` | `null` or `0.0` - `1.0` | Override sentiment with a fixed temperature value |

### Architecture

```
MAGS/QQQ Options (via yfinance)
    │
    ▼
tools/sentiment_temperature.py
    ├─ fetch put/call ratio (4 nearest expirations)
    ├─ normalize via sigmoid curve → temperature (0.1 - 0.95)
    └─ cache result (60 min TTL)
         │
         ├──► BaseAgent.initialize() → ChatOpenAI(temperature=X)
         ├──► GUI sentiment indicator bar
         └──► MCP tool (port 8006) → agent can query during trading
```

---

## Installation

### Prerequisites

- Python 3.10 or higher
- Windows 10/11
- Internet connection

### Required API Keys

1. **OpenAI API Key**: Get from https://platform.openai.com/api-keys
2. **Alpaca API Key**: Sign up free at https://app.alpaca.markets/signup

### Setup Steps

1. **Install Python dependencies:**
   ```bash
   pip install alpaca-trade-api openai python-dotenv yfinance
   ```

2. **Configure API keys in `.env` file:**
   ```
   OPENAI_API_KEY=sk-your-openai-key-here
   ALPACA_API_KEY=your-alpaca-key
   ALPACA_SECRET_KEY=your-alpaca-secret
   ALPACA_BASE_URL=https://paper-api.alpaca.markets
   ```

3. **Run the trader:**
   ```bash
   python live_trader_gui.py
   ```

   Or double-click `START_TRADER.bat`

---

## Usage

### Starting the Trader

1. Double-click **"Clawdbot Trader"** shortcut on your desktop
2. Click **START** to begin AI trading
3. Watch the console for real-time updates

### Controls

| Button | Action |
|--------|--------|
| **START** | Begin AI trading loop |
| **PAUSE** | Pause AI decisions (keeps positions open) |
| **RESUME** | Resume AI trading after pause |
| **STOP** | Stop trading and SELL ALL positions |

### Console Color Guide

| Color | Meaning |
|-------|---------|
| Green | Normal info, successful actions |
| Yellow | Warnings, paused state |
| Red | Errors, stop commands |
| Cyan | Trade executions (BUY/SELL) |
| White | Price data |

---

## File Structure

```
AI-Trader/
├── main.py                          # Backtesting entry point
├── main_parrallel.py                # Parallel execution variant
├── live_trader.py                   # CLI live paper trading (Alpaca)
├── live_trader_gui.py               # GUI live paper trading
├── strategy_chat.py                 # Interactive strategy chat
├── START_TRADER.bat                 # Windows launcher
├── START_STRATEGY_CHAT.bat          # Strategy chat launcher
├── create_shortcut.vbs              # Desktop shortcut creator
├── .env                             # API keys (DO NOT SHARE!)
│
├── agent/                           # Agent classes (decision orchestration)
│   ├── base_agent/
│   │   └── base_agent.py            # Core agent: initialize(), run_trading_session()
│   ├── base_agent_hour/
│   │   └── base_agent_hour.py       # Hourly US stock agent
│   ├── base_agent_astock/
│   │   └── base_agent_astock.py     # Chinese A-share agent (T+1, lot sizes)
│   ├── base_agent_astock_hour/
│   │   └── base_agent_astock_hour.py# Hourly A-share agent
│   └── base_agent_crypto/
│       └── base_agent_crypto.py     # Crypto agent (fractional amounts)
│
├── agent_tools/                     # MCP tool endpoints (trade execution)
│   ├── tool_trade.py                # buy(), sell() for stocks
│   ├── tool_crypto_trade.py         # buy_crypto(), sell_crypto() for crypto
│   ├── tool_get_price_local.py      # get_price_local() OHLCV data
│   ├── tool_indicators.py           # RSI, VWAP, Bollinger Bands, Momentum Score
│   ├── tool_alphavantage_news.py    # News/search via AlphaVantage
│   ├── tool_sentiment_temperature.py# Sentiment temperature MCP service (port 8006)
│   └── start_mcp_services.py       # Launches all MCP services
│
├── prompts/                         # System prompt templates
│   ├── agent_prompt.py              # US stock prompt (includes memory injection)
│   ├── agent_prompt_astock.py       # A-share prompt (Chinese market rules)
│   └── agent_prompt_crypto.py       # Crypto prompt
│
├── tools/                           # Shared utilities
│   ├── memory_tools.py              # Strategy memory: save/load/format insights
│   ├── performance_tracker.py       # Trade outcome tracking and win rates
│   ├── sentiment_temperature.py     # MAGS/QQQ P/C ratio → LLM temperature
│   ├── price_tools.py               # Price data access, position lookup
│   └── general_tools.py             # Config persistence, parsing
│
├── configs/                         # Trading configurations
│   ├── default_config.json          # US stock config
│   ├── default_astock_config.json   # A-share config
│   ├── astock_hour_config.json      # A-share hourly config
│   └── default_crypto_config.json   # Crypto config
│
├── data/                            # Market data and runtime state
│   ├── merged.jsonl                 # US stock price data
│   ├── get_price_yahoo.py           # Yahoo Finance price fetcher
│   ├── A_stock/merged.jsonl         # A-share price data
│   ├── crypto/crypto_merged.jsonl   # Crypto price data
│   ├── memory/                      # Persistent strategy memory
│   │   ├── strategy_insights.jsonl  # Learned trading rules
│   │   ├── trade_outcomes.jsonl     # Trade history with P/L
│   │   └── conversations.jsonl      # Saved strategy chats
│   ├── sentiment/                   # Sentiment temperature cache
│   │   └── temperature_cache.json   # Cached P/C ratio + temperature
│   └── {signature}/                 # Per-model runtime data
│       ├── position/position.jsonl  # Position history (one txn per line)
│       └── log/{date}/log.jsonl     # Agent conversation logs
│
├── CLAUDE.md                        # Development notes
└── README.md                        # This file
```

---

## Configuration

### Live Trading Configuration

Edit these values in `live_trader_gui.py` to customize live trading:

```python
# Stocks to trade
SYMBOLS = ["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA"]

# Time between AI decisions (seconds)
TRADE_INTERVAL = 60

# Maximum portfolio allocation per stock (0.2 = 20%)
MAX_POSITION_SIZE = 0.2
```

### Backtesting Configuration

Backtesting is configured via JSON files in `configs/`. Example (`default_config.json`):

```json
{
  "agent_type": "BaseAgent_Hour",
  "market": "us",
  "date_range": {
    "init_date": "2026-01-21 09:30:00",
    "end_date": "2026-01-23 15:30:00"
  },
  "models": [
    {
      "name": "gpt-4o-mini",
      "basemodel": "gpt-4o-mini",
      "signature": "gpt-4o-mini",
      "enabled": true,
      "openai_base_url": null,
      "openai_api_key": null
    }
  ],
  "agent_config": {
    "max_steps": 15,
    "max_retries": 3,
    "base_delay": 1.0,
    "initial_cash": 10000.0,
    "verbose": true,
    "sentiment_mode": "trend_following"
  },
  "log_config": {
    "log_path": "./data/agent_data"
  }
}
```

**Agent config parameters:**

| Parameter | Default | Description |
|-----------|---------|-------------|
| `max_steps` | 10-30 | Agentic reasoning iterations per trading day |
| `max_retries` | 3 | API failure retry attempts (exponential backoff) |
| `base_delay` | 0.5-1.0 | Base delay in seconds before retries |
| `initial_cash` | 10,000-50,000 | Starting portfolio value |
| `verbose` | true/false | Enable LangChain debug logging |
| `sentiment_mode` | `"trend_following"` | `"trend_following"`, `"contrarian"`, or `null` to disable |
| `fixed_temperature` | `null` | Override sentiment with a fixed temperature (0.0-1.0) |

**Supported LLM models:** gpt-4o, gpt-4o-mini, claude-3.7-sonnet, deepseek-chat-v3.1, qwen3-max, MiniMax-M2, gemini-2.5-flash

---

## Three Operating Modes

### 1. Live Paper Trading (Real-time with Alpaca)

Uses real market prices, executes trades on your Alpaca paper account ($100,000 fake money).

```bash
# GUI version
python live_trader_gui.py

# Command-line version
python -u live_trader.py
```

### 2. Backtesting (Historical Simulation)

Tests AI strategies on historical price data with simulated execution via MCP tools.

```bash
# US stocks
python main.py configs/default_config.json

# Chinese A-shares
python main.py configs/default_astock_config.json

# Cryptocurrency
python main.py configs/default_crypto_config.json
```

### 3. Strategy Chat (Learning & Improvement)

Interactive chat for discussing and refining trading strategies. Insights are saved to memory.

```bash
# Interactive chat
python strategy_chat.py

# Quick-save an insight
python strategy_chat.py --insight "Buy tech dips on Mondays"

# Check memory stats
python strategy_chat.py --stats
```

---

## Safety & Disclaimers

1. **Paper Trading Only**: This system uses Alpaca's paper trading by default. No real money is at risk.

2. **API Key Security**:
   - Never share your `.env` file
   - Never commit API keys to git
   - Regenerate keys if accidentally exposed

3. **Market Hours**: US stock market hours are 9:30 AM - 4:00 PM Eastern Time, Monday-Friday (excluding holidays).

4. **No Financial Advice**: This is an educational project. AI trading is experimental and unpredictable. Past performance does not guarantee future results.

5. **Use at Your Own Risk**: The developers are not responsible for any losses incurred.

---

## Troubleshooting

### "Market is CLOSED"
The US stock market only operates 9:30 AM - 4:00 PM Eastern Time, Monday-Friday.

### "Could not get prices"
- Check your internet connection
- Verify Alpaca API status at https://status.alpaca.markets

### "Invalid API key" (401 error)
- Double-check your API keys in `.env`
- Ensure no extra spaces or quotes
- For OpenAI: verify key at https://platform.openai.com/api-keys
- For Alpaca: regenerate keys if needed

### GUI doesn't open
Run from command line to see error messages:
```bash
python live_trader_gui.py
```

### "Module not found" errors
Install missing dependencies:
```bash
pip install alpaca-trade-api openai python-dotenv tkinter
```

---

## Credits

- **AI Engines**: OpenAI (GPT-4o), Anthropic (Claude), DeepSeek, Qwen, Google (Gemini), MiniMax
- **Trading Platform**: Alpaca Markets (paper trading)
- **Original Framework**: Based on AI-Trader by HKUDS
- **Agent Framework**: LangChain with MCP (Model Context Protocol)
- **Price Data**: Yahoo Finance, Alpha Vantage
- **Sentiment Data**: MAGS/QQQ options via yfinance

---

## License

MIT License - For educational and personal use only.

**This is not financial advice. Trade responsibly.**
