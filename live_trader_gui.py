#!/usr/bin/env python3
"""
Clawdbot Live Trader GUI - Real-time AI Trading with Alpaca
Console window with pause/resume functionality
Now with integrated Strategy Chat!
"""

import os
import sys
import json
import time
import re
import threading
from datetime import datetime
from dotenv import load_dotenv
import tkinter as tk
from tkinter import scrolledtext, ttk

load_dotenv()

import alpaca_trade_api as tradeapi
from openai import OpenAI

# Import memory tools
try:
    from tools.memory_tools import (
        save_strategy_insight,
        format_insights_for_prompt,
        get_memory_stats,
        get_memory_context_for_prompt,
        save_conversation,
        clear_strategy_insights
    )
    from tools.performance_tracker import PerformanceTracker
    MEMORY_ENABLED = True
except ImportError:
    MEMORY_ENABLED = False

# Import sentiment temperature
try:
    from tools.sentiment_temperature import get_sentiment_temperature
    SENTIMENT_ENABLED = True
except ImportError:
    SENTIMENT_ENABLED = False

# Configuration
SYMBOLS = ["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA"]
TRADE_INTERVAL = 60
MAX_POSITION_SIZE = 0.2

# AI Provider configurations
AI_PROVIDERS = {
    "DeepSeek (deepseek-chat)": {
        "api_key_env": "DEEPSEEK_API_KEY",
        "base_url_env": "DEEPSEEK_API_BASE",
        "base_url_default": "https://api.deepseek.com/v1",
        "model": "deepseek-chat"
    },
    "DeepSeek (deepseek-reasoner)": {
        "api_key_env": "DEEPSEEK_API_KEY",
        "base_url_env": "DEEPSEEK_API_BASE",
        "base_url_default": "https://api.deepseek.com/v1",
        "model": "deepseek-reasoner"
    },
    "OpenAI (gpt-4o-mini)": {
        "api_key_env": "OPENAI_API_KEY",
        "base_url_env": "OPENAI_API_BASE",
        "base_url_default": "https://api.openai.com/v1",
        "model": "gpt-4o-mini"
    },
    "OpenAI (gpt-4o)": {
        "api_key_env": "OPENAI_API_KEY",
        "base_url_env": "OPENAI_API_BASE",
        "base_url_default": "https://api.openai.com/v1",
        "model": "gpt-4o"
    },
    "xAI (grok-2)": {
        "api_key_env": "XAI_API_KEY",
        "base_url_env": "XAI_API_BASE",
        "base_url_default": "https://api.x.ai/v1",
        "model": "grok-2-latest"
    },
    "xAI (grok-3)": {
        "api_key_env": "XAI_API_KEY",
        "base_url_env": "XAI_API_BASE",
        "base_url_default": "https://api.x.ai/v1",
        "model": "grok-3"
    },
    "xAI (grok-3-mini)": {
        "api_key_env": "XAI_API_KEY",
        "base_url_env": "XAI_API_BASE",
        "base_url_default": "https://api.x.ai/v1",
        "model": "grok-3-mini"
    },
    "xAI (grok-4)": {
        "api_key_env": "XAI_API_KEY",
        "base_url_env": "XAI_API_BASE",
        "base_url_default": "https://api.x.ai/v1",
        "model": "grok-4"
    }
}


class TradingGUI:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Clawdbot Live Trader")
        self.root.geometry("1000x800")
        self.root.configure(bg='#1a1a2e')

        # State
        self.paused = False
        self.running = False
        self.trade_count = 0
        self._trade_lock = threading.Lock()

        # Chat state
        self.chat_messages = []
        self.chat_processing = False

        # Initialize APIs
        self.api = tradeapi.REST(
            os.getenv('ALPACA_API_KEY'),
            os.getenv('ALPACA_SECRET_KEY'),
            os.getenv('ALPACA_BASE_URL'),
            api_version='v2'
        )

        # Performance tracker for memory
        if MEMORY_ENABLED:
            self.tracker = PerformanceTracker("live-trader-gui")
        else:
            self.tracker = None

        # AI Provider setup - select first available provider
        self.openai = None
        self.model = None
        self.current_provider = None

        # Try to find an available provider
        for provider_name in AI_PROVIDERS.keys():
            config = AI_PROVIDERS[provider_name]
            if os.getenv(config["api_key_env"]):
                self.current_provider = provider_name
                self.set_ai_provider(provider_name)
                break

        self.setup_gui()

    def set_ai_provider(self, provider_name):
        """Set the AI provider and reinitialize the client"""
        if provider_name not in AI_PROVIDERS:
            return False

        config = AI_PROVIDERS[provider_name]
        api_key = os.getenv(config["api_key_env"])
        base_url = os.getenv(config["base_url_env"], config["base_url_default"])

        if not api_key:
            if hasattr(self, 'console'):
                self.log(f"Error: {config['api_key_env']} not found in environment", 'error')
            return False

        self.openai = OpenAI(api_key=api_key, base_url=base_url, timeout=60.0)
        self.model = config["model"]
        self.current_provider = provider_name

        if hasattr(self, 'model_label'):
            self.model_label.config(text=f"Model: {self.model}")

        # Update chat tab AI label
        if hasattr(self, 'chat_ai_label'):
            self.chat_ai_label.config(text=f"AI: {self.model}")

        if hasattr(self, 'console'):
            self.log(f"Switched to: {provider_name} (model: {self.model})", 'info')

        # Also log in chat if available
        if hasattr(self, 'chat_display'):
            self.chat_log(f"AI Provider changed to: {self.model}", 'system')

        return True

    def on_provider_change(self, event=None):
        """Handle AI provider dropdown change"""
        selected = self.provider_var.get()
        if selected != self.current_provider:
            success = self.set_ai_provider(selected)
            if not success:
                # Revert to previous selection
                self.provider_var.set(self.current_provider)

    def setup_gui(self):
        # Title
        title_frame = tk.Frame(self.root, bg='#1a1a2e')
        title_frame.pack(fill='x', padx=10, pady=10)

        title = tk.Label(title_frame, text="CLAWDBOT LIVE TRADER",
                        font=('Consolas', 20, 'bold'), fg='#00ff88', bg='#1a1a2e')
        title.pack()

        subtitle_text = "Real-time AI Trading with Alpaca Paper Trading"
        if MEMORY_ENABLED:
            subtitle_text += " | Memory Enabled"
        subtitle = tk.Label(title_frame, text=subtitle_text,
                           font=('Consolas', 10), fg='#888888', bg='#1a1a2e')
        subtitle.pack()

        # Status bar
        status_frame = tk.Frame(self.root, bg='#16213e')
        status_frame.pack(fill='x', padx=10, pady=5)

        self.status_label = tk.Label(status_frame, text="Status: STOPPED",
                                     font=('Consolas', 12, 'bold'), fg='#ff6b6b', bg='#16213e')
        self.status_label.pack(side='left', padx=10, pady=5)

        self.portfolio_label = tk.Label(status_frame, text="Portfolio: $0.00",
                                        font=('Consolas', 12), fg='#4ecdc4', bg='#16213e')
        self.portfolio_label.pack(side='right', padx=10, pady=5)

        self.cash_label = tk.Label(status_frame, text="Cash: $0.00",
                                   font=('Consolas', 12), fg='#ffe66d', bg='#16213e')
        self.cash_label.pack(side='right', padx=10, pady=5)

        # P&L and Win Rate bar
        pl_frame = tk.Frame(self.root, bg='#16213e')
        pl_frame.pack(fill='x', padx=10, pady=2)

        self.daily_pl_label = tk.Label(pl_frame, text="Daily P/L: $0.00",
                                        font=('Consolas', 12, 'bold'), fg='#00ff88', bg='#16213e')
        self.daily_pl_label.pack(side='left', padx=10, pady=5)

        self.winrate_label = tk.Label(pl_frame, text="Win Rate: --",
                                       font=('Consolas', 12), fg='#4ecdc4', bg='#16213e')
        self.winrate_label.pack(side='right', padx=10, pady=5)

        # Sentiment Temperature indicator
        sentiment_frame = tk.Frame(self.root, bg='#16213e')
        sentiment_frame.pack(fill='x', padx=10, pady=2)

        temp_icon = tk.Label(sentiment_frame, text="SENTIMENT",
                             font=('Consolas', 9, 'bold'), fg='#888888', bg='#16213e')
        temp_icon.pack(side='left', padx=(10, 5), pady=5)

        self.sentiment_label = tk.Label(sentiment_frame, text="--",
                                         font=('Consolas', 12, 'bold'), fg='#888888', bg='#16213e')
        self.sentiment_label.pack(side='left', padx=5, pady=5)

        self.temp_value_label = tk.Label(sentiment_frame, text="Temp: --",
                                          font=('Consolas', 11), fg='#888888', bg='#16213e')
        self.temp_value_label.pack(side='left', padx=10, pady=5)

        self.pc_ratio_label = tk.Label(sentiment_frame, text="P/C: --",
                                        font=('Consolas', 11), fg='#888888', bg='#16213e')
        self.pc_ratio_label.pack(side='left', padx=10, pady=5)

        self.temp_bar_canvas = tk.Canvas(sentiment_frame, width=200, height=20,
                                          bg='#0f0f23', highlightthickness=1,
                                          highlightbackground='#333333')
        self.temp_bar_canvas.pack(side='left', padx=10, pady=5)

        self.sentiment_source_label = tk.Label(sentiment_frame, text="",
                                                font=('Consolas', 9), fg='#555555', bg='#16213e')
        self.sentiment_source_label.pack(side='right', padx=10, pady=5)

        # Initial sentiment fetch
        if SENTIMENT_ENABLED:
            threading.Thread(target=self.update_sentiment_display, daemon=True).start()

        # AI Provider selector
        ai_frame = tk.Frame(self.root, bg='#1a1a2e')
        ai_frame.pack(fill='x', padx=10, pady=5)

        ai_label = tk.Label(ai_frame, text="AI Provider:",
                           font=('Consolas', 11), fg='#ffffff', bg='#1a1a2e')
        ai_label.pack(side='left', padx=5)

        self.provider_var = tk.StringVar(value=self.current_provider)
        self.provider_dropdown = ttk.Combobox(ai_frame, textvariable=self.provider_var,
                                               values=list(AI_PROVIDERS.keys()),
                                               state='readonly', width=25,
                                               font=('Consolas', 10))
        self.provider_dropdown.pack(side='left', padx=5)
        self.provider_dropdown.bind('<<ComboboxSelected>>', self.on_provider_change)

        # Style the combobox
        style = ttk.Style()
        style.theme_use('clam')
        style.configure('TCombobox', fieldbackground='#16213e', background='#16213e',
                       foreground='#00ff88', arrowcolor='#00ff88')

        self.model_label = tk.Label(ai_frame, text=f"Model: {self.model}",
                                    font=('Consolas', 10), fg='#4ecdc4', bg='#1a1a2e')
        self.model_label.pack(side='left', padx=15)

        # Control buttons
        btn_frame = tk.Frame(self.root, bg='#1a1a2e')
        btn_frame.pack(fill='x', padx=10, pady=10)

        self.start_btn = tk.Button(btn_frame, text="START", command=self.start_trading,
                                   font=('Consolas', 12, 'bold'), bg='#00ff88', fg='#000000',
                                   width=12, height=2, cursor='hand2')
        self.start_btn.pack(side='left', padx=5)

        self.pause_btn = tk.Button(btn_frame, text="PAUSE", command=self.toggle_pause,
                                   font=('Consolas', 12, 'bold'), bg='#ffe66d', fg='#000000',
                                   width=12, height=2, cursor='hand2', state='disabled')
        self.pause_btn.pack(side='left', padx=5)

        self.stop_btn = tk.Button(btn_frame, text="STOP", command=self.stop_trading,
                                  font=('Consolas', 12, 'bold'), bg='#ff6b6b', fg='#000000',
                                  width=12, height=2, cursor='hand2', state='disabled')
        self.stop_btn.pack(side='left', padx=5)

        # Trade count
        self.trade_label = tk.Label(btn_frame, text="Trades: 0",
                                    font=('Consolas', 12), fg='#ffffff', bg='#1a1a2e')
        self.trade_label.pack(side='right', padx=10)

        # Notebook (tabs)
        style = ttk.Style()
        style.theme_use('clam')
        style.configure('TNotebook', background='#1a1a2e', borderwidth=0)
        style.configure('TNotebook.Tab', background='#16213e', foreground='#00ff88',
                       padding=[15, 8], font=('Consolas', 11, 'bold'))
        style.map('TNotebook.Tab', background=[('selected', '#0f0f23')],
                 foreground=[('selected', '#00ff88')])

        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill='both', expand=True, padx=10, pady=10)

        # === TRADING TAB ===
        trading_frame = tk.Frame(self.notebook, bg='#1a1a2e')
        self.notebook.add(trading_frame, text='  Trading  ')

        self.console = scrolledtext.ScrolledText(trading_frame,
                                                  font=('Consolas', 10),
                                                  bg='#0f0f23', fg='#00ff88',
                                                  insertbackground='#00ff88',
                                                  wrap='word')
        self.console.pack(fill='both', expand=True)

        # Configure tags for colors
        self.console.tag_configure('info', foreground='#00ff88')
        self.console.tag_configure('warning', foreground='#ffe66d')
        self.console.tag_configure('error', foreground='#ff6b6b')
        self.console.tag_configure('trade', foreground='#4ecdc4')
        self.console.tag_configure('price', foreground='#ffffff')
        self.console.tag_configure('header', foreground='#00ff88', font=('Consolas', 10, 'bold'))

        self.log("=" * 60, 'header')
        self.log("  CLAWDBOT LIVE TRADER INITIALIZED", 'header')
        self.log("=" * 60, 'header')
        self.log(f"AI Provider: {self.current_provider}", 'info')
        self.log(f"Trading Symbols: {', '.join(SYMBOLS)}", 'info')
        self.log(f"Trade Interval: {TRADE_INTERVAL} seconds", 'info')
        if MEMORY_ENABLED:
            self.log("Memory System: ENABLED", 'info')
        self.log("Click START to begin trading\n", 'info')

        # === STRATEGY CHAT TAB ===
        self.setup_chat_tab()

        # Update account info
        self.update_account_display()

        # Start background account updater (every 5 seconds)
        self.account_update_thread = threading.Thread(target=self.account_update_loop, daemon=True)
        self.account_update_thread.start()

    def log(self, message, tag='info'):
        """Log message to console"""
        timestamp = datetime.now().strftime('%H:%M:%S')
        self.console.insert('end', f"[{timestamp}] {message}\n", tag)
        self.console.see('end')

    def update_account_display(self):
        """Update account info display including P&L and win rate"""
        try:
            account = self.api.get_account()
            cash = float(account.cash)
            portfolio = float(account.portfolio_value)
            self.cash_label.config(text=f"Cash: ${cash:,.2f}")
            self.portfolio_label.config(text=f"Portfolio: ${portfolio:,.2f}")

            # Update daily P/L and win rate
            positions = self.api.list_positions()
            if positions:
                total_pl = sum(float(p.unrealized_pl) for p in positions)
                winners = sum(1 for p in positions if float(p.unrealized_pl) > 0)
                losers = sum(1 for p in positions if float(p.unrealized_pl) < 0)
                total = winners + losers
                win_rate = (winners / total * 100) if total > 0 else 0

                sign = "+" if total_pl >= 0 else ""
                pl_color = '#00ff88' if total_pl >= 0 else '#ff6b6b'
                self.daily_pl_label.config(text=f"Daily P/L: {sign}${total_pl:,.2f}", fg=pl_color)
                self.winrate_label.config(text=f"Win Rate: {win_rate:.0f}% ({winners}W/{losers}L)")
            else:
                self.daily_pl_label.config(text="Daily P/L: $0.00", fg='#888888')
                self.winrate_label.config(text="Win Rate: -- (no positions)")
        except Exception:
            pass  # Silently fail for background updates

    def account_update_loop(self):
        """Background loop to update account info every 5 seconds"""
        consecutive_failures = 0
        sentiment_counter = 0
        while True:
            try:
                self.update_account_display()
                consecutive_failures = 0
            except Exception:
                consecutive_failures += 1
                if consecutive_failures >= 5:
                    try:
                        self.root.after(0, lambda: self.status_label.config(
                            text="Status: API ERROR", fg='#ff6b6b'))
                    except Exception:
                        pass
            # Update sentiment every ~60 seconds (12 * 5s ticks)
            sentiment_counter += 1
            if sentiment_counter >= 12 and SENTIMENT_ENABLED:
                sentiment_counter = 0
                try:
                    self.update_sentiment_display()
                except Exception:
                    pass
            time.sleep(5)

    def update_sentiment_display(self):
        """Fetch sentiment temperature and update the GUI indicator"""
        if not SENTIMENT_ENABLED:
            return
        try:
            data = get_sentiment_temperature(force_refresh=True)
            temp = data.get("temperature", 0.5)
            pc_ratio = data.get("put_call_ratio", 0.7)
            sentiment = data.get("sentiment_label", "NEUTRAL")
            ticker = data.get("ticker_used", "?")
            source = data.get("source", "?")

            # Color mapping based on sentiment
            colors = {
                "EXTREME_FEAR": "#ff0000",
                "FEAR": "#ff6b6b",
                "NEUTRAL": "#ffe66d",
                "GREED": "#00cc66",
                "EXTREME_GREED": "#00ff88",
            }
            color = colors.get(sentiment, "#888888")

            # Bar gradient: red (left/cold) -> yellow (mid) -> green (right/hot)
            def temp_to_bar_color(t):
                if t < 0.5:
                    r = 255
                    g = int(255 * (t / 0.5))
                    b = 0
                else:
                    r = int(255 * ((1.0 - t) / 0.5))
                    g = 255
                    b = 0
                return f"#{r:02x}{g:02x}{b:02x}"

            bar_color = temp_to_bar_color(temp)

            # Schedule GUI updates on main thread
            def _update():
                self.sentiment_label.config(text=sentiment, fg=color)
                self.temp_value_label.config(text=f"Temp: {temp:.3f}", fg=color)
                self.pc_ratio_label.config(text=f"P/C: {pc_ratio:.3f}", fg='#ffffff')
                self.sentiment_source_label.config(text=f"{ticker} | {source}")

                # Draw temperature bar
                self.temp_bar_canvas.delete("all")
                bar_width = int(temp * 196)
                # Background
                self.temp_bar_canvas.create_rectangle(2, 2, 198, 18, fill='#1a1a2e', outline='')
                # Filled portion
                if bar_width > 0:
                    self.temp_bar_canvas.create_rectangle(2, 2, 2 + bar_width, 18,
                                                           fill=bar_color, outline='')
                # Tick marks at 0.25, 0.5, 0.75
                for tick in [0.25, 0.5, 0.75]:
                    x = 2 + int(tick * 196)
                    self.temp_bar_canvas.create_line(x, 2, x, 18, fill='#444444', width=1)

            self.root.after(0, _update)

        except Exception as e:
            self.root.after(0, lambda: self.sentiment_label.config(text="ERROR", fg='#ff6b6b'))

    def start_trading(self):
        """Start the trading loop"""
        self.running = True
        self.paused = False
        self.start_btn.config(state='disabled')
        self.pause_btn.config(state='normal')
        self.stop_btn.config(state='normal')
        self.provider_dropdown.config(state='disabled')
        self.status_label.config(text="Status: RUNNING", fg='#00ff88')

        self.log("\n" + "=" * 40, 'header')
        self.log("  TRADING STARTED", 'header')
        self.log("=" * 40 + "\n", 'header')

        # Start trading thread
        self.trade_thread = threading.Thread(target=self.trading_loop, daemon=True)
        self.trade_thread.start()

    def toggle_pause(self):
        """Toggle pause state"""
        self.paused = not self.paused
        if self.paused:
            self.pause_btn.config(text="RESUME", bg='#00ff88')
            self.status_label.config(text="Status: PAUSED", fg='#ffe66d')
            self.log("\n*** AI TRADING PAUSED ***\n", 'warning')
        else:
            self.pause_btn.config(text="PAUSE", bg='#ffe66d')
            self.status_label.config(text="Status: RUNNING", fg='#00ff88')
            self.log("\n*** AI TRADING RESUMED ***\n", 'info')

    def stop_trading(self):
        """Stop trading and liquidate all positions"""
        self.running = False
        self.paused = False
        self.start_btn.config(state='disabled')
        self.pause_btn.config(state='disabled', text="PAUSE", bg='#ffe66d')
        self.stop_btn.config(state='disabled')
        self.status_label.config(text="Status: LIQUIDATING...", fg='#ff6b6b')

        self.log("\n" + "=" * 40, 'error')
        self.log("  STOPPING - LIQUIDATING ALL POSITIONS", 'error')
        self.log("=" * 40, 'error')

        # Liquidate in separate thread to not freeze GUI
        threading.Thread(target=self.liquidate_all_positions, daemon=True).start()

    def liquidate_all_positions(self):
        """Sell all positions"""
        try:
            positions = self.api.list_positions()

            if not positions:
                self.log("No positions to liquidate", 'info')
            else:
                for pos in positions:
                    try:
                        symbol = pos.symbol
                        qty = float(pos.qty)  # Keep as float for fractional shares
                        self.log(f"Selling {qty} {symbol}...", 'trade')

                        sell_price = float(pos.current_price)
                        order = self.api.submit_order(
                            symbol=symbol,
                            qty=str(qty),  # Pass as string to Alpaca for fractional share support
                            side='sell',
                            type='market',
                            time_in_force='day'
                        )
                        self.log(f"  SOLD {qty} {symbol}", 'trade')
                        with self._trade_lock:
                            self.trade_count += 1

                        # Track sell for win/loss calculation
                        if self.tracker:
                            self.tracker.record_trade(symbol, "sell", qty,
                                                      sell_price, "Liquidation on STOP")

                    except Exception as e:
                        self.log(f"  Error selling {pos.symbol}: {e}", 'error')

            # Wait for orders to settle
            import time
            time.sleep(2)

            # Update display
            self.update_account_display()
            self.trade_label.config(text=f"Trades: {self.trade_count}")

            self.log("\n*** ALL POSITIONS LIQUIDATED ***", 'warning')
            self.log("*** TRADING STOPPED ***\n", 'error')

        except Exception as e:
            self.log(f"Liquidation error: {e}", 'error')

        finally:
            self.start_btn.config(state='normal')
            self.provider_dropdown.config(state='readonly')
            self.status_label.config(text="Status: STOPPED", fg='#ff6b6b')

    def get_current_prices(self):
        """Get current prices"""
        prices = {}
        try:
            bars = self.api.get_latest_bars(SYMBOLS)
            for symbol in SYMBOLS:
                if symbol in bars:
                    prices[symbol] = {
                        'price': float(bars[symbol].c),
                        'open': float(bars[symbol].o),
                        'high': float(bars[symbol].h),
                        'low': float(bars[symbol].l),
                        'volume': int(bars[symbol].v)
                    }
        except Exception as e:
            self.log(f"Error getting prices: {e}", 'error')
        return prices

    def get_portfolio_status(self):
        """Get portfolio status"""
        account = self.api.get_account()
        positions = self.api.list_positions()

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
        """Get AI trading decision with memory context"""
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
                self.log(f"Memory load error: {e}", 'warning')

        prompt = f"""You are Clawdbot, an AI stock trader with memory of past strategies.
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
5. Apply any relevant strategy insights from your memory!

Respond with EXACTLY ONE JSON object (no other text):
{{"action": "BUY" or "SELL" or "HOLD", "symbol": "TICKER", "quantity": NUMBER, "reason": "brief reason"}}
"""

        try:
            # DeepSeek reasoner needs more tokens for reasoning chain
            max_tokens = 2000 if "reasoner" in self.model else 200

            # Build messages - reasoner doesn't support system message well
            if "reasoner" in self.model:
                messages = [
                    {"role": "user", "content": "You are a professional stock trader. Respond with valid JSON only.\n\n" + prompt}
                ]
            else:
                messages = [
                    {"role": "system", "content": "You are a professional stock trader. Always respond with valid JSON only."},
                    {"role": "user", "content": prompt}
                ]

            self.log(f"Waiting for {self.model}...", 'info')

            response = self.openai.chat.completions.create(
                model=self.model,
                messages=messages,
                max_tokens=max_tokens
            )

            # Get content - DeepSeek reasoner puts answer in content, reasoning in reasoning_content
            message = response.choices[0].message
            content = message.content

            # Try reasoning_content if content is empty (some API versions)
            if not content and hasattr(message, 'reasoning_content') and message.reasoning_content:
                # Extract JSON from reasoning if needed
                content = message.reasoning_content

            if content is None:
                content = ""
            content = content.strip()

            # Log raw response for debugging
            if not content:
                self.log(f"Empty response from {self.model}", 'warning')
                return {"action": "HOLD", "symbol": "", "quantity": 0, "reason": "Empty response from AI"}

            if '{' in content and '}' in content:
                # Find the first complete JSON object
                start = content.find('{')
                depth = 0
                end = start
                for i, char in enumerate(content[start:], start):
                    if char == '{':
                        depth += 1
                    elif char == '}':
                        depth -= 1
                        if depth == 0:
                            end = i
                            break
                json_str = content[start:end+1]

                try:
                    return json.loads(json_str)
                except json.JSONDecodeError:
                    # Try to fix common issues - remove newlines, fix quotes
                    json_str = json_str.replace('\n', ' ').replace('\r', '')
                    # Try regex to extract action, symbol, quantity, reason
                    import re
                    action_match = re.search(r'"action"\s*:\s*"(\w+)"', json_str, re.IGNORECASE)
                    symbol_match = re.search(r'"symbol"\s*:\s*"(\w*)"', json_str, re.IGNORECASE)
                    qty_match = re.search(r'"quantity"\s*:\s*(\d+)', json_str, re.IGNORECASE)
                    reason_match = re.search(r'"reason"\s*:\s*"([^"]*)"', json_str, re.IGNORECASE)

                    if action_match:
                        return {
                            "action": action_match.group(1),
                            "symbol": symbol_match.group(1) if symbol_match else "",
                            "quantity": int(qty_match.group(1)) if qty_match else 0,
                            "reason": reason_match.group(1) if reason_match else "Parsed from response"
                        }
                    self.log(f"Bad JSON: {json_str[:80]}...", 'warning')

            self.log(f"Response: {content[:100]}...", 'warning')
            return {"action": "HOLD", "symbol": "", "quantity": 0, "reason": "Could not parse response"}

        except Exception as e:
            self.log(f"AI Error: {str(e)[:100]}", 'error')
            return {"action": "HOLD", "symbol": "", "quantity": 0, "reason": f"Error: {e}"}

    def execute_trade(self, decision, prices=None):
        """Execute trade and track for memory"""
        action = decision.get('action', 'HOLD').upper()
        symbol = decision.get('symbol', '')
        quantity = int(decision.get('quantity', 0))
        reason = decision.get('reason', '')

        if action == 'HOLD' or quantity <= 0:
            self.log(f"Decision: HOLD - {reason}", 'info')
            return None

        # Position size enforcement for buys
        if action == 'BUY' and prices and symbol in prices:
            try:
                account = self.api.get_account()
                portfolio_value = float(account.portfolio_value)
                if portfolio_value > 0:
                    current_value = 0
                    for pos in self.api.list_positions():
                        if pos.symbol == symbol:
                            current_value = float(pos.market_value)
                            break
                    proposed_value = current_value + quantity * prices[symbol]['price']
                    position_pct = proposed_value / portfolio_value
                    if position_pct > MAX_POSITION_SIZE:
                        max_qty = int((MAX_POSITION_SIZE * portfolio_value - current_value) / prices[symbol]['price'])
                        if max_qty <= 0:
                            self.log(f"REJECTED: {symbol} already at max position size ({position_pct*100:.1f}% > {MAX_POSITION_SIZE*100}%)", 'warning')
                            return None
                        self.log(f"WARNING: Reducing {symbol} qty from {quantity} to {max_qty} (position limit {MAX_POSITION_SIZE*100}%)", 'warning')
                        quantity = max_qty
            except Exception as e:
                self.log(f"Warning: Could not check position size: {e}", 'warning')

        try:
            if action == 'BUY':
                order = self.api.submit_order(
                    symbol=symbol, qty=quantity, side='buy',
                    type='market', time_in_force='day'
                )
                self.log(f"BUY ORDER: {quantity} {symbol} - {reason}", 'trade')
                with self._trade_lock:
                    self.trade_count += 1
                self.trade_label.config(text=f"Trades: {self.trade_count}")

                # Track for memory
                if self.tracker and prices and symbol in prices:
                    self.tracker.record_trade(symbol, "buy", quantity,
                                              prices[symbol]['price'], reason)
                    self.log("[Memory] Tracking buy", 'info')

                return order

            elif action == 'SELL':
                order = self.api.submit_order(
                    symbol=symbol, qty=quantity, side='sell',
                    type='market', time_in_force='day'
                )
                self.log(f"SELL ORDER: {quantity} {symbol} - {reason}", 'trade')
                with self._trade_lock:
                    self.trade_count += 1
                self.trade_label.config(text=f"Trades: {self.trade_count}")

                # Track for memory
                if self.tracker and prices and symbol in prices:
                    self.tracker.record_trade(symbol, "sell", quantity,
                                              prices[symbol]['price'], reason)
                    self.log("[Memory] Trade outcome recorded", 'info')

                return order

        except Exception as e:
            self.log(f"Trade Error: {e}", 'error')
            return None

    def safe_update_status(self, text, fg):
        """Thread-safe status label update"""
        try:
            self.root.after(0, lambda t=text, f=fg: self.status_label.config(text=t, fg=f))
        except Exception:
            pass

    def trading_loop(self):
        """Main trading loop"""
        while self.running:
            try:
                # Check if paused
                if self.paused:
                    time.sleep(1)
                    continue

                # Check market status
                clock = self.api.get_clock()
                if not clock.is_open:
                    try:
                        next_open = clock.next_open
                        open_str = next_open.astimezone().strftime('%I:%M %p')
                    except Exception:
                        open_str = "?"
                    self.safe_update_status(f"Status: WAITING - Market opens {open_str}", '#ffe66d')
                    self.log(f"Market is CLOSED. Opens at {open_str}. Waiting...", 'warning')
                    # Interruptible sleep so STOP works immediately
                    for _ in range(60):
                        if not self.running:
                            return
                        time.sleep(1)
                    continue

                self.safe_update_status("Status: TRADING", '#00ff88')
                self.log("\n--- Checking market ---", 'header')

                # Get prices
                prices = self.get_current_prices()
                if not prices:
                    self.log("Could not get prices. Waiting...", 'warning')
                    time.sleep(30)
                    continue

                # Display prices
                self.log("Current Prices:", 'price')
                for symbol, data in prices.items():
                    change = ((data['price'] - data['open']) / data['open']) * 100
                    color = 'info' if change >= 0 else 'error'
                    self.log(f"  {symbol}: ${data['price']:.2f} ({change:+.2f}%)", color)

                # Get portfolio
                portfolio_status, cash, buying_power = self.get_portfolio_status()
                self.update_account_display()

                # Get AI decision
                self.log("\nAsking AI for decision...", 'info')
                decision = self.get_ai_decision(prices, portfolio_status, cash, buying_power)

                # Execute (pass prices for memory tracking)
                self.execute_trade(decision, prices)

                # Update display
                self.update_account_display()

                # Wait
                self.log(f"\nWaiting {TRADE_INTERVAL}s until next check...", 'info')

                # Interruptible sleep
                for _ in range(TRADE_INTERVAL):
                    if not self.running:
                        break
                    time.sleep(1)

            except Exception as e:
                self.log(f"Error: {e}", 'error')
                time.sleep(30)

    # === STRATEGY CHAT METHODS ===

    def setup_chat_tab(self):
        """Setup the Strategy Chat tab"""
        chat_frame = tk.Frame(self.notebook, bg='#1a1a2e')
        self.notebook.add(chat_frame, text='  Strategy Chat  ')

        # Stats bar (memory + AI provider)
        stats_frame = tk.Frame(chat_frame, bg='#16213e')
        stats_frame.pack(fill='x', padx=5, pady=5)

        self.memory_stats_label = tk.Label(stats_frame, text="Memory: Loading...",
                                           font=('Consolas', 10), fg='#4ecdc4', bg='#16213e')
        self.memory_stats_label.pack(side='left', padx=10, pady=5)

        self.chat_ai_label = tk.Label(stats_frame, text=f"AI: {self.model}",
                                      font=('Consolas', 10), fg='#00ff88', bg='#16213e')
        self.chat_ai_label.pack(side='right', padx=10, pady=5)

        # Quick action buttons
        btn_frame = tk.Frame(chat_frame, bg='#1a1a2e')
        btn_frame.pack(fill='x', padx=5, pady=5)

        tk.Button(btn_frame, text="Show Insights", command=self.show_insights,
                 font=('Consolas', 10), bg='#4ecdc4', fg='#000000',
                 cursor='hand2').pack(side='left', padx=3)

        tk.Button(btn_frame, text="Show Stats", command=self.show_stats,
                 font=('Consolas', 10), bg='#ffe66d', fg='#000000',
                 cursor='hand2').pack(side='left', padx=3)

        tk.Button(btn_frame, text="Clear Chat", command=self.clear_chat,
                 font=('Consolas', 10), bg='#ff6b6b', fg='#000000',
                 cursor='hand2').pack(side='left', padx=3)

        tk.Button(btn_frame, text="Clear Insights", command=self.clear_insights,
                 font=('Consolas', 10), bg='#e74c3c', fg='#ffffff',
                 cursor='hand2').pack(side='left', padx=3)

        # Input frame at bottom
        input_frame = tk.Frame(chat_frame, bg='#1a1a2e')
        input_frame.pack(fill='x', side='bottom', padx=10, pady=10)

        self.send_btn = tk.Button(input_frame, text="SEND", command=self.send_chat_message,
                                  font=('Consolas', 12, 'bold'), bg='#00ff88', fg='#000000',
                                  width=10, cursor='hand2')
        self.send_btn.pack(side='right', padx=(10, 0))

        self.chat_input = tk.Entry(input_frame, font=('Consolas', 12),
                                   bg='#16213e', fg='#ffffff',
                                   insertbackground='#00ff88')
        self.chat_input.pack(side='left', fill='x', expand=True, ipady=8)
        self.chat_input.bind('<Return>', self.send_chat_message)

        # Chat display
        self.chat_display = scrolledtext.ScrolledText(chat_frame,
                                                       font=('Consolas', 10),
                                                       bg='#0f0f23', fg='#ffffff',
                                                       insertbackground='#00ff88',
                                                       wrap='word')
        self.chat_display.pack(fill='both', expand=True, padx=5, pady=5)

        # Configure chat tags
        self.chat_display.tag_configure('user', foreground='#4ecdc4')
        self.chat_display.tag_configure('bot', foreground='#00ff88')
        self.chat_display.tag_configure('system', foreground='#ffe66d')
        self.chat_display.tag_configure('saved', foreground='#ff6b6b', font=('Consolas', 10, 'italic'))

        # Welcome message
        self.chat_log("Welcome to Clawdbot Strategy Chat!", 'system')
        self.chat_log(f"Using AI: {self.model}", 'system')
        self.chat_log("Discuss trading strategies and I'll remember your insights.", 'system')
        self.chat_log("Type a message below to start chatting.\n", 'system')

        # Update memory stats
        self.update_memory_stats()

    def chat_log(self, message, tag='bot'):
        """Log message to chat display"""
        timestamp = datetime.now().strftime('%H:%M')
        prefix = ""
        if tag == 'user':
            prefix = f"[{timestamp}] You: "
        elif tag == 'bot':
            prefix = f"[{timestamp}] Clawdbot: "
        elif tag == 'system':
            prefix = f"[{timestamp}] "
        elif tag == 'saved':
            prefix = f"[{timestamp}] [SAVED] "

        self.chat_display.insert('end', f"{prefix}{message}\n", tag)
        self.chat_display.see('end')

    def _get_live_win_rate(self):
        """Calculate win rate from live Alpaca positions (profitable vs losing)."""
        try:
            positions = self.api.list_positions()
            if not positions:
                return None, 0, 0, 0.0
            winners = sum(1 for p in positions if float(p.unrealized_pl) > 0)
            losers = sum(1 for p in positions if float(p.unrealized_pl) < 0)
            total = winners + losers
            total_pl = sum(float(p.unrealized_pl) for p in positions)
            rate = (winners / total * 100) if total > 0 else 0.0
            return rate, winners, losers, total_pl
        except Exception:
            return None, 0, 0, 0.0

    def update_memory_stats(self):
        """Update memory stats display"""
        try:
            parts = []
            if MEMORY_ENABLED:
                stats = get_memory_stats()
                parts.append(f"Insights: {stats['strategy_insights']}")
                closed_wins = stats['win_rate']['wins']
                closed_losses = stats['win_rate']['losses']
                if closed_wins + closed_losses > 0:
                    parts.append(f"Closed W/L: {stats['win_rate']['win_rate']:.1f}%")

            live_rate, winners, losers, total_pl = self._get_live_win_rate()
            if live_rate is not None and (winners + losers) > 0:
                pl_color = "+" if total_pl >= 0 else ""
                parts.append(f"Positions: {winners}W/{losers}L ({live_rate:.0f}%)")
                parts.append(f"P/L: {pl_color}${total_pl:,.2f}")

            if parts:
                self.memory_stats_label.config(text=" | ".join(parts))
            else:
                self.memory_stats_label.config(text="No positions open")
        except Exception as e:
            self.memory_stats_label.config(text=f"Stats Error: {e}")

    def show_insights(self):
        """Show current strategy insights"""
        if not MEMORY_ENABLED:
            self.chat_log("Memory system not available.", 'system')
            return

        self.chat_log("\n--- Current Strategy Insights ---", 'system')
        insights = format_insights_for_prompt(n=10)
        self.chat_log(insights, 'bot')
        self.chat_log("---\n", 'system')

    def show_stats(self):
        """Show memory and live portfolio statistics"""
        self.chat_log("\n--- Portfolio Performance ---", 'system')

        # Live Alpaca positions
        try:
            positions = self.api.list_positions()
            account = self.api.get_account()
            if positions:
                winners = 0
                losers = 0
                total_pl = 0.0
                for p in positions:
                    pl = float(p.unrealized_pl)
                    pl_pct = float(p.unrealized_plpc) * 100
                    total_pl += pl
                    if pl > 0:
                        winners += 1
                    elif pl < 0:
                        losers += 1
                    sign = "+" if pl >= 0 else ""
                    self.chat_log(f"  {p.symbol}: {p.qty} shares | {sign}${pl:,.2f} ({sign}{pl_pct:.1f}%)", 'bot')
                total = winners + losers
                live_rate = (winners / total * 100) if total > 0 else 0
                sign = "+" if total_pl >= 0 else ""
                self.chat_log(f"  Total P/L: {sign}${total_pl:,.2f}", 'bot')
                self.chat_log(f"  Win rate: {live_rate:.0f}% ({winners}W / {losers}L of {len(positions)} positions)", 'bot')
                self.chat_log(f"  Portfolio: ${float(account.portfolio_value):,.2f} | Cash: ${float(account.cash):,.2f}", 'bot')
            else:
                self.chat_log("  No open positions", 'bot')
        except Exception as e:
            self.chat_log(f"  Could not fetch positions: {e}", 'bot')

        # Closed trade stats from memory
        if MEMORY_ENABLED:
            stats = get_memory_stats()
            closed_wins = stats['win_rate']['wins']
            closed_losses = stats['win_rate']['losses']
            if closed_wins + closed_losses > 0:
                self.chat_log(f"\n  Closed trades: {stats['win_rate']['win_rate']:.1f}% win rate ({closed_wins}W / {closed_losses}L)", 'bot')
            self.chat_log(f"  Strategy insights: {stats['strategy_insights']}", 'bot')

        self.chat_log("---\n", 'system')
        self.update_memory_stats()

    def clear_insights(self):
        """Clear all strategy insights with confirmation"""
        if not MEMORY_ENABLED:
            self.chat_log("Memory system not available.", 'system')
            return

        from tkinter import messagebox
        if messagebox.askyesno("Clear Insights",
                               "Are you sure you want to delete all strategy insights?\nThis cannot be undone."):
            if clear_strategy_insights():
                self.chat_log("All strategy insights cleared.", 'system')
            else:
                self.chat_log("No insights to clear.", 'system')
            self.update_memory_stats()

    def clear_chat(self):
        """Clear chat history"""
        self.chat_display.delete('1.0', 'end')
        self.chat_messages = []
        self.chat_log("Chat cleared. Starting fresh.\n", 'system')

    def send_chat_message(self, event=None):
        """Send a chat message"""
        message = self.chat_input.get().strip()
        if not message or self.chat_processing:
            return

        self.chat_input.delete(0, 'end')
        self.chat_log(message, 'user')

        # Process in background thread
        self.chat_processing = True
        self.send_btn.config(state='disabled', text="...")
        threading.Thread(target=self.process_chat_message, args=(message,), daemon=True).start()

    def process_chat_message(self, message):
        """Process chat message with AI"""
        try:
            # Build system prompt with memory context
            memory_context = ""
            if MEMORY_ENABLED:
                memory_context = get_memory_context_for_prompt()

            system_prompt = f"""You are Clawdbot's Strategy Advisor - an expert AI trading strategist.

Your role is to help improve and refine trading strategies through conversation.

## CURRENT MEMORY STATE:
{memory_context}

## YOUR CAPABILITIES:
1. Analyze proposed strategy changes - discuss pros, cons, and risks
2. Suggest improvements based on past performance
3. Help formalize trading rules
4. Review and critique current approaches

## IMPORTANT:
- When the user proposes a valuable insight or strategy rule, save it by outputting:
  <SAVE_INSIGHT>the insight to save</SAVE_INSIGHT>
- Be specific and actionable in your advice
- Keep responses concise (2-3 paragraphs max)
"""

            # Build messages
            messages = [{"role": "system", "content": system_prompt}]

            # Add conversation history (last 10 messages)
            for msg in self.chat_messages[-10:]:
                messages.append(msg)

            # Add current message
            messages.append({"role": "user", "content": message})
            self.chat_messages.append({"role": "user", "content": message})

            # Call AI
            response = self.openai.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.7,
                max_tokens=500
            )

            reply = response.choices[0].message.content

            # Extract and save any insights
            insights_saved = []
            pattern = r'<SAVE_INSIGHT(?:\s+tags="([^"]*)")?\s*>(.*?)</SAVE_INSIGHT>'
            matches = re.findall(pattern, reply, re.DOTALL)

            for tags_str, insight in matches:
                tags = [t.strip() for t in tags_str.split(",")] if tags_str else []
                if MEMORY_ENABLED:
                    save_strategy_insight(insight=insight.strip(), tags=tags, source="chat")
                    insights_saved.append(insight.strip())

            # Clean response for display
            display_reply = re.sub(pattern, '', reply, flags=re.DOTALL).strip()

            # Update UI from main thread
            self.root.after(0, lambda: self._display_chat_response(display_reply, insights_saved))

            # Save to conversation history
            self.chat_messages.append({"role": "assistant", "content": reply})

        except Exception as e:
            self.root.after(0, lambda: self.chat_log(f"Error: {str(e)[:100]}", 'system'))

        finally:
            self.root.after(0, self._reset_chat_input)

    def _display_chat_response(self, reply, insights_saved):
        """Display chat response (called from main thread)"""
        self.chat_log(reply, 'bot')

        for insight in insights_saved:
            self.chat_log(f"Insight saved: {insight[:60]}...", 'saved')

        if insights_saved:
            self.update_memory_stats()

    def _reset_chat_input(self):
        """Reset chat input state (called from main thread)"""
        self.chat_processing = False
        self.send_btn.config(state='normal', text="Send")

    def run(self):
        """Start GUI"""
        self.root.mainloop()


def main():
    # Verify credentials
    required_alpaca = ['ALPACA_API_KEY', 'ALPACA_SECRET_KEY']
    missing_alpaca = [k for k in required_alpaca if not os.getenv(k)]
    if missing_alpaca:
        print(f"Error: Missing Alpaca credentials: {missing_alpaca}")
        return

    # Check for at least one AI provider
    has_openai = os.getenv('OPENAI_API_KEY')
    has_deepseek = os.getenv('DEEPSEEK_API_KEY')
    if not has_openai and not has_deepseek:
        print("Error: No AI API key found. Please set OPENAI_API_KEY or DEEPSEEK_API_KEY")
        return

    app = TradingGUI()
    app.run()


if __name__ == "__main__":
    main()
