import os
import sys
import pytest
import pandas as pd
import numpy as np

# Ensure module path imports work
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "t4crte"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, "t4crte")

from indicators import add_all_indicators
from ai_advisor import AIAdvisor, AIAnalysisResult


def make_df(n=300, pattern="constant"):
    """
    دالة مساعدة لتوليد OHLCV اصطناعياً ثم تمريره في add_all_indicators
    """
    timestamps = pd.date_range("2025-01-01", periods=n, freq="15min")
    if pattern == "constant":
        closes = np.full(n, 100.0)
    elif pattern == "strong_uptrend":
        closes = []
        for i in range(n):
            base = 100.0 + (i / n) * 100.0
            closes.append(base + (2.0 if i % 2 == 0 else -1.5))
        closes = np.array(closes)
    elif pattern == "sharp_drop":
        closes = [100.0] * 280
        for i in range(15):
            closes.append(100.0 - (i + 1) * 2.0)
        for i in range(5):
            closes.append(70.0 - (i + 1) * 5.0)
        closes = np.array(closes)
    elif pattern == "nan_ema200":
        closes = np.full(n, 100.0)
    else:
        closes = np.full(n, 100.0)

    df = pd.DataFrame({
        'timestamp': [int(t.timestamp() * 1000) for t in timestamps],
        'open': closes,
        'high': closes + 0.5,
        'low': closes - 0.5,
        'close': closes,
        'volume': np.full(n, 1000.0),
        'datetime': timestamps
    })

    df = add_all_indicators(df)

    if pattern == "nan_ema200":
        df['ema_200'] = np.nan

    return df


def test_ai_advisor_insufficient_rows():
    """df بـ 100 صف → signal == 'HOLD' وسبب يحوي '200'"""
    df = make_df(n=100, pattern="constant")
    res = AIAdvisor.analyze(df, "BTC/USDT")
    assert res.signal == "HOLD"
    assert any("200" in reason for reason in res.reasons)
    assert 0 <= res.confidence <= 100
    assert 0 <= res.safety_score <= 100


def test_ai_advisor_constant_df():
    """df ثابت 300 صف → HOLD (لا نقاط شراء ولا بيع)"""
    df = make_df(n=300, pattern="constant")
    res = AIAdvisor.analyze(df, "BTC/USDT")
    assert res.signal == "HOLD"
    assert res.buy_points == 0
    assert res.sell_points == 0
    assert 0 <= res.confidence <= 100
    assert 0 <= res.safety_score <= 100


def test_ai_advisor_strong_uptrend():
    """df صاعد قوي (سعر > ema_50 > ema_200، ema_9 > ema_21) بدون تشبع RSI → buy_points >= 10, sentiment يحوي Bullish"""
    df = make_df(n=300, pattern="strong_uptrend")
    res = AIAdvisor.analyze(df, "BTC/USDT")
    assert res.buy_points >= 10
    assert "Bullish" in res.market_sentiment
    assert 0 <= res.confidence <= 100
    assert 0 <= res.safety_score <= 100


def test_ai_advisor_sharp_drop():
    """df ينزل بحدة ثم يستقر (RSI < 25 والسعر عند BB السفلي) → buy_points >= 55 وsentiment يحوي Bearish"""
    df = make_df(n=300, pattern="sharp_drop")
    res = AIAdvisor.analyze(df, "BTC/USDT")
    assert res.buy_points >= 55
    assert "Bearish" in res.market_sentiment
    assert 0 <= res.confidence <= 100
    assert 0 <= res.safety_score <= 100


def test_ai_advisor_nan_ema200():
    """df بعمود ema_200 كله NaN → HOLD وليس استثناء"""
    df = make_df(n=300, pattern="nan_ema200")
    res = AIAdvisor.analyze(df, "BTC/USDT")
    assert res.signal == "HOLD"
    assert any("200" in reason for reason in res.reasons)
    assert 0 <= res.confidence <= 100
    assert 0 <= res.safety_score <= 100
