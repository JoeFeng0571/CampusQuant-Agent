import akshare as ak

try:
    df = ak.stock_zh_a_spot_em()
    row = df[df['代码']=='600519']
    print('OK1 A股行情OK, 茅台最新价:', row.iloc[0]['最新价'])
except Exception as e:
    print('FAIL1 A股行情失败:', e)

try:
    df2 = ak.stock_zh_a_hist(symbol='600519', period='daily', adjust='qfq')
    print('OK2 A股K线OK, 行数:', len(df2), ', 最近收盘:', df2.iloc[-1]['收盘'])
except Exception as e:
    print('FAIL2 A股K线失败:', e)

try:
    df3 = ak.stock_zh_index_spot_em(symbol='沪深重要指数')
    print('OK3 指数OK, 上证:', df3[df3['代码']=='000001'].iloc[0]['最新价'])
except Exception as e:
    print('FAIL3 指数失败:', e)

