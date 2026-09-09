import os
import threading
import time
import datetime
import ccxt
from typing import Optional
from config import config, TradingConfig
from trading_engine import TradingEngine, _timeframe_to_seconds
from universal_ai import UniversalAIClient
from indicators import drop_forming_candle
from logger import setup_logger

logger = setup_logger("worker", log_file="worker.log")

STATUS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "worker_status.json")

class AutonomousTradingWorker:
    _instance = None
    _thread: Optional[threading.Thread] = None
    _stop_event = threading.Event()

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        self.engine = TradingEngine()
        self._start_time = None

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _write_status(self, status: str, details: str = "", cycle_duration_ms: int = 0):
        import json
        data = {
            "status": status,
            "details": details,
            "pid": os.getpid(),
            "started_at": self._start_time.isoformat() if self._start_time else None,
            "updated_at": datetime.datetime.now().isoformat(),
            "consecutive_errors": 0,
            "cycle_duration_ms": cycle_duration_ms,
        }
        try:
            tmp_file = STATUS_FILE + ".tmp"
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            os.replace(tmp_file, STATUS_FILE)
        except Exception as e:
            logger.warning(f"فشل كتابة ملف الحالة: {e}")

    def start(self):
        if self.is_running():
            logger.info("العامل الخلفي يعمل بالفعل.")
            return

        self._stop_event.clear()
        self._start_time = datetime.datetime.now()
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="TradingWorkerThread")
        self._thread.start()
        self.engine.set_worker_state(is_running=True, message="المحرك يعمل في الخلفية بنجاح 🟢")
        logger.info("🚀 تم تشغيل محرك التداول الآلي في الخلفية (24/7 Daemon).")
        self._write_status("RUNNING", "المحرك تعمل في الخلفية")

    def stop(self):
        if not self.is_running():
            self.engine.set_worker_state(is_running=False, message="المحرك متوقف 🔴")
            return

        logger.info("جاري إيقاف محرك التداول الآلي...")
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=4)
        self.engine.set_worker_state(is_running=False, message="المحرك متوقف 🔴")
        logger.info("🛑 تم إيقاف محرك التداول بنجاح.")

    def _run_loop(self):
        logger.info("بدء حلقة المراقبة والتنفيذ المستمرة...")
        last_scanner_time = time.time()
        while not self._stop_event.is_set():
            cycle_start = time.time()
            try:
                # Reload latest config on each iteration
                current_cfg = TradingConfig.load_from_json()

                # 0. معالجة الأوامر المعلقة من الواجهة (OPEN / CLOSE / KILL)
                try:
                    cmd_results = self.engine.process_pending_commands()
                    for res in cmd_results:
                        logger.info(f"⚡ تم تنفيذ أمر من الواجهة: {res}")
                except Exception as cmd_err:
                    logger.error(f"خطأ أثناء معالجة الأوامر المعلقة: {cmd_err}")

                # 0.1 مسح واقتناص الفرص الدوري في الخلفية (كل 3 دقائق)
                if time.time() - last_scanner_time > 180 and not self._stop_event.is_set():
                    try:
                        from market_scanner import MarketOpportunityScanner
                        scanner = MarketOpportunityScanner(self.engine)
                        scanner.scan_opportunities(max_pairs=10, stop_event=self._stop_event)
                        last_scanner_time = time.time()
                    except Exception as scan_err:
                        logger.warning(f"تنبيه مسح الفرص الدوري في الخلفية: {scan_err}")

                # 1. Update all open positions (Trailing stop, TP, SL)
                events = self.engine.update_open_positions()
                for ev in events:
                    logger.info(f"⚡ حدث تداول: {ev}")

                # 2. If Auto-trading is enabled, scan monitored pairs
                if current_cfg.auto_trading_enabled:
                    state = self.engine.get_portfolio_state()
                    open_trades = self.engine.get_open_trades()
                    open_pairs = [t['pair'] for t in open_trades]

                    if len(open_trades) < current_cfg.max_open_trades and state['usdt_balance'] >= current_cfg.trade_amount_usdt:
                        for pair in current_cfg.monitored_pairs:
                            if self._stop_event.is_set():
                                break
                            if pair in open_pairs:
                                continue

                            # Fetch market data
                            candles = self.engine.fetch_market_candles(pair, timeframe=current_cfg.timeframe, limit=250)
                            if candles.empty:
                                continue
                            candles = drop_forming_candle(candles, current_cfg.timeframe)

                            # Analyze with configured AI
                            ai_res = UniversalAIClient.analyze_market_with_llm(
                                candles_df=candles,
                                pair=pair,
                                base_url=current_cfg.ai_base_url,
                                api_key=current_cfg.ai_api_key,
                                model_name=current_cfg.ai_model,
                                take_profit_pct=current_cfg.take_profit_pct,
                                stop_loss_pct=current_cfg.stop_loss_pct
                            )

                            # Log analysis to DB
                            self.engine.log_ai_analysis(pair, ai_res)

                            # If AI strongly recommends BUY, execute automatically
                            if ai_res.signal == "BUY" and ai_res.confidence >= 65 and ai_res.safety_score >= 80:
                                logger.info(
                                    f"🤖 إشارة شراء مؤكدة من الذكاء الاصطناعي لـ {pair} | "
                                    f"الثقة: {ai_res.confidence}% | الأمان: {ai_res.safety_score}%"
                                )
                                res = self.engine.open_position(
                                    pair=pair,
                                    current_price=ai_res.current_price,
                                    amount_usdt=current_cfg.trade_amount_usdt,
                                    is_paper=current_cfg.is_paper_trading
                                )
                                trade_id = res[0] if isinstance(res, tuple) else res
                                if trade_id:
                                    logger.info(f"✅ تم تنفيذ الشراء التلقائي بنجاح! صفقة #{trade_id} على {pair}")
                                    break  # Open one trade per cycle to avoid race conditions

                # 3. Record Heartbeat & cycle duration
                cycle_duration_ms = int((time.time() - cycle_start) * 1000)
                tf_seconds = _timeframe_to_seconds(current_cfg.timeframe)
                if (time.time() - cycle_start) > (0.8 * tf_seconds):
                    logger.warning(
                        f"⚠️ تحذير: استغرقت دورة المحرك {cycle_duration_ms} ميلي ثانية وهي تتجاوز 80% من فترة الفريم ({current_cfg.timeframe} = {tf_seconds}s)"
                    )

                self.engine.set_worker_state(
                    is_running=True,
                    cycle_inc=True,
                    message=f"آخر فحص: {datetime.datetime.now().strftime('%H:%M:%S')} | تم فحص {len(current_cfg.monitored_pairs)} أزواج"
                )
                self._write_status(
                    "RUNNING",
                    f"آخر فحص: {datetime.datetime.now().strftime('%H:%M:%S')}",
                    cycle_duration_ms=cycle_duration_ms
                )

            except ccxt.BaseError as ccxt_err:
                now_dt = datetime.datetime.now(datetime.timezone.utc)
                self.engine.risk_manager.on_api_error(now_dt)
                logger.error(f"خطأ في الـ API من CCXT: {ccxt_err}")
                self.engine.set_worker_state(is_running=True, message=f"خطأ API: {str(ccxt_err)[:100]}")
            except Exception as e:
                logger.error(f"خطأ غير متوقع في دورة المحرك الآلي: {e}")
                self.engine.set_worker_state(is_running=True, message=f"تنبيه: {str(e)[:100]}")

            # Sleep in 1-second chunks to allow prompt shutdown
            interval = max(5, current_cfg.worker_interval_seconds)
            for _ in range(interval):
                if self._stop_event.is_set():
                    break
                time.sleep(1)

        self.engine.set_worker_state(is_running=False, message="المحرك متوقف")

def start_worker():
    AutonomousTradingWorker.get_instance().start()

def stop_worker():
    AutonomousTradingWorker.get_instance().stop()

def get_worker_status() -> bool:
    from background_worker import is_worker_running
    return AutonomousTradingWorker.get_instance().is_running() or is_worker_running()
