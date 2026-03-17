# CampusQuant · 校园财商智能平台

> 专为**在校大学生**设计的多智能体量化分析系统——本金安全第一，财商教育优先。

基于 **LangGraph + LLM** 的多 Agent 协作分析平台，覆盖 **A股、港股、美股**三大市场。9 个智能体节点全链路已端对端验证贯通，通过 FastAPI SSE 实时流式输出分析进度与深度研报。内置大学生专属风控守则与 AI 财商助手，帮助大学生建立正确的投资认知，识别金融风险，远离高危杠杆产品。

> **红线声明**：本项目已全面移除加密货币（Crypto）支持。高波动、高杠杆、诈骗高发，不适合本金有限的大学生。所有交易指令均指向**本地模拟撮合引擎**，不接入任何真实交易所 API。

---

## 功能特点

| 功能 | 说明 |
|------|------|
| **多 Agent 并行分析** | 基本面、技术面、情感面三路 Agent 并发执行，四节点扇出再汇聚 |
| **多空辩论机制** | 分析师意见冲突时触发辩论节点，最多 2 轮对抗性推理 |
| **大学生专属风控** | 仓位上限（A股≤15%，港/美≤10%），ATR%>8% 直接拒绝，禁止杠杆/期权 |
| **持仓体检** | 独立健康检查分支，从集中度、回撤、流动性三维评分并给出优化建议 |
| **混合 RAG 知识库** | Chroma 向量检索 + BM25 稀疏检索 + DuckDuckGo 实时联网，三路融合 |
| **SSE 实时流式推送** | FastAPI Server-Sent Events，逐节点推送分析进度，前端打字机效果 |
| **智能标的搜索** | 60+ 标的中英文模糊匹配，"茅台"→`600519.SH`，"英伟达"→`NVDA` |
| **AI 财商助手** | "财财学长"侧边栏聊天机器人，用打比方讲解投资概念，强烈劝退高风险行为 |
| **结构化输出** | 所有 LLM 输出经 Pydantic 模型验证，彻底取代正则/JSON 手工解析 |
| **多界面支持** | 静态 HTML 前端（8页）、Streamlit Web UI、CLI 命令行、REST API |

---

## 系统架构

### LangGraph 状态机工作流

```
START → data_node
              │
   ┌──────────┼──────────┬──────────┐
   ▼          ▼          ▼          ▼
fund_node  tech_node  sent_node  rag_node     ← 四节点并行
   └──────────┼──────────┴──────────┘
              ▼
        portfolio_node  ← 综合决策（大学生专属规则注入）
              │
     ┌────────┴────────┐
   [有冲突]          [无冲突]
     ▼                 ▼
 debate_node       risk_node     ← 大学生专属严格风控
     │                 │
     └──→ portfolio_node          ← 辩论后重新决策
                   ▼
           ┌──────┴──────┐
        [批准]          [拒绝 ≤2次]
           ▼                ▼
    trade_executor    portfolio_node（重试）
           │
          END

──────── 独立分支（持仓体检）────────
START → health_node → END
```

**关键设计**：
- **并行扇出**：`data_node` 完成后四个分析节点同时调度
- **条件路由**：`portfolio_node` 根据冲突标志决定进入辩论还是直接风控
- **循环保护**：辩论最多 `MAX_DEBATE_ROUNDS=2` 轮，风控拒绝最多 `MAX_RISK_RETRIES=2` 次
- **Anti-Loop**：`tool_call_counts` 字典记录各节点工具调用次数，超 `MAX_TOOL_CALLS=3` 强制降级
- **持仓体检**：独立 `build_health_graph()` 分支，`START→health_node→END`，可单独触发

### 整体分层架构

```
┌────────────────────────────────────────────────────────────────┐
│                        前端界面层                               │
├────────────────────┬───────────────────────────────────────────┤
│  静态 HTML 前端     │  Streamlit Web UI     │  CLI / REST API  │
│  index.html (首页)  │  app.py              │  workflow.py     │
│  trade.html (演练)  │  ├─ 智能模糊搜索      │  api/server.py   │
│  platforms.html     │  └─ "财财学长"助手    │  FastAPI + SSE   │
│  market.html 等     │                       │                  │
└────────────────────┴───────────────────────┴──────────────────┘
                              │
┌─────────────────────────────▼──────────────────────────────────┐
│                      LangGraph 编排层                           │
│  graph/builder.py  StateGraph / build_graph() / build_health_graph()
│  graph/nodes.py    9个节点实现（含 health_node + anti-loop）   │
│  graph/state.py    TypedDict 状态 + Pydantic 结构化输出模型    │
└─────────────┬───────────────────────────────────────────────────┘
              │
   ┌──────────┼──────────────────────┐
   ▼          ▼                      ▼
┌──────────┐ ┌──────────────────┐  ┌─────────────┐
│  数据层  │ │    分析引擎层    │  │  LLM 引擎   │
│DataLoader│ │ fundamental_node │  │ LLMClient   │
│A股 akshare│ │ technical_node  │  │ DashScope/  │
│港股 akshare│ │ sentiment_node │  │ Qwen（主）  │
│美股 yfinance│ │ rag_node      │  │ OpenAI/     │
│TTL缓存   │ │ portfolio_node  │  │ Anthropic   │
│指数退避  │ │ debate_node     │  │ CoT 推理    │
└──────────┘ │ risk_node       │  │ Pydantic    │
             │ trade_executor  │  │ 结构化输出  │
             │ health_node     │  └─────────────┘
             └─────────────────┘
```

### 市场差异化分析权重

| 市场 | 基本面 | 技术面 | 舆情 | 风控 | 分析重点 |
|------|--------|--------|------|------|----------|
| A股  | 20%    | 35%    | 35%  | 10%  | 政策催化 + 行业动量 + EPS 增长 |
| 港股 | 45%    | 20%    | 25%  | 10%  | 价值投资 + 安全边际 + FCF 质量 |
| 美股 | 35%    | 30%    | 25%  | 10%  | 估值效率 + FCF 收益率 + 盈利超预期 |

---

## 前端界面

### 静态 HTML 前端（8 页互通）

项目包含一套完整的静态 HTML 前端，所有页面共享同一设计系统（glassmorphism 风格，CSS 变量统一）并可相互跳转。

| 文件 | 导航名称 | 核心内容 |
|------|----------|----------|
| `index.html` | **首页** | 产品介绍、功能模块卡片、AI 分析 SSE 演示 Demo |
| `trade.html` | **模拟演练** | 股票代码输入、市场选择、SSE 流式 AI 分析、节点进度徽章、结果卡片 |
| `platforms.html` | **持仓体检** | 持仓录入表单（代码/数量/成本）、健康评分环形图、三维风险指标、AI 优化建议 |
| `market.html` | **市场快讯** | 六大指数概览、A股/港股/美股热门标的切换表、市场资讯 feed、情绪栏 |
| `community.html` | **投教社区** | 学习资源入口、讨论广场、学习路径、热门话题、大学生投资守则 |
| `team.html` | **关于我们** | 使命愿景、项目数据、发展时间轴、核心功能、团队成员 |
| `home.html` | —（辅助页）| 学习中心：模拟持仓概览、自选股监控、学习进度、AI 分析历史 |
| `resources.html` | —（辅助页）| 学习资源库：精选教程文章、推荐书单，从 community.html 链接进入 |

**导航结构**：`首页 → 模拟演练 → 持仓体检 → 市场快讯 → 投教社区 → 关于我们`

### Streamlit Web UI（`app.py`）

功能更丰富的交互界面，包含：
- 智能股票搜索（中文模糊匹配，60+ 标的）
- LangGraph 分析进度实时可视化（节点状态 ⬜→🔄→✅）
- 多列结果展示（分析师报告卡、辩论摘要、风控决策、最终指令）
- 侧边栏"**财财学长**"AI 财商助手（独立 LLM 对话，不经 LangGraph）

---

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置 API Key

复制环境变量模板：

```bash
cp .env.example .env
```

编辑 `.env`（至少配置主 LLM）：

```env
# 主 LLM：阿里云百炼 Qwen（国内直连，无需代理）
DASHSCOPE_API_KEY=sk-your-dashscope-key

# 备用 LLM（可选，取消注释启用）
# OPENAI_API_KEY=sk-your-openai-key
# ANTHROPIC_API_KEY=sk-ant-your-anthropic-key
```

### 3. 启动服务

#### 方式 A：静态 HTML 前端 + FastAPI 后端（推荐）

```bash
# 启动 FastAPI 后端（提供 SSE 分析 API）
uvicorn api.server:app --host 127.0.0.1 --port 8000 --reload
```

然后直接在浏览器中打开 `index.html`（或用任意静态文件服务器托管）：

```bash
# 方式一：浏览器直接打开（部分 SSE 功能受 file:// 协议限制）
# 方式二：用 Python 内置服务器（推荐）
python -m http.server 3000
# 访问 http://localhost:3000
```

#### 方式 B：Streamlit Web UI

```bash
# 终端 1：FastAPI 后端
uvicorn api.server:app --host 127.0.0.1 --port 8000

# 终端 2：Streamlit 前端
streamlit run app.py
# 访问 http://localhost:8501
```

#### 方式 C：命令行（CLI）

```bash
python workflow.py
```

选择分析模式：
- **模式 1**：单标的分析（如 `AAPL`、`600519.SH`、`00700.HK`）
- **模式 2**：批量分析 `config.py` 中的所有预设标的
- **模式 3**：自定义批量分析

#### 方式 D：快速功能测试

```bash
python quick_start.py
```

---

## 项目结构

```
trading_agents_system/
│
├── config.py                      # 全局配置（API Keys、标的列表、技术指标参数、风控参数）
├── requirements.txt               # 依赖库清单
├── workflow.py                    # CLI 主程序入口（三种分析模式）
├── app.py                         # Streamlit Web UI（智能搜索 + "财财学长"助手）
├── quick_start.py                 # 快速环境测试脚本
├── README.md                      # 本文档
├── API_DOCS.md                    # REST API 接口文档
│
├── 静态 HTML 前端
│   ├── index.html                 # 首页（产品介绍 + AI 分析演示）
│   ├── trade.html                 # 模拟演练（SSE 流式分析）
│   ├── platforms.html             # 持仓体检（AI 健康诊断）
│   ├── market.html                # 市场快讯（A/港/美股行情）
│   ├── community.html             # 投教社区（学习讨论）
│   ├── team.html                  # 关于我们（项目信息）
│   ├── home.html                  # 学习中心（模拟仪表盘）
│   └── resources.html             # 学习资源库
│
├── graph/                         # LangGraph 状态机（主执行路径）
│   ├── state.py                   # TypedDict 全局状态 + Pydantic 输出模型
│   │                              #   AnalystReport / RiskDecision / TradeOrder
│   │                              #   DebateOutcome / PortfolioPosition / PortfolioHealthReport
│   ├── builder.py                 # StateGraph 图结构组装
│   │                              #   build_graph() / build_graph_with_memory()
│   │                              #   build_health_graph() / make_initial_state()
│   └── nodes.py                   # 9个节点实现
│                                  #   data_node / fundamental_node / technical_node
│                                  #   sentiment_node / rag_node / portfolio_node
│                                  #   debate_node / risk_node / trade_executor
│                                  #   health_node（持仓体检专属节点）
│
├── tools/                         # 工具层（供节点调用）
│   ├── market_data.py             # @tool 装饰的市场数据函数（封装 DataLoader）
│   └── knowledge_base.py          # 混合 RAG：Chroma + BM25 + DuckDuckGo + PDF加载
│
├── utils/                         # 通用工具模块
│   ├── data_loader.py             # 多市场数据加载器
│   │                              #   A股 akshare / 港股 akshare / 美股 yfinance
│   │                              #   TTL 内存缓存（5分钟）+ 指数退避重试（最多3次）
│   ├── llm_client.py              # LLM 统一接口（DashScope/OpenAI/Anthropic 切换）
│   └── market_classifier.py       # 市场分类 + 60+ 标的模糊名称匹配
│
├── api/                           # FastAPI 后端
│   └── server.py                  # SSE 流式接口（详见下方 API 端点说明）
│
├── agents/                        # 原始 Agent 类（已被 graph/ 节点取代，保留供参考）
│   ├── base_agent.py
│   ├── data_agent.py / fundamental_agent.py / technical_agent.py
│   ├── sentiment_agent.py / risk_manager.py / portfolio_manager.py
│
├── data/                          # 知识库数据（自动创建）
│   ├── docs/                      # 放置研报 PDF/TXT（可选，触发 RAG 索引）
│   └── chroma_db/                 # Chroma 向量库持久化存储
│
└── logs/                          # 日志目录（自动创建）
```

---

## 核心模块说明

### 1. 状态定义（`graph/state.py`）

所有节点共享 `TradingGraphState`（TypedDict），关键字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| `symbol` / `market_type` | str | 交易标的与市场类型 |
| `market_data` | Dict | data_node 填充的原始行情数据 |
| `fundamental_report` / `technical_report` / `sentiment_report` | Optional[Dict] | 三路并行分析师报告 |
| `rag_context` | str | RAG 检索到的宏观/研报知识 |
| `has_conflict` | bool | 分析师意见冲突标志（触发辩论） |
| `debate_outcome` | Optional[Dict] | DebateOutcome，含 bull/bear 完整对话历史 |
| `debate_rounds` | int | 已辩论轮次（≥ MAX_DEBATE_ROUNDS=2 时跳过） |
| `risk_decision` | Optional[Dict] | RiskDecision，含批准状态、仓位建议、止损止盈 |
| `risk_rejection_count` | int | 风控拒绝次数（≥ MAX_RISK_RETRIES=2 时强制放行） |
| `trade_order` | Optional[Dict] | 最终 TradeOrder，`simulated=True`（模拟撮合） |
| `tool_call_counts` | Dict[str, int] | Anti-Loop 计数器，各节点工具调用超 3 次强制降级 |
| `portfolio_positions` | Optional[List[Dict]] | 持仓体检输入（PortfolioPosition 列表） |
| `health_report` | Optional[Dict] | PortfolioHealthReport，持仓体检结果 |
| `messages` | List[BaseMessage] | LangGraph add_messages reducer，追加而非覆盖 |
| `execution_log` | List[str] | 自定义 _append_log reducer，并行安全日志合并 |
| `error_type` | Optional[str] | 细粒度错误分类：`data_error`/`llm_error`/`rate_limit`/`timeout` |

### 2. LangGraph 节点（`graph/nodes.py`）

所有节点均注入**大学生专属规则**（`_CAMPUS_RULES`），不可豁免：

| 节点 | 核心职责 | 关键规则 |
|------|----------|----------|
| `data_node` | 获取历史日线 + 计算技术指标 | 失败返回空 DataFrame，不阻断流程 |
| `fundamental_node` | PE/FCF/盈利质量 LLM 分析 | 置信度 < 60% → 强制 HOLD |
| `technical_node` | MACD/RSI/均线 LLM 分析 | Anti-Loop：工具调用 ≤ 3 次 |
| `sentiment_node` | 新闻/舆情 LLM 评分 | 禁止推荐高风险投机策略 |
| `rag_node` | Chroma+BM25+DDG 三路检索 | 补充宏观政策/研报背景 |
| `portfolio_node` | 综合四路报告，加权决策 | 综合置信度 < 60% → 强制 HOLD；禁止杠杆 |
| `debate_node` | 多空辩论（最多 2 轮） | 产出 DebateOutcome + bull/bear 历史 |
| `risk_node` | 大学生专属风控审批 | A股仓位≤15%，港/美≤10%，ATR%>8%拒绝 |
| `trade_executor` | 生成最终 TradeOrder | `simulated=True`，不接入任何交易所 |
| `health_node` | 持仓组合健康诊断 | 集中度/回撤/流动性三维评分，产出 PortfolioHealthReport |

### 3. 数据加载器（`utils/data_loader.py`）

```
DataLoader.get_historical_data(symbol, days)
    │
    ├─ 市场识别 → MarketClassifier.classify(symbol)
    │
    ├─ A_STOCK  → akshare.stock_zh_a_hist(adjust="qfq")
    ├─ HK_STOCK → akshare.stock_hk_hist(adjust="qfq") + 本地日期截断
    ├─ US_STOCK → yfinance.Ticker.history(auto_adjust=True).reset_index()
    └─ CRYPTO   → 直接抛出 ValueError（已禁止）

    └─ _standardize() → 统一列名映射（中/英双语）→ [timestamp, open, high, low, close, volume]

可靠性保障：
  - TTL 内存缓存（默认 5 分钟），相同请求不重复调用 API
  - 指数退避重试（最多 3 次，base_wait=1.5s），应对网络抖动
```

### 4. 混合 RAG 知识库（`tools/knowledge_base.py`）

```
Query
  ├─ BM25 稀疏检索（rank_bm25）        → 精准词匹配（股票代码/专有名词）
  ├─ Chroma 向量检索（DashScope embedding）→ 语义模糊匹配（同义词/概念相似）
  │    └─ EnsembleRetriever 50%+50% RRF 排名融合
  └─ DuckDuckGo 实时搜索               → 最新新闻/突发事件/实时财报

内置财商教育知识：
  - ETF 定投入门（沪深300/纳指/红利，策略与常见误区）
  - 价值投资基础（PE/PB/FCF 通俗讲解，大学生选股原则）
  - 识别金融诈骗（杀猪盘特征，正规平台判断，紧急处置）

扩充知识库：将研报 PDF/TXT 放入 data/docs/ 目录
```

### 5. 智能标的搜索（`utils/market_classifier.py`）

| 用户输入 | 自动转换 | 市场 |
|----------|----------|------|
| 茅台、贵州茅台 | `600519.SH` | A股 |
| 宁德时代、CATL | `300750.SZ` | A股 |
| 沪深300ETF | `510300.SH` | A股 |
| 腾讯、Tencent | `00700.HK` | 港股 |
| 苹果、Apple | `AAPL` | 美股 |
| 英伟达、NVIDIA | `NVDA` | 美股 |
| 拼多多 | `PDD` | 美股 |

无法匹配时直接使用原始输入（适用于已知标准代码的用户）。

---

## API 端点

FastAPI 后端（默认 `http://localhost:8000`）：

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/v1/analyze` | `POST` | SSE 流式分析（主端点） |
| `/api/v1/health-check` | `POST` | 持仓体检（JSON 请求/响应） |
| `/api/v1/market/indices` | `GET` | 8 路实时大盘指数（沪深港美，akshare） |
| `/api/v1/market/news` | `GET` | 财联社 7×24 快讯（`?limit=N`，默认 20 条） |
| `/api/v1/health` | `GET` | 服务健康检查 |
| `/api/v1/graph/mermaid` | `GET` | 返回图拓扑 Mermaid 字符串 |
| `/docs` | `GET` | Swagger 交互式 API 文档 |

### `/api/v1/analyze` SSE 事件格式

```json
{
  "event": "node_complete",
  "node": "fundamental_node",
  "message": "📈 基本面分析师完成",
  "data": {
    "recommendation": "BUY",
    "confidence": 0.78,
    "reasoning": "...",
    "key_factors": ["ROE 连续5年超25%", "..."],
    "price_target": 2000.0,
    "risk_factors": ["估值偏高"]
  },
  "timestamp": "2026-03-03T10:00:00Z",
  "seq": 5
}
```

`complete` 事件的 `data` 字段还包含：
- `trade_order`：最终 TradeOrder（含 action / quantity_pct / stop_loss / take_profit）
- `final_markdown_report`：Markdown 格式完整深度研报（六节：基本面→技术→情绪→风控→辩论→指令）
- `financial_chart_data`：近5年营收/净利润图表数据（`years / revenue / profit` 数组）

事件类型：`start` / `node_start` / `node_complete` / `conflict` / `debate` / `risk_check` / `risk_retry` / `trade_order` / `complete` / `error`

### `/api/v1/health-check` 请求示例

```json
{
  "positions": [
    { "symbol": "600519.SH", "quantity": 100, "avg_cost": 1800.0 },
    { "symbol": "AAPL",      "quantity": 10,  "avg_cost": 175.0 }
  ]
}
```

---

## 风控机制（大学生专属）

**仓位上限**（比通用版更保守）：

| 市场 | 最大仓位 | 建议止损 | 止损范围 | 高波动拒绝阈值 |
|------|----------|----------|----------|----------------|
| A股  | 15%      | 5%       | 0~50%    | ATR% > 8%      |
| 港股 | 10%      | 7%       | 0~50%    | ATR% > 8%      |
| 美股 | 10%      | 7%       | 0~50%    | ATR% > 8%      |

**不可豁免的拒绝条件**：
- 任何形式的杠杆/融资融券（Margin Trading）
- 任何期权投机（Options Speculation）
- 加密货币（已从系统全面移除）
- 综合置信度 < 60% 且方向为 BUY/SELL → 强制降仓至 ≤5% 或直接拒绝

---

## LLM 配置

主 LLM 为**阿里云百炼 Qwen**（国内直连，无需代理）：

```python
# config.py / .env
PRIMARY_LLM_PROVIDER = "dashscope"
QWEN_MODEL_NAME = "qwen3.5-plus"           # 推理模型（默认，可覆盖）
DASHSCOPE_EMBEDDING_MODEL = "text-embedding-v3"  # RAG 向量化
```

切换为 OpenAI 或 Anthropic：

```python
# 备选 A：OpenAI GPT
PRIMARY_LLM_PROVIDER = "openai"
OPENAI_MODEL = "gpt-4o"

# 备选 B：Anthropic Claude
PRIMARY_LLM_PROVIDER = "anthropic"
ANTHROPIC_MODEL = "claude-sonnet-4-6"
```

> **代理注意**：若使用系统代理（TUN 模式），请在 `.env` 中配置 `NO_PROXY=dashscope.aliyuncs.com,aliyuncs.com` 避免 DashScope 请求被拦截。

---

## 模块测试

```bash
# 完整环境快速测试（验证 LLM 连通 + 图构建）
python quick_start.py

# 市场分类 + 模糊匹配测试
python utils/market_classifier.py

# 多市场数据加载测试（A股/港股/美股各一例）
python utils/data_loader.py

# LLM 客户端连通测试
python utils/llm_client.py
```

---

## 扩展开发

### 扩充模糊匹配词典

编辑 `utils/market_classifier.py` 中的 `_FUZZY_NAME_MAP`：

```python
"拼多多": "PDD",
"蔚来":   "09866.HK",
"小鹏汽车": "09868.HK",
```

### 扩充研报知识库

将 PDF 或 TXT 研报放入 `data/docs/`，然后重建索引：

```python
from tools.knowledge_base import init_knowledge_base
init_knowledge_base(force_rebuild=True)
```

### 添加 LangGraph 节点

1. 在 `graph/nodes.py` 中实现新节点函数
2. 在 `graph/state.py` 中扩展 `TradingGraphState` 字段
3. 在 `graph/builder.py` 中注册节点并连接边

### 调整风控参数

编辑 `graph/nodes.py` 中 `_PROMPTS["risk"]` 或 `risk_node` 的大学生规则字符串，修改仓位上限、ATR 拒绝阈值等。

---

## 为什么不支持加密货币

1. **极高波动**：BTC 单日波动常超 10%，大学生本金有限，一次暴跌可能亏损数月生活费
2. **杠杆陷阱**：主流交易所提供 10x-100x 杠杆，是大学生血本无归的常见路径
3. **监管风险**：中国境内加密货币交易合规性存疑，法律保护缺失
4. **诈骗高发**："杀猪盘"最高发场景，大学生是主要受害群体

**如果已被"炒币"诱惑**，请拨打全国反诈热线 **96110**。

---

## 免责声明

**本系统仅用于学习、研究与财商教育目的，不构成任何投资建议。**

- 系统输出的 BUY/SELL/HOLD 仅供参考，不保证盈利
- `simulated=True` 标记确保所有指令仅指向本地模拟引擎，不接入真实交易所
- 历史数据回测结果不代表未来表现
- 请先在模拟账户中验证，再考虑小仓位实盘
- 如有疑问，请咨询持牌金融顾问

---

## 依赖说明

| 类别 | 主要库 |
|------|--------|
| 数据科学 | `pandas`, `numpy` |
| 市场数据 | `akshare`（A股/港股）, `yfinance`（美股） |
| 技术分析 | `pandas-ta` |
| LLM 框架 | `langgraph`, `langchain`, `langchain-core`, `langchain-community` |
| LLM 提供商 | `langchain-openai`（DashScope/OpenAI）, `langchain-anthropic`（备用）|
| 混合 RAG | `chromadb`, `pypdf`, `rank_bm25`, `duckduckgo-search` |
| 后端服务 | `fastapi`, `uvicorn[standard]`, `sse-starlette`, `httpx`, `python-multipart` |
| 前端 | `streamlit` |
| 工具库 | `python-dotenv`, `pydantic`, `tenacity`, `loguru`, `requests` |

> `ccxt`（加密货币库）已从 `requirements.txt` 移除。`faiss-cpu` 已被 `chromadb` 替代。

---

## TODO

- [ ] 支持更多技术指标（Ichimoku、Fibonacci 回撤位）
- [ ] 添加历史回测引擎（基于历史数据模拟交易记录）
- [ ] 财商教育题库（选择题测验大学生金融知识水平）
- [ ] 多语言支持（English version for overseas students）
- [ ] 移动端响应式适配（HTML 前端）
- [ ] LangGraph 持久化升级（MemorySaver → SqliteSaver，支持多并发）

---

## 许可证

MIT License

---

**如果这个项目对你有帮助，欢迎 Star！**
**如果你是大学生，记住：时间和学习才是你最大的资产。投资自己，胜过投资任何股票。**
