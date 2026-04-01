# CampusQuant — 校园财商智能分析平台

基于 LangGraph 的多 Agent AI 投资研究平台，面向中国大学生。覆盖 A 股、港股、美股，集成混合 RAG 和金融风控体系。

**核心设计理念**：大模型输出的概率性不确定性 vs 金融合规的零容忍 — 全部工程设计都在这两者之间寻找可运行的工程解。

**线上访问**：http://47.76.197.100

---

## 系统架构

```mermaid
flowchart TD
    START([START]) --> data_node["data_node\n行情数据获取\nOHLCV + 技术指标"]

    data_node --> fundamental_node["fundamental_node\n基本面分析师\n商业模式 + 护城河 + 估值\n+ RAG"]
    data_node --> technical_node["technical_node\n技术分析师\nMACD/RSI/BOLL + RAG"]
    data_node --> sentiment_node["sentiment_node\n舆情分析师\n新闻资讯 + RAG"]
    data_node --> rag_node["rag_node\n全局 RAG\n宏观政策/行业景气"]

    fundamental_node --> portfolio_node
    technical_node   --> portfolio_node
    sentiment_node   --> portfolio_node
    rag_node         --> portfolio_node

    portfolio_node["portfolio_node\n基金经理综合决策\n冲突检测 + 数学预加权"] -->|has_conflict=True| debate_node["debate_node\n多空辩论"]
    portfolio_node -->|无冲突| risk_node

    debate_node --> portfolio_node

    risk_node["risk_node\n四重硬风控\nATR阻断 + 仓位截断\n亏损反算 + 置信度惩罚"] -->|REJECTED| portfolio_node
    risk_node -->|APPROVED / CONDITIONAL| trade_executor["trade_executor\n生成模拟交易指令\nsimulated=True 恒成立"]

    trade_executor --> END([END])
```

**控制参数**：辩论循环 <=2 轮 | 风控重试 <=2 次 | 工具调用 <=3 次/节点

---

## 市场数据覆盖

### 实时指数（8 个）

| 指数 | 数据源 | 服务器 |
|------|--------|--------|
| 上证指数 | akshare (东财/新浪) | 内地 relay |
| 深证成指 | akshare (东财/新浪) | 内地 relay |
| 沪深300 | akshare (东财/新浪) | 内地 relay |
| 恒生指数 | yfinance (^HSI) | 香港直连 |
| 恒生科技 | yfinance (^HSTECH) | 香港直连 |
| 标普500 | yfinance (^GSPC) | 香港直连 |
| 纳斯达克 | yfinance (^IXIC) | 香港直连 |
| 道琼斯 | yfinance (^DJI) | 香港直连 |

### 行业板块（50 个）

数据源：同花顺 `stock_board_industry_summary_ths`，按涨跌幅排序 TOP50，含领涨股、上涨/下跌家数。

### 热门标的（24 只）

| 市场 | 数量 | 示例 |
|------|------|------|
| A 股 | 8 只 | 贵州茅台、五粮液、比亚迪、宁德时代... |
| 港股 | 8 只 | 腾讯、阿里巴巴、美团、京东、小米... |
| 美股 | 8 只 | 苹果、微软、英伟达、谷歌、特斯拉、AMD... |

### 新闻聚合（4 平台）

财联社 / 华尔街见闻 / 新浪财经 / 澎湃新闻，各 TOP3 实时热榜。

---

## 分析维度

### 基本面分析（fundamental_node）

每次分析必须覆盖 6 个维度：

1. **商业模式 & 收入驱动** — 公司靠什么赚钱？主营业务和收入结构
2. **护城河 & 竞争优势** — 品牌、技术壁垒、网络效应、规模效应
3. **催化剂** — 未来 1-2 个季度可能推动股价变动的事件
4. **同行对比** — 相对于同行业公司，估值偏高还是偏低
5. **情景分析** — 乐观/悲观两种情景
6. **投资论点** — 2-3 句话概括推荐/不推荐理由

**市场差异化权重**：

| 市场 | 基本面 | 技术面 | 情绪面 | 侧重 |
|------|--------|--------|--------|------|
| A 股 | 40% | 25% | 35% | 政策驱动 + 景气度 |
| 港股 | 55% | 20% | 25% | 价值投资，FCF + 分红 |
| 美股 | 50% | 25% | 25% | EPS + FCF 主导 |

### 技术面分析（technical_node）

MA5/20/60 趋势 + MACD 动量 + RSI14/BOLL 超买超卖 + 量比量价 + ATR 波动率。

### 情绪分析（sentiment_node）

资金热度 + 宏观政策面 + 板块轮动 + 极端情绪信号。

---

## 研报输出格式

论文式研报结构（非 Agent dump）：

```
投资建议（推荐/置信度/仓位/止损/止盈）
  投资论点
  商业模式 & 收入驱动
  护城河 & 竞争优势
  估值 & 同行对比（PE/PB/ROE）
  催化剂（未来 1-2 季度）
  核心风险
  情景分析（乐观/悲观）
  学生行动建议
  [可展开] 各 Agent 详细分析过程
```

---

## 四重硬风控

| 风控层 | 触发条件 | 执行方式 |
|--------|---------|---------|
| ATR 硬阻断 | ATR% > 8.0% | REJECTED，仓位归零 |
| ATR 减半 | ATR% > 5.0% | CONDITIONAL，仓位减半 |
| 仓位上限截断 | A 股 > 15% / 港美 > 10% | 截断到上限 |
| 单次亏损反算 | 亏损 > 3000 元 | 反算最大安全仓位 |

置信度惩罚：< 0.40 强制 HOLD | 0.40-0.55 线性缩仓 | >= 0.55 正常执行。

---

## 模拟交易

三市场独立账户（A 股 10 万 CNH / 港股 10 万 HKD / 美股 1 万 USD），支持：

- 买入：输入代码 + 数量，自动校验最小手数
- 部分卖出：25% / 50% / 75% / 100% 快捷比例按钮
- K 线图：日K/周K/月K，支持搜索自动补全
- 实时持仓：均价、现价、浮盈、一键卖出
- 成交记录：完整历史订单

---

## 混合 RAG 检索

BM25 关键词（50%）+ Chroma 语义向量（50%）RRF 排名融合 + DuckDuckGo 实时补充。

每个节点拥有独立 RAG 查询：

| 节点 | 查询 | 用途 |
|------|------|------|
| fundamental | `{symbol} 财务报表 基本面 盈利 机构评级` | 财务深度 |
| technical | `{symbol} 近期资金面 行业技术利好利空` | 资金面 |
| sentiment | `{symbol} 最新宏观政策 行业动态 突发新闻` | 时效性 |
| debate | `{symbol} 行业核心风险点 前景 护城河` | 裁判依据 |

---

## 双服务器部署架构

```
用户浏览器 --> http://47.76.197.100
    |
    v
+---------------------------------------------+
|  香港服务器 (2C/1G) - 47.76.197.100          |
|  Nginx -> FastAPI -> LangGraph Agent 调度    |
|  LLM (DashScope) + yfinance 全球指数/港美股  |
|  DuckDuckGo 搜索 + 前端静态页                |
+----------------------+-----------------------+
                       | HTTP (Bearer token)
                       v
+---------------------------------------------+
|  内地服务器 (2C/2G) - 47.108.191.110:8001    |
|  akshare A股数据 + 同花顺板块                |
|  BM25 RAG 检索 + MySQL 用户数据库            |
|  财联社/新浪/澎湃国内新闻源                  |
|  缓存持久化（重启后恢复上一交易日数据）       |
+---------------------------------------------+
```

---

## 快速启动

**环境要求**：Python 3.10+

```bash
pip install -r requirements.txt
# 在 .env 中填入 DASHSCOPE_API_KEY 等
uvicorn api.server:app --host 127.0.0.1 --port 8000
python -m http.server 3000   # 前端 http://localhost:3000
```

### 服务器部署

**香港服务器**（主站）：
```bash
cd /opt/CampusQuant-Agent && source .venv/bin/activate
pip install -r requirements-hk.txt
nohup .venv/bin/uvicorn api.server:app --host 127.0.0.1 --port 8000 > server.log 2>&1 &
```

**内地服务器**（数据中继）：
```bash
cd /opt/CampusQuant-Agent/inland_relay && source .venv/bin/activate
pip install -r requirements.txt
nohup .venv/bin/uvicorn server:app --host 0.0.0.0 --port 8001 > relay.log 2>&1 &
```

**内地服务器 GitHub 不通时**（用香港中转）：
```bash
# 香港服务器上
cd /opt/CampusQuant-Agent && git pull && tar czf /tmp/relay-update.tar.gz inland_relay/server.py
# 内地服务器上
scp root@47.76.197.100:/tmp/relay-update.tar.gz /tmp/ && cd /opt/CampusQuant-Agent && tar xzf /tmp/relay-update.tar.gz
```

---

## 项目结构

```
trading_agents_system/
├── graph/
│   ├── nodes.py          # LangGraph 节点 + _PROMPTS + 风控
│   ├── state.py          # TradingGraphState + Pydantic 模型
│   └── builder.py        # StateGraph DAG 装配
├── agents/               # Agent 类（部分已由 nodes.py 取代）
├── tools/
│   ├── market_data.py    # akshare / yfinance + 内地 relay
│   ├── knowledge_base.py # BM25 + Chroma + DuckDuckGo RAG
│   └── hot_news.py       # 多平台热榜聚合
├── api/
│   ├── server.py         # FastAPI SSE 流式后端
│   ├── mock_exchange.py  # 模拟撮合引擎
│   └── auth.py           # JWT 鉴权
├── inland_relay/
│   ├── server.py         # 内地数据中继服务（akshare + 同花顺 + RAG）
│   └── requirements.txt  # 内地服务器依赖
├── db/                   # SQLAlchemy 异步 ORM
├── utils/                # LLM 客户端、数据加载器
├── data/
│   ├── docs/             # 研报 PDF/TXT（RAG 源）
│   ├── chroma_db/        # Chroma 向量库
│   └── bm25_index.pkl    # BM25 索引
├── config.py             # 全局配置
├── requirements.txt      # 完整依赖
├── requirements-hk.txt   # 香港服务器精简依赖
└── scripts/build_kb.py   # 离线建库脚本
```

---

## SSE 事件类型

| 事件 | 触发时机 |
|------|---------|
| `start` | 分析请求受理 |
| `node_start` / `node_complete` | 节点开始/完成（含详细描述） |
| `conflict` | 基本面与技术面冲突 |
| `debate` | 辩论裁决完成 |
| `risk_check` / `risk_retry` | 风控审批/拒绝重试 |
| `trade_order` | 模拟交易指令生成 |
| `complete` | 全流程完成，含完整研报 + 财务图表 |
| `error` | 错误（含 error_type 归因） |

---

## 安全红线

- 无真实交易所 API（无 Binance、CCXT、IBKR）
- TradeOrder.simulated 恒为 True（代码层强制覆盖）
- 无加密货币业务逻辑（仅 A 股/港股/美股）
- 严禁杠杆（融资融券、期权投机一律拒绝）

---

## 技术栈

| 层 | 选型 |
|----|------|
| LLM | DashScope/Qwen（主）、OpenAI/Anthropic（备） |
| Agent 框架 | LangGraph（StateGraph + 条件边） |
| RAG | Chroma + rank_bm25 + DuckDuckGo |
| 市场数据 | akshare + 同花顺 + yfinance |
| 后端 | FastAPI + SSE |
| 前端 | 静态 HTML（Nginx 托管） |
| 数据库 | MySQL（asyncmy） |
| 部署 | 香港 + 内地双服务器，Nginx 反向代理 |
| 缓存 | 内存 + 磁盘持久化（非交易时段数据保留） |
