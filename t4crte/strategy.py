import pandas as pd
import numpy as np
from dataclasses import dataclass, field
from indicators import add_all_indicators

@dataclass
class Signal:
    action: str            # "BUY" | "HOLD"
    regime: str            # "TREND_UP" | "RANGE" | "NO_TRADE"
    entry: float
    stop: float
    take_profit: float
    rr: float
    reasons: list[str] = field(default_factory=list)


def detect_regime(df_htf: pd.DataFrame) -> str:
    """
    df_htf = شموع الفريم الأعلى (1h) مع المؤشرات
    last = آخر شمعة مغلقة
    TREND_UP إذا: close > ema_200 و ema_50 > ema_50.shift(10) و ema_50 > ema_200
    RANGE إذا: abs(ema_50 - ema_50.shift(10))/ema_50 < 0.002 و
               (bb_upper-bb_lower)/bb_middle < median((bb_upper-bb_lower)/bb_middle آخر 100 شمعة)
    غير ذلك: NO_TRADE
    """
    if df_htf is None or df_htf.empty or len(df_htf) < 200:
        return "NO_TRADE"

    if "ema_200" not in df_htf.columns or df_htf["ema_200"].isnull().all():
        df_htf = add_all_indicators(df_htf)

    if len(df_htf) < 200:
        return "NO_TRADE"

    last = df_htf.iloc[-1]
    close = float(last['close'])
    ema_200 = float(last['ema_200'])
    ema_50 = float(last['ema_50'])

    # ema_50.shift(10) at last row is iloc[-11]
    if len(df_htf) < 11:
        return "NO_TRADE"
    ema_50_shift10 = float(df_htf['ema_50'].iloc[-11])

    if pd.isna(close) or pd.isna(ema_200) or pd.isna(ema_50) or pd.isna(ema_50_shift10):
        return "NO_TRADE"

    # 1. Check TREND_UP
    if close > ema_200 and ema_50 > ema_50_shift10 and ema_50 > ema_200:
        return "TREND_UP"

    # 2. Check RANGE
    if ema_50 != 0:
        ema_diff_ratio = abs(ema_50 - ema_50_shift10) / ema_50
        if ema_diff_ratio < 0.002:
            bb_upper = df_htf['bb_upper']
            bb_lower = df_htf['bb_lower']
            bb_middle = df_htf['bb_middle']

            bandwidth_series = (bb_upper - bb_lower) / bb_middle.replace(0, np.nan)
            last_bw = float(bandwidth_series.iloc[-1])

            recent_bw = bandwidth_series.tail(min(100, len(bandwidth_series)))
            median_bw = float(recent_bw.median())

            if not pd.isna(last_bw) and not pd.isna(median_bw) and last_bw < median_bw:
                return "RANGE"

    return "NO_TRADE"


def generate_signal(df_ltf: pd.DataFrame, df_htf: pd.DataFrame, fee_pct: float, slippage_pct: float, cfg) -> Signal:
    """
    توليد إشارة التداول بناءً على نظام السوق وقواعد ATR
    """
    if df_ltf is None or df_ltf.empty or len(df_ltf) < 5:
        return Signal("HOLD", "NO_TRADE", 0.0, 0.0, 0.0, 0.0, ["بيانات الشموع غير كافية"])

    if "ema_50" not in df_ltf.columns or "atr" not in df_ltf.columns or df_ltf["ema_50"].isnull().all():
        df_ltf = add_all_indicators(df_ltf)

    if df_htf is not None and not df_htf.empty and ("ema_200" not in df_htf.columns or df_htf["ema_200"].isnull().all()):
        df_htf = add_all_indicators(df_htf)

    regime = detect_regime(df_htf)
    last = df_ltf.iloc[-1]
    entry = float(last['close'])

    if regime == "NO_TRADE":
        return Signal("HOLD", regime, entry, 0.0, 0.0, 0.0, ["نظام السوق غير مناسب للتداول (NO_TRADE)"])

    reasons = []

    # شرط سيولة: last.volume_ratio >= 1.0 وإلا HOLD
    volume_ratio = float(last.get('volume_ratio', 1.0))
    if volume_ratio < 1.0:
        reasons.append("ضعف السيولة: volume_ratio < 1.0")
        return Signal("HOLD", regime, entry, 0.0, 0.0, 0.0, reasons)

    prev = df_ltf.iloc[-2]
    atr_val = float(last['atr']) if 'atr' in last and not pd.isna(last['atr']) else (float(last['high']) - float(last['low']))
    atr_stop_mult = getattr(cfg, 'atr_stop_mult', 0.5) if cfg else 0.5
    atr_tp_mult = getattr(cfg, 'atr_tp_mult', 2.5) if cfg else 2.5

    stop = 0.0
    take_profit = 0.0

    if regime == "TREND_UP":
        # TREND_UP (دخول Pullback): last.close > ema_50 و prev.low <= prev.ema_21 و last.close > last.ema_9
        last_close = float(last['close'])
        last_ema_50 = float(last['ema_50'])
        prev_low = float(prev['low'])
        prev_ema_21 = float(prev['ema_21'])
        last_ema_9 = float(last['ema_9'])

        if last_close > last_ema_50 and prev_low <= prev_ema_21 and last_close > last_ema_9:
            lowest_5 = float(df_ltf['low'].tail(5).min())
            stop = lowest_5 - atr_stop_mult * atr_val
            take_profit = entry + atr_tp_mult * atr_val
        else:
            reasons.append("شروط دخول الاتجاه الصاعد (Pullback) غير متحققة")
            return Signal("HOLD", regime, entry, 0.0, 0.0, 0.0, reasons)

    elif regime == "RANGE":
        # RANGE (ارتداد): prev.close <= prev.bb_lower و last.close > last.bb_lower و last.rsi قطع 30 للأعلى (prev.rsi < 30 <= last.rsi)
        prev_close = float(prev['close'])
        prev_bb_lower = float(prev['bb_lower'])
        last_close = float(last['close'])
        last_bb_lower = float(last['bb_lower'])
        prev_rsi = float(prev['rsi'])
        last_rsi = float(last['rsi'])

        if prev_close <= prev_bb_lower and last_close > last_bb_lower and (prev_rsi < 30 <= last_rsi):
            prev_low = float(prev['low'])
            stop = prev_low - atr_stop_mult * atr_val
            take_profit = float(last['bb_middle'])
        else:
            reasons.append("شروط دخول ارتداد النطاق العرضي (RANGE) غير متحققة")
            return Signal("HOLD", regime, entry, 0.0, 0.0, 0.0, reasons)

    # Risk / Reward calculations
    risk = entry - stop
    if risk <= 0:
        reasons.append("الوقف أعلى من أو يساوي سعر الدخول")
        return Signal("HOLD", regime, entry, stop, take_profit, 0.0, reasons)

    reward = take_profit - entry
    rr = reward / risk

    # Min R:R check
    min_rr = getattr(cfg, 'min_rr', 1.5) if cfg else 1.5
    if rr < min_rr:
        reasons.append("R:R منخفض")
        return Signal("HOLD", regime, entry, stop, take_profit, round(rr, 2), reasons)

    # Fee cover check: min_tp_pct = 3 * (2*fee_pct + slippage_pct)
    min_tp_pct = 3.0 * (2.0 * fee_pct + slippage_pct)
    tp_pct = ((take_profit - entry) / entry) * 100.0
    if tp_pct < min_tp_pct:
        reasons.append("الهدف لا يغطي الرسوم")
        return Signal("HOLD", regime, entry, stop, take_profit, round(rr, 2), reasons)

    # Max SL check: (entry - stop) / entry > 0.03
    sl_pct = (entry - stop) / entry
    if sl_pct > 0.03:
        reasons.append("الوقف بعيد جداً")
        return Signal("HOLD", regime, entry, stop, take_profit, round(rr, 2), reasons)

    reasons.append(f"إشارة شراء بنظام {regime}")
    return Signal(
        action="BUY",
        regime=regime,
        entry=entry,
        stop=stop,
        take_profit=take_profit,
        rr=round(rr, 2),
        reasons=reasons
    )
