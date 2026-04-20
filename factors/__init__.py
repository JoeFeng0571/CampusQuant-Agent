"""
factors — 因子库与 IC/IR 分析

核心抽象：
    因子面板（factor panel）= DataFrame，index = date, columns = symbols
                              单个因子的时间 × 横截面矩阵
    前向收益面板                 = DataFrame，同上，values 为未来 N 日收益

五类因子：
    - 价值  (value.py)    : BP / EP / SP / 股息率
    - 质量  (quality.py)  : ROE / ROIC / 毛利率稳定性 / 现金流覆盖
    - 动量  (momentum.py) : N 月动量、反转因子
    - 波动率 (volatility.py): 60 日 vol / 下行偏差 / 最大回撤
    - 情绪  (sentiment.py): 新闻情绪打分 + 换手率（当前为接口占位）

分析工具：
    - ic_analyzer.py : rank IC、IC_IR、IC 胜率、衰减曲线
    - combine.py     : 施密特正交化、等权/IC/IR 加权合成

用法示例：

    from factors import compute_momentum, rank_ic, ic_ir
    m12 = compute_momentum(prices, window=252)
    fwd = prices.pct_change(20).shift(-20)
    ic_series = rank_ic(m12, fwd)
    print(f"IC_IR = {ic_ir(ic_series):.3f}")
"""
from factors.value import (
    compute_book_to_price,
    compute_earnings_to_price,
    compute_sales_to_price,
    compute_dividend_yield,
)
from factors.quality import (
    compute_roe,
    compute_roic,
    compute_gross_margin_stability,
    compute_cashflow_coverage,
)
from factors.momentum import (
    compute_momentum,
    compute_reversal,
    compute_multi_horizon_momentum,
)
from factors.volatility import (
    compute_realized_volatility,
    compute_downside_deviation,
    compute_max_drawdown,
)
from factors.ic_analyzer import (
    rank_ic,
    ic_ir,
    ic_win_rate,
    ic_decay,
    summarize_ic,
)
from factors.combine import (
    orthogonalize,
    combine_factors,
    ic_weighted,
    ic_ir_weighted,
)
from factors.sentiment import (
    compute_turnover_ratio,
    compute_news_sentiment,
)

__all__ = [
    # Value
    "compute_book_to_price",
    "compute_earnings_to_price",
    "compute_sales_to_price",
    "compute_dividend_yield",
    # Quality
    "compute_roe",
    "compute_roic",
    "compute_gross_margin_stability",
    "compute_cashflow_coverage",
    # Momentum
    "compute_momentum",
    "compute_reversal",
    "compute_multi_horizon_momentum",
    # Volatility
    "compute_realized_volatility",
    "compute_downside_deviation",
    "compute_max_drawdown",
    # IC analysis
    "rank_ic",
    "ic_ir",
    "ic_win_rate",
    "ic_decay",
    "summarize_ic",
    # Combine
    "orthogonalize",
    "combine_factors",
    "ic_weighted",
    "ic_ir_weighted",
    # Sentiment
    "compute_turnover_ratio",
    "compute_news_sentiment",
]
