# CampusQuant 产品交付审计报告（终版）

> 审计时间：2026-04-02
> 审计方：Claude Opus 4.6（产品体验 + 4 个并行测试 Agent） + GPT-5.4（产品总监审阅）
> 审计视角：以大二学生（5000元本金、零投资经验）首次使用为基准
> 测试环境：香港主站 47.76.197.100 + 内地中继 47.108.191.110:8001

---

## 核心结论

CampusQuant 功能覆盖面广，但**安全基线、首访体验、数据质量**三个方面存在系统性问题，不适合直接面向大学生规模化上线。

**如果只能修 3 个：**
1. **安全基线** — 数据库密码硬编码 + JWT弱密钥 + XSS + 无鉴权交易，组合起来可完整接管账户
2. **首访路径** — Landing Page + Onboarding，让用户知道这是什么、第一步做什么
3. **数据质量** — 实时行情全部 fallback、搜索结果错乱、知识库未初始化，核心数据不可信

---

## 一、安全问题（共 11 项）

### S1. 数据库密码硬编码在源码中 — Critical

`db/engine.py:26-29` 直接写死了 MySQL 用户名密码和 IP：
```python
DEFAULT_DATABASE_URL = "mysql+asyncmy://monijiaoyishuju:fGNFEYSf66tmTeCD@47.108.191.110/..."
```
任何有仓库访问权限的人都能拿到生产数据库凭据。

### S2. JWT 默认弱密钥 — Critical

`api/auth.py:25`：
```python
SECRET_KEY = os.getenv("JWT_SECRET_KEY", "campusquant-dev-secret-change-in-prod")
```
如果环境变量未设置，攻击者可直接伪造任意用户的 JWT。Token 有效期 7 天，放大风险。

### S3. CORS 全开 — Critical

`api/server.py:98-104`：`allow_origins=["*"]`，任何网站都能直接调用 API。

### S4. 验证码用 `random.randint` 而非密码学安全随机 — Critical

`api/server.py:1083`：Mersenne Twister PRNG 可预测，攻击者观察几次后可推算后续验证码。应改用 `secrets.randbelow(1000000)`。

### S5. 交易接口无鉴权 — Critical

`POST /api/v1/trade/order` 不要求 JWT token。测试中无 token 直接发请求，返回 200（仅因余额不足才失败）。**任何人都能替他人下单**。

### S6. XSS 攻击面 — High

- `dashboard.html` 新闻渲染 `${item.title}` 未转义
- `dashboard.html` 聊天 `renderMsgHTML()` 中 `msg.text` 未转义
- `market.html` 新闻标题同样未转义
- 社区帖子内容存库时无清洗（`db/crud.py:429`）

### S7. Token 存储在 localStorage + XSS = 账户接管 — High

JWT 存在 `localStorage`，结合 S6 的 XSS，攻击链：注入恶意脚本 → 读取 token → 伪造身份。

### S8. 登录开放重定向 — High

`auth.html` 的 `redirect` 参数直接进入 `location.href`，无白名单。攻击者可构造 `auth.html?redirect=https://evil.com`。

### S9. BM25 Pickle 反序列化风险 — High

`tools/knowledge_base.py:374` 直接 `pickle.load()`，无完整性校验。被篡改的 pkl 文件可执行任意代码。

### S10. 缺少 CSP 等安全头 — Medium

无 Content-Security-Policy、X-Frame-Options，放大 XSS 后果。

### S11. 验证码无频率限制 + 账户枚举 — Medium

注册/登录返回信息暴露邮箱是否已注册。验证码无尝试次数限制。

---

## 二、数据质量问题（共 8 项）

### D1. 实时行情全部 fallback — High

`GET /api/v1/market/quotes` 所有股票返回 `is_fallback: true, source: "kline"`。实时数据抓取不工作，用户看到的是缓存的 K 线收盘价，不是实时价格。

### D2. 知识库未初始化 — High

`GET /api/v1/health` 返回 `kb_ready: false`。Chroma + BM25 知识库未加载，RAG 检索返回空结果。分析流程中 rag_node 形同虚设。

### D3. 搜索结果错乱 — Medium

| 搜索词 | 期望 | 实际 |
|--------|------|------|
| `600519` | name:"贵州茅台" | name:"sh600519" |
| `mt`（拼音） | symbol:"美团-W" | symbol:";美团-W"（带分号）, name:"ESG" |
| `AAPL` | name:"Apple/苹果", type:"美股" | name:"AAPL", type:"其他" |

### D4. 部分指数返回 null — High

`^KS11`（韩国KOSPI）返回 `price: null, change: null, change_pct: null`。前端渲染会出现 NaN 或空白。

### D5. Dashboard 快讯有空标题 — High

`GET /api/v1/dashboard/summary` 返回的 5 条新闻中 3 条 `title: ""`，Dashboard 上显示空白条目。

### D6. Spot 行情延迟 18 秒 — High

`GET /api/v1/market/spot?symbol=600519` 响应 18.5 秒。K 线接口 16-22 秒。对"实时行情"场景完全不可用。

### D7. 闭市指数显示 0% 而非标注"已收盘" — Medium

HSI、Nikkei、美债等闭市时显示 `change: 0.0, change_pct: 0.0`，用户以为行情没动，实际是没数据。

### D8. `price_change_pct` 始终为 null — Low

SSE 分析流 data_node 完成事件中 `price_change_pct: null`，信息缺失。

---

## 三、用户旅程断裂点（共 6 项）

### U1. 首页是空跳转，没有产品介绍 — Critical

`index.html` 只有 `<meta http-equiv="refresh" content="0; url=dashboard.html">`。大学生第一次打开看到的是满屏数据的 Dashboard，不知道这是什么产品。

### U2. 新用户无引导 — Critical

新注册后 Dashboard：自选股为空、持仓为空、账户全是初始值。没有新手教程、没有"第一步做什么"。

### U3. 导航栏不一致 — High

- "控制台" vs "仪表盘"：dashboard/trade 叫"控制台"，其他页叫"仪表盘"
- "持仓体检"只在 platforms.html 和 team.html 导航中出现，其他 8 个页面**完全没有入口**
- platforms.html 和 team.html **缺少登录/注册组件**（无 auth-widget）
- 4 个页面（platforms/team/home/resources）导航没有 active 状态高亮

### U4. 侧边栏问题 — High

- 33 个 `href="#"` 死链分布在 9 个页面，无任何反馈
- 各页面侧边栏内容不统一：market.html 只有 4 项且无 emoji；其他页 5 项有 emoji
- market.html 侧边栏链接 `learning.html`，其他页链接 `home.html`

### U5. resources.html 完全不可交互 — High

- 分类筛选按钮（技术分析/基本面等）只切换 CSS，不实际过滤文章列表
- 排序按钮（全部/最新/热门）无点击事件
- 文章条目不是链接，点击无反应
- 所有数据（阅读数、日期）硬编码

### U6. AI 聊天不透明降级 — High

`/api/v1/chat/mentor` 首次调用超时 60s。降级到前端 if-else 规则后，用户无法分辨对面是 AI 还是规则引擎。应加入降级标识。

---

## 四、后端架构问题（共 8 项）

### B1. `/docs` 被静态文件覆盖 — Critical

Swagger UI (`/docs`) 和 ReDoc (`/redoc`) 被 Nginx 静态文件路由覆盖，返回 index.html。生产环境无法访问 API 文档。

### B2. 持仓体检 87 秒 + 泄漏 Pydantic 错误 — Critical

`POST /api/v1/health-check` 响应 87.5 秒，返回的 `overall_diagnosis` 包含原始 Pydantic 验证错误：`"3 validation errors for PortfolioHealthReport\nconcentration_risk\n Field required"`。内部异常直接暴露给用户。

### B3. 错误信息泄漏内部细节 — High

多个端点将 `str(e)` 直接返回给客户端，包含堆栈信息、模型名、API URL、内部路径。

### B4. `_MARKET_CACHE` 非线程安全 — High

全局 dict 被后台 poller 写入 + 请求处理器读取，无锁保护。部分更新期间读取可能导致不一致数据。

### B5. 无速率限制 — High

`/api/v1/analyze`（每次触发 5+ 次 LLM 调用）和 `/api/v1/health-check` 无任何限流。恶意用户可耗尽 LLM API 额度。

### B6. MemorySaver 无 TTL — Medium

每次分析创建新 thread_id，状态永久留在内存。高负载下内存无限增长。

### B7. 异步上下文中使用同步阻塞调用 — Medium

`graph/nodes.py` 中多个 `.invoke()` 调用是同步 HTTP 请求，阻塞事件循环。

### B8. Chat 模型硬编码 — Low

`api/server.py:954` 聊天用 `qwen3.5-flash` 硬编码，未走 config 配置。

---

## 五、LangGraph Agent 逻辑问题（共 6 项）

### G1. 用户输入 symbol 直接注入 LLM Prompt — High

`graph/nodes.py:843,992,1129` 等 8 处将 `symbol` 直接 f-string 进系统/用户 prompt，无清洗。攻击者可提交 `"AAPL\n\nIgnore all previous instructions..."` 进行提示注入。

### G2. `_guard_node("fundamental_report")` 用在 portfolio_node 上 — Medium

portfolio_node 崩溃时，fallback 写入 `fundamental_report` key，**覆盖掉 fundamental_node 的真实分析结果**。

### G3. risk_node 异常 fallback 绕过所有安全检查 — Medium

异常时返回 `position_pct: 10.0, approval_status: "CONDITIONAL"`，跳过 ATR 硬阻断、最大亏损上限、仓位限制。高波动股本应被 REJECT 但会通过。

### G4. `simulated` 字段无 Pydantic 验证器强制为 True — Medium

`TradeOrder.simulated` 默认 True 但无 `@model_validator` 阻止 LLM 输出 `false`。虽然 `trade_executor` 代码层面覆写了，但防御不够深入。

### G5. 辩论只检测基本面 vs 技术面冲突，忽略情绪面 — Medium

如果基本面 BUY、技术面 BUY、但情绪面以 0.95 置信度 SELL，不会触发辩论。

### G6. data_node 失败后 status 被 trade_executor 覆写为 "completed" — Medium

`status` 字段无 reducer（last-write-wins），data 失败 → 降级 HOLD → trade_executor 写 `status: "completed"`，掩盖原始错误。

---

## 六、前端通用问题（共 4 项）

### F1. CSS 全部内联（200-500行/页） — Medium

10 个 HTML 文件各有独立 CSS，导航/侧边栏样式高度重复。改一个导航需改 10 个文件。

### F2. 移动端不可用 — High

- market.html 三栏硬布局 + `overflow: hidden`，手机上完全不可用
- 导航栏 6 个链接在 375px 手机上溢出
- 仅 trade.html 的 nav 加了 `overflow-x: auto`

### F3. 零无障碍支持 — Medium

全站零 `aria-*` 属性，sidebar 按钮无 `aria-label`，表单 label 缺少 `for` 属性。

### F4. "校园财商" vs "专业终端"风格矛盾 — High

面向大学生，但 UI 是深色终端 + 三栏行情 + 专业 K 线。缺少教育引导，缺少免责声明（"不构成投资建议"）。这是**业务合规风险**。

---

## 修复路线图

### P0 — 不修不上线（安全 + 数据基线）

| # | 问题 | 工作量 |
|---|------|--------|
| 1 | S1 数据库密码从源码移除，改纯环境变量 | 小 |
| 2 | S2 JWT 弱密钥移除，强制环境变量 | 小 |
| 3 | S4 验证码改 `secrets` 模块 | 小 |
| 4 | S5 交易接口加鉴权 | 小 |
| 5 | S6 XSS 全面转义（新闻/聊天/社区） | 小 |
| 6 | S3 CORS 白名单（不再 `*`） | 小 |
| 7 | B2 health-check Pydantic 错误不外泄 | 小 |
| 8 | B1 /docs 路由不被静态文件覆盖 | 小 |
| 9 | D2 知识库初始化（部署时 build_kb.py） | 中 |

### P1 — 上线一周内修（体验 + 数据）

| # | 问题 | 工作量 |
|---|------|--------|
| 10 | U1+U2 Landing Page + 新用户引导 | 大 |
| 11 | U3 导航栏统一（命名+入口+auth-widget） | 中 |
| 12 | D1 实时行情修复（不全 fallback） | 中 |
| 13 | D3 搜索结果修复 | 中 |
| 14 | D4+D5 null 指数 + 空标题过滤 | 小 |
| 15 | S8 登录重定向白名单 | 小 |
| 16 | U6 AI 聊天降级标识 | 小 |
| 17 | G1 symbol 输入清洗 | 小 |
| 18 | B5 关键接口限流 | 中 |
| 19 | F4 合规免责声明 | 小 |

### P2 — 两周内优化

| # | 问题 | 工作量 |
|---|------|--------|
| 20 | U4 侧边栏统一 + 死链处理 | 小 |
| 21 | U5 resources.html 交互修复 | 中 |
| 22 | G2 _guard_node key 修复 | 小 |
| 23 | G3 risk fallback 保留安全检查 | 小 |
| 24 | G4 simulated 加 validator | 小 |
| 25 | S7 Token 改 HttpOnly Cookie | 中 |
| 26 | F2 移动端适配 | 大 |
| 27 | F1 CSS 抽取公共样式 | 大 |
| 28 | B6 MemorySaver 加 TTL | 小 |

---

## 问题汇总

| 级别 | 数量 | 关键主题 |
|------|------|----------|
| Critical | 9 | 硬编码凭据、JWT弱密钥、CORS全开、无鉴权交易、验证码可预测、首页无内容、无用户引导、健康检查泄漏错误、/docs被覆盖 |
| High | 18 | XSS、Token接管、开放重定向、行情全fallback、KB未初始化、搜索错乱、null指数、空标题、延迟18s、提示注入、移动端不可用、风格矛盾 |
| Medium | 14 | 账户枚举、CSP缺失、pickle风险、缓存线程安全、搜索质量、导航不一致、CSS内联、无障碍、MemorySaver、阻塞调用 |
| Low | 5 | 聊天模型硬编码、price_change_pct null、闭市显示、硬编码资本假设、status覆写 |
| **总计** | **46** | |
