# CampusQuant-Agent · 校园财商智能分析平台

> 专为**在校大学生**设计的多智能体量化分析系统——本金安全第一，财商教育优先。

基于 **LLM + LangGraph** 的多智能体协作分析平台，覆盖 **A股、港股、美股** 三大市场。内置 AI 财商助手"财财学长"，帮助大学生建立正确的投资认知，识别金融诈骗，远离高风险杠杆产品。

> **产品转型说明**：本项目已从"通用量化交易系统"转型为"校园财商智能助手"。
> 加密货币（Crypto）相关功能已**全面移除**，理由：高波动、高杠杆、诈骗高发，不适合本金有限的大学生。

---

## 产品特点

- **大学生优先风控**: 仓位上限更保守（A股≤15%，港股/美股≤10%），禁止任何形式的杠杆交易
- **智能标的搜索**: 输入"茅台""英伟达""腾讯"等中文名，自动映射为标准代码
- **多智能体协作**: 6个专业智能体并行分析，支持多空辩论机制与风控重试循环
- **LLM 驱动决策**: 通义千问 Qwen（阿里云百炼 DashScope）进行 Chain-of-Thought 推理，低置信度强制 HOLD
- **LangGraph 状态机**: StateGraph 有向图工作流，并行节点 + 条件路由 + 循环保护
- **混合 RAG 知识库**: Chroma 向量检索 + BM25 关键词检索 + DuckDuckGo 实时联网搜索
- **财商教育知识库**: 内置 ETF定投入门、价值投资基础、识别金融杀猪盘三大知识模块
- **AI 财商助手**: 侧边栏"财财学长"聊天机器人，用食堂打饭解释市盈率，识别并阻止高风险行为
- **多界面支持**: Streamlit Web UI（含 AI 助手）、CLI 命令行、RESTful API（FastAPI + SSE）

---

## 系统架构

### LangGraph 状态机工作流

```
START → data_node
              │
   ┌──────────┼──────────┬──────────┐
   ▼          ▼          ▼          ▼
fund_node  tech_node  sent_node  rag_node   ← 四节点并行
   └──────────┼──────────┴──────────┘
              ▼
        portfolio_node  ← 综合决策（大学生专属规则注入）
              │
     ┌────────┴────────┐
     │ 有分析冲突?      │
     ▼YES              ▼NO
 debate_node       risk_node  ← 大学生专属严格风控
     │                 │
     └──→ portfolio_node  ──→ risk_node
                       │
              ┌────────┴────────┐
              │ 风控批准?        │
              ▼YES              ▼NO
        trade_executor   portfolio_node（重试≤2次）
              │
             END
```

### 整体架构

```
┌─────────────────────────────────────────────────────────────────┐
│                        用户界面层                               │
├─────────────────────────────────────────────────────────────────┤
│  app.py (Streamlit)                api/server.py (FastAPI SSE)  │
│  ├─ 智能搜索框（模糊匹配）         POST /api/v1/analyze          │
│  └─ AI财商助手"财财学长"（侧边栏） 实时 SSE 事件流              │
│      独立 session_state，直接 LLM 调用，不经 LangGraph          │
└────────────────────────────┬────────────────────────────────────┘
                             │
┌────────────────────────────▼────────────────────────────────────┐
│                      LangGraph 编排层                           │
├─────────────────────────────────────────────────────────────────┤
│  graph/builder.py  StateGraph 图结构                            │
│  graph/nodes.py    节点实现（含大学生风控规则）                  │
│  graph/state.py    TypedDict 状态 + Pydantic 结构化输出         │
└────────────────────────────┬────────────────────────────────────┘
                             │
        ┌────────────────────┼──────────────────────┐
        │                    │                      │
┌───────▼────┐   ┌───────────▼──────────┐   ┌──────▼──────┐
│  数据层    │   │      分析引擎层       │   │  LLM 引擎   │
├────────────┤   ├──────────────────────┤   ├─────────────┤
│DataLoader  │   │ FundamentalAgent     │   │ LLMClient   │
│ A股 Akshare│   │ TechnicalAgent       │   │ DashScope/  │
│ 港股 Akshare│  │ SentimentAgent       │   │ Qwen（主）  │
│ 美股 yfinance  │ RiskManager（大学生版）│   │             │
└────────────┘   │ PortfolioManager     │   │ CoT 推理    │
                 │ tools/knowledge_base │   │ 结构化输出  │
                 │ （混合 RAG）         │   └─────────────┘
                 └──────────────────────┘
```

### 市场差异化分析权重

| 市场 | 基本面 | 技术面 | 舆情 | 风控 | 分析重点 |
|------|--------|--------|------|------|----------|
| A股  | 20%    | 35%    | 35%  | 10%  | 政策催化 + 行业动量 + EPS 增长 |
| 港股 | 45%    | 20%    | 25%  | 10%  | 价值投资 + 安全边际 + FCF 质量 |
| 美股 | 35%    | 30%    | 25%  | 10%  | 估值效率 + FCF 收益率 + 盈利超预期 |

> 加密货币已从系统全面移除，不再支持。

---

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

混合 RAG 模块新增依赖（如未自动安装）：

```bash
pip install chromadb pypdf rank_bm25 duckduckgo-search
```

### 2. 配置 API Keys

```bash
cp .env.example .env
```

编辑 `.env`：

```env
# 主 LLM：阿里云百炼（国内直连，无需代理）
DASHSCOPE_API_KEY=sk-ce03276f462f4cc5b93458d2642b56d3

# 备用 LLM（按需启用，取消注释即可）
# OPENAI_API_KEY=sk-your-openai-key
# ANTHROPIC_API_KEY=sk-ant-your-anthropic-key

# 代理（访问 OpenAI / Anthropic 等境外服务时需要，DashScope 无需）
# HTTP_PROXY=http://127.0.0.1:7890
# HTTPS_PROXY=http://127.0.0.1:7890
```

> Binance API 已不再需要（加密货币功能已移除）。

### 3. 运行方式

#### 方式 A: Streamlit Web UI（推荐）

```bash
# 终端 1：启动 FastAPI 后端
uvicorn api.server:app --host 127.0.0.1 --port 8000

# 终端 2：启动 Streamlit 前端
streamlit run app.py
```

浏览器访问 `http://localhost:8501`。

**界面功能**：
- 左侧搜索框：输入"英伟达"自动转为 `NVDA`，输入"茅台"自动转为 `600519.SH`
- 左侧快速示例：一键选择贵州茅台 / 腾讯 / 苹果 / 英伟达 / 宁德时代 / 沪深300ETF
- 左侧底部：**AI 财商助手"财财学长"**，独立对话框，随时可问投资基础知识

#### 方式 B: 命令行（CLI）

```bash
python workflow.py
```

选择模式：
- **模式 1**: 单标的分析（如 `AAPL`、`600519.SH`、`00700.HK`）
- **模式 2**: 批量分析配置文件中的所有标的
- **模式 3**: 自定义批量分析

#### 方式 C: 快速测试

```bash
python quick_start.py
```

#### 方式 D: REST API

```bash
uvicorn api.server:app --host 0.0.0.0 --port 8000
```

详见 [API_DOCS.md](API_DOCS.md)。

---

## 项目结构

```
trading_agents_system/
├── config.py                      # 全局配置（API Keys、交易标的、参数）
├── requirements.txt               # 依赖库
├── workflow.py                    # CLI 主程序入口
├── app.py                         # Streamlit Web UI（含智能搜索 + AI财商助手）
├── quick_start.py                 # 快速测试脚本
├── .env.example                   # 环境变量模板
├── README.md                      # 本文档
├── API_DOCS.md                    # REST API 文档
│
├── agents/                        # 原始智能体模块（已被 graph/ 节点取代）
│   ├── base_agent.py
│   ├── data_agent.py
│   ├── fundamental_agent.py
│   ├── sentiment_agent.py
│   ├── technical_agent.py
│   ├── risk_manager.py
│   └── portfolio_manager.py
│
├── graph/                         # LangGraph 状态机（主执行路径）
│   ├── state.py                  # TypedDict 状态 + Pydantic 模型
│   ├── builder.py                # StateGraph 图结构组装
│   └── nodes.py                  # 节点实现（含大学生专属风控规则）
│
├── tools/                         # 外部工具
│   ├── market_data.py            # 市场数据工具函数
│   └── knowledge_base.py         # 混合 RAG（Chroma + BM25 + DuckDuckGo）
│
├── utils/                         # 工具模块
│   ├── data_loader.py            # 多市场数据加载器（A股/港股/美股）
│   ├── llm_client.py             # LLM 统一接口
│   └── market_classifier.py      # 市场分类 + 模糊名称匹配
│
├── api/                           # FastAPI 后端
│   └── server.py                 # SSE 实时流式接口（v2.0）
│
├── data/                          # 知识库数据（自动创建）
│   ├── docs/                     # 放置研报 PDF/TXT（可选）
│   └── chroma_db/                # Chroma 向量库持久化存储
│
└── logs/                          # 日志目录（自动创建）
    ├── trading_system_*.log
    └── decisions_*.log
```

---

## 核心模块说明

### 1. 智能标的搜索（`utils/market_classifier.py`）

新增 `fuzzy_match()` 模糊匹配方法，覆盖 60+ 主流标的的中英文名称映射：

| 用户输入 | 自动转换 | 市场 |
|----------|----------|------|
| 茅台、贵州茅台 | `600519.SH` | A股 |
| 宁德时代、CATL | `300750.SZ` | A股 |
| 沪深300ETF、HS300 | `510300.SH` | A股 |
| 腾讯、Tencent | `00700.HK` | 港股 |
| 苹果、Apple | `AAPL` | 美股 |
| 英伟达、NVIDIA | `NVDA` | 美股 |

无法匹配时直接使用原始输入（适用于已知标准代码的用户）。

### 2. LangGraph 节点（`graph/nodes.py`）

**大学生专属规则（所有节点注入，不可豁免）**：

| 节点 | 规则摘要 |
|------|----------|
| `fundamental_node` | 本金安全优先；置信度<60%→HOLD；推荐 ETF 而非个股投机 |
| `portfolio_node` | 综合置信度<60%强制输出 HOLD；禁止推荐杠杆策略；持仓周期建议≥3个月 |
| `risk_node` | 仓位上限：A股15%，港股/美股10%；ATR%>8%直接拒绝；禁止杠杆/期权/加密货币 |

### 3. 混合 RAG 知识库（`tools/knowledge_base.py`）

**双路本地检索 + 实时联网**：

```
Query
  ├─ BM25 稀疏检索（rank_bm25）    → 精准词匹配（股票代码/专有名词）
  ├─ Chroma 向量检索（DashScope text-embedding-v3） → 语义模糊匹配（同义词/概念）
  │    └─ EnsembleRetriever（各50%，RRF 排名融合）
  └─ DuckDuckGo 实时搜索           → 最新新闻/突发事件/实时财报
```

**内置财商教育知识**：
- ETF 定投入门（沪深300/纳指/红利 ETF，定投策略，常见误区）
- 价值投资基础（PE/PB/FCF 通俗解释，大学生选股原则）
- 识别金融杀猪盘（典型特征，正规平台判断，紧急处置步骤）

### 4. AI 财商助手"财财学长"（`app.py` 侧边栏）

独立于 LangGraph 主流程，使用同步 LLM 调用 + 独立 `session_state` 维护对话历史：

```python
# 不经过 LangGraph，直接调用 LLM
response = llm.invoke([
    SystemMessage(content=ADVISOR_SYSTEM_PROMPT),
    *chat_history_messages,
])
```

**人设特点**：
- 风格：靠谱学长学姐，年轻接地气，偶用括号感叹
- 打比方：市盈率 = 食堂奶茶店回本年数；降息 = 存款利息变少，大家去买股票
- 强烈劝退：炒虚拟币 / 加杠杆 / 借网贷炒股 / 满仓操作
- 推荐：定投宽基 ETF，长期持有，时间复利

### 5. 风控机制（大学生专属）

**仓位上限（比通用版更保守）**：

| 市场 | 最大仓位 | 止损线 | 高波动拒绝阈值 |
|------|----------|--------|----------------|
| A股  | 15%      | 5%     | ATR% > 8%      |
| 港股 | 10%      | 7%     | ATR% > 8%      |
| 美股 | 10%      | 7%     | ATR% > 8%      |

**不可豁免的拒绝条件**：
- 任何形式的杠杆/融资融券（Margin Trading）
- 任何期权投机（Options Trading）
- 加密货币（已从系统全面移除）
- 综合置信度 < 0.60 且建议方向为 BUY/SELL → 强制压仓至 ≤5% 或直接拒绝

---

## 使用示例

### Web UI 智能搜索

```
用户输入: "英伟达"
系统提示: 🔎 自动识别 英伟达 → NVDA
点击「开始分析」→ LangGraph 分析 NVDA（美股成长价值策略）
```

### AI 财商助手对话示例

```
用户: 市盈率是什么？
财财学长: 市盈率（PE）= 你花多少钱买公司每年1元利润的权益。
         比如一家奶茶店每年净赚1万，你花20万买下来，
         PE就是20——意味着不考虑增长，20年才能回本。
         PE越低通常越便宜，但别只看这一个数，还要看增长速度哦～

用户: 我想把所有零花钱全部梭哈英伟达
财财学长: 等等等等！（这很重要！）梭哈是赌场策略，不是投资策略。
         就算是英伟达这样的好公司，股价也可以从高点跌50%+。
         大学生的本金有限，一次满仓输光，可能影响你好几年的生活质量。
         建议：最多拿出可投资资金的10%买单只股票，其余先定投沪深300ETF。
```

### CLI 分析示例

```bash
python workflow.py
# 选择模式 1，输入: 00700.HK
```

输出示例：

```
════════════════════════════════════════════════════════════════
 00700.HK 交易决策报告（大学生专属风控版）
════════════════════════════════════════════════════════════════

【最终决策】 HOLD
【置信度】   58.2%（< 60% 阈值，自动降级为观望）
【风控审批】 CONDITIONAL

【决策依据】
综合置信度低于60%，根据大学生用户专属规则，建议观望等待更明确信号。
技术面存在分歧，基本面向好但短期存在宏观压力，持仓风险高于预期。

【风控建议】
  最大仓位: 5%（低置信度限制）
  止损设置: 必须设置，建议 7%
  持仓建议: 等待季报确认基本面趋势后再做决策
```

---

## 依赖说明

| 类别 | 库 |
|------|----|
| 数据科学 | pandas, numpy |
| 市场数据 | akshare（A/港股）, yfinance（美股） |
| 技术分析 | pandas-ta |
| LLM 框架 | langgraph, langchain, langchain-core, langchain-community |
| LLM 提供商 | langchain-openai（DashScope/OpenAI 共用）, langchain-anthropic（备用）|
| 混合 RAG | chromadb（向量库）, pypdf（PDF加载）, rank_bm25（关键词检索）, duckduckgo-search（联网搜索）|
| 后端服务 | fastapi, uvicorn, sse-starlette, httpx |
| 前端 | streamlit |
| 工具库 | python-dotenv, pydantic, tenacity, loguru, requests |

> 旧版 `faiss-cpu` 已被 `chromadb` 替代，可保留作备选。
> `ccxt`（加密货币数据库）已从主流程移除，requirements.txt 中已注释。

---

## 扩展开发

### 扩充模糊匹配词典

编辑 `utils/market_classifier.py` 中的 `_FUZZY_NAME_MAP` 字典，添加新的名称→代码映射：

```python
# 示例：添加新标的
"拼多多": "PDD",
"蔚来":   "09866.HK",
```

### 添加财商教育知识

将研报 PDF 或 TXT 文件放入 `data/docs/` 目录，然后重建知识库：

```python
from tools.knowledge_base import init_knowledge_base
init_knowledge_base(force_rebuild=True)
```

### 调整大学生风控参数

编辑 `graph/nodes.py` 中 `risk_node` 的 `system_prompt`，修改仓位上限、ATR 拒绝阈值等参数。

### 切换 LLM 模型

修改 `config.py`：

```python
# 默认（推荐）：阿里云百炼 Qwen，国内直连
PRIMARY_LLM_PROVIDER = "dashscope"
DASHSCOPE_MODEL = "qwen-plus"

# 备选 A：OpenAI GPT
# PRIMARY_LLM_PROVIDER = "openai"
# OPENAI_MODEL = "gpt-4-turbo-preview"

# 备选 B：Anthropic Claude
# PRIMARY_LLM_PROVIDER = "anthropic"
# ANTHROPIC_MODEL = "claude-3-5-sonnet-20241022"
```

### 添加 LangGraph 节点

在 `graph/nodes.py` 中实现新节点函数，在 `graph/builder.py` 中注册，在 `graph/state.py` 中扩展状态字段。

---

## 测试各模块

```bash
# 快速测试整体环境
python quick_start.py

# 测试模糊匹配（验证中文名称转换）
python utils/market_classifier.py

# 测试数据加载器
python utils/data_loader.py

# 测试 LLM 客户端
python utils/llm_client.py
```

---

## 为什么不支持加密货币

本项目明确拒绝分析任何加密货币（Bitcoin / 以太坊等），原因：

1. **极高波动性**：BTC 单日波动常超 10%，大学生本金有限，一次暴跌可能亏损数月生活费
2. **杠杆陷阱**：主流交易所提供 10x-100x 杠杆，是大学生血本无归的常见原因
3. **监管风险**：中国境内加密货币交易合规性存疑，法律保护缺失
4. **诈骗高发**：加密货币是"杀猪盘"最高发场景，大学生是主要受害群体

**如果你已经被"炒币"诱惑**，请拨打全国反诈热线 **96110**。

---

## 免责声明

**本系统仅用于学习、研究与财商教育目的，不构成任何投资建议。**

- 系统输出的 BUY/SELL/HOLD 建议仅供参考，不保证盈利
- 历史数据回测结果不代表未来表现
- 股票投资存在本金亏损风险，请量力而行
- 建议先在模拟账户中验证策略，再考虑小仓位实盘
- 如有疑问，请咨询持牌金融顾问

---

## TODO

- [ ] 接入真实新闻 API（NewsAPI、财联社）
- [ ] 支持更多技术指标（Ichimoku、Fibonacci）
- [ ] 添加回测引擎（基于历史数据模拟）
- [ ] 支持实盘对接（富途牛牛、老虎证券 API）
- [ ] 财商教育题库（选择题测验大学生金融知识）
- [ ] 多语言支持（English version for overseas students）

---

## 许可证

MIT License

---

**如果这个项目对你有帮助，欢迎给一个 Star！**
**如果你是大学生，记住：时间和知识才是你最大的资产。**
