# CampusQuant · 后端算法优化方案 v2.2

> **文档定位**：针对后端**算法逻辑层**的专项审计与优化方案，覆盖 LangGraph 多 Agent 决策链、RAG 检索、技术指标、冲突检测、辩论机制、风控模型、模拟撮合、缓存策略，并把**回测重构 + 产品闭环 + 内存预算**三件事显式写入方案。
> **不重复**：`UPGRADE_PLAN.md`（平台工程 / CI / 回测 / observability 等 7 个工作流）、`AUDIT_REPORT.md`（2026-04-02 安全 + 数据质量 + 用户旅程审计）。
> **作者**：Feng Yuqiao
> **日期**：2026-04-14
> **版本**：v2.2
>
> **v2.2 变更要点**（相对 v2.1，吸收外部审阅 + 真实定价）：
> - **定价订正**：Qwen3.5-Plus ≤128K 档位真实单价为 ¥0.8/M 输入 + ¥4.8/M 输出 → 单次 analyze 成本从 ¥0.04（估算）修正为 **¥0.065**（1.6 倍）
> - **股票池 30→20**：预算重算后 30 支超预算（¥140），收到 20 支（A10 + HK5 + US5），其中 A 股成长组 金山办公 → **中信证券**
> - **2025 holdout + block bootstrap**：§5 统计口径从"3 个指标 p<0.05"降级为**探索性 A/B**，显著性改为月度截面 block bootstrap + leave-one-market-out
> - **Signal 预计算桥接**：回测引擎保持同步（`backtest/engine.py` 现状），新增 async `precompute_signals.py` 先跑 LLM 写 parquet → `SignalReplayStrategy` 同步读取喂给现有引擎
> - **`CostTracker(run_id)`**：替代模块级全局变量，按实验隔离成本累计，避免 A/B/shadow/线上交叉污染
> - **代码生成结构化引文**：P0-A 的 fundamental/technical evidence_citations 由代码从 `fund_data_dict` / `indicators` 直接生成，LLM 只对新闻/RAG 做抽取，**零数字幻觉 + 省 ~20% 输出 token**
> - **Kelly 推迟**：P1-D Kelly 仓位从 Phase 9 挪到 Phase 13（§6 数据飞轮之后），避免未校准 confidence 放大仓位风险
>
> **v2.1 变更要点**：
> - 回测规模收敛：**3 年**（2023-2025，非 7 年）+ 月度频率（非双周/周频）
> - 模型选择：**Qwen-Plus**（与生产一致，非 Turbo）
> - 预算压缩：**≤ ¥100**（v2.0 是 ~¥2000），新增 ¥95 成本硬停机制
> - 运行位置：**本地开发机**（32 GB / 14 核，实测），彻底移除云 GPU 方案
> - 单窗口不做 Walk-Forward（预算不允许多窗口切分）
>
> **v2.0 变更要点**：
> 1. 新增 §5 **回测重构 & 证据故事线** —— 主角是"落地 EMNLP 论文方法前后的回测指标对比"，这是整份方案的销售点
> 2. 新增 §6 **产品思维：Badcase 闭环 + 数据飞轮 + 灰度发布 + 置信度校准**
> 3. 新增 §7 **内存预算与运行时约束**，基于两台服务器的真实 `free -h` 实测数据
> 4. §1-§4 保持 v1.0 核心内容（12 个优化项），但并入内存预算红线约束

---

## 0. Executive Summary

### 0.1 问题与证据

当前后端算法"能跑通"，但在 **agent 通信格式、决策聚合数学、RAG 冗余、撮合真实度、缓存鲁棒性** 五个维度存在可量化的改进空间。与此同时，产品层缺少 **Badcase → 数据飞轮 → 迭代** 的闭环，回测只覆盖 2023-2024 小样本，没办法**证明**任何算法改动是真的变好了。

本文档提出 **12 个算法级优化项 + 1 个回测重构 + 5 个产品闭环 + 1 份内存预算**。

| 档位 | 数量 | 性质 |
|------|------|------|
| **P0 · 方法论升级** | 3 项 | 会显著改变输出质量，建议立即做；含 EMNLP 2025 论文方法落地 |
| **P1 · 鲁棒性 & 正确性** | 5 项 | 存在已知缺陷或潜在误判，逐个修复 |
| **P2 · 工程化打磨** | 4 项 | 性能 / 成本 / 可维护性，时间允许时做 |
| **§5 回测重构** | 1 项 | 证据故事线的核心，出产算法 A/B 的量化结论 |
| **§6 产品闭环** | 5 项 | Badcase → 数据飞轮 → 灰度 → 校准 → 分群 |
| **§7 内存预算** | 1 份 | 硬约束，所有新增组件必须过这一关 |

### 0.2 故事线（The Narrative Arc）

整份方案是围绕一条叙事结构设计的，最终产出一句可复述的结论：

> "我们读到 EMNLP 2025 一篇关于多 Agent 证据共享的论文（《What Should LLM Agents Share?》），发现它的核心主张——**共享原始证据 > 共享结论**——恰好能解决 CampusQuant 的决策层锚定问题。我们在系统里加了 `evidence_citations` 字段（结构化数据由代码直接生成，新闻/RAG 才走 LLM 抽取），改写了 `portfolio_node` 和 `debate_node` 的 prompt，让基金经理和辩论裁判看到的是证据而不是结论。然后我们用 **20 支股票 × 3 年**（2023-01 → 2025-12）的月频回测，**2023-2024 作 in-sample、2025 作 holdout**，在同样的风控规则下跑了两组 A/B：Group A 用旧 prompt（hypothesis+rationale 共享），Group B 用新 prompt（evidence-cited 共享）。月度截面 block bootstrap 显著性检验下，Sharpe 从 X 提升到 X'，胜率 +Y pp，最大回撤 -Z pp，且 holdout 期方向一致。这是一个**探索性**的量化证据，配得上在简历/毕设里讲这一段。"

**股票池与时间跨度的选择依据**：
- **3 年**（非 7 年）：大学生极少持股超 3 年，用 7 年数据反而不贴合目标用户的行为周期
- **20 支**（非 30 / 80 支）：真实 Qwen3.5-Plus 单价下，¥100 预算内跑完 A/B 两组 + 留 ¥6 余量的最大可行规模
- **月度频率**（非双周）：月度观察日贴合大学生"看一次调一次"的真实频率，也是预算下能用 Qwen-Plus（跟生产模型一致）的唯一选择
- **2025 作 holdout**：吸收 reviewer 建议，2023-2024 作 in-sample，2025 年完全锁死不用于调 prompt，**免费的鲁棒性检查**

这条故事线贯穿全文，每个章节都在为这句话服务：
- §2-§4 做算法改进（P0-A 是核心，其他是辅助）
- §5 建回测底座，让 A/B 可执行
- §6 建产品闭环，让改进后的系统可以持续进化
- §7 定硬约束，保证所有改动在两台小服务器上能跑得动

### 0.3 硬约束

**内存**：cq-hk 总 882 MB / 余 200 MB；cq-inland 总 1.6 GB / 余 464 MB。任何新增组件必须过 §7 的预算表。

**成本**：LLM 调用预算 **≤ ¥100**（用于一次完整 A/B 回测；日常生产运行成本另计，与本方案解耦）。方案 A 实际预算 **¥94**（20 × 36 × 2 × ¥0.065），留 ¥6 余量。回测预计算脚本必须内嵌 `CostTracker(run_id)` + **¥95 硬停机制**。

**时间**：算法改动 1-2 周完成，回测 1 周完成（离线本地跑，¥94 预算），产品闭环 1 个月内先落 Badcase 收集和数据飞轮骨架。

**执行位置**：回测一律在**本地开发机**跑（32 GB RAM / 14 核，余量充裕），生产服务器永远不跑回测。

### 0.4 一句话总结

当前算法链的最大弱点不在各个 agent 的分析能力，而在 **agent 之间共享什么**——基金经理和辩论节点收到的都是"结论 + 置信度 + 推理摘要"，缺少可独立审核的原始证据。EMNLP 2025 论文实证：共享原始证据比共享结论在多跳 QA 上 EM 提升 +10.1 ~ +16.0 pp。这个结论直接适用于本系统的 `portfolio_node` 和 `debate_node`，我们要把它复现出来，用 **20 支股票 × 3 年**月度回测（2023-2024 in-sample + 2025 holdout）在 **¥94 预算内**（真实 Qwen3.5-Plus 单价下）写出探索性 A/B 数字。

---

## 1. 当前后端算法拓扑

### 1.1 主分析图（`graph/builder.py:build_graph`）

```
START → data_node
          │
   ┌──────┼───────┬───────────┐
   ▼      ▼       ▼           ▼
 fund_   tech_  sentiment_   rag_
 node    node   node         node            (4 路并行)
   │      │       │           │
   └──────┴───┬───┴───────────┘
              ▼
        portfolio_node ──── has_conflict=True ──► debate_node
              │                                        │
              │◄───────────────────────────────────────┘
              ▼
          risk_node
              │
     ┌────────┴──────────┐
     │ REJECTED          │ APPROVED / CONDITIONAL
     ▼                   ▼
  portfolio_node    trade_executor → END
  (最多重试 2 次)
```

### 1.2 独立分支

- **持仓体检**：`build_health_graph()` · `START → health_node → END`

### 1.3 关键算法函数一览

| 位置 | 函数 | 职责 |
|------|------|------|
| `graph/nodes.py:1339` | `_compute_weighted_score` | 三方加权分 + 多数投票覆盖（决策锚点） |
| `graph/nodes.py:1325` | `_MARKET_WEIGHTS` | 市场差异化权重（A/HK/US） |
| `graph/nodes.py:1447` | `has_conflict` 判定 | 基本面 vs 技术面 + 情绪反对 |
| `graph/nodes.py:_apply_atr_hard_block` | ATR 硬阻断 | risk_node 代码层强制风控 |
| `graph/nodes.py:_apply_confidence_penalty` | 置信度惩罚 | trade_executor 低置信度降仓 |
| `graph/nodes.py:_apply_max_loss_cap` | 单次亏损上限反算 | 基于 position×stop_loss 反推 |
| `tools/market_data.py:551` | `_calc_indicators_from_ohlcv` | MA/RSI/MACD/BOLL/ATR/量比 |
| `tools/market_data.py:105` | `_akshare_with_retry` | 指数退避重试（2 次，0.8s×n） |
| `tools/market_data.py:49` | `_cache_get/set` | 朴素 TTL dict 缓存 |
| `tools/knowledge_base.py:397` | `_build_ensemble_retriever` | BM25 50% + Chroma 50% RRF 融合 |
| `tools/knowledge_base.py:592` | `_expand_query_synonyms` | 查询扩展（20 条同义词表） |
| `api/mock_exchange.py:103` | `place_order` | 单价成交，无滑点，threading 锁 |
| `backtest/engine.py` | `BacktestEngine` | 日频回测，0.03% 手续费 + 0.1% 滑点，当前仅 equal_weight 策略 |

---

## 2. P0 · 方法论升级（3 项）

### 2.1 【P0-A】Agent 通信证据化改造（EMNLP 2025 方法落地）⭐️

#### 2.1.1 问题

当前 `portfolio_node` 和 `debate_node` 消费的是**处理后的结论**，不是**原始证据**：

**portfolio_node `nodes.py:1534-1553`：**
```python
user_prompt = f"""
【基本面报告】
- 建议: {fund_rec} | 置信度: {fundamental.get('confidence', 0):.2f}
- 核心逻辑: {fundamental.get('reasoning', 'N/A')[:200]}
- 关键因素: {', '.join(fundamental.get('key_factors', [])[:3])}
（下略技术/舆情同构字段）
"""
```

**debate_node `nodes.py:1731-1742`：**
```python
bull_argument = (
    f"立场: {fund_rec} | 置信度: {fundamental.get('confidence', 0.5):.2f}\n"
    f"论据: {fund_logic}\n"
)
```

这正是 EMNLP 2025 论文《What Should LLM Agents Share? Auditable Content Supports Belief Revision in Controlled Multi-Agent Deliberation》中定义的 **policyHypothesis + policyRationale 混合**：给了答案、置信度、处理后的推理，但没给**可独立审核的原始证据**。

#### 2.1.2 论文核心发现

3-agent、2-round、多跳 QA（HotpotQA / MuSiQue / 2WikiMultihopQA），4 个模型家族：

| 共享内容 | 格式 | EM (vs Hypothesis) | C→W 锚定率 | 机制 |
|----------|------|-------------------|-----------|------|
| **policyEvidence** | 原始证据文本 | **+10.1 ~ +16.0 pp** | ≈ 0% | 接收方可独立审核 |
| **policyRationale** | 答案+置信度+推理摘要 | 居中 | 高 | 被推理说服 |
| **policyHypothesis** | 只有答案+置信度 | 基线 | **最高** | 纯锚定 |
| **policyPrivate** | 不共享 | 低 | 0 | 无交流 |

**关键结论**：87-89% 的 EM 提升来自 W→C 恢复（wrong-to-correct），即"错误 agent 看到原始证据后自行修正"。Hypothesis 共享虽然传递了结论，但没传递让错误方醒悟的证据。

**轻量变体 ESC（Evidence-Summary-Cited）**：2-3 句推理摘要 + 1 条逐字证据引文。成本是 full-evidence 的 ~1/5，HotpotQA 上效果接近或略超 full-evidence。

#### 2.1.3 在 CampusQuant 的落地方案（v2.2 代码生成优化版）

> **v2.2 关键改进**：v2.1 的方案是"让 LLM 生成引文 + 模糊子串校验"，但基本面/技术面本来就是**结构化数据**（PE/PB/ROE/MA/MACD/RSI），让 LLM 复述这些数字既烧 token 又有"数字改错"的幻觉风险。v2.2 改为**代码直接从数据字典生成结构化引文**，LLM 只负责在 narrative 里解释这些引文的含义。只有新闻（`news_text`）和 RAG 片段（非结构化文本）才走 LLM 抽取 + 子串校验。

**Step 1 — 扩展 `AnalystReport` 模型**（`graph/state.py:55`）

```python
evidence_citations: List[str] = Field(
    default_factory=list,
    description="2-4 条结构化引文。基本面/技术面由代码从数据字典生成（无需 LLM 输出），"
                "sentiment/rag 由 LLM 从 news_text / rag_snippet 中抽取逐字片段。",
    max_length=5,
)
```

**Step 2 — 代码生成结构化引文**（`graph/nodes.py`，新增 helper 函数）

```python
# graph/nodes.py 新增
def build_fundamental_citations(data: dict) -> list[str]:
    """从 fund_data_dict 代码生成 2-3 条结构化引文，零幻觉。"""
    cites = []
    if data.get("pe") is not None:
        cites.append(f"PE={data['pe']:.1f}（行业中位数约 {data.get('industry_pe', 'N/A')}）")
    if data.get("roe") is not None:
        cites.append(f"ROE={data['roe']:.1f}%")
    if data.get("revenue_yoy") is not None:
        cites.append(f"营收同比 {data['revenue_yoy']:+.1f}%")
    if data.get("net_profit_yoy") is not None:
        cites.append(f"净利润同比 {data['net_profit_yoy']:+.1f}%")
    return cites[:3]

def build_technical_citations(indicators: dict) -> list[str]:
    """从 market_data.indicators 代码生成技术面引文。"""
    cites = []
    ma5, ma20, ma60 = indicators.get("MA5"), indicators.get("MA20"), indicators.get("MA60")
    if ma5 and ma20 and ma60:
        alignment = "多头排列" if ma5 > ma20 > ma60 else \
                    "空头排列" if ma5 < ma20 < ma60 else "震荡"
        cites.append(f"MA5={ma5:.2f} / MA20={ma20:.2f} / MA60={ma60:.2f}（{alignment}）")
    rsi = indicators.get("RSI14")
    if rsi is not None:
        state = "超买" if rsi > 70 else "超卖" if rsi < 30 else "中性"
        cites.append(f"RSI14={rsi:.1f}（{state}）")
    macd = indicators.get("MACD")
    sig  = indicators.get("MACD_signal")
    if macd is not None and sig is not None:
        cites.append(f"MACD={macd:.3f} / Signal={sig:.3f}（{'金叉' if macd > sig else '死叉'}）")
    atr_pct = indicators.get("ATR_pct")
    if atr_pct is not None:
        cites.append(f"ATR%={atr_pct:.1f}% (14 日波动率)")
    return cites[:4]
```

在 `fundamental_node` / `technical_node` 的末尾，**不经过 LLM 就**直接把这些引文塞进 `report_dict["evidence_citations"]`：

```python
# fundamental_node 末尾
report_dict = report.model_dump(mode='json')
report_dict["evidence_citations"] = build_fundamental_citations(fundamental_data_dict)
# technical_node 同理
report_dict["evidence_citations"] = build_technical_citations(indicators)
```

**Step 3 — sentiment_node 的 LLM 抽取引文（仅这一路需要 LLM）**

新闻和 RAG 是非结构化文本，只有 LLM 能理解"哪些是关键信息"。`sentiment_node` 的 prompt 里增加要求：

```
【证据引文】请从上方 news_text 和 rag_context 中**逐字复制** 1-2 条最有说服力的
原文片段放入 evidence_citations 字段。禁止改写、总结、拼接。每条 ≤100 字。
```

**Step 4 — 子串校验（仅对 sentiment 的 LLM 抽取引文）**

```python
def _validate_llm_citations(citations: list[str], source_text: str, min_ratio: float = 0.7) -> list[str]:
    """只保留至少 70% 字符能在 source_text 中找到的引文。"""
    valid = []
    for c in citations:
        if len(c) < 10:
            continue
        window = max(10, int(len(c) * min_ratio))
        if c[:window] in source_text or c[-window:] in source_text:
            valid.append(c)
    return valid[:2]  # sentiment 最多 2 条
```

不通过校验的引文直接剔除，并在 `observability/metrics` 里记 counter `evidence_citation_rejection_total{node="sentiment"}`，作为幻觉率指标。

**Step 5 — 改写 `portfolio_node.user_prompt`**

把当前的"建议+置信度+reasoning"顺序**反转**——先给证据，再给结论：

```python
user_prompt = f"""
请综合以下三位分析师提交的**原始证据与分析**，独立做出投资决策。

【一、基本面证据（原始数据，你应基于这些证据独立判断）】
{chr(10).join(f"  • {c}" for c in fundamental.get('evidence_citations', []))}
分析推理: {fundamental.get('reasoning', '')[:150]}

【二、技术面证据】
{chr(10).join(f"  • {c}" for c in technical.get('evidence_citations', []))}
分析推理: {technical.get('reasoning', '')[:150]}

【三、舆情证据】
{chr(10).join(f"  • {c}" for c in sentiment.get('evidence_citations', []))}
分析推理: {sentiment.get('reasoning', '')[:150]}

【各分析师的结论仅供参考，勿轻易锚定】
基本面建议: {fund_rec}（置信度 {fundamental.get('confidence', 0):.2f}）
技术面建议: {tech_rec}（置信度 {technical.get('confidence', 0):.2f}）
舆情建议:   {sent_rec}（置信度 {sentiment.get('confidence', 0):.2f}）

【量化预加权锚点】{pre_signal_text}

请优先从三方的原始证据出发做独立推理，再参考他们的结论与预加权锚点。
如果你的判断与多数分析师不一致，请在 reasoning 中说明你更相信的具体证据。
"""
```

**论文依据**：把答案字段放到**底部**并用"仅供参考"前缀是论文 Appendix 里的 ordering sensitivity 对照组——不会消除锚定，但削弱 first-impression 效应（论文证明主结论在反序下依然成立，E>H 在 8/8 cross-model cells 保持）。

**Step 6 — 改写 `debate_node` 的 bull/bear 论点构造**

```python
bull_argument = (
    f"【多头方证据（基本面分析师的结构化引文，代码生成）】\n"
    + "\n".join(f"  • {c}" for c in fundamental.get("evidence_citations", []))
    + f"\n【多头方核心论点】{fund_logic[:200]}"
)
bear_argument = (
    f"【空头方证据（技术面分析师的结构化引文，代码生成）】\n"
    + "\n".join(f"  • {c}" for c in technical.get("evidence_citations", []))
    + f"\n【空头方核心论点】{tech_logic[:200]}"
)
```

裁判 LLM 看到的是**结构化证据对峙**（代码生成的真实数字 + 状态标签）而非**结论对峙**，**零数字幻觉风险**。

#### 2.1.4 改动范围与风险（v2.2 版）

| 文件 | 改动量 | 风险 |
|------|--------|------|
| `graph/state.py` | +8 行 | 低（新增字段，向后兼容） |
| `graph/nodes.py` | ~100 行（`build_fundamental_citations` / `build_technical_citations` helper + sentiment prompt + portfolio/debate user_prompt + `_validate_llm_citations` 仅覆盖 sentiment） | 低（不改拓扑） |
| `bench/evidence_sharing_ab.py`（新建） | +200 行 | 0（离线） |

**v2.2 vs v2.1 的差异**：
- ❌ 去掉：对 fund/tech 引文的 LLM 生成 + 子串校验路径（代码生成无需校验）
- ✅ 新增：`build_fundamental_citations` / `build_technical_citations` 两个零 LLM 开销的 helper
- ✅ 保留：仅 sentiment 路走 LLM 抽取 + 子串校验（因为新闻/RAG 是非结构化文本）
- ✅ 输出 token 预计节省 ~20%（Group B 分析师不再复述数字）

**成功指标**：
- 结构化引文生成率 100%（代码逻辑，无随机性）
- sentiment LLM 抽取引文的子串校验通过率 ≥ 85%
- 三方分裂场景下（2 BUY vs 1 SELL 且置信度均 > 0.6）portfolio_node 与"独立重判"的方向一致率 ≥ 70%
- 辩论节点 `confidence_after_debate` 均值从当前 ~0.65 下降到 ~0.55
- **最关键**：§5 回测 A/B 中，Group B 的 Sharpe / 胜率 / MDD 在月度 block bootstrap 下方向一致优于 Group A

---

### 2.2 【P0-B】决策聚合数学重写 `_compute_weighted_score`

#### 2.2.1 问题

当前函数（`nodes.py:1339-1398`）：

```python
f_score = _REC_SCORE[f_rec] * f_conf   # BUY=1.0, HOLD=0.5, SELL=0.0
weighted_score = fw * f_score + tw * t_score + sw * s_score
# 阈值: >=0.52 BUY, <=0.40 SELL, 否则 HOLD
# 叠加: 2/3 多数且 conf>0.5 覆盖为 BUY/SELL
```

**问题 1：置信度与方向的耦合有歧义**
- `HOLD × conf=1.0 = 0.5`（中性 + 强确信）
- `BUY × conf=0.5 = 0.5`（看多 + 半信半疑）
- 两者分数相同，但语义不同。

**问题 2：BUY/SELL 阈值非对称（0.52 vs 0.40）**
- 注释写"降低 BUY 门槛 0.60→0.52"，主动引入**多头偏见**
- 大学生面临牛短熊长的 A 股，这种偏见会系统性地"高买"
- 没有经验或回测依据，拍脑袋选的

**问题 3：多数投票覆盖规则过强**
- 2/3 方向一致且各 conf>0.50 就直接翻越加权分
- 0.50 恰好是 fallback 置信度的下限，等于任何时候多数票都会覆盖
- 这让权重 `_MARKET_WEIGHTS` 形同虚设

**问题 4：无置信度方差惩罚**
- 三方 conf = `[0.9, 0.5, 0.5]`（一个确信 + 两个不确定）
- 三方 conf = `[0.7, 0.7, 0.5]`（两个中等信心 + 一个不确定）
- 两组 avg 差不多但风险明显不同，应该有分歧惩罚

#### 2.2.2 重写方案

```python
def _compute_weighted_score(
    fundamental: dict, technical: dict, sentiment: dict,
    weights: dict, market_type: str,
) -> dict:
    """
    改进版：分数与置信度解耦 + 分歧惩罚 + 对称阈值。
    """
    fw, tw, sw = weights["fundamental"], weights["technical"], weights["sentiment"]

    # 方向分: BUY=+1, HOLD=0, SELL=-1（以 0 为中性）
    DIR = {"BUY": 1.0, "HOLD": 0.0, "SELL": -1.0}
    f_dir, t_dir, s_dir = DIR[f_rec], DIR[t_rec], DIR[s_rec]
    f_conf = max(0.3, float(fundamental.get("confidence", 0.5)))
    t_conf = max(0.3, float(technical.get("confidence", 0.5)))
    s_conf = max(0.3, float(sentiment.get("confidence", 0.5)))

    # 加权方向分（-1 ~ +1）
    raw_score = fw * f_dir * f_conf + tw * t_dir * t_conf + sw * s_dir * s_conf

    # 分歧惩罚：三方方向标准差越大 → 越降低幅度
    dir_std = statistics.pstdev([f_dir, t_dir, s_dir])  # 0(全同) ~ 0.816(全反)
    disagreement_penalty = 1.0 - 0.4 * dir_std          # 最低 0.67
    adjusted_score = raw_score * disagreement_penalty

    # 对称阈值 ±0.20
    if adjusted_score >= 0.20:
        pre_signal = "BUY"
    elif adjusted_score <= -0.20:
        pre_signal = "SELL"
    else:
        pre_signal = "HOLD"

    # 多数投票：2/3 同向 且 同向平均置信度 ≥ 0.65
    buy_conf  = [c for r, c in [(f_rec, f_conf), (t_rec, t_conf), (s_rec, s_conf)] if r == "BUY"]
    sell_conf = [c for r, c in [(f_rec, f_conf), (t_rec, t_conf), (s_rec, s_conf)] if r == "SELL"]
    if len(buy_conf) >= 2 and statistics.mean(buy_conf) >= 0.65:
        pre_signal = "BUY"
    elif len(sell_conf) >= 2 and statistics.mean(sell_conf) >= 0.65:
        pre_signal = "SELL"

    avg_conf = fw * f_conf + tw * t_conf + sw * s_conf
    final_conf = avg_conf * disagreement_penalty

    return {
        "weighted_score":       round(adjusted_score, 3),  # -1 ~ +1
        "avg_confidence":       round(final_conf, 3),
        "disagreement_penalty": round(disagreement_penalty, 3),
        "pre_signal":           pre_signal,
        "majority_vote":        f"BUY×{len(buy_conf)} SELL×{len(sell_conf)}",
        "breakdown": {...},
    }
```

**关键改动**：
1. `DIR = {-1, 0, +1}` 替代 `{0, 0.5, 1}` → HOLD 的"置信度=1"不会再被误算
2. 对称阈值 `±0.20` 消除多头偏见
3. 分歧惩罚 `dir_std` → 越不一致，分数绝对值越低，更容易 HOLD
4. 多数投票阈值从 0.50 提到 0.65
5. 综合置信度也被分歧惩罚拉低，直接影响 `_apply_confidence_penalty`

**验证方法**：`bench/scoring_sanity.py` 构造 20 组极端情况测试，人工评分一致率 ≥ 85%。

---

### 2.3 【P0-C】RAG 检索层重构：从 4 次并行到 1 次共享 + 按需追问

#### 2.3.1 问题

每次 `/api/v1/analyze` 触发 **4 次 `search_knowledge_base` 调用**：

1. `rag_node`（`nodes.py:831`）：宽口径查询 → `state.rag_context`
2. `fundamental_node`（`nodes.py:944`）：`"{symbol} 财务报表 基本面 盈利 机构评级"`
3. `technical_node`（`nodes.py:1070`）：`"{symbol} 近期资金面 行业技术利好利空"`
4. `sentiment_node`（`nodes.py:1238`）：`"{symbol} 最新宏观政策 行业动态 突发新闻"`

外加 `debate_node` 触发时第 5 次。

**冗余代价**：
- 每次 RAG 走内地 relay，15s HTTP 超时，最坏 60s 累积
- 4 个 query 重叠严重，命中片段高度重复
- 内存占用：每次 query 都把 ~1KB 片段加入 prompt，总 5KB 进 LLM，付费重复
- `rag_node` 写的 `rag_context` 只给 portfolio/debate 用，分析师根本不读 → **预取 = 浪费**

#### 2.3.2 重构方案：共享池 + 按需追问

1. **删除独立 `rag_node`**，拓扑改为 `data_node → [fund/tech/sentiment 并行] → portfolio_node`
2. **共享 RAG 池 `state.rag_evidence_pool: Dict[str, List[str]]`** —— 在 `data_node` 尾部做一次宽口径检索，按主题分类到 4 个 bucket：
   ```python
   rag_evidence_pool = {
       "fundamental": [...],
       "technical":   [...],
       "sentiment":   [...],
       "shared":      [...],  # 跨主题兜底
   }
   ```
3. **三个分析师从池里读，不再发新 query**；必要时通过 `_check_tool_limit` 做 ≤1 次窄口径补检索
4. **portfolio / debate 也从池里读**，不再依赖独立 `rag_context`

**调用次数变化**：
- 最坏：1 预取 + 3 追问 + 1 debate = 5 次（与现状持平）
- 典型：1 + 0 + 0 = **1 次**
- 平均：**1.5 ~ 2.5 次**，较现在 4 次降 40-60%

**分类算法**：用关键词启发式（fundamental 关键词：PE/PB/ROE/财报/估值；technical：K线/MA/MACD；sentiment：政策/新闻/监管），落在两个以上 bucket 的进 `shared`。无需额外 embedding 调用。

**改动范围**：`graph/state.py` +5 行，`graph/builder.py` -1 节点 -4 条边，`graph/nodes.py` ~50 行。

---

## 3. P1 · 鲁棒性 & 正确性（5 项）

### 3.1 【P1-A】技术指标算法的盲区

**`_calc_indicators_from_ohlcv`（`market_data.py:551`）现状**：
- `tech_signal` 只用 MA5/MA20/RSI14 判定 → 完全没用到 MACD / BOLL / ATR
- 单周期 RSI14，无 6/14/28 多周期共振
- 算了 BOLL upper/mid/lower 但**没算 `BOLL_pct_B`**——而 `technical_node` prompt 里却在读它（`nodes.py:1087`），永远读到 None
- ATR% 直接 `atr14 / last_close × 100`，无历史分位数参照
- `volume_ratio` 只看当前 / 20 日均，没有换手率

**优化方案**：

1. **补 `BOLL_pct_B`**：`boll_pct_b = (close - lower) / (upper - lower)`

2. **多信号共振打分**：
   ```python
   signals = {
       "ma_bullish":   ma5 > ma20 > ma60,
       "macd_golden":  (macd_prev <= signal_prev) and (macd_now > signal_now),
       "rsi_moderate": 30 < rsi14 < 70,
       "boll_middle":  0.2 < boll_pct_b < 0.8,
       "volume_surge": volume_ratio >= 1.5,
   }
   bull_score = sum(signals.values())  # 0~5
   tech_signal = "strong_bullish" if bull_score >= 4 else \
                 "bullish"        if bull_score == 3 else \
                 "neutral"        if bull_score == 2 else \
                 "bearish"        if bull_score == 1 else "strong_bearish"
   indicators["tech_signal_detail"] = signals
   ```

3. **ATR 历史分位数**：`atr_percentile_90d = (atr14_series <= atr14_now).mean()`

4. **多周期 RSI**：RSI6 / RSI14 / RSI28，共振才算强。

---

### 3.2 【P1-B】冲突检测从二元 flag 改连续分数

**当前**：`has_conflict` 是 boolean，只检测"基本面 vs 技术面"或"情绪反对且 conf≥0.8"两种模式，遗漏"两方 HOLD + 一方强 BUY/SELL"等场景。

**优化方案**：

```python
def _conflict_score(recs: list, confs: list) -> dict:
    """返回 0~1 的冲突强度，≥0.6 触发辩论。"""
    DIR = {"BUY": 1, "HOLD": 0, "SELL": -1}
    dirs = [DIR[r] for r in recs]
    dir_std = statistics.pstdev(dirs)  # 0~0.816

    max_conflict = 0.0
    for i, j in [(0,1), (0,2), (1,2)]:
        if dirs[i] * dirs[j] < 0:
            max_conflict = max(max_conflict, min(confs[i], confs[j]))

    score = 0.6 * (dir_std / 0.816) + 0.4 * max_conflict
    return {"score": round(score, 3), "should_debate": score >= 0.60}
```

**额外信号**：三方全 HOLD 且 avg_conf < 0.50 → 进入"全员犹豫"分支，仓位强制压到 ≤ 3%。

---

### 3.3 【P1-C】辩论机制不是真正的多 agent 对话

**现状**：`debate_node` 是**一个 LLM** 扮演"裁判 + 多头 + 空头"三个角色，bull/bear 的"论点"是从 fundamental/technical 的 reasoning 字段截取的。这不是真辩论，是 single-LLM 自我角色扮演。

**问题**：自我确认偏差、置信度失真、无真实对抗。

**优化方案（两档）**：

**方案 A（真辩论）**：把辩论改成 3 次独立 LLM 调用
1. `bull_llm(temperature=0.7)` 扮演多头，反驳空头
2. `bear_llm(temperature=0.7)` 对称反驳多头
3. `judge_llm(temperature=0.1)` 看双方发言后裁决

成本 ×3，延迟 ~30s，但对抗性真实。

**方案 B（保留现状但诚实）**：
- 改名 `debate_node` → `devils_advocate_node`（魔鬼代言人）
- 明确文档：single-LLM adversarial self-reflection
- 减小 `confidence_after_debate` 变动幅度（从 ±0.2 降到 ±0.05）

**我的推荐**：先 B（零成本 + 诚实），回测观察效果后再考虑 A。

---

### 3.4 【P1-D】风控层缺少仓位管理数学基础（Kelly 部分推迟）

**当前**：仓位上限硬编码（A 15%, HK/US 10%），ATR 硬阻断 5%/8% 拍脑袋选的，`max_loss_amount` 写死 3000 元。没有 Kelly / 风险平价。

> **v2.2 重要变更**：Kelly 仓位的"根据 confidence 反推 win_rate"这条路径**推迟到 Phase 13**（§9 路线图中的第 7-10 周），理由见下。Phase 5-9 先只做 ATR 动态止损这一半。

#### 3.4.1 为什么 Kelly 要推迟

审阅指出的核心风险：**未校准的 confidence 直接驱动 Kelly 会放大模型偏差**。

```
未校准路径（危险）：
  LLM 输出 confidence=0.85（可能系统性高估）
  → win_rate ≈ 50% + (0.85 - 0.5) × 0.4 = 64%
  → Kelly 建议仓位 ~15%
  → 但真实胜率可能只有 55%，应建议仓位 5%
  → 结果：错判的单子被放大 3 倍
```

LLM 的 confidence 在未经校准前**系统性偏乐观**是已知现象。这一偏差如果直接喂进 Kelly，会把"错误的信号"放大成"错误的大仓位"——比不做 Kelly 更危险。

#### 3.4.2 正确的时序

```
Phase 5-9（Kelly 不接入）:
  风控只用硬上限（A 15% / HK 10% / US 10%） + 置信度惩罚（conf < 0.6 → × 0.5）
  + ATR 动态止损（本节 3.4.3）
  fixed_fraction = 0.25 写在配置里不动

Phase 12:
  §6.2 decisions 表上线，开始记录每次决策的 confidence 和后续 outcome_90d

Phase 13（第 7-10 周，等飞轮有数据）:
  按 confidence 分桶算真实胜率:
    SELECT ROUND(confidence*10)/10 AS bucket,
           AVG(outcome_90d > 0) AS real_win_rate
    FROM decisions
    GROUP BY bucket
  用 real_win_rate 替代 raw confidence 驱动 Kelly
  这时 Kelly 才真正校准，才能安全接入
```

#### 3.4.3 Phase 5-9 可以做的：ATR 动态止损（Kelly 的另一半）

这部分不依赖 confidence 校准，现在就可以接入：

```python
# risk_node 代码层强制执行（不依赖 Prompt 约束）
atr_based_stop = 2.0 * atr_pct
decision_dict["stop_loss_pct"] = max(decision_dict["stop_loss_pct"], atr_based_stop, 5.0)
```

**含义**：止损设置为 `max(LLM 给的止损, 2×ATR, 5%)`。高波动股票强制更宽的止损，避免被正常波动扫出。

#### 3.4.4 Phase 13 的 Kelly 校准版（预览）

```python
# Phase 13 才启用，依赖 decisions 表有 N ≥ 500 条带 outcome_90d 的历史
def calibrated_kelly_position(
    confidence: float,
    win_loss_ratio: float,
    calibration_table: dict[float, float],  # {0.5: 0.52, 0.6: 0.56, 0.7: 0.61, ...}
    kelly_fraction: float = 0.25,
) -> float:
    # 用历史真实胜率替代 raw confidence
    bucket = round(confidence * 10) / 10
    real_win_rate = calibration_table.get(bucket, 0.5)
    p, q = real_win_rate, 1 - real_win_rate
    b = win_loss_ratio
    full_kelly = max((b * p - q) / b, 0.0) if b > 0 else 0.0
    return min(full_kelly * kelly_fraction, 0.25)
```

**连续亏损降仓**：访问账户近 N 笔交易的胜率；胜率 < 0.3 → `position_pct × 0.5`。也推迟到 Phase 13。

---

### 3.5 【P1-E】模拟撮合引擎缺少市场真实性

**当前 `api/mock_exchange.py`**：
- 单价成交，无滑点、无部分成交
- 固定万三手续费（不分市场）
- `threading.Lock` 在 async 里会阻塞事件循环
- 无 T+1、无涨跌停限制
- `get_spot_price_raw` 走最新收盘价（非 tick）

**优化方案**：

1. **分市场手续费**：
   ```python
   FEE_RATES = {
       "A":  {"buy": 0.0003, "sell": 0.0013},  # 万三 + 千一印花
       "HK": {"buy": 0.00125, "sell": 0.00225},
       "US": {"buy": 0.0,     "sell": 0.00001},  # SEC fee
   }
   ```

2. **简单滑点**：成交价 = 收盘价 × (1 + sign × ATR_pct / 10 / 100)

3. **A 股 T+1**：`Position.last_bought_date`，当日买入禁卖

4. **涨跌停限制**：`(price - prev_close) / prev_close` 接近 ±10% → 拒单

5. **async 化**：`threading.Lock` → `asyncio.Lock`，`place_order` → `async def`

**硬规则不变**：`simulated=True`，永远不连真实交易所。

---

## 4. P2 · 工程化打磨（4 项）

### 4.1 【P2-A】缓存算法升级

**现状**：`tools/market_data.py:49-62` 朴素 `dict` + TTL，无淘汰、无锁、无穿透保护。

**优化方案**：
1. 换 `cachetools.TTLCache(maxsize=1000, ttl=300)`，内存上限确定
2. `asyncio.Lock`-per-key，并发去重
3. 连续失败的 key 进 30s 静默期（返回 sentinel）
4. cache hit/miss 进 Prometheus（`observability/metrics.py` 已有骨架）

**内存占用**：1000 条 × 平均 2KB/条 ≈ **2 MB**（远低于 §7 硬红线）

---

### 4.2 【P2-B】持仓体检加数学锚点

**现状**：`health_score` 完全由 LLM 输出，无可验证性。

**优化方案**：代码层基线评分 `compute_health_baseline()`，LLM 输出必须在 `baseline ± 15` 内否则截断：

```python
def compute_health_baseline(positions) -> dict:
    total_mv = sum(p.quantity * (p.current_price or p.avg_cost) for p in positions)
    weights = [(p.quantity * (p.current_price or p.avg_cost)) / total_mv for p in positions]
    hhi = sum(w ** 2 for w in weights)              # 0~1
    concentration_score = (1 - hhi) * 100           # 0~100
    market_diversity = min(len(set(p.market_type for p in positions)) / 3.0, 1.0) * 100
    overweight_count = sum(1 for w in weights if w > 0.15)
    overweight_penalty = overweight_count * 15
    baseline = max(0, 0.5*concentration_score + 0.3*market_diversity + 0.2*100 - overweight_penalty)
    return {"baseline_score": round(baseline, 1), ...}
```

---

### 4.3 【P2-C】LLM 响应缓存（磁盘版）

**现状**：同 symbol 5 分钟内被不同用户分析会重复付费。

**优化方案**：key = `hash(system_prompt + user_prompt + model_name + market_data_snapshot)`，TTL 300s。**存 SQLite 磁盘缓存**，不占 RAM（内存预算严）。

```python
from sqlitedict import SqliteDict
_llm_cache = SqliteDict("data/llm_cache.sqlite", autocommit=True)
```

只缓存分析师层（fundamental/technical/sentiment），不缓存 portfolio/risk/debate（依赖组合上游）。

**预期**：同 symbol 重复分析节省 ~60% token。

---

### 4.4 【P2-D】Prompt 外化 & 版本管理

**现状**：`_PROMPTS` 字典是 Python 字符串，改要重启。

**优化方案**：
1. 抽到 `prompts/*.yaml`，每个节点一个文件
2. `/api/v1/admin/reload_prompts` 热重载（JWT 管理员）
3. 每个 prompt 带 `version: v3.2` + `updated_at`，写入响应 metadata 便于 A/B

与 §6.3 Champion-Challenger 联动：没有版本号就做不了灰度。

---

## 5. 回测重构 & 证据故事线

> 这一节是整份方案的**主角**。所有前面的算法改动都是手段，最终目的是**在回测上看到 EMNLP 方法带来的量化改善**。

### 5.1 当前回测的局限

`backtest/engine.py`（347 行）+ `backtest/strategies/equal_weight.py`（目前唯一策略）：

| 问题 | 影响 |
|------|------|
| 时间区间 2023-2024（只 2 年） | 样本太小，Sharpe 置信区间宽到无意义 |
| 股票池固定（代码里写死） | 选股偏差，无法反映不同行业/市值/波动 |
| 只有 equal-weight 策略 | 没接 agent 决策，无法验证 LangGraph 输出价值 |
| 无 walk-forward | 阈值/权重可能 overfit 整段区间 |
| 无 baseline 对照 | 绝对指标无比较，不知道好坏 |
| OHLCV 从 akshare 实时拉 | 回测慢、不可复现、akshare 限流 |

**核心症结**：当前回测**不能回答一个问题**——"如果我改了 prompt，整体投资表现变好还是变坏？"而这恰恰是我们最需要回答的。

### 5.2 重构总览

```
┌─────────────────────────────────────────────────────────┐
│                 bench/backtest/ 新架构                   │
├─────────────────────────────────────────────────────────┤
│                                                          │
│  [1] 数据层  (离线，一次性下载后复用)                      │
│      20 支股票 × 2023-01 → 2025-12 → parquet/ 分文件     │
│      akshare + yfinance 拉取，~2 MB parquet 总量          │
│      本地盘缓存，无需 cron                                 │
│                                                          │
│  [2a] 异步 Signal 预计算 (bench/precompute_signals.py)   │
│      async graph.ainvoke × 20 股 × 36 月 × 2 版本         │
│      CostTracker(run_id) 按实验隔离成本，硬停 ¥95          │
│      输出 bench/data/signals_{version}.parquet           │
│      [date, symbol, action, confidence, qty_pct, ...]    │
│                                                          │
│  [2b] 同步 SignalReplayStrategy(Strategy)                 │
│      从 parquet 读取，sync generate() 直接返回            │
│      完美适配现有 sync BacktestEngine                      │
│                                                          │
│  [3] 引擎层  (现有 BacktestEngine 零改动)                 │
│      单窗口测试：2023-2024 in-sample + 2025 holdout        │
│      Baseline 对照组（5 个，全非 LLM）                     │
│      成本/滑点/T+1 已在 P1-E 解决                          │
│                                                          │
│  [4] 报告层  (bench/backtest/report.py)                  │
│      Sharpe / Sortino / Calmar / MDD                     │
│      胜率 / Profit factor                                │
│      决策精度（BUY 后 30/60/90 天超额收益）               │
│      置信度校准曲线（reliability diagram）                │
│      A/B 对比表（baseline vs ESC）← 故事线终点            │
│                                                          │
└─────────────────────────────────────────────────────────┘
```

### 5.3 数据层重设计

#### 5.3.1 股票池构造（20 支）

目标：真实 Qwen3.5-Plus 单价（¥0.065/analyze）下，¥100 LLM 预算内能跑完 A/B 两组 + 留 ¥6 余量的最大规模，同时保持跨市场 + 跨风格的代表性。

| 组 | 数量 | 构成 | 理由 |
|----|------|------|------|
| **A 股大盘蓝筹 + 金融** | 6 | **贵州茅台**（消费）、**宁德时代**（新能源）、**招商银行**（银行）、**中国平安**（保险）、**比亚迪**（汽车）、**中信证券**（券商龙头） | A 股核心价值配置，券商作为券商板块代表 |
| **A 股中盘成长** | 2 | **中芯国际**、**韦尔股份** | 半导体代表，近 3 年营收 CAGR > 20% |
| **A 股主题** | 2 | **寒武纪**（AI 算力）、**阳光电源**（新能源） | 捕捉主题行情波动 |
| **港股恒生科技** | 3 | **腾讯**、**阿里**、**美团** | 港股互联网主力 |
| **港股蓝筹** | 2 | **汇丰**、**友邦** | 港股传统金融 |
| **美股科技** | 3 | **AAPL**、**MSFT**、**NVDA** | 美股 Mag7 核心 |
| **美股其他** | 2 | **AMZN**（消费）、**JPM**（金融） | 风格分散 |
| **合计** | **20** | A 10 + HK 5 + US 5 | |

**避免幸存者偏差**：故意纳入 2023-2025 期间回撤严重的标的（如部分中概股），让回测体现真实熊市环境。**排除**：退市股、长期停牌股。

**相比 v2.1 的变更**：v2.1 的 30 支版本（A15 + HK8 + US7）在真实 Qwen3.5-Plus 单价下成本约 ¥140，超预算 40%。v2.2 收到 20 支后成本为 ¥94（20 × 36 × 2 × ¥0.065），留 ¥6 安全余量。金山办公在 v2.1 作为成长股代表，v2.2 被中信证券替换以纳入券商行业代表。

**文件**：`bench/backtest/universe.yaml` 固化清单 + 纳入日期 + 备注字段。

#### 5.3.2 OHLCV 存储

- 格式：**parquet**（列存 + snappy 压缩，比 CSV 小 80%）
- 路径：`bench/data/ohlcv/{market}/{symbol}.parquet`
- 字段：`date, open, high, low, close, volume, adj_close`
- 大小估算：20 支 × 750 行（3 年交易日）× 7 列 × 8 字节 ≈ **0.9 MB 总量**；加 metadata 和索引约 **2 MB**。本地盘轻松胜任，`.gitignore` 掉不入库。

**下载脚本**：`scripts/download_universe_history.py`
- 从 akshare（A/HK）+ yfinance（US）拉 **2023-01-01 → 2025-12-31**
- 指数退避重试，失败 symbol 日志到 `bench/data/universe_errors.log`
- 一次性下载，无需增量更新（3 年区间固定不动）
- 预计运行时间 **~7 分钟**（20 支 × 2-5 秒/支 + 重试），完全免费（akshare/yfinance 0 成本）

#### 5.3.3 运行位置：本地开发机

**实测本地配置**：
- 总内存 **32 GB**，可用 ~15 GB
- CPU **14 物理核 / 20 逻辑核**
- 磁盘：充裕

**为什么不在生产服务器跑**：

| 位置 | 可跑 | 原因 |
|------|------|------|
| **本地开发机** | ✅ 首选 | 15 GB 余量 >> 600 MB 回测峰值（3.8% 占用） |
| cq-hk (882 MB) | ❌ | 余量 200 MB，跑回测必 OOM |
| cq-inland (1.6 GB) | ❌ | 464 MB 余量虽能跑但会挤占 Chroma/MySQL，影响生产 |
| 云 GPU 实例 | ❌ 不必要 | 本地已足够，无须花钱 |

**硬规则**：`cq-hk` / `cq-inland` 永远只跑 API 主应用与 relay，回测一次都别跑；所有回测代码位于 `bench/` 目录，与 `api/` 解耦，不会被生产进程加载。

**并发建议**：本地 14 核可以把 `AgentStrategy` 的 `asyncio.Semaphore` 从默认 5 提到 **10**，充分利用多核但不撑爆 DashScope API 的 20 RPS 限流。

### 5.4 Agent 策略适配：预计算 + 重放 两阶段

#### 5.4.1 背景：为什么不能直接 async 化现有引擎

现有 `backtest/engine.py`（347 行，已验证）是**完全同步**的：

- `class Strategy` 的 `generate(self, t, prices) -> list[Signal]` 是 `def`
- `BacktestEngine.run()` 的主循环直接 `self.strategy.generate(t, prices)`
- 引擎内部用的是 pandas + dict，全部同步

如果硬把 `Strategy.generate` 改成 `async def`，需要把整个 `BacktestEngine.run` + 止损检查 + rebalance 都改成 async，**范围太大且没必要**——因为回测引擎本身跑得极快（每天 ~1ms），慢的只有 LLM 调用。

**正确做法（v2.2，吸收 reviewer #2 建议）**：**两阶段解耦**——先异步预计算所有 LLM 产出的信号，存 parquet；再用同步策略读 parquet 喂给现有引擎。

```
Phase 1（慢，离线，异步）：
  bench/precompute_signals.py
  ─────────────────────────────
  for (month, symbol, version) in cartesian_product:
      signal = await graph.ainvoke(state, config={"cost_tracker": ...})
      append to signals_{version}.parquet
  
  输出：
    bench/data/signals_v1_baseline.parquet  (720 行)
    bench/data/signals_v2_esc.parquet       (720 行)

Phase 2（快，同步，可多次重放）：
  bench/backtest/signal_replay_strategy.py
  ─────────────────────────────────────────
  class SignalReplayStrategy(Strategy):
      def __init__(self, signals_parquet_path):
          self.df = pd.read_parquet(signals_parquet_path)  # 一次性读入
      
      def generate(self, t, prices):
          monthly_signals = self.df[self.df["date"] == t]
          return [Signal(s.symbol, weight=s.weight) for s in monthly_signals.itertuples()]
  
  直接喂给现有 BacktestEngine，零引擎改动
```

**这样做的好处**：
1. **零改动现有引擎**——`backtest/engine.py` 不动一行
2. **慢快分离**——LLM 跑一次，回测可以跑 N 次（调策略参数、滑点模型、止损规则都不用重跑 LLM）
3. **可审计**——`signals_*.parquet` 就是 A/B 两组的原始决策快照，任何人可以事后复查
4. **便于扩展**——将来想做 walk-forward 多窗口，只要 filter parquet 的日期列即可，LLM 零额外开销

#### 5.4.2 Phase 1：异步 Signal 预计算脚本

```python
# bench/precompute_signals.py
import asyncio
import pandas as pd
from graph.builder import build_graph, make_initial_state
from observability.llm_tracker import CostTracker

async def precompute_signals(
    universe: list[str],
    start_date: str,
    end_date: str,
    version: str,          # "v1_baseline" or "v2_esc"
    graph,                 # 对应版本的已编译 graph
    output_path: str,
    hard_stop_cny: float = 47.0,  # A/B 各占预算一半
) -> pd.DataFrame:
    """
    对 universe × 每月首交易日 × version 跑一遍 analyze graph，
    把输出的 TradeOrder 写成 parquet，供 SignalReplayStrategy 读取。
    """
    tracker = CostTracker(run_id=f"ab_{version}", hard_stop_cny=hard_stop_cny)
    semaphore = asyncio.Semaphore(10)   # 本地 14 核，限 10 并发

    rebalance_dates = _get_monthly_first_trading_days(start_date, end_date)
    rows = []

    async def run_one(symbol, date):
        async with semaphore:
            state = make_initial_state(symbol)
            state["market_data_override_date"] = date  # 让 data_node 拉历史数据
            config = {"configurable": {
                "cost_tracker": tracker,
                "thread_id": f"{version}:{symbol}:{date}",
            }}
            try:
                result = await graph.ainvoke(state, config=config)
                trade_order = result.get("trade_order", {})
                rows.append({
                    "version": version,
                    "date":    date,
                    "symbol":  symbol,
                    "action":  trade_order.get("action", "HOLD"),
                    "confidence": trade_order.get("confidence", 0.5),
                    "quantity_pct": trade_order.get("quantity_pct", 0.0),
                    "stop_loss":    trade_order.get("stop_loss"),
                    "take_profit":  trade_order.get("take_profit"),
                    "reasoning":    trade_order.get("rationale", "")[:200],
                    "evidence_citations": trade_order.get("evidence_citations", []),
                })
            except CostExceeded as e:
                logger.error(f"[{version}] 成本硬停: {e}")
                raise

    tasks = [run_one(s, d) for d in rebalance_dates for s in universe]
    await asyncio.gather(*tasks, return_exceptions=False)

    df = pd.DataFrame(rows).sort_values(["date", "symbol"])
    df.to_parquet(output_path, index=False)
    logger.info(f"[{version}] 预计算完成: {len(df)} 行, 成本 ¥{tracker.total_cny:.2f}, 写入 {output_path}")
    return df
```

**运行时间预估**：
- 20 支 × 36 月 = 720 次 analyze / version
- Semaphore(10) 并发 + 单次 ~5-8 秒 = 约 **6-10 分钟 / version**
- A + B 两组合计 **~20 分钟**

#### 5.4.3 Phase 2：同步 SignalReplayStrategy

```python
# bench/backtest/signal_replay_strategy.py
import pandas as pd
from backtest.engine import Strategy, Signal

class SignalReplayStrategy(Strategy):
    """
    从预计算的 signals parquet 读取，sync 返回信号。
    完美适配现有 sync BacktestEngine，零改动。
    """
    def __init__(self, signals_parquet: str, version: str):
        self.name = f"signal_replay_{version}"
        self.df = pd.read_parquet(signals_parquet)
        self.df["date"] = pd.to_datetime(self.df["date"]).dt.date
        self._last_rebalance_month: tuple[int, int] | None = None

    def generate(self, t, prices: dict[str, float]) -> list[Signal]:
        # 只在每月首个交易日返回信号，其他日子返回空列表
        if self._last_rebalance_month == (t.year, t.month):
            return []
        self._last_rebalance_month = (t.year, t.month)

        # 取当月所有信号（date == t 或 date 是当月首交易日）
        monthly = self.df[
            (self.df["date"].dt.year == t.year) &
            (self.df["date"].dt.month == t.month)
        ]
        if monthly.empty:
            return []

        signals = []
        for row in monthly.itertuples():
            if row.action == "BUY" and row.confidence >= 0.6:
                weight = min(row.quantity_pct / 100, 0.1)
                signals.append(Signal(symbol=row.symbol, weight=weight))
            elif row.action == "SELL":
                signals.append(Signal(symbol=row.symbol, weight=0.0))
        return signals
```

**关键设计点**：

1. **完全同步**：继承现有 `Strategy` 基类，`generate()` 是 `def` 不是 `async def`，可直接喂给现有 `BacktestEngine`
2. **一次读入**：`pd.read_parquet` 一次读全表到内存（~200 KB，零压力）
3. **月度过滤**：只在月份切换时返回一次信号，其他日子返回 `[]`，匹配 v2.1 的月度节奏
4. **信号转换**：`BUY + conf≥0.6 → weight=min(quantity_pct/100, 0.1)`，`SELL → weight=0`
5. **最多 10 个仓位**：在引擎层控制（或在这里 `signals[:10]` 截断）
6. **零 LLM 调用**：预计算阶段已跑完，重放阶段可无限次重复

**优势相对 v2.1 原设计**：
- ✅ 不改 `backtest/engine.py`，零 blocker 风险
- ✅ 调策略参数（止损规则、Kelly 系数）不用重跑 LLM，节省成本
- ✅ signals parquet 作为中间产物可 git-track（纳入 `bench/data/`），A/B 结果可复现

### 5.5 成本估算与预算

#### 5.5.1 单次 analyze 的 LLM 成本（真实定价）

每次完整 analyze 在实测下的 LLM 调用情况：

| 节点 | LLM 调用数 | 输入 token | 输出 token |
|------|----------|-----------|-----------|
| fund / tech / sentiment | 3 | ~24K | ~6K |
| portfolio | 1 | ~4K | ~1K |
| debate（15% 触发） | 0.15 | ~0.5K | ~0.2K |
| risk | 1 | ~2K | ~0.5K |
| trade_executor | 1 | ~1K | ~0.5K |
| **总计** | **~6.15** | **~31.5K 输入** | **~8.2K 输出** |

**Qwen3.5-Plus 真实定价**（DashScope ≤128K 档位，我们全部 analyses 都在此档）：
- 输入：**¥0.8 / 1M token** = ¥0.0008/1K
- 输出：**¥4.8 / 1M token** = ¥0.0048/1K
- 128K-256K 档和 256K-1M 档更贵（2/12 和 4/24 per M），但我们的 31.5K 输入完全用不到

**单次成本**：
- 输入：31.5 × ¥0.8 / 1000 = **¥0.0252**
- 输出：8.2 × ¥4.8 / 1000 = **¥0.0394**
- **合计：¥0.0646 / analyze**

安全系数取 **¥0.065 / analyze**（留出 debate 重试、结构化输出纠错重试、网络波动缓冲）。

> ⚠️ **v2.2 订正**：v2.1 写的 ¥0.04 / analyze 是凭印象估算（基于旧版 qwen-plus 公网价 ¥0.002/1K 输出），真实 Qwen3.5-Plus 输出单价是 ¥0.0048/1K（2.4 倍），导致全案预算 ×1.6。同时代码 `observability/llm_tracker.py:24` 里写的 `{"in": 0.004, "out": 0.012}` 是 256K-1M 大窗口档位的 per-1K 价，对 31K 输入场景**又多算了 5 倍**（见 Phase 5.5 子任务）。

#### 5.5.2 总预算计算

| 参数 | 取值 |
|------|------|
| 股票池 | **20 支** |
| 时间跨度 | 3 年（2023-01 → 2025-12） |
| In-sample | 2023-01 → 2024-12（24 个月） |
| Holdout | 2025-01 → 2025-12（12 个月，锁死） |
| 观察频率 | 每月首个交易日 |
| 每股 observation 数 | 36 个月 × 1 = **36** |
| 每组 analyses | 20 × 36 = **720** |
| A/B 两组 | 720 × 2 = **1440** |
| 单次成本 | ¥0.065 |
| **总成本** | **¥94** |

**预算上限**：**¥100**，实际 ¥94，留 ¥6 安全余量用于：
- Debate 触发率超 15% 预期
- 网络重试 / 结构化输出解析兜底
- 失败后的局部回跑

> **P0-A 代码生成引文带来的额外节省**：Group B（ESC）因为 evidence_citations 由代码生成而非 LLM 输出，每次 analyze 输出 token 减少 ~20%（8.2K → 6.5K），Group B 单次成本降至 ~¥0.056。两组实际总成本约 **¥87**，余量进一步扩大到 ¥13。

#### 5.5.3 替代方案比较（为什么选 A）

| 方案 | 频率 | 模型 | Universe | 单次 | 成本 | 入选 |
|------|------|------|----------|------|------|------|
| **⭐ A（本方案）** | **月度** | **Plus** | **20** | **¥0.065** | **¥94** | ✅ |
| A- (v2.1 原案) | 月度 | Plus | 30 | ¥0.065 | ¥140 | ❌ 超预算 40% |
| B | 月度 | Turbo | 60 | ¥0.024 | ¥104 | ❌ Turbo 与生产不一致 |
| C | 双周 | Plus | 10 | ¥0.065 | ¥94 | ❌ 样本太小统计不显著 |
| D | 每 6 周 | Plus | 30 | ¥0.065 | ¥101 | ❌ 频率太稀疏，略超 |

**选 A 的核心理由**：
1. **模型一致**：跟生产线上一样用 Qwen3.5-Plus，A/B 结果可直接外推到线上
2. **频率贴合**：大学生持股超 3 年都很少，月度观察比双周更贴合真实用户行为
3. **统计功效**：20 支 × 36 个月 = 720 observations per group，支撑 block bootstrap 显著性检验（见 §5.8）
4. **预算余量充足**：留 ¥6-13 兜底，不是卡着红线跑
5. **Holdout 可用**：2025 作 holdout 12 个月，2023-2024 作 in-sample 24 个月，比例 2:1 合理

#### 5.5.4 成本监控（CostTracker 按实验隔离）

**为什么需要按实验隔离**：模块级全局变量 `_cumulative_cost_cny` 会被 A/B 两组、shadow run、甚至线上生产请求同时写入，导致成本归因混乱。正确做法是每个"实验"（A/B 各一次、shadow 一次…）持有独立 tracker 实例。

```python
# observability/llm_tracker.py (v2.2 新增)
class CostTracker:
    def __init__(self, run_id: str, hard_stop_cny: float = 95.0):
        self.run_id = run_id
        self.hard_stop = hard_stop_cny
        self._total_cny = 0.0
        self._n_calls = 0
        self._lock = asyncio.Lock()

    async def record(self, *, model: str, prompt_tokens: int, completion_tokens: int):
        async with self._lock:
            cost = self._compute_cost(model, prompt_tokens, completion_tokens)
            self._total_cny += cost
            self._n_calls += 1
            if self._n_calls % 100 == 0:
                logger.info(
                    f"[CostTracker:{self.run_id}] N={self._n_calls}, "
                    f"total=¥{self._total_cny:.2f}, avg=¥{self._total_cny/self._n_calls:.4f}/call"
                )
            if self._total_cny >= self.hard_stop:
                raise CostExceeded(
                    f"{self.run_id}: ¥{self._total_cny:.2f} >= ¥{self.hard_stop}"
                )
            return cost

    @staticmethod
    def _compute_cost(model, p_tok, c_tok):
        # Qwen3.5-Plus ≤128K 档位真实定价
        if model.startswith("qwen") and "plus" in model:
            return p_tok / 1000 * 0.0008 + c_tok / 1000 * 0.0048
        if model.startswith("qwen") and "turbo" in model:
            return p_tok / 1000 * 0.0003 + c_tok / 1000 * 0.0006
        # 其他模型按当前 _COST_TABLE
        raise ValueError(f"Unknown model: {model}")

    @property
    def total_cny(self) -> float:
        return self._total_cny
```

**接入 LangGraph**：通过 `config.configurable.cost_tracker` 传入节点：

```python
# bench/precompute_signals.py
tracker_a = CostTracker(run_id="ab_2026_04_14_baseline", hard_stop_cny=47.0)  # A 组限额一半
config_a = {"configurable": {"cost_tracker": tracker_a, "thread_id": "..."}}
await graph.ainvoke(state, config=config_a)

tracker_b = CostTracker(run_id="ab_2026_04_14_esc", hard_stop_cny=47.0)
# B 组使用独立 tracker
```

**节点内使用**（在 `graph/nodes.py` 的 `_invoke_structured_with_fallback` 之后）：

```python
tracker = config.get("configurable", {}).get("cost_tracker")
if tracker and hasattr(raw_resp, "usage_metadata"):
    await tracker.record(
        model=config.DASHSCOPE_MODEL,
        prompt_tokens=raw_resp.usage_metadata.get("input_tokens", 0),
        completion_tokens=raw_resp.usage_metadata.get("output_tokens", 0),
    )
```

**Phase 5.5 子任务（必做）**：
1. 订正 `observability/llm_tracker.py:23-31` 的 `_COST_TABLE`：
   ```python
   _COST_TABLE = {
       # Qwen3.5-Plus ≤128K 档位真实定价（2026 Q1 DashScope）
       "qwen-plus":     {"in": 0.0008, "out": 0.0048},
       "qwen3.5-plus":  {"in": 0.0008, "out": 0.0048},
       # 256K-1M 档位另设，但日常 analyze 用不到
       "qwen-plus-long":{"in": 0.004,  "out": 0.024},
       "qwen-turbo":    {"in": 0.0003, "out": 0.0006},
       ...
   }
   ```
2. 新增 `CostTracker(run_id)` 类（见上）
3. 在 `_invoke_structured_with_fallback` 末尾接入 tracker.record()
4. 本地单元测试：假造 usage → 验证成本累计正确、硬停抛异常

**硬约束**：如果 `observability/llm_tracker.py` 没落地 `CostTracker` + 真实单价，P0-A 的回测**不许开跑**——宁可延迟一天先把 tracker 修好，也别开一个没有油表的飞机。

### 5.6 探索性 A/B：In-sample + Holdout 设计

```
├──────── In-sample (调 prompt) ────────┤─── Holdout (锁死) ───┤
  2023-01                          2024-12 2025-01          2025-12
  
  In-sample:  24 个月，允许看结果迭代 prompt
  Holdout:    12 个月，prompt 冻结后只跑一次，独立报告
```

**为什么把 A/B 定义成探索性而不是"显著性证据"**：

吸收外部审阅意见，本方案的 A/B 定位为**探索性 (exploratory) 证据**，不是学术级的因果推断。理由：

1. **1440 observations 不是 1440 个独立样本**：同一月份内所有 A 股高度相关（共同市场冲击），同一股票相邻月份强自相关。朴素 paired bootstrap 会严重高估显著性。
2. **预算不允许多窗口 walk-forward**：¥100 分成 3 个滚动窗口后每窗口仅 ~13 支 × 1 年，统计功效不足。
3. **3 年区间覆盖一轮完整牛熊**（2023 结构性行情 → 2024 下跌 → 2025 反弹），单窗口的时间多样性对探索性目的足够。

**In-sample vs Holdout 设计**：
- **In-sample（2023-01 → 2024-12，24 个月）**：允许看指标调 prompt、调阈值、调 evidence_citations 模板。这是**工程迭代空间**。
- **Holdout（2025-01 → 2025-12，12 个月）**：prompt 在 in-sample 跑完后**完全冻结**，holdout 独立运行一次，结果单独报告。任何"holdout 成绩不好就回头改 prompt 再跑"都构成 p-hacking，**直接作废方案**。
- **比例 24:12 = 2:1** 合理，且不影响 ¥94 总预算（仍然 20 × 36 × 2 × ¥0.065）。

**为什么不做 Walk-Forward 滚动**：
- 已在上面说明（预算不允许 + 探索性目标不需要）
- 想要更严谨的滚动证据，放到未来版本 v3.0，等数据飞轮积累 90d outcome 后再说

**关键纪律**：
- 测试期指标发布后，**不允许回头改 prompt 再跑 holdout**
- 如果 P0-A 证据化改造之后想再迭代，测试期必须**往后延一年**（2026）——等实盘数据积累
- 想要更严谨的 walk-forward 证据，放到未来版本 v3.0 再做，目前不要动

**Hyperparameter 固定**（in-sample 阶段之前一次性锁定，in-sample 跑完允许微调，holdout 前再次冻结）：
- `_MARKET_WEIGHTS` 沿用当前生产值
- `conflict_score` 阈值固定 0.60
- Kelly fraction 固定 0.25（且本阶段 Kelly 不接入，见 §3.4 P1-D 推迟说明）
- evidence_citations 的代码生成模板（见 §2.1.3）

### 5.7 Baseline 对照组（6 组）

| 编号 | 组 | 说明 |
|------|----|----|
| B0 | **Buy-and-Hold** | 每支股票等权重持有到底 |
| B1 | **月度 Equal-Weight** | 每月再平衡到等权 |
| B2 | **Index Baseline** | CSI300 + HSI + SPX 三等权 |
| B3 | **Random Signal** | 同样风控规则下随机 BUY/SELL/HOLD |
| **A** | **Baseline Agents** | 当前 prompts（hypothesis+rationale 共享） |
| **B** | **ESC Agents** | P0-A 之后的 evidence-cited prompts |

**最关键的对比**：**A vs B** → 故事线终点

**次要对比**：B vs B2（Agent 是否打败了指数？）、B vs B3（Agent 是否比随机好？）

### 5.8 指标清单

#### 5.8.1 标准金融指标

- **年化收益率**（Return）
- **Sharpe Ratio**（`(R - Rf) / σ`，Rf=3% 无风险利率）
- **Sortino Ratio**（只惩罚下行波动）
- **Calmar Ratio**（`return / max_drawdown`）
- **最大回撤**（Max Drawdown）
- **胜率**（winning_trades / total_trades）
- **Profit Factor**（`gross_profit / gross_loss`）

#### 5.8.2 决策质量指标（本项目专属）

- **BUY 后 30/60/90 天超额收益**：相对 index 的超额部分
- **SELL 后 30/60/90 天避损率**：卖出后股票下跌 → 正向
- **置信度校准斜率**：把所有决策按 confidence 分箱（0-0.6, 0.6-0.7, 0.7-0.8, 0.8-0.9, 0.9-1.0），每箱算实际胜率，画 reliability diagram。理想曲线 y=x，偏离越小越好。

#### 5.8.3 Agent 内部行为指标

- **辩论触发率**（has_conflict = True 的比例）
- **风控拒绝率**（risk_rejection_count > 0 的比例）
- **HOLD 比例**（LLM 选 HOLD 占所有决策的比例）
- **引文子串校验通过率**（仅对新闻/RAG 抽取的引文，结构化引文由代码生成无需校验）
- **LLM token 使用量 / 次分析**

#### 5.8.4 统计显著性方法（探索性 A/B 专用）

考虑到月度截面相关和股票自相关，朴素 paired bootstrap 不适用。采用**月度 block bootstrap**：

```python
def monthly_block_bootstrap(
    returns_a: pd.Series,  # Group A 的月度收益，index 是月末日期
    returns_b: pd.Series,  # Group B 同上，共 24 或 36 个月
    n_resamples: int = 10000,
    metric_fn=sharpe_ratio,
) -> dict:
    """以月为 block 重抽样，保留截面相关，打破时间相关。"""
    n_months = len(returns_a)
    deltas = []
    for _ in range(n_resamples):
        # 有放回抽 n_months 个月份
        sampled_idx = np.random.choice(n_months, size=n_months, replace=True)
        delta = metric_fn(returns_b.iloc[sampled_idx]) - metric_fn(returns_a.iloc[sampled_idx])
        deltas.append(delta)
    return {
        "point_estimate": metric_fn(returns_b) - metric_fn(returns_a),
        "ci_95_low":  np.percentile(deltas, 2.5),
        "ci_95_high": np.percentile(deltas, 97.5),
        "p_two_sided": 2 * min((np.array(deltas) <= 0).mean(), (np.array(deltas) >= 0).mean()),
    }
```

**报告格式**：对 Sharpe / Sortino / 胜率 / MDD / BUY-后-90d 超额 5 个关键指标，各做一次 block bootstrap，给出 **point estimate + 95% CI**。**不报 p-value**，只报 CI 是否跨零（更诚实）。

**Leave-One-Market-Out (LOMO) 稳健性检查**（免费增量）：
- 在 A/B 结果之外，另报三次切片：去 A 股、去港股、去美股
- 如果三次切片下 Group B 相对 Group A 的方向**全部一致**，说明效果不是被单一市场驱动的
- 如果有一个市场切片翻盘，在最终报告里**显著标注**这个局限

**Holdout 报告**：
- In-sample 指标（2023-2024，24 个月）和 holdout 指标（2025，12 个月）**并列展示**
- 如果 holdout 方向与 in-sample 一致 → 支持效果稳健
- 如果 holdout 方向与 in-sample 相反 → 疑似 in-sample 过拟合，需要明确告知读者并在结论里降级表述

### 5.9 A/B 故事线（The Climax）

**两个脚本，两阶段执行**：

```python
# bench/evidence_sharing_ab.py
import asyncio
import pandas as pd
from pathlib import Path

from graph.builder import build_graph
from bench.precompute_signals import precompute_signals
from bench.backtest.signal_replay_strategy import SignalReplayStrategy
from backtest.engine import BacktestEngine
from bench.backtest.report import generate_ab_report

UNIVERSE_YAML    = "bench/backtest/universe.yaml"
IN_SAMPLE_START  = "2023-01-01"
IN_SAMPLE_END    = "2024-12-31"
HOLDOUT_START    = "2025-01-01"
HOLDOUT_END      = "2025-12-31"
FULL_START, FULL_END = IN_SAMPLE_START, HOLDOUT_END

SIGNALS_A = Path("bench/data/signals_v1_baseline.parquet")
SIGNALS_B = Path("bench/data/signals_v2_esc.parquet")

# ──────────────────────────────────────────────────────────────
# Phase 1: 异步预计算 A/B 两组信号（这里烧 LLM 预算）
# ──────────────────────────────────────────────────────────────
async def phase1_precompute():
    universe = load_universe(UNIVERSE_YAML)       # 20 支

    if not SIGNALS_A.exists():
        graph_a = build_graph(prompt_version="v1_baseline")
        await precompute_signals(
            universe, FULL_START, FULL_END,
            version="v1_baseline", graph=graph_a,
            output_path=SIGNALS_A, hard_stop_cny=47.0,
        )

    if not SIGNALS_B.exists():
        graph_b = build_graph(prompt_version="v2_esc")
        await precompute_signals(
            universe, FULL_START, FULL_END,
            version="v2_esc", graph=graph_b,
            output_path=SIGNALS_B, hard_stop_cny=47.0,
        )

# ──────────────────────────────────────────────────────────────
# Phase 2: 同步回测重放 + A/B 报告（可多次重跑，零 LLM 开销）
# ──────────────────────────────────────────────────────────────
def phase2_replay_and_report():
    def _run_engine(signals_path, version, start, end):
        strat = SignalReplayStrategy(signals_parquet=signals_path, version=version)
        engine = BacktestEngine(strategy=strat, start=start, end=end)
        return engine.run()

    # In-sample: 2023-2024
    result_a_in = _run_engine(SIGNALS_A, "v1_baseline", IN_SAMPLE_START, IN_SAMPLE_END)
    result_b_in = _run_engine(SIGNALS_B, "v2_esc",      IN_SAMPLE_START, IN_SAMPLE_END)

    # Holdout: 2025
    result_a_ho = _run_engine(SIGNALS_A, "v1_baseline", HOLDOUT_START, HOLDOUT_END)
    result_b_ho = _run_engine(SIGNALS_B, "v2_esc",      HOLDOUT_START, HOLDOUT_END)

    generate_ab_report(
        in_sample={"A": result_a_in, "B": result_b_in},
        holdout={"A": result_a_ho, "B": result_b_ho},
        output="bench/results/ab_esc_vs_baseline.html",
        bootstrap_method="monthly_block",   # 见 §5.8.4
        n_resamples=10000,
    )

# ──────────────────────────────────────────────────────────────
async def main():
    await phase1_precompute()
    phase2_replay_and_report()  # 同步，不用 await

if __name__ == "__main__":
    asyncio.run(main())
```

**预期运行时间**（本地 14 核 / 32 GB）：
- Phase 1 预计算：20 支 × 36 月 × 2 组 = 1440 analyses ÷ 10 并发 ÷ ~1.5 RPS 实际 ≈ **~20 分钟**
- Phase 2 重放回测：现有 sync 引擎每天 ~1ms × 750 交易日 × 4 runs ≈ **~3 秒**
- 报告生成（含 block bootstrap 10000 次重抽样）：**~30 秒**
- **总计：~21 分钟**（+ 网络波动缓冲）

**成本**：Phase 1 总 ¥87-94（Group A ~¥47, Group B ~¥40 因 P0-A 省 20% 输出 token），Phase 2 零成本

**可重跑性**：如果发现回测参数（止损规则、手续费）需要调整，只需重跑 Phase 2（3 秒），**不需要再烧一分钱 LLM 成本**。

**期望结果表**（这张表最终会出现在简历 / 毕设答辩 / paper 的摘要里）：

| 指标 | Group A (baseline) | Group B (ESC) | Δ | 显著性 |
|------|-------------------|--------------|------|--------|
| 年化收益率 | [填] | [填] | [填] pp | [paired t-test p 值] |
| Sharpe | 0.X | 0.X' | +0.X' | p < 0.05 |
| Sortino | 0.Y | 0.Y' | +0.Y' | p < 0.05 |
| Max DD | -XX% | -YY% | +ZZ pp | p < 0.05 |
| 胜率 | 5X% | 6X% | +Y pp | p < 0.01 |
| Profit Factor | 1.X | 1.Y | +0.X | — |
| BUY 后 90 天超额收益 | +X% | +Y% | +Z pp | p < 0.05 |
| 置信度校准斜率 | 0.X 偏离 1 | 0.Y 接近 1 | — | — |
| 辩论触发率 | ~10% | ~15% | +5 pp | — |
| 引文校验通过率 | N/A | ~90% | — | — |

**显著性检验**：对每一对 return 序列做 paired bootstrap（10000 次重采样），给出 p 值和 95% 置信区间。

**人工合理性检查**：
- 随机抽 20 个案例，看 Group B 的 reasoning 是否真的引用了 evidence_citations
- 看 Group B 在三方分裂时是否更倾向于看证据而不是跟随多数
- 看 Group B 的置信度分布是否更"诚实"（不再扎堆 0.7-0.8）

### 5.10 回测模块内存预算

回测只在**本地机器**跑，但依然要控制峰值内存（养成习惯，方便未来规模化）：

| 进程 | 内存预算 | 说明 |
|------|---------|------|
| Python 主进程 | ≤ 300 MB | pandas + numpy + 20 parquet 按需读 |
| 单个 graph 实例（预计算阶段） | ≤ 50 MB | 正常 analyze 占用 |
| Semaphore(10) 并发（仅预计算阶段） | ≤ 500 MB | 10 个 graph 同时跑 |
| LLM 响应缓存（SQLite） | 磁盘 | 不占 RAM |
| Signal parquet（预计算产物） | 磁盘 ~200 KB | 20 × 36 × 2 版本 × 元信息 |
| DataFrame（回测 nav 序列） | ≤ 3 MB | 3 年 × 20 支 × 750 行 ≈ 0.9 MB |
| **预计算阶段峰值** | **≤ 850 MB** | |
| **回测重放阶段峰值** | **≤ 350 MB** | 不跑 LLM 时大幅下降 |
| **合计占本地 32 GB** | **< 3%** | 轻松胜任 |

**严禁**：
- 把 20 支 OHLCV 一次性 load 进 dict 缓存（用 `lru_cache(maxsize=10)` 按需读）
- 在生产服务器上跑任何一行回测代码
- LLM 响应缓存用 dict 而非 sqlitedict

---

## 6. 产品思维：Badcase 闭环 + 数据飞轮 + 灰度 + 校准 + 分群

> 算法优化只是"把系统变好一次"。产品闭环是"让系统持续变好"。两者缺一不可。

### 6.1 Badcase 闭环

#### 6.1.1 收集

**前端**：每个 analyze 结果卡片下加 "🚩 这个分析有问题" 按钮，点击弹出三选一：
- 数据错（显示的价格/财报不对）
- 分析错（推理逻辑有问题）
- 建议不合理（BUY/SELL/HOLD 方向错）

+ 可选自由文本框 + 是否允许加入公开 Badcase 集合勾选框。

**后端**：新端点 `POST /api/v1/badcase`，写 `db.badcases` 表：

```sql
CREATE TABLE badcases (
    id            BIGINT PRIMARY KEY,
    user_id       VARCHAR(64),
    trace_id      VARCHAR(64),        -- 链路追踪 ID，关联原始 analyze 调用
    symbol        VARCHAR(32),
    category      ENUM('data','reasoning','decision','other'),
    user_comment  TEXT,
    agent_output  JSON,               -- 完整的 trade_order + 三份报告
    market_data   JSON,               -- 当时的 market_data snapshot
    llm_version   VARCHAR(32),        -- prompt 版本（P2-D 依赖）
    status        ENUM('new','triaged','resolved','archived') DEFAULT 'new',
    resolution    TEXT,
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    triaged_at    TIMESTAMP NULL,
    triaged_by    VARCHAR(64) NULL,
    INDEX idx_status (status),
    INDEX idx_category (category)
);
```

**内存占用**：表常驻磁盘，不占 RAM。每个 badcase 约 10KB JSON，10000 条才 100 MB，完全可以放 cq-inland MySQL。

#### 6.1.2 分流 & 人工复核

每周五晚上 cron 拉出 `status='new'` 的 badcases，按 category 分流到 triage 队列。每周花 1 小时人工复核 20-30 条，打标签：
- 真 bug → 转 GitHub Issues
- Prompt 缺陷 → 进 prompt 迭代 backlog
- 用户误解 → 更新前端说明文案
- 确实是市场噪音 → 归档

**Golden Badcase 集合**：每周挑 3-5 条"高信息量"的 badcase 进入固定回归集合，后续所有 prompt 改动必须通过这个集合。

#### 6.1.3 闭环接入 P2-D Prompt 版本管理

新版本 prompt 升级前：
1. 在 Golden Badcase 集合上跑一次
2. 确保没有新的回归（原通过的不能挂）
3. 通过后才允许切换版本

这一步让 P0-A（证据化改造）不会在上线后因为某个新 badcase 被回滚——因为它已经在 Golden 集合上验证过。

### 6.2 数据飞轮

#### 6.2.1 原理

用户触发一次 analyze → Agent 出建议（BUY AAPL @ $180, stop 5%, take 15%） → 这次决策落 `db.decisions` 表 → **3 个月后自动计算实际结果**：
- 如果 3 个月内触碰止盈 → +15%（胜）
- 如果 3 个月内触碰止损 → -5%（败）
- 如果都没触碰 → 以 3 个月后的收盘价算收益

**实现**：

```sql
CREATE TABLE decisions (
    id                BIGINT PRIMARY KEY,
    trace_id          VARCHAR(64),
    user_id           VARCHAR(64),
    symbol            VARCHAR(32),
    action            ENUM('BUY','SELL','HOLD'),
    confidence        FLOAT,
    entry_price       FLOAT,
    stop_loss         FLOAT,
    take_profit       FLOAT,
    prompt_version    VARCHAR(32),
    -- 飞轮字段（延迟填充）
    outcome_30d       FLOAT NULL,   -- 30 天后的超额收益
    outcome_60d       FLOAT NULL,
    outcome_90d       FLOAT NULL,
    hit_stop_loss     BOOLEAN NULL,
    hit_take_profit   BOOLEAN NULL,
    evaluated_at      TIMESTAMP NULL,
    created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

**后台任务**：`scripts/evaluate_decisions.py`，每天凌晨跑一次：
1. 查所有 `evaluated_at IS NULL AND created_at < now() - 30 days` 的决策
2. 对每个 symbol 拉 30/60/90 天的价格走势
3. 计算 outcome 字段

**内存占用**：批量处理，每次最多 200 条，完全在 inland 服务器 464 MB 余量内可跑。

#### 6.2.2 反哺

有了 `decisions.outcome_*` 字段后：

**Ⅰ. Prompt 版本的长期胜率对比**（最重要）
```sql
SELECT prompt_version,
       COUNT(*) AS n,
       AVG(outcome_90d) AS avg_excess,
       AVG(CASE WHEN outcome_90d > 0 THEN 1 ELSE 0 END) AS win_rate
FROM decisions
WHERE evaluated_at IS NOT NULL
GROUP BY prompt_version;
```
直接看 **v1_baseline vs v2_esc 的实盘模拟对比**。这是回测之外的**真实用户数据**。

**Ⅱ. 置信度校准（§6.5）**
```sql
SELECT ROUND(confidence * 10) / 10 AS conf_bucket,
       COUNT(*) AS n,
       AVG(CASE WHEN outcome_90d > 0 THEN 1 ELSE 0 END) AS actual_win_rate
FROM decisions
WHERE evaluated_at IS NOT NULL
GROUP BY conf_bucket;
```
画 reliability diagram，看 LLM 的 0.8 置信度是不是真的对应 80% 胜率。

**Ⅲ. 冲突类型的长期效果对比**
```sql
SELECT conflict_score_bucket,
       AVG(outcome_90d) AS avg_excess
FROM decisions
GROUP BY conflict_score_bucket;
```
看"冲突 0.4-0.6 不辩论"和"冲突 0.6-0.8 辩论一次"和"冲突 0.8+ 辩论两次"哪组效果最好，反调阈值。

**Ⅳ. 风控阈值校准**
看 Kelly 公式选的仓位和实际胜率是否匹配。

### 6.3 Champion-Challenger / 灰度发布

#### 6.3.1 Shadow Mode（影子模式）

**背景**：P0-A 证据化改造后，直接切换到 ESC prompt 是有风险的——万一线上效果不如回测那么好。

**方案**：让 v1_baseline（champion）和 v2_esc（challenger）**同时跑**，只把 champion 的结果展示给用户，challenger 结果写日志不展示。

```python
# graph/builder.py 加一个参数
def build_graph_with_shadow(primary_version, shadow_version=None):
    primary = build_graph(version=primary_version)
    shadow = build_graph(version=shadow_version) if shadow_version else None
    return primary, shadow

# api/server.py 的 /api/v1/analyze 处理器
result_primary = await primary.ainvoke(state)
if shadow:
    asyncio.create_task(log_shadow_run(shadow, state))  # 异步不阻塞响应
return result_primary
```

**数据采集**：shadow run 的 trade_order / confidence / evidence_citations 全部落 `db.shadow_runs` 表，3 个月后进入 `decisions` 飞轮计算。

**内存开销**：shadow 是异步任务，并发数严格控制（`Semaphore(1)` 在 cq-hk 上），跑完即释放。峰值内存 ~50 MB，在 200 MB 余量内安全。

**硬约束**：cq-hk 内存紧张，shadow mode 仅在**每次 analyze 随机 10%** 的请求上触发。

#### 6.3.2 Canary 灰度

Shadow 跑满 200 次（约 2 周）后，如果 KPI 通过（`v2_esc` 的 outcome_90d 统计显著优于 `v1_baseline`）：
1. **Canary 10%**：10% 用户走 v2_esc，90% 走 v1_baseline，跑 1 周
2. **Canary 50%**：继续跑 1 周
3. **Canary 100%**：全量

**回滚机制**：任一阶段发现 v2 的 win_rate 比 v1 低 5pp 以上，立即回滚。

**灰度分片**：按 `user_id % 100` 分，保证同一用户始终走同一版本（一致性体验）。

### 6.4 用户分群

**背景**：当前对所有用户都用同一套风控规则和 prompt，但新手和活跃用户的需求不同。

**分群**：

| 分群 | 判定规则 | 差异化配置 |
|------|---------|-----------|
| **新手** (80%) | 试算次数 < 5 或账户注册 < 7 天 | 仓位上限 × 0.7；reasoning 加更多通俗解释 |
| **活跃用户** (15%) | 持仓 ≥ 3 或周度登录 | 标准配置 |
| **有体检记录** (5%) | 最近 30 天做过持仓体检 | 推荐偏向用户已持有的板块风格（避免过度分散） |

**实现**：在 `portfolio_node` 的 prompt 里根据 `user_cohort` 动态调整 `CAMPUS_RULES` 字符串。无需改拓扑。

### 6.5 置信度校准监控

#### 6.5.1 监控

每次 agent 输出决策，记录 `(confidence, 最终是否正确)` 到 `decisions` 表。按周汇总画 reliability diagram：

```
actual_win_rate
    ^
 1.0│              .·
    │           .·
    │        .·
    │     .·    ← 实际曲线
 0.5│  .·
    │.·    ← 理想曲线 y=x
 0.0└────────────────→
    0.0    0.5    1.0   confidence
```

#### 6.5.2 校准干预

如果实际曲线系统性地在 y=x 之上（模型过度悲观）或之下（模型过度乐观）：
- 在 `_apply_confidence_penalty` 里做**事后校准**：`corrected_conf = calibration_fn(raw_conf)`
- 校准函数用 Platt Scaling 或 Isotonic Regression，参数由历史数据拟合
- 每月重新拟合一次

**验证**：新版本发布后监控 reliability diagram 是否更贴近 y=x。

---

## 7. 内存预算与运行时约束

> **所有方案必须通过这一节的预算表**。否则不允许上线。

### 7.1 服务器资源实测

**实测时间**：2026-04-14 20:08

**cq-hk (47.76.197.100)** — 主应用服务器
```
               total        used        free      shared  buff/cache   available
Mem:           882Mi       680Mi        89Mi       2.6Mi       256Mi       201Mi
Swap:          1.0Gi          0B       1.0Gi
CPU: 2 cores
```

- 总内存 **882 MB**
- 已用 **680 MB**
- 可用 **201 MB**
- Swap 1 GB（不可依赖——OOM 时 swap 反而会拖死服务）

**cq-inland (47.108.191.110)** — 数据 relay + Chroma/BM25 + MySQL
```
               total        used        free      shared  buff/cache   available
Mem:           1.6Gi       1.1Gi        89Mi       3.5Mi       539Mi       464Mi
Swap:          1.0Gi          0B       1.0Gi
CPU: 2 cores
```

- 总内存 **1.6 GB**
- 已用 **1.1 GB**
- 可用 **464 MB**

### 7.2 当前进程内存实测

**cq-hk**：
| PID | 进程 | RSS | % MEM |
|-----|------|-----|-------|
| 467305 | uvicorn (api.server:app) | **214 MB** | 23.7% |
| 406195 | systemd-journald | 47 MB | 5.2% |
| 1370 | AliYunDun 云监控 | 40 MB | 4.4% |
| 其他系统 | — | ~100 MB | — |
| **总计** | | **~400 MB** | |

FastAPI 主应用就吃 214 MB，这是 P0-A / P0-C 代码落地后的**固定成本**。

**cq-inland**：
| PID | 进程 | RSS | % MEM |
|-----|------|-----|-------|
| 152030 | uvicorn (inland_relay) | **398 MB** | 24% |
| 27772 | MySQL | 193 MB | 11.7% |
| 36447 | 宝塔面板 | 106 MB | 6.4% |
| 1262 | AliYunDun | 65 MB | 3.9% |
| 其他系统 | — | ~150 MB | — |
| **总计** | | **~910 MB** | |

inland_relay 是大头 **398 MB**（含 Chroma 向量库 + BM25 pickle 索引），这是 P0-C RAG 重构落地后的固定成本。

### 7.3 各优化项的内存增量预算

| 优化项 | 运行位置 | 预估内存增量 | 预算 | 过/不过 |
|--------|---------|------------|------|--------|
| P0-A evidence_citations 字段 | HK | +5 MB（prompt 扩张） | 20 MB | ✅ |
| P0-B 决策聚合重写 | HK | 0 | 0 | ✅ |
| P0-C RAG 共享池 | HK | +10 MB（rag_evidence_pool） | 20 MB | ✅ |
| P0-C RAG 分类查询 | Inland | -20 MB（RAG 调用减少） | — | ✅ |
| P1-A 技术指标补齐 | HK | 0 | 0 | ✅ |
| P1-B 冲突打分 | HK | 0 | 0 | ✅ |
| P1-C 辩论改名 | HK | 0 | 0 | ✅ |
| P1-D Kelly 仓位 | HK | 0 | 0 | ✅ |
| P1-E 撮合真实度 | HK | +5 MB（T+1 持仓记录） | 20 MB | ✅ |
| P2-A `TTLCache(maxsize=1000)` | HK | **+2 MB**（替代无界 dict，实际减） | — | ✅ |
| P2-B 持仓体检基线 | HK | 0 | 0 | ✅ |
| P2-C LLM 响应缓存 | Disk | **0 RAM**（sqlite 磁盘缓存） | — | ✅ |
| P2-D prompts/*.yaml | HK | +2 MB（YAML 热加载） | 10 MB | ✅ |
| §5 回测引擎 | **本地** | 不在服务器跑 | — | ✅ |
| §6.1 Badcase 表 | Inland MySQL 磁盘 | 0 RAM | — | ✅ |
| §6.2 Decisions 飞轮表 | Inland MySQL 磁盘 | 0 RAM | — | ✅ |
| §6.3 Shadow mode (10% sample) | HK | +30 MB（并发异步 task） | 40 MB | ✅ |
| §6.5 Reliability 监控 | HK | +1 MB（内存累计器） | 5 MB | ✅ |

**HK 总增量**：约 **+55 MB**
**Inland 总增量**：约 **-20 MB**（RAG 调用数减半）

**预算结论**：HK 剩余 200 MB → 55 MB 新增 → **剩 145 MB 安全余量** ✅
Inland 剩余 464 MB → 反而节省 → **剩 484 MB 安全余量** ✅

### 7.4 硬红线

1. **HK 总进程内存 ≤ 700 MB**（留 180 MB 给 OS + buff cache）
2. **Inland 总进程内存 ≤ 1.3 GB**（留 300 MB）
3. **Swap 不可作为正常内存使用** —— 一旦开始用 swap 就是告警
4. **回测引擎永远不在生产服务器上跑** —— 零例外
5. **MemorySaver 必须有 TTL + maxsize**：
   ```python
   from langgraph.checkpoint.memory import MemorySaver
   _MEMORY_SAVER_MAX_THREADS = 100  # 原来 200 太多
   _MEMORY_SAVER_TTL_MINUTES = 30    # 新增
   ```
   定时清理任务每 5 分钟删掉超过 30 分钟的 thread。
6. **任何 in-memory dict 缓存必须声明 maxsize**（cachetools）
7. **并行 analyze 必须限流**（目前 uvicorn worker=1，但未来加 worker 前必须配 Semaphore）

### 7.5 监控与告警

- `observability/metrics.py` 骨架已有，加两个指标：
  - `process_rss_mb{server="hk|inland"}` Gauge
  - `cache_size_bytes{name="market_data|llm_response|..."}` Gauge
- 告警：
  - HK RSS > 700 MB → Feishu 通知
  - Inland RSS > 1.3 GB → Feishu 通知
  - Swap 使用 > 0 → 立即通知

### 7.6 扩容路径（仅做决策参考）

- **短期（1 个月）**：不扩。按本文方案推进。
- **中期（3 个月）**：如果用户量涨到 200+ DAU，HK 升级到 **2 GB**（阿里云 ECS 约 ¥35/月增量），解决 uvicorn 并发问题。
- **长期（6 个月）**：回测服务单独一台 **4 GB / 8 GB 按需实例**，跑完就释放，月均 ≤ ¥20。
- **不考虑**：Redis 集群、K8s、分布式向量库——这些是 UPGRADE_PLAN.md 的事，本方案不涉及。

---

## 8. 算法层与 EMNLP 论文方法对照速查表

| 论文概念 | 论文结论 | 当前系统状态 | 本文档优化项 |
|----------|---------|-------------|-------------|
| policyPrivate | 不共享，基线 | ✅ 分析师并行阶段天然 private | — |
| policyHypothesis（answer+conf） | 最差，最高锚定 | ❌ portfolio/debate 正是这样消费 | **P0-A** |
| policyRationale（+reasoning） | 居中 | ❌ 当前的 reasoning[:200] 属这类 | **P0-A** |
| policyEvidence（raw text） | 最好，+10-16pp EM | ❌ 没有 evidence_citations 字段 | **P0-A** |
| ESC（summary + cited quote） | 接近 full evidence，成本 1/5 | ❌ 无 | **P0-A** |
| 验证机制（verifiability） | 核心机制：独立审核 | ❌ 无独立审核步骤 | **P0-A Step 5** |
| Round-transition decomposition | C→W / W→C 归因 | ❌ 无度量 | §5.8 决策质量指标 |
| 3-agent / 2-round 协议 | 论文协议 | ✅ 天然对应（3 分析师 + portfolio + debate） | — |
| 跨 model 稳健性检验 | E>H 在 4/4 模型家族保持 | ❌ 无 | §5.9 A/B 多次运行 |
| 人工标注校验 | κ=0.93 高可靠 | ❌ 无 | §6.1 Golden Badcase |

---

## 9. 实施路线图

| Phase | 内容 | 预估工作量 | 收益 | 服务器 |
|-------|------|----------|------|--------|
| **Phase 0** (本周) | §7 内存监控：加 `process_rss_mb` 指标 + Feishu 告警 | 0.5 天 | 底座，后续所有改动都依赖 | HK + Inland |
| **Phase 1** (本周) | P0-A Step 1-5：证据化改造（字段 + 3 分析师 prompt + portfolio/debate user_prompt + 子串校验） | 1-2 天 | 决策质量 & 可审计性 | HK |
| **Phase 2** (本周) | P0-B：重写 `_compute_weighted_score`，补 `bench/scoring_sanity.py` | 0.5 天 | 消除多头偏见，修复置信度耦合 | HK |
| **Phase 3** (下周) | P0-C：RAG 共享池重构，删 `rag_node` | 2 天 | RAG 调用 -50%，延迟 -30% | HK + Inland |
| **Phase 4** (下周) | P1-A + P1-B + P1-C：技术指标补齐 + 冲突打分 + 辩论改名 | 1 天 | 信号质量提升 | HK |
| **Phase 5** (第 3 周) | §5.3 20 支 universe.yaml + `scripts/download_universe_history.py`（2023-2025 三年 OHLCV） | 0.5 天 | 回测底座，7 分钟跑完下载 | 本地 |
| **Phase 5.5** (第 3 周) | `observability/llm_tracker.py` 改造：(a) 订正 `_COST_TABLE` 为 Qwen3.5-Plus ≤128K 档真实单价 ¥0.0008/¥0.0048；(b) 新增 `CostTracker(run_id)` 类；(c) `_invoke_structured_with_fallback` 末尾接入 tracker.record() | 0.5 天 | 没油表不许起飞；按实验隔离防污染 | 本地 |
| **Phase 6a** (第 3 周) | §5.4.2 `bench/precompute_signals.py` 异步预计算脚本 | 0.5 天 | A/B 两组 signals_*.parquet 产物 | 本地 |
| **Phase 6b** (第 3 周) | §5.4.3 `bench/backtest/signal_replay_strategy.py` 同步重放（**零改动 `backtest/engine.py`**） | 0.5 天 | 与现有 sync 引擎完美桥接 | 本地 |
| **Phase 7** (第 4 周) | **§5.9 A/B Phase 1 预计算**（20 支 × 3 年 × 2 组 × 月度 = ¥94，约 20 分钟） —— 核心故事线烧钱时刻 | 0.5 天运行 + 1 天分析 | 出**量化证据**，整份方案的销售点 | 本地 |
| **Phase 7.5** (第 4 周) | §5.9 Phase 2 同步重放（in-sample + holdout 各 A/B）+ §5.8.4 月度 block bootstrap + LOMO | 0.5 天 | 显著性检验 | 本地 |
| **Phase 8** (第 4 周) | §5.9 报告生成 `bench/results/ab_esc_vs_baseline.html`（含 holdout 并列 + 方向一致性 + reliability diagram） | 1 天 | 可视化输出 | 本地 |
| **Phase 9** (第 5 周) | P1-E 撮合真实度（T+1 / 涨跌停 / async 化） + ATR 动态止损（P1-D 的一半） | 1 天 | 演练真实度提升 | HK |
| **Phase 10** (第 5 周) | P2-A 缓存升级 + P2-C LLM 响应缓存（sqlite） | 1 天 | 成本与性能 | HK |
| **Phase 11** (第 6 周) | P2-D Prompt YAML 外化 + §6.3 shadow mode 骨架 | 2 天 | 灰度发布能力 | HK |
| **Phase 12** (第 6 周) | §6.1 Badcase DB schema + 前端按钮 + §6.2 decisions 飞轮表 | 2 天 | 产品闭环启动 | HK + Inland |
| **Phase 13** (第 7-10 周) | P2-B 持仓体检锚点 + §6.4 用户分群 + **P1-D Kelly 校准版**（基于 decisions 表 90d outcome 数据，按 confidence 分桶算真实胜率后再接入 Kelly，避免未校准的 raw confidence 放大仓位风险） | 2-3 天（需等飞轮积累数据） | 数据飞轮驱动的风控闭环 | HK |
| **Phase 14** (持续) | Badcase 每周复核 + Reliability diagram 每周生成 | 每周 2 小时 | 持续进化 | — |

**总预算**：
- 人日：**约 15-20 人日**（7 周开发 + 持续运维；Phase 13 Kelly 校准版需等飞轮数据，不计入初期）
- LLM 调用（一次完整 A/B）：**≤ ¥100**（方案 A：20 支 × 3 年 × 月度 × 双组 ≈ ¥94，代码生成引文后 ~¥87）
- 服务器成本：**0**（不扩容，回测本地跑）
- 内存增量：HK +55 MB / Inland -20 MB / 本地回测峰值 ~850 MB（Phase 1）或 ~350 MB（Phase 2）

**最关键的里程碑**：Phase 7 的 A/B 回测报告——整份方案的**故事线终点**。这个报告出来前，所有前面的改动都只是"感觉有用"；出来后，所有改动都有"数字证明"。

---

## 10. 成功指标（Definition of Done）

### 10.1 算法层

| 项 | 可量化指标 |
|----|----------|
| **P0-A** | 引文子串校验通过率 ≥ 85%；分裂场景一致性人工评分 ≥ 4/5 |
| **P0-B** | `scoring_sanity.py` 20 组测试 100% 通过；历史 100 次分析中 BUY:SELL 比从 ~3:1 降至 ~1.5:1 |
| **P0-C** | 平均每次 `/api/v1/analyze` RAG 调用数从 4 降到 ≤ 2；P50 延迟 -20% |
| **P1-A** | `BOLL_pct_B` 非 None 率 100%；`tech_signal` 细分为 5 档 |
| **P1-B** | `conflict_score` 线性化，辩论触发率从 ~10% 调整到 ~15-20% |
| **P1-C** | `devils_advocate_node` 重命名，confidence 变动 ≤ 0.1 |
| **P1-D** | Kelly 仓位公式接入，日志可追溯 |
| **P1-E** | A 股 T+1 / 涨跌停生效；async 下单不阻塞事件循环 |
| **P2-A** | cache hit rate ≥ 60%；`TTLCache` 容量不超 1000 |
| **P2-B** | `baseline_score` 与 `health_score` 差值 ≤ 15 分 |
| **P2-C** | 同 symbol 5 分钟内重复分析 LLM token 节省 ≥ 50% |
| **P2-D** | Prompt 热重载可用；版本号写入响应 metadata |

### 10.2 回测 & 故事线（最关键）

| 项 | 指标 |
|----|------|
| **股票池** | 20 支（A10 + HK5 + US5），2023-01 → 2025-12，parquet 存储 ≤ 2 MB |
| **频率** | 月度观察日（每月首个交易日），全量 20 支，不采样 |
| **模型** | Qwen3.5-Plus（与生产一致） |
| **单位成本** | ¥0.065 / analyze（≤128K 档位真实单价，v2.2 订正） |
| **时间分层** | In-sample 2023-01 → 2024-12（24 月）+ Holdout 2025-01 → 2025-12（12 月，锁死） |
| **成本** | A + B 两组总成本 ~¥94（代码生成引文后 ~¥87），硬停 ¥95 |
| **执行架构** | 两阶段：Phase 1 异步预计算 signals parquet → Phase 2 同步 SignalReplayStrategy 喂给现有 BacktestEngine（零引擎改动） |
| **Baseline 对照** | B0-B3 四组 + A/B 两组 agent，共 6 组跑完 |
| **显著性方法** | 月度 block bootstrap（10000 次重抽样）+ Leave-One-Market-Out 稳健性检查 |
| **A/B 判定** | **不报 p-value**（样本非独立），改报"point estimate + 95% CI"；Group B 需要在至少 3 个关键指标上 CI 不跨零，且 holdout 方向一致 |
| **EMNLP 故事** | 可复述一句话：**"20 支股票 × 3 年月度回测，in-sample + 2025 holdout 双验证下，Group B 的 Sharpe / 胜率 / BUY-90d 超额收益的 95% CI 全部不跨零，方向与 in-sample 一致"** |
| **报告产出** | `bench/results/ab_esc_vs_baseline.html` 包含 in-sample/holdout 并列表 + 收益曲线 + block bootstrap CI 条 + reliability diagram + LOMO 切片 + 成本明细 |
| **运行时间** | Phase 1 预计算 ~20 分钟 + Phase 2 重放 ~3 秒 + 报告 ~30 秒 = **~21 分钟** |
| **可重跑性** | Phase 2 零 LLM 成本，调回测参数可无限次重跑 |

### 10.3 产品闭环

| 项 | 指标 |
|----|------|
| **Badcase** | 前端按钮上线；每周复核 ≥ 20 条；Golden 集合 ≥ 30 条 |
| **数据飞轮** | `decisions` 表每日增量；`evaluate_decisions.py` 稳定运行；每月出一次 prompt version 胜率对比 |
| **Shadow Mode** | 10% 采样率；2 周跑满 200 条 shadow run；可对比两版本的 outcome_90d |
| **灰度发布** | Canary 10% → 50% → 100% 机制可用；回滚脚本就绪 |
| **用户分群** | 新手/活跃/体检三档，prompt 差异化生效 |
| **置信度校准** | 每周生成 reliability diagram；偏离 y=x 的斜率 ≤ 0.15 |

### 10.4 内存约束

| 项 | 指标 |
|----|------|
| **HK RSS** | 持续 ≤ 700 MB（25% 安全余量） |
| **Inland RSS** | 持续 ≤ 1.3 GB |
| **Swap 使用** | 恒为 0 |
| **`_CACHE` 大小** | ≤ 2 MB（`cachetools.TTLCache(maxsize=1000)`） |
| **`MemorySaver` 大小** | ≤ 100 threads，每个 thread 30 分钟 TTL |

---

## 11. 不做什么（Out of Scope）

- **不接入任何真实交易所 API**（硬规则，永远不变）
- **不改拓扑**（P0-C 删 `rag_node` 是减法，不是重新设计）
- **不换 LLM 主模型**（DashScope/Qwen 不变，算法优化与模型选择正交）
- **不做分布式缓存**（Redis 等）——内存吃不下，也没必要
- **不做 agent 训练 / fine-tune**（本项目是 prompt engineering 项目）
- **不在生产服务器上跑回测**（内存硬约束）
- **不扩容服务器**（短期内用内存预算硬撑）
- **不做高频交易 / 日内策略**（Agent 决策天然是周度，高频无意义）

---

## 12. 参考文献

1. 《What Should LLM Agents Share? Auditable Content Supports Belief Revision in Controlled Multi-Agent Deliberation》(Anonymous, EMNLP 2025 under review)
   — 本文档 **P0-A + §5 A/B 故事线** 的直接理论依据。路径：`D:/000research/emnlp/paper/main.tex`
2. `UPGRADE_PLAN.md` — 平台工程 8 周路线图（2026-04-10）
3. `AUDIT_REPORT.md` — 产品交付审计报告（2026-04-02）
4. `CLAUDE.md` — 项目约束与硬规则
5. Kelly, J. L. (1956). *A New Interpretation of Information Rate.* — P1-D 仓位公式
6. Platt, J. (1999). *Probabilistic Outputs for Support Vector Machines...* — §6.5 置信度校准方法
7. Harris, T. (1998). *The Winner's Curse: Paradoxes and Anomalies of Economic Life.* — §5.7 baseline random signal 的灵感来源

---

## 13. 变更记录

| 版本 | 日期 | 作者 | 变更 |
|------|------|------|------|
| v1.0 | 2026-04-14 | Feng Yuqiao | 首版，12 个优化项，覆盖 Agent 通信、决策聚合、RAG、技术指标、风控、撮合、缓存 |
| v2.0 | 2026-04-14 | Feng Yuqiao | 大幅扩展：新增 §5 回测重构（80 支 × 7 年 × walk-forward × A/B）、§6 产品闭环（Badcase + 飞轮 + 灰度 + 分群 + 校准）、§7 内存预算（基于实测 882 MB / 1.6 GB），整体围绕 EMNLP 论文 A/B 故事线重组路线图 |
| v2.1 | 2026-04-14 | Feng Yuqiao | §5 回测规模收敛：3 年（非 7 年）+ 30 支（非 80 支）+ 月度频率（非双周/周频）+ Qwen-Plus 生产一致，成本从 ~¥2000 压到 ~¥86，单窗口运行（不做 walk-forward），回测位置改本地（32 GB / 14 核），新增 §5.5 成本硬停机制 ¥95，Phase 5.5 新增 `llm_tracker` token 计数 |
| v2.2 | 2026-04-14 | Feng Yuqiao | 吸收外部审阅 + 真实定价：(1) 定价订正 Qwen3.5-Plus ≤128K 档位 ¥0.8/M in + ¥4.8/M out，单次 analyze ¥0.065；(2) 股票池 30→20（金山办公→中信证券 600030）；(3) 2025 holdout + block bootstrap 替代 p<0.05；(4) Signal 预计算 + SignalReplayStrategy 桥接同步引擎；(5) CostTracker(run_id) 按实验隔离；(6) P0-A 结构化引文代码生成，LLM 只做新闻/RAG 抽取；(7) Kelly 推迟至 Phase 13。预算从 ¥86 调整为 ¥94（20×36×2×¥0.065） |
