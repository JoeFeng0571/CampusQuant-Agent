# CampusQuant AI 投研平台升级方案

> **版本**：v2 · 2026-04-20
> **定位**：`CampusQuant AI 投研平台`。面向校园场景的"学习模式"作为**应用层延伸**，不改变产品主线定位。
>
> **背景**：
> - 指导老师建议加强"从理论到实践的完整体验"（知识→分析→模拟→复盘）
> - 同时需要保证算法层的技术深度与专业性，避免向"教育产品"倾斜
> - 因此本方案采用**分层结构**：算法层（核心技术）→ 研报层（结构化输出）→ 应用层（校园场景功能）

---

## 目录

1. [设计原则与分层结构](#一设计原则与分层结构)
2. [第一章 · 算法层升级](#二第一章算法层升级)
3. [第二章 · 研报深化（Agent 输出结构化）](#三第二章研报深化agent-输出结构化)
4. [第三章 · 校园应用层（学习模式）](#四第三章校园应用层学习模式)
5. [实施路线图与工作量](#五实施路线图与工作量)
6. [演示脚本](#六演示脚本)
7. [风险与取舍](#七风险与取舍)

---

## 一、设计原则与分层结构

### 1.1 命名与叙事
- **产品名称**：`CampusQuant AI 投研平台`
- **一句话介绍**：基于 LangGraph 的多 Agent 投研系统，覆盖 A股/港股/美股，内置混合 RAG 与量化因子研究，并面向校园场景提供学习模式。

### 1.2 分层结构
```
┌─────────────────────────────────────────────────────┐
│         CampusQuant AI 投研平台                      │
├─────────────────────────────────────────────────────┤
│                                                     │
│  第一章 · 算法层（核心技术）                         │
│    ├─ 因子库 + IC/IR 分析                           │
│    ├─ 置信度校准（Calibration）                     │
│    ├─ 组合优化节点（Markowitz / 风险平价）          │
│    ├─ Walk-forward 回测框架                         │
│    └─ 事件研究法（CAR，可选）                       │
│                                                     │
│  第二章 · 研报深化（结构化输出 × 教学友好）          │
│    ├─ 推理链卡片（数据→概念→判断→结论）              │
│    ├─ 术语跳转                                      │
│    └─ 引文来源可视化（RAG citation）                 │
│                                                     │
│  第三章 · 校园应用层（学习模式）                     │
│    ├─ 学习进度系统                                  │
│    ├─ 模块扩充（行为金融/宏观/纪律）                 │
│    ├─ 案例库 + 计算器                               │
│    ├─ 知识问答（RAG 前端化）                        │
│    └─ 规则化模拟盘（止盈止损强制 + 周度复盘）        │
│                                                     │
└─────────────────────────────────────────────────────┘
```

---

## 二、第一章 · 算法层升级

> 本章每一项都是独立的量化/机器学习工作，有明确的方法论和输出。

### 2.1 因子库 + IC/IR 分析（**最高优先级**）

**核心价值**：把现有"多 Agent 打分"抽象为因子工程，建立量化投研的基本研究框架。

**内容**：
- 构建 5 类因子（**在 `factors/` 新建目录**）：
  - **价值因子**：BP（账面市值比）、EP、SP、股息率
  - **质量因子**：ROE、ROIC、毛利率稳定性、经营现金流/净利润
  - **动量因子**：过去 1 月 / 3 月 / 12 月 return，反转因子
  - **波动率因子**：过去 60 日 vol、下行风险
  - **情绪因子**：基于财联社新闻的情绪打分 + 换手率
- **IC 分析**：每个因子在 A 股池（沪深 300 或中证 500）上逐日计算 rank IC，输出：
  - IC 时间序列图
  - IC 均值、IC_IR、IC 胜率
  - IC 衰减曲线（t, t+5, t+10, t+20 天）
- **因子正交化**：对强相关因子做施密特正交（`statsmodels` 或手写）
- **因子合成**：等权 vs IC 加权 vs IC_IR 加权三种合成方式对比

**交付物**：
- [ ] `factors/` 目录：`value.py` / `quality.py` / `momentum.py` / `volatility.py` / `sentiment.py`
- [ ] `factors/ic_analyzer.py`：核心 IC 计算 + 衰减
- [ ] `factors/combine.py`：三种合成方式
- [ ] `bench/factor_research.ipynb`：研究笔记本 + 图表
- [ ] `FACTOR_RESEARCH.md`：方法论与结论报告

**工时**：3 人日

---

### 2.2 置信度校准（Confidence Calibration）

**核心价值**：v2.3 已加入"置信度惩罚"机制，但尚未量化评估校准质量。补齐 Brier / ECE / 可靠性图全套评估体系。

**内容**：
- 收集历史 Agent 输出的 `confidence ∈ [0, 1]` 与事后收益结果
- 计算 **Brier Score**、**ECE（Expected Calibration Error）**
- 绘制**可靠性图**（Reliability Diagram）：x 轴预测置信度分箱，y 轴实际胜率
- 若模型过度自信，应用 **Platt Scaling** 或 **Isotonic Regression** 做再校准
- 校准前后对比，写入 Agent 输出的 `confidence_calibrated` 字段

**交付物**：
- [ ] `eval/calibration.py`：Brier / ECE / Reliability Diagram
- [ ] `eval/calibration_report.ipynb`：校准前后对比
- [ ] `graph/nodes.py`：输出 `confidence_calibrated` 字段
- [ ] `CALIBRATION_REPORT.md`：评估方法论文档

**工时**：2 人日

---

### 2.3 组合优化节点（Portfolio Optimizer）

**核心价值**：
- 将经典的 Markowitz 均值方差优化引入 LangGraph 决策链路
- 对应用层贡献：大学生能直观看到"仓位如何被量化分配"，衔接老师要求的"理财规则完善"

**内容**：
- 新增 `graph/nodes.py::portfolio_optimizer_node`
- 输入：候选股票列表 + 各自 Agent 分析结果
- 三种优化方法：
  - **Markowitz 均值方差**（`cvxpy` 或 `scipy.optimize`）
  - **风险平价**（Risk Parity）
  - **Black-Litterman**（将 Agent 观点作为 view matrix，是本项目特色结合点）
- 约束条件：单标的 ≤ 30%、行业集中度 ≤ 50%、最小仓位 5%
- 输出：权重向量 + 预期收益/波动率/夏普比

**接入图**：`portfolio_node` 生成候选池 → `portfolio_optimizer_node` 分配权重 → `risk_node` 审核。

**交付物**：
- [ ] `graph/nodes.py::portfolio_optimizer_node`
- [ ] `graph/state.py::OptimizedPortfolio` Pydantic 模型
- [ ] `graph/builder.py` 接入新节点
- [ ] `tests/test_portfolio_optimizer.py`
- [ ] `PORTFOLIO_OPTIMIZER.md`：三种方法对比 + Black-Litterman 如何结合 Agent 观点

**工时**：2 人日

---

### 2.4 Walk-forward 回测框架升级

**核心价值**：现有 `bench/backtest/` 基本可用，但未强制 walk-forward，存在未来函数风险。升级后回测结论更具说服力。

**内容**：
- 引入时间序列 **Walk-forward** 切分（滚动训练窗 + 非重叠测试窗）
- 实现指标：年化收益、年化波动、最大回撤、夏普、卡玛、胜率、盈亏比
- 基准对比：沪深 300 / 中证 500 / 等权组合
- 交易成本建模（佣金 0.025% + 印花税 0.1% + 滑点 0.05%）
- 输出权益曲线图 + 策略 vs 基准对比

**交付物**：
- [ ] `bench/backtest/walk_forward.py`：核心切分逻辑
- [ ] `bench/backtest/metrics.py`：完整指标集
- [ ] `bench/backtest/report.py`：生成 HTML/PDF 报告
- [ ] `BACKTEST_METHODOLOGY.md`：方法论说明

**工时**：2 人日

---

### 2.5 事件研究法（CAR 分析，选做）

**核心价值**：已有财联社新闻数据，做**累计超额收益（CAR）**分析是事件驱动策略的经典方法。

**内容**：
- 对重大新闻事件（业绩超预期 / 增减持 / 政策等）做事件研究
- 事件窗口：[-5, +5] 日
- 估计窗口：[-60, -10] 日，用市场模型算预期收益
- 计算 AR（异常收益）、CAR（累计异常收益）、t 检验
- 识别"值得交易"的事件类型

**交付物**：
- [ ] `factors/event_study.py`
- [ ] `bench/event_study.ipynb`
- [ ] `EVENT_STUDY_REPORT.md`

**工时**：2 人日（可放到 P3 或砍掉）

---

### 2.6 Agent 集成加权（选做）

**核心价值**：多 Agent 投票不应等权，应基于历史命中率加权（Dawid-Skene 弱监督思路）。

**内容**：
- 统计每个 Agent 过去 N 次预测的命中率
- 加权公式：`weight_i = log(p_i / (1 - p_i))`（logit 权重）
- 应用到辩论节点 / 组合决策

**工时**：2 人日（P3 可选）

---

## 三、第二章 · 研报深化（Agent 输出结构化）

> 这一层同时服务于算法侧（Prompt 工程与结构化输出）和应用侧（教学友好）。

### 3.1 推理链卡片（Reasoning Chain Card）

Agent 输出从"纯文本结论"升级为**结构化推理链**：

```json
{
  "conclusion": "建议持有",
  "confidence": 0.78,
  "confidence_calibrated": 0.71,
  "reasoning_chain": [
    {
      "step": 1,
      "type": "data",
      "content": "2024Q3 营收 345 亿，同比 +12%",
      "source": "akshare::stock_financial_abstract"
    },
    {
      "step": 2,
      "type": "concept",
      "content": "营收增速放缓至双位数以下时的消费龙头估值回归",
      "term_refs": ["营收增速", "估值回归"]
    },
    {
      "step": 3,
      "type": "judgment",
      "content": "当前 PE 23.5 位于近 5 年 68% 分位，不便宜但未高估",
      "term_refs": ["PE", "历史分位"]
    },
    {
      "step": 4,
      "type": "conclusion",
      "content": "估值合理 + 基本面稳健 → 持有观望"
    }
  ]
}
```

前端 `trade.html` 渲染为**可折叠的四步卡片**，每步不同颜色：数据（蓝）/ 概念（紫）/ 判断（橙）/ 结论（绿）。

**交付物**：
- [ ] `graph/state.py::ReasoningStep` Pydantic 模型
- [ ] `graph/nodes.py` 的 `_PROMPTS` 改造（要求 LLM 按此结构输出）
- [ ] `trade.html` 渲染逻辑 + CSS

**工时**：2 人日

---

### 3.2 术语跳转（已确认实施）

**改造范围**：所有 Agent 输出里的财务/技术/风控术语可点击，hover 显示释义，点击跳 `resources.html` 对应锚点。

**首批术语词典**（~30 个，放 `assets/data/terms.json`）：

| 类别 | 术语 |
|---|---|
| 估值 | PE、PB、PS、PEG、历史分位、安全边际、DCF、股息率 |
| 财务 | ROE、ROIC、毛利率、净利率、经营现金流、资产负债率、杜邦分析、商誉 |
| 技术 | MA60、MACD、RSI、布林带、支撑位、压力位、成交量背离、均线金叉死叉 |
| 风控 | 止损位、止盈位、仓位、最大回撤、夏普比率、凯利公式、波动率 |
| 宏观 | CPI、PMI、社融、LPR、十年期国债收益率、M2 |

**术语词典格式**：
```json
{
  "PE": {
    "full_name": "市盈率 Price-to-Earnings Ratio",
    "definition": "股价 / 每股收益，反映投资者愿为每单位利润支付的价格",
    "anchor": "/resources.html#valuation/pe-ratio",
    "level": "beginner"
  }
}
```

**交付物**：
- [ ] `assets/data/terms.json`
- [ ] `assets/js/term-tooltip.js`（通用 tooltip 组件）
- [ ] `graph/nodes.py` prompt 要求 LLM 用 `{{term:PE}}` 标记术语（后处理转 `<a>`）
- [ ] `trade.html` 引入 term-tooltip.js

**工时**：2 人日

---

### 3.3 引文来源可视化（RAG Citation）

v2.3 已实现引文合并，但前端没有充分展示。

**内容**：
- Agent 输出里每个关键论据挂一个 `citation_id`
- 前端悬停/点击显示原文片段 + 出处（研报标题 / 新闻时间）
- 强化 RAG 可解释性与专业感

**交付物**：
- [ ] `tools/knowledge_base.py`：返回 citation metadata
- [ ] `trade.html`：引文悬浮卡片样式
- [ ] 演示脚本

**工时**：1 人日

---

## 四、第三章 · 校园应用层（学习模式）

> 老师要求的"从理论到实践的完整体验"在这一章落地。这一层面向 C 端用户（大学生），是产品完整度的补齐。

### 4.1 学习进度系统

**数据模型**（`db/models.py`）：

```python
class LearningProgress(Base):
    __tablename__ = "learning_progress"
    id          = Column(Integer, primary_key=True)
    user_id     = Column(Integer, ForeignKey("users.id"), index=True)
    module_id   = Column(String(64))
    section_id  = Column(String(64))
    status      = Column(String(16))  # reading / done
    quiz_score  = Column(Integer, nullable=True)
    completed_at= Column(DateTime, nullable=True)

class LearningBadge(Base):
    __tablename__ = "learning_badges"
    id        = Column(Integer, primary_key=True)
    user_id   = Column(Integer, ForeignKey("users.id"))
    badge_id  = Column(String(64))
    earned_at = Column(DateTime, default=func.now())
```

**API**：
```
GET  /api/v1/learning/progress
POST /api/v1/learning/progress
POST /api/v1/learning/quiz/submit
GET  /api/v1/learning/badges
GET  /api/v1/learning/recommendation
```

**前端**：
- `home.html` 进度卡去掉硬编码假数据，接真实 API
- 每个 `learn_*.html` 章节末尾加"✅ 标记已读" + 3–5 题小测

**工时**：3 人日

---

### 4.2 模块扩充（新增 3 个模块）

现有覆盖：财商入门 / 股票 ETF / 财报 / 估值 / 风控 / 策略 / 防骗。新增：

| 新模块 | 页面 | 核心章节 |
|---|---|---|
| **行为金融** | `learn_behavior.html` | 锚定效应 / 损失厌恶 / 过度自信 / FOMO / 反制清单 |
| **宏观框架** | `learn_macro.html` | 利率 / 汇率 / CPI-PMI-社融 / 政策周期 |
| **交易纪律与复盘** | `learn_discipline.html` | 仓位管理 / 止损止盈 / 最大回撤 / 交易日志 / 复盘模板 |

（**中国家庭理财** 和 **AI 分析边界** 两模块降级为选做，视时间放 P3）

**工时**：6 人日（每模块 ~2 人日）

---

### 4.3 案例库 + 计算器

**`/cases.html` · 案例库**（每周 1 篇）：

| # | 策略 | 标的 | 侧重 |
|---|---|---|---|
| 1 | 价值投资 | 招商银行 | 低 PB + 高 ROE + 股息率 |
| 2 | 趋势跟随 | 宁德时代 | 均线系统 + 顶背离 |
| 3 | 均值回归 | 煤炭板块 | 极端估值分位 |
| 4 | 财报排雷 | （某雷股）| 商誉减值 + 现金流恶化 |
| 5 | 估值陷阱 | （某低估周期股）| PE 低 ≠ 便宜 |

每个案例页：背景 → 数据 → 用学过的知识点推理 → 结论 → "AI 分析这只股" 跳 `trade.html`。

**`/tools/calculator.html` · 计算器**：复利 / 定投 / 仓位 / 最大回撤。

**工时**：3 人日（前 3 个案例 + 计算器）

---

### 4.4 知识问答（RAG 前端化）

**新增页面**：`/ask.html`

**API**：`POST /api/v1/knowledge/ask` → `{answer, citations, suggested_modules}`

对接已有 `tools/knowledge_base.py`（Chroma + BM25 混合）。

**工时**：1 人日

---

### 4.5 模拟盘提示化设计 + 周度复盘

> **设计原则**：模拟盘**不强制拦截任何交易**。违规行为会被**可视化提示 + 知识跳转 + 记录到复盘**，但最终是否提交由用户自己决定。模拟就是用来犯错学习的，家长式拦截反而削弱了"用真实决策体验后果"的教育价值。

**下单表单（前端 `trade.html`）**：用户只需填 3 项：
- `quantity` — 交易手数
- `stop_loss_pct` — 止损比例（建议填写，不强制）
- `take_profit_pct` — 止盈比例（建议填写，不强制）

**仓位自动计算**：
```
position_pct = quantity × current_price / account_total_value × 100%
```

**仓位渐变色指示条**（前端实时绘制）：

用一条横向进度条，底色为 **绿→黄→红** 的线性渐变，用户当前仓位对应位置显示一个指示游标。
```
0%                    15%                  30%                    50%+
┃━━━━━━━━━━━━━━━━━━━━━┃━━━━━━━━━━━━━━━━━━━━┃━━━━━━━━━━━━━━━━━━━━━┃
绿                    黄绿                  橙                    红
                              ▲ (当前 22%)
```
CSS 实现：
```css
.position-gauge {
  background: linear-gradient(90deg,
    #5eead4 0%,      /* 绿 */
    #a7f3d0 15%,     /* 黄绿 */
    #fbbf24 30%,     /* 橙黄 */
    #fb923c 45%,     /* 橙红 */
    #ef4444 70%      /* 红 */
  );
}
```
游标下方显示当前百分比 + 一句自适应文案（如 "仓位稳健"、"接近单标的建议上限"、"已超激进型上限"）。

**知识跳转提示**（不拦截，仅展示）：

触发条件命中时，表单下方展开一张小卡片（可关闭），显示相关章节的 1-2 句摘要 + "展开学习 →" 跳转链接。用户可以**阅读后继续下单**，也可以**关闭卡片直接下单**。

| 触发条件 | 提示卡片 |
|---|---|
| 仓位 > 30%（稳健）/ 50%（激进） | "单标的仓位过高，波动对账户冲击大 → 仓位管理" |
| 未填止损 | "没有止损的交易等于把损失上限交给市场 → 止损规则" |
| `take_profit_pct < stop_loss_pct` | "盈亏比小于 1 时，胜率 60% 以上才不亏 → 盈亏比" |
| 同标的当日 ≥ 3 次开平仓 | "频繁交易会放大情绪成本和手续费 → 行为金融·过度交易" |

**后端职责**（`api/mock_exchange.py`）：
- **正常接单**，不做任何拒绝
- **记录违规标记** 到订单表（新增 `warnings: list[str]` 字段）——供周度复盘使用
- 同一规则用同一公式在前端+后端都算一次，防止前端绕过但不影响下单本身

**周度复盘**（新增 `graph/nodes.py::review_node`）：
- 胜率 / 盈亏比 / **止损执行率**（此处"未填止损次数/总交易"才真正被分析）
- 情绪化交易识别（追涨 / 割肉次数 / 频繁交易次数）
- **违规提示触发统计**：哪类规则被忽略最多 → 针对性推荐学习章节
- 投资风格标签
- 推荐下周学习章节

**工时**：3 人日

---

## 五、实施路线图与工作量

### 5.1 阶段划分

| 阶段 | 内容 | 工时 | 验收标志 |
|---|---|---|---|
| **P0 · 算法核心 + 研报关键** | 因子库+IC / 置信度校准 / 组合优化节点 / 推理链+术语跳转 | 9 人日 | 因子 IC 报告 + 校准报告 + 组合优化 + 带术语跳转的研报 |
| **P1 · 进度与模块** | 学习进度系统 / 3 新模块 / 知识图谱可视化 | 9 人日 | 完整课程体系 + 真实进度 |
| **P2 · 研报完善 + 案例 + 问答** | 引文可视化 / 案例库（3 篇） / 计算器 / `/ask.html` | 5 人日 | 报告可追溯到原文 + 大学生能自测工具 |
| **P3 · 回测框架 + 模拟盘提示 + 复盘** | Walk-forward / 仓位渐变色+知识跳转提示 / 周度复盘 | 7 人日 | 完整闭环：学→练→盘 |
| **P4 · 选做** | 事件研究法 / Agent 集成加权 / 中国家庭理财 / AI 边界 | 6 人日 | 扩展增强项 |

**合计**：P0–P3 共 **30 人日**，建议 6 周完成（兼顾其他工作）。

### 5.2 关键路径

```
Week 1-2: P0 算法核心
Week 3:   P1 学习进度
Week 4:   P1 模块扩充 + P2 案例库
Week 5:   P2 问答 + P3 回测框架
Week 6:   P3 模拟盘规则 + 复盘 + 整体串联
```

### 5.3 建议起手顺序

**第一刀**：`2.3 组合优化节点`（2 人日）
- 理由：**同时覆盖算法层（经典量化方法）与应用层（仓位规则）**，一石二鸟
- 成果：Markowitz + 风险平价 + Black-Litterman 全落地

**第二刀**：`2.1 因子库 + IC`（3 人日）
- 理由：**独立的量化研究工作**，产出 `FACTOR_RESEARCH.md` 作为技术文档

**第三刀**：`3.1 推理链卡片 + 3.2 术语跳转`（4 人日）
- 理由：演示视觉冲击最强，**算法结构化与教学友好双赢**

---

## 六、演示脚本

### 6.1 项目一句话介绍

> "CampusQuant 是一个 AI 投研平台。技术栈上是 **LangGraph 多 Agent 并行编排 + 多空辩论收敛机制**，数据层做了 **Chroma + BM25 混合 RAG**，算法层补了**因子库 IC 研究、置信度校准、组合优化**三块量化工作。产品层面向校园场景做了学习模式——术语跳转、案例库、规则化模拟盘。"

### 6.2 技术展示顺序（5 分钟版本）

1. **LangGraph 编排**：并行节点 + 辩论循环（≤2 轮）+ 风控重试（≤2 次）+ 防死循环计数器
2. **混合 RAG**：Chroma 稠密（dashscope embedding）+ BM25 稀疏 + v2.3 引文合并和置信度惩罚
3. **因子研究**：5 类因子 × IC_IR × 衰减曲线 × 正交化 × 三种合成
4. **置信度校准**：Brier / ECE / Reliability Diagram，Platt Scaling 再校准
5. **组合优化**：Markowitz / 风险平价 / Black-Litterman（把 Agent 观点作为 view matrix 是本项目特色）
6. **回测**：Walk-forward，避免未来函数 + 交易成本建模

### 6.3 产品完整度演示（5 分钟版本）

1. 打开 `home.html` 展示真实学习进度 + 徽章
2. 点任一章节 → 读完 → 做小测 → 进度自动更新
3. 进入 `trade.html` 分析某只股 → 看到推理链卡片 + 术语可点击跳转
4. 打开 `cases.html` → 看"用价值投资看招商银行"案例
5. 下模拟订单时仓位渐变条从绿过渡到红，未填止损弹出章节提示卡片（但不拦截）
6. 进入 `ask.html` → 问"PE 和 PB 区别" → RAG 答案 + 引文来源

---

## 七、风险与取舍

### 7.1 定位一致性
- **不改名字**：保持 `CampusQuant AI 投研平台`
- **教育模块位置**：README/简介首行是"AI 投研平台"，学习模式描述为"面向校园场景的应用层功能"

### 7.2 实施风险
- **因子库数据量**：A 股历史数据建议至少 3 年覆盖，akshare 限速要注意
- **Calibration 样本不足**：初期 Agent 历史预测可能不够做校准，可用**合成数据或 K 折交叉**兜底
- **cvxpy 依赖**：组合优化引入 cvxpy 需在 requirements.txt 登记 + 部署时验证

### 7.3 要砍的功能（不做）
- ❌ 游戏化排行榜（引导做题而非真懂）
- ❌ 手机原生 App（PWA 够用）
- ❌ 直播课（非 MVP）
- ❌ 真实交易所对接（硬规则，永不）

### 7.4 可延后的选做项
- 事件研究法（CAR）— 算法扩展包
- Agent 集成加权 — 等 Calibration 做完再看必要性
- 中国家庭理财 / AI 边界模块 — 学习模式扩展，有时间再写

---

## 八、附录：文件清单（交付物索引）

**新增代码目录**：
- `factors/` — 因子库
- `eval/` — 评估工具（校准、回测指标）

**新增/修改文件**：
- `graph/state.py` — `ReasoningStep` / `OptimizedPortfolio` 模型
- `graph/nodes.py` — `portfolio_optimizer_node` / `review_node` / prompt 改造
- `graph/builder.py` — 接入新节点
- `api/server.py` — 学习进度 API / 知识问答 API
- `api/mock_exchange.py` — 下单规则拦截
- `db/models.py` — `LearningProgress` / `LearningBadge`
- `tools/knowledge_base.py` — citation metadata
- `bench/backtest/` — Walk-forward 升级
- `tests/` — 对应单元测试

**新增前端页面**：
- `cases.html` / `ask.html` / `curriculum.html`
- `learn_behavior.html` / `learn_macro.html` / `learn_discipline.html`
- `tools/calculator.html`

**新增技术文档**：
- `FACTOR_RESEARCH.md`
- `CALIBRATION_REPORT.md`
- `PORTFOLIO_OPTIMIZER.md`
- `BACKTEST_METHODOLOGY.md`

**配置/数据**：
- `assets/data/terms.json` — 术语词典
- `assets/data/curriculum.json` — 课程元数据

---

**下一步**：按 `5.3 建议起手顺序` 开工，从**组合优化节点**起手。确认后开始 P0。
