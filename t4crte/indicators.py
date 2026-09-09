import time
import ccxt
import pandas as pd
import numpy as np
from typing import Dict, Any, Tuple
from config import config

def ema(series: pd.Series, period: int) -> pd.Series:
    """Exponential Moving Average (vectorized)."""
    return series.ewm(span=period, adjust=False, min_periods=period).mean()

def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Relative Strength Index (vectorized)."""
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1/period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1/period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    out = 100 - (100 / (1 + rs))
    out = out.where(avg_loss != 0, 100.0)   # كله ارتفاع => 100
    out = out.where(~((avg_gain == 0) & (avg_loss == 0)), 50.0)  # ثابت => 50
    return out

def bollinger(close: pd.Series, period: int = 20, std_mult: float = 2.0) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """Bollinger Bands (vectorized). Returns (upper, middle, lower)."""
    mid = close.rolling(period, min_periods=period).mean()
    sd = close.rolling(period, min_periods=period).std(ddof=0)
    return mid + std_mult * sd, mid, mid - std_mult * sd

def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """Average True Range (vectorized)."""
    prev_close = close.shift(1)
    tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1/period, adjust=False, min_periods=period).mean()

def add_all_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    إضافة كافة المؤشرات الفنية للجدول (vectorized float64)
    """
    df = df.copy()
    if df.empty:
        return df

    df['ema_9'] = ema(df['close'], 9).astype('float64')
    df['ema_21'] = ema(df['close'], 21).astype('float64')
    df['ema_50'] = ema(df['close'], 50).astype('float64')
    df['ema_200'] = ema(df['close'], 200).astype('float64')

    df['rsi'] = rsi(df['close'], 14).astype('float64')

    bb_upper, bb_middle, bb_lower = bollinger(df['close'], period=20, std_mult=2.0)
    df['bb_upper'] = bb_upper.astype('float64')
    df['bb_middle'] = bb_middle.astype('float64')
    df['bb_lower'] = bb_lower.astype('float64')

    df['atr'] = atr(df['high'], df['low'], df['close'], period=14).astype('float64')

    df['volume_sma_20'] = df['volume'].rolling(window=20, min_periods=20).mean().astype('float64')
    df['volume_ratio'] = (df['volume'] / df['volume_sma_20']).astype('float64')

    return df

def min_candles_required() -> int:
    """أقل عدد شموع مطلوب لحساب المؤشرات بدقة"""
    return 210

def drop_forming_candle(df: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    """
    حذف الشمعة الجاري تشكلها إذا كان وقت إغلاقها لم يأتِ بعد
    """
    if df.empty or 'timestamp' not in df.columns or len(df) == 0:
        return df.copy()

    timeframe_ms = ccxt.Exchange.parse_timeframe(timeframe) * 1000
    last_ts = df['timestamp'].iloc[-1]
    now_ms = time.time() * 1000

    if last_ts + timeframe_ms > now_ms:
        return df.iloc[:-1].copy()

    return df.copy()

class TechnicalIndicators:
    """
    مكتبة حساب المؤشرات الفنية بدقة عالية (غلاف للتوافق الخلفي)
    """

    @staticmethod
    def calculate_rsi(series: pd.Series, period: int = 14) -> pd.Series:
        return rsi(series, period=period)

    @staticmethod
    def calculate_ema(series: pd.Series, span: int) -> pd.Series:
        return ema(series, period=span)

    @staticmethod
    def calculate_bollinger_bands(series: pd.Series, period: int = 20, std_dev: float = 2.0) -> Dict[str, pd.Series]:
        upper, middle, lower = bollinger(series, period=period, std_mult=std_dev)
        bandwidth = (upper - lower) / middle.replace(0, np.nan) * 100
        return {
            "bb_upper": upper,
            "bb_middle": middle,
            "bb_lower": lower,
            "bb_bandwidth": bandwidth
        }

    @staticmethod
    def calculate_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
        return atr(df['high'], df['low'], df['close'], period=period)

    @classmethod
    def enrich_dataframe(cls, df: pd.DataFrame) -> pd.DataFrame:
        """
        إضافة كافة المؤشرات الفنية المتقدمة لبيانات الشموع
        """
        if df.empty or len(df) < 30:
            return df

        df_enriched = add_all_indicators(df)
        df_enriched['bb_bandwidth'] = (df_enriched['bb_upper'] - df_enriched['bb_lower']) / df_enriched['bb_middle'].replace(0, np.nan) * 100
        df_enriched['volume_sma20'] = df_enriched['volume_sma_20']

        return df_enriched
