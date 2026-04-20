# Confidence Calibration · 置信度校准方法论

> **模块**：`eval/calibration.py` · **Demo 脚本**：`bench/calibration_demo.py`
> **测试**：`tests/test_calibration.py`（19 项全部通过）
> **Pydantic 模型**：`graph/state.py::CalibrationReport`

---

## 一、为什么做校准

多 Agent 的 `AnalystReport.confidence ∈ [0, 1]` 是系统对自身判断的主观信心，但：

- 大模型/Agent 系统普遍**过度自信**（Guo et al. 2017 观察到 CNN 也如此）
- 未经校准的 confidence 作为下游权重会放大错误
- v2.3 已加的"置信度惩罚"只是启发式，没有量化评估

本模块提供**评估 + 再校准**两套工具：
- 评估：Brier / ECE / MCE / Reliability Diagram，用数字说清楚"模型自信度值不值这个价"
- 再校准：Platt / Isotonic / Histogram 三种方法各自适合不同数据量和失调形态

---

## 二、三个核心评估指标

### 2.1 Brier Score

$$
\text{Brier} = \frac{1}{N} \sum_{i=1}^{N} (p_i - y_i)^2 \quad y_i \in \{0, 1\}
$$

| 值 | 解读 |
|---|---|
| 0.00 | 完美预测 |
| 0.25 | 随机猜（p=0.5，base rate=0.5） |
| 1.00 | 全错 |

Brier 同时惩罚**判别能力低**和**校准失调**，是最通用的综合指标。

### 2.2 ECE — Expected Calibration Error

$$
\text{ECE} = \sum_{b=1}^{B} \frac{|n_b|}{N} \cdot \left| \text{acc}(b) - \text{conf}(b) \right|
$$

按分箱的加权平均偏差：每一箱的 `accuracy` 与平均 `confidence` 的差，按该箱样本数加权。

| ECE | 评价 | 处理 |
|---|---|---|
| < 0.05 | 校准良好 | 无需处理 |
| 0.05 – 0.10 | 可接受 | 可选校准 |
| > 0.10 | 严重失调 | 应该再校准 |

### 2.3 MCE — Maximum Calibration Error

$$
\text{MCE} = \max_b \left| \text{acc}(b) - \text{conf}(b) \right|
$$

对最坏分箱敏感。ECE 低但 MCE 高意味着"平均对、但存在黑洞箱"。生产场景建议 MCE < 0.15。

### 2.4 Reliability Diagram

每个分箱画一个点 $(\text{confidence}, \text{accuracy})$。**完美校准时点连成 y=x 对角线**。

- 点都在对角线**下方**（acc < conf）→ 过度自信
- 都在**上方**（acc > conf） → 过度谦虚
- 左高右低 → 低置信高准确（奇怪但偶有见）
- 高箱偏差大 → 模型在"我很确定"时反而容易错

---

## 三、三种校准器

### 3.1 Platt Scaling — 两参数 sigmoid

$$
p_{\text{cal}} = \sigma(A \cdot \text{logit}(p_{\text{raw}}) + B)
$$

参数 $A, B$ 用带 Platt 平滑目标的负对数似然优化：

$$
\hat{y}_i = \begin{cases}
\frac{N_+ + 1}{N_+ + 2} & y_i = 1 \\
\frac{1}{N_- + 2}       & y_i = 0
\end{cases}
$$

**优点**：只有两个参数，小样本（N < 500）也稳定
**缺点**：假设失调是 sigmoid 形式，对非单调或多峰失调失效

**参数物理意义**：
- $A \approx 1/T$ 的作用（类似温度缩放），$A < 1$ 把极端概率向 0.5 推
- $B$ 是整体偏置

### 3.2 Isotonic Calibration — 保序回归

非参数单调拟合：
1. 按 $p_{\text{raw}}$ 排序样本
2. 对 $y$ 跑 **Pool Adjacent Violators**（PAV）算法，得到最接近原序列的非递减序列
3. 新样本预测用分段线性插值

**优点**：能拟合任意单调失调形态
**缺点**：样本 < 1000 时容易阶梯状过拟合

### 3.3 Histogram Binning — 分箱频率

把 [0, 1] 等分为 $B$ 个箱，每箱用该箱实际命中率替代预测。

**优点**：极简、工程极稳健
**缺点**：输出离散，相邻箱差异明显

---

## 四、合成数据实测对比

> 完整数据在 `bench/results/calibration_report.md`

**设定**：过度自信 Agent (`raw_p = sigmoid(3x)` vs `true_p = sigmoid(x)`)，4000 样本，70/30 train/test。

### 测试集校准指标

| 方法 | Brier | ECE | MCE | 改善（vs 未校准）|
|---|---|---|---|---|
| uncalibrated | 0.2104 | 0.1583 | 0.2756 | — |
| platt        | 0.1832 | 0.0490 | 0.1130 | ECE −69% |
| isotonic     | 0.1827 | 0.0356 | 0.0707 | ECE **−78%** |
| histogram    | 0.1865 | 0.0476 | 0.0966 | ECE −70% |

### 结论
- 三种方法都能显著降低测试集 ECE（无过拟合）
- Isotonic 最灵活，ECE/MCE 表现最好
- Platt 作为两参数拟合，稳定性和可解释性最强
- Histogram 在小数据集更稳健，但输出离散

---

## 五、CampusQuant 落地路径

### 5.1 数据收集（已具备）

Agent 每次分析都会产出 `recommendation` + `confidence`。需要把这些与**事后结果**配对：

```
AnalystReport.confidence  →  (predicted)
20 日后的实际走势         →  (actual)
    • BUY  且后续收益 > 0%  → y=1
    • SELL 且后续收益 < 0%  → y=1
    • 其余                  → y=0
    • HOLD 跳过（非方向性预测）
```

### 5.2 校准节点（未来实现）

```python
# graph/nodes.py 追加（demo 伪码）
async def calibration_node(state: TradingGraphState) -> dict:
    scaler = load_calibrator()                # 周期性训练
    raw = state["analyst_report"]["confidence"]
    calibrated = scaler.transform([raw])[0]
    return {"confidence_calibrated": calibrated}
```

### 5.3 下游消费

- **Black-Litterman view matrix**：Ω 矩阵的对角元 ∝ 1 / calibrated_confidence，让模型对自身置信的估计直接影响观点权重
- **Risk Node**：仓位决策中把 calibrated confidence 作为额外权重
- **前端展示**：Reliability Diagram 作为透明度组件，让用户看到"模型说 80% 自信时实际命中多少次"——这本身就是极好的教学材料

### 5.4 再校准触发条件

- ECE > 0.10 持续 2 周 → 自动再校准
- 样本量不足时回退到 Platt（更稳）
- 校准前后 Brier 无改善 → 保留原始 confidence

---

## 六、工程注意事项

- **不要在训练集上评估校准**：Isotonic/Histogram 在训练集 ECE 近乎 0 是假象，必须独立 holdout
- **分箱策略选择**：`uniform` 适合 confidence 分布均匀时；若分布集中在 0.6-0.9 之间，`quantile` 分位更有意义
- **样本量门槛**：< 300 样本时 ECE 方差极大，校准意义有限
- **HOLD 样本处理**：校准是二分类问题，HOLD 不适合直接参与；可单独评估 HOLD 的"保守度"

---

## 七、参考文献

- Brier, G. W. (1950). Verification of Forecasts Expressed in Terms of Probability. *Monthly Weather Review*, 78(1).
- Platt, J. (1999). Probabilistic Outputs for Support Vector Machines and Comparisons to Regularized Likelihood Methods. *Advances in Large Margin Classifiers*.
- Zadrozny, B., & Elkan, C. (2002). Transforming Classifier Scores into Accurate Multiclass Probability Estimates. *KDD'02*.
- Guo, C., Pleiss, G., Sun, Y., & Weinberger, K. Q. (2017). On Calibration of Modern Neural Networks. *ICML*.
- Naeini, M. P., Cooper, G. F., & Hauskrecht, M. (2015). Obtaining Well Calibrated Probabilities Using Bayesian Binning. *AAAI*.
