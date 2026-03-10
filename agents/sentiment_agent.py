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
你是一位专业的金融舆情分析师，擅长从真实财经新闻中提取市场情绪信号。

你的分析必须：
1. 完全基于提供的真实新闻标题，不得凭空捏造事件
2. 判断新闻整体情感倾向：乐观、悲观或中性
3. 识别对股价影响最大的关键事件
4. 评估市场情绪热度（恐慌/谨慎/中性/乐观/狂热）
5. 给出有据可查的操作建议

若新闻数量不足或内容有限，请如实说明并降低置信度，不得捏造分析依据。
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
            # 1. 获取真实新闻数据
            news_data = self._fetch_news(symbol, market_type)
            result["news"] = news_data

            # 2. LLM 综合分析
            llm_analysis = self._llm_analyze(symbol, news_data)
            result.update(llm_analysis)

            self.log_analysis(symbol, result)

        except Exception as e:
            logger.error(f"❌ {symbol} 舆情分析异常: {e}")
            result["status"] = "error"
            result["error"] = str(e)

        return result

    def _fetch_news(self, symbol: str, market_type: MarketType) -> List[Dict[str, Any]]:
        """
        获取相关新闻（真实数据源）

        A股 / 港股：使用 akshare.stock_news_em（东方财富新闻接口）
        美股       ：使用 yfinance.Ticker.news

        任何网络或解析异常都会被捕获，logger.error 记录后返回空列表，
        绝不让异常向上传播导致整个分析流程崩溃。

        Args:
            symbol: 交易标的代码（标准格式，如 600519.SH / 00700.HK / TSLA）
            market_type: 市场类型枚举

        Returns:
            新闻列表，每项包含 title / source / timestamp 字段
        """
        if market_type in (MarketType.A_STOCK, MarketType.HK_STOCK):
            return self._fetch_news_akshare(symbol)
        elif market_type == MarketType.US_STOCK:
            return self._fetch_news_yfinance(symbol)
        else:
            logger.warning(f"⚠️ 未知市场类型 {market_type}，无法获取新闻")
            return []

    def _fetch_news_akshare(self, symbol: str) -> List[Dict[str, Any]]:
        """
        通过 akshare 东方财富接口获取 A股 / 港股 新闻。

        东方财富接口要求纯数字代码：
          600519.SH → 600519
          00700.HK  → 00700
        """
        try:
            import akshare as ak

            # 剥离交易所后缀，保留纯数字部分
            pure_code = symbol.split(".")[0]

            df = ak.stock_news_em(symbol=pure_code)
            if df is None or df.empty:
                logger.warning(f"⚠️ akshare 未返回 {symbol} 的新闻数据")
                return []

            news = []
            # 取最新 8 条；列名视 akshare 版本而定，做兼容处理
            title_col  = next((c for c in df.columns if "标题" in c or "title" in c.lower()), None)
            time_col   = next((c for c in df.columns if "时间" in c or "date" in c.lower()), None)
            source_col = next((c for c in df.columns if "来源" in c or "source" in c.lower()), None)

            if title_col is None:
                logger.error(f"❌ akshare 返回的 DataFrame 中未找到标题列，列名: {list(df.columns)}")
                return []

            for _, row in df.head(8).iterrows():
                item: Dict[str, Any] = {
                    "title":     str(row[title_col]).strip(),
                    "source":    str(row[source_col]).strip() if source_col else "东方财富",
                    "timestamp": str(row[time_col]).strip()   if time_col  else "",
                }
                news.append(item)

            logger.info(f"✅ akshare 获取 {symbol} 新闻 {len(news)} 条")
            return news

        except ImportError:
            logger.error("❌ akshare 未安装，无法获取 A股/港股 新闻（pip install akshare）")
            return []
        except Exception as e:
            logger.error(f"❌ akshare 获取 {symbol} 新闻失败: {e}")
            return []

    def _fetch_news_yfinance(self, symbol: str) -> List[Dict[str, Any]]:
        """
        通过 yfinance 获取美股新闻。
        yfinance Ticker.news 返回 list[dict]，每项含 title / publisher / providerPublishTime。
        """
        try:
            import yfinance as yf

            ticker = yf.Ticker(symbol)
            raw_news = ticker.news  # list[dict]

            if not raw_news:
                logger.warning(f"⚠️ yfinance 未返回 {symbol} 的新闻数据")
                return []

            news = []
            for item in raw_news[:8]:
                # providerPublishTime 是 Unix 时间戳（整数秒）
                pub_ts = item.get("providerPublishTime", 0)
                try:
                    pub_str = datetime.fromtimestamp(pub_ts).strftime("%Y-%m-%d %H:%M:%S")
                except Exception:
                    pub_str = ""

                news.append({
                    "title":     str(item.get("title", "")).strip(),
                    "source":    str(item.get("publisher", "")).strip(),
                    "timestamp": pub_str,
                })

            logger.info(f"✅ yfinance 获取 {symbol} 新闻 {len(news)} 条")
            return news

        except ImportError:
            logger.error("❌ yfinance 未安装，无法获取美股新闻（pip install yfinance）")
            return []
        except Exception as e:
            logger.error(f"❌ yfinance 获取 {symbol} 新闻失败: {e}")
            return []

    def _llm_analyze(
        self,
        symbol: str,
        news: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        使用 LLM 综合分析真实新闻舆情

        Args:
            symbol: 交易标的
            news:   通过 API 实时抓取的新闻列表

        Returns:
            LLM 分析结果（含 recommendation / confidence / overall_sentiment 等字段）
        """
        if not news:
            logger.warning(f"⚠️ {symbol} 无可用新闻，LLM 分析将返回低置信度默认结果")
            return {
                "recommendation":   "HOLD",
                "confidence":       0.2,
                "overall_sentiment": "中性",
                "sentiment_score":  0.0,
                "reasoning":        "未能获取到实时新闻数据，无法进行舆情分析，建议保持观望。",
                "key_events":       [],
                "market_mood":      "中性",
                "attention_level":  "LOW",
                "news_analyzed":    0,
            }

        # 将新闻列表格式化为可读文本，传入 prompt
        news_text = "\n".join(
            f"{i+1}. [{item.get('timestamp', '')}] {item['title']}  （来源: {item.get('source', '未知')}）"
            for i, item in enumerate(news)
        )

        prompt = f"""以下是通过 API 实时抓取的 {symbol} 股票最新真实新闻（共 {len(news)} 条），
请严格基于这些新闻进行舆情与情感分析，不得引用新闻以外的虚构事件：

{news_text}

请以 JSON 格式返回你的分析结果：
{{
    "recommendation": "BUY/SELL/HOLD",
    "confidence": 0.0到1.0之间的小数,
    "overall_sentiment": "乐观/中性/悲观",
    "sentiment_score": -1.0到1.0之间的小数,
    "reasoning": "基于上述真实新闻标题的综合舆情分析（200字以内）",
    "key_events": ["对股价影响最大的新闻标题1", "新闻标题2"],
    "market_mood": "恐慌/谨慎/中性/乐观/狂热",
    "attention_level": "HIGH/MEDIUM/LOW"
}}
"""

        try:
            result = self.llm_client.generate_structured(
                prompt=prompt,
                system_prompt=self.get_system_prompt(),
            )
            result["news_analyzed"] = len(news)
            return result

        except Exception as e:
            logger.error(f"LLM 舆情分析失败: {e}")
            return {
                "recommendation":   "HOLD",
                "confidence":       0.3,
                "overall_sentiment": "中性",
                "sentiment_score":  0.0,
                "reasoning":        f"LLM 分析异常: {e}",
                "key_events":       [],
                "market_mood":      "中性",
                "attention_level":  "LOW",
                "news_analyzed":    len(news),
            }


# ==================== 测试代码 ====================
if __name__ == "__main__":
    logger.add("logs/sentiment_agent_test.log", rotation="10 MB")

    agent = SentimentAgent()

    # 测试 A 股
    print("\n=== 测试 A 股舆情（贵州茅台）===")
    result = agent.analyze("600519.SH", data={})
    print(agent.format_report(result))

    # 测试美股
    print("\n=== 测试美股舆情（特斯拉）===")
    result = agent.analyze("TSLA", data={})
    print(agent.format_report(result))
