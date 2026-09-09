"""
نظام الاختبار الرجعي (Backtesting Engine)
يختبر استراتيجية التداول وإدارة المخاطر على بيانات الشموع التاريخية
لقياس نسبة النجاح، الأرباح، وأقصى تراجع (Max Drawdown) قبل التداول الحقيقي
"""

import sys
import os
import datetime
import tempfile
import uuid
import pandas as pd
import numpy as np
from typing import Dict, Any, List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import config
from indicators import add_all_indicators, min_candles_required
from strategy import generate_signal
from risk_manager import RiskManager, RiskConfig, position_size_usdt


class BacktestEngine:
    """محرك الاختبار الرجعي للاستراتيجية الكمية"""

    @classmethod
    def run_backtest(
        cls,
        df_ltf: pd.DataFrame = None,
        df_htf: Optional[pd.DataFrame] = None,
        initial_balance: float = 100.0,
        fee_pct: float = 0.001,
        slippage_pct: float = 0.0005,
        risk_cfg: Optional[RiskConfig] = None,
        strategy_cfg: Any = None,
        pair: str = "BTC/USDT",
        **kwargs
    ) -> Dict[str, Any]:
        """
        تشغيل اختبار رجعي على إطار بيانات الشموع
        """
        # Backwards compatibility for parameter aliases
        if df_ltf is None:
            df_ltf = kwargs.get("candles_df", kwargs.get("df"))

        if df_ltf is None or df_ltf.empty:
            return {
                "success": False,
                "error": "البيانات التاريخية غير كافية لإجراء الاختبار.",
                "total_trades": 0,
                "win_rate": 0.0,
                "net_pnl": 0.0,
                "profit_factor": 0.0,
                "max_drawdown_pct": 0.0,
                "expectancy_per_trade": 0.0,
                "avg_rr": 0.0,
                "fees_paid": 0.0,
                "trades": []
            }

        df_ltf = df_ltf.copy()
        if 'timestamp' not in df_ltf.columns:
            df_ltf['timestamp'] = range(len(df_ltf))

        if 'ema_50' not in df_ltf.columns or 'atr' not in df_ltf.columns:
            df_ltf = add_all_indicators(df_ltf)

        if df_htf is None or df_htf.empty:
            df_htf = df_ltf.copy()
        else:
            df_htf = df_htf.copy()
            if 'timestamp' not in df_htf.columns:
                df_htf['timestamp'] = range(len(df_htf))
            if 'ema_200' not in df_htf.columns:
                df_htf = add_all_indicators(df_htf)

        risk_config = risk_cfg or RiskConfig()
        temp_db_path = os.path.join(tempfile.gettempdir(), f"risk_bt_{uuid.uuid4().hex}.db")

        try:
            risk_mgr = RiskManager(cfg=risk_config, db_path=temp_db_path)

            balance = float(initial_balance)
            peak_balance = float(initial_balance)
            max_drawdown_pct = 0.0
            total_fees_paid = 0.0

            open_position = None
            trades: List[Dict[str, Any]] = []

            min_req = min_candles_required()  # 210
            start_idx = min_req if len(df_ltf) >= min_req else max(1, min(35, len(df_ltf) - 1))

            for i in range(start_idx, len(df_ltf)):
                curr_row = df_ltf.iloc[i]
                open_i = float(curr_row['open'])
                high_i = float(curr_row['high'])
                low_i = float(curr_row['low'])
                close_i = float(curr_row['close'])

                raw_ts = curr_row.get('datetime', curr_row.get('timestamp', i))
                if isinstance(raw_ts, (int, float, np.integer, np.floating)):
                    now_dt = datetime.datetime.fromtimestamp(raw_ts / 1000.0, tz=datetime.timezone.utc) if raw_ts > 1e11 else datetime.datetime.now(datetime.timezone.utc)
                elif isinstance(raw_ts, datetime.datetime):
                    now_dt = raw_ts
                else:
                    try:
                        now_dt = datetime.datetime.fromisoformat(str(raw_ts))
                    except Exception:
                        now_dt = datetime.datetime.now(datetime.timezone.utc)

                # 1. إذا كانت هناك صفقة مفتوحة، فحص الخروج أولاً
                if open_position is not None:
                    hit_sl = (low_i <= open_position['stop'])
                    hit_tp = (high_i >= open_position['take_profit'])

                    closed = False
                    exit_price = 0.0
                    exit_reason = ""

                    # تحقق أولاً من low <= stop (خسارة) ثم high >= tp
                    if hit_sl:
                        exit_price = open_position['stop']
                        exit_reason = "وقف الخسارة 🛑"
                        closed = True
                    elif hit_tp:
                        exit_price = open_position['take_profit']
                        exit_reason = "هدف الربح 🎯"
                        closed = True

                    if closed:
                        qty = open_position['qty']
                        notional_entry = open_position['notional']
                        entry_fee = open_position['entry_fee']

                        exit_notional = qty * exit_price
                        exit_fee = exit_notional * fee_pct
                        trade_fees = entry_fee + exit_fee
                        total_fees_paid += exit_fee

                        pnl_amt = exit_notional - notional_entry - trade_fees
                        pnl_pct = (pnl_amt / notional_entry) * 100.0 if notional_entry > 0 else 0.0
                        balance += (notional_entry + pnl_amt)

                        is_win = pnl_amt >= 0
                        trades.append({
                            "pair": pair,
                            "entry_time": open_position['entry_time'],
                            "exit_time": str(raw_ts),
                            "entry_price": open_position['actual_entry'],
                            "exit_price": exit_price,
                            "qty": qty,
                            "pnl_amount": round(pnl_amt, 6),
                            "pnl_pct": round(pnl_pct, 2),
                            "fee_paid": round(trade_fees, 6),
                            "rr": open_position['rr'],
                            "reason": exit_reason,
                            "is_win": is_win
                        })

                        risk_mgr.on_trade_closed(pair, pnl_amt, now_dt, pnl_pct)
                        open_position = None

                # 2. فحص الدخول إذا لم تكن هناك صفقة مفتوحة
                elif open_position is None:
                    slice_ltf = df_ltf.iloc[:i]
                    prev_ts = df_ltf['timestamp'].iloc[i - 1]
                    slice_htf = df_htf[df_htf['timestamp'] <= prev_ts]

                    sig = generate_signal(slice_ltf, slice_htf, fee_pct, slippage_pct, strategy_cfg)

                    if sig.action == "BUY":
                        can_open_flag, _ = risk_mgr.can_open(pair, now_dt, state={"open_positions_count": 0})
                        if can_open_flag:
                            notional, _ = position_size_usdt(
                                equity=balance,
                                entry=sig.entry,
                                stop=sig.stop,
                                cfg=risk_config,
                                symbol=pair
                            )
                            if notional > 0 and balance >= notional:
                                actual_entry = open_i * (1.0 + slippage_pct)
                                entry_fee = notional * fee_pct
                                total_fees_paid += entry_fee
                                qty = notional / actual_entry

                                balance -= notional

                                open_position = {
                                    "entry_time": str(raw_ts),
                                    "actual_entry": actual_entry,
                                    "qty": qty,
                                    "notional": notional,
                                    "entry_fee": entry_fee,
                                    "stop": sig.stop,
                                    "take_profit": sig.take_profit,
                                    "rr": sig.rr
                                }

                # حساب أقصى تراجع
                current_equity = balance + (open_position['qty'] * close_i if open_position else 0.0)
                if current_equity > peak_balance:
                    peak_balance = current_equity
                dd = ((peak_balance - current_equity) / peak_balance) * 100.0 if peak_balance > 0 else 0.0
                if dd > max_drawdown_pct:
                    max_drawdown_pct = dd

            # إغلاق أي صفقة مفتوحة في نهاية البيانات
            if open_position is not None:
                last_close = float(df_ltf.iloc[-1]['close'])
                qty = open_position['qty']
                exit_notional = qty * last_close
                exit_fee = exit_notional * fee_pct
                trade_fees = open_position['entry_fee'] + exit_fee
                total_fees_paid += exit_fee

                pnl_amt = exit_notional - open_position['notional'] - trade_fees
                pnl_pct = (pnl_amt / open_position['notional']) * 100.0 if open_position['notional'] > 0 else 0.0
                balance += (open_position['notional'] + pnl_amt)

                trades.append({
                    "pair": pair,
                    "entry_time": open_position['entry_time'],
                    "exit_time": "نهاية فترة الاختبار",
                    "entry_price": open_position['actual_entry'],
                    "exit_price": last_close,
                    "qty": qty,
                    "pnl_amount": round(pnl_amt, 6),
                    "pnl_pct": round(pnl_pct, 2),
                    "fee_paid": round(trade_fees, 6),
                    "rr": open_position['rr'],
                    "reason": "إغلاق بنهاية البيانات ⏳",
                    "is_win": pnl_amt >= 0
                })
                open_position = None

            # الإحصائيات الفردية والمجمعة
            total_trades = len(trades)
            wins = [t for t in trades if t['is_win']]
            losses = [t for t in trades if not t['is_win']]
            win_count = len(wins)
            loss_count = len(losses)
            win_rate = (win_count / total_trades * 100.0) if total_trades > 0 else 0.0

            total_profit = sum(t['pnl_amount'] for t in wins)
            total_loss = abs(sum(t['pnl_amount'] for t in losses))
            profit_factor = (total_profit / total_loss) if total_loss > 0 else (99.0 if total_profit > 0 else 0.0)

            net_pnl = balance - initial_balance
            net_pnl_pct = (net_pnl / initial_balance) * 100.0 if initial_balance > 0 else 0.0
            expectancy_per_trade = (net_pnl / total_trades) if total_trades > 0 else 0.0
            avg_rr = float(np.mean([t['rr'] for t in trades])) if total_trades > 0 else 0.0

            return {
                "success": True,
                "pair": pair,
                "initial_balance": initial_balance,
                "final_balance": round(balance, 4),
                "net_pnl": round(net_pnl, 6),
                "net_pnl_pct": round(net_pnl_pct, 2),
                "total_trades": total_trades,
                "win_count": win_count,
                "loss_count": loss_count,
                "win_rate": round(win_rate, 2),
                "profit_factor": round(profit_factor, 2),
                "max_drawdown_pct": round(max_drawdown_pct, 2),
                "expectancy_per_trade": round(expectancy_per_trade, 4),
                "avg_rr": round(avg_rr, 2),
                "fees_paid": round(total_fees_paid, 6),
                "trades": trades
            }

        finally:
            for ext in ["", "-wal", "-shm"]:
                f = temp_db_path + ext
                if os.path.exists(f):
                    try:
                        os.remove(f)
                    except Exception:
                        pass


def walk_forward(
    df_ltf: pd.DataFrame,
    df_htf: Optional[pd.DataFrame] = None,
    n_splits: int = 4,
    initial_balance: float = 100.0,
    fee_pct: float = 0.001,
    slippage_pct: float = 0.0005,
    risk_cfg: Optional[RiskConfig] = None,
    strategy_cfg: Any = None,
    pair: str = "BTC/USDT"
) -> Dict[str, Any]:
    """
    تحليل Walk-Forward لتقسيم البيانات زمنياً واختبار استقرار الاستراتيجية عبر الفترات
    """
    if df_ltf is None or df_ltf.empty or len(df_ltf) < n_splits * 10:
        print("البيانات غير كافية لإجراء تحليل Walk-Forward.")
        return {"splits": [], "unstable_warning": False, "is_stable": True}

    chunk_size = len(df_ltf) // n_splits
    splits_results = []
    negative_count = 0

    print("=" * 70)
    print(f"📊 بدء تحليل Walk-Forward (عدد الأجزاء: {n_splits}) لـ {pair}")
    print("=" * 70)

    for k in range(n_splits):
        start_i = k * chunk_size
        end_i = (k + 1) * chunk_size if k < n_splits - 1 else len(df_ltf)

        sub_ltf = df_ltf.iloc[start_i:end_i].copy()
        sub_htf = None
        if df_htf is not None and not df_htf.empty and 'timestamp' in sub_ltf.columns and 'timestamp' in df_htf.columns:
            ts_start = sub_ltf['timestamp'].iloc[0]
            ts_end = sub_ltf['timestamp'].iloc[-1]
            sub_htf = df_htf[(df_htf['timestamp'] >= ts_start) & (df_htf['timestamp'] <= ts_end)].copy()

        res = BacktestEngine.run_backtest(
            df_ltf=sub_ltf,
            df_htf=sub_htf,
            initial_balance=initial_balance,
            fee_pct=fee_pct,
            slippage_pct=slippage_pct,
            risk_cfg=risk_cfg,
            strategy_cfg=strategy_cfg,
            pair=pair
        )

        net_pnl = res.get("net_pnl", 0.0)
        if net_pnl < 0:
            negative_count += 1

        start_time_str = str(sub_ltf.iloc[0].get('datetime', sub_ltf.iloc[0].get('timestamp', start_i)))
        end_time_str = str(sub_ltf.iloc[-1].get('datetime', sub_ltf.iloc[-1].get('timestamp', end_i)))

        splits_results.append({
            "split": k + 1,
            "start_time": start_time_str,
            "end_time": end_time_str,
            "total_trades": res.get("total_trades", 0),
            "win_rate": res.get("win_rate", 0.0),
            "net_pnl": net_pnl,
            "profit_factor": res.get("profit_factor", 0.0),
            "max_drawdown_pct": res.get("max_drawdown_pct", 0.0),
            "fees_paid": res.get("fees_paid", 0.0)
        })

    # طباعة الجدول
    df_summary = pd.DataFrame(splits_results)
    print(df_summary.to_string(index=False))

    unstable_warning = (negative_count > (n_splits / 2))
    if unstable_warning:
        print("\nالاستراتيجية غير مستقرة")
    else:
        print("\n✅ الاستراتيجية مستقرة عبر الفترات الزمنية الاختيارية.")

    print("=" * 70)

    return {
        "splits": splits_results,
        "summary_df": df_summary,
        "negative_count": negative_count,
        "unstable_warning": unstable_warning,
        "is_stable": not unstable_warning
    }


if __name__ == "__main__":
    print("=" * 60)
    print("🔍 بدء تجربة سريعة للاختبار الرجعي (Backtest Demo)")
    print("=" * 60)
    from trading_engine import TradingEngine
    engine = TradingEngine()
    print("جاري جلب 300 شمعة حية لاختبار الاستراتيجية...")
    df = engine.fetch_market_candles("BTC/USDT", timeframe="15m", limit=300)
    if not df.empty:
        results = BacktestEngine.run_backtest(df_ltf=df, pair="BTC/USDT", initial_balance=100.0)
        print(f"الزوج: {results['pair']}")
        print(f"إجمالي الصفقات المنفذة: {results['total_trades']}")
        print(f"نسبة النجاح: {results['win_rate']}% ({results['win_count']} رابحة / {results['loss_count']} خاسرة)")
        print(f"صافي الربح/الخسارة: {results['net_pnl']:+.4f}$ ({results['net_pnl_pct']:+.2f}%)")
        print(f"معامل الربحية (Profit Factor): {results['profit_factor']}")
        print(f"أقصى تراجع (Max Drawdown): {results['max_drawdown_pct']}%")
        print(f"متوسط عائد الصفقة: {results['expectancy_per_trade']:+.4f}$")
        print(f"إجمالي الرسوم المدفوعة: {results['fees_paid']:.4f}$")
        print(f"الرصيد النهائي: {results['final_balance']}$")

        wf_res = walk_forward(df, n_splits=4)
    else:
        print("تعذر جلب البيانات. يرجى التأكد من الاتصال بالإنترنت.")
