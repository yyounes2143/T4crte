"""
اختبارات وحدة لمحرك الاختبار الرجعي (Backtest Engine) وحساب الرسوم والـ Walk-Forward
"""

import os
import sys
import unittest
import pandas as pd
import numpy as np

# Ensure t4crte directory is in path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
t4crte_dir = os.path.join(project_root, "t4crte")
if t4crte_dir not in sys.path:
    sys.path.insert(0, t4crte_dir)

from indicators import add_all_indicators
from backtest import BacktestEngine, walk_forward
from strategy import generate_signal
from config import TradingConfig
from risk_manager import RiskConfig


class TestBacktestEngine(unittest.TestCase):
    """اختبارات محرك الاختبار الرجعي الواقعي"""

    def setUp(self):
        # Create baseline synthetic dataset (220 rows)
        timestamps = pd.date_range('2025-01-01', periods=220, freq='5min')
        closes = np.linspace(100.0, 150.0, 220)
        self.df_base = pd.DataFrame({
            'timestamp': [int(t.timestamp() * 1000) for t in timestamps],
            'datetime': timestamps,
            'open': closes - 0.1,
            'high': closes + 0.5,
            'low': closes - 0.5,
            'close': closes,
            'volume': [100.0] * 220
        })
        # Set row 208 low to cause a pullback trigger below ema_21
        self.df_base.loc[208, 'low'] = 144.0
        self.df_base = add_all_indicators(self.df_base)

        self.strategy_cfg = TradingConfig()
        self.strategy_cfg.min_rr = 0.5
        self.risk_cfg = RiskConfig(risk_per_trade_pct=1.0)

    def test_backtest_tp_hit_matches_manual_calculation(self):
        """اختبار صفقة ربح عند بلوغ الهدف والتحقق من تطابق الحساب اليدوي ± 1e-6"""
        df = self.df_base.copy()

        # Candle 210: open trade at 148.0 + slippage
        df.loc[210, 'open'] = 148.0
        df.loc[210, 'high'] = 149.0
        df.loc[210, 'low'] = 147.0
        df.loc[210, 'close'] = 140.0  # Prevent new signal at 211

        # Candle 211: hits Take Profit
        df.loc[211, 'open'] = 148.5
        df.loc[211, 'high'] = 155.0  # > tp (150.71)
        df.loc[211, 'low'] = 148.0  # > stop (143.40)
        df.loc[211, 'close'] = 140.0

        fee_pct = 0.001
        slippage_pct = 0.0005
        init_balance = 100.0

        res = BacktestEngine.run_backtest(
            df_ltf=df.iloc[:212],
            df_htf=df.iloc[:212],
            initial_balance=init_balance,
            fee_pct=fee_pct,
            slippage_pct=slippage_pct,
            risk_cfg=self.risk_cfg,
            strategy_cfg=self.strategy_cfg,
            pair='BTC/USDT'
        )

        self.assertTrue(res['success'])
        self.assertEqual(res['total_trades'], 1)
        self.assertEqual(res['win_count'], 1)

        # Signal generated at candle 209
        sig = generate_signal(df.iloc[:210], df.iloc[:210], fee_pct, slippage_pct, self.strategy_cfg)
        self.assertEqual(sig.action, "BUY")

        sig_entry = sig.entry
        sig_stop = sig.stop
        sig_tp = sig.take_profit

        actual_entry = 148.0 * (1.0 + slippage_pct)
        risk_usdt = init_balance * (self.risk_cfg.risk_per_trade_pct / 100.0)
        stop_dist_pct = (sig_entry - sig_stop) / sig_entry
        notional = risk_usdt / stop_dist_pct
        qty = notional / actual_entry

        entry_fee = notional * fee_pct
        exit_notional = qty * sig_tp
        exit_fee = exit_notional * fee_pct
        expected_pnl = exit_notional - notional - (entry_fee + exit_fee)

        self.assertAlmostEqual(res['net_pnl'], expected_pnl, delta=1e-6)

    def test_backtest_sl_hit(self):
        """اختبار صفقة خاسرة عند ضرب وقف الخسارة والتحقق من net_pnl < 0"""
        df = self.df_base.copy()

        # Candle 210: open trade at 148.0
        df.loc[210, 'open'] = 148.0
        df.loc[210, 'high'] = 149.0
        df.loc[210, 'low'] = 147.0
        df.loc[210, 'close'] = 140.0

        # Candle 211: drops to hit Stop Loss
        df.loc[211, 'open'] = 148.0
        df.loc[211, 'high'] = 148.5
        df.loc[211, 'low'] = 140.0  # < stop (143.40)
        df.loc[211, 'close'] = 140.0

        res = BacktestEngine.run_backtest(
            df_ltf=df.iloc[:212],
            df_htf=df.iloc[:212],
            initial_balance=100.0,
            fee_pct=0.001,
            slippage_pct=0.0005,
            risk_cfg=self.risk_cfg,
            strategy_cfg=self.strategy_cfg,
            pair='BTC/USDT'
        )

        self.assertTrue(res['success'])
        self.assertEqual(res['total_trades'], 1)
        self.assertEqual(res['loss_count'], 1)
        self.assertLess(res['net_pnl'], 0)

    def test_both_sl_and_tp_hit_same_candle(self):
        """شمعة تلمس Stop و TP معاً -> تُحسب كخسارة (الافتراض المتشائم)"""
        df = self.df_base.copy()

        # Candle 210: open trade
        df.loc[210, 'open'] = 148.0
        df.loc[210, 'high'] = 149.0
        df.loc[210, 'low'] = 147.0
        df.loc[210, 'close'] = 140.0

        # Candle 211: touches both SL (140.0) and TP (155.0)
        df.loc[211, 'open'] = 148.0
        df.loc[211, 'high'] = 155.0  # > tp
        df.loc[211, 'low'] = 140.0   # < stop
        df.loc[211, 'close'] = 145.0

        res = BacktestEngine.run_backtest(
            df_ltf=df.iloc[:212],
            df_htf=df.iloc[:212],
            initial_balance=100.0,
            fee_pct=0.001,
            slippage_pct=0.0005,
            risk_cfg=self.risk_cfg,
            strategy_cfg=self.strategy_cfg,
            pair='BTC/USDT'
        )

        self.assertTrue(res['success'])
        self.assertEqual(res['total_trades'], 1)
        self.assertEqual(res['loss_count'], 1)
        self.assertLess(res['net_pnl'], 0)
        self.assertIn("وقف الخسارة", res['trades'][0]['reason'])

    def test_no_future_leakage(self):
        """اختبار عدم تسرب المستقبل: تعديل شمعة في المستقبل لا يغير إشارة أو قرار الدخول عند i"""
        df_orig = self.df_base.copy()

        # Signal index i = 210
        sig_orig = generate_signal(df_orig.iloc[:210], df_orig.iloc[:210], 0.001, 0.0005, self.strategy_cfg)

        # Modify a future candle at index 215
        df_mod = df_orig.copy()
        df_mod.loc[215, 'close'] = 99999.0
        df_mod.loc[215, 'high'] = 100000.0

        sig_mod = generate_signal(df_mod.iloc[:210], df_mod.iloc[:210], 0.001, 0.0005, self.strategy_cfg)

        self.assertEqual(sig_orig.action, sig_mod.action)
        self.assertEqual(sig_orig.entry, sig_mod.entry)
        self.assertEqual(sig_orig.stop, sig_mod.stop)
        self.assertEqual(sig_orig.take_profit, sig_mod.take_profit)

    def test_walk_forward_warning_on_unstable_strategy(self):
        """اختبار تحذير Walk-Forward عند الخسارة في أكثر من نصف الأجزاء"""
        df = self.df_base.copy()
        # Force consecutive losing trades across splits
        df['close'] = np.linspace(150.0, 50.0, len(df))
        df['open'] = df['close'] + 0.1
        df['high'] = df['open'] + 0.5
        df['low'] = df['close'] - 0.5
        df = add_all_indicators(df)

        wf_res = walk_forward(
            df_ltf=df,
            df_htf=df,
            n_splits=4,
            initial_balance=100.0,
            fee_pct=0.001,
            slippage_pct=0.0005,
            risk_cfg=self.risk_cfg,
            strategy_cfg=self.strategy_cfg,
            pair='BTC/USDT'
        )

        self.assertIn('unstable_warning', wf_res)
        self.assertEqual(len(wf_res['splits']), 4)


if __name__ == "__main__":
    unittest.main(verbosity=2)
