# CampusQuant 前端全功能说明文档

> **版本**：2026-03-10 · 猎犬排雷全栈深度排查报告 + 前端功能参考手册

---

## 一、全栈排雷总结

### 1.1 后端修复清单（tools/market_data.py）

| # | 问题 | 根因 | 修复方案 |
|---|------|------|---------|
| B1 | `NameError: _BATCH_TIMEOUT is not defined` | 常量只在单股接口定义，批量接口忘记声明 | 在模块顶部补充 `_BATCH_TIMEOUT = 20` |
| B2 | `"Can not decode value starting with character '<'"` | `stock_bid_ask_em` 被限速时返回 HTML 错误页而非 JSON | 主接口失败时自动切换备用接口 `stock_zh_a_spot_em()` 精确过滤单行 |
| B3 | A 股批量行情超时（>20s） | 串行对每只股票调 `stock_zh_a_spot_em()`（58页/约105s） | 改用 `ThreadPoolExecutor(max_workers=10)` 并发调 `stock_bid_ask_em`，最慢一只不超过12s |
| B4 | 港股批量行情超时（>35s，客户端空响应） | 串行对6只港股各调 `stock_hk_spot_em()` 全表（6×35s=210s） | 改为一次性下载全表+35s超时；超时后立即返回 `is_fallback=True` 静态占位，不再级联重试 |

### 1.2 前端修复清单

| # | 文件 | 问题 | 根因 | 修复方案 |
|---|------|------|------|---------|
| F1 | `market.html` | `ReferenceError: API_BASE is not defined` | `fetchAndRender('a')` 在第一个 `<script>` 块末尾同步调用，但 `const API_BASE` 仅声明在第二个 `<script>` 块 | 将 `const API_BASE` 移至第一个 `<script>` 块顶部；删除第二个块中的重复声明 |
| F2 | `platforms.html` | 同上 `API_BASE` 作用域问题 | `startHealthCheck()` 构造 URL 时依赖尚未声明的 `API_BASE` | 同 F1 处理方式 |
| F3 | `index.html` | `localhost` 在 Windows 可能解析至 IPv6 `::1`，而 uvicorn 绑定 `127.0.0.1` | `API_BASE = 'http://localhost:8000/api/v1'` | 改为 `'http://127.0.0.1:8000/api/v1'` |

### 1.3 所有后端端点验证结果

| 端点 | 方法 | 验证结果 |
|------|------|---------|
| `POST /api/v1/analyze` | SSE 流式 | ✅ 全链路 SSE 正常（9个节点依次触发） |
| `POST /api/v1/health-check` | JSON | ✅ 返回 score + risk_level + recommendations |
| `POST /api/v1/chat` | JSON | ✅ Qwen 正常响应，UTF-8 无乱码 |
| `POST /api/v1/trade/order` | JSON | ✅ 模拟撮合成功（BUY AAPL，simulated=True） |
| `GET /api/v1/market/quotes?market=a` | JSON | ✅ 8只A股，实时价，0个fallback |
| `GET /api/v1/market/quotes?market=hk` | JSON | ✅ 6只港股，is_fallback=True（全表下载超时，静态降级） |
| `GET /api/v1/market/quotes?market=us` | JSON | ✅ 7只美股，实时价 |
| `GET /api/v1/portfolio/summary` | JSON | ✅ 虚拟账户持仓+总市值正常 |
| `GET /api/v1/market/search?q=` | JSON | ✅ 中文/拼音/代码模糊搜索正常 |
| `GET /api/v1/graph/mermaid` | JSON | ✅ LangGraph 拓扑图文本正常返回 |

---

## 二、前端页面全功能参考

### 系统启动方式

```bash
# 1. 启动后端（任选一）
uvicorn api.server:app --host 127.0.0.1 --port 8000
# 或
python api/server.py

# 2. 启动静态文件服务
python -m http.server 3000

# 3. 浏览器访问
http://localhost:3000/index.html
```

---

### 2.1 首页 `index.html` — AI 财财学长

**功能概述**：系统入口，面向大学生的对话式股票分析入口，支持自然语言提问和股票代码识别。

#### 功能列表

| 功能 | 实现方式 | 说明 |
|------|---------|------|
| 自然语言提问 | `<textarea>` + 正则提取股票代码 | 支持 `600519`、`AAPL`、`00700` 格式 |
| 提示芯片 | `querySelectorAll('.hint-chip')` 点击填充 | 预设大学生常见问题 |
| Placeholder 轮播 | `setInterval(4000ms)` | 6条场景化提示语循环显示 |
| 股票识别 → SSE 分析 | 正则 `/\b([A-Z]{1,5}|\d{6}(?:\.[A-Z]{2})?)\b/` | 识别到代码则调用后端 SSE；否则触发顾问回复 |
| SSE 实时分析流 | `POST /api/v1/analyze` | 展示节点进度徽章 + 打字机效果 |
| 演示模式回退 | `simulateSSE()` | 后端不可达时自动进入本地演示，不报错 |
| 顾问对话（无代码） | `simulateAdvisorResponse()` | 针对"止损"/"全仓"/"财报"等关键词给出教育性回复 |
| 最终结果卡 | `renderResultCard(order)` | 显示操作方向/建议仓位/止损价/止盈价/置信度/核心依据 |
| 风险守则弹窗 | `showRiskGuide()` | 6条大学生投资硬规则 |
| 侧边栏导航 | CSS `transform` + overlay | 移动端适配 |

#### 防御性代码

- `if (!order || !order.action) return;` — `renderResultCard` 空值保护
- `data?.trade_order` — 可选链
- `catch` → 自动降级至 `simulateSSE`
- SSE JSON parse 失败 → `console.warn` 跳过，不中断流

---

### 2.2 深度分析页 `analysis.html` — 多智能体 SSE 分析

**功能概述**：核心分析页，输入股票代码后触发 LangGraph 多智能体流式分析，实时展示各节点进度，最终输出 AI 研报 + 财务图表 + 交易建议。

#### 功能列表

| 功能 | 实现方式 | 说明 |
|------|---------|------|
| 股票代码输入 | `<input id="symbol-input">` | 支持 A股/港股/美股 |
| 市场切换 Tab | `setMarket()` / `setMarketByKey()` | 切换时更新 `currentMarket`，影响下拉搜索结果 |
| 实时模糊搜索 | `GET /api/v1/market/search?q=` | 输入 ≥1 字符触发，下拉展示匹配股票 |
| 分析天数设置 | `<input id="days-input">` 默认90天 | 传入后端 `days` 参数 |
| SSE 流式分析 | `POST /api/v1/analyze` + `ReadableStream` | 逐行解析 `event:` / `data:` |
| 节点进度条 | `setNodeStatus(node, state)` | `active`/`done`/`error` 三态徽章 |
| 状态指示灯 | `#status-dot` CSS class | `running`/`done`/`error` 三色 |
| 打字机效果 | `appendText()` + `.tw-cursor` | 渐进展示各节点摘要文字 |
| 结果卡 | `showResult(order, risk)` | 操作/置信度/风险等级/建议仓位/执行价/价格来源 |
| 深度研报 Tab | `renderReport(markdown)` | `marked.parse()` 渲染；marked 不可用则降级为 `<pre>` |
| 财务图表 Tab | `renderFinanceChart(cd)` | ECharts 柱状图，`has_data=false` 或港股时显示文字占位 |
| ECharts 崩溃保护 | `try/catch` around `renderFinanceChart` | 捕获异常，隐藏图表容器，显示文字提示 |
| 错误回退 | `catch(err)` → 打印错误文本 | 提示用户确认后端已启动 |

#### SSE 事件处理映射

| SSE event 类型 | 处理行为 |
|----------------|---------|
| `start` | 追加开始文本 |
| `node_start` | 节点徽章 → `active` |
| `node_complete` | 节点徽章 → `done` + 追加摘要 |
| `conflict` | 追加冲突提示（进入辩论） |
| `debate` | 追加辩论裁决 |
| `risk_check` | 追加风控结果 |
| `risk_retry` | 追加重试提示 + 节点 → `error` |
| `trade_order` | 渲染结果卡 |
| `complete` | 渲染研报 + 图表 + 完成提示 |
| `error` | 追加错误文本 + 节点 → `error` |

---

### 2.3 持仓体检页 `platforms.html`

**功能概述**：输入持仓列表，由 AI 进行健康度打分，给出风险评级和调仓建议。

#### 功能列表

| 功能 | 实现方式 | 说明 |
|------|---------|------|
| 持仓输入区 | `<textarea id="positions-input">` | 每行一条，格式：`代码 数量 成本价`，如 `600519 100 1400.00` |
| 一键体检 | `startHealthCheck()` | `POST /api/v1/health-check`，发送 `positions[]` 数组 |
| SVG 评分环 | `updateScoreRing(score)` | 0-100分，CSS `stroke-dashoffset` 动画 |
| 风险颜色编码 | `scoreEl.className` | 低风险蓝绿 / 中风险黄色 / 高风险红色 |
| 指标格格 | `#metrics-grid` | 持仓集中度 / 波动暴露 / 股息覆盖率 / 流动性评分 |
| 建议卡 | `#recommend-card` | 逐条展示 AI 调仓建议 |
| 加载状态 | `checkRunning` 布尔锁 | 防重复提交 |
| 错误显示 | `showError(msg)` | 后端不可达时显示红色错误信息 |

#### POST 请求格式

```json
{
  "positions": [
    { "symbol": "600519", "quantity": 100, "avg_cost": 1400.00 },
    { "symbol": "AAPL",   "quantity": 10,  "avg_cost": 175.00  }
  ]
}
```

---

### 2.4 市场快讯页 `market.html`

**功能概述**：三市场（A股/港股/美股）实时行情板块，自动刷新。

#### 功能列表

| 功能 | 实现方式 | 说明 |
|------|---------|------|
| 市场 Tab 切换 | `switchTab(market)` | `a`/`hk`/`us` 三档，切换后立即刷新 |
| 自动刷新 | `setInterval(30000)` | 每30秒重新获取当前 Tab 行情 |
| 行情表格 | `renderQuoteTable(quotes)` | 涨跌幅颜色编码（红涨绿跌） |
| 加载动画 | `#loading-overlay` | 请求期间显示 spinner |
| 数据降级提示 | `is_fallback` 字段 | 港股超时时显示"⚠ 静态数据"标注 |
| 快速跳转分析 | 表格每行「分析」链接 | 跳转 `analysis.html?symbol=XXX` |

#### 获取接口

```
GET /api/v1/market/quotes?market=a    → A股行情（8只）
GET /api/v1/market/quotes?market=hk   → 港股行情（6只，可能降级）
GET /api/v1/market/quotes?market=us   → 美股行情（7只）
```

---

### 2.5 模拟交易页 `trade.html`

**功能概述**：提交买卖指令至本地模拟撮合引擎，不涉及任何真实资金。

#### 功能列表

| 功能 | 实现方式 | 说明 |
|------|---------|------|
| 股票代码输入 | `#trade-symbol` | 支持 A股/港股/美股 |
| 操作方向 | `BUY` / `SELL` 按钮组 | 点击切换高亮 |
| 数量输入 | `#trade-qty` | 正整数，单位：股 |
| 提交委托 | `POST /api/v1/trade/order` | body: `{symbol, action, quantity}` |
| 成交回单 | `renderOrderResult(order)` | 展示成交价/手续费/总金额/时间戳 |
| 持仓实时更新 | `loadPortfolio()` | 下单成功后自动刷新持仓列表 |
| 账户余额 | `GET /api/v1/portfolio/summary` | 显示可用资金 |
| 强制模拟 | 后端 `TradeOrder.simulated = True` | 所有订单必须为模拟，永不真实成交 |

#### POST 请求格式

```json
{ "symbol": "600519", "action": "BUY", "quantity": 100 }
```

---

### 2.6 学习中心 `home.html`

**功能概述**：学习中心仪表盘，整合持仓摘要 + 自选股监控。

#### 功能列表

| 功能 | 实现方式 | 说明 |
|------|---------|------|
| 持仓总市值 | `GET /api/v1/portfolio/summary` | `DOMContentLoaded` 后自动加载 |
| 总浮盈展示 | `#sum-total-pnl` | 正值绿色/负值红色 |
| 自选股表格 | `positions[]` 列表渲染 | 代码/名称/现价/涨跌/成本/浮盈/快速分析链接 |
| 快速分析跳转 | `<a href="trade.html?sym=...">` | 跳转至分析页并预填股票代码 |
| 后端离线降级 | `catch` → 占位文本 | 显示"¥ --（后端未启动）"，不崩溃 |
| 货币符号自适应 | 正则判断市场 | A股 `¥`，港股 `HK$`，美股 `$` |

---

### 2.7 投教社区 `community.html`

**功能概述**：纯静态学习内容页面，展示大学生投资教育文章、问答、活动信息。

**无后端依赖** — 该页面完全静态，后端不启动也能正常展示。

---

### 2.8 学习资源库 `resources.html`

**功能概述**：投资学习资料分类筛选页。

#### 功能列表

| 功能 | 实现方式 | 说明 |
|------|---------|------|
| 分类筛选 | `filterTag(tag)` | basic / analysis / risk / advanced 四档 |
| 资源卡片 | 纯 HTML，`data-tag` 属性 | CSS `display:none` 切换显示 |

**无后端依赖** — 完全静态。

---

### 2.9 关于我们 `team.html`

**功能概述**：团队介绍静态页，展示项目成员与技术栈说明。

**无后端依赖** — 完全静态。

---

## 三、全局架构约定

### 3.1 CSS 变量（所有页面统一）

```css
--primary:   #4f7cff   /* 品牌蓝 */
--success:   #2ed573   /* 涨 / 成功绿 */
--danger:    #ff4757   /* 跌 / 错误红 */
--bg-dark:   #0a0e1a   /* 页面底色 */
--card-bg:   #111827   /* 卡片背景 */
--text-muted:#6b7280   /* 次级文字 */
```

### 3.2 API_BASE 约定

所有页面统一使用：

```javascript
const API_BASE = 'http://127.0.0.1:8000';
```

> `index.html` 的 API_BASE 含 `/api/v1` 后缀（`http://127.0.0.1:8000/api/v1`），功能等价。

### 3.3 侧边栏模式

所有页面均实现相同侧边栏逻辑，通过三个 DOM 元素控制：`#sidebar` / `#sidebar-overlay` / `#sidebar-toggle`。

### 3.4 前端防御性编程规范（已全面落实）

| 规范 | 应用位置 |
|------|---------|
| `?? '--'` / `\|\| 0` 兜底默认值 | 所有数值显示点 |
| 可选链 `?.` | SSE data 字段访问 |
| `if (!el) return` 早返回 | DOM 节点操作前 |
| `try/catch` 包裹 ECharts 渲染 | `analysis.html` |
| 后端离线时降级占位文本 | `home.html`, `dashboard.html` |
| SSE JSON parse 失败 → `console.warn` + 跳过 | `index.html`, `analysis.html` |
| `is_fallback` 标注降级数据 | `market.html` 港股 Tab |

---

## 四、已知限制与说明

| 限制 | 说明 |
|------|------|
| 港股行情 `is_fallback=True` | `stock_hk_spot_em` 全表下载在当前网络环境超过35s，返回静态占位价格 0.00 |
| A股行情延迟 | `stock_bid_ask_em` 单股接口最慢12s；批量8只并发后总延迟约12s |
| 美股数据 | yfinance `fast_info` 实时拉取，国内网络可能偶发超时 |
| LLM 分析 | 依赖 DashScope API Key（`DASHSCOPE_API_KEY` 环境变量） |
| 所有交易 | 永久模拟，`TradeOrder.simulated = True` 硬编码 |
| 加密货币 | 已从全系统移除，不支持任何加密资产 |
