from flask import Flask, render_template, request, jsonify
import pandas as pd
import sqlite3
import os
from datetime import datetime
import pickle

app = Flask(__name__)

DB_FILE = "stock_data.db"
STOCK_LIST_CACHE = "stock_list_cache.csv"
RANK_CACHE_DIR = "rank_cache"

# 内存缓存
rank_memory_cache = {}


def get_db_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def get_cached_rank(target_date_str):
    """三级缓存：内存 → 磁盘 → 数据库"""
    # 统一日期格式为 YYYYMMDD
    date_key = target_date_str.replace('-', '')

    # ① 内存缓存
    if date_key in rank_memory_cache:
        return rank_memory_cache[date_key]

    # ② 磁盘缓存
    cache_file = os.path.join(RANK_CACHE_DIR, f"{date_key}.pkl")
    if os.path.exists(cache_file):
        try:
            with open(cache_file, 'rb') as f:
                data = pickle.load(f)
                rank_memory_cache[date_key] = data
                return data
        except:
            pass
    return None


def save_cached_rank(target_date_str, data):
    """保存到内存和磁盘缓存"""
    os.makedirs(RANK_CACHE_DIR, exist_ok=True)
    # 统一日期格式为 YYYYMMDD
    date_key = target_date_str.replace('-', '')
    cache_file = os.path.join(RANK_CACHE_DIR, f"{date_key}.pkl")
    with open(cache_file, 'wb') as f:
        pickle.dump(data, f)
    rank_memory_cache[date_key] = data




def calculate_top_50(target_date_str):
    """查询排行（带缓存）"""
    print(f"[DEBUG] 开始检查缓存：{target_date_str}")

    cached_data = get_cached_rank(target_date_str)
    if cached_data:
        print(f"[DEBUG] 缓存命中")
        return cached_data, None

    print(f"[DEBUG] 缓存未命中，开始数据库查询")
    target_num = int(target_date_str.replace('-', ''))
    conn = get_db_connection()

    try:
        print(f"[DEBUG] 执行 SQL 查询...")
        df = pd.read_sql_query('''
            SELECT ts_code, trade_date, close 
            FROM daily_data 
            WHERE trade_date <= ?
            ORDER BY ts_code, trade_date
        ''', conn, params=(target_num,))
        print(f"[DEBUG] SQL 查询完成，数据量：{len(df)}")

        if df.empty:
            return [], "该日期无数据"

        results = []
        print(f"[DEBUG] 开始计算涨幅...")
        for ts_code in df['ts_code'].unique():
            stock_df = df[df['ts_code'] == ts_code].sort_values('trade_date').tail(101)
            if len(stock_df) < 101:
                continue
            current_close = stock_df.iloc[-1]['close']
            past_close = stock_df.iloc[0]['close']
            if past_close > 0:
                pct_change = (current_close - past_close) / past_close * 100
                results.append({
                    "code": ts_code,
                    "change": round(pct_change, 2),
                    "price": round(current_close, 2)
                })

        print(f"[DEBUG] 涨幅计算完成，结果数：{len(results)}")
        results.sort(key=lambda x: x['change'], reverse=True)
        top_50 = results[:50]

        # 加载股票名称
        try:
            stock_map = pd.read_csv(STOCK_LIST_CACHE)
            stock_dict = dict(zip(stock_map['ts_code'].astype(str), stock_map['name']))
            for item in top_50:
                item['name'] = stock_dict.get(item['code'], "未知")
        except:
            pass

        save_cached_rank(target_date_str, top_50)
        return top_50, None

    except Exception as e:
        print(f"[ERROR] 异常：{str(e)}")
        return [], f"查询失败：{str(e)}"
    finally:
        conn.close()


from datetime import datetime, timedelta


@app.route('/api/chart')
def get_chart_data():
    ts_code = request.args.get('code')
    date_str = request.args.get('date')

    if not ts_code or not date_str:
        return jsonify({"error": "缺少参数"}), 400

    conn = get_db_connection()

    try:
        from datetime import datetime, timedelta
        target_date = datetime.strptime(date_str, "%Y-%m-%d")
        start_date = target_date - timedelta(days=50)
        end_date = target_date + timedelta(days=20)

        start_num = int(start_date.strftime("%Y%m%d"))
        end_num = int(end_date.strftime("%Y%m%d"))
        target_num = int(target_date.strftime("%Y%m%d"))

        df = pd.read_sql_query('''
            SELECT trade_date, open, high, low, close, vol
            FROM daily_data
            WHERE ts_code = ? AND trade_date BETWEEN ? AND ?
            ORDER BY trade_date
        ''', conn, params=(ts_code, start_num, end_num))

        if df.empty:
            return jsonify({"error": "未找到该股票数据"}), 404

        # ✅ 确保日期格式为 YYYY-MM-DD
        df['date_str'] = df['trade_date'].apply(
            lambda x: f"{int(x) // 10000:04d}-{(int(x) % 10000) // 100:02d}-{int(x) % 100:02d}"
        )

        target_date_str = target_date.strftime("%Y-%m-%d")

        # 查找标记日期
        if target_date_str in df['date_str'].values:
            mark_date = target_date_str
        else:
            past_dates = df[df['date_str'] <= target_date_str]['date_str']
            mark_date = past_dates.iloc[-1] if not past_dates.empty else df['date_str'].iloc[-1]

        data_list = []
        for _, row in df.iterrows():
            data_list.append({
                "date": row['date_str'],
                "kline": [float(row['open']), float(row['close']),
                          float(row['low']), float(row['high'])],
                "volume": int(row['vol']),
                "is_target": row['date_str'] == mark_date
            })

        return jsonify({
            "code": ts_code,
            "target_date": mark_date,
            "data": data_list
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()


@app.route('/')
def index():
    default_date = datetime.now().strftime("%Y-%m-%d")
    return render_template('index.html', default_date=default_date)


@app.route('/api/rank')
def get_rank():
    print("收到排行查询请求")
    date_str = request.args.get('date')
    print(f" 查询日期：{date_str}")

    if not date_str:
        return jsonify({"error": "请选择日期"}), 400

    data, error = calculate_top_50(date_str)

    if error:
        print(f" 查询失败：{error}")
        return jsonify({"error": error}), 400

    print(f" 查询成功，返回 {len(data)} 条数据")
    return jsonify(data)



if __name__ == '__main__':
    print("启动复盘系统...")
    print(f"数据库：{os.path.abspath(DB_FILE)}")
    print(f"缓存目录：{os.path.abspath(RANK_CACHE_DIR)}")
    app.run(debug=True, host='0.0.0.0', port=5050)

