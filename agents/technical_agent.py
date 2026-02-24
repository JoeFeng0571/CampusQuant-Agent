"""
技术分析师 (Technical Analyst)
负责计算和分析技术指标
"""
import pandas as pd
import numpy as np
from typing import Dict, Any
from loguru import logger
import json

from .base_agent import BaseAgent
from config import config


class TechnicalAgent(BaseAgent):
    """技术分析师"""

    def __init__(self, llm_client=None):
        super().__init__(name="技术分析师 (Technical Analyst)", llm_client=llm_client)

    def get_system_prompt(self) -> str:
        """系统提示词"""
        return """
你是一位经验丰富的技术分析师，精通各种技术指标的含义和应用。

你的专长包括:
1. 趋势判断: 利用移动平均线、MACD、布林带识别趋势
2. 动量分析: 使用 RSI、KDJ 判断超买超卖
3. 成交量分析: 通过 Volume、OBV 确认趋势强度
4. 支撑阻力位判断

请基于技术指标给出明确的买入/卖出/观望建议，并解释你的判断依据。
"""

    def analyze(self, symbol: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        进行技术分析

        Args:
            symbol: 交易标的代码
            data: 必须包含 'historical_data' (DataFrame)

        Returns:
            技术分析结果
        """
        logger.info(f"📈 {self.name} 开始分析 {symbol}...")

        df = data.get("historical_data")
        if df is None or df.empty:
            logger.error(f"❌ {symbol} 缺少历史数据")
            return {"status": "failed", "error": "缺少历史数据"}

        result = {
            "symbol": symbol,
            "status": "success",
        }

        try:
            # 计算所有技术指标
            indicators = self._calculate_indicators(df)
            result["indicators"] = indicators

            # 生成信号
            signals = self._generate_signals(indicators)
            result["signals"] = signals

            # LLM 综合分析
            llm_analysis = self._llm_analyze(symbol, indicators, signals)
            result.update(llm_analysis)

            self.log_analysis(symbol, result)

        except Exception as e:
            logger.error(f"❌ {symbol} 技术分析异常: {e}")
            result["status"] = "error"
            result["error"] = str(e)

        return result

    def _calculate_indicators(self, df: pd.DataFrame) -> Dict[str, Any]:
        """
        计算所有技术指标

        Args:
            df: 包含 OHLCV 的 DataFrame

        Returns:
            指标字典
        """
        indicators = {}

        try:
            import pandas_ta as ta

            # 1. 移动平均线 (MA)
            for period in config.TECHNICAL_PARAMS["MA_PERIODS"]:
                df[f'MA{period}'] = ta.sma(df['close'], length=period)

            indicators["moving_averages"] = {
                f"MA{p}": float(df[f'MA{p}'].iloc[-1])
                for p in config.TECHNICAL_PARAMS["MA_PERIODS"]
                if f'MA{p}' in df.columns and not pd.isna(df[f'MA{p}'].iloc[-1])
            }

            # 2. MACD
            macd = ta.macd(
                df['close'],
                fast=config.TECHNICAL_PARAMS["MACD_FAST"],
                slow=config.TECHNICAL_PARAMS["MACD_SLOW"],
                signal=config.TECHNICAL_PARAMS["MACD_SIGNAL"],
            )
            if macd is not None:
                indicators["MACD"] = {
                    "macd": float(macd[f'MACD_{config.TECHNICAL_PARAMS["MACD_FAST"]}_{config.TECHNICAL_PARAMS["MACD_SLOW"]}_{config.TECHNICAL_PARAMS["MACD_SIGNAL"]}'].iloc[-1]),
                    "signal": float(macd[f'MACDs_{config.TECHNICAL_PARAMS["MACD_FAST"]}_{config.TECHNICAL_PARAMS["MACD_SLOW"]}_{config.TECHNICAL_PARAMS["MACD_SIGNAL"]}'].iloc[-1]),
                    "histogram": float(macd[f'MACDh_{config.TECHNICAL_PARAMS["MACD_FAST"]}_{config.TECHNICAL_PARAMS["MACD_SLOW"]}_{config.TECHNICAL_PARAMS["MACD_SIGNAL"]}'].iloc[-1]),
                }

            # 3. RSI
            rsi = ta.rsi(df['close'], length=config.TECHNICAL_PARAMS["RSI_PERIOD"])
            if rsi is not None:
                indicators["RSI"] = {
                    "value": float(rsi.iloc[-1]),
                    "overbought": config.TECHNICAL_PARAMS["RSI_OVERBOUGHT"],
                    "oversold": config.TECHNICAL_PARAMS["RSI_OVERSOLD"],
                }

            # 4. 布林带 (Bollinger Bands)
            bbands = ta.bbands(
                df['close'],
                length=config.TECHNICAL_PARAMS["BBANDS_PERIOD"],
                std=config.TECHNICAL_PARAMS["BBANDS_STD"],
            )
            if bbands is not None:
                indicators["BollingerBands"] = {
                    "upper": float(bbands[f'BBU_{config.TECHNICAL_PARAMS["BBANDS_PERIOD"]}_{config.TECHNICAL_PARAMS["BBANDS_STD"]}.0'].iloc[-1]),
                    "middle": float(bbands[f'BBM_{config.TECHNICAL_PARAMS["BBANDS_PERIOD"]}_{config.TECHNICAL_PARAMS["BBANDS_STD"]}.0'].iloc[-1]),
                    "lower": float(bbands[f'BBL_{config.TECHNICAL_PARAMS["BBANDS_PERIOD"]}_{config.TECHNICAL_PARAMS["BBANDS_STD"]}.0'].iloc[-1]),
                    "current_price": float(df['close'].iloc[-1]),
                }

            # 5. KDJ (Stochastic)
            stoch = ta.stoch(
                df['high'],
                df['low'],
                df['close'],
                k=config.TECHNICAL_PARAMS["KDJ_N"],
                d=config.TECHNICAL_PARAMS["KDJ_M1"],
            )
            if stoch is not None:
                indicators["KDJ"] = {
                    "K": float(stoch[f'STOCHk_{config.TECHNICAL_PARAMS["KDJ_N"]}_{config.TECHNICAL_PARAMS["KDJ_M1"]}_3'].iloc[-1]),
                    "D": float(stoch[f'STOCHd_{config.TECHNICAL_PARAMS["KDJ_N"]}_{config.TECHNICAL_PARAMS["KDJ_M1"]}_3'].iloc[-1]),
                }

            # 6. ATR (平均真实波幅)
            atr = ta.atr(
                df['high'],
                df['low'],
                df['close'],
                length=config.TECHNICAL_PARAMS["ATR_PERIOD"],
            )
            if atr is not None:
                indicators["ATR"] = {
                    "value": float(atr.iloc[-1]),
                    "volatility_pct": float(atr.iloc[-1] / df['close'].iloc[-1] * 100),
                }

            # 7. OBV (能量潮)
            obv = ta.obv(df['close'], df['volume'])
            if obv is not None:
                indicators["OBV"] = {
                    "value": float(obv.iloc[-1]),
                    "trend": "上升" if obv.iloc[-1] > obv.iloc[-5] else "下降",
                }

            # 8. 成交量分析
            indicators["Volume"] = {
                "current": float(df['volume'].iloc[-1]),
                "average_20d": float(df['volume'].tail(20).mean()),
                "ratio": float(df['volume'].iloc[-1] / df['volume'].tail(20).mean()),
            }

        except Exception as e:
            logger.error(f"技术指标计算失败: {e}")
            indicators["error"] = str(e)

        return indicators

    def _generate_signals(self, indicators: Dict[str, Any]) -> Dict[str, str]:
        """
        根据技术指标生成交易信号

        Args:
            indicators: 技术指标字典

        Returns:
            信号字典
        """
        signals = {}

        try:
            # 1. 趋势信号 (基于 MA)
            ma = indicators.get("moving_averages", {})
            if "MA5" in ma and "MA20" in ma:
                if ma["MA5"] > ma["MA20"]:
                    signals["trend"] = "BUY"  # 短期均线上穿长期均线
                elif ma["MA5"] < ma["MA20"]:
                    signals["trend"] = "SELL"
                else:
                    signals["trend"] = "HOLD"

            # 2. MACD 信号
            macd = indicators.get("MACD", {})
            if macd:
                if macd["histogram"] > 0:
                    signals["macd"] = "BUY"
                elif macd["histogram"] < 0:
                    signals["macd"] = "SELL"
                else:
                    signals["macd"] = "HOLD"

            # 3. RSI 信号
            rsi = indicators.get("RSI", {})
            if rsi:
                if rsi["value"] > rsi["overbought"]:
                    signals["rsi"] = "SELL"  # 超买
                elif rsi["value"] < rsi["oversold"]:
                    signals["rsi"] = "BUY"   # 超卖
                else:
                    signals["rsi"] = "HOLD"

            # 4. 布林带信号
            bb = indicators.get("BollingerBands", {})
            if bb:
                if bb["current_price"] > bb["upper"]:
                    signals["bollinger"] = "SELL"  # 突破上轨
                elif bb["current_price"] < bb["lower"]:
                    signals["bollinger"] = "BUY"   # 突破下轨
                else:
                    signals["bollinger"] = "HOLD"

            # 5. KDJ 信号
            kdj = indicators.get("KDJ", {})
            if kdj:
                if kdj["K"] > 80 and kdj["D"] > 80:
                    signals["kdj"] = "SELL"  # 超买区
                elif kdj["K"] < 20 and kdj["D"] < 20:
                    signals["kdj"] = "BUY"   # 超卖区
                else:
                    signals["kdj"] = "HOLD"

            # 6. 成交量信号
            vol = indicators.get("Volume", {})
            if vol and vol["ratio"] > 1.5:
                signals["volume"] = "STRONG"  # 放量
            elif vol and vol["ratio"] < 0.7:
                signals["volume"] = "WEAK"    # 缩量
            else:
                signals["volume"] = "NORMAL"

        except Exception as e:
            logger.error(f"信号生成失败: {e}")

        return signals

    def _llm_analyze(
        self,
        symbol: str,
        indicators: Dict[str, Any],
        signals: Dict[str, str],
    ) -> Dict[str, Any]:
        """
        使用 LLM 综合分析技术指标

        Args:
            symbol: 交易标的
            indicators: 技术指标
            signals: 交易信号

        Returns:
            LLM 分析结果
        """
        prompt = f"""
请作为技术分析师，对 {symbol} 的技术指标进行综合分析：

【技术指标】
{json.dumps(indicators, ensure_ascii=False, indent=2)}

【初步信号】
{json.dumps(signals, ensure_ascii=False, indent=2)}

请以 JSON 格式返回你的分析：
{{
    "recommendation": "BUY/SELL/HOLD",
    "confidence": 0.0-1.0,
    "reasoning": "你的分析推理（200字内）",
    "key_factors": ["关键因素1", "关键因素2", ...],
    "price_target": {{
        "support": 支撑位价格,
        "resistance": 阻力位价格
    }},
    "risk_level": "HIGH/MEDIUM/LOW"
}}
"""

        try:
            result = self.llm_client.generate_structured(
                prompt=prompt,
                system_prompt=self.get_system_prompt(),
            )
            return result

        except Exception as e:
            logger.error(f"LLM 分析失败: {e}")
            return {
                "recommendation": "HOLD",
                "confidence": 0.3,
                "reasoning": f"LLM 分析异常: {e}",
                "key_factors": [],
                "risk_level": "HIGH",
            }


# ==================== 测试代码 ====================
if __name__ == "__main__":
    logger.add("logs/technical_agent_test.log", rotation="10 MB")

    from agents.data_agent import DataAgent

    # 先获取数据
    data_agent = DataAgent()
    data_result = data_agent.analyze("AAPL", data={"days": 60})

    if data_result["status"] == "success":
        # 技术分析
        tech_agent = TechnicalAgent()
        tech_result = tech_agent.analyze("AAPL", data=data_result)

        print(tech_agent.format_report(tech_result))
