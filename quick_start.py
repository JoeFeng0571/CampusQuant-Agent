"""
quick_start.py — CampusQuant-Agent 系统自检脚本

逐层测试各核心模块，确认系统就绪：
  1. 配置校验        — config.py + .env
  2. 模糊匹配        — utils/market_classifier.py
  3. LLM 连接        — DashScope qwen-plus 文本生成
  4. Embedding 连接  — DashScope text-embedding-v3
  5. 知识库初始化    — tools/knowledge_base.py (Chroma + BM25)
  6. 知识库检索      — search_knowledge_base()
  7. 图结构编译      — graph/builder.py → StateGraph.compile()
"""
import sys
import io
from pathlib import Path

# 强制 UTF-8 输出（Windows 终端兼容）
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

sys.path.append(str(Path(__file__).parent))

from loguru import logger
logger.remove()
logger.add(sys.stdout, format="<green>{time:HH:mm:ss}</green> | {message}", level="WARNING")
logger.add("logs/quick_start.log", rotation="10 MB", level="DEBUG")

SEP = "=" * 60


def _ok(msg: str):  print(f"  ✅ {msg}")
def _fail(msg: str): print(f"  ❌ {msg}")
def _info(msg: str): print(f"     {msg}")


# ──────────────────────────────────────────────────────────────
# 测试 1: 配置校验
# ──────────────────────────────────────────────────────────────
def test_config() -> bool:
    print(f"\n{SEP}")
    print("测试 1/7  配置校验")
    print(SEP)
    try:
        from config import config, validate_config
        _info(f"LLM 提供商 : {config.PRIMARY_LLM_PROVIDER}")
        _info(f"文本模型   : {config.DASHSCOPE_MODEL}")
        _info(f"Embedding  : {config.DASHSCOPE_EMBEDDING_MODEL}")
        _info(f"API Key    : {config.DASHSCOPE_API_KEY[:8]}...（已隐藏）")
        ok = validate_config()
        if ok:
            _ok("配置校验通过")
        else:
            _fail("配置校验未通过，请检查 DASHSCOPE_API_KEY")
        return ok
    except Exception as e:
        _fail(f"配置加载失败: {e}")
        return False


# ──────────────────────────────────────────────────────────────
# 测试 2: 模糊匹配
# ──────────────────────────────────────────────────────────────
def test_fuzzy_match() -> bool:
    print(f"\n{SEP}")
    print("测试 2/7  智能标的搜索（模糊匹配）")
    print(SEP)
    try:
        from utils.market_classifier import MarketClassifier, MarketType
        cases = [
            ("茅台",   "600519.SH"),
            ("腾讯",   "00700.HK"),
            ("英伟达", "NVDA"),
            ("苹果",   "AAPL"),
            ("沪深300ETF", "510300.SH"),
        ]
        all_pass = True
        for query, expected in cases:
            result = MarketClassifier.fuzzy_match(query)
            if result == expected:
                _ok(f"{query:8s} → {result}")
            else:
                _fail(f"{query:8s} → {result}（期望 {expected}）")
                all_pass = False

        # 测试 classify
        mt, _ = MarketClassifier.classify("600519.SH")
        assert mt == MarketType.A_STOCK, f"classify 失败: {mt}"
        _ok("market classify A股 通过")

        return all_pass
    except Exception as e:
        _fail(f"模糊匹配测试失败: {e}")
        return False


# ──────────────────────────────────────────────────────────────
# 测试 3: LLM 文本生成
# ──────────────────────────────────────────────────────────────
def test_llm() -> bool:
    print(f"\n{SEP}")
    print("测试 3/7  LLM 文本生成（DashScope qwen-plus）")
    print(SEP)
    try:
        from utils.llm_client import LLMClient
        client = LLMClient()
        reply = client.generate(
            prompt="用一句话解释什么是ETF。",
            system_prompt="你是面向大学生的财商教育老师，回答简洁。",
            max_tokens=80,
        )
        _ok(f"LLM 响应成功（{len(reply)} 字）")
        _info(f"回复：{reply[:60]}{'...' if len(reply)>60 else ''}")
        return True
    except Exception as e:
        _fail(f"LLM 测试失败: {e}")
        return False


# ──────────────────────────────────────────────────────────────
# 测试 4: Embedding
# ──────────────────────────────────────────────────────────────
def test_embedding() -> bool:
    print(f"\n{SEP}")
    print("测试 4/7  Embedding（DashScope text-embedding-v3）")
    print(SEP)
    try:
        from config import config
        from langchain_openai import OpenAIEmbeddings
        emb = OpenAIEmbeddings(
            model=config.DASHSCOPE_EMBEDDING_MODEL,
            api_key=config.DASHSCOPE_API_KEY,
            base_url=config.DASHSCOPE_BASE_URL,
            check_embedding_ctx_length=False,
        )
        vec = emb.embed_query("沪深300ETF定投策略")
        _ok(f"Embedding 成功，向量维度: {len(vec)}")
        return True
    except Exception as e:
        _fail(f"Embedding 测试失败: {e}")
        return False


# ──────────────────────────────────────────────────────────────
# 测试 5: 知识库初始化
# ──────────────────────────────────────────────────────────────
def test_knowledge_base_init() -> bool:
    print(f"\n{SEP}")
    print("测试 5/7  知识库初始化（Chroma + BM25）")
    print(SEP)
    try:
        from tools.knowledge_base import init_knowledge_base
        _info("首次运行会写入 Chroma，耗时约 5-15 秒...")
        ok = init_knowledge_base(force_rebuild=False)
        if ok:
            _ok("知识库初始化成功")
        else:
            _fail("知识库初始化返回 False，请检查日志")
        return ok
    except Exception as e:
        _fail(f"知识库初始化异常: {e}")
        return False


# ──────────────────────────────────────────────────────────────
# 测试 6: 知识库检索
# ──────────────────────────────────────────────────────────────
def test_knowledge_base_search() -> bool:
    print(f"\n{SEP}")
    print("测试 6/7  知识库检索")
    print(SEP)
    try:
        from tools.knowledge_base import search_knowledge_base
        result = search_knowledge_base.invoke({
            "query": "ETF定投适合大学生吗",
            "market_type": "A_STOCK",
        })
        if result and len(result) > 20:
            _ok(f"检索成功，返回内容 {len(result)} 字")
            _info(f"摘要：{result[:80].replace(chr(10), ' ')}...")
            return True
        else:
            _fail(f"检索结果为空或过短: {result!r}")
            return False
    except Exception as e:
        _fail(f"知识库检索异常: {e}")
        return False


# ──────────────────────────────────────────────────────────────
# 测试 7: LangGraph 图结构编译
# ──────────────────────────────────────────────────────────────
def test_graph_compile() -> bool:
    print(f"\n{SEP}")
    print("测试 7/7  LangGraph 图结构编译")
    print(SEP)
    try:
        from graph.builder import build_graph
        compiled = build_graph()
        nodes = list(compiled.nodes.keys())
        _ok(f"StateGraph 编译成功，共 {len(nodes)} 个节点")
        _info(f"节点列表: {', '.join(nodes)}")
        return True
    except Exception as e:
        _fail(f"图编译失败: {e}")
        return False


# ──────────────────────────────────────────────────────────────
# 主函数
# ──────────────────────────────────────────────────────────────
def main():
    print("""
╔═══════════════════════════════════════════════════════════╗
║                                                           ║
║      CampusQuant-Agent  系统自检                         ║
║                                                           ║
╚═══════════════════════════════════════════════════════════╝
    """)

    results = {
        "配置校验":     test_config(),
        "模糊匹配":     test_fuzzy_match(),
        "LLM 连接":     test_llm(),
        "Embedding":    test_embedding(),
        "知识库初始化": test_knowledge_base_init(),
        "知识库检索":   test_knowledge_base_search(),
        "图结构编译":   test_graph_compile(),
    }

    # ── 汇总报告 ──
    print(f"\n{SEP}")
    print("自检结果汇总")
    print(SEP)
    passed = sum(results.values())
    total  = len(results)
    for name, ok in results.items():
        status = "✅ PASS" if ok else "❌ FAIL"
        print(f"  {status}  {name}")

    print(f"\n{passed}/{total} 项通过", end="  ")
    if passed == total:
        print("🎉 系统就绪，可以运行主程序！")
        print(f"\n  启动 Web UI:  uvicorn api.server:app & streamlit run app.py")
        print(f"  命令行分析:  python workflow.py")
    else:
        print("⚠️  部分模块异常，请根据上方错误信息排查")
    print(SEP + "\n")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n用户中断自检")
    except Exception as e:
        logger.exception(f"自检异常: {e}")
        print(f"\n❌ 自检异常: {e}")
