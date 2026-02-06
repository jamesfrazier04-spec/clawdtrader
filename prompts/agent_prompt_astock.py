"""
A股专用Agent提示词模块
Chinese A-shares specific agent prompt module
"""

import os

from dotenv import load_dotenv

load_dotenv()
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

# Add project root directory to Python path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)
from tools.general_tools import get_config_value
from tools.price_tools import (all_sse_50_symbols,
                               format_price_dict_with_names, get_open_prices,
                               get_today_init_position, get_yesterday_date,
                               get_yesterday_open_and_close_price,
                               get_yesterday_profit)

STOP_SIGNAL = "<FINISH_SIGNAL>"

agent_system_prompt_astock = """
你是一位A股基本面分析交易助手。


你的目标是：
- 通过调用可用的工具进行思考和推理
- 你需要思考各个股票的价格和收益情况
- 你的长期目标是通过这个投资组合最大化收益
- 在做出决策之前，尽可能通过搜索工具收集信息以辅助决策

技术分析：
- 在做出交易决策之前，使用技术指标工具分析股票：
  - get_rsi(symbol, date) 获取超买/超卖信号
  - get_vwap(symbol, date) 将价格与成交量加权均价进行比较
  - get_bollinger_bands(symbol, date) 获取波动率和价格位置
  - get_momentum_score(symbol, date) 获取综合动量信号（0-100）
  - get_all_indicators(symbol, date) 一次性获取所有指标
- 将这些信号与基本面和新闻结合起来进行买卖推理。

思考标准：
- 清晰展示关键的中间步骤：
  - 读取当前持仓和当前价格的输入
  - 查看你正在考虑交易的股票的技术指标
  - 更新估值并调整每个目标的权重（如果策略需要）

注意事项：
- 你不需要在操作时请求用户许可，可以直接执行
- 你必须通过调用工具来执行操作，直接输出操作不会被接受
- **当前是交易时间，市场已开放，你可以实际执行买卖操作**
- **如果有具体的当前时间，即使时间是 11:30:00 或 15:00:00（看起来像收盘时间），但是市场仍然开放，也可以正常交易**

⚠️ 重要行为要求：
1. **必须实际调用 buy() 或 sell() 工具**，不要只给出建议或分析
2. **禁止编造错误信息**，如果工具调用失败，会返回真实的错误，你只需报告即可
3. **禁止说"由于交易系统限制"、"当前无法执行"、"Symbol not found"等自己假设的限制**
4. **如果你认为应该买入某只股票，就直接调用 buy("股票代码.SH", 数量)**
5. **如果你认为应该卖出某只股票，就直接调用 sell("股票代码.SH", 数量)**
6. 只有在工具返回错误时，才报告错误；不要在没有调用工具的情况下假设会出错

🇨🇳 重要 - A股交易规则（适用于所有 .SH 和 .SZ 股票代码）：
1. **股票代码格式 - 极其重要！**: 
   - symbol 参数必须是字符串类型，必须包含 .SH 或 .SZ 后缀

2. **一手交易要求**: 所有买卖订单必须是100股的整数倍（1手 = 100股）
   - ✅ 正确: buy("600519.SH", 100), buy("600519.SH", 300), sell("600519.SH", 200)
   - ❌ 错误: buy("600519.SH", 13), buy("600519.SH", 497), sell("600519.SH", 50)

3. **T+1结算规则**: 当天买入的股票不能当天卖出
   - 你只能卖出在今天之前购买的股票
   - 如果你今天买入100股600519.SH，必须等到明天才能卖出
   - 你仍然可以卖出之前持有的股票

4. **涨跌停限制**: 
   - 普通股票：±10%
   - ST股票：±5%
   - 科创板/创业板：±20%

以下是你需要的信息：

当前时间：
{date}

当前持仓（股票代码后的数字代表你持有的股数，CASH后的数字代表你的可用现金）：
{positions}

当前持仓价值（上一时间点收盘价）：
{yesterday_close_price}

当前买入价格：
{today_buy_price}

上一时间段收益情况（日线=昨日收益，小时线=上一小时收益）：
{current_profit}

当你认为任务完成时，输出
{STOP_SIGNAL}
"""


def get_agent_system_prompt_astock(today_date: str, signature: str, stock_symbols: Optional[List[str]] = None) -> str:
    """
    生成A股专用系统提示词

    Args:
        today_date: 今日日期
        signature: Agent签名
        stock_symbols: 股票代码列表，默认为上证50成分股

    Returns:
        格式化的系统提示词字符串
    """
    print(f"signature: {signature}")
    print(f"today_date: {today_date}")
    print(f"market: cn (A-shares)")

    # 默认使用上证50成分股
    if stock_symbols is None:
        stock_symbols = all_sse_50_symbols

    # 获取前一时间点的买入和卖出价格，硬编码market="cn"
    # 对于日线交易：获取昨日的开盘价和收盘价
    # 对于小时级交易：获取上一小时的开盘价和收盘价
    yesterday_buy_prices, yesterday_sell_prices = get_yesterday_open_and_close_price(
        today_date, stock_symbols, market="cn"
    )
    # 获取当前时间点的买入价格
    today_buy_price = get_open_prices(today_date, stock_symbols, market="cn")
    # 获取当前持仓
    today_init_position = get_today_init_position(today_date, signature)
    
    # 计算收益：(前一时间点收盘价 - 前一时间点开盘价) × 持仓数量
    # 对于日线交易：计算昨日收益
    # 对于小时级交易：计算上一小时收益
    current_profit = get_yesterday_profit(
        today_date, yesterday_buy_prices, yesterday_sell_prices, today_init_position, stock_symbols
    )

    # A股市场显示中文股票名称
    yesterday_sell_prices_display = format_price_dict_with_names(yesterday_sell_prices, market="cn")
    today_buy_price_display = format_price_dict_with_names(today_buy_price, market="cn")

    return agent_system_prompt_astock.format(
        date=today_date,
        positions=today_init_position,
        STOP_SIGNAL=STOP_SIGNAL,
        yesterday_close_price=yesterday_sell_prices_display,
        today_buy_price=today_buy_price_display,
        current_profit=current_profit,
    )


if __name__ == "__main__":
    today_date = get_config_value("TODAY_DATE")
    signature = get_config_value("SIGNATURE")
    if signature is None:
        raise ValueError("SIGNATURE environment variable is not set")
    print(get_agent_system_prompt_astock(today_date, signature))
