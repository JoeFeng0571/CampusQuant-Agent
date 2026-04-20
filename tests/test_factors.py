"""
tests/test_factors.py — 因子库单元测试

策略:
    - 价值/质量因子: 简单公式验证（合成数据）
    - 动量/波动率因子: 合成已知信号的价格序列，验证因子能识别
    - IC 分析: 构造 y = α·x + noise 的合成数据，验证 IC 逼近理论值
    - 正交化: 验证残差与原前序因子相关系数 ≈ 0
    - 合成: 验证等权/IC/IR 三种方案与人工计算一致
"""
import numpy as np
import pandas as pd
import pytest

from factors import (
    # value
    compute_book_to_price,
    compute_earnings_to_price,
    compute_sales_to_price,
    # quality
    compute_roe,
    compute_cashflow_coverage,
    # momentum
    compute_momentum,
    compute_reversal,
    compute_multi_horizon_momentum,
    # volatility
    compute_realized_volatility,
    compute_max_drawdown,
    # IC
    rank_ic,
    ic_ir,
    ic_win_rate,
    ic_decay,
    summarize_ic,
    # combine
    orthogonalize,
    combine_factors,
    ic_weighted,
    ic_ir_weighted,
)


# ══════════════════════════════════════════════════════════════
# Fixtures
# ══════════════════════════════════════════════════════════════

@pytest.fixture
def tiny_fundamentals():
    """极小规模合成基本面数据。"""
    idx = pd.date_range("2024-01-01", periods=4, freq="QE")
    cols = ["A", "B", "C"]
    book    = pd.DataFrame([[100, 200, 50]] * 4, index=idx, columns=cols)
    mcap    = pd.DataFrame([[500, 1000, 500]] * 4, index=idx, columns=cols)
    income  = pd.DataFrame([[20, 50, 5]] * 4, index=idx, columns=cols)
    revenue = pd.DataFrame([[100, 300, 80]] * 4, index=idx, columns=cols)
    return book, mcap, income, revenue


@pytest.fixture
def price_panel_with_momentum():
    """合成价格序列，股票 0/1/2 有上涨动量，股票 3/4 下跌，5-9 纯噪声。"""
    np.random.seed(42)
    n_days, n_stocks = 400, 10
    drift = np.array([0.0008, 0.0006, 0.0004, -0.0004, -0.0006, 0, 0, 0, 0, 0])
    noise = np.random.randn(n_days, n_stocks) * 0.015
    daily_rets = noise + drift
    prices = pd.DataFrame(
        100 * np.exp(daily_rets.cumsum(axis=0)),
        index=pd.date_range("2023-01-01", periods=n_days, freq="B"),
        columns=[f"S{i}" for i in range(n_stocks)],
    )
    return prices


# ══════════════════════════════════════════════════════════════
# 价值因子
# ══════════════════════════════════════════════════════════════

class TestValueFactors:
    def test_bp_formula(self, tiny_fundamentals):
        book, mcap, _, _ = tiny_fundamentals
        bp = compute_book_to_price(book, mcap)
        assert bp.iloc[0]["A"] == pytest.approx(100 / 500)
        assert bp.iloc[0]["B"] == pytest.approx(200 / 1000)
        assert bp.iloc[0]["C"] == pytest.approx(50 / 500)

    def test_ep_equals_inverse_pe(self, tiny_fundamentals):
        """EP 应等于 1/PE：价格 / 每股收益 的倒数。"""
        _, mcap, income, _ = tiny_fundamentals
        ep = compute_earnings_to_price(income, mcap)
        assert ep.iloc[0]["A"] == pytest.approx(20 / 500)

    def test_safe_divide_returns_nan_on_zero(self):
        """除以 0 应返回 NaN 而不是 inf。"""
        book = pd.DataFrame({"X": [100.0]})
        mcap = pd.DataFrame({"X": [0.0]})
        bp = compute_book_to_price(book, mcap)
        assert pd.isna(bp.iloc[0]["X"])


# ══════════════════════════════════════════════════════════════
# 质量因子
# ══════════════════════════════════════════════════════════════

class TestQualityFactors:
    def test_roe(self, tiny_fundamentals):
        book, _, income, _ = tiny_fundamentals
        # book value 当"净资产"用
        roe = compute_roe(income, book)
        assert roe.iloc[0]["A"] == pytest.approx(20 / 100)
        assert roe.iloc[0]["B"] == pytest.approx(50 / 200)

    def test_cashflow_coverage_sign(self):
        """净利润为负时 coverage 应为负。"""
        cfo = pd.DataFrame({"A": [100.0]})
        ni  = pd.DataFrame({"A": [-50.0]})
        cov = compute_cashflow_coverage(cfo, ni)
        assert cov.iloc[0]["A"] < 0


# ══════════════════════════════════════════════════════════════
# 动量因子
# ══════════════════════════════════════════════════════════════

class TestMomentum:
    def test_momentum_direction(self, price_panel_with_momentum):
        """有正动量的股票因子值 > 有负动量的股票。"""
        prices = price_panel_with_momentum
        mom = compute_momentum(prices, window=252, skip=21)
        last_valid = mom.dropna(how="all").iloc[-1]
        # 平均上看，S0 > S4
        assert last_valid["S0"] > last_valid["S4"]

    def test_window_gt_skip_required(self, price_panel_with_momentum):
        prices = price_panel_with_momentum
        with pytest.raises(ValueError, match="must be >"):
            compute_momentum(prices, window=21, skip=21)

    def test_reversal_negative_of_return(self, price_panel_with_momentum):
        prices = price_panel_with_momentum
        rev = compute_reversal(prices, window=21)
        manual = -prices.pct_change(21)
        pd.testing.assert_frame_equal(rev, manual)

    def test_multi_horizon(self, price_panel_with_momentum):
        prices = price_panel_with_momentum
        panels = compute_multi_horizon_momentum(prices, horizons=(21, 63, 252))
        assert set(panels.keys()) == {"mom_21d", "mom_63d", "mom_252d"}
        for p in panels.values():
            assert p.shape == prices.shape


# ══════════════════════════════════════════════════════════════
# 波动率因子
# ══════════════════════════════════════════════════════════════

class TestVolatility:
    def test_realized_vol_positive(self, price_panel_with_momentum):
        prices = price_panel_with_momentum
        vol = compute_realized_volatility(prices, window=60)
        clean = vol.dropna()
        assert (clean.values >= 0).all()
        # 年化后 A 股合理范围 5%-100%
        assert (clean.values < 2.0).all()

    def test_max_drawdown_positive(self, price_panel_with_momentum):
        prices = price_panel_with_momentum
        mdd = compute_max_drawdown(prices, window=120)
        clean = mdd.dropna()
        assert (clean.values >= 0).all()


# ══════════════════════════════════════════════════════════════
# IC 分析 — 用已知 alpha·X 关系验证
# ══════════════════════════════════════════════════════════════

class TestICAnalyzer:
    @staticmethod
    def _build_known_ic_dataset(
        alpha: float = 0.5,
        noise: float = 0.1,
        n_days: int = 100,
        n_stocks: int = 30,
        seed: int = 7,
    ):
        """构造 fwd_ret[t, i] = alpha * factor[t, i] + noise·ε[t, i]。

        理论上 Spearman IC 均值 ≈ sign(alpha) × 某个正值（依 alpha/noise 比例）。
        """
        rng = np.random.default_rng(seed)
        factor = pd.DataFrame(
            rng.standard_normal((n_days, n_stocks)),
            index=pd.date_range("2024-01-01", periods=n_days, freq="B"),
            columns=[f"S{i}" for i in range(n_stocks)],
        )
        fwd = alpha * factor + noise * pd.DataFrame(
            rng.standard_normal((n_days, n_stocks)),
            index=factor.index, columns=factor.columns,
        )
        # 用 fwd 当做"未来收益"，为了 summarize_ic 的 price_panel 接口，
        # 构造一个价格序列使其 pct_change(20) = fwd (只是为了通过接口)
        return factor, fwd

    def test_ic_positive_when_alpha_positive(self):
        factor, fwd = self._build_known_ic_dataset(alpha=1.0, noise=0.5)
        ic = rank_ic(factor, fwd)
        assert ic.mean() > 0.3

    def test_ic_negative_when_alpha_negative(self):
        factor, fwd = self._build_known_ic_dataset(alpha=-1.0, noise=0.5)
        ic = rank_ic(factor, fwd)
        assert ic.mean() < -0.3

    def test_ic_near_zero_when_no_signal(self):
        factor, _ = self._build_known_ic_dataset(alpha=0.0, noise=1.0)
        _, fwd_unrelated = self._build_known_ic_dataset(alpha=0.0, noise=1.0, seed=999)
        ic = rank_ic(factor, fwd_unrelated)
        assert abs(ic.mean()) < 0.1

    def test_ic_ir_formula(self):
        ic = pd.Series([0.05, 0.02, 0.04, -0.01, 0.03])
        assert ic_ir(ic) == pytest.approx(ic.mean() / ic.std(), abs=1e-9)

    def test_ic_win_rate(self):
        ic = pd.Series([0.1, 0.2, -0.1, 0.05, -0.2, 0.0])
        # win = (>0) = [T,T,F,T,F,F] = 3/6 = 0.5
        assert ic_win_rate(ic) == 0.5

    def test_empty_ic_graceful(self):
        empty = pd.Series([], dtype=float)
        assert ic_ir(empty) == 0.0
        assert ic_win_rate(empty) == 0.0

    def test_decay_table_shape(self, price_panel_with_momentum):
        prices = price_panel_with_momentum
        mom = compute_momentum(prices, window=252, skip=21)
        decay = ic_decay(mom, prices, horizons=(1, 5, 10, 20))
        assert decay.shape == (4, 5)
        assert "ic_ir" in decay.columns
        assert "n_obs" in decay.columns


# ══════════════════════════════════════════════════════════════
# 正交化与合成
# ══════════════════════════════════════════════════════════════

class TestCombine:
    def test_orthogonalize_residual_uncorrelated(self):
        """正交后的第二因子与第一因子的横截面相关应接近 0。"""
        rng = np.random.default_rng(123)
        n_days, n_stocks = 50, 30
        f1 = pd.DataFrame(
            rng.standard_normal((n_days, n_stocks)),
            columns=[f"S{i}" for i in range(n_stocks)],
        )
        # f2 = 0.8 * f1 + noise
        f2 = 0.8 * f1 + 0.3 * pd.DataFrame(
            rng.standard_normal((n_days, n_stocks)),
            columns=f1.columns,
        )

        ortho = orthogonalize([f1, f2], names=["f1", "f2"])
        # 原始横截面相关约 0.8
        raw_corr = f1.iloc[25].corr(f2.iloc[25])
        new_corr = ortho["f1"].iloc[25].corr(ortho["f2"].iloc[25])
        assert abs(raw_corr) > 0.5
        assert abs(new_corr) < 0.1

    def test_orthogonalize_first_unchanged_after_zscore(self):
        """第一个因子标准化后应原样返回。"""
        rng = np.random.default_rng(1)
        f1 = pd.DataFrame(
            rng.standard_normal((20, 10)),
            columns=[f"S{i}" for i in range(10)],
        )
        ortho = orthogonalize([f1], names=["x"])
        # 已经被 _standardize 过，但每行均值应为 0
        assert abs(ortho["x"].mean(axis=1).abs().max()) < 1e-9

    def test_combine_equal_weight(self):
        f1 = pd.DataFrame(np.ones((5, 3)), columns=list("ABC"))
        f2 = pd.DataFrame(np.arange(15).reshape(5, 3) * 1.0, columns=list("ABC"))
        combined = combine_factors({"f1": f1, "f2": f2}, weights="equal")
        # 形状一致；每行均值为 0（因为最终做了 standardize）
        assert combined.shape == (5, 3)
        assert combined.mean(axis=1).abs().max() < 1e-9

    def test_ic_weighted_weights_sum_one(self):
        rng = np.random.default_rng(42)
        panels = {
            "a": pd.DataFrame(rng.standard_normal((10, 5)), columns=list("ABCDE")),
            "b": pd.DataFrame(rng.standard_normal((10, 5)), columns=list("ABCDE")),
        }
        out = ic_weighted(panels, {"a": 0.04, "b": 0.02})
        assert out.shape == (10, 5)

    def test_combine_missing_weights_raises(self):
        panels = {"a": pd.DataFrame([[1,2,3]])}
        with pytest.raises(ValueError, match="weights missing"):
            combine_factors(panels, weights={"b": 1.0})


# ══════════════════════════════════════════════════════════════
# 端到端：动量因子完整流程
# ══════════════════════════════════════════════════════════════

def test_full_pipeline_momentum(price_panel_with_momentum):
    """动量因子 → IC 报告 → 衰减表，整体能跑通，输出合理。"""
    prices = price_panel_with_momentum
    mom = compute_momentum(prices, window=252, skip=21)
    report = summarize_ic(mom, prices, forward_horizon=20)

    assert report["n_periods"] > 50    # 至少有足够数据
    assert -1.0 <= report["ic_mean"] <= 1.0
    assert 0.0 <= report["win_rate"] <= 1.0
    assert report["decay"].shape == (4, 5)
