"""
风控官 (Risk Manager)
负责风险控制、仓位管理、止损止盈设置
"""
from typing import Dict, Any
from loguru import logger
import json

from .base_agent import BaseAgent
from config import config


class RiskManager(BaseAgent):
    """风控官"""

    def __init__(self, llm_client=None):
        super().__init__(name="风控官 (Risk Manager)", llm_client=llm_client)
        self.capital = config.SYSTEM_PARAMS["INITIAL_CAPITAL"]

    def get_system_prompt(self) -> str:
        """系统提示词"""
        return """
你是一位严谨的风险控制专家，你的首要职责是保护资金安全。

你的专长包括:
1. 仓位管理：根据波动率和风险承受能力计算合理仓位
2. 止损止盈：基于技术支撑/阻力位设定止损止盈点
3. 回撤控制：监控最大回撤，及时预警
4. 风险评估：对交易决策进行风险评级

你的原则:
- 单笔交易风险不超过总资金的 2%
- 总持仓不超过 80%
- 高波动品种降低仓位
- 必要时有权否决高风险交易
"""

    def analyze(self, symbol: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        进行风险分析

        Args:
            symbol: 交易标的代码
            data: 包含技术指标、价格信息、交易建议等

        Returns:
            风险分析结果
        """
        logger.info(f"🛡️ {self.name} 开始风险评估 {symbol}...")

        result = {
            "symbol": symbol,
            "status": "success",
        }

        try:
            # 1. 提取必要数据
            current_price = data.get("latest_price", 0)
            atr = data.get("indicators", {}).get("ATR", {}).get("value", 0)
            recommendation = data.get("recommendation", "HOLD")

            # 2. 计算仓位
            position_size = self._calculate_position_size(current_price, atr)
            result["position_sizing"] = position_size

            # 3. 设定止损止盈
            stop_loss_take_profit = self._calculate_stop_loss_take_profit(
                current_price, atr, recommendation, data
            )
            result["stop_loss_take_profit"] = stop_loss_take_profit

            # 4. 风险评估
            risk_assessment = self._assess_risk(data, position_size)
            result["risk_assessment"] = risk_assessment

            # 5. LLM 风控审核
            llm_review = self._llm_review(symbol, recommendation, result)
            result.update(llm_review)

            self.log_analysis(symbol, result)

        except Exception as e:
            logger.error(f"❌ {symbol} 风险分析异常: {e}")
            result["status"] = "error"
            result["error"] = str(e)

        return result

    def _calculate_position_size(self, price: float, atr: float) -> Dict[str, Any]:
        """
        计算建议仓位

        Args:
            price: 当前价格
            atr: 平均真实波幅

        Returns:
            仓位建议
        """
        if price <= 0 or atr <= 0:
            return {
                "shares": 0,
                "position_value": 0,
                "position_pct": 0,
                "reason": "价格或波动率数据无效",
            }

        # 风险金额 = 总资金 * 单笔风险比例
        risk_amount = self.capital * (config.RISK_PARAMS["MAX_RISK_PER_TRADE"] / 100)

        # 每股风险 = ATR (假设止损设在 1 倍 ATR)
        risk_per_share = atr

        # 建议股数 = 风险金额 / 每股风险
        shares = int(risk_amount / risk_per_share)

        # 持仓价值
        position_value = shares * price

        # 持仓占比
        position_pct = (position_value / self.capital) * 100

        # 检查是否超过最大持仓比例
        if position_pct > config.RISK_PARAMS["MAX_TOTAL_POSITION"]:
            # 调整仓位
            max_value = self.capital * (config.RISK_PARAMS["MAX_TOTAL_POSITION"] / 100)
            shares = int(max_value / price)
            position_value = shares * price
            position_pct = (position_value / self.capital) * 100

        return {
            "shares": shares,
            "position_value": round(position_value, 2),
            "position_pct": round(position_pct, 2),
            "risk_per_share": round(risk_per_share, 2),
            "total_capital": self.capital,
        }

    def _calculate_stop_loss_take_profit(
        self,
        price: float,
        atr: float,
        recommendation: str,
        data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        计算止损止盈位

        Args:
            price: 当前价格
            atr: 平均真实波幅
            recommendation: 交易建议
            data: 包含技术指标等信息

        Returns:
            止损止盈建议
        """
        if recommendation == "HOLD":
            return {
                "stop_loss": None,
                "take_profit": None,
                "reason": "观望中，无需设定止损止盈",
            }

        # 方法1: 基于 ATR
        stop_loss_atr = price - (2 * atr) if recommendation == "BUY" else price + (2 * atr)
        take_profit_atr = price + (3 * atr) if recommendation == "BUY" else price - (3 * atr)

        # 方法2: 基于百分比
        stop_loss_pct = price * (1 - config.RISK_PARAMS["STOP_LOSS_PCT"] / 100) if recommendation == "BUY" \
            else price * (1 + config.RISK_PARAMS["STOP_LOSS_PCT"] / 100)
        take_profit_pct = price * (1 + config.RISK_PARAMS["TAKE_PROFIT_PCT"] / 100) if recommendation == "BUY" \
            else price * (1 - config.RISK_PARAMS["TAKE_PROFIT_PCT"] / 100)

        # 方法3: 基于技术位（如果有）
        price_target = data.get("price_target", {})
        support = price_target.get("support")
        resistance = price_target.get("resistance")

        result = {
            "current_price": round(price, 2),
            "recommendation": recommendation,
            "methods": {
                "ATR_based": {
                    "stop_loss": round(stop_loss_atr, 2),
                    "take_profit": round(take_profit_atr, 2),
                    "risk_reward_ratio": round((take_profit_atr - price) / (price - stop_loss_atr), 2) if recommendation == "BUY"
                        else round((price - take_profit_atr) / (stop_loss_atr - price), 2),
                },
                "percentage_based": {
                    "stop_loss": round(stop_loss_pct, 2),
                    "take_profit": round(take_profit_pct, 2),
                },
            },
        }

        if support and resistance:
            result["methods"]["technical_levels"] = {
                "stop_loss": round(support, 2) if recommendation == "BUY" else round(resistance, 2),
                "take_profit": round(resistance, 2) if recommendation == "BUY" else round(support, 2),
            }

        # 推荐使用 ATR 方法（更动态）
        result["recommended"] = result["methods"]["ATR_based"]

        return result

    def _assess_risk(
        self,
        data: Dict[str, Any],
        position_size: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        综合风险评估

        Args:
            data: 所有分析数据
            position_size: 仓位信息

        Returns:
            风险评估报告
        """
        risk_factors = []
        risk_score = 0  # 0-100，越高风险越大

        # 1. 波动率风险
        atr_pct = data.get("indicators", {}).get("ATR", {}).get("volatility_pct", 0)
        if atr_pct > 5:
            risk_factors.append(f"高波动率: {atr_pct:.2f}%")
            risk_score += 30
        elif atr_pct > 3:
            risk_factors.append(f"中等波动率: {atr_pct:.2f}%")
            risk_score += 15

        # 2. 仓位风险
        position_pct = position_size.get("position_pct", 0)
        if position_pct > 50:
            risk_factors.append(f"重仓位: {position_pct:.2f}%")
            risk_score += 25
        elif position_pct > 30:
            risk_factors.append(f"中等仓位: {position_pct:.2f}%")
            risk_score += 10

        # 3. 技术指标风险
        rsi = data.get("indicators", {}).get("RSI", {}).get("value", 50)
        if rsi > 70:
            risk_factors.append("RSI 超买")
            risk_score += 15
        elif rsi < 30:
            risk_factors.append("RSI 超卖（可能反弹）")
            risk_score += 10

        # 4. 舆情风险
        sentiment_score = data.get("sentiment_score", 0)
        if sentiment_score < -0.5:
            risk_factors.append("市场情绪悲观")
            risk_score += 20
        elif sentiment_score > 0.7:
            risk_factors.append("市场情绪过度乐观")
            risk_score += 15

        # 5. 数据质量风险
        if data.get("data_quality", {}).get("completeness", 100) < 90:
            risk_factors.append("数据质量不佳")
            risk_score += 10

        # 风险等级
        if risk_score < 30:
            risk_level = "LOW"
        elif risk_score < 60:
            risk_level = "MEDIUM"
        else:
            risk_level = "HIGH"

        return {
            "risk_score": min(risk_score, 100),
            "risk_level": risk_level,
            "risk_factors": risk_factors if risk_factors else ["风险可控"],
            "max_drawdown_limit": config.RISK_PARAMS["MAX_DRAWDOWN_PCT"],
        }

    def _llm_review(
        self,
        symbol: str,
        recommendation: str,
        risk_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        LLM 风控审核

        Args:
            symbol: 交易标的
            recommendation: 交易建议
            risk_data: 风险数据

        Returns:
            审核结果
        """
        prompt = f"""
请作为风控官，对 {symbol} 的交易决策进行最后审核：

【交易建议】
{recommendation}

【风险评估】
{json.dumps(risk_data, ensure_ascii=False, indent=2)}

请以 JSON 格式返回你的审核结果：
{{
    "approval_status": "APPROVED/REJECTED/CONDITIONAL",
    "recommendation": "BUY/SELL/HOLD",
    "confidence": 0.0-1.0,
    "reasoning": "风控审核意见（150字内）",
    "conditions": ["如果是 CONDITIONAL，列出必须满足的条件"],
    "warnings": ["风险提示"],
    "max_position_allowed": "允许的最大仓位比例(%)"
}}
"""

        try:
            result = self.llm_client.generate_structured(
                prompt=prompt,
                system_prompt=self.get_system_prompt(),
            )
            return result

        except Exception as e:
            logger.error(f"LLM 风控审核失败: {e}")
            return {
                "approval_status": "CONDITIONAL",
                "recommendation": "HOLD",
                "confidence": 0.3,
                "reasoning": f"风控系统异常，建议观望: {e}",
                "conditions": ["等待系统恢复"],
                "warnings": ["风控系统异常"],
                "max_position_allowed": "0%",
            }


# ==================== 测试代码 ====================
if __name__ == "__main__":
    logger.add("logs/risk_manager_test.log", rotation="10 MB")

    risk_manager = RiskManager()

    # 模拟数据
    mock_data = {
        "latest_price": 150.0,
        "recommendation": "BUY",
        "indicators": {
            "ATR": {"value": 3.5, "volatility_pct": 2.3},
            "RSI": {"value": 45},
        },
        "sentiment_score": 0.3,
        "price_target": {
            "support": 145,
            "resistance": 160,
        },
        "data_quality": {"completeness": 95},
    }

    result = risk_manager.analyze("AAPL", data=mock_data)
    print(risk_manager.format_report(result))
