from typing import Optional, Tuple, Dict, Any


class ExchangeRules:
    """
    إدارة قواعد المنصة والتحقق من صفقات الشراء والبيع:
    - الحدود الأدنى للتكلفة والكمية (min_cost, min_amount)
    - نسبة الرسوم (taker_fee)
    - تقريب الكمية والسعر إلى دقة المنصة (round_amount, round_price)
    - التحقق من إمكانية تنفيذ الأمر (validate_order)
    """

    def __init__(self, exchange):
        self.exchange = exchange
        self._markets: Optional[Dict[str, Any]] = None

    def load(self):
        """تحميل الأسواق من المنصة"""
        if self.exchange and hasattr(self.exchange, 'load_markets'):
            try:
                self._markets = self.exchange.load_markets()
            except Exception:
                self._markets = {}

    def market(self, symbol: str) -> dict:
        """جلب بيانات سوق رمز معين"""
        if self._markets is None:
            self.load()
        if self._markets and symbol in self._markets:
            return self._markets[symbol]
        if self.exchange and hasattr(self.exchange, 'markets') and self.exchange.markets:
            return self.exchange.markets.get(symbol, {})
        return {}

    def min_cost(self, symbol: str) -> float:
        """الحد الأدنى للتكلفة بالـ USDT (افتراضي 5.0 إن كان غير محدد)"""
        m = self.market(symbol)
        try:
            val = m.get('limits', {}).get('cost', {}).get('min')
            if val is not None and float(val) > 0:
                return float(val)
        except Exception:
            pass
        return 5.0

    def min_amount(self, symbol: str) -> float:
        """الحد الأدنى للكمية (افتراضي 0)"""
        m = self.market(symbol)
        try:
            val = m.get('limits', {}).get('amount', {}).get('min')
            if val is not None and float(val) > 0:
                return float(val)
        except Exception:
            pass
        return 0.0

    def taker_fee(self, symbol: str) -> float:
        """نسبة رسوم الآخذ (افتراضي 0.001 أي 0.1%)"""
        m = self.market(symbol)
        try:
            val = m.get('taker')
            if val is not None and float(val) >= 0:
                return float(val)
        except Exception:
            pass
        return 0.001

    def round_amount(self, symbol: str, amount: float) -> float:
        """تقريب الكمية بناءً على دقة المنصة"""
        if self.exchange and hasattr(self.exchange, 'amount_to_precision'):
            try:
                res = self.exchange.amount_to_precision(symbol, amount)
                return float(res)
            except Exception:
                pass
        return float(amount)

    def round_price(self, symbol: str, price: float) -> float:
        """تقريب السعر بناءً على دقة المنصة"""
        if self.exchange and hasattr(self.exchange, 'price_to_precision'):
            try:
                res = self.exchange.price_to_precision(symbol, price)
                return float(res)
            except Exception:
                pass
        return float(price)

    def validate_order(self, symbol: str, amount: float, price: float) -> Tuple[bool, str]:
        """
        التحقق من صلاحية الأمر قبل التنفيذ:
        يرفض إذا:
        - الكمية بعد التقريب تساوي صفر
        - الكمية أقل من min_amount
        - التكلفة (amount * price) أقل من min_cost
        """
        r_amount = self.round_amount(symbol, amount)
        if r_amount <= 0:
            return False, "الكمية بعد التقريب تساوي صفر"

        min_amt = self.min_amount(symbol)
        if r_amount < min_amt:
            return False, f"الكمية ({r_amount}) أقل من الحد الأدنى المسموح به ({min_amt})"

        cost = r_amount * price
        min_c = self.min_cost(symbol)
        if cost < min_c:
            return False, f"قيمة الأمر ({cost:.2f}$) أقل من الحد الأدنى للتكلفة ({min_c:.2f}$)"

        return True, "الأمر صالِح"
