"""
Pocket Option Trading Signal Bot
=================================
Scans multiple assets with multi-indicator analysis and sends
BUY / SELL signals via Telegram.

Setup:
  1. Create a Telegram bot via @BotFather and get the token.
  2. Get your chat ID by messaging @userinfobot.
  3. Add TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID to your .env file.
  4. Run: python pocket_option_bot.py

.env keys used:
  TELEGRAM_BOT_TOKEN   - Bot token from @BotFather
  TELEGRAM_CHAT_ID     - Your personal or group chat ID
  SCAN_INTERVAL        - Seconds between scans (default 300 = 5 min)
  MIN_CONFIDENCE       - Minimum signal confidence to send (default 60)
"""

import os
import time
import logging
import requests
import warnings
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime
from dotenv import load_dotenv

warnings.filterwarnings("ignore")
load_dotenv()

# ─── Configuration ────────────────────────────────────────────────────────────

TELEGRAM_BOT_TOKEN  = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID    = os.getenv("TELEGRAM_CHAT_ID", "")
SCAN_INTERVAL_SECS  = int(os.getenv("SCAN_INTERVAL", "300"))   # 5 min
MIN_CONFIDENCE      = int(os.getenv("MIN_CONFIDENCE", "60"))    # 60 %

# (yfinance_ticker, display_name, suggested_expiry_for_pocket_option)
ASSETS = [
    # Forex
    ("EURUSD=X",  "EUR/USD",  "5 min"),
    ("GBPUSD=X",  "GBP/USD",  "5 min"),
    ("USDJPY=X",  "USD/JPY",  "5 min"),
    ("AUDUSD=X",  "AUD/USD",  "5 min"),
    ("USDCAD=X",  "USD/CAD",  "5 min"),
    ("USDCHF=X",  "USD/CHF",  "5 min"),
    # Crypto
    ("BTC-USD",   "BTC/USD",  "15 min"),
    ("ETH-USD",   "ETH/USD",  "15 min"),
    ("SOL-USD",   "SOL/USD",  "15 min"),
    # Indices
    ("^GSPC",     "S&P 500",  "15 min"),
    ("^NDX",      "NASDAQ",   "15 min"),
    # Commodities
    ("GC=F",      "Gold",     "15 min"),
    ("CL=F",      "Oil (WTI)", "15 min"),
]

CANDLE_PERIOD   = "7d"
CANDLE_INTERVAL = "5m"   # 5-minute bars

# ─── Logging ─────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("pocket_option_bot.log", encoding="utf-8"),
    ],
)
log = logging.getLogger("PO_Bot")

# ─── Technical Indicator Helpers ─────────────────────────────────────────────

def _ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def calc_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain  = delta.clip(lower=0)
    loss  = (-delta).clip(lower=0)
    avg_g = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_l = loss.ewm(com=period - 1, min_periods=period).mean()
    rs    = avg_g / avg_l.replace(0, np.inf)
    return 100 - (100 / (1 + rs))


def calc_macd(close: pd.Series, fast=12, slow=26, sig=9):
    macd_line   = _ema(close, fast) - _ema(close, slow)
    signal_line = _ema(macd_line, sig)
    histogram   = macd_line - signal_line
    return macd_line, signal_line, histogram


def calc_bollinger(close: pd.Series, period=20, std_dev=2.0):
    sma   = close.rolling(period).mean()
    std   = close.rolling(period).std()
    upper = sma + std_dev * std
    lower = sma - std_dev * std
    return upper, sma, lower


def calc_stochastic(high: pd.Series, low: pd.Series, close: pd.Series,
                    k=14, d=3):
    ll = low.rolling(k).min()
    hh = high.rolling(k).max()
    stoch_k = 100 * (close - ll) / (hh - ll).replace(0, np.nan)
    stoch_d = stoch_k.rolling(d).mean()
    return stoch_k, stoch_d


def calc_atr(high: pd.Series, low: pd.Series, close: pd.Series,
             period=14) -> pd.Series:
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low  - close.shift()).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(com=period - 1, min_periods=period).mean()


# ─── Signal Engine ────────────────────────────────────────────────────────────

def analyze_asset(ticker: str, display_name: str, expiry: str) -> dict | None:
    """
    Download recent 5-min OHLCV data, compute 5 indicator families,
    tally BUY / SELL votes, and return a signal dict when confidence
    meets the threshold.  Returns None if no qualifying signal.
    """
    try:
        raw = yf.download(
            ticker,
            period=CANDLE_PERIOD,
            interval=CANDLE_INTERVAL,
            progress=False,
            auto_adjust=True,
        )
    except Exception as exc:
        log.warning(f"{display_name}: download failed – {exc}")
        return None

    if raw is None or len(raw) < 60:
        log.debug(f"{display_name}: not enough bars ({len(raw) if raw is not None else 0})")
        return None

    # Flatten MultiIndex columns if present
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)

    close = raw["Close"].dropna()
    high  = raw["High"].dropna()
    low   = raw["Low"].dropna()

    if len(close) < 60:
        return None

    # ── Indicators ───────────────────────────────────────────────────────────
    rsi               = calc_rsi(close)
    ema9              = _ema(close, 9)
    ema21             = _ema(close, 21)
    ema50             = _ema(close, 50)
    macd_l, macd_s, hist = calc_macd(close)
    bb_up, bb_mid, bb_lo = calc_bollinger(close)
    stk_k, stk_d     = calc_stochastic(high, low, close)

    # Latest / prev values
    def v(series, offset=0):
        idx = -(1 + offset)
        val = series.iloc[idx]
        return float(val) if not (isinstance(val, float) and np.isnan(val)) else 0.0

    cur_close = v(close)
    cur_rsi   = v(rsi)
    prev_rsi  = v(rsi, 1)
    cur_e9    = v(ema9);  prev_e9  = v(ema9, 1)
    cur_e21   = v(ema21); prev_e21 = v(ema21, 1)
    cur_e50   = v(ema50)
    cur_hist  = v(hist);  prev_hist = v(hist, 1)
    cur_macdl = v(macd_l); cur_macds = v(macd_s)
    cur_bb_up = v(bb_up);  cur_bb_lo = v(bb_lo); cur_bb_mid = v(bb_mid)
    prev_bb_mid = v(bb_mid, 1)
    prev_close  = v(close, 1)
    cur_stk   = v(stk_k); prev_stk = v(stk_k, 1)
    cur_std   = v(stk_d); prev_std = v(stk_d, 1)

    buy_votes  = []
    sell_votes = []

    # ── 1. RSI ───────────────────────────────────────────────────────────────
    if cur_rsi < 25:
        buy_votes.append(f"RSI {cur_rsi:.1f} — deeply oversold")
    elif cur_rsi < 35:
        buy_votes.append(f"RSI {cur_rsi:.1f} — oversold")
    elif cur_rsi > 75:
        sell_votes.append(f"RSI {cur_rsi:.1f} — deeply overbought")
    elif cur_rsi > 65:
        sell_votes.append(f"RSI {cur_rsi:.1f} — overbought")
    # RSI momentum cross
    if prev_rsi < 50 <= cur_rsi:
        buy_votes.append(f"RSI crossed 50 upward ({cur_rsi:.1f})")
    elif prev_rsi > 50 >= cur_rsi:
        sell_votes.append(f"RSI crossed 50 downward ({cur_rsi:.1f})")

    # ── 2. EMA Trend ─────────────────────────────────────────────────────────
    # Crossover signals
    if cur_e9 > cur_e21 and prev_e9 <= prev_e21:
        buy_votes.append("EMA 9 crossed above EMA 21 (bullish cross)")
    elif cur_e9 < cur_e21 and prev_e9 >= prev_e21:
        sell_votes.append("EMA 9 crossed below EMA 21 (bearish cross)")
    # Trend alignment
    if cur_e9 > cur_e21 > cur_e50:
        buy_votes.append("EMA stack bullish (9 > 21 > 50)")
    elif cur_e9 < cur_e21 < cur_e50:
        sell_votes.append("EMA stack bearish (9 < 21 < 50)")

    # ── 3. MACD ──────────────────────────────────────────────────────────────
    if cur_hist > 0 and prev_hist <= 0:
        buy_votes.append(f"MACD histogram flipped positive")
    elif cur_hist < 0 and prev_hist >= 0:
        sell_votes.append(f"MACD histogram flipped negative")
    elif cur_hist > 0 and cur_macdl > cur_macds:
        buy_votes.append(f"MACD bullish (histogram +{cur_hist:.5f})")
    elif cur_hist < 0 and cur_macdl < cur_macds:
        sell_votes.append(f"MACD bearish (histogram {cur_hist:.5f})")

    # ── 4. Bollinger Bands ───────────────────────────────────────────────────
    if cur_bb_mid > 0:
        pct_b = (cur_close - cur_bb_lo) / (cur_bb_up - cur_bb_lo) if (cur_bb_up - cur_bb_lo) > 0 else 0.5
        if cur_close <= cur_bb_lo:
            buy_votes.append(f"Price ≤ lower BB ({cur_close:.5f} ≤ {cur_bb_lo:.5f})")
        elif cur_close >= cur_bb_up:
            sell_votes.append(f"Price ≥ upper BB ({cur_close:.5f} ≥ {cur_bb_up:.5f})")
        elif pct_b < 0.25:
            buy_votes.append(f"%B = {pct_b:.2f} — near lower band")
        elif pct_b > 0.75:
            sell_votes.append(f"%B = {pct_b:.2f} — near upper band")
        # Midline cross
        if prev_close < prev_bb_mid and cur_close >= cur_bb_mid:
            buy_votes.append("Price crossed above BB midline")
        elif prev_close > prev_bb_mid and cur_close <= cur_bb_mid:
            sell_votes.append("Price crossed below BB midline")

    # ── 5. Stochastic ────────────────────────────────────────────────────────
    if cur_stk < 20 and cur_std < 20:
        buy_votes.append(f"Stochastic oversold (K={cur_stk:.1f}, D={cur_std:.1f})")
    elif cur_stk > 80 and cur_std > 80:
        sell_votes.append(f"Stochastic overbought (K={cur_stk:.1f}, D={cur_std:.1f})")
    if cur_stk > cur_std and prev_stk <= prev_std and cur_stk < 80:
        buy_votes.append(f"Stochastic bullish K/D cross (K={cur_stk:.1f})")
    elif cur_stk < cur_std and prev_stk >= prev_std and cur_stk > 20:
        sell_votes.append(f"Stochastic bearish K/D cross (K={cur_stk:.1f})")

    # ── Scoring ──────────────────────────────────────────────────────────────
    n_buy  = len(buy_votes)
    n_sell = len(sell_votes)
    total  = n_buy + n_sell

    if total == 0 or n_buy == n_sell:
        return None

    if n_buy > n_sell:
        direction = "BUY"
        reasons   = buy_votes
        dominant  = n_buy
    else:
        direction = "SELL"
        reasons   = sell_votes
        dominant  = n_sell

    # Confidence: ratio of agreeing votes × 100, with a bonus for consensus
    raw_conf = dominant / max(total, 1)
    bonus    = 0.10 * min(dominant, 3)          # up to +30% for 3+ indicators
    confidence = int(min((raw_conf + bonus) * 100, 97))

    if confidence < MIN_CONFIDENCE:
        return None

    return {
        "ticker":     ticker,
        "name":       display_name,
        "direction":  direction,
        "confidence": confidence,
        "expiry":     expiry,
        "entry":      cur_close,
        "reasons":    reasons,
        "rsi":        cur_rsi,
        "timestamp":  datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
    }


# ─── Telegram ────────────────────────────────────────────────────────────────

_TELEGRAM_URL = "https://api.telegram.org/bot{token}/sendMessage"


def _tg_post(text: str) -> bool:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        log.warning("Telegram not configured — printing to console.")
        print("\n" + text + "\n")
        return False
    url = _TELEGRAM_URL.format(token=TELEGRAM_BOT_TOKEN)
    try:
        resp = requests.post(
            url,
            json={"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"},
            timeout=12,
        )
        if resp.status_code == 200:
            return True
        log.error(f"Telegram HTTP {resp.status_code}: {resp.text[:200]}")
        return False
    except Exception as exc:
        log.error(f"Telegram send failed: {exc}")
        return False


def _confidence_bar(pct: int) -> str:
    filled = round(pct / 10)
    return "█" * filled + "░" * (10 - filled)


def format_signal(sig: dict) -> str:
    icon   = "🟢" if sig["direction"] == "BUY" else "🔴"
    action = "CALL ▲" if sig["direction"] == "BUY" else "PUT ▼"
    bar    = _confidence_bar(sig["confidence"])

    # Format entry price with appropriate decimal places
    entry = sig["entry"]
    if entry > 1000:
        entry_str = f"{entry:,.2f}"
    elif entry > 10:
        entry_str = f"{entry:.4f}"
    else:
        entry_str = f"{entry:.5f}"

    # Escape < > & so Telegram HTML parser doesn't choke on indicator text
    def _esc(s: str) -> str:
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    reasons_text = "\n".join(f"  • {_esc(r)}" for r in sig["reasons"])

    return (
        f"{icon} <b>{sig['name']}  —  {action}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"⏱  Expiry : <b>{sig['expiry']}</b>\n"
        f"💰 Entry  : <b>{entry_str}</b>\n"
        f"📊 Confidence : <b>{sig['confidence']}%</b>  [{bar}]\n"
        f"🕐 Time   : {sig['timestamp']}\n\n"
        f"<b>Indicators:</b>\n{reasons_text}\n\n"
        f"⚠️ <i>Risk warning: binary options carry high risk.\n"
        f"Never invest more than you can afford to lose.</i>"
    )


def send_startup_message() -> None:
    assets = ", ".join(a[1] for a in ASSETS)
    msg = (
        f"🤖 <b>Pocket Option Signal Bot — Online</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📡 Monitoring : {assets}\n"
        f"⏰ Scan every : {SCAN_INTERVAL_SECS}s\n"
        f"🎯 Min confidence : {MIN_CONFIDENCE}%\n"
        f"📈 Timeframe : {CANDLE_INTERVAL} candles\n"
        f"🕐 Started : {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}"
    )
    _tg_post(msg)


def send_scan_summary(n_signals: int) -> None:
    if n_signals == 0:
        msg = (
            f"📭 No qualifying signals this scan.\n"
            f"🕐 {datetime.utcnow().strftime('%H:%M UTC')}  |  "
            f"Next scan in {SCAN_INTERVAL_SECS}s"
        )
        _tg_post(msg)


# ─── Main Scan Loop ───────────────────────────────────────────────────────────

def run_scan() -> int:
    log.info("─" * 55)
    log.info(f"Scan started — {datetime.utcnow().strftime('%H:%M:%S UTC')}")
    signals = []

    for ticker, name, expiry in ASSETS:
        log.info(f"  Analyzing {name}…")
        sig = analyze_asset(ticker, name, expiry)
        if sig:
            log.info(f"    → {sig['direction']}  conf={sig['confidence']}%")
            signals.append(sig)
        else:
            log.info(f"    → No signal")

    # Sort best signals first
    signals.sort(key=lambda x: x["confidence"], reverse=True)

    for sig in signals:
        msg = format_signal(sig)
        _tg_post(msg)
        time.sleep(0.6)   # avoid Telegram flood limits

    if not signals:
        log.info("  No qualifying signals found.")
        send_scan_summary(0)
    else:
        log.info(f"  Sent {len(signals)} signal(s).")

    return len(signals)


def main() -> None:
    log.info("Pocket Option Signal Bot starting…")

    if not TELEGRAM_BOT_TOKEN:
        log.warning(
            "TELEGRAM_BOT_TOKEN not set in .env — signals will be printed to console only."
        )
    if not TELEGRAM_CHAT_ID:
        log.warning(
            "TELEGRAM_CHAT_ID not set in .env — signals will be printed to console only."
        )

    send_startup_message()

    while True:
        try:
            run_scan()
        except KeyboardInterrupt:
            log.info("Bot stopped by user (KeyboardInterrupt).")
            _tg_post("🛑 <b>Pocket Option Signal Bot stopped.</b>")
            break
        except Exception as exc:
            log.error(f"Unexpected error during scan: {exc}", exc_info=True)
            _tg_post(f"⚠️ Bot error: {exc}")

        log.info(f"  Sleeping {SCAN_INTERVAL_SECS}s…")
        time.sleep(SCAN_INTERVAL_SECS)


if __name__ == "__main__":
    main()
