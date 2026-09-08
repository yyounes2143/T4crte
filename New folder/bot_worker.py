import threading
import time
import datetime
from typing import Optional
from config import config, TradingConfig
from trading_engine import TradingEngine
from universal_ai import UniversalAIClient
from logger import setup_logger

logger = setup_logger("worker", log_file="worker.log")

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

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self):
        if self.is_running():
            logger.info("العامل الخلفي يعمل بالفعل.")
            return

        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="TradingWorkerThread")
        self._thread.start()
        self.engine.set_worker_state(is_running=True, message="المحرك يعمل في الخلفية بنجاح 🟢")
        logger.info("🚀 تم تشغيل محرك التداول الآلي في الخلفية (24/7 Daemon).")

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
            try:
                # Reload latest config on each iteration
                current_cfg = TradingConfig.load_from_json()

                # 0. مسح واقتناص الفرص الدوري في الخلفية (كل 3 دقائق)
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
                            candles = self.engine.fetch_market_candles(pair, timeframe=current_cfg.timeframe, limit=60)
                            if candles.empty:
                                continue

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
                                trade_id = self.engine.open_position(
                                    pair=pair,
                                    current_price=ai_res.current_price,
                                    amount_usdt=current_cfg.trade_amount_usdt,
                                    is_paper=current_cfg.is_paper_trading
                                )
                                if trade_id:
                                    logger.info(f"✅ تم تنفيذ الشراء التلقائي بنجاح! صفقة #{trade_id} على {pair}")
                                    break  # Open one trade per cycle to avoid race conditions

                # 3. Record Heartbeat
                self.engine.set_worker_state(
                    is_running=True,
                    cycle_inc=True,
                    message=f"آخر فحص: {datetime.datetime.now().strftime('%H:%M:%S')} | تم فحص {len(current_cfg.monitored_pairs)} أزواج"
                )

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
    return AutonomousTradingWorker.get_instance().is_running()
