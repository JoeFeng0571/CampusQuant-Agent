"""
全局配置文件
存放 API Keys、交易对列表、系统参数等
"""
import os
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()


class Config:
    """系统全局配置"""

    # ==================== 主 LLM：阿里云百炼（DashScope）====================
    DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY", "")
    DASHSCOPE_MODEL   = os.getenv("QWEN_MODEL_NAME", "qwen3.5-plus")  # 文本生成模型
    DASHSCOPE_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"  # OpenAI 兼容端点
    DASHSCOPE_EMBEDDING_MODEL = "text-embedding-v3"                     # Embedding 模型

    # ==================== 备用 LLM（按需启用）====================
    # OpenAI API
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
    OPENAI_MODEL   = "gpt-4-turbo-preview"

    # Anthropic Claude API
    ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
    ANTHROPIC_MODEL   = "claude-3-5-sonnet-20241022"

    # ==================== LLM 选择 ====================
    # 可选: 'dashscope' | 'openai' | 'anthropic'
    PRIMARY_LLM_PROVIDER = "dashscope"

    # ==================== 交易标的配置 ====================
    # 支持的交易标的列表（A股 / 港股 / 美股）
    TRADING_SYMBOLS = [
        # A股 (上海: .SH, 深圳: .SZ)
        "600519.SH",  # 贵州茅台
        "000858.SZ",  # 五粮液
        "300750.SZ",  # 宁德时代
        "510300.SH",  # 沪深300ETF

        # 港股 (使用 HK 后缀)
        "00700.HK",   # 腾讯控股
        "09988.HK",   # 阿里巴巴-SW

        # 美股 (直接使用股票代码)
        "AAPL",       # 苹果
        "TSLA",       # 特斯拉
        "NVDA",       # 英伟达
    ]

    # ==================== 技术指标参数 ====================
    TECHNICAL_PARAMS = {
        # 移动平均线周期
        "MA_PERIODS": [5, 10, 20, 60, 120, 144, 300],

        # MACD 参数
        "MACD_FAST": 12,
        "MACD_SLOW": 26,
        "MACD_SIGNAL": 9,

        # RSI 参数
        "RSI_PERIOD": 14,
        "RSI_OVERBOUGHT": 70,
        "RSI_OVERSOLD": 30,

        # KDJ 参数
        "KDJ_N": 9,
        "KDJ_M1": 3,
        "KDJ_M2": 3,

        # 布林带参数
        "BBANDS_PERIOD": 20,
        "BBANDS_STD": 2,

        # ATR 参数 (平均真实波幅)
        "ATR_PERIOD": 14,
    }

    # ==================== 风控参数（大学生保守策略）====================
    RISK_PARAMS = {
        # 最大回撤限制 (%)
        "MAX_DRAWDOWN_PCT": 15,

        # 单笔交易最大风险 (占总资金的%)
        "MAX_RISK_PER_TRADE": 2,

        # 最大总持仓比例（A股≤15%，港股/美股≤10%）
        "MAX_TOTAL_POSITION": 50,

        # 止损比例 (%)
        "STOP_LOSS_PCT": 5,

        # 止盈比例 (%)
        "TAKE_PROFIT_PCT": 15,
    }

    # ==================== 数据获取参数 ====================
    DATA_PARAMS = {
        # 历史数据天数
        "HISTORY_DAYS": 180,

        # 数据更新频率 (分钟)
        "UPDATE_INTERVAL_MIN": 5,

        # 是否使用缓存
        "USE_CACHE": True,
        "CACHE_EXPIRY_MIN": 10,
    }

    # ==================== 港美股 Relay（Cloudflare Workers） ====================
    MARKET_RELAY_BASE_URL = os.getenv("MARKET_RELAY_BASE_URL", "").strip().rstrip("/")
    MARKET_RELAY_TOKEN = os.getenv("MARKET_RELAY_TOKEN", "").strip()

    # ==================== 内地数据 Relay（阿里云内地服务器） ====================
    # 提供 akshare A股/港股/美股数据 + RAG 知识库检索 + 国内新闻源
    INLAND_RELAY_BASE_URL = os.getenv("INLAND_RELAY_BASE_URL", "").strip().rstrip("/")
    INLAND_RELAY_TOKEN = os.getenv("INLAND_RELAY_TOKEN", "").strip()

    # ==================== 系统参数 ====================
    SYSTEM_PARAMS = {
        # 初始资金假设（大学生场景，单位：人民币）
        "INITIAL_CAPITAL": 50000,

        # 日志级别
        "LOG_LEVEL": "INFO",

        # 日志输出目录
        "LOG_DIR": "logs",

        # 是否启用回测模式
        "BACKTEST_MODE": True,

        # Agent 协作模式: "sequential" (流水线) 或 "round_robin" (回合制)
        "COLLABORATION_MODE": "sequential",
    }

    # ==================== Agent 权重配置 ====================
    AGENT_WEIGHTS = {
        "fundamental": 0.30,
        "sentiment": 0.20,
        "technical": 0.40,
        "risk": 0.10,
    }


# 创建全局配置实例
config = Config()


# ==================== 辅助函数 ====================
def validate_config():
    """验证配置完整性"""
    errors = []

    if config.PRIMARY_LLM_PROVIDER == "dashscope":
        key = config.DASHSCOPE_API_KEY
        if not key or len(key) < 20:
            errors.append("请设置有效的 DASHSCOPE_API_KEY")

    elif config.PRIMARY_LLM_PROVIDER == "openai":
        if not config.OPENAI_API_KEY or "your-openai" in config.OPENAI_API_KEY:
            errors.append("请设置有效的 OPENAI_API_KEY")

    elif config.PRIMARY_LLM_PROVIDER == "anthropic":
        if not config.ANTHROPIC_API_KEY or "your-anthropic" in config.ANTHROPIC_API_KEY:
            errors.append("请设置有效的 ANTHROPIC_API_KEY")

    if errors:
        print("⚠️ 配置验证失败:")
        for error in errors:
            print(f"  - {error}")
        return False

    print("✅ 配置验证通过")
    return True


if __name__ == "__main__":
    print("=== CampusQuant-Agent 配置概览 ===")
    print(f"LLM 提供商: {config.PRIMARY_LLM_PROVIDER}")
    print(f"文本模型:   {config.DASHSCOPE_MODEL}")
    print(f"Embedding:  {config.DASHSCOPE_EMBEDDING_MODEL}")
    print(f"交易标的数量: {len(config.TRADING_SYMBOLS)}")
    print(f"假设本金: ¥{config.SYSTEM_PARAMS['INITIAL_CAPITAL']:,}")
    validate_config()
