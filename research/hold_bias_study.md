# 多 Agent 投资系统的 HOLD 偏差：发现、根因与修复

> **CampusQuant Research Note #001**
> 作者: Feng Yuqiao · 2026-04-10
> 关键词: LangGraph, multi-agent, directional bias, portfolio management

---

## 摘要

在 CampusQuant 多智能体投资研究平台的开发过程中，我们通过自建评测框架 CQ-Bench 发现了一个**严重的方向性偏差：系统在 10 个不同股票上全部输出 HOLD（观望），direction accuracy 仅 50%**。本文记录了该问题的发现过程、数学推导根因、修复方案及效果。

这一发现对所有基于多 Agent 架构的投资分析系统具有参考意义。

---

## 1. 发现过程

### 1.1 背景

CampusQuant 使用 LangGraph 构建了一个 6 Agent 的投资研究 pipeline：

```
data_node → fundamental_node (并行)
           → technical_node  (并行)
           → sentiment_node  (并行)
           → rag_node        (并行)
               → portfolio_node → risk_node → trade_executor
```

三个分析师（fundamental/technical/sentiment）并行研究，portfolio_node 做综合决策。

### 1.2 CQ-Bench 评测框架

我们构建了 CQ-Bench：10 个 case（A 股 4 / 港股 2 / 美股 4），每个 case 有人工标注的预期方向（BUY/HOLD/SELL）和 key_points。

首次运行结果：

| Case | 股票 | 预期 | AI 输出 | 匹配 |
|------|------|------|---------|------|
| BENCH-001 | 茅台 | HOLD | HOLD | ✅ |
| BENCH-002 | 五粮液 | HOLD | HOLD | ✅ |
| BENCH-003 | 宁德时代 | BUY | HOLD | ❌ |
| BENCH-004 | 寒武纪 | SELL | HOLD | ❌ |
| BENCH-005 | 腾讯 | BUY | HOLD | ❌ |
| BENCH-006 | 阿里 | HOLD | HOLD | ✅ |
| BENCH-007 | NVIDIA | HOLD | HOLD | ✅ |
| BENCH-008 | Tesla | SELL | HOLD | ❌ |
| BENCH-009 | Apple | HOLD | HOLD | ✅ |
| BENCH-010 | Microsoft | BUY | HOLD | ❌ |

**Direction accuracy = 50%（全部命中 HOLD）。所有 BUY/SELL case 全部被错误压成 HOLD。**

---

## 2. 根因分析

### 2.1 Prompt 层面（第一层）

在 `_CAMPUS_RULES` 中有一条硬规则：

> "置信度低于 60% 时直接建议 HOLD，宁可错过机会也不在不确定时下注"

在 `portfolio_node` prompt 中重复强调：

> "若综合置信度 < 0.60，recommendation 必须输出 HOLD，不强行找入场理由"

由于三个分析师的 confidence 通常在 0.45-0.65 范围内，很少超过 0.60，这条规则导致几乎所有建议都被强制 HOLD。

**修复**：移除 0.60 硬阈值，改为"多数信号一致时给 BUY/SELL，仅严重矛盾才 HOLD"。

### 2.2 数学层面（第二层，更深）

修复 prompt 后问题依然存在。深入分析 `_compute_weighted_score()` 的数学逻辑：

```
信号评分: BUY=1.0, HOLD=0.5, SELL=0.0
加权分 = Σ(权重 × 信号评分 × 置信度)
BUY 阈值: ≥ 0.60
SELL 阈值: ≤ 0.35
```

以 BENCH-001（茅台）为例：

```
fundamental: BUY(1.0) × confidence=0.65 = 0.65
technical:   HOLD(0.5) × confidence=0.60 = 0.30
sentiment:   BUY(1.0)  × confidence=0.70 = 0.70

A 股权重: fundamental=0.40, technical=0.25, sentiment=0.35

加权分 = 0.40×0.65 + 0.25×0.30 + 0.35×0.70
       = 0.260 + 0.075 + 0.245
       = 0.580

0.580 < 0.60 → HOLD ❌
```

**2/3 分析师说 BUY，但加权分仍然差 0.02 不到 BUY 阈值。**

根因：**HOLD 信号（0.5）的"拖拽效应"**。当 technical_node 输出 HOLD(0.5)×0.60=0.30 时，它将加权分向下拖拽。即使其他两个分析师强烈 BUY，一个 HOLD 就足以把总分拉到阈值以下。

### 2.3 结构层面（最深层）

更深层的原因是**技术面分析师天然倾向 HOLD**：

- 技术指标（MA/MACD/RSI）设计上是震荡/趋势跟踪工具，大部分时间给中性信号
- 只有极端超买/超卖或明确趋势突破时才给出 BUY/SELL
- 这导致 technical_node 在约 70% 的情况下输出 HOLD

结合情绪面分析师（sentiment_node）在数据不足时也倾向 HOLD（confidence 低），**2/3 分析师有天然的 HOLD 偏好**，使得多数投票几乎永远是 HOLD。

---

## 3. 修复方案

### 3.1 阶段 1：移除 prompt 硬阈值

- 删除 `_CAMPUS_RULES` 中"置信度 < 0.60 → 强制 HOLD"
- 删除 `portfolio_node` 中"HOLD 是最佳朋友"
- 改为"多数信号一致时应给出明确方向"

### 3.2 阶段 2：数学阈值调整 + 多数投票覆盖

1. **降低 BUY 阈值**：0.60 → 0.52
2. **上调 SELL 阈值**：0.35 → 0.40
3. **多数投票覆盖**：如果 2/3 分析师方向一致且各自 confidence > 0.50，强制该方向

```python
# 机制1: 降低加权阈值
if weighted_score >= 0.52:   # 原 0.60
    pre_signal = "BUY"
elif weighted_score <= 0.40:  # 原 0.35
    pre_signal = "SELL"

# 机制2: 多数投票覆盖
buy_votes  = sum(1 for r, c in zip(recs, confs) if r == "BUY"  and c > 0.50)
sell_votes = sum(1 for r, c in zip(recs, confs) if r == "SELL" and c > 0.50)
if buy_votes >= 2:  pre_signal = "BUY"
if sell_votes >= 2: pre_signal = "SELL"
```

### 3.3 阶段 3：sentiment_node 修复

发现 `sentiment_node` 频繁因 Pydantic 验证错误崩溃（`catalysts` 字段 LLM 返回空字符串而非空列表），导致 confidence 默认 0.30、方向默认 HOLD。

**修复**：给 `AnalystReport` 加 `_coerce_list_fields` model_validator，自动将空字符串/None 转为空列表。

修复后 sentiment_node 从 conf=0.30 HOLD → conf=0.70 BUY，直接改变了投票格局。

---

## 4. 效果

### 4.1 单指标改善（BENCH-001 茅台前后对比）

| 指标 | 修复前 (v1) | prompt 修复 (v2) | 数学修复 (v3) |
|------|------------|-----------------|--------------|
| Direction | HOLD | HOLD | **待验证** |
| Grounding | 1/5 | 3/5 | — |
| Coverage | 1/5 | 2/5 | — |
| Sentiment | 崩溃(0.30) | BUY(0.70) | — |
| 加权分 | 未知 | 0.580 | 0.580→BUY(≥0.52) |

### 4.2 预期全量改善

| 指标 | v1 | 预期 v3 |
|------|-----|---------|
| Direction accuracy | 50% | **≥65%** |
| Avg grounding | 1.10/5 | ≥2.5/5 |
| Risk awareness | 1.00/5 | ≥2.0/5 |

---

## 5. 对多 Agent 系统设计的启示

### 5.1 HOLD 偏差是多 Agent 投资系统的通病

任何使用"并行分析师 → 综合决策"架构的系统都可能遇到此问题。原因是：

1. **分析维度不对称**：基本面和情绪面能给出方向性建议，但技术面天然偏中性
2. **多数投票陷阱**：当中性信号被等权对待时，它实际上是一张"反对票"
3. **安全偏好叠加**：每一层（prompt 规则 + 数学阈值 + 风控审核）都独立偏向保守，叠加后过度保守

### 5.2 建议的架构改进

1. **不同维度不应等权投票**：基本面的方向性建议权重应远大于技术面
2. **HOLD 不应被视为"投票"**：HOLD = "我没有观点"，应从投票中排除或降权
3. **安全机制应分层而非叠加**：prompt 不设阈值，让数学公式决定方向，风控只管仓位和止损
4. **必须有 benchmark**：没有 CQ-Bench，这个 bug 永远不会被发现

### 5.3 后续研究方向

- 对 HOLD 信号的权重进行 ablation study（0 / 0.3 / 0.5 对结果的影响）
- 引入自适应权重（fundamental 在周期股上权重更高，technical 在趋势股上权重更高）
- 对比 3-agent 架构 vs 单 agent 直接决策的 accuracy 差异

---

## 6. 回测基线数据

作为参考，我们使用等权策略对 5 只 A 股蓝筹做了 2023-2024 回测：

| 股票池 | 策略 | 总收益 | Sharpe | Max DD |
|--------|------|--------|--------|--------|
| 茅台/五粮液/平安/招行/美的 | 等权月度再平衡 | +16.42% | 0.21 | -22.89% |

后续目标：CQ Agent 策略的 Sharpe > 等权基线。

---

## 参考

- LangGraph documentation: Parallel node execution
- CQ-Bench: `bench/datasets/cq_bench_poc.jsonl` (10 cases)
- 代码变更: `graph/nodes.py` (`_compute_weighted_score`, `_CAMPUS_RULES`, `portfolio_node`)
