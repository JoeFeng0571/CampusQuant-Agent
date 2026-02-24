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

    # ==================== API Keys ====================
    # OpenAI API (推荐使用环境变量或.env文件存储)
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "your-openai-api-key-here")
    OPENAI_MODEL = "gpt-4-turbo-preview"  # 或 "gpt-4o"

    # Anthropic Claude API
    ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "your-anthropic-api-key-here")
    ANTHROPIC_MODEL = "claude-3-5-sonnet-20241022"

    # Binance API (加密货币)
    BINANCE_API_KEY = os.getenv("BINANCE_API_KEY", "your-binance-api-key")
    BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET", "your-binance-secret-key")

    # Binance 代理设置 (针对网络限制地区)
    BINANCE_PROXY = {
        'http': os.getenv('HTTP_PROXY', None),   # 例如: 'http://127.0.0.1:7890'
        'https': os.getenv('HTTPS_PROXY', None),  # 例如: 'http://127.0.0.1:7890'
    }

    # ==================== LLM 选择 ====================
    # 可选: 'openai' 或 'anthropic'
    PRIMARY_LLM_PROVIDER = "anthropic"

    # ==================== 交易对配置 ====================
    # 支持的交易标的列表
    TRADING_SYMBOLS = [
        # A股 (上海: .SH, 深圳: .SZ)
        "600519.SH",  # 贵州茅台
        "000858.SZ",  # 五粮液

        # 港股 (使用 HK 后缀)
        "00700.HK",   # 腾讯控股
        "09988.HK",   # 阿里巴巴-SW

        # 美股 (直接使用股票代码)
        "AAPL",       # 苹果
        "TSLA",       # 特斯拉
        "NVDA",       # 英伟达

        # 加密货币 (CCXT 格式: BASE/QUOTE)
        "BTC/USDT",
        "ETH/USDT",
        "BNB/USDT",
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

    # ==================== 风控参数 ====================
    RISK_PARAMS = {
        # 最大回撤限制 (%)
        "MAX_DRAWDOWN_PCT": 20,

        # 单笔交易最大风险 (占总资金的%)
        "MAX_RISK_PER_TRADE": 2,

        # 最大总持仓比例 (%)
        "MAX_TOTAL_POSITION": 80,

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

    # ==================== 系统参数 ====================
    SYSTEM_PARAMS = {
        # 初始资金 (USD)
        "INITIAL_CAPITAL": 100000,

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
    # Portfolio Manager 综合决策时各智能体的权重
    AGENT_WEIGHTS = {
        "fundamental": 0.30,  # 基本面分析权重
        "sentiment": 0.20,    # 舆情分析权重
        "technical": 0.40,    # 技术分析权重
        "risk": 0.10,         # 风控权重
    }


# 创建全局配置实例
config = Config()


# ==================== 辅助函数 ====================
def validate_config():
    """验证配置完整性"""
    errors = []

    if config.PRIMARY_LLM_PROVIDER == "openai" and "your-openai-api-key" in config.OPENAI_API_KEY:
        errors.append("请设置有效的 OPENAI_API_KEY")

    if config.PRIMARY_LLM_PROVIDER == "anthropic" and "your-anthropic-api-key" in config.ANTHROPIC_API_KEY:
        errors.append("请设置有效的 ANTHROPIC_API_KEY")

    if "your-binance-api-key" in config.BINANCE_API_KEY:
        errors.append("警告: 未设置 Binance API Key，加密货币交易功能将受限")

    if errors:
        print("⚠️ 配置验证失败:")
        for error in errors:
            print(f"  - {error}")
        return False

    print("✅ 配置验证通过")
    return True


if __name__ == "__main__":
    # 测试配置加载
    print("=== 交易系统配置概览 ===")
    print(f"LLM 提供商: {config.PRIMARY_LLM_PROVIDER}")
    print(f"交易标的数量: {len(config.TRADING_SYMBOLS)}")
    print(f"初始资金: ${config.SYSTEM_PARAMS['INITIAL_CAPITAL']:,}")
    print(f"协作模式: {config.SYSTEM_PARAMS['COLLABORATION_MODE']}")
    validate_config()
