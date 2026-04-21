"""快速验证 yfinance 对三市场的 symbol 转换与数据可用性"""
import yfinance as yf

cases = [
    ("600519.SH", "600519.SS"),
    ("000858.SZ", "000858.SZ"),
    ("00700.HK",  "0700.HK"),
    ("03690.HK",  "3690.HK"),
    ("09988.HK",  "9988.HK"),
    ("AAPL",      "AAPL"),
    ("NVDA",      "NVDA"),
]

for sym_internal, sym_yf in cases:
    try:
        info = yf.Ticker(sym_yf).info or {}
        pe = info.get("trailingPE")
        pb = info.get("priceToBook")
        roe = info.get("returnOnEquity")
        eps = info.get("trailingEps")
        cap = info.get("marketCap")
        print(f"{sym_internal:14s} → {sym_yf:12s}: "
              f"pe={pe} pb={pb} roe={roe} eps={eps} cap={cap}")
    except Exception as e:
        print(f"{sym_internal:14s} → {sym_yf:12s}: ERROR {type(e).__name__}: {e}")
