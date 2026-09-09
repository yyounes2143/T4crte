"""
أداة جلب البيانات التاريخية لشبكة التداول من المنصات عبر CCXT
تستخدم التصفح (Pagination) بجلب الشموع عبر المعامل since
وتحفظ النتائج كملفات CSV في المجلد data/
"""

import os
import sys
import time
import ccxt
import pandas as pd

# Allow running from project root or tools directory
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)


def get_working_exchange():
    """
    اختيار أول منصة تعمل بنجاح بدون قيود جغرافية
    """
    exchanges_to_try = ["mexc", "gateio", "kucoin", "binance", "bybit"]
    for ex_id in exchanges_to_try:
        try:
            ex_cls = getattr(ccxt, ex_id)
            ex = ex_cls({'enableRateLimit': True, 'timeout': 10000})
            ex.fetch_ohlcv("BTC/USDT", timeframe="5m", limit=5)
            print(f"✅ تم اختيار المنصة: {ex_id.upper()}")
            return ex
        except Exception:
            continue
    # Fallback to mexc
    return ccxt.mexc({'enableRateLimit': True, 'timeout': 10000})


def fetch_candles_paginated(exchange, symbol: str, timeframe: str, total_candles: int) -> pd.DataFrame:
    """
    جلب عدد معين من الشموع التاريخية بالتصفح (Pagination) عبر since
    """
    print(f"⌛ جلب {total_candles} شمعة بالإطار الزمني {timeframe} لـ {symbol}...")

    tf_ms = ccxt.Exchange.parse_timeframe(timeframe) * 1000
    now_ms = int(time.time() * 1000)
    since = now_ms - (total_candles * tf_ms)

    all_ohlcv = []
    max_retries = 3

    while len(all_ohlcv) < total_candles:
        retries = 0
        fetched = None
        while retries < max_retries:
            try:
                limit = min(1000, total_candles - len(all_ohlcv) + 50)
                fetched = exchange.fetch_ohlcv(symbol, timeframe=timeframe, since=since, limit=limit)
                break
            except Exception as e:
                retries += 1
                print(f"⚠️ خطأ أثناء جلب البيانات (المحاولة {retries}/{max_retries}): {e}")
                time.sleep(1)

        if not fetched:
            print("⚠️ لم يتم استرجاع المزيد من الشموع أو انتهت البيانات المتاحة.")
            break

        all_ohlcv.extend(fetched)
        last_ts = fetched[-1][0]
        since = last_ts + 1

        print(f"  - تم جلب {len(all_ohlcv)}/{total_candles} شمعة حتى الآن...")

        # Stop if last candle fetched is close to now
        if last_ts >= now_ms - tf_ms:
            break

        time.sleep(exchange.rateLimit / 1000.0 if hasattr(exchange, 'rateLimit') else 0.2)

    if not all_ohlcv:
        return pd.DataFrame()

    df = pd.DataFrame(all_ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df = df.drop_duplicates(subset=['timestamp']).sort_values('timestamp').reset_index(drop=True)

    if len(df) > total_candles:
        df = df.tail(total_candles).reset_index(drop=True)

    df['datetime'] = pd.to_datetime(df['timestamp'], unit='ms')
    return df


def main():
    symbol = sys.argv[1] if len(sys.argv) > 1 else "BTC/USDT"
    print("=" * 60)
    print(f"🚀 البدء في جلب البيانات التاريخية لـ {symbol}")
    print("=" * 60)

    exchange = get_working_exchange()

    data_dir = os.path.join(project_root, "data")
    os.makedirs(data_dir, exist_ok=True)

    # 1. Fetch 3000 candles of 5m
    df_5m = fetch_candles_paginated(exchange, symbol, timeframe="5m", total_candles=3000)
    # 2. Fetch 1000 candles of 1h
    df_1h = fetch_candles_paginated(exchange, symbol, timeframe="1h", total_candles=1000)

    clean_sym = symbol.replace("/", "_")

    if not df_5m.empty:
        file_5m = os.path.join(data_dir, f"{clean_sym}_5m.csv")
        df_5m.to_csv(file_5m, index=False)
        print(f"✅ تم حفظ {len(df_5m)} شمعة (5m) في: {file_5m}")

    if not df_1h.empty:
        file_1h = os.path.join(data_dir, f"{clean_sym}_1h.csv")
        df_1h.to_csv(file_1h, index=False)
        print(f"✅ تم حفظ {len(df_1h)} شمعة (1h) في: {file_1h}")

    print("=" * 60)
    print("🎉 اكتمل جلب البيانات التاريخية بنجاح!")


if __name__ == "__main__":
    main()
