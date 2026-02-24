"""
app.py — CampusQuant-Agent · 校园财商智能分析平台

产品定位:
  目标用户：在校大学生（缺乏经验、本金有限、需要财商教育）
  核心功能：
    1. 智能标的搜索（支持中文公司名/拼音/代码的模糊匹配）
    2. 多智能体实时分析（A股/港股/美股，LangGraph SSE 流式渲染）
    3. 侧边栏 AI 财商助手"财财学长"（独立对话，财商教育导向）

技术架构:
  Streamlit 前端 ←→ FastAPI 后端 (SSE 流式)
  AI 财商助手：直接调用 LLM，独立 session state，不与 LangGraph 冲突

运行方式:
  1. uvicorn api.server:app --host 127.0.0.1 --port 8000
  2. streamlit run app.py
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Generator, List

import httpx
import streamlit as st

sys.path.append(str(Path(__file__).parent))

from utils.market_classifier import MarketClassifier, MarketType

# ════════════════════════════════════════════════════════════════════
# 页面配置
# ════════════════════════════════════════════════════════════════════

st.set_page_config(
    page_title="CampusQuant 校园财商智能分析",
    page_icon="🎓",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ════════════════════════════════════════════════════════════════════
# CSS 样式
# ════════════════════════════════════════════════════════════════════

st.markdown("""
<style>
/* ── 决策卡片 ───────────────────────────────────────────── */
.decision-card { border-radius:12px; padding:20px 24px; margin:12px 0; }
.decision-buy  { border-left:6px solid #4CAF50; background:#f0faf0; }
.decision-sell { border-left:6px solid #f44336; background:#fff5f5; }
.decision-hold { border-left:6px solid #FF9800; background:#fffbf0; }

/* ── 徽章 ───────────────────────────────────────────────── */
.badge-buy  { background:#e8f5e9; color:#2e7d32; padding:3px 12px; border-radius:12px; font-weight:700; font-size:14px; }
.badge-sell { background:#ffebee; color:#c62828; padding:3px 12px; border-radius:12px; font-weight:700; font-size:14px; }
.badge-hold { background:#fff8e1; color:#f57f17; padding:3px 12px; border-radius:12px; font-weight:700; font-size:14px; }
.badge-info { background:#e3f2fd; color:#1565c0; padding:3px 12px; border-radius:12px; font-weight:700; font-size:14px; }

/* ── 市场标签 ───────────────────────────────────────────── */
.market-tag     { display:inline-block; padding:3px 12px; border-radius:20px; font-size:13px; font-weight:600; margin-bottom:6px; }
.market-a-stock { background:#fff3e0; color:#e65100; }
.market-hk-stock{ background:#fce4ec; color:#880e4f; }
.market-us-stock{ background:#e8eaf6; color:#283593; }

/* ── SSE 日志流 ─────────────────────────────────────────── */
.log-container {
    background:#0d1117; color:#58a6ff;
    font-family:'Courier New',monospace; font-size:12.5px;
    padding:14px 18px; border-radius:8px;
    max-height:280px; overflow-y:auto; line-height:1.7;
}
.log-success { color:#3fb950; }
.log-warning { color:#d29922; }
.log-error   { color:#f85149; }
.log-debate  { color:#bc8cff; }
.log-risk    { color:#79c0ff; }

/* ── 打字机光标 ─────────────────────────────────────────── */
.typewriter::after { content:'▍'; animation:blink 0.8s step-end infinite; }
@keyframes blink { 50% { opacity:0; } }

/* ── 节点卡片 ───────────────────────────────────────────── */
.node-card    { background:white; border:1px solid #e0e0e0; border-radius:10px; padding:14px 18px; margin:8px 0; box-shadow:0 1px 4px rgba(0,0,0,.06); }
.node-running { border-left:4px solid #2196F3; animation:pulse 1.5s ease-in-out infinite; }
.node-done    { border-left:4px solid #4CAF50; }
@keyframes pulse { 0%,100% { opacity:1; } 50% { opacity:.7; } }

/* ── 最终指令卡片 ───────────────────────────────────────── */
.order-card { border-radius:14px; padding:24px 28px; margin-top:16px; font-size:15px; }
.order-buy  { background:linear-gradient(135deg,#e8f5e9,#c8e6c9); border:2px solid #4CAF50; }
.order-sell { background:linear-gradient(135deg,#ffebee,#ffcdd2); border:2px solid #f44336; }
.order-hold { background:linear-gradient(135deg,#fff8e1,#fff3cd); border:2px solid #FF9800; }

/* ── 搜索结果提示条 ─────────────────────────────────────── */
.match-hint { background:#e8f4fd; border-left:4px solid #2196F3;
              padding:8px 14px; border-radius:6px; font-size:13px; margin:6px 0; }

/* ── 财商助手聊天气泡 ─────────────────────────────────────── */
.chat-bubble-user      { background:#dcf8c6; padding:8px 12px; border-radius:12px 12px 2px 12px; margin:4px 0; font-size:13px; }
.chat-bubble-assistant { background:#f0f0f0; padding:8px 12px; border-radius:12px 12px 12px 2px; margin:4px 0; font-size:13px; }
</style>
""", unsafe_allow_html=True)

# ════════════════════════════════════════════════════════════════════
# 配置常量
# ════════════════════════════════════════════════════════════════════

API_BASE    = "http://127.0.0.1:8000"
SSE_TIMEOUT = 300

# ════════════════════════════════════════════════════════════════════
# Session State 初始化
# ════════════════════════════════════════════════════════════════════

if "advisor_messages" not in st.session_state:
    st.session_state.advisor_messages: List[dict] = []  # {"role": "user"/"assistant", "content": str}

# ════════════════════════════════════════════════════════════════════
# AI 财商助手：System Prompt & LLM 调用
# ════════════════════════════════════════════════════════════════════

_ADVISOR_SYSTEM_PROMPT = """你是"财财学长"，一个专为在校大学生设计的校园财商AI导师。

你的人设与说话风格：
- 像靠谱的学长学姐，年轻接地气，偶尔用括号加感叹词（比如"（这很重要！）"），但不夸张
- 说话简洁有力，不用官腔，不装高深
- 擅长用校园生活打比方解释金融概念：
  • 市盈率 = 你花多少顿饭钱买一家奶茶店每年1块钱利润的权益
  • 降息 = 你存银行的零花钱利息变少了，大家就更愿意冒险买股票
  • 分散投资 = 不要把鸡蛋放在一个篮子里（你总在宿舍听到这句话对吧）
  • 定投 = 每月固定买一点，就像交房租，不用想什么时候买最划算

你的核心立场（必须坚守）：
1. 极其排斥学生去炒虚拟币、加杠杆、或借网贷炒股——一旦有人提，必须严厉劝退并解释风险
2. 当有人问"能不能满仓干""押注全部身家"，你会严肃说不，并给出教育性说明
3. 推荐定投宽基ETF（如沪深300ETF、纳斯达克100ETF）作为大学生入门首选
4. 会识别并警告"金融杀猪盘"套路：高收益承诺、拉群荐股、境外套利平台
5. 你的目标是培养学生的长期财商，不是教他们如何暴富

当学生问具体股票时：
- 可以解释这家公司是做什么的、基本面怎么看
- 但要提醒：单只股票风险高于ETF，建议作为ETF定投之外的"卫星仓"
- 从不给出具体的买卖时机建议，这需要专业分析工具（引导他们用系统的分析功能）

禁止项（绝对不做）：
❌ 不推荐任何加密货币（比特币/以太坊等）
❌ 不教任何杠杆操作、融资融券技巧
❌ 不提供具体的"什么时候买/卖"的择时建议
❌ 不承诺任何收益，不说"稳赚""保本"

你的回复长度：80-200字，精炼有力，不废话。"""


def _call_advisor(history: List[dict]) -> str:
    """
    同步调用 LLM 作为财商助手。

    独立于 LangGraph 工作流，使用简单的同步 invoke 调用。
    维护自己的 history，不干扰主分析流程的 state。

    Args:
        history: 完整对话历史 [{"role": "user"/"assistant", "content": str}, ...]

    Returns:
        助手回复文本
    """
    try:
        from config import config
        from langchain_core.messages import SystemMessage, HumanMessage, AIMessage as LCAIMessage

        lc_messages = [SystemMessage(content=_ADVISOR_SYSTEM_PROMPT)]
        for msg in history:
            if msg["role"] == "user":
                lc_messages.append(HumanMessage(content=msg["content"]))
            else:
                lc_messages.append(LCAIMessage(content=msg["content"]))

        provider = config.PRIMARY_LLM_PROVIDER.lower()
        if provider == "anthropic":
            from langchain_anthropic import ChatAnthropic
            llm = ChatAnthropic(
                model=config.ANTHROPIC_MODEL,
                api_key=config.ANTHROPIC_API_KEY,
                temperature=0.75,
                max_tokens=500,
            )
        else:
            from langchain_openai import ChatOpenAI
            llm = ChatOpenAI(
                model=config.OPENAI_MODEL,
                api_key=config.OPENAI_API_KEY,
                temperature=0.75,
                max_tokens=500,
            )

        response = llm.invoke(lc_messages)
        return response.content

    except Exception as e:
        return f"学长暂时离线啦，请稍后再试 😅（技术原因：{str(e)[:60]}）"


# ════════════════════════════════════════════════════════════════════
# 辅助函数
# ════════════════════════════════════════════════════════════════════

def classify_symbol(symbol: str):
    """分类标的并返回展示用元数据"""
    market_type, _ = MarketClassifier.classify(symbol)
    mapping = {
        MarketType.A_STOCK:  ("A股",  "market-a-stock",   "A股景气度 + 政策驱动策略"),
        MarketType.HK_STOCK: ("港股",  "market-hk-stock",  "港股价值投资策略"),
        MarketType.US_STOCK: ("美股",  "market-us-stock",  "美股成长价值策略"),
    }
    label, css, strategy = mapping.get(market_type, ("未知", "badge-info", "通用策略"))
    return market_type, label, css, strategy


def rec_badge(rec: str) -> str:
    css  = {"BUY": "badge-buy", "SELL": "badge-sell", "HOLD": "badge-hold"}.get(rec, "badge-info")
    text = {"BUY": "📈 买入",   "SELL": "📉 卖出",   "HOLD": "⏸ 观望"  }.get(rec, rec)
    return f'<span class="{css}">{text}</span>'


def confidence_bar(conf: float) -> str:
    pct   = int(conf * 100)
    color = "#4CAF50" if pct >= 70 else "#FF9800" if pct >= 50 else "#f44336"
    return (
        f'<div style="background:#eee;border-radius:6px;height:8px;width:100%;margin:4px 0;">'
        f'<div style="background:{color};width:{pct}%;height:8px;border-radius:6px;"></div>'
        f'</div><small style="color:#666;">{pct}% 置信度</small>'
    )


def _check_backend() -> bool:
    try:
        r = httpx.get(f"{API_BASE}/api/v1/health", timeout=3)
        return r.status_code == 200
    except Exception:
        return False


# ════════════════════════════════════════════════════════════════════
# SSE 消费器
# ════════════════════════════════════════════════════════════════════

def consume_sse(symbol: str) -> Generator[dict, None, None]:
    url    = f"{API_BASE}/api/v1/analyze"
    with httpx.stream(
        "POST", url,
        json={"symbol": symbol},
        timeout=SSE_TIMEOUT,
        headers={"Accept": "text/event-stream"},
    ) as resp:
        resp.raise_for_status()
        for raw_line in resp.iter_lines():
            if raw_line.startswith("data:"):
                json_str = raw_line[5:].strip()
                if json_str:
                    try:
                        yield json.loads(json_str)
                    except json.JSONDecodeError:
                        pass


# ════════════════════════════════════════════════════════════════════
# 渲染组件
# ════════════════════════════════════════════════════════════════════

def render_analyst_mini(title: str, icon: str, rec: str, conf: float, preview: str):
    st.markdown(
        f"""<div class="node-card node-done">
        <b>{icon} {title}</b>&nbsp;&nbsp;{rec_badge(rec)}<br>
        {confidence_bar(conf)}
        <small style="color:#555;margin-top:6px;display:block;">{preview[:120]}...</small>
        </div>""",
        unsafe_allow_html=True,
    )


def render_trade_order(order: dict):
    action      = order.get("action", "HOLD")
    symbol      = order.get("symbol", "N/A")
    qty_pct     = order.get("quantity_pct", 0)
    stop_loss   = order.get("stop_loss")
    take_profit = order.get("take_profit")
    confidence  = order.get("confidence", 0)
    rationale   = order.get("rationale", "")
    order_type  = order.get("order_type", "LIMIT")

    action_map = {
        "BUY":  ("📈 买入",    "order-buy",  "#2e7d32"),
        "SELL": ("📉 卖出",    "order-sell", "#c62828"),
        "HOLD": ("⏸ 持仓观望", "order-hold", "#f57f17"),
    }
    action_label, card_css, color = action_map.get(action, ("N/A", "order-hold", "#888"))

    st.markdown(
        f"""<div class="order-card {card_css}">
        <h3 style="color:{color};margin:0 0 12px 0;">🎯 最终交易指令</h3>
        <table style="width:100%;border-collapse:collapse;">
          <tr>
            <td style="padding:6px 0;width:50%;"><b>标的</b>: <code style="font-size:15px;">{symbol}</code></td>
            <td style="padding:6px 0;"><b>操作</b>: <span style="font-size:18px;font-weight:700;color:{color};">{action_label}</span></td>
          </tr>
          <tr>
            <td style="padding:6px 0;"><b>仓位</b>: <span style="font-size:16px;font-weight:600;">{qty_pct:.0f}%</span> 总资金</td>
            <td style="padding:6px 0;"><b>订单类型</b>: {order_type}</td>
          </tr>
          <tr>
            <td style="padding:6px 0;"><b>止损价</b>: <span style="color:#f44336;">{stop_loss if stop_loss else 'N/A'}</span></td>
            <td style="padding:6px 0;"><b>止盈价</b>: <span style="color:#4CAF50;">{take_profit if take_profit else 'N/A'}</span></td>
          </tr>
          <tr>
            <td colspan="2" style="padding:10px 0 0 0;">
              <b>综合置信度</b>: {int(confidence*100)}%<br>
              <div style="background:rgba(255,255,255,.5);border-radius:6px;height:8px;width:100%;margin:4px 0;">
                <div style="background:{color};width:{int(confidence*100)}%;height:8px;border-radius:6px;"></div>
              </div>
            </td>
          </tr>
          <tr>
            <td colspan="2" style="padding:10px 0 0 0;">
              <b>决策依据</b>:<br><span style="color:#444;">{rationale}</span>
            </td>
          </tr>
        </table>
        </div>""",
        unsafe_allow_html=True,
    )


# ════════════════════════════════════════════════════════════════════
# 侧边栏
# ════════════════════════════════════════════════════════════════════

with st.sidebar:
    # ── 品牌标题 ─────────────────────────────────────────────────
    st.markdown("""
<div style="text-align:center;padding:8px 0 4px 0;">
  <span style="font-size:28px;">🎓</span><br>
  <span style="font-size:18px;font-weight:700;color:#1a73e8;">CampusQuant</span><br>
  <span style="font-size:12px;color:#888;">校园财商智能分析平台</span>
</div>
""", unsafe_allow_html=True)

    st.markdown("---")

    # ── 后端状态 ─────────────────────────────────────────────────
    backend_ok = _check_backend()
    if backend_ok:
        st.success("✅ 后端已连接", icon=None)
    else:
        st.error("❌ 后端未启动\n`uvicorn api.server:app --port 8000`")

    st.markdown("---")

    # ── 智能搜索框 ───────────────────────────────────────────────
    st.markdown("**🔍 输入你想分析的标的**")
    st.caption("支持中文名、英文名、代码（如：茅台、英伟达、00700、AAPL）")

    raw_input = st.text_input(
        label="标的搜索",
        placeholder="输入代码、拼音或公司名（如：AAPL, 茅台, 00700）",
        label_visibility="collapsed",
    ).strip()

    # 模糊匹配转换
    symbol_input = ""
    match_hint   = ""
    if raw_input:
        matched = MarketClassifier.fuzzy_match(raw_input)
        if matched.upper() != raw_input.upper():
            # 触发了模糊匹配
            match_hint   = f"自动识别 **{raw_input}** → `{matched}`"
            symbol_input = matched
        else:
            symbol_input = matched

        # 展示匹配提示
        if match_hint:
            st.markdown(
                f'<div class="match-hint">🔎 {match_hint}</div>',
                unsafe_allow_html=True,
            )
        else:
            mtype, mlabel, _, _ = classify_symbol(symbol_input)
            if mtype != MarketType.UNKNOWN:
                st.caption(f"市场: {mlabel}  |  代码: `{symbol_input}`")
            else:
                st.warning("未能识别市场类型，请检查代码格式")

    # 不支持加密货币提示
    if raw_input and "/" in raw_input:
        st.error("⚠️ CampusQuant 不支持加密货币分析\n\n加密货币对大学生风险极高，已从系统移除。推荐先从ETF定投开始学习投资。")
        symbol_input = ""

    st.markdown("---")

    # 快速示例
    st.markdown("**快速示例**")
    col_a, col_b = st.columns(2)
    with col_a:
        if st.button("贵州茅台", use_container_width=True):
            st.session_state["_quick_sym"] = "600519.SH"
        if st.button("沪深300ETF", use_container_width=True):
            st.session_state["_quick_sym"] = "510300.SH"
        if st.button("苹果 AAPL", use_container_width=True):
            st.session_state["_quick_sym"] = "AAPL"
    with col_b:
        if st.button("腾讯控股", use_container_width=True):
            st.session_state["_quick_sym"] = "00700.HK"
        if st.button("英伟达 NVDA", use_container_width=True):
            st.session_state["_quick_sym"] = "NVDA"
        if st.button("宁德时代", use_container_width=True):
            st.session_state["_quick_sym"] = "300750.SZ"

    # 快速示例覆盖输入
    if "_quick_sym" in st.session_state and not raw_input:
        symbol_input = st.session_state.pop("_quick_sym")
        mtype, mlabel, _, _ = classify_symbol(symbol_input)
        st.info(f"已选: `{symbol_input}`  {mlabel}")

    st.markdown("---")

    run_btn = st.button(
        "🚀 开始多智能体分析",
        type="primary",
        disabled=not (symbol_input and backend_ok and symbol_input != ""),
        use_container_width=True,
    )

    st.caption("LangGraph 并行4节点 · 辩论循环≤2 · 风控重试≤2")

    st.markdown("---")
    st.markdown("""
**支持市场**
- A股（.SH / .SZ）
- 港股（.HK）
- 美股（AAPL / TSLA…）

**架构**
- LangGraph 状态机
- Chroma+BM25 混合 RAG
- FastAPI SSE 实时流
- Pydantic 结构化输出
""")

    # ════════════════════════════════════════════════════════════
    # AI 财商助手：财财学长
    # ════════════════════════════════════════════════════════════

    st.markdown("---")
    st.markdown("""
<div style="background:linear-gradient(135deg,#e3f2fd,#e8f5e9);
            border-radius:10px;padding:10px 14px;margin-bottom:8px;">
  <b>💬 财财学长</b>  <span style="font-size:12px;color:#555;">AI 财商助手</span><br>
  <span style="font-size:11px;color:#777;">有任何投资问题、不懂的金融词，都可以问我～</span>
</div>
""", unsafe_allow_html=True)

    # 渲染历史消息（最近 6 条，保持侧边栏简洁）
    recent_msgs = st.session_state.advisor_messages[-6:]
    for msg in recent_msgs:
        with st.chat_message(msg["role"],
                             avatar="🧑‍🎓" if msg["role"] == "user" else "🎓"):
            st.write(msg["content"])

    # 聊天输入框（Streamlit >= 1.31 支持在 sidebar 内使用 chat_input）
    advisor_input = st.chat_input(
        "问问财财学长…（如：市盈率是啥？能满仓吗？）",
        key="advisor_chat_input",
    )

    if advisor_input:
        # 1. 追加用户消息
        st.session_state.advisor_messages.append(
            {"role": "user", "content": advisor_input}
        )

        # 2. 调用 LLM（同步，不干扰 LangGraph 流程）
        with st.spinner("财财学长思考中…"):
            reply = _call_advisor(st.session_state.advisor_messages)

        # 3. 追加助手回复
        st.session_state.advisor_messages.append(
            {"role": "assistant", "content": reply}
        )

        # 4. Streamlit re-run 会自动刷新渲染
        st.rerun()

    # 清空对话按钮
    if st.session_state.advisor_messages:
        if st.button("清空对话记录", key="clear_advisor", use_container_width=True):
            st.session_state.advisor_messages = []
            st.rerun()


# ════════════════════════════════════════════════════════════════════
# 主区域
# ════════════════════════════════════════════════════════════════════

st.markdown("""
<div style="display:flex;align-items:center;gap:10px;margin-bottom:4px;">
  <span style="font-size:32px;">🎓</span>
  <div>
    <h1 style="margin:0;font-size:26px;">CampusQuant 校园财商智能分析</h1>
    <p style="margin:0;color:#888;font-size:13px;">
      专为大学生设计 · 多智能体驱动 · LangGraph + Chroma RAG + FastAPI SSE
    </p>
  </div>
</div>
""", unsafe_allow_html=True)

if not run_btn:
    # ── 欢迎页 ─────────────────────────────────────────────────
    st.markdown("---")

    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown("""
#### 🔍 智能标的搜索
- 输入**中文名**"英伟达"自动识别为 NVDA
- 输入**拼音/代码**均可精准匹配
- 支持 A股 / 港股 / 美股主流标的
- 不支持加密货币（保护大学生）
""")
    with col2:
        st.markdown("""
#### 🧠 多智能体分析
- **4节点并行**：基本面/技术/舆情/RAG
- **辩论机制**：分歧时自动多空辩论
- **风控把关**：大学生专属严格风控
- **本金安全第一**的决策逻辑
""")
    with col3:
        st.markdown("""
#### 💬 AI 财商助手
- 校园风格"财财学长"陪你学投资
- 用**食堂打饭**解释市盈率
- 识别并警告**金融杀猪盘**套路
- 推荐**定投ETF**作为入门方式
""")

    st.markdown("---")

    # 大学生风险提示
    st.info(
        "📌 **给同学的话**：投资是马拉松，不是百米冲刺。大学生最宝贵的资产是**时间和知识**，"
        "而不是短期暴富的运气。从定投沪深300ETF开始，把更多精力放在提升自己的能力上。"
        "有疑问可以在左侧问问**财财学长** 👈"
    )

    # 不支持加密货币的明确说明
    with st.expander("⚠️ 为什么不支持加密货币分析？"):
        st.markdown("""
**CampusQuant 不提供加密货币（Bitcoin/以太坊等）分析，原因如下：**

1. **极高波动性**：BTC 单日波动常超 10%，对本金有限的大学生风险极高
2. **杠杆陷阱**：大多数加密货币交易平台提供高倍杠杆，许多大学生因此血本无归
3. **监管风险**：中国境内加密货币交易违规，法律保护缺失
4. **诈骗高发**：加密货币领域是"杀猪盘"最高发的场景之一

**如果你已经被"炒币"诱惑，记住：**
- 任何"100%年化收益""稳赚不赔"的项目都是骗局
- 拉你进"内部群""VIP社区"荐币的，大概率是诈骗
- 有疑问请拨打 **96110**（全国反诈热线）

**更适合大学生的选择：** 定投宽基ETF，长期复利，时间才是最大的资产。
""")

    with st.expander("查看 LangGraph 图拓扑"):
        st.code("""
START → data_node
          ├─ fundamental_node (并行)  → portfolio_node
          ├─ technical_node   (并行)  → portfolio_node
          ├─ sentiment_node   (并行)  → portfolio_node
          └─ rag_node         (并行)  → portfolio_node

portfolio_node ─[冲突]──→ debate_node ─→ portfolio_node (循环≤2)
               ─[无冲突]─→ risk_node

risk_node ─[REJECTED]─→ portfolio_node (重试≤2)
          ─[APPROVED]─→ trade_executor → END
        """, language="text")

    st.markdown("---")
    st.info("👈 在左侧输入标的名称（如**茅台**、**苹果**、**腾讯**），点击「开始分析」")

else:
    # ════════════════════════════════════════════════════════════
    # 分析流程：SSE 实时渲染
    # ════════════════════════════════════════════════════════════
    if not symbol_input:
        st.warning("请在左侧输入有效的交易标的")
        st.stop()

    market_type, market_label, market_css, strategy = classify_symbol(symbol_input)

    if market_type == MarketType.UNKNOWN:
        st.error(
            f"无法识别标的 `{symbol_input}` 的市场类型。\n\n"
            "请检查格式：A股使用 600519.SH，港股使用 00700.HK，美股使用 AAPL"
        )
        st.stop()

    # 顶部标的信息栏
    st.markdown(
        f"""<div style="display:flex;align-items:center;gap:12px;margin-bottom:16px;">
        <span class="market-tag {market_css}">{market_label}</span>
        <h2 style="margin:0;">{symbol_input}</h2>
        <small style="color:#888;">策略: {strategy}</small>
        </div>""",
        unsafe_allow_html=True,
    )

    # 布局：左侧实时日志 + 右侧结果面板
    log_col, result_col = st.columns([1, 1], gap="large")

    with log_col:
        st.markdown("### 📡 实时执行日志")
        log_placeholder  = st.empty()
        prog_placeholder = st.empty()
        log_lines: list[str] = []

        def update_log(line: str, css_class: str = ""):
            log_lines.append(
                f'<span class="{css_class}">{line}</span>' if css_class else line
            )
            display = log_lines[-40:]
            log_placeholder.markdown(
                f'<div class="log-container">{"<br>".join(display)}</div>',
                unsafe_allow_html=True,
            )

    with result_col:
        st.markdown("### 📊 分析结果")
        result_placeholder = st.empty()

    # ── 状态收集 ─────────────────────────────────────────────
    collected: dict = {
        "fundamental": None,
        "technical":   None,
        "sentiment":   None,
        "debate":      None,
        "risk":        None,
        "order":       None,
        "latest_price": None,
        "tech_signal":  None,
    }

    # ── 节点进度追踪 ──────────────────────────────────────────
    node_order = [
        ("data_node",        "数据情报员"),
        ("rag_node",         "RAG 知识检索"),
        ("fundamental_node", "基本面分析师"),
        ("technical_node",   "技术分析师"),
        ("sentiment_node",   "舆情分析师"),
        ("portfolio_node",   "基金经理"),
        ("debate_node",      "多空辩论"),
        ("risk_node",        "风控官（大学生专属严格风控）"),
        ("trade_executor",   "交易指令生成"),
    ]
    node_status: dict[str, str] = {n: "pending" for n, _ in node_order}

    def render_progress():
        icons = {"pending": "⬜", "running": "🔄", "done": "✅"}
        rows  = []
        for node_key, label in node_order:
            status = node_status.get(node_key, "pending")
            if node_key == "debate_node" and status == "pending":
                continue
            rows.append(f"{icons.get(status,'⬜')} **{label}**")
        prog_placeholder.markdown("  \n".join(rows))

    render_progress()

    # ── 结果面板逐步刷新 ────────────────────────────────────
    def refresh_result_panel():
        with result_placeholder.container():
            if collected["latest_price"]:
                m1, m2 = st.columns(2)
                m1.metric("最新价格", f"{collected['latest_price']:.4g}")
                m2.metric("技术信号", collected.get("tech_signal", "N/A"))

            analysts_done = sum(
                1 for k in ("fundamental", "technical", "sentiment")
                if collected[k] is not None
            )
            if analysts_done > 0:
                st.markdown("---")
                st.markdown("**分析师研判**")

            if collected["fundamental"]:
                r = collected["fundamental"]
                render_analyst_mini("基本面分析师", "📈",
                    r.get("recommendation", "HOLD"),
                    r.get("confidence", 0.5),
                    r.get("reasoning", ""))
            if collected["technical"]:
                r = collected["technical"]
                render_analyst_mini("技术分析师", "📊",
                    r.get("recommendation", "HOLD"),
                    r.get("confidence", 0.5),
                    r.get("reasoning", ""))
            if collected["sentiment"]:
                r = collected["sentiment"]
                render_analyst_mini("舆情分析师", "💬",
                    r.get("recommendation", "HOLD"),
                    r.get("confidence", 0.5),
                    r.get("reasoning", ""))

            if collected["debate"]:
                d = collected["debate"]
                st.markdown("---")
                st.markdown(
                    f"""⚖️ **辩论裁决**: {rec_badge(d.get('resolved_recommendation','HOLD'))}
                    &nbsp;&nbsp;置信度 {d.get('confidence_after_debate', 0):.0%}""",
                    unsafe_allow_html=True,
                )
                st.caption(f"决定因素: {d.get('deciding_factor', '')}")

            if collected["risk"]:
                r = collected["risk"]
                st.markdown("---")
                approval = r.get("approval_status", "N/A")
                emoji    = {"APPROVED": "✅", "CONDITIONAL": "⚠️", "REJECTED": "❌"}.get(approval, "?")
                st.markdown(
                    f"{emoji} **风控（大学生专属）**: {approval} | "
                    f"风险 {r.get('risk_level', 'N/A')} | "
                    f"仓位 {r.get('position_pct', 0):.0f}%"
                )

            if collected["order"]:
                st.markdown("---")
                render_trade_order(collected["order"])

    # ── 消费 SSE 流 ──────────────────────────────────────────
    update_log(f"🚀 正在连接 FastAPI 后端 ({API_BASE})...", "log-success")

    error_occurred = False
    try:
        for event_data in consume_sse(symbol_input):
            ev_type = event_data.get("event", "")
            node    = event_data.get("node", "")
            message = event_data.get("message", "")
            data    = event_data.get("data", {})
            seq     = event_data.get("seq", 0)

            timestamp = event_data.get("timestamp", "")[:19].replace("T", " ")
            log_css   = ""
            if ev_type in ("node_complete", "trade_order", "complete"):
                log_css = "log-success"
            elif ev_type in ("conflict", "debate"):
                log_css = "log-debate"
            elif ev_type in ("risk_check", "risk_retry"):
                log_css = "log-risk"
            elif ev_type == "error":
                log_css = "log-error"

            update_log(f"[{seq:02d}] {message}", log_css)

            if ev_type == "node_start" and node in node_status:
                node_status[node] = "running"
                render_progress()
            elif ev_type in ("node_complete", "trade_order", "debate", "risk_check"):
                if node in node_status:
                    node_status[node] = "done"
                    render_progress()

            if ev_type == "node_complete" and node == "data_node":
                collected["latest_price"] = data.get("latest_price")
                collected["tech_signal"]  = data.get("tech_signal")
            elif ev_type == "node_complete" and node == "fundamental_node":
                collected["fundamental"] = {
                    "recommendation": data.get("recommendation"),
                    "confidence":     data.get("confidence", 0.5),
                    "reasoning":      data.get("reasoning_preview", ""),
                }
            elif ev_type == "node_complete" and node == "technical_node":
                collected["technical"] = {
                    "recommendation": data.get("recommendation"),
                    "confidence":     data.get("confidence", 0.5),
                    "reasoning":      data.get("signal_strength", ""),
                }
            elif ev_type == "node_complete" and node == "sentiment_node":
                collected["sentiment"] = {
                    "recommendation": data.get("recommendation"),
                    "confidence":     data.get("confidence", 0.5),
                    "reasoning":      "舆情分析完成",
                }
            elif ev_type == "conflict":
                node_status["debate_node"] = "running"
                render_progress()
                update_log("⚡ 触发多空辩论机制...", "log-debate")
            elif ev_type == "debate":
                node_status["debate_node"] = "done"
                render_progress()
                collected["debate"] = data
            elif ev_type == "risk_check":
                collected["risk"] = data
            elif ev_type == "risk_retry":
                collected["risk"] = data
                update_log("🔄 风控拒绝，基金经理进入修订模式...", "log-warning")
            elif ev_type == "trade_order":
                collected["order"] = data
                node_status["trade_executor"] = "done"
                render_progress()
            elif ev_type == "complete":
                if data.get("trade_order"):
                    collected["order"] = data["trade_order"]
            elif ev_type == "error":
                error_occurred = True
                update_log(f"❌ 错误: {message}", "log-error")
                st.error(f"分析过程发生错误: {message}")
                break

            refresh_result_panel()
            time.sleep(0.05)

    except httpx.ConnectError:
        st.error(
            f"无法连接到 FastAPI 后端 ({API_BASE})。\n\n"
            "请确保已运行:\n```\nuvicorn api.server:app --host 127.0.0.1 --port 8000\n```"
        )
        error_occurred = True
    except httpx.ReadTimeout:
        st.error("请求超时，分析时间过长。请检查后端日志。")
        error_occurred = True
    except Exception as e:
        st.error(f"未预期错误: {e}")
        error_occurred = True

    # ── 最终状态 ────────────────────────────────────────────
    if not error_occurred:
        update_log("━" * 40, "log-success")
        final_action = collected.get("order", {}).get("action", "N/A") if collected.get("order") else "N/A"
        update_log(
            f"✅ 分析完成！最终建议: {final_action}  {symbol_input}",
            "log-success",
        )
        refresh_result_panel()

        # 提示学生风险意识
        if final_action == "BUY":
            st.info(
                "📌 **学长提醒**：系统给出买入建议，不代表一定会涨。"
                "请严格遵守建议的仓位比例（≤总资金10-15%），记住止损价位，量力而行。"
                "有疑问可以问左侧的**财财学长** 👈"
            )

        with st.expander("📋 查看完整执行日志"):
            for line in log_lines:
                st.markdown(
                    f'<span style="font-family:monospace;font-size:12px;">{line}</span>',
                    unsafe_allow_html=True,
                )
