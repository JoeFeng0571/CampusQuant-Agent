"""
factors/value.py — 价值因子

所有函数签名一致：
    输入 fundamentals: DataFrame, index=date, columns=MultiIndex[(symbol, field)]
         或更简单的 dict[symbol -> DataFrame[date, field]]
    输出：DataFrame, index=date, columns=symbols

本模块只实现公式，不假设数据源。调用方负责准备 fundamentals 面板。
"""
from __future__ import annotations

import pandas as pd


def _safe_divide(num: pd.DataFrame, den: pd.DataFrame) -> pd.DataFrame:
    """防 0 除，0 除时返回 NaN。"""
    return num.where(den.abs() > 1e-12, other=float("nan")) / den.where(
        den.abs() > 1e-12, other=float("nan")
    )


def compute_book_to_price(
    book_value: pd.DataFrame,
    market_cap: pd.DataFrame,
) -> pd.DataFrame:
    """BP（账面市值比）= 股东权益 / 市值。

    低估值股票 BP 高。是价值投资的最核心指标之一（Fama-French 三因子里的 HML）。
    """
    return _safe_divide(book_value, market_cap)


def compute_earnings_to_price(
    net_income: pd.DataFrame,
    market_cap: pd.DataFrame,
) -> pd.DataFrame:
    """EP（盈利市值比）= 净利润 / 市值 = 1 / PE。

    EP 比 PE 更适合做因子值——PE 在亏损股票上无意义（负值），EP 则线性。
    """
    return _safe_divide(net_income, market_cap)


def compute_sales_to_price(
    revenue: pd.DataFrame,
    market_cap: pd.DataFrame,
) -> pd.DataFrame:
    """SP（销售市值比）= 营收 / 市值 = 1 / PS。

    对于成长期、亏损期的公司（EP 失效），SP 仍有判断力。
    """
    return _safe_divide(revenue, market_cap)


def compute_dividend_yield(
    dividends_ttm: pd.DataFrame,
    price: pd.DataFrame,
) -> pd.DataFrame:
    """股息率 = 过去 12 月分红 / 当前股价。

    高股息率 = 股东回报 + 现金流稳健的代理变量。
    """
    return _safe_divide(dividends_ttm, price)
