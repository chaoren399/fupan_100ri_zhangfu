import pandas as pd
import sqlite3
import os
import glob
from tqdm import tqdm

DATA_DIR = "stock_data_cache"
DB_FILE = "stock_data.db"
#步骤 1：初始化 SQLite 数据库

def init_database():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    # 创建表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS daily_data (
            ts_code TEXT NOT NULL,
            trade_date INTEGER NOT NULL,
            open REAL, high REAL, low REAL, close REAL,
            vol REAL, amount REAL,
            PRIMARY KEY (ts_code, trade_date)
        )
    ''')

    # 创建索引
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_trade_date ON daily_data(trade_date)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_ts_code ON daily_data(ts_code)')

    csv_files = glob.glob(os.path.join(DATA_DIR, "*.csv"))
    for file_path in tqdm(csv_files, desc="导入数据"):
        try:
            df = pd.read_csv(file_path)
            ts_code = os.path.basename(file_path).replace('.csv', '').replace('_', '.')
            df['ts_code'] = ts_code
            df['trade_date'] = df['trade_date'].astype(int)
            cols = ['ts_code', 'trade_date', 'open', 'high', 'low', 'close', 'vol', 'amount']
            df[cols].to_sql('daily_data', conn, if_exists='append', index=False, method='multi')
        except:
            continue

    conn.commit()
    conn.close()
    print("✅ 数据库初始化完成")


if __name__ == '__main__':
    init_database()
