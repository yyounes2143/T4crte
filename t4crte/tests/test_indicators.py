import time
import pytest
import pandas as pd
import numpy as np
from indicators import (
    ema, rsi, bollinger, atr,
    add_all_indicators, min_candles_required, drop_forming_candle
)

def test_min_candles_required():
    assert min_candles_required() == 210

def test_constant_series():
    series = pd.Series([100.0] * 300)

    # EMA test
    ema_val = ema(series, 20)
    assert pytest.approx(ema_val.iloc[20], abs=1e-6) == 100.0
    assert pytest.approx(ema_val.iloc[-1], abs=1e-6) == 100.0

    # RSI test
    rsi_val = rsi(series, 14)
    assert pytest.approx(rsi_val.iloc[15], abs=1e-6) == 50.0
    assert pytest.approx(rsi_val.iloc[-1], abs=1e-6) == 50.0

    # Bollinger test
    bb_upper, bb_mid, bb_lower = bollinger(series, period=20, std_mult=2.0)
    assert pytest.approx(bb_upper.iloc[-1], abs=1e-6) == 100.0
    assert pytest.approx(bb_mid.iloc[-1], abs=1e-6) == 100.0
    assert pytest.approx(bb_lower.iloc[-1], abs=1e-6) == 100.0

    # ATR test
    high = pd.Series([100.0] * 300)
    low = pd.Series([100.0] * 300)
    close = pd.Series([100.0] * 300)
    atr_val = atr(high, low, close, period=14)
    assert pytest.approx(atr_val.iloc[-1], abs=1e-6) == 0.0

def test_linearly_increasing_series():
    close = pd.Series(list(range(1, 301)), dtype=float)
    rsi_val = rsi(close, 14)
    # RSI after 30 values = 100 (+/- 1e-6)
    assert pytest.approx(rsi_val.iloc[30], abs=1e-6) == 100.0
    assert pytest.approx(rsi_val.iloc[-1], abs=1e-6) == 100.0

    ema_9_val = ema(close, 9)
    ema_21_val = ema(close, 21)
    ema_50_val = ema(close, 50)

    assert ema_9_val.iloc[-1] > ema_21_val.iloc[-1] > ema_50_val.iloc[-1]

def test_linearly_decreasing_series():
    close = pd.Series(list(range(300, 0, -1)), dtype=float)
    rsi_val = rsi(close, 14)
    assert pytest.approx(rsi_val.iloc[-1], abs=1e-6) == 0.0

    ema_9_val = ema(close, 9)
    ema_21_val = ema(close, 21)
    assert ema_9_val.iloc[-1] < ema_21_val.iloc[-1]

def test_nan_counts():
    series = pd.Series(list(range(1, 301)), dtype=float)
    ema_200_val = ema(series, 200)
    assert ema_200_val.isna().sum() == 199

    rsi_14_val = rsi(series, 14)
    assert rsi_14_val.isna().sum() == 14

def test_add_all_indicators_performance_and_dtypes():
    df = pd.DataFrame({
        'high': np.random.rand(300) + 100,
        'low': np.random.rand(300) + 90,
        'close': np.random.rand(300) + 95,
        'volume': np.random.rand(300) * 1000 + 100
    })

    start_time = time.perf_counter()
    res = add_all_indicators(df)
    elapsed_ms = (time.perf_counter() - start_time) * 1000

    assert elapsed_ms < 50.0, f"Execution took {elapsed_ms:.2f}ms, expected < 50ms"

    expected_cols = [
        'ema_9', 'ema_21', 'ema_50', 'ema_200',
        'rsi', 'bb_upper', 'bb_middle', 'bb_lower',
        'atr', 'volume_sma_20', 'volume_ratio'
    ]
    for col in expected_cols:
        assert col in res.columns
        assert res[col].dtype == np.float64

def test_drop_forming_candle():
    now_ms = time.time() * 1000
    df_forming = pd.DataFrame({
        'timestamp': [now_ms - 300000, now_ms],
        'close': [100.0, 101.0]
    })
    res_forming = drop_forming_candle(df_forming, '5m')
    assert len(res_forming) == 1

    df_closed = pd.DataFrame({
        'timestamp': [now_ms - 7200000, now_ms - 3600000],
        'close': [100.0, 101.0]
    })
    res_closed = drop_forming_candle(df_closed, '5m')
    assert len(res_closed) == 2
