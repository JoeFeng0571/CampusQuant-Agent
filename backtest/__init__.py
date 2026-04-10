"""
backtest/ — CampusQuant 回测引擎

升级计划 §5.2 W2: 让"AI 能选股"从吹牛变成 Sharpe 数字。

架构:
  engine.py     — 向量化回测核心循环
  metrics.py    — Sharpe / max_dd / CAGR / Sortino
  strategies/   — 策略接口 + CQ agent 策略
  report.py     — HTML 回测报告
  cli.py        — python -m backtest.run
"""
