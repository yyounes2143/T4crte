import pandas as pd
import numpy as np
from typing import Dict, Any, Tuple, Optional
from dataclasses import dataclass
from config import config

@dataclass
class AIAnalysisResult:
    signal: str  # "BUY", "SELL", "HOLD"
    signal_arabic: str  # "شراء قوي 🟢", "بيع/تأمين 🔴", "مراقبة وانتظار 🟡"
    confidence: int  # 0 to 100%
    safety_score: int  # 0 to 100%
    market_sentiment: str  # "صاعد (Bullish)", "هابط (Bearish)", "تذبذب عرضي (Sideways)"
    current_price: float
    recommended_tp: float
    recommended_sl: float
    reasons: list
    arabic_summary: str
    detailed_advice: str
    buy_points: int = 0
    sell_points: int = 0

class AIAdvisor:
    """
    محرك التحليل الاستشاري للذكاء الاصطناعي
    يقوم بفحص كافة المؤشرات وتوليد نصائح وتوصيات دقيقة باللغة العربية
    """

    @classmethod
    def analyze(
        cls,
        df: pd.DataFrame,
        pair: str,
        take_profit_pct: float = 1.8,
        stop_loss_pct: float = 1.2,
        analysis_time: Optional[float] = None
    ) -> AIAnalysisResult:
        if df.empty or len(df) < 210:
            current_price = 0.0 if df.empty or 'close' not in df.columns else float(df.iloc[-1]['close'])
            return AIAnalysisResult(
                signal="HOLD",
                signal_arabic="بيانات غير كافية ⏳",
                confidence=0,
                safety_score=50,
                market_sentiment="غير محدد",
                current_price=current_price,
                recommended_tp=0.0,
                recommended_sl=0.0,
                reasons=["يلزم 200 شمعة على الأقل لحساب كافة المؤشرات بدقة."],
                arabic_summary="جاري انتظار اكتمال بيانات الشموع للزوج.",
                detailed_advice="يرجى الانتظار بضع ثوانٍ لجلب الشموع الكاملة.",
                buy_points=0,
                sell_points=0
            )

        last_row = df.iloc[-1]
        prev_row = df.iloc[-2]

        current_price = float(last_row['close'])
        rsi = float(last_row['rsi'])
        ema_9 = float(last_row['ema_9'])
        ema_21 = float(last_row['ema_21'])
        ema_50 = float(last_row['ema_50'])
        ema_200 = float(last_row['ema_200']) if 'ema_200' in df.columns else float('nan')
        bb_upper = float(last_row['bb_upper'])
        bb_lower = float(last_row['bb_lower'])
        bb_middle = float(last_row['bb_middle'])
        volume_ratio = float(last_row.get('volume_ratio', 1.0))
        atr = float(last_row.get('atr', current_price * 0.01))

        # فحص القيم غير الصالحة
        values_to_check = [rsi, ema_9, ema_21, ema_50, ema_200, bb_upper, bb_lower, bb_middle]
        if any(pd.isna(v) or np.isinf(v) for v in values_to_check):
            if pd.isna(ema_200) or np.isinf(ema_200):
                sig_arabic = "بيانات غير كافية ⏳"
                reason_msg = "يلزم 200 شمعة على الأقل لحساب كافة المؤشرات بدقة."
            else:
                sig_arabic = "بيانات غير مكتملة ⚠️"
                reason_msg = "بعض المؤشرات الفنية تحتوي على قيم غير صالحة. يتم إعادة الحساب..."

            return AIAnalysisResult(
                signal='HOLD',
                signal_arabic=sig_arabic,
                confidence=0,
                safety_score=50,
                market_sentiment='غير محدد',
                current_price=current_price,
                recommended_tp=0.0,
                recommended_sl=0.0,
                reasons=[reason_msg],
                arabic_summary='تم اكتشاف قيم غير صالحة أو غير مكتملة في المؤشرات. يرجى الانتظار.',
                detailed_advice='سيتم تحديث البيانات تلقائياً في الدورة القادمة.',
                buy_points=0,
                sell_points=0
            )

        # 1. Macro Trend Determination
        if current_price > ema_50 and ema_50 > ema_200:
            sentiment = "صاعد قوي (Bullish 🚀)"
            trend_score = 30
        elif current_price > ema_50:
            sentiment = "صاعد معتدل (Moderate Bullish 📈)"
            trend_score = 20
        elif current_price < ema_50 and ema_50 < ema_200:
            sentiment = "هابط قوي (Bearish 📉)"
            trend_score = -25
        else:
            sentiment = "تذبذب عرضي محايد (Sideways ↔️)"
            trend_score = 0

        # 2. Indicators Signal Evaluation
        buy_points = 0
        sell_points = 0
        reasons = []

        # RSI Checks
        if rsi <= config.rsi_oversold - 5:
            buy_points += 35
            reasons.append(f"مؤشر القوة النسبية RSI ({rsi:.1f}) في منطقة تشبع بيعي حاد، فرصة ممتازة للارتداد الصاعد.")
        elif rsi <= config.rsi_oversold + 3:
            buy_points += 20
            reasons.append(f"مؤشر RSI ({rsi:.1f}) يقترب من مناطق القاع السعري، مما يمنح أفضلية لدخول آمن.")
        elif rsi >= config.rsi_overbought + 2:
            sell_points += 35
            reasons.append(f"مؤشر RSI ({rsi:.1f}) في تشبع شرائي مفرط، خطر تصحيح سعري وشيك.")
        elif rsi >= config.rsi_overbought - 6:
            sell_points += 15
            reasons.append(f"مؤشر RSI ({rsi:.1f}) في منطقة مرتفعة تتطلب الحذر.")

        # Bollinger Bands Checks
        if bb_upper > bb_lower:
            if current_price <= bb_lower * 1.002:
                buy_points += 25
                reasons.append(f"السعر يلامس النطاق السفلي لبولينجر ({bb_lower:.2f})، وهو مستوى دعم فني صلب.")
            elif current_price >= bb_upper * 0.998:
                sell_points += 25
                reasons.append(f"السعر يختبر النطاق العلوي لبولينجر ({bb_upper:.2f})، مقاومة قوية قد توقف الصعود.")

        # Moving Averages Alignment
        if ema_9 > ema_21 and prev_row['ema_9'] <= prev_row['ema_21']:
            buy_points += 25
            reasons.append("تقاطع ذهبي سريع: متوسط EMA-9 اخترق EMA-21 للأعلى مؤكداً بداية زخم شرائي.")
        elif ema_9 > ema_21:
            buy_points += 10
            reasons.append("المتوسطات السريعة (EMA 9/21) تدعم استمرار الحركة الإيجابية.")
        elif ema_9 < ema_21 and prev_row['ema_9'] >= prev_row['ema_21']:
            sell_points += 25
            reasons.append("تقاطع سلبي سريع: EMA-9 هبط تحت EMA-21 معلناً بداية ضعف الزخم.")

        # Volume Confirmation
        if volume_ratio >= 1.2:
            reasons.append(f"حجم التداول أعلى من المعتاد بـ {volume_ratio:.1f}x، مما يمنح مصداقية إضافية للحركة.")
            if buy_points > sell_points:
                buy_points += 10
            elif sell_points > buy_points:
                sell_points += 10

        # Total Calculation
        total_score = buy_points - sell_points + trend_score

        confidence = int(max(0, min(100, 50 + total_score / 2)))
        safety_score = int(max(0, min(100, 100 - sell_points - (25 if trend_score < 0 else 0))))

        # Targets
        recommended_tp = current_price * (1 + (take_profit_pct / 100))
        recommended_sl = current_price * (1 - (stop_loss_pct / 100))

        if total_score >= 65 and sell_points < 20:
            signal = "BUY"
            signal_arabic = "شراء مؤكد 🟢"
            summary = f"الفرصة مهيأة لصفقة شراء ذات احتمالية نجاح عالية على {pair}. المؤشرات تدل على ارتداد إيجابي محمي بوقف خسارة."
            advice = (
                f"يوصى بالدخول بسعر حوالي {current_price:.2f}$. "
                f"تم تحديد جني الأرباح عند {recommended_tp:.2f}$ (+{take_profit_pct}%) "
                f"مع تفعيل الوقف المتحرك بمجرد تحقيق +0.8% لحماية رأس المال كاملاً."
            )
        elif sell_points >= 45 or total_score < -20:
            signal = "SELL"
            signal_arabic = "بيع / جني أرباح 🔴"
            summary = f"إشارة لتهدئة المراكز على {pair}. السعر يواجه مقاومات فنية وتشبعاً شرائياً."
            advice = "إذا كانت لديك صفقة مفتوحة، يفضل جني الأرباح الآن أو تشديد وقف الخسارة المتحرك لحجز العوائد."
        else:
            signal = "HOLD"
            signal_arabic = "مراقبة وانتظار 🟡"
            summary = f"السوق في حالة ترقب وتوازن نسبي على {pair}. نفضل البقاء بالدولار (USDT) لحين ظهور إشارة مؤكدة."
            advice = "وفقاً لاستراتيجية الحفاظ القصوى على رأس المال (4$)، لا ندخل في صفقات عشوائية حتى تتطابق شروط الأمان 100%."

        return AIAnalysisResult(
            signal=signal,
            signal_arabic=signal_arabic,
            confidence=confidence,
            safety_score=safety_score,
            market_sentiment=sentiment,
            current_price=current_price,
            recommended_tp=recommended_tp,
            recommended_sl=recommended_sl,
            reasons=reasons,
            arabic_summary=summary,
            detailed_advice=advice,
            buy_points=buy_points,
            sell_points=sell_points
        )
