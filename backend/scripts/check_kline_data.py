"""检查 ClickHouse 中的 K线数据统计"""
import clickhouse_connect

# 连接 ClickHouse
client = clickhouse_connect.get_client(host='localhost', port=8124)

# 先查看有哪些数据库
print("=== 数据库列表 ===")
result = client.query("SHOW DATABASES")
for row in result.result_rows:
    print(row)

# 查看 quantagent 数据库中的表
print("\n=== quantagent 数据库中的表 ===")
try:
    result = client.query("SHOW TABLES FROM quantagent")
    for row in result.result_rows:
        print(row)
except Exception as e:
    print(f"Error: {e}")

# 查询各周期数据量
print("\n=== BTCUSDT 各周期数据统计 ===")
try:
    result = client.query("""
        SELECT 
            interval, 
            count(*) as cnt, 
            min(open_time) as min_time, 
            max(open_time) as max_time,
            dateDiff('day', min(open_time), max(open_time)) as days_range
        FROM quantagent.klines 
        WHERE symbol = 'BTCUSDT' 
        GROUP BY interval 
        ORDER BY interval
    """)
    print(f"{'Interval':<10} {'Count':<10} {'Min Time':<25} {'Max Time':<25} {'Days Range':<10}")
    print("-" * 80)
    for row in result.result_rows:
        interval, cnt, min_time, max_time, days = row
        print(f"{interval:<10} {cnt:<10} {str(min_time):<25} {str(max_time):<25} {days:<10}")
except Exception as e:
    print(f"Error: {e}")

# 测试 Binance API 能否获取更早的 1d 数据
print("\n=== 测试 Binance API 获取 2021 年数据 ===")
import ccxt
import datetime

exchange = ccxt.binance({
    'enableRateLimit': True,
    'proxies': {
        'http': 'http://127.0.0.1:7897',
        'https': 'http://127.0.0.1:7897',
    }
})

# 尝试获取 2021 年的日线数据
since = int(datetime.datetime(2021, 1, 1).timestamp() * 1000)
try:
    ohlcv = exchange.fetch_ohlcv('BTC/USDT', timeframe='1d', since=since, limit=10)
    print(f"获取到 {len(ohlcv)} 条 1d 数据")
    if ohlcv:
        first_date = datetime.datetime.fromtimestamp(ohlcv[0][0]/1000)
        last_date = datetime.datetime.fromtimestamp(ohlcv[-1][0]/1000)
        print(f"日期范围: {first_date} ~ {last_date}")
except Exception as e:
    print(f"Error: {e}")

# 尝试获取 2017 年的日线数据
since_2017 = int(datetime.datetime(2017, 8, 1).timestamp() * 1000)
try:
    ohlcv = exchange.fetch_ohlcv('BTC/USDT', timeframe='1d', since=since_2017, limit=10)
    print(f"\n获取到 2017 年 {len(ohlcv)} 条 1d 数据")
    if ohlcv:
        first_date = datetime.datetime.fromtimestamp(ohlcv[0][0]/1000)
        last_date = datetime.datetime.fromtimestamp(ohlcv[-1][0]/1000)
        print(f"日期范围: {first_date} ~ {last_date}")
except Exception as e:
    print(f"Error: {e}")
