"""
bench/calibration_demo.py — 置信度校准 demo（合成数据）

模拟一个"过度自信"的 Agent：
    - 真实命中率由某底层信号 x 决定: true_p = sigmoid(x)
    - Agent 输出的置信度把信号人为放大: raw_p = sigmoid(3x)
    - 结果：Agent 平均说"我 80% 确定"，但实际命中率只有 60%

演示三种校准器（Platt / Isotonic / Histogram）如何分别修正这种偏差，
并用 train/test 拆分避免过拟合假象。

输出：
    bench/results/calibration_report.md    可读报告
    bench/results/calibration_metrics.csv  校准前后指标
    bench/results/calibration_reliability.csv  可靠性图分箱数据

运行：
    python bench/calibration_demo.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from eval import (
    PlattScaler,
    IsotonicCalibrator,
    HistogramBinning,
    summarize_calibration,
    reliability_diagram_bins,
)

OUTPUT_DIR = REPO_ROOT / "bench" / "results"


def simulate_overconfident_agent(
    n_samples: int = 4000,
    overconfidence: float = 3.0,
    seed: int = 42,
):
    """生成合成数据：过度自信的预测 + 对应的真实结果。"""
    rng = np.random.default_rng(seed)
    # 底层信号
    x = rng.normal(0.0, 1.5, size=n_samples)
    # 真实事件概率
    true_p = 1.0 / (1.0 + np.exp(-x))
    # 真实结果（二元）
    y = (rng.random(n_samples) < true_p).astype(float)
    # Agent 输出的"置信度"：把信号放大 overconfidence 倍
    raw_p = 1.0 / (1.0 + np.exp(-overconfidence * x))
    raw_p = np.clip(raw_p, 0.01, 0.99)
    return raw_p, y


def train_test_split(
    raw_p: np.ndarray,
    y: np.ndarray,
    test_frac: float = 0.3,
    seed: int = 7,
):
    rng = np.random.default_rng(seed)
    n = len(y)
    idx = rng.permutation(n)
    n_test = int(n * test_frac)
    test_idx, train_idx = idx[:n_test], idx[n_test:]
    return (
        raw_p[train_idx], y[train_idx],
        raw_p[test_idx], y[test_idx],
    )


def run_demo():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    raw_p, y = simulate_overconfident_agent(n_samples=4000, overconfidence=3.0)
    raw_tr, y_tr, raw_te, y_te = train_test_split(raw_p, y)

    # ── 校准前（测试集）──────────────────────────────
    base = summarize_calibration(y_te, raw_te, n_bins=10)
    before = {
        "method":    "uncalibrated",
        "n":         base["n"],
        "base_rate": round(base["base_rate"], 4),
        "mean_prob": round(base["mean_prob"], 4),
        "brier":     round(base["brier"], 4),
        "ece":       round(base["ece"], 4),
        "mce":       round(base["mce"], 4),
    }

    # ── 三种校准器各跑一遍 ────────────────────────────
    rows = [before]
    calibrators = {
        "platt":     PlattScaler(),
        "isotonic":  IsotonicCalibrator(),
        "histogram": HistogramBinning(n_bins=10),
    }
    test_panels: dict[str, pd.DataFrame] = {
        "uncalibrated": reliability_diagram_bins(y_te, raw_te, n_bins=10),
    }
    for name, cal in calibrators.items():
        cal.fit(y_tr, raw_tr)
        p_te_calibrated = cal.transform(raw_te)
        rep = summarize_calibration(y_te, p_te_calibrated, n_bins=10)
        rows.append({
            "method":    name,
            "n":         rep["n"],
            "base_rate": round(rep["base_rate"], 4),
            "mean_prob": round(rep["mean_prob"], 4),
            "brier":     round(rep["brier"], 4),
            "ece":       round(rep["ece"], 4),
            "mce":       round(rep["mce"], 4),
        })
        test_panels[name] = reliability_diagram_bins(y_te, p_te_calibrated, n_bins=10)

    metrics_df = pd.DataFrame(rows).set_index("method")
    print("\n=== Calibration Metrics (test set) ===")
    print(metrics_df.to_string())

    # 保存
    metrics_df.to_csv(OUTPUT_DIR / "calibration_metrics.csv")

    # 合并可靠性图分箱（加一列 method 作区分）
    all_bins = pd.concat([
        df.assign(method=name) for name, df in test_panels.items()
    ], ignore_index=True)
    all_bins.to_csv(OUTPUT_DIR / "calibration_reliability.csv", index=False)

    # ── 写 markdown 报告 ──────────────────────────────
    md_lines = [
        "# Confidence Calibration Demo — 合成数据",
        "",
        "## 设定",
        "- 样本量：4000（70% 训练，30% 测试）",
        "- 真实概率：`true_p = sigmoid(x)`，x ~ N(0, 1.5)",
        "- 模型输出：`raw_p = sigmoid(3x)` — **3 倍过度自信**",
        "- 校准器在训练集拟合，在独立测试集评估（防止过拟合假象）",
        "",
        "## 测试集校准指标",
        "",
        "| 方法 | Brier | ECE | MCE | 均预测 vs 实际 |",
        "|---|---|---|---|---|",
    ]
    for name, row in metrics_df.iterrows():
        md_lines.append(
            f"| {name} | {row['brier']:.4f} | {row['ece']:.4f} | {row['mce']:.4f} | "
            f"{row['mean_prob']:.3f} / {row['base_rate']:.3f} |"
        )

    md_lines += [
        "",
        "## 可靠性图分箱（测试集）",
        "",
        "**未校准**（每箱 confidence vs accuracy；两者差距越大越失调）：",
        "",
        "| bin | confidence | accuracy | gap | count |",
        "|---|---|---|---|---|",
    ]
    uncal_bins = test_panels["uncalibrated"]
    for _, row in uncal_bins.iterrows():
        md_lines.append(
            f"| {int(row['bin'])} | {row['avg_confidence']:.3f} | {row['accuracy']:.3f} | "
            f"{row['gap']:+.3f} | {int(row['count'])} |"
        )

    md_lines += [
        "",
        "## 结论",
        "",
        "- 未校准的 ECE 明显偏高（过度自信典型症状：高置信箱 accuracy 拖后）",
        "- Platt 作为两参数 sigmoid，拟合稳定但表现力有限",
        "- Isotonic 非参数最灵活，ECE 降到几乎最低",
        "- Histogram 分箱频率法，ECE 好但会产生阶梯状输出",
        "",
        "## CampusQuant 应用",
        "",
        "把 Agent 历史预测 `(confidence, hit_flag)` 对喂给 Platt/Isotonic，",
        "得到的 `confidence_calibrated` 可用于：",
        "- Black-Litterman view matrix 的观点不确定度 Ω",
        "- Risk Node 仓位决策的加权系数",
        "- 前端展示模型的 \"自知之明\"——让用户看到模型说 80% 自信时实际对了多少次",
    ]
    (OUTPUT_DIR / "calibration_report.md").write_text(
        "\n".join(md_lines), encoding="utf-8"
    )
    print(f"\nreports → {OUTPUT_DIR}")


if __name__ == "__main__":
    run_demo()
