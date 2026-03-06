"""
舆情分析师 (Sentiment Analyst)
负责分析新闻、社交媒体情绪，监控市场情绪变化
"""
from typing import Dict, Any, List
from loguru import logger
import json
from datetime import datetime

from .base_agent import BaseAgent
from utils import MarketClassifier, MarketType


class SentimentAgent(BaseAgent):
    """舆情分析师"""

    def __init__(self, llm_client=None):
        super().__init__(name="舆情分析师 (Sentiment Analyst)", llm_client=llm_client)

    def get_system_prompt(self) -> str:
        """系统提示词"""
        return """
你是一位专业的金融舆情分析师，擅长：

1. 新闻情感分析：从财经新闻中提取市场情绪
2. 社交媒体监控：分析 Twitter、Reddit 等平台的投资者情绪
3. 宏观事件影响：评估美联储政策、地缘政治对市场的影响
4. 行业政策解读：分析监管政策变化的影响
5. 恐慌与贪婪指数：判断市场整体情绪

请基于舆情信息，判断市场情绪是乐观、悲观还是中性。
"""

    def analyze(self, symbol: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        进行舆情分析

        Args:
            symbol: 交易标的代码
            data: 包含价格变化、市场数据等

        Returns:
            舆情分析结果
        """
        logger.info(f"📰 {self.name} 开始分析 {symbol}...")

        market_type, _ = MarketClassifier.classify(symbol)

        result = {
            "symbol": symbol,
            "market_type": market_type.value,
            "timestamp": datetime.now().isoformat(),
            "status": "success",
        }

        try:
            # 1. 获取新闻数据（模拟）
            news_data = self._fetch_news(symbol, market_type)
            result["news"] = news_data

            # 2. 获取社交媒体情绪（模拟）
            social_sentiment = self._fetch_social_sentiment(symbol, market_type)
            result["social_sentiment"] = social_sentiment

            # 3. 获取宏观事件（模拟）
            macro_events = self._fetch_macro_events(market_type)
            result["macro_events"] = macro_events

            # 4. LLM 综合分析
            llm_analysis = self._llm_analyze(symbol, news_data, social_sentiment, macro_events)
            result.update(llm_analysis)

            self.log_analysis(symbol, result)

        except Exception as e:
            logger.error(f"❌ {symbol} 舆情分析异常: {e}")
            result["status"] = "error"
            result["error"] = str(e)

        return result

    def _fetch_news(self, symbol: str, market_type: MarketType) -> List[Dict[str, Any]]:
        """
        获取相关新闻（模拟）

        实际应用中可接入:
        - Google News API
        - NewsAPI.org
        - 财联社、东方财富网爬虫
        - Crypto: CoinDesk, CoinTelegraph

        Args:
            symbol: 交易标的
            market_type: 市场类型

        Returns:
            新闻列表
        """
        # 模拟新闻数据
        if market_type == MarketType.CRYPTO:
            mock_news = [
                
                {
                    "title": "SEC 主席表示将加强对加密货币交易所的监管",
                    "source": "Bloomberg",
                    "timestamp": "2024-01-14 15:20:00",
                    "sentiment": "negative",
                },
                {
                    "title": "以太坊 2.0 质押量创历史新高",
                    "source": "The Block",
                    "timestamp": "2024-01-13 09:00:00",
                    "sentiment": "positive",
                },
            ]
        else:
            mock_news = [
                {
                    "title": f"{symbol} 发布Q4财报，营收超预期10%",
                    "source": "财联社",
                    "timestamp": "2024-01-15 09:00:00",
                    "sentiment": "positive",
                },
                {
                    "title": "行业监管政策收紧，多家公司受影响",
                    "source": "华尔街日报",
                    "timestamp": "2024-01-14 16:00:00",
                    "sentiment": "negative",
                },
                {
                    "title": f"{symbol} 宣布回购计划，金额达50亿美元",
                    "source": "路透社",
                    "timestamp": "2024-01-13 14:30:00",
                    "sentiment": "positive",
                },
            ]

        return mock_news

    def _fetch_social_sentiment(self, symbol: str, market_type: MarketType) -> Dict[str, Any]:
        """
        获取社交媒体情绪（模拟）

        实际应用中可接入:
        - Twitter API (X)
        - Reddit API (r/wallstreetbets, r/cryptocurrency)
        - StockTwits
        - 雪球、东方财富吧

        Args:
            symbol: 交易标的
            market_type: 市场类型

        Returns:
            社交媒体情绪数据
        """
        import random

        # 模拟社交媒体情绪分数
        sentiment_score = random.uniform(-0.3, 0.7)  # -1 到 1

        return {
            "overall_score": sentiment_score,
            "data_sources": ["Twitter", "Reddit", "StockTwits"],
            "mention_count": random.randint(500, 5000),
            "positive_ratio": max(0, sentiment_score * 0.5 + 0.5),
            "negative_ratio": max(0, -sentiment_score * 0.5 + 0.3),
            "neutral_ratio": 0.2,
            "trending": sentiment_score > 0.5,
            "top_keywords": ["突破", "买入", "长期持有"] if sentiment_score > 0 else ["下跌", "止损", "观望"],
            "note": "模拟数据，实际应接入 Twitter/Reddit API",
        }

    def _fetch_macro_events(self, market_type: MarketType) -> List[Dict[str, Any]]:
        """
        获取宏观事件（模拟）

        实际应用中可接入:
        - 美联储会议日程
        - 经济数据日历（非农、CPI、GDP）
        - 地缘政治新闻源

        Args:
            market_type: 市场类型

        Returns:
            宏观事件列表
        """
        mock_events = [
            {
                "event": "美联储利率决议",
                "date": "2024-01-31",
                "impact": "high",
                "description": "市场预期维持利率不变，但关注鲍威尔讲话基调",
            },
            {
                "event": "CPI 通胀数据公布",
                "date": "2024-01-15",
                "impact": "medium",
                "description": "预期环比上涨 0.3%，核心 CPI 同比 3.8%",
            },
            {
                "event": "中美贸易谈判进展",
                "date": "2024-01-20",
                "impact": "medium",
                "description": "双方同意降低部分商品关税",
            },
        ]

        if market_type == MarketType.CRYPTO:
            mock_events.append({
                "event": "比特币 ETF 审批结果",
                "date": "2024-01-10",
                "impact": "high",
                "description": "SEC 批准现货比特币 ETF，市场情绪高涨",
            })

        return mock_events

    def _llm_analyze(
        self,
        symbol: str,
        news: List[Dict[str, Any]],
        social_sentiment: Dict[str, Any],
        macro_events: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        使用 LLM 综合分析舆情

        Args:
            symbol: 交易标的
            news: 新闻数据
            social_sentiment: 社交媒体情绪
            macro_events: 宏观事件

        Returns:
            LLM 分析结果
        """
        # 对新闻进行情感分析
        news_summaries = []
        for item in news[:5]:  # 取最近5条
            analysis = self.llm_client.analyze_sentiment(item["title"])
            news_summaries.append({
                "title": item["title"],
                "sentiment_score": analysis.get("sentiment_score", 0),
                "sentiment_label": analysis.get("sentiment_label", "neutral"),
            })

        # 综合分析
        prompt = f"""
请作为舆情分析师，对 {symbol} 的市场情绪进行综合分析：

【新闻舆情】
{json.dumps(news_summaries, ensure_ascii=False, indent=2)}

【社交媒体情绪】
{json.dumps(social_sentiment, ensure_ascii=False, indent=2)}

【宏观事件】
{json.dumps(macro_events, ensure_ascii=False, indent=2)}

请以 JSON 格式返回你的分析：
{{
    "recommendation": "BUY/SELL/HOLD",
    "confidence": 0.0-1.0,
    "overall_sentiment": "乐观/中性/悲观",
    "sentiment_score": -1.0到1.0的情感得分,
    "reasoning": "综合舆情分析（200字内）",
    "key_events": ["影响最大的事件1", "事件2", ...],
    "market_mood": "恐慌/谨慎/中性/乐观/狂热",
    "attention_level": "HIGH/MEDIUM/LOW"
}}
"""

        try:
            result = self.llm_client.generate_structured(
                prompt=prompt,
                system_prompt=self.get_system_prompt(),
            )

            # 添加原始数据引用
            result["news_analyzed"] = len(news_summaries)
            result["social_mentions"] = social_sentiment.get("mention_count", 0)

            return result

        except Exception as e:
            logger.error(f"LLM 舆情分析失败: {e}")
            return {
                "recommendation": "HOLD",
                "confidence": 0.3,
                "overall_sentiment": "中性",
                "sentiment_score": 0.0,
                "reasoning": f"LLM 分析异常: {e}",
                "key_events": [],
                "market_mood": "中性",
                "attention_level": "LOW",
            }


# ==================== 测试代码 ====================
if __name__ == "__main__":
    logger.add("logs/sentiment_agent_test.log", rotation="10 MB")

    agent = SentimentAgent()

    # 测试美股
    print("\n=== 测试美股舆情 ===")
    result = agent.analyze("TSLA", data={})
    print(agent.format_report(result))

    # 测试加密货币
    print("\n=== 测试加密货币舆情 ===")
    result = agent.analyze("BTC/USDT", data={})
    print(agent.format_report(result))
