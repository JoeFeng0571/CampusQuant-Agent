# INTERVIEW_GUIDE.md — CampusQuant 高阶 AI PM 通用面试手册

> 适用场景：AI Product Manager / LLM 应用方向 / 大模型 Agent 相关岗位面试
> 本手册所有技术细节均来自真实代码（graph/nodes.py、eval_pipeline.py 等），数字与代码一一对应。

---

## 一、项目核心叙事

### 30 秒版本

CampusQuant 是面向在校大学生的 AI 量化分析平台。核心矛盾是：大模型输出天然具有概率性不确定性，但金融建议对用户的实际影响是零容忍的。我的解决方案是在 LangGraph 多智能体框架上，叠加一套代码层硬风控，把 LLM 的不确定性转化为仓位约束——置信度越低，建议仓位越小，而不是任由 LLM 输出随意影响用户决策。

### 2 分钟版本

项目背景：大学生有投资意愿但缺乏分析能力，市面工具信息密度过高，直接入市风险极大。我做了 200+ 份问卷和 15 场深度访谈，确定了三个核心痛点：看不懂股票、没有实战机会、缺乏风控意识。产品定义为"AI 研报 + 模拟交易 + 财商教育"三位一体。

技术架构核心是 9 节点 LangGraph DAG：4 路并行分析师（基本面/技术/舆情/RAG）→ 基金经理综合决策 → 辩论消解冲突 → 四重硬风控 → 模拟交易指令。每个分析节点有独立的域感知 RAG 查询，最终风控是代码层截断，不依赖 Prompt。

最有价值的设计：发现系统存在"系统性 HOLD 偏差"问题——因为所有 LLM 输出的置信度普遍偏低，导致大量正确信号被错误过滤。我分析出三层根因，设计了置信度惩罚函数（`_apply_confidence_penalty`），将 LLM 的置信度映射为仓位百分比，而非二值化 HOLD/执行。综合准确率从约 65% 提升至约 90%（D1-D4 四维评测）。

---

## 二、4 个 STAR 技术案例

---

### Case A：AI 置信度惩罚体系设计（解决系统性 HOLD 偏差）

**Situation**：
CampusQuant 早期版本设置了置信度阈值：综合置信度 < 0.60 时强制输出 HOLD。上线后发现系统 HOLD 率异常高（约 70% 的分析请求返回 HOLD），用户体验极差，但又不能简单降低阈值——阈值过低则失去风控价值。

**Task**：
设计一种机制，在不损害风控底线的前提下，减少"有信号但被过滤"的假阴性，同时保留"无信号时强制等待"的保护。

**Action**：
深挖问题发现三层根因：
1. LLM 在训练上倾向于给出保守的中等置信度（0.50-0.65），即使信号明确也如此
2. 单一阈值（0.60）在阈值处产生"悬崖效应"：0.59 和 0.61 的行为完全不同
3. 置信度 0.45 和置信度 0.30 被同等对待，信息被浪费

设计了三阶段线性惩罚函数，代码实现在 `graph/nodes.py`：

```python
_CONF_FLOOR     = 0.40   # 低于此值：模型完全无把握，任何仓位都是噪声
_CONF_THRESHOLD = 0.55   # 低于此值：进入惩罚带，线性缩仓

def _apply_confidence_penalty(action, confidence, base_pct):
    if confidence < _CONF_FLOOR:
        return "HOLD", 0.0, f"置信度{confidence:.2f}<0.40，强制HOLD"

    if confidence < _CONF_THRESHOLD:
        scale = (confidence - _CONF_FLOOR) / (_CONF_THRESHOLD - _CONF_FLOOR)
        penalized_pct = round(base_pct * scale, 2)
        return action, penalized_pct, f"置信度惩罚: {base_pct}×{scale:.3f}={penalized_pct:.2f}%"

    return action, base_pct, None
```

调用位置：`trade_executor` 在生成 LLM 调用之前执行，覆盖 LLM 的仓位建议。

**Result**：
- 系统 HOLD 率从约 70% 降至约 35%（置信度惩罚带代替了二值化硬 HOLD）
- D3+D4 综合通过率提升约 18 个百分点
- 关键设计决策：0.40 是"LLM 自己认为有 60% 概率分析有误"的语义边界，0.55 是"基本有依据但不充分"的门槛，两值之间的线性区间消除了悬崖效应

**追问 1：为什么是 0.40 和 0.55，不是 0.35 和 0.60？**
> 0.40 和 0.55 是通过对不同阈值下系统 HOLD 率与人工标注正确率的交叉分析确定的，不是严格统计意义上的最优解。这两个值更重要的是它们的**语义边界**：0.40 对应"三路分析师平均信号强度达到基准（0.50）的 80%"，0.55 对应"超过基准 10%"。可以坦诚这是经验值，后续可以用更大测试集做阈值优化。

**追问 2：如果 LLM 输出的置信度本身就不可靠，惩罚机制有意义吗？**
> 这是一个深刻问题。LLM 的置信度是"校准后的相对量"而非"绝对概率"——单个样本不可靠，但在大量样本上，高置信度建议的正确率统计上显著高于低置信度建议。置信度惩罚的作用不是依赖单次置信度的精确度，而是在群体层面系统性地"为模糊信号减少曝光"。这与广告 CTR 预估的应用逻辑完全一致：单次预测未必准，但群体上 pCTR 高的广告确实有更高点击率。

**追问 3：如果用户明确要求高仓位怎么办？**
> 风控是代码层截断，不是 Prompt 建议，所以无论 LLM 输出什么都会被覆盖。TradeOrder.simulated 永远为 True，仓位上限代码强制执行，这是架构层面的物理隔断，不存在"用户要求绕过"的路径。

---

### Case B：混合 RAG + RRF 检索精度优化

**Situation**：
早期 RAG 使用纯 BM25 关键词检索，对"美联储降息"和"联储宽松"之类的同义表达无法关联，对中英文混用的金融查询（如"NVDA AI算力"）精度差。Recall@5 约 64%。

**Task**：
在不引入昂贵闭源向量服务的前提下，将 Recall@5 提升到 85% 以上。

**Action**：
设计了三路信息融合架构（代码在 `tools/knowledge_base.py`）：

1. **BM25 关键词检索**：精准词匹配，优势在股票代码、机构名称、财务指标名
2. **Chroma 语义向量检索**：DashScope text-embedding-v3 / OpenAI text-embedding-3-small，优势在同义词、语义模糊匹配
3. **DuckDuckGo 实时联网**：补充时效性盲区（突发新闻、当季财报）

三路融合使用 RRF（Reciprocal Rank Fusion）算法：
```
score(rank) = 1 / (rank + 60)
融合得分 = Σ score(rank_i)  for each retriever
```

**Double-hit 效应**（关键优化点）：某个文档同时被 BM25 和 Chroma 检出时，融合得分约为单路的 2 倍，自然排到最前。这意味着"既精准又语义相关"的文档会被优先返回。

动静分离架构：离线端 `python scripts/build_kb.py` 一次性构建 Chroma + BM25.pkl，在线端 < 2s 加载（无 Embedding API 调用），不影响请求延迟。

**Result**：
- Recall@5 从约 64% 提升至约 88%（+24pp）
- 主要来源：BM25 负责股票代码精准匹配，Chroma 负责同义词覆盖，两路 double-hit 使高质量文档优先级显著上升
- 可接受的 trade-off：检索延迟从约 50ms 增加至约 200ms（三路并行检索），context window 占用增加但通过 `max_length` 参数受控

**追问 1：Recall@5 = 88% 怎么量化测试的？**
> 构建了 25 个标注查询对，每个 query 人工标注 5 个相关文档（gold set）。测试时用混合检索返回 Top-5 文档，计算与 gold set 的交集比例。25 个查询的平均 Recall@5 = 88%。这是小样本内测值，存在标注偏差。面试中可坦诚这一点，并说明扩大测试集的方向。

**追问 2：Chroma 和 FAISS 怎么选的？**
> FAISS 是内存型，不支持持久化，每次重启需重建索引（约 2-5 分钟）；Chroma 支持 SQLite 持久化，在线端 < 500ms 打开文件句柄。对于学生项目，启动速度比极致查询性能更重要，所以选 Chroma。

**追问 3：动静分离的设计意图是什么？**
> 把计算密集型操作（PDF 解析 + Embedding 调用）移到离线阶段一次性完成，在线端只做磁盘读取，避免每次服务启动都调用 Embedding API（成本+延迟）。这是数据密集型应用的经典分层设计。

---

### Case C：域感知 RAG 路由架构设计（Per-Node Specialized Retrieval）

**Situation**：
早期架构中，4 个分析节点共享同一个全局 RAG 查询。问题：基本面分析师需要的是财务报表、机构评级类深度内容；舆情分析师需要的是最新政策、突发新闻；技术分析师需要资金面数据。一个通用 query 无法同时满足三种信息需求，导致每个节点的 RAG 上下文信号噪音大。

**Task**：
在不修改 LangGraph State Schema 的前提下（避免破坏性改动），为每个分析节点设计独立的检索逻辑。

**Action**：
在每个节点函数内部，在调用 LLM 之前，先独立执行一次域专属的 `search_knowledge_base.invoke()`，结果注入该节点的 `user_prompt`，不写入全局 State。

实现细节（以 fundamental_node 为例，`graph/nodes.py` 第 637-647 行）：
```python
# 【Per-Node RAG】基本面专项检索
fund_rag_context = ""
try:
    fund_rag_context = search_knowledge_base.invoke({
        "query":       f"{symbol} 财务报表 基本面 盈利 机构评级",
        "market_type": market_type,
        "max_length":  1200,
    })
except Exception as _re:
    logger.warning(f"[fundamental_node] 专项RAG检索失败（降级为空）: {_re}")
```

四个节点的域差异化设计：

| 节点 | 专项 Query | max_length | 信息域定位 |
|------|-----------|-----------|----------|
| fundamental | `{symbol} 财务报表 基本面 盈利 机构评级` | 1200 | 深度财务分析 |
| technical | `{symbol} 近期资金面 行业技术利好利空` | 1000 | 技术面信号 |
| sentiment | `{symbol} 最新宏观政策 行业动态 突发新闻` | 1000 | 时效性舆情 |
| debate | `{symbol} 行业核心风险点 前景 护城河` | 1200 | 辩论裁决依据 |

**Result**：
- 非破坏性改造：不修改 TradingGraphState，不引入新字段，向后兼容
- 各节点 RAG 上下文与其分析域精准对齐，减少噪音注入
- 每个 RAG 调用有独立的 try/except 降级，节点不因 RAG 失败而崩溃

**追问 1：为什么不把 4 个 query 全部并发执行，统一放在 rag_node 里？**
> 两个原因：1）各节点的 query 包含该节点才能确定的上下文（如 technical 的 tech_signal），无法在 rag_node 执行时提前知道；2）per-node RAG 的结果只有该节点需要，集中在 rag_node 会浪费状态存储空间并增加 portfolio_node 的上下文长度。

**追问 2：max_length 不同的设计逻辑？**
> fundamental 和 debate 的分析深度更高，需要更多上下文（1200 字符）；technical 和 sentiment 主要提取关键信号，信息密度低，1000 字符足够。max_length 过大会撑大 LLM prompt，增加 token 成本和响应延迟。

---

### Case D：代理环境下数据获取崩溃修复

**Situation**：
项目在开发环境使用 TUN 模式 VPN，akshare 对东方财富、新浪财经的 HTTP 直连请求被 VPN 截断，导致 `RemoteDisconnected` / `RemoteProtocolError` 错误率约 40%，data_node 频繁失败，整个分析流程无法走完。

**Task**：
在不关闭 VPN 的前提下，保证数据获取的稳定性，不影响开发效率。

**Action**：
分三层修复（代码在 `api/server.py` 和 `graph/nodes.py`）：

**Layer 1：NO_PROXY 精准绕过**（`api/server.py` 第 66-80 行）
```python
_no_proxy_extra = (
    "dashscope.aliyuncs.com,aliyuncs.com,"
    "eastmoney.com,push2.eastmoney.com,"
    "hq.sinajs.cn,sinajs.cn,sina.com.cn"
)
os.environ["NO_PROXY"] = _no_proxy_extra  # 指定国内金融域名直连
```

**Layer 2：LLM 域名白名单**（`graph/nodes.py` `_build_llm` 函数）
```python
_dashscope_no_proxy = "dashscope.aliyuncs.com,aliyuncs.com"
os.environ["NO_PROXY"] = _cur_no_proxy + "," + _dashscope_no_proxy
```

**Layer 3：data_fetch_failed 早退机制**
data_node 失败时设置 `data_fetch_failed=True`，4 个并行节点检测到后立即返回 HOLD 降级报告，不调用 LLM，避免在错误数据上浪费推理资源。

**Result**：
- 本地开发环境错误率从约 40% 降至 < 2%
- 增加了 data_fetch_failed 早退机制，使系统在数据层失败时能快速失败而非无限等待
- 经验迁移：代理环境是国内开发 AI 应用的常见隐性问题，NO_PROXY 精准配置比关闭代理更实用

**追问 1：为什么不用重试（retry）而是 NO_PROXY？**
> 重试只治表不治本——如果每次都被 VPN 截断，重试只会多次失败并增加延迟。NO_PROXY 让国内数据源直连，从根本上消除了截断原因。重试是在 NO_PROXY 之上的兜底。

**追问 2：data_fetch_failed 早退设计的价值？**
> 在不改变 DAG 拓扑结构的前提下，实现了"数据层错误时短路全流程"。每个并行节点的早退只需一个 if 判断，比在 builder.py 里修改条件边更简单，且保持了状态 schema 的向后兼容。

---

## 三、量化指标防追问底层依据

### 3.1 置信度三阶段计算链路

**完整链路（三阶段）**：

**阶段 1：三路分析师各自输出置信度**
- `fundamental_node` → `AnalystReport.confidence`（如 0.78）
- `technical_node` → `AnalystReport.confidence`（如 0.82）
- `sentiment_node` → `AnalystReport.confidence`（如 0.65）

**阶段 2：`_compute_weighted_score` 加权合并**（`graph/nodes.py` portfolio_node）
```python
# A股权重：基本面 35% + 技术面 40% + 舆情 25%
f_score = _REC_SCORE[f_rec] * f_conf  # BUY=1.0, HOLD=0.5, SELL=0.0
t_score = _REC_SCORE[t_rec] * t_conf
s_score = _REC_SCORE[s_rec] * s_conf

weighted_score = 0.35*f_score + 0.40*t_score + 0.25*s_score
avg_confidence = 0.35*f_conf  + 0.40*t_conf  + 0.25*s_conf
```

**数字示例（A股三路均 BUY）**：

| 分析师 | 建议 | 置信度 | 权重 | 信号贡献 |
|--------|------|--------|------|---------|
| 基本面 | BUY  | 0.78 | 0.35 | 1.0×0.78×0.35 = 0.273 |
| 技术面 | BUY  | 0.82 | 0.40 | 1.0×0.82×0.40 = 0.328 |
| 舆情   | BUY  | 0.65 | 0.25 | 1.0×0.65×0.25 = 0.163 |
| **合计** | — | — | — | weighted_score = **0.764** → BUY |

avg_confidence = 0.78×0.35 + 0.82×0.40 + 0.65×0.25 = **0.763**

**阶段 3：`_apply_confidence_penalty` 映射为仓位约束**（`graph/nodes.py` trade_executor）

```
avg_confidence = 0.763 → 阶段3检查：0.763 >= 0.55 → 正常执行，仓位不惩罚
```

若 avg_confidence = 0.47：`scale = (0.47-0.40)/(0.55-0.40) = 0.467` → `base_pct × 0.467`

### 3.2 综合准确率 90% 的来源

**公式**（`eval_pipeline.py` 第 480-484 行）：
```python
acc = (0.20 * d1_rate + 0.30 * d2_rate + 0.30 * d3_rate + 0.20 * d4_rate)
```

**各维度内测数字**：
- D1（市场分类）≈ 100%：三级正则+字典+新浪API，50只测试集格式明确
- D2（数据获取）≈ 100%：双路并发+日线降级，保证有数据返回
- D3（研报完整性）≈ 83%：少量因 LLM 超时或字段不规范未通过
- D4（风控合规）≈ 83%：少量因 LLM 输出量纲错误（代码修正后提升）

**代入公式**：`0.20×1.0 + 0.30×1.0 + 0.30×0.83 + 0.20×0.83 = 0.20 + 0.30 + 0.249 + 0.166 = 0.915 ≈ 90%`

**诚实说明**：50 只测试集是已知局限，样本量较小。这是内测值，不是严格统计意义上的 benchmark。测试集设计覆盖 A股（20只，含大盘蓝筹/中小盘/ETF）+ 港股（15只）+ 美股（15只），覆盖三市场但分布不均衡。

### 3.3 Recall@5 = 88% 的来源

**测试方法**：
1. 构建 25 个标注查询对（每个 query + 5 个人工标注相关文档 = gold set）
2. 运行混合检索（BM25 + Chroma + RRF），取 Top-5
3. `Recall@5 = |Top-5 ∩ gold_set| / |gold_set|` 对 25 个 query 取平均

**RRF double-hit 示例**：query = "NVDA AI芯片出货量"
- BM25 结果中含"NVDA"段落 rank=1 → `score = 1/61 ≈ 0.0164`
- Chroma 结果中含"英伟达算力"段落（语义相近）rank=1 → `score = 1/61 ≈ 0.0164`
- 若含"NVDA"的段落同时在两路中出现（double-hit）：`融合得分 ≈ 0.032`，大幅领先其他文档

纯 BM25 Recall@5 ≈ 64%，加入 Chroma 后 ≈ 80%，加入 DuckDuckGo 后 ≈ 88%（时效性查询提升显著）。

### 3.4 50 只股票测试集的设计逻辑

测试集设计原则：**覆盖边界条件而非代表性抽样**

```
A股（20只）：
  - 沪深300权重股（工行/茅台/宁德）：主流代码格式
  - 科创板（688XXX）：特殊代码格式
  - 深交所创业板（300XXX）：不同交易所
  - 宽基ETF（510300/159915）：非个股场景

港股（15只）：
  - 腾讯/阿里/美团：南向资金主力标的
  - 国企H股（0939.HK）：A+H溢价场景

美股（15只）：
  - AAPL/NVDA/MSFT：大市值科技
  - 中概股（BABA/JD）：中美双重监管场景
```

**设计意图**：D1 市场分类的最大挑战是边界情况（科创板 688XXX 容易被误判为港股 6XXXXX），这 50 只股票刻意涵盖这类边界。

---

## 四、跨域启发——从 CampusQuant 到商业安全审核

| CampusQuant 机制 | 对应的广告/内容安全机制 | 核心相通原理 |
|-----------------|----------------------|------------|
| `_apply_confidence_penalty`：置信度低 → 仓位小 | 审核置信度低 → 进人工复审队列，不直接放量 | 不确定性映射为处理强度，而非二值决策 |
| 四重硬风控（ATR阻断/仓位截断/亏损反算/置信度惩罚） | 多级审核规则（关键词黑名单→模型分类→人工审核） | 多层防御，每层有独立触发条件，不依赖单一检测 |
| `TradeOrder.simulated = True` 架构级硬隔断 | 广告平台禁止某类广告主的账户级封禁 | 在架构层划红线，而非依赖运行时判断 |
| debate_node 多空辩论消解分歧 | 内容审核中的多模型投票（ensemble 决策） | 分歧信号触发更严格的二次审核 |
| domain-aware RAG（每个节点专项检索） | 多模态审核：图片检测/文字检测/账号信誉各自独立检索上下文 | 不同信息域需要不同的知识库和查询策略 |
| D1-D4 四维评测流水线（持续量化）| 审核系统的误拦率/漏拦率 A/B 测试 | 将"好的审核"量化，支持持续迭代 |
| data_fetch_failed 快速失败早退 | 基础特征缺失时拒绝处理，返回人工审核 | 数据质量不满足时宁可降级，不用低质量输入做决策 |
| MAX_TOOL_CALLS Anti-Loop 防死循环 | 审核流程中的最大重试次数限制 | 防止异常状态导致无限循环消耗资源 |
| LLM 不确定性 → 置信度惩罚 vs 直接使用 | pCTR 预估不确定性 → explore/exploit 策略 | 用不确定性指导"多保守还是多激进"，而非忽视 |
| MemorySaver 会话持久化 | 用户行为序列上下文（Session 级审核） | 单次请求之外的历史上下文增强判断 |

---

## 五、大模型 Agent 高频问题答题模板

**Q1：Agent 和普通 API 调用的区别是什么？**

> 普通 API 调用是单次：输入 → 黑箱 → 输出，没有状态，没有迭代。Agent 的核心特征是**状态 + 工具 + 循环**：LLM 可以根据中间结果决定下一步调用什么工具，形成自主的目标导向行为链。CampusQuant 里，risk_node 的 REJECTED 状态会让 portfolio_node 重新评估方案，这是普通 API 无法做到的自主迭代。从产品角度，Agent 的价值在于把"需要人类介入决策的中间步骤"自动化，代价是结果的不确定性和延迟可控性下降。

**Q2：如何保证可靠性——不信任 LLM 输出？**

> 分三层：1）**输出格式层**：用 `with_structured_output(PydanticModel)` 强制 LLM 输出符合 Schema 的 JSON，Pydantic 校验失败则降级，不接受自由格式文本。2）**业务规则层**：代码层硬覆盖——仓位截断（A股15%/港美10%）、ATR 硬阻断（> 8% 强制拒绝）、置信度惩罚函数，这些都在 LLM 调用结果之后执行，LLM 无法绕过。3）**兜底层**：所有节点有 `try/except` + 降级逻辑，最坏情况返回 HOLD + 低置信度报告，不崩溃。核心原则：LLM 是"专家顾问"而非"最终决策者"，代码层拥有否决权。

**Q3：域感知 RAG 路由的设计思路？**

> 核心洞察：不同分析角色需要的"外部知识"完全不同，同一个 query 服务所有人会产生域内噪音。设计时问：这个节点的决策需要什么类型的事实支撑？基本面分析师需要财务报表和机构评级；技术分析师需要资金面和量价关系；辩论裁决需要行业风险点和护城河。每个域专项检索后通过 `max_length` 控制注入量，防止撑大 prompt。实现上选择非侵入式设计：各节点内部独立调用，不修改 State Schema，向后兼容。

**Q4：大模型在安全审核场景的局限？**

> 三个核心局限：1）**幻觉**：LLM 在没有明确证据时倾向于编造合理的解释，金融/安全场景下这是致命的。解法：强制使用真实数据注入（RAG + tool call），不允许纯凭 LLM 知识推断。2）**置信度不校准**：LLM 的置信度输出不是严格概率，在分布外样本上尤其不可靠。解法：置信度只用来作相对排序和阈值过滤，不直接当作概率使用。3）**对抗性输入**：恶意用户可以通过特制 prompt 绕过基于 LLM 的审核。解法：关键安全规则不走 LLM 判断，而是代码层规则（类比信用卡反欺诈中的黑名单 vs 模型）。

**Q5：如何处理多 Agent 意见分歧？**

> CampusQuant 的解法是两层：1）**数学预加权**：在 LLM 做最终综合决策前，用 `_compute_weighted_score` 计算三路信号的数学加权结果，注入 prompt 作为"锚点"，防止 LLM 主观加权偏离预定权重。2）**条件辩论**：当基本面和技术面方向严格相反时（BUY vs SELL），触发 debate_node 进行结构化辩论，引入 RAG 外部事实作为裁决依据。上限是 2 轮辩论，避免无限循环。设计原则：分歧本身是有价值的信号，代表信息的边界，用辩论结构化地消解，而不是直接取平均或随机选一个。

---

## 六、英文 30 秒版本（面试英文自我介绍）

> I built CampusQuant, an AI-powered stock analysis platform for college students. The core challenge is that LLMs produce probabilistic outputs, but financial recommendations have zero tolerance for errors. My solution was a 9-node LangGraph multi-agent system with domain-aware RAG routing — each analyst node queries a specialized knowledge base — and a four-layer hard risk control that runs after LLM output as code-level overrides, not prompt instructions. The key innovation is a confidence penalty function that maps LLM uncertainty to position sizing: low confidence means smaller position, not binary HOLD-or-execute. This raised the system's overall accuracy from about 65% to 90% on a 50-stock evaluation set across A-share, Hong Kong, and US markets.

---

## 附：常见陷阱与应对

| 面试官追问方向 | 危险回答 | 正确定向 |
|-------------|---------|---------|
| "置信度怎么算的？" | "LLM 直接输出" | 说完整三阶段：三路各自 → 加权合并 → 惩罚映射 |
| "90%准确率怎么测的？" | "感觉差不多" | 说 D1-D4 四维公式 + 50只测试集 + 承认样本量局限 |
| "RAG 有什么用？" | "让模型知道更多" | 说 Recall@5 从 64%→88% + double-hit 原理 |
| "风控靠什么保证？" | "Prompt 里写了不能超过15%" | 强调代码层截断，LLM 输出后强制覆盖，四个函数 |
| "simulated=True 如何保证？" | "我们告诉模型要模拟" | 代码第1783行 `order_dict["simulated"] = True` 强制覆盖 |
| "如果 LLM 超时怎么办？" | "重试" | 所有节点有 `_safe_fallback_report` 降级，整图不崩溃 |
