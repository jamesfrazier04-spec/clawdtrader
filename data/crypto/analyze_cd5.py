#!/usr/bin/env python3
import json
import numpy as np
import sys
from pathlib import Path

# 添加项目根目录到路径，以便导入result_tools
project_root = Path(__file__).resolve().parents[2]  # data/crypto -> Clawdbot Trader
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from tools.result_tools import (
    calculate_daily_returns, calculate_sharpe_ratio, calculate_max_drawdown,
    calculate_cumulative_return, calculate_volatility, calculate_win_rate
)

# 读取CD5指数数据
with open('CD5_crypto_index.json', 'r') as f:
    data = json.load(f)

time_series = data['Time Series (Daily)']
dates = sorted(time_series.keys())

# 过滤掉11-01的数据，从11-02开始，与agent模拟时间保持一致
agent_start_date = "2025-11-02"
if agent_start_date in dates:
    start_index = dates.index(agent_start_date)
    dates = dates[start_index:]
    print(f'⚠️ 时间对齐: 跳过11-01，从{agent_start_date}开始计算，与agent模拟保持一致')
else:
    print(f'⚠️ 未找到{agent_start_date}数据，使用全部可用数据')

print('=== CD5指数数据分析 (与Agent时间对齐) ===')
print(f'数据日期范围: {dates[0]} 到 {dates[-1]}')
print(f'总交易日数: {len(dates)}')

# 计算CD5指数表现 (与result_tools.py保持一致，使用收盘价)
# 构建组合价值字典 (与result_tools.py格式一致)
portfolio_values = {}
for date in dates:
    portfolio_values[date] = float(time_series[date]['4. close'])

initial_value = portfolio_values[dates[0]]  # 使用第一天的收盘价，与result_tools.py一致
final_value = portfolio_values[dates[-1]]  # 使用最后一天的收盘价

print(f'初始价值: ${initial_value:,.2f}')
print(f'最终价值: ${final_value:,.2f}')
print(f'价值变化: ${final_value - initial_value:,.2f}')

# 使用result_tools.py的函数计算指标，确保完全一致
from datetime import datetime

# 计算各项指标 (与result_tools.py保持完全一致)
daily_returns = calculate_daily_returns(portfolio_values)
volatility = calculate_volatility(daily_returns, trading_days=365)  # 加密货币365天
win_rate = calculate_win_rate(daily_returns)
sharpe_ratio = calculate_sharpe_ratio(daily_returns, trading_days=365)  # 加密货币365天
max_drawdown, drawdown_start, drawdown_end = calculate_max_drawdown(portfolio_values)

# 使用result_tools.py的累计收益率函数确保一致性
cumulative_return = calculate_cumulative_return(portfolio_values)
print(f'累计收益率: {cumulative_return:.2%} (使用result_tools.py计算)')

# 计算年化收益率
start_date = datetime.strptime(dates[0], "%Y-%m-%d")
end_date = datetime.strptime(dates[-1], "%Y-%m-%d")
days = (end_date - start_date).days

if days > 0:
    annualized_return = (1 + cumulative_return) ** (365 / days) - 1
else:
    annualized_return = 0.0

print(f'年化收益率: {annualized_return:.2%}')
print(f'投资天数: {days}天')
print(f'最大回撤: {max_drawdown:.2%}')
print(f'回撤期间: {drawdown_start} 到 {drawdown_end}')
print(f'年化波动率: {volatility:.2%}')
print(f'夏普比率: {sharpe_ratio:.4f}')
print(f'胜率: {win_rate:.2%}')

# 为了兼容性，保留原有的变量名
daily_volatility = np.std(daily_returns, ddof=1) if daily_returns else 0.0
mean_return = np.mean(daily_returns) if daily_returns else 0.0
annualized_return_for_sharpe = mean_return * 365
risk_free_rate = 0.02

# portfolio_values 已经在上面构建了，无需重复

# 输出用于报告的数据
print(f'\n=== 用于报告的数据 ===')
print(f'CD5指数:')
print(f'  累计收益率: {cumulative_return:.2%}')
print(f'  年化收益率: {annualized_return:.2%}')
print(f'  夏普比率: {sharpe_ratio:.4f}')
print(f'  最大回撤: {max_drawdown:.2%}')
print(f'  胜率: {win_rate:.2%}')
print(f'  最终价值: ${final_value:,.0f}')

# 保存CD5结果到JSON文件
save_cd5_results = True
if save_cd5_results:
    from datetime import datetime
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = f'CD5_metrics_{timestamp}.json'

    cd5_results = {
        "evaluation_time": datetime.now().isoformat(),
        "model_name": "CD5指数",
        "market": "crypto",
        "trading_days": len(dates),
        "start_date": dates[0],
        "end_date": dates[-1],
        "initial_value": initial_value,
        "final_value": final_value,
        "value_change": final_value - initial_value,
        "cumulative_return": round(cumulative_return, 4),
        "annualized_return": round(annualized_return, 4),
        "sharpe_ratio": round(sharpe_ratio, 4),
        "max_drawdown": round(max_drawdown, 4),
        "max_drawdown_start": drawdown_start,
        "max_drawdown_end": drawdown_end,
        "volatility": round(volatility, 4),
        "win_rate": round(win_rate, 4),
        "trading_days_with_data": len(daily_returns),
        "investment_days": days,
        "daily_returns_count": len(daily_returns),
        "daily_volatility": round(daily_volatility, 6),
        "mean_daily_return": round(mean_return, 6),
        "annualized_return_for_sharpe": round(annualized_return_for_sharpe, 4),
        "risk_free_rate": risk_free_rate,
        "trading_days_per_year": 365,  # 加密货币365天交易
        "cd5_composition": {
            "BTC": 74.56,
            "ETH": 15.97,
            "XRP": 5.20,
            "SOL": 3.53,
            "ADA": 0.76
        },
        "notes": "CD5指数基准，使用365天交易计算年化指标"
    }

    # 保存详细结果
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(cd5_results, f, indent=2, ensure_ascii=False)

    print(f'\n💾 CD5指标已保存到: {output_file}')

    # 同时保存一个固定名称的最新结果文件
    latest_file = 'CD5_latest_metrics.json'
    with open(latest_file, 'w', encoding='utf-8') as f:
        json.dump(cd5_results, f, indent=2, ensure_ascii=False)

    print(f'💾 最新CD5指标已保存到: {latest_file}')

    # 生成可用于报告的简化数据
    report_data = {
        "model_name": "CD5指数",
        "status": "✅ 基准",
        "trading_days": len(dates),
        "start_date": dates[0],
        "end_date": dates[-1],
        "cumulative_return": round(cumulative_return, 4),
        "annualized_return": round(annualized_return, 4),
        "sharpe_ratio": round(sharpe_ratio, 4),
        "max_drawdown": round(max_drawdown, 4),
        "volatility": round(volatility, 4),
        "win_rate": round(win_rate, 4),
        "initial_value": initial_value,
        "final_value": final_value,
        "value_change": final_value - initial_value,
        "value_change_percent": round(cumulative_return, 4),
        "is_benchmark": True
    }

    # 保存简化版本用于模型对比
    report_file = 'CD5_for_comparison.json'
    with open(report_file, 'w', encoding='utf-8') as f:
        json.dump(report_data, f, indent=2, ensure_ascii=False)

    print(f'💾 对比用CD5数据已保存到: {report_file}')
else:
    print('\n⚠️ CD5结果保存功能已禁用')