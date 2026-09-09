import os
import sqlite3
import datetime
import json
import threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Any


@dataclass
class RiskConfig:
    risk_per_trade_pct: float = 1.0      # نسبة الرصيد المخاطر بها لكل صفقة
    max_open_positions: int = 2
    daily_loss_limit_pct: float = 3.0
    max_consecutive_losses: int = 3
    pair_cooldown_minutes: int = 60      # بعد خسارة على زوج
    max_api_errors_per_hour: int = 10


def position_size_usdt(
    equity: float,
    entry: float,
    stop: float,
    cfg: RiskConfig,
    rules: Any = None,
    symbol: str = "BTC/USDT"
) -> Tuple[float, str]:
    """
    حساب حجم الصفقة بالـ USDT بناءً على المخاطرة المسموحة ومسافة وقف الخسارة.
    يرجع (notional, "ok") أو (0.0, "سبب الرفض")
    """
    if entry <= 0 or stop >= entry:
        return 0.0, "وقف غير صالح"

    stop_distance_pct = (entry - stop) / entry
    if stop_distance_pct <= 0:
        return 0.0, "وقف غير صالح"

    risk_usdt = equity * (cfg.risk_per_trade_pct / 100.0)
    notional = risk_usdt / stop_distance_pct
    notional = min(notional, equity * 0.5)  # لا أكثر من نصف الرصيد

    min_c = 5.0
    if rules is not None and hasattr(rules, 'min_cost'):
        try:
            min_c = rules.min_cost(symbol)
        except Exception:
            min_c = 5.0

    if notional < min_c:
        return 0.0, "أقل من الحد الأدنى للمنصة"

    return round(notional, 4), "ok"


class RiskManager:
    _lock = threading.RLock()

    def __init__(self, cfg: Optional[RiskConfig] = None, db_path: Optional[str] = None):
        self.cfg = cfg or RiskConfig()
        if db_path is None:
            try:
                from config import config
                db_path = config.db_path
            except Exception:
                db_path = os.path.join(os.path.dirname(__file__), "trading_data.db")
        self.db_path = db_path

        self.consecutive_losses: int = 0
        self.today_realized_pnl_pct: float = 0.0
        self.last_reset_date: str = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
        self.last_loss_time_by_pair: Dict[str, str] = {}
        self.api_errors_last_hour: List[str] = []
        self.kill_switch: bool = False

        self._init_db()
        self.load_state()

    def _get_connection(self):
        conn = sqlite3.connect(self.db_path, timeout=10, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self):
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS risk_state (
                        id INTEGER PRIMARY KEY,
                        consecutive_losses INTEGER DEFAULT 0,
                        today_realized_pnl_pct REAL DEFAULT 0.0,
                        today_date TEXT,
                        last_loss_time_by_pair TEXT,
                        api_errors_json TEXT,
                        kill_switch INTEGER DEFAULT 0,
                        updated_at TEXT
                    )
                """)
                conn.commit()

    def save_state(self):
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()
                cursor.execute("""
                    INSERT OR REPLACE INTO risk_state (
                        id, consecutive_losses, today_realized_pnl_pct, today_date,
                        last_loss_time_by_pair, api_errors_json, kill_switch, updated_at
                    ) VALUES (1, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    self.consecutive_losses,
                    self.today_realized_pnl_pct,
                    self.last_reset_date,
                    json.dumps(self.last_loss_time_by_pair),
                    json.dumps(self.api_errors_last_hour),
                    1 if self.kill_switch else 0,
                    now_str
                ))
                conn.commit()

    def load_state(self):
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT consecutive_losses, today_realized_pnl_pct, today_date,
                           last_loss_time_by_pair, api_errors_json, kill_switch
                    FROM risk_state WHERE id = 1
                """)
                row = cursor.fetchone()
                if row:
                    self.consecutive_losses = row[0] or 0
                    self.today_realized_pnl_pct = row[1] or 0.0
                    self.last_reset_date = row[2] or datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
                    try:
                        self.last_loss_time_by_pair = json.loads(row[3]) if row[3] else {}
                    except Exception:
                        self.last_loss_time_by_pair = {}
                    try:
                        self.api_errors_last_hour = json.loads(row[4]) if row[4] else []
                    except Exception:
                        self.api_errors_last_hour = []
                    self.kill_switch = bool(row[5])

    def _parse_time(self, t: Any) -> datetime.datetime:
        if isinstance(t, datetime.datetime):
            return t
        if isinstance(t, str):
            try:
                return datetime.datetime.fromisoformat(t)
            except Exception:
                pass
        return datetime.datetime.now(datetime.timezone.utc)

    def can_open(
        self,
        pair: str,
        now: datetime.datetime,
        state: Optional[Dict[str, Any]] = None
    ) -> Tuple[bool, str]:
        """
        التحقق من إمكانية فتح صفقة بناءً على القواعد والأولويات.
        يرفض بترتيب:
        1. kill_switch فعال
        2. حد يومي (daily loss limit)
        3. خسائر متتالية (max consecutive losses)
        4. تهدئة الزوج (pair cooldown)
        5. عدد الصفقات (max open positions)
        6. أخطاء API (max api errors per hour)
        """
        st = state or {}

        # Check UTC day change
        current_date_str = now.strftime("%Y-%m-%d") if isinstance(now, datetime.datetime) else datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
        if current_date_str != self.last_reset_date:
            self.reset_daily(now)

        # 1. Kill switch
        is_kill = st.get("kill_switch", st.get("kill_switch_active", self.kill_switch))
        if is_kill:
            return False, "kill_switch فعال"

        # 2. Daily Loss Limit
        today_pnl_pct = st.get("today_realized_pnl_pct", self.today_realized_pnl_pct)
        if today_pnl_pct <= -self.cfg.daily_loss_limit_pct:
            return False, "تجاوز الحد اليومي للخسارة"

        # 3. Max Consecutive Losses
        consec_losses = st.get("consecutive_losses", self.consecutive_losses)
        if consec_losses >= self.cfg.max_consecutive_losses:
            return False, "تجاوز حد الخسائر المتتالية"

        # 4. Pair Cooldown
        loss_dict = st.get("last_loss_time_by_pair", self.last_loss_time_by_pair)
        if pair in loss_dict and loss_dict[pair]:
            last_loss_dt = self._parse_time(loss_dict[pair])
            # calculate difference in minutes
            diff_mins = (now - last_loss_dt).total_seconds() / 60.0
            if diff_mins < self.cfg.pair_cooldown_minutes:
                return False, "الزوج في فترة التهدئة بعد الخسارة"

        # 5. Max Open Positions
        open_pos_count = st.get("open_positions_count", 0)
        max_pos = st.get("max_open_positions", self.cfg.max_open_positions)
        if open_pos_count >= max_pos:
            return False, "تجاوز الحد الأقصى للصفقات المفتوحة"

        # 6. API Errors
        api_errs = st.get("api_errors_last_hour", self.api_errors_last_hour)
        # Prune older than 1 hour (3600 seconds) relative to now
        valid_errs = []
        for err_time in api_errs:
            err_dt = self._parse_time(err_time)
            if (now - err_dt).total_seconds() <= 3600:
                valid_errs.append(err_time)

        if len(valid_errs) >= self.cfg.max_api_errors_per_hour:
            return False, "تجاوز حد أخطاء API في الساعة الأخيرة"

        return True, "ok"

    def on_trade_closed(
        self,
        pair: str,
        pnl_amount: float,
        now: datetime.datetime,
        pnl_pct: float = 0.0
    ):
        now_dt = self._parse_time(now)
        now_str = now_dt.isoformat()

        if pnl_amount < 0 or pnl_pct < 0:
            self.consecutive_losses += 1
            self.last_loss_time_by_pair[pair] = now_str
        elif pnl_amount > 0 or pnl_pct > 0:
            self.consecutive_losses = 0

        self.today_realized_pnl_pct += pnl_pct
        self.save_state()

    def on_api_error(self, now: datetime.datetime):
        now_dt = self._parse_time(now)
        now_str = now_dt.isoformat()
        self.api_errors_last_hour.append(now_str)

        # Prune errors older than 3600s
        self.api_errors_last_hour = [
            t for t in self.api_errors_last_hour
            if (now_dt - self._parse_time(t)).total_seconds() <= 3600
        ]
        self.save_state()

    def count_api_errors_last_hour(self, now: datetime.datetime) -> int:
        """
        عدد أخطاء API داخل الساعة الأخيرة (مع استبعاد الأخطاء الأقدم).
        يُستخدم لتفعيل الـ Kill Switch التلقائي عند تجاوز الحد المسموح.
        """
        now_dt = self._parse_time(now)
        with self._lock:
            return sum(
                1 for t in self.api_errors_last_hour
                if (now_dt - self._parse_time(t)).total_seconds() <= 3600
            )

    def reset_daily(self, now: datetime.datetime):
        now_dt = self._parse_time(now)
        self.today_realized_pnl_pct = 0.0
        self.last_reset_date = now_dt.strftime("%Y-%m-%d")
        self.save_state()

    def reset_all(self):
        """إعادة تعيين كامل حالة المدير (تُستخدم للاختبارات وإعادة الضبط)"""
        with self._lock:
            self.consecutive_losses = 0
            self.today_realized_pnl_pct = 0.0
            self.last_loss_time_by_pair = {}
            self.api_errors_last_hour = []
            self.kill_switch = False
            self.last_reset_date = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM risk_state")
                conn.commit()
