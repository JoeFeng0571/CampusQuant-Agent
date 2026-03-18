"""
基金经理 (Portfolio Manager) - 主脑
负责综合所有智能体的分析结果，做出最终交易决策

策略路由：
- A股：景气度 + 政策驱动策略（提高情绪/技术权重，降低静态估值权重）
- 美股/港股：价值投资策略（提高基本面权重，关注长期支撑）
"""
from typing import Dict, Any, List
from loguru import logger
import json
from datetime import datetime

from .base_agent import BaseAgent
from utils import MarketClassifier, MarketType


# ==================== 市场差异化决策策略配置 ====================
MARKET_PORTFOLIO_STRATEGIES = {
    MarketType.A_STOCK: {
        "name": "A股景气度与政策驱动策略",
        "description": "偏重政策催化、行业景气度与EPS增速，动量技术面信号权重高",
        # 权重：情绪(宏观政策/行业利好) + 技术(MACD动量/趋势) 大幅提升
        # 基本面降权（不看静态PE/PB，关注EPS增速/PEG）
        "weights": {
            "fundamental": 0.20,   # 降低：重EPS增速而非静态估值
            "sentiment": 0.35,     # 提高：政策利好/宏观情绪是A股核心驱动
            "technical": 0.35,     # 提高：MACD/MA动量 + 量比/换手率是重要信号
            "risk": 0.10,          # 保持：风控一票否决
        },
        "decision_focus": [
            "行业是否处于政策扶持期/景气上行周期",
            "EPS增速是否高于市场平均水平（20%+）",
            "MACD/MA趋势是否形成多头排列",
            "量比/换手率是否显示主力资金介入",
            "板块资金轮动方向是否利好本标的",
        ],
        "decision_cautions": [
            "不以低静态PE/PB作为唯一买入依据",
            "关注政策落地执行的不确定性风险",
            "防范板块热点切换导致的快速轮动风险",
            "注意市场整体风险偏好变化",
        ],
        "system_prompt_addon": """
【A股特殊决策原则】
当前采用A股景气度与政策驱动策略：
1. 情绪+技术联合权重 70%：政策催化信号和技术动量信号是主要决策依据
2. 基本面权重 20%：重视EPS增速（PEG法），而非单一低PE/PB
3. 在景气度上行 + 政策利好 + 技术多头排列三重共振时，是最强买入信号
4. 风控官有一票否决权（10%权重），但A股可适当容忍更高技术性风险换取弹性
5. 如各Agent出现严重分歧（景气度好但技术弱），优先等待技术确认信号
""",
    },
    MarketType.HK_STOCK: {
        "name": "港股价值投资策略",
        "description": "偏重基本面定价与安全边际，关注PE/PB、FCF、南向资金",
        "weights": {
            "fundamental": 0.45,   # 大幅提高：价值估值是港股决策核心
            "sentiment": 0.25,     # 适中：美联储政策/南向资金/市场情绪
            "technical": 0.20,     # 降低：短期技术震荡不影响长期价值判断
            "risk": 0.10,
        },
        "decision_focus": [
            "当前PE/PB是否低于历史均值，是否具有安全边际",
            "自由现金流是否充裕，股息率是否稳健",
            "A/H溢价是否提供额外折扣",
            "美联储货币政策走向对港股估值的影响",
            "南向资金是否持续净流入",
        ],
        "decision_cautions": [
            "港股流动性折价需要更高安全边际",
            "地缘政治风险对港股整体估值的压制",
            "汇率波动（港元/人民币/美元）风险",
            "短期技术震荡不能作为主要决策依据",
        ],
        "system_prompt_addon": """
【港股特殊决策原则】
当前采用港股价值投资策略：
1. 基本面权重 45%：合理估值（PE/PB）、FCF质量、分红是核心决策依据
2. 情绪权重 25%：美联储政策周期、南向资金流向是重要宏观背景
3. 技术权重 20%：仅用于辨别入场时机，不影响价值判断方向
4. 必须有充足安全边际（相对历史均值有20%+的估值折扣）才考虑买入
5. 港股"便宜不等于值得买"——需要催化剂（南向资金、港股通纳入、业绩复苏）
""",
    },
    MarketType.US_STOCK: {
        "name": "美股价值成长策略",
        "description": "偏重基本面定价，关注FCF、财报超预期、利率环境",
        "weights": {
            "fundamental": 0.45,   # 大幅提高：美股基本面定价效率高
            "sentiment": 0.25,     # 适中：财报季情绪/美联储政策/分析师预期
            "technical": 0.20,     # 降低：关注长线支撑位，不追短期动量
            "risk": 0.10,
        },
        "decision_focus": [
            "Forward PE是否低于历史均值或行业均值",
            "FCF Yield是否有吸引力（>3%通常为合理）",
            "近期财报EPS/营收超预期幅度及管理层指引趋势",
            "股东回报（分红+回购）是否稳健增长",
            "当前利率环境下DCF估值是否合理",
        ],
        "decision_cautions": [
            "美股高效市场，避免追逐已反映的共识",
            "注意利率上升对高估值成长股的冲击",
            "财报季前后容易出现'买消息卖事实'",
            "避免将短期技术信号误认为趋势改变",
        ],
        "system_prompt_addon": """
【美股特殊决策原则】
当前采用美股价值成长策略：
1. 基本面权重 45%：Forward PE、FCF Yield、财报质量是核心决策依据
2. 情绪权重 25%：财报季指引、分析师预期变化、美联储政策是重要背景
3. 技术权重 20%：识别长期支撑位和趋势方向，不追短期噪音
4. 美股定价效率高，真正的超额收益来自"预期差"——寻找市场低估的优质公司
5. 利率环境敏感：当美联储降息周期时，可适当提高成长股容忍度
""",
    },
}


class PortfolioManager(BaseAgent):
    """基金经理 (决策主脑) - 支持市场差异化策略路由"""

    def __init__(self, llm_client=None):
        super().__init__(name="基金经理 (Portfolio Manager)", llm_client=llm_client)

    def get_system_prompt(self) -> str:
        """默认系统提示词"""
        return """
你是一位经验丰富的基金经理和交易决策专家。你的职责是：

1. 综合分析：整合基本面、技术面、舆情三个维度的分析报告
2. 权衡利弊：平衡收益机会与风险控制
3. 最终决策：给出明确的交易指令（买入/卖出/观望）
4. 逻辑推理：使用 Chain of Thought 解释决策过程

决策原则：
- 风控官有一票否决权
- 多个智能体意见严重分歧时，选择观望
- 必须清晰解释决策逻辑，让投资者理解"为什么"
- 不同市场采用不同的权重体系和分析框架
"""

    def _get_market_system_prompt(self, market_type: MarketType) -> str:
        """根据市场类型返回差异化系统提示词"""
        base_prompt = self.get_system_prompt()
        strategy = MARKET_PORTFOLIO_STRATEGIES.get(market_type, {})
        addon = strategy.get("system_prompt_addon", "")
        return base_prompt + addon

    def _get_market_weights(self, market_type: MarketType) -> Dict[str, float]:
        """根据市场类型返回差异化权重"""
        strategy = MARKET_PORTFOLIO_STRATEGIES.get(market_type)
        if strategy:
            return strategy["weights"]
        # 默认权重（回退）
        return {
            "fundamental": 0.30,
            "sentiment": 0.20,
            "technical": 0.40,
            "risk": 0.10,
        }

    def analyze(self, symbol: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        综合决策（市场差异化）

        Args:
            symbol: 交易标的代码
            data: 包含所有智能体的分析结果
                {
                    "fundamental": {...},
                    "technical": {...},
                    "sentiment": {...},
                    "risk": {...},
                }

        Returns:
            最终交易决策
        """
        logger.info(f"🎯 {self.name} 开始综合决策 {symbol}...")

        # 确定市场类型，选择对应策略
        market_type, _ = MarketClassifier.classify(symbol)
        strategy = MARKET_PORTFOLIO_STRATEGIES.get(market_type, {})
        strategy_name = strategy.get("name", "通用策略")
        weights = self._get_market_weights(market_type)

        logger.info(f"  └─ 策略路由: {strategy_name}")
        logger.info(
            f"  └─ 权重配置: 基本面={weights['fundamental']:.0%} | "
            f"情绪={weights['sentiment']:.0%} | "
            f"技术={weights['technical']:.0%} | "
            f"风控={weights['risk']:.0%}"
        )

        result = {
            "symbol": symbol,
            "market_type": market_type.value,
            "strategy_applied": strategy_name,
            "weights_applied": weights,
            "timestamp": datetime.now().isoformat(),
            "status": "success",
        }

        try:
            # 1. 提取各智能体的建议（使用市场差异化权重）
            recommendations = self._extract_recommendations(data, weights)
            result["agent_recommendations"] = recommendations

            # 2. 计算综合得分
            aggregated_score = self._aggregate_scores(recommendations)
            result["aggregated_score"] = aggregated_score

            # 3. 检查风控审批
            risk_approval = data.get("risk", {}).get("approval_status", "APPROVED")
            result["risk_approval"] = risk_approval

            # 4. LLM 综合决策（CoT 推理，包含市场策略上下文）
            final_decision = self._llm_decision_making(
                symbol, data, recommendations, aggregated_score, risk_approval,
                market_type, strategy
            )
            result.update(final_decision)

            # 5. 生成交易指令
            trade_order = self._generate_trade_order(symbol, result, data)
            result["trade_order"] = trade_order

            self.log_analysis(symbol, result)

            logger.info(
                f"✅ {symbol} 最终决策: {result.get('recommendation', 'HOLD')} | "
                f"置信度: {result.get('confidence', 0):.2f} | "
                f"风控: {risk_approval} | 策略: {strategy_name}"
            )

        except Exception as e:
            logger.error(f"❌ {symbol} 决策过程异常: {e}")
            result["status"] = "error"
            result["error"] = str(e)
            result["recommendation"] = "HOLD"
            result["reasoning"] = "决策系统异常，暂时观望"

        return result

    def _extract_recommendations(
        self,
        data: Dict[str, Any],
        weights: Dict[str, float],
    ) -> Dict[str, Dict[str, Any]]:
        """
        提取各智能体的推荐意见（使用市场差异化权重）

        Args:
            data: 所有智能体的分析结果
            weights: 市场差异化权重字典

        Returns:
            整理后的推荐字典
        """
        recommendations = {}

        # 基本面分析师
        fundamental = data.get("fundamental", {})
        if fundamental:
            recommendations["fundamental"] = {
                "recommendation": fundamental.get("recommendation", "HOLD"),
                "confidence": fundamental.get("confidence", 0.5),
                "reasoning": fundamental.get("reasoning", ""),
                "weight": weights["fundamental"],
                "strategy_applied": fundamental.get("strategy_applied", ""),
            }

        # 技术分析师
        technical = data.get("technical", {})
        if technical:
            recommendations["technical"] = {
                "recommendation": technical.get("recommendation", "HOLD"),
                "confidence": technical.get("confidence", 0.5),
                "reasoning": technical.get("reasoning", ""),
                "weight": weights["technical"],
            }

        # 舆情分析师
        sentiment = data.get("sentiment", {})
        if sentiment:
            recommendations["sentiment"] = {
                "recommendation": sentiment.get("recommendation", "HOLD"),
                "confidence": sentiment.get("confidence", 0.5),
                "reasoning": sentiment.get("reasoning", ""),
                "sentiment_score": sentiment.get("sentiment_score", 0),
                "weight": weights["sentiment"],
            }

        # 风控官
        risk = data.get("risk", {})
        if risk:
            recommendations["risk"] = {
                "recommendation": risk.get("recommendation", "HOLD"),
                "confidence": risk.get("confidence", 0.5),
                "approval_status": risk.get("approval_status", "APPROVED"),
                "risk_level": risk.get("risk_assessment", {}).get("risk_level", "MEDIUM"),
                "weight": weights["risk"],
            }

        return recommendations

    def _aggregate_scores(self, recommendations: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
        """
        加权聚合各智能体的推荐（使用市场差异化权重）

        Args:
            recommendations: 各智能体推荐（含差异化权重）

        Returns:
            聚合结果
        """
        action_to_score = {"BUY": 1, "HOLD": 0, "SELL": -1}

        weighted_sum = 0
        total_weight = 0
        vote_count = {"BUY": 0, "HOLD": 0, "SELL": 0}

        for agent_name, rec in recommendations.items():
            if agent_name == "risk":
                continue  # 风控官单独处理（一票否决制）

            recommendation = rec.get("recommendation", "HOLD")
            confidence = rec.get("confidence", 0.5)
            weight = rec.get("weight", 0.25)

            vote_count[recommendation] += 1

            score = action_to_score[recommendation]
            weighted_sum += score * confidence * weight
            total_weight += weight

        if total_weight > 0:
            aggregated_score = weighted_sum / total_weight
        else:
            aggregated_score = 0

        # 根据得分确定推荐
        if aggregated_score > 0.3:
            aggregated_recommendation = "BUY"
        elif aggregated_score < -0.3:
            aggregated_recommendation = "SELL"
        else:
            aggregated_recommendation = "HOLD"

        return {
            "score": round(aggregated_score, 3),
            "recommendation": aggregated_recommendation,
            "vote_count": vote_count,
            "consensus": max(vote_count, key=vote_count.get),
            "disagreement": len(set(v for v in vote_count.values() if v > 0)) > 1,
        }

    def _llm_decision_making(
        self,
        symbol: str,
        all_data: Dict[str, Any],
        recommendations: Dict[str, Dict[str, Any]],
        aggregated: Dict[str, Any],
        risk_approval: str,
        market_type: MarketType,
        strategy: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        LLM 综合决策（Chain of Thought 推理，含市场策略上下文）

        Args:
            symbol: 交易标的
            all_data: 所有原始分析数据
            recommendations: 各智能体推荐（含差异化权重）
            aggregated: 聚合结果
            risk_approval: 风控审批状态
            market_type: 市场类型
            strategy: 当前市场策略配置

        Returns:
            最终决策
        """
        strategy_name = strategy.get("name", "通用策略")
        decision_focus = strategy.get("decision_focus", [])
        decision_cautions = strategy.get("decision_cautions", [])
        weights = self._get_market_weights(market_type)

        # 构建决策上下文
        context = {
            "symbol": symbol,
            "market_type": market_type.value,
            "strategy_applied": strategy_name,
            "weights_applied": weights,
            "current_price": all_data.get("data", {}).get("latest_price"),
            "agent_recommendations": {
                k: {
                    "recommendation": v["recommendation"],
                    "confidence": v["confidence"],
                    "weight": v["weight"],
                }
                for k, v in recommendations.items()
            },
            "aggregated_analysis": aggregated,
            "risk_approval": risk_approval,
        }

        prompt = f"""
作为基金经理，请使用【{strategy_name}】对 {symbol} 做出最终交易决策。

【当前策略权重配置】
- 基本面分析: {weights['fundamental']:.0%}（{strategy.get('description', '')}）
- 舆情/情绪分析: {weights['sentiment']:.0%}
- 技术面分析: {weights['technical']:.0%}
- 风控: {weights['risk']:.0%}（一票否决权）

【策略重点关注】
{chr(10).join(f"✓ {f}" for f in decision_focus)}

【策略风险警示】
{chr(10).join(f"⚠ {c}" for c in decision_cautions)}

【决策上下文（含差异化权重）】
{json.dumps(context, ensure_ascii=False, indent=2)}

【各智能体详细分析报告】
基本面 ({weights['fundamental']:.0%})：{recommendations.get('fundamental', {}).get('reasoning', 'N/A')}
技术面 ({weights['technical']:.0%})：{recommendations.get('technical', {}).get('reasoning', 'N/A')}
舆情/情绪 ({weights['sentiment']:.0%})：{recommendations.get('sentiment', {}).get('reasoning', 'N/A')}
风控审批：{recommendations.get('risk', {}).get('approval_status', 'N/A')} | 风险等级：{recommendations.get('risk', {}).get('risk_level', 'N/A')}

【Chain of Thought 决策要求】
1. 首先确认当前市场策略（{strategy_name}）的核心驱动因素是否具备
2. 按差异化权重评估各智能体意见的综合影响
3. 如风控状态为 REJECTED，必须选择 HOLD
4. 如智能体意见严重分歧，分析主因并谨慎决策
5. 给出符合当前市场特征的具体决策理由

请以 JSON 格式返回（严格按照如下结构）：
{{
    "recommendation": "BUY/SELL/HOLD",
    "confidence": 0.0到1.0之间的浮点数,
    "reasoning": "Chain of Thought 推理过程（先分析{strategy_name}核心驱动因素，再综合各Agent意见，最后给出决策，300字内）",
    "strategy_verdict": "当前{strategy_name}策略下，最关键的支持/反对决策的因素是什么（100字内）",
    "key_supporting_factors": ["支持决策的关键因素1", "因素2"],
    "key_concerns": ["主要担忧点1", "担忧2"],
    "expected_return": "预期收益率(%)",
    "time_horizon": "建议持仓周期（天）",
    "alternative_scenario": "如果出现X情况，应该采取Y行动"
}}
"""

        system_prompt = self._get_market_system_prompt(market_type)

        try:
            decision = self.llm_client.generate_structured(
                prompt=prompt,
                system_prompt=system_prompt,
            )

            # 风控一票否决
            if risk_approval == "REJECTED":
                decision["recommendation"] = "HOLD"
                decision["confidence"] = min(decision.get("confidence", 0.5), 0.3)
                decision["reasoning"] = (
                    f"[风控否决] {decision.get('reasoning', '')} | "
                    f"风控否决原因: {recommendations.get('risk', {}).get('reasoning', '风险过高')}"
                )

            return decision

        except Exception as e:
            logger.error(f"LLM 决策失败: {e}")
            return {
                "recommendation": "HOLD",
                "confidence": 0.2,
                "reasoning": f"决策系统异常: {e}",
                "strategy_verdict": "系统异常，无法执行策略分析",
                "key_supporting_factors": [],
                "key_concerns": ["系统异常"],
                "expected_return": "0%",
                "time_horizon": "0",
                "alternative_scenario": "等待系统恢复",
            }

    def _generate_trade_order(
        self,
        symbol: str,
        decision: Dict[str, Any],
        all_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """生成具体的交易指令"""
        recommendation = decision.get("recommendation", "HOLD")

        if recommendation == "HOLD":
            return {
                "action": "HOLD",
                "quantity": 0,
                "price": None,
                "message": "观望，不执行交易",
            }

        current_price = all_data.get("data", {}).get("latest_price", 0)
        position_info = all_data.get("risk", {}).get("position_sizing", {})
        stop_loss_info = all_data.get("risk", {}).get("stop_loss_take_profit", {})

        shares = position_info.get("shares", 0)

        return {
            "action": recommendation,
            "symbol": symbol,
            "quantity": shares,
            "price": current_price,
            "order_type": "MARKET",
            "stop_loss": stop_loss_info.get("recommended", {}).get("stop_loss"),
            "take_profit": stop_loss_info.get("recommended", {}).get("take_profit"),
            "expected_cost": position_info.get("position_value", 0),
            "position_pct": position_info.get("position_pct", 0),
            "timestamp": datetime.now().isoformat(),
            "confidence": decision.get("confidence", 0.5),
        }

    def explain_decision(self, result: Dict[str, Any]) -> str:
        """生成人类可读的决策说明"""
        symbol = result.get("symbol", "UNKNOWN")
        recommendation = result.get("recommendation", "HOLD")
        confidence = result.get("confidence", 0.5)
        reasoning = result.get("reasoning", "无详细说明")
        strategy_name = result.get("strategy_applied", "通用策略")
        weights = result.get("weights_applied", {})

        trade_order = result.get("trade_order", {})

        report = f"""
{'='*70}
🎯 {symbol} 交易决策报告  [{strategy_name}]
{'='*70}

【最终决策】 {recommendation}
【置信度】   {confidence:.1%}
【风控审批】 {result.get('risk_approval', 'N/A')}
【市场类型】 {result.get('market_type', 'N/A')}

【差异化权重配置】
  基本面: {weights.get('fundamental', 0):.0%} | 情绪: {weights.get('sentiment', 0):.0%} | 技术: {weights.get('technical', 0):.0%} | 风控: {weights.get('risk', 0):.0%}

【Chain of Thought 推理】
{reasoning}

【策略核心判断】
{result.get('strategy_verdict', 'N/A')}

【关键支持因素】
"""
        for factor in result.get("key_supporting_factors", []):
            report += f"  ✓ {factor}\n"

        report += "\n【主要担忧】\n"
        for concern in result.get("key_concerns", []):
            report += f"  ⚠ {concern}\n"

        report += "\n【各智能体投票】\n"
        vote_count = result.get("aggregated_score", {}).get("vote_count", {})
        for action, count in vote_count.items():
            report += f"  {action}: {count} 票\n"

        if recommendation != "HOLD":
            report += f"""
【交易指令】
  动作:     {trade_order.get('action')}
  数量:     {trade_order.get('quantity')} 股
  价格:     {trade_order.get('price')} (市价单)
  止损:     {trade_order.get('stop_loss')}
  止盈:     {trade_order.get('take_profit')}
  预计成本: ${trade_order.get('expected_cost', 0):,.2f}
  仓位占比: {trade_order.get('position_pct', 0):.1f}%
"""

        report += f"""
【预期与计划】
  预期收益: {result.get('expected_return', 'N/A')}
  持仓周期: {result.get('time_horizon', 'N/A')} 天
  备选方案: {result.get('alternative_scenario', 'N/A')}

{'='*70}
"""
        return report


# ==================== 测试代码 ====================
if __name__ == "__main__":
    logger.add("logs/portfolio_manager_test.log", rotation="10 MB")

    mock_data = {
        "data": {"latest_price": 150.0},
        "fundamental": {
            "recommendation": "BUY",
            "confidence": 0.7,
            "reasoning": "FCF Yield 4.5%，Forward PE 22x低于历史均值，近两季EPS连续超预期",
            "strategy_applied": "美股价值成长策略",
        },
        "technical": {
            "recommendation": "BUY",
            "confidence": 0.8,
            "reasoning": "MA5 上穿 MA20，MACD 金叉，RSI 处于健康区间",
        },
        "sentiment": {
            "recommendation": "HOLD",
            "confidence": 0.6,
            "reasoning": "市场情绪中性偏乐观，美联储暂停加息有利于估值修复",
            "sentiment_score": 0.3,
        },
        "risk": {
            "recommendation": "BUY",
            "confidence": 0.7,
            "approval_status": "APPROVED",
            "risk_assessment": {"risk_level": "MEDIUM"},
            "position_sizing": {
                "shares": 100,
                "position_value": 15000,
                "position_pct": 15,
            },
            "stop_loss_take_profit": {
                "recommended": {
                    "stop_loss": 143,
                    "take_profit": 165,
                },
            },
        },
    }

    pm = PortfolioManager()

    # 测试美股（价值成长策略）
    print("\n=== 美股 (价值成长策略) ===")
    result = pm.analyze("AAPL", data=mock_data)
    print(pm.explain_decision(result))

    # 测试A股（景气度策略）
    print("\n=== A股 (景气度策略) ===")
    result = pm.analyze("600519.SH", data=mock_data)
    print(f"策略: {result.get('strategy_applied')}")
    print(f"权重: {result.get('weights_applied')}")
