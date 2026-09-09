"""
وكيل مسح واقتناص الفرص الذكي (Market Opportunity Scanner Agent)
يقوم بمسح دوري لمجموعة من العملات الرقمية وتحليل حركتها الفنية والكمية
وتحديد أفضل العملات الموصى بالتداول فيها بناءً على مؤشرات الزخم والأمان.
"""

import time
import datetime
import sqlite3
import pandas as pd
from typing import List, Dict, Any, Optional
from config import config
from trading_engine import TradingEngine, POPULAR_PAIRS
from indicators import TechnicalIndicators
from logger import setup_logger

logger = setup_logger("scanner", log_file="trading.log")


class MarketOpportunityScanner:
    """
    وكيل ذكي مخصص لمسح ومقارنة العملات في السوق اللحظي
    واستخراج أفضل فرص التداول الفوري.
    """

    _last_scan_time: float = 0
    _last_results: List[Dict[str, Any]] = []

    def __init__(self, engine: Optional[TradingEngine] = None):
        self.engine = engine or TradingEngine()

    def scan_opportunities(
        self,
        pairs: Optional[List[str]] = None,
        max_pairs: int = 15,
        timeframe: str = "15m"
    ) -> List[Dict[str, Any]]:
        """
        مسح مجموعة من العملات واحتساب درجات الفرص والزخم لكل منها.
        """
        # إذا لم يتم تحديد أزواج، استخدم قائمة العملات الشعبية ومراقبة المحفظة
        if not pairs:
            monitored = list(config.monitored_pairs) if hasattr(config, "monitored_pairs") else []
            combined = monitored + [p for p in POPULAR_PAIRS if p not in monitored]
            pairs = combined[:max_pairs]

        logger.info(f"بدء مسح الفرص لـ {len(pairs)} عملة عبر وكيل اقتناص الفرص...")
        results = []

        for pair in pairs:
            try:
                # 1. جلب بيانات الشموع والمؤشرات
                df = self.engine.fetch_market_candles(pair, timeframe=timeframe, limit=250)
                if df.empty or len(df) < 25:
                    continue

                last_row = df.iloc[-1]
                prev_row = df.iloc[-2]
                curr_price = float(last_row['close'])
                prev_close = float(prev_row['close'])

                # حساب التغير السعري اللحظي وخلال الشموع الأخيرة
                price_change_pct = ((curr_price - prev_close) / prev_close) * 100 if prev_close > 0 else 0.0
                
                # حساب التغير السعري من بداية السلسلة المقروءة (تقريبي لـ 12-24 ساعة حسب الإطار)
                first_close = float(df.iloc[0]['close'])
                period_change_pct = ((curr_price - first_close) / first_close) * 100 if first_close > 0 else 0.0

                rsi = float(last_row.get('rsi', 50.0))
                ema_9 = float(last_row.get('ema_9', curr_price))
                ema_21 = float(last_row.get('ema_21', curr_price))
                ema_50 = float(last_row.get('ema_50', curr_price))
                bb_upper = float(last_row.get('bb_upper', curr_price * 1.02))
                bb_lower = float(last_row.get('bb_lower', curr_price * 0.98))
                bb_middle = float(last_row.get('bb_middle', curr_price))
                vol_ratio = float(last_row.get('volume_ratio', 1.0))

                # 2. احتساب نقاط الفرصة والزخم (Opportunity Score من 0 إلى 100)
                score = 50  # نقطة ارتكاز محايدة
                reasons = []

                # تقييم مؤشر RSI
                if rsi <= 30:
                    score += 25
                    reasons.append(f"تشبع بيعي حاد (RSI {rsi:.1f}) يرجح ارتداداً صاعداً قوياً")
                elif 30 < rsi <= 42:
                    score += 18
                    reasons.append(f"مناطق تجميع سعري منخفضة المخاطر (RSI {rsi:.1f})")
                elif 45 <= rsi <= 62:
                    score += 10
                    reasons.append(f"زخم صاعد صحي ومستمر (RSI {rsi:.1f})")
                elif rsi >= 72:
                    score -= 25
                    reasons.append(f"تشبع شرائي مرتفع (RSI {rsi:.1f})، احتمالية تصحيح وشيك")

                # تقييم المتوسطات الأسية والاتجاه
                if ema_9 > ema_21 > ema_50:
                    score += 20
                    reasons.append("ترتيب مثالي للمتوسطات الأسية (EMA 9 > 21 > 50) يدعم الاتجاه الصاعد")
                elif curr_price > ema_50:
                    score += 10
                    reasons.append("السعر يتداول أعلى متوسط الاتجاه الرئيسي (EMA 50)")
                else:
                    score -= 10
                    reasons.append("السعر يتداول أسفل متوسط الاتجاه (EMA 50)")

                # تقييم نطاقات بولينجر
                bb_range = bb_upper - bb_lower if bb_upper > bb_lower else curr_price * 0.01
                bb_position = (curr_price - bb_lower) / bb_range if bb_range > 0 else 0.5
                if bb_position <= 0.2:
                    score += 15
                    reasons.append("ارتداد واعد من النطاق السفلي لبولينجر (قاع محلي)")
                elif bb_position >= 0.85:
                    score -= 15
                    reasons.append("ملامسة النطاق العلوي لبولينجر (مقاومة سعرية)")

                # تقييم السيولة وحجم التداول
                if vol_ratio >= 1.4:
                    score += 10
                    reasons.append(f"تزايد غير عادي في حجم التداول ({vol_ratio:.1f}x مقارنة بالمتوسط)")

                # حصر الدرجة بين 1 و 99
                score = max(5, min(95, score))

                # تحديد الإشارة والتوصية
                if score >= 75:
                    signal = "STRONG_BUY"
                    signal_arabic = "شراء موصى به بقوة 🚀"
                    action_advice = "فرصة ذهبية عالية الأمان والزخم للدخول الفوري"
                elif score >= 62:
                    signal = "BUY"
                    signal_arabic = "فرصة ارتداد واعدة 🟢"
                    action_advice = "دخول آمن مع الالتزام بجني الربح عند الهدف"
                elif score >= 45:
                    signal = "WATCH"
                    signal_arabic = "مراقبة وتأهب 🟡"
                    action_advice = "انتظار تأكيد إضافي قبل تنفيذ أي صفقة"
                else:
                    signal = "AVOID"
                    signal_arabic = "تجنب / اتجاه ضعيف 🔴"
                    action_advice = "لا ينصح بالتداول حالياً لتفادي الانعكاسات"

                tp_price = curr_price * (1 + (config.take_profit_pct / 100))
                sl_price = curr_price * (1 - (config.stop_loss_pct / 100))

                results.append({
                    "pair": pair,
                    "price": curr_price,
                    "change_pct": round(period_change_pct, 2),
                    "rsi": round(rsi, 1),
                    "score": score,
                    "signal": signal,
                    "signal_arabic": signal_arabic,
                    "action_advice": action_advice,
                    "recommended_tp": round(tp_price, 4 if curr_price < 1 else 2),
                    "recommended_sl": round(sl_price, 4 if curr_price < 1 else 2),
                    "reasons": reasons,
                    "volume_ratio": round(vol_ratio, 2)
                })

            except Exception as e:
                logger.warning(f"خطأ أثناء مسح {pair}: {e}")
                continue

        # ترتيب النتائج تنازلياً حسب درجة الفرصة والزخم
        results.sort(key=lambda x: x["score"], reverse=True)

        # حفظ النتائج في قاعدة البيانات وذاكرة الكاش
        MarketOpportunityScanner._last_scan_time = time.time()
        MarketOpportunityScanner._last_results = results
        self._save_to_db(results)

        logger.info(f"اكتمل مسح السوق بنجاح. تم فحص {len(results)} عملة.")
        return results

    def _save_to_db(self, results: List[Dict[str, Any]]):
        """حفظ نتائج المسح في جدول scanner_history"""
        if not results:
            return
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            with self.engine._db_connection() as conn:
                cursor = conn.cursor()
                for r in results:
                    cursor.execute("""
                        INSERT INTO scanner_history (
                            scan_time, pair, price, change_24h, volume_24h, rsi,
                            opportunity_score, signal, signal_arabic, reasons
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        now_str,
                        r["pair"],
                        r["price"],
                        r["change_pct"],
                        r.get("volume_ratio", 1.0),
                        r["rsi"],
                        r["score"],
                        r["signal"],
                        r["signal_arabic"],
                        " | ".join(r["reasons"])
                    ))
                conn.commit()
        except Exception as e:
            logger.error(f"فشل حفظ نتائج المسح في قاعدة البيانات: {e}")

    @classmethod
    def get_latest_results(cls) -> List[Dict[str, Any]]:
        """جلب آخر نتائج مسح تم إجراؤها من الذاكرة"""
        return cls._last_results

    @classmethod
    def get_last_scan_time(cls) -> float:
        """جلب توقيت آخر مسح تم إجراؤه"""
        return cls._last_scan_time

    @classmethod
    def get_time_since_last_scan(cls) -> str:
        """عرض الوقت المنقضي منذ آخر مسح بصيغة عربية مقروءة"""
        if cls._last_scan_time <= 0:
            return "لم يتم المسح بعد"
        diff_sec = int(time.time() - cls._last_scan_time)
        if diff_sec < 60:
            return f"منذ {diff_sec} ثانية"
        mins = diff_sec // 60
        return f"منذ {mins} دقيقة"
