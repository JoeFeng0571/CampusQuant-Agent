"""
基本面分析师 (Fundamental Analyst)
负责分析财务数据、市盈率、市净率等基本面指标
根据不同市场类型采用差异化的分析框架：
- A股：景气度 + 政策驱动 + EPS增速
- 美港股：价值投资 + PE/PB + 自由现金流
- Crypto：链上数据 + 项目基本面
"""
from typing import Dict, Any
from loguru import logger
import json

from .base_agent import BaseAgent
from utils import MarketClassifier, MarketType


# ==================== 市场差异化分析框架 ====================
MARKET_FUNDAMENTAL_STRATEGIES = {
    MarketType.A_STOCK: {
        "name": "A股景气度策略",
        "system_prompt": """
你是一位专注A股市场的景气度与政策驱动分析专家。

【A股核心分析框架】
1. 行业景气度 (最高权重)：当前行业是否处于上行周期？是否受政策扶持？
2. EPS增速与业绩弹性：预期净利润增速是否高于市场平均(20%+)？是否存在业绩拐点信号？
3. PEG估值法：动态PE / 预期EPS增速，PEG < 1 通常代表低估
4. 资金热度：换手率、量比是否显示主力资金积极介入？
5. 政策催化剂：是否有具体的行业政策、补贴、或监管松绑利好？

【分析原则】
- 不要以"低静态PE/PB"作为主要买入理由，A股估值受情绪驱动更强
- 重点关注"业绩高增+政策利好+资金介入"三重共振
- 景气度拐点（从衰退到复苏）比长期高景气更值得关注
- 国企改革、新质生产力、数字经济等政策主线是重要α来源
""",
        "prompt_framework": """
请以A股景气度分析框架对 {symbol} 进行基本面评估：

【重点评估维度】
1. 行业景气度与政策驱动：此标的所在行业当前处于景气周期哪个阶段？有哪些政策催化剂？
2. 业绩增速评估：EPS增长率是否具有吸引力？是否存在业绩超预期的可能性？
3. PEG评估（而非单一PE）：当前估值相对于业绩增速是否合理？
4. 资金与市场热度：换手率、量比、振幅反映出怎样的资金行为？
5. 主要风险点：行业政策风险、业绩不及预期的风险、板块轮动风险

注意：A股市场政策和景气度权重大于传统静态估值
""",
    },
    MarketType.HK_STOCK: {
        "name": "港股价值投资策略",
        "system_prompt": """
你是一位专注港股市场的价值投资分析专家，融合香港市场特色与全球视野。

【港股核心分析框架】
1. 合理估值 (最高权重)：PE/PB与历史均值、A/H溢价、行业同类比较
2. 自由现金流 (FCF)：FCF是否充裕？FCF Yield是否具有吸引力？
3. 分红与回购：股息率是否可持续增长？是否有积极的回购计划？
4. ROE与竞争护城河：ROE是否持续高于资本成本？公司壁垒是否稳固？
5. 宏观因素：美联储货币政策周期对估值折现率的影响；南向资金流向

【分析原则】
- 港股流动性相对偏弱，需要更高的安全边际（折扣）才值得投资
- 关注A/H溢价：H股相对A股的折价幅度是否提供额外安全边际
- 美联储降息周期对港股（尤其高息股/REITs）是重要催化剂
- 南向资金持续流入是重要的边际买方力量
""",
        "prompt_framework": """
请以价值投资框架对港股 {symbol} 进行基本面评估：

【重点评估维度】
1. 估值合理性：当前PE/PB vs 历史均值 vs 行业同类，是否存在安全边际？
2. 自由现金流与分红：FCF Yield如何？股息率是否稳健且可增长？
3. 护城河分析：ROE水平与稳定性说明什么？公司竞争优势是否可持续？
4. 宏观敏感度：美联储政策、汇率风险、南向资金对该标的的影响？
5. 主要风险：流动性折价、地缘政治风险、港股整体估值压制风险

注意：港股应以价值为锚，寻找安全边际充足的标的
""",
    },
    MarketType.US_STOCK: {
        "name": "美股价值成长策略",
        "system_prompt": """
你是一位专注美股市场的价值成长分析专家，擅长结合基本面与财报季节奏。

【美股核心分析框架】
1. 合理估值 (高权重)：forward PE、EV/EBITDA与历史均值、行业估值比较
2. 自由现金流 (FCF)：FCF Yield、FCF增长率、FCF转化率
3. 财报季指引：最新EPS/营收是否超预期(beat)？管理层Full-year指引上调/下调？
4. 股东回报：股息增长率、回购规模、资本配置优先级
5. 美联储与利率：加息/降息周期对成长股/价值股的估值重估影响

【分析原则】
- 美股定价效率高，寻找"预期差"而非已反映的共识
- 重视财报超预期程度与管理层指引变化（EPS revision trend）
- 区分"便宜但有原因"与"真正低估"：护城河是关键判断标准
- 科技/成长股用DCF+多期FCF增长模型；传统行业用EV/EBITDA
""",
        "prompt_framework": """
请以美股价值成长分析框架对 {symbol} 进行基本面评估：

【重点评估维度】
1. 估值合理性：Forward PE/EV-EBITDA vs 历史区间、同行比较，是否存在低估？
2. FCF质量：自由现金流规模、增长趋势、FCF Yield是否具吸引力？
3. 财报质量：最近几个季度的EPS/营收超预期幅度？指引变化趋势如何？
4. 股东回报能力：分红增长历史、回购力度、管理层资本配置质量？
5. 利率敏感度：在当前利率环境下，估值折现率影响几何？

注意：美股高效市场，"预期差"和"长期复利"是超额收益来源
""",
    },
    MarketType.CRYPTO: {
        "name": "加密货币链上基本面策略",
        "system_prompt": """
你是一位专注加密货币基本面分析的链上数据专家。

【Crypto核心分析框架】
1. 链上活跃度 (最高权重)：活跃地址数、日交易量、用户增长趋势
2. 网络安全性：算力(PoW)/质押率(PoS)是否稳定且增长？
3. 生态系统健康度：DeFi TVL、NFT/GameFi活跃度、开发者活动(GitHub commits)
4. 资金费率与市场结构：永续合约资金费率（正/负）、期货溢价、大户仓位
5. 市场主导地位：BTC/ETH市占率变化、山寨季信号

【分析原则】
- 加密货币无传统PE/PB，链上数据是核心估值工具
- NVT Ratio (市值/日链上交易量) 类似传统市场PE，数值过高代表高估
- 长期持有者(LTH)比例上升 = 筹码集中/底部信号
- 矿工净持仓、交易所净流入是领先指标
""",
        "prompt_framework": """
请以链上基本面框架对加密货币 {symbol} 进行评估：

【重点评估维度】
1. 链上活跃度：活跃地址数、日交易量、用户增长趋势说明网络使用情况如何？
2. 网络安全与去中心化：算力/质押量是否健康？是否存在中心化风险？
3. 生态系统活跃度：DeFi/NFT等应用生态是否繁荣？开发活动是否持续？
4. 市场微观结构：资金费率、大户仓位、长期持有者比例透露什么信号？
5. 估值参考：NVT Ratio等链上估值指标相对历史水平如何？

注意：加密货币以链上数据为核心，技术面和情绪面协同判断
""",
    },
}


class FundamentalAgent(BaseAgent):
    """基本面分析师 - 支持市场差异化分析框架"""

    def __init__(self, llm_client=None):
        super().__init__(name="基本面分析师 (Fundamental Analyst)", llm_client=llm_client)

    def get_system_prompt(self) -> str:
        """默认系统提示词（无市场类型时使用）"""
        return """
你是一位资深的基本面分析专家，擅长：

1. 股票分析：解读财务报表（PE、PB、ROE、EPS、营收增长）
2. 行业景气度：判断行业所处周期与政策催化剂
3. 估值分析：PEG法、DCF法、EV/EBITDA等多维估值工具
4. 加密货币：分析链上数据（活跃地址、Gas费、NVT）和项目基本面

请基于基本面数据，给出投资价值判断和风险提示。
"""

    def get_system_prompt_for_market(self, market_type: MarketType) -> str:
        """根据市场类型返回差异化系统提示词"""
        strategy = MARKET_FUNDAMENTAL_STRATEGIES.get(market_type)
        if strategy:
            return strategy["system_prompt"]
        return self.get_system_prompt()

    def analyze(self, symbol: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        进行基本面分析（市场差异化）

        Args:
            symbol: 交易标的代码
            data: 包含数据情报员提供的信息

        Returns:
            基本面分析结果
        """
        logger.info(f"📊 {self.name} 开始分析 {symbol}...")

        # 判断市场类型
        market_type, _ = MarketClassifier.classify(symbol)

        # 获取市场策略名称（用于日志和UI展示）
        strategy = MARKET_FUNDAMENTAL_STRATEGIES.get(market_type, {})
        strategy_name = strategy.get("name", "通用策略")
        logger.info(f"  └─ 策略路由: {strategy_name}")

        result = {
            "symbol": symbol,
            "market_type": market_type.value,
            "strategy_applied": strategy_name,
            "status": "success",
        }

        try:
            if market_type in [MarketType.A_STOCK, MarketType.HK_STOCK, MarketType.US_STOCK]:
                fundamental_data = self._get_stock_fundamentals(symbol, market_type)
                result["fundamentals"] = fundamental_data

            elif market_type == MarketType.CRYPTO:
                fundamental_data = self._get_crypto_fundamentals(symbol)
                result["fundamentals"] = fundamental_data

            else:
                result["status"] = "unsupported"
                result["error"] = f"不支持的市场类型: {market_type.value}"
                return result

            # LLM 差异化分析
            llm_analysis = self._llm_analyze(symbol, market_type, fundamental_data)
            result.update(llm_analysis)

            self.log_analysis(symbol, result)

        except Exception as e:
            logger.error(f"❌ {symbol} 基本面分析异常: {e}")
            result["status"] = "error"
            result["error"] = str(e)

        return result

    def _get_stock_fundamentals(self, symbol: str, market_type: MarketType) -> Dict[str, Any]:
        """获取股票基本面数据"""
        fundamentals = {}

        try:
            if market_type == MarketType.US_STOCK:
                fundamentals = self._get_us_stock_fundamentals(symbol)
            elif market_type == MarketType.A_STOCK:
                fundamentals = self._get_a_stock_fundamentals(symbol)
            elif market_type == MarketType.HK_STOCK:
                fundamentals = self._get_hk_stock_fundamentals(symbol)

        except Exception as e:
            logger.error(f"股票基本面获取失败: {e}")
            fundamentals["error"] = str(e)

        return fundamentals

    def _get_us_stock_fundamentals(self, symbol: str) -> Dict[str, Any]:
        """获取美股基本面数据（价值成长分析所需指标）"""
        try:
            import yfinance as yf

            ticker = yf.Ticker(symbol)
            info = ticker.info

            # 计算 FCF（若数据可用）
            fcf = "N/A"
            try:
                cashflow = ticker.cashflow
                if not cashflow.empty:
                    op_cf = cashflow.loc["Operating Cash Flow"].iloc[0] if "Operating Cash Flow" in cashflow.index else 0
                    capex = cashflow.loc["Capital Expenditure"].iloc[0] if "Capital Expenditure" in cashflow.index else 0
                    fcf = op_cf + capex  # capex 通常为负数
            except Exception:
                pass

            market_cap = info.get("marketCap", 0)
            fcf_yield = f"{(fcf / market_cap * 100):.1f}%" if (isinstance(fcf, (int, float)) and market_cap) else "N/A"

            return {
                "market_cap": market_cap,
                "PE_ratio": info.get("trailingPE", "N/A"),
                "forward_PE": info.get("forwardPE", "N/A"),
                "PB_ratio": info.get("priceToBook", "N/A"),
                "EPS": info.get("trailingEps", "N/A"),
                "EPS_forward": info.get("forwardEps", "N/A"),
                "revenue": info.get("totalRevenue", "N/A"),
                "revenue_growth": info.get("revenueGrowth", "N/A"),
                "earnings_growth": info.get("earningsGrowth", "N/A"),
                "profit_margin": info.get("profitMargins", "N/A"),
                "ROE": info.get("returnOnEquity", "N/A"),
                "ROA": info.get("returnOnAssets", "N/A"),
                "debt_to_equity": info.get("debtToEquity", "N/A"),
                "free_cash_flow": fcf,
                "fcf_yield": fcf_yield,
                "dividend_yield": info.get("dividendYield", "N/A"),
                "payout_ratio": info.get("payoutRatio", "N/A"),
                "52w_high": info.get("fiftyTwoWeekHigh", "N/A"),
                "52w_low": info.get("fiftyTwoWeekLow", "N/A"),
                "beta": info.get("beta", "N/A"),
                "sector": info.get("sector", "N/A"),
                "industry": info.get("industry", "N/A"),
                "analyst_recommendation": info.get("recommendationKey", "N/A"),
                "target_price": info.get("targetMeanPrice", "N/A"),
            }

        except Exception as e:
            logger.error(f"yfinance 获取失败: {e}")
            return {"error": str(e)}

    def _get_a_stock_fundamentals(self, symbol: str) -> Dict[str, Any]:
        """获取A股基本面数据（景气度分析所需指标）"""
        try:
            import akshare as ak

            stock_code = symbol.split(".")[0]

            # 获取实时行情（含 PE、PB、换手率、量比）
            realtime = ak.stock_zh_a_spot_em()
            stock_data = realtime[realtime['代码'] == stock_code]

            if stock_data.empty:
                return {"error": "未找到股票数据"}

            row = stock_data.iloc[0]

            fundamentals = {
                "name": row.get('名称', 'N/A'),
                "market_cap": row.get('总市值', 'N/A'),
                "PE_ratio_dynamic": row.get('市盈率-动态', 'N/A'),
                "PB_ratio": row.get('市净率', 'N/A'),
                "turnover_rate": row.get('换手率', 'N/A'),
                "amplitude": row.get('振幅', 'N/A'),
                "volume_ratio": row.get('量比', 'N/A'),
                "price_change_pct": row.get('涨跌幅', 'N/A'),
                "current_price": row.get('最新价', 'N/A'),
                "60d_change_pct": row.get('60日涨跌幅', 'N/A'),
                "note_strategy": "A股景气度策略：关注行业上行周期、政策催化与EPS增速，换手率/量比反映资金热度",
            }

            # 尝试获取行业信息
            try:
                industry_df = ak.stock_board_industry_name_em()
                fundamentals["available_sectors"] = "（可查akshare板块数据）"
            except Exception:
                pass

            return fundamentals

        except Exception as e:
            logger.error(f"Akshare A股数据获取失败: {e}")
            return {"error": str(e)}

    def _get_hk_stock_fundamentals(self, symbol: str) -> Dict[str, Any]:
        """获取港股基本面数据（价值投资分析所需指标）"""
        try:
            import akshare as ak

            # 尝试通过 akshare 获取港股数据
            hk_code = symbol.split(".")[0].lstrip("0")  # 去除前导零，如 00700 -> 700
            hk_code_padded = symbol.split(".")[0]  # 保留原始格式

            realtime_hk = ak.stock_hk_spot_em()
            stock_data = realtime_hk[
                (realtime_hk['代码'] == hk_code) | (realtime_hk['代码'] == hk_code_padded)
            ]

            if not stock_data.empty:
                row = stock_data.iloc[0]
                return {
                    "name": row.get('名称', 'N/A'),
                    "current_price": row.get('最新价', 'N/A'),
                    "price_change_pct": row.get('涨跌幅', 'N/A'),
                    "market_cap": row.get('总市值', 'N/A'),
                    "PE_ratio": row.get('市盈率', 'N/A'),
                    "PB_ratio": row.get('市净率', 'N/A'),
                    "note_strategy": "港股价值策略：关注PE/PB安全边际、FCF yield、A/H溢价、南向资金流向",
                    "data_note": "港股部分数据通过akshare获取，FCF/股息等详细数据建议接入港交所API",
                }

        except Exception as e:
            logger.warning(f"Akshare港股实时数据获取失败，使用模拟数据: {e}")

        # 回退到模拟数据
        return {
            "note": "港股基本面数据（模拟）- 建议接入港交所或Bloomberg数据源",
            "market_cap": "模拟数据",
            "PE_ratio": "模拟数据",
            "PB_ratio": "模拟数据",
            "dividend_yield": "模拟数据",
            "note_strategy": "港股价值策略：关注PE/PB安全边际、FCF yield、稳定分红、美联储政策影响",
        }

    def _get_crypto_fundamentals(self, symbol: str) -> Dict[str, Any]:
        """
        获取加密货币基本面数据（链上指标）

        Args:
            symbol: 加密货币交易对

        Returns:
            链上基本面指标（模拟，实际应接入Glassnode/CoinMetrics）
        """
        base_currency = symbol.split("/")[0]

        fundamentals = {
            "asset": base_currency,
            "type": "加密货币",
            "on_chain_metrics": {
                "active_addresses": "模拟: 50万/日 (近30日趋势: 上升)",
                "transaction_count": "模拟: 30万笔/日",
                "hash_rate": "模拟: 400 EH/s (历史高位附近)" if base_currency == "BTC" else "N/A",
                "staking_rate": "模拟: 26% (质押率)" if base_currency == "ETH" else "N/A",
                "gas_fees": "模拟: 中等偏低" if base_currency == "ETH" else "N/A",
                "long_term_holder_pct": "模拟: 68% (筹码集中度高)" if base_currency == "BTC" else "模拟: N/A",
            },
            "market_metrics": {
                "24h_volume": "模拟: $20B",
                "market_dominance": "模拟: 52%" if base_currency == "BTC" else "模拟: 17%",
                "nvt_ratio": "模拟: 85 (历史均值附近，估值合理)" if base_currency == "BTC" else "模拟: N/A",
                "funding_rate": "模拟: +0.01% (略偏多头，无过热)",
                "open_interest": "模拟: 适中",
            },
            "ecosystem": {
                "defi_tvl": "模拟: $50B" if base_currency == "ETH" else "N/A",
                "developer_activity": "模拟: 活跃 (GitHub commits 持续)",
            },
            "note": "实际应接入 Glassnode/CoinMetrics 等链上数据 API 获取真实数据",
            "note_strategy": "Crypto链上策略：NVT估值、活跃地址趋势、LTH比例、资金费率为核心判断依据",
        }

        return fundamentals

    def _llm_analyze(
        self,
        symbol: str,
        market_type: MarketType,
        fundamentals: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        使用 LLM 进行市场差异化基本面分析

        Args:
            symbol: 交易标的
            market_type: 市场类型
            fundamentals: 基本面数据

        Returns:
            LLM 分析结果
        """
        strategy = MARKET_FUNDAMENTAL_STRATEGIES.get(market_type, {})
        system_prompt = strategy.get("system_prompt", self.get_system_prompt())
        prompt_framework = strategy.get("prompt_framework", "")

        # 填充 symbol
        prompt_framework = prompt_framework.format(symbol=symbol)

        prompt = f"""
{prompt_framework}

【原始基本面数据】
{json.dumps(fundamentals, ensure_ascii=False, indent=2)}

请以 JSON 格式返回你的分析结果（严格按照如下结构，不要添加额外字段）：
{{
    "recommendation": "BUY/SELL/HOLD",
    "confidence": 0.0到1.0之间的浮点数,
    "reasoning": "基于{strategy.get('name', '基本面')}框架的分析推理（200字内）",
    "valuation": "高估/合理/低估",
    "key_metrics": {{
        "最关键指标1": "数值与解读",
        "最关键指标2": "数值与解读",
        "最关键指标3": "数值与解读"
    }},
    "key_strengths": ["优势1", "优势2"],
    "key_risks": ["风险1", "风险2"],
    "investment_horizon": "短期(1-4周)/中期(1-3月)/长期(3月+)"
}}
"""

        try:
            result = self.llm_client.generate_structured(
                prompt=prompt,
                system_prompt=system_prompt,
            )
            return result

        except Exception as e:
            logger.error(f"LLM 基本面分析失败: {e}")
            return {
                "recommendation": "HOLD",
                "confidence": 0.3,
                "reasoning": f"LLM 分析异常: {e}",
                "valuation": "未知",
                "key_metrics": {},
                "key_strengths": [],
                "key_risks": ["数据不足或分析异常"],
                "investment_horizon": "中期",
            }


# ==================== 测试代码 ====================
if __name__ == "__main__":
    logger.add("logs/fundamental_agent_test.log", rotation="10 MB")

    agent = FundamentalAgent()

    # 测试美股（价值成长策略）
    print("\n=== 测试美股基本面 (价值成长策略) ===")
    result = agent.analyze("AAPL", data={})
    print(f"策略: {result.get('strategy_applied')}")
    print(agent.format_report(result))

    # 测试A股（景气度策略）
    print("\n=== 测试A股基本面 (景气度策略) ===")
    result = agent.analyze("600519.SH", data={})
    print(f"策略: {result.get('strategy_applied')}")
    print(agent.format_report(result))

    # 测试加密货币（链上策略）
    print("\n=== 测试加密货币基本面 (链上策略) ===")
    result = agent.analyze("BTC/USDT", data={})
    print(f"策略: {result.get('strategy_applied')}")
    print(agent.format_report(result))
