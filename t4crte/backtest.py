"""
نظام الاختبار الرجعي (Backtesting Engine)
يختبر استراتيجية التداول وإدارة المخاطر على بيانات الشموع التاريخية
لقياس نسبة النجاح، الأرباح، وأقصى تراجع (Max Drawdown) قبل التداول الحقيقي
"""

import sys
import os
import pandas as pd
import numpy as np
from typing import Dict, Any, List

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import config
from indicators import TechnicalIndicators, drop_forming_candle
from ai_advisor import AIAdvisor
from trading_engine import TradingEngine


class BacktestEngine:
    """محرك الاختبار الرجعي للاستراتيجية الكمية"""

    @classmethod
    def run_backtest(
        cls,
        candles_df: pd.DataFrame,
        pair: str = "BTC/USDT",
        initial_balance: float = 100.0,
        trade_amount: float = 20.0,
        take_profit_pct: float = 1.8,
        stop_loss_pct: float = 1.2,
        trailing_activation_pct: float = 0.8,
        trailing_callback_pct: float = 0.4,
        timeframe: str = "15m"
    ) -> Dict[str, Any]:
        """
        تشغيل اختبار رجعي على إطار بيانات الشموع
        """
        if candles_df.empty or len(candles_df) < 40:
            return {
                "success": False,
                "error": "البيانات التاريخية غير كافية لإجراء الاختبار (مطلوب 40 شمعة على الأقل)."
            }

        # التأكد من حساب المؤشرات الفنية
        if 'rsi' not in candles_df.columns:
            candles_df = TechnicalIndicators.enrich_dataframe(candles_df)

        balance = initial_balance
        peak_balance = initial_balance
        max_drawdown_pct = 0.0

        open_position = None
        trades: List[Dict[str, Any]] = []

        # المحاكاة شمعة بشمعة
        for i in range(35, len(candles_df)):
            current_slice = candles_df.iloc[:i+1]
            row = current_slice.iloc[-1]
            curr_price = float(row['close'])
            high_price = float(row['high'])
            low_price = float(row['low'])
            timestamp = row.get('datetime', row.get('timestamp', i))

            # 1. إذا كانت هناك صفقة مفتوحة، تفقد شروط الخروج أولاً
            if open_position is not None:
                entry_p = open_position['entry_price']
                highest_seen = max(open_position['highest_price'], high_price)
                open_position['highest_price'] = highest_seen

                trailing_stop = open_position['trailing_stop_price']
                tp_target = open_position['take_profit_price']
                sl_target = open_position['stop_loss_price']

                # تفعيل وتحديث الوقف المتحرك
                cur_profit_pct = ((highest_seen - entry_p) / entry_p) * 100
                trailing_activated = trailing_stop > sl_target

                if cur_profit_pct >= trailing_activation_pct:
                    new_ts = highest_seen * (1 - (trailing_callback_pct / 100))
                    if new_ts > trailing_stop:
                        trailing_stop = new_ts
                        open_position['trailing_stop_price'] = trailing_stop
                        trailing_activated = True

                closed = False
                exit_price = curr_price
                exit_reason = ""

                # فحص ضرب الهدف بالقمة
                if high_price >= tp_target:
                    exit_price = tp_target
                    exit_reason = f"تحقيق الهدف (+{take_profit_pct}%) 🎯"
                    closed = True
                # فحص ضرب الوقف المتحرك
                elif trailing_activated and low_price <= trailing_stop:
                    exit_price = trailing_stop
                    exit_reason = "حجز الأرباح بالوقف المتحرك 🛡️"
                    closed = True
                # فحص ضرب وقف الخسارة
                elif low_price <= sl_target:
                    exit_price = sl_target
                    exit_reason = f"وقف الخسارة الأقصى (-{stop_loss_pct}%) 🛑"
                    closed = True

                if closed:
                    pnl_pct = ((exit_price - entry_p) / entry_p) * 100
                    pnl_amt = (open_position['amount'] * exit_price) - open_position['cost']
                    balance += open_position['cost'] + pnl_amt

                    trades.append({
                        "pair": pair,
                        "entry_time": open_position['entry_time'],
                        "exit_time": str(timestamp),
                        "entry_price": entry_p,
                        "exit_price": exit_price,
                        "pnl_amount": round(pnl_amt, 4),
                        "pnl_pct": round(pnl_pct, 2),
                        "reason": exit_reason,
                        "is_win": pnl_amt >= 0
                    })
                    open_position = None

            # 2. فحص الدخول إذا لم تكن هناك صفقة مفتوحة ولديه رصيد
            elif balance >= trade_amount:
                advisor_res = AIAdvisor.analyze(
                    df=drop_forming_candle(current_slice, timeframe),
                    pair=pair,
                    take_profit_pct=take_profit_pct,
                    stop_loss_pct=stop_loss_pct
                )

                if advisor_res.signal == "BUY" and advisor_res.confidence >= 65 and advisor_res.safety_score >= 80:
                    cost = trade_amount
                    amount = cost / curr_price
                    tp = curr_price * (1 + (take_profit_pct / 100))
                    sl = curr_price * (1 - (stop_loss_pct / 100))

                    open_position = {
                        "entry_time": str(timestamp),
                        "entry_price": curr_price,
                        "amount": amount,
                        "cost": cost,
                        "highest_price": curr_price,
                        "take_profit_price": tp,
                        "stop_loss_price": sl,
                        "trailing_stop_price": sl
                    }
                    balance -= cost

            # حساب أقصى تراجع
            current_equity = balance + (open_position['cost'] if open_position else 0)
            if current_equity > peak_balance:
                peak_balance = current_equity
            dd = ((peak_balance - current_equity) / peak_balance) * 100 if peak_balance > 0 else 0
            if dd > max_drawdown_pct:
                max_drawdown_pct = dd

        # إغلاق أي صفقة مفتوحة في نهاية البيانات
        if open_position is not None:
            last_p = float(candles_df.iloc[-1]['close'])
            pnl_amt = (open_position['amount'] * last_p) - open_position['cost']
            pnl_pct = ((last_p - open_position['entry_price']) / open_position['entry_price']) * 100
            balance += open_position['cost'] + pnl_amt
            trades.append({
                "pair": pair,
                "entry_time": open_position['entry_time'],
                "exit_time": "نهاية فترة الاختبار",
                "entry_price": open_position['entry_price'],
                "exit_price": last_p,
                "pnl_amount": round(pnl_amt, 4),
                "pnl_pct": round(pnl_pct, 2),
                "reason": "إغلاق بنهاية البيانات ⏳",
                "is_win": pnl_amt >= 0
            })

        # الإحصائيات
        total_trades = len(trades)
        wins = [t for t in trades if t['is_win']]
        losses = [t for t in trades if not t['is_win']]
        win_count = len(wins)
        loss_count = len(losses)
        win_rate = (win_count / total_trades * 100) if total_trades > 0 else 0.0

        total_profit = sum(t['pnl_amount'] for t in wins)
        total_loss = abs(sum(t['pnl_amount'] for t in losses))
        profit_factor = (total_profit / total_loss) if total_loss > 0 else (99.0 if total_profit > 0 else 0.0)

        net_pnl = balance - initial_balance
        net_pnl_pct = (net_pnl / initial_balance) * 100

        return {
            "success": True,
            "pair": pair,
            "initial_balance": initial_balance,
            "final_balance": round(balance, 2),
            "net_pnl": round(net_pnl, 4),
            "net_pnl_pct": round(net_pnl_pct, 2),
            "total_trades": total_trades,
            "win_count": win_count,
            "loss_count": loss_count,
            "win_rate": round(win_rate, 1),
            "profit_factor": round(profit_factor, 2),
            "max_drawdown_pct": round(max_drawdown_pct, 2),
            "trades": trades
        }


if __name__ == "__main__":
    print("=" * 60)
    print("🔍 بدء تجربة سريعة للاختبار الرجعي (Backtest Demo)")
    print("=" * 60)
    engine = TradingEngine()
    print("جاري جلب 250 شمعة حية لاختبار الاستراتيجية...")
    df = engine.fetch_market_candles("BTC/USDT", timeframe="15m", limit=250)
    if not df.empty:
        results = BacktestEngine.run_backtest(df, pair="BTC/USDT", initial_balance=100.0, trade_amount=20.0)
        print(f"الزوج: {results['pair']}")
        print(f"إجمالي الصفقات المنفذة: {results['total_trades']}")
        print(f"نسبة النجاح: {results['win_rate']}% ({results['win_count']} رابحة / {results['loss_count']} خاسرة)")
        print(f"صافي الربح/الخسارة: {results['net_pnl']:+.4f}$ ({results['net_pnl_pct']:+.2f}%)")
        print(f"معامل الربحية (Profit Factor): {results['profit_factor']}")
        print(f"أقصى تراجع (Max Drawdown): {results['max_drawdown_pct']}%")
        print(f"الرصيد النهائي: {results['final_balance']}$")
    else:
        print("تعذر جلب البيانات. يرجى التأكد من الاتصال بالإنترنت.")
