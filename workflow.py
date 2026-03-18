"""
Multi-Agent Trading System - 主程序
协调所有智能体进行协作决策
"""
import sys
from pathlib import Path
from loguru import logger
from datetime import datetime
from typing import Dict, Any, List, Generator
import json

# 添加项目根目录到路径
sys.path.append(str(Path(__file__).parent))

from config import config, validate_config
from agents import (
    DataAgent,
    FundamentalAgent,
    SentimentAgent,
    TechnicalAgent,
    RiskManager,
    PortfolioManager,
)


class TradingWorkflow:
    """交易工作流程编排器"""

    def __init__(self):
        """初始化工作流"""
        logger.info("="*70)
        logger.info("🚀 初始化多智能体交易系统")
        logger.info("="*70)

        # 配置日志
        self._setup_logging()

        # 验证配置
        if not validate_config():
            raise ValueError("配置验证失败，请检查 config.py")

        # 初始化所有智能体
        logger.info("🤖 正在初始化智能体...")
        self.data_agent = DataAgent()
        self.fundamental_agent = FundamentalAgent()
        self.sentiment_agent = SentimentAgent()
        self.technical_agent = TechnicalAgent()
        self.risk_manager = RiskManager()
        self.portfolio_manager = PortfolioManager()

        logger.info("✅ 所有智能体初始化完成\n")

    def _setup_logging(self):
        """配置日志系统"""
        log_dir = Path(config.SYSTEM_PARAMS["LOG_DIR"])
        log_dir.mkdir(exist_ok=True)

        # 主日志文件
        logger.add(
            log_dir / "trading_system_{time:YYYY-MM-DD}.log",
            rotation="00:00",
            retention="30 days",
            level=config.SYSTEM_PARAMS["LOG_LEVEL"],
            format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
        )

        # 决策记录（单独文件）
        logger.add(
            log_dir / "decisions_{time:YYYY-MM-DD}.log",
            rotation="00:00",
            retention="90 days",
            level="INFO",
            filter=lambda record: "DECISION" in record["extra"],
        )

    def run_sequential(self, symbol: str) -> Dict[str, Any]:
        """
        顺序执行模式（流水线）

        工作流:
        1. 数据情报员 获取数据
        2. 基本面、技术面、舆情 三个分析师并行分析
        3. 风控官 进行风险评估
        4. 基金经理 综合决策

        Args:
            symbol: 交易标的代码

        Returns:
            完整的决策结果
        """
        logger.info(f"\n{'='*70}")
        logger.info(f"📊 开始分析: {symbol}")
        logger.info(f"⏰ 时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info(f"🔄 模式: 顺序执行 (Sequential)")
        logger.info(f"{'='*70}\n")

        workflow_result = {
            "symbol": symbol,
            "timestamp": datetime.now().isoformat(),
            "mode": "sequential",
        }

        try:
            # ==================== 阶段 1: 数据获取 ====================
            logger.info("📡 [阶段 1/5] 数据情报员 - 获取市场数据")
            data_result = self.data_agent.analyze(
                symbol,
                data={"days": config.DATA_PARAMS["HISTORY_DAYS"]}
            )

            if data_result["status"] != "success":
                logger.error(f"❌ 数据获取失败: {data_result.get('error')}")
                return {"status": "failed", "error": "数据获取失败"}

            workflow_result["data"] = data_result
            print(self.data_agent.get_summary(data_result))

            # ==================== 阶段 2: 三维分析（并行） ====================
            logger.info("\n📊 [阶段 2/5] 三维度分析 - 基本面 / 技术面 / 舆情")

            # 2.1 基本面分析
            logger.info("  └─ 基本面分析师工作中...")
            fundamental_result = self.fundamental_agent.analyze(symbol, data=data_result)
            workflow_result["fundamental"] = fundamental_result
            self._print_agent_summary("基本面", fundamental_result)

            # 2.2 技术分析
            logger.info("  └─ 技术分析师工作中...")
            technical_result = self.technical_agent.analyze(symbol, data=data_result)
            workflow_result["technical"] = technical_result
            self._print_agent_summary("技术面", technical_result)

            # 2.3 舆情分析
            logger.info("  └─ 舆情分析师工作中...")
            sentiment_result = self.sentiment_agent.analyze(symbol, data=data_result)
            workflow_result["sentiment"] = sentiment_result
            self._print_agent_summary("舆情", sentiment_result)

            # ==================== 阶段 3: 风险评估 ====================
            logger.info("\n🛡️ [阶段 3/5] 风控官 - 风险评估与仓位管理")

            # 整合所有数据给风控官
            risk_input = {**data_result}
            risk_input["indicators"] = technical_result.get("indicators", {})
            risk_input["recommendation"] = technical_result.get("recommendation", "HOLD")
            risk_input["sentiment_score"] = sentiment_result.get("sentiment_score", 0)
            risk_input["price_target"] = technical_result.get("price_target", {})

            risk_result = self.risk_manager.analyze(symbol, data=risk_input)
            workflow_result["risk"] = risk_result
            self._print_risk_summary(risk_result)

            # ==================== 阶段 4: 综合决策 ====================
            logger.info("\n🎯 [阶段 4/5] 基金经理 - 综合决策")

            decision_input = {
                "data": data_result,
                "fundamental": fundamental_result,
                "technical": technical_result,
                "sentiment": sentiment_result,
                "risk": risk_result,
            }

            final_decision = self.portfolio_manager.analyze(symbol, data=decision_input)
            workflow_result["final_decision"] = final_decision

            # ==================== 阶段 5: 输出结果 ====================
            logger.info("\n📋 [阶段 5/5] 生成决策报告")
            decision_report = self.portfolio_manager.explain_decision(final_decision)
            print(decision_report)

            # 记录决策（用于回测）
            self._log_decision(workflow_result)

            workflow_result["status"] = "success"
            logger.info("✅ 分析流程完成\n")

        except Exception as e:
            logger.error(f"❌ 工作流执行异常: {e}")
            workflow_result["status"] = "error"
            workflow_result["error"] = str(e)

        return workflow_result

    def run_streaming(self, symbol: str) -> Generator[Dict[str, Any], None, None]:
        """
        流式运行模式（生成器）：逐步 yield 每个 Agent 的中间结果

        专为 Streamlit 等 UI 框架设计，允许实时渲染每个阶段的输出。

        每次 yield 的格式：
        {
            "stage": int,           # 阶段编号 (1-5)
            "stage_name": str,      # 阶段名称
            "agent": str,           # 当前执行的 Agent 名称
            "status": str,          # "running" | "done" | "error"
            "result": dict | None,  # Agent 输出结果（done/error 时才有）
            "workflow_result": dict,# 当前积累的完整 workflow 结果
        }

        Args:
            symbol: 交易标的代码

        Yields:
            每个 Agent 的执行状态和结果
        """
        logger.info(f"\n{'='*70}")
        logger.info(f"📊 [流式模式] 开始分析: {symbol}")
        logger.info(f"{'='*70}\n")

        workflow_result: Dict[str, Any] = {
            "symbol": symbol,
            "timestamp": datetime.now().isoformat(),
            "mode": "streaming",
        }

        def _make_event(stage: int, stage_name: str, agent: str, status: str, result=None):
            return {
                "stage": stage,
                "stage_name": stage_name,
                "agent": agent,
                "status": status,
                "result": result,
                "workflow_result": workflow_result,
            }

        try:
            # ==================== 阶段 1: 数据获取 ====================
            yield _make_event(1, "数据获取", "数据情报员", "running")

            data_result = self.data_agent.analyze(
                symbol, data={"days": config.DATA_PARAMS["HISTORY_DAYS"]}
            )
            workflow_result["data"] = data_result

            if data_result["status"] != "success":
                yield _make_event(1, "数据获取", "数据情报员", "error", data_result)
                return

            yield _make_event(1, "数据获取", "数据情报员", "done", data_result)

            # ==================== 阶段 2: 三维度分析 ====================
            # 2.1 基本面分析师
            yield _make_event(2, "三维度分析", "基本面分析师", "running")
            fundamental_result = self.fundamental_agent.analyze(symbol, data=data_result)
            workflow_result["fundamental"] = fundamental_result
            yield _make_event(2, "三维度分析", "基本面分析师", "done", fundamental_result)

            # 2.2 技术分析师
            yield _make_event(2, "三维度分析", "技术分析师", "running")
            technical_result = self.technical_agent.analyze(symbol, data=data_result)
            workflow_result["technical"] = technical_result
            yield _make_event(2, "三维度分析", "技术分析师", "done", technical_result)

            # 2.3 舆情分析师
            yield _make_event(2, "三维度分析", "舆情分析师", "running")
            sentiment_result = self.sentiment_agent.analyze(symbol, data=data_result)
            workflow_result["sentiment"] = sentiment_result
            yield _make_event(2, "三维度分析", "舆情分析师", "done", sentiment_result)

            # ==================== 阶段 3: 风险评估 ====================
            yield _make_event(3, "风险评估", "风控官", "running")

            risk_input = {**data_result}
            risk_input["indicators"] = technical_result.get("indicators", {})
            risk_input["recommendation"] = technical_result.get("recommendation", "HOLD")
            risk_input["sentiment_score"] = sentiment_result.get("sentiment_score", 0)
            risk_input["price_target"] = technical_result.get("price_target", {})

            risk_result = self.risk_manager.analyze(symbol, data=risk_input)
            workflow_result["risk"] = risk_result
            yield _make_event(3, "风险评估", "风控官", "done", risk_result)

            # ==================== 阶段 4: 综合决策 ====================
            yield _make_event(4, "综合决策", "基金经理", "running")

            decision_input = {
                "data": data_result,
                "fundamental": fundamental_result,
                "technical": technical_result,
                "sentiment": sentiment_result,
                "risk": risk_result,
            }

            final_decision = self.portfolio_manager.analyze(symbol, data=decision_input)
            workflow_result["final_decision"] = final_decision
            yield _make_event(4, "综合决策", "基金经理", "done", final_decision)

            # ==================== 阶段 5: 完成 ====================
            self._log_decision(workflow_result)
            workflow_result["status"] = "success"
            yield _make_event(5, "分析完成", "系统", "done", workflow_result)

        except Exception as e:
            logger.error(f"❌ 流式工作流异常: {e}")
            workflow_result["status"] = "error"
            workflow_result["error"] = str(e)
            yield _make_event(
                0, "异常", "系统", "error",
                {"error": str(e), "symbol": symbol}
            )

    def run_batch(self, symbols: List[str]) -> Dict[str, Any]:
        """
        批量分析多个交易标的

        Args:
            symbols: 交易标的列表

        Returns:
            所有标的的决策结果
        """
        logger.info(f"\n🔄 批量分析模式: {len(symbols)} 个标的")

        results = {}
        for i, symbol in enumerate(symbols, 1):
            logger.info(f"\n[{i}/{len(symbols)}] 处理: {symbol}")
            try:
                result = self.run_sequential(symbol)
                results[symbol] = result
            except Exception as e:
                logger.error(f"❌ {symbol} 分析失败: {e}")
                results[symbol] = {"status": "error", "error": str(e)}

        # 生成批量摘要
        self._print_batch_summary(results)

        return results

    def _print_agent_summary(self, agent_name: str, result: Dict[str, Any]):
        """打印智能体分析摘要"""
        if result.get("status") != "success":
            print(f"    ❌ {agent_name}: 分析失败")
            return

        recommendation = result.get("recommendation", "N/A")
        confidence = result.get("confidence", 0)
        reasoning = result.get("reasoning", "")[:80]  # 截断

        print(f"    ✓ {agent_name}: {recommendation} (置信度: {confidence:.2f})")
        print(f"      理由: {reasoning}...")

    def _print_risk_summary(self, result: Dict[str, Any]):
        """打印风控摘要"""
        if result.get("status") != "success":
            print("    ❌ 风控评估失败")
            return

        approval = result.get("approval_status", "N/A")
        risk_level = result.get("risk_assessment", {}).get("risk_level", "N/A")
        position_pct = result.get("position_sizing", {}).get("position_pct", 0)

        symbol = "✅" if approval == "APPROVED" else "⚠️" if approval == "CONDITIONAL" else "❌"
        print(f"    {symbol} 审批状态: {approval}")
        print(f"    📊 风险等级: {risk_level} | 建议仓位: {position_pct:.1f}%")

    def _print_batch_summary(self, results: Dict[str, Any]):
        """打印批量分析摘要"""
        print("\n" + "="*70)
        print("📊 批量分析摘要")
        print("="*70)

        buy_count = 0
        sell_count = 0
        hold_count = 0
        error_count = 0

        for symbol, result in results.items():
            if result.get("status") == "error":
                error_count += 1
                continue

            decision = result.get("final_decision", {})
            rec = decision.get("recommendation", "HOLD")

            if rec == "BUY":
                buy_count += 1
            elif rec == "SELL":
                sell_count += 1
            else:
                hold_count += 1

        print(f"总标的数: {len(results)}")
        print(f"  📈 买入: {buy_count}")
        print(f"  📉 卖出: {sell_count}")
        print(f"  ⏸️  观望: {hold_count}")
        print(f"  ❌ 错误: {error_count}")
        print("="*70 + "\n")

    def _log_decision(self, workflow_result: Dict[str, Any]):
        """记录决策到日志（用于回测）"""
        decision = workflow_result.get("final_decision", {})
        trade_order = decision.get("trade_order", {})

        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "symbol": workflow_result["symbol"],
            "decision": decision.get("recommendation", "HOLD"),
            "confidence": decision.get("confidence", 0),
            "trade_order": trade_order,
        }

        logger.bind(DECISION=True).info(json.dumps(log_entry, ensure_ascii=False))


def main():
    """主函数"""
    print("""
    ╔═══════════════════════════════════════════════════════════════╗
    ║                                                               ║
    ║      🤖 多智能体自动化交易系统 (Multi-Agent Trading AI)      ║
    ║                                                               ║
    ║      支持市场: A股 | 港股 | 美股                             ║
    ║      驱动技术: LangChain + LLM (GPT-4 / Claude 3.5)          ║
    ║                                                               ║
    ╚═══════════════════════════════════════════════════════════════╝
    """)

    try:
        # 初始化工作流
        workflow = TradingWorkflow()

        # ==================== 模式选择 ====================
        print("\n请选择运行模式:")
        print("1. 单标的分析")
        print("2. 批量分析 (使用配置文件中的标的列表)")
        print("3. 自定义批量分析")

        choice = input("\n请输入选项 (1/2/3): ").strip()

        if choice == "1":
            # 单标的分析
            symbol = input("请输入交易标的代码 (如 AAPL, 600519.SH, 00700.HK): ").strip()
            if symbol:
                workflow.run_sequential(symbol)

        elif choice == "2":
            # 使用配置文件中的列表
            symbols = config.TRADING_SYMBOLS
            print(f"\n将分析以下 {len(symbols)} 个标的:")
            for s in symbols:
                print(f"  - {s}")

            confirm = input("\n确认开始? (y/n): ").strip().lower()
            if confirm == 'y':
                workflow.run_batch(symbols)

        elif choice == "3":
            # 自定义批量
            symbols_input = input("请输入标的代码（用逗号分隔）: ").strip()
            symbols = [s.strip() for s in symbols_input.split(",") if s.strip()]

            if symbols:
                workflow.run_batch(symbols)
            else:
                print("❌ 未输入有效标的")

        else:
            print("❌ 无效选项")

    except KeyboardInterrupt:
        print("\n\n⚠️ 用户中断程序")
    except Exception as e:
        logger.exception(f"❌ 程序异常: {e}")
        print(f"\n❌ 程序异常: {e}")


if __name__ == "__main__":
    main()
