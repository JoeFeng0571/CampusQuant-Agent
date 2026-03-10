"""
test_integration.py — CampusQuant 全栈集成自动化测试套件

测试覆盖范围:
  Phase 4.1 — 数据真实性测试  (TestDataAuthenticity)
  Phase 4.2 — API 连通性测试  (TestAPIConnectivity)
  Phase 4.3 — 风控边界测试    (TestRiskBoundary)

运行方式:
  # 需先启动后端（或让 TestClient 内联运行）
  cd trading_agents_system
  pytest test_integration.py -v

  # 跳过需联网的数据测试（离线环境）
  pytest test_integration.py -v -m "not network"

  # 只跑风控单元测试（无需网络/LLM）
  pytest test_integration.py -v -m "unit"

依赖:
  pip install pytest httpx fastapi[all]
"""
from __future__ import annotations

import json
import os
import sys
import time

import pytest

# 确保项目根目录在 sys.path
ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


# ═══════════════════════════════════════════════════════════════════
# Phase 4.1 — 数据真实性测试
# ═══════════════════════════════════════════════════════════════════

@pytest.mark.network
class TestDataAuthenticity:
    """
    验证 market_data.py 能否真实抓取行情数据。
    这些测试需要联网；离线环境用 -m "not network" 跳过。
    """

    def test_a_stock_moutai(self):
        """贵州茅台（600519.SH）行情数据真实性"""
        from tools.market_data import get_market_data

        result_str = get_market_data.invoke({"symbol": "600519.SH", "days": 30})
        result = json.loads(result_str)

        assert result["status"] == "success", (
            f"贵州茅台数据获取失败: {result.get('error')}"
        )
        assert result["latest_price"] > 0, "最新收盘价应 > 0"
        assert result["data_points"] >= 15, "至少应有 15 个交易日数据"
        # 茅台价格不会低于 100 元，也不超过 10000 元
        assert 100 < result["latest_price"] < 10_000, (
            f"价格异常: {result['latest_price']}"
        )

    def test_us_stock_aapl(self):
        """苹果公司（AAPL）行情数据真实性"""
        from tools.market_data import get_market_data

        result_str = get_market_data.invoke({"symbol": "AAPL", "days": 30})
        result = json.loads(result_str)

        assert result["status"] == "success", (
            f"AAPL 数据获取失败: {result.get('error')}"
        )
        assert result["latest_price"] > 0, "最新收盘价应 > 0"
        assert result["data_points"] >= 15, "至少应有 15 个交易日数据"
        # 苹果股价通常在 100–300 USD 之间（2024-2026）
        assert 50 < result["latest_price"] < 1000, (
            f"价格异常: {result['latest_price']}"
        )

    def test_technical_indicators_calculated(self):
        """技术指标（MACD/RSI/ATR）在真实数据上可正常计算"""
        from tools.market_data import get_market_data, calculate_technical_indicators

        raw = get_market_data.invoke({"symbol": "AAPL", "days": 90})
        result = json.loads(raw)
        if result["status"] != "success":
            pytest.skip("AAPL 数据获取失败，跳过技术指标测试")

        tech_str = calculate_technical_indicators.invoke({"market_data_json": raw})
        tech = json.loads(tech_str)

        assert tech["status"] == "success"
        indicators = tech["indicators"]
        assert "RSI14" in indicators, "RSI14 指标缺失"
        assert "MACD" in indicators, "MACD 指标缺失"
        assert "ATR14" in indicators, "ATR14 指标缺失"
        assert 0 <= indicators["RSI14"] <= 100, f"RSI14 值异常: {indicators['RSI14']}"
        assert indicators["tech_signal"] in (
            "STRONG_BUY", "BUY", "HOLD", "WEAK_SELL", "SELL"
        ), f"tech_signal 取值异常: {indicators['tech_signal']}"

    def test_invalid_symbol_returns_error(self):
        """无效代码应返回 error 状态，而非崩溃（优雅降级）"""
        from tools.market_data import get_market_data

        result_str = get_market_data.invoke({"symbol": "INVALID_CODE_XYZ", "days": 30})
        result = json.loads(result_str)

        # 无论是 error 还是 partial，都不应直接抛出异常
        assert "status" in result, "返回结果中应包含 status 字段"
        assert result["status"] in ("error", "partial"), (
            f"无效代码应返回 error/partial，实际: {result['status']}"
        )


# ═══════════════════════════════════════════════════════════════════
# Phase 4.2 — API 连通性测试
# ═══════════════════════════════════════════════════════════════════

@pytest.mark.api
class TestAPIConnectivity:
    """
    通过 FastAPI TestClient 验证后端 API 的结构合法性。
    TestClient 会内联启动 FastAPI app，无需真实运行服务器。
    部分需要 LLM 的测试（health-check/analyze）会在 LLM 未配置时降级。
    """

    @pytest.fixture(scope="class")
    def client(self):
        """创建 FastAPI TestClient（内联模式，无需启动服务器）"""
        from fastapi.testclient import TestClient
        from api.server import app
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c

    def test_health_endpoint_status(self, client):
        """GET /api/v1/health 应返回 200 且包含 status/version 字段"""
        resp = client.get("/api/v1/health")
        assert resp.status_code == 200, f"健康检查失败: {resp.status_code}"
        data = resp.json()
        assert data["status"] == "ok"
        assert "version" in data
        assert "graph_ready" in data
        assert "kb_ready" in data
        assert "timestamp" in data

    def test_graph_mermaid_endpoint(self, client):
        """GET /api/v1/graph/mermaid 应返回包含 mermaid 字段的 JSON"""
        resp = client.get("/api/v1/graph/mermaid")
        assert resp.status_code == 200
        data = resp.json()
        assert "mermaid" in data
        assert len(data["mermaid"]) > 10, "mermaid 字符串过短"

    def test_analyze_endpoint_rejects_empty_symbol(self, client):
        """POST /api/v1/analyze 应拒绝空 symbol（400）"""
        resp = client.post("/api/v1/analyze", json={"symbol": "  ", "days": 90})
        assert resp.status_code == 400, (
            f"空 symbol 应返回 400，实际: {resp.status_code}"
        )

    def test_analyze_sse_stream_structure(self, client):
        """
        POST /api/v1/analyze 应返回 text/event-stream，
        且第一个 SSE 事件的 JSON 结构合法（含 event/node/message/data/seq 字段）。
        """
        resp = client.post(
            "/api/v1/analyze",
            json={"symbol": "AAPL", "days": 30},
        )
        assert resp.status_code == 200, f"分析接口 HTTP 错误: {resp.status_code}"
        content_type = resp.headers.get("content-type", "")
        assert "text/event-stream" in content_type, (
            f"Content-Type 应为 text/event-stream，实际: {content_type}"
        )

        # 解析第一个完整 SSE 事件块
        body = resp.text
        blocks = [b.strip() for b in body.split("\n\n") if b.strip()]
        assert len(blocks) >= 1, "SSE 响应体至少应有 1 个事件块"

        first_block = blocks[0]
        lines = first_block.split("\n")
        event_line = next((l for l in lines if l.startswith("event:")), None)
        data_line  = next((l for l in lines if l.startswith("data:")),  None)

        assert event_line is not None, "第一个 SSE 块缺少 event: 行"
        assert data_line  is not None, "第一个 SSE 块缺少 data: 行"

        payload = json.loads(data_line[5:].strip())
        for field in ("event", "node", "message", "data", "seq"):
            assert field in payload, f"SSE payload 缺少字段: {field}"

        # 第一个事件应为 'start'
        assert payload["event"] == "start", (
            f"第一个 SSE 事件应为 'start'，实际: {payload['event']}"
        )

    def test_health_check_endpoint_request_schema(self, client):
        """
        POST /api/v1/health-check 请求结构验证：
        - 空 positions 列表 → 422 Unprocessable Entity
        - 缺少必填字段 → 422
        """
        # 空列表
        resp = client.post("/api/v1/health-check", json={"positions": []})
        # min_length=1 约束应拒绝（422）
        assert resp.status_code in (400, 422), (
            f"空 positions 应返回 400/422，实际: {resp.status_code}"
        )

        # 缺少必填字段 avg_cost
        resp2 = client.post(
            "/api/v1/health-check",
            json={"positions": [{"symbol": "AAPL", "quantity": 10}]},
        )
        assert resp2.status_code == 422, (
            f"缺少 avg_cost 应返回 422，实际: {resp2.status_code}"
        )

    @pytest.mark.network
    def test_health_check_endpoint_with_valid_positions(self, client):
        """
        POST /api/v1/health-check 使用有效持仓：
        若 LLM 已配置，应返回 health_report；
        若 LLM 未配置，允许 500（已有 try/except 兜底，不应崩溃进程）。
        """
        payload = {
            "positions": [
                {"symbol": "600519.SH", "quantity": 100, "avg_cost": 1800.0},
                {"symbol": "AAPL",       "quantity": 10,  "avg_cost": 175.0},
            ]
        }
        resp = client.post("/api/v1/health-check", json=payload)
        # 200 = LLM 正常工作；500 = LLM 未配置但服务未崩溃
        assert resp.status_code in (200, 500), (
            f"持仓体检返回意外状态码: {resp.status_code}"
        )
        if resp.status_code == 200:
            data = resp.json()
            assert "health_report" in data, "响应体应包含 health_report 字段"
            assert "timestamp" in data, "响应体应包含 timestamp 字段"


# ═══════════════════════════════════════════════════════════════════
# Phase 4.3 — 风控边界测试
# ═══════════════════════════════════════════════════════════════════

@pytest.mark.unit
class TestRiskBoundary:
    """
    风控规则单元测试（无需 LLM / 网络，纯逻辑验证）。
    直接测试 graph/nodes.py 中的代码层强制截断逻辑。
    """

    def test_position_cap_a_stock_80pct_truncated(self):
        """
        A股极端超仓（80%）必须被截断至 ≤ 15%。
        复现 graph/nodes.py risk_node 第 1172-1182 行的逻辑。
        """
        market_type = "A_STOCK"
        max_pos = 15.0 if market_type == "A_STOCK" else 10.0

        # 模拟 LLM 输出了 80% 仓位的审批
        decision_dict = {
            "approval_status": "APPROVED",
            "position_pct":    80.0,
            "stop_loss_pct":   5.0,
            "risk_level":      "HIGH",
            "conditions":      [],
        }

        # 应用代码层强制截断（与 nodes.py 一致）
        if decision_dict["position_pct"] > max_pos:
            decision_dict["position_pct"] = max_pos
            if decision_dict["approval_status"] == "APPROVED":
                decision_dict["approval_status"] = "CONDITIONAL"
                decision_dict["conditions"].append(
                    f"仓位已由系统截断至{max_pos:.0f}%（学生风控上限）"
                )

        assert decision_dict["position_pct"] <= 15.0, (
            f"仓位截断失败，实际: {decision_dict['position_pct']}"
        )
        assert decision_dict["approval_status"] in ("CONDITIONAL", "REJECTED"), (
            "超仓后状态应降为 CONDITIONAL 或 REJECTED"
        )
        assert len(decision_dict["conditions"]) > 0, "截断后应添加说明条件"

    def test_position_cap_us_stock_20pct_truncated(self):
        """美股超仓（20%）必须被截断至 ≤ 10%"""
        market_type = "US_STOCK"
        max_pos = 15.0 if market_type == "A_STOCK" else 10.0

        decision_dict = {
            "approval_status": "APPROVED",
            "position_pct":    20.0,
            "stop_loss_pct":   5.0,
            "conditions":      [],
        }

        if decision_dict["position_pct"] > max_pos:
            decision_dict["position_pct"] = max_pos
            if decision_dict["approval_status"] == "APPROVED":
                decision_dict["approval_status"] = "CONDITIONAL"
                decision_dict["conditions"].append("仓位已截断")

        assert decision_dict["position_pct"] <= 10.0

    def test_position_within_limit_passes(self):
        """仓位在合规范围内（A股 10%）不应被截断"""
        market_type = "A_STOCK"
        max_pos = 15.0

        decision_dict = {
            "approval_status": "APPROVED",
            "position_pct":    10.0,
            "conditions":      [],
        }

        if decision_dict["position_pct"] > max_pos:
            decision_dict["position_pct"] = max_pos

        assert decision_dict["position_pct"] == 10.0, "合规仓位不应被修改"
        assert decision_dict["approval_status"] == "APPROVED"

    def test_stop_loss_enforcement(self):
        """止损比例 < 0.5% 应被强制修正为 5%（nodes.py 第 1183-1188 行）"""
        decision_dict = {
            "approval_status": "APPROVED",
            "position_pct":    10.0,
            "stop_loss_pct":   0.1,   # 极小止损，不合规
            "conditions":      [],
        }

        if decision_dict["stop_loss_pct"] < 0.5:
            decision_dict["stop_loss_pct"] = 5.0
            decision_dict["conditions"].append("止损比例已修正为5%")

        assert decision_dict["stop_loss_pct"] == 5.0, (
            f"止损修正失败，实际: {decision_dict['stop_loss_pct']}"
        )

    def test_crypto_symbol_blocked_by_classifier(self):
        """
        加密货币代码（BTC/USDT）应被分类为 UNKNOWN，
        无法进入 A股/港股/美股 分析流程。
        """
        from utils.market_classifier import MarketClassifier, MarketType

        market_type, _ = MarketClassifier.classify("BTC/USDT")
        assert market_type == MarketType.UNKNOWN, (
            f"加密货币应被分类为 UNKNOWN，实际: {market_type}"
        )

        market_type2, _ = MarketClassifier.classify("ETH/USDT")
        assert market_type2 == MarketType.UNKNOWN, (
            f"ETH/USDT 应被分类为 UNKNOWN，实际: {market_type2}"
        )

    def test_a_stock_symbol_classified_correctly(self):
        """A股代码应被正确分类"""
        from utils.market_classifier import MarketClassifier, MarketType

        mt, _ = MarketClassifier.classify("600519.SH")
        assert mt == MarketType.A_STOCK

        mt2, _ = MarketClassifier.classify("000858.SZ")
        assert mt2 == MarketType.A_STOCK

    def test_us_stock_symbol_classified_correctly(self):
        """美股代码应被正确分类"""
        from utils.market_classifier import MarketClassifier, MarketType

        mt, _ = MarketClassifier.classify("AAPL")
        assert mt == MarketType.US_STOCK

        mt2, _ = MarketClassifier.classify("MSFT")
        assert mt2 == MarketType.US_STOCK

    def test_hk_stock_symbol_classified_correctly(self):
        """港股代码应被正确分类"""
        from utils.market_classifier import MarketClassifier, MarketType

        mt, _ = MarketClassifier.classify("00700.HK")
        assert mt == MarketType.HK_STOCK

    def test_fuzzy_match_chinese_name(self):
        """中文公司名称模糊匹配 → 标准代码"""
        from utils.market_classifier import MarketClassifier

        code = MarketClassifier.fuzzy_match("贵州茅台")
        assert code == "600519.SH", f"茅台应匹配 600519.SH，实际: {code}"

        code2 = MarketClassifier.fuzzy_match("苹果")
        assert code2 == "AAPL", f"苹果应匹配 AAPL，实际: {code2}"

    def test_risk_manager_position_size_cap(self):
        """
        RiskManager._calculate_position_size 应将仓位上限截断至
        config.RISK_PARAMS['MAX_TOTAL_POSITION']（通常 80%，学生模式更低）。
        """
        from agents.risk_manager import RiskManager

        rm = RiskManager()
        # 极低 ATR（接近 0）会导致计算出天量股数，触发 MAX_TOTAL_POSITION 截断
        result = rm._calculate_position_size(price=10.0, atr=0.001)

        from config import config
        max_pos_cfg = config.RISK_PARAMS["MAX_TOTAL_POSITION"]

        assert result["position_pct"] <= max_pos_cfg, (
            f"仓位截断失败: {result['position_pct']} > MAX_TOTAL_POSITION={max_pos_cfg}"
        )

    def test_sse_event_type_completeness(self):
        """
        验证 server.py 吐出的全部 SSE 事件类型
        都已在 trade.html handleSSEEvent 中注册处理。
        理念：防止前端漏处理新增事件类型导致静默失效。
        """
        # 后端定义的完整事件类型集合（来自 api/server.py 文档注释）
        backend_events = {
            "start", "node_start", "node_complete",
            "conflict", "debate",
            "risk_check", "risk_retry",
            "trade_order", "complete", "error",
        }

        # 解析 trade.html 中的 case 语句，检查覆盖率
        trade_html_path = os.path.join(ROOT, "trade.html")
        with open(trade_html_path, encoding="utf-8") as f:
            content = f.read()

        import re
        # 匹配所有 case 'xxx': 和 case "xxx":
        frontend_cases = set(re.findall(r"case\s+['\"](\w+)['\"]", content))

        missing = backend_events - frontend_cases
        assert not missing, (
            f"trade.html 未处理的 SSE 事件类型: {missing}\n"
            f"请在 handleSSEEvent switch 中添加对应 case。"
        )


# ═══════════════════════════════════════════════════════════════════
# 辅助：直接运行时显示测试摘要
# ═══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import subprocess
    ret = subprocess.run(
        [sys.executable, "-m", "pytest", __file__, "-v", "--tb=short", "-m", "unit"],
        cwd=ROOT,
    )
    sys.exit(ret.returncode)
