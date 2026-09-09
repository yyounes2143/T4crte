"""
وحدة التنبيهات والإشعارات الفورية (Telegram Alerts)
ترسل رسائل مباشرة إلى حسابك أو قناتك على تيليجرام عند فتح الصفقات وإغلاقها وتحقيق الأهداف
"""

import requests
from config import config
from logger import setup_logger

logger = setup_logger("notifier", log_file="trading.log")


class TelegramNotifier:
    """إرسال إشعارات فورية عبر Telegram Bot API"""

    @staticmethod
    def send_message(message: str) -> bool:
        """إرسال رسالة نصية بتنسيق HTML إلى تيليجرام"""
        if not config.telegram_enabled or not config.telegram_bot_token or not config.telegram_chat_id:
            return False

        try:
            url = f"https://api.telegram.org/bot{config.telegram_bot_token.strip()}/sendMessage"
            payload = {
                "chat_id": config.telegram_chat_id.strip(),
                "text": message,
                "parse_mode": "HTML",
                "disable_web_page_preview": True
            }
            res = requests.post(url, json=payload, timeout=6)
            if res.status_code == 200:
                logger.debug("تم إرسال إشعار تيليجرام بنجاح")
                return True
            else:
                logger.warning(f"فشل إرسال إشعار تيليجرام (كود {res.status_code}): {res.text}")
                return False
        except Exception as e:
            logger.warning(f"خطأ في إرسال إشعار تيليجرام: {e}")
            return False

    @classmethod
    def notify_trade_opened(cls, pair: str, price: float, qty: float, cost: float, tp: float, sl: float, is_paper: bool):
        """إشعار عند فتح صفقة شراء جديدة"""
        mode = "🧪 تجريبية (ورقية)" if is_paper else "🔴 حقيقية (Live)"
        msg = f"""⚡ <b>فتح صفقة شراء جديدة</b> | {mode}

🪙 <b>الزوج:</b> <code>{pair}</code>
💵 <b>سعر الدخول:</b> <code>{price:.2f}$</code>
📦 <b>الكمية:</b> <code>{qty:.6f}</code>
💰 <b>التكلفة:</b> <code>{cost:.2f}$</code>
🎯 <b>هدف الربح:</b> <code>{tp:.2f}$</code> (+{config.take_profit_pct}%)
🛑 <b>وقف الخسارة:</b> <code>{sl:.2f}$</code> (-{config.stop_loss_pct}%)
🛡️ <b>الوقف المتحرك:</b> مفعل لحجز الأرباح
"""
        return cls.send_message(msg)

    @classmethod
    def notify_trade_closed(cls, pair: str, entry_price: float, exit_price: float, pnl_amt: float, pnl_pct: float, reason: str):
        """إشعار عند إغلاق صفقة"""
        icon = "💰" if pnl_amt >= 0 else "📉"
        status_text = "رابحة ✅" if pnl_amt >= 0 else "خاسرة 🛑"
        sign = "+" if pnl_amt >= 0 else ""
        msg = f"""{icon} <b>إغلاق صفقة ({status_text})</b>

🪙 <b>الزوج:</b> <code>{pair}</code>
📈 <b>سعر الدخول:</b> <code>{entry_price:.2f}$</code>
📉 <b>سعر الخروج:</b> <code>{exit_price:.2f}$</code>
📊 <b>الربح الصافي:</b> <code>{sign}{pnl_amt:.4f}$ ({sign}{pnl_pct:.2f}%)</code>
📋 <b>السبب:</b> {reason}
"""
        return cls.send_message(msg)

    @classmethod
    def notify_kill_switch(cls, count: int):
        """إشعار تفعيل مفتاح التسييل الطارئ"""
        msg = f"""🚨 <b>تنبيه طوارئ: تفعيل زر التسييل الفوري (Kill Switch)</b>

تم إغلاق كافة الصفقات المفتوحة (عدد: {count}) فوراً من قبل المستخدم لحماية المحفظة.
"""
        return cls.send_message(msg)

    @classmethod
    def test_connection(cls, bot_token: str, chat_id: str) -> dict:
        """اختبار صحة مفاتيح تيليجرام"""
        if not bot_token or not chat_id:
            return {"success": False, "error": "يرجى ملء Bot Token و Chat ID"}

        try:
            url = f"https://api.telegram.org/bot{bot_token.strip()}/sendMessage"
            payload = {
                "chat_id": chat_id.strip(),
                "text": "⚡ <b>تم ربط بوت التداول بنجاح!</b>\nستصلك إشعارات الصفقات والأرباح هنا فور حدوثها.",
                "parse_mode": "HTML"
            }
            res = requests.post(url, json=payload, timeout=8)
            if res.status_code == 200:
                return {"success": True, "message": "تم إرسال رسالة تجريبية بنجاح إلى حسابك في تيليجرام!"}
            else:
                return {"success": False, "error": f"خطأ من تيليجرام ({res.status_code}): {res.text}"}
        except Exception as e:
            return {"success": False, "error": str(e)}
