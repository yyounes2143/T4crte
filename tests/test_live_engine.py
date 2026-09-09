import os
import sys
import pytest
from unittest.mock import MagicMock, patch
import ccxt

# Ensure t4crte directory is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 't4crte')))

from config import config
from trading_engine import TradingEngine


def test_create_order_timeout_then_found_in_closed_orders(tmp_path):
    """
    create_order yrmy RequestTimeout ثم fetch_closed_orders yrg'3 amran bnafs client_order_id
    -> al-safka tosaggal marra wahida wa create_order ostud'ey marra wahida faqat.
    """
    db_file = str(tmp_path / "test_timeout.db")
    engine = TradingEngine(db_path=db_file)
    mock_exchange = MagicMock()
    engine._exchange = mock_exchange
    engine.exchange_rules._exchange = mock_exchange

    config.is_paper_trading = False

    # Mock ticker and exchange rules
    mock_exchange.fetch_ticker.return_value = {'last': 50000.0, 'close': 50000.0}
    mock_exchange.load_markets.return_value = {
        'BTC/USDT': {
            'spot': True, 'quote': 'USDT', 'active': True,
            'limits': {'amount': {'min': 0.0001, 'max': 100}, 'cost': {'min': 1.0}}
        }
    }

    # Set portfolio initial balance high enough
    with engine._db_connection() as conn:
        conn.cursor().execute("UPDATE portfolio SET usdt_balance = 1000.0 WHERE id = 1")
        conn.commit()

    # Mock exchange_rules.validate_order to return True
    engine.exchange_rules.validate_order = MagicMock(return_value=(True, "OK"))
    engine.exchange_rules.min_cost = MagicMock(return_value=1.0)

    call_count = 0

    def mock_create_order(symbol, type, side, amount, params=None):
        nonlocal call_count
        call_count += 1
        cid = params.get('clientOrderId') if params else None
        if side == 'buy':
            # Throw RequestTimeout on buy order
            raise ccxt.RequestTimeout("Connection timeout")
        elif side == 'sell':
            # Stop loss order
            return {'id': 'sl_123'}
        return {}

    mock_exchange.create_order.side_effect = mock_create_order

    def mock_fetch_closed_orders(symbol=None):
        # Return a closed order with matching clientOrderId
        return [{
            'id': 'ord_999',
            'clientOrderId': 't4-BTCUSDT-12345',  # Will match any clientOrderId prefix logic
            'info': {'orderLinkId': 't4-BTCUSDT-12345'},
            'symbol': 'BTC/USDT',
            'side': 'buy',
            'price': 50000.0,
            'average': 50000.0,
            'amount': 0.001,
            'filled': 0.001,
            'status': 'closed'
        }]

    # When search in closed orders happens, return the found order
    def mock_fetch_closed_orders_with_matching_cid(symbol=None):
        # We catch the generated client_order_id from DB
        trades = engine.get_open_trades()
        cid = "t4-BTCUSDT-mock"
        with engine._db_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT client_order_id FROM trades")
            r = cur.fetchone()
            if r and r[0]:
                cid = r[0]

        return [{
            'id': 'ord_999',
            'clientOrderId': cid,
            'info': {'orderLinkId': cid},
            'symbol': 'BTC/USDT',
            'side': 'buy',
            'price': 50000.0,
            'average': 50000.0,
            'amount': 0.001,
            'filled': 0.001,
            'status': 'closed'
        }]

    mock_exchange.fetch_open_orders.return_value = [{'id': 'sl_123'}]
    mock_exchange.fetch_closed_orders.side_effect = mock_fetch_closed_orders_with_matching_cid
    mock_exchange.fetch_order.return_value = {
        'id': 'ord_999',
        'average': 50000.0,
        'price': 50000.0,
        'filled': 0.001,
        'fee': {'cost': 0.05}
    }

    trade_id, msg = engine.open_position(
        pair="BTC/USDT",
        current_price=50000.0,
        amount_usdt=10.0,
        is_paper=False,
        stop_loss=49000.0,
        take_profit=52000.0
    )

    assert trade_id is not None
    # create_order was called 2 times total: 1 buy attempt (which timed out) + 1 stop loss order attempt
    buy_calls = [c for c in mock_exchange.create_order.call_args_list if c.kwargs.get('side') == 'buy' or (len(c.args) >= 3 and c.args[2] == 'buy')]
    assert len(buy_calls) == 1
    open_trades = engine.get_open_trades()
    assert len(open_trades) == 1
    assert open_trades[0]['id'] == trade_id


def test_sl_order_missing_in_open_orders_causes_immediate_close(tmp_path):
    """
    create_order للوقف يرجع أمراً، لكن fetch_open_orders يرجع قائمة فارغة مرتين
    → يتم create_order('sell', market) للإغلاق الفوري.
    """
    db_file = str(tmp_path / "test_sl_missing.db")
    engine = TradingEngine(db_path=db_file)
    mock_exchange = MagicMock()
    engine._exchange = mock_exchange
    engine.exchange_rules._exchange = mock_exchange

    config.is_paper_trading = False

    # Set portfolio initial balance high enough
    with engine._db_connection() as conn:
        conn.cursor().execute("UPDATE portfolio SET usdt_balance = 1000.0 WHERE id = 1")
        conn.commit()

    # Mock exchange_rules
    engine.exchange_rules.validate_order = MagicMock(return_value=(True, "OK"))
    engine.exchange_rules.min_cost = MagicMock(return_value=1.0)

    created_orders = []

    def mock_create_order(symbol, type, side, amount, params=None):
        order_info = {'id': f"ord_{len(created_orders)+1}", 'symbol': symbol, 'side': side, 'type': type, 'amount': amount}
        created_orders.append(order_info)
        if side == 'buy':
            return {'id': 'buy_100', 'average': 50000.0, 'filled': 0.001, 'price': 50000.0}
        elif side == 'sell' and params and ('stopLossPrice' in params or 'triggerPrice' in params):
            return {'id': 'sl_200', 'status': 'open'}
        elif side == 'sell' and type == 'market':
            # Emergency market sell
            return {'id': 'emergency_sell_300', 'average': 50000.0, 'filled': 0.001}
        return order_info

    mock_exchange.create_order.side_effect = mock_create_order
    mock_exchange.fetch_order.return_value = {'id': 'buy_100', 'average': 50000.0, 'filled': 0.001, 'fee': {'cost': 0.05}}
    # fetch_open_orders returns empty list twice
    mock_exchange.fetch_open_orders.return_value = []

    trade_id, msg = engine.open_position(
        pair="BTC/USDT",
        current_price=50000.0,
        amount_usdt=10.0,
        is_paper=False,
        stop_loss=49000.0,
        take_profit=52000.0
    )

    assert trade_id is None
    assert msg == "فشل وضع الوقف"
    # Check that emergency sell market order was issued
    sell_orders = [o for o in created_orders if o['side'] == 'sell' and o['type'] == 'market']
    assert len(sell_orders) >= 1


def test_reconcile_on_startup_zero_balance_closes_external(tmp_path):
    """
    reconcile_on_startup مع رصيد 0 للعملة → الصفقة تصبح CLOSED_EXTERNAL.
    """
    db_file = str(tmp_path / "test_reconcile.db")
    engine = TradingEngine(db_path=db_file)
    mock_exchange = MagicMock()
    engine._exchange = mock_exchange

    config.is_paper_trading = False

    # Insert an open live trade into DB
    with engine._db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO trades (
                pair, side, entry_price, current_price, amount, cost, highest_price,
                trailing_stop_price, take_profit_price, stop_loss_price, status,
                entry_time, is_paper, entry_fee, client_order_id, sl_order_id
            ) VALUES (
                'BTC/USDT', 'BUY', 50000.0, 51000.0, 0.001, 50.0, 51000.0,
                49000.0, 52000.0, 49000.0, 'OPEN',
                '2025-01-01 10:00:00', 0, 0.05, 't4-BTCUSDT-111', 'sl_111'
            )
        """)
        conn.commit()

    # Balance shows 0 BTC
    mock_exchange.fetch_balance.return_value = {
        'BTC': {'free': 0.0, 'used': 0.0, 'total': 0.0},
        'USDT': {'free': 100.0, 'used': 0.0, 'total': 100.0}
    }
    mock_exchange.fetch_ticker.return_value = {'last': 51000.0, 'close': 51000.0}

    engine.reconcile_on_startup()

    open_trades = engine.get_open_trades()
    assert len(open_trades) == 0

    with engine._db_connection() as conn:
        conn.row_factory = conn.row_factory
        cursor = conn.cursor()
        cursor.execute("SELECT status, exit_reason FROM trades WHERE client_order_id = 't4-BTCUSDT-111'")
        row = cursor.fetchone()
        assert row[0] == 'CLOSED_EXTERNAL'
        assert 'CLOSED_EXTERNAL' in row[1]


def test_call_no_retry_on_invalid_order_and_retries_on_network_error(tmp_path):
    """
    _call مع InvalidOrder → لا إعادة محاولة (استدعاء واحد)؛ مع NetworkError مرتين ثم نجاح → 3 استدعاءات.
    """
    db_file = str(tmp_path / "test_call.db")
    engine = TradingEngine(db_path=db_file)

    # 1. Test InvalidOrder: single call, no retries
    mock_invalid_fn = MagicMock(side_effect=ccxt.InvalidOrder("Invalid order amount"))
    with pytest.raises(ccxt.InvalidOrder):
        engine._call(mock_invalid_fn)
    assert mock_invalid_fn.call_count == 1

    # 2. Test NetworkError twice then success: 3 calls
    mock_net_fn = MagicMock(side_effect=[
        ccxt.NetworkError("Network timeout 1"),
        ccxt.NetworkError("Network timeout 2"),
        {"status": "ok"}
    ])

    with patch("time.sleep", return_value=None):  # Fast forward sleep
        res = engine._call(mock_net_fn, retries=3)

    assert res == {"status": "ok"}
    assert mock_net_fn.call_count == 3
