"""
eval/calibration.py — 置信度校准核心算法

本模块提供评估与再校准两套工具：

**评估指标**（`y_true ∈ {0,1}`, `y_prob ∈ [0,1]`）：
    - Brier Score = E[(y_prob - y_true)²]                  越小越好，上限 1
    - ECE (Expected Calibration Error)                      加权偏差（按分箱样本数）
    - MCE (Maximum Calibration Error)                       最坏分箱的偏差
    - Reliability Diagram                                   每个分箱的 (confidence, accuracy)

**校准器**（统一接口 fit/transform）：
    - PlattScaler           — sigmoid(A·logit(p) + B)，参数化最少，适合样本量少
    - IsotonicCalibrator    — 保序回归（Pool Adjacent Violators），非参数最灵活
    - HistogramBinning      — 简单分箱频率，离散但极稳健

CampusQuant 场景：
    Agent 输出的 `confidence ∈ [0,1]` 是主观先验，需要用历史"预测 vs 实际"对
    训练一个校准器，得到 `confidence_calibrated` 作为贝叶斯权重用于 BL 组合优化
    或 Risk Node 的仓位决策。

参考：
    Brier (1950), "Verification of Forecasts Expressed in Terms of Probability"
    Platt (1999), "Probabilistic Outputs for Support Vector Machines..."
    Zadrozny & Elkan (2002), "Transforming Classifier Scores into Accurate Probability Estimates"
    Guo et al. (2017), "On Calibration of Modern Neural Networks"
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd
from scipy.optimize import minimize


# ══════════════════════════════════════════════════════════════
# 评估指标
# ══════════════════════════════════════════════════════════════

def _check_inputs(y_true: np.ndarray, y_prob: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    y_true = np.asarray(y_true, dtype=float).reshape(-1)
    y_prob = np.asarray(y_prob, dtype=float).reshape(-1)
    if len(y_true) != len(y_prob):
        raise ValueError(f"length mismatch: y_true={len(y_true)}, y_prob={len(y_prob)}")
    if len(y_true) == 0:
        raise ValueError("empty input")
    unique = np.unique(y_true)
    if not np.all(np.isin(unique, [0.0, 1.0])):
        raise ValueError(f"y_true must be binary (0/1), got unique values {unique}")
    if not np.all((y_prob >= 0.0) & (y_prob <= 1.0)):
        raise ValueError("y_prob must be in [0, 1]")
    return y_true, y_prob


def brier_score(y_true: np.ndarray, y_prob: np.ndarray) -> float:
    """Brier Score = mean((y_prob - y_true)²)。

    解读：
        0.00  完美预测
        0.25  随机猜（所有 p=0.5 且 base rate=0.5）
        1.00  最差（所有 p=1 但 y=0 或反之）

    Brier 同时考虑 refinement（分箱方差）和 reliability（分箱偏差），
    不像 ECE 只看 reliability。
    """
    y_true, y_prob = _check_inputs(y_true, y_prob)
    return float(np.mean((y_prob - y_true) ** 2))


def _bin_predictions(
    y_true: np.ndarray,
    y_prob: np.ndarray,
    n_bins: int = 10,
    strategy: str = "uniform",
) -> pd.DataFrame:
    """按预测概率分箱，每箱统计 avg_confidence / accuracy / count。

    Args:
        strategy: "uniform" = 均分 [0,1]； "quantile" = 等频分位
    """
    if strategy == "uniform":
        edges = np.linspace(0.0, 1.0, n_bins + 1)
    elif strategy == "quantile":
        edges = np.quantile(y_prob, np.linspace(0.0, 1.0, n_bins + 1))
        edges[0], edges[-1] = 0.0, 1.0
        edges = np.unique(edges)
    else:
        raise ValueError(f"unknown strategy: {strategy}")

    # np.digitize 用右开区间；idx=0 不可能（最小 edge=0），idx>n_bins 也不可能（最大 edge=1）
    idx = np.clip(np.digitize(y_prob, edges[1:-1], right=False), 0, len(edges) - 2)

    rows = []
    for b in range(len(edges) - 1):
        mask = idx == b
        if mask.sum() == 0:
            continue
        rows.append({
            "bin": b,
            "edge_lo": float(edges[b]),
            "edge_hi": float(edges[b + 1]),
            "avg_confidence": float(y_prob[mask].mean()),
            "accuracy":        float(y_true[mask].mean()),
            "count":            int(mask.sum()),
            "gap":             float(y_prob[mask].mean() - y_true[mask].mean()),
        })
    return pd.DataFrame(rows)


def reliability_diagram_bins(
    y_true: np.ndarray,
    y_prob: np.ndarray,
    n_bins: int = 10,
    strategy: str = "uniform",
) -> pd.DataFrame:
    """可靠性图所需的分箱数据。

    绘制时把 (avg_confidence, accuracy) 作为散点/折线，
    理想情况下与对角线 y=x 重合。

    返回 DataFrame，列：bin / edge_lo / edge_hi / avg_confidence / accuracy / count / gap
    """
    y_true, y_prob = _check_inputs(y_true, y_prob)
    return _bin_predictions(y_true, y_prob, n_bins=n_bins, strategy=strategy)


def expected_calibration_error(
    y_true: np.ndarray,
    y_prob: np.ndarray,
    n_bins: int = 10,
    strategy: str = "uniform",
) -> float:
    """ECE = Σ_b (|n_b|/N) · |accuracy_b - confidence_b|。

    经验阈值：
        < 0.05  校准良好
        0.05-0.10 可接受
        > 0.10  严重失调，建议再校准
    """
    y_true, y_prob = _check_inputs(y_true, y_prob)
    bins = _bin_predictions(y_true, y_prob, n_bins=n_bins, strategy=strategy)
    if bins.empty:
        return 0.0
    total = bins["count"].sum()
    return float((bins["count"] / total * bins["gap"].abs()).sum())


def maximum_calibration_error(
    y_true: np.ndarray,
    y_prob: np.ndarray,
    n_bins: int = 10,
    strategy: str = "uniform",
) -> float:
    """MCE = max_b |accuracy_b - confidence_b|。

    对最坏分箱敏感。在生产场景中，MCE < 0.15 通常可接受。
    """
    y_true, y_prob = _check_inputs(y_true, y_prob)
    bins = _bin_predictions(y_true, y_prob, n_bins=n_bins, strategy=strategy)
    return 0.0 if bins.empty else float(bins["gap"].abs().max())


# ══════════════════════════════════════════════════════════════
# 校准器基类
# ══════════════════════════════════════════════════════════════

@dataclass
class CalibratorBase:
    """所有校准器的公共接口。"""
    fitted: bool = field(default=False, init=False)

    def fit(self, y_true: np.ndarray, y_prob: np.ndarray) -> "CalibratorBase":
        raise NotImplementedError

    def transform(self, y_prob: np.ndarray) -> np.ndarray:
        raise NotImplementedError

    def fit_transform(self, y_true: np.ndarray, y_prob: np.ndarray) -> np.ndarray:
        return self.fit(y_true, y_prob).transform(y_prob)


# ══════════════════════════════════════════════════════════════
# 1. Platt Scaling — 两参数 sigmoid
# ══════════════════════════════════════════════════════════════

def _logit(p: np.ndarray, eps: float = 1e-7) -> np.ndarray:
    p = np.clip(p, eps, 1.0 - eps)
    return np.log(p / (1.0 - p))


def _sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-x))


@dataclass
class PlattScaler(CalibratorBase):
    """Platt Scaling：拟合 p_calibrated = sigmoid(A · logit(p_raw) + B)。

    优点：参数只有 2 个，小样本下稳定、不过拟合
    缺点：假设校准函数是 sigmoid 形式，对极端非单调失调无能为力

    损失函数使用 Platt 原论文的"平滑目标"以减轻过拟合：
        y_smoothed = (N_pos + 1) / (N_pos + 2)  for y=1
        y_smoothed = 1 / (N_neg + 2)           for y=0
    """
    A: float = field(default=1.0, init=False)
    B: float = field(default=0.0, init=False)

    def fit(self, y_true: np.ndarray, y_prob: np.ndarray) -> "PlattScaler":
        y_true, y_prob = _check_inputs(y_true, y_prob)

        # Platt 论文的平滑目标
        n_pos = int(y_true.sum())
        n_neg = int(len(y_true) - n_pos)
        if n_pos == 0 or n_neg == 0:
            # 退化：全 0 或全 1，用 identity
            self.A, self.B, self.fitted = 1.0, 0.0, True
            return self
        hi = (n_pos + 1.0) / (n_pos + 2.0)
        lo = 1.0 / (n_neg + 2.0)
        target = np.where(y_true > 0.5, hi, lo)

        logit_p = _logit(y_prob)

        def neg_log_lik(params: np.ndarray) -> float:
            A, B = params
            q = _sigmoid(A * logit_p + B)
            q = np.clip(q, 1e-12, 1.0 - 1e-12)
            return -float(np.mean(target * np.log(q) + (1 - target) * np.log(1 - q)))

        result = minimize(
            neg_log_lik, x0=np.array([1.0, 0.0]),
            method="L-BFGS-B",
            options={"maxiter": 200},
        )
        self.A, self.B = float(result.x[0]), float(result.x[1])
        self.fitted = True
        return self

    def transform(self, y_prob: np.ndarray) -> np.ndarray:
        if not self.fitted:
            raise RuntimeError("PlattScaler not fitted")
        y_prob = np.asarray(y_prob, dtype=float)
        return _sigmoid(self.A * _logit(y_prob) + self.B)


# ══════════════════════════════════════════════════════════════
# 2. Isotonic Calibration — Pool Adjacent Violators
# ══════════════════════════════════════════════════════════════

def _pool_adjacent_violators(y_sorted: np.ndarray) -> np.ndarray:
    """Pool Adjacent Violators 算法：产生非递减序列。

    输入：按某 x 轴排序后的 y 值
    输出：同长度的非递减序列，是在最小二乘意义下最接近原序列的单调递增近似
    复杂度：O(n)
    """
    y = y_sorted.astype(float).copy()
    n = len(y)
    # 使用 stack 存每个块 (start, end, mean, weight)
    # 简单实现：逐元素合并
    weights = np.ones(n, dtype=float)
    values = y.copy()

    # 不断合并违反单调的相邻块
    i = 0
    while i < len(values) - 1:
        if values[i] > values[i + 1] + 1e-12:
            # 合并 i 与 i+1
            total_w = weights[i] + weights[i + 1]
            merged_val = (values[i] * weights[i] + values[i + 1] * weights[i + 1]) / total_w
            values[i] = merged_val
            weights[i] = total_w
            # 删除 i+1
            values = np.delete(values, i + 1)
            weights = np.delete(weights, i + 1)
            # 合并后回退，检查与左侧是否仍满足单调
            if i > 0:
                i -= 1
        else:
            i += 1

    # 把压缩后的每个块展开回原长度
    out = np.zeros(n)
    idx = 0
    for val, w in zip(values, weights):
        w_int = int(round(w))
        out[idx:idx + w_int] = val
        idx += w_int
    return out


@dataclass
class IsotonicCalibrator(CalibratorBase):
    """保序回归校准：非参数单调拟合，比 Platt 更灵活。

    步骤：
        1. 把 (y_prob, y_true) 按 y_prob 排序
        2. 对排序后的 y_true 跑 Pool Adjacent Violators
        3. 预测时用排序后的 y_prob → 校准值的插值

    优点：对非 sigmoid 形式的失调也能拟合
    缺点：样本量少时台阶明显，容易过拟合
    """
    _x_sorted: Optional[np.ndarray] = field(default=None, init=False)
    _y_iso:    Optional[np.ndarray] = field(default=None, init=False)

    def fit(self, y_true: np.ndarray, y_prob: np.ndarray) -> "IsotonicCalibrator":
        y_true, y_prob = _check_inputs(y_true, y_prob)
        order = np.argsort(y_prob)
        x_sorted = y_prob[order]
        y_sorted = y_true[order]
        y_iso = _pool_adjacent_violators(y_sorted)
        self._x_sorted = x_sorted
        self._y_iso = y_iso
        self.fitted = True
        return self

    def transform(self, y_prob: np.ndarray) -> np.ndarray:
        if not self.fitted or self._x_sorted is None:
            raise RuntimeError("IsotonicCalibrator not fitted")
        y_prob = np.asarray(y_prob, dtype=float)
        # 线性插值；越界时用端点值
        return np.interp(y_prob, self._x_sorted, self._y_iso,
                         left=float(self._y_iso[0]),
                         right=float(self._y_iso[-1]))


# ══════════════════════════════════════════════════════════════
# 3. Histogram Binning — 简单分箱频率
# ══════════════════════════════════════════════════════════════

@dataclass
class HistogramBinning(CalibratorBase):
    """分箱频率校准：每个分箱内用实际命中率替代预测概率。

    最朴素但最稳健的方法，工程上作为基线。
    """
    n_bins: int = 10
    strategy: str = "uniform"
    _edges: Optional[np.ndarray] = field(default=None, init=False)
    _bin_accuracy: Optional[np.ndarray] = field(default=None, init=False)

    def fit(self, y_true: np.ndarray, y_prob: np.ndarray) -> "HistogramBinning":
        y_true, y_prob = _check_inputs(y_true, y_prob)
        if self.strategy == "uniform":
            edges = np.linspace(0.0, 1.0, self.n_bins + 1)
        else:
            edges = np.quantile(y_prob, np.linspace(0.0, 1.0, self.n_bins + 1))
            edges[0], edges[-1] = 0.0, 1.0
            edges = np.unique(edges)

        idx = np.clip(np.digitize(y_prob, edges[1:-1], right=False),
                      0, len(edges) - 2)

        n_bins_actual = len(edges) - 1
        accuracy = np.zeros(n_bins_actual)
        for b in range(n_bins_actual):
            mask = idx == b
            if mask.sum() == 0:
                # 空箱：用箱中点作为兜底，避免 NaN
                accuracy[b] = (edges[b] + edges[b + 1]) / 2.0
            else:
                accuracy[b] = y_true[mask].mean()

        self._edges = edges
        self._bin_accuracy = accuracy
        self.fitted = True
        return self

    def transform(self, y_prob: np.ndarray) -> np.ndarray:
        if not self.fitted or self._edges is None:
            raise RuntimeError("HistogramBinning not fitted")
        y_prob = np.asarray(y_prob, dtype=float)
        idx = np.clip(np.digitize(y_prob, self._edges[1:-1], right=False),
                      0, len(self._edges) - 2)
        return self._bin_accuracy[idx]


# ══════════════════════════════════════════════════════════════
# 综合报告
# ══════════════════════════════════════════════════════════════

def summarize_calibration(
    y_true: np.ndarray,
    y_prob: np.ndarray,
    n_bins: int = 10,
    strategy: str = "uniform",
) -> dict:
    """一次性产出 Brier / ECE / MCE / 可靠性图分箱数据。

    Returns:
        {
            "n":       样本数
            "base_rate": y_true 的平均
            "mean_prob": y_prob 的平均（若与 base_rate 差距大说明整体偏差明显）
            "brier":   Brier Score
            "ece":     Expected Calibration Error
            "mce":     Maximum Calibration Error
            "reliability_bins": DataFrame
        }
    """
    y_true, y_prob = _check_inputs(y_true, y_prob)
    return {
        "n":          int(len(y_true)),
        "base_rate":  float(y_true.mean()),
        "mean_prob":  float(y_prob.mean()),
        "brier":      brier_score(y_true, y_prob),
        "ece":        expected_calibration_error(y_true, y_prob, n_bins, strategy),
        "mce":        maximum_calibration_error(y_true, y_prob, n_bins, strategy),
        "reliability_bins": reliability_diagram_bins(y_true, y_prob, n_bins, strategy),
    }
