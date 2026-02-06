#!/usr/bin/env python3
"""
Clawdbot Live Trader - Real-time AI Trading with Alpaca
Uses GPT to analyze markets and execute trades in real-time
Now with MEMORY - learns from past trades and strategy insights!
"""

import os
import sys
import json
import time
from datetime import datetime
from dotenv import load_dotenv

# Fix Windows encoding and buffering
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

# Unbuffered output
sys.stdout = os.fdopen(sys.stdout.fileno(), 'w', buffering=1)

load_dotenv()

import alpaca_trade_api as tradeapi
from openai import OpenAI

# Import memory tools
try:
    from tools.memory_tools import (
        format_insights_for_prompt,
        get_memory_context_for_prompt,
        save_strategy_insight
    )
    from tools.performance_tracker import PerformanceTracker
    MEMORY_ENABLED = True
except ImportError:
    MEMORY_ENABLED = False
    print("Warning: Memory tools not available. Running without memory.")

# Configuration
SYMBOLS = ["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA"]  # Stocks to trade
TRADE_INTERVAL = 60  # Seconds between trading decisions
MAX_POSITION_SIZE = 0.2  # Max 20% of portfolio in one stock


class LiveTrader:
    def __init__(self):
        # Initialize Alpaca
        self.api = tradeapi.REST(
            os.getenv('ALPACA_API_KEY'),
            os.getenv('ALPACA_SECRET_KEY'),
            os.getenv('ALPACA_BASE_URL'),
            api_version='v2'
        )

        # Initialize OpenAI
        self.openai = OpenAI(
            api_key=os.getenv('OPENAI_API_KEY'),
            base_url=os.getenv('OPENAI_API_BASE', 'https://api.openai.com/v1')
        )

        self.model = "gpt-4o-mini"

        # Initialize performance tracker for memory
        if MEMORY_ENABLED:
            self.tracker = PerformanceTracker("live-trader")
            print("Memory system enabled - learning from trades!")
        else:
            self.tracker = None

    def get_account(self):
        """Get account info"""
        return self.api.get_account()

    def get_positions(self):
        """Get current positions"""
        return self.api.list_positions()

    def get_current_prices(self, symbols):
        """Get current prices for symbols"""
        prices = {}
        try:
            bars = self.api.get_latest_bars(symbols)
            for symbol in symbols:
                if symbol in bars:
                    prices[symbol] = {
                        'price': float(bars[symbol].c),
                        'open': float(bars[symbol].o),
                        'high': float(bars[symbol].h),
                        'low': float(bars[symbol].l),
                        'volume': int(bars[symbol].v)
                    }
        except Exception as e:
            print(f"Error getting prices: {e}")
        return prices

    def get_market_status(self):
        """Check if market is open"""
        clock = self.api.get_clock()
        return clock.is_open

    def format_portfolio_status(self):
        """Format current portfolio for AI"""
        account = self.get_account()
        positions = self.get_positions()

        status = f"""
ACCOUNT STATUS:
- Cash: ${float(account.cash):,.2f}
- Portfolio Value: ${float(account.portfolio_value):,.2f}
- Buying Power: ${float(account.buying_power):,.2f}

CURRENT POSITIONS:
"""
        if positions:
            for pos in positions:
                pnl = float(pos.unrealized_pl)
                pnl_pct = float(pos.unrealized_plpc) * 100
                status += f"- {pos.symbol}: {pos.qty} shares @ ${float(pos.avg_entry_price):.2f} (P/L: ${pnl:,.2f} / {pnl_pct:.1f}%)\n"
        else:
            status += "- No positions\n"

        return status, float(account.cash), float(account.buying_power)

    def get_ai_decision(self, prices, portfolio_status, cash, buying_power):
        """Get trading decision from AI with memory context"""

        price_info = "CURRENT MARKET PRICES:\n"
        for symbol, data in prices.items():
            change = ((data['price'] - data['open']) / data['open']) * 100
            price_info += f"- {symbol}: ${data['price']:.2f} (Today: {change:+.2f}%)\n"

        # Get memory context if available
        memory_section = ""
        if MEMORY_ENABLED:
            try:
                memory_context = get_memory_context_for_prompt()
                if memory_context and "No previous strategy insights" not in memory_context:
                    memory_section = f"""
STRATEGY MEMORY (Apply these learnings!):
{memory_context}
"""
            except Exception as e:
                print(f"  Warning: Could not load memory: {e}")

        prompt = f"""You are Clawdbot, an AI stock trader with memory of past strategies and learnings.
{memory_section}
{portfolio_status}

{price_info}

Available cash: ${cash:,.2f}
Buying power: ${buying_power:,.2f}

RULES:
1. You can only trade these stocks: {', '.join(SYMBOLS)}
2. Maximum position size: {MAX_POSITION_SIZE*100}% of portfolio per stock
3. Consider risk management - don't go all-in
4. You can BUY, SELL, or HOLD
5. IMPORTANT: Apply any relevant strategy insights from your memory!

Respond with EXACTLY ONE JSON object (no other text):
{{"action": "BUY" or "SELL" or "HOLD", "symbol": "TICKER", "quantity": NUMBER, "reason": "brief reason"}}

Examples:
{{"action": "BUY", "symbol": "AAPL", "quantity": 5, "reason": "Strong momentum, diversifying portfolio"}}
{{"action": "SELL", "symbol": "TSLA", "quantity": 3, "reason": "Taking profits after 10% gain"}}
{{"action": "HOLD", "symbol": "", "quantity": 0, "reason": "Market uncertain, preserving capital"}}
"""

        try:
            response = self.openai.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are a professional stock trader. Always respond with valid JSON only."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                max_tokens=200
            )

            content = response.choices[0].message.content.strip()
            # Extract JSON from response
            if '{' in content and '}' in content:
                json_str = content[content.find('{'):content.rfind('}')+1]
                return json.loads(json_str)
            return {"action": "HOLD", "symbol": "", "quantity": 0, "reason": "Could not parse response"}

        except Exception as e:
            print(f"AI Error: {e}")
            return {"action": "HOLD", "symbol": "", "quantity": 0, "reason": f"Error: {e}"}

    def execute_trade(self, decision, prices):
        """Execute the trading decision and track for learning"""
        action = decision.get('action', 'HOLD').upper()
        symbol = decision.get('symbol', '')
        quantity = int(decision.get('quantity', 0))
        reason = decision.get('reason', '')

        if action == 'HOLD' or quantity <= 0:
            print(f"  Decision: HOLD - {reason}")
            return None

        # Position size enforcement for buys
        if action == 'BUY' and symbol in prices:
            try:
                account = self.get_account()
                portfolio_value = float(account.portfolio_value)
                if portfolio_value > 0:
                    # Current position value for this symbol
                    current_value = 0
                    for pos in self.get_positions():
                        if pos.symbol == symbol:
                            current_value = float(pos.market_value)
                            break
                    proposed_value = current_value + quantity * prices[symbol]['price']
                    position_pct = proposed_value / portfolio_value
                    if position_pct > MAX_POSITION_SIZE:
                        max_qty = int((MAX_POSITION_SIZE * portfolio_value - current_value) / prices[symbol]['price'])
                        if max_qty <= 0:
                            print(f"  REJECTED: {symbol} already at max position size ({position_pct*100:.1f}% > {MAX_POSITION_SIZE*100}%)")
                            return None
                        print(f"  WARNING: Reducing {symbol} quantity from {quantity} to {max_qty} to stay under {MAX_POSITION_SIZE*100}% limit")
                        quantity = max_qty
            except Exception as e:
                print(f"  Warning: Could not check position size: {e}")

        try:
            if action == 'BUY':
                order = self.api.submit_order(
                    symbol=symbol,
                    qty=quantity,
                    side='buy',
                    type='market',
                    time_in_force='day'
                )
                print(f"  BUY ORDER: {quantity} {symbol} - {reason}")

                # Track for memory/learning
                if self.tracker and symbol in prices:
                    self.tracker.record_trade(
                        symbol=symbol,
                        action="buy",
                        amount=quantity,
                        price=prices[symbol]['price'],
                        reasoning=reason
                    )
                    print(f"  [Memory] Tracking buy for future analysis")

                return order

            elif action == 'SELL':
                order = self.api.submit_order(
                    symbol=symbol,
                    qty=quantity,
                    side='sell',
                    type='market',
                    time_in_force='day'
                )
                print(f"  SELL ORDER: {quantity} {symbol} - {reason}")

                # Track for memory/learning
                if self.tracker and symbol in prices:
                    self.tracker.record_trade(
                        symbol=symbol,
                        action="sell",
                        amount=quantity,
                        price=prices[symbol]['price'],
                        reasoning=reason
                    )
                    print(f"  [Memory] Trade outcome recorded")

                return order

        except Exception as e:
            print(f"  Trade Error: {e}")
            return None

    def run(self):
        """Main trading loop"""
        print("=" * 60)
        print("  CLAWDBOT LIVE TRADER")
        print("  Real-time AI Trading with Alpaca Paper Trading")
        print("  Now with MEMORY - Learning from every trade!")
        print("=" * 60)

        # Check account
        account = self.get_account()
        print(f"\nAccount Status: {account.status}")
        print(f"Portfolio Value: ${float(account.portfolio_value):,.2f}")
        print(f"Cash: ${float(account.cash):,.2f}")
        print(f"Trading Symbols: {', '.join(SYMBOLS)}")
        print(f"Trade Interval: {TRADE_INTERVAL} seconds")

        # Show memory status
        if MEMORY_ENABLED:
            try:
                from tools.memory_tools import get_memory_stats
                stats = get_memory_stats()
                print(f"\nMemory Status:")
                print(f"  Strategy insights: {stats['strategy_insights']}")
                print(f"  Tracked trades: {stats['trade_outcomes']}")
                if stats['win_rate']['total_trades'] > 0:
                    print(f"  Historical win rate: {stats['win_rate']['win_rate']:.1f}%")
            except Exception as e:
                print(f"  Could not load memory stats: {e}")

        print("\n" + "=" * 60)

        trade_count = 0

        while True:
            try:
                now = datetime.now()
                print(f"\n[{now.strftime('%Y-%m-%d %H:%M:%S')}] Checking market...")

                # Check market status
                if not self.get_market_status():
                    print("  Market is CLOSED. Waiting...")
                    time.sleep(60)
                    continue

                print("  Market is OPEN")

                # Get current data
                prices = self.get_current_prices(SYMBOLS)
                if not prices:
                    print("  Could not get prices. Waiting...")
                    time.sleep(30)
                    continue

                portfolio_status, cash, buying_power = self.format_portfolio_status()

                # Display current prices
                print("\n  Current Prices:")
                for symbol, data in prices.items():
                    change = ((data['price'] - data['open']) / data['open']) * 100
                    print(f"    {symbol}: ${data['price']:.2f} ({change:+.2f}%)")

                # Get AI decision
                print("\n  Asking AI for trading decision...")
                decision = self.get_ai_decision(prices, portfolio_status, cash, buying_power)

                # Execute trade (pass prices for memory tracking)
                order = self.execute_trade(decision, prices)
                if order:
                    trade_count += 1
                    print(f"  Total trades today: {trade_count}")

                # Show updated portfolio
                print("\n  Portfolio Update:")
                positions = self.get_positions()
                if positions:
                    for pos in positions:
                        print(f"    {pos.symbol}: {pos.qty} shares (${float(pos.market_value):,.2f})")
                else:
                    print("    No positions")

                account = self.get_account()
                print(f"    Cash: ${float(account.cash):,.2f}")
                print(f"    Total Value: ${float(account.portfolio_value):,.2f}")

                # Wait for next interval
                print(f"\n  Waiting {TRADE_INTERVAL} seconds until next check...")
                time.sleep(TRADE_INTERVAL)

            except KeyboardInterrupt:
                print("\n\nStopping trader...")
                break
            except Exception as e:
                print(f"  Error: {e}")
                time.sleep(30)


def main():
    print("\nInitializing Clawdbot Live Trader...")

    # Verify credentials
    required = ['ALPACA_API_KEY', 'ALPACA_SECRET_KEY', 'OPENAI_API_KEY']
    missing = [k for k in required if not os.getenv(k)]
    if missing:
        print(f"Error: Missing environment variables: {missing}")
        return

    trader = LiveTrader()

    # Test connection
    try:
        account = trader.get_account()
        print(f"Connected to Alpaca! Account: {account.status}")
    except Exception as e:
        print(f"Failed to connect to Alpaca: {e}")
        return

    trader.run()


if __name__ == "__main__":
    main()
