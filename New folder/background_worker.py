"""
المحرك الخلفي المستقل (Background Worker)
يعمل بشكل مستقل عن واجهة Streamlit لمراقبة الصفقات المفتوحة وتنفيذ أوامر الوقف والربح
"""

import time
import signal
import sys
import os
import threading
from datetime import datetime, timedelta
from typing import Optional

# إضافة مسار المشروع
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from logger import setup_logger
from config import config
from trading_engine import TradingEngine

logger = setup_logger("worker", log_file="worker.log")

# ============================================================
# إعدادات المحرك الخلفي
# ============================================================
MONITOR_INTERVAL_SECONDS = 20       # فترة المراقبة بالثواني
MAX_RETRIES_ON_ERROR = 5            # أقصى عدد محاولات متتالية عند الخطأ
BACKOFF_BASE_SECONDS = 5            # الوقت الأساسي للتراجع بين المحاولات
HEARTBEAT_INTERVAL_MINUTES = 30     # فترة نبض القلب (لتسجيل أن الـ Worker يعمل)

# ============================================================
# ملف حالة الـ Worker (لتتبع الحالة من الواجهة)
# ============================================================
STATUS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "worker_status.json")


class BackgroundWorker:
    """
    المحرك الخلفي المستقل لمراقبة وإدارة الصفقات المفتوحة.
    يعمل في حلقة مستمرة حتى بدون واجهة المستخدم.
    """

    def __init__(self):
        self._running = False
        self._engine: Optional[TradingEngine] = None
        self._consecutive_errors = 0
        self._total_cycles = 0
        self._total_events = 0
        self._start_time: Optional[datetime] = None
        self._last_heartbeat: Optional[datetime] = None

    def _write_status(self, status: str, details: str = ""):
        """كتابة حالة الـ Worker في ملف JSON لقراءتها من الواجهة"""
        import json
        data = {
            "status": status,
            "details": details,
            "pid": os.getpid(),
            "started_at": self._start_time.isoformat() if self._start_time else None,
            "updated_at": datetime.now().isoformat(),
            "total_cycles": self._total_cycles,
            "total_events": self._total_events,
            "consecutive_errors": self._consecutive_errors,
        }
        try:
            tmp_file = STATUS_FILE + ".tmp"
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            os.replace(tmp_file, STATUS_FILE)
        except Exception as e:
            logger.warning(f"فشل كتابة ملف الحالة: {e}")

    def _handle_shutdown(self, signum, frame):
        """معالجة إشارات الإيقاف (Ctrl+C أو إيقاف النظام)"""
        sig_name = signal.Signals(signum).name if hasattr(signal, 'Signals') else str(signum)
        logger.info(f"تم استقبال إشارة إيقاف ({sig_name}). جاري الإغلاق بأمان...")
        self._running = False

    def start(self):
        """تشغيل المحرك الخلفي"""
        logger.info("=" * 60)
        logger.info("🚀 بدء تشغيل المحرك الخلفي المستقل (Background Worker)")
        logger.info(f"   المنصة: {config.exchange_id.upper()}")
        logger.info(f"   وضع التداول: {'ورقي (Paper)' if config.is_paper_trading else 'حقيقي (Live) ⚠️'}")
        logger.info(f"   فترة المراقبة: كل {MONITOR_INTERVAL_SECONDS} ثانية")
        logger.info(f"   الأزواج المراقبة: {', '.join(config.monitored_pairs)}")
        logger.info("=" * 60)

        # تسجيل معالجات الإيقاف
        signal.signal(signal.SIGINT, self._handle_shutdown)
        signal.signal(signal.SIGTERM, self._handle_shutdown)
        if hasattr(signal, 'SIGBREAK'):
            signal.signal(signal.SIGBREAK, self._handle_shutdown)

        self._running = True
        self._start_time = datetime.now()
        self._last_heartbeat = datetime.now()

        # تهيئة محرك التداول
        try:
            self._engine = TradingEngine()
            logger.info("✅ تم تهيئة محرك التداول بنجاح")
        except Exception as e:
            logger.critical(f"❌ فشل تهيئة محرك التداول: {e}")
            self._write_status("ERROR", f"فشل التهيئة: {e}")
            return

        self._write_status("RUNNING", "المحرك يعمل ويراقب الصفقات")

        # =====================================================
        # الحلقة الرئيسية
        # =====================================================
        while self._running:
            try:
                self._run_cycle()
                self._consecutive_errors = 0  # إعادة العداد عند النجاح

            except KeyboardInterrupt:
                logger.info("تم إيقاف المحرك يدوياً (Ctrl+C)")
                break

            except Exception as e:
                self._consecutive_errors += 1
                logger.error(
                    f"❌ خطأ في دورة المراقبة (المحاولة {self._consecutive_errors}/{MAX_RETRIES_ON_ERROR}): {e}",
                    exc_info=True
                )

                if self._consecutive_errors >= MAX_RETRIES_ON_ERROR:
                    logger.critical(
                        f"🚨 تجاوز الحد الأقصى للأخطاء المتتالية ({MAX_RETRIES_ON_ERROR}). "
                        "إيقاف المحرك لحماية المحفظة."
                    )
                    self._write_status("ERROR", f"توقف بسبب {MAX_RETRIES_ON_ERROR} أخطاء متتالية")
                    break

                # Exponential Backoff
                backoff = BACKOFF_BASE_SECONDS * (2 ** (self._consecutive_errors - 1))
                backoff = min(backoff, 120)  # أقصى انتظار: دقيقتين
                logger.info(f"⏳ انتظار {backoff} ثانية قبل إعادة المحاولة...")
                self._write_status("RETRYING", f"إعادة المحاولة بعد {backoff} ثانية")
                self._interruptible_sleep(backoff)
                continue

            # نبض القلب (Heartbeat) — تسجيل دوري
            if self._last_heartbeat and (datetime.now() - self._last_heartbeat) >= timedelta(minutes=HEARTBEAT_INTERVAL_MINUTES):
                uptime = datetime.now() - self._start_time
                logger.info(
                    f"💓 نبض القلب — المحرك يعمل منذ {uptime} | "
                    f"إجمالي الدورات: {self._total_cycles} | الأحداث: {self._total_events}"
                )
                self._last_heartbeat = datetime.now()

            # الانتظار بين الدورات
            self._write_status("RUNNING", f"آخر دورة: {datetime.now().strftime('%H:%M:%S')}")
            self._interruptible_sleep(MONITOR_INTERVAL_SECONDS)

        # إيقاف نظيف
        self._shutdown()

    def _run_cycle(self):
        """تنفيذ دورة مراقبة واحدة مع دعم التداول الآلي"""
        self._total_cycles += 1

        # إعادة قراءة الإعدادات لالتقاط التغييرات الفورية من الواجهة
        from config import TradingConfig
        current_cfg = TradingConfig.load_from_json()

        # 1. تحديث الصفقات المفتوحة (الوقف، الهدف، الوقف المتحرك)
        events = self._engine.update_open_positions()

        if events:
            self._total_events += len(events)
            for event in events:
                logger.info(f"📢 حدث تداول: {event}")

        # 2. التداول الآلي: فحص الأزواج وفتح صفقات جديدة إذا كان مفعلاً
        if current_cfg.auto_trading_enabled:
            try:
                from universal_ai import UniversalAIClient
                state = self._engine.get_portfolio_state()
                open_trades = self._engine.get_open_trades()
                open_pairs = [t['pair'] for t in open_trades]

                if len(open_trades) < current_cfg.max_open_trades and state['usdt_balance'] >= current_cfg.trade_amount_usdt:
                    for pair in current_cfg.monitored_pairs:
                        if not self._running:
                            break
                        if pair in open_pairs:
                            continue

                        candles = self._engine.fetch_market_candles(pair, timeframe=current_cfg.timeframe, limit=60)
                        if candles.empty:
                            continue

                        ai_res = UniversalAIClient.analyze_market_with_llm(
                            candles_df=candles,
                            pair=pair,
                            base_url=current_cfg.ai_base_url,
                            api_key=current_cfg.ai_api_key,
                            model_name=current_cfg.ai_model,
                            take_profit_pct=current_cfg.take_profit_pct,
                            stop_loss_pct=current_cfg.stop_loss_pct
                        )

                        self._engine.log_ai_analysis(pair, ai_res)

                        if ai_res.signal == "BUY" and ai_res.confidence >= 65 and ai_res.safety_score >= 80:
                            logger.info(
                                f"🤖 إشارة شراء مؤكدة لـ {pair} | "
                                f"الثقة: {ai_res.confidence}% | الأمان: {ai_res.safety_score}%"
                            )
                            trade_id = self._engine.open_position(
                                pair=pair,
                                current_price=ai_res.current_price,
                                amount_usdt=current_cfg.trade_amount_usdt,
                                is_paper=current_cfg.is_paper_trading
                            )
                            if trade_id:
                                logger.info(f"✅ تم تنفيذ الشراء التلقائي! صفقة #{trade_id} على {pair}")
                                self._total_events += 1
                                break
            except Exception as e:
                logger.error(f"خطأ في التداول الآلي: {e}")

        # تسجيل ملخص الدورة (فقط كل 10 دورات لتقليل الضوضاء)
        if self._total_cycles % 10 == 0:
            open_trades = self._engine.get_open_trades()
            portfolio = self._engine.get_portfolio_state()
            logger.info(
                f"📊 ملخص الدورة #{self._total_cycles}: "
                f"صفقات مفتوحة: {len(open_trades)} | "
                f"الرصيد: {portfolio['usdt_balance']:.2f}$ | "
                f"إجمالي PnL: {portfolio['total_pnl']:+.4f}$"
            )

    def _interruptible_sleep(self, seconds: float):
        """نوم قابل للمقاطعة — يتوقف فوراً عند إشارة الإيقاف"""
        end_time = time.time() + seconds
        while self._running and time.time() < end_time:
            time.sleep(min(1.0, end_time - time.time()))

    def _shutdown(self):
        """إيقاف نظيف للمحرك"""
        self._running = False
        uptime = datetime.now() - self._start_time if self._start_time else timedelta(0)
        logger.info("=" * 60)
        logger.info("🛑 تم إيقاف المحرك الخلفي بأمان")
        logger.info(f"   مدة التشغيل: {uptime}")
        logger.info(f"   إجمالي دورات المراقبة: {self._total_cycles}")
        logger.info(f"   إجمالي الأحداث المعالجة: {self._total_events}")
        logger.info("=" * 60)
        self._write_status("STOPPED", f"توقف بعد {self._total_cycles} دورة")

        # تنظيف ملف الحالة
        try:
            if os.path.exists(STATUS_FILE):
                os.remove(STATUS_FILE)
        except Exception:
            pass


def is_worker_running() -> bool:
    """التحقق إن كان الـ Worker يعمل حالياً (يُستخدم من الواجهة)"""
    import json
    try:
        if not os.path.exists(STATUS_FILE):
            return False
        with open(STATUS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        # تحقق من أن الحالة RUNNING وأن آخر تحديث لم يتجاوز دقيقتين
        if data.get("status") not in ("RUNNING", "RETRYING"):
            return False

        updated_at = datetime.fromisoformat(data["updated_at"])
        if (datetime.now() - updated_at) > timedelta(minutes=2):
            return False

        # تحقق أن العملية (PID) ما زالت تعمل
        pid = data.get("pid")
        if pid:
            try:
                os.kill(pid, 0)  # لا يُرسل إشارة فعلية، فقط يتحقق من وجود العملية
            except OSError:
                return False

        return True
    except Exception:
        return False


def get_worker_status() -> dict:
    """جلب حالة الـ Worker التفصيلية (يُستخدم من الواجهة)"""
    import json
    try:
        if not os.path.exists(STATUS_FILE):
            return {"status": "STOPPED", "details": "لم يتم تشغيل المحرك الخلفي"}
        with open(STATUS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"status": "UNKNOWN", "details": "تعذر قراءة حالة المحرك"}


# ============================================================
# نقطة الدخول
# ============================================================
if __name__ == "__main__":
    worker = BackgroundWorker()
    worker.start()
