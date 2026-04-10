"""
CQ-Bench — CampusQuant Agent Evaluation Framework

Goal: 让 AI 输出质量从"感觉"变成"数字"。

Architecture:
  bench/
  ├── schema.py           Case / Output / Score 数据模型
  ├── datasets/           *.jsonl 评测数据集
  ├── runners/            能跑一个 case 输出 agent 结果的 runner
  ├── judges/             LLM-as-judge 评分器 + 指标聚合
  ├── results/            每次运行的结果（自动创建）
  ├── report.py           生成 HTML 报告
  └── run.py              CLI 入口
"""

__version__ = "0.1.0"
