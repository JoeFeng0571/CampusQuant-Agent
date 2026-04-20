"""
portfolio — 组合优化模块

提供三种经典组合优化方法，输出带完整指标的 OptimizationResult：

    from portfolio import (
        markowitz_optimize,
        risk_parity_optimize,
        black_litterman_optimize,
        PortfolioConstraints,
        OptimizationResult,
    )

方法概览：
    - Markowitz 均值方差：给定期望收益与协方差，求效用最大化的权重
    - 风险平价：使每个资产对组合方差的贡献相等
    - Black-Litterman：把 CampusQuant Agent 的主观观点作为 view matrix
      与市场均衡先验贝叶斯合成后验收益，再做均值方差优化

参考文献：
    Markowitz (1952), "Portfolio Selection", The Journal of Finance.
    Maillard, Roncalli, Teïletche (2010), "The Properties of Equally Weighted
        Risk Contribution Portfolios", Journal of Portfolio Management.
    Black & Litterman (1992), "Global Portfolio Optimization", Financial
        Analysts Journal.
"""
from portfolio.optimizer import (
    PortfolioConstraints,
    OptimizationResult,
    markowitz_optimize,
    risk_parity_optimize,
    black_litterman_optimize,
    compute_portfolio_stats,
    estimate_covariance,
    agent_views_to_bl_inputs,
)

__all__ = [
    "PortfolioConstraints",
    "OptimizationResult",
    "markowitz_optimize",
    "risk_parity_optimize",
    "black_litterman_optimize",
    "compute_portfolio_stats",
    "estimate_covariance",
    "agent_views_to_bl_inputs",
]
