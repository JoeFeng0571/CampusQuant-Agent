"""
bench/smoke_analyze_v22.py - v2.2 evidence-citation smoke test

Single-stock analyze to verify:
  1. fundamental/technical evidence_citations are code-generated (deterministic)
  2. sentiment evidence_citations are LLM-extracted + substring validated
  3. portfolio_node reasoning references citation keywords (real integration)
  4. tech_signal upgraded to 5-tier
  5. debate_node sees evidence confrontation (not conclusion confrontation)

Usage:
    .venv/Scripts/python.exe -m bench.smoke_analyze_v22 600519

Cost: ~Y0.065 per analyze (Qwen3.5-Plus <=128K tier real price)
"""
from __future__ import annotations

import asyncio
import io
import json
import sys
from pathlib import Path

from loguru import logger

from graph.builder import build_graph, make_initial_state

# Force stdout to UTF-8 on Windows (avoids GBK codec errors on bullets etc.)
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")


def _fmt_cites(cites: list[str]) -> str:
    if not cites:
        return "    (empty)"
    # Use ASCII bullet to be safe on non-UTF consoles
    return "\n".join(f"    - {c}" for c in cites)


async def run_smoke(symbol: str) -> dict:
    logger.info(f"=== v2.2 smoke analyze: {symbol} ===")
    graph = build_graph()
    state = make_initial_state(symbol)

    config = {
        "configurable": {
            "thread_id": f"smoke_v22_{symbol}",
        },
        "recursion_limit": 50,
    }

    result = await graph.ainvoke(state, config=config)
    return result


def _extract_report(result: dict, key: str) -> dict:
    rep = result.get(key) or {}
    if isinstance(rep, dict):
        return rep
    return {}


def print_verification(result: dict) -> None:
    print()
    print("=" * 70)
    print("【v2.2 证据化改造验证】")
    print("=" * 70)

    # 基本面
    fund = _extract_report(result, "fundamental_report")
    print("\n### 基本面节点")
    print(f"  recommendation: {fund.get('recommendation', 'N/A')}")
    print(f"  confidence: {fund.get('confidence', 'N/A')}")
    print(f"  evidence_citations (代码生成,应来自 fund_data_dict):")
    print(_fmt_cites(fund.get("evidence_citations", [])))

    # 技术面
    tech = _extract_report(result, "technical_report")
    print("\n### 技术面节点")
    print(f"  recommendation: {tech.get('recommendation', 'N/A')}")
    print(f"  confidence: {tech.get('confidence', 'N/A')}")
    print(f"  evidence_citations (代码生成,应来自 indicators):")
    print(_fmt_cites(tech.get("evidence_citations", [])))

    # 舆情
    sent = _extract_report(result, "sentiment_report")
    print("\n### 舆情节点")
    print(f"  recommendation: {sent.get('recommendation', 'N/A')}")
    print(f"  confidence: {sent.get('confidence', 'N/A')}")
    print(f"  evidence_citations (LLM 抽取 + 子串校验):")
    print(_fmt_cites(sent.get("evidence_citations", [])))

    # 市场数据: 确认 P1-A 技术指标升级生效
    md = result.get("market_data") or {}
    ind = md.get("indicators") or {}
    print("\n### 技术指标 (P1-A 升级验证)")
    print(f"  tech_signal: {ind.get('tech_signal', 'N/A')} (应为 5 档之一)")
    print(f"  tech_signal_detail: {ind.get('tech_signal_detail', 'N/A')}")
    print(f"  ma_alignment: {ind.get('ma_alignment', 'N/A')}")
    print(f"  BOLL_pct_B: {ind.get('BOLL_pct_B', 'N/A')} (应非 None)")
    print(f"  ATR_percentile_90d: {ind.get('ATR_percentile_90d', 'N/A')}")
    print(f"  bull_score / bear_score: {ind.get('bull_score')}/{ind.get('bear_score')}")

    # 基金经理最终决策 + reasoning 检查是否提到引文
    portfolio_dec = fund.get("_portfolio_decision") or {}
    print("\n### 基金经理决策 (portfolio_node)")
    print(f"  recommendation: {portfolio_dec.get('recommendation', 'N/A')}")
    print(f"  confidence: {portfolio_dec.get('confidence', 'N/A')}")
    print(f"  has_conflict: {result.get('has_conflict', False)}")
    reasoning = portfolio_dec.get("reasoning", "")
    print(f"  reasoning (前 500 字):")
    print(f"    {reasoning[:500]}")
    # 检查 reasoning 是否引用了引文里的具体数字或标签
    markers_found = []
    for keyword in ["PE=", "PB=", "ROE=", "MA5=", "MA20=", "RSI14", "MACD", "BOLL", "ATR"]:
        if keyword in reasoning:
            markers_found.append(keyword)
    print(f"  引文关键词命中: {markers_found if markers_found else '(无)'}")

    # 辩论结果(如果触发)
    debate = result.get("debate_outcome")
    if debate:
        print("\n### 辩论结果 (debate_node)")
        print(f"  resolved: {debate.get('resolved_recommendation')}")
        print(f"  confidence_after_debate: {debate.get('confidence_after_debate')}")
        print(f"  deciding_factor: {debate.get('deciding_factor', '')[:200]}")

    # 风控决策
    risk = result.get("risk_decision") or {}
    print("\n### 风控决策 (risk_node)")
    print(f"  approval_status: {risk.get('approval_status')}")
    print(f"  position_pct: {risk.get('position_pct')}%")
    print(f"  stop_loss_pct: {risk.get('stop_loss_pct')}% (ATR 动态应生效)")
    print(f"  ATR_pct 原值: {ind.get('ATR_pct')}%")
    print(f"  2*ATR 期望下限: {2 * (ind.get('ATR_pct') or 0):.1f}%")

    # 最终交易指令
    order = result.get("trade_order") or {}
    print("\n### 最终交易指令 (trade_executor)")
    print(f"  action: {order.get('action')}")
    print(f"  quantity_pct: {order.get('quantity_pct')}%")
    print(f"  simulated: {order.get('simulated')} (必须 True)")
    print(f"  rationale: {(order.get('rationale') or '')[:200]}")

    print("\n" + "=" * 70)


def main():
    symbol = sys.argv[1] if len(sys.argv) > 1 else "600519"

    # Reduce log noise from 3rd party libs
    logger.remove()
    logger.add(sys.stderr, level="WARNING")

    result = asyncio.run(run_smoke(symbol))

    # 全量 JSON 保存到文件供事后审阅
    out_path = Path(f"bench/results/smoke_v22_{symbol}.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # messages 里有 AIMessage 对象不能直接 JSON 序列化,只保留 content
    result_dump = {}
    for k, v in result.items():
        if k == "messages":
            result_dump[k] = [
                {"name": getattr(m, "name", ""), "content": str(getattr(m, "content", m))[:400]}
                for m in v
            ]
        else:
            try:
                json.dumps(v, ensure_ascii=False)
                result_dump[k] = v
            except (TypeError, ValueError):
                result_dump[k] = str(v)[:500]

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result_dump, f, ensure_ascii=False, indent=2)

    print_verification(result)
    print(f"\n完整结果已保存到: {out_path}")


if __name__ == "__main__":
    main()
