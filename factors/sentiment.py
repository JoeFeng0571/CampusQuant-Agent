"""
factors/sentiment.py — 情绪因子（接口占位）

完整的情绪因子需要对财联社新闻做逐日情绪打分，涉及独立的 NLP 流程。
当前模块只提供：

    1. 接口约定（`compute_news_sentiment`）
    2. 换手率因子（流动性/情绪代理）

完整 NLP 管线（FinBERT 或大模型打分 → 日度聚合）留待后续扩展。
"""
from __future__ import annotations

import pandas as pd


def compute_turnover_ratio(
    volume: pd.DataFrame,
    shares_outstanding: pd.DataFrame,
    window: int = 20,
) -> pd.DataFrame:
    """换手率 = 成交量 / 流通股数，滚动平均。

    用作情绪/流动性的代理。高换手率 = 活跃/关注度高，
    但在 A 股通常是**负向因子**（过度关注的股票后续跑输）。
    """
    turnover = volume / shares_outstanding
    return turnover.rolling(window=window, min_periods=window // 2).mean()


def compute_news_sentiment(
    news_scores: pd.DataFrame,
    window: int = 5,
) -> pd.DataFrame:
    """基于预打分的新闻情绪滚动均值。

    Args:
        news_scores: DataFrame, index=date, columns=symbols, values ∈ [-1, +1]
                     **调用方负责产生打分**（调用 FinBERT / LLM / 词典等）
        window: 滚动平均窗口（日），默认 5 日

    Returns:
        DataFrame 同结构，经滚动平滑降噪
    """
    return news_scores.rolling(window=window, min_periods=1).mean()
