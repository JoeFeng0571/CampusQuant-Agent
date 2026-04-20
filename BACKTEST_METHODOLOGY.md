# Walk-Forward Backtest · 方法论与多市场适配

> **模块**：`bench/backtest/walk_forward.py` + `market_rules.py` + `report.py`
> **Demo**：`bench/walk_forward_demo.py` · **测试**：`tests/test_walk_forward.py`（24 项全过）
> **零 API 消耗**：仅读本地 `signals_*.parquet` + OHLCV，纯数值运算

---

## 一、为什么用 Walk-Forward

"In-sample 超收益都是灯下黑"是量化回测的通用毒瘤。传统做法是把三年数据一次性喂给模型，在**同一时间区间**评估——模型可能无意识地吃到了"未来信息"，回测漂亮，真实上线扑街。

**Walk-Forward** 在时间轴上滚动切分：
- 训练窗 `[t-12m, t)`  —— 用于拟合参数（因子权重、校准 Platt、选参等）
- 测试窗 `[t, t+3m)`    —— 完全未见过的时间段，评估绩效
- **测试窗之间不重叠**  —— 避免同一时点被多次计数

两种模式：

| 模式 | 训练窗 | 特点 |
|---|---|---|
| **rolling** | 固定长度往后滑 | 把"训练期市场结构"限制在近期，对快速变化的风格友好 |
| **expanding** | 起点固定终点滑 | 训练样本越来越多，对参数估计更稳定，但可能被"老数据"拖累 |

---

## 二、避免未来函数的三条红线

1. **信号计算只能用 `t` 及以前的数据**
   本模块的 `run_signal_replay` 读已预计算的信号 parquet（v2.2 产出），
   parquet 里的每条 `(date, symbol, action)` 都是在那个 `date` 基础上用历史数据产生，
   不存在前视。

2. **前向收益必须 shift**
   在 `factors/ic_analyzer.py` 里所有 forward return 都用 `.shift(-h)` 的形式构造：
   `ret[t] = price[t+h] / price[t] - 1`。绝不用 `pct_change(h)` 直接接到因子上。

3. **测试窗互不重叠**
   `generate_splits()` 保证 `splits[i+1].test_start >= splits[i].test_end`。

---

## 三、多市场规则适配（CLAUDE.md 硬约束）

CampusQuant 覆盖 A 股 / 港股 / 美股三个市场，每个市场的交易规则差异巨大：

| 规则 | A 股 | 港股 | 美股 |
|---|---|---|---|
| 交易时间 | 9:30-11:30, 13:00-15:00 (北京) | 9:30-12:00, 13:00-16:00 | 22:30-次日 5:00 (冬令时 +1h) |
| **T+N** | **T+1** | T+0 | T+0 |
| **佣金** | 0.025% (低 5 元) | 0.025% (低 3 HKD) | **0%** |
| **印花税** | 0.1% **仅卖方** | 0.1% **双边** | — |
| 过户费 | 0.001% 双边 (沪) | — | — |
| 规费 | — | 交易征费 0.0027% 双边 | **SEC fee 0.00278% 仅卖方** |
| 涨跌幅 | ±10% (主板) / ±20% (创/科) / ±5% (ST) | 无 | 无（个股熔断除外） |
| **最小单位** | **100 股** (1 手) | 1 手各股不同 (默认 100) | **1 股** |

`bench/backtest/market_rules.py::CostModel.compute_cost()` 按 side ∈ {buy, sell} 自动代入对应公式。`classify_market(symbol)` 用符号推断：`.HK` 结尾 → 港股，6 位数字 → A 股，其余字母 → 美股。

### T+1 的工程实现

`PortfolioState.holdings[sym]` 记录 `{qty, buy_date_idx}`。卖出前校验：

```python
if not can_sell_today(buy_date_idx=pos["buy_date_idx"],
                     today_idx=current_date_idx,
                     t_plus=cost_model.t_plus):
    continue   # A 股同日买不能卖，跳过本只
```

买同一只会把 `buy_date_idx` 更新到最新（简化处理；严格 FIFO 可以给每笔买入独立 tag，此处权衡代码复杂度）。

---

## 四、绩效指标

复用 `backtest/metrics.py`：
- CAGR（年化复合增长）
- Sharpe (rf=3%)
- Sortino（仅下行波动）
- Max Drawdown
- Calmar = CAGR / |MDD|
- Volatility（年化）
- 胜率（日级）

额外扩展在 `walk_forward.py::trade_level_stats`：
- **交易级胜率**：FIFO 配对买卖，计算每对配对的 PnL 是否为正
- **盈亏比**：`avg_win / avg_loss`

交易级胜率比日级胜率更能反映"抓机会"的能力——大多数日子不持仓的策略，日级胜率会被大量 0 收益日稀释。

---

## 五、实测结果（真实 Agent 信号回放）

> 完整输出在 `bench/results/walk_forward_report.md`

### 数据

- 信号：`bench/data/signals_v2_alt.parquet`（v2.2 预计算，144 条 rebalance）
- 标的：00700.HK, 09988.HK, 300750, 600036, 600519, NVDA（A 股+港+美混合）
- 期间：2023-01 至 2025-12（实际 walk-forward 测试窗 2024-01 到 2025-10）
- 切分：rolling，12 月训练 + 3 月测试，共 7 个切分

### 关键指标

| 指标 | 策略 | 基准（等权 B&H） |
|---|---|---|
| CAGR | +20.7% | +66.2% |
| 夏普 | **2.10** | 2.30 |
| Max DD | **-4.9%** | -14.2% |
| 交易级胜率 | **84.6%** | — |
| 盈亏比 | **3.26** | — |
| 摩擦成本 | 7,236 (0.114%) | — |

### 解读

- **策略跑输基准**——这是诚实的结果。2024-2025 恰好是 NVDA/宁德时代主升浪，等权长持享尽红利
- **但策略回撤减半**：`-4.93%` vs `-14.19%`，这是风控节奏带来的价值
- **交易级胜率 84%** 说明 Agent 的"买入时点"质量不错，但**HOLD 太多**导致敞口不足
- 关键启发：Agent 应在强趋势期更激进，或搭配趋势跟随信号提升参与率

---

## 六、用法

### 6.1 在现有信号上运行

```bash
python bench/walk_forward_demo.py
# → bench/results/walk_forward_report.md
```

### 6.2 自定义切分

```python
from bench.backtest.walk_forward import run_walk_forward

results, nav, bench = run_walk_forward(
    signals,        # 你的信号 DataFrame
    prices,         # OHLCV close 面板
    train_months=6,
    test_months=1,
    mode="expanding",
    initial_cash=500_000,
)
```

### 6.3 覆盖费用模型（例如大户佣金折扣）

```python
from bench.backtest.market_rules import CostModel
from bench.backtest.walk_forward import run_signal_replay

custom = {
    "600519": CostModel(
        market="A_STOCK", commission_rate=0.00005,  # 万 0.5
        stamp_duty_rate=0.001, min_commission=0,
        slippage_rate=0.0002, min_lot_size=100, t_plus=1,
    ),
}
nav, trades = run_signal_replay(signals, prices, cost_overrides=custom)
```

---

## 七、工程限制

- **不建模跌停/涨停撮合失败**：真实交易中涨停买不到/跌停卖不掉，简化版按收盘价成交
- **全现金账户，不支持融资**：`total weights > 1` 自动归一化到 1
- **日频撮合**：不支持 intraday 盘口，适合日度 rebalance 的策略
- **无股票除权**：`prices` 需已复权（现有 OHLCV 是前复权收盘价）

---

## 八、未来扩展

- **训练窗参与建模**：当前框架预留了训练窗但未使用，可在训练窗做：
  - 因子权重拟合（合成训练期表现最好的因子）
  - Platt 校准器训练（用训练期 (confidence, outcome) 对）
  - 超参搜索（rebalance 频率、止损阈值等）
- **加入 Purge + Embargo**（López de Prado 方法）：训练窗与测试窗之间留 gap，消除信息泄漏
- **集成 Black-Litterman**：把训练窗 calibrated confidence 作为 BL view 权重

---

## 九、参考文献

- López de Prado, M. (2018). *Advances in Financial Machine Learning*. 尤其第 7 章 Cross-Validation in Finance
- Bailey, D. H., & López de Prado, M. (2014). The Deflated Sharpe Ratio
- Harvey, C. R., Liu, Y., & Zhu, H. (2016). ... and the Cross-Section of Expected Returns
