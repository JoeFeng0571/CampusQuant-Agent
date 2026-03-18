# Multi-Agent Trading System — API 文档

> 版本: v2.0.0 | 协议: HTTP/1.1 + SSE | 基础路径: `http://localhost:8000`

---

## 快速开始

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 启动后端
uvicorn api.server:app --host 0.0.0.0 --port 8000 --reload

# 3. 启动前端（可选）
streamlit run app.py
```

---

## 接口列表

| 方法 | 路径 | 描述 |
|------|------|------|
| `POST` | `/api/v1/analyze` | 流式分析交易标的（SSE） |
| `GET`  | `/api/v1/health`  | 健康检查 |
| `GET`  | `/api/v1/graph/mermaid` | 获取图拓扑 Mermaid 字符串 |
| `GET`  | `/docs` | Swagger 交互式文档 |

---

## POST /api/v1/analyze

### 请求

```http
POST /api/v1/analyze
Content-Type: application/json
Accept: text/event-stream
```

**请求体**

```json
{
  "symbol": "AAPL",
  "days": 180
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `symbol` | string | ✅ | 交易标的代码。支持格式见下表 |
| `days` | integer | ❌ | 历史数据天数，默认 180，范围 30-365 |

**支持的 symbol 格式**

| 市场 | 格式 | 示例 |
|------|------|------|
| A股 | `数字.SH` / `数字.SZ` | `600519.SH`（茅台）、`000858.SZ`（五粮液） |
| 港股 | `数字.HK` | `00700.HK`（腾讯）、`09988.HK`（阿里） |
| 美股 | 股票代码 | `AAPL`、`NVDA`、`TSLA` |

### 响应

**Content-Type**: `text/event-stream`

响应为 Server-Sent Events (SSE) 格式，每个事件结构如下：

```
event: <事件类型>
data: <JSON 字符串>

```

**事件 data 字段通用结构**

```json
{
  "event":     "node_complete",
  "node":      "fundamental_node",
  "message":   "基本面分析: BUY (置信度 85%)",
  "data":      { ... },
  "timestamp": "2025-01-01T12:00:00.000000+00:00",
  "seq":       3
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `event` | string | 事件类型（见下方详细说明） |
| `node` | string | 产生此事件的节点名称 |
| `message` | string | 人类可读的事件摘要 |
| `data` | object | 节点输出的结构化数据 |
| `timestamp` | string | ISO 8601 UTC 时间戳 |
| `seq` | integer | 事件序号（从 1 递增） |

---

## SSE 事件类型详解

### `start` — 分析启动

```json
{
  "event": "start",
  "node": "system",
  "message": "开始分析 AAPL，LangGraph 多智能体引擎启动...",
  "data": {
    "symbol": "AAPL",
    "thread_id": "uuid-v4-string"
  }
}
```

---

### `node_start` — 节点开始执行

```json
{
  "event": "node_start",
  "node": "fundamental_node",
  "message": "⚙️ 基本面分析师 开始工作...",
  "data": {
    "label": "基本面分析师"
  }
}
```

**可能的 `node` 值**

| node | 含义 | 并行? |
|------|------|-------|
| `data_node` | 数据情报员 | 否 |
| `rag_node` | RAG 知识检索 | 是（与分析师并行） |
| `fundamental_node` | 基本面分析师 | 是 |
| `technical_node` | 技术分析师 | 是 |
| `sentiment_node` | 舆情分析师 | 是 |
| `portfolio_node` | 基金经理 | 否 |
| `debate_node` | 多空辩论裁决 | 否（条件触发） |
| `risk_node` | 风险控制官 | 否 |
| `trade_executor` | 交易指令生成 | 否 |

---

### `node_complete` — 节点执行完成

**data_node 完成示例**

```json
{
  "event": "node_complete",
  "node": "data_node",
  "data": {
    "latest_price": 227.50,
    "price_change_pct": 1.25,
    "tech_signal": "BUY"
  }
}
```

**fundamental_node 完成示例**

```json
{
  "event": "node_complete",
  "node": "fundamental_node",
  "data": {
    "recommendation": "BUY",
    "confidence": 0.82,
    "signal_strength": "STRONG",
    "reasoning_preview": "苹果公司AI战略持续推进，iPhone 16超级周期启动..."
  }
}
```

---

### `conflict` — 检测到多空冲突

当基本面建议与技术面建议相反（一个 BUY 一个 SELL）时触发。

```json
{
  "event": "conflict",
  "node": "portfolio_node",
  "message": "⚡ 检测到基本面与技术面意见冲突，启动多空辩论机制...",
  "data": {
    "conflict": true
  }
}
```

---

### `debate` — 多空辩论完成

```json
{
  "event": "debate",
  "node": "debate_node",
  "message": "⚖️ 辩论第1轮裁决: BUY (置信度 70%)",
  "data": {
    "resolved_recommendation": "BUY",
    "confidence_after_debate": 0.70,
    "deciding_factor": "美联储降息周期支撑估值扩张，基本面论点更具说服力",
    "debate_rounds": 1
  }
}
```

---

### `risk_check` — 风控审批结果

```json
{
  "event": "risk_check",
  "node": "risk_node",
  "message": "✅ 风控审批: APPROVED | 风险 MEDIUM | 仓位 15%",
  "data": {
    "approval_status": "APPROVED",
    "risk_level": "MEDIUM",
    "position_pct": 15.0,
    "stop_loss_pct": 7.0,
    "take_profit_pct": 20.0,
    "rejection_reason": null
  }
}
```

**`approval_status` 可选值**

| 值 | 含义 |
|----|------|
| `APPROVED` | 审批通过，按建议执行 |
| `CONDITIONAL` | 条件通过，需遵循附加条件 |
| `REJECTED` | 拒绝，要求基金经理修订 |

---

### `risk_retry` — 风控拒绝，进入修订流程

```json
{
  "event": "risk_retry",
  "node": "risk_node",
  "message": "❌ 风控拒绝（第1次）: 仓位超出风控上限 → 要求基金经理修订方案",
  "data": {
    "approval_status": "REJECTED",
    "risk_level": "HIGH",
    "position_pct": 0,
    "rejection_reason": "建议仓位30%超出单标的仓位上限10%"
  }
}
```

---

### `trade_order` — 最终交易指令

这是最核心的事件，包含完整的交易指令结构。

```json
{
  "event": "trade_order",
  "node": "trade_executor",
  "message": "🎯 交易指令: BUY AAPL | 仓位 15% | 止损 211.57 | 止盈 272.90",
  "data": {
    "symbol": "AAPL",
    "action": "BUY",
    "quantity_pct": 15.0,
    "order_type": "LIMIT",
    "limit_price": 227.96,
    "stop_loss": 211.57,
    "take_profit": 272.90,
    "rationale": "苹果AI战略布局叠加美联储降息周期，技术面多头排列确认，MACD金叉配合放量，风险收益比约1:2.5",
    "confidence": 0.78,
    "market_type": "US_STOCK",
    "valid_until": "2025-01-08"
  }
}
```

**`action` 可选值**: `BUY` | `SELL` | `HOLD`
**`order_type` 可选值**: `MARKET` | `LIMIT`

---

### `complete` — 全流程完成

```json
{
  "event": "complete",
  "node": "system",
  "message": "✅ 分析完成: AAPL → BUY (仓位 15%)",
  "data": {
    "symbol": "AAPL",
    "status": "completed",
    "trade_order": { ... }
  }
}
```

---

### `error` — 发生错误

```json
{
  "event": "error",
  "node": "system",
  "message": "分析过程异常: API key 无效",
  "data": {
    "error": "API key 无效"
  }
}
```

---

## 客户端代码示例

### JavaScript (EventSource)

```javascript
const eventSource = new EventSource(
  '/api/v1/analyze',
  // 注意: EventSource 不支持 POST，需改用 fetch + ReadableStream
);

// 使用 fetch 实现 POST + SSE
async function analyzeSymbol(symbol) {
  const response = await fetch('http://localhost:8000/api/v1/analyze', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ symbol }),
  });

  const reader = response.body.getReader();
  const decoder = new TextDecoder();

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    const text = decoder.decode(value);
    const lines = text.split('\n');

    for (const line of lines) {
      if (line.startsWith('data:')) {
        const eventData = JSON.parse(line.slice(5).trim());
        handleEvent(eventData);
      }
    }
  }
}

function handleEvent(event) {
  console.log(`[${event.seq}] ${event.event}: ${event.message}`);

  switch (event.event) {
    case 'trade_order':
      renderTradeOrder(event.data);
      break;
    case 'conflict':
      showDebateStarted();
      break;
    case 'complete':
      showCompleted(event.data);
      break;
    case 'error':
      showError(event.data.error);
      break;
  }
}
```

### Python (httpx)

```python
import httpx
import json

def analyze_streaming(symbol: str):
    url = "http://localhost:8000/api/v1/analyze"

    with httpx.stream("POST", url, json={"symbol": symbol}, timeout=300) as resp:
        for line in resp.iter_lines():
            if line.startswith("data:"):
                event = json.loads(line[5:])
                print(f"[{event['seq']:02d}] {event['event']}: {event['message']}")

                if event["event"] == "trade_order":
                    order = event["data"]
                    print(f"  → {order['action']} {symbol} | 仓位 {order['quantity_pct']}%")

                elif event["event"] == "complete":
                    print("分析完成!")
                    return event["data"]["trade_order"]

trade_order = analyze_streaming("AAPL")
```

### Vue 3 组合式 API

```vue
<script setup>
import { ref, reactive } from 'vue'

const events = ref([])
const tradeOrder = ref(null)
const isAnalyzing = ref(false)

async function startAnalysis(symbol) {
  isAnalyzing.value = true
  events.value = []
  tradeOrder.value = null

  const response = await fetch('http://localhost:8000/api/v1/analyze', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ symbol }),
  })

  const reader = response.body.getReader()
  const decoder = new TextDecoder()

  while (true) {
    const { done, value } = await reader.read()
    if (done) break

    const text = decoder.decode(value)
    for (const line of text.split('\n')) {
      if (line.startsWith('data:')) {
        const event = JSON.parse(line.slice(5))
        events.value.push(event)

        if (event.event === 'trade_order') {
          tradeOrder.value = event.data
        }
      }
    }
  }

  isAnalyzing.value = false
}
</script>
```

---

## 健康检查

```http
GET /api/v1/health
```

**响应**

```json
{
  "status":      "ok",
  "version":     "2.0.0",
  "graph_ready": true,
  "kb_ready":    true,
  "timestamp":   "2025-01-01T12:00:00.000000+00:00"
}
```

---

## 错误码

| HTTP 状态码 | 场景 |
|-------------|------|
| `200` | 成功（SSE 流已建立） |
| `400` | 请求参数错误（symbol 为空） |
| `422` | 请求体格式错误（Pydantic 验证失败） |
| `500` | 服务器内部错误 |

---

## 注意事项

1. **超时设置**: SSE 连接最长持续 300 秒（5分钟），LLM 推理耗时因 API 响应速度而异
2. **并发限制**: 当前使用 MemorySaver（内存存储），服务重启后历史记录清空
3. **API Key**: 需要在 `.env` 文件中配置 `ANTHROPIC_API_KEY` 或 `OPENAI_API_KEY`
4. **FAISS 知识库**: 若未配置 OpenAI API Key，知识库将降级为关键词检索模式
5. **市场数据**: 美股需要联网（yfinance）；A股/港股通过 akshare

---

*由 LangGraph + FastAPI + FAISS + Pydantic 强力驱动*
