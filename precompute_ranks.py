import pandas as pd
import sqlite3
import os
import pickle
from tqdm import tqdm
from concurrent.futures import ProcessPoolExecutor
import numpy as np

DB_FILE = "stock_data.db"
STOCK_LIST_CACHE = "stock_list_cache.csv"
RANK_CACHE_DIR = "rank_cache"


def load_all_data():
    """一次性加载所有数据到内存"""
    conn = sqlite3.connect(DB_FILE)
    df = pd.read_sql_query('''
        SELECT ts_code, trade_date, close 
        FROM daily_data 
        ORDER BY ts_code, trade_date
    ''', conn)
    conn.close()
    return df


def load_stock_names():
    """加载股票名称映射"""
    try:
        df_map = pd.read_csv(STOCK_LIST_CACHE)
        return dict(zip(df_map['ts_code'].astype(str), df_map['name']))
    except:
        return {}


def calculate_ranks_for_date(args):
    """计算单个日期的排行（用于并行处理）"""
    date, stock_groups, stock_names = args
    date_str = str(date)

    results = []
    for ts_code, group in stock_groups:
        # 获取该日期及之前的数据
        history = group[group['trade_date'] <= date].sort_values('trade_date')

        if len(history) < 101:
            continue

        # 向量化计算：取最后 101 条
        last_101 = history.tail(101)
        current_close = last_101.iloc[-1]['close']
        past_close = last_101.iloc[0]['close']

        if past_close > 0:
            pct_change = (current_close - past_close) / past_close * 100
            results.append({
                "code": ts_code,
                "name": stock_names.get(ts_code, "未知"),
                "change": round(pct_change, 2),
                "price": round(current_close, 2)
            })

    results.sort(key=lambda x: x['change'], reverse=True)
    return date_str, results[:50]


def precompute_all_ranks_optimized():
    """优化版：批量加载 + 向量化计算 + 并行处理"""
    print("🚀 开始优化版预计算...")
    os.makedirs(RANK_CACHE_DIR, exist_ok=True)

    # 1. 一次性加载所有数据
    print("📥 加载全部数据到内存...")
    df = load_all_data()
    stock_names = load_stock_names()

    # 2. 按股票分组（只分组一次）
    print("📊 数据分组...")
    stock_groups = df.groupby('ts_code')

    # 3. 获取所有交易日
    dates = df['trade_date'].unique()
    dates = sorted(dates, reverse=True)
    print(f"📅 共 {len(dates)} 个交易日需要处理")

    # 4. 并行处理（根据 CPU 核心数调整）
    print("⚡ 开始并行计算...")
    tasks = [(date, stock_groups, stock_names) for date in dates]

    results_count = 0
    with ProcessPoolExecutor(max_workers=4) as executor:  # 根据 CPU 调整
        for date_str, top_50 in tqdm(
                executor.map(calculate_ranks_for_date, tasks),
                total=len(dates),
                desc="预计算排行"
        ):
            # 保存缓存
            cache_file = os.path.join(RANK_CACHE_DIR, f"{date_str}.pkl")
            with open(cache_file, 'wb') as f:
                pickle.dump(top_50, f)
            results_count += 1

    print("-" * 30)
    print(f"✅ 预计算完成！缓存文件：{results_count}/{len(dates)}")
    print(f"📂 缓存目录：{os.path.abspath(RANK_CACHE_DIR)}")


def precompute_all_ranks_vectorized():
    """极致优化版：完全向量化计算（推荐）"""
    print("🚀 开始向量化版预计算...")
    os.makedirs(RANK_CACHE_DIR, exist_ok=True)

    # 1. 加载数据
    conn = sqlite3.connect(DB_FILE)
    df = pd.read_sql_query('''
        SELECT ts_code, trade_date, close 
        FROM daily_data 
        ORDER BY ts_code, trade_date
    ''', conn)
    conn.close()

    stock_names = load_stock_names()

    # 2. 使用 shift 向量化计算 100 日涨幅
    print("📊 向量化计算涨幅...")
    df['prev_close'] = df.groupby('ts_code')['close'].shift(100)
    df['pct_change'] = (df['close'] - df['prev_close']) / df['prev_close'] * 100

    # 3. 按交易日分组，取前 50
    print("📅 按日期生成排行...")
    dates = df['trade_date'].unique()

    for date in tqdm(sorted(dates, reverse=True), desc="生成缓存"):
        date_str = str(date)

        # 筛选该日期的数据
        day_data = df[df['trade_date'] == date].copy()
        day_data = day_data.dropna(subset=['pct_change'])

        # 排序取前 50
        top_50 = day_data.nlargest(50, 'pct_change')

        # 格式化输出
        results = []
        for _, row in top_50.iterrows():
            results.append({
                "code": row['ts_code'],
                "name": stock_names.get(row['ts_code'], "未知"),
                "change": round(row['pct_change'], 2),
                "price": round(row['close'], 2)
            })

        # 保存缓存
        cache_file = os.path.join(RANK_CACHE_DIR, f"{date_str}.pkl")
        with open(cache_file, 'wb') as f:
            pickle.dump(results, f)

    print("-" * 30)
    print(f"✅ 预计算完成！缓存文件：{len(dates)} 个")


if __name__ == '__main__':
    # 推荐使用向量化版本，速度最快
    precompute_all_ranks_vectorized()
