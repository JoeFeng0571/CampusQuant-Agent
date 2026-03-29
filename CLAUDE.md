# CampusQuant — Claude 工作指南

## 项目概述

基于 LangGraph 的多 Agent AI 投资研究平台（校园财商智能分析平台），面向中国大学生。
覆盖 A股、港股、美股，集成混合 RAG（Chroma + BM25）和金融风控体系。

**绝对禁止**：
- 接入任何真实交易所 API（Binance、CCXT、IBKR 等）
- 加入任何加密货币业务逻辑
- 将 `TradeOrder.simulated` 设为 `False`
- 所有交易执行必须走本地 mock matching engine（`api/mock_exchange.py`）

---

## 环境激活与运行

```bash
# 激活虚拟环境（PowerShell）
& .\.venv\Scripts\Activate.ps1

# 激活虚拟环境（bash/Git Bash）
source .venv/Scripts/activate

# 安装依赖
pip install -r requirements.txt
```

### 启动服务

```bash
# FastAPI 后端（SSE 流式接口，主入口）
uvicorn api.server:app --host 127.0.0.1 --port 8000

# 静态前端（HTML 页面）
python -m http.server 3000
# 浏览器打开 http://localhost:3000

# Streamlit 界面（备用）
streamlit run app.py
# 浏览器打开 http://localhost:8501

# 直接运行主程序（命令行测试）
python main.py
```

### 构建知识库（首次或更新 data/docs/ 后执行）

```bash
python scripts/build_kb.py
```

---

## 代码结构

```
trading_agents_system/
├── graph/               # LangGraph 核心 Agent 逻辑
│   ├── state.py         # TradingGraphState TypedDict + 所有 Pydantic 模型
│   ├── nodes.py         # 所有节点函数 + _PROMPTS 字典
│   └── builder.py       # StateGraph 组装 + build_health_graph()
├── agents/              # 各专项 Agent 类
│   ├── fundamental_agent.py
│   ├── technical_agent.py
│   ├── sentiment_agent.py
│   ├── risk_manager.py
│   ├── portfolio_manager.py
│   └── data_agent.py
├── api/                 # FastAPI 后端
│   ├── server.py        # SSE 流式接口 + 所有 REST 端点
│   ├── mock_exchange.py # 本地模拟撮合引擎
│   └── auth.py          # JWT 鉴权
├── tools/               # LangChain Tools
│   ├── market_data.py   # akshare / yfinance 数据获取（含 TTL 缓存 + 重试）
│   ├── knowledge_base.py# 混合 RAG（Chroma 稠密 + BM25 稀疏）
│   └── hot_news.py      # 财联社 7x24 热点新闻
├── utils/
│   ├── data_loader.py   # DataLoader._standardize() 统一列格式
│   ├── llm_client.py    # LLM 客户端（DashScope / OpenAI / Anthropic）
│   └── market_classifier.py
├── db/                  # SQLAlchemy 2.x 异步 ORM
│   ├── models.py
│   ├── crud.py
│   └── engine.py
├── data/
│   ├── docs/            # 研报 PDF（RAG 知识库原始文档）
│   ├── chroma_db/       # Chroma 持久化向量库
│   └── bm25_index.pkl   # BM25 稀疏索引（build_kb.py 生成）
├── tests/               # pytest 测试
│   └── test_extreme_cases.py
├── config.py            # 全局配置（API Keys、模型名、技术指标参数）
├── main.py              # 命令行入口
├── workflow.py          # 完整 workflow 封装
├── app.py               # Streamlit 入口
└── requirements.txt
```

---

## 核心架构

### LangGraph 执行拓扑

```
START
 └─ data_node
     ├─ fundamental_node  (并行)
     ├─ technical_node    (并行)
     ├─ sentiment_node    (并行)
     └─ rag_node          (并行)
         └─ portfolio_node          ← 有条件循环
             ├─ [冲突] debate_node  ← 多空辩论（≤ 2 轮）
             │   └─ portfolio_node
             └─ [无冲突] risk_node  ← 风控审核（重试 ≤ 2 次）
                 ├─ [拒绝] portfolio_node
                 └─ [通过] trade_executor → END

持仓体检独立分支: START → health_node → END
```

### Pydantic 模型（graph/state.py）

| 模型 | 用途 |
|------|------|
| `AnalystReport` | fundamental / technical / sentiment 节点输出 |
| `RiskDecision` | risk_node 输出 |
| `TradeOrder` | trade_executor 输出（`simulated=True` 恒为真） |
| `DebateOutcome` | debate_node 输出（含 bull_history / bear_history） |
| `PortfolioPosition` | 单个持仓，持仓体检入参 |
| `PortfolioHealthReport` | health_node 输出 |

### 防死循环机制

每个节点调用工具前必须通过 `_check_tool_limit()`：
- State 中 `tool_call_counts` dict 跟踪每节点调用次数
- 超过 `MAX_TOOL_CALLS=3` 后抛出 `ToolLimitExceeded`，触发降级路径

---

## LLM 配置（config.py）

- **主 LLM**：DashScope/Qwen（`DASHSCOPE_API_KEY`）
- **备用**：OpenAI（`OPENAI_API_KEY`）、Anthropic（`ANTHROPIC_API_KEY`）
- 切换方式：修改 `Config.PRIMARY_LLM_PROVIDER = "dashscope" | "openai" | "anthropic"`

---

## 主要 API 端点（api/server.py）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/analyze` | 触发股票分析，SSE 流式返回 |
| POST | `/api/v1/health-check` | 持仓体检 |
| GET | `/api/v1/market/indices` | 8 个实时指数（akshare） |
| GET | `/api/v1/market/news?limit=N` | 财联社 7x24 新闻 |

### SSE 事件类型

`start` | `node_start` | `node_complete` | `conflict` | `debate` | `risk_check` | `risk_retry` | `trade_order` | `complete` | `error`

---

## 数据源注意事项

### akshare 列顺序陷阱

- `stock_zh_index_spot_em`：col[1]=代码, col[3]=最新价, col[4]=涨跌幅%, col[5]=涨跌额；399xxx 深证指数**不在**该接口
- `index_global_spot_em`：col[4]=涨跌额(pts), col[5]=涨跌幅%（col4/col5 顺序与 A股**相反**）
- `stock_financial_abstract_ths`：升序排列（最旧在前），取财务数据用 `.tail(5)`；数值为带"亿"字符串如 `"862.28亿"`

### 市场数据流

```
akshare → A股/港股日线
yfinance → 美股日线
       ↓
DataLoader._standardize()
       ↓
[timestamp, open, high, low, close, volume]
```

TTL 缓存 300s，指数退避重试 3 次（1.5× base）。

---

## 测试

```bash
# 运行所有测试
pytest

# 运行极端情况测试
pytest tests/test_extreme_cases.py -v

# 运行集成测试
python test_integration.py
```

---

## 前端页面

| 文件 | 页面 |
|------|------|
| `index.html` | 首页（Landing） |
| `trade.html` | 模拟演练（SSE 动画） |
| `platforms.html` | 持仓体检 |
| `market.html` | 市场快讯 |
| `community.html` | 投教社区 |
| `team.html` | 关于我们 |
| `home.html` | 学习中心 Dashboard |
| `resources.html` | 学习资源库 |

---

## 常见问题

**Q: akshare 拉取失败怎么办？**
A: `tools/market_data.py` 已有指数退避重试，连续失败说明网络或 akshare 接口变更，检查 akshare 版本 `pip show akshare`。

**Q: Chroma 向量库为空？**
A: 先运行 `python scripts/build_kb.py` 建库。首次构建需要 DashScope Embedding API Key。

**Q: bcrypt 兼容性报错？**
A: `requirements.txt` 已固定 `bcrypt==4.0.1`，升级会导致 passlib 兼容性问题，不要更新此版本。
