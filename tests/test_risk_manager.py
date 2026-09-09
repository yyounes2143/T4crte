import pytest
import datetime
from risk_manager import RiskConfig, RiskManager, position_size_usdt


def test_position_size_usdt_nominal():
    cfg = RiskConfig(risk_per_trade_pct=1.0)
    # equity=100, entry=100, stop=98 -> risk=1$, distance=2%, notional=50$
    notional, msg = position_size_usdt(equity=100.0, entry=100.0, stop=98.0, cfg=cfg)
    assert notional == 50.0
    assert msg == "ok"


def test_position_size_usdt_under_min_cost():
    cfg = RiskConfig(risk_per_trade_pct=1.0)
    # equity=4, entry=100, stop=98 -> notional=2 < min_cost 5 -> (0, "أقل من الحد الأدنى")
    notional, msg = position_size_usdt(equity=4.0, entry=100.0, stop=98.0, cfg=cfg)
    assert notional == 0.0
    assert "أقل من الحد الأدنى" in msg


def test_position_size_usdt_invalid_stop():
    cfg = RiskConfig(risk_per_trade_pct=1.0)
    # stop >= entry
    notional, msg = position_size_usdt(equity=100.0, entry=100.0, stop=100.0, cfg=cfg)
    assert notional == 0.0
    assert "وقف غير صالح" in msg

    notional2, msg2 = position_size_usdt(equity=100.0, entry=100.0, stop=105.0, cfg=cfg)
    assert notional2 == 0.0
    assert "وقف غير صالح" in msg2


def test_can_open_daily_loss_limit(tmp_path):
    db_path = str(tmp_path / "test_risk.db")
    cfg = RiskConfig(daily_loss_limit_pct=3.0)
    rm = RiskManager(cfg=cfg, db_path=db_path)
    now = datetime.datetime.now(datetime.timezone.utc)

    # Losses accumulated to 3.1%
    rm.today_realized_pnl_pct = -3.1
    rm.save_state()

    can_open, reason = rm.can_open("BTC/USDT", now)
    assert can_open is False
    assert "الحد اليومي" in reason


def test_can_open_consecutive_losses_and_reset_on_win(tmp_path):
    db_path = str(tmp_path / "test_risk.db")
    cfg = RiskConfig(max_consecutive_losses=3)
    rm = RiskManager(cfg=cfg, db_path=db_path)
    now = datetime.datetime.now(datetime.timezone.utc)

    # 3 consecutive losses
    rm.on_trade_closed("BTC/USDT", pnl_amount=-10.0, now=now, pnl_pct=-1.0)
    rm.on_trade_closed("ETH/USDT", pnl_amount=-5.0, now=now, pnl_pct=-0.5)
    rm.on_trade_closed("SOL/USDT", pnl_amount=-2.0, now=now, pnl_pct=-0.2)

    assert rm.consecutive_losses == 3
    can_open, reason = rm.can_open("XRP/USDT", now)
    assert can_open is False
    assert "الخسائر المتتالية" in reason or "خسائر" in reason

    # Then 1 win -> counter resets to 0
    rm.on_trade_closed("XRP/USDT", pnl_amount=15.0, now=now, pnl_pct=1.5)
    assert rm.consecutive_losses == 0

    can_open2, reason2 = rm.can_open("XRP/USDT", now)
    assert can_open2 is True


def test_can_open_pair_cooldown(tmp_path):
    db_path = str(tmp_path / "test_risk.db")
    cfg = RiskConfig(pair_cooldown_minutes=60)
    rm = RiskManager(cfg=cfg, db_path=db_path)
    now = datetime.datetime.now(datetime.timezone.utc)
    loss_time = now - datetime.timedelta(minutes=30)  # Loss 30 minutes ago

    rm.on_trade_closed("BTC/USDT", pnl_amount=-5.0, now=loss_time, pnl_pct=-0.5)

    # False for BTC
    can_open_btc, reason_btc = rm.can_open("BTC/USDT", now)
    assert can_open_btc is False
    assert "التهدئة" in reason_btc or "تهدئة" in reason_btc

    # True for ETH
    can_open_eth, reason_eth = rm.can_open("ETH/USDT", now)
    assert can_open_eth is True


def test_reset_daily(tmp_path):
    db_path = str(tmp_path / "test_risk.db")
    cfg = RiskConfig(daily_loss_limit_pct=3.0, max_consecutive_losses=3)
    rm = RiskManager(cfg=cfg, db_path=db_path)
    now = datetime.datetime.now(datetime.timezone.utc)

    rm.today_realized_pnl_pct = -3.5
    rm.consecutive_losses = 2
    rm.save_state()

    next_day = now + datetime.timedelta(days=1)
    rm.reset_daily(next_day)

    # Daily loss reset to 0.0
    assert rm.today_realized_pnl_pct == 0.0
    # Other counters preserved
    assert rm.consecutive_losses == 2


def test_state_persistence_and_restoration(tmp_path):
    db_path = str(tmp_path / "test_risk.db")
    cfg = RiskConfig()
    rm1 = RiskManager(cfg=cfg, db_path=db_path)
    now = datetime.datetime.now(datetime.timezone.utc)

    rm1.on_trade_closed("BTC/USDT", pnl_amount=-10.0, now=now, pnl_pct=-1.5)
    rm1.on_trade_closed("ETH/USDT", pnl_amount=-5.0, now=now, pnl_pct=-0.5)
    rm1.on_api_error(now)

    assert rm1.consecutive_losses == 2
    assert rm1.today_realized_pnl_pct == -2.0
    assert "BTC/USDT" in rm1.last_loss_time_by_pair
    assert len(rm1.api_errors_last_hour) == 1

    # Create new instance pointing to same DB
    rm2 = RiskManager(cfg=cfg, db_path=db_path)

    # State restored successfully
    assert rm2.consecutive_losses == 2
    assert rm2.today_realized_pnl_pct == -2.0
    assert "BTC/USDT" in rm2.last_loss_time_by_pair
    assert len(rm2.api_errors_last_hour) == 1


def test_kill_switch_and_max_positions_and_api_errors(tmp_path):
    db_path = str(tmp_path / "test_risk.db")
    cfg = RiskConfig(max_open_positions=2, max_api_errors_per_hour=3)
    rm = RiskManager(cfg=cfg, db_path=db_path)
    now = datetime.datetime.now(datetime.timezone.utc)

    # Test Kill Switch
    rm.kill_switch = True
    rm.save_state()
    can_open, reason = rm.can_open("BTC/USDT", now)
    assert can_open is False
    assert "kill_switch" in reason.lower()

    rm.kill_switch = False
    rm.save_state()

    # Test Max Open Positions
    can_open_max, reason_max = rm.can_open("BTC/USDT", now, state={"open_positions_count": 2})
    assert can_open_max is False
    assert "المفتوحة" in reason_max

    # Test API Errors
    rm.on_api_error(now)
    rm.on_api_error(now)
    rm.on_api_error(now)
    can_open_err, reason_err = rm.can_open("BTC/USDT", now)
    assert can_open_err is False
    assert "API" in reason_err
