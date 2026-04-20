"""
portfolio/optimizer.py — 组合优化核心算法

本模块实现三种经典组合优化方法：

1. Markowitz 均值方差（`markowitz_optimize`）
       最大化 U(w) = w'μ − (λ/2) · w'Σw
       s.t.  sum(w) = 1,  lb ≤ w_i ≤ ub,  Aw ≤ b

2. 风险平价（`risk_parity_optimize`）
       使 RC_i = w_i · (Σw)_i / sqrt(w'Σw)  对所有 i 相等
       通过最小化对数风险贡献的方差求解

3. Black-Litterman（`black_litterman_optimize`）
       合成市场均衡先验 π 与投资者观点 (P, Q, Ω)：
           μ_BL = [(τΣ)^{-1} + P'Ω^{-1}P]^{-1} [(τΣ)^{-1}π + P'Ω^{-1}Q]
       得到后验收益后，再走 Markowitz 得到最终权重

CampusQuant 特色：在 `black_litterman_optimize` 中，多 Agent 的 recommendation
与 confidence 直接映射为 (P, Q, Ω)：
    - recommendation ∈ {BUY, HOLD, SELL} → Q 的方向与幅度
    - confidence ∈ [0, 1]                → Ω 对角元（低置信 = 大不确定度）

所有优化都构造成凸二次规划（Markowitz / BL）或可用 SLSQP 解的非线性规划
（Risk Parity），无需 cvxpy 等重依赖，仅用 numpy + scipy.optimize 即可。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Literal, Optional

import numpy as np
from scipy.optimize import minimize

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════
# 数据结构
# ══════════════════════════════════════════════════════════════

@dataclass
class PortfolioConstraints:
    """组合约束。全部为年化意义下。

    Attributes:
        weight_bounds: 单资产权重上下限 (lb, ub)，默认 (0, 0.5) 即禁止卖空且单标的 ≤50%
                       提示：ub × n_assets 必须 ≥ 1，否则约束不可行
        sector_map: 每个资产的行业/板块标签，与资产顺序对齐
        sector_caps: {行业: 上限}，例如 {"科技": 0.50} 限制科技股累计 ≤50%
        min_weight: 若 >0，小于该阈值的仓位会在后处理阶段被置零并重新归一化
                    （避免输出一堆 0.001% 的"灰尘仓位"）
    """
    weight_bounds: tuple[float, float] = (0.0, 0.5)
    sector_map: Optional[list[str]] = None
    sector_caps: Optional[dict[str, float]] = None
    min_weight: float = 0.0


@dataclass
class OptimizationResult:
    """优化结果。

    Attributes:
        weights: 优化后的权重向量，sum=1
        method: 使用的优化方法名
        expected_return: 年化期望收益
        volatility: 年化波动率
        sharpe: 夏普比率（risk_free_rate=0 时等于 return/vol）
        risk_contributions: 各资产风险贡献度（RC_i，sum=volatility^2 / sqrt(variance)=vol）
        converged: 求解器是否收敛
        message: 求解器返回的消息
        metadata: 方法特定的附加信息（如 BL 的后验 μ_BL）
    """
    weights: np.ndarray
    method: str
    expected_return: float
    volatility: float
    sharpe: float
    risk_contributions: np.ndarray
    converged: bool
    message: str = ""
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """序列化为可 JSON 化的 dict。"""
        return {
            "weights": self.weights.tolist(),
            "method": self.method,
            "expected_return": float(self.expected_return),
            "volatility": float(self.volatility),
            "sharpe": float(self.sharpe),
            "risk_contributions": self.risk_contributions.tolist(),
            "converged": bool(self.converged),
            "message": self.message,
            "metadata": self.metadata,
        }


# ══════════════════════════════════════════════════════════════
# 公共工具
# ══════════════════════════════════════════════════════════════

def compute_portfolio_stats(
    weights: np.ndarray,
    expected_returns: np.ndarray,
    cov_matrix: np.ndarray,
    risk_free_rate: float = 0.0,
) -> tuple[float, float, float, np.ndarray]:
    """计算组合的年化期望收益、波动率、夏普比与各资产风险贡献。

    风险贡献（Euler allocation）：
        MRC_i = (Σw)_i                    # 边际风险贡献
        RC_i  = w_i · MRC_i / σ_p         # 各资产风险贡献，sum(RC_i) = σ_p

    Returns:
        (ret, vol, sharpe, risk_contributions)
    """
    w = np.asarray(weights, dtype=float).reshape(-1)
    mu = np.asarray(expected_returns, dtype=float).reshape(-1)
    cov = np.asarray(cov_matrix, dtype=float)

    ret = float(w @ mu)
    variance = float(w @ cov @ w)
    vol = float(np.sqrt(max(variance, 0.0)))
    sharpe = (ret - risk_free_rate) / vol if vol > 1e-12 else 0.0

    if vol > 1e-12:
        mrc = cov @ w
        rc = w * mrc / vol
    else:
        rc = np.zeros_like(w)

    return ret, vol, sharpe, rc


def estimate_covariance(
    returns: np.ndarray,
    shrinkage: float = 0.1,
    annualize: int = 252,
) -> np.ndarray:
    """估计协方差矩阵，带简化版 Ledoit-Wolf 收缩到单位阵。

    Σ_shrunk = (1 − δ) · Σ_sample + δ · (trace(Σ_sample)/n) · I

    Args:
        returns: 日收益率矩阵，形状 (T, n) — T 为样本期数，n 为资产数
        shrinkage: 收缩强度 δ ∈ [0, 1]，默认 0.1。样本量小 / 资产数多时可提高到 0.2~0.5
        annualize: 年化系数（日频=252，周频=52，月频=12）

    Returns:
        年化协方差矩阵，形状 (n, n)
    """
    if returns.ndim != 2:
        raise ValueError(f"returns must be 2D (T, n), got shape {returns.shape}")

    if not (0.0 <= shrinkage <= 1.0):
        raise ValueError(f"shrinkage must be in [0, 1], got {shrinkage}")

    sample_cov = np.cov(returns, rowvar=False, ddof=1)
    n = sample_cov.shape[0]
    target = (np.trace(sample_cov) / n) * np.eye(n)
    shrunk = (1.0 - shrinkage) * sample_cov + shrinkage * target
    return shrunk * annualize


def _apply_min_weight(weights: np.ndarray, min_weight: float) -> np.ndarray:
    """去除尘埃仓位：< min_weight 的权重置零并重新归一化。"""
    if min_weight <= 0:
        return weights
    w = weights.copy()
    w[w < min_weight] = 0.0
    total = w.sum()
    return w / total if total > 1e-12 else weights


def _build_constraints(
    n: int,
    constraints: PortfolioConstraints,
) -> list[dict]:
    """scipy.optimize.minimize 格式的约束列表（提供解析雅可比以确保 SLSQP 收敛）。"""
    out: list[dict] = [
        {
            "type": "eq",
            "fun":  lambda w: float(w.sum() - 1.0),
            "jac":  lambda w: np.ones_like(w),
        },
    ]

    if constraints.sector_map and constraints.sector_caps:
        if len(constraints.sector_map) != n:
            raise ValueError(
                f"sector_map length {len(constraints.sector_map)} != n_assets {n}"
            )
        for sector, cap in constraints.sector_caps.items():
            idx = [i for i, s in enumerate(constraints.sector_map) if s == sector]
            if idx:
                mask = np.zeros(n)
                mask[idx] = 1.0
                out.append({
                    "type": "ineq",
                    "fun":  lambda w, mask=mask, cap=cap: float(cap - w @ mask),
                    "jac":  lambda w, mask=mask: -mask,
                })
    return out


# ══════════════════════════════════════════════════════════════
# 1. Markowitz 均值方差优化
# ══════════════════════════════════════════════════════════════

def markowitz_optimize(
    expected_returns: np.ndarray,
    cov_matrix: np.ndarray,
    risk_aversion: float = 1.0,
    objective: Literal["utility", "min_variance", "max_sharpe"] = "utility",
    target_return: Optional[float] = None,
    constraints: Optional[PortfolioConstraints] = None,
    risk_free_rate: float = 0.0,
) -> OptimizationResult:
    """Markowitz 均值方差优化。

    三种目标函数：

    - ``utility`` (默认): 最大化 U(w) = w'μ − (λ/2) · w'Σw
      λ=0 退化为最大收益（单资产解），λ→∞ 退化为最小方差
      一般 λ ∈ [1, 5]，保守投资者用更高的 λ

    - ``min_variance``: 最小化 w'Σw（忽略期望收益）
      适合不信任任何收益预测、只想分散风险的场景

    - ``max_sharpe``: 最大化 (w'μ − r_f) / sqrt(w'Σw)
      通过 scipy SLSQP 求解。若目标收益 ``target_return`` 指定，
      则改为最小化方差 s.t. w'μ ≥ target_return

    Args:
        expected_returns: 年化期望收益率，形状 (n,)
        cov_matrix: 年化协方差矩阵，形状 (n, n)，应对称半正定
        risk_aversion: 风险厌恶系数 λ，仅在 objective='utility' 时生效
        objective: 优化目标类型
        target_return: 若指定，优化目标变为"在满足此目标收益下最小化方差"
        constraints: 权重/行业约束，默认 (0, 30%) + 无行业约束
        risk_free_rate: 无风险利率，仅 sharpe 计算时使用

    Returns:
        OptimizationResult
    """
    mu = np.asarray(expected_returns, dtype=float).reshape(-1)
    cov = np.asarray(cov_matrix, dtype=float)
    n = len(mu)

    if cov.shape != (n, n):
        raise ValueError(
            f"cov_matrix shape {cov.shape} incompatible with {n} assets"
        )

    constraints = constraints or PortfolioConstraints()
    lb, ub = constraints.weight_bounds
    bounds = [(lb, ub)] * n
    cons = _build_constraints(n, constraints)

    # 可行性快速检查
    if lb * n > 1.0 + 1e-9:
        raise ValueError(
            f"infeasible: n={n} × lb={lb} > 1.0, 每个资产下限之和已超过 100%"
        )
    if ub * n < 1.0 - 1e-9:
        raise ValueError(
            f"infeasible: n={n} × ub={ub} < 1.0, 每个资产上限之和不足 100%"
        )

    # 目标函数
    if objective == "min_variance":
        def obj(w: np.ndarray) -> float:
            return float(w @ cov @ w)
        def jac(w: np.ndarray) -> np.ndarray:
            return 2.0 * (cov @ w)

    elif objective == "max_sharpe":
        def obj(w: np.ndarray) -> float:
            ret = float(w @ mu) - risk_free_rate
            var = float(w @ cov @ w)
            vol = np.sqrt(max(var, 1e-20))
            return -ret / vol   # minimize negative sharpe
        jac = None

    else:  # utility
        if target_return is not None:
            # 最小化方差 s.t. w'μ ≥ target_return
            def obj(w: np.ndarray) -> float:
                return float(w @ cov @ w)
            def jac(w: np.ndarray) -> np.ndarray:
                return 2.0 * (cov @ w)
            cons.append({
                "type": "ineq",
                "fun": lambda w: float(w @ mu - target_return),
            })
        else:
            # 效用最大化
            def obj(w: np.ndarray) -> float:
                return -(float(w @ mu) - 0.5 * risk_aversion * float(w @ cov @ w))
            def jac(w: np.ndarray) -> np.ndarray:
                return -(mu - risk_aversion * (cov @ w))

    # 初始猜测：等权
    w0 = np.ones(n) / n

    result = minimize(
        obj,
        w0,
        jac=jac,
        method="SLSQP",
        bounds=bounds,
        constraints=cons,
        options={"maxiter": 500, "ftol": 1e-10},
    )

    weights = result.x
    weights = np.clip(weights, lb, ub)
    weights = weights / weights.sum() if weights.sum() > 1e-12 else w0
    weights = _apply_min_weight(weights, constraints.min_weight)

    ret, vol, sharpe, rc = compute_portfolio_stats(
        weights, mu, cov, risk_free_rate
    )

    return OptimizationResult(
        weights=weights,
        method=f"markowitz_{objective}",
        expected_return=ret,
        volatility=vol,
        sharpe=sharpe,
        risk_contributions=rc,
        converged=bool(result.success),
        message=str(result.message),
        metadata={
            "risk_aversion": risk_aversion,
            "target_return": target_return,
            "n_iter": int(result.nit),
        },
    )


# ══════════════════════════════════════════════════════════════
# 2. 风险平价
# ══════════════════════════════════════════════════════════════

def risk_parity_optimize(
    cov_matrix: np.ndarray,
    constraints: Optional[PortfolioConstraints] = None,
    expected_returns: Optional[np.ndarray] = None,
    risk_free_rate: float = 0.0,
) -> OptimizationResult:
    """风险平价（Equal Risk Contribution）。

    目标：使每个资产的风险贡献 RC_i 相等。

    用对数风险贡献差的平方和作为目标函数（无约束形式的凸松弛）：
        min   sum_i (log(RC_i) − mean(log(RC_j)))²
        s.t.  sum(w) = 1,  w >= 0

    相比纯等权，风险平价会**自动降低高波动资产的权重**。在没有可信收益预测
    的场景（行业基本面不确定/跨市场配置）比 Markowitz 更稳健。

    Args:
        cov_matrix: 年化协方差矩阵 (n, n)
        constraints: 默认 (0, 0.5) — 风险平价自然会把权重推得更分散
        expected_returns: 可选，仅用于计算结果的 expected_return/sharpe
        risk_free_rate: 无风险利率（仅 sharpe 计算）

    Returns:
        OptimizationResult
    """
    cov = np.asarray(cov_matrix, dtype=float)
    n = cov.shape[0]
    if cov.shape != (n, n):
        raise ValueError(f"cov_matrix must be square, got {cov.shape}")

    constraints = constraints or PortfolioConstraints(weight_bounds=(1e-4, 0.5))
    lb, ub = constraints.weight_bounds
    # 风险平价要求权重严格大于 0 以避免 log 爆炸
    lb = max(lb, 1e-6)
    bounds = [(lb, ub)] * n
    cons = _build_constraints(n, constraints)

    def obj(w: np.ndarray) -> float:
        variance = float(w @ cov @ w)
        if variance < 1e-20:
            return 1e10
        sigma = np.sqrt(variance)
        mrc = cov @ w
        rc = w * mrc / sigma          # 各资产风险贡献 (n,), sum=sigma
        log_rc = np.log(np.maximum(rc, 1e-20))
        return float(np.var(log_rc))  # 对数风险贡献的方差 → 所有相等时为 0

    w0 = np.ones(n) / n
    result = minimize(
        obj,
        w0,
        method="SLSQP",
        bounds=bounds,
        constraints=cons,
        options={"maxiter": 1000, "ftol": 1e-12},
    )

    weights = result.x
    weights = np.clip(weights, lb, ub)
    weights = weights / weights.sum() if weights.sum() > 1e-12 else w0
    weights = _apply_min_weight(weights, constraints.min_weight)

    if expected_returns is not None:
        mu = np.asarray(expected_returns, dtype=float).reshape(-1)
    else:
        mu = np.zeros(n)

    ret, vol, sharpe, rc = compute_portfolio_stats(
        weights, mu, cov, risk_free_rate
    )

    return OptimizationResult(
        weights=weights,
        method="risk_parity",
        expected_return=ret,
        volatility=vol,
        sharpe=sharpe,
        risk_contributions=rc,
        converged=bool(result.success),
        message=str(result.message),
        metadata={
            "rc_dispersion": float(np.std(rc) / (np.mean(rc) + 1e-12)),
            "n_iter": int(result.nit),
        },
    )


# ══════════════════════════════════════════════════════════════
# 3. Black-Litterman
# ══════════════════════════════════════════════════════════════

def black_litterman_optimize(
    market_cap_weights: np.ndarray,
    cov_matrix: np.ndarray,
    P: np.ndarray,
    Q: np.ndarray,
    view_confidences: Optional[np.ndarray] = None,
    tau: float = 0.05,
    risk_aversion: float = 2.5,
    constraints: Optional[PortfolioConstraints] = None,
    risk_free_rate: float = 0.0,
) -> OptimizationResult:
    """Black-Litterman 贝叶斯合成市场先验与投资者观点。

    步骤：

    1. 从市场均衡反推先验收益（Idzorek reverse optimization）:
           π = λ · Σ · w_mkt

    2. 用 Ω 表达对 k 个观点的不确定度。若 view_confidences 给定，则：
           Ω = diag(τ · p_k' Σ p_k / c_k)     (He-Litterman 变体)
       其中 c_k ∈ (0, 1]，confidence=1 时 Ω_kk 最小（观点最可信）

    3. 后验期望收益：
           μ_BL = [(τΣ)^{-1} + P'Ω^{-1}P]^{-1} · [(τΣ)^{-1}π + P'Ω^{-1}Q]
       后验协方差：
           Σ_BL = Σ + [(τΣ)^{-1} + P'Ω^{-1}P]^{-1}

    4. 用 μ_BL 做 Markowitz 效用最大化（传入同一 risk_aversion）

    Args:
        market_cap_weights: 市场均衡权重（先验），形状 (n,)，sum=1
        cov_matrix: 年化协方差矩阵 (n, n)
        P: 观点矩阵 (k, n)，每行对应一个观点
                - 绝对观点: [0, 0, 1, 0, ...]  → 资产 3 的期望收益 = Q_i
                - 相对观点: [1, −1, 0, ...]   → 资产 1 − 资产 2 的期望收益 = Q_i
        Q: 观点预期收益，形状 (k,)
        view_confidences: 观点置信度 c ∈ (0, 1]，形状 (k,)，
                          在 CampusQuant 中直接用 Agent 的 confidence 分数
        tau: 先验的标量缩放，文献值 0.025 ~ 0.05
        risk_aversion: Markowitz 效用最大化的风险厌恶系数
        constraints: 权重约束
        risk_free_rate: 无风险利率（sharpe 计算）

    Returns:
        OptimizationResult（metadata 包含后验 μ_BL 以便审计）
    """
    w_mkt = np.asarray(market_cap_weights, dtype=float).reshape(-1)
    cov = np.asarray(cov_matrix, dtype=float)
    P = np.asarray(P, dtype=float)
    Q = np.asarray(Q, dtype=float).reshape(-1)

    n = len(w_mkt)
    k = len(Q)

    if cov.shape != (n, n):
        raise ValueError(f"cov shape {cov.shape} != ({n}, {n})")
    if P.ndim != 2 or P.shape != (k, n):
        raise ValueError(f"P shape {P.shape} != ({k}, {n})")

    if abs(w_mkt.sum() - 1.0) > 1e-6:
        logger.warning(
            "market_cap_weights sum = %.6f, 归一化后继续", w_mkt.sum()
        )
        w_mkt = w_mkt / w_mkt.sum()

    # Step 1: 先验收益 π = λ · Σ · w_mkt
    pi = risk_aversion * (cov @ w_mkt)

    # Step 2: 观点不确定度 Ω
    if view_confidences is None:
        view_confidences = np.ones(k) * 0.5
    c = np.asarray(view_confidences, dtype=float).reshape(-1)
    c = np.clip(c, 1e-4, 1.0)
    # He-Litterman: Ω_kk = τ · p_k' Σ p_k / c_k
    omega_diag = np.array([
        tau * float(P[i] @ cov @ P[i]) / c[i]
        for i in range(k)
    ])
    omega_diag = np.maximum(omega_diag, 1e-10)
    omega = np.diag(omega_diag)

    # Step 3: 后验 μ_BL
    tau_cov = tau * cov
    tau_cov_inv = np.linalg.inv(tau_cov)
    omega_inv = np.diag(1.0 / omega_diag)

    posterior_precision = tau_cov_inv + P.T @ omega_inv @ P
    posterior_cov_addon = np.linalg.inv(posterior_precision)
    mu_bl = posterior_cov_addon @ (tau_cov_inv @ pi + P.T @ omega_inv @ Q)
    sigma_bl = cov + posterior_cov_addon

    # Step 4: 用后验 μ_BL 跑 Markowitz 效用最大化
    constraints = constraints or PortfolioConstraints()
    result = markowitz_optimize(
        expected_returns=mu_bl,
        cov_matrix=sigma_bl,
        risk_aversion=risk_aversion,
        objective="utility",
        constraints=constraints,
        risk_free_rate=risk_free_rate,
    )

    # 用 BL 后验收益 + 样本协方差 再计算一次报告指标
    ret, vol, sharpe, rc = compute_portfolio_stats(
        result.weights, mu_bl, cov, risk_free_rate
    )

    return OptimizationResult(
        weights=result.weights,
        method="black_litterman",
        expected_return=ret,
        volatility=vol,
        sharpe=sharpe,
        risk_contributions=rc,
        converged=result.converged,
        message=result.message,
        metadata={
            "prior_returns": pi.tolist(),
            "posterior_returns": mu_bl.tolist(),
            "tau": tau,
            "risk_aversion": risk_aversion,
            "n_views": k,
            "view_confidences": c.tolist(),
        },
    )


# ══════════════════════════════════════════════════════════════
# CampusQuant 适配层：Agent 观点 → BL view matrix
# ══════════════════════════════════════════════════════════════

def agent_views_to_bl_inputs(
    symbols: list[str],
    agent_signals: list[dict],
    expected_return_magnitudes: Optional[dict[str, float]] = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """把 CampusQuant Agent 的研判结果转为 Black-Litterman 的 (P, Q, view_confidences)。

    规则：
        recommendation == "BUY"  → 该资产年化超额收益 = +mag
        recommendation == "SELL" → 该资产年化超额收益 = −mag
        recommendation == "HOLD" → 不生成观点（置信度偏低时也忽略）

    每个有方向的研判对应一个绝对观点（P 的一行只在该资产位置为 1）。
    observation 的 confidence 直接作为 view_confidences。

    Args:
        symbols: 资产代码列表，顺序与权重向量对齐
        agent_signals: list of {"symbol": ..., "recommendation": "BUY/SELL/HOLD", "confidence": 0~1}
                       支持同一 symbol 多个 agent 产出多行观点
        expected_return_magnitudes: {symbol: 年化幅度}，默认 BUY=+10%, SELL=−10%

    Returns:
        (P, Q, view_confidences)
    """
    n = len(symbols)
    sym_idx = {s: i for i, s in enumerate(symbols)}

    default_mag = 0.10
    mag_map = expected_return_magnitudes or {}

    P_rows: list[np.ndarray] = []
    Q_vals: list[float] = []
    c_vals: list[float] = []

    for sig in agent_signals:
        sym = sig.get("symbol")
        rec = sig.get("recommendation", "HOLD")
        conf = float(sig.get("confidence", 0.5))
        if sym not in sym_idx or rec == "HOLD":
            continue

        i = sym_idx[sym]
        row = np.zeros(n)
        row[i] = 1.0
        mag = mag_map.get(sym, default_mag)
        q = mag if rec == "BUY" else -mag

        P_rows.append(row)
        Q_vals.append(q)
        c_vals.append(conf)

    if not P_rows:
        # 空观点矩阵：后续 BL 会退化为纯先验
        return np.zeros((0, n)), np.zeros(0), np.zeros(0)

    return np.array(P_rows), np.array(Q_vals), np.array(c_vals)
