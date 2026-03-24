# CampusQuant 技术面试手册
## Agent 开发 / 后端研发岗位深度追问版
## V1.0（2026-03）

---

## 一、多智能体架构与调度

### 简历原文
> 基于LangGraph设计9节点DAG工作流，内置A/港/美股差异化推理Prompt与权重配置，支持基本面/技术面/舆情/RAG四路并行分析，汇聚后条件路由——有分歧触发多空辩论（≤2轮），风控拒绝触发重试回路（≤2次）。

---

### 1.1 为什么选 LangGraph，不用普通 LangChain Chain 或手写 asyncio？

| 需求 | 普通 Chain | 手写 asyncio | LangGraph |
|------|-----------|-------------|-----------|
| 并行执行多个 Agent | ❌ 串行 | ✅ 需手动管理 | ✅ 原生 Fan-out |
| 条件路由（按状态决定下一节点） | ❌ | ❌ 需大量 if-else | ✅ add_conditional_edges |
| 受控循环（辩论≤2轮） | ❌ | ⚠️ 需自己实现终止 | ✅ 计数器+条件边 |
| 全节点共享状态 | ❌ 需手动传参 | ❌ | ✅ TradingGraphState |
| 流式事件（astream_events） | ❌ | ❌ | ✅ 原生支持 |

LangChain Chain 是线性的有向无环图（其实是链），不支持回路和并行分支。LangGraph 的 StateGraph 是真正的图结构，支持 Fan-out/Fan-in 并行、条件边、受控循环，是这个场景的唯一合理选型。

---

### 1.2 9节点 DAG 完整拓扑（代码级）

```
START
  └─► data_node（数据拉取 + 技术指标预计算）
        ├─► fundamental_node  ┐
        ├─► technical_node    ├─ Fan-out 并行（LangGraph 自动调度）
        ├─► sentiment_node    │
        └─► rag_node          ┘
              └─► portfolio_node（Fan-in 汇聚 + 加权评分 + 冲突检测）
                    │
                    ├─► [has_conflict=True 且 rounds<2] → debate_node
                    │         └─► portfolio_node（重新决策，形成辩论回路）
                    │
                    └─► [无冲突 或 rounds≥2] → risk_node
                              │
                              ├─► [REJECTED 且 retries<2] → portfolio_node（修订）
                              │
                              └─► [APPROVED/CONDITIONAL 或 retries≥2] → trade_executor
                                        └─► END
```

**代码实现（builder.py 核心片段）**：

```python
# Fan-out：同一个源节点 → 4个并行节点
graph.add_edge("data_node", "fundamental_node")
graph.add_edge("data_node", "technical_node")
graph.add_edge("data_node", "sentiment_node")
graph.add_edge("data_node", "rag_node")

# Fan-in：4个节点 → portfolio_node（LangGraph 自动等待全部完成）
graph.add_edge("fundamental_node", "portfolio_node")
graph.add_edge("technical_node",   "portfolio_node")
graph.add_edge("sentiment_node",   "portfolio_node")
graph.add_edge("rag_node",         "portfolio_node")

# 条件边1：portfolio_node → debate 或 risk
graph.add_conditional_edges("portfolio_node", route_after_portfolio,
    {"debate_node": "debate_node", "risk_node": "risk_node"})

# 辩论回路：debate → portfolio（重新决策）
graph.add_edge("debate_node", "portfolio_node")

# 条件边2：risk → portfolio（重试）或 trade_executor（通过）
graph.add_conditional_edges("risk_node", route_after_risk,
    {"portfolio_node": "portfolio_node", "trade_executor": "trade_executor"})
```

**关键设计点**：LangGraph 对"多条边指向同一节点"会自动 Fan-in——等待所有前置节点完成后才执行 portfolio_node，无需手写 `asyncio.gather` 或 barrier 同步原语。

---

### 1.3 TradingGraphState：并行安全的共享状态设计

所有节点读写同一个 `TradingGraphState`（TypedDict）。并行场景下存在写冲突风险，LangGraph 用 **Reducer** 解决：

```python
# state.py

def _append_log(left: List[str], right: List[str]) -> List[str]:
    """execution_log：并行节点各自追加日志，不覆盖"""
    return left + right

def _merge_counts(left: Dict[str, int], right: Dict[str, int]) -> Dict[str, int]:
    """tool_call_counts：各节点写自己的 key，reducer 合并
    修复 LangGraph 默认 last-write-wins 导致并行节点计数互相覆盖的 Bug"""
    merged = dict(left)
    merged.update(right)
    return merged

class TradingGraphState(TypedDict, total=False):
    # 普通字段：last-write-wins（节点间无冲突字段）
    symbol:            str
    fundamental_report: Optional[Dict]
    ...
    # Reducer 字段：并行安全
    messages:        Annotated[List[BaseMessage], add_messages]   # LangGraph 内置
    execution_log:   Annotated[List[str], _append_log]            # 自定义
    tool_call_counts: Annotated[Dict[str, int], _merge_counts]    # 自定义
```

**面试追问点**：为什么 `fundamental_report` 不需要 Reducer？因为各并行节点写的是**不同的 key**（fundamental_report / technical_report / sentiment_report），LangGraph 默认行为（last-write-wins on key）不会冲突。只有多个节点写同一个 key 时才需要 Reducer。

---

### 1.4 差异化推理 Prompt 与权重配置（两层实现）

**第一层：Prompt 差异化（fundamental_node）**

```python
# nodes.py _PROMPTS["fundamental"]
"A_STOCK": "核心框架：行业景气度(30%) + EPS增速/PEG(30%) + 政策催化剂(25%) + 资金热度(15%)"
"HK_STOCK": "核心框架：合理估值PE/PB(35%) + 自由现金流FCF(25%) + 分红/回购(20%) + 宏观因素(20%)"
"US_STOCK": "核心框架：EPS增速/PEG(30%) + 自由现金流(25%) + AI/科技主题(25%) + 宏观Beta(20%)"
```

为什么 A 股强调政策催化剂而美股强调 AI 主题？因为 A 股是政策市，散户主导，政策边际变化是最强价格驱动力；美股机构化程度高，EPS 增速与估值模型是主流分析框架。Prompt 工程的核心价值是把领域知识编码进模型的推理起点。

**第二层：数学预加权（portfolio_node）**

技术面和舆情节点使用统一 DEFAULT Prompt（市场间差异不显著），但 portfolio_node 在调用 LLM 之前先做**数学加权计算**，把结果作为"锚点"注入 Prompt，防止 LLM 主观忽略预定权重：

```python
# nodes.py _MARKET_WEIGHTS
_MARKET_WEIGHTS = {
    "A_STOCK":  {"fundamental": 0.35, "technical": 0.40, "sentiment": 0.25},
    "HK_STOCK": {"fundamental": 0.50, "technical": 0.25, "sentiment": 0.25},
    "US_STOCK": {"fundamental": 0.40, "technical": 0.35, "sentiment": 0.25},
}

# _compute_weighted_score()
f_score = _REC_SCORE[f_rec] * f_conf   # BUY=1.0, HOLD=0.5, SELL=0.0
weighted_score = fw * f_score + tw * t_score + sw * s_score
# 0.60以上→pre_signal=BUY，0.35以下→SELL，中间→HOLD
# 将此预计算结果注入 portfolio_node Prompt，作为 LLM 推理锚点
```

A 股技术面权重最高（0.40）因为量化交易主导，技术信号有自我实现效应；港股基本面最高（0.50）因为机构价值投资导向。

---

### 1.5 路由逻辑代码实现

```python
# nodes.py
def route_after_portfolio(state: TradingGraphState) -> str:
    if state.get("has_conflict") and state.get("debate_rounds", 0) < MAX_DEBATE_ROUNDS:
        return "debate_node"    # 有分歧 且 未超轮次 → 辩论
    return "risk_node"          # 无分歧 或 已满轮次 → 直接风控

def route_after_risk(state: TradingGraphState) -> str:
    status  = (state.get("risk_decision") or {}).get("approval_status", "APPROVED")
    retries = state.get("risk_rejection_count", 0)
    if status == "REJECTED" and retries < MAX_RISK_RETRIES:
        return "portfolio_node"   # 拒绝 且 未超重试 → 返回重新决策
    return "trade_executor"       # 通过 或 重试耗尽 → 执行
```

**MAX_DEBATE_ROUNDS=2，MAX_RISK_RETRIES=2** 是经过权衡的产品参数：轮次太少分析不充分，轮次太多用户等待不可接受。这两个数字决定了最坏情况下的节点执行次数上界。

---

## 二、异构数据管道与混合 RAG

### 简历原文
> 统一封装A/港/美股多源API，配套内存缓存与指数退避重试容错机制，实现稳定数据获取。搭建混合RAG（Chroma稠密向量+BM25稀疏关键词+实时Web检索引擎），结合RRF重排序融合多路结果，混合Recall@5达88%，较BM25单路提升约24pp，提升垂直域金融研报的检索精度。

---

### 2.1 多源异构数据管道

**为什么叫"异构"？**

三个市场的数据源完全不同，字段名、数值单位、时区都不一致：

| 市场 | 数据源 | 特殊处理 |
|------|--------|---------|
| A股 | akshare `stock_zh_a_spot_em` | 字段位置索引（非列名），无时区 |
| 港股 | akshare `stock_hk_spot_em` | 代码需去前导零（`00700→0700.HK`） |
| 美股 | yfinance `Ticker.history()` | UTC时区转换，货币单位USD |
| A股指数 | 新浪财经直连 `hq.sinajs.cn` | 原始文本解析（非DataFrame） |
| 全球指数 | yfinance `fast_info` | `previous_close` 计算涨跌幅 |

`DataLoader._standardize()` 把所有来源统一转为 `[timestamp, open, high, low, close, volume]`，上层节点只消费标准格式，不感知数据来源。这是**适配器模式（Adapter Pattern）**的应用。

**TTL 缓存（300s）**：

```python
# 逻辑示意
_cache: dict[str, tuple] = {}   # symbol → (data, expire_time)

def get_cached(symbol):
    if symbol in _cache and time.time() < _cache[symbol][1]:
        return _cache[symbol][0]   # 命中：~100ms（内存读取）
    data = fetch_from_api(symbol)  # 未命中：5-10s（网络请求）
    _cache[symbol] = (data, time.time() + 300)
    return data
```

"10s+→100ms"是冷请求和缓存命中的对比，不是同一次请求被优化了。用户频繁刷新同一标的时，5分钟内全部命中缓存，接口压力降为 1/N。

**指数退避重试（Exponential Backoff）**：

```python
for attempt in range(3):
    try:
        return fetch_data(symbol)
    except (RemoteDisconnected, Timeout):
        time.sleep(1.5 ** attempt)   # 1s → 1.5s → 2.25s
raise DataFetchError("all retries exhausted")
```

为什么退避而非固定间隔？服务端过载时，固定间隔重试会形成**重试风暴**加剧拥塞；指数退避让服务端有喘息窗口，是分布式系统的标准容错模式（TCP 拥塞控制同理）。

---

### 2.2 大盘指数的 Fail-Fast 容灾（实战工程案例）

这是项目中最典型的"发现问题→诊断→最小化修复"案例。

**现象**：`/api/v1/market/indices` 接口频繁 10s+ 超时，日志大量 `RemoteDisconnected` 警告。

**诊断过程**：
1. 写基准测试脚本，对 `stock_zh_index_spot_em`（东方财富）和新浪直连分别连续请求3次
2. 结果：东方财富 1/3 成功率，失败耗时 5.7~8.6s；新浪直连 3/3，平均 619ms
3. 根因：`push2.eastmoney.com` 被本机代理拦截（ProxyError），akshare 内部有 `request_with_retry` 自带重试，加上外层 `retries=1`，双重重试 → 每次失败等 8s

**修复（三处代码改动）**：

```python
# 修复前：retries=1（外层再重试1次，和akshare内部重试叠加）
_akshare_with_retry(ak.stock_zh_index_spot_em, retries=1, delay=0.5)

# 修复后：retries=0（去除外层重试，依赖新浪兜底）
_akshare_with_retry(ak.stock_zh_index_spot_em, retries=0, delay=0)

# Event wait：12s → 4s（Fail-Fast，4s后不等akshare，用新浪数据）
_ak_a_ev.wait(timeout=4)   # 原来 timeout=12

# 优先级调整：新浪直连从"最低优先"升为"覆盖akshare"
price_map.update(akshare_result)   # 先填akshare（低优先）
price_map.update(sina_result)      # 再用新浪覆盖（高优先，更稳定）
price_map.update(yfinance_result)  # yfinance 最高（全球指数）
```

**效果**：最坏情况响应时间从 12s → 4s；新浪直连 619ms 覆盖全部4个国内指数，正常情况 <1s 返回。

**面试价值**：这个案例展示了"测量先于优化"的工程方法论——先用基准脚本定量分析，找到根因（双重重试），再做最小改动，而不是凭感觉换接口。

---

### 2.3 混合 RAG 架构深度解析

**为什么纯向量检索不够？**

金融文本有大量精确专有名词：`600519`、`ROE`、`PE-TTM`、`茅台`。向量模型对精确字符串的编码能力弱——"净利润"和"盈利能力"向量相近，但 `600519` 和 `000001` 的向量距离可能反而更近（都是6位数字）。BM25 是词频模型，精确匹配这类 token 是其强项。

**三层混合架构（knowledge_base.py）**：

```
用户查询（如："茅台 A_STOCK 行业景气度 宏观经济"）
   │
   ├─► Chroma 向量检索（OpenAI/DashScope Embedding）
   │       → 语义相关文档（擅长泛化理解）
   │
   ├─► BM25 稀疏检索（rank_bm25）
   │       → 精确匹配专有名词/数字（擅长精确召回）
   │
   └─► DuckDuckGo Web 实时搜索（duckduckgo-search）
           → 最新新闻/公告（擅长时效性信息）
               │
               ▼
      LangChain EnsembleRetriever（内置 RRF 融合）
               │
               ▼
      Top-K 文档片段 → 注入分析节点 Prompt
```

**RRF（Reciprocal Rank Fusion）算法**：

```
RRF_score(d) = Σ 1 / (k + rank_i(d))
```

`d` 在检索器 `i` 的结果中排名越靠前，得分越高。k=60 是经验超参，作用是压缩头部文档的得分优势，避免某路结果排名第1的文档绝对主导最终排名。

**为什么用 RRF 而不是加权平均？**

不同检索器返回的相关性分数不可比较（Chroma 返回余弦相似度 0~1，BM25 返回 TF-IDF 分数无上界）。直接加权平均会被量纲不同的分数主导。RRF 只用排名位置，不用原始分数，天然解决了量纲不统一问题。

**离线知识库预构建（scripts/build_kb.py）**：

```
离线（一次性执行）：
  python scripts/build_kb.py
    → 读取 data/docs/ 所有文档
    → 调用 Embedding API（耗时 ~60s，含网络请求）
    → 写入 data/chroma_db/（持久化向量索引）
    → 序列化 data/bm25_index.pkl

在线（每次启动）：
  _load_chroma() → 直接从磁盘加载向量索引（无 Embedding 调用）
  _load_bm25()   → 反序列化 pkl
  总耗时 < 2s
```

"60s→2s"是离线构建 vs 在线加载的对比，不是同一流程被优化了。

**Recall@5=88%，较BM25单路+24pp（内测值）**：

在金融垂直域 25 条测试查询（含精确代码、指标的复杂问题）下统计。提升主要来自两类：含精确 token 的查询（BM25贡献）+语义泛化查询（向量检索贡献）。RRF 融合后两类查询都能稳定召回。

---

## 三、高可用工程与稳定性治理

### 简历原文
> 构建指数退避重试与底层网络补丁的容灾体系，攻克跨市场数据请求超时与国内代理环境下的API拦截痛点，保障数据链路与大模型接口稳定。封装节点降级逻辑，结合Pydantic约束LLM结构化输出，具备异常可降级能力。

---

### 3.1 Pydantic 结构化输出（7处调用，4种模型）

**为什么需要 Pydantic 约束？**

LLM 原始输出是字符串，即使要求输出 JSON，也可能：
- 多余的 Markdown 包裹（```json ... ```）
- 字段名拼写错误（`recommendation` 写成 `recommandation`）
- 数值类型错误（仓位写成 `"10%"` 而非 `10.0`）
- 必填字段缺失

`with_structured_output(PydanticModel)` 底层用 Function Calling / JSON Schema 约束模型输出，再自动解析为 Python 对象。

**4种 Pydantic 模型（state.py）**：

```python
class AnalystReport(BaseModel):
    recommendation: Literal["BUY", "SELL", "HOLD"]
    confidence: float = Field(ge=0, le=1)          # 置信度约束
    reasoning: str
    key_factors: List[str]
    risk_factors: List[str]
    price_target: Optional[float] = None
    signal_strength: Literal["STRONG", "MODERATE", "WEAK"]

class DebateOutcome(BaseModel):
    resolved_recommendation: Literal["BUY", "SELL", "HOLD"]
    bull_argument_summary: str
    bear_argument_summary: str
    deciding_factor: str
    confidence: float = Field(ge=0, le=1)
    debate_summary: str = Field(min_length=80)    # 最少80字符，防止敷衍输出

class RiskDecision(BaseModel):
    approval_status: Literal["APPROVED", "CONDITIONAL", "REJECTED"]
    position_pct: float = Field(ge=0, le=20)      # 仓位 0~20%
    stop_loss_pct: float
    take_profit_pct: float
    rejection_reason: Optional[str] = None
    max_loss_amount: Optional[float] = None

class TradeOrder(BaseModel):
    action: Literal["BUY", "SELL", "HOLD"]
    quantity_pct: float = Field(ge=0, le=100)
    rationale: str = Field(min_length=30)         # 最少30字符
    simulated: bool = Field(default=True)         # 永远为True，物理隔断实盘
```

**7处 with_structured_output 调用**：fundamental / technical / sentiment / portfolio（各用AnalystReport）+ debate（DebateOutcome）+ risk（RiskDecision）+ trade_executor（TradeOrder）。

---

### 3.2 节点降级逻辑（Fail-Safe 设计）

每个节点都有三层兜底，从上到下降级：

```
层1：with_structured_output（Function Calling / JSON Schema）
     ↓ 失败（模型不支持 / 超时）
层2：原始字符串 JSON 解析 + 键名归一化（兼容同义词替换）
     ↓ 失败（JSON 格式错误）
层3：保守降级默认值
     → risk_node：REJECTED, position_pct=0, rationale="风控评估异常，系统保守降级为HOLD"
     → trade_executor：HOLD, quantity_pct=0
```

**为什么降级方向是 HOLD/0仓位，而不是随机值？**

这是 **Fail-Safe** 原则：系统失效时趋向安全状态。对于金融场景，不操作（HOLD）永远比随机操作安全。如果降级方向是 BUY，LLM 异常可能导致用户直接下单，后果不可控。

---

### 3.3 data_fetch_failed 短路机制

`data_node` 获取行情失败时，设置 `data_fetch_failed=True`。四个并行分析节点在执行开头检测此标志：

```python
async def fundamental_node(state):
    if state.get("data_fetch_failed"):
        return {
            "fundamental_report": {"recommendation": "HOLD", "confidence": 0.1,
                                   "reasoning": "数据获取失败，降级HOLD"},
            ...
        }
    # 正常执行 LLM 分析...
```

**设计价值**：在无效数据上调用 LLM 是浪费（每次调用有 Token 成本），且 LLM 会基于空数据"幻觉"出分析结论。短路机制确保数据失败时**不消耗 LLM 调用**，直接降级。

---

## 四、全栈开发与业务落地

### 简历原文
> 基于FastAPI+SSE实现9节点推理状态与市场数据实时流式推送。系统层内置四重不可豁免风控（差异化仓位上限、ATR%波动率阻断、单次亏损硬上限、LLM保守降级）与动态置信度惩罚机制，消除大模型输出均值化偏差。

---

### 4.1 FastAPI + SSE 流式推送

**为什么用 SSE 而不是 WebSocket？**

| 维度 | SSE | WebSocket |
|------|-----|-----------|
| 通信方向 | 服务端单向推送 | 双向 |
| 协议 | HTTP/1.1（标准） | WS 协议（需升级握手） |
| 实现复杂度 | 低（sse-starlette） | 高 |
| 断线重连 | 浏览器原生支持 | 需手动实现 |
| 适用场景 | 进度推送/日志流 | 聊天/游戏 |

研报生成是**纯服务端推送**场景（用户只接收，不中途发消息），SSE 是正确选型，比 WebSocket 轻量且易运维。

**9种 SSE 事件类型（server.py）**：

```
start        → 分析任务开始
node_start   → 某节点开始执行（触发前端进度条动画）
node_complete→ 某节点执行完毕（显示节点状态徽章）
conflict     → portfolio_node 检测到分歧（触发辩论提示）
debate       → debate_node 输出辩论内容（触发打字机效果）
risk_check   → risk_node 输出风控决策
risk_retry   → 风控拒绝，触发重试（前端显示重审提示）
trade_order  → 最终交易指令（触发结果卡片展示）
complete     → 全流程完成
error        → 异常（含 error_type 字段供前端细粒度展示）
```

**FastAPI SSE 实现核心**：

```python
# server.py
async def analyze_stream(symbol: str):
    yield _make_sse_event(event="start", data={"symbol": symbol})

    async for event in graph.astream_events(initial_state, ...):
        node_name = event.get("name", "")
        if event["event"] == "on_chain_start":
            yield _make_sse_event(event="node_start", data={"node": node_name})
        elif event["event"] == "on_chain_end":
            output = event.get("data", {}).get("output", {})
            # 根据 node_name 判断事件类型
            if node_name == "portfolio_node" and output.get("has_conflict"):
                yield _make_sse_event(event="conflict", data=output)
            elif node_name == "debate_node":
                yield _make_sse_event(event="debate", data=output)
            # ...
```

---

### 4.2 四重不可豁免风控（代码层强制执行）

**"不可豁免"的含义**：风控在代码层执行，不依赖 Prompt 约束。Prompt 可以被模型忽略，代码不会。

**① 差异化仓位上限（risk_node）**

```python
max_pos = 15.0 if market_type == "A_STOCK" else 10.0
if decision_dict["position_pct"] > max_pos:
    decision_dict["position_pct"] = max_pos   # 强制截断
```

A 股≤15%、港美≤10%。设计依据：假设本金5万，15%=7500元，按5%止损最大亏损375元，在大学生可承受范围内。

**② ATR% 波动率阻断**

```python
if atr_pct > 8.0 and current_rec != "HOLD":
    decision_dict["approval_status"] = "REJECTED"
    decision_dict["position_pct"] = 0.0          # 直接拒绝
elif atr_pct > 5.0 and status == "APPROVED":
    decision_dict["position_pct"] *= 0.5          # 仓位减半，降为CONDITIONAL
```

ATR%（14日平均真实波动幅度/收盘价）是标的日内波动的标准度量。高 ATR% 意味着止损价难以设置，大学生在情绪压力下很难执行纪律止损。

**③ 单次亏损硬上限（¥3000）**

```python
_CAPITAL = 50_000   # 假设本金5万
_MAX_LOSS = 3_000   # 单次最大亏损

implied_loss = _CAPITAL * position_pct/100 * stop_loss_pct/100
if implied_loss > _MAX_LOSS:
    safe_pos = _MAX_LOSS / (_CAPITAL * stop_loss_pct/100) * 100
    decision_dict["position_pct"] = safe_pos   # 按比例压缩仓位
```

¥3000 是调研中大学生自报"能接受的最大单次损失"中位数，硬编码为系统上限。

**④ LLM 异常保守降级**

```python
except Exception as e:
    return {
        "risk_decision": {
            "approval_status": "REJECTED",
            "position_pct": 0.0,
            "rejection_reason": f"风控评估异常（{str(e)[:80]}），系统保守降级为HOLD"
        }
    }
```

---

### 4.3 动态置信度惩罚（trade_executor 第二道防线）

风控红线在 risk_node 执行，但 trade_executor 还有独立的置信度惩罚机制：

```python
# nodes.py
_CONF_FLOOR     = 0.40   # 低于此值强制HOLD
_CONF_THRESHOLD = 0.55   # 低于此值线性缩仓

def _apply_confidence_penalty(action, confidence, base_pct):
    if confidence < _CONF_FLOOR:
        return "HOLD", 0.0, "置信度过低，强制HOLD"
    if confidence < _CONF_THRESHOLD:
        scale = (confidence - _CONF_FLOOR) / (_CONF_THRESHOLD - _CONF_FLOOR)
        return action, round(base_pct * scale, 2), f"置信度惩罚: {base_pct}×{scale:.2f}"
    return action, base_pct, None
```

**0.40 和 0.55 阈值的设计逻辑**：
- 0.40 → 模型自认为有60%概率分析错误，此时任何建议都是噪声，强制 HOLD
- 0.55 → "基本有依据"的门槛，0.40~0.55 之间线性过渡，避免0.39/0.40处的悬崖效应

**极值阻断（5条规则，_extreme_value_block）**：

```
1. quantity_pct > max_position → 截断至上限
2. BUY时止盈隐含收益 > 80% → 截断（防LLM输出不合理止盈价）
3. 止损幅度 < 1% 或 > 20% → 修正到边界
4. BUY时 stop_loss > current_price → 止损在现价上方（无效），清空
5. SELL时 stop_loss < current_price → 止损在现价下方（无效），清空
```

两道防线串联（risk_node → trade_executor），形成纵深防御。

---

## 五、高频面试问题

**Q1：LangGraph 的 Fan-out 并行是真正的多线程并行吗？**

> 取决于执行器配置。默认情况下 LangGraph 用 Python 的 `asyncio` 事件循环，四个节点通过 `async/await` 并发执行，不是多线程。由于节点内部的 LLM 调用（HTTP 请求）是 I/O 密集型操作，asyncio 并发在这个场景下几乎等同于真并行——等待网络响应时 CPU 可以切换执行其他节点。如果节点内有 CPU 密集型计算，才需要 `ThreadPoolExecutor` 或 `ProcessPoolExecutor`。

**Q2：为什么 `tool_call_counts` 需要自定义 Reducer，而 `fundamental_report` 不需要？**

> `fundamental_report`、`technical_report`、`sentiment_report` 是三个不同的 key，每个并行节点只写自己对应的 key，LangGraph 默认的 last-write-wins 在不同 key 上不冲突。但 `tool_call_counts` 是一个 dict，所有节点都往这个 dict 里写，如果用 last-write-wins，后写入的节点会覆盖前面节点写入的内容，导致某些节点的计数器丢失。`_merge_counts` 用 `dict.update` 语义，把各节点的 key 合并，每个节点只写自己的 key，互不覆盖。这是我在参考开源项目（TradingAgents-CN）时发现的并发 Bug，并在本项目中修复。

**Q3：混合 RAG 中 EnsembleRetriever 的权重（BM25 50% + Chroma 50%）和 RRF 是什么关系？**

> LangChain 的 `EnsembleRetriever` 内部就是用 RRF 算法融合多路结果，权重参数控制的是 RRF 公式中各路结果的贡献系数，而不是直接的分数加权（原始分数量纲不同，不可直接加权）。50%:50% 表示两路在 RRF 融合时权重相等，实际召回时两路各自检索 Top-K 个文档，RRF 按排名位置融合，最终返回综合排名最高的文档。

**Q4：Pydantic 约束一定能防止 LLM 输出错误吗？**

> 不是100%保证。`with_structured_output` 底层走 Function Calling 或 JSON Schema 路径，主流模型（GPT-4、Qwen-Max）遵从率很高，但仍可能出现字段语义正确但值越界（如 confidence=1.5）的情况，这时 Pydantic 的 `Field(ge=0, le=1)` 会在解析时抛 `ValidationError`。本项目的应对方式是三层兜底：层1 with_structured_output 失败 → 层2 原始 JSON 解析 + 键名归一化 → 层3 保守降级默认值。

**Q5：SSE 和长轮询（Long Polling）有什么区别？**

> Long Polling 是客户端主动发请求、服务端"挂起"直到有数据再响应，每次响应后客户端需要立即发新请求，有重复建连开销。SSE 建立一次 HTTP 连接后保持长开，服务端持续通过 `text/event-stream` 格式推送，客户端无需重复请求，且浏览器原生支持断线自动重连（`EventSource` API）。研报生成期间节点状态频繁变化（秒级），SSE 避免了 Long Polling 的高频建连开销。

**Q6：ATR% 如何计算？为什么用它衡量波动率而不是历史波动率（HV）？**

> ATR（Average True Range）= 过去14日 max(High-Low, |High-PrevClose|, |Low-PrevClose|) 的平均值。ATR% = ATR / 收盘价 × 100%。相比历史波动率（标准差 × √252），ATR 能捕捉**跳空**（gap）—— 比如某股票昨日收盘100，今日跳空低开到90，HV 可能低估这个风险，但 ATR 把 |Low-PrevClose|=10 纳入计算，更贴近"实际价格滑动范围"。对于大学生这种止损纪律较弱的用户群体，ATR% 提供了更直观的"最坏情况单日亏损比例"估算。

**Q7：项目中遇到的最难的工程问题是什么？**

> 大盘指数接口 Fail-Fast 修复。现象是 `/api/v1/market/indices` 频繁 10s+ 超时。通过写基准测试脚本定量分析，发现东方财富接口被本机代理拦截（ProxyError），akshare 内部自带 retry，加上外层 `retries=1`，双重重试导致每次失败要等 5-8 秒才放弃。新浪财经直连稳定性 3/3、619ms。修复：去除外层重试 + Event wait 从 12s 降到 4s + 新浪优先级升高。关键方法论是**先测量再优化**，基准脚本给了定量数据，避免了凭感觉盲目换接口。

---

## 六、系统设计追问（开放题）

**Q：如果要把这个系统扩展到支持100个并发用户同时请求分析，需要做哪些改造？**

> 当前瓶颈分析：
> 1. **LLM 调用**：每个请求独立调用7次 LLM，100并发 = 700次并行 LLM 调用，会触发 API 限流（Rate Limit）。需要引入**请求队列 + 令牌桶限流**，或者使用支持更高并发的 LLM 服务。
> 2. **内存缓存**：当前用进程内 dict，多进程部署（uvicorn workers > 1）时各进程缓存独立，命中率降低。需要改为 **Redis 共享缓存**。
> 3. **MemorySaver**：LangGraph 的 MemorySaver 把所有 thread_id 状态存在进程内存，100用户并发 × 每个状态 ~100KB = 10MB，量级可接受，但多进程时状态不共享。生产级应改为 **SqliteSaver 或 RedisSaver**。
> 4. **SSE 连接**：100 个 SSE 长连接，FastAPI 异步处理没有问题，但部署时需要 Nginx 配置 `proxy_buffering off` 确保 SSE 数据实时传输。

---

*文档版本：V1.0（2026-03）| 适用岗位：Agent开发/后端研发 | 追问深度：技术面二面/三面*
