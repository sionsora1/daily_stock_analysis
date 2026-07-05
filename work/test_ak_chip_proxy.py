import akshare as ak
import time
start = time.time()
try:
    df = ak.stock_cyq_em(symbol='603259')
    print('OK', len(df), 'elapsed', round(time.time()-start, 2))
    print(df.tail(1).to_string())
except Exception as e:
    print('ERR', repr(e), 'elapsed', round(time.time()-start, 2))
