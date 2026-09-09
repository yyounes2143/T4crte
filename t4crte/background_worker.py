"""
المحرك الخلفي المستقل (Background Worker)
يعمل بشكل مستقل عن واجهة Streamlit لمراقبة الصفقات المفتوحة وتنفيذ أوامر الوقف والربح
"""

import time
import signal
import sys
import os
import threading
import ccxt
from datetime import datetime, timedelta, timezone
from typing import Optional

# إضافة مسار المشروع
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from logger import setup_logger
from config import config
from trading_engine import TradingEngine
from indicators import drop_forming_candle

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

    def _write_status(self, status: str, details: str = "", cycle_duration_ms: int = 0):
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
            "cycle_duration_ms": cycle_duration_ms,
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

            except ccxt.BaseError as ccxt_err:
                self._consecutive_errors += 1
                if self._engine and hasattr(self._engine, 'risk_manager'):
                    self._engine.risk_manager.on_api_error(datetime.now(timezone.utc))
                logger.error(
                    f"❌ خطأ API في CCXT (المحاولة {self._consecutive_errors}/{MAX_RETRIES_ON_ERROR}): {ccxt_err}"
                )
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
        cycle_start = time.time()

        # إعادة قراءة الإعدادات لالتقاط التغييرات الفورية من الواجهة
        from config import TradingConfig
        current_cfg = TradingConfig.load_from_json()

        # 0. معالجة الأوامر المعلقة من الواجهة (OPEN / CLOSE / KILL)
        try:
            cmd_results = self._engine.process_pending_commands()
            if cmd_results:
                self._total_events += len(cmd_results)
                for res in cmd_results:
                    logger.info(f"⚡ تم تنفيذ أمر من الواجهة: {res}")
        except Exception as cmd_err:
            logger.error(f"خطأ أثناء معالجة الأوامر المعلقة: {cmd_err}")

        # 1. تحديث الصفقات المفتوحة (الوقف، الهدف، الوقف المتحرك)
        events = self._engine.update_open_positions()

        if events:
            self._total_events += len(events)
            for event in events:
                logger.info(f"📢 حدث تداول: {event}")

        # 2. التداول الآلي: فحص الأزواج باستخدام استراتيجية نظام السوق وقواعد ATR
        if current_cfg.auto_trading_enabled:
            try:
                from strategy import generate_signal
                from risk_manager import position_size_usdt
                import pandas as pd

                state = self._engine.get_portfolio_state()
                open_trades = self._engine.get_open_trades()
                open_pairs = [t['pair'] for t in open_trades]

                htf_tf = getattr(current_cfg, 'htf_timeframe', '1h')
                fee_pct = getattr(current_cfg, 'paper_fee_pct', 0.1) if current_cfg.is_paper_trading else 0.1
                slippage_pct = getattr(current_cfg, 'paper_slippage_pct', 0.05) if current_cfg.is_paper_trading else 0.05

                for pair in current_cfg.monitored_pairs:
                    if not self._running:
                        break

                    # Fetch market data (LTF and HTF)
                    df_ltf = self._engine.fetch_market_candles(pair, timeframe=current_cfg.timeframe, limit=250)
                    if df_ltf.empty:
                        continue
                    df_ltf = drop_forming_candle(df_ltf, current_cfg.timeframe)

                    df_htf = self._engine.fetch_market_candles(pair, timeframe=htf_tf, limit=250)
                    if not df_htf.empty:
                        df_htf = drop_forming_candle(df_htf, htf_tf)

                    sig = generate_signal(df_ltf, df_htf, fee_pct=fee_pct, slippage_pct=slippage_pct, cfg=current_cfg)
                    logger.info(
                        f"📊 الزوج: {pair} | Regime: {sig.regime} | Action: {sig.action} | "
                        f"Entry: {sig.entry:.4f} | Stop: {sig.stop:.4f} | TP: {sig.take_profit:.4f} | "
                        f"R:R: {sig.rr} | Reasons: {', '.join(sig.reasons)}"
                    )

                    if pair in open_pairs:
                        continue

                    if len(open_trades) < current_cfg.max_open_trades and state['usdt_balance'] >= current_cfg.trade_amount_usdt:
                        if sig.action == "BUY":
                            last_row = df_ltf.iloc[-1]
                            atr_val = float(last_row['atr']) if 'atr' in last_row and not pd.isna(last_row['atr']) else (float(last_row['high']) - float(last_row['low']))

                            pos_usdt, size_msg = position_size_usdt(
                                equity=state['total_equity'],
                                entry=sig.entry,
                                stop=sig.stop,
                                cfg=current_cfg.get_risk_config(),
                                rules=self._engine.exchange_rules,
                                symbol=pair
                            )
                            amount_to_use = min(current_cfg.trade_amount_usdt, pos_usdt) if pos_usdt > 0 else current_cfg.trade_amount_usdt

                            res = self._engine.open_position(
                                pair=pair,
                                current_price=sig.entry,
                                amount_usdt=amount_to_use,
                                is_paper=current_cfg.is_paper_trading,
                                stop_loss=sig.stop,
                                take_profit=sig.take_profit,
                                atr_at_entry=atr_val
                            )
                            trade_id = res[0] if isinstance(res, tuple) else res
                            if trade_id:
                                logger.info(f"✅ تم تنفيذ الشراء التلقائي بنجاح! صفقة #{trade_id} على {pair} [Regime: {sig.regime}]")
                                self._total_events += 1
                                open_trades = self._engine.get_open_trades()
                                open_pairs = [t['pair'] for t in open_trades]
                                break  # Open one trade per cycle to avoid race conditions
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

        # حساب زمن الدورة ومقارنته بالفريم الزمني
        cycle_duration_ms = int((time.time() - cycle_start) * 1000)
        from trading_engine import _timeframe_to_seconds
        tf_seconds = _timeframe_to_seconds(current_cfg.timeframe)
        if (time.time() - cycle_start) > (0.8 * tf_seconds):
            logger.warning(
                f"⚠️ تحذير: استغرقت دورة المحرك {cycle_duration_ms} ميلي ثانية وهي تتجاوز 80% من فترة الفريم ({current_cfg.timeframe} = {tf_seconds}s)"
            )
        self._write_status("RUNNING", f"آخر دورة: {datetime.now().strftime('%H:%M:%S')}", cycle_duration_ms=cycle_duration_ms)

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
