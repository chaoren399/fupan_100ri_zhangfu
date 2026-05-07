import tushare as ts
import pandas as pd
import os
import time
import random
from datetime import datetime, timedelta
from tqdm import tqdm
from dotenv import load_dotenv  # ✅ 新增导入

# ✅ 加载 .env 环境变量
load_dotenv()

# ================= 配置区域 =================
TS_TOKEN = os.getenv('TS_TOKEN')  # ✅ 从环境变量读取
DATA_DIR = "stock_data_cache_all"
STOCK_LIST_CACHE = "stock_list_cache.csv"
CACHE_EXPIRE_HOURS = 24

# 限流配置
SLEEP_MIN = 1.5
SLEEP_MAX = 2.0

# 重试机制配置
MAX_RETRIES = 3
BASE_RETRY_DELAY = 5
MAX_RETRY_DELAY = 60

# 时间范围配置
START_DATE = '20240101'
END_DATE = '20260430'

# 主板代码前缀
# MAIN_BOARD_PREFIXES = [
#     '600', '601', '603', '605',  # 沪市主板
#     '000', '001', '002', '003',  # 深市主板
# ]

# ✅ 验证 Token 是否加载成功
if not TS_TOKEN:
    raise ValueError("❌ 未找到 TS_TOKEN，请检查 .env 文件")

ts.set_token(TS_TOKEN)
pro = ts.pro_api()





def is_main_board(ts_code):
    """✅ 判断是否为主板股票"""
    code = ts_code.split('.')[0]
    return any(code.startswith(prefix) for prefix in MAIN_BOARD_PREFIXES)


def get_stock_list():
    """获取股票列表（带本地缓存）"""
    if os.path.exists(STOCK_LIST_CACHE):
        file_time = datetime.fromtimestamp(os.path.getmtime(STOCK_LIST_CACHE))
        if datetime.now() - file_time < timedelta(hours=CACHE_EXPIRE_HOURS):
            print(f"📂 使用缓存的股票列表：{STOCK_LIST_CACHE}")
            return pd.read_csv(STOCK_LIST_CACHE)

    print("🌐 正在从 Tushare 获取股票列表...")
    try:
        df = pro.stock_basic(exchange='', list_status='L', fields='ts_code,symbol,name')
        df.to_csv(STOCK_LIST_CACHE, index=False)
        return df
    except Exception as e:
        print(f"❌ 获取失败：{e}")
        if os.path.exists(STOCK_LIST_CACHE):
            print("⚠️ 降级：使用过期的本地缓存")
            return pd.read_csv(STOCK_LIST_CACHE)
        return pd.DataFrame()


def download_single_stock(ts_code, name, max_retries=MAX_RETRIES):
    """
    下载单只股票数据（带重试机制）
    """
    file_path = os.path.join(DATA_DIR, f"{ts_code.replace('.', '_')}.csv")

    if os.path.exists(file_path) and os.path.getsize(file_path) > 0:
        return False

    attempt = 0
    while attempt < max_retries:
        try:
            # ✅ 修改：使用配置的时间范围
            df = pro.daily(
                ts_code=ts_code,
                start_date=START_DATE,
                end_date=END_DATE
            )

            if df is not None and not df.empty:
                df = df.sort_values('trade_date').reset_index(drop=True)
                df.to_csv(file_path, index=False)
                return True
            elif df is not None and df.empty:
                return False

        except Exception as e:
            error_msg = str(e)
            attempt += 1

            if "权限不够" in error_msg or "积分不够" in error_msg or "token 无效" in error_msg:
                print(f"   ❌ 致命错误 [{ts_code}]: {error_msg}")
                return False

            if "每分钟最多访问" in error_msg or "每小时最多访问" in error_msg:
                wait_time = 60
                print(f"   ⚠️ 触发限流 [{ts_code}], 强制暂停 {wait_time} 秒...")
                time.sleep(wait_time)
                continue

            if attempt < max_retries:
                delay = min(MAX_RETRY_DELAY, BASE_RETRY_DELAY * (2 ** (attempt - 1)) + random.uniform(1, 3))
                print(f"   ⚠️ 下载失败 [{ts_code}] ({attempt}/{max_retries}): {error_msg}. {delay:.1f}秒后重试...")
                time.sleep(delay)
            else:
                print(f"   ❌ 最终失败 [{ts_code}]: 达到最大重试次数，跳过。")
                return False

    return False


def main():
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR)
        print(f"✅ 创建数据目录：{DATA_DIR}")

    stock_list = get_stock_list()
    if stock_list.empty:
        print("❌ 无法获取股票列表")
        return

    total = len(stock_list)
    print(f"🚀 开始下载 {total} 只全市场股票的历史数据 (CSV)...")
    print(f"   时间范围：{START_DATE} 至 {END_DATE}")
    print(f"   策略：正常间隔 {SLEEP_MIN}-{SLEEP_MAX}s, 失败重试最多 {MAX_RETRIES} 次")

    success_count = 0
    skip_count = 0
    fail_count = 0

    for _, row in tqdm(stock_list.iterrows(), total=total, desc="下载进度"):
        ts_code = row['ts_code']
        name = row['name']

        time.sleep(random.uniform(SLEEP_MIN, SLEEP_MAX))

        result = download_single_stock(ts_code, name)

        if result is True:
            success_count += 1
        elif result is False:
            file_path = os.path.join(DATA_DIR, f"{ts_code.replace('.', '_')}.csv")
            if os.path.exists(file_path) and os.path.getsize(file_path) > 0:
                skip_count += 1
            else:
                fail_count += 1

    print("-" * 30)
    print(f"✅ 完成！新增下载：{success_count}, 跳过 (已存在)：{skip_count}, 失败：{fail_count}")
    print(f"📂 数据保存在：{os.path.abspath(DATA_DIR)}")


if __name__ == '__main__':
    main()
