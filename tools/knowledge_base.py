"""
tools/knowledge_base.py — 高阶混合 RAG 知识检索工具 (v2.0)

架构升级说明：
  旧版：FAISS + 硬编码占位符文档（仅种子文本，无外部文件支持）
  新版：现代混合 RAG，三大核心能力全面升级

══════════════════════════════════════════════════════════════════════
  混合召回架构总览
══════════════════════════════════════════════════════════════════════

  ┌─────────────────────────────────────────────────────────────────┐
  │              本地知识库（data/docs/ 研报/PDF/TXT）               │
  │                           │                                     │
  │   ┌───────────────────────┴───────────────────────┐            │
  │   │                                               │            │
  │   ▼                                               ▼            │
  │  [稠密向量检索] Chroma DB                    [稀疏关键词检索]   │
  │  + OpenAI Embeddings                         BM25Retriever     │
  │  ─────────────────────                      ──────────────────  │
  │  • 语义模糊匹配                              • 精准词匹配        │
  │  • 捕捉概念相似度                            • 专有名词可靠检索   │
  │  • 同义词/近义词理解                         • 股票代码/机构名   │
  │  • 持久化至 data/chroma_db/                  • rank_bm25 驱动   │
  │                   │                                │            │
  │                   └────────────┬───────────────────┘            │
  │                                ▼                                │
  │                    EnsembleRetriever                            │
  │                  （BM25 50% + Chroma 50%）                      │
  │                  RRF 排名融合 → 去重 → Top-K                    │
  └────────────────────────────────┬────────────────────────────────┘
                                   │
  ┌────────────────────────────────▼────────────────────────────────┐
  │              实时联网搜索（DuckDuckGoSearchRun）                 │
  │  • 补充知识库时效性盲区（突发新闻/最新财报/实时行情评论）         │
  │  • duckduckgo-search 驱动，无需 API Key                        │
  └────────────────────────────────┬────────────────────────────────┘
                                   │
  ┌────────────────────────────────▼────────────────────────────────┐
  │              @tool search_knowledge_base 统一出口               │
  │  本地研报深度片段 + 实时网络搜索摘要 → 格式化 RAG 上下文字符串   │
  │  直接注入 LLM Prompt，供 PortfolioManager / RAG 节点消费        │
  └─────────────────────────────────────────────────────────────────┘

══════════════════════════════════════════════════════════════════════
  目录约定与持久化策略
══════════════════════════════════════════════════════════════════════

  data/docs/       ← 将研报 PDF/TXT/Markdown 放入此目录
  data/chroma_db/  ← Chroma 向量库持久化存储（自动创建，勿手动删除）

  首次启动：读取 data/docs/ 所有文件 + 内置种子 → Embedding → 写入 Chroma
  后续启动：直接加载 Chroma，跳过 Embedding，秒级就绪
  新增文档：init_knowledge_base(force_rebuild=True) 重建索引

══════════════════════════════════════════════════════════════════════
  新增依赖（需手动安装，旧 faiss-cpu 可保留也可移除）
══════════════════════════════════════════════════════════════════════

  pip install chromadb pypdf rank_bm25 duckduckgo-search
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import List, Optional

from langchain_core.documents import Document
from langchain_core.tools import tool
from langchain_text_splitters import RecursiveCharacterTextSplitter
from loguru import logger


# ════════════════════════════════════════════════════════════════════
# 目录常量 — 自动创建，首次运行无需手动建目录
# ════════════════════════════════════════════════════════════════════

_BASE_DIR   = Path(__file__).parent.parent           # 项目根目录
_DOCS_DIR   = _BASE_DIR / "data" / "docs"            # 研报/PDF 存放目录
_CHROMA_DIR = _BASE_DIR / "data" / "chroma_db"       # Chroma 持久化目录
_BM25_PKL   = _BASE_DIR / "data" / "bm25_index.pkl"  # BM25 序列化索引（离线建库产物）
_COLLECTION = "trading_knowledge"                     # Chroma 集合名称

_DOCS_DIR.mkdir(parents=True, exist_ok=True)
_CHROMA_DIR.mkdir(parents=True, exist_ok=True)


# ════════════════════════════════════════════════════════════════════
# 内置种子文档
# 作用：确保 data/docs/ 为空时系统仍有基础知识可用；
#       生产中建议用真实研报 PDF 替代（放入 data/docs/ 即生效）
# ════════════════════════════════════════════════════════════════════

_SEED_DOCUMENTS = [
    # ── 宏观政策：美联储 ──────────────────────────────────────
    """[美联储货币政策 2024-2025]
美联储在2024年9月启动降息周期，联邦基金利率目标区间从5.25%-5.50%下调25bp至5.00%-5.25%。
此轮降息周期预期持续至2025年底，市场预期终端利率约为3.00%-3.50%。
降息周期对美股科技板块（NASDAQ）、港股高息股、黄金构成正向催化。
关键风险：若核心PCE通胀数据高于预期（>2.5%），美联储可能暂停或放缓降息节奏。
""",
    # ── 宏观政策：中国央行 ───────────────────────────────────
    """[中国货币政策与A股市场 2024-2025]
中国人民银行多次下调MLF利率和LPR利率，1年期LPR降至3.10%，5年期LPR降至3.60%（截至2024Q4）。
政策目标：支持实体经济，激活资本市场，稳楼市防风险。
A股重大政策催化：2024年9月"一揽子政策"（降准+降息+地产政策组合拳）推动市场快速反弹。
重点扶持行业：AI/算力、新能源汽车、半导体国产化、生物医药、低空经济。
监管重点：加强量化交易监管，限制高频量化；鼓励长期价值投资。
""",
    # ── A股：行业景气度 ──────────────────────────────────────
    """[A股行业景气度报告 2025年]
高景气行业（政策+基本面双驱动）:
1. AI算力/半导体: 国产替代加速（华为昇腾、海光信息），PEG普遍<1.5
2. 新能源汽车: 渗透率突破50%，供应链降本完成，头部净利率回升至5-8%
3. 低空经济: eVTOL/无人机适航认证推进，2025年市场规模预期超500亿
4. 创新药/CXO: 创新药出海加速，叠加医保改革利好
5. 算力基础设施: IDC、液冷散热需求随AI推理需求井喷
低景气行业: 地产链施工端、消费白马（估值切换中）、部分银行（息差收窄压力）。
""",
    # ── 港股：市场特征 ──────────────────────────────────────
    """[港股市场特征与估值框架]
港股定价三大维度:
1. 流动性定价：港股存在25-35%流动性折价，买入需更高安全边际
2. 南向资金：沪深港通南向持续净买入是重要正向信号
3. 外资影响：美元指数走弱→外资加仓新兴市场
重点标的：腾讯(00700) AI+回购+股息 PE15-18x；阿里(09988) 云剥离+EBITA改善；美团(03690) FCF改善。
估值锚：港股互联网历史PE中枢12-20x，<15x配合基本面改善可关注。
""",
    # ── 美股：市场框架 ──────────────────────────────────────
    """[美股市场投资框架 2025]
核心驱动：企业EPS增速（标普500预期10-12%），AI相关板块20-30%。
Forward PE约20-22x，高于历史均值18x，泡沫风险需关注。
重点主题：AI基础设施(NVDA/AMD/AVGO)、AI应用层(MSFT/GOOGL/META)、传统价值(BRK/JPM/HD)。
风险因素：关税政策不确定性（特朗普2.0），地缘冲突对供应链影响。
""",
    # ── 大学生理财：ETF定投入门 ──────────────────────────────
    """[大学生入门理财：宽基ETF定投策略]
什么是ETF（Exchange-Traded Fund，交易所交易基金）？
- 把一篮子股票打包成一个产品，像买股票一样在交易所买卖
- 宽基ETF追踪指数（如沪深300、纳斯达克100），天然分散化，风险低于单只股票
- 费率极低（年费0.1%~0.5%），适合长期持有

大学生推荐入门ETF：
1. 沪深300ETF（510300.SH）: 追踪A股最大300家公司，代表中国经济基本盘
2. 创业板ETF（159915.SZ）: 追踪创业板100只成长股，适合长期定投
3. 纳斯达克100ETF（513100.SH）: 追踪美国科技龙头，人民币即可购买
4. 中证红利ETF（510880.SH）: 高分红策略，适合保守型学生

定投策略（专为大学生设计）：
- 每月定额（如500元/月），无论涨跌坚持买入，自动摊平成本（美元成本平均法）
- 不需要每天盯盘，更不需要预测市场方向
- 持续3-5年以上，历史数据显示长期年化收益约8-12%
- 核心原则：时间是大学生最大的资产，越早开始越好

常见误区：
❌ 试图"抄底"找完美入场点 → 时机选择90%以上的人都做不到
❌ 看到短期亏损就停止定投 → 正好应该坚持买，在下跌中摊低成本
✅ 设置自动扣款，忘掉它，继续学习和生活
""",
    # ── 大学生理财：价值投资基础 ─────────────────────────────
    """[大学生价值投资基础：看懂一家公司]
价值投资核心思想（巴菲特式）：
- 股票 = 公司的一小份所有权，买股票就是买企业
- 以合理价格买入优质公司，长期持有，让时间和复利工作

关键财务指标入门理解：
1. 市盈率（PE = Price/Earnings）
   - 理解：你花多少元买这家公司1元的年利润
   - 比喻：买一家奶茶店，PE=20 意味着你花20年才能回本（假设利润不变）
   - 参考：A股市场平均PE约15-20x；PE越低越便宜（但需结合增速）
2. 市净率（PB = Price/Book）
   - 理解：你花多少元买这家公司1元净资产
   - 银行股PB<1意味着你用8折买到了净资产
3. 净利润增速（EPS Growth）
   - 快速增长的公司可以享受高PE（因为未来利润大）
   - 停滞增长的公司应该给低PE
4. 自由现金流（FCF）
   - 比净利润更真实：企业实际到手的现金
   - FCF为正且持续增长 = 真实赚钱的公司

选股入门原则（大学生版）：
✅ 选择你真正理解的业务（你用它的产品吗？）
✅ 财务健康：资产负债率<60%，连续多年盈利
✅ 行业地位：细分领域前三名，有护城河（品牌/专利/规模效应）
❌ 远离概念炒作：只有PPT没有盈利的公司不碰
❌ 远离财务造假风险：应收账款极高、现金流与利润背离
""",
    # ── 大学生理财：防范金融诈骗 ─────────────────────────────
    """[大学生必看：识别金融杀猪盘与常见投资诈骗]
"杀猪盘"是什么？
- 诈骗者先通过社交软件（微信/陌陌/交友APP）建立情感或信任关系
- 然后以"内幕消息""AI量化""境外套利"为诱饵，引导受害者入金
- 初期小额提现让你放松警惕（养猪），最后卷走全部资产（杀猪）
- 大学生是主要目标群体：社会经验少、渴望快速致富、容易轻信

典型骗局特征（出现任意一条即警惕）：
❗ "稳赚不赔""年化100%""保本保息" — 合法投资市场不存在零风险
❗ 陌生人发来"内幕消息""分析师推荐" — 真正的内幕消息是违法的
❗ 要求下载非正规APP/平台入金 — 正规平台都有证监会牌照
❗ 初期小赚吸引你加大投入 — 这是标准养猪流程
❗ 催促转账、不让提款、账户被"冻结"需缴税才能提现
❗ 拉入"投资交流群""名师指导群" — 群里全是托

正规平台判断标准：
✅ 券商账户（华泰/中信/国泰君安等）须在证监会登记备案
✅ 在证监会官网（csrc.gov.cn）可查询机构资质
✅ 正规平台从不承诺收益，从不主动联系推荐股票

如果不幸遇到：
1. 立即停止汇款，截图保留所有聊天记录
2. 向平台举报，向公安机关（反诈热线96110）报案
3. 不要相信"再交钱就能提回来"的谎言

口诀：高收益=高风险，陌生人荐股必有鬼，遇到催钱先报警。
""",
    # ── 技术分析 ────────────────────────────────────────────
    """[技术分析核心框架]
趋势判断：
- 黄金交叉（MA5上穿MA20，MA20上穿MA60）: 中长期多头信号
- 死叉（MA5下穿MA20）: 短期看空，MA60也下行则中期空头
MACD解读：
- 金叉（DIF上穿DEA）: 买入信号；死叉（DIF下穿DEA）: 卖出信号
- 顶/底背离：价格创新高但MACD未创新高=顶背离（卖出信号）
RSI解读：
- RSI<30超卖关注反弹，RSI>70超买关注回调，背离=弱势信号
布林带：
- 触上轨(%B>0.85)超买，触下轨(%B<0.15)超卖，带宽收窄后扩张=突破信号
量价关系：
- 放量上涨（量比>2.0+涨幅>2%）: 主力积极做多
- 缩量横盘: 蓄势整理；放量下跌: 空头占优
""",
    # ── 风险管理 ─────────────────────────────────────────────
    """[量化交易风险管理框架]
核心原则：
1. 单笔风险≤总资金2%（凯利公式优化）
2. 最大回撤≤20%，触发后降仓50%
3. 单个标的≤总资金20%
止损纪律：A股5%，美股7%，严格执行不抱幻想。
止盈策略：分批止盈（目标价附近先止盈50%）+ 移动止损跟踪剩余仓位。
极端风险：保留20%现金应对黑天鹅（地缘冲突、政策突变、交易所安全事件）。
""",
]


# ════════════════════════════════════════════════════════════════════
# 全局单例（惰性初始化，首次调用 search_knowledge_base 时自动触发）
# ════════════════════════════════════════════════════════════════════

_ensemble_retriever = None   # EnsembleRetriever（BM25 + Chroma）
_web_search_tool    = None   # DuckDuckGoSearchRun 实例


# ════════════════════════════════════════════════════════════════════
# 内部构建函数
# ════════════════════════════════════════════════════════════════════

# _load_all_documents() 已迁移至 scripts/build_kb.py（离线建库脚本）
# 在线端不再执行文档加载与切块，直接从磁盘读取预构建索引。


def _build_embedding_model():
    """
    按优先级构建 Embedding 模型：
      优先级 1: DashScope text-embedding-v3（默认，使用 OpenAI 兼容端点）
      优先级 2: OpenAI text-embedding-3-small（备选，需 OPENAI_API_KEY）
      优先级 3: 返回 None → 触发"仅 BM25"降级模式
    """
    from config import config

    # 优先使用 DashScope Embedding（OpenAI 兼容协议）
    try:
        dashscope_key = getattr(config, "DASHSCOPE_API_KEY", None)
        if dashscope_key and len(dashscope_key) > 20:
            from langchain_openai import OpenAIEmbeddings
            model = OpenAIEmbeddings(
                model=config.DASHSCOPE_EMBEDDING_MODEL,
                api_key=dashscope_key,
                base_url=config.DASHSCOPE_BASE_URL,
                # DashScope 仅接受原始字符串，禁用 LangChain 的 tiktoken 预分词
                check_embedding_ctx_length=False,
                # 【关键】DashScope embedding API 限制 batch size ≤ 10
                # langchain_openai 默认 chunk_size=1000 会导致 400 错误
                chunk_size=10,
            )
            logger.info(f"  Embedding 模型: DashScope {config.DASHSCOPE_EMBEDDING_MODEL} ✅")
            return model
    except Exception as e:
        logger.warning(f"  DashScope Embeddings 初始化失败: {e}")

    # 备选：OpenAI 官方 Embedding
    try:
        key = getattr(config, "OPENAI_API_KEY", None)
        if key and "your-openai" not in key.lower() and len(key) > 20:
            from langchain_openai import OpenAIEmbeddings
            model = OpenAIEmbeddings(
                model="text-embedding-3-small",
                api_key=key,
            )
            logger.info("  Embedding 模型: OpenAI text-embedding-3-small ✅")
            return model
    except Exception as e:
        logger.warning(f"  OpenAI Embeddings 初始化失败: {e}")

    logger.warning("  ⚠️ 无可用 Embedding 模型，向量检索降级为纯 BM25 模式")
    logger.warning("     若需开启向量检索，请在 .env 中配置有效的 DASHSCOPE_API_KEY")
    return None


def _build_chroma_retriever(embedding_model) -> Optional[object]:
    """
    【在线端-极速加载】从已持久化目录实例化 Chroma 检索器，不执行任何 Embedding。

    前提：已执行过 python scripts/build_kb.py，data/chroma_db/ 中存有向量索引。
    耗时：< 500ms（仅打开 SQLite 文件句柄，无网络请求）。

    若索引不存在，返回 None 并打印引导信息（系统降级为纯 BM25 或纯联网模式）。
    """
    if embedding_model is None:
        logger.info("  跳过 Chroma 加载（无 Embedding 模型）")
        return None

    try:
        import chromadb
        try:
            from langchain_chroma import Chroma
        except ImportError:
            from langchain_community.vectorstores import Chroma

        chroma_client = chromadb.PersistentClient(path=str(_CHROMA_DIR))
        existing_names = [c.name for c in chroma_client.list_collections()]

        if _COLLECTION not in existing_names:
            logger.warning(
                f"  Chroma 集合 '{_COLLECTION}' 不存在。"
                f"请先运行离线建库脚本: python scripts/build_kb.py"
            )
            return None

        vector_store = Chroma(
            client=chroma_client,
            collection_name=_COLLECTION,
            embedding_function=embedding_model,
        )
        # 检查向量数量
        coll = chroma_client.get_collection(_COLLECTION)
        vec_count = coll.count()
        if vec_count == 0:
            logger.warning(
                f"  ⚠ Chroma 集合 '{_COLLECTION}' 存在但向量数=0！"
                f"请运行: python scripts/build_kb.py 重建索引"
            )
            return None

        retriever = vector_store.as_retriever(
            search_type="similarity",
            search_kwargs={"k": 5},
        )
        logger.info(f"  Chroma 向量检索器: {vec_count} 向量，从磁盘加载完成 ✅")
        return retriever

    except ImportError:
        logger.warning("  chromadb 未安装: pip install chromadb")
        return None
    except Exception as e:
        logger.error(f"  Chroma 加载失败: {e}")
        return None


def _build_bm25_retriever() -> Optional[object]:
    """
    【在线端-极速加载】从 pickle 文件反序列化 BM25 检索器实例。

    前提：已执行过 python scripts/build_kb.py，data/bm25_index.pkl 已生成。
    耗时：< 100ms（纯内存反序列化，无任何计算）。

    若文件不存在，返回 None 并打印引导信息（系统降级为纯 Chroma 或纯联网模式）。
    """
    import pickle

    if not _BM25_PKL.exists():
        logger.warning(
            f"  BM25 索引文件不存在: {_BM25_PKL.name}。"
            f"请先运行离线建库脚本: python scripts/build_kb.py"
        )
        return None

    try:
        with open(_BM25_PKL, "rb") as f:
            bm25 = pickle.load(f)
        logger.info(f"  BM25 关键词检索器: 从 {_BM25_PKL.name} 加载完成 ✅")
        return bm25
    except Exception as e:
        logger.error(f"  BM25 加载失败（pkl 文件可能已损坏，重新运行 build_kb.py）: {e}")
        return None


def _build_ensemble_retriever(
    bm25_retriever,
    chroma_retriever,
) -> Optional[object]:
    """
    组装 EnsembleRetriever（混合召回融合器）。

    ── 混合召回原理（RRF 排名融合）─────────────────────────────────
    Reciprocal Rank Fusion（RRF）算法：
      • 对每路检索结果分别按排名赋予 1/(rank+60) 的得分
      • 对同一文档在多路结果中的得分求和
      • 按融合后得分重新排序，返回 Top-K

    例：Query = "NVDA 2025年AI芯片出货量预测"
      BM25 结果（精准词匹配）:
        [1] 含 "NVDA"  的段落（rank=1） → 得分 1/61 ≈ 0.016
        [2] 含 "AI芯片" 的段落（rank=2）→ 得分 1/62 ≈ 0.016
      Chroma 结果（语义相似）:
        [1] 含 "英伟达" 的段落（rank=1）→ 得分 1/61 ≈ 0.016
        [2] 含 "NVDA"  的段落（rank=2）→ 得分 1/62 ≈ 0.016
      融合后（含 "NVDA" 的段落同时被两路检出）:
        → 融合得分 1/61 + 1/62 ≈ 0.032，大幅领先其他文档 → 排名第一

    weights=[0.5, 0.5]：两路平等投票，可根据业务需求调整
      • 专有名词多的场景：偏向 BM25（如 weights=[0.7, 0.3]）
      • 语义理解要求高的场景：偏向 Chroma（如 weights=[0.3, 0.7]）
    """
    if not bm25_retriever and not chroma_retriever:
        logger.error("  ❌ 两路检索器均不可用，RAG 功能将受限")
        return None

    if bm25_retriever and chroma_retriever:
        try:
            try:
                from langchain_classic.retrievers.ensemble import EnsembleRetriever  # LangChain >= 1.0
            except ImportError:
                from langchain.retrievers import EnsembleRetriever  # LangChain < 1.0 旧版
            ensemble = EnsembleRetriever(
                retrievers=[bm25_retriever, chroma_retriever],
                weights=[0.5, 0.5],   # BM25 关键词 50% + Chroma 语义 50%
            )
            logger.info("  EnsembleRetriever (BM25 50% + Chroma 50%): ✅ 就绪")
            return ensemble
        except Exception as e:
            logger.warning(f"  EnsembleRetriever 组装失败: {e}，降级单路检索")

    # 降级：只有一路可用时单独使用
    fallback = chroma_retriever or bm25_retriever
    mode = "Chroma 语义" if chroma_retriever else "BM25 关键词"
    logger.warning(f"  ⚠️ 降级模式：仅使用 {mode} 单路检索")
    return fallback


def _build_web_search_tool() -> Optional[object]:
    """
    初始化 DuckDuckGo 实时联网搜索工具。

    ── 联网搜索的必要性 ─────────────────────────────────────────────
    本地知识库的时效性存在上限：研报发布日期之后的信息无法覆盖。
    以下场景本地知识库无能为力，必须依赖实时联网搜索：
      • 今日突发新闻（股价暴跌原因、政策突然发布）
      • 最新财报数据（当季 EPS、营收超预期或不及预期）
      • 实时市场情绪（社媒热度、机构最新评级调整）
      • 政策突发事件（监管新规、行业整顿）

    ── DuckDuckGo vs 其他搜索工具 ──────────────────────────────────
    • DuckDuckGo：免费、无需 API Key、隐私保护、langchain 原生支持
    • Tavily：需要付费 API Key，但结果更结构化（备选方案）
    • Bing/Google：需要付费 API Key

    需要安装：pip install duckduckgo-search
    """
    try:
        from langchain_community.tools import DuckDuckGoSearchRun
        search = DuckDuckGoSearchRun()
        logger.info("  DuckDuckGo 实时联网搜索: ✅ 就绪")
        return search
    except ImportError:
        logger.warning("  ⚠️ duckduckgo-search 未安装: pip install duckduckgo-search")
        return None
    except Exception as e:
        logger.warning(f"  ⚠️ DuckDuckGo 初始化失败（可能网络受限）: {e}")
        return None


# ════════════════════════════════════════════════════════════════════
# 公开初始化函数
# ════════════════════════════════════════════════════════════════════

def init_knowledge_base(force_reload: bool = False) -> bool:
    """
    【在线端-极速初始化】从预构建的磁盘索引加载混合 RAG 知识库。

    动静分离架构说明：
      离线端（一次性）: python scripts/build_kb.py
        → 解析 PDF/TXT → 切块 → Embedding → 持久化 Chroma + BM25.pkl
      在线端（每次启动）: 本函数
        → pickle.load(bm25)  ← < 100ms
        → Chroma 打开文件句柄 ← < 500ms
        → 组装 EnsembleRetriever + DuckDuckGo
        → 总耗时 < 2s，不依赖任何 Embedding API 调用

    Args:
        force_reload: True = 清除已有单例，强制从磁盘重新加载
                      适用场景：运行 build_kb.py 后希望热更新索引

    Returns:
        True  = 至少一路检索器可用（可降级运行）
        False = 所有检索器均不可用（极少见）

    若 data/bm25_index.pkl 或 data/chroma_db/ 不存在，
    请先运行: python scripts/build_kb.py
    """
    global _ensemble_retriever, _web_search_tool

    if _ensemble_retriever is not None and not force_reload:
        logger.debug("知识库已初始化，跳过（force_reload=False）")
        return True

    logger.info("=" * 60)
    logger.info("RAG 知识库在线加载（动静分离架构 v3.0）")
    logger.info(f"  BM25 索引 : {_BM25_PKL}")
    logger.info(f"  Chroma 目录: {_CHROMA_DIR}")
    logger.info("=" * 60)
    t0 = time.time()

    # [1] BM25 — 从 pkl 文件反序列化（< 100ms）
    logger.info("[1/3] 加载 BM25 关键词检索器（pkl 反序列化）...")
    bm25_retriever = _build_bm25_retriever()

    # [2] Chroma — 打开已持久化向量库（< 500ms，无 Embedding API 调用）
    logger.info("[2/3] 加载 Chroma 语义向量检索器（磁盘读取）...")
    embedding_model  = _build_embedding_model()
    chroma_retriever = _build_chroma_retriever(embedding_model)

    # [3] 组装 EnsembleRetriever + DuckDuckGo
    logger.info("[3/3] 组装 EnsembleRetriever + DuckDuckGo 联网搜索...")
    _ensemble_retriever = _build_ensemble_retriever(bm25_retriever, chroma_retriever)
    _web_search_tool    = _build_web_search_tool()

    elapsed = time.time() - t0
    success = _ensemble_retriever is not None

    bm25_ok   = bm25_retriever   is not None
    chroma_ok = chroma_retriever is not None
    web_ok    = _web_search_tool is not None

    if bm25_ok and chroma_ok:
        retrieval_mode = "混合 (BM25 + Chroma + RRF)"
    elif bm25_ok:
        retrieval_mode = "降级: 仅 BM25 关键词"
    elif chroma_ok:
        retrieval_mode = "降级: 仅 Chroma 语义"
    else:
        retrieval_mode = "不可用 — 请运行 python scripts/build_kb.py"

    logger.info("─" * 60)
    logger.info(f"知识库加载完成  耗时 {elapsed:.2f}s")
    logger.info(f"  检索模式: {retrieval_mode}")
    logger.info(f"  联网搜索: {'DuckDuckGo 已启用' if web_ok else '不可用'}")
    if not bm25_ok or not chroma_ok:
        logger.warning("  请运行: python scripts/build_kb.py 以构建完整索引")
    logger.info("─" * 60)

    return success


# ════════════════════════════════════════════════════════════════════
# 查询扩展 — 金融领域同义词/翻译
# ════════════════════════════════════════════════════════════════════

_SYNONYM_MAP = {
    "美联储": "Federal Reserve Fed 联邦储备 降息 加息",
    "央行": "PBOC 中国人民银行 货币政策 LPR",
    "市盈率": "PE P/E ratio 估值",
    "市净率": "PB P/B ratio 净资产",
    "净资产收益率": "ROE Return on Equity",
    "每股收益": "EPS Earnings Per Share",
    "自由现金流": "FCF Free Cash Flow",
    "营收": "revenue 营业收入 总收入",
    "净利润": "net income 归母净利润",
    "毛利率": "gross margin 毛利",
    "研发": "R&D 研发费用 研发投入",
    "股息": "dividend 分红 派息",
    "回购": "buyback 股票回购",
    "减持": "insider selling 大股东减持",
    "融资融券": "margin trading 两融",
    "北向资金": "northbound 外资 QFII 沪股通 深股通",
    "南向资金": "southbound 港股通",
    "ETF": "交易型开放式基金 指数基金",
    "量化": "quant quantitative 程序化交易",
    "AI芯片": "GPU AI chip 英伟达 NVIDIA 算力",
    "新能源": "NEV 电动车 光伏 锂电 储能",
}

def _expand_query_synonyms(query: str) -> str:
    """在查询中发现领域术语时，追加同义词/英文翻译以提升召回"""
    extras = []
    q_lower = query.lower()
    for term, synonyms in _SYNONYM_MAP.items():
        if term.lower() in q_lower or term in query:
            # 只取前 3 个同义词，避免查询过长
            parts = synonyms.split()[:3]
            extras.extend(parts)
    if extras:
        return query + " " + " ".join(extras)
    return query


# ════════════════════════════════════════════════════════════════════
# @tool — search_knowledge_base（LangGraph 节点调用的统一入口）
# ════════════════════════════════════════════════════════════════════

@tool
def search_knowledge_base(query: str, market_type: str = "ALL", max_length: int = 1500) -> str:
    """
    在本地研报知识库与全网实时信息中，检索与查询最相关的分析上下文。

    ── 双路信息融合机制 ─────────────────────────────────────────────
    ① 本地混合检索（EnsembleRetriever）:
         BM25 关键词精准匹配 + Chroma 语义模糊匹配 → RRF 融合排序
         适合：挖掘研报深度内容（行业分析、政策解读、历史规律、风险框架）

    ② 全网实时搜索（DuckDuckGo）:
         适合：最新新闻、突发事件、当季财报、实时市场动态

    最终返回"本地研报深度 + 实时网络广度"的格式化双层 RAG 上下文，
    直接可作为 LLM Prompt 的 system_context 或 user_message 使用。

    Args:
        query:       检索查询，例如:
                       "NVDA 2025年AI芯片出货量与竞争格局"
                       "美联储降息对A股科技股的影响"
                       "腾讯00700 港股估值与南向资金动向"
                       "沪深300ETF 定投策略与历史收益"
        market_type: 市场类型，用于优化本地检索查询词权重
                     可选值: "A_STOCK" | "HK_STOCK" | "US_STOCK" | "ALL"
        max_length:  返回字符串的最大长度，0 表示不截断，默认 1500

    Returns:
        str: 格式化 RAG 上下文字符串，供 LLM 直接消费
             格式：
             【本地知识库 — 混合检索结果（BM25 + 向量语义）】
               [1] 来源: xxx.pdf  p.3
                   ...片段内容...
               [2] 来源: builtin_seed
                   ...

             【实时联网搜索结果 — DuckDuckGo】
               搜索词: xxx
               ...搜索摘要...
    """
    global _ensemble_retriever, _web_search_tool

    sections: List[str] = []

    # ────────────────────────────────────────────────────────────────
    # ① 本地混合检索：优先走内地 relay（RAG 部署在内地服务器）
    # ────────────────────────────────────────────────────────────────
    inland_result = _search_local_via_inland_relay(query, market_type, max_length)
    if inland_result:
        sections.append(inland_result)
    else:
        # 回退：本地 RAG 检索
        if _ensemble_retriever is None:
            logger.info("[RAG] 触发惰性初始化...")
            init_knowledge_base()

        _MARKET_HINTS = {
            "A_STOCK":  "A股 中国 上证 深证 政策 行业景气度 ETF定投",
            "HK_STOCK": "港股 香港 恒生 南向资金 估值折价 安全边际",
            "US_STOCK": "美股 纳斯达克 标普500 美联储 EPS FCF 盈利",
        }
        market_hint    = _MARKET_HINTS.get(market_type, "")
        expanded_query = _expand_query_synonyms(query)
        enhanced_query = f"{expanded_query} {market_hint}".strip()
        sections.append(_search_local(enhanced_query, original_query=query))

    # ────────────────────────────────────────────────────────────────
    # ② 实时联网搜索：DuckDuckGo
    # ────────────────────────────────────────────────────────────────
    sections.append(_search_web(query, market_type))

    result = "\n\n".join(sections)
    return result[:max_length] if max_length > 0 else result


# ════════════════════════════════════════════════════════════════════
# 内部执行函数（不对外暴露）
# ════════════════════════════════════════════════════════════════════

def _search_local_via_inland_relay(query: str, market_type: str, max_length: int) -> Optional[str]:
    """
    通过内地 relay 服务执行 RAG 检索。
    成功返回格式化文本，失败返回 None（触发本地回退）。
    """
    try:
        from config import config
        import requests as _requests

        base_url = (getattr(config, "INLAND_RELAY_BASE_URL", "") or "").rstrip("/")
        token = (getattr(config, "INLAND_RELAY_TOKEN", "") or "").strip()
        if not base_url or not token:
            return None

        resp = _requests.get(
            f"{base_url}/relay/rag/search",
            params={"query": query, "market_type": market_type, "max_length": max_length},
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") in ("success", "partial") and data.get("local_results"):
            logger.info(f"[RAG] 内地 relay 检索成功，{data.get('doc_count', 0)} 条结果")
            return data["local_results"]
        return None
    except Exception as exc:
        logger.warning(f"[RAG] 内地 relay 检索失败，回退本地: {exc}")
        return None


def _search_local(enhanced_query: str, original_query: str) -> str:
    """
    执行本地混合检索，返回格式化本地知识片段。

    去重逻辑：EnsembleRetriever 在极端情况下可能返回重复文档，
    以前80字符为 key 进行去重，保证输出片段多样性。
    """
    if _ensemble_retriever is None:
        return (
            "【本地知识库】\n"
            "  暂不可用（检索器未初始化），请基于市场原始数据进行分析。\n"
            "  提示 → pip install rank_bm25 chromadb 并配置 OPENAI_API_KEY"
        )

    try:
        raw_docs = _ensemble_retriever.invoke(enhanced_query)

        if not raw_docs:
            return "【本地知识库】\n  未检索到与查询相关的内容，建议补充 data/docs/ 研报文件。"

        # 去重（以前80字符为指纹）
        seen: set[str] = set()
        unique_docs = []
        for doc in raw_docs:
            fingerprint = doc.page_content[:80]
            if fingerprint not in seen:
                seen.add(fingerprint)
                unique_docs.append(doc)

        snippets = []
        for i, doc in enumerate(unique_docs[:5], 1):  # 最多保留5条
            source = doc.metadata.get("source", "内置知识库")
            page   = doc.metadata.get("page", "")
            src_str = source + (f"  p.{page}" if page != "" else "")
            snippets.append(
                f"  [{i}] 来源: {src_str}\n"
                f"      {doc.page_content.strip()}"
            )

        body = "\n\n".join(snippets)
        logger.info(f"[RAG-Local] '{original_query}' → {len(unique_docs)} 个去重片段")
        return f"【本地知识库 — 混合检索结果（BM25 + 向量语义）】\n{body}"

    except Exception as e:
        logger.error(f"[RAG-Local] 检索异常: {e}")
        return f"【本地知识库检索异常】: {str(e)}"


def _search_web(query: str, market_type: str) -> str:
    """
    执行 DuckDuckGo 实时联网搜索，返回格式化网络搜索结果。

    搜索查询构建策略：
      • 追加市场标识词提升精准度（中英文混用效果更佳）
      • 例：query="AAPL 财报" → 搜索词="AAPL 财报 stock market news 2025"
    """
    if _web_search_tool is None:
        return (
            "【实时联网搜索】\n"
            "  不可用（duckduckgo-search 未安装或当前网络环境受限）\n"
            "  提示 → pip install duckduckgo-search"
        )

    _WEB_SUFFIXES = {
        "A_STOCK":  "A股 最新消息 2025",
        "HK_STOCK": "港股 Hong Kong stock news 2025",
        "US_STOCK": "US stock market news earnings 2025",
        "ALL":      "financial market news 2025",
    }
    suffix       = _WEB_SUFFIXES.get(market_type, "financial market 2025")
    search_query = f"{query} {suffix}"

    try:
        logger.info(f"[RAG-Web] DuckDuckGo 搜索: '{search_query}'")
        raw = _web_search_tool.run(search_query)

        if not raw or len(raw.strip()) < 30:
            return "【实时联网搜索】\n  未获取到有效搜索结果（可能为网络限制或查询词过于罕见）。"

        logger.info(f"[RAG-Web] 获取 {len(raw)} 字符")
        return (
            f"【实时联网搜索结果 — DuckDuckGo】\n"
            f"  搜索词: {search_query}\n\n"
            f"  {raw.strip()}"
        )

    except Exception as e:
        logger.warning(f"[RAG-Web] 搜索失败: {e}")
        return f"【实时联网搜索】\n  请求失败（可能为网络受限）: {str(e)}"
