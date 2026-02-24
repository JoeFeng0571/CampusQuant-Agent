"""
多市场数据加载器
统一接口获取 A股、港股、美股、加密货币的行情数据
"""
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from loguru import logger
import time

from config import config
from .market_classifier import MarketClassifier, MarketType


class DataLoader:
    """多市场数据加载器"""

    def __init__(self):
        """初始化数据加载器"""
        self.classifier = MarketClassifier()
        self._init_crypto_client()
        logger.info("✅ DataLoader 初始化完成")

    def _init_crypto_client(self):
        """初始化加密货币客户端 (CCXT)"""
        try:
            import ccxt

            # 创建 Binance 客户端
            self.binance = ccxt.binance({
                'apiKey': config.BINANCE_API_KEY,
                'secret': config.BINANCE_API_SECRET,
                'enableRateLimit': True,
                'proxies': config.BINANCE_PROXY,  # 代理设置
            })

            # 测试连接
            self.binance.load_markets()
            logger.info("✅ Binance 连接成功")

        except Exception as e:
            logger.warning(f"⚠️ Binance 初始化失败: {e}")
            self.binance = None

    def get_historical_data(
        self,
        symbol: str,
        days: int = 180,
        interval: str = "1d",
    ) -> pd.DataFrame:
        """
        获取历史行情数据（统一接口）

        Args:
            symbol: 交易标的代码
            days: 历史天数
            interval: K线周期 ('1d', '1h', '4h' 等)

        Returns:
            包含 OHLCV 的 DataFrame，列名统一为:
            ['timestamp', 'open', 'high', 'low', 'close', 'volume']
        """
        market_type, normalized_symbol = self.classifier.classify(symbol)

        try:
            if market_type == MarketType.A_STOCK:
                df = self._get_a_stock_data(normalized_symbol, days)
            elif market_type == MarketType.HK_STOCK:
                df = self._get_hk_stock_data(normalized_symbol, days)
            elif market_type == MarketType.US_STOCK:
                df = self._get_us_stock_data(normalized_symbol, days)
            elif market_type == MarketType.CRYPTO:
                df = self._get_crypto_data(normalized_symbol, days, interval)
            else:
                raise ValueError(f"不支持的市场类型: {market_type}")

            # 数据验证
            if df is None or df.empty:
                logger.error(f"❌ {symbol} 数据获取失败: 返回空数据")
                return pd.DataFrame()

            # 标准化列名
            df = self._standardize_dataframe(df)

            logger.info(f"✅ {symbol} 数据获取成功: {len(df)} 条记录")
            return df

        except Exception as e:
            logger.error(f"❌ {symbol} 数据获取异常: {e}")
            return pd.DataFrame()

    def _get_a_stock_data(self, symbol: str, days: int) -> pd.DataFrame:
        """获取A股历史数据 (使用 Akshare)"""
        try:
            import akshare as ak

            # 计算起止日期
            end_date = datetime.now().strftime("%Y%m%d")
            start_date = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")

            # 提取纯股票代码（去除 .SH 或 .SZ）
            stock_code = symbol.split(".")[0]

            # 使用 Akshare 获取日线数据
            df = ak.stock_zh_a_hist(
                symbol=stock_code,
                start_date=start_date,
                end_date=end_date,
                adjust="qfq"  # 前复权
            )

            return df

        except Exception as e:
            logger.error(f"Akshare A股数据获取失败: {e}")
            return pd.DataFrame()

    def _get_hk_stock_data(self, symbol: str, days: int) -> pd.DataFrame:
        """获取港股历史数据 (使用 Akshare)"""
        try:
            import akshare as ak

            # 提取纯股票代码
            stock_code = symbol.replace(".HK", "")

            # Akshare 港股接口
            df = ak.stock_hk_hist(symbol=stock_code, period="daily", adjust="qfq")

            # 过滤日期
            if not df.empty and '日期' in df.columns:
                df['日期'] = pd.to_datetime(df['日期'])
                cutoff_date = datetime.now() - timedelta(days=days)
                df = df[df['日期'] >= cutoff_date]

            return df

        except Exception as e:
            logger.error(f"Akshare 港股数据获取失败: {e}")
            return pd.DataFrame()

    def _get_us_stock_data(self, symbol: str, days: int) -> pd.DataFrame:
        """获取美股历史数据 (使用 yfinance)"""
        try:
            import yfinance as yf

            # 计算起止日期
            end_date = datetime.now()
            start_date = end_date - timedelta(days=days)

            # 下载数据
            ticker = yf.Ticker(symbol)
            df = ticker.history(start=start_date, end=end_date)

            return df

        except Exception as e:
            logger.error(f"yfinance 美股数据获取失败: {e}")
            return pd.DataFrame()

    def _get_crypto_data(
        self,
        symbol: str,
        days: int,
        interval: str = "1d",
    ) -> pd.DataFrame:
        """获取加密货币历史数据 (使用 CCXT)"""
        if not self.binance:
            logger.error("Binance 客户端未初始化")
            return pd.DataFrame()

        try:
            # 转换时间周期格式
            timeframe = interval  # CCXT 格式: '1d', '4h', '1h'

            # 计算起始时间戳（毫秒）
            since = int((datetime.now() - timedelta(days=days)).timestamp() * 1000)

            # 获取 OHLCV 数据
            ohlcv = self.binance.fetch_ohlcv(
                symbol=symbol,
                timeframe=timeframe,
                since=since,
                limit=1000,
            )

            # 转换为 DataFrame
            df = pd.DataFrame(
                ohlcv,
                columns=['timestamp', 'open', 'high', 'low', 'close', 'volume']
            )

            # 时间戳转换
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')

            return df

        except Exception as e:
            logger.error(f"CCXT 加密货币数据获取失败: {e}")
            return pd.DataFrame()

    def _standardize_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        标准化 DataFrame 列名和格式

        统一输出格式:
        ['timestamp', 'open', 'high', 'low', 'close', 'volume']
        """
        if df.empty:
            return df

        # 列名映射 (中文 -> 英文)
        column_mapping = {
            # Akshare A股/港股
            '日期': 'timestamp',
            '开盘': 'open',
            '收盘': 'close',
            '最高': 'high',
            '最低': 'low',
            '成交量': 'volume',
            # yfinance 美股
            'Open': 'open',
            'High': 'high',
            'Low': 'low',
            'Close': 'close',
            'Volume': 'volume',
            'Date': 'timestamp',
        }

        # 重命名列
        df = df.rename(columns=column_mapping)

        # 确保必要列存在
        required_columns = ['timestamp', 'open', 'high', 'low', 'close', 'volume']
        for col in required_columns:
            if col not in df.columns:
                logger.warning(f"缺少必要列: {col}")

        # 只保留必要列
        available_columns = [col for col in required_columns if col in df.columns]
        df = df[available_columns]

        # 时间戳标准化
        if 'timestamp' in df.columns:
            df['timestamp'] = pd.to_datetime(df['timestamp'])

        # 重置索引
        df = df.reset_index(drop=True)

        # 按时间排序
        if 'timestamp' in df.columns:
            df = df.sort_values('timestamp').reset_index(drop=True)

        return df

    def get_realtime_price(self, symbol: str) -> Optional[float]:
        """
        获取实时价格

        Args:
            symbol: 交易标的代码

        Returns:
            当前价格
        """
        market_type, normalized_symbol = self.classifier.classify(symbol)

        try:
            if market_type == MarketType.CRYPTO:
                ticker = self.binance.fetch_ticker(normalized_symbol)
                return ticker['last']

            else:
                # 股票市场：获取最新一条数据
                df = self.get_historical_data(symbol, days=5)
                if not df.empty:
                    return float(df.iloc[-1]['close'])

        except Exception as e:
            logger.error(f"实时价格获取失败: {e}")

        return None

    def get_order_book(self, symbol: str, limit: int = 20) -> Dict[str, Any]:
        """
        获取订单簿深度（仅适用于加密货币）

        Args:
            symbol: 交易标的代码
            limit: 深度档位数量

        Returns:
            包含买盘和卖盘的字典
        """
        market_type, normalized_symbol = self.classifier.classify(symbol)

        if market_type != MarketType.CRYPTO:
            logger.warning(f"{symbol} 不支持订单簿查询")
            return {}

        try:
            order_book = self.binance.fetch_order_book(normalized_symbol, limit=limit)
            return {
                'bids': order_book['bids'][:limit],  # 买盘 [[price, amount], ...]
                'asks': order_book['asks'][:limit],  # 卖盘
                'timestamp': order_book['timestamp'],
            }
        except Exception as e:
            logger.error(f"订单簿获取失败: {e}")
            return {}


# ==================== 测试代码 ====================
if __name__ == "__main__":
    logger.add("logs/data_loader_test.log", rotation="10 MB")

    loader = DataLoader()

    # 测试不同市场的数据获取
    test_symbols = [
        "600519.SH",  # A股: 贵州茅台
        "00700.HK",   # 港股: 腾讯
        "AAPL",       # 美股: 苹果
        "BTC/USDT",   # 加密货币: 比特币
    ]

    for symbol in test_symbols:
        print(f"\n{'='*60}")
        print(f"测试标的: {symbol}")
        print('='*60)

        # 获取历史数据
        df = loader.get_historical_data(symbol, days=30)
        if not df.empty:
            print(f"数据行数: {len(df)}")
            print(f"数据列名: {df.columns.tolist()}")
            print(f"最新数据:\n{df.tail(3)}")

        # 获取实时价格
        price = loader.get_realtime_price(symbol)
        if price:
            print(f"\n当前价格: {price}")

        time.sleep(1)  # 避免请求过快
