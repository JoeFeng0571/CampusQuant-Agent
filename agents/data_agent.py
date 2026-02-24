"""
数据情报员 (Data Agent)
负责获取和标准化不同市场的数据
"""
from typing import Dict, Any
from loguru import logger

from .base_agent import BaseAgent
from utils import DataLoader
from config import config


class DataAgent(BaseAgent):
    """数据情报员"""

    def __init__(self, llm_client=None):
        super().__init__(name="数据情报员 (Data Agent)", llm_client=llm_client)
        self.data_loader = DataLoader()

    def get_system_prompt(self) -> str:
        """系统提示词"""
        return """
你是一名专业的金融数据情报员。你的职责是：
1. 从多个数据源获取准确的市场数据
2. 确保数据的完整性和一致性
3. 对数据质量进行验证
4. 提供数据摘要和关键指标
"""

    def analyze(self, symbol: str, data: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        获取并分析市场数据

        Args:
            symbol: 交易标的代码
            data: 额外参数（如历史天数）

        Returns:
            包含历史数据、实时价格等信息的字典
        """
        logger.info(f"📡 {self.name} 开始获取 {symbol} 的数据...")

        days = data.get("days", config.DATA_PARAMS["HISTORY_DAYS"]) if data else config.DATA_PARAMS["HISTORY_DAYS"]

        result = {
            "symbol": symbol,
            "data_source": self._get_data_source(symbol),
            "status": "success",
        }

        try:
            # 1. 获取历史数据
            df = self.data_loader.get_historical_data(symbol, days=days)

            if df.empty:
                result["status"] = "failed"
                result["error"] = "历史数据获取失败"
                return result

            # 2. 计算统计指标
            latest_close = float(df.iloc[-1]['close'])
            latest_volume = float(df.iloc[-1]['volume'])

            result.update({
                "historical_data": df,
                "latest_price": latest_close,
                "latest_volume": latest_volume,
                "data_points": len(df),
                "date_range": {
                    "start": str(df.iloc[0]['timestamp']),
                    "end": str(df.iloc[-1]['timestamp']),
                },
            })

            # 3. 数据质量分析
            result["data_quality"] = self._analyze_data_quality(df)

            # 4. 获取实时价格（如果可用）
            realtime_price = self.data_loader.get_realtime_price(symbol)
            if realtime_price:
                result["realtime_price"] = realtime_price
                result["price_change"] = (
                    (realtime_price - latest_close) / latest_close * 100
                )

            # 5. 基础统计
            result["statistics"] = {
                "mean_price": float(df['close'].mean()),
                "std_price": float(df['close'].std()),
                "max_price": float(df['high'].max()),
                "min_price": float(df['low'].min()),
                "mean_volume": float(df['volume'].mean()),
            }

            logger.info(f"✅ {symbol} 数据获取成功: {len(df)} 条记录")
            self.log_analysis(symbol, result)

        except Exception as e:
            logger.error(f"❌ {symbol} 数据获取异常: {e}")
            result["status"] = "error"
            result["error"] = str(e)

        return result

    def _get_data_source(self, symbol: str) -> str:
        """获取数据源名称"""
        from utils import MarketClassifier

        market_type, _ = MarketClassifier.classify(symbol)
        return MarketClassifier.get_data_source(market_type)

    def _analyze_data_quality(self, df) -> Dict[str, Any]:
        """
        分析数据质量

        Args:
            df: 历史数据 DataFrame

        Returns:
            数据质量报告
        """
        quality = {
            "completeness": 100.0,  # 完整性
            "issues": [],
        }

        # 检查缺失值
        missing = df.isnull().sum()
        if missing.sum() > 0:
            quality["completeness"] = (1 - missing.sum() / df.size) * 100
            quality["issues"].append(f"存在 {missing.sum()} 个缺失值")

        # 检查零值（成交量不应为0）
        if (df['volume'] == 0).any():
            zero_count = (df['volume'] == 0).sum()
            quality["issues"].append(f"存在 {zero_count} 个零成交量数据点")

        # 检查异常价格（高低价关系）
        if (df['high'] < df['low']).any():
            quality["issues"].append("存在异常价格数据（最高价 < 最低价）")

        if not quality["issues"]:
            quality["issues"].append("数据质量良好")

        return quality

    def get_summary(self, result: Dict[str, Any]) -> str:
        """
        生成数据摘要

        Args:
            result: analyze() 返回的结果

        Returns:
            可读的数据摘要
        """
        if result["status"] != "success":
            return f"❌ 数据获取失败: {result.get('error', '未知错误')}"

        summary = f"""
📊 {result['symbol']} 数据概览

数据源: {result['data_source']}
数据点数: {result['data_points']}
日期范围: {result['date_range']['start']} 至 {result['date_range']['end']}

最新价格: {result['latest_price']:.2f}
"""

        if "realtime_price" in result:
            change = result['price_change']
            arrow = "📈" if change > 0 else "📉"
            summary += f"实时价格: {result['realtime_price']:.2f} {arrow} {change:+.2f}%\n"

        summary += f"""
价格统计:
  - 平均: {result['statistics']['mean_price']:.2f}
  - 最高: {result['statistics']['max_price']:.2f}
  - 最低: {result['statistics']['min_price']:.2f}
  - 波动率: {result['statistics']['std_price']:.2f}

数据质量: {result['data_quality']['completeness']:.1f}%
"""

        return summary


# ==================== 测试代码 ====================
if __name__ == "__main__":
    logger.add("logs/data_agent_test.log", rotation="10 MB")

    agent = DataAgent()

    # 测试不同市场
    test_symbols = ["600519.SH", "AAPL", "BTC/USDT"]

    for symbol in test_symbols:
        print(f"\n{'='*60}")
        result = agent.analyze(symbol, data={"days": 30})

        if result["status"] == "success":
            print(agent.get_summary(result))
        else:
            print(f"❌ {symbol} 分析失败")
