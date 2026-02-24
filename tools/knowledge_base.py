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

_BASE_DIR   = Path(__file__).parent.parent   # 项目根目录
_DOCS_DIR   = _BASE_DIR / "data" / "docs"    # 研报/PDF 存放目录
_CHROMA_DIR = _BASE_DIR / "data" / "chroma_db"  # Chroma 持久化目录
_COLLECTION = "trading_knowledge"            # Chroma 集合名称（逻辑命名空间）

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
降息周期对美股科技板块（NASDAQ）、港股高息股、黄金及部分加密货币构成正向催化。
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
3. 单个标的≤总资金20%；加密货币合约≤10%
止损纪律：A股5%，美股7%，加密货币10%，严格执行不抱幻想。
止盈策略：分批止盈（目标价附近先止盈50%）+ 移动止损跟踪剩余仓位。
极端风险：保留20%现金应对黑天鹅（地缘冲突、政策突变、交易所安全事件）。
""",
]


# ════════════════════════════════════════════════════════════════════
# 文本切分配置（全局共用）
# ════════════════════════════════════════════════════════════════════

_SPLITTER = RecursiveCharacterTextSplitter(
    chunk_size=500,        # 每块最大字符数（中文语境适当放大）
    chunk_overlap=100,     # 块间重叠字符数，保证跨块上下文连贯
    separators=["\n\n", "\n", "。", "；", "，", " "],
)


# ════════════════════════════════════════════════════════════════════
# 全局单例（惰性初始化，首次调用 search_knowledge_base 时自动触发）
# ════════════════════════════════════════════════════════════════════

_ensemble_retriever = None   # EnsembleRetriever（BM25 + Chroma）
_web_search_tool    = None   # DuckDuckGoSearchRun 实例


# ════════════════════════════════════════════════════════════════════
# 内部构建函数
# ════════════════════════════════════════════════════════════════════

def _load_all_documents() -> List[Document]:
    """
    汇总加载所有文档来源：
      ① 内置种子文档 — 系统底线知识，无外部文件时保证基本可用
      ② data/docs/ 本地文件 — 支持 PDF、TXT、Markdown，自动递归扫描

    文件加载失败时单独跳过，不影响其他文件。
    """
    docs: List[Document] = []

    # ① 内置种子文档
    seed_docs = [
        Document(page_content=text, metadata={"source": "builtin_seed"})
        for text in _SEED_DOCUMENTS
    ]
    docs.extend(seed_docs)
    logger.info(f"  ① 内置种子文档: {len(seed_docs)} 篇")

    # ② 扫描本地文件
    local_files = (
        list(_DOCS_DIR.rglob("*.pdf"))
        + list(_DOCS_DIR.rglob("*.txt"))
        + list(_DOCS_DIR.rglob("*.md"))
    )

    if not local_files:
        logger.info(f"  ② data/docs/ 目录为空，仅使用内置种子知识")
        logger.info(f"     提示 → 将研报 PDF/TXT 放入 {_DOCS_DIR} 可扩充知识库")
        return docs

    logger.info(f"  ② 发现 {len(local_files)} 个本地文件，逐一加载中...")
    loaded_count = 0
    for fpath in local_files:
        try:
            if fpath.suffix.lower() == ".pdf":
                # PDF 加载：需要 pypdf（pip install pypdf）
                from langchain_community.document_loaders import PyPDFLoader
                loader = PyPDFLoader(str(fpath))
            else:
                # TXT / Markdown 加载
                from langchain_community.document_loaders import TextLoader
                loader = TextLoader(str(fpath), encoding="utf-8")

            file_docs = loader.load()
            # 注入文件名元数据（用于检索结果溯源）
            for d in file_docs:
                d.metadata.setdefault("source", fpath.name)
            docs.extend(file_docs)
            loaded_count += 1
            logger.info(f"     ✓ {fpath.name}  ({len(file_docs)} 段)")
        except ImportError as e:
            logger.warning(f"     ✗ {fpath.name} — 缺少依赖: {e}")
        except Exception as e:
            logger.warning(f"     ✗ {fpath.name} — 加载失败: {e}")

    logger.info(f"  ② 本地文件加载完成: {loaded_count}/{len(local_files)} 成功")
    return docs


def _build_embedding_model():
    """
    按优先级构建 Embedding 模型：
      优先级 1: OpenAI text-embedding-3-small（效果最佳，需 OPENAI_API_KEY）
      优先级 2: 返回 None → 触发"仅 BM25"降级模式

    说明：Anthropic 官方不提供 Embedding 模型，故无 Anthropic 备选。
    """
    try:
        from config import config
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
    logger.warning("     若需开启向量检索，请在 .env 中配置有效的 OPENAI_API_KEY")
    return None


def _build_chroma_retriever(
    chunks: List[Document],
    embedding_model,
    force_rebuild: bool,
) -> Optional[object]:
    """
    构建 Chroma 持久化向量数据库检索器（稠密检索）。

    ── 稠密向量检索工作原理 ─────────────────────────────────────────
    1. Embedding：将每个文本块通过 OpenAI Embeddings 转换为高维向量（1536维）
    2. 存储：向量持久化至 data/chroma_db/（SQLite + 向量文件）
    3. 检索：将 Query 转为向量，计算与库中所有向量的余弦相似度
    4. 排序：按相似度降序取 Top-K 结果返回

    ── 稠密检索的优势与劣势 ────────────────────────────────────────
    优势：理解语义/概念相似度（如 "英伟达" 能匹配含 "NVDA" 的段落）
    劣势：对特定格式专有名词（如 "000858.SZ" 股票代码）召回不稳定
          → 由 BM25 精准匹配补偿此劣势

    ── 持久化策略 ──────────────────────────────────────────────────
    • 首次/force_rebuild=True：执行 Embedding → 写入 Chroma（耗时，需 API 调用）
    • 后续启动：直接加载已有 Chroma 集合，无需重新 Embedding（秒级就绪）
    • 新增文档后：调用 init_knowledge_base(force_rebuild=True) 重建
    """
    if embedding_model is None:
        logger.info("  跳过 Chroma 构建（无 Embedding 模型）")
        return None

    try:
        import chromadb
        from langchain_community.vectorstores import Chroma

        # 创建持久化客户端（数据存储于 data/chroma_db/）
        chroma_client = chromadb.PersistentClient(path=str(_CHROMA_DIR))
        existing_names = [c.name for c in chroma_client.list_collections()]
        has_existing = _COLLECTION in existing_names

        if has_existing and not force_rebuild:
            # ── 快速加载：跳过 Embedding，直接读取已持久化向量 ──────
            logger.info("  Chroma 向量库已存在，直接加载（秒级启动，无 API 调用）")
            vector_store = Chroma(
                client=chroma_client,
                collection_name=_COLLECTION,
                embedding_function=embedding_model,
            )
        else:
            # ── 重建：清除旧集合，重新 Embedding 写入 ───────────────
            if has_existing:
                chroma_client.delete_collection(_COLLECTION)
                logger.info("  已清除旧 Chroma 集合，强制重建中...")

            logger.info(f"  开始向 Chroma 写入 {len(chunks)} 个文本块（需调用 Embedding API）...")

            # 分批写入，避免单次请求超过 OpenAI API 限制（每批 ≤50 块）
            BATCH = 50
            if len(chunks) <= BATCH:
                vector_store = Chroma.from_documents(
                    documents=chunks,
                    embedding=embedding_model,
                    client=chroma_client,
                    collection_name=_COLLECTION,
                )
            else:
                vector_store = Chroma(
                    client=chroma_client,
                    collection_name=_COLLECTION,
                    embedding_function=embedding_model,
                )
                for i in range(0, len(chunks), BATCH):
                    batch = chunks[i: i + BATCH]
                    vector_store.add_documents(batch)
                    pct = min(i + BATCH, len(chunks))
                    logger.info(f"    Embedding 进度: {pct}/{len(chunks)} 块")

        retriever = vector_store.as_retriever(
            search_type="similarity",
            search_kwargs={"k": 5},  # 稠密检索候选数，与 BM25 保持一致
        )
        logger.info("  Chroma 语义向量检索器: ✅ 就绪")
        return retriever

    except ImportError:
        logger.warning("  ⚠️ chromadb 未安装: pip install chromadb")
        return None
    except Exception as e:
        logger.error(f"  ❌ Chroma 构建失败: {e}")
        return None


def _build_bm25_retriever(chunks: List[Document]) -> Optional[object]:
    """
    构建 BM25 稀疏关键词检索器（精准词匹配）。

    ── BM25 工作原理（稀疏检索）──────────────────────────────────
    BM25（Best Matching 25）是 TF-IDF 的改进版信息检索算法：
      • TF（词频）：目标词在文档中出现越多，得分越高（但有饱和上限）
      • IDF（逆文档频率）：越罕见的词权重越高（过滤"的""了"等停用词效果）
      • BM25 在 TF 上加入饱和函数 k1 和文档长度归一化参数 b，更健壮

    检索过程：
      1. 将所有文本块分词建立倒排索引（rank_bm25 库维护）
      2. 检索时对 Query 分词，计算每个词与所有文档块的 BM25 得分
      3. 按得分降序返回 Top-K 文档块

    ── BM25 的优势与劣势 ────────────────────────────────────────
    优势：精准词匹配，对股票代码（AAPL/000858.SZ）、人名、机构名稳定可靠
    劣势：无法理解同义词（"英伟达" 无法匹配 "NVDA"）
          → 由 Chroma 语义检索补偿此劣势

    这正是混合召回 EnsembleRetriever 的核心价值：两路互补，覆盖更全面。

    需要安装：pip install rank_bm25
    """
    try:
        from langchain_community.retrievers import BM25Retriever
        bm25 = BM25Retriever.from_documents(chunks)
        bm25.k = 5  # 稀疏检索候选数，与 Chroma 保持一致
        logger.info("  BM25 关键词检索器: ✅ 就绪")
        return bm25
    except ImportError:
        logger.warning("  ⚠️ rank_bm25 未安装: pip install rank_bm25")
        return None
    except Exception as e:
        logger.error(f"  ❌ BM25 构建失败: {e}")
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
            from langchain.retrievers import EnsembleRetriever
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
      • 加密货币实时事件（交易所上线新币、监管新规）

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

def init_knowledge_base(force_rebuild: bool = False) -> bool:
    """
    初始化高阶混合 RAG 知识库（建议在应用启动时主动调用一次）。

    若未主动调用，search_knowledge_base @tool 会在首次被调用时自动触发（惰性初始化）。

    执行流程：
      [1/5] 加载文档   ← 内置种子 + data/docs/ 本地 PDF/TXT/Markdown
      [2/5] 文本切块   ← RecursiveCharacterTextSplitter（500字符/块，100字符重叠）
      [3/5] BM25       ← 稀疏关键词检索器（rank_bm25）
      [4/5] Chroma     ← 稠密向量检索器（OpenAI Embeddings + Chroma 持久化）
      [5/5] Ensemble   ← 混合召回融合（BM25 50% + Chroma 50%，RRF 排名融合）
      [+]   联网搜索   ← DuckDuckGoSearchRun（实时信息补充）

    Args:
        force_rebuild: True = 清除旧 Chroma 集合，强制重新 Embedding
                       适用场景：data/docs/ 新增/更新了研报文件

    Returns:
        True  = 全功能模式（混合检索 + 联网搜索，至少一路检索器可用）
        False = 完全失败（极少见，仅在所有依赖均缺失时发生）
    """
    global _ensemble_retriever, _web_search_tool

    if _ensemble_retriever is not None and not force_rebuild:
        logger.debug("知识库已初始化，跳过重复构建")
        return True

    logger.info("=" * 62)
    logger.info("🔧 初始化高阶混合 RAG 知识库 (v2.0)")
    logger.info(f"   docs 目录  : {_DOCS_DIR}")
    logger.info(f"   Chroma 目录: {_CHROMA_DIR}")
    logger.info(f"   强制重建   : {force_rebuild}")
    logger.info("=" * 62)
    t0 = time.time()

    # [1] 加载文档
    logger.info("[1/5] 加载文档来源...")
    raw_docs = _load_all_documents()
    logger.info(f"  共计: {len(raw_docs)} 篇原始文档")

    # [2] 文本切块
    logger.info("[2/5] 文本切块（RecursiveCharacterTextSplitter）...")
    chunks = _SPLITTER.split_documents(raw_docs)
    logger.info(f"  {len(raw_docs)} 篇 → {len(chunks)} 个文本块")

    # [3] BM25
    logger.info("[3/5] 构建 BM25 稀疏关键词检索器...")
    bm25_retriever = _build_bm25_retriever(chunks)

    # [4] Chroma
    logger.info("[4/5] 构建 Chroma 稠密向量检索器...")
    embedding_model  = _build_embedding_model()
    chroma_retriever = _build_chroma_retriever(chunks, embedding_model, force_rebuild)

    # [5] Ensemble
    logger.info("[5/5] 组装 EnsembleRetriever（混合召回）...")
    _ensemble_retriever = _build_ensemble_retriever(bm25_retriever, chroma_retriever)

    # [+] 联网搜索
    logger.info("[+] 初始化 DuckDuckGo 实时联网搜索工具...")
    _web_search_tool = _build_web_search_tool()

    # ── 打印初始化摘要 ────────────────────────────────────────────
    elapsed = time.time() - t0
    success = _ensemble_retriever is not None

    bm25_ok   = bm25_retriever   is not None
    chroma_ok = chroma_retriever is not None
    web_ok    = _web_search_tool is not None

    if bm25_ok and chroma_ok:
        retrieval_mode = "混合 (BM25 + Chroma)"
    elif bm25_ok:
        retrieval_mode = "仅 BM25 关键词"
    elif chroma_ok:
        retrieval_mode = "仅 Chroma 语义"
    else:
        retrieval_mode = "❌ 不可用"

    logger.info("─" * 62)
    logger.info(f"{'✅' if success else '❌'} 知识库初始化完成  耗时 {elapsed:.1f}s")
    logger.info(f"   检索模式 : {retrieval_mode}")
    logger.info(f"   联网搜索 : {'✅ DuckDuckGo 已启用' if web_ok else '❌ 不可用'}")
    logger.info(f"   文本块数 : {len(chunks)}")
    if not bm25_ok:
        logger.info("   提示 → pip install rank_bm25  （启用关键词检索）")
    if not chroma_ok:
        logger.info("   提示 → pip install chromadb   （启用向量检索）")
        logger.info("          并在 .env 中配置 OPENAI_API_KEY")
    if not web_ok:
        logger.info("   提示 → pip install duckduckgo-search  （启用联网搜索）")
    logger.info("─" * 62)

    return success


# ════════════════════════════════════════════════════════════════════
# @tool — search_knowledge_base（LangGraph 节点调用的统一入口）
# ════════════════════════════════════════════════════════════════════

@tool
def search_knowledge_base(query: str, market_type: str = "ALL") -> str:
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

    # 惰性初始化（若应用启动时未主动调用 init_knowledge_base）
    if _ensemble_retriever is None:
        logger.info("[RAG] 触发惰性初始化...")
        init_knowledge_base()

    # ── 构建增强查询（在原始 query 基础上注入市场上下文关键词）──────
    # 目的：提升 BM25 关键词检索对特定市场文档的召回率
    _MARKET_HINTS = {
        "A_STOCK":  "A股 中国 上证 深证 政策 行业景气度 ETF定投",
        "HK_STOCK": "港股 香港 恒生 南向资金 估值折价 安全边际",
        "US_STOCK": "美股 纳斯达克 标普500 美联储 EPS FCF 盈利",
    }
    market_hint    = _MARKET_HINTS.get(market_type, "")
    enhanced_query = f"{query} {market_hint}".strip()

    sections: List[str] = []

    # ────────────────────────────────────────────────────────────────
    # ① 本地混合检索：EnsembleRetriever（BM25 + Chroma）
    # ────────────────────────────────────────────────────────────────
    sections.append(_search_local(enhanced_query, original_query=query))

    # ────────────────────────────────────────────────────────────────
    # ② 实时联网搜索：DuckDuckGo
    # ────────────────────────────────────────────────────────────────
    sections.append(_search_web(query, market_type))

    return "\n\n".join(sections)


# ════════════════════════════════════════════════════════════════════
# 内部执行函数（不对外暴露）
# ════════════════════════════════════════════════════════════════════

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
