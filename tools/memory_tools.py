"""
Memory Tools for Clawdbot Trader
Provides persistent memory for strategy learnings, insights, and trade outcomes.
"""

import json
import os
import sys
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


# Cross-platform file locking
@contextmanager
def _file_lock(filepath: Path):
    """Cross-platform advisory file lock for serializing access to a file."""
    lock_path = filepath.parent / (filepath.name + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fh = open(lock_path, "a+")
    try:
        if sys.platform == "win32":
            import msvcrt
            # msvcrt.locking needs a non-zero length; lock 1 byte
            msvcrt.locking(fh.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        yield fh
    finally:
        try:
            if sys.platform == "win32":
                import msvcrt
                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        finally:
            fh.close()

# Resolve paths relative to project root
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
MEMORY_DIR = DATA_DIR / "memory"

# Memory files
STRATEGY_MEMORY_FILE = MEMORY_DIR / "strategy_insights.jsonl"
TRADE_OUTCOMES_FILE = MEMORY_DIR / "trade_outcomes.jsonl"
CONVERSATION_MEMORY_FILE = MEMORY_DIR / "conversations.jsonl"


def _ensure_memory_dir():
    """Ensure memory directory exists."""
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)


# =============================================================================
# STRATEGY INSIGHTS MEMORY
# =============================================================================

def save_strategy_insight(
    insight: str,
    context: Optional[Dict[str, Any]] = None,
    source: str = "manual",
    tags: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Save a strategy learning/insight to memory.

    Args:
        insight: The strategy insight or learning
        context: Optional context (symbol, prices, conditions, etc.)
        source: Source of insight ("manual", "chat", "performance", "backtest")
        tags: Optional tags for categorization

    Returns:
        The saved entry
    """
    _ensure_memory_dir()

    with _file_lock(STRATEGY_MEMORY_FILE):
        entry = {
            "id": _get_next_id_unlocked(STRATEGY_MEMORY_FILE),
            "timestamp": datetime.now().isoformat(),
            "insight": insight,
            "context": context or {},
            "source": source,
            "tags": tags or [],
            "active": True  # Can be deactivated if insight proves wrong
        }

        with open(STRATEGY_MEMORY_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    print(f"[Memory] Saved insight: {insight[:50]}...")
    return entry


def get_strategy_insights(
    n: int = 20,
    active_only: bool = True,
    tags: Optional[List[str]] = None,
    source: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Retrieve strategy insights from memory.

    Args:
        n: Maximum number of insights to return (most recent first)
        active_only: Only return active insights
        tags: Filter by tags (any match)
        source: Filter by source

    Returns:
        List of insight entries
    """
    if not STRATEGY_MEMORY_FILE.exists():
        return []

    insights = []
    with open(STRATEGY_MEMORY_FILE, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                try:
                    entry = json.loads(line)

                    # Apply filters
                    if active_only and not entry.get("active", True):
                        continue
                    if source and entry.get("source") != source:
                        continue
                    if tags and not any(t in entry.get("tags", []) for t in tags):
                        continue

                    insights.append(entry)
                except json.JSONDecodeError:
                    continue

    # Return most recent first
    return insights[-n:][::-1]


def format_insights_for_prompt(n: int = 15) -> str:
    """
    Format insights as a string for injection into agent prompts.

    Args:
        n: Maximum number of insights to include

    Returns:
        Formatted string of insights
    """
    insights = get_strategy_insights(n=n)

    if not insights:
        return "No previous strategy insights recorded yet."

    lines = []
    for i, entry in enumerate(insights, 1):
        insight = entry.get("insight", "")
        source = entry.get("source", "unknown")
        tags = entry.get("tags", [])

        tag_str = f" [{', '.join(tags)}]" if tags else ""
        lines.append(f"{i}. {insight}{tag_str} (from {source})")

    return "\n".join(lines)


def deactivate_insight(insight_id: int, reason: str = "") -> bool:
    """
    Deactivate an insight that proved to be wrong.

    Args:
        insight_id: The ID of the insight to deactivate
        reason: Reason for deactivation

    Returns:
        True if successful
    """
    if not STRATEGY_MEMORY_FILE.exists():
        return False

    with _file_lock(STRATEGY_MEMORY_FILE):
        lines = []
        found = False

        with open(STRATEGY_MEMORY_FILE, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    entry = json.loads(line)
                    if entry.get("id") == insight_id:
                        entry["active"] = False
                        entry["deactivated_at"] = datetime.now().isoformat()
                        entry["deactivation_reason"] = reason
                        found = True
                    lines.append(json.dumps(entry, ensure_ascii=False))

        if found:
            with open(STRATEGY_MEMORY_FILE, "w", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")

    return found


# =============================================================================
# TRADE OUTCOMES MEMORY
# =============================================================================

def save_trade_outcome(
    symbol: str,
    action: str,
    amount: int,
    entry_price: float,
    exit_price: Optional[float] = None,
    profit_pct: Optional[float] = None,
    reasoning: str = "",
    outcome: str = "pending"  # "pending", "win", "loss", "neutral"
) -> Dict[str, Any]:
    """
    Save a trade outcome for learning.

    Args:
        symbol: Stock/crypto symbol
        action: "buy" or "sell"
        amount: Number of shares/units
        entry_price: Price at entry
        exit_price: Price at exit (if closed)
        profit_pct: Profit/loss percentage
        reasoning: Why this trade was made
        outcome: Trade outcome category

    Returns:
        The saved entry
    """
    _ensure_memory_dir()

    with _file_lock(TRADE_OUTCOMES_FILE):
        entry = {
            "id": _get_next_id_unlocked(TRADE_OUTCOMES_FILE),
            "timestamp": datetime.now().isoformat(),
            "symbol": symbol,
            "action": action,
            "amount": amount,
            "entry_price": entry_price,
            "exit_price": exit_price,
            "profit_pct": profit_pct,
            "reasoning": reasoning,
            "outcome": outcome
        }

        with open(TRADE_OUTCOMES_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    return entry


def get_trade_outcomes(
    n: int = 50,
    symbol: Optional[str] = None,
    outcome: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Retrieve trade outcomes.

    Args:
        n: Maximum number of outcomes to return
        symbol: Filter by symbol
        outcome: Filter by outcome ("win", "loss", "neutral")

    Returns:
        List of trade outcome entries
    """
    if not TRADE_OUTCOMES_FILE.exists():
        return []

    outcomes = []
    with open(TRADE_OUTCOMES_FILE, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                try:
                    entry = json.loads(line)

                    if symbol and entry.get("symbol") != symbol:
                        continue
                    if outcome and entry.get("outcome") != outcome:
                        continue

                    outcomes.append(entry)
                except json.JSONDecodeError:
                    continue

    return outcomes[-n:]


def get_win_rate(symbol: Optional[str] = None) -> Dict[str, Any]:
    """
    Calculate win rate from trade outcomes.

    Args:
        symbol: Optional symbol to filter by

    Returns:
        Dict with win rate statistics
    """
    outcomes = get_trade_outcomes(n=1000, symbol=symbol)

    if not outcomes:
        return {"win_rate": 0, "total_trades": 0, "wins": 0, "losses": 0}

    wins = sum(1 for o in outcomes if o.get("outcome") == "win")
    losses = sum(1 for o in outcomes if o.get("outcome") == "loss")
    total = wins + losses

    return {
        "win_rate": (wins / total * 100) if total > 0 else 0,
        "total_trades": len(outcomes),
        "wins": wins,
        "losses": losses,
        "neutral": sum(1 for o in outcomes if o.get("outcome") == "neutral"),
        "pending": sum(1 for o in outcomes if o.get("outcome") == "pending")
    }


# =============================================================================
# CONVERSATION MEMORY
# =============================================================================

def save_conversation(
    messages: List[Dict[str, str]],
    summary: str = "",
    insights_extracted: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Save a strategy chat conversation.

    Args:
        messages: List of conversation messages
        summary: Summary of the conversation
        insights_extracted: List of insights extracted from this conversation

    Returns:
        The saved entry
    """
    _ensure_memory_dir()

    with _file_lock(CONVERSATION_MEMORY_FILE):
        entry = {
            "id": _get_next_id_unlocked(CONVERSATION_MEMORY_FILE),
            "timestamp": datetime.now().isoformat(),
            "messages": messages,
            "summary": summary,
            "insights_extracted": insights_extracted or []
        }

        with open(CONVERSATION_MEMORY_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    return entry


def get_recent_conversations(n: int = 5) -> List[Dict[str, Any]]:
    """
    Get recent conversation summaries.

    Args:
        n: Number of conversations to return

    Returns:
        List of conversation entries
    """
    if not CONVERSATION_MEMORY_FILE.exists():
        return []

    conversations = []
    with open(CONVERSATION_MEMORY_FILE, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                try:
                    conversations.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

    return conversations[-n:]


# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

def _get_next_id_unlocked(filepath: Path) -> int:
    """Get next available ID for a memory file. Caller must hold the lock."""
    if not filepath.exists():
        return 1

    max_id = 0
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                try:
                    entry = json.loads(line)
                    max_id = max(max_id, entry.get("id", 0))
                except json.JSONDecodeError:
                    continue

    return max_id + 1


def _get_next_id(filepath: Path) -> int:
    """Get next available ID for a memory file (thread/process safe)."""
    with _file_lock(filepath):
        return _get_next_id_unlocked(filepath)


def get_memory_stats() -> Dict[str, Any]:
    """Get statistics about stored memories."""
    stats = {
        "strategy_insights": 0,
        "trade_outcomes": 0,
        "conversations": 0,
        "win_rate": get_win_rate()
    }

    if STRATEGY_MEMORY_FILE.exists():
        with open(STRATEGY_MEMORY_FILE, "r", encoding="utf-8") as f:
            stats["strategy_insights"] = sum(1 for line in f if line.strip())

    if TRADE_OUTCOMES_FILE.exists():
        with open(TRADE_OUTCOMES_FILE, "r", encoding="utf-8") as f:
            stats["trade_outcomes"] = sum(1 for line in f if line.strip())

    if CONVERSATION_MEMORY_FILE.exists():
        with open(CONVERSATION_MEMORY_FILE, "r", encoding="utf-8") as f:
            stats["conversations"] = sum(1 for line in f if line.strip())

    return stats


def clear_strategy_insights() -> bool:
    """
    Clear all strategy insights.

    Returns:
        True if cleared successfully
    """
    if STRATEGY_MEMORY_FILE.exists():
        STRATEGY_MEMORY_FILE.unlink()
        return True
    return False


def clear_all_memory(confirm: bool = False) -> bool:
    """
    Clear all memory files. USE WITH CAUTION.

    Args:
        confirm: Must be True to actually clear

    Returns:
        True if cleared
    """
    if not confirm:
        print("Warning: Set confirm=True to actually clear all memory")
        return False

    for filepath in [STRATEGY_MEMORY_FILE, TRADE_OUTCOMES_FILE, CONVERSATION_MEMORY_FILE]:
        if filepath.exists():
            filepath.unlink()
            print(f"Deleted: {filepath}")

    return True


# =============================================================================
# QUICK ACCESS FOR PROMPTS
# =============================================================================

def get_memory_context_for_prompt() -> str:
    """
    Get a comprehensive memory context string for injection into prompts.
    Includes insights, recent performance, and patterns.
    """
    lines = []

    # Strategy insights
    insights = format_insights_for_prompt(n=10)
    lines.append("## LEARNED STRATEGY INSIGHTS:")
    lines.append(insights)
    lines.append("")

    # Win rate
    win_stats = get_win_rate()
    if win_stats["total_trades"] > 0:
        lines.append("## TRADING PERFORMANCE:")
        lines.append(f"- Win rate: {win_stats['win_rate']:.1f}%")
        lines.append(f"- Total trades analyzed: {win_stats['total_trades']}")
        lines.append(f"- Wins: {win_stats['wins']}, Losses: {win_stats['losses']}")
        lines.append("")

    # Recent losses to learn from
    recent_losses = get_trade_outcomes(n=5, outcome="loss")
    if recent_losses:
        lines.append("## RECENT LOSSES TO LEARN FROM:")
        for loss in recent_losses[-3:]:
            symbol = loss.get("symbol", "?")
            pct = loss.get("profit_pct", 0)
            reason = loss.get("reasoning", "")[:50]
            lines.append(f"- {symbol}: {pct:.1f}% loss - {reason}")
        lines.append("")

    return "\n".join(lines)


if __name__ == "__main__":
    # Test the memory system
    print("=== Memory Tools Test ===\n")

    # Save a test insight
    save_strategy_insight(
        "Tech stocks tend to dip on Monday mornings - good buying opportunity",
        context={"observation_period": "2024-2025"},
        source="manual",
        tags=["timing", "tech"]
    )

    # Show stats
    stats = get_memory_stats()
    print(f"\nMemory Stats: {json.dumps(stats, indent=2)}")

    # Show formatted insights
    print("\n" + "="*50)
    print("Formatted insights for prompt:")
    print(format_insights_for_prompt())
