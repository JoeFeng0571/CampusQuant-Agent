#!/usr/bin/env python3
"""
eval_rag.py — CampusQuant 混合 RAG 检索召回率评测

核心指标：Recall@5
  对每条查询，检索 Top-5 文档，判断是否命中"预期关键词"中的至少一个。
  Recall@5 = 命中查询数 / 总查询数

三路对比（可选，需要 Embedding API Key）：
  ① BM25 单路（无需 API Key，纯关键词匹配）
  ② Chroma 单路（需 Embedding API Key，语义向量检索）
  ③ 混合 Ensemble（BM25 50% + Chroma 50% + RRF 融合）← 对应简历中的"混合 RAG"

设计思路：
  - 25 条测试查询，覆盖三类检索挑战：
      keyword  : 专有名词/代码精确匹配 (BM25 擅长)
      semantic : 语义理解/同义词 (Chroma 擅长)
      hybrid   : 两路互补，混合 RAG 才能全部命中
  - 预期结论：混合 Recall@5 > 单路 Chroma ≥ 单路 BM25

运行方式：
  # 仅 BM25（无需 API Key，几秒内完成）
  python eval_rag.py --bm25-only

  # 完整三路对比（需 DASHSCOPE_API_KEY 或 OPENAI_API_KEY）
  python eval_rag.py

  # 保存 JSON 报告
  python eval_rag.py --output rag_eval_report.json

测试集知识来源：knowledge_base.py 内置种子文档（_SEED_DOCUMENTS），
包含：美联储政策、中国央行政策、A股行业景气度、港股估值框架、
      美股投资框架、ETF 定投、价值投资、防骗指南、技术分析、风险管理。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# ══════════════════════════════════════════════════════════════════
# 一、测试集（25 条，覆盖 keyword / semantic / hybrid 三类挑战）
# ══════════════════════════════════════════════════════════════════

RAG_TEST_CASES: List[Dict[str, Any]] = [
    # ── keyword 类：专有名词/代码精确匹配（BM25 擅长）──────────
    {
        "id": 1,
        "query": "美联储联邦基金利率降息周期 2024 2025",
        "expected_keywords": ["联邦基金利率", "降息", "5.25", "5.00"],
        "challenge": "keyword",
        "note": "数字和固定词组，BM25 精确命中",
    },
    {
        "id": 2,
        "query": "LPR利率 MLF A股政策降准",
        "expected_keywords": ["LPR", "MLF", "降准", "3.10"],
        "challenge": "keyword",
        "note": "金融术语缩写，BM25 强项",
    },
    {
        "id": 3,
        "query": "510300 沪深300ETF 159915 创业板",
        "expected_keywords": ["510300", "沪深300ETF", "159915", "创业板ETF"],
        "challenge": "keyword",
        "note": "证券代码精确匹配，BM25 核心优势",
    },
    {
        "id": 4,
        "query": "00700 腾讯港股 AI 回购股息 PE 15x",
        "expected_keywords": ["00700", "腾讯", "回购", "PE15"],
        "challenge": "keyword",
        "note": "港股代码 + 量化指标",
    },
    {
        "id": 5,
        "query": "NVDA AMD AVGO AI基础设施芯片美股",
        "expected_keywords": ["NVDA", "AMD", "AVGO", "AI基础设施"],
        "challenge": "keyword",
        "note": "英文股票代码，BM25 精确匹配",
    },
    {
        "id": 6,
        "query": "BRK JPM HD 价值股 传统行业 美股",
        "expected_keywords": ["BRK", "JPM", "HD", "传统价值"],
        "challenge": "keyword",
        "note": "价值股代码组合",
    },
    {
        "id": 7,
        "query": "RSI超卖 RSI<30 布林带 %B 技术指标",
        "expected_keywords": ["RSI<30", "RSI", "布林带", "超卖"],
        "challenge": "keyword",
        "note": "技术分析公式符号，BM25 直接匹配",
    },
    {
        "id": 8,
        "query": "杀猪盘 96110 反诈热线 证监会牌照",
        "expected_keywords": ["杀猪盘", "96110", "证监会", "反诈"],
        "challenge": "keyword",
        "note": "特定词组，BM25 擅长",
    },
    {
        "id": 9,
        "query": "凯利公式 最大回撤20% 止损5% 风险管理",
        "expected_keywords": ["凯利公式", "最大回撤", "止损", "20%"],
        "challenge": "keyword",
        "note": "风险管理术语+数字组合",
    },

    # ── semantic 类：语义理解/同义词/概念迁移（Chroma 擅长）────
    {
        "id": 10,
        "query": "货币宽松周期对新兴市场股市的提振作用",
        "expected_keywords": ["降息", "降准", "A股", "新兴市场"],
        "challenge": "semantic",
        "note": "用'宽松'替代'降息'，需语义理解",
    },
    {
        "id": 11,
        "query": "港股相比A股的折价原因和流动性差异",
        "expected_keywords": ["流动性折价", "港股", "折价", "南向资金"],
        "challenge": "semantic",
        "note": "用'折价原因'表述，需理解'流动性折价'概念",
    },
    {
        "id": 12,
        "query": "大学生如何通过分散投资降低风险",
        "expected_keywords": ["ETF", "分散化", "宽基ETF", "定投"],
        "challenge": "semantic",
        "note": "'分散投资'->'ETF'语义映射",
    },
    {
        "id": 13,
        "query": "判断一家公司是否真实盈利而非账面利润",
        "expected_keywords": ["自由现金流", "FCF", "现金流", "净利润"],
        "challenge": "semantic",
        "note": "'真实盈利'->'自由现金流'概念迁移",
    },
    {
        "id": 14,
        "query": "美国科技龙头公司股票投资机会",
        "expected_keywords": ["MSFT", "GOOGL", "META", "AI应用层", "纳斯达克"],
        "challenge": "semantic",
        "note": "'美国科技龙头'->具体股票名语义对应",
    },
    {
        "id": 15,
        "query": "如何识别网络诈骗分子以投资为名的圈套",
        "expected_keywords": ["杀猪盘", "诈骗", "内幕消息", "稳赚不赔"],
        "challenge": "semantic",
        "note": "'网络诈骗圈套'->'杀猪盘'语义扩展",
    },
    {
        "id": 16,
        "query": "股票均线金叉死叉趋势信号",
        "expected_keywords": ["金叉", "死叉", "MA5", "MA20", "黄金交叉"],
        "challenge": "semantic",
        "note": "'均线信号'->具体技术指标语义匹配",
    },

    # ── hybrid 类：BM25+Chroma 互补，单路均有盲区（Ensemble 擅长）
    {
        "id": 17,
        "query": "英伟达 AI算力需求爆发 2025年出货量预测",
        "expected_keywords": ["NVDA", "英伟达", "AI", "算力"],
        "challenge": "hybrid",
        "note": "Chroma 匹配'英伟达'，BM25 匹配'NVDA'，两路互补",
    },
    {
        "id": 18,
        "query": "阿里巴巴港股估值修复和云业务分拆机会",
        "expected_keywords": ["09988", "阿里", "云", "EBITA"],
        "challenge": "hybrid",
        "note": "Chroma 匹配语义，BM25 匹配'09988'代码",
    },
    {
        "id": 19,
        "query": "国产半导体替代浪潮下算力基础设施投资价值",
        "expected_keywords": ["半导体国产化", "AI算力", "IDC", "算力"],
        "challenge": "hybrid",
        "note": "跨文档语义拼接，需要多文档召回",
    },
    {
        "id": 20,
        "query": "市盈率PE和自由现金流FCF如何结合判断股票价值",
        "expected_keywords": ["PE", "FCF", "市盈率", "自由现金流"],
        "challenge": "hybrid",
        "note": "BM25 命中'PE FCF'缩写，Chroma 命中'市盈率自由现金流'",
    },
    {
        "id": 21,
        "query": "如何用定投策略应对市场波动减少择时风险",
        "expected_keywords": ["定投", "美元成本平均", "自动扣款", "摊平成本"],
        "challenge": "hybrid",
        "note": "BM25 匹配'定投'，Chroma 匹配'规避择时'语义",
    },
    {
        "id": 22,
        "query": "南向资金对港股科技互联网股的影响",
        "expected_keywords": ["南向资金", "港股", "互联网", "南向"],
        "challenge": "hybrid",
        "note": "BM25 精确匹配'南向资金'，Chroma 补充科技互联网语义",
    },
    {
        "id": 23,
        "query": "看跌信号：股价创新高但量价背离MACD顶背离",
        "expected_keywords": ["顶背离", "MACD", "背离", "卖出信号"],
        "challenge": "hybrid",
        "note": "BM25 匹配技术术语，Chroma 理解'看跌信号'语义",
    },
    {
        "id": 24,
        "query": "新能源汽车产业链渗透率提升和净利率回升趋势",
        "expected_keywords": ["新能源汽车", "渗透率", "供应链", "净利率"],
        "challenge": "hybrid",
        "note": "行业分析术语，BM25+Chroma 双路联合覆盖",
    },
    {
        "id": 25,
        "query": "大学生小额资金入门投资的低风险资产配置建议",
        "expected_keywords": ["ETF", "宽基", "定投", "分散", "低风险"],
        "challenge": "hybrid",
        "note": "综合性查询，需要多段落融合回答",
    },
]


# ══════════════════════════════════════════════════════════════════
# 二、数据结构
# ══════════════════════════════════════════════════════════════════

@dataclass
class QueryResult:
    """单条查询的检索结果"""
    id:            int
    query:         str
    challenge:     str
    expected_keywords: List[str]

    # 各路召回结果
    bm25_hit:      Optional[bool] = None
    bm25_docs:     int = 0
    bm25_matched:  str = ""         # 命中的关键词

    chroma_hit:    Optional[bool] = None
    chroma_docs:   int = 0
    chroma_matched: str = ""

    ensemble_hit:  Optional[bool] = None
    ensemble_docs: int = 0
    ensemble_matched: str = ""

    latency_ms:    float = 0.0


@dataclass
class RagEvalReport:
    """RAG 评测完整报告"""
    run_at:          str = ""
    total_queries:   int = 0

    bm25_recall:     float = 0.0    # BM25 单路 Recall@5
    chroma_recall:   float = 0.0    # Chroma 单路 Recall@5
    ensemble_recall: float = 0.0    # 混合 Ensemble Recall@5

    bm25_pass:       int = 0
    chroma_pass:     int = 0
    ensemble_pass:   int = 0
    chroma_available: bool = False

    # 按挑战类型分类统计
    by_challenge: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    query_results: List[dict] = field(default_factory=list)


# ══════════════════════════════════════════════════════════════════
# 三、检索器构建（独立构建，用于对比）
# ══════════════════════════════════════════════════════════════════

def _load_chunks():
    """加载并切分知识库文档（供所有检索器共用）"""
    from langchain_text_splitters import RecursiveCharacterTextSplitter
    from langchain_core.documents import Document
    from tools.knowledge_base import _SEED_DOCUMENTS, _DOCS_DIR

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=500,
        chunk_overlap=100,
        separators=["\n\n", "\n", "。", "；", "，", " "],
    )

    # 种子文档
    docs = [
        Document(page_content=t, metadata={"source": "builtin_seed"})
        for t in _SEED_DOCUMENTS
    ]

    # 本地文件（如有）
    for fpath in (list(_DOCS_DIR.rglob("*.pdf"))
                  + list(_DOCS_DIR.rglob("*.txt"))
                  + list(_DOCS_DIR.rglob("*.md"))):
        try:
            if fpath.suffix.lower() == ".pdf":
                from langchain_community.document_loaders import PyPDFLoader
                docs.extend(PyPDFLoader(str(fpath)).load())
            else:
                from langchain_community.document_loaders import TextLoader
                docs.extend(TextLoader(str(fpath), encoding="utf-8").load())
        except Exception:
            pass

    return splitter.split_documents(docs)


def _build_bm25_only(chunks) -> Optional[object]:
    """构建纯 BM25 检索器"""
    try:
        from langchain_community.retrievers import BM25Retriever
        r = BM25Retriever.from_documents(chunks)
        r.k = 5
        return r
    except ImportError:
        print("  [WARN]  rank_bm25 未安装: pip install rank_bm25")
        return None


def _build_chroma_only(chunks) -> Optional[object]:
    """构建纯 Chroma 语义检索器（需 Embedding API Key）"""
    from tools.knowledge_base import _build_embedding_model, _CHROMA_DIR, _COLLECTION
    embedding_model = _build_embedding_model()
    if embedding_model is None:
        return None
    try:
        import chromadb
        try:
            from langchain_chroma import Chroma
        except ImportError:
            from langchain_community.vectorstores import Chroma

        client = chromadb.PersistentClient(path=str(_CHROMA_DIR))
        existing = [c.name for c in client.list_collections()]
        if _COLLECTION in existing:
            # 直接加载已有向量库
            vs = Chroma(client=client, collection_name=_COLLECTION,
                        embedding_function=embedding_model)
        else:
            # 新建（会调用 Embedding API）
            vs = Chroma.from_documents(documents=chunks, embedding=embedding_model,
                                       client=client, collection_name=_COLLECTION)
        return vs.as_retriever(search_type="similarity", search_kwargs={"k": 5})
    except Exception as e:
        print(f"  [WARN]  Chroma 构建失败: {e}")
        return None


def _build_ensemble_retriever(bm25_r, chroma_r) -> Optional[object]:
    """组装 EnsembleRetriever（BM25 + Chroma + RRF）"""
    if bm25_r is None:
        return chroma_r
    if chroma_r is None:
        return bm25_r
    try:
        try:
            from langchain_classic.retrievers.ensemble import EnsembleRetriever
        except ImportError:
            from langchain.retrievers import EnsembleRetriever
        return EnsembleRetriever(
            retrievers=[bm25_r, chroma_r],
            weights=[0.5, 0.5],
        )
    except Exception as e:
        print(f"  [WARN]  EnsembleRetriever 构建失败: {e}")
        return bm25_r


# ══════════════════════════════════════════════════════════════════
# 四、单条查询评测
# ══════════════════════════════════════════════════════════════════

def _check_hit(docs, expected_keywords: List[str]) -> Tuple[bool, str]:
    """
    判断检索结果是否命中：
    任意一个 expected_keyword 出现在任意一条检索结果的正文中即为命中。
    返回 (is_hit, matched_keyword)
    """
    for doc in docs:
        content = doc.page_content
        for kw in expected_keywords:
            if kw in content:
                return True, kw
    return False, ""


def _retrieve_safe(retriever, query: str) -> Tuple[list, float]:
    """安全调用检索器，返回 (docs, latency_ms)"""
    t0 = time.time()
    try:
        docs = retriever.invoke(query)
    except Exception as e:
        print(f"    检索异常: {e}")
        docs = []
    ms = (time.time() - t0) * 1000
    return docs, ms


def eval_single_query(
    tc: Dict[str, Any],
    bm25_r, chroma_r, ensemble_r,
) -> QueryResult:
    """对单条测试用例运行三路检索并评测"""
    result = QueryResult(
        id=tc["id"],
        query=tc["query"],
        challenge=tc["challenge"],
        expected_keywords=tc["expected_keywords"],
    )

    t_total = 0.0

    # BM25
    if bm25_r:
        docs, ms = _retrieve_safe(bm25_r, tc["query"])
        t_total += ms
        hit, matched = _check_hit(docs, tc["expected_keywords"])
        result.bm25_hit     = hit
        result.bm25_docs    = len(docs)
        result.bm25_matched = matched

    # Chroma
    if chroma_r:
        docs, ms = _retrieve_safe(chroma_r, tc["query"])
        t_total += ms
        hit, matched = _check_hit(docs, tc["expected_keywords"])
        result.chroma_hit      = hit
        result.chroma_docs     = len(docs)
        result.chroma_matched  = matched

    # Ensemble
    if ensemble_r:
        docs, ms = _retrieve_safe(ensemble_r, tc["query"])
        t_total += ms
        hit, matched = _check_hit(docs, tc["expected_keywords"])
        result.ensemble_hit      = hit
        result.ensemble_docs     = len(docs)
        result.ensemble_matched  = matched

    result.latency_ms = round(t_total, 1)
    return result


# ══════════════════════════════════════════════════════════════════
# 五、汇总报告
# ══════════════════════════════════════════════════════════════════

def compute_rag_report(
    query_results: List[QueryResult],
    chroma_available: bool,
) -> RagEvalReport:
    """汇总所有查询结果，计算各路 Recall@5"""
    n = len(query_results)
    report = RagEvalReport(
        run_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        total_queries=n,
        chroma_available=chroma_available,
    )

    for r in query_results:
        if r.bm25_hit:
            report.bm25_pass += 1
        if r.chroma_hit:
            report.chroma_pass += 1
        if r.ensemble_hit:
            report.ensemble_pass += 1
        report.query_results.append(asdict(r))

    if n > 0:
        report.bm25_recall     = round(report.bm25_pass     / n * 100, 1)
        report.chroma_recall   = round(report.chroma_pass   / n * 100, 1)
        report.ensemble_recall = round(report.ensemble_pass / n * 100, 1)

    # 按挑战类型分类
    for challenge in ("keyword", "semantic", "hybrid"):
        group = [r for r in query_results if r.challenge == challenge]
        if not group:
            continue
        gc = len(group)
        report.by_challenge[challenge] = {
            "total":    gc,
            "bm25":     sum(1 for r in group if r.bm25_hit) / gc * 100 if gc else 0,
            "chroma":   sum(1 for r in group if r.chroma_hit) / gc * 100 if gc else 0,
            "ensemble": sum(1 for r in group if r.ensemble_hit) / gc * 100 if gc else 0,
        }

    return report


# ══════════════════════════════════════════════════════════════════
# 六、输出格式化
# ══════════════════════════════════════════════════════════════════

def print_rag_summary(report: RagEvalReport) -> None:
    try:
        from tabulate import tabulate
        HAS_TABULATE = True
    except ImportError:
        HAS_TABULATE = False

    sep = "═" * 64
    print(f"\n{sep}")
    print("  CampusQuant RAG 检索召回率评测报告 (Recall@5)")
    print(sep)
    print(f"  运行时间  : {report.run_at}")
    print(f"  测试查询数: {report.total_queries}")
    print(f"  Chroma 可用: {'是（三路完整对比）' if report.chroma_available else '否（仅 BM25 单路）'}")
    print()

    # 主结果表
    rows = []
    bm25_flag = f"{report.bm25_pass}/{report.total_queries}"
    rows.append(["BM25 单路（关键词）", bm25_flag, f"{report.bm25_recall:.1f}%", "基线"])

    if report.chroma_available:
        c_flag = f"{report.chroma_pass}/{report.total_queries}"
        rows.append(["Chroma 单路（语义）", c_flag, f"{report.chroma_recall:.1f}%", "对比"])
        e_flag = f"{report.ensemble_pass}/{report.total_queries}"
        delta  = report.ensemble_recall - report.bm25_recall
        rows.append([
            "混合 Ensemble ← 简历指标",
            e_flag,
            f"{report.ensemble_recall:.1f}%",
            f"+{delta:.1f}% vs BM25",
        ])
    else:
        rows.append(["混合 Ensemble（BM25 降级）", bm25_flag,
                     f"{report.bm25_recall:.1f}%", "需配置 Embedding Key"])

    headers = ["检索模式", "命中/总计", "Recall@5", "备注"]
    if HAS_TABULATE:
        print(tabulate(rows, headers=headers, tablefmt="simple"))
    else:
        print(f"  {'检索模式':<24} {'命中/总计':>8} {'Recall@5':>9} {'备注'}")
        print("  " + "-" * 55)
        for row in rows:
            print(f"  {row[0]:<24} {row[1]:>8} {row[2]:>9} {row[3]}")

    print()

    # 按挑战类型分项
    if report.by_challenge:
        print("  按检索挑战类型分项 (Recall@5 %):")
        ch_rows = []
        ch_names = {
            "keyword":  "精确关键词 (BM25 擅长)",
            "semantic": "语义理解  (Chroma 擅长)",
            "hybrid":   "混合互补  (Ensemble 擅长)",
        }
        for ch, stat in report.by_challenge.items():
            row = [
                ch_names.get(ch, ch),
                f"{stat['total']}条",
                f"{stat['bm25']:.0f}%",
                f"{stat['chroma']:.0f}%" if report.chroma_available else "N/A",
                f"{stat['ensemble']:.0f}%" if report.chroma_available else f"{stat['bm25']:.0f}%",
            ]
            ch_rows.append(row)
        ch_headers = ["挑战类型", "数量", "BM25", "Chroma", "Ensemble"]
        if HAS_TABULATE:
            print(tabulate(ch_rows, headers=ch_headers, tablefmt="simple",
                           colalign=("left","center","right","right","right")))
        else:
            for row in ch_rows:
                print(f"  {row[0]:<24} {row[1]:>4} BM25:{row[2]:>5} "
                      f"Chroma:{row[3]:>5} Ensemble:{row[4]:>5}")

    # 未命中清单
    missed = [r for r in report.query_results if not r.get("ensemble_hit")]
    if missed:
        print(f"\n  [WARN]  Ensemble 未命中查询 ({len(missed)} 条):")
        for r in missed:
            print(f"     [{r['id']:2d}] {r['query'][:50]:<50}  预期:{r['expected_keywords'][0]}")

    print(f"\n{sep}")
    if report.chroma_available:
        print(f"  [RPT] 核心指标: 混合 RAG Recall@5 = {report.ensemble_recall:.1f}%")
        print(f"     （较 BM25 单路提升 "
              f"{report.ensemble_recall - report.bm25_recall:+.1f}%，"
              f"较 Chroma 单路提升 "
              f"{report.ensemble_recall - report.chroma_recall:+.1f}%）")
    else:
        print(f"  [RPT] BM25 单路 Recall@5 = {report.bm25_recall:.1f}%")
        print("     运行 python eval_rag.py 并配置 Embedding API Key 可获得完整对比报告")
    print(f"{sep}\n")


def save_rag_report(report: RagEvalReport, path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(asdict(report), f, ensure_ascii=False, indent=2)
    print(f"  [FILE] RAG 评测报告已保存: {path}")


# ══════════════════════════════════════════════════════════════════
# 七、主入口
# ══════════════════════════════════════════════════════════════════

def main() -> None:
    parser = argparse.ArgumentParser(
        description="CampusQuant 混合 RAG 检索召回率评测 (Recall@5)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--bm25-only", action="store_true",
        help="只跑 BM25（无需 Embedding API Key，数秒内完成）",
    )
    parser.add_argument(
        "--output", type=str, default="",
        help="保存 JSON 报告的文件路径，默认不保存",
    )
    args = parser.parse_args()

    print("\n[eval] CampusQuant RAG 检索召回率评测 (Recall@5)")
    print(f"   测试集: {len(RAG_TEST_CASES)} 条查询")
    print(f"   模式: {'BM25 单路' if args.bm25_only else '三路对比 (BM25 + Chroma + Ensemble)'}\n")

    # ── 构建检索器 ──────────────────────────────────────────────
    print("- Step 1/3  加载知识库文档...")
    chunks = _load_chunks()
    print(f"  共 {len(chunks)} 个文本块\n")

    print("- Step 2/3  构建检索器...")
    bm25_r    = _build_bm25_only(chunks)
    chroma_r  = None if args.bm25_only else _build_chroma_only(chunks)
    ensemble_r = _build_ensemble_retriever(bm25_r, chroma_r)

    chroma_available = chroma_r is not None
    if chroma_available:
        print("  [OK] 三路检索器均已就绪（BM25 + Chroma + Ensemble）")
    else:
        print("  [INFO]  Chroma 不可用，将仅评测 BM25 单路")
    print()

    # ── 执行评测 ──────────────────────────────────────────────
    print("- Step 3/3  执行 25 条查询评测...")
    query_results: List[QueryResult] = []

    for tc in RAG_TEST_CASES:
        challenge_icon = {"keyword": "[KW]", "semantic": "[SM]", "hybrid": "[HY]"}.get(
            tc["challenge"], "?"
        )
        r = eval_single_query(tc, bm25_r, chroma_r, ensemble_r)
        query_results.append(r)

        b_icon = "OK" if r.bm25_hit else "XX"
        c_icon = ("OK" if r.chroma_hit else "XX") if chroma_available else "-"
        e_icon = ("OK" if r.ensemble_hit else "XX") if ensemble_r else "-"
        matched = r.ensemble_matched or r.bm25_matched or ""

        print(f"  [{tc['id']:2d}] {challenge_icon} {tc['query'][:42]:<42}  "
              f"BM25:{b_icon} Chroma:{c_icon} Ensemble:{e_icon}"
              + (f"  -> '{matched}'" if matched else ""))

    # ── 报告 ──────────────────────────────────────────────────
    report = compute_rag_report(query_results, chroma_available=chroma_available)
    print_rag_summary(report)

    if args.output:
        save_rag_report(report, args.output)


if __name__ == "__main__":
    main()
