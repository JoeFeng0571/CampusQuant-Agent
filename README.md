# CampusQuant — 校园财商智能分析平台

> 基于 LangGraph 的多 Agent AI 投资研究平台，面向中国大学生。
> 覆盖 A 股、港股、美股，集成混合 RAG 和金融风控体系。
> 线上访问：**http://47.76.197.100**

**核心设计理念**：大模型输出的概率性不确定性 vs 金融合规的零容忍 — 全部工程设计都在这两者之间寻找可运行的工程解。

**v2.2 亮点**（2026-04 落地，吸收 EMNLP 2025 论文方法）：

- **证据化 Agent 通信**：分析师之间交换的不再是结论摘要，而是代码生成的结构化证据引文（`evidence_citations` 字段），基金经理和辩论裁判看到的是原始数据而不是被处理过的结论 → 减少锚定偏差
- **RAG 共享池**：从 v2.1 的 5 次独立检索降到 1 次宽口径预取 + 代码启发式主题分类（4 bucket），所有下游节点按需读取 → 延迟下降 60-80%
- **决策聚合重写**：对称阈值 ±0.20 替代不对称 0.52/0.40，消除多头偏见；分歧惩罚让三方分散时分数自动向 0 靠拢
- **技术指标升级**：5 档 `tech_signal` 共振打分（MA/MACD/RSI/BOLL/量比 5 维度）+ `BOLL_pct_B` 首次真正计算 + `ATR_percentile_90d` 历史分位数
- **CostTracker 按实验隔离**：通过 `contextvars` 让每次 A/B 实验独立累计 LLM 成本，`hard_stop_cny` 硬停机制防失控烧钱
- **回测底座**：20 支股票 × 2023-2025 三年 × 月度 A/B 框架，¥94 预算跑完完整对比

---

## 目录

- [硬规则与安全红线](#硬规则与安全红线)
- [系统架构（v2.2）](#系统架构v22)
- [核心算法详解](#核心算法详解)
  - [1. 证据化 Agent 通信（P0-A）](#1-证据化-agent-通信p0-a)
  - [2. 决策聚合数学（P0-B）](#2-决策聚合数学p0-b)
  - [3. RAG 共享池（P0-C）](#3-rag-共享池p0-c)
  - [4. 技术指标升级（P1-A）](#4-技术指标升级p1-a)
  - [5. 连续冲突检测（P1-B）](#5-连续冲突检测p1-b)
  - [6. ATR 动态止损（P1-D 部分）](#6-atr-动态止损p1-d-部分)
  - [7. CostTracker 按实验隔离成本累计](#7-costtracker-按实验隔离成本累计)
- [市场数据覆盖](#市场数据覆盖)
- [研报输出格式](#研报输出格式)
- [风控体系](#风控体系)
- [模拟交易引擎](#模拟交易引擎)
- [回测框架（v2.2 新增）](#回测框架v22-新增)
- [API 端点](#api-端点)
- [SSE 事件流](#sse-事件流)
- [双服务器部署](#双服务器部署)
- [快速启动](#快速启动)
- [环境变量配置](#环境变量配置)
- [项目结构](#项目结构)
- [前端页面](#前端页面)
- [常见问题](#常见问题)
- [测试与验证](#测试与验证)
- [技术栈](#技术栈)
- [文档索引](#文档索引)
- [参考文献](#参考文献)

---

## 硬规则与安全红线

这些规则是**代码层强制**的，而不是口头约定：

| 规则 | 强制机制 |
|------|---------|
| **无真实交易所 API** | `api/mock_exchange.py` 是唯一撮合路径，不连接 Binance/CCXT/IBKR |
| **`TradeOrder.simulated` 恒为 True** | `TradeOrder.force_simulated_true` Pydantic validator 在模型层覆盖 LLM 输出 |
| **无加密货币业务** | 市场类型只支持 `A_STOCK / HK_STOCK / US_STOCK` |
| **禁杠杆** | 风控 prompt 明确写入"严禁推荐任何形式的杠杆操作、融资融券、期权投机" |
| **学生风控上限** | 单标的仓位 A 股 ≤15% / 港美 ≤10%，代码层 `_apply_atr_hard_block` 强制截断 |
| **单次亏损上限** | 反算 `position × stop_loss`，超过 ¥3000 自动压缩仓位 |
| **ATR 硬阻断** | ATR% > 8% 直接 REJECTED；ATR% > 5% CONDITIONAL 减半 |

---

## 系统架构（v2.2）

```
┌────────────────────────────────────────────────────────────────┐
│                                                                │
│   START                                                        │
│     ↓                                                          │
│   data_node                                                    │
│     • 拉 OHLCV + 预计算技术指标                                │
│     • 【v2.2 P0-C】末尾调 build_rag_evidence_pool()             │
│       一次宽口径 RAG → 代码分类到 4 bucket                      │
│     ↓                                                          │
│   ┌───────────────┬───────────────┬───────────────┐           │
│   │               │               │               │           │
│   ▼               ▼               ▼               ▼           │
│ fundamental_   technical_    sentiment_      (rag_node        │
│   node         node          node             已删除)         │
│  • get_fund_   • 读 5 档     • get_stock_                     │
│    data        tech_signal    news + LLM                      │
│  • 代码生成    • 代码生成     抽取引文                        │
│    结构化引文    结构化引文   + 子串校验                      │
│  • 读 RAG      • 读 RAG       • 读 RAG                        │
│    pool:fund   pool:tech      pool:sent                       │
│   │               │               │                           │
│   └───────────────┼───────────────┘                           │
│                   ▼                                            │
│             portfolio_node                                     │
│              • _compute_weighted_score                         │
│                (方向分 +1/0/-1 + 对称阈值 ±0.20                │
│                 + 分歧惩罚 + 多数覆盖 0.65)                    │
│              • _conflict_score ≥ 0.60 → debate                │
│              • user_prompt: 证据优先,结论置底                   │
│                ┌───────────┴───────────┐                       │
│    has_conflict│                       │ 无冲突                │
│                ▼                       ▼                       │
│          debate_node                risk_node                  │
│          • 结构化证据对峙           • 四重硬风控               │
│          • 多空交换 evidence_cites  • ATR 动态止损             │
│          • 最多 2 轮                 • 代码层仓位截断          │
│                │                        │                     │
│                └────┐            ┌──────┤                     │
│                     ▼            ▼      │                     │
│              portfolio_node  REJECTED   │                     │
│              (修订仓位)      最多重试 2 │                     │
│                              次         │                     │
│                                         │ APPROVED/           │
│                                         │ CONDITIONAL         │
│                                         ▼                     │
│                                   trade_executor              │
│                                   • 生成 TradeOrder           │
│                                   • simulated=True 恒成立     │
│                                         │                     │
│                                         ▼                     │
│                                       END                     │
│                                                                │
└────────────────────────────────────────────────────────────────┘
```

**关键差异 v2.1 → v2.2**：

| 项 | v2.1 | v2.2 |
|---|------|------|
| Graph 节点数 | 10（含 `rag_node`） | **9**（`rag_node` 删除） |
| RAG 调用次数 / analyze | 5 次（rag_node + 3 分析师 + debate） | **1 次**（data_node 末尾预取） |
| `evidence_citations` | 无 | AnalystReport 新字段 |
| 基本面/技术面引文来源 | 无 | **代码生成**（零 LLM，零幻觉） |
| 舆情引文来源 | 无 | LLM 抽取 + 子串校验 |
| `tech_signal` | 2 档（bullish/bearish/neutral） | **5 档** + 5 维度共振打分 |
| `BOLL_pct_B` | 永远 None（计算缺失） | 真实计算 |
| `conflict_score` | 二元 boolean | **0~1 连续值**，阈值 0.60 |
| 决策阈值 | 0.52 BUY / 0.40 SELL（多头偏见） | **对称 ±0.20** |
| ATR 动态止损 | 无 | `stop = max(LLM, 2×ATR, 5%)` |
| 成本跟踪 | 全局 histogram（无累计） | `CostTracker(run_id)` + contextvar 硬停 |

**控制参数**：辩论循环 ≤ 2 轮 | 风控重试 ≤ 2 次 | 工具调用 ≤ 3 次/节点

---

## 核心算法详解

### 1. 证据化 Agent 通信（P0-A）

> **理论依据**：EMNLP 2025《What Should LLM Agents Share? Auditable Content Supports Belief Revision in Controlled Multi-Agent Deliberation》。论文实证：在 3-agent、2-round 协议下，共享原始证据（policyEvidence）比共享结论（policyHypothesis + Rationale）在多跳 QA 上 EM 提升 +10.1~16.0 pp，87-89% 的 EM 提升来自 W→C 恢复（错误 agent 看到证据后自行修正）。

#### 设计

当前 `portfolio_node` 和 `debate_node` 在 v2.1 看到的是分析师的**结论摘要**（answer + confidence + reasoning），无法独立审核证据真伪，容易被自信的错误结论锚定。v2.2 的改造：

1. **`AnalystReport` 新增 `evidence_citations: List[str]`**
2. **基本面/技术面引文由代码直接生成**（`graph/nodes.py`）：
   ```python
   def build_fundamental_citations(data: dict) -> list[str]:
       """从 fund_data_dict 代码生成引文，零 LLM，零幻觉"""
       cites = []
       if data.get("pe") is not None:
           cites.append(f"PE={data['pe']:.1f}（行业中位数约 {data.get('industry_pe', 'N/A')}）")
       if data.get("roe") is not None:
           cites.append(f"ROE={data['roe']:.1f}%")
       if data.get("revenue_yoy") is not None:
           cites.append(f"营收同比 {data['revenue_yoy']:+.1f}%")
       ...
       return cites[:4]

   def build_technical_citations(indicators: dict) -> list[str]:
       """从 indicators 代码生成引文"""
       cites = []
       if ma5 and ma20 and ma60:
           cites.append(f"MA5={ma5:.2f} / MA20={ma20:.2f} / MA60={ma60:.2f}（{ma_alignment}）")
       if rsi is not None:
           state = "超买" if rsi > 70 else "超卖" if rsi < 30 else "中性"
           cites.append(f"RSI14={rsi:.1f}（{state}）")
       if macd_golden_cross:
           cites.append(f"MACD={macd:.3f} / Signal={sig:.3f}（金叉）")
       if boll_pct_b is not None:
           cites.append(f"BOLL_%B={boll_pct_b:.2f}（{position}）")
       ...
   ```
3. **舆情引文 LLM 抽取 + 子串校验**（非结构化文本无法代码化）：sentiment_node prompt 要求"逐字复制"1-2 条新闻/RAG 原文片段，节点返回后用 `_validate_llm_citations()` 做 60% 字符匹配校验，不通过的引文剔除并记 `evidence_citation_rejection_total` counter。
4. **`portfolio_node` user_prompt 证据优先，结论置底**：把三方的 `evidence_citations` 放在 prompt 最上方，结论字段放到底部并前缀"仅供参考，勿轻易锚定"。
5. **`debate_node` 结构化证据对峙**：bull/bear argument 不再是"立场 + reasoning[:300]"，而是"引文 block + 核心论点"，裁判 LLM 看到的是真实数字对峙而非结论强度对比。

#### 降级路径也生效

分析师节点的 `except` 分支 fallback 也会调用 `build_*_citations()`，即便 LLM 完全失败（超时/token 用尽/欠费），引文仍然从已获取的结构化数据中生成。在 2026-04-14 的 DashScope 欠费期间，我们实测了这个降级路径：所有 LLM 调用失败，但 `evidence_citations` 依然正确产出。

#### 实际效果（600519 茅台 smoke test）

```
fundamental.evidence_citations:
  • ROE=24.6%
  • EPS=51.53

technical.evidence_citations:
  • MA5=1453.94 / MA20=1442.68 / MA60=1431.63（多头排列）
  • RSI14=64.0（中性）
  • MACD=5.160 / Signal=3.882（多头）
  • BOLL_%B=0.54（通道中位）

sentiment.evidence_citations (LLM 抽取):
  • 2026-04-14 贵州茅台：聘任余思明为财务总监并代行董秘职责
  • 2026-04-13 茅台总经理王莉"失联"？公司回应：假的

portfolio_node.reasoning (节选):
  "基本面：公司 ROE 高达 24.6%...当前 PE 约 28.08 倍...EPS 51.53 元
   支撑股价。技术面：股价 1446.9 元站稳 MA20 1442.68 元之上，MA60
   向上发散，MACD 多头信号确认趋势未坏..."
```

基金经理 reasoning 直接引用了 6 条引文的具体数值（`ROE=24.6%`、`PE`、`EPS=51.53`、`MA5`、`MA20`、`MACD`），证明它确实从证据出发而非锚定分析师结论。

---

### 2. 决策聚合数学（P0-B）

**`_compute_weighted_score`**（`graph/nodes.py`）重写，修正 v2.1 的 4 个数学缺陷：

#### v2.1 的问题

1. **置信度与方向耦合有歧义**：`HOLD × conf=1.0 = 0.5` 和 `BUY × conf=0.5 = 0.5` 在 `{BUY=1, HOLD=0.5, SELL=0}` 映射下分数相同，语义不同
2. **BUY/SELL 阈值不对称**（0.52 vs 0.40）：v2.1 注释自己写"降低 BUY 门槛"，主动引入多头偏见
3. **多数投票阈值过松**：0.50 恰好是 fallback 下限，任何时候多数票都覆盖加权分，权重配置形同虚设
4. **无分歧惩罚**：三方方向分散时加权分不会向 0 靠拢

#### v2.2 重写

```python
# 【v2.2 P0-B】对称方向分
_DIR_SCORE = {"BUY": 1.0, "HOLD": 0.0, "SELL": -1.0}

def _compute_weighted_score(fundamental, technical, sentiment, weights, market_type):
    # 方向分 × 置信度 × 权重
    f_contrib = fw * _DIR_SCORE[f_rec] * f_conf  # [-0.4, +0.4] A 股
    t_contrib = tw * _DIR_SCORE[t_rec] * t_conf
    s_contrib = sw * _DIR_SCORE[s_rec] * s_conf
    raw_score = f_contrib + t_contrib + s_contrib  # [-1.0, +1.0]

    # 分歧惩罚: 方向标准差越大 → 越降低幅度
    dir_std = pstdev([f_dir, t_dir, s_dir])  # 0(全同) ~ 0.816(极端分散)
    disagreement_penalty = max(0.67, 1.0 - 0.4 * dir_std)  # 0.67 ~ 1.0
    adjusted_score = raw_score * disagreement_penalty

    # 对称阈值 ±0.20
    if adjusted_score >= 0.20:
        pre_signal = "BUY"
    elif adjusted_score <= -0.20:
        pre_signal = "SELL"
    else:
        pre_signal = "HOLD"

    # 多数投票覆盖: 阈值提到 0.65 (真有信心的多数才覆盖)
    buy_confs = [c for r, c in recs if r == "BUY"]
    if len(buy_confs) >= 2 and mean(buy_confs) >= 0.65:
        pre_signal = "BUY"
    ...
```

#### 市场差异化权重

| 市场 | 基本面 | 技术面 | 情绪面 | 侧重 |
|------|--------|--------|--------|------|
| A 股 | 40% | 25% | 35% | 政策驱动 + 景气度 |
| 港股 | 55% | 20% | 25% | 价值投资 + FCF + 分红 |
| 美股 | 50% | 25% | 25% | EPS + FCF 主导 |

#### 效果对比（7 个 edge case 单元测试）

| 场景 | v2.1 输出 | v2.2 输出 | 改进 |
|---|---|---|---|
| 三方全 BUY 强置信 | BUY, 0.88 | BUY, 0.875 | 对称 |
| 三方全 HOLD 强置信 | HOLD, 0.50 | HOLD, **0.00** | 真正中性 |
| 三方全 SELL 强置信 | SELL, 0.12 | SELL, **-0.875** | 与 BUY 场景对称 |
| 1 strong BUY + 2 HOLD | 可能 HOLD | BUY, 0.365 | 主角带动生效 |
| 三方分散 BUY/HOLD/SELL 均强 | BUY（多头偏见） | **HOLD, 0.152**（分歧惩罚） | 正确识别不确定 |
| 2 BUY conf=0.6 vs 1 SELL conf=0.55 | BUY 触发 | BUY 通过加权阈值 | 不靠宽松覆盖 |

---

### 3. RAG 共享池（P0-C）

#### v2.1 的问题

每次 `/api/v1/analyze` 触发 **5 次 `search_knowledge_base` 调用**：

1. `rag_node`（独立节点）
2. `fundamental_node` 专项：`"{symbol} 财务报表 基本面 盈利 机构评级"`
3. `technical_node` 专项：`"{symbol} 近期资金面 行业技术利好利空"`
4. `sentiment_node` 专项：`"{symbol} 最新宏观政策 行业动态 突发新闻"`
5. `debate_node` 专项：`"{symbol} 行业核心风险点 前景 护城河"`（条件触发）

冗余代价：
- 5 次 RAG 走内地 relay，每次 15s HTTP 超时，最坏 75s 累积
- 4 个 query 重叠严重，命中片段高度重复
- embedding API 5 次付费，结果合并后意义有限

#### v2.2 方案

**删除独立 `rag_node`**，`data_node` 末尾一次宽口径预取 + **代码启发式主题分类**到 4 个 bucket：

```python
def build_rag_evidence_pool(symbol, market_type) -> dict[str, list[str]]:
    """一次宽口径 RAG → 分类到 4 个 bucket"""
    query = f"{symbol} {market_type} 财务估值 盈利增长 技术形态 趋势动量 行业政策 宏观新闻 市场情绪"
    raw = search_knowledge_base.invoke({"query": query, "market_type": market_type, "max_length": 2500})

    pool = {"fundamental": [], "technical": [], "sentiment": [], "shared": []}
    for segment in raw.split("\n\n"):
        for bucket in _classify_rag_snippet(segment):
            if len(pool[bucket]) < 5:  # 每 bucket 上限 5 条
                pool[bucket].append(segment)
    return pool


_RAG_KEYWORDS_FUND = ["PE", "PB", "ROE", "EPS", "毛利率", "净利润", "营收", "现金流", ...]
_RAG_KEYWORDS_TECH = ["K线", "MA5", "MACD", "RSI", "BOLL", "金叉", "量比", "突破", ...]
_RAG_KEYWORDS_SENT = ["政策", "监管", "央行", "美联储", "利好", "热点", "公告", ...]


def _classify_rag_snippet(text: str) -> list[str]:
    """启发式分类: 单主题命中 → 专项 bucket,0 或 2+ 主题 → shared"""
    hits = []
    if any(k in text for k in _RAG_KEYWORDS_FUND):  hits.append("fundamental")
    if any(k in text for k in _RAG_KEYWORDS_TECH):  hits.append("technical")
    if any(k in text for k in _RAG_KEYWORDS_SENT):  hits.append("sentiment")
    return hits if len(hits) == 1 else ["shared"]
```

#### 下游节点改为从 pool 读取

```python
def _read_pool(state, bucket, include_shared=True, max_chars=1200) -> str:
    pool = state.get("rag_evidence_pool") or {}
    snippets = pool.get(bucket, []) + (pool.get("shared", []) if include_shared else [])
    return "\n\n".join(snippets)[:max_chars]


# fundamental_node:
fund_rag_context = _read_pool(state, "fundamental", include_shared=True, max_chars=1200)

# technical_node:
tech_rag_context = _read_pool(state, "technical", include_shared=True, max_chars=1000)

# sentiment_node:
sent_rag_context = _read_pool(state, "sentiment", include_shared=True, max_chars=1000)

# portfolio_node:
rag_context = _read_pool(state, "shared", include_shared=False, max_chars=600)

# debate_node:
debate_rag_context = _read_pool(state, "shared", include_shared=False, max_chars=1200)
```

#### 收益

- **RAG 调用次数**：5 次 → **1 次**（-80%）
- **延迟**：最坏 75s → 15s（-80%）
- **embedding 成本**：-80%
- **图拓扑简化**：10 个节点 → 9 个节点

---

### 4. 技术指标升级（P1-A）

`tools/market_data.py` 的 `_calc_indicators_from_ohlcv` 升级：

#### 修复 1：`BOLL_pct_B` 首次真正计算

v2.1 的 `technical_node` prompt 里早就在读 `indicators.get('BOLL_pct_B')`，但 `_calc_indicators_from_ohlcv` 从来没计算过这个字段，永远返回 `None`。v2.2 补齐：

```python
boll_range = (upper - lower).replace(0, pd.NA)
boll_pct_b = (close - lower) / boll_range
# BOLL_pct_B > 0.85 近上轨, < 0.15 近下轨
```

#### 修复 2：`tech_signal` 5 档共振打分

v2.1 的 `tech_signal` 只用 MA5/MA20/RSI14 判定，完全没用到 MACD/BOLL/ATR/量比。v2.2 升级为 5 维度共振打分：

```python
signals_detail = {
    "ma_bullish":    ma5 > ma20 > ma60,
    "macd_golden":   macd_prev <= sig_prev and macd_now > sig_now,
    "rsi_moderate":  30 < rsi14 < 70,
    "boll_middle":   0.2 < boll_pct_b < 0.8,
    "volume_surge":  volume_ratio >= 1.5,
}
bull_score = sum(signals_detail.values())  # 0~5

tech_signal = "strong_bullish" if bull_score >= 4 else \
              "bullish"        if bull_score == 3 else \
              "neutral"        if bull_score == 2 else \
              "bearish"        if bull_score == 1 else "strong_bearish"
```

同时暴露 `bull_score / bear_score / tech_signal_detail / ma_alignment / MACD_golden_cross` 给 `build_technical_citations` 消费。

#### 修复 3：`ATR_percentile_90d` 历史分位数

单一 ATR% 数字没有参照系（"4.5% ATR 到底是高是低?"）。v2.2 新增：

```python
atr_percentile_90d = (atr14_series.tail(90) <= atr14_v).mean()
# 0.85 意味着"当前波动率在近 90 天的 top 15%",比单看 ATR% 更有信息量
```

---

### 5. 连续冲突检测（P1-B）

v2.1 的 `has_conflict` 是二元 boolean，只检测两种硬模式：
- 基本面 vs 技术面方向相反
- 情绪面以 `conf >= 0.8` 强烈反对一致的基本/技术

这漏掉了很多场景（例如 `2 BUY + 1 mild SELL (conf=0.55)`）。v2.2 改为连续分数：

```python
def _conflict_score(recs: list[str], confs: list[float]) -> dict:
    DIR = {"BUY": 1, "HOLD": 0, "SELL": -1}
    dirs = [DIR[r] for r in recs]

    # 方向分散度
    dir_std = pstdev(dirs)  # 0 ~ 0.816

    # 最自信的矛盾对
    max_conflict = 0.0
    for i, j in [(0,1), (0,2), (1,2)]:
        if dirs[i] * dirs[j] < 0:  # 一正一负
            max_conflict = max(max_conflict, min(confs[i], confs[j]))

    # 综合冲突分
    score = 0.6 * (dir_std / 0.816) + 0.4 * max_conflict
    return {"score": score, "should_debate": score >= 0.60}
```

`portfolio_node` 用 `should_debate` 替代原 `has_conflict` 触发辩论。

---

### 6. ATR 动态止损（P1-D 部分）

v2.1 的止损 `stop_loss_pct` 是 LLM 给的硬编码值或代码兜底 5%，完全不考虑该股当前波动率。高波动股（寒武纪、阳光电源等）的正常波动就能扫出止损。

v2.2 改为：

```python
# risk_node 代码层强制
atr_pct_f = float(atr_pct) if atr_pct is not None else 0.0
atr_based_stop = 2.0 * atr_pct_f
decision_dict["stop_loss_pct"] = max(llm_stop, atr_based_stop, 5.0)
```

- `max(LLM 给的, 2×ATR, 5%)`
- 正常路径和 fallback 路径都启用
- Kelly 仓位校准版（依赖真实胜率数据）推迟至 Phase 13，当前只启用 ATR 动态止损这一半

---

### 7. CostTracker 按实验隔离成本累计

v2.1 的 `observability/llm_tracker.py` 只有 `track_llm_call()` 全局埋点，没有"按实验隔离"的累计器，A/B 回测、shadow run、线上请求会互相污染成本数据。

v2.2 新增 `CostTracker` 类 + `contextvars`：

```python
# observability/llm_tracker.py

class CostTracker:
    def __init__(self, run_id: str, hard_stop_cny: float = 95.0):
        self.run_id = run_id
        self.hard_stop = hard_stop_cny
        self._total_cny = 0.0
        self._lock = asyncio.Lock()

    async def record(self, *, model, prompt_tokens, completion_tokens) -> float:
        cost = _compute_cost_cny(model, prompt_tokens, completion_tokens)
        async with self._lock:
            self._total_cny += cost
            if self._total_cny >= self.hard_stop:
                raise CostExceeded(f"{self.run_id}: ¥{self._total_cny:.2f} >= ¥{self.hard_stop}")
        return cost


# 通过 contextvars 下发到 _invoke_structured_with_fallback, 节点不需改签名
_current_tracker: ContextVar[CostTracker | None] = ContextVar("cost_tracker", default=None)
```

**自动接入**：`_invoke_structured_with_fallback` 改用 `include_raw=True` 拿到原始 `AIMessage` 的 `usage_metadata`，层 1 / 层 2 成功后自动 `await tracker.record()`。生产环境不设置 tracker 时完全 no-op。

**定价订正**：v2.1 的 `_COST_TABLE` 里 `qwen-plus: {"in": 0.004, "out": 0.012}` 是 256K-1M 大窗口档位的 per-1K 价格，对我们 31K 输入场景**多算了 5 倍**。v2.2 订正为 ≤128K 档位真实价格：

```python
_COST_TABLE = {
    "qwen-plus":        {"in": 0.0008, "out": 0.0048},   # Qwen3.5-Plus ≤128K 真实单价
    "qwen3.5-plus":     {"in": 0.0008, "out": 0.0048},
    "qwen-plus-long":   {"in": 0.004,  "out": 0.024},    # 256K-1M 大窗口(我们用不到)
    "qwen-turbo":       {"in": 0.0003, "out": 0.0006},
    ...
}
```

单次 analyze 成本：`31.5K × ¥0.0008 + 8.2K × ¥0.0048 = ¥0.065`

---

## 市场数据覆盖

### 实时指数（8 个）

| 指数 | 数据源 | 服务器 |
|------|--------|--------|
| 上证指数 | akshare `stock_zh_index_spot_em` | 内地 relay |
| 深证成指 | akshare `stock_zh_index_spot_em` | 内地 relay |
| 沪深 300 | akshare `stock_zh_index_spot_em` | 内地 relay |
| 恒生指数 | yfinance `^HSI` | 香港直连 |
| 恒生科技 | yfinance `^HSTECH` | 香港直连 |
| 标普 500 | yfinance `^GSPC` | 香港直连 |
| 纳斯达克 | yfinance `^IXIC` | 香港直连 |
| 道琼斯 | yfinance `^DJI` | 香港直连 |

### akshare 列顺序陷阱（务必警惕）

- `stock_zh_index_spot_em`：`col[1]=代码, col[3]=最新价, col[4]=涨跌幅%, col[5]=涨跌额`。注意 `399xxx` 深证指数**不在**该接口里
- `index_global_spot_em`：`col[1]=代码, col[3]=最新价, col[4]=涨跌额(pts), col[5]=涨跌幅%`。注意 col4/col5 顺序与 A 股**相反**
- `stock_financial_abstract_ths`：升序排列（最旧在前），取财务数据用 `.tail(5)`；数值为带"亿"字符串如 `"862.28亿"`，需 `_to_yi()` 剥离

### 行业板块（50 个）

数据源：同花顺 `stock_board_industry_summary_ths`，按涨跌幅排序 TOP 50，含领涨股、上涨家数、下跌家数。

### 热门标的（24 只）

| 市场 | 数量 | 示例 |
|------|------|------|
| A 股 | 8 只 | 贵州茅台、五粮液、比亚迪、宁德时代... |
| 港股 | 8 只 | 腾讯、阿里巴巴、美团、京东、小米... |
| 美股 | 8 只 | 苹果、微软、英伟达、谷歌、特斯拉、AMD... |

### 新闻聚合（4 平台）

财联社 / 华尔街见闻 / 新浪财经 / 澎湃新闻，各 TOP 3 实时热榜。

### 市场数据流

```
akshare (A 股 + 港股) → 内地 relay (47.108.191.110:8001)
                              ↓
yfinance (美股 + 全球指数) → HK 主站
                              ↓
                    DataLoader._standardize()
                              ↓
            [timestamp, open, high, low, close, volume]
                              ↓
                  _calc_indicators_from_ohlcv()
                              ↓
           MA5/10/20/60 + MACD + RSI14 + BOLL + ATR
         + tech_signal(5 档) + ATR_percentile_90d
         + ma_alignment + MACD_golden_cross + BOLL_pct_B
```

**TTL 缓存** 300s，**指数退避重试** 3 次（1.5× base）。

---

## 研报输出格式

论文式研报结构，不是 Agent 日志 dump：

```
投资建议（推荐 / 置信度 / 仓位 / 止损 / 止盈）
│
├─ 投资论点（2-3 句核心观点）
├─ 商业模式 & 收入驱动（主营业务 / 收入结构 / 毛利率趋势）
├─ 护城河 & 竞争优势（品牌 / 技术 / 规模 / 网络效应）
├─ 估值 & 同行对比（PE / PB / ROE / 与同行对比）
├─ 催化剂（未来 1-2 季度的 3+ 个事件）
├─ 核心风险（至少 2 个具体风险因素）
├─ 情景分析
│     ├─ 乐观情景：目标估值倍数 + 目标价
│     └─ 悲观情景：量化下跌幅度 + 触发条件
├─ 学生行动建议（周期 / 仓位 / 止损）
│
└─ [可展开] 各 Agent 详细分析过程
      ├─ 基本面证据引文 (代码生成)
      ├─ 技术面证据引文 (代码生成)
      ├─ 舆情证据引文 (LLM 抽取 + 校验)
      ├─ 基金经理 reasoning
      └─ 风控决策细节
```

前端 ECharts 渲染：
- K 线图（日 K / 周 K / 月 K）
- 财务三表柱状图（营收 / 净利润 / ROE 近 5 年）
- 收益曲线
- 持仓健康评分 SVG 环

---

## 风控体系

### 四重硬风控

| 风控层 | 触发条件 | 执行方式 |
|--------|---------|---------|
| **ATR 硬阻断** | ATR% > 8.0% | REJECTED，仓位归零 |
| **ATR 减半** | ATR% > 5.0% | CONDITIONAL，仓位 × 0.5 |
| **仓位上限截断** | A 股 > 15% / 港美 > 10% | 截断到上限，conditions 记录 |
| **单次亏损反算** | `position × stop_loss` 金额 > ¥3000 | 反算最大安全仓位 |

### 【v2.2】ATR 动态止损

```python
dynamic_stop = max(llm_stop, 2.0 * atr_pct, 5.0)
```

正常路径和异常 fallback 路径都启用。

### 置信度惩罚

```python
if confidence < 0.40:                     # 强制 HOLD，仓位归零
    action = "HOLD"; position = 0
elif 0.40 <= confidence < 0.55:           # 线性缩仓
    scale = (confidence - 0.40) / (0.55 - 0.40)
    position = base_position * scale
else:                                      # >= 0.55 正常执行
    position = base_position
```

### 硬编码禁止项（写在 prompt 里 + 代码二次校验）

- 严禁杠杆（融资融券 / 期权投机）
- 单次最大亏损 ≤ ¥3000（反算）
- 投资周期建议 ≥ 3 个月，不推荐短线高频

---

## 模拟交易引擎

`api/mock_exchange.py`：**三市场独立账户**，永远只走本地撮合，不连任何真实交易所。

| 市场 | 初始资金 | 货币 |
|------|---------|------|
| A 股 | 100,000 | CNH |
| 港股 | 100,000 | HKD |
| 美股 | 10,000 | USD |

支持功能：

- **买入**：输入代码 + 数量，自动校验最小手数（A 股 100 股 / 港股 100-500 股 / 美股 1 股）
- **部分卖出**：25% / 50% / 75% / 100% 快捷比例按钮
- **K 线图**：日 K / 周 K / 月 K，支持搜索自动补全
- **实时持仓**：均价、现价、浮盈、一键卖出
- **成交记录**：完整历史订单
- **手续费**：万三（未来升级为分市场费率）

**硬约束**：`TradeOrder.simulated` 字段有 Pydantic `@model_validator(mode="after")` 强制覆盖为 `True`，即便 LLM 输出 `false` 也会被改回。

---

## 回测框架（v2.2 新增）

> **目标**：用 20 支股票 × 2023-2025 三年 × 月度 A/B 对比，在 ¥100 预算内量化证明 v2.2 证据化改造（Group B）相对 v2.1 baseline（Group A）的提升。
>
> **完整方案**：见 `BACKEND_ALGO_OPTIMIZATION.md` §5。

### 股票池（20 支）

`bench/backtest/universe.yaml` 固化：

| 市场 | 数量 | 清单 |
|---|---|---|
| **A 股** | 10 | 贵州茅台 / 宁德时代 / 招商银行 / 中国平安 / 比亚迪 / **中信证券** / 中芯国际 / 韦尔股份 / 寒武纪 / 阳光电源 |
| **港股** | 5 | 腾讯 / 阿里巴巴 / 美团 / 汇丰 / 友邦 |
| **美股** | 5 | AAPL / MSFT / NVDA / AMZN / JPM |

风格分布：蓝筹 10 / 科技蓝筹 3 / 成长 2 / 主题 2 / Mega Cap 3。故意纳入寒武纪、阳光电源等高波动主题股，避免幸存者偏差。

### 两阶段架构

为什么不直接把 `backtest/engine.py`（同步）改成 async？因为改动范围太大且没必要——回测引擎本身跑得极快（每天 ~1ms），慢的只有 LLM 调用。正确做法是**两阶段解耦**。

```
Phase 1（慢，离线，异步）：
  bench/precompute_signals.py
    for (month, symbol, version) in cartesian_product:
        signal = await graph.ainvoke(state, config=...)
        append to signals_{version}.parquet

  ├─ CostTracker(run_id="precompute_v1_baseline", hard_stop=47) 隔离成本
  ├─ contextvars 下发 tracker, 节点不改签名
  └─ 产物: bench/data/signals_{v1_baseline,v2_esc}.parquet


Phase 2（快，同步，可重放）：
  bench/backtest/signal_replay_strategy.py
    class SignalReplayStrategy(Strategy):
        def generate(self, t, prices):
            # 从 parquet 读当月信号, 直接返回 Signal 列表

  ├─ 继承现有 backtest/engine.Strategy 基类
  ├─ 完全同步, sync BacktestEngine 原封不动
  └─ 可无限次重放（调参数、改手续费）不烧 LLM
```

### 预算与成本

| 参数 | 取值 |
|---|---|
| 单次 analyze 成本 | ¥0.065（Qwen3.5-Plus ≤128K 档真实价） |
| Universe | 20 支 |
| 时间跨度 | 2023-01 → 2025-12（36 月） |
| 每组 analyses | 20 × 36 = 720 |
| A + B 两组 | 1440 |
| **总成本** | **¥94**（留 ¥6 安全余量） |
| CostTracker 硬停 | 每组 ¥47 |
| 运行时间 | ~20 分钟（Semaphore 10 并发）|

代码生成引文（P0-A）让 Group B 的输出 token 减少 ~20%，实际预算 ~¥87。

### Walk-Forward 时间分层

```
├──── In-sample (调 prompt) ────┤── Holdout (锁死) ──┤
 2023-01                      2024-12              2025-12

  In-sample:  24 个月, 允许看指标迭代 prompt
  Holdout:    12 个月, prompt 冻结后独立运行一次
```

吸收外部审阅建议，本方案定位为**探索性 A/B**（非学术级统计显著性），用**月度截面 block bootstrap** 做鲁棒性检验 + **Leave-One-Market-Out** 免费稳健性检查。

### 用法

```bash
# 一次性下载 20 支 OHLCV (10 分钟, 免费)
python -m scripts.download_universe_history

# Phase 1: 预计算 Group A baseline 信号 (~¥47, ~10 分钟)
python -m bench.precompute_signals v1_baseline 2023-01-01 2025-12-31

# Phase 1: 预计算 Group B ESC 信号 (~¥40, ~10 分钟)
python -m bench.precompute_signals v2_esc 2023-01-01 2025-12-31

# Phase 2: 同步重放 A/B + 报告 (秒级, 零成本)
# TODO: bench/evidence_sharing_ab.py (待实现)
```

**当前状态**：Phase 1 的 `data_node` 仍然拉"最新"市场数据而不是历史时点，真实时点回测需要升级 `data_node` 支持 `state["rebalance_date"]`（这是 v2.3 的 TODO）。

---

## API 端点

### 主要 REST / SSE 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| **POST** | `/api/v1/analyze` | 触发股票分析，SSE 流式返回完整研报 |
| **POST** | `/api/v1/health-check` | 持仓体检，返回评分 + 诊断 + 优化建议 |
| **GET** | `/api/v1/market/indices` | 8 个实时指数 |
| **GET** | `/api/v1/market/industries` | 同花顺 50 行业板块 TOP |
| **GET** | `/api/v1/market/hot-stocks` | 24 只热门标的（A/HK/US 各 8） |
| **GET** | `/api/v1/market/news?limit=N` | 财联社 7x24 新闻 |
| **GET** | `/api/v1/market/indicators/{symbol}` | 单股技术指标（含 v2.2 5 档 tech_signal） |
| **POST** | `/api/v1/trade/order` | 模拟交易下单 |
| **GET** | `/api/v1/trade/account` | 账户快照 + 持仓 + 资金 |
| **POST** | `/api/v1/auth/login` | JWT 登录 |
| **POST** | `/api/v1/auth/register` | 注册（邮箱验证码） |

---

## SSE 事件流

`/api/v1/analyze` 使用 Server-Sent Events 推送进度：

| 事件 | 载荷 | 触发时机 |
|------|------|---------|
| `start` | `{symbol, market_type, thread_id}` | 分析请求受理 |
| `node_start` | `{node, description}` | 节点开始（含中文描述） |
| `node_complete` | `{node, result_summary}` | 节点完成 |
| `conflict` | `{conflict_score, should_debate}` | 检测到分析师冲突 |
| `debate` | `{round, resolved_recommendation, confidence}` | 辩论裁决完成 |
| `risk_check` | `{approval_status, risk_level, position_pct}` | 风控审批 |
| `risk_retry` | `{attempt, rejection_reason}` | 风控拒绝重试 |
| `trade_order` | `{action, quantity_pct, stop_loss, take_profit}` | 模拟交易指令生成 |
| `complete` | `{full_report, evidence_citations, financial_chart_data}` | 全流程完成 |
| `error` | `{error_type, error_message}` | 错误（含归因） |

---

## 双服务器部署

```
用户浏览器
    │
    ▼ HTTPS
┌─────────────────────────────────────────────┐
│  香港服务器 (2C/1G) - 47.76.197.100          │
│  ├─ Nginx (反向代理 + 静态文件)              │
│  ├─ FastAPI (uvicorn)                        │
│  ├─ LangGraph Agent 调度                     │
│  ├─ DashScope LLM (Qwen3.5-Plus)             │
│  ├─ yfinance (全球指数 / 港美股)             │
│  ├─ DuckDuckGo 实时搜索                      │
│  └─ 前端静态页 (Nginx 托管)                  │
└──────────────┬──────────────────────────────┘
               │
               │ HTTP + Bearer token
               ▼
┌─────────────────────────────────────────────┐
│  内地服务器 (2C/2G) - 47.108.191.110:8001    │
│  ├─ FastAPI (inland_relay/server.py)         │
│  ├─ akshare (A 股 + 港股数据)                │
│  ├─ 同花顺板块 + 财务三表                    │
│  ├─ BM25 RAG 检索 (rank_bm25)                │
│  ├─ Chroma 向量库（可选）                    │
│  ├─ MySQL 用户数据库 (asyncmy)               │
│  ├─ 财联社 / 新浪 / 澎湃新闻源               │
│  └─ 缓存持久化（重启后恢复上一交易日数据）    │
└─────────────────────────────────────────────┘
```

**内存实测**（2026-04）：
- cq-hk: 882 MB total / 680 MB used / **200 MB 余量**（FastAPI uvicorn 吃 214 MB）
- cq-inland: 1.6 GB total / 1.1 GB used / **464 MB 余量**（inland_relay 398 MB + MySQL 193 MB）

**硬约束**：
- HK 总进程内存 ≤ 700 MB（留 180 MB 给 OS + buff cache）
- Inland 总进程内存 ≤ 1.3 GB（留 300 MB）
- Swap 使用 = 0（开始用 swap 就是告警）
- **回测永远不在生产服务器上跑**——所有 `bench/*` 脚本本地执行

---

## 快速启动

### 本地开发

```bash
# 1. Clone + 虚拟环境
git clone https://github.com/JoeFeng0571/CampusQuant-Agent.git
cd CampusQuant-Agent
python -m venv .venv
.venv/Scripts/activate       # Windows
# source .venv/bin/activate  # Linux/Mac

# 2. 依赖
pip install -r requirements.txt

# 3. 环境变量（见下一节）
cp .env.example .env
# 在 .env 里填入 DASHSCOPE_API_KEY 等

# 4. 首次构建 RAG 知识库（可选，需 Embedding API）
python -m scripts.build_kb

# 5. 启动后端
uvicorn api.server:app --host 127.0.0.1 --port 8000

# 6. 启动前端（另一个终端）
python -m http.server 3000
# 打开 http://localhost:3000
```

### 服务器部署

**香港服务器**（主站）：

```bash
cd /opt/CampusQuant-Agent
source .venv/bin/activate
git pull
pip install -r requirements-hk.txt   # 香港精简依赖（无 akshare）
# 重启 uvicorn
nohup .venv/bin/uvicorn api.server:app --host 127.0.0.1 --port 8000 > server.log 2>&1 &
```

**内地服务器**（数据中继）：

```bash
cd /opt/CampusQuant-Agent/inland_relay
source .venv/bin/activate
git pull
pip install -r requirements.txt       # 含 akshare / 同花顺
nohup .venv/bin/uvicorn server:app --host 0.0.0.0 --port 8001 > relay.log 2>&1 &
```

**内地服务器 GitHub 不通时**（用香港中转）：

```bash
# 香港服务器上
cd /opt/CampusQuant-Agent && git pull && tar czf /tmp/relay-update.tar.gz inland_relay/

# 内地服务器上
scp root@47.76.197.100:/tmp/relay-update.tar.gz /tmp/
cd /opt/CampusQuant-Agent && tar xzf /tmp/relay-update.tar.gz
```

### Windows 本地 SSH 部署（Git-Bash 有 Unicode 问题）

```bash
# /usr/bin/ssh 在 Windows + Chinese HOME path 下会乱码路径,改用 Windows 原生 ssh.exe
/c/Windows/System32/OpenSSH/ssh.exe cq-hk 'cd /opt/CampusQuant-Agent && git pull'
```

---

## 环境变量配置

`.env` 文件（**不要进 git**，已在 `.gitignore`）：

```bash
# ── LLM ──────────────────────────────────────────────
DASHSCOPE_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
QWEN_MODEL_NAME=qwen3.5-plus
OPENAI_API_KEY=sk-...                    # 备用
OPENAI_BASE_URL=https://api.openai.com/v1

# ── 数据库 ────────────────────────────────────────────
DATABASE_URL=mysql+asyncmy://user:pass@host/dbname?charset=utf8mb4

# ── 邮件（注册验证码） ─────────────────────────────────
SMTP_HOST=smtp.qq.com
SMTP_PORT=465
SMTP_USERNAME=xxx@qq.com
SMTP_PASSWORD=xxxxxxxxxxxxxxxx
SMTP_FROM_EMAIL=xxx@qq.com
SMTP_FROM_NAME=CampusQuant
SMTP_USE_SSL=true

# ── 内地数据中继 ──────────────────────────────────────
INLAND_RELAY_BASE_URL=http://47.108.191.110:8001
INLAND_RELAY_TOKEN=CQ_Relay_Secure_xxx

# ── 香港市场 relay（可选，主要用于 yfinance 代理）────
MARKET_RELAY_BASE_URL=
MARKET_RELAY_TOKEN=

# ── JWT 鉴权 ─────────────────────────────────────────
JWT_SECRET_KEY=your-strong-random-secret-key

# ── （仅本地回测）DashScope "仅使用免费额度" 模式需要关掉 ───
# 控制台 → API-KEY 管理 → 关闭 "Use free tier only" 开关
```

**DashScope 账户状态排查**：如果分析时所有节点都返回 HOLD/0.30，查看日志，可能是：
- `type: 'Arrearage'` → 欠费，充值即可
- `type: 'AllocationQuota.FreeTierOnly'` → 账户被设成"仅使用免费额度"，去控制台关掉开关

---

## 项目结构

```
trading_agents_system/
│
├─ graph/                        # ═══ LangGraph 核心 ═══
│   ├─ state.py                  # TradingGraphState TypedDict + Pydantic 模型
│   │                             # ├─ AnalystReport (含 evidence_citations)
│   │                             # ├─ RiskDecision
│   │                             # ├─ TradeOrder (simulated=True 恒真)
│   │                             # ├─ DebateOutcome
│   │                             # ├─ PortfolioPosition / PortfolioHealthReport
│   │                             # └─ rag_evidence_pool (v2.2)
│   ├─ nodes.py                  # 9 个节点 + 30+ 辅助函数
│   │                             # ├─ data_node + build_rag_evidence_pool (v2.2)
│   │                             # ├─ fundamental/technical/sentiment_node
│   │                             # ├─ portfolio_node + _compute_weighted_score (v2.2)
│   │                             # ├─ debate_node + _conflict_score (v2.2)
│   │                             # ├─ risk_node + _apply_atr_hard_block + ATR 动态止损 (v2.2)
│   │                             # ├─ trade_executor + _apply_confidence_penalty
│   │                             # ├─ health_node
│   │                             # ├─ build_fundamental_citations (v2.2)
│   │                             # ├─ build_technical_citations (v2.2)
│   │                             # ├─ _validate_llm_citations (v2.2)
│   │                             # ├─ _read_pool / _classify_rag_snippet (v2.2)
│   │                             # ├─ _record_cost_from_metadata (v2.2)
│   │                             # └─ _PROMPTS 字典
│   └─ builder.py                # StateGraph DAG 装配 + build_health_graph
│
├─ api/                          # ═══ FastAPI 后端 ═══
│   ├─ server.py                 # SSE 流式接口 + 所有 REST 端点（2500+ 行）
│   ├─ mock_exchange.py          # 本地模拟撮合引擎（三市场独立账户）
│   └─ auth.py                   # JWT 鉴权 + 邮箱验证码
│
├─ inland_relay/                 # ═══ 内地数据中继服务 ═══
│   ├─ server.py                 # akshare + 同花顺 + RAG + MySQL 封装
│   └─ requirements.txt          # 内地服务器专属依赖
│
├─ tools/                        # ═══ LangChain Tools ═══
│   ├─ market_data.py            # akshare / yfinance + 内地 relay 客户端
│   │                             # └─ _calc_indicators_from_ohlcv (v2.2 5 档 tech_signal)
│   ├─ knowledge_base.py         # BM25 + Chroma + DuckDuckGo 混合 RAG
│   │                             # └─ search_knowledge_base + 同义词扩展
│   └─ hot_news.py               # 多平台热榜聚合
│
├─ observability/                # ═══ 可观测性 ═══
│   ├─ llm_tracker.py            # CostTracker(run_id) + contextvars + _COST_TABLE (v2.2)
│   ├─ metrics.py                # Prometheus histogram / counter
│   └─ middleware.py             # FastAPI 中间件（trace_id）
│
├─ backtest/                     # ═══ 通用同步回测引擎 ═══
│   ├─ engine.py                 # BacktestEngine + Strategy 基类（sync）
│   ├─ metrics.py                # Sharpe / Sortino / Calmar / MDD
│   └─ strategies/
│       └─ equal_weight.py       # 等权重 baseline 策略
│
├─ bench/                        # ═══ v2.2 A/B 回测脚手架 ═══
│   ├─ backtest/
│   │   ├─ universe.yaml         # 20 支股票池定义
│   │   └─ signal_replay_strategy.py  # SignalReplayStrategy (sync, 读 parquet)
│   ├─ precompute_signals.py     # Phase 1 async 预计算 + CostTracker
│   ├─ smoke_analyze_v22.py      # 单股烟雾测试，验证 v2.2 证据化
│   ├─ data/
│   │   ├─ ohlcv/                # 20 支 × 2023-2025 parquet (gitignored)
│   │   └─ signals_*.parquet     # 预计算产物 (gitignored)
│   ├─ run.py / auto_run.py      # 旧 bench runner
│   ├─ quick_rag_test.py         # RAG 质量快测
│   ├─ judges/ / runners/        # Agent benchmark 基础设施
│   └─ datasets/                 # benchmark 数据集
│
├─ tests/                        # ═══ pytest ═══
│   ├─ test_extreme_cases.py     # 主要测试集（含 v2.2 P0-C / RAG pool 验证）
│   ├─ test_matching_engine.py   # 模拟撮合
│   ├─ test_backtest_stops.py    # 止损逻辑
│   ├─ test_rag_expansion.py     # RAG 查询扩展
│   └─ test_report_cache.py      # 研报缓存
│
├─ scripts/                      # ═══ 运维脚本 ═══
│   ├─ build_kb.py               # 构建 Chroma + BM25 知识库
│   ├─ download_universe_history.py  # v2.2: 20 支 OHLCV 下载（走 inland relay）
│   ├─ seed_community.py         # 社区种子数据
│   └─ evaluate_decisions.py     # v2.2 数据飞轮（TODO）
│
├─ db/                           # ═══ SQLAlchemy 异步 ORM ═══
│   ├─ models.py                 # 用户 / 交易 / 社区 / badcase / decisions
│   ├─ crud.py                   # 增删改查
│   └─ engine.py                 # asyncmy 连接池
│
├─ utils/
│   ├─ data_loader.py            # DataLoader._standardize 统一 OHLCV 列
│   ├─ llm_client.py             # LLM 客户端（多厂商切换）
│   └─ market_classifier.py      # symbol → MarketType 映射
│
├─ data/                         # ═══ RAG 源数据 & 向量库 ═══
│   ├─ docs/                     # 研报 PDF / TXT（RAG 源）
│   ├─ chroma_db/                # Chroma 持久化向量库
│   └─ bm25_index.pkl            # BM25 索引（build_kb.py 生成）
│
├─ cloudflare_worker/            # ═══ CF Worker 边缘计算 ═══
│   └─ market-relay/             # 备用市场数据 relay
│
├─ qa/                           # ═══ QA 文档 ═══
│   ├─ frontend_acceptance_test_plan.md
│   ├─ frontend_test_results.md
│   └─ frontend_optimization_report.md
│
├─ research/                     # 研究笔记（hold_bias_study 等）
├─ paper/                        # 论文草稿
├─ assets/                       # 前端静态资源
│
├─ *.html                        # 前端页面（见下一节）
├─ BACKEND_ALGO_OPTIMIZATION.md  # v2.2 完整优化方案（1934 行）
├─ AUDIT_REPORT.md               # 产品交付审计报告（2026-04）
├─ UPGRADE_PLAN.md               # 平台工程升级路线图
├─ CLAUDE.md                     # Claude Code 工作指南（给 AI 助手看的）
├─ README.md                     # 本文件
├─ config.py                     # 全局配置
├─ main.py                       # CLI 入口
├─ workflow.py                   # 完整 workflow 封装
├─ app.py                        # Streamlit 备用入口
├─ requirements.txt              # 完整依赖
├─ requirements-hk.txt           # 香港精简依赖
└─ .gitignore
```

---

## 前端页面

| HTML 文件 | 页面 | 核心功能 |
|---|---|---|
| `index.html` | 首页 Landing | 品牌展示 + 免责声明 + CTA |
| `trade.html` | 模拟演练 | SSE 流式分析 + K 线图 + 下单 |
| `platforms.html` | 持仓体检 | 持仓表单 → SVG 评分环 + 优化建议 |
| `market.html` | 市场快讯 | 8 指数 + 50 行业 + 24 热股 + 4 平台新闻 |
| `community.html` | 投教社区 | 文章列表 + 评论 + 点赞 |
| `team.html` | 关于我们 | 团队介绍 + 愿景 |
| `home.html` | 学习中心 Dashboard | 学习进度 + 推荐路径 |
| `resources.html` | 学习资源库 | 研报下载 + 教学视频 |
| `learn_basics.html` | 基础财商知识 | 股票/基金/债券入门 |
| `learn_strategies.html` | 投资策略 | 价值 / 成长 / 宏观配置 |
| `learn_antifraud.html` | 反金融诈骗 | 常见骗局识别 |
| `article_detail.html` | 文章详情 | 单篇文章阅读 |
| `auth.html` | 登录注册 | JWT + 邮箱验证码 |
| `profile.html` | 个人中心 | 账户设置 + 资产快照 |

**设计系统** (v3, 2026-04 重写)：
- 多字体排版（标题 Serif / 正文 Sans / 代码 Mono）
- 4 级文本色
- 12 个 JS 模块（命令面板、设置抽屉、hero pattern、背景模式切换）
- Linear / Railway 风格的极简美学
- 零 emoji（除非用户明确要求）

---

## 常见问题

**Q: 分析时所有节点都返回 HOLD/0.30，reasoning 里写"结构化输出解析三层全失败"？**

A: LLM 调用失败，检查 DashScope 账户：
1. 欠费（`type: Arrearage`）→ 充值
2. 仅使用免费额度已耗尽（`type: AllocationQuota.FreeTierOnly`）→ DashScope 控制台关闭"Use free tier only"开关
3. API key 无效 → 检查 `.env` 的 `DASHSCOPE_API_KEY`

即使 LLM 完全挂掉，v2.2 的代码生成引文依然会在降级路径输出（`fundamental.evidence_citations` 仍然会包含 `ROE=24.6%` 等真实数据）。

**Q: akshare 拉取失败怎么办？**

A: `tools/market_data.py` 已有指数退避重试（2 次 × 0.8s × 1.5^n）。如果连续失败：
1. 检查 akshare 版本 `pip show akshare`
2. 本地是否被反爬？`download_universe_history.py` 已经 monkey-patch 掉 `urllib.getproxies` 绕过本地系统代理
3. 如果本地反爬无法绕过，改走 `inland_relay` 接口

**Q: Chroma 向量库为空？**

A: 先运行 `python -m scripts.build_kb` 建库。首次构建需要 DashScope / OpenAI Embedding API Key。失败后 `knowledge_base.py` 会自动降级为纯 BM25 模式。

**Q: bcrypt 兼容性报错？**

A: `requirements.txt` 已固定 `bcrypt==4.0.1`。升级会导致 passlib 兼容性问题，**不要更新此版本**。

**Q: 前端 SSE 连接断了？**

A: 检查 Nginx 配置是否关闭 buffering：
```nginx
location /api/v1/analyze {
    proxy_pass http://127.0.0.1:8000;
    proxy_buffering off;
    proxy_cache off;
    proxy_read_timeout 300s;
}
```

**Q: 持仓体检耗时 >60s 是正常的？**

A: v2.1 曾出现 87s 的退化（见 `AUDIT_REPORT.md` B2），目前应该在 15-30s 内完成。如果超过 60s，先查 LLM 超时配置，然后看是否命中缓存。

**Q: Windows 下跑 SSH / 脚本中文乱码？**

A: 两个独立问题：
1. Git-Bash `/usr/bin/ssh` 在 HOME 含中文时会乱码 → 用 `/c/Windows/System32/OpenSSH/ssh.exe`
2. Python 脚本 print 时 GBK 报错 → 脚本开头加 `sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')`

**Q: CostTracker 的 ¥95 硬停会影响生产环境？**

A: 不会。CostTracker 通过 `contextvars` 下发，生产环境不 `set_current_tracker()` 时 `get_current_tracker()` 返回 `None`，`_record_cost_from_metadata` 直接 return，完全 no-op。只有 `bench/precompute_signals.py` 显式设置 tracker 时才会累计。

---

## 测试与验证

### 运行 pytest

```bash
.venv/Scripts/python.exe -m pytest tests/ -x -q
# Windows 记得用 venv 里的 python
```

**当前状态**：**109 passed / 0 failed**（包括 v2.2 新增的 9 个 P0-C 语义测试）。

### 关键测试类

| 文件 | 测试类 | 覆盖 |
|---|---|---|
| `test_extreme_cases.py::TestSearchKnowledgeBaseMaxLength` | 4 项 | 三个分析师节点都用 `_read_pool` 而非直接调 `search_knowledge_base`，带 `max_chars` 截断 |
| `test_extreme_cases.py::TestRagEvidencePoolArchitecture` | 9 项 | v2.2 P0-C RAG 共享池架构、`rag_node` 已删、分类函数、`_read_pool` routing |
| `test_extreme_cases.py::TestD1D4WeightedFormula` | 多项 | D1-D4 加权公式数学准确性 |
| `test_matching_engine.py` | 多项 | 模拟撮合引擎的买卖 / 余额 / 持仓校验 |
| `test_backtest_stops.py` | 多项 | 回测引擎的止损 / 止盈规则 |
| `test_rag_expansion.py` | 多项 | RAG 查询扩展（同义词表） |
| `test_report_cache.py` | 多项 | 研报响应缓存 |

### 单股 smoke 测试

```bash
# v2.2 证据化验证，单股真实 LLM 调用（~¥0.065）
.venv/Scripts/python.exe -m bench.smoke_analyze_v22 600519

# 或任何其他 symbol
.venv/Scripts/python.exe -m bench.smoke_analyze_v22 NVDA
```

输出会详细打印每个节点的 `evidence_citations`、技术指标、基金经理 reasoning 的引文命中情况、风控决策、最终交易指令。

---

## 技术栈

| 层 | 选型 | 版本 |
|----|------|------|
| **LLM** | DashScope / Qwen3.5-Plus（主） | `qwen3.5-plus` ≤128K |
| | OpenAI / Anthropic（备用） | 可热切换 |
| **Agent 框架** | LangGraph | StateGraph + conditional edges |
| **LLM 封装** | LangChain | `with_structured_output(include_raw=True)` |
| **RAG** | Chroma + rank_bm25 + DuckDuckGo | RRF 融合 |
| **Embedding** | DashScope text-embedding-v1 | 备用 OpenAI |
| **市场数据** | akshare + 同花顺 + yfinance | 三路互补 |
| **后端** | FastAPI + uvicorn + SSE | asyncio |
| **前端** | 静态 HTML + Vanilla JS + ECharts | Nginx 托管 |
| **数据库** | MySQL + asyncmy | 异步 ORM |
| **部署** | 香港 + 内地双服务器 | Nginx 反向代理 |
| **缓存** | 内存 TTL + 磁盘持久化 | 非交易时段数据保留 |
| **回测引擎** | pandas + 自写 sync engine | backtest/engine.py |
| **预计算** | asyncio.Semaphore + CostTracker | bench/precompute_signals.py |
| **存储** | parquet (snappy) | bench/data/*.parquet |
| **观测性** | Prometheus-style metrics | observability/metrics.py |
| **成本追踪** | CostTracker + contextvars | observability/llm_tracker.py |
| **测试** | pytest 9.0.3 | 109 passed |
| **依赖管理** | pip + requirements.txt / requirements-hk.txt | 分环境 |

---

## 文档索引

| 文档 | 用途 |
|---|---|
| `README.md` | **本文件**（项目总览 + v2.2 特性） |
| `BACKEND_ALGO_OPTIMIZATION.md` | v2.2 完整算法优化方案（1934 行，13 章） |
| `AUDIT_REPORT.md` | 产品交付审计报告（2026-04-02，安全 + 数据质量） |
| `UPGRADE_PLAN.md` | 平台工程升级路线图（8 周） |
| `CLAUDE.md` | Claude Code 工作指南（AI 助手约束） |
| `API_DOCS.md` | API 端点详细文档 |
| `CampusQuant_PPT.md` | 项目演示 PPT 大纲 |
| `OVERNIGHT_NOTES.md` | 夜间开发笔记 |
| `qa/frontend_*.md` | 前端验收 / 测试 / 优化报告 |
| `paper/*.md` | 论文草稿 + 实验计划 |
| `research/*.md` | 研究笔记 |

---

## 参考文献

1. **《What Should LLM Agents Share? Auditable Content Supports Belief Revision in Controlled Multi-Agent Deliberation》**（EMNLP 2025, under review）
   — v2.2 P0-A 证据化改造的**直接理论依据**。论文在 3-agent、2-round 多跳 QA 协议下实证：共享原始证据（policyEvidence）比共享结论（policyHypothesis + Rationale）在 HotpotQA/MuSiQue/2WikiMultihopQA 上 EM 提升 +10.1 ~ +16.0 pp，87-89% 的 EM 提升来自 W→C 恢复。

2. **Kelly, J. L. (1956)**. *A New Interpretation of Information Rate*. Bell System Technical Journal.
   — 分数 Kelly 仓位公式的原始论文，用于 P1-D 仓位管理（校准版推迟至 Phase 13）。

3. **Platt, J. (1999)**. *Probabilistic Outputs for Support Vector Machines and Comparisons to Regularized Likelihood Methods*.
   — 置信度校准方法（Phase 13 数据飞轮的理论基础）。

4. **LangGraph 官方文档**：https://langchain-ai.github.io/langgraph/
   — StateGraph + conditional edges 的权威参考。

5. **DashScope API 文档**：https://help.aliyun.com/zh/model-studio/
   — Qwen3.5-Plus 定价（≤128K / 128K-256K / 256K-1M 三档）。

---

## 许可证 & 免责声明

**免责声明**：本平台所有交易均为**模拟交易**，不构成任何投资建议。`TradeOrder.simulated` 字段恒为 `True`，代码层强制。实盘投资风险自负。

**面向人群**：在校大学生（有限本金，风险承受能力低）。

**硬编码禁止**：杠杆、融资融券、期权投机、加密货币。

**贡献**：欢迎 issue / PR。代码改动必须通过 `pytest tests/ -q` 全绿（当前 109 passed）。

---

**最后更新**：2026-04-15（v2.2 完整版本）
**作者**：Feng Yuqiao（@JoeFeng0571）
**仓库**：https://github.com/JoeFeng0571/CampusQuant-Agent
