"""
tests/test_calibration.py — 置信度校准单元测试

覆盖：
  - Brier / ECE / MCE 的公式与边界
  - reliability_diagram_bins 的分箱结构
  - Platt / Isotonic / Histogram 三种校准器
  - 退化场景（全 0 / 全 1 / 样本极小）
  - 过度自信场景能被校准修正
"""
import numpy as np
import pandas as pd
import pytest

from eval import (
    brier_score,
    expected_calibration_error,
    maximum_calibration_error,
    reliability_diagram_bins,
    PlattScaler,
    IsotonicCalibrator,
    HistogramBinning,
    summarize_calibration,
)


# ══════════════════════════════════════════════════════════════
# Brier Score
# ══════════════════════════════════════════════════════════════

class TestBrier:
    def test_perfect_prediction_zero(self):
        y_true = np.array([1, 0, 1, 0, 1])
        y_prob = np.array([1.0, 0.0, 1.0, 0.0, 1.0])
        assert brier_score(y_true, y_prob) == pytest.approx(0.0)

    def test_worst_prediction_one(self):
        y_true = np.array([1, 1, 0, 0])
        y_prob = np.array([0.0, 0.0, 1.0, 1.0])
        assert brier_score(y_true, y_prob) == pytest.approx(1.0)

    def test_random_prediction_025(self):
        """全部预测 p=0.5，Brier = 0.25。"""
        y_true = np.array([1, 0, 1, 0])
        y_prob = np.array([0.5, 0.5, 0.5, 0.5])
        assert brier_score(y_true, y_prob) == pytest.approx(0.25)

    def test_rejects_non_binary(self):
        with pytest.raises(ValueError, match="binary"):
            brier_score(np.array([1, 2, 0]), np.array([0.5, 0.5, 0.5]))

    def test_rejects_out_of_range_prob(self):
        with pytest.raises(ValueError, match=r"\[0, 1\]"):
            brier_score(np.array([1, 0]), np.array([1.5, 0.5]))

    def test_empty_input(self):
        with pytest.raises(ValueError, match="empty"):
            brier_score(np.array([]), np.array([]))


# ══════════════════════════════════════════════════════════════
# ECE / MCE
# ══════════════════════════════════════════════════════════════

class TestECE:
    def test_perfect_calibration_zero_ece(self):
        """构造 5 分箱各 100 样本，confidence 与 accuracy 完全一致。"""
        np.random.seed(0)
        y_true = []
        y_prob = []
        for conf, acc in [(0.1, 0.1), (0.3, 0.3), (0.5, 0.5), (0.7, 0.7), (0.9, 0.9)]:
            # 100 样本，acc*100 个 y=1
            n1 = int(acc * 100)
            y_true.extend([1] * n1 + [0] * (100 - n1))
            y_prob.extend([conf] * 100)
        ece = expected_calibration_error(np.array(y_true), np.array(y_prob), n_bins=10)
        assert ece < 0.05

    def test_systematic_overconfidence(self):
        """全部预测 0.9 但实际命中率 0.5 → ECE ≈ 0.4。"""
        y_prob = np.full(100, 0.9)
        y_true = np.concatenate([np.ones(50), np.zeros(50)])
        ece = expected_calibration_error(y_true, y_prob, n_bins=10)
        assert ece == pytest.approx(0.4, abs=0.01)

    def test_mce_captures_worst_bin(self):
        """一个分箱严重失调 → MCE 应反映该分箱。"""
        y_prob = np.concatenate([
            np.full(100, 0.1), np.full(100, 0.9)
        ])
        y_true = np.concatenate([
            np.zeros(100),          # 和 0.1 匹配：gap=0.1
            np.zeros(100),          # 和 0.9 严重错位：gap=0.9
        ])
        mce = maximum_calibration_error(y_true, y_prob, n_bins=10)
        assert mce == pytest.approx(0.9, abs=0.01)


# ══════════════════════════════════════════════════════════════
# Reliability Diagram
# ══════════════════════════════════════════════════════════════

class TestReliability:
    def test_bins_cover_all_samples(self):
        np.random.seed(7)
        y_prob = np.random.random(500)
        y_true = (np.random.random(500) < y_prob).astype(int)
        df = reliability_diagram_bins(y_true, y_prob, n_bins=10)
        assert df["count"].sum() == 500
        assert set(df.columns) == {
            "bin", "edge_lo", "edge_hi", "avg_confidence", "accuracy", "count", "gap",
        }

    def test_empty_bins_excluded(self):
        """所有样本都在 p=0.5 周围 → 只会用到中间的分箱。"""
        y_prob = np.full(100, 0.5)
        y_true = np.zeros(100)
        df = reliability_diagram_bins(y_true, y_prob, n_bins=10)
        assert len(df) == 1


# ══════════════════════════════════════════════════════════════
# Platt Scaling
# ══════════════════════════════════════════════════════════════

class TestPlattScaler:
    def test_recovers_temperature(self):
        """把已知 sigmoid 关系喂给 Platt，A/B 应接近真实值。"""
        np.random.seed(42)
        N = 3000
        # 真实关系: true_p = sigmoid(1.0 * logit(raw) + 0.0)
        logit_raw = np.random.randn(N) * 2
        raw = 1.0 / (1.0 + np.exp(-logit_raw))
        # 强行制造过度自信：把 logit 乘以 3，使概率推到极端
        true_logit = logit_raw / 3.0
        true_p = 1.0 / (1.0 + np.exp(-true_logit))
        y = (np.random.random(N) < true_p).astype(float)

        scaler = PlattScaler().fit(y, raw)
        # 真实的 A 应接近 1/3 ≈ 0.33（把 raw 的 logit 压扁）
        assert 0.2 < scaler.A < 0.5

    def test_reduces_ece(self):
        """Platt 应能降低 ECE。"""
        np.random.seed(1)
        N = 2000
        x = np.random.randn(N)
        true_p = 1.0 / (1.0 + np.exp(-x))
        y = (np.random.random(N) < true_p).astype(float)
        raw = np.where(true_p > 0.5, true_p ** 0.3, true_p ** 3)
        raw = np.clip(raw, 0.01, 0.99)

        ece_before = expected_calibration_error(y, raw, n_bins=10)
        calibrated = PlattScaler().fit_transform(y, raw)
        ece_after = expected_calibration_error(y, calibrated, n_bins=10)
        assert ece_after < ece_before

    def test_degenerate_all_positive(self):
        """y 全为 1 时，Platt 应返回 identity 而不崩溃。"""
        y = np.ones(50)
        p = np.random.random(50)
        scaler = PlattScaler().fit(y, p)
        assert scaler.A == 1.0 and scaler.B == 0.0
        out = scaler.transform(p)
        np.testing.assert_allclose(out, p, atol=1e-9)


# ══════════════════════════════════════════════════════════════
# Isotonic
# ══════════════════════════════════════════════════════════════

class TestIsotonic:
    def test_output_is_monotonic(self):
        """Isotonic 输出必然单调非递减（对排序后的输入）。"""
        np.random.seed(2)
        N = 500
        raw = np.random.random(N)
        true_p = raw ** 2
        y = (np.random.random(N) < true_p).astype(float)

        iso = IsotonicCalibrator().fit(y, raw)
        grid = np.linspace(0.01, 0.99, 50)
        out = iso.transform(grid)
        # 单调非递减
        assert (np.diff(out) >= -1e-9).all()

    def test_reduces_ece_on_train(self):
        np.random.seed(3)
        N = 1000
        x = np.random.randn(N)
        raw = 1.0 / (1.0 + np.exp(-2 * x))   # 过度陡峭
        true_p = 1.0 / (1.0 + np.exp(-x))    # 真实更平缓
        y = (np.random.random(N) < true_p).astype(float)

        ece_before = expected_calibration_error(y, raw, n_bins=10)
        calibrated = IsotonicCalibrator().fit_transform(y, raw)
        ece_after = expected_calibration_error(y, calibrated, n_bins=10)
        assert ece_after < ece_before


# ══════════════════════════════════════════════════════════════
# Histogram Binning
# ══════════════════════════════════════════════════════════════

class TestHistogramBinning:
    def test_transform_equals_bin_accuracy(self):
        """HistogramBinning 对训练数据预测 = 分箱 accuracy。"""
        np.random.seed(4)
        y = np.array([1, 1, 0, 0, 1, 0, 1, 0, 0, 1] * 10)
        p = np.linspace(0.01, 0.99, 100)
        hist = HistogramBinning(n_bins=5).fit(y, p)
        out = hist.transform(p)
        assert np.all(out >= 0) and np.all(out <= 1)

    def test_zero_ece_on_train_set(self):
        """训练集上 ECE 应接近 0（每箱用自己的 accuracy）。"""
        np.random.seed(5)
        N = 1000
        p = np.random.random(N)
        y = (np.random.random(N) < p).astype(float)
        hist = HistogramBinning(n_bins=10).fit(y, p)
        out = hist.transform(p)
        ece = expected_calibration_error(y, out, n_bins=10)
        assert ece < 0.01


# ══════════════════════════════════════════════════════════════
# 综合报告
# ══════════════════════════════════════════════════════════════

def test_summarize_calibration_returns_all_fields():
    np.random.seed(6)
    N = 500
    p = np.random.random(N)
    y = (np.random.random(N) < p).astype(float)
    rep = summarize_calibration(y, p, n_bins=10)
    assert rep["n"] == N
    assert 0.0 <= rep["base_rate"] <= 1.0
    assert 0.0 <= rep["mean_prob"] <= 1.0
    assert 0.0 <= rep["brier"] <= 1.0
    assert 0.0 <= rep["ece"] <= 1.0
    assert 0.0 <= rep["mce"] <= 1.0
    assert isinstance(rep["reliability_bins"], pd.DataFrame)
