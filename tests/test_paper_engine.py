import os
import sys
import math
import unittest
from unittest.mock import patch, MagicMock

# Ensure t4crte directory is in python path
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "t4crte"))

from config import config
from trading_engine import TradingEngine


class TestPaperEngineSimulation(unittest.TestCase):
    """اختبارات المحاكاة الواقعية للمحرك التجريبي (الرسوم، الانزلاق، الحد الأدنى، والدقة)"""

    @classmethod
    def setUpClass(cls):
        cls.test_db = os.path.join(os.path.dirname(__file__), "test_paper_engine.db")
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
        for f in [cls.test_db, cls.test_db + "-wal", cls.test_db + "-shm"]:
            if os.path.exists(f):
                try:
                    os.remove(f)
                except Exception:
                    pass

    def setUp(self):
        """تهيئة الموك والبيانات لكل اختبار"""
        self.engine.reset_paper_balance(20.0)

        # إنشاء كائن MagicMock يمثل المنصة بكافة الخصائص المطلوبة
        self.mock_exchange = MagicMock()
        fake_markets = {
            "BTC/USDT": {
                "symbol": "BTC/USDT",
                "limits": {
                    "cost": {"min": 5.0},
                    "amount": {"min": 0.001}
                },
                "precision": {
                    "amount": 0.001,
                    "price": 0.01
                },
                "taker": 0.001,
                "spot": True,
                "quote": "USDT",
                "active": True
            }
        }
        self.mock_exchange.load_markets.return_value = fake_markets
        self.mock_exchange.markets = fake_markets

        # تقريب الكمية والسعر بناءً على دقة المنصة المخترعة (3 خانات للكمية)
        def mock_amount_to_precision(symbol, amount):
            val = math.floor(float(amount) * 1000) / 1000.0
            return f"{val:.3f}"

        def mock_price_to_precision(symbol, price):
            return f"{float(price):.2f}"

        self.mock_exchange.amount_to_precision.side_effect = mock_amount_to_precision
        self.mock_exchange.price_to_precision.side_effect = mock_price_to_precision

        # ربط الموك بمحرك التداول
        self.engine._exchange = self.mock_exchange
        self.engine.exchange_rules.exchange = self.mock_exchange
        self.engine.exchange_rules.load()

    def test_open_position_rejected_under_min_cost(self):
        """فتح صفقة بـ 2$ على سوق حده الأدنى 5$ → يُرفض ولا يتغير الرصيد"""
        initial_balance = self.engine.get_portfolio_state()["usdt_balance"]

        trade_id, msg = self.engine.open_position("BTC/USDT", current_price=100.0, amount_usdt=2.0, is_paper=True)

        self.assertIsNone(trade_id)
        self.assertIn("أقل من الحد الأدنى للتكلفة", msg)

        after_balance = self.engine.get_portfolio_state()["usdt_balance"]
        self.assertEqual(initial_balance, after_balance)

    def test_open_position_success_math_and_precision(self):
        """فتح صفقة بـ 10$ عند 100: entry_price == 100.05، amount == 0.099، خصم الرصيد بـ 0.099*100.05*1.001"""
        initial_balance = self.engine.get_portfolio_state()["usdt_balance"]  # 20.0

        trade_id, msg = self.engine.open_position("BTC/USDT", current_price=100.0, amount_usdt=10.0, is_paper=True)
        self.assertIsNotNone(trade_id)

        open_trades = self.engine.get_open_trades()
        self.assertEqual(len(open_trades), 1)
        trade = open_trades[0]

        # 1. entry_price == 100.0 * (1 + 0.05/100) = 100.05
        self.assertAlmostEqual(trade["entry_price"], 100.05, places=4)

        # 2. amount == round_amount("BTC/USDT", 10.0 / 100.05) == 0.099
        self.assertAlmostEqual(trade["amount"], 0.099, places=4)

        # 3. الرصيد ينقص بالضبط بمقدار: amount * fill_price * (1 + fee/100)
        expected_deduction = 0.099 * 100.05 * 1.001  # 9.91485495
        expected_balance = initial_balance - expected_deduction
        current_balance = self.engine.get_portfolio_state()["usdt_balance"]
        self.assertAlmostEqual(current_balance, round(expected_balance, 4), places=4)

    def test_close_position_at_same_price_negative_pnl(self):
        """إغلاق عند 100 (بدون حركة سعر): pnl_amount < 0 (الخسارة = رسوم + انزلاق فقط)"""
        trade_id, _ = self.engine.open_position("BTC/USDT", current_price=100.0, amount_usdt=10.0, is_paper=True)
        self.assertIsNotNone(trade_id)

        # إغلاق عند نفس السعر 100.0
        self.engine.close_position(trade_id, exit_price=100.0, reason="No move close")

        history = self.engine.get_trade_history(limit=1)
        self.assertEqual(len(history), 1)
        trade = history[0]

        # pnl_amount يجب أن يكون سالباً بسبب الرسوم والانزلاق
        self.assertLess(trade["pnl_amount"], 0.0)

    def test_close_position_at_higher_price_exact_pnl(self):
        """إغلاق عند 102: pnl_amount يساوي الحساب اليدوي ± 1e-6"""
        trade_id, _ = self.engine.open_position("BTC/USDT", current_price=100.0, amount_usdt=10.0, is_paper=True)
        self.assertIsNotNone(trade_id)

        self.engine.close_position(trade_id, exit_price=102.0, reason="Profit close")

        history = self.engine.get_trade_history(limit=1)
        self.assertEqual(len(history), 1)
        trade = history[0]

        # الحساب اليدوي:
        # entry_fill = 100.05
        # amount = 0.099
        # entry_fee = 0.099 * 100.05 * 0.001 = 0.00990495
        # exit_fill = 102.0 * (1 - 0.05/100) = 101.949
        # exit_fee = 0.099 * 101.949 * 0.001 = 0.010092951
        # gross_return = 0.099 * 101.949 - 0.010092951 = 10.082858049
        # total_entry_cost = 0.099 * 100.05 + 0.00990495 = 9.91485495
        # expected_pnl = gross_return - total_entry_cost = 0.168003099
        entry_total = 0.099 * 100.05 * 1.001
        exit_total = 0.099 * (102.0 * 0.9995) * (1 - 0.001)
        manual_pnl = exit_total - entry_total

        self.assertAlmostEqual(trade["pnl_amount"], manual_pnl, delta=1e-6)


if __name__ == "__main__":
    unittest.main(verbosity=2)
