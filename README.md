# CampusQuant-Agent

这是一个面向大学生投资教育场景的多智能体量化分析项目。仓库不是标准的“单一前后端工程”，而是三套链路混在一起：

- 当前主线：静态 HTML 页面 + `api/server.py` + `graph/*`

- 第二入口：`app.py` Streamlit 前端 + 同一套 FastAPI 后端

- 遗留链路：`workflow.py + agents/*` 的旧版 CLI 编排，以及 `main.py`、`trade.py` 这类早期示例服务

这份 README 只按“当前代码真实情况”写，不按理想架构写，重点解释前后端调用逻辑、LangGraph 执行流程、数据库读写路径，以及仓库里哪些文件是主线、哪些只是遗留或辅助。

---

## 1. 当前推荐运行方式

如果你要跑现在最完整的版本，建议这样启动：

1. 后端：

```bash
uvicorn api.server:app --host 127.0.0.1 --port 8000 --reload
```

2. 静态页面：

```bash
python -m http.server 3000
```

3. 浏览器访问：

```text
http://localhost:3000/dashboard.html
```

注意两点：

- `api/server.py` 的根路径会重定向到 `/dashboard.html`，但它没有挂载静态资源目录，所以单靠 `uvicorn` 不能直接把这些 HTML 页面服务出来。

- HTML 页面必须单独放在静态服务器下，或者由 Nginx 之类的 Web Server 托管。

---

## 2. 仓库应该怎么分层理解

### 主后端

- `api/server.py`

- `api/auth.py`

- `api/mock_exchange.py`

### 多智能体编排

- `graph/state.py`

- `graph/builder.py`

- `graph/nodes.py`

### 数据与工具

- `tools/market_data.py`

- `tools/knowledge_base.py`

- `tools/hot_news.py`

- `utils/market_classifier.py`

- `utils/data_loader.py`

- `utils/llm_client.py`

### 持久化

- `db/engine.py`

- `db/models.py`

- `db/crud.py`

### 静态前端页面

- `dashboard.html`

- `analysis.html`

- `trade.html`

- `market.html`

- `platforms.html`

- `community.html`

- `auth.html`

- `home.html`

- `resources.html`

- `team.html`

- `index.html`

### 旧版或辅助入口

- `app.py`

- `workflow.py`

- `agents/*`

- `main.py`

- `trade.py`

- `quick_start.py`

- `eval_pipeline.py`

- `eval_rag.py`

- `test_integration.py`

---

## 3. 先记住三条“产品线”

### 主线 A：静态 HTML + FastAPI

这是当前最重要的链路。

- 前端页面都在根目录 `*.html`

- 页面统一通过 `fetch()` 调 `http://127.0.0.1:8000/api/v1/*`

- 个股分析走 `/api/v1/analyze`

- `/api/v1/analyze` 会进入 `graph/*`

- `graph/nodes.py` 再调用行情工具、RAG 工具、LLM 和风控逻辑

- 结果由后端包装成 SSE 推回页面

### 主线 B：Streamlit

`app.py` 是另一套前端。

- 也会调用 `/api/v1/analyze`

- 也会消费 SSE

- 但它的“财商学长”聊天不是调 `/api/v1/chat`，而是在 `app.py` 里直接构造 LLM 请求

### 旧链路：CLI + agents

`workflow.py` 依赖 `agents/*`。

- 不走 LangGraph

- 不走 SSE

- 更像旧版实验实现，不是当前网页主链

### 需要明确视为遗留示例的文件

- `main.py`：早期注册登录示例，直接连远程 MySQL，不属于当前 JWT + SQLite 主架构

- `trade.py`：早期交易示例，也直接连远程 MySQL，不属于当前主架构

---

## 4. 前端页面与接口映射

| 页面 | 页面职责 | 实际调用接口 |
|---|---|---|
| `auth.html` | 登录/注册 | `/api/v1/auth/login`、`/api/v1/auth/register` |
| `dashboard.html` | 欢迎页、账户摘要、热榜、聊天 | `/api/v1/trade/account`、`/api/v1/market/hotnews`、`/api/v1/chat/mentor` |
| `analysis.html` | 个股分析主页面 | `/api/v1/market/search`、`/api/v1/analyze` |
| `trade.html` | 模拟交易页面 | `/api/v1/market/search`、`/api/v1/market/spot`、`/api/v1/trade/order`、`/api/v1/trade/account`、`/api/v1/trade/orders`、`/api/v1/market/kline` |
| `market.html` | 行情、指数、板块、热榜、K 线 | `/api/v1/market/quotes`、`/api/v1/market/indices`、`/api/v1/market/sectors`、`/api/v1/market/hotnews`、`/api/v1/market/kline` |
| `platforms.html` | 持仓体检 | `/api/v1/health-check` |
| `community.html` | 社区列表、点赞、发帖 | `/api/v1/community/posts`、`/api/v1/community/posts/{id}/like`、`/api/v1/community/posts` |
| `home.html` | 辅助首页/持仓摘要 | `/api/v1/portfolio/summary` |
| `resources.html` | 静态资源页 | 无 |
| `team.html` | 团队介绍页 | 无 |
| `index.html` | 跳转页 | 无，直接跳到 `dashboard.html` |

---

## 5. 登录态怎么在前端里传

所有 HTML 页面都靠 `localStorage` 共享登录态，没有统一前端状态管理。

使用的 key 是：

- `cq_token`

- `cq_username`

- `cq_user_id`

流程是：

1. `auth.html` 登录或注册成功后，把 token 写进 `localStorage`

2. 其他页面读取这些 key

3. 需要鉴权时，在 `fetch()` 请求头里加 `Authorization: Bearer <token>`

4. 退出登录时删除这三个 key

---

## 6. 个股分析主链

这一条链是整个项目最核心的链路：

`analysis.html -> /api/v1/analyze -> _stream_graph_events() -> LangGraph -> SSE -> analysis.html`

### 6.1 前端做什么

`analysis.html` 的主要流程：

1. 用户输入股票名、拼音或代码

2. 页面先调用 `/api/v1/market/search` 做联想搜索

3. 用户点击“开始分析”后，前端 `POST /api/v1/analyze`

4. 请求头声明 `Accept: text/event-stream`

5. 前端不用 `EventSource`，而是用 `fetch + ReadableStream` 手动解析 SSE

6. 收到 `node_start`、`node_complete`、`debate`、`risk_check`、`trade_order`、`complete` 等事件后，逐步更新页面

### 6.2 后端入口怎么接

`api/server.py` 里的 `/api/v1/analyze`：

1. 对用户输入做 `MarketClassifier.fuzzy_match()`

2. 生成 `thread_id`

3. 返回 `StreamingResponse`

4. 真正的内容由 `_stream_graph_events(symbol, thread_id)` 产生

### 6.3 `_stream_graph_events()` 做什么

这个函数是“LangGraph 事件翻译层”。

它会：

1. 用 `graph.builder.make_initial_state(symbol)` 创建初始状态

2. 用 `_compiled_graph.astream_events()` 运行图

3. 监听图节点开始和结束事件

4. 根据节点名，把图状态翻译成前端能消费的 SSE 事件

5. 最后额外补发一个 `complete` 事件，里面带最终交易指令、Markdown 研报和图表数据

### 6.4 LangGraph 拓扑

主图定义在 `graph/builder.py`，结构是：

```text
START
 -> data_node
 -> fundamental_node
 -> technical_node
 -> sentiment_node
 -> rag_node
 -> portfolio_node
 -> debate_node 或 risk_node
 -> trade_executor
 -> END
```

更准确的执行顺序是：

- `data_node` 先执行

- 然后并行分叉到 `fundamental_node`、`technical_node`、`sentiment_node`、`rag_node`

- 四路汇总到 `portfolio_node`

- `portfolio_node` 判断是否冲突，决定走 `debate_node` 还是 `risk_node`

- `risk_node` 判断是回到 `portfolio_node` 修订，还是进入 `trade_executor`

### 6.5 每个节点到底负责什么

| 节点 | 作用 | 主要调用 | 主要输出 |
|---|---|---|---|
| `data_node` | 拉基础行情与技术指标 | `get_market_data`、`calculate_technical_indicators` | `market_data`、`data_fetch_failed` |
| `rag_node` | 提供外部上下文 | `search_knowledge_base` | `rag_context` |
| `fundamental_node` | 基本面研判 | `get_fundamental_data`、`get_deep_financial_data`、LLM | `fundamental_report`、`fundamental_data` |
| `technical_node` | 技术面研判 | LLM + 技术指标结果 | `technical_report` |
| `sentiment_node` | 舆情与新闻研判 | `get_stock_news`、LLM | `sentiment_report`、`news_data` |
| `portfolio_node` | 汇总三路分析师观点 | LLM | 综合决策、`has_conflict` |
| `debate_node` | 冲突时多空辩论 | LLM | `debate_outcome`、`debate_rounds` |
| `risk_node` | 大学生风控审批 | 风控规则 + LLM | `risk_decision`、`risk_rejection_count` |
| `trade_executor` | 生成最终交易指令 | LLM 结构化输出 | `trade_order` |

### 6.6 为什么前端最后还能拿到图表

`complete` 事件里除了 `trade_order` 以外，还会带：

- `final_markdown_report`

- `financial_chart_data`

所以 `analysis.html` 在分析结束后还能继续渲染：

- Markdown 深度研报

- 财务柱状图

- 主营构成图

- 业绩趋势图

### 6.7 这条链的兜底逻辑

- `tool_call_counts` 限制工具调用次数，防止节点死循环

- `data_fetch_failed=True` 时，下游节点会早退，不再继续拿坏数据喂 LLM

- `debate_node`、`trade_executor` 都有结构化输出兜底

- 即使图中途异常，后端也会尽量补发 `complete`，让前端展示部分结果

---

## 7. 持仓体检链路

这一条是独立图，不走主分析图：

`platforms.html -> /api/v1/health-check -> build_health_graph() -> health_node`

### 前端

`platforms.html`：

1. 用户输入多条持仓

2. 点击开始体检

3. `POST /api/v1/health-check`

4. 收到 JSON 后渲染评分、集中度、回撤、流动性和建议

### 后端

`/api/v1/health-check`：

1. 把前端输入转成 `PortfolioPosition`

2. 调 `build_health_graph()`

3. 这张图只有 `START -> health_node -> END`

4. `health_node` 会补当前价格、算仓位权重、算浮盈亏，再让 LLM 输出 `PortfolioHealthReport`

### 与主图的区别

- 主图面向单标的分析

- 健康图面向已有持仓组合诊断

- 两者共用状态模型文件，但拓扑完全不同

---

## 8. 模拟交易链路

这条链是：

`trade.html -> /api/v1/trade/order -> api/mock_exchange.py -> db/crud.py`

### 8.1 前端行为

`trade.html` 分成几块：

- 搜索股票：`/api/v1/market/search`

- 获取现价：`/api/v1/market/spot`

- 提交订单：`/api/v1/trade/order`

- 刷新账户：`/api/v1/trade/account`

- 拉成交历史：`/api/v1/trade/orders`

- 切换 K 线：`/api/v1/market/kline`

额外细节：

- 页面每 5 秒轮询一次现价

- 每次换股票时只拉一次 K 线

- 可以从持仓表一键切到卖出

### 8.2 后端下单逻辑

`/api/v1/trade/order` 的主要流程：

1. 标准化 symbol

2. 通过 `api.mock_exchange.get_account()` 拿到全局内存账户

3. 在线程池里执行 `account.place_order()`

4. `place_order()` 内部再调用 `get_spot_price_raw()` 拿现价

5. 更新现金、持仓、订单

6. 返回成交结果

### 8.3 登录后和未登录的区别

- 未登录：只改内存账户，重启就丢

- 已登录：除了内存账户，还会同步写 SQLite

同步用到的 CRUD 主要是：

- `get_or_create_virtual_account`

- `create_order`

- `update_account_cash_by_market`

- `upsert_position`

- `delete_position`

### 8.4 当前实现的边界

交易状态来源目前不是完全统一的：

- 撮合执行依赖内存账户 `mock_exchange`

- 历史订单查询 `/api/v1/trade/orders` 读的是 DB

- 账户汇总 `/api/v1/trade/account` 目前主要还是从内存快照算出来，接口虽然注入了 `current_user` 和 `db`，但这两个参数并没有真正参与账户汇总计算

也就是说，“登录后持久化”已经做了，但交易账户这块还不是完全 DB-first 的实现。

---

## 9. 市场页链路

`market.html` 不走 LangGraph，它是纯接口聚合页。

调用的接口是：

- `/api/v1/market/quotes`

- `/api/v1/market/indices`

- `/api/v1/market/sectors`

- `/api/v1/market/hotnews`

- `/api/v1/market/kline`

前端刷新策略：

- 行情列表前端自己做 30 秒缓存

- 指数每 60 秒刷新

- 板块每 120 秒刷新

- 热榜每 15 分钟刷新

后端启动时也会启动后台任务提前刷新指数和热榜缓存。

---

## 10. Dashboard 聊天链路

`dashboard.html` 上的“财商学长”走的是：

- `/api/v1/chat/mentor`

不是：

- `/api/v1/chat`

### 前端

`dashboard.html` 会把聊天历史存在 `localStorage`，每次发送时带上最近 10 条消息的 `history`。

如果接口失败，它不会直接报错，而是走前端本地规则 `localMentorFallback()` 兜底。

### 后端

`/api/v1/chat/mentor` 会：

1. 拼 `SystemMessage + history + 当前问题`

2. 调 `graph.nodes._build_llm()`

3. 返回一条简短回复

### 另一个聊天接口为什么存在

`/api/v1/chat` 才是带数据库记忆的版本：

- 依赖 `session_key`

- 会写 `chat_sessions` 和 `chat_messages`

- 走 `utils.llm_client.LLMClient`

但当前 HTML 页面并没有接它，所以它更像“后端已实现、主前端未接入”的能力。

---

## 11. 社区链路

### 已接通的前端功能

`community.html` 已经接了：

- 帖子列表：`GET /api/v1/community/posts`

- 点赞/取消赞：`POST /api/v1/community/posts/{id}/like`

- 发帖：`POST /api/v1/community/posts`

### 后端其实还做了更多

后端还实现了：

- `GET /api/v1/community/posts/{post_id}`：帖子详情 + 评论

- `POST /api/v1/community/posts/{post_id}/comments`：发表评论

### 当前断点

`community.html` 点击帖子后会跳到：

- `post_detail.html?id=...`

但仓库里没有 `post_detail.html` 文件。

所以当前状态是：

- 后端详情/评论接口存在

- 列表页跳转存在

- 详情页前端缺失

---

## 12. FastAPI 主后端 `api/server.py` 怎么读

它负责五类事情。

### 启动初始化

启动时会执行：

1. `db.engine.init_db()`

2. `tools.knowledge_base.init_knowledge_base()`

3. `graph.builder.build_graph_with_memory()`

4. 启动热榜后台刷新

5. 启动市场数据后台轮询

### 分析类接口

- `/api/v1/analyze`

- `/api/v1/health-check`

- `/api/v1/graph/mermaid`

- `/api/v1/health`

### 交易与行情接口

- `/api/v1/trade/order`

- `/api/v1/trade/orders`

- `/api/v1/trade/account`

- `/api/v1/trade/positions`

- `/api/v1/market/search`

- `/api/v1/market/quotes`

- `/api/v1/market/spot`

- `/api/v1/market/kline`

- `/api/v1/market/indices`

- `/api/v1/market/news`

- `/api/v1/market/sectors`

- `/api/v1/market/hotnews`

- `/api/v1/portfolio/summary`

### 认证接口

- `/api/v1/auth/register`

- `/api/v1/auth/login`

- `/api/v1/auth/me`

### 社区接口

- `/api/v1/community/posts`

- `/api/v1/community/posts/{id}`

- `/api/v1/community/posts/{id}/comments`

- `/api/v1/community/posts/{id}/like`

---

## 13. LangGraph 最佳阅读顺序

如果你要读懂多智能体编排，推荐顺序：

1. `graph/state.py`

2. `graph/builder.py`

3. `graph/nodes.py`

4. `api/server.py` 里的 `_stream_graph_events()`

### `graph/state.py`

这里定义：

- `TradingGraphState`

- `AnalystReport`

- `RiskDecision`

- `TradeOrder`

- `DebateOutcome`

- `PortfolioPosition`

- `PortfolioHealthReport`

关键状态字段包括：

- `market_data`

- `fundamental_report`

- `technical_report`

- `sentiment_report`

- `rag_context`

- `has_conflict`

- `debate_outcome`

- `risk_decision`

- `trade_order`

- `tool_call_counts`

- `execution_log`

### `graph/builder.py`

这里负责：

- 注册节点

- 连接边

- 条件路由

- 构建主图

- 构建持仓体检专用图

### `graph/nodes.py`

这是项目真正的业务中枢。节点内部主要做三件事：

1. 调工具函数拿真实数据

2. 用 LLM 生成结构化结论

3. 往共享状态里写结果

这里还放了：

- `_build_llm()` 模型工厂

- anti-loop 限制

- 节点统一降级逻辑

- `route_after_portfolio()` 和 `route_after_risk()` 两个路由函数

---

## 14. 数据层怎么分工

### `utils/market_classifier.py`

这是用户输入清洗层。

它负责：

- 中文、英文、拼音、代码模糊匹配

- 市场分类：A 股 / 港股 / 美股

- 代码标准化

- 搜股联想

### `tools/market_data.py`

这是项目里最重要的数据能力底座，提供：

- `get_market_data()`

- `calculate_technical_indicators()`

- `get_fundamental_data()`

- `get_stock_news()`

- `get_spot_price_raw()`

- `get_batch_quotes_raw()`

- `get_market_indices_raw()`

- `get_market_news_raw()`

- `get_sector_data_raw()`

- `get_deep_financial_data()`

- `get_kline_data_raw()`

### `tools/knowledge_base.py`

这是 RAG 模块。

内部结构是：

- BM25 稀疏检索

- Chroma 向量检索

- Ensemble 融合

- DuckDuckGo 实时联网搜索

对外统一暴露：

- `search_knowledge_base(query, market_type)`

### `scripts/build_kb.py`

这是离线构建知识库脚本，不是在线请求时跑的。

它会生成：

- `data/bm25_index.pkl`

- `data/chroma_db/`

在线后端启动时只加载，不重建。

---

## 15. 数据库层怎么分工

### `db/models.py`

当前主线数据库模型包括：

- `users`

- `virtual_accounts`

- `positions`

- `orders`

- `chat_sessions`

- `chat_messages`

- `community_posts`

- `community_comments`

- `post_likes`

- `news_cache`

### `db/engine.py`

默认数据库是：

```text
sqlite+aiosqlite:///./campusquant.db
```

特点：

- Async SQLAlchemy

- 每个请求一个 session

- 启动时自动建表

- SQLite 下会做一次 `virtual_accounts` 字段迁移

### `db/crud.py`

这里提供统一 CRUD，负责：

- 用户注册和密码校验

- 虚拟账户创建

- 持仓 upsert / 删除

- 订单创建

- 多币种现金更新

- 聊天记忆持久化

- 社区帖子、评论、点赞

- 热榜缓存写入

---

## 16. 模拟交易引擎 `api/mock_exchange.py`

这个模块非常关键，因为它定义了“本项目所有交易都只是模拟撮合”。

特点：

- 全局单例账户

- 三个币种独立维护：CNH、HKD、USD

- 买卖时实时调用 `get_spot_price_raw()` 拿价格

- 内存里维护现金、持仓、订单

- 用线程锁保护并发修改

它是这些接口的共同底层状态源：

- `/api/v1/trade/order`

- `/api/v1/portfolio/summary`

- `/api/v1/trade/account`

- `/api/v1/trade/positions`

---

## 17. Streamlit 前端 `app.py`

`app.py` 不是简单的展示壳，它有自己一套交互逻辑：

- 调 `/api/v1/health` 检查后端是否可用

- 调 `/api/v1/analyze` 消费 SSE

- 用 Streamlit session state 维护聊天历史

- “财商学长”聊天直接在 `app.py` 里构造模型，不走 `/api/v1/chat` 或 `/api/v1/chat/mentor`

所以 HTML 版和 Streamlit 版共用了分析后端，但聊天实现并不统一。

---

## 18. 旧版 CLI 与评估脚本

### `workflow.py`

旧版 CLI 编排器，使用 `agents/*`，不走 LangGraph。

### `agents/*`

包括：

- `data_agent.py`

- `fundamental_agent.py`

- `technical_agent.py`

- `sentiment_agent.py`

- `portfolio_manager.py`

- `risk_manager.py`

它们更像上一代实现，不是当前 FastAPI 主线。

### 其他脚本

- `quick_start.py`：环境与模块自检

- `eval_pipeline.py`：主流程评估

- `eval_rag.py`：RAG 召回评估

- `test_integration.py`：集成测试

---

## 19. 启动前的配置建议

### 安装依赖

```bash
pip install -r requirements.txt
```

### 创建 `.env`

当前仓库没有 `.env.example`，需要手动创建 `.env`。

至少建议配置：

```env
DASHSCOPE_API_KEY=your_key
QWEN_MODEL_NAME=qwen3.5-plus
JWT_SECRET_KEY=change-me
```

可选：

```env
OPENAI_API_KEY=...
ANTHROPIC_API_KEY=...
DATABASE_URL=sqlite+aiosqlite:///./campusquant.db
```

### 可选：先构建知识库

```bash
python scripts/build_kb.py
```

---

## 20. 当前代码里的已知错位点

### `dashboard.html` 和 `/api/v1/trade/account` 的返回结构不完全一致

`dashboard.html` 渲染时更期待 `markets`、`positions` 这种结构，但后端当前主要返回 `accounts`、`positions_all`。

### 后端有 `/api/v1/dashboard/summary`，但页面没用它

`dashboard.html` 目前是自己分别请求：

- `/api/v1/trade/account`

- `/api/v1/market/hotnews`

- `/api/v1/chat/mentor`

### `/api/v1/chat` 有数据库记忆，但主 HTML 没接

当前主页面聊天走的是 `/api/v1/chat/mentor`。

### 社区详情页缺前端文件

`community.html` 跳 `post_detail.html`，但仓库没有这个文件。

### `main.py` 和 `trade.py` 不要和 `api/server.py` 并行当主后端

它们属于旧示例链路。

---

## 21. 建议阅读顺序

如果你要最快看懂整个仓库，建议顺序：

1. `api/server.py`

2. `graph/builder.py`

3. `graph/state.py`

4. `graph/nodes.py`

5. `analysis.html`

6. `trade.html`

7. `tools/market_data.py`

8. `tools/knowledge_base.py`

9. `db/models.py`

10. `db/crud.py`

如果你要准备答辩，可以直接用下面这句概括：

> 当前主架构是“静态 HTML 前端通过 `fetch` 调 FastAPI；FastAPI 用 LangGraph 编排多智能体；节点调用行情工具、RAG 工具和 LLM；结果以 SSE 流式返回前端；交易、社区和聊天记忆再由 SQLite 提供部分持久化”。

