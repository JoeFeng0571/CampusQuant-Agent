"""
eval — 预测评估与置信度校准

核心模块：
    calibration.py — Brier / ECE / MCE / 可靠性图 + Platt / Isotonic / Histogram 三种校准器

用法：
    from eval import brier_score, expected_calibration_error, PlattScaler

    scaler = PlattScaler().fit(y_true, y_raw_prob)
    y_calibrated = scaler.transform(y_raw_prob)

    before = expected_calibration_error(y_true, y_raw_prob)
    after  = expected_calibration_error(y_true, y_calibrated)
"""
from eval.calibration import (
    brier_score,
    expected_calibration_error,
    maximum_calibration_error,
    reliability_diagram_bins,
    PlattScaler,
    IsotonicCalibrator,
    HistogramBinning,
    summarize_calibration,
)

__all__ = [
    "brier_score",
    "expected_calibration_error",
    "maximum_calibration_error",
    "reliability_diagram_bins",
    "PlattScaler",
    "IsotonicCalibrator",
    "HistogramBinning",
    "summarize_calibration",
]
