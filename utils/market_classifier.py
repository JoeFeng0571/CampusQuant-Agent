"""
utils/market_classifier.py — 市场分类工具 (CampusQuant 版)

功能:
  1. MarketType 枚举：支持 A_STOCK、HK_STOCK、US_STOCK（已移除 CRYPTO）
  2. MarketClassifier.classify()：根据代码格式判断市场类型
  3. MarketClassifier.fuzzy_match()：中英文公司名称 → 标准代码的模糊映射
     — 大学生用户习惯输入"茅台""英伟达""腾讯"，系统自动转换为标准代码

产品背景:
  CampusQuant-Agent 目标用户为在校大学生，不支持加密货币交易
  （高波动、高杠杆产品对初学者风险极高，已从系统全面移除）
"""
from enum import Enum
from typing import Optional, Tuple
import re
import urllib.request
import urllib.parse


class MarketType(Enum):
    """市场类型枚举（加密货币已移除）"""
    A_STOCK  = "A股"
    HK_STOCK = "港股"
    US_STOCK = "美股"
    UNKNOWN  = "未知"


# ════════════════════════════════════════════════════════════════════
# 模糊匹配字典：中英文公司名称 / 拼音缩写 → 标准代码
#
# 设计原则：覆盖大学生最可能搜索的主流标的
#   • A股：沪深300权重股、热门成长股
#   • 港股：互联网/消费龙头（南向资金主要标的）
#   • 美股：中国学生最熟悉的科技巨头 + 中概股
#
# 匹配规则：输入转小写后查找（不区分大小写）
# ════════════════════════════════════════════════════════════════════

_FUZZY_NAME_MAP: dict[str, str] = {
    # ── A股：消费 ───────────────────────────────────────────────
    "茅台":       "600519.SH",
    "贵州茅台":   "600519.SH",
    "maotai":     "600519.SH",
    "五粮液":     "000858.SZ",
    "五粮":       "000858.SZ",
    "海天":       "603288.SH",
    "海天味业":   "603288.SH",
    "青岛啤酒":   "600600.SH",
    "伊利":       "600887.SH",
    "伊利股份":   "600887.SH",
    "山西汾酒":   "600809.SH",
    "汾酒":       "600809.SH",
    "洋河":       "002304.SZ",
    "洋河股份":   "002304.SZ",

    # ── A股：新能源 & 科技 ──────────────────────────────────────
    "宁德时代":   "300750.SZ",
    "宁德":       "300750.SZ",
    "catl":       "300750.SZ",
    "比亚迪":     "002594.SZ",
    "byd":        "002594.SZ",
    "隆基":       "601012.SH",
    "隆基绿能":   "601012.SH",
    "阳光电源":   "300274.SZ",
    "中芯国际":   "688981.SH",
    "中芯":       "688981.SH",
    "华为":       "不上市",           # 提醒用户华为未上市
    "科大讯飞":   "002230.SZ",
    "讯飞":       "002230.SZ",
    "立讯精密":   "002475.SZ",

    # ── A股：金融 ───────────────────────────────────────────────
    "招商银行":   "600036.SH",
    "招行":       "600036.SH",
    "工商银行":   "601398.SH",
    "工行":       "601398.SH",
    "平安":       "601318.SH",
    "中国平安":   "601318.SH",
    "兴业银行":   "601166.SH",
    "东方财富":   "300059.SZ",

    # ── A股：消费电子 & 家电 ─────────────────────────────────────
    "格力":       "000651.SZ",
    "格力电器":   "000651.SZ",
    "美的":       "000333.SZ",
    "美的集团":   "000333.SZ",
    "海尔":       "600690.SH",
    "海尔智家":   "600690.SH",

    # ── A股：医疗 ───────────────────────────────────────────────
    "迈瑞":       "300760.SZ",
    "迈瑞医疗":   "300760.SZ",
    "药明康德":   "603259.SH",
    "药明":       "603259.SH",

    # ── A股：ETF（大学生最推荐的入门工具）───────────────────────
    "沪深300etf": "510300.SH",
    "沪深300":    "510300.SH",
    "hs300":      "510300.SH",
    "创业板etf":  "159915.SZ",
    "创业板":     "159915.SZ",
    "科创50etf":  "588000.SH",
    "科创50":     "588000.SH",
    "纳指etf":    "513100.SH",
    "纳斯达克etf": "513100.SH",
    "标普500etf": "513500.SH",
    "标普500":    "513500.SH",
    "红利etf":    "510880.SH",
    "央企etf":    "512960.SH",

    # ── 港股：互联网巨头 ─────────────────────────────────────────
    "腾讯":       "00700.HK",
    "腾讯控股":   "00700.HK",
    "tencent":    "00700.HK",
    "阿里":       "09988.HK",
    "阿里巴巴":   "09988.HK",
    "alibaba":    "09988.HK",
    "美团":       "03690.HK",
    "meituan":    "03690.HK",
    "京东":       "09618.HK",
    "jd":         "09618.HK",
    "小米":       "01810.HK",
    "xiaomi":     "01810.HK",
    "快手":       "01024.HK",
    "kuaishou":   "01024.HK",
    "百度":       "09888.HK",
    "baidu":      "09888.HK",
    "网易":       "09999.HK",
    "netease":    "09999.HK",
    "哔哩哔哩":   "09626.HK",
    "b站":        "09626.HK",
    "bilibili":   "09626.HK",
    "携程":       "09961.HK",
    "trip":       "09961.HK",
    "中国移动":   "00941.HK",
    "理想汽车":   "02015.HK",
    "理想":       "02015.HK",
    "蔚来":       "09866.HK",
    "nio":        "09866.HK",

    # ── 美股：科技巨头（FAANG + α）──────────────────────────────
    "苹果":       "AAPL",
    "apple":      "AAPL",
    "英伟达":     "NVDA",
    "nvidia":     "NVDA",
    "微软":       "MSFT",
    "microsoft":  "MSFT",
    "谷歌":       "GOOGL",
    "google":     "GOOGL",
    "alphabet":   "GOOGL",
    "亚马逊":     "AMZN",
    "amazon":     "AMZN",
    "特斯拉":     "TSLA",
    "tesla":      "TSLA",
    "meta":       "META",
    "脸书":       "META",
    "facebook":   "META",
    "奈飞":       "NFLX",
    "netflix":    "NFLX",
    "台积电":     "TSM",
    "tsmc":       "TSM",
    "博通":       "AVGO",
    "amd":        "AMD",
    "高通":       "QCOM",
    "qualcomm":   "QCOM",
    "伯克希尔":   "BRK-B",
    "摩根大通":   "JPM",
    "家得宝":     "HD",
    "沃尔玛":     "WMT",
    "walmart":    "WMT",
    "可口可乐":   "KO",
    "coca-cola":  "KO",
    "星巴克":     "SBUX",
    "starbucks":  "SBUX",
    "迪士尼":     "DIS",
    "disney":     "DIS",

    # ── 美股：中概股 ─────────────────────────────────────────────
    "拼多多":     "PDD",
    "pinduoduo":  "PDD",
    "网易美股":   "NTES",
    "爱奇艺":     "IQ",
    "b站美股":    "BILI",
    "好未来":     "TAL",
    "新东方":     "EDU",
}


class MarketClassifier:
    """
    市场分类器

    对外方法：
      classify(symbol)      → (MarketType, 标准化代码)
      fuzzy_match(query)    → 标准代码（若无匹配返回原始输入）
      get_data_source(...)  → 数据源名称
      normalize_symbol(...) → 标准化代码
      get_exchange(...)     → 交易所名称
    """

    @staticmethod
    def fuzzy_match(query: str) -> str:
        """
        根据用户输入（中文名/英文名/代码）模糊匹配标准代码。

        匹配逻辑（按优先级）：
          1. 直接精确匹配（不区分大小写）——命中 _FUZZY_NAME_MAP 快速缓存
          2. 前缀匹配（用户输入是映射键的前缀，≥2字符）
          3. HTTP 回退——调用新浪财经 Suggest API 全市场搜索（仅非标准代码触发）
             URL: http://suggest3.sinajs.cn/suggest/type=&key={query}
             超时 3 秒，任何异常静默降级
          4. 无匹配 → 返回原始输入大写（可能已是标准代码如 AAPL/600519.SH）

        特殊情况：
          - "华为" 匹配后返回原始值并提示（华为未上市）
          - 若匹配结果为 "不上市"，返回原始查询

        Args:
            query: 用户原始输入（如"英伟达"/"NVDA"/"苹果"/"光大银行"）

        Returns:
            标准代码字符串（如 "NVDA"/"600519.SH"/"601818.SH"），或原始输入大写
        """
        if not query:
            return query

        query_lower = query.lower().strip()

        # 1. 精确匹配
        if query_lower in _FUZZY_NAME_MAP:
            result = _FUZZY_NAME_MAP[query_lower]
            return query if result == "不上市" else result

        # 2. 前缀匹配（用户输入是某个键的前缀，且至少2字符）
        if len(query_lower) >= 2:
            for key, code in _FUZZY_NAME_MAP.items():
                if key.startswith(query_lower) and code != "不上市":
                    return code

        # 3. HTTP 回退：新浪财经 Suggest API
        #    若输入已像标准代码（纯大写字母/数字/点），跳过网络请求
        _STANDARD_CODE_RE = re.compile(r'^[A-Z0-9][A-Z0-9.\-]{1,11}$')
        if not _STANDARD_CODE_RE.match(query.strip().upper()):
            try:
                url = (
                    "http://suggest3.sinajs.cn/suggest/type=&key="
                    + urllib.parse.quote(query.strip(), encoding="utf-8")
                )
                req = urllib.request.Request(
                    url,
                    headers={"User-Agent": "Mozilla/5.0 (compatible; CampusQuant/1.0)"},
                )
                with urllib.request.urlopen(req, timeout=3) as resp:
                    raw = resp.read().decode("gbk", errors="replace")

                # 响应格式: var suggestvalue="名称,类型,代码,简称,拼音,...|名称2,...";
                m = re.search(r'"([^"]+)"', raw)
                if m:
                    first_entry = m.group(1).split("|")[0]
                    fields = first_entry.split(",")
                    if len(fields) >= 3:
                        code = fields[2].strip()
                        # 按代码格式推断交易所（比依赖 Sina 类型码更稳定）
                        if re.match(r'^\d{6}$', code):
                            if code.startswith(("60", "68", "90")):
                                return f"{code}.SH"
                            return f"{code}.SZ"
                        if re.match(r'^\d{5}$', code):
                            return f"{code}.HK"
                        if re.match(r'^[A-Z]{1,5}$', code) or re.match(r'^[A-Z]{1,4}-[AB]$', code):
                            return code
            except Exception:
                pass  # 网络超时或解析失败，静默降级到步骤 4

        # 4. 无匹配，直接返回原始输入大写（可能已是标准代码如 AAPL/600519.SH）
        return query.strip().upper()

    @staticmethod
    def classify(symbol: str) -> Tuple[MarketType, str]:
        """
        判断交易标的所属市场类型。

        注意：本版本已移除加密货币（CRYPTO）支持。
             若用户输入含"/"的加密货币代码，返回 UNKNOWN。

        Args:
            symbol: 交易标的代码（应已经过 fuzzy_match 转换）

        Returns:
            (市场类型, 标准化代码)
        """
        symbol = symbol.strip().upper()

        # A股（以 .SH 或 .SZ 结尾，或6位纯数字）
        if symbol.endswith(".SH") or symbol.endswith(".SZ"):
            return MarketType.A_STOCK, symbol
        if re.match(r'^\d{6}$', symbol):
            # 6位纯数字：60/688开头 → SH，其余 → SZ
            if symbol.startswith(("60", "68", "90")):
                return MarketType.A_STOCK, f"{symbol}.SH"
            return MarketType.A_STOCK, f"{symbol}.SZ"

        # 港股（以 .HK 结尾，或 5位数字）
        if symbol.endswith(".HK"):
            return MarketType.HK_STOCK, symbol
        if re.match(r'^\d{5}$', symbol):
            return MarketType.HK_STOCK, f"{symbol}.HK"

        # 美股（1-5个大写字母，含 BRK-B 类格式）
        if re.match(r'^[A-Z]{1,5}$', symbol) or re.match(r'^[A-Z]{1,4}-[AB]$', symbol):
            return MarketType.US_STOCK, symbol

        # 加密货币代码（含"/"）— 已从系统移除，返回 UNKNOWN
        if "/" in symbol:
            return MarketType.UNKNOWN, symbol

        return MarketType.UNKNOWN, symbol

    @staticmethod
    def get_data_source(market_type: MarketType) -> str:
        """根据市场类型返回数据源名称"""
        mapping = {
            MarketType.A_STOCK:  "akshare",
            MarketType.HK_STOCK: "akshare",
            MarketType.US_STOCK: "yfinance",
        }
        return mapping.get(market_type, "unknown")

    @staticmethod
    def normalize_symbol(symbol: str, market_type: MarketType) -> str:
        """将交易代码标准化为各数据源所需格式"""
        if market_type == MarketType.A_STOCK:
            return symbol

        elif market_type == MarketType.HK_STOCK:
            if not symbol.endswith(".HK"):
                if symbol.isdigit():
                    return f"{symbol.zfill(5)}.HK"
            return symbol

        elif market_type == MarketType.US_STOCK:
            return symbol.replace(".US", "")

        return symbol

    @staticmethod
    def get_exchange(market_type: MarketType, symbol: str) -> str:
        """获取交易所名称"""
        if market_type == MarketType.A_STOCK:
            if symbol.endswith(".SH"):
                return "上海证券交易所"
            elif symbol.endswith(".SZ"):
                return "深圳证券交易所"
            return "A股交易所"

        elif market_type == MarketType.HK_STOCK:
            return "香港交易所"

        elif market_type == MarketType.US_STOCK:
            return "纳斯达克 / 纽交所"

        return "未知交易所"

    @staticmethod
    def search_stock_suggestions(query: str, limit: int = 8) -> list:
        """
        股票联想搜索：输入中文名/拼音缩写/代码，返回标准化建议列表。

        搜索优先级：
          1. 本地 _FUZZY_NAME_MAP 前缀匹配（零延迟，最多 5 条）
          2. 新浪财经 Suggest API 补充（最多 limit 条，3s 超时）

        Returns:
            list of {"symbol": str, "name": str, "type": str}
              type ∈ {"A股", "港股", "美股", "ETF", "其他"}
        """
        if not query or len(query.strip()) < 1:
            return []

        query_stripped = query.strip()
        query_lower    = query_stripped.lower()
        results: list[dict] = []
        seen_symbols: set[str] = set()

        # ── 1. 本地字典前缀匹配 ──────────────────────────────────────
        for key, code in _FUZZY_NAME_MAP.items():
            if code == "不上市":
                continue
            if key.startswith(query_lower) or query_lower in key:
                if code not in seen_symbols:
                    seen_symbols.add(code)
                    market_type, norm_code = MarketClassifier.classify(code)
                    type_label = market_type.value if market_type != MarketType.UNKNOWN else "其他"
                    # 用 key 的标题化作为展示名（去掉拼音缩写类键）
                    if not re.match(r'^[a-z]+$', key):
                        results.append({"symbol": norm_code, "name": key, "type": type_label})
                    if len(results) >= 5:
                        break

        # ── 2. 新浪财经 Suggest API ──────────────────────────────────
        # 响应格式: var suggestvalue="名称,类型码,代码,简称,拼音,...|名称2,...";
        # 类型码: 11=A股 31/33=ETF/基金 41=港股 71=美股
        _TYPE_MAP = {
            "11": "A股", "31": "ETF", "33": "基金",
            "41": "港股", "71": "美股",
        }
        try:
            url = (
                "http://suggest3.sinajs.cn/suggest/type=&key="
                + urllib.parse.quote(query_stripped, encoding="utf-8")
            )
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0 (compatible; CampusQuant/1.0)"},
            )
            with urllib.request.urlopen(req, timeout=3) as resp:
                raw = resp.read().decode("gbk", errors="replace")

            m = re.search(r'"([^"]+)"', raw)
            if m and m.group(1):
                for entry in m.group(1).split("|"):
                    if not entry.strip():
                        continue
                    fields = entry.split(",")
                    if len(fields) < 3:
                        continue
                    name      = fields[0].strip()
                    type_code = fields[1].strip()
                    raw_code  = fields[2].strip()
                    if not raw_code or not name:
                        continue

                    # 规范化代码
                    if re.match(r'^\d{6}$', raw_code):
                        if raw_code.startswith(("60", "68", "90", "11")):
                            symbol = f"{raw_code}.SH"
                        else:
                            symbol = f"{raw_code}.SZ"
                    elif re.match(r'^\d{5}$', raw_code):
                        symbol = f"{raw_code}.HK"
                    elif re.match(r'^[A-Z]{1,5}$', raw_code.upper()):
                        symbol = raw_code.upper()
                    else:
                        symbol = raw_code.upper()

                    if symbol in seen_symbols:
                        continue
                    seen_symbols.add(symbol)
                    type_label = _TYPE_MAP.get(type_code, "其他")
                    results.append({"symbol": symbol, "name": name, "type": type_label})
                    if len(results) >= limit:
                        break
        except Exception:
            pass   # 网络超时或解析失败，静默降级至本地结果

        return results[:limit]


# ════════════════════════════════════════════════════════════════════
# 测试
# ════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    test_cases = [
        # 中文模糊匹配测试
        ("茅台",    "600519.SH"),
        ("英伟达",  "NVDA"),
        ("腾讯",    "00700.HK"),
        ("沪深300", "510300.SH"),
        # 标准代码直接分类
        ("600519.SH", "A股"),
        ("00700.HK",  "港股"),
        ("AAPL",      "美股"),
        # 应被拒绝的加密货币
        ("BTC/USDT",  "未知"),
    ]

    print("=== CampusQuant 市场分类测试 ===\n")
    for query, expected in test_cases:
        matched   = MarketClassifier.fuzzy_match(query)
        mtype, normalized = MarketClassifier.classify(matched)
        ok = "✅" if (expected in [mtype.value, normalized]) else "⚠️"
        print(f"{ok} 输入: {query:15s} → 匹配: {matched:15s} | 市场: {mtype.value} | 期望: {expected}")
