"""
Pocket Option — 500-Scan Results Runner
Runs exactly 500 scans at 60-second intervals, logs every signal,
then sends a full summary report to Telegram.
"""

import os, time, json, logging
from datetime import datetime
from collections import defaultdict
from dotenv import load_dotenv
import requests

load_dotenv()

from pocket_option_bot import (
    ASSETS, analyze_asset,
    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
    _tg_post, format_signal,
)

TOTAL_RUNS    = 500
INTERVAL_SECS = 60
RESULTS_FILE  = "pocket_option_results.json"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("pocket_option_runner.log", encoding="utf-8"),
    ],
)
log = logging.getLogger("PO_Runner")

# ─── Results tracking ────────────────────────────────────────────────────────

results = []          # list of every signal dict
scan_counts = defaultdict(int)          # asset → total scans
signal_counts = defaultdict(int)        # asset → signals fired
direction_counts = defaultdict(lambda: {"BUY": 0, "SELL": 0})  # asset → {BUY, SELL}
confidence_totals = defaultdict(float)  # asset → sum of confidences

def record_signal(sig: dict) -> None:
    results.append({
        "scan": sig.get("scan_num"),
        "timestamp": sig["timestamp"],
        "asset": sig["name"],
        "direction": sig["direction"],
        "confidence": sig["confidence"],
        "entry": sig["entry"],
        "expiry": sig["expiry"],
        "reasons": sig["reasons"],
    })
    signal_counts[sig["name"]] += 1
    direction_counts[sig["name"]][sig["direction"]] += 1
    confidence_totals[sig["name"]] += sig["confidence"]


def save_results() -> None:
    with open(RESULTS_FILE, "w") as f:
        json.dump(results, f, indent=2)


def build_summary_report(total_scans: int, elapsed_mins: float) -> str:
    total_signals = len(results)
    if total_signals == 0:
        return "📭 No signals were generated across all 500 scans."

    # Top assets by signal count
    sorted_assets = sorted(signal_counts.items(), key=lambda x: x[1], reverse=True)

    lines = [
        f"📊 <b>Pocket Option — 500 Scan Summary</b>",
        f"━━━━━━━━━━━━━━━━━━━━━━━━",
        f"✅ Scans completed : <b>{total_scans}</b>",
        f"📡 Total signals   : <b>{total_signals}</b>",
        f"⏱  Total time      : <b>{elapsed_mins:.1f} min</b>",
        f"📈 Signal rate     : <b>{total_signals/total_scans*100:.1f}% of scans</b>",
        f"",
        f"<b>─── Per-Asset Breakdown ───</b>",
    ]

    for asset, count in sorted_assets:
        buys  = direction_counts[asset]["BUY"]
        sells = direction_counts[asset]["SELL"]
        avg_conf = confidence_totals[asset] / count if count else 0
        bias = "🟢 BUY" if buys > sells else ("🔴 SELL" if sells > buys else "⚖️ NEUTRAL")
        lines.append(
            f"{asset}  →  <b>{count}</b> signals  |  {bias}  |  avg conf <b>{avg_conf:.0f}%</b>  (↑{buys} ↓{sells})"
        )

    # Most confident signal
    if results:
        best = max(results, key=lambda x: x["confidence"])
        lines += [
            f"",
            f"<b>─── Strongest Signal ───</b>",
            f"🏆 {best['asset']}  {best['direction']}  {best['confidence']}% conf",
            f"   Entry {best['entry']:.5g}  |  Expiry {best['expiry']}",
            f"   {best['timestamp']}",
        ]

    lines += [
        f"",
        f"💾 Full results saved to <code>{RESULTS_FILE}</code>",
    ]

    return "\n".join(lines)


# ─── Main runner ─────────────────────────────────────────────────────────────

def main() -> None:
    log.info(f"Starting 500-scan runner  ({INTERVAL_SECS}s interval = ~{TOTAL_RUNS*INTERVAL_SECS/60:.0f} min)")
    _tg_post(
        f"🚀 <b>500-Scan Runner Started</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📡 {len(ASSETS)} assets  |  60s interval\n"
        f"⏱  ETA: ~{TOTAL_RUNS * INTERVAL_SECS // 60} min\n"
        f"Results + summary sent when complete."
    )

    start_time = time.time()

    for scan_num in range(1, TOTAL_RUNS + 1):
        scan_start = time.time()
        log.info(f"Scan {scan_num}/{TOTAL_RUNS}")

        for ticker, name, expiry in ASSETS:
            scan_counts[name] += 1
            sig = analyze_asset(ticker, name, expiry)
            if sig:
                sig["scan_num"] = scan_num
                record_signal(sig)
                log.info(f"  {name}: {sig['direction']} {sig['confidence']}%")
                _tg_post(format_signal(sig))
                time.sleep(0.5)

        # Checkpoint every 100 scans
        if scan_num % 100 == 0:
            save_results()
            pct = scan_num / TOTAL_RUNS * 100
            elapsed = (time.time() - start_time) / 60
            remaining = (TOTAL_RUNS - scan_num) * INTERVAL_SECS / 60
            _tg_post(
                f"📍 <b>Checkpoint {scan_num}/500 ({pct:.0f}%)</b>\n"
                f"Signals so far: {len(results)}\n"
                f"Elapsed: {elapsed:.1f} min  |  ETA: {remaining:.0f} min"
            )

        # Sleep for remainder of 60s interval
        elapsed_scan = time.time() - scan_start
        sleep_time = max(0, INTERVAL_SECS - elapsed_scan)
        if scan_num < TOTAL_RUNS:
            time.sleep(sleep_time)

    # Final summary
    elapsed_mins = (time.time() - start_time) / 60
    save_results()
    summary = build_summary_report(TOTAL_RUNS, elapsed_mins)
    log.info("Run complete. Sending summary…")
    _tg_post(summary)
    log.info(f"Done. {len(results)} total signals. Results saved to {RESULTS_FILE}")


if __name__ == "__main__":
    main()
