import os
import pandas as pd
from dotenv import load_dotenv
from supabase import create_client, Client
import twstock
from datetime import datetime, timedelta
import requests
from bs4 import BeautifulSoup

# 載入 .env
load_dotenv()
SUPABASE_URL = 'https://lftzvpmjkokupxsxhxiu.supabase.co'
SUPABASE_API_KEY = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImxmdHp2cG1qa29rdXB4c3hoeGl1Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NDYwOTY2MzgsImV4cCI6MjA2MTY3MjYzOH0.pwceHLeerh3CAj3RUAfXSKF0TUvlXg3QS2olQSoyVmo'
supabase: Client = create_client(SUPABASE_URL, SUPABASE_API_KEY)

def get_current_price(symbol):
    try:
        stock = twstock.Stock(symbol)
        return stock.price[-1] if stock.price else None
    except Exception as e:
        print(f"⚠️ 無法取得即時價格 [{symbol}]: {e}")
        return None

def load_stock_list(file_path='stock_list.txt'):
    # 若不存在則自動產生範例檔案
    if not os.path.exists(file_path):
        print(f"⚠️ 未找到 {file_path}，正在建立預設股票清單...")
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write("2330\n2317\n2603\n2882\n")
        print(f"✅ 已建立 {file_path}，請自行編輯股票清單後重新執行")
        return []

    # 讀取存在的檔案
    with open(file_path, 'r', encoding='utf-8') as f:
        stocks = [line.strip() for line in f if line.strip().isdigit()]

    if not stocks:
        print(f"⚠️ {file_path} 為空或格式不正確，請確認內含股票代碼")
    return stocks

# 建立名稱快取 dict
stock_name_cache = {}

def get_stock_name(stock_id):
    # 先從快取查找
    if stock_id in stock_name_cache:
        return stock_name_cache[stock_id]

    # 用 twstock 嘗試抓取
    stock = twstock.codes.get(stock_id)
    if stock:
        stock_name_cache[stock_id] = stock.name
        return stock.name

    # twstock 找不到，改用 Goodinfo 抓名稱
    url = f"https://goodinfo.tw/tw/StockDetail.asp?STOCK_ID={stock_id}"
    headers = {"User-Agent": "Mozilla/5.0"}

    try:
        res = requests.get(url, headers=headers, timeout=5)
        res.encoding = 'utf-8'
        soup = BeautifulSoup(res.text, 'html.parser')

        # 股票名稱在 <title> 裡，例如「4916 事欣科 - 個股基本資料」
        title = soup.title.string
        name = title.split(' ')[1] if ' ' in title else "未知"

        # 儲存到快取中
        stock_name_cache[stock_id] = name
        return name

    except Exception as e:
        print(f"⚠️ 無法取得名稱 [{stock_id}]：{e}")
        stock_name_cache[stock_id] = "未知"
        return "未知"

def get_twstock_df(stock_id, days=10):
    stock = twstock.Stock(stock_id)
    #date1 =datetime(2025,4,27)
    start_date = datetime.today() - timedelta(days=days)
    #start_date = date1 - timedelta(days=days)
    
    

    fetch_data = stock.fetch_from(start_date.year, start_date.month)

    if not fetch_data:
        print(f"[{stock_id}] 沒有資料")
        return pd.DataFrame()

    df = pd.DataFrame(fetch_data, columns=[
        'date', 'capacity', 'turnover', 'open', 'high', 'low', 'close',
        'change', 'transaction'
    ])
    df = df[['date', 'close', 'capacity', 'open', 'high', 'low']]  # 修正欄位選擇
    df = df.rename(columns={'capacity': 'volume'})
    df['volume'] = df['volume']  # 成交量（張）
    df['avg_5'] = df['volume'].rolling(5).mean()  # 修正五日平均量計算方式
    print(f"⏭️ 已存在: {df['date']} ，xxx")
    return df.dropna()

def get_twstock_df_5(stock_id, n_days=5, lookback_days=60):
    stock = twstock.Stock(stock_id)

    # 從過去 60 天（或指定）開始抓資料
    start_date = datetime.today() - timedelta(days=lookback_days)
    raw_data = stock.fetch_from(start_date.year, start_date.month)

    if not raw_data:
        print(f"[{stock_id}] 沒有資料")
        return pd.DataFrame()

    df = pd.DataFrame(raw_data, columns=[
        'date', 'capacity', 'turnover', 'open', 'high', 'low', 'close',
        'change', 'transaction'
    ])
    
    df = df[['date', 'close', 'capacity', 'open', 'high', 'low']]
    df = df.rename(columns={'capacity': 'volume'})
    df['avg_5'] = df['volume'].rolling(5).mean()

    # 只取最後 n 天交易日（排除非交易日）
    df = df.dropna().sort_values(by='date').tail(n_days).reset_index(drop=True)

    print(f"[{stock_id}] 最後 {n_days} 筆交易日資料：")
    print(df)
    return df

def check_breakout(df):
    if len(df) < 2:
        print("資料不足")
        return False

    latest = df.iloc[-1]
    print(f"✅ 測試 {latest['date'].date()} 強制觸發訊號")
    return True

def save_to_supabase(code, name, volume, avg_5, open, high, low, close, trade_date):
    # 檢查是否已存在該筆資料
    existing = supabase.table("volume_alerts") \
        .select("id") \
        .eq("code", code) \
        .eq("trade_date", str(trade_date)) \
        .execute()

    if existing.data and len(existing.data) > 0:
        print(f"⏭️ 已存在: {code} {trade_date}，跳過儲存")
        return

    # 插入新資料
    data = {
        "code": code,
        "name": name,
        "trade_date": str(trade_date),
        "avg_5": int(avg_5) if pd.notna(avg_5) else None,
        "open": float(open),
        "high": float(high),
        "low": float(low),
        "close": float(close),
        "volume": int(volume)
    }
    supabase.table("volume_alerts").insert(data).execute()
    print(f"✅ 上傳成功: {code} {name} {trade_date}")

# 分析股票清單
#target_stocks = ['2330', '2317', '2303', '2603']
target_stocks = load_stock_list()
for symbol in target_stocks:
    #df = get_twstock_df_5(symbol, n_days=5)
    df = get_twstock_df(symbol)
    if df.empty:
        print(f"⚠️ {symbol} 資料為空，跳過")
        continue

    name = get_stock_name(symbol)

    for _, row in df.iterrows():
        # 判斷是否爆量（你可以保留 check_breakout，也可以直接用爆量條件）
        if row["volume"] > 0 * row["avg_5"]:
            print(f"📣 爆量: {symbol} {name} - {row['date'].date()} 收盤: {row['close']} 成交量: {row['volume']}")

            save_to_supabase(
                symbol, 
                name, 
                row['volume'], 
                row['avg_5'],
                row['open'],
                row['high'],
                row['low'],
                row['close'], 
                row['date'].date()  # 修正日期格式
            )
        else:
            print(f"❌ 無爆量: {symbol} {name} - {row['date'].date()}")
