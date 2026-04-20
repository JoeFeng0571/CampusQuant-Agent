"""
factors/ic_analyzer.py — 因子 IC/IR 分析

IC (Information Coefficient) 与 IR (Information Ratio) 是量化选股的核心评估指标。

定义：

    日度 IC_t = Spearman_rho(factor_panel[t], forward_return_panel[t])
              = rank_corr( 因子横截面, 下期收益横截面 )

    IC_IR = mean(IC_t) / std(IC_t)
          类似夏普比率的思想：衡量因子"单位波动"能产生多少预测力

    IC 胜率 = P(IC_t > 0)
            ≥ 55% 视为稳定有效因子

经验解读：
    |IC| 均值 > 0.03, IC_IR > 0.5 → 有实用价值
    |IC| 均值 > 0.05, IC_IR > 1.0 → 强因子
    IC_IR < 0.2 → 风险 >> 收益，不值得用
"""
from __future__ import annotations

from typing import Iterable, Optional

import numpy as np
import pandas as pd


def _align_panels(
    factor: pd.DataFrame, forward_ret: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """对齐两个面板的 index 和 columns。"""
    idx = factor.index.intersection(forward_ret.index)
    cols = factor.columns.intersection(forward_ret.columns)
    return factor.loc[idx, cols], forward_ret.loc[idx, cols]


def rank_ic(
    factor_panel: pd.DataFrame,
    forward_return_panel: pd.DataFrame,
    min_coverage: int = 3,
) -> pd.Series:
    """每期横截面秩相关系数（Spearman rank IC）。

    Args:
        factor_panel: DataFrame, index=date, columns=symbols, values=因子值
        forward_return_panel: 同结构，values=未来 N 日收益
        min_coverage: 当日横截面至少多少只股有数据才计算 IC，否则置 NaN

    Returns:
        pd.Series，index=date，values=日度 rank IC
    """
    f, r = _align_panels(factor_panel, forward_return_panel)
    ic = pd.Series(index=f.index, dtype=float)

    for dt in f.index:
        fv = f.loc[dt]
        rv = r.loc[dt]
        # 两边都非 NaN 的股票才参与
        valid = fv.notna() & rv.notna()
        if valid.sum() < min_coverage:
            ic.loc[dt] = np.nan
            continue
        # Spearman: 先排名再算 Pearson
        fr = fv[valid].rank()
        rr = rv[valid].rank()
        if fr.std() < 1e-12 or rr.std() < 1e-12:
            ic.loc[dt] = np.nan
            continue
        ic.loc[dt] = float(fr.corr(rr))
    return ic


def ic_ir(ic_series: pd.Series) -> float:
    """IC_IR = mean(IC) / std(IC)。"""
    clean = ic_series.dropna()
    if len(clean) < 2 or clean.std() < 1e-12:
        return 0.0
    return float(clean.mean() / clean.std())


def ic_win_rate(ic_series: pd.Series) -> float:
    """IC 胜率 = P(IC > 0)。"""
    clean = ic_series.dropna()
    if len(clean) == 0:
        return 0.0
    return float((clean > 0).mean())


def ic_decay(
    factor_panel: pd.DataFrame,
    price_panel: pd.DataFrame,
    horizons: Iterable[int] = (1, 5, 10, 20),
    min_coverage: int = 3,
) -> pd.DataFrame:
    """IC 衰减曲线：不同前向持有期下的 IC_IR / IC 均值 / 胜率。

    Args:
        factor_panel: 因子面板
        price_panel: 价格面板（用于计算 forward return）
        horizons: 持有期列表（日），默认 (1, 5, 10, 20)

    Returns:
        DataFrame, index=horizon, columns=['ic_mean', 'ic_std', 'ic_ir', 'win_rate', 'n_obs']
    """
    rows = []
    for h in horizons:
        # forward_return: 从 t 持有到 t+h 的收益 = (price[t+h] / price[t] - 1)
        fwd = price_panel.pct_change(fill_method=None, periods=h).shift(-h)
        ic = rank_ic(factor_panel, fwd, min_coverage=min_coverage)
        clean = ic.dropna()
        rows.append({
            "horizon": h,
            "ic_mean": float(clean.mean()) if len(clean) else 0.0,
            "ic_std":  float(clean.std())  if len(clean) > 1 else 0.0,
            "ic_ir":   ic_ir(ic),
            "win_rate": ic_win_rate(ic),
            "n_obs":   int(len(clean)),
        })
    return pd.DataFrame(rows).set_index("horizon")


def summarize_ic(
    factor_panel: pd.DataFrame,
    price_panel: pd.DataFrame,
    forward_horizon: int = 20,
    decay_horizons: Iterable[int] = (1, 5, 10, 20),
    min_coverage: int = 3,
) -> dict:
    """一次性生成因子的完整 IC 报告。

    Returns:
        {
            "ic_series":  pd.Series     # 主 horizon 的 IC 时间序列
            "ic_mean":    float
            "ic_std":     float
            "ic_ir":      float
            "win_rate":   float
            "t_stat":     float          # IC 均值的 t 检验统计量
            "decay":      pd.DataFrame  # 多 horizon 衰减
            "n_periods":  int
        }
    """
    fwd = price_panel.pct_change(fill_method=None, periods=forward_horizon).shift(-forward_horizon)
    ic_series = rank_ic(factor_panel, fwd, min_coverage=min_coverage)
    clean = ic_series.dropna()

    if len(clean) >= 2 and clean.std() > 1e-12:
        t_stat = float(clean.mean() / (clean.std() / np.sqrt(len(clean))))
    else:
        t_stat = 0.0

    decay = ic_decay(factor_panel, price_panel, horizons=decay_horizons,
                      min_coverage=min_coverage)

    return {
        "ic_series": ic_series,
        "ic_mean": float(clean.mean()) if len(clean) else 0.0,
        "ic_std":  float(clean.std())  if len(clean) > 1 else 0.0,
        "ic_ir":   ic_ir(ic_series),
        "win_rate": ic_win_rate(ic_series),
        "t_stat":  t_stat,
        "decay":   decay,
        "n_periods": int(len(clean)),
    }
