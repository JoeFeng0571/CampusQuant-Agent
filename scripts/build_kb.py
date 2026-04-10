#!/usr/bin/env python3
"""
scripts/build_kb.py — CampusQuant 离线知识库构建脚本

动静分离架构中的【离线端】，承担所有耗时操作：
  1. 加载文档  ← 内置种子 + data/docs/ 中的 PDF/TXT/Markdown
  2. 文本切块  ← RecursiveCharacterTextSplitter
  3. 构建 Chroma 向量库，持久化至 data/chroma_db/
  4. 构建 BM25 检索器，序列化至 data/bm25_index.pkl

构建完成后，在线端（tools/knowledge_base.py）重启时将直接读取这两个产物，
无需再解析文档或调用 Embedding API，启动耗时从 ~60s 降至 <2s。

运行方式：
  # 首次建库 / 新增研报后重建
  cd trading_agents_system
  python scripts/build_kb.py

  # 强制重建 Chroma（不重建则跳过已有向量，只重建 BM25）
  python scripts/build_kb.py --force-chroma

  # 指定研报目录（默认 data/docs/）
  python scripts/build_kb.py --docs-dir /path/to/your/reports

依赖：
  pip install chromadb rank_bm25 pypdf langchain-openai langchain-community
  .env 中需配置 DASHSCOPE_API_KEY 或 OPENAI_API_KEY（用于 Embedding）
"""
from __future__ import annotations

import argparse
import os
import pickle
import re
import sys
import time
from pathlib import Path
from typing import List

# 【Fix】PyPDF 有时会抽出孤儿 UTF-16 surrogate 字符（\ud800-\udfff），
# Chroma/embedding API 无法处理。此正则用于清洗。
_BAD_CHAR_RE = re.compile(r'[\ud800-\udfff]')

def _sanitize_text(text: str) -> str:
    """清洗 PDF 抽取时产生的孤儿 surrogate / 不可见控制字符"""
    if not text:
        return text
    # 移除孤儿 surrogate
    text = _BAD_CHAR_RE.sub('', text)
    # 移除 null bytes 和其他控制字符（保留 \n \r \t）
    text = ''.join(c for c in text if c == '\n' or c == '\r' or c == '\t' or ord(c) >= 32)
    return text

# ── 确保项目根目录在 sys.path ──────────────────────────────────────
ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ── 路径常量（与 tools/knowledge_base.py 保持一致）─────────────────
_BASE_DIR   = ROOT
_DOCS_DIR   = _BASE_DIR / "data" / "docs"
_CHROMA_DIR = _BASE_DIR / "data" / "chroma_db"
_BM25_PKL   = _BASE_DIR / "data" / "bm25_index.pkl"
_COLLECTION = "trading_knowledge"

_DOCS_DIR.mkdir(parents=True, exist_ok=True)
_CHROMA_DIR.mkdir(parents=True, exist_ok=True)

# ── 文本切分配置（与在线端解耦后，唯一保留此处）──────────────────
from langchain_text_splitters import RecursiveCharacterTextSplitter

_SPLITTER = RecursiveCharacterTextSplitter(
    chunk_size=500,
    chunk_overlap=100,
    separators=["\n\n", "\n", "。", "；", "，", " "],
)


# ══════════════════════════════════════════════════════════════════
# 一、文档加载（从 knowledge_base.py 迁移）
# ══════════════════════════════════════════════════════════════════

def _load_seed_documents():
    """加载内置种子文档（从在线模块复用，保持内容一致）"""
    from langchain_core.documents import Document
    from tools.knowledge_base import _SEED_DOCUMENTS
    docs = [
        Document(page_content=text, metadata={"source": "builtin_seed"})
        for text in _SEED_DOCUMENTS
    ]
    print(f"  [①] 内置种子文档: {len(docs)} 篇")
    return docs


def _load_local_files(docs_dir: Path):
    """扫描并加载 docs_dir 中的 PDF / TXT / Markdown 文件"""
    from langchain_core.documents import Document

    local_files = (
        list(docs_dir.rglob("*.pdf"))
        + list(docs_dir.rglob("*.txt"))
        + list(docs_dir.rglob("*.md"))
    )

    if not local_files:
        print(f"  [②] {docs_dir} 目录为空，仅使用内置种子文档")
        print(f"       提示 → 将研报 PDF/TXT 放入该目录后重新运行此脚本")
        return []

    print(f"  [②] 发现 {len(local_files)} 个本地文件，开始解析...")
    docs = []
    loaded, failed = 0, 0
    for fpath in local_files:
        try:
            if fpath.suffix.lower() == ".pdf":
                from langchain_community.document_loaders import PyPDFLoader
                loader = PyPDFLoader(str(fpath))
            else:
                from langchain_community.document_loaders import TextLoader
                loader = TextLoader(str(fpath), encoding="utf-8")

            file_docs = loader.load()
            for d in file_docs:
                d.metadata.setdefault("source", fpath.name)
            docs.extend(file_docs)
            loaded += 1
            print(f"       OK  {fpath.name}  ({len(file_docs)} 段)")
        except ImportError as e:
            failed += 1
            print(f"       !! 缺少依赖: {e}")
        except Exception as e:
            failed += 1
            print(f"       !! {fpath.name} 解析失败: {e}")

    print(f"  [②] 本地文件: {loaded} 成功 / {failed} 失败")
    return docs


def load_all_documents(docs_dir: Path):
    """汇总加载种子文档 + 本地文件"""
    docs = _load_seed_documents()
    docs.extend(_load_local_files(docs_dir))
    return docs


# ══════════════════════════════════════════════════════════════════
# 二、构建 Chroma 向量库
# ══════════════════════════════════════════════════════════════════

def build_chroma(chunks, force: bool) -> bool:
    """
    将文本块 Embedding 并持久化写入 data/chroma_db/。

    Args:
        chunks:  切块后的 Document 列表
        force:   True = 删除旧集合重建；False = 集合已存在则跳过

    Returns:
        True = 构建成功（或跳过），False = 失败
    """
    try:
        import chromadb
        try:
            from langchain_chroma import Chroma
        except ImportError:
            from langchain_community.vectorstores import Chroma

        from tools.knowledge_base import _build_embedding_model
        embedding_model = _build_embedding_model()
        if embedding_model is None:
            print("  [Chroma] 无可用 Embedding 模型，跳过向量库构建")
            print("           请在 .env 中配置 DASHSCOPE_API_KEY 或 OPENAI_API_KEY")
            return False

        client = chromadb.PersistentClient(path=str(_CHROMA_DIR))
        existing = [c.name for c in client.list_collections()]
        has_existing = _COLLECTION in existing

        if has_existing and not force:
            print(f"  [Chroma] 集合 '{_COLLECTION}' 已存在，跳过（使用 --force-chroma 强制重建）")
            return True

        if has_existing:
            client.delete_collection(_COLLECTION)
            print(f"  [Chroma] 已删除旧集合，开始重建...")

        print(f"  [Chroma] 开始 Embedding {len(chunks)} 个文本块（需调用 API，请稍候）...")
        t0 = time.time()

        # DashScope 限制 batch size ≤ 10，用 10 的小批次写入 Chroma
        # 注意这是 Chroma 的写入批次，不是 Embedding API 批次（后者由 OpenAIEmbeddings.chunk_size 控制）
        BATCH = 100
        vs = Chroma(
            client=client,
            collection_name=_COLLECTION,
            embedding_function=embedding_model,
        )
        for i in range(0, len(chunks), BATCH):
            batch = chunks[i: i + BATCH]
            vs.add_documents(batch)
            done = min(i + BATCH, len(chunks))
            print(f"           进度: {done}/{len(chunks)} 块 ({done/len(chunks)*100:.1f}%)")

        elapsed = time.time() - t0
        print(f"  [Chroma] 构建完成，耗时 {elapsed:.1f}s，持久化至 {_CHROMA_DIR}")
        return True

    except ImportError as e:
        print(f"  [Chroma] 缺少依赖: {e}  →  pip install chromadb")
        return False
    except Exception as e:
        print(f"  [Chroma] 构建失败: {e}")
        return False


# ══════════════════════════════════════════════════════════════════
# 三、构建 BM25 并序列化
# ══════════════════════════════════════════════════════════════════

def build_bm25(chunks) -> bool:
    """
    构建 BM25 检索器并序列化至 data/bm25_index.pkl。

    BM25 是纯内存计算，无需 API Key，速度极快（通常 <5s）。
    序列化后在线端可在 <100ms 内完成加载。
    """
    try:
        from langchain_community.retrievers import BM25Retriever

        print(f"  [BM25]  从 {len(chunks)} 个文本块构建倒排索引...")
        t0 = time.time()
        bm25 = BM25Retriever.from_documents(chunks)
        bm25.k = 5
        elapsed = time.time() - t0
        print(f"  [BM25]  索引构建完成，耗时 {elapsed:.2f}s")

        with open(_BM25_PKL, "wb") as f:
            pickle.dump(bm25, f, protocol=pickle.HIGHEST_PROTOCOL)

        size_kb = _BM25_PKL.stat().st_size / 1024
        print(f"  [BM25]  已序列化至 {_BM25_PKL.name}  ({size_kb:.1f} KB)")
        return True

    except ImportError:
        print("  [BM25]  rank_bm25 未安装: pip install rank_bm25")
        return False
    except Exception as e:
        print(f"  [BM25]  构建失败: {e}")
        return False


# ══════════════════════════════════════════════════════════════════
# 四、主流程
# ══════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="CampusQuant 离线知识库构建脚本",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--force-chroma", action="store_true",
        help="强制重建 Chroma 向量库（否则集合已存在时跳过 Embedding）",
    )
    parser.add_argument(
        "--docs-dir", type=str, default=str(_DOCS_DIR),
        help=f"研报文件目录，默认 {_DOCS_DIR}",
    )
    parser.add_argument(
        "--bm25-only", action="store_true",
        help="仅重建 BM25 索引，跳过 Chroma（无需 Embedding API Key）",
    )
    args = parser.parse_args()

    docs_dir = Path(args.docs_dir)
    sep = "=" * 60

    print(f"\n{sep}")
    print("  CampusQuant 离线知识库构建脚本")
    print(f"  文档目录  : {docs_dir}")
    print(f"  Chroma 目录: {_CHROMA_DIR}")
    print(f"  BM25 文件  : {_BM25_PKL}")
    print(f"  强制重建   : {'Chroma + BM25' if args.force_chroma else 'BM25 always, Chroma skip if exists'}")
    print(sep)

    total_start = time.time()

    # ── Step 1: 加载文档 ──────────────────────────────────────────
    print("\n[Step 1/3] 加载文档...")
    raw_docs = load_all_documents(docs_dir)
    print(f"  共 {len(raw_docs)} 篇原始文档")

    # ── Step 2: 文本切块 ──────────────────────────────────────────
    print("\n[Step 2/3] 文本切块...")
    chunks = _SPLITTER.split_documents(raw_docs)
    print(f"  {len(raw_docs)} 篇 → {len(chunks)} 个文本块（chunk_size=500, overlap=100）")

    # 清洗所有 chunk 的 page_content
    cleaned = 0
    for chunk in chunks:
        orig = chunk.page_content
        chunk.page_content = _sanitize_text(orig)
        if chunk.page_content != orig:
            cleaned += 1
    if cleaned:
        print(f"  清洗了 {cleaned} 个含孤儿 surrogate / 控制字符的块")
    # 过滤掉清洗后为空的块
    chunks = [c for c in chunks if c.page_content.strip()]
    print(f"  清洗后保留 {len(chunks)} 个有效块")

    # ── Step 3: 构建索引 ──────────────────────────────────────────
    print("\n[Step 3/3] 构建检索索引...")

    bm25_ok    = build_bm25(chunks)
    chroma_ok  = False if args.bm25_only else build_chroma(chunks, force=args.force_chroma)

    # ── 结果摘要 ──────────────────────────────────────────────────
    total_elapsed = time.time() - total_start
    print(f"\n{sep}")
    print(f"  构建完成，总耗时 {total_elapsed:.1f}s")
    print(f"  BM25  索引: {'OK' if bm25_ok else 'FAIL'} → {_BM25_PKL.name}")
    print(f"  Chroma 索引: {'OK' if chroma_ok else ('跳过' if args.bm25_only else 'FAIL')} → {_CHROMA_DIR.name}/")
    print()

    if bm25_ok or chroma_ok:
        print("  后续操作：重启 FastAPI 后端，知识库将在 <2s 内完成加载")
        print("  验证命令：uvicorn api.server:app --host 127.0.0.1 --port 8000")
    else:
        print("  警告：两个索引均未成功构建，请检查依赖和 API Key 配置")
        sys.exit(1)

    print(sep + "\n")


if __name__ == "__main__":
    main()
