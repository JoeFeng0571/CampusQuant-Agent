# Portfolio Optimizer · 方法论与实现

> **模块**：`portfolio/` · **端点**：`POST /api/v1/portfolio/optimize`
> **测试**：`tests/test_portfolio_optimizer.py`（21 项全部通过）
> **依赖**：numpy + scipy.optimize（无 cvxpy，避开 Windows 编译问题）

---

## 一、为什么做组合优化

CampusQuant 的多 Agent 分析对**单一标的**输出研判，但真实投资决策面对的是**一篮子候选股**。本模块把量化投资的三种经典组合方法带进来：

- **Markowitz 均值方差**：最优化风险收益权衡的起点
- **风险平价**：不依赖收益预测，在跨市场/跨策略配置时更稳健
- **Black-Litterman**：**本项目特色** — 把多 Agent 的研判结果作为 view matrix，与市场均衡先验贝叶斯合成

---

## 二、三种方法的核心公式

### 2.1 Markowitz 均值方差

Markowitz (1952) 的二次效用最大化问题：

$$
\max_w \; w^\top \mu - \frac{\lambda}{2} w^\top \Sigma w
\quad \text{s.t.} \quad \mathbf{1}^\top w = 1, \; w_i \in [l, u]
$$

| 符号 | 含义 |
|---|---|
| $w \in \mathbb{R}^n$ | 权重向量 |
| $\mu$ | 年化期望收益 |
| $\Sigma$ | 年化协方差矩阵 |
| $\lambda$ | 风险厌恶系数（越大越保守） |

三种等价目标形式（本模块均支持）：
- `objective="utility"`：效用最大化（默认，需要 $\mu$）
- `objective="min_variance"`：仅最小化 $w^\top \Sigma w$（不依赖 $\mu$，适合不信任收益预测的场景）
- `objective="max_sharpe"`：最大化 $\frac{w^\top \mu - r_f}{\sqrt{w^\top \Sigma w}}$

求解器：SLSQP（`scipy.optimize.minimize`），提供解析雅可比以确保线性不等式约束可靠收敛。

### 2.2 风险平价（Equal Risk Contribution）

Maillard-Roncalli-Teïletche (2010)。目标：使每个资产对组合波动率的贡献相等：

$$
\text{RC}_i = w_i \cdot \frac{(\Sigma w)_i}{\sqrt{w^\top \Sigma w}}, \quad \text{RC}_i = \text{RC}_j \; \forall i, j
$$

直接求解该非线性方程组难度较高。本模块采用等价的**对数风险贡献方差最小化**：

$$
\min_w \; \operatorname{Var}\left(\ln(\text{RC}_1), \ldots, \ln(\text{RC}_n)\right)
\quad \text{s.t.} \quad \mathbf{1}^\top w = 1, \; w_i \geq \epsilon
$$

对数形式的两个好处：
- 比例不变，$\log$ 把乘法关系转成加法，更容易做凸优化近似
- 当所有 $\text{RC}_i$ 相等时目标函数严格为 0，作为收敛判据

**不依赖期望收益**是风险平价的最大优势 — 面对不确定的市场预测时，把 $\mu$ 从决策变量里剔除是一种稳健性。

### 2.3 Black-Litterman

Black-Litterman (1992) 的核心是**把主观观点与市场均衡贝叶斯合成**，避免纯 Markowitz 的"极端权重"问题。

**第一步：反向优化得到先验 $\pi$**

从市场资本权重 $w_{\text{mkt}}$ 反推隐含均衡收益：

$$
\pi = \lambda \Sigma w_{\text{mkt}}
$$

这是假设"市场处于均衡状态、市场权重对应最优解"时的隐含期望收益。

**第二步：用 $(P, Q, \Omega)$ 表达观点**

| 符号 | 含义 | CampusQuant 对应 |
|---|---|---|
| $P \in \mathbb{R}^{k \times n}$ | 观点映射矩阵（每行一个观点） | 第 $i$ 行全 0 只在相关资产置 1（绝对观点） |
| $Q \in \mathbb{R}^k$ | 每个观点的预期收益 | BUY → +10%，SELL → −10%（幅度可调） |
| $\Omega \in \mathbb{R}^{k \times k}$ | 观点不确定度（协方差） | He-Litterman：$\Omega_{ii} = \tau \cdot p_i^\top \Sigma p_i / c_i$ |
| $c_i \in (0, 1]$ | 观点置信度 | 直接用 Agent 输出的 `confidence` |

**第三步：后验收益（Bayesian）**

$$
\mu_{\text{BL}} = \left[ (\tau \Sigma)^{-1} + P^\top \Omega^{-1} P \right]^{-1}
              \left[ (\tau \Sigma)^{-1} \pi + P^\top \Omega^{-1} Q \right]
$$

$$
\Sigma_{\text{BL}} = \Sigma + \left[ (\tau \Sigma)^{-1} + P^\top \Omega^{-1} P \right]^{-1}
$$

后验收益 $\mu_{\text{BL}}$ 是先验 $\pi$ 与观点 $Q$ 的加权平均，权重由 $\Omega$ 决定（观点越可信 → 权重越偏向 $Q$）。

**第四步：用后验做 Markowitz 效用最大化**

最终权重 = `markowitz_optimize(μ_BL, Σ_BL, ...)`。

---

## 三、CampusQuant 特色：Agent 观点 → BL view matrix

`portfolio.optimizer.agent_views_to_bl_inputs()` 实现了这个适配层：

```python
signals = [
    {"symbol": "600519.SH", "recommendation": "BUY",  "confidence": 0.78},
    {"symbol": "00700.HK",  "recommendation": "SELL", "confidence": 0.65},
    {"symbol": "AAPL",      "recommendation": "HOLD", "confidence": 0.50},
]
P, Q, c = agent_views_to_bl_inputs(["600519.SH", "00700.HK", "AAPL"], signals)
# P = [[1, 0, 0], [0, 1, 0]]     # HOLD 被过滤
# Q = [+0.10, −0.10]
# c = [0.78, 0.65]
```

映射规则：

| Agent 输出 | BL 观点 |
|---|---|
| `recommendation = "BUY"` | 该资产相对先验超额收益 +10%（幅度可配） |
| `recommendation = "SELL"` | 相对先验超额收益 −10% |
| `recommendation = "HOLD"` | 不生成观点 |
| `confidence ∈ [0, 1]` | 映射到 $\Omega$ 对角元（低置信 = 大 $\Omega_{ii}$ = 观点被稀释） |

这是一个**天然的贝叶斯融合场景**：
- 先验 $\pi$ 来自市场结构（客观、稳定但可能过时）
- 观点 $Q$ 来自 AI 多 Agent 研判（灵敏但可能过激）
- 后验 $\mu_{\text{BL}}$ 在两者之间取最优平衡

---

## 四、API 使用示例

### 4.1 Markowitz 效用最大化（历史数据推导）

```bash
curl -X POST http://127.0.0.1:8000/api/v1/portfolio/optimize \
  -H "Content-Type: application/json" \
  -d '{
    "symbols": ["600519.SH", "000858.SZ", "601318.SH"],
    "method": "markowitz_utility",
    "historical_returns": [[0.01, -0.005, 0.003], ...],
    "risk_aversion": 2.0,
    "weight_upper": 0.5
  }'
```

### 4.2 风险平价（仅需协方差）

```bash
curl -X POST http://127.0.0.1:8000/api/v1/portfolio/optimize \
  -H "Content-Type: application/json" \
  -d '{
    "symbols": ["A", "B", "C"],
    "method": "risk_parity",
    "cov_matrix": [[0.04,0.01,0],[0.01,0.02,0],[0,0,0.01]]
  }'
```

### 4.3 Black-Litterman（Agent 观点驱动）

```bash
curl -X POST http://127.0.0.1:8000/api/v1/portfolio/optimize \
  -H "Content-Type: application/json" \
  -d '{
    "symbols": ["600519.SH", "000858.SZ", "601318.SH"],
    "method": "black_litterman",
    "cov_matrix": [[...], [...], [...]],
    "market_cap_weights": [0.4, 0.3, 0.3],
    "agent_signals": [
      {"symbol": "600519.SH", "recommendation": "BUY", "confidence": 0.82},
      {"symbol": "601318.SH", "recommendation": "SELL", "confidence": 0.60}
    ],
    "view_magnitude": 0.12,
    "risk_aversion": 2.5
  }'
```

---

## 五、返回字段

```json
{
  "symbols": ["600519.SH", "000858.SZ", "601318.SH"],
  "method": "black_litterman",
  "weights": [0.485, 0.318, 0.197],
  "expected_return": 0.094,
  "volatility": 0.163,
  "sharpe": 0.577,
  "risk_contributions": [0.089, 0.051, 0.023],
  "converged": true,
  "message": "Optimization terminated successfully",
  "metadata": {
    "prior_returns": [0.050, 0.030, 0.020],
    "posterior_returns": [0.094, 0.041, 0.005],
    "tau": 0.05,
    "risk_aversion": 2.5,
    "n_views": 2,
    "view_confidences": [0.82, 0.60]
  }
}
```

重点字段：
- `risk_contributions`：Euler 风险贡献度，合计等于 `volatility`
- `metadata.posterior_returns`：BL 后验收益（仅 `black_litterman` 方法返回）—— 审计时可看到 Agent 观点如何改写了先验
- `converged`：优化器是否真正收敛；为 `false` 时权重仍返回但应视作参考

---

## 六、方法选型建议

| 场景 | 推荐方法 | 理由 |
|---|---|---|
| 有可靠 $\mu$ 预测，追求最优风险收益比 | `markowitz_max_sharpe` | 直接最大化夏普 |
| 有 $\mu$ 预测但希望按风险偏好调整 | `markowitz_utility` | $\lambda$ 可调（保守→激进） |
| 不信任任何 $\mu$ 预测 | `markowitz_min_variance` | 仅依赖协方差 |
| 跨市场/跨策略资金配置 | `risk_parity` | 对预测误差最不敏感 |
| 有 Agent/主观观点想融合 | `black_litterman` | 贝叶斯合成先验与观点 |

---

## 七、工程约束与未来工作

**当前限制**：
- 仅支持线性约束（单资产边界、sum=1、行业 cap）
- 不支持卖空（`lb < 0` 理论支持但未充分测试）
- 不支持整数约束（最小成交单位、手数约束）

**可扩展方向**：
- **协方差估计器**：当前用简化 Ledoit-Wolf（收缩到单位阵），可升级为 Ledoit-Wolf 2004 全版本（shrinkage target 用因子模型残差）
- **鲁棒优化**：Worst-case Markowitz（把 $\mu$ 和 $\Sigma$ 置于椭球不确定集内）
- **交易成本**：在目标函数加入 $\|\Delta w\|_1$ 惩罚
- **因子化组合**：用 `factors/` 模块（第一章 2.1 规划）输出因子暴露约束

---

## 八、参考文献

- Markowitz, H. (1952). Portfolio Selection. *The Journal of Finance*, 7(1).
- Black, F., & Litterman, R. (1992). Global Portfolio Optimization. *Financial Analysts Journal*, 48(5).
- He, G., & Litterman, R. (1999). The Intuition Behind Black-Litterman Model Portfolios. *Goldman Sachs Working Paper*.
- Maillard, S., Roncalli, T., & Teïletche, J. (2010). The Properties of Equally Weighted Risk Contribution Portfolios. *Journal of Portfolio Management*, 36(4).
- Ledoit, O., & Wolf, M. (2004). A Well-Conditioned Estimator for Large-Dimensional Covariance Matrices. *Journal of Multivariate Analysis*, 88(2).
- Idzorek, T. (2005). A Step-By-Step Guide to the Black-Litterman Model.
