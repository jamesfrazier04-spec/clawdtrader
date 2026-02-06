import os
import sys
from typing import Any, Dict, List, Optional

from fastmcp import FastMCP

from typing import Dict, List, Optional, Any
from pathlib import Path

# Cross-platform file locking
if sys.platform == 'win32':
    import msvcrt
    def lock_file(f):
        msvcrt.locking(f.fileno(), msvcrt.LK_LOCK, 1)
    def unlock_file(f):
        msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
else:
    import fcntl
    def lock_file(f):
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
    def unlock_file(f):
        fcntl.flock(f.fileno(), fcntl.LOCK_UN)
# Add project root directory to Python path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)
import json

from tools.general_tools import get_config_value, write_config_value
from tools.price_tools import (get_latest_position, get_open_prices,
                               get_yesterday_date,
                               get_yesterday_open_and_close_price,
                               get_yesterday_profit)

mcp = FastMCP("TradeTools")

def _position_lock(signature: str):
    """Context manager for file-based lock to serialize position updates per signature."""
    class _Lock:
        def __init__(self, name: str):
            # Prefer LOG_PATH so the lock file lives alongside the positions file
            log_path = get_config_value("LOG_PATH", "./data/agent_data")
            # Resolve base dir for this signature under the configured log path
            if os.path.isabs(log_path):
                # Absolute path (e.g., temp directory)
                base_dir = Path(log_path) / name
            else:
                # Relative path: treat "./data/xxx" specially to keep compatibility
                if log_path.startswith("./data/"):
                    log_rel = log_path[7:]  # strip "./data/"
                else:
                    log_rel = log_path
                base_dir = Path(project_root) / "data" / log_rel / name
            base_dir.mkdir(parents=True, exist_ok=True)
            self.lock_path = base_dir / ".position.lock"
            # Ensure lock file exists
            self._fh = open(self.lock_path, "a+")
        def __enter__(self):
            lock_file(self._fh)
            return self
        def __exit__(self, exc_type, exc, tb):
            try:
                unlock_file(self._fh)
            finally:
                self._fh.close()
    return _Lock(signature)



@mcp.tool()
def buy(symbol: str, amount: int) -> Dict[str, Any]:
    """
    Buy stock function

    This function simulates stock buying operations, including the following steps:
    1. Get current position and operation ID
    2. Get stock opening price for the day
    3. Validate buy conditions (sufficient cash, lot size for CN market)
    4. Update position (increase stock quantity, decrease cash)
    5. Record transaction to position.jsonl file

    Args:
        symbol: Stock symbol, such as "AAPL", "MSFT", etc.
        amount: Buy quantity, must be a positive integer, indicating how many shares to buy
                For Chinese A-shares (symbols ending with .SH or .SZ), must be multiples of 100

    Returns:
        Dict[str, Any]:
          - Success: Returns new position dictionary (containing stock quantity and cash balance)
          - Failure: Returns {"error": error message, ...} dictionary

    Raises:
        ValueError: Raised when SIGNATURE environment variable is not set

    Example:
        >>> result = buy("AAPL", 10)
        >>> print(result)  # {"AAPL": 110, "MSFT": 5, "CASH": 5000.0, ...}
        >>> result = buy("600519.SH", 100)  # Chinese A-shares must be multiples of 100
        >>> print(result)  # {"600519.SH": 100, "CASH": 85000.0, ...}
    """
    # Step 1: Get environment variables and basic information
    # Get signature (model name) from environment variable, used to determine data storage path
    signature = get_config_value("SIGNATURE")
    if signature is None:
        raise ValueError("SIGNATURE environment variable is not set")

    # Get current trading date from environment variable
    today_date = get_config_value("TODAY_DATE")

    # Auto-detect market type based on symbol format
    if symbol.endswith((".SH", ".SZ")):
        market = "cn"
    else:
        market = "us"

    # Amount validation for stocks
    try:
        amount = int(amount)  # Convert to int for stocks
    except ValueError:
        return {
            "error": f"Invalid amount format. Amount must be an integer for stock trading. You provided: {amount}",
            "symbol": symbol,
            "date": today_date,
        }

    if amount <= 0:
        return {
            "error": f"Amount must be positive. You tried to buy {amount} shares.",
            "symbol": symbol,
            "amount": amount,
            "date": today_date,
        }

    # 🇨🇳 Chinese A-shares trading rule: Must trade in lots of 100 shares (一手 = 100股)
    if market == "cn" and amount % 100 != 0:
        return {
            "error": f"Chinese A-shares must be traded in multiples of 100 shares (1 lot = 100 shares). You tried to buy {amount} shares.",
            "symbol": symbol,
            "amount": amount,
            "date": today_date,
            "suggestion": f"Please use {(amount // 100) * 100} or {((amount // 100) + 1) * 100} shares instead.",
        }

    # Acquire lock for atomic read-validate-modify-write on positions
    with _position_lock(signature):
        # Step 2: Get current latest position and operation ID
        try:
            current_position, current_action_id = get_latest_position(today_date, signature)
        except Exception as e:
            print(e)
            print(today_date, signature)
            return {"error": f"Failed to load latest position: {e}", "symbol": symbol, "date": today_date}

        # Step 3: Get stock opening price for the day
        try:
            this_symbol_price = get_open_prices(today_date, [symbol], market=market)[f"{symbol}_price"]
        except KeyError:
            return {
                "error": f"Symbol {symbol} not found! This action will not be allowed.",
                "symbol": symbol,
                "date": today_date,
            }
        if this_symbol_price is None:
            return {
                "error": f"Price data not available for {symbol} at {today_date}.",
                "symbol": symbol,
                "date": today_date,
                "market": market,
            }

        # Step 4: Position size limit check (max 20% of portfolio)
        cash = current_position.get("CASH", 0)
        portfolio_value = cash
        for k, v in current_position.items():
            if k == "CASH":
                continue
            try:
                sym_price = get_open_prices(today_date, [k], market="cn" if k.endswith((".SH", ".SZ")) else "us").get(f"{k}_price", 0)
                if sym_price:
                    portfolio_value += v * sym_price
            except Exception:
                pass  # If we can't price a position, skip it for this check
        proposed_value = (current_position.get(symbol, 0) + amount) * this_symbol_price
        if portfolio_value > 0 and (proposed_value / portfolio_value) > 0.20:
            return {
                "error": f"Position size limit exceeded! {symbol} would be {proposed_value/portfolio_value*100:.1f}% of portfolio (max 20%).",
                "symbol": symbol,
                "proposed_pct": round(proposed_value / portfolio_value * 100, 1),
                "max_pct": 20,
                "date": today_date,
            }

        # Step 5: Validate cash
        try:
            cash_left = current_position["CASH"] - this_symbol_price * amount
        except Exception as e:
            return {
                "error": f"Failed to compute cash after purchase: {e}",
                "symbol": symbol,
                "date": today_date,
                "price": this_symbol_price,
                "amount": amount,
                "position_keys": list(current_position.keys()),
            }

        if cash_left < 0:
            return {
                "error": "Insufficient cash! This action will not be allowed.",
                "required_cash": this_symbol_price * amount,
                "cash_available": current_position.get("CASH", 0),
                "symbol": symbol,
                "date": today_date,
            }

        # Step 6: Execute buy operation, update position
        new_position = current_position.copy()
        new_position["CASH"] = cash_left
        new_position[symbol] = new_position.get(symbol, 0) + amount

        # Step 7: Record transaction to position.jsonl file
        log_path = get_config_value("LOG_PATH", "./data/agent_data")
        if log_path.startswith("./data/"):
            log_path = log_path[7:]
        position_file_path = os.path.join(project_root, "data", log_path, signature, "position", "position.jsonl")
        with open(position_file_path, "a") as f:
            print(
                f"Writing to position.jsonl: {json.dumps({'date': today_date, 'id': current_action_id + 1, 'this_action':{'action':'buy','symbol':symbol,'amount':amount},'positions': new_position})}"
            )
            f.write(
                json.dumps(
                    {
                        "date": today_date,
                        "id": current_action_id + 1,
                        "this_action": {"action": "buy", "symbol": symbol, "amount": amount},
                        "positions": new_position,
                    }
                )
                + "\n"
            )

    # Step 8: Return updated position
    write_config_value("IF_TRADE", True)
    print("IF_TRADE", get_config_value("IF_TRADE"))
    return new_position


def _get_today_buy_amount(symbol: str, today_date: str, signature: str) -> int:
    """
    Helper function to get the total amount bought today for T+1 restriction check

    Args:
        symbol: Stock symbol
        today_date: Trading date
        signature: Model signature

    Returns:
        Total shares bought today
    """
    log_path = get_config_value("LOG_PATH", "./data/agent_data")
    if log_path.startswith("./data/"):
        log_path = log_path[7:]  # Remove "./data/" prefix
    position_file_path = os.path.join(project_root, "data", log_path, signature, "position", "position.jsonl")

    if not os.path.exists(position_file_path):
        return 0

    total_bought_today = 0
    with open(position_file_path, "r") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                record = json.loads(line)
                if record.get("date") == today_date:
                    this_action = record.get("this_action", {})
                    if this_action.get("action") == "buy" and this_action.get("symbol") == symbol:
                        total_bought_today += this_action.get("amount", 0)
            except Exception:
                continue

    return total_bought_today


@mcp.tool()
def sell(symbol: str, amount: int) -> Dict[str, Any]:
    """
    Sell stock function

    This function simulates stock selling operations, including the following steps:
    1. Get current position and operation ID
    2. Get stock opening price for the day
    3. Validate sell conditions (position exists, sufficient quantity, lot size, T+1 for CN market)
    4. Update position (decrease stock quantity, increase cash)
    5. Record transaction to position.jsonl file

    Args:
        symbol: Stock symbol, such as "AAPL", "MSFT", etc.
        amount: Sell quantity, must be a positive integer, indicating how many shares to sell
                For Chinese A-shares (symbols ending with .SH or .SZ), must be multiples of 100
                and cannot sell shares bought on the same day (T+1 rule)

    Returns:
        Dict[str, Any]:
          - Success: Returns new position dictionary (containing stock quantity and cash balance)
          - Failure: Returns {"error": error message, ...} dictionary

    Raises:
        ValueError: Raised when SIGNATURE environment variable is not set

    Example:
        >>> result = sell("AAPL", 10)
        >>> print(result)  # {"AAPL": 90, "MSFT": 5, "CASH": 15000.0, ...}
        >>> result = sell("600519.SH", 100)  # Chinese A-shares must be multiples of 100
        >>> print(result)  # {"600519.SH": 0, "CASH": 115000.0, ...}
    """
    # Step 1: Get environment variables and basic information
    # Get signature (model name) from environment variable, used to determine data storage path
    signature = get_config_value("SIGNATURE")
    if signature is None:
        raise ValueError("SIGNATURE environment variable is not set")

    # Get current trading date from environment variable
    today_date = get_config_value("TODAY_DATE")

    # Auto-detect market type based on symbol format
    if symbol.endswith((".SH", ".SZ")):
        market = "cn"
    else:
        market = "us"

    # Amount validation for stocks
    try:
        amount = int(amount)  # Convert to int for stocks
    except ValueError:
        return {
            "error": f"Invalid amount format. Amount must be an integer for stock trading. You provided: {amount}",
            "symbol": symbol,
            "date": today_date,
        }

    if amount <= 0:
        return {
            "error": f"Amount must be positive. You tried to sell {amount} shares.",
            "symbol": symbol,
            "amount": amount,
            "date": today_date,
        }

    # 🇨🇳 Chinese A-shares trading rule: Must trade in lots of 100 shares (一手 = 100股)
    if market == "cn" and amount % 100 != 0:
        return {
            "error": f"Chinese A-shares must be traded in multiples of 100 shares (1 lot = 100 shares). You tried to sell {amount} shares.",
            "symbol": symbol,
            "amount": amount,
            "date": today_date,
            "suggestion": f"Please use {(amount // 100) * 100} or {((amount // 100) + 1) * 100} shares instead.",
        }

    # Acquire lock for atomic read-validate-modify-write on positions
    with _position_lock(signature):
        # Step 2: Get current latest position and operation ID
        current_position, current_action_id = get_latest_position(today_date, signature)

        # Step 3: Get stock opening price for the day
        try:
            this_symbol_price = get_open_prices(today_date, [symbol], market=market)[f"{symbol}_price"]
        except KeyError:
            return {
                "error": f"Symbol {symbol} not found! This action will not be allowed.",
                "symbol": symbol,
                "date": today_date,
            }

        # Step 4: Validate sell conditions
        if symbol not in current_position:
            return {
                "error": f"No position for {symbol}! This action will not be allowed.",
                "symbol": symbol,
                "date": today_date,
            }

        if current_position[symbol] < amount:
            return {
                "error": "Insufficient shares! This action will not be allowed.",
                "have": current_position.get(symbol, 0),
                "want_to_sell": amount,
                "symbol": symbol,
                "date": today_date,
            }

        # Chinese A-shares T+1 trading rule
        if market == "cn":
            bought_today = _get_today_buy_amount(symbol, today_date, signature)
            if bought_today > 0:
                sellable_amount = current_position[symbol] - bought_today
                if amount > sellable_amount:
                    return {
                        "error": f"T+1 restriction violated! You bought {bought_today} shares of {symbol} today and cannot sell them until tomorrow.",
                        "symbol": symbol,
                        "total_position": current_position[symbol],
                        "bought_today": bought_today,
                        "sellable_today": max(0, sellable_amount),
                        "want_to_sell": amount,
                        "date": today_date,
                    }

        # Step 5: Execute sell operation, update position
        new_position = current_position.copy()
        new_position[symbol] -= amount
        new_position["CASH"] = new_position.get("CASH", 0) + this_symbol_price * amount

        # Step 6: Record transaction to position.jsonl file
        log_path = get_config_value("LOG_PATH", "./data/agent_data")
        if log_path.startswith("./data/"):
            log_path = log_path[7:]
        position_file_path = os.path.join(project_root, "data", log_path, signature, "position", "position.jsonl")
        with open(position_file_path, "a") as f:
            print(
                f"Writing to position.jsonl: {json.dumps({'date': today_date, 'id': current_action_id + 1, 'this_action':{'action':'sell','symbol':symbol,'amount':amount},'positions': new_position})}"
            )
            f.write(
                json.dumps(
                    {
                        "date": today_date,
                        "id": current_action_id + 1,
                        "this_action": {"action": "sell", "symbol": symbol, "amount": amount},
                        "positions": new_position,
                    }
                )
                + "\n"
            )

    # Step 7: Return updated position
    write_config_value("IF_TRADE", True)
    return new_position


if __name__ == "__main__":
    # new_result = buy("AAPL", 1)
    # print(new_result)
    # new_result = sell("AAPL", 1)
    # print(new_result)
    port = int(os.getenv("TRADE_HTTP_PORT", "8002"))
    mcp.run(transport="streamable-http", port=port)
