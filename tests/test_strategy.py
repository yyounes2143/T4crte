import os
import sys
import tempfile
import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "t4crte"))

from strategy import detect_regime, generate_signal, Signal
from indicators import add_all_indicators
from config import config, TradingConfig
from trading_engine import TradingEngine


def synth(trend_pct_per_bar: float, noise: float, n: int, start_price: float = 100.0) -> pd.DataFrame:
    np.random.seed(42)
    timestamps = [int((1700000000 + i * 900) * 1000) for i in range(n)]
    prices = [start_price]
    for i in range(1, n):
        change = prices[-1] * (trend_pct_per_bar / 100.0) + np.random.normal(0, noise)
        prices.append(max(0.01, prices[-1] + change))

    closes = np.array(prices)
    highs = closes + np.random.uniform(0.1, 0.5, n)
    lows = closes - np.random.uniform(0.1, 0.5, n)
    opens = closes + np.random.uniform(-0.2, 0.2, n)
    volumes = [1000.0] * n

    df = pd.DataFrame({
        'timestamp': timestamps,
        'open': opens,
        'high': highs,
        'low': lows,
        'close': closes,
        'volume': volumes
    })
    return add_all_indicators(df)


def test_htf_downtrend_no_trade():
    df_htf = synth(-0.1, 0.05, 250, start_price=200.0)
    regime = detect_regime(df_htf)
    assert regime == "NO_TRADE"

    df_ltf = synth(0.1, 0.05, 250, start_price=100.0)
    sig = generate_signal(df_ltf, df_htf, fee_pct=0.1, slippage_pct=0.05, cfg=config)

    assert sig.regime == "NO_TRADE"
    assert sig.action == "HOLD"


def test_htf_uptrend_ltf_pullback_buy_signal():
    df_htf = synth(0.2, 0.01, 250, start_price=50.0)
    regime = detect_regime(df_htf)
    assert regime == "TREND_UP"

    # LTF: trend up gently
    df_ltf = synth(0.05, 0.005, 250, start_price=100.0)

    last_idx = df_ltf.index[-1]
    prev_idx = df_ltf.index[-2]

    ema_21_prev = float(df_ltf.loc[prev_idx, 'ema_21'])
    ema_50_last = float(df_ltf.loc[last_idx, 'ema_50'])
    ema_9_last = float(df_ltf.loc[last_idx, 'ema_9'])

    # prev.low dips slightly below ema_21_prev
    df_ltf.loc[prev_idx, 'low'] = ema_21_prev - 0.1
    df_ltf.loc[prev_idx, 'close'] = ema_21_prev + 0.1

    # last close > ema_50 and ema_9
    entry_p = max(ema_50_last, ema_9_last) + 0.2
    df_ltf.loc[last_idx, 'close'] = entry_p
    df_ltf.loc[last_idx, 'high'] = entry_p + 0.2
    df_ltf.loc[last_idx, 'low'] = entry_p - 0.1
    df_ltf.loc[last_idx, 'atr'] = 1.0  # Set ATR to 1.0 so reward = 2.5*1.0 = 2.5

    # Ensure lowest 5 low is prev.low (ema_21_prev - 0.1)
    for idx in range(-5, -2):
        df_ltf.loc[df_ltf.index[idx], 'low'] = ema_21_prev

    sig = generate_signal(df_ltf, df_htf, fee_pct=0.1, slippage_pct=0.05, cfg=config)

    assert sig.regime == "TREND_UP"
    assert sig.action == "BUY"
    assert sig.stop < sig.entry < sig.take_profit
    assert sig.rr >= 1.5


def test_htf_range_ltf_bounce_buy_signal():
    np.random.seed(10)
    n = 250
    timestamps = [int((1700000000 + i * 3600) * 1000) for i in range(n)]
    closes = np.full(n, 100.0)
    closes[:240] += np.random.uniform(-0.5, 0.5, 240)
    closes[240:] += np.random.uniform(-0.01, 0.01, 10)

    highs = closes + 0.2
    lows = closes - 0.2
    highs[240:] = closes[240:] + 0.02
    lows[240:] = closes[240:] - 0.02

    df_htf = pd.DataFrame({
        'timestamp': timestamps,
        'open': closes,
        'high': highs,
        'low': lows,
        'close': closes,
        'volume': [1000.0] * n
    })
    df_htf = add_all_indicators(df_htf)

    regime = detect_regime(df_htf)
    assert regime == "RANGE"

    df_ltf = synth(0.0, 0.05, 250, start_price=100.0)

    bb_low_prev = float(df_ltf.iloc[-2]['bb_lower'])

    df_ltf.loc[df_ltf.index[-2], 'close'] = bb_low_prev - 0.2
    df_ltf.loc[df_ltf.index[-2], 'low'] = bb_low_prev - 0.4
    df_ltf.loc[df_ltf.index[-2], 'rsi'] = 25.0

    entry_p = bb_low_prev + 0.1
    df_ltf.loc[df_ltf.index[-1], 'close'] = entry_p
    df_ltf.loc[df_ltf.index[-1], 'high'] = entry_p + 0.2
    df_ltf.loc[df_ltf.index[-1], 'low'] = entry_p - 0.1
    df_ltf.loc[df_ltf.index[-1], 'rsi'] = 35.0
    df_ltf.loc[df_ltf.index[-1], 'volume_ratio'] = 1.2
    df_ltf.loc[df_ltf.index[-1], 'bb_middle'] = entry_p + 2.0

    sig = generate_signal(df_ltf, df_htf, fee_pct=0.1, slippage_pct=0.05, cfg=config)
    assert sig.regime == "RANGE"
    assert sig.action == "BUY"

    # Liquidity Filter Test (volume_ratio = 0.5)
    df_ltf.loc[df_ltf.index[-1], 'volume_ratio'] = 0.5
    sig_low_vol = generate_signal(df_ltf, df_htf, fee_pct=0.1, slippage_pct=0.05, cfg=config)
    assert sig_low_vol.action == "HOLD"
    assert any("السيولة" in r or "volume_ratio" in r for r in sig_low_vol.reasons)

    # Fee Filter Test (fee_pct = 1.0)
    df_ltf.loc[df_ltf.index[-1], 'volume_ratio'] = 1.2
    sig_high_fee = generate_signal(df_ltf, df_htf, fee_pct=1.0, slippage_pct=0.05, cfg=config)
    assert sig_high_fee.action == "HOLD"
    assert any("الرسوم" in r for r in sig_high_fee.reasons)


def test_atr_trailing_stop_simulation():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_file = os.path.join(tmpdir, "test_trading.db")
        engine = TradingEngine(db_path=db_file)
        engine.reset_paper_balance(20.0)

        trade_id, msg = engine.open_position(
            pair="BTC/USDT",
            current_price=100.0,
            amount_usdt=10.0,
            is_paper=True,
            stop_loss=95.0,
            take_profit=110.0,
            atr_at_entry=1.0
        )
        assert trade_id is not None

        def get_trade():
            trades = engine.get_open_trades()
            return trades[0] if trades else None

        t0 = get_trade()
        entry_fill_price = t0['entry_price']

        engine._price_cache["BTC/USDT"] = (1e10, 100.0)
        engine.update_open_positions()
        t = get_trade()
        assert t['highest_price'] == entry_fill_price
        assert t['trailing_stop_price'] == 95.0

        engine._price_cache["BTC/USDT"] = (1e10, 100.5)
        engine.update_open_positions()
        t = get_trade()
        assert t['highest_price'] == 100.5
        assert t['trailing_stop_price'] == 95.0

        engine._price_cache["BTC/USDT"] = (1e10, 101.05)
        engine.update_open_positions()
        t = get_trade()
        assert t['highest_price'] == 101.05
        assert t['trailing_stop_price'] == 100.05

        engine._price_cache["BTC/USDT"] = (1e10, 102.05)
        engine.update_open_positions()
        t = get_trade()
        assert t['highest_price'] == 102.05
        assert t['trailing_stop_price'] == 101.05

        engine._price_cache["BTC/USDT"] = (1e10, 101.55)
        engine.update_open_positions()
        t = get_trade()
        assert t['highest_price'] == 102.05
        assert t['trailing_stop_price'] == 101.05
        assert t['status'] == 'OPEN'
