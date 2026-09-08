import pandas as pd
import numpy as np
from typing import Dict, Any
from config import config

class TechnicalIndicators:
    """
    مكتبة حساب المؤشرات الفنية بدقة عالية
    """

    @staticmethod
    def calculate_rsi(series: pd.Series, period: int = 14) -> pd.Series:
        """Calculate Relative Strength Index (RSI) using Wilder's smoothing"""
        delta = series.diff()
        gain = (delta.where(delta > 0, 0.0))
        loss = (-delta.where(delta < 0, 0.0))

        # Wilder's Smoothing
        avg_gain = gain.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1/period, min_periods=period, adjust=False).mean()

        rs = avg_gain / (avg_loss + 1e-10)
        rsi = 100 - (100 / (1 + rs))
        return rsi

    @staticmethod
    def calculate_ema(series: pd.Series, span: int) -> pd.Series:
        """Calculate Exponential Moving Average (EMA)"""
        return series.ewm(span=span, adjust=False).mean()

    @staticmethod
    def calculate_bollinger_bands(series: pd.Series, period: int = 20, std_dev: float = 2.0) -> Dict[str, pd.Series]:
        """Calculate Bollinger Bands (Upper, Middle, Lower, Bandwidth)"""
        middle = series.rolling(window=period).mean()
        std = series.rolling(window=period).std()
        upper = middle + (std_dev * std)
        lower = middle - (std_dev * std)
        bandwidth = (upper - lower) / (middle + 1e-10) * 100
        return {
            "bb_upper": upper,
            "bb_middle": middle,
            "bb_lower": lower,
            "bb_bandwidth": bandwidth
        }

    @staticmethod
    def calculate_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
        """Calculate Average True Range (ATR)"""
        high = df['high']
        low = df['low']
        close = df['close'].shift(1)
        tr1 = high - low
        tr2 = (high - close).abs()
        tr3 = (low - close).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
        return atr

    @classmethod
    def enrich_dataframe(cls, df: pd.DataFrame) -> pd.DataFrame:
        """
        إضافة كافة المؤشرات الفنية المتقدمة لبيانات الشموع
        """
        if df.empty or len(df) < 30:
            return df
        
        df = df.copy()

        # Moving Averages
        df['ema_9'] = cls.calculate_ema(df['close'], span=config.ema_fast)
        df['ema_21'] = cls.calculate_ema(df['close'], span=config.ema_slow)
        df['ema_50'] = cls.calculate_ema(df['close'], span=config.ema_trend)
        df['ema_200'] = cls.calculate_ema(df['close'], span=config.ema_baseline)

        # RSI
        df['rsi'] = cls.calculate_rsi(df['close'], period=14)

        # Bollinger Bands
        bb = cls.calculate_bollinger_bands(df['close'], period=config.bollinger_period, std_dev=config.bollinger_std_dev)
        df['bb_upper'] = bb['bb_upper']
        df['bb_middle'] = bb['bb_middle']
        df['bb_lower'] = bb['bb_lower']
        df['bb_bandwidth'] = bb['bb_bandwidth']

        # ATR
        df['atr'] = cls.calculate_atr(df, period=14)

        # Volume Moving Average
        df['volume_sma20'] = df['volume'].rolling(window=20).mean()
        df['volume_ratio'] = df['volume'] / (df['volume_sma20'] + 1e-10)

        df = df.ffill()

        return df
