import os
import sys
import time
import sqlite3
import threading
import unittest
from unittest.mock import MagicMock, patch

# Ensure directories are in sys.path
root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
t4crte_dir = os.path.join(root_dir, "t4crte")
for d in [root_dir, t4crte_dir]:
    if d not in sys.path:
        sys.path.insert(0, d)

from config import config
from trading_engine import TradingEngine


class TestCommandsAndConcurrency(unittest.TestCase):
    def setUp(self):
        self.test_db = os.path.join(os.path.dirname(__file__), "test_commands.db")
        for f in [self.test_db, self.test_db + "-wal", self.test_db + "-shm"]:
            if os.path.exists(f):
                try:
                    os.remove(f)
                except Exception:
                    pass
        self.engine = TradingEngine(db_path=self.test_db)

    def tearDown(self):
        del self.engine
        for f in [self.test_db, self.test_db + "-wal", self.test_db + "-shm"]:
            if os.path.exists(f):
                try:
                    os.remove(f)
                except Exception:
                    pass

    def test_open_command_execution(self):
        """أدرج أمر OPEN عبر دالة الواجهة، شغّل دالة معالجة الأوامر مع engine مزيف (mock) -> status == 'DONE' وopen_position استُدعي مرة واحدة بالضبط."""
        # Insert OPEN command
        cmd_id = self.engine.add_command('OPEN', pair='BTC/USDT', amount_usdt=10.0)
        self.assertIsNotNone(cmd_id)

        # Mock open_position and get_current_price
        self.engine.open_position = MagicMock(return_value=(101, "تم فتح الصفقة بنجاح"))
        self.engine.get_current_price = MagicMock(return_value=50000.0)

        # Execute process_pending_commands
        results = self.engine.process_pending_commands()

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['status'], 'DONE')
        self.engine.open_position.assert_called_once_with('BTC/USDT', 50000.0, 10.0, is_paper=config.is_paper_trading)

        # Verify command status in DB is no longer pending
        pending = self.engine.get_pending_commands()
        self.assertEqual(len(pending), 0)

    def test_race_condition_concurrent_writes(self):
        """اختبار السباق: شغّل 5 خيوط تكتب صفقات في DB بالتوازي 50 مرة -> لا استثناء database is locked وعدد الصفوف = 250."""
        errors = []

        def worker_task(thread_id):
            for i in range(50):
                try:
                    with self.engine._lock:
                        with self.engine._db_connection() as conn:
                            cursor = conn.cursor()
                            now = "2025-01-01 00:00:00"
                            cursor.execute("""
                                INSERT INTO trades (
                                    pair, side, entry_price, current_price, amount, cost, highest_price,
                                    trailing_stop_price, take_profit_price, stop_loss_price, status, entry_time
                                ) VALUES ('BTC/USDT', 'BUY', 100.0, 100.0, 1.0, 100.0, 100.0, 95.0, 105.0, 95.0, 'OPEN', ?)
                            """, (now,))
                            conn.commit()
                except Exception as e:
                    errors.append(e)

        threads = []
        for t_idx in range(5):
            t = threading.Thread(target=worker_task, args=(t_idx,))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        self.assertEqual(len(errors), 0, f"حدثت أخطاء أثناء الكتابة المتوازية: {errors}")

        with self.engine._db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM trades")
            count = cursor.fetchone()[0]

        self.assertEqual(count, 250)

    def test_candle_cache(self):
        """اختبار الكاش: mock لـ fetch_ohlcv واستدعِ fetch_market_candles مرتين خلال ثانية -> fetch_ohlcv استُدعي مرة واحدة."""
        mock_exchange = MagicMock()
        fake_ohlcv = [
            [1700000000000, 100.0, 105.0, 99.0, 102.0, 10.0],
            [1700000900000, 102.0, 106.0, 101.0, 104.0, 12.0],
        ]
        mock_exchange.fetch_ohlcv.return_value = fake_ohlcv
        self.engine._exchange = mock_exchange

        # Call fetch_market_candles first time
        df1 = self.engine.fetch_market_candles('BTC/USDT', timeframe='15m', limit=250)
        self.assertFalse(df1.empty)

        # Call fetch_market_candles second time within 1 second
        df2 = self.engine.fetch_market_candles('BTC/USDT', timeframe='15m', limit=250)
        self.assertFalse(df2.empty)

        # Verify fetch_ohlcv was called exactly once due to cache hit
        mock_exchange.fetch_ohlcv.assert_called_once_with('BTC/USDT', timeframe='15m', limit=250)


if __name__ == "__main__":
    unittest.main(verbosity=2)
