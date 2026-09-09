import os
import sqlite3
import datetime
import json
import time
import functools
import ccxt
import pandas as pd
from typing import List, Dict, Any, Optional, Tuple
from contextlib import contextmanager
from config import config
from indicators import TechnicalIndicators
from ai_advisor import AIAdvisor, AIAnalysisResult
from logger import setup_logger
from exchange_rules import ExchangeRules

logger = setup_logger("engine", log_file="trading.log")


def _retry_on_network_error(max_retries: int = 3, base_delay: float = 2.0):
    """مُزيِّن لإعادة المحاولة عند أخطاء الشبكة مع تراجع أُسّي"""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(1, max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except (ccxt.NetworkError, ccxt.RequestTimeout, ccxt.ExchangeNotAvailable) as e:
                    if attempt == max_retries:
                        logger.error(f"فشل {func.__name__} بعد {max_retries} محاولات: {e}")
                        raise
                    delay = base_delay * (2 ** (attempt - 1))
                    logger.warning(
                        f"خطأ شبكة في {func.__name__} (المحاولة {attempt}/{max_retries}): {e}. "
                        f"إعادة المحاولة بعد {delay:.1f} ثانية..."
                    )
                    time.sleep(delay)
                except ccxt.RateLimitExceeded as e:
                    if attempt == max_retries:
                        logger.error(f"تجاوز حد الطلبات في {func.__name__}: {e}")
                        raise
                    delay = base_delay * (2 ** attempt)  # تراجع أطول لـ Rate Limit
                    logger.warning(f"تجاوز حد الطلبات. انتظار {delay:.1f} ثانية...")
                    time.sleep(delay)
            return None
        return wrapper
    return decorator


POPULAR_PAIRS = [
    "BTC/USDT", "ETH/USDT", "SOL/USDT", "XRP/USDT", "DOGE/USDT",
    "ADA/USDT", "PEPE/USDT", "SUI/USDT", "AVAX/USDT", "LINK/USDT",
    "NEAR/USDT", "SHIB/USDT", "DOT/USDT", "LTC/USDT", "BCH/USDT",
    "APT/USDT", "ARB/USDT", "OP/USDT", "INJ/USDT", "RENDER/USDT",
    "FET/USDT", "TIA/USDT", "SEI/USDT", "GALA/USDT", "POL/USDT"
]


class TradingEngine:
    def __init__(self, db_path: str = None):
        self.db_path = db_path or config.db_path
        self._cached_spot_pairs: List[str] = []
        self._last_spot_pairs_time: float = 0
        self.init_db()
        self._exchange = None
        self._init_exchange()

    @contextmanager
    def _db_connection(self):
        """مدير سياق آمن لفتح وإغلاق اتصالات SQLite مع وضع WAL"""
        conn = sqlite3.connect(self.db_path, timeout=10)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=5000")
            yield conn
        finally:
            conn.close()

    def _init_exchange(self):
        """تهيئة الاتصال بالمنصة لجلب بيانات الأسعار الحية"""
        try:
            exchange_class = getattr(ccxt, config.exchange_id, ccxt.bybit)
            options = {
                'enableRateLimit': True,
                'timeout': 15000,
            }
            if not config.is_paper_trading and config.api_key and config.api_secret:
                options['apiKey'] = config.api_key
                options['secret'] = config.api_secret
                if config.api_passphrase:
                    options['password'] = config.api_passphrase
            
            self._exchange = exchange_class(options)
            logger.info(f"تم تهيئة الاتصال بمنصة {config.exchange_id.upper()} بنجاح")
        except Exception as e:
            logger.error(f"خطأ في تهيئة المنصة ({config.exchange_id}): {e}. الرجوع إلى Bybit الافتراضية.")
            self._exchange = ccxt.bybit({'enableRateLimit': True})
        self.exchange_rules = ExchangeRules(self._exchange)

    def init_db(self):
        """إنشاء جداول قاعدة البيانات إذا لم تكن موجودة"""
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            
            # جدول الصفقات
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    pair TEXT NOT NULL,
                    side TEXT NOT NULL,
                    entry_price REAL NOT NULL,
                    current_price REAL NOT NULL,
                    amount REAL NOT NULL,
                    cost REAL NOT NULL,
                    highest_price REAL NOT NULL,
                    trailing_stop_price REAL NOT NULL,
                    take_profit_price REAL NOT NULL,
                    stop_loss_price REAL NOT NULL,
                    status TEXT NOT NULL,  -- 'OPEN' or 'CLOSED'
                    exit_price REAL,
                    exit_reason TEXT,
                    pnl_amount REAL DEFAULT 0.0,
                    pnl_pct REAL DEFAULT 0.0,
                    entry_time TEXT NOT NULL,
                    exit_time TEXT,
                    is_paper INTEGER DEFAULT 1,
                    entry_fee REAL DEFAULT 0.0,
                    exit_fee REAL DEFAULT 0.0
                )
            """)

            # أضف أعمدة DB الجديدة (entry_fee, exit_fee) بطريقة آمنة
            try:
                cursor.execute("ALTER TABLE trades ADD COLUMN entry_fee REAL DEFAULT 0.0")
            except sqlite3.OperationalError:
                pass

            try:
                cursor.execute("ALTER TABLE trades ADD COLUMN exit_fee REAL DEFAULT 0.0")
            except sqlite3.OperationalError:
                pass

            # جدول المحفظة والرصيد
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS portfolio (
                    id INTEGER PRIMARY KEY,
                    usdt_balance REAL NOT NULL,
                    initial_balance REAL NOT NULL,
                    total_realized_pnl REAL DEFAULT 0.0,
                    win_trades INTEGER DEFAULT 0,
                    loss_trades INTEGER DEFAULT 0,
                    updated_at TEXT NOT NULL
                )
            """)

            # جدول سجل استشارات الذكاء الاصطناعي
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS ai_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    pair TEXT NOT NULL,
                    signal TEXT NOT NULL,
                    confidence INTEGER,
                    safety_score INTEGER,
                    sentiment TEXT,
                    summary TEXT,
                    details TEXT
                )
            """)

            # التأكد من وجود سجل رصيد أولي
            cursor.execute("SELECT COUNT(*) FROM portfolio WHERE id = 1")
            if cursor.fetchone()[0] == 0:
                now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                cursor.execute("""
                    INSERT INTO portfolio (id, usdt_balance, initial_balance, total_realized_pnl, win_trades, loss_trades, updated_at)
                    VALUES (1, ?, ?, 0.0, 0, 0, ?)
                """, (config.initial_balance, config.initial_balance, now))

            # جدول حالة عامل التشغيل في الخلفية
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS bot_worker_state (
                    id INTEGER PRIMARY KEY,
                    is_running INTEGER DEFAULT 0,
                    last_heartbeat TEXT,
                    cycle_count INTEGER DEFAULT 0,
                    last_message TEXT
                )
            """)
            cursor.execute("SELECT COUNT(*) FROM bot_worker_state WHERE id = 1")
            if cursor.fetchone()[0] == 0:
                cursor.execute("""
                    INSERT INTO bot_worker_state (id, is_running, last_heartbeat, cycle_count, last_message)
                    VALUES (1, 0, NULL, 0, 'المحرك متوقف')
                """)

            # جدول سجل نتائج مسح واقتناص الفرص
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS scanner_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    scan_time TEXT NOT NULL,
                    pair TEXT NOT NULL,
                    price REAL NOT NULL,
                    change_24h REAL NOT NULL,
                    volume_24h REAL,
                    rsi REAL,
                    opportunity_score INTEGER,
                    signal TEXT,
                    signal_arabic TEXT,
                    reasons TEXT
                )
            """)
            
            conn.commit()
        finally:
            conn.close()

    def get_portfolio_state(self) -> Dict[str, Any]:
        """الحصول على الحالة اللحظية للمحفظة والرصيد"""
        with self._db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT usdt_balance, initial_balance, total_realized_pnl, win_trades, loss_trades FROM portfolio WHERE id = 1")
            row = cursor.fetchone()
            if row:
                usdt_balance, initial_balance, realized_pnl, wins, losses = row
            else:
                usdt_balance, initial_balance, realized_pnl, wins, losses = config.initial_balance, config.initial_balance, 0.0, 0, 0

            # حساب الأرباح العائمة للصفقات المفتوحة
            cursor.execute("SELECT cost, pnl_amount, COALESCE(entry_fee, 0.0) FROM trades WHERE status = 'OPEN'")
            open_rows = cursor.fetchall()
            unrealized_pnl = sum([r[1] for r in open_rows])
            total_invested = sum([r[0] + r[2] for r in open_rows])

            total_equity = usdt_balance + total_invested + unrealized_pnl
            total_pnl = realized_pnl + unrealized_pnl
            total_pnl_pct = ((total_equity - initial_balance) / initial_balance) * 100 if initial_balance > 0 else 0.0
            
            total_trades = wins + losses
            win_rate = (wins / total_trades * 100) if total_trades > 0 else 0.0

            return {
                "usdt_balance": round(usdt_balance, 4),
                "total_equity": round(total_equity, 4),
                "initial_balance": round(initial_balance, 4),
                "realized_pnl": round(realized_pnl, 4),
                "unrealized_pnl": round(unrealized_pnl, 4),
                "total_pnl": round(total_pnl, 4),
                "total_pnl_pct": round(total_pnl_pct, 2),
                "open_trades_count": len(open_rows),
                "wins": wins,
                "losses": losses,
                "win_rate": round(win_rate, 1)
            }

    def reset_paper_balance(self, new_balance: float = 4.0):
        """إعادة تعيين الرصيد التجريبي ومسح الصفقات التجريبية"""
        with self._db_connection() as conn:
            cursor = conn.cursor()
            now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            cursor.execute("""
                UPDATE portfolio 
                SET usdt_balance = ?, initial_balance = ?, total_realized_pnl = 0.0, win_trades = 0, loss_trades = 0, updated_at = ?
                WHERE id = 1
            """, (new_balance, new_balance, now))
            cursor.execute("DELETE FROM trades WHERE is_paper = 1")
            cursor.execute("DELETE FROM ai_logs")
            conn.commit()

    @_retry_on_network_error(max_retries=3, base_delay=2.0)
    def fetch_market_candles(self, pair: str, timeframe: str = "15m", limit: int = 250) -> pd.DataFrame:
        """جلب بيانات الشموع الحية من المنصة مع حساب المؤشرات الفنية"""
        try:
            ohlcv = self._exchange.fetch_ohlcv(pair, timeframe=timeframe, limit=limit)
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['datetime'] = pd.to_datetime(df['timestamp'], unit='ms')
            df = TechnicalIndicators.enrich_dataframe(df)
            logger.debug(f"تم جلب {len(df)} شمعة لـ {pair} ({timeframe})")
            return df
        except (ccxt.NetworkError, ccxt.RequestTimeout, ccxt.ExchangeNotAvailable, ccxt.RateLimitExceeded):
            raise  # يتم معالجتها بواسطة مُزيِّن الإعادة
        except Exception as e:
            logger.error(f"خطأ في جلب شموع {pair}: {e}", exc_info=True)
            return pd.DataFrame()

    @_retry_on_network_error(max_retries=3, base_delay=1.5)
    def get_current_price(self, pair: str) -> float:
        """جلب السعر الحالي الفوري للزوج"""
        try:
            ticker = self._exchange.fetch_ticker(pair)
            price = float(ticker['last'] or ticker['close'])
            if price <= 0:
                logger.warning(f"سعر غير صالح لـ {pair}: {price}")
                return 0.0
            return price
        except (ccxt.NetworkError, ccxt.RequestTimeout, ccxt.ExchangeNotAvailable, ccxt.RateLimitExceeded):
            raise  # يتم معالجتها بواسطة مُزيِّن الإعادة
        except Exception as e:
            logger.error(f"خطأ في جلب سعر {pair}: {e}")
            return 0.0

    def get_available_spot_pairs(self, force_refresh: bool = False) -> List[str]:
        """
        جلب قائمة جميع أزواج التداول الفوري المتاحة مع USDT من المنصة مع التخزين المؤقت.
        ترتيب النتائج مع إعطاء الأولوية للعملات الأكثر شعبية يتبعها الترتيب الأبجدي.
        """
        now = time.time()
        # التخزين المؤقت صالح لمدة 10 دقائق لتوفير استهلاك الـ API
        if not force_refresh and self._cached_spot_pairs and (now - self._last_spot_pairs_time < 600):
            return self._cached_spot_pairs

        try:
            if self._exchange:
                markets = self._exchange.load_markets()
                pairs = [
                    s for s, m in markets.items()
                    if m.get('spot', False) and m.get('quote') == 'USDT' and m.get('active', True)
                ]
                if pairs:
                    popular_set = set(POPULAR_PAIRS)
                    top_pairs = [p for p in POPULAR_PAIRS if p in pairs]
                    other_pairs = sorted([p for p in pairs if p not in popular_set])
                    ordered = top_pairs + other_pairs
                    self._cached_spot_pairs = ordered
                    self._last_spot_pairs_time = now
                    return ordered
        except Exception as e:
            logger.warning(f"تعذر جلب أزواج العملات من المنصة ({e}). استخدام القائمة الافتراضية.")

        if not self._cached_spot_pairs:
            self._cached_spot_pairs = POPULAR_PAIRS
            self._last_spot_pairs_time = now
        return self._cached_spot_pairs

    def normalize_and_validate_pair(self, pair_input: str) -> Tuple[bool, str, str]:
        """
        معالجة وتصحيح رمز الزوج المدخل والتحقق من صلاحيته للتداول الفوري.
        يقبل صيغ مختلفة: 'btc', 'BTC', 'BTCUSDT', 'btc/usdt', 'BTC/USDT'.
        يعيد: (is_valid, normalized_pair, message)
        """
        if not pair_input or not pair_input.strip():
            return False, "", "الرمز المدخل فارغ."

        cleaned = pair_input.strip().upper().replace(" ", "")
        
        # تحويل الصيغ بدون سلاش مثل BTCUSDT إلى BTC/USDT
        if "/" not in cleaned:
            if cleaned.endswith("USDT") and len(cleaned) > 4:
                base = cleaned[:-4]
                cleaned = f"{base}/USDT"
            else:
                cleaned = f"{cleaned}/USDT"

        # فحص إذا كان الزوج متاحاً
        all_pairs = self.get_available_spot_pairs()
        if cleaned in all_pairs:
            return True, cleaned, f"الزوج {cleaned} متاح وجاهز للتداول الفوري بنجاح ✅"

        # التحقق مباشرة من المنصة إذا لم يكن موجوداً في الكاش
        try:
            if self._exchange:
                ticker = self._exchange.fetch_ticker(cleaned)
                if ticker and (ticker.get('last') or ticker.get('close')):
                    if cleaned not in self._cached_spot_pairs:
                        self._cached_spot_pairs.append(cleaned)
                    return True, cleaned, f"تم التحقق من الزوج {cleaned} بنجاح من المنصة ✅"
        except Exception:
            pass

        return False, cleaned, f"الزوج {cleaned} غير موجود أو غير مدعوم للتداول الفوري مقابل USDT في المنصة."

    def get_open_trades(self) -> List[Dict[str, Any]]:
        """جلب جميع الصفقات المفتوحة حالياً"""
        with self._db_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM trades WHERE status = 'OPEN' ORDER BY id DESC")
            return [dict(row) for row in cursor.fetchall()]

    def get_trade_history(self, limit: int = 50) -> List[Dict[str, Any]]:
        """جلب سجل الصفقات المغلقة"""
        with self._db_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM trades WHERE status = 'CLOSED' ORDER BY id DESC LIMIT ?", (limit,))
            return [dict(row) for row in cursor.fetchall()]

    def get_recent_ai_logs(self, limit: int = 10) -> List[Dict[str, Any]]:
        """جلب آخر سجلات تحليلات الذكاء الاصطناعي"""
        with self._db_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM ai_logs ORDER BY id DESC LIMIT ?", (limit,))
            return [dict(row) for row in cursor.fetchall()]

    @staticmethod
    def test_exchange_connection(exchange_id: str, api_key: str, api_secret: str, passphrase: str = "") -> Dict[str, Any]:
        """
        فحص الاتصال المباشر بمنصة التداول والتحقق من صحة مفاتيح API وجلب رصيد الحساب الحقيقي
        """
        if not exchange_id or not api_key or not api_secret:
            return {
                "success": False,
                "error": "يرجى إدخال اسم المنصة ومفتاح الـ API والـ Secret كاملاً."
            }

        try:
            exchange_class = getattr(ccxt, exchange_id.lower(), None)
            if not exchange_class:
                return {"success": False, "error": f"المنصة {exchange_id} غير مدعومة في CCXT."}

            config_opts = {
                'apiKey': api_key.strip(),
                'secret': api_secret.strip(),
                'enableRateLimit': True,
                'timeout': 10000,
                'options': {'defaultType': 'spot'}
            }
            if passphrase and passphrase.strip():
                config_opts['password'] = passphrase.strip()

            inst = exchange_class(config_opts)
            balance = inst.fetch_balance()
            
            # Extract USDT details
            usdt_info = balance.get('USDT', {})
            free_usdt = float(usdt_info.get('free', 0.0) or 0.0)
            used_usdt = float(usdt_info.get('used', 0.0) or 0.0)
            total_usdt = float(usdt_info.get('total', 0.0) or 0.0)

            # Find non-zero balances
            other_assets = {}
            total_dict = balance.get('total', {})
            for coin, val in total_dict.items():
                if val and float(val) > 0 and coin != 'USDT':
                    other_assets[coin] = round(float(val), 6)

            return {
                "success": True,
                "exchange": exchange_id.upper(),
                "free_usdt": round(free_usdt, 4),
                "used_usdt": round(used_usdt, 4),
                "total_usdt": round(total_usdt, 4),
                "other_assets": other_assets,
                "message": f"تم الاتصال بنجاح! رصيد USDT المتاح: {free_usdt:.2f}$"
            }
        except ccxt.AuthenticationError as e:
            return {"success": False, "error": f"خطأ مصادقة API: تأكد من صحة المفاتيح: {e}"}
        except ccxt.PermissionDenied as e:
            return {"success": False, "error": f"صلاحيات غير كافية: تأكد من تفعيل صلاحية Spot Trading: {e}"}
        except ccxt.NetworkError as e:
            return {"success": False, "error": f"خطأ شبكة في الاتصال بخادم {exchange_id}: {e}"}
        except Exception as e:
            return {"success": False, "error": f"فشل فحص الاتصال: {str(e)}"}

    def get_worker_state(self) -> Dict[str, Any]:
        """الحصول على حالة عامل التشغيل الآلي في الخلفية"""
        with self._db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT is_running, last_heartbeat, cycle_count, last_message FROM bot_worker_state WHERE id = 1")
            row = cursor.fetchone()
            if row:
                return {
                    "is_running": bool(row[0]),
                    "last_heartbeat": row[1] or "لا يوجد",
                    "cycle_count": row[2],
                    "last_message": row[3] or ""
                }
            return {"is_running": False, "last_heartbeat": "متوقف", "cycle_count": 0, "last_message": ""}

    def set_worker_state(self, is_running: bool, cycle_inc: bool = False, message: str = None):
        """تحديث حالة المحرك ونبضات النشاط"""
        with self._db_connection() as conn:
            cursor = conn.cursor()
            now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            if cycle_inc:
                cursor.execute("""
                    UPDATE bot_worker_state 
                    SET is_running = ?, last_heartbeat = ?, cycle_count = cycle_count + 1, last_message = COALESCE(?, last_message)
                    WHERE id = 1
                """, (1 if is_running else 0, now, message))
            else:
                cursor.execute("""
                    UPDATE bot_worker_state 
                    SET is_running = ?, last_heartbeat = ?, last_message = COALESCE(?, last_message)
                    WHERE id = 1
                """, (1 if is_running else 0, now, message))
            conn.commit()

    def open_position(self, pair: str, current_price: float, amount_usdt: float, is_paper: bool = True) -> Tuple[Optional[int], str]:
        """فتح صفقة شراء جديدة مع ضبط الوقف وأخذ الربح ومحاكاة الرسوم والانزلاق"""
        if current_price <= 0:
            return None, "سعر غير صالح"

        with self._db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT usdt_balance FROM portfolio WHERE id = 1")
            balance = cursor.fetchone()[0]

            if balance < amount_usdt:
                msg = f"رصيد غير كافٍ لفتح صفقة {pair}: المتاح {balance:.2f}$ < المطلوب {amount_usdt:.2f}$"
                logger.warning(msg)
                return None, msg

            # Check open positions limit
            cursor.execute("SELECT COUNT(*) FROM trades WHERE status = 'OPEN'")
            open_count = cursor.fetchone()[0]
            if open_count >= config.max_open_trades:
                msg = f"تم بلوغ الحد الأقصى للصفقات المفتوحة ({config.max_open_trades}). لن يتم فتح صفقة جديدة."
                logger.info(msg)
                return None, msg

            now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            if is_paper:
                slippage = getattr(config, 'paper_slippage_pct', 0.05)
                fee_pct = getattr(config, 'paper_fee_pct', 0.1)

                fill_price = current_price * (1 + (slippage / 100))
                raw_amount = amount_usdt / fill_price
                amount = self.exchange_rules.round_amount(pair, raw_amount)

                is_valid, val_msg = self.exchange_rules.validate_order(pair, amount, fill_price)
                if not is_valid:
                    logger.warning(f"رفض أمر التداول التجريبي لـ {pair}: {val_msg}")
                    return None, val_msg

                cost = amount * fill_price
                fee_usdt = cost * (fee_pct / 100)
                total_deduction = cost + fee_usdt

                if balance < total_deduction:
                    msg = f"الرصيد المتاح ({balance:.2f}$) غير كافٍ لتغطية التكلفة والرسوم ({total_deduction:.2f}$)"
                    logger.warning(msg)
                    return None, msg

                actual_price = fill_price
                actual_qty = amount
                actual_cost = cost
                entry_fee = fee_usdt

            else:
                raw_amount = amount_usdt / current_price
                is_valid, val_msg = self.exchange_rules.validate_order(pair, raw_amount, current_price)
                if not is_valid:
                    logger.warning(f"رفض أمر التداول الحقيقي لـ {pair}: {val_msg}")
                    return None, val_msg

                try:
                    qty = self.exchange_rules.round_amount(pair, raw_amount)
                    order = self._exchange.create_market_buy_order(pair, qty)
                    actual_price = float(order.get('average', order.get('price', current_price)) or current_price)
                    actual_qty = float(order.get('filled', qty) or qty)
                    actual_cost = actual_qty * actual_price
                    fee_rate = self.exchange_rules.taker_fee(pair)
                    entry_fee = actual_cost * fee_rate
                    total_deduction = actual_cost + entry_fee
                    logger.info(f"✅ تم تنفيذ أمر شراء حقيقي على المنصة | Order ID: {order.get('id')} | السعر الفعلي: {actual_price:.2f}$")
                except Exception as e:
                    msg = f"❌ فشل تنفيذ أمر الشراء الحقيقي على المنصة: {e}"
                    logger.error(msg)
                    return None, msg

            take_profit = actual_price * (1 + (config.take_profit_pct / 100))
            stop_loss = actual_price * (1 - (config.stop_loss_pct / 100))
            trailing_stop = stop_loss

            cursor.execute("""
                INSERT INTO trades (
                    pair, side, entry_price, current_price, amount, cost, highest_price,
                    trailing_stop_price, take_profit_price, stop_loss_price, status,
                    entry_time, is_paper, entry_fee
                ) VALUES (?, 'BUY', ?, ?, ?, ?, ?, ?, ?, ?, 'OPEN', ?, ?, ?)
            """, (
                pair, actual_price, actual_price, actual_qty, actual_cost, actual_price,
                trailing_stop, take_profit, stop_loss, now, 1 if is_paper else 0, entry_fee
            ))
            trade_id = cursor.lastrowid

            # Deduct total cost + fee from portfolio balance
            cursor.execute("UPDATE portfolio SET usdt_balance = usdt_balance - ? WHERE id = 1", (total_deduction,))
            conn.commit()

            trade_mode = "ورقية" if is_paper else "حقيقية"
            logger.info(
                f"📈 فتح صفقة {trade_mode} #{trade_id} | {pair} | "
                f"سعر الدخول: {actual_price:.4f}$ | الكمية: {actual_qty} | "
                f"التكلفة: {actual_cost:.2f}$ | الرسوم: {entry_fee:.4f}$ | الهدف: {take_profit:.2f}$ | الوقف: {stop_loss:.2f}$"
            )
            try:
                from notifier import TelegramNotifier
                TelegramNotifier.notify_trade_opened(
                    pair, actual_price, actual_qty, actual_cost, take_profit, stop_loss, is_paper
                )
            except Exception:
                pass
            return trade_id, "تم فتح الصفقة بنجاح"

    def close_position(self, trade_id: int, exit_price: float, reason: str):
        """إغلاق صفقة معينة واحتساب الأرباح المحققة وتحديث الرصيد محاكاة الرسوم والانزلاق"""
        with self._db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT cost, amount, entry_price, pair, COALESCE(entry_fee, 0.0), is_paper FROM trades WHERE id = ? AND status = 'OPEN'", (trade_id,))
            row = cursor.fetchone()
            if not row:
                logger.warning(f"محاولة إغلاق صفقة غير موجودة أو مغلقة مسبقاً: #{trade_id}")
                return

            cost, amount, entry_price, pair, entry_fee, is_paper_val = row
            is_paper_trade = bool(is_paper_val)

            if is_paper_trade:
                slippage = getattr(config, 'paper_slippage_pct', 0.05)
                fee_pct = getattr(config, 'paper_fee_pct', 0.1)

                fill_price = exit_price * (1 - (slippage / 100))
                exit_fee = amount * fill_price * (fee_pct / 100)
                gross_return = (amount * fill_price) - exit_fee
                pnl_amount = gross_return - ((amount * entry_price) + entry_fee)
                entry_total = (amount * entry_price) + entry_fee
                pnl_pct = (pnl_amount / entry_total) * 100 if entry_total > 0 else 0.0
                actual_exit_price = fill_price
            else:
                try:
                    order = self._exchange.create_market_sell_order(pair, amount)
                    actual_exit_price = float(order.get('average', order.get('price', exit_price)) or exit_price)
                    logger.info(f"✅ تم تنفيذ أمر بيع حقيقي على المنصة | Order ID: {order.get('id')} | السعر الفعلي: {actual_exit_price:.2f}$")
                except Exception as e:
                    logger.error(f"❌ فشل تنفيذ أمر البيع الحقيقي: {e}. سيتم التسجيل بالسعر المقدّر.")
                    actual_exit_price = exit_price

                fee_rate = self.exchange_rules.taker_fee(pair)
                exit_fee = amount * actual_exit_price * fee_rate
                gross_return = (amount * actual_exit_price) - exit_fee
                entry_total = (amount * entry_price) + entry_fee
                pnl_amount = gross_return - entry_total
                pnl_pct = ((actual_exit_price - entry_price) / entry_price) * 100 if entry_price > 0 else 0.0

            now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            cursor.execute("""
                UPDATE trades SET 
                    status = 'CLOSED',
                    exit_price = ?,
                    exit_reason = ?,
                    pnl_amount = ?,
                    pnl_pct = ?,
                    exit_time = ?,
                    exit_fee = ?
                WHERE id = ?
            """, (actual_exit_price, reason, pnl_amount, pnl_pct, now, exit_fee, trade_id))

            # Update Portfolio
            win_inc = 1 if pnl_amount >= 0 else 0
            loss_inc = 1 if pnl_amount < 0 else 0

            cursor.execute("""
                UPDATE portfolio SET
                    usdt_balance = usdt_balance + ?,
                    total_realized_pnl = total_realized_pnl + ?,
                    win_trades = win_trades + ?,
                    loss_trades = loss_trades + ?,
                    updated_at = ?
                WHERE id = 1
            """, (gross_return, pnl_amount, win_inc, loss_inc, now))
            conn.commit()

            pnl_icon = "💰" if pnl_amount >= 0 else "📉"
            logger.info(
                f"{pnl_icon} إغلاق صفقة #{trade_id} | {pair} | "
                f"دخول: {entry_price:.2f}$ → خروج: {actual_exit_price:.2f}$ | "
                f"PnL: {pnl_amount:+.4f}$ ({pnl_pct:+.2f}%) | السبب: {reason}"
            )
            try:
                from notifier import TelegramNotifier
                TelegramNotifier.notify_trade_closed(
                    pair, entry_price, actual_exit_price, pnl_amount, pnl_pct, reason
                )
            except Exception:
                pass

    def update_open_positions(self) -> List[str]:
        """
        تحديث ومراقبة كافة الصفقات المفتوحة:
        - تحديث الأسعار اللحظية والربح العائم
        - رفع الوقف المتحرك (Trailing Stop) لحجز الأرباح
        - تنفيذ الخروج التلقائي عند بلوغ الهدف أو الوقف
        """
        events = []
        open_trades = self.get_open_trades()
        if not open_trades:
            return events

        for trade in open_trades:
            pair = trade['pair']
            trade_id = trade['id']
            entry_price = trade['entry_price']
            highest_price = trade['highest_price']
            trailing_stop = trade['trailing_stop_price']
            take_profit = trade['take_profit_price']
            stop_loss = trade['stop_loss_price']
            cost = trade['cost']
            amount = trade['amount']

            current_price = self.get_current_price(pair)
            if current_price <= 0:
                continue

            slippage = getattr(config, 'paper_slippage_pct', 0.05)
            fee_pct = getattr(config, 'paper_fee_pct', 0.1)
            entry_fee = trade.get('entry_fee', 0.0) or 0.0

            est_exit_price = current_price * (1 - (slippage / 100))
            est_exit_fee = amount * est_exit_price * (fee_pct / 100)
            entry_total = (amount * entry_price) + entry_fee

            current_pnl_amt = (amount * est_exit_price - est_exit_fee) - entry_total
            current_pnl_pct = ((est_exit_price - entry_price) / entry_price) * 100

            # Update highest price seen
            if current_price > highest_price:
                highest_price = current_price

            # Check Trailing Stop activation and update
            trailing_activated = trailing_stop > stop_loss  # الوقف المتحرك مفعّل إذا كان أعلى من وقف الخسارة الأصلي
            if current_pnl_pct >= config.trailing_stop_activation_pct:
                new_trailing_stop = highest_price * (1 - (config.trailing_stop_callback_pct / 100))
                if new_trailing_stop > trailing_stop:
                    trailing_stop = new_trailing_stop
                    trailing_activated = True

            # Check Exit Conditions
            if current_price >= take_profit:
                self.close_position(trade_id, current_price, f"تحقيق هدف الربح (+{config.take_profit_pct}%) 🎯")
                events.append(f"تم إغلاق {pair} بنجاح عند {current_price:.2f}$ محققاً ربح +{current_pnl_pct:.2f}% 💰")
                continue

            if trailing_activated and current_price <= trailing_stop:
                self.close_position(trade_id, current_price, "تفعيل الوقف المتحرك وحجز الأرباح 🛡️")
                events.append(f"تم حجز أرباح {pair} بوقف متحرك عند {current_price:.2f}$ بربح +{current_pnl_pct:.2f}% 🔒")
                continue

            if current_price <= stop_loss:
                self.close_position(trade_id, current_price, "وقف الخسارة الأقصى (Stop Loss) ⚠️")
                events.append(f"تم تفعيل وقف الخسارة لحماية المحفظة على {pair} بنسبة {current_pnl_pct:.2f}% ⚠️")
                continue

            # Update position in DB
            with self._db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    UPDATE trades SET 
                        current_price = ?,
                        highest_price = ?,
                        trailing_stop_price = ?,
                        pnl_amount = ?,
                        pnl_pct = ?
                    WHERE id = ?
                """, (current_price, highest_price, trailing_stop, current_pnl_amt, current_pnl_pct, trade_id))
                conn.commit()

        return events

    def log_ai_analysis(self, pair: str, analysis: AIAnalysisResult):
        """حفظ تحليل وتوصية الذكاء الاصطناعي في السجل"""
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO ai_logs (timestamp, pair, signal, confidence, safety_score, sentiment, summary, details)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                now, pair, analysis.signal_arabic, analysis.confidence, analysis.safety_score,
                analysis.market_sentiment, analysis.arabic_summary, analysis.detailed_advice
            ))
            conn.commit()
