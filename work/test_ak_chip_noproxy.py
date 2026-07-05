import os
for k in ['HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','http_proxy','https_proxy','all_proxy']:
    os.environ.pop(k, None)
os.environ['NO_PROXY'] = '*'
import akshare as ak
import time
start = time.time()
try:
    df = ak.stock_cyq_em(symbol='603259')
    print('OK', len(df), 'elapsed', round(time.time()-start, 2))
    print(df.tail(1).to_string())
except Exception as e:
    print('ERR', repr(e), 'elapsed', round(time.time()-start, 2))
