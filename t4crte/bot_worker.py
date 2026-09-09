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
        try:
            self.engine.reconcile_on_startup()
        except Exception as rec_err:
            logger.error(f"خطأ أثناء reconcile_on_startup: {rec_err}")

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

                # 2. If Auto-trading is enabled, scan monitored pairs using new Strategy
                if current_cfg.auto_trading_enabled:
                    from strategy import generate_signal
                    from risk_manager import position_size_usdt
                    import pandas as pd

                    state = self.engine.get_portfolio_state()
                    open_trades = self.engine.get_open_trades()
                    open_pairs = [t['pair'] for t in open_trades]

                    htf_tf = getattr(current_cfg, 'htf_timeframe', '1h')
                    fee_pct = getattr(current_cfg, 'paper_fee_pct', 0.1) if current_cfg.is_paper_trading else 0.1
                    slippage_pct = getattr(current_cfg, 'paper_slippage_pct', 0.05) if current_cfg.is_paper_trading else 0.05

                    for pair in current_cfg.monitored_pairs:
                        if self._stop_event.is_set():
                            break

                        # Fetch market data (LTF and HTF)
                        df_ltf = self.engine.fetch_market_candles(pair, timeframe=current_cfg.timeframe, limit=250)
                        if df_ltf.empty:
                            continue
                        df_ltf = drop_forming_candle(df_ltf, current_cfg.timeframe)

                        df_htf = self.engine.fetch_market_candles(pair, timeframe=htf_tf, limit=250)
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
                                    rules=self.engine.exchange_rules,
                                    symbol=pair
                                )
                                amount_to_use = min(current_cfg.trade_amount_usdt, pos_usdt) if pos_usdt > 0 else current_cfg.trade_amount_usdt

                                res = self.engine.open_position(
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
                                    open_trades = self.engine.get_open_trades()
                                    open_pairs = [t['pair'] for t in open_trades]
                                    break  # Open one trade per cycle to avoid race conditions

                # 3. Record Heartbeat & cycle duration
                cycle_duration_ms = int((time.time() - cycle_start) * 1000)
                tf_seconds = _timeframe_to_seconds(current_cfg.timeframe)
                if (time.time() - cycle_start) > (0.8 * tf_seconds):
                    logger.warning(
                        f"⚠️ تحذير: استغرقت دورة المحرك {cycle_duration_ms} ميلي ثانية وهي تتجاوز 80% من فترة الفريم ({current_cfg.timeframe} = {tf_seconds}s)"
                    )

                # 4. Kill Switch تلقائي عند تجاوز حد أخطاء API في الساعة الأخيرة
                if not self.engine.risk_manager.kill_switch:
                    now_dt = datetime.datetime.now(datetime.timezone.utc)
                    max_api_errs = self.engine.risk_manager.cfg.max_api_errors_per_hour
                    if self.engine.risk_manager.count_api_errors_last_hour(now_dt) > max_api_errs:
                        logger.error("🚨 تجاوز عدد أخطاء API الحد المسموح — تفعيل Kill Switch تلقائي")
                        self.engine.execute_kill_switch("تجاوز عدد أخطاء API في الساعة الأخيرة (تلقائي)")

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
