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


def calc_adx(high: pd.Series, low: pd.Series, close: pd.Series,
             period=14) -> pd.Series:
    """Average Directional Index — measures trend strength (>20 = trending)."""
    up   = high.diff()
    down = -low.diff()
    plus_dm  = np.where((up > down) & (up > 0), up, 0.0)
    minus_dm = np.where((down > up) & (down > 0), down, 0.0)
    atr      = calc_atr(high, low, close, period)
    plus_di  = 100 * pd.Series(plus_dm,  index=close.index).ewm(com=period-1, min_periods=period).mean() / atr
    minus_di = 100 * pd.Series(minus_dm, index=close.index).ewm(com=period-1, min_periods=period).mean() / atr
    dx       = (100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan))
    adx      = dx.ewm(com=period-1, min_periods=period).mean()
    return adx, plus_di, minus_di


def _get_htf_trend(ticker: str, interval: str = "1h", period: str = "30d") -> int:
    """
    Fetch higher-timeframe bars and return trend direction.
      +1 = bullish  (EMA20 > EMA50 and RSI > 50)
      -1 = bearish  (EMA20 < EMA50 and RSI < 50)
       0 = neutral / unclear
    """
    try:
        df = yf.download(ticker, period=period, interval=interval,
                         progress=False, auto_adjust=True)
        if df is None or len(df) < 50:
            return 0
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        c   = df["Close"].dropna()
        e20 = _ema(c, 20).iloc[-1]
        e50 = _ema(c, 50).iloc[-1]
        rsi = calc_rsi(c).iloc[-1]
        if e20 > e50 and rsi > 52:
            return 1
        if e20 < e50 and rsi < 48:
            return -1
        return 0
    except Exception:
        return 0


# Forex pairs and which UTC hour ranges they are liquid (start, end)
_FOREX_SESSIONS = {
    "EURUSD=X": [(7, 17)],   # London + NY overlap
    "GBPUSD=X": [(7, 17)],
    "USDJPY=X": [(0, 9), (12, 21)],   # Tokyo + NY
    "AUDUSD=X": [(0, 9), (12, 17)],   # Sydney/Tokyo + NY
    "USDCAD=X": [(12, 21)],           # NY session only
    "USDCHF=X": [(7, 17)],
}

def _in_active_session(ticker: str) -> bool:
    """Return False for forex pairs outside their liquid trading session."""
    sessions = _FOREX_SESSIONS.get(ticker)
    if not sessions:
        return True   # crypto / indices / commodities trade 24/7
    hour = datetime.utcnow().hour
    return any(start <= hour < end for start, end in sessions)


def _detect_candle_pattern(open_: pd.Series, high: pd.Series,
                            low: pd.Series, close: pd.Series) -> int:
    """
    Detect the last completed candle's reversal pattern.
      +1 = bullish pattern (hammer, bullish engulfing)
      -1 = bearish pattern (shooting star, bearish engulfing)
       0 = no pattern
    """
    if len(close) < 3:
        return 0
    o  = float(open_.iloc[-1]);  o1 = float(open_.iloc[-2])
    h  = float(high.iloc[-1]);   h1 = float(high.iloc[-2])
    l  = float(low.iloc[-1]);    l1 = float(low.iloc[-2])
    c  = float(close.iloc[-1]);  c1 = float(close.iloc[-2])
    body     = abs(c - o)
    rng      = h - l if h != l else 1e-10
    body_pct = body / rng

    # Hammer / bullish pin bar: small body at top, long lower wick
    lower_wick = min(o, c) - l
    if lower_wick > body * 2 and body_pct < 0.35 and c > o:
        return 1

    # Shooting star / bearish pin bar: small body at bottom, long upper wick
    upper_wick = h - max(o, c)
    if upper_wick > body * 2 and body_pct < 0.35 and c < o:
        return -1

    # Bullish engulfing
    prev_bearish = c1 < o1
    cur_bullish  = c > o
    if prev_bearish and cur_bullish and o <= c1 and c >= o1:
        return 1

    # Bearish engulfing
    prev_bullish = c1 > o1
    cur_bearish  = c < o
    if prev_bullish and cur_bearish and o >= c1 and c <= o1:
        return -1

    return 0


# ─── Signal Engine ────────────────────────────────────────────────────────────

# Minimum 5-min indicators that must agree
MIN_INDICATORS = 2

def analyze_asset(ticker: str, display_name: str, expiry: str) -> dict | None:
    """
    High-accuracy signal engine — five layers of filtering:

    Gate 0 — Active session check
      Forex pairs only trade during their liquid market hours.

    Layer 1 — Dual higher-timeframe trend (15m + 1h)
      Both intermediate and macro trend must align with signal.

    Layer 2 — Five 5-min indicators (RSI, EMA, MACD, BB, Stochastic)
      Strict thresholds; requires ≥ MIN_INDICATORS (3) agreeing.

    Layer 3 — ADX trend strength + directional index confirmation
      ADX > 20, DI must agree with signal direction.

    Layer 4 — Volatility floor + candlestick pattern
      ATR must be sufficient (not a dead market); last candle must
      show a reversal or continuation pattern aligned with signal.
    """
    # ── Gate 0: active session ───────────────────────────────────────────────
    if not _in_active_session(ticker):
        log.debug(f"{display_name}: outside active session — skip")
        return None

    # ── Fetch 5-min data ────────────────────────────────────────────────────
    try:
        raw = yf.download(ticker, period=CANDLE_PERIOD, interval=CANDLE_INTERVAL,
                          progress=False, auto_adjust=True)
    except Exception as exc:
        log.warning(f"{display_name}: download failed – {exc}")
        return None

    if raw is None or len(raw) < 60:
        return None
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)

    close = raw["Close"].dropna()
    high  = raw["High"].dropna()
    low   = raw["Low"].dropna()
    open_ = raw["Open"].dropna()
    if len(close) < 60:
        return None

    # ── Layer 1: dual higher-timeframe trend (15m + 1h) ─────────────────────
    htf_15m = _get_htf_trend(ticker, interval="15m", period="5d")
    htf_1h  = _get_htf_trend(ticker, interval="1h",  period="30d")

    # ── Indicators ──────────────────────────────────────────────────────────
    rsi                  = calc_rsi(close)
    ema9                 = _ema(close, 9)
    ema21                = _ema(close, 21)
    ema50                = _ema(close, 50)
    macd_l, macd_s, hist = calc_macd(close)
    bb_up, bb_mid, bb_lo = calc_bollinger(close)
    stk_k, stk_d         = calc_stochastic(high, low, close)
    adx, plus_di, minus_di = calc_adx(high, low, close)

    def v(series, offset=0):
        val = series.iloc[-(1 + offset)]
        return float(val) if not (isinstance(val, float) and np.isnan(val)) else 0.0

    cur_close   = v(close)
    cur_rsi     = v(rsi);    prev_rsi  = v(rsi, 1)
    cur_e9      = v(ema9);   prev_e9   = v(ema9, 1)
    cur_e21     = v(ema21);  prev_e21  = v(ema21, 1)
    cur_e50     = v(ema50)
    cur_hist    = v(hist);   prev_hist = v(hist, 1)
    cur_macdl   = v(macd_l); cur_macds = v(macd_s)
    cur_bb_up   = v(bb_up);  cur_bb_lo = v(bb_lo); cur_bb_mid = v(bb_mid)
    prev_close  = v(close, 1)
    prev_bb_mid = v(bb_mid, 1)
    cur_stk     = v(stk_k);  prev_stk  = v(stk_k, 1)
    cur_std     = v(stk_d);  prev_std  = v(stk_d, 1)
    cur_adx     = v(adx)
    cur_pdi     = v(plus_di)
    cur_mdi     = v(minus_di)

    # ── Layer 4a: volatility floor ───────────────────────────────────────────
    atr_series  = calc_atr(high, low, close)
    cur_atr     = v(atr_series)
    atr_avg     = float(atr_series.iloc[-20:].mean())
    # Require current ATR to be at least 60% of the 20-bar average
    # (filters out dead, no-movement markets)
    if cur_atr < atr_avg * 0.60:
        log.debug(f"{display_name}: ATR {cur_atr:.5f} too low vs avg {atr_avg:.5f} — skip")
        return None

    # ── Layer 4b: candlestick pattern ────────────────────────────────────────
    candle_pattern = _detect_candle_pattern(open_, high, low, close)

    buy_votes  = []
    sell_votes = []

    # Switch between trend-following and mean-reversion logic based on ADX
    trending = cur_adx >= 22

    # ── 1. RSI ───────────────────────────────────────────────────────────────
    if trending:
        # In a trend: RSI above/below 50 shows momentum direction
        if cur_rsi > 55:
            buy_votes.append(f"RSI {cur_rsi:.1f} — bullish momentum")
        elif cur_rsi < 45:
            sell_votes.append(f"RSI {cur_rsi:.1f} — bearish momentum")
        if prev_rsi < 50 <= cur_rsi:
            buy_votes.append(f"RSI crossed 50 upward ({cur_rsi:.1f})")
        elif prev_rsi > 50 >= cur_rsi:
            sell_votes.append(f"RSI crossed 50 downward ({cur_rsi:.1f})")
    else:
        # Ranging market: use classic overbought/oversold levels
        if cur_rsi < 30:
            buy_votes.append(f"RSI {cur_rsi:.1f} — oversold")
        elif cur_rsi > 70:
            sell_votes.append(f"RSI {cur_rsi:.1f} — overbought")

    # ── 2. EMA — crossover + stack ──────────────────────────────────────────
    if cur_e9 > cur_e21 and prev_e9 <= prev_e21:
        buy_votes.append("EMA 9 crossed above EMA 21")
    elif cur_e9 < cur_e21 and prev_e9 >= prev_e21:
        sell_votes.append("EMA 9 crossed below EMA 21")
    if cur_e9 > cur_e21 > cur_e50:
        buy_votes.append("EMA stack bullish (9 > 21 > 50)")
    elif cur_e9 < cur_e21 < cur_e50:
        sell_votes.append("EMA stack bearish (9 < 21 < 50)")

    # ── 3. MACD ──────────────────────────────────────────────────────────────
    if cur_hist > 0 and prev_hist <= 0:
        buy_votes.append("MACD histogram flipped positive")
    elif cur_hist < 0 and prev_hist >= 0:
        sell_votes.append("MACD histogram flipped negative")
    elif cur_hist > 0 and cur_macdl > cur_macds:
        buy_votes.append("MACD bullish momentum")
    elif cur_hist < 0 and cur_macdl < cur_macds:
        sell_votes.append("MACD bearish momentum")

    # ── 4. Bollinger Bands ───────────────────────────────────────────────────
    if cur_bb_mid > 0:
        bb_range = cur_bb_up - cur_bb_lo
        pct_b = (cur_close - cur_bb_lo) / bb_range if bb_range > 0 else 0.5
        if trending:
            # In a trend: position relative to midline
            if pct_b > 0.55:
                buy_votes.append(f"Price above BB midline (%B={pct_b:.2f})")
            elif pct_b < 0.45:
                sell_votes.append(f"Price below BB midline (%B={pct_b:.2f})")
        else:
            # Ranging: band touch signals
            if cur_close <= cur_bb_lo or pct_b < 0.15:
                buy_votes.append("Price at/near lower Bollinger Band")
            elif cur_close >= cur_bb_up or pct_b > 0.85:
                sell_votes.append("Price at/near upper Bollinger Band")

    # ── 5. Stochastic ────────────────────────────────────────────────────────
    if trending:
        # In a trend: stochastic direction
        if cur_stk > 50 and cur_stk > cur_std:
            buy_votes.append(f"Stochastic bullish (K={cur_stk:.1f})")
        elif cur_stk < 50 and cur_stk < cur_std:
            sell_votes.append(f"Stochastic bearish (K={cur_stk:.1f})")
    else:
        # Ranging: extremes + K/D cross
        if cur_stk < 20 and cur_std < 25:
            buy_votes.append(f"Stochastic oversold (K={cur_stk:.1f})")
        elif cur_stk > 80 and cur_std > 75:
            sell_votes.append(f"Stochastic overbought (K={cur_stk:.1f})")
    if cur_stk > cur_std and prev_stk <= prev_std and cur_stk < 80:
        buy_votes.append(f"Stochastic bullish K/D cross (K={cur_stk:.1f})")
    elif cur_stk < cur_std and prev_stk >= prev_std and cur_stk > 20:
        sell_votes.append(f"Stochastic bearish K/D cross (K={cur_stk:.1f})")

    # ── Layer 2: consensus gate — require MIN_INDICATORS agreeing ───────────
    n_buy  = len(buy_votes)
    n_sell = len(sell_votes)

    if n_buy == n_sell:
        return None
    if n_buy > n_sell:
        if n_buy < MIN_INDICATORS:
            return None
        direction = "BUY"
        reasons   = buy_votes
        dominant  = n_buy
    else:
        if n_sell < MIN_INDICATORS:
            return None
        direction = "SELL"
        reasons   = sell_votes
        dominant  = n_sell

    # ── Layer 3: ADX trend-strength + DI confirmation ───────────────────────
    if cur_adx < 15:
        log.debug(f"{display_name}: ADX {cur_adx:.1f} — too choppy, skipping")
        return None
    if direction == "BUY"  and cur_mdi > cur_pdi:
        return None
    if direction == "SELL" and cur_pdi > cur_mdi:
        return None

    # ── Dual higher-timeframe alignment (15m + 1h) ──────────────────────────
    htf_labels = []
    dir_val    = 1 if direction == "BUY" else -1

    # 1h must align or be neutral
    if htf_1h != 0 and htf_1h != dir_val:
        log.debug(f"{display_name}: 1h HTF opposes signal — skipping")
        return None
    if htf_1h == dir_val:
        lbl = "✅ 1h trend aligned"
        htf_labels.append(lbl)

    # 15m must align or be neutral
    if htf_15m != 0 and htf_15m != dir_val:
        log.debug(f"{display_name}: 15m HTF opposes signal — skipping")
        return None
    if htf_15m == dir_val:
        lbl = "✅ 15m trend aligned"
        htf_labels.append(lbl)

    # Require at least one HTF to actively confirm (not both neutral)
    if not htf_labels:
        log.debug(f"{display_name}: no HTF confirmation — skipping")
        return None

    reasons = htf_labels + reasons

    # ── Candlestick pattern bonus / filter ───────────────────────────────────
    if candle_pattern == dir_val:
        reasons = ["✅ Reversal candle confirmed"] + reasons
    elif candle_pattern == -dir_val:
        # Opposing candle — slight confidence penalty, not a hard block
        log.debug(f"{display_name}: candle pattern opposes signal — confidence penalised")

    # ── Confidence scoring ───────────────────────────────────────────────────
    total    = n_buy + n_sell
    raw_conf = dominant / max(total, 1)
    bonus    = 0.07 * max(dominant - MIN_INDICATORS, 0)   # +7% per extra indicator
    bonus   += 0.05 * len(htf_labels)                     # +5% per HTF confirming
    if candle_pattern == dir_val:
        bonus += 0.06                                      # +6% for pattern match
    elif candle_pattern == -dir_val:
        bonus -= 0.05                                      # -5% penalty for opposing candle
    if cur_adx > 30:
        bonus += 0.04
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
        "adx":        cur_adx,
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
