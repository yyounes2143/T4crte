"""
اختبارات شاملة لبوت التداول — تتضمن:
- اختبارات محلية (بدون اتصال بالإنترنت) باستخدام Mock
- اختبارات سيناريوهات الفشل والحالات الحدية
- تنظيف تلقائي لقاعدة البيانات المؤقتة
"""

import os
import sys
import unittest
import gc
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Configure stdout for UTF-8 on Windows
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

import pandas as pd
import numpy as np

from config import config
from indicators import TechnicalIndicators
from ai_advisor import AIAdvisor
from trading_engine import TradingEngine


def _create_mock_candles(rows: int = 60, base_price: float = 60000.0) -> pd.DataFrame:
    """إنشاء بيانات شموع وهمية للاختبار بدون اتصال بالإنترنت"""
    np.random.seed(42)
    timestamps = pd.date_range("2025-01-01", periods=rows, freq="15min")
    closes = base_price + np.cumsum(np.random.randn(rows) * 50)
    df = pd.DataFrame({
        'timestamp': [int(t.timestamp() * 1000) for t in timestamps],
        'open': closes - np.random.rand(rows) * 20,
        'high': closes + np.random.rand(rows) * 30,
        'low': closes - np.random.rand(rows) * 30,
        'close': closes,
        'volume': np.random.rand(rows) * 100 + 50,
        'datetime': timestamps,
    })
    return TechnicalIndicators.enrich_dataframe(df)


class TestTradingEngineLocal(unittest.TestCase):
    """اختبارات محرك التداول — محلية بالكامل (بدون API)"""

    @classmethod
    def setUpClass(cls):
        cls.test_db = os.path.join(os.path.dirname(__file__), "test_trading.db")
        # تنظيف أي بقايا من اختبارات سابقة
        for f in [cls.test_db, cls.test_db + "-wal", cls.test_db + "-shm"]:
            if os.path.exists(f):
                try:
                    os.remove(f)
                except Exception:
                    pass
        cls.engine = TradingEngine(db_path=cls.test_db)

    @classmethod
    def tearDownClass(cls):
        del cls.engine
        gc.collect()
        # تنظيف جميع ملفات قاعدة البيانات المؤقتة
        for f in [cls.test_db, cls.test_db + "-wal", cls.test_db + "-shm"]:
            if os.path.exists(f):
                try:
                    os.remove(f)
                except Exception:
                    pass

    def setUp(self):
        """إعادة ضبط الرصيد قبل كل اختبار"""
        self.engine.reset_paper_balance(4.0)

    # ============================================================
    # اختبارات المحفظة والأوامر الأساسية
    # ============================================================

    def test_initial_portfolio_state(self):
        """التحقق من الحالة الأولية للمحفظة"""
        state = self.engine.get_portfolio_state()
        self.assertEqual(state["usdt_balance"], 4.0)
        self.assertEqual(state["initial_balance"], 4.0)
        self.assertEqual(state["open_trades_count"], 0)
        self.assertEqual(state["wins"], 0)
        self.assertEqual(state["losses"], 0)

    def test_open_position_success(self):
        """فتح صفقة بنجاح"""
        trade_id = self.engine.open_position("BTC/USDT", 60000.0, 2.0, is_paper=True)
        self.assertIsNotNone(trade_id)

        state = self.engine.get_portfolio_state()
        self.assertEqual(state["usdt_balance"], 2.0)
        self.assertEqual(state["open_trades_count"], 1)

    def test_open_position_insufficient_balance(self):
        """رفض فتح صفقة عند عدم كفاية الرصيد"""
        trade_id = self.engine.open_position("BTC/USDT", 60000.0, 10.0, is_paper=True)
        self.assertIsNone(trade_id)

    def test_open_position_zero_price(self):
        """رفض فتح صفقة بسعر صفر"""
        trade_id = self.engine.open_position("BTC/USDT", 0.0, 2.0, is_paper=True)
        self.assertIsNone(trade_id)

    def test_max_open_trades_limit(self):
        """التحقق من الحد الأقصى للصفقات المفتوحة"""
        # فتح الحد الأقصى (config.max_open_trades = 2)
        self.engine.open_position("BTC/USDT", 60000.0, 1.5, is_paper=True)
        self.engine.open_position("ETH/USDT", 3000.0, 1.5, is_paper=True)
        # المحاولة الثالثة يجب أن تفشل
        trade_id = self.engine.open_position("SOL/USDT", 100.0, 1.0, is_paper=True)
        self.assertIsNone(trade_id)

    def test_close_position_with_profit(self):
        """إغلاق صفقة بربح والتحقق من تحديث المحفظة"""
        trade_id = self.engine.open_position("BTC/USDT", 60000.0, 2.0, is_paper=True)
        self.assertIsNotNone(trade_id)

        # إغلاق بربح +1.8%
        exit_price = 60000.0 * 1.018  # = 61,080
        self.engine.close_position(trade_id, exit_price, "Take Profit ✅")

        state = self.engine.get_portfolio_state()
        self.assertEqual(state["open_trades_count"], 0)
        self.assertGreater(state["usdt_balance"], 4.0)
        self.assertEqual(state["wins"], 1)
        self.assertEqual(state["losses"], 0)

    def test_close_position_with_loss(self):
        """إغلاق صفقة بخسارة والتحقق من تحديث المحفظة"""
        trade_id = self.engine.open_position("BTC/USDT", 60000.0, 2.0, is_paper=True)
        self.assertIsNotNone(trade_id)

        # إغلاق بخسارة -1.2%
        exit_price = 60000.0 * 0.988  # = 59,280
        self.engine.close_position(trade_id, exit_price, "Stop Loss ⚠️")

        state = self.engine.get_portfolio_state()
        self.assertEqual(state["open_trades_count"], 0)
        self.assertLess(state["usdt_balance"], 4.0)
        self.assertEqual(state["wins"], 0)
        self.assertEqual(state["losses"], 1)

    def test_close_nonexistent_trade(self):
        """محاولة إغلاق صفقة غير موجودة (يجب أن لا يحدث خطأ)"""
        # يجب أن لا يرمي استثناءً
        self.engine.close_position(99999, 60000.0, "Nonexistent")

    def test_reset_paper_balance(self):
        """التحقق من إعادة ضبط الرصيد التجريبي"""
        self.engine.open_position("BTC/USDT", 60000.0, 2.0, is_paper=True)
        self.engine.reset_paper_balance(10.0)
        state = self.engine.get_portfolio_state()
        self.assertEqual(state["usdt_balance"], 10.0)
        self.assertEqual(state["open_trades_count"], 0)

    # ============================================================
    # اختبارات المؤشرات الفنية
    # ============================================================

    def test_indicators_on_mock_data(self):
        """التحقق من حساب المؤشرات الفنية على بيانات وهمية"""
        df = _create_mock_candles(60)
        self.assertFalse(df.empty)
        self.assertIn("rsi", df.columns)
        self.assertIn("ema_9", df.columns)
        self.assertIn("ema_21", df.columns)
        self.assertIn("ema_50", df.columns)
        self.assertIn("bb_upper", df.columns)
        self.assertIn("bb_lower", df.columns)
        self.assertIn("atr", df.columns)

        # التحقق من عدم وجود NaN بعد الإثراء
        last = df.iloc[-1]
        self.assertFalse(pd.isna(last['rsi']))
        self.assertFalse(pd.isna(last['ema_9']))

    def test_indicators_insufficient_data(self):
        """التحقق من عدم حدوث خطأ مع بيانات غير كافية"""
        df = _create_mock_candles(5)
        # يجب أن تعود كما هي بدون مؤشرات
        self.assertNotIn("rsi", df.columns)

    # ============================================================
    # اختبارات المستشار الذكي (AI Advisor)
    # ============================================================

    def test_ai_advisor_valid_data(self):
        """اختبار المستشار الذكي مع بيانات صالحة"""
        df = _create_mock_candles(60)
        result = AIAdvisor.analyze(df, "BTC/USDT", take_profit_pct=1.8, stop_loss_pct=1.2)

        self.assertIn(result.signal, ["BUY", "SELL", "HOLD"])
        self.assertGreater(len(result.arabic_summary), 5)
        self.assertGreater(len(result.detailed_advice), 5)
        self.assertGreaterEqual(result.safety_score, 0)
        self.assertLessEqual(result.safety_score, 100)

    def test_ai_advisor_empty_data(self):
        """اختبار المستشار الذكي مع بيانات فارغة"""
        result = AIAdvisor.analyze(pd.DataFrame(), "BTC/USDT")
        self.assertEqual(result.signal, "HOLD")
        self.assertEqual(result.confidence, 0)

    def test_ai_advisor_insufficient_data(self):
        """اختبار المستشار الذكي مع شموع أقل من 30"""
        df = _create_mock_candles(10)
        result = AIAdvisor.analyze(df, "BTC/USDT")
        self.assertEqual(result.signal, "HOLD")

    # ============================================================
    # اختبارات مع Mock لأخطاء الشبكة
    # ============================================================

    def test_get_current_price_network_failure(self):
        """التحقق من سلوك جلب السعر عند فشل الشبكة"""
        with patch.object(self.engine._exchange, 'fetch_ticker', side_effect=Exception("Network Error")):
            price = self.engine.get_current_price("BTC/USDT")
            self.assertEqual(price, 0.0)

    def test_fetch_candles_network_failure(self):
        """التحقق من سلوك جلب الشموع عند فشل الشبكة"""
        with patch.object(self.engine._exchange, 'fetch_ohlcv', side_effect=Exception("Timeout")):
            df = self.engine.fetch_market_candles("BTC/USDT")
            self.assertTrue(df.empty)

    # ============================================================
    # اختبار الوقف المتحرك (Trailing Stop)
    # ============================================================

    def test_trailing_stop_activation(self):
        """اختبار تفعيل الوقف المتحرك عند تحقق الشرط"""
        trade_id = self.engine.open_position("BTC/USDT", 60000.0, 2.0, is_paper=True)
        self.assertIsNotNone(trade_id)

        # المرحلة 1: ارتفاع السعر إلى 60600 (+1%) → يُفعّل الوقف المتحرك
        # trailing_stop = 60600 * (1 - 0.004) = 60357.6
        with patch.object(self.engine, 'get_current_price', return_value=60600.0):
            events = self.engine.update_open_positions()

        # المرحلة 2: ارتفاع إضافي إلى 61000 (+1.67%) → يُرفع الوقف المتحرك
        # trailing_stop = 61000 * (1 - 0.004) = 60756.0
        with patch.object(self.engine, 'get_current_price', return_value=61000.0):
            events = self.engine.update_open_positions()

        # المرحلة 3: هبوط تحت الوقف المتحرك لكن فوق عتبة التفعيل (+0.8%)
        # السعر 60700 → pnl = +1.17% > 0.8% (activated) و 60700 < 60756 (trailing stop)
        with patch.object(self.engine, 'get_current_price', return_value=60700.0):
            events = self.engine.update_open_positions()

        # يجب أن تُغلق الصفقة بالوقف المتحرك مع ربح
        state = self.engine.get_portfolio_state()
        self.assertEqual(state["open_trades_count"], 0)
        self.assertGreater(state["usdt_balance"], 4.0)  # ربح محجوز

    def test_take_profit_trigger(self):
        """اختبار إغلاق الصفقة عند بلوغ هدف الربح"""
        trade_id = self.engine.open_position("BTC/USDT", 60000.0, 2.0, is_paper=True)
        self.assertIsNotNone(trade_id)

        # سعر أعلى من هدف الربح (+1.8%)
        tp_price = 60000.0 * 1.02  # 61,200 > الهدف 61,080
        with patch.object(self.engine, 'get_current_price', return_value=tp_price):
            events = self.engine.update_open_positions()

        self.assertTrue(len(events) > 0)
        state = self.engine.get_portfolio_state()
        self.assertEqual(state["open_trades_count"], 0)
        self.assertEqual(state["wins"], 1)

    def test_stop_loss_trigger(self):
        """اختبار إغلاق الصفقة عند بلوغ وقف الخسارة"""
        trade_id = self.engine.open_position("BTC/USDT", 60000.0, 2.0, is_paper=True)
        self.assertIsNotNone(trade_id)

        # سعر أقل من وقف الخسارة (-1.2%)
        sl_price = 60000.0 * 0.985  # 59,100 < الوقف 59,280
        with patch.object(self.engine, 'get_current_price', return_value=sl_price):
            events = self.engine.update_open_positions()

        self.assertTrue(len(events) > 0)
        state = self.engine.get_portfolio_state()
        self.assertEqual(state["open_trades_count"], 0)
        self.assertEqual(state["losses"], 1)


class TestTradingBotLive(unittest.TestCase):
    """اختبارات تتطلب اتصال حقيقي بالإنترنت — تُتخطى عند عدم التوفر"""

    @classmethod
    def setUpClass(cls):
        cls.test_db = os.path.join(os.path.dirname(__file__), "test_live.db")
        if os.path.exists(cls.test_db):
            try:
                os.remove(cls.test_db)
            except Exception:
                pass
        cls.engine = TradingEngine(db_path=cls.test_db)

    @classmethod
    def tearDownClass(cls):
        del cls.engine
        gc.collect()
        for f in [cls.test_db, cls.test_db + "-wal", cls.test_db + "-shm"]:
            if os.path.exists(f):
                try:
                    os.remove(f)
                except Exception:
                    pass

    def test_live_market_data(self):
        """اختبار جلب بيانات السوق الحية"""
        try:
            candles = self.engine.fetch_market_candles("BTC/USDT", timeframe="15m", limit=250)
        except Exception:
            self.skipTest("لا يتوفر اتصال بالإنترنت")
        
        if candles.empty:
            self.skipTest("لا يتوفر اتصال بالإنترنت أو المنصة معطلة")

        self.assertIn("rsi", candles.columns)
        self.assertIn("ema_50", candles.columns)
        self.assertIn("bb_upper", candles.columns)
        self.assertGreater(len(candles), 0)

    def test_live_price_fetch(self):
        """اختبار جلب السعر الحالي"""
        try:
            price = self.engine.get_current_price("BTC/USDT")
        except Exception:
            self.skipTest("لا يتوفر اتصال بالإنترنت")

        if price == 0.0:
            self.skipTest("لا يتوفر اتصال بالإنترنت أو المنصة معطلة")

        self.assertGreater(price, 0)


class TestUniversalFeatures(unittest.TestCase):
    """اختبارات الميزات الشاملة الجديدة: Universal AI و Exchange Tester و Background Worker"""

    def test_universal_ai_empty_url_handling(self):
        """التحقق من معالجة الرابط الفارغ في فاحص الذكاء الاصطناعي"""
        from universal_ai import UniversalAIClient
        res = UniversalAIClient.test_connection("", "", "model")
        self.assertFalse(res["success"])
        self.assertIn("error", res)

    def test_exchange_connection_empty_keys(self):
        """التحقق من رفض المفاتيح الفارغة في فاحص المنصات"""
        res = TradingEngine.test_exchange_connection("bybit", "", "")
        self.assertFalse(res["success"])
        self.assertIn("error", res)

    def test_worker_lifecycle(self):
        """اختبار دورة تشغيل وإيقاف عامل الخلفية"""
        from bot_worker import AutonomousTradingWorker
        worker = AutonomousTradingWorker.get_instance()
        self.assertFalse(worker.is_running())
        with patch.object(worker.engine, 'fetch_market_candles', return_value=pd.DataFrame()):
            worker.start()
            self.assertTrue(worker.is_running())
            worker.stop()
            self.assertFalse(worker.is_running())

    def test_telegram_notifier_empty_credentials(self):
        """التحقق من معالجة بيانات تيليجرام الفارغة بأمان"""
        from notifier import TelegramNotifier
        res = TelegramNotifier.test_connection("", "")
        self.assertFalse(res["success"])
        self.assertIn("error", res)

    def test_backtest_engine_on_mock_data(self):
        """اختبار محرك الاختبار الرجعي على بيانات وهمية"""
        from backtest import BacktestEngine
        df = _create_mock_candles(rows=80)
        res = BacktestEngine.run_backtest(df, pair="BTC/USDT", initial_balance=100.0, trade_amount=20.0)
        self.assertTrue(res["success"])
        self.assertIn("win_rate", res)
        self.assertIn("total_trades", res)
        self.assertIn("final_balance", res)

    def test_config_serialization_contains_indicators(self):
        """التحقق من حفظ حقول المؤشرات الفنية وتيليجرام في الإعدادات"""
        from config import TradingConfig
        cfg = TradingConfig()
        self.assertTrue(hasattr(cfg, "ema_fast"))
        self.assertTrue(hasattr(cfg, "bollinger_period"))
        self.assertTrue(hasattr(cfg, "telegram_enabled"))
        self.assertTrue(hasattr(cfg, "dashboard_password"))


class TestAgentsAndLiveFeatures(unittest.TestCase):
    """اختبارات الوكلاء الأذكياء الجدد وميزات البث المباشر واختيار العملات"""

    def setUp(self):
        self.engine = TradingEngine()

    def test_normalize_and_validate_pair_formats(self):
        """التحقق من تصحيح ومعالجة صيغ العملات المختلفة"""
        # test clean base symbol
        is_val, pair, _ = self.engine.normalize_and_validate_pair("btc")
        self.assertEqual(pair, "BTC/USDT")

        # test format without slash
        is_val, pair, _ = self.engine.normalize_and_validate_pair("dogeusdt")
        self.assertEqual(pair, "DOGE/USDT")

        # test standard format
        is_val, pair, _ = self.engine.normalize_and_validate_pair("SOL/USDT")
        self.assertEqual(pair, "SOL/USDT")

        # test empty input
        is_val, pair, msg = self.engine.normalize_and_validate_pair("")
        self.assertFalse(is_val)

    def test_get_available_spot_pairs(self):
        """التحقق من جلب قائمة أزواج التداول الفوري وأنها تحتوي على العملات الرئيسية"""
        pairs = self.engine.get_available_spot_pairs()
        self.assertIsInstance(pairs, list)
        self.assertGreater(len(pairs), 5)
        self.assertIn("BTC/USDT", pairs)
        self.assertIn("ETH/USDT", pairs)

    def test_market_opportunity_scanner_scoring(self):
        """اختبار وكيل اقتناص الفرص واحتساب الدرجات والتوصيات"""
        from market_scanner import MarketOpportunityScanner
        scanner = MarketOpportunityScanner(self.engine)

        # Mock candles for testing scanner without live network dependency
        mock_df = _create_mock_candles(rows=60)
        with patch.object(self.engine, 'fetch_market_candles', return_value=mock_df):
            results = scanner.scan_opportunities(pairs=["BTC/USDT", "ETH/USDT"], max_pairs=2)
            self.assertEqual(len(results), 2)
            for r in results:
                self.assertIn("pair", r)
                self.assertIn("score", r)
                self.assertIn("signal_arabic", r)
                self.assertIn("recommended_tp", r)
                self.assertIn("recommended_sl", r)
                self.assertGreaterEqual(r["score"], 0)
                self.assertLessEqual(r["score"], 100)

    def test_bybit_health_validator_structure(self):
        """اختبار وكيل التحقق من ربط بايبيت وهيكل التقرير التشخيصي"""
        from bybit_health_agent import BybitHealthValidatorAgent
        # Test API permissions check with empty keys (Paper Mode)
        perm_res = BybitHealthValidatorAgent.test_api_permissions("", "")
        self.assertEqual(perm_res["status"], "INFO")
        self.assertIn("Paper", perm_res["message"])

        # Test diagnostic report structure
        res = BybitHealthValidatorAgent.run_full_diagnostic("BTC/USDT")
        self.assertIn("overall_status", res)
        self.assertIn("overall_arabic", res)
        self.assertIn("overall_score", res)
        self.assertIn("checks", res)
        self.assertGreaterEqual(len(res["checks"]), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
