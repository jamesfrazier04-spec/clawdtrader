"""
Pocket Option — Trade Outcome Tracker
======================================
Wraps the signal bot. When a signal fires:
  1. Records entry price + direction + expiry time
  2. Waits for the expiry (5 or 15 min)
  3. Fetches the price at expiry via yfinance
  4. Logs WIN / LOSS and updates running stats
  5. Sends result + running win rate to Telegram

Run:
  python pocket_option_tracker.py
"""

import os, time, json, threading, logging
from datetime import datetime, timezone
from collections import defaultdict
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))

import yfinance as yf
from pocket_option_bot import (
    ASSETS, SCAN_INTERVAL_SECS, analyze_asset,
    _tg_post, format_signal,
)

# ─── Config ──────────────────────────────────────────────────────────────────

OUTCOMES_FILE = "pocket_option_outcomes.json"

# Map expiry label → seconds to wait before checking result
EXPIRY_SECONDS = {
    "5 min":  5 * 60,
    "15 min": 15 * 60,
}

# ─── Logging ─────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("pocket_option_tracker.log", encoding="utf-8"),
    ],
)
log = logging.getLogger("PO_Tracker")

# ─── Stats (shared across threads) ───────────────────────────────────────────

_lock       = threading.Lock()
_outcomes   = []          # list of completed trade dicts
_wins       = 0
_losses     = 0
_asset_wins   = defaultdict(int)
_asset_losses = defaultdict(int)

def _save_outcomes():
    with open(OUTCOMES_FILE, "w") as f:
        json.dump(_outcomes, f, indent=2)

# ─── Price fetcher ───────────────────────────────────────────────────────────

def fetch_current_price(ticker: str) -> float | None:
    """Fetch the most recent close price for a ticker."""
    try:
        df = yf.download(ticker, period="1d", interval="1m", progress=False, auto_adjust=True)
        if df is None or len(df) == 0:
            return None
        if hasattr(df.columns, "get_level_values"):
            df.columns = df.columns.get_level_values(0)
        return float(df["Close"].dropna().iloc[-1])
    except Exception as exc:
        log.warning(f"Price fetch failed for {ticker}: {exc}")
        return None

# ─── Outcome checker (runs in background thread) ─────────────────────────────

def _check_outcome(sig: dict):
    """
    Wait for expiry, fetch exit price, determine WIN/LOSS, notify Telegram.
    Runs in its own thread so it never blocks the scan loop.
    """
    global _wins, _losses

    expiry_label = sig["expiry"]
    wait_secs    = EXPIRY_SECONDS.get(expiry_label, 5 * 60)

    log.info(f"  [{sig['name']}] Waiting {wait_secs}s for expiry…")
    time.sleep(wait_secs)

    exit_price = fetch_current_price(sig["ticker"])
    if exit_price is None:
        log.warning(f"  [{sig['name']}] Could not fetch exit price — skipping outcome.")
        return

    entry_price = sig["entry"]
    direction   = sig["direction"]

    # WIN if price moved in the predicted direction
    if direction == "BUY":
        won = exit_price > entry_price
    else:
        won = exit_price < entry_price

    result_label = "WIN ✅" if won else "LOSS ❌"
    pips         = abs(exit_price - entry_price)
    pct_move     = (exit_price - entry_price) / entry_price * 100

    # Update stats
    with _lock:
        if won:
            _wins += 1
            _asset_wins[sig["name"]] += 1
        else:
            _losses += 1
            _asset_losses[sig["name"]] += 1

        total     = _wins + _losses
        win_rate  = _wins / total * 100 if total else 0

        outcome = {
            "asset":       sig["name"],
            "direction":   direction,
            "confidence":  sig["confidence"],
            "entry":       entry_price,
            "exit":        exit_price,
            "pct_move":    round(pct_move, 4),
            "result":      "WIN" if won else "LOSS",
            "expiry":      expiry_label,
            "signal_time": sig["timestamp"],
            "exit_time":   datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        }
        _outcomes.append(outcome)
        _save_outcomes()

    # Format exit price nicely
    if exit_price > 1000:
        ep_str = f"{exit_price:,.2f}"
        en_str = f"{entry_price:,.2f}"
    elif exit_price > 10:
        ep_str = f"{exit_price:.4f}"
        en_str = f"{entry_price:.4f}"
    else:
        ep_str = f"{exit_price:.5f}"
        en_str = f"{entry_price:.5f}"

    direction_icon = "▲" if direction == "BUY" else "▼"
    result_icon    = "✅" if won else "❌"
    move_sign      = "+" if pct_move >= 0 else ""

    msg = (
        f"{result_icon} <b>{sig['name']}  {direction} {direction_icon}  —  {'WIN' if won else 'LOSS'}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📥 Entry  : <b>{en_str}</b>\n"
        f"📤 Exit   : <b>{ep_str}</b>\n"
        f"📉 Move   : <b>{move_sign}{pct_move:.3f}%</b>\n"
        f"⏱  Expiry : {expiry_label}\n\n"
        f"📊 <b>Running Stats</b>\n"
        f"  Wins   : {_wins}   Losses : {_losses}\n"
        f"  Win Rate : <b>{win_rate:.1f}%</b>  ({total} trades)"
    )

    log.info(f"  [{sig['name']}] {result_label}  entry={en_str} exit={ep_str}  WR={win_rate:.1f}%")
    _tg_post(msg)


# ─── Main loop ────────────────────────────────────────────────────────────────

def main():
    log.info("Pocket Option Tracker starting…")
    _tg_post(
        "📡 <b>Pocket Option Tracker Online</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Signals fire → entry recorded\n"
        "After expiry → exit price checked\n"
        "WIN/LOSS + live win rate sent to Telegram\n"
        f"Scan interval: {SCAN_INTERVAL_SECS}s"
    )

    scan_num = 0
    while True:
        scan_num += 1
        log.info(f"─── Scan #{scan_num}  {datetime.utcnow().strftime('%H:%M:%S UTC')} ───")

        for ticker, name, expiry in ASSETS:
            sig = analyze_asset(ticker, name, expiry)
            if sig:
                log.info(f"  Signal: {name} {sig['direction']} {sig['confidence']}%  entry={sig['entry']:.5g}")
                # Send signal alert immediately
                _tg_post(format_signal(sig))
                time.sleep(0.4)
                # Spin up outcome checker in background — won't block next scan
                t = threading.Thread(
                    target=_check_outcome,
                    args=(sig,),
                    daemon=True,
                )
                t.start()

        log.info(f"  Sleeping {SCAN_INTERVAL_SECS}s…")
        time.sleep(SCAN_INTERVAL_SECS)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        total    = _wins + _losses
        win_rate = _wins / total * 100 if total else 0
        log.info(f"Stopped. Final: {_wins}W / {_losses}L  WR={win_rate:.1f}%")
        _tg_post(
            f"🛑 <b>Tracker stopped.</b>\n"
            f"Final: {_wins}W / {_losses}L  |  Win Rate: <b>{win_rate:.1f}%</b>  ({total} trades)"
        )
