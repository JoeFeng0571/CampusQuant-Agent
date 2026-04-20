"""
factors/combine.py — 因子正交化与合成

多因子投资的两个核心环节：

1. **正交化**：把相关性高的因子拆成独立信号
   施密特正交（Gram-Schmidt）：保留主因子，后续因子减去对前序因子的回归残差

2. **合成**：把多个因子打分合成一个综合打分
   三种权重方案：
       - 等权（最稳健，无参数估计风险）
       - IC 加权（信号越强权重越大）
       - IC_IR 加权（同时考虑信号强度和稳定性）
"""
from __future__ import annotations

from typing import Literal

import numpy as np
import pandas as pd


def _standardize(panel: pd.DataFrame) -> pd.DataFrame:
    """横截面标准化：每日减均值除标准差，消除量纲差异。"""
    mean = panel.mean(axis=1)
    std = panel.std(axis=1)
    return panel.sub(mean, axis=0).div(std.replace(0, np.nan), axis=0)


def orthogonalize(
    panels: list[pd.DataFrame],
    names: list[str] | None = None,
) -> dict[str, pd.DataFrame]:
    """施密特正交化多个因子面板。

    顺序：第 i 个因子减去对前 (i-1) 个因子的横截面 OLS 回归残差。

    每日独立做一次正交：
        f_i^⊥[t] = f_i[t] - X[t] · β_i[t]
    其中 X[t] = [f_0[t], ..., f_{i-1}[t]]，β_i[t] 是 OLS 回归系数。

    Args:
        panels: 因子面板列表，顺序决定正交主导关系（第一个保留完整）
        names: 因子名称，输出 dict 的 key；不传则用 f_0/f_1/...

    Returns:
        {name: orthogonalized_panel}，与输入同顺序
    """
    if not panels:
        return {}
    names = names or [f"f_{i}" for i in range(len(panels))]
    if len(names) != len(panels):
        raise ValueError("names length must match panels length")

    # 先全部横截面标准化，否则残差计算受量纲影响
    std_panels = [_standardize(p) for p in panels]

    out: dict[str, pd.DataFrame] = {names[0]: std_panels[0].copy()}
    running: list[pd.DataFrame] = [std_panels[0]]

    for i in range(1, len(panels)):
        target = std_panels[i]
        residual = target.copy()

        # 每日独立回归：target[t, :] vs [running[0][t, :], ..., running[i-1][t, :]]
        for dt in target.index:
            y = target.loc[dt].values.astype(float)
            # 构造 X: shape (n_stocks, n_prev_factors)
            X_cols = [p.loc[dt].values.astype(float) if dt in p.index else np.full_like(y, np.nan)
                      for p in running]
            X = np.column_stack(X_cols)

            # 同时非 NaN 的股票才参与
            mask = ~np.isnan(y) & ~np.any(np.isnan(X), axis=1)
            if mask.sum() < X.shape[1] + 2:
                # 样本不足，保留原始值
                continue

            X_valid = X[mask]
            y_valid = y[mask]
            # OLS: beta = (X'X)^-1 X'y
            try:
                beta, *_ = np.linalg.lstsq(X_valid, y_valid, rcond=None)
                predicted = X_valid @ beta
                resid_full = y.copy()
                resid_full[mask] = y_valid - predicted
                residual.loc[dt] = resid_full
            except np.linalg.LinAlgError:
                continue

        out[names[i]] = residual
        running.append(residual)

    return out


def combine_factors(
    panels: dict[str, pd.DataFrame],
    weights: dict[str, float] | Literal["equal"] = "equal",
) -> pd.DataFrame:
    """把多个因子面板合成一个综合打分面板。

    步骤：
        1. 每个因子横截面标准化（z-score）
        2. 按权重加权求和
        3. 再做一次横截面标准化（方便下游做分组回测）

    Args:
        panels: {name: panel} 因子面板字典
        weights: {name: weight} 或 "equal"（等权）

    Returns:
        合成后的因子面板
    """
    if not panels:
        raise ValueError("no factor panels provided")

    if weights == "equal":
        weights = {k: 1.0 / len(panels) for k in panels}
    missing = set(panels) - set(weights)
    if missing:
        raise ValueError(f"weights missing for factors: {missing}")

    total_w = sum(weights.values())
    if abs(total_w) < 1e-12:
        raise ValueError("weights sum to zero")
    weights = {k: v / total_w for k, v in weights.items()}

    stacked: pd.DataFrame | None = None
    for name, panel in panels.items():
        z = _standardize(panel)
        w = weights[name]
        if stacked is None:
            stacked = z * w
        else:
            stacked = stacked.add(z * w, fill_value=0.0)

    return _standardize(stacked)


def ic_weighted(
    panels: dict[str, pd.DataFrame],
    ic_stats: dict[str, float],
) -> pd.DataFrame:
    """IC 加权合成 —— 权重 ∝ |IC|。

    使用因子自身历史 |IC| 作为权重。符号通过 sign(IC) 处理，
    保证因子方向统一。
    """
    weights = {
        name: abs(ic_stats.get(name, 0.0))
        * (1.0 if ic_stats.get(name, 0.0) >= 0 else -1.0)
        for name in panels
    }
    total = sum(abs(w) for w in weights.values())
    if total < 1e-12:
        return combine_factors(panels, weights="equal")
    weights = {k: v / total for k, v in weights.items()}
    return combine_factors(panels, weights=weights)


def ic_ir_weighted(
    panels: dict[str, pd.DataFrame],
    ic_ir_stats: dict[str, float],
) -> pd.DataFrame:
    """IC_IR 加权合成 —— 权重 ∝ IC_IR。

    IC_IR 同时考虑信号强度和稳定性，是因子选择里最常用的加权方式。
    """
    weights = dict(ic_ir_stats)
    total = sum(abs(w) for w in weights.values())
    if total < 1e-12:
        return combine_factors(panels, weights="equal")
    weights = {k: v / total for k, v in weights.items()}
    return combine_factors(panels, weights=weights)
