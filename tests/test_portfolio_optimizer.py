"""
tests/test_portfolio_optimizer.py — 组合优化器单元测试

覆盖：
  - 三种优化方法的基本正确性
  - 退化场景（单资产 / 对角协方差 / 零期望收益）
  - 约束边界（weight_bounds / 行业 cap / min_weight）
  - Black-Litterman 的 Agent 观点映射
  - 协方差估计（shrinkage）
"""
import numpy as np
import pytest

from portfolio import (
    PortfolioConstraints,
    black_litterman_optimize,
    compute_portfolio_stats,
    estimate_covariance,
    markowitz_optimize,
    risk_parity_optimize,
)
from portfolio.optimizer import agent_views_to_bl_inputs


# ══════════════════════════════════════════════════════════════
# Fixtures
# ══════════════════════════════════════════════════════════════

@pytest.fixture
def three_asset_problem():
    """经典三资产示例：收益递减、第一资产风险最高。"""
    mu = np.array([0.12, 0.08, 0.05])
    cov = np.array([
        [0.04, 0.01, 0.00],
        [0.01, 0.02, 0.00],
        [0.00, 0.00, 0.01],
    ])
    return mu, cov


@pytest.fixture
def diagonal_cov():
    """对角协方差：资产间独立，等波动。"""
    return np.eye(4) * 0.04


# ══════════════════════════════════════════════════════════════
# Markowitz
# ══════════════════════════════════════════════════════════════

class TestMarkowitz:
    def test_utility_converges(self, three_asset_problem):
        mu, cov = three_asset_problem
        r = markowitz_optimize(mu, cov, risk_aversion=2.0)
        assert r.converged
        assert r.method == "markowitz_utility"
        assert abs(r.weights.sum() - 1.0) < 1e-6
        assert (r.weights >= -1e-9).all()
        assert r.sharpe > 0

    def test_min_variance_prefers_low_vol(self, three_asset_problem):
        """最小方差应把最多权重给到低波动资产（asset 2，var=0.01）。"""
        mu, cov = three_asset_problem
        r = markowitz_optimize(mu, cov, objective="min_variance")
        assert r.converged
        assert r.weights[2] > r.weights[0]
        # 最小方差的波动率应低于等权组合
        ew = np.ones(3) / 3
        _, ew_vol, _, _ = compute_portfolio_stats(ew, mu, cov)
        assert r.volatility < ew_vol

    def test_max_sharpe_beats_utility_sharpe(self, three_asset_problem):
        """max_sharpe 解的夏普应 ≥ utility 解的夏普（定义上）。"""
        mu, cov = three_asset_problem
        rs = markowitz_optimize(mu, cov, objective="max_sharpe")
        ru = markowitz_optimize(mu, cov, risk_aversion=2.0)
        assert rs.converged and ru.converged
        assert rs.sharpe >= ru.sharpe - 1e-3

    def test_weight_bounds_respected(self, three_asset_problem):
        mu, cov = three_asset_problem
        cons = PortfolioConstraints(weight_bounds=(0.10, 0.50))
        r = markowitz_optimize(mu, cov, risk_aversion=2.0, constraints=cons)
        assert (r.weights >= 0.10 - 1e-6).all()
        assert (r.weights <= 0.50 + 1e-6).all()

    def test_target_return_satisfied(self, three_asset_problem):
        """指定 target_return 时，结果期望收益应 ≥ target。"""
        mu, cov = three_asset_problem
        target = 0.09
        r = markowitz_optimize(mu, cov, target_return=target)
        assert r.expected_return >= target - 1e-4

    def test_infeasible_raises(self, three_asset_problem):
        """上限 × n < 1 时应抛错。"""
        mu, cov = three_asset_problem
        cons = PortfolioConstraints(weight_bounds=(0.0, 0.25))   # 0.25 × 3 = 0.75 < 1
        with pytest.raises(ValueError, match="infeasible"):
            markowitz_optimize(mu, cov, constraints=cons)

    def test_single_asset_degenerate(self):
        """单资产时权重应为 1。"""
        r = markowitz_optimize(
            np.array([0.1]), np.array([[0.05]]),
            constraints=PortfolioConstraints(weight_bounds=(0, 1)),
        )
        assert abs(r.weights[0] - 1.0) < 1e-6

    def test_sector_cap(self, three_asset_problem):
        """资产 0 和 1 同属"科技"行业，合计 ≤ 0.50。

        注意可行性: tech cap + consumer 单资产上限必须 ≥ 1。
        这里 cap=0.50, consumer ub=0.80, 合计 1.30 足以覆盖 sum=1。
        """
        mu, cov = three_asset_problem
        cons = PortfolioConstraints(
            weight_bounds=(0.0, 0.80),
            sector_map=["tech", "tech", "consumer"],
            sector_caps={"tech": 0.50},
        )
        r = markowitz_optimize(mu, cov, risk_aversion=0.5, constraints=cons)
        assert r.weights[0] + r.weights[1] <= 0.50 + 1e-4


# ══════════════════════════════════════════════════════════════
# Risk Parity
# ══════════════════════════════════════════════════════════════

class TestRiskParity:
    def test_equal_rc_on_diagonal_cov(self, diagonal_cov):
        """对角等方差协方差 → 风险平价应趋近等权。"""
        r = risk_parity_optimize(diagonal_cov)
        assert r.converged
        assert (np.abs(r.weights - 0.25) < 1e-3).all()

    def test_rc_equal_for_three_asset(self, three_asset_problem):
        """三资产风险平价：各 RC 应在 1% 内相等。"""
        _, cov = three_asset_problem
        r = risk_parity_optimize(cov)
        assert r.converged
        rc = r.risk_contributions
        assert rc.std() / rc.mean() < 0.02   # 2% 以内离散度

    def test_sum_to_one(self, three_asset_problem):
        _, cov = three_asset_problem
        r = risk_parity_optimize(cov)
        assert abs(r.weights.sum() - 1.0) < 1e-6

    def test_non_negative(self, three_asset_problem):
        _, cov = three_asset_problem
        r = risk_parity_optimize(cov)
        assert (r.weights > 0).all()   # 严格正，因为 log(RC) 要求


# ══════════════════════════════════════════════════════════════
# Black-Litterman
# ══════════════════════════════════════════════════════════════

class TestBlackLitterman:
    def test_bullish_view_shifts_weight(self, three_asset_problem):
        """看多资产 0 → 资产 0 权重应比市场权重高。"""
        _, cov = three_asset_problem
        w_mkt = np.array([0.4, 0.4, 0.2])
        P = np.array([[1.0, 0.0, 0.0]])
        Q = np.array([0.15])
        conf = np.array([0.8])
        r = black_litterman_optimize(w_mkt, cov, P, Q, conf, risk_aversion=2.0)
        assert r.converged
        assert r.weights[0] > w_mkt[0]   # 观点提高了 asset 0 权重

    def test_posterior_between_prior_and_view(self, three_asset_problem):
        """后验收益应夹在先验和观点之间。"""
        _, cov = three_asset_problem
        w_mkt = np.array([0.4, 0.4, 0.2])
        P = np.array([[1.0, 0.0, 0.0]])
        Q = np.array([0.20])
        r = black_litterman_optimize(w_mkt, cov, P, Q, np.array([0.5]))
        prior = np.array(r.metadata["prior_returns"])
        posterior = np.array(r.metadata["posterior_returns"])
        # asset 0: prior < posterior < Q
        assert prior[0] < posterior[0] < 0.20

    def test_higher_confidence_moves_closer_to_view(self, three_asset_problem):
        _, cov = three_asset_problem
        w_mkt = np.array([0.4, 0.4, 0.2])
        P = np.array([[1.0, 0.0, 0.0]])
        Q = np.array([0.20])
        r_low = black_litterman_optimize(w_mkt, cov, P, Q, np.array([0.1]))
        r_high = black_litterman_optimize(w_mkt, cov, P, Q, np.array([0.99]))
        post_low = np.array(r_low.metadata["posterior_returns"])[0]
        post_high = np.array(r_high.metadata["posterior_returns"])[0]
        assert post_high > post_low

    def test_agent_views_translation(self):
        symbols = ["A", "B", "C"]
        signals = [
            {"symbol": "A", "recommendation": "BUY",  "confidence": 0.8},
            {"symbol": "B", "recommendation": "HOLD", "confidence": 0.6},
            {"symbol": "C", "recommendation": "SELL", "confidence": 0.7},
        ]
        P, Q, conf = agent_views_to_bl_inputs(symbols, signals)
        assert P.shape == (2, 3)   # HOLD 被过滤
        assert Q.tolist() == [0.10, -0.10]
        assert conf.tolist() == [0.8, 0.7]

    def test_empty_agent_views(self):
        symbols = ["A", "B"]
        signals = [
            {"symbol": "A", "recommendation": "HOLD", "confidence": 0.5},
        ]
        P, Q, conf = agent_views_to_bl_inputs(symbols, signals)
        assert P.shape == (0, 2)
        assert len(Q) == 0


# ══════════════════════════════════════════════════════════════
# 工具函数
# ══════════════════════════════════════════════════════════════

class TestUtilities:
    def test_compute_stats_equal_weight(self, three_asset_problem):
        mu, cov = three_asset_problem
        w = np.ones(3) / 3
        ret, vol, sharpe, rc = compute_portfolio_stats(w, mu, cov)
        assert abs(ret - mu.mean()) < 1e-9
        assert vol > 0
        assert abs(rc.sum() - vol) < 1e-9   # RC 之和等于总波动

    def test_cov_estimation_shrinkage(self):
        """shrinkage=1 时，估计协方差应为 (tr(S)/n) · I （纯 target）。"""
        np.random.seed(42)
        T, n = 100, 4
        returns = np.random.randn(T, n) * 0.01
        cov = estimate_covariance(returns, shrinkage=1.0, annualize=1)
        # 对角元全相等，非对角为 0
        assert np.allclose(cov - np.diag(np.diag(cov)), 0, atol=1e-9)
        diag_vals = np.diag(cov)
        assert np.allclose(diag_vals, diag_vals[0], atol=1e-9)

    def test_cov_estimation_annualize(self):
        np.random.seed(7)
        returns = np.random.randn(500, 3) * 0.01
        cov_daily = estimate_covariance(returns, shrinkage=0.0, annualize=1)
        cov_annual = estimate_covariance(returns, shrinkage=0.0, annualize=252)
        assert np.allclose(cov_annual, cov_daily * 252)


# ══════════════════════════════════════════════════════════════
# 端到端：from historical_returns → optimize
# ══════════════════════════════════════════════════════════════

def test_full_pipeline_from_history():
    """模拟一次完整的历史数据 → Markowitz utility 优化链路。"""
    np.random.seed(1)
    T, n = 252, 5
    true_mu = np.array([0.10, 0.08, 0.06, 0.04, 0.02]) / 252
    L = np.random.randn(n, n) * 0.005
    true_cov = L @ L.T + np.eye(n) * 0.0001
    returns = np.random.multivariate_normal(true_mu, true_cov, size=T)

    cov = estimate_covariance(returns, shrinkage=0.1, annualize=252)
    mu = returns.mean(axis=0) * 252

    r = markowitz_optimize(mu, cov, risk_aversion=3.0)
    assert r.converged
    assert abs(r.weights.sum() - 1.0) < 1e-6
    assert r.sharpe > 0
