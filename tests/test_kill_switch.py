"""
اختبارات انحدار (Regression) للإصلاحات الحرجة:
- حماية الإغلاق بسعر 0 (ورقي): تجاهل الإغلاق بدل خسارة وهمية
- execute_kill_switch: إغلاق عند آخر سعر معروف + قفل فتح الصفقات + إشعار
- count_api_errors_last_hour: ععداد نافذة ساعة (للكيل التلقائي)
- scan_opportunities: دعم stop_event (إصلاح كسر المسح الدوري في الـ worker)
"""
import os
import sys
import math
import datetime
import threading
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "t4crte"))

import pandas as pd
import pytest

from trading_engine import TradingEngine
from indicators import add_all_indicators


@pytest.fixture
def engine(tmp_path):
    db_file = str(tmp_path / "test_kill.db")
    eng = TradingEngine(db_path=db_file)
    # منصة وهمية (paper) بدون أي اتصال حقيقي
    mock_exchange = MagicMock()
    fake_markets = {
        "BTC/USDT": {
            "spot": True,
            "quote": "USDT",
            "active": True,
            "limits": {"cost": {"min": 5.0}, "amount": {"min": 0.001}},
            "taker": 0.001,
        }
    }
    mock_exchange.load_markets.return_value = fake_markets
    mock_exchange.markets = fake_markets
    mock_exchange.amount_to_precision.side_effect = (
        lambda symbol, amount: f"{math.floor(float(amount) * 1000) / 1000:.3f}"
    )
    mock_exchange.price_to_precision.side_effect = lambda symbol, price: f"{float(price):.2f}"
    eng._exchange = mock_exchange
    eng.exchange_rules.exchange = mock_exchange
    eng.exchange_rules.load()
    eng.reset_paper_balance(50.0)
    yield eng


def _open_paper(engine, price=100.0, amount_usdt=10.0):
    tid, msg = engine.open_position(
        "BTC/USDT", current_price=price, amount_usdt=amount_usdt, is_paper=True
    )
    assert tid is not None, msg
    return tid


def test_close_position_skipped_at_zero_price_paper(engine):
    """ورقي: محاولة إغلاق بسعر 0 يجب أن تتجاهل الإغلاق (لا خسارة وهمية 100%)"""
    tid = _open_paper(engine, price=100.0)
    engine.close_position(tid, exit_price=0.0, reason="Kill أثناء انقطاع")
    trades = engine.get_open_trades()
    assert len(trades) == 1
    assert trades[0]["id"] == tid


def test_execute_kill_switch_closes_at_last_known_price(engine):
    """Kill Switch بدون سعر متاح: يُغلق عند آخر سعر معروف من DB (وليس 0) ويُقفل الفتح"""
    tid = _open_paper(engine, price=100.0)
    # محاكاة انقطاع الشبكة: جلب السعر يفشل (0)
    engine.get_current_price = MagicMock(return_value=0.0)
    closed = engine.execute_kill_switch("اختبار kill switch")
    assert closed == 1
    assert engine.risk_manager.kill_switch is True

    assert len(engine.get_open_trades()) == 0
    hist = engine.get_trade_history(limit=1)
    assert len(hist) == 1
    # سعر الخروج يجب أن يكون آخر سعر معروف (~100) وليس 0
    assert hist[0]["exit_price"] > 50.0
    # الخسارة يجب أن تكون صغيرة (رسوم + انزلاق) وليست خسارة كاملة
    assert hist[0]["pnl_amount"] > -5.0


def test_kill_switch_blocks_new_opens(engine):
    """بعد تفعيل الـ Kill Switch: يُرفض فتح أي صفقة جديدة"""
    engine.execute_kill_switch("اختبار قفل الفتح")
    tid, msg = engine.open_position(
        "BTC/USDT", current_price=100.0, amount_usdt=10.0, is_paper=True
    )
    assert tid is None
    assert "kill_switch" in msg


def test_count_api_errors_last_hour(engine):
    """العداد يحسب فقط أخطاء الساعة الأخيرة (الأقدم تُستبعد)"""
    rm = engine.risk_manager
    now = datetime.datetime.now(datetime.timezone.utc)
    assert rm.count_api_errors_last_hour(now) == 0
    rm.on_api_error(now)
    rm.on_api_error(now - datetime.timedelta(hours=2))  # خارج النافذة
    assert rm.count_api_errors_last_hour(now) == 1


def _mock_candles() -> pd.DataFrame:
    rows = 60
    closes = [100.0] * rows
    df = pd.DataFrame(
        {
            "timestamp": [int((1700000000 + i * 900) * 1000) for i in range(rows)],
            "open": closes,
            "high": [c + 0.5 for c in closes],
            "low": [c - 0.5 for c in closes],
            "close": closes,
            "volume": [1000.0] * rows,
        }
    )
    return add_all_indicators(df)


def test_scanner_accepts_stop_event(engine):
    """إصلاح: scan_opportunities تقبل stop_event وتتوقف عند إشارته (كانت ترمي TypeError)"""
    from market_scanner import MarketOpportunityScanner

    scanner = MarketOpportunityScanner(engine)
    engine.fetch_market_candles = MagicMock(return_value=_mock_candles())

    # 1) استدعاء عادي مع stop_event=None (كيفية استدعاء الواجهة)
    res = scanner.scan_opportunities(pairs=["BTC/USDT"], max_pairs=1, stop_event=None)
    assert len(res) == 1

    # 2) مع stop_event مُفعّل: يتوقف المسح فوراً بدون نتائج
    stop = threading.Event()
    stop.set()
    res2 = scanner.scan_opportunities(
        pairs=["BTC/USDT", "ETH/USDT"], max_pairs=2, stop_event=stop
    )
    assert len(res2) == 0
