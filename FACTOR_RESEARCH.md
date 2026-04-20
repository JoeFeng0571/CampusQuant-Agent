# Factor Research · 因子库与 IC/IR 分析

> **模块**：`factors/` · **Demo 脚本**：`bench/factor_research.py`
> **测试**：`tests/test_factors.py`（24 项全部通过）
> **实测报告**：`bench/results/factor_research_report.md`

---

## 一、为什么做因子研究

多 Agent 投研给单股出研判，量化研究给横截面选股。**因子工程** 是连接这两者的桥梁：

- **因子**（factor）：对"这只股现在处于什么状态"的一个数值刻画
- **IC**（Information Coefficient）：因子排序与未来收益排序的秩相关系数，量化"这个因子到底能不能选股"
- **IC_IR**：IC 均值 / IC 标准差，等价于因子的"信号夏普比"

CampusQuant 的因子库为后续工作打地基：
- 作为组合优化的候选打分
- 作为 Agent 观点之外的第二种"选股输入"
- 作为 Black-Litterman 先验收益的备选来源

---

## 二、五类因子

### 2.1 价值因子 (`factors/value.py`)

| 因子 | 公式 | 含义 |
|---|---|---|
| BP | 股东权益 / 市值 | Fama-French HML 的核心，越高越"便宜" |
| EP | 净利润 / 市值 = 1/PE | 比 PE 线性，亏损股票也可用 |
| SP | 营收 / 市值 = 1/PS | 成长期/亏损期公司仍有判断力 |
| DY | TTM 分红 / 价格 | 股东回报 + 现金流稳健代理 |

### 2.2 质量因子 (`factors/quality.py`)

| 因子 | 公式 | 含义 |
|---|---|---|
| ROE | 净利润 / 净资产 | 巴菲特偏爱 > 15% 连续 10 年 |
| ROIC | NOPAT / 投入资本 | 排除杠杆，更严格的资本回报 |
| 毛利率稳定性 | −std(毛利率, 8 季度) | 取负后"稳 → 高分" |
| CFO/NI | 经营现金流 / 净利润 | > 1 真金白银；< 0.8 警惕纸面利润 |

### 2.3 动量因子 (`factors/momentum.py`)

| 因子 | 公式 | 含义 |
|---|---|---|
| J-K 动量 | $P_{t-K} / P_{t-J} - 1$ | Jegadeesh-Titman (1993)，经典 J=12m, K=1m |
| 短期反转 | $-P_t / P_{t-21} + 1$ | 取负使"跌 → 高分"，合成时符号统一 |
| 多尺度 | 1m / 3m / 12m 同时计算 | 不同时间粒度的信号 |

### 2.4 波动率因子 (`factors/volatility.py`)

| 因子 | 公式 | 含义 |
|---|---|---|
| 已实现波动率 | std(daily_ret, 60d) × √252 | "低波异象"：波动低反而长期跑赢 |
| 下行偏差 | √mean((ret − r)^{-2}) | Sortino 的分母，更反映亏损风险 |
| 最大回撤 | \|min((P − rolling_max) / rolling_max)\| | 过去 252 日最大回撤 |

### 2.5 情绪因子 (`factors/sentiment.py`)

当前只有换手率（流动性/关注度代理）。完整的 NLP 情绪打分留待后续扩展（需接入 FinBERT 或大模型逐日打分）。

---

## 三、IC/IR 理论与实现

### 3.1 Rank IC（截面 Spearman 秩相关）

$$
\text{IC}_t = \text{rank\_corr}(\text{factor}[t, :], \; \text{fwd\_return}[t, :])
$$

用**秩**而非 Pearson 原因：
- 对极端值不敏感
- 消除因子与收益可能存在的非线性单调关系

### 3.2 IC_IR（信息比率）

$$
\text{IC\_IR} = \frac{\overline{\text{IC}_t}}{\text{std}(\text{IC}_t)}
$$

经验阈值：

| IC_IR | 评价 |
|---|---|
| > 1.0 | 强因子 |
| 0.5 – 1.0 | 有实用价值 |
| 0.2 – 0.5 | 弱信号，需正交合成 |
| < 0.2 | 风险 >> 收益，不值得用 |

### 3.3 IC 衰减（decay curve）

同一因子在不同前向持有期（1d / 5d / 10d / 20d）下的 IC。解读：

- IC(1d) 高、IC(20d) 几近 0 → 短期动量/反转信号，需高频调仓
- IC 各期均维持 → 信号持久，调仓频率可降低
- IC 反号 → 一类特殊情况：短期有效但长期反转（典型中国 A 股中长期动量）

### 3.4 t 检验

$$
t = \frac{\overline{\text{IC}}}{\text{std}(\text{IC}) / \sqrt{n}}
$$

|t| > 2 可粗略认为 IC ≠ 0 在统计意义上显著。

---

## 四、正交化（施密特）

多因子面板常出现强相关（比如 mom_63d 与 mom_252d）。直接合成会重复计算同一维信号。

**施密特正交**：保留第一个因子，后续因子减去其对前序因子的横截面 OLS 回归残差：

$$
f_i^{\perp}[t] = f_i[t] - X[t] \cdot \beta_i[t], \quad X[t] = [f_0[t], \ldots, f_{i-1}[t]]
$$

每日独立做一次。每日的横截面就是一次 OLS 回归的样本。

**实际效果**：高度相关（0.8+）的两个因子，正交后相关 < 0.1。

---

## 五、三种合成方式

| 方案 | 权重公式 | 适用 |
|---|---|---|
| 等权 | $w_i = 1/K$ | 最稳健，无参数估计风险。因子数量少或 IC 都不高时首选 |
| IC 加权 | $w_i \propto \|\text{IC}_i\|$（符号用 sign(IC) 修正） | 信号越强权重越大 |
| IC_IR 加权 | $w_i \propto \text{IC\_IR}_i$ | 同时考虑信号强度和稳定性，业界最常用 |

**流程**：
1. 每因子每日横截面标准化（z-score，消除量纲）
2. 按权重加权求和
3. 再做一次横截面标准化（便于分组回测）

---

## 六、A 股实测结果（10 只股，2023-01 ~ 2025-12）

> 完整数据在 `bench/results/factor_research_report.md`

### 6.1 各因子 IC 指标

| 因子 | IC 均值 | IC_IR | t 值 | 胜率 |
|---|---|---|---|---|
| mom_21d | +0.024 | +0.06 | +1.58 | 52.9% |
| mom_63d | −0.070 | **−0.19** | −4.79 | 42.1% |
| mom_252d | −0.153 | **−0.44** | −9.39 | 38.2% |
| reversal_21d | −0.024 | −0.06 | −1.58 | 47.1% |
| neg_vol_60d | −0.033 | −0.08 | −1.99 | 48.2% |
| neg_mdd_252d | −0.093 | −0.25 | −6.29 | 42.6% |

### 6.2 观察

- **短期动量（1 月）弱正相关**：52.9% 胜率，IC_IR +0.06，信号微弱
- **中长期动量（3/12 月）显著反转**：IC_IR 分别 −0.19 / −0.44，**反转效应明显**
  - 这与 A 股"长期反转"现象一致——和美股的"12-1 动量"相反
- **低波/低回撤因子表现弱**：IC_IR −0.08 / −0.25，在本 10 股小池里优势不显著
- **正交 + IC_IR 加权合成** IC_IR = −0.29，主要被长期动量反转主导

### 6.3 方法有效性验证

虽然样本仅 10 只股（横截面小），但 t 检验显著性说明**测量框架本身工作正常**：
- mom_252d 的 t 值 = −9.39，即便小样本也是高度显著的反转信号
- 正交化后相关性下降 —— 验证合成不再重复计数同一维度

---

## 七、工程约束

**当前限制**：
- **基本面因子暂无真实数据**：akshare 只返回最新快照，无历史面板。价值/质量类因子只在 `tests/test_factors.py` 中用合成数据验证
- **股票池小（10 只）**：统计显著性有限，真实研究建议 ≥ 300 只（中证 500 或全市场）
- **情绪因子简化**：目前只有换手率，NLP 打分待后续扩展

**扩展路线**：
- 补基本面历史面板（Tushare Pro / Wind / 聚宽 API）
- 扩大股票池到沪深 300 全成分
- 接入财联社新闻的 FinBERT 情绪打分
- 加入**行业/市值中性化**（去除行业/规模偏差）
- 因子库版本化（每月 rolling 计算 IC 用于下月权重更新）

---

## 八、用法示例

### 8.1 计算单因子 + IC 报告

```python
import pandas as pd
from factors import compute_momentum, summarize_ic

prices = pd.read_parquet("bench/data/ohlcv/a/600519.parquet") \
           .set_index("date")["close"].to_frame("600519")
# ... 加载多只股到同一 DataFrame ...

mom = compute_momentum(prices, window=252, skip=21)
report = summarize_ic(mom, prices, forward_horizon=20)
print(f"IC_IR = {report['ic_ir']:.3f}, win_rate = {report['win_rate']:.1%}")
```

### 8.2 多因子正交化 + 合成

```python
from factors import orthogonalize, combine_factors, ic_ir_weighted

ortho = orthogonalize(
    [mom_21, mom_63, mom_252, rev_21],
    names=["mom_21d", "mom_63d", "mom_252d", "reversal_21d"],
)

ic_ir_stats = {name: ic_ir(rank_ic(p, fwd_ret)) for name, p in ortho.items()}
composite = ic_ir_weighted(ortho, ic_ir_stats)
```

### 8.3 运行真实数据 demo

```bash
python bench/factor_research.py
# → bench/results/factor_research_report.md
# → bench/results/factor_ic_table.csv
```

---

## 九、参考文献

- Jegadeesh, N., & Titman, S. (1993). Returns to Buying Winners and Selling Losers. *Journal of Finance*, 48(1).
- Fama, E. F., & French, K. R. (1993). Common Risk Factors in the Returns on Stocks and Bonds. *Journal of Financial Economics*, 33(1).
- Asness, C., Moskowitz, T. J., & Pedersen, L. H. (2013). Value and Momentum Everywhere. *Journal of Finance*, 68(3).
- Novy-Marx, R. (2013). The Other Side of Value: The Gross Profitability Premium. *Journal of Financial Economics*, 108(1).
- Ang, A., Hodrick, R. J., Xing, Y., & Zhang, X. (2006). The Cross-Section of Volatility and Expected Returns. *Journal of Finance*, 61(1).
- Asness, C. S., Frazzini, A., & Pedersen, L. H. (2019). Quality Minus Junk. *Review of Accounting Studies*, 24.
