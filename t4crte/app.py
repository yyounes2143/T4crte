import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime
import time
import hashlib
import os

from config import config, TradingConfig
from trading_engine import TradingEngine
from indicators import drop_forming_candle
from universal_ai import UniversalAIClient, AI_PRESETS
from bot_worker import start_worker, stop_worker, get_worker_status
from notifier import TelegramNotifier
from backtest import BacktestEngine
from market_scanner import MarketOpportunityScanner
from bybit_health_agent import BybitHealthValidatorAgent

# Page Configuration
st.set_page_config(
    page_title="المركز الشامل للتداول الفوري الذكي | Universal AI Spot Bot",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Custom Styling for Modern Dark Theme & Native RTL Arabic
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Cairo:wght@400;600;700;900&display=swap');
    
    html, body, [class*="css"], .stMarkdown, .stText, h1, h2, h3, h4, h5, h6, .stSelectbox, .stTextInput, .stNumberInput {
        font-family: 'Cairo', sans-serif !important;
        direction: rtl;
        text-align: right;
    }
    
    /* Top Bar Styling */
    .top-bar {
        background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%);
        border: 1px solid #334155;
        border-radius: 12px;
        padding: 14px 20px;
        margin-bottom: 20px;
        display: flex;
        justify-content: space-between;
        align-items: center;
    }

    /* Metric Cards */
    .metric-card {
        background: linear-gradient(135deg, #1e2638 0%, #151a28 100%);
        border: 1px solid #2d3748;
        border-radius: 12px;
        padding: 16px 20px;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.2);
        margin-bottom: 12px;
    }
    .metric-title {
        color: #94a3b8;
        font-size: 13px;
        font-weight: 600;
        margin-bottom: 6px;
    }
    .metric-value {
        color: #f8fafc;
        font-size: 24px;
        font-weight: 700;
    }
    .metric-pnl-positive {
        color: #10b981;
        font-weight: 700;
    }
    .metric-pnl-negative {
        color: #ef4444;
        font-weight: 700;
    }

    /* AI Box Callout */
    .ai-box {
        background: radial-gradient(circle at top left, #1e3a8a25, #0f172a);
        border: 1px solid #3b82f655;
        border-radius: 14px;
        padding: 20px;
        margin-bottom: 20px;
    }

    /* Status Badges */
    .badge-running {
        background-color: #065f46;
        color: #34d399;
        padding: 4px 12px;
        border-radius: 20px;
        font-size: 13px;
        font-weight: 700;
        border: 1px solid #059669;
    }
    .badge-stopped {
        background-color: #7f1d1d;
        color: #f87171;
        padding: 4px 12px;
        border-radius: 20px;
        font-size: 13px;
        font-weight: 700;
        border: 1px solid #b91c1c;
    }

    /* Live Pulse Indicator */
    .live-indicator {
        display: inline-flex;
        align-items: center;
        gap: 8px;
        background: #064e3b;
        color: #34d399;
        padding: 4px 12px;
        border-radius: 20px;
        font-size: 12px;
        font-weight: 700;
        border: 1px solid #059669;
    }
    .live-dot {
        width: 9px;
        height: 9px;
        background-color: #10b981;
        border-radius: 50%;
        display: inline-block;
        box-shadow: 0 0 0 rgba(16, 185, 129, 0.7);
        animation: pulse 1.5s infinite;
    }
    @keyframes pulse {
        0% { box-shadow: 0 0 0 0 rgba(16, 185, 129, 0.7); }
        70% { box-shadow: 0 0 0 8px rgba(16, 185, 129, 0); }
        100% { box-shadow: 0 0 0 0 rgba(16, 185, 129, 0); }
    }

    /* Scanner Card Styling */
    .scanner-card {
        background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%);
        border: 1px solid #334155;
        border-radius: 12px;
        padding: 16px;
        margin-bottom: 14px;
        transition: transform 0.2s, border-color 0.2s;
    }
    .scanner-card:hover {
        border-color: #3b82f6;
        transform: translateY(-2px);
    }
    .scanner-card-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 10px;
    }

    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
</style>
""", unsafe_allow_html=True)

dashboard_pwd_hash = os.environ.get("T4_DASHBOARD_PASSWORD_HASH", "").strip() or os.environ.get("DASHBOARD_PASSWORD_HASH", "").strip() or getattr(config, "dashboard_password_hash", "").strip()
if not dashboard_pwd_hash and getattr(config, "dashboard_password", ""):
    dashboard_pwd_hash = hashlib.sha256(config.dashboard_password.encode('utf-8')).hexdigest()

if dashboard_pwd_hash:
    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False
        
    if not st.session_state.authenticated:
        st.markdown("<div style='max-width: 400px; margin: 50px auto; padding: 30px; background: #1e293b; border-radius: 12px; border: 1px solid #334155; text-align: center;'>", unsafe_allow_html=True)
        st.markdown("<h2 style='color: #38bdf8; margin-bottom: 20px;'>🔒 تسجيل الدخول</h2>", unsafe_allow_html=True)
        pwd_input = st.text_input("كلمة المرور", type="password", label_visibility="collapsed", placeholder="أدخل كلمة المرور...")
        if st.button("دخول", type="primary", use_container_width=True):
            input_hash = hashlib.sha256(pwd_input.encode('utf-8')).hexdigest()
            if input_hash == dashboard_pwd_hash:
                st.session_state.authenticated = True
                st.rerun()
            else:
                st.error("كلمة المرور غير صحيحة!")
        st.markdown("</div>", unsafe_allow_html=True)
        st.stop()

@st.cache_resource
def get_engine():
    return TradingEngine()

engine = get_engine()

if "active_pair" not in st.session_state:
    st.session_state.active_pair = config.monitored_pairs[0] if config.monitored_pairs else "BTC/USDT"
if "auto_refresh_enabled" not in st.session_state:
    st.session_state.auto_refresh_enabled = True
if "refresh_interval_sec" not in st.session_state:
    st.session_state.refresh_interval_sec = 5

worker_running = get_worker_status()
worker_state = engine.get_worker_state()

top_c1, top_c2 = st.columns([6, 1])
with top_c1:
    st.markdown(f"""
    <div class="top-bar">
        <div>
            <h2 style="margin: 0; color: #f8fafc;">⚡ المركز الشامل للبوت الذكي (Universal AI Spot Trading Bot)</h2>
            <span style="color: #94a3b8; font-size: 14px;">
                المنصة النشطة: <b style="color: #38bdf8;">{config.exchange_id.upper()}</b> | 
                الوضع: <b style="color: {'#34d399' if config.is_paper_trading else '#f87171'};">{'محاكاة ورقية (Paper)' if config.is_paper_trading else 'تداول حقيقي (Live)'}</b> | 
                مزود الذكاء الاصطناعي: <b style="color: #fbbf24;">{AI_PRESETS.get(config.ai_provider, {}).get('name', config.ai_provider)} ({config.ai_model})</b>
            </span>
        </div>
    </div>
    """, unsafe_allow_html=True)
with top_c2:
    if dashboard_pwd_hash and st.session_state.get("authenticated", False):
        st.markdown("<div style='margin-top: 14px;'></div>", unsafe_allow_html=True)
        if st.button("🚪 خروج", use_container_width=True):
            st.session_state.authenticated = False
            st.rerun()

# Main Navigation Tabs
tab_live, tab_scanner, tab_ai_hub, tab_exchange, tab_telegram, tab_backtest, tab_settings = st.tabs([
    "📊 لوحة المتابعة والصفقات (Live)",
    "🎯 وكيل اقتناص الفرص (Scanner)",
    "🤖 مركز ربط أي ذكاء اصطناعي (AI Hub)",
    "🔌 ربط وفحص منصات التداول (Exchange API)",
    "📱 إشعارات تيليجرام (Telegram Alerts)",
    "🧪 الاختبار الرجعي (Backtest)",
    "⚙️ إعدادات التداول والأمان (Settings)"
])

# ==============================================================================
# TAB 1: LIVE DASHBOARD
# ==============================================================================
with tab_live:
    # 1. Quick Controls & Live Auto-Refresh Controller
    col_w1, col_w2, col_w3, col_w4 = st.columns([3, 2, 2, 2])
    with col_w1:
        if worker_running:
            st.markdown(f'<span class="badge-running">🟢 المحرك الآلي يعمل في الخلفية 24/7</span> &nbsp; <span style="color: #94a3b8; font-size: 12px;">(دورة: {worker_state.get("cycle_count", 0)})</span>', unsafe_allow_html=True)
        else:
            st.markdown('<span class="badge-stopped">🔴 المحرك الآلي متوقف</span>', unsafe_allow_html=True)
    with col_w2:
        if worker_running:
            if st.button("⏹️ إيقاف المحرك الآلي", use_container_width=True):
                stop_worker()
                st.rerun()
        else:
            if st.button("▶️ تشغيل المحرك الآلي 24/7", type="primary", use_container_width=True):
                start_worker()
                st.rerun()
    with col_w3:
        live_ref_toggle = st.toggle("🔴 بث مباشر وتحديث حي", value=st.session_state.auto_refresh_enabled, key="toggle_live_ref")
        if live_ref_toggle != st.session_state.auto_refresh_enabled:
            st.session_state.auto_refresh_enabled = live_ref_toggle
            st.rerun()
    with col_w4:
        ref_options = [3, 5, 10, 30]
        cur_ref_idx = ref_options.index(st.session_state.refresh_interval_sec) if st.session_state.refresh_interval_sec in ref_options else 1
        sel_interval = st.selectbox(
            "فترة التحديث اللحظي:",
            ref_options,
            index=cur_ref_idx,
            format_func=lambda s: f"كل {s} ثوانٍ" + (" ⚡" if s == 3 else ""),
            key="select_ref_interval"
        )
        if sel_interval != st.session_state.refresh_interval_sec:
            st.session_state.refresh_interval_sec = sel_interval
            st.rerun()

    # 2. Universal Coin Selection Section
    st.markdown("<div style='margin-top: 10px;'></div>", unsafe_allow_html=True)
    all_available_pairs = engine.get_available_spot_pairs()
    active_sym = st.session_state.active_pair
    if active_sym not in all_available_pairs:
        all_available_pairs = [active_sym] + all_available_pairs

    c_sel1, c_sel2, c_sel3 = st.columns([3, 2, 1])
    with c_sel1:
        picked_pair = st.selectbox(
            "اختر أي عملة للتحليل والمتابعة (Spot USDT):",
            all_available_pairs,
            index=all_available_pairs.index(active_sym) if active_sym in all_available_pairs else 0,
            key="universal_pair_picker"
        )
        if picked_pair != st.session_state.active_pair:
            st.session_state.active_pair = picked_pair
            st.rerun()
    with c_sel2:
        st.markdown("<div style='margin-top: 4px;'></div>", unsafe_allow_html=True)
        c_sym_txt, c_sym_btn = st.columns([3, 1])
        with c_sym_txt:
            custom_pair_txt = st.text_input("رمز العملة:", placeholder="مثال: DOGE أو PEPE", label_visibility="collapsed", key="txt_custom_pair")
        with c_sym_btn:
            if st.button("🔎 بحث", key="btn_validate_custom", use_container_width=True):
                if custom_pair_txt:
                    is_ok, norm_p, msg = engine.normalize_and_validate_pair(custom_pair_txt)
                    if is_ok:
                        st.session_state.active_pair = norm_p
                        st.toast(msg, icon="✅")
                        st.rerun()
                    else:
                        st.error(msg)
    with c_sel3:
        st.markdown("<div style='margin-top: 4px;'></div>", unsafe_allow_html=True)
        is_in_watchlist = st.session_state.active_pair in config.monitored_pairs
        star_title = "⭐ في المراقبة" if is_in_watchlist else "☆ + للمراقبة"
        if st.button(star_title, key="btn_toggle_watch", use_container_width=True, help="إضافة أو إزالة العملة من قائمة المراقبة التلقائية"):
            if is_in_watchlist:
                config.monitored_pairs.remove(st.session_state.active_pair)
                st.toast(f"تمت إزالة {st.session_state.active_pair} من قائمة المراقبة", icon="🗑️")
            else:
                config.monitored_pairs.append(st.session_state.active_pair)
                st.toast(f"تمت إضافة {st.session_state.active_pair} إلى قائمة المراقبة الدائمة ⭐", icon="✅")
            config.save_to_json()
            st.rerun()

    # Quick-select chips
    popular_chips = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "XRP/USDT", "DOGE/USDT", "PEPE/USDT", "SUI/USDT", "ADA/USDT", "NEAR/USDT", "AVAX/USDT"]
    chip_cols = st.columns(len(popular_chips))
    for idx, p_chip in enumerate(popular_chips):
        with chip_cols[idx]:
            is_cur = (p_chip == st.session_state.active_pair)
            if st.button(p_chip.replace("/USDT", ""), key=f"chip_btn_{p_chip}", type="primary" if is_cur else "secondary", use_container_width=True):
                st.session_state.active_pair = p_chip
                st.rerun()

    st.markdown("---")

    # 3. Real-Time Live Auto-Refresh Fragment
    frag_seconds = st.session_state.refresh_interval_sec if st.session_state.auto_refresh_enabled else None

    def safe_fragment(run_every=None):
        if hasattr(st, "fragment"):
            return st.fragment(run_every=run_every)
        def decorator(func):
            return func
        return decorator

    @safe_fragment(run_every=frag_seconds)
    def render_live_fragment():
        # Live updates
        live_portfolio = engine.get_portfolio_state()
        curr_active_pair = st.session_state.active_pair

        # Live header with indicator
        now_time_str = datetime.now().strftime("%H:%M:%S")
        c_lh1, c_lh2 = st.columns([3, 1])
        with c_lh1:
            st.markdown(f"### 📊 أداء المحفظة اللحظي")
        with c_lh2:
            if st.session_state.auto_refresh_enabled:
                st.markdown(f'<div style="text-align: left;"><span class="live-indicator"><span class="live-dot"></span> بث مباشر نشط ({now_time_str})</span></div>', unsafe_allow_html=True)
            else:
                st.markdown(f'<div style="text-align: left; color: #94a3b8; font-size: 13px;">تحديث يدوي ({now_time_str})</div>', unsafe_allow_html=True)

        # KPIs Row
        k1, k2, k3, k4, k5 = st.columns(5)
        with k1:
            st.markdown(f"""
            <div class="metric-card">
                <div class="metric-title">💵 رصيد USDT المتاح</div>
                <div class="metric-value">{live_portfolio['usdt_balance']:.2f}$</div>
            </div>
            """, unsafe_allow_html=True)
        with k2:
            st.markdown(f"""
            <div class="metric-card">
                <div class="metric-title">📊 القيمة الكلية للمحفظة</div>
                <div class="metric-value">{live_portfolio['total_equity']:.2f}$</div>
            </div>
            """, unsafe_allow_html=True)
        with k3:
            pnl_class = "metric-pnl-positive" if live_portfolio['total_pnl'] >= 0 else "metric-pnl-negative"
            sign = "+" if live_portfolio['total_pnl'] >= 0 else ""
            st.markdown(f"""
            <div class="metric-card">
                <div class="metric-title">📈 صافي الربح / الخسارة (PnL)</div>
                <div class="metric-value {pnl_class}">{sign}{live_portfolio['total_pnl']:.3f}$ ({sign}{live_portfolio['total_pnl_pct']:.2f}%)</div>
            </div>
            """, unsafe_allow_html=True)
        with k4:
            st.markdown(f"""
            <div class="metric-card">
                <div class="metric-title">🎯 نسبة نجاح الصفقات</div>
                <div class="metric-value">{live_portfolio['win_rate']:.1f}%</div>
            </div>
            """, unsafe_allow_html=True)
        with k5:
            st.markdown(f"""
            <div class="metric-card">
                <div class="metric-title">📦 صفقات (ربح / خسارة)</div>
                <div class="metric-value">{live_portfolio['wins']} رابحة / {live_portfolio['losses']} خاسرة</div>
            </div>
            """, unsafe_allow_html=True)

        # Market Selection & AI Live Insights
        st.markdown(f"### 🤖 تحليلات واستشارات الذكاء الاصطناعي لـ <span style='color: #38bdf8;'>{curr_active_pair}</span>", unsafe_allow_html=True)
        col_p_inf, col_at = st.columns([2, 2])
        with col_p_inf:
            curr_p_live = engine.get_current_price(curr_active_pair)
            live_price_display = f"{curr_p_live:.4f}$" if curr_p_live < 1 else f"{curr_p_live:.2f}$"
            st.markdown(f"**السعر الفوري اللحظي:** <span style='color: #38bdf8; font-size: 20px; font-weight: bold;'>{live_price_display}</span>", unsafe_allow_html=True)
        with col_at:
            auto_trade_toggle = st.checkbox(
                "⚡ تفعيل التنفيذ التلقائي الفوري لصفقات الشراء عند موافقة الذكاء الاصطناعي (Auto-Trade)",
                value=config.auto_trading_enabled,
                help="عند التفعيل، يقوم المحرك بالشراء تلقائياً عندما تكون الإشارة شراء مؤكد 🟢 بنسبة أمان عالية",
                key="chk_auto_trade_live"
            )
            if auto_trade_toggle != config.auto_trading_enabled:
                config.auto_trading_enabled = auto_trade_toggle
                config.save_to_json()
                st.toast("تم تحديث وضع التداول التلقائي!", icon="⚙️")

        # Fetch live candles & analyze with configured AI
        candles_df = engine.fetch_market_candles(curr_active_pair, timeframe=config.timeframe, limit=250)
        candles_df = drop_forming_candle(candles_df, config.timeframe)
        ai_res = UniversalAIClient.analyze_market_with_llm(
            candles_df=candles_df,
            pair=curr_active_pair,
            base_url=config.ai_base_url,
            api_key=config.ai_api_key,
            model_name=config.ai_model,
            take_profit_pct=config.take_profit_pct,
            stop_loss_pct=config.stop_loss_pct
        )
        if not candles_df.empty:
            engine.log_ai_analysis(curr_active_pair, ai_res)

        # Display AI Box
        st.markdown(f"""
        <div class="ai-box">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
                <h3 style="margin: 0; color: #60a5fa;">💡 إشارة الذكاء الاصطناعي: {ai_res.signal_arabic}</h3>
                <span style="background: #1e293b; padding: 6px 14px; border-radius: 20px; font-weight: bold; border: 1px solid #475569;">
                    السعر الحالي: <b>{ai_res.current_price:.2f}$</b> | مسار السوق: <b>{ai_res.market_sentiment}</b>
                </span>
            </div>
            <div style="margin-bottom: 14px; font-size: 16px; color: #e2e8f0; line-height: 1.6;">
                <b>ملخص الموقف:</b> {ai_res.arabic_summary}
            </div>
            <div style="background: rgba(15, 23, 42, 0.7); padding: 12px 16px; border-radius: 10px; border-right: 4px solid #3b82f6; margin-bottom: 14px;">
                <b>🎯 توجيه النظام:</b> {ai_res.detailed_advice}
            </div>
            <div style="display: flex; gap: 20px; font-size: 14px; color: #cbd5e1;">
                <div>🛡️ معدل الأمان: <b style="color: #10b981;">{ai_res.safety_score}%</b></div>
                <div>🔍 نسبة الثقة: <b style="color: #38bdf8;">{ai_res.confidence}%</b></div>
                <div>🎯 هدف الربح: <b style="color: #4ade80;">{ai_res.recommended_tp:.2f}$</b> (+{config.take_profit_pct}%)</div>
                <div>🛑 وقف الخسارة الأولي: <b style="color: #f87171;">{ai_res.recommended_sl:.2f}$</b> (-{config.stop_loss_pct}%)</div>
            </div>
        </div>
        """, unsafe_allow_html=True)

        # Reasons & Buy Button
        c_rea, c_btn = st.columns([3, 1])
        with c_rea:
            with st.expander("🔎 الأسباب والمؤشرات الفنية لقرار الذكاء الاصطناعي:"):
                for r in ai_res.reasons:
                    st.markdown(f"- {r}")
        with c_btn:
            open_pairs = [t['pair'] for t in engine.get_open_trades()]
            if curr_active_pair in open_pairs:
                st.warning(f"⚠️ توجد صفقة مفتوحة بالفعل لـ {curr_active_pair}")
            else:
                if st.button(f"🛒 تنفيذ صفقة شراء لـ {curr_active_pair}", key=f"btn_buy_{curr_active_pair}", type="primary", use_container_width=True):
                    current_time = time.time()
                    last_click = st.session_state.get("last_buy_click", 0)
                    if current_time - last_click < 3:
                        st.warning("⏳ يرجى الانتظار 3 ثوانٍ قبل تنفيذ صفقة جديدة لمنع التكرار.")
                    else:
                        st.session_state.last_buy_click = current_time
                        if not worker_running:
                            st.warning("شغّل المحرك الآلي أولاً")
                        elif live_portfolio['usdt_balance'] < config.trade_amount_usdt:
                            st.error("الرصيد المتاح غير كافٍ لفتح الصفقة!")
                        else:
                            cmd_id = engine.add_command('OPEN', pair=curr_active_pair, amount_usdt=config.trade_amount_usdt)
                            st.toast(f"تم إدراج أمر شراء لـ {curr_active_pair} (في الانتظار) ⏳", icon="📥")
                            st.rerun()

        # Chart Section
        if not candles_df.empty:
            st.markdown("### 📈 الرسم البياني التفاعلي اللحظي")
            fig = go.Figure()
            fig.add_trace(go.Candlestick(
                x=candles_df['datetime'],
                open=candles_df['open'], high=candles_df['high'],
                low=candles_df['low'], close=candles_df['close'],
                name=curr_active_pair,
                increasing_line_color='#10b981', decreasing_line_color='#ef4444'
            ))
            if 'ema_9' in candles_df:
                fig.add_trace(go.Scatter(x=candles_df['datetime'], y=candles_df['ema_9'], line=dict(color='#38bdf8', width=1.5), name='EMA 9'))
            if 'ema_21' in candles_df:
                fig.add_trace(go.Scatter(x=candles_df['datetime'], y=candles_df['ema_21'], line=dict(color='#f59e0b', width=1.5), name='EMA 21'))
            if 'ema_50' in candles_df:
                fig.add_trace(go.Scatter(x=candles_df['datetime'], y=candles_df['ema_50'], line=dict(color='#a855f7', width=1.5), name='EMA 50'))
            if 'bb_upper' in candles_df and 'bb_lower' in candles_df:
                fig.add_trace(go.Scatter(x=candles_df['datetime'], y=candles_df['bb_upper'], line=dict(color='rgba(255,255,255,0.2)', dash='dot'), name='BB Upper'))
                fig.add_trace(go.Scatter(x=candles_df['datetime'], y=candles_df['bb_lower'], line=dict(color='rgba(255,255,255,0.2)', dash='dot'), fill='tonexty', fillcolor='rgba(255,255,255,0.03)', name='BB Lower'))

            fig.update_layout(
                template="plotly_dark",
                paper_bgcolor="#0f172a", plot_bgcolor="#0f172a",
                height=420, margin=dict(l=20, r=20, t=30, b=20),
                xaxis_rangeslider_visible=False
            )
            st.plotly_chart(fig, use_container_width=True)

        # Active Open Trades
        st.markdown("### 📋 الصفقات المفتوحة حالياً")
        open_trades = engine.get_open_trades()
        if not open_trades:
            st.info("لا توجد صفقات مفتوحة حالياً. البوت في وضع المراقبة التلقائية لحماية رأس المال.")
        else:
            for t in open_trades:
                c1, c2, c3, c4, c5, c6 = st.columns([2, 2, 2, 2, 2, 2])
                pnl_val = t['pnl_pct']
                pnl_color = "#10b981" if pnl_val >= 0 else "#ef4444"
                pnl_sign = "+" if pnl_val >= 0 else ""
                with c1:
                    st.markdown(f"**الزوج:** {t['pair']}<br><span style='color: #94a3b8; font-size: 12px;'>دخول: {t['entry_time']}</span>", unsafe_allow_html=True)
                with c2:
                    st.markdown(f"**سعر الدخول:** {t['entry_price']:.2f}$<br>**السعر الحالي:** {t['current_price']:.2f}$", unsafe_allow_html=True)
                with c3:
                    st.markdown(f"**القيمة:** {t['cost']:.2f}$<br>**الكمية:** {t['amount']:.6f}", unsafe_allow_html=True)
                with c4:
                    st.markdown(f"**الربح اللحظي:**<br><span style='color: {pnl_color}; font-size: 18px; font-weight: bold;'>{pnl_sign}{t['pnl_amount']:.3f}$ ({pnl_sign}{pnl_val:.2f}%)</span>", unsafe_allow_html=True)
                with c5:
                    st.markdown(f"**الهدف:** {t['take_profit_price']:.2f}$<br>**الوقف المتحرك:** {t['trailing_stop_price']:.2f}$", unsafe_allow_html=True)
                with c6:
                    if st.button("❌ إغلاق يدوي فوري", key=f"close_{t['id']}", use_container_width=True):
                        engine.add_command('CLOSE', pair=t['pair'], trade_id=t['id'])
                        st.toast(f"تم إدراج أمر إغلاق صفقة #{t['id']} (في الانتظار) ⏳", icon="📥")
                        st.rerun()
                st.markdown("<hr style='margin: 8px 0; border-color: #334155;'>", unsafe_allow_html=True)

        # History Table
        st.markdown("### 📜 سجل الصفقات المكتملة")
        history = engine.get_trade_history(limit=25)
        if history:
            df_hist = pd.DataFrame(history)[[
                'pair', 'entry_price', 'exit_price', 'cost', 'pnl_amount', 'pnl_pct', 'exit_reason', 'entry_time', 'exit_time'
            ]]
            df_hist.columns = ['الزوج', 'الدخول', 'الخروج', 'التكلفة', 'صافي الربح', 'نسبة الربح %', 'سبب الخروج', 'وقت الدخول', 'وقت الخروج']
            df_hist['الدخول'] = df_hist['الدخول'].map(lambda x: f"{x:.2f}$")
            df_hist['الخروج'] = df_hist['الخروج'].map(lambda x: f"{x:.2f}$" if pd.notnull(x) else "-")
            df_hist['التكلفة'] = df_hist['التكلفة'].map(lambda x: f"{x:.2f}$")
            df_hist['صافي الربح'] = df_hist['صافي الربح'].map(lambda x: f"{x:+.3f}$")
            df_hist['نسبة الربح %'] = df_hist['نسبة الربح %'].map(lambda x: f"{x:+.2f}%")
            st.dataframe(df_hist, use_container_width=True, hide_index=True)
        else:
            st.caption("لم يتم إغلاق أي صفقات بعد.")

    render_live_fragment()

# ==============================================================================
# TAB 2: OPPORTUNITY SCANNER AGENT
# ==============================================================================
with tab_scanner:
    st.markdown("## 🎯 وكيل مسح واقتناص الفرص (Market Opportunity Scanner Agent)")
    st.markdown("""
    يقوم هذا الوكيل الذكي بمسح دوري لمجموعة واسعة من العملات في السوق اللحظي،
    ويقيس مؤشرات الزخم والسيولة ونقاط الانعكاس الفنية (RSI, EMA Trend, Bollinger Bands, Volume Surge)،
    ثم يقدم لك توصيات مصنفة بأفضل العملات المرشحة للتداول مع أهداف الربح ونقاط الأمان.
    """)

    scanner = MarketOpportunityScanner(engine)
    latest_results = MarketOpportunityScanner.get_latest_results()

    col_sc1, col_sc2, col_sc3 = st.columns([2, 1, 1])
    with col_sc1:
        time_since = MarketOpportunityScanner.get_time_since_last_scan()
        st.markdown(f"**حالة الوكيل:** 🟢 جاهز للمسح | آخر مسح: <b style='color: #38bdf8;'>{time_since}</b>", unsafe_allow_html=True)
    with col_sc2:
        scan_limit = st.selectbox("عدد العملات المراد مسحها:", [10, 15, 25, 40], index=1, key="scan_limit_select")
    with col_sc3:
        scan_now_btn = st.button("🔍 مسح واقتناص الفرص الآن", type="primary", use_container_width=True)

    if scan_now_btn or not latest_results:
        with st.spinner(f"جاري مسح واقتناص الفرص لأعلى {scan_limit} عملة في السوق..."):
            latest_results = scanner.scan_opportunities(max_pairs=scan_limit)

    if latest_results:
        st.markdown("### 🌟 أفضل الفرص الموصى بها حالياً (Top Recommended Trades)")
        top_picks = latest_results[:3]
        cols_top = st.columns(len(top_picks))
        for i, pick in enumerate(top_picks):
            with cols_top[i]:
                score_color = "#10b981" if pick['score'] >= 70 else ("#f59e0b" if pick['score'] >= 55 else "#ef4444")
                sign_str = "+" if pick['change_pct'] >= 0 else ""
                chg_color = "#10b981" if pick['change_pct'] >= 0 else "#ef4444"
                pick_price_str = f"{pick['price']:.4f}$" if pick['price'] < 1 else f"{pick['price']:.2f}$"
                
                st.markdown(f"""
                <div class="scanner-card" style="border-top: 4px solid {score_color};">
                    <div class="scanner-card-header">
                        <h3 style="margin: 0; color: #f8fafc;">{pick['pair']}</h3>
                        <span style="background: {score_color}22; color: {score_color}; padding: 4px 10px; border-radius: 12px; font-weight: bold; font-size: 14px; border: 1px solid {score_color}55;">
                            درجة الفرصة: {pick['score']}/100
                        </span>
                    </div>
                    <div style="font-size: 20px; font-weight: bold; color: #f8fafc; margin-bottom: 6px;">
                        {pick_price_str}
                        <span style="font-size: 13px; color: {chg_color};">({sign_str}{pick['change_pct']}%)</span>
                    </div>
                    <div style="color: #60a5fa; font-weight: bold; margin-bottom: 8px;">
                        {pick['signal_arabic']}
                    </div>
                    <div style="font-size: 13px; color: #cbd5e1; margin-bottom: 8px;">
                        {pick['action_advice']}
                    </div>
                    <hr style="border-color: #334155; margin: 8px 0;">
                    <div style="font-size: 12px; color: #94a3b8; line-height: 1.6;">
                        🎯 <b>الهدف:</b> <span style="color: #4ade80;">{pick['recommended_tp']}$</span> | 🛑 <b>الوقف:</b> <span style="color: #f87171;">{pick['recommended_sl']}$</span><br>
                        📊 <b>RSI:</b> {pick['rsi']} | <b>السيولة:</b> {pick.get('volume_ratio', 1.0)}x
                    </div>
                </div>
                """, unsafe_allow_html=True)

                if st.button(f"⚡ تداول فوري بـ {pick['pair']}", key=f"trade_pick_{pick['pair']}", use_container_width=True):
                    st.session_state.active_pair = pick['pair']
                    st.toast(f"تم اختيار {pick['pair']}! تم التبديل إلى لوحة المتابعة الحية.", icon="🎯")
                    st.rerun()

        st.markdown("### 📋 جدول نتائج فحص كافة العملات المفحوصة")
        df_scan = pd.DataFrame(latest_results)[[
            'pair', 'price', 'change_pct', 'rsi', 'score', 'signal_arabic', 'action_advice', 'recommended_tp', 'recommended_sl'
        ]]
        df_scan.columns = ['الزوج', 'السعر الحالي', 'التغير %', 'RSI', 'درجة الفرصة', 'التوصية', 'توجيه الوكيل', 'هدف الربح', 'وقف الخسارة']
        df_scan['السعر الحالي'] = df_scan['السعر الحالي'].map(lambda x: f"{x:.4f}$" if x < 1 else f"{x:.2f}$")
        df_scan['التغير %'] = df_scan['التغير %'].map(lambda x: f"{x:+.2f}%")
        df_scan['هدف الربح'] = df_scan['هدف الربح'].map(lambda x: f"{x:.4f}$" if x < 1 else f"{x:.2f}$")
        df_scan['وقف الخسارة'] = df_scan['وقف الخسارة'].map(lambda x: f"{x:.4f}$" if x < 1 else f"{x:.2f}$")
        st.dataframe(df_scan, use_container_width=True, hide_index=True)
    else:
        st.info("اضغط زر 'مسح واقتناص الفرص الآن' لبدء تشغيل الوكيل ومسح السوق.")

# ==============================================================================
# TAB 2: UNIVERSAL AI HUB
# ==============================================================================
with tab_ai_hub:
    st.markdown("## 🤖 مركز ربط أي نموذج ذكاء اصطناعي (Universal AI Hub)")
    st.markdown("""
    يتيح لك هذا القسم ربط **أي نموذج ذكاء اصطناعي من أي منصة** باستخدام بروتوكول OpenAI-Compatible REST API.
    يمكنك استخدام نماذج سحابية قوية مثل **DeepSeek، OpenRouter، Groq، OpenAI، Gemini** أو حتى نموذج محلي مجاني عبر **Ollama**.
    """)

    col_ai1, col_ai2 = st.columns([1, 1])

    with col_ai1:
        st.subheader("1. اختيار المزود أو التخصيص")
        provider_keys = list(AI_PRESETS.keys())
        current_idx = provider_keys.index(config.ai_provider) if config.ai_provider in provider_keys else 0
        
        selected_prov = st.selectbox(
            "اختر منصة / مزود الذكاء الاصطناعي:",
            provider_keys,
            format_func=lambda k: AI_PRESETS[k]['name'],
            index=current_idx
        )

        preset = AI_PRESETS[selected_prov]
        st.info(f"ℹ️ {preset['info']}")

        # Pre-fill defaults when changing preset, or use custom
        default_base = preset['base_url'] if selected_prov != "custom" else config.ai_base_url
        default_model = preset['default_model'] if selected_prov != "custom" else config.ai_model

        base_url_input = st.text_input(
            "رابط الخادم الأساسي (Base URL):",
            value=config.ai_base_url if config.ai_provider == selected_prov else default_base,
            help="مثال: https://api.deepseek.com/v1 أو https://openrouter.ai/api/v1 أو http://localhost:11434/v1"
        )

        api_key_input = st.text_input(
            "مفتاح الـ API الخاص بك (API Key):",
            value=config.ai_api_key,
            type="password",
            help="مفتاح الـ API للنموذج المختار (اتركه فارغاً إذا كنت تستخدم المحرك الكمي أو Ollama محلياً)"
        )

        model_name_input = st.text_input(
            "اسم النموذج (Model Name):",
            value=config.ai_model if config.ai_provider == selected_prov else default_model,
            help="مثال: deepseek-chat, gpt-4o-mini, gemini-2.0-flash, llama-3.3-70b-versatile"
        )

        if st.button("💾 حفظ إعدادات الذكاء الاصطناعي", type="primary", use_container_width=True):
            config.ai_provider = selected_prov
            config.ai_base_url = base_url_input.strip()
            config.ai_api_key = api_key_input.strip()
            config.ai_model = model_name_input.strip()
            config.save_to_json()
            st.success("✅ تم حفظ إعدادات الذكاء الاصطناعي بنجاح!")
            st.rerun()

    with col_ai2:
        st.subheader("2. فحص واختبار الاتصال بالنموذج")
        st.markdown("اضغط الزر أدناه لإرسال طلب حي إلى النموذج المختار والتحقق من صحة المفتاح وسرعة الاستجابة:")

        if st.button("🔍 فحص استجابة الذكاء الاصطناعي الآن (Test AI Model)", use_container_width=True):
            if selected_prov == "quant_builtin":
                st.success("✅ المحرك الكمي الداخلي جاهز ويعمل محلياً بدون أي مفاتيح بنسبة أمان 100%!")
            else:
                with st.spinner("جاري الاتصال بالنموذج وإرسال طلب الاختبار..."):
                    res = UniversalAIClient.test_connection(
                        base_url=base_url_input.strip(),
                        api_key=api_key_input.strip(),
                        model_name=model_name_input.strip()
                    )
                    if res.get("success"):
                        st.markdown(f"""
                        <div style="background: #064e3b; border: 1px solid #059669; border-radius: 10px; padding: 16px; margin-top: 10px;">
                            <h4 style="margin: 0; color: #34d399;">✅ تم الاتصال بالنموذج بنجاح تام!</h4>
                            <p style="margin: 8px 0; color: #f0fdf4;"><b>النموذج المجيب:</b> {res.get('model')}</p>
                            <p style="margin: 8px 0; color: #f0fdf4;"><b>زمن الاستجابة:</b> <span style="color: #a7f3d0; font-weight: bold;">{res.get('latency_ms')} ميلي ثانية ⚡</span></p>
                            <hr style="border-color: #059669; margin: 8px 0;">
                            <p style="margin: 0; color: #d1fae5;"><b>رد النموذج:</b> "{res.get('reply')}"</p>
                        </div>
                        """, unsafe_allow_html=True)
                    else:
                        st.error(f"❌ فشل الاتصال بالنموذج: {res.get('error')}")

        st.markdown("---")
        st.markdown("""
        #### 💡 روابط مساعدة للحصول على مفاتيح API مجانية:
        - **Google Gemini:** احصل على مفتاح مجاني فوري من [Google AI Studio](https://aistudio.google.com).
        - **Groq:** استجابة خارقة السرعة مجاناً من [Groq Console](https://console.groq.com).
        - **OpenRouter:** استكشف مئات النماذج المجانية والمدفوعة من [OpenRouter](https://openrouter.ai).
        - **DeepSeek:** احصل على مفتاح اقتصادي جداً من [DeepSeek Platform](https://platform.deepseek.com).
        """)

# ==============================================================================
# TAB 3: EXCHANGE API HUB
# ==============================================================================
with tab_exchange:
    st.markdown("## 🔌 ربط وفحص منصات التداول (Exchange API Hub)")
    st.markdown("""
    قم بإدخال مفاتيح الـ API الخاصة بحسابك في منصة التداول للبدء في التداول الحقيقي (Live Trading).
    """)

    col_ex1, col_ex2 = st.columns([1, 1])

    with col_ex1:
        st.subheader("1. إعدادات مفاتيح المنصة")
        supported_exchanges = ["bybit", "binance", "mexc", "kucoin", "gateio", "okx"]
        curr_ex_idx = supported_exchanges.index(config.exchange_id) if config.exchange_id in supported_exchanges else 0

        chosen_exchange = st.selectbox(
            "اختر المنصة:",
            supported_exchanges,
            index=curr_ex_idx,
            format_func=lambda x: x.upper()
        )

        ex_key_input = st.text_input("API Key:", value=config.api_key, type="password")
        ex_sec_input = st.text_input("API Secret:", value=config.api_secret, type="password")
        ex_pass_input = st.text_input("API Passphrase (اختياري - مطلوب لـ KuCoin/OKX):", value=config.api_passphrase, type="password")

        if st.button("💾 حفظ مفاتيح المنصة", type="primary", use_container_width=True):
            config.exchange_id = chosen_exchange
            config.api_key = ex_key_input.strip()
            config.api_secret = ex_sec_input.strip()
            config.api_passphrase = ex_pass_input.strip()
            config.save_to_json()
            st.success(f"✅ تم حفظ إعدادات {chosen_exchange.upper()} بنجاح!")
            st.rerun()

    with col_ex2:
        st.subheader("2. فحص الاتصال والتحقق من الرصيد الحقيقي")
        st.markdown("اضغط الزر أدناه للاتصال بحسابك في المنصة وجلب رصيد USDT الفعلي والتأكد من الصلاحيات:")

        if st.button("🔍 فحص الاتصال وجلب الرصيد الحقيقي (Test Connection)", use_container_width=True):
            with st.spinner(f"جاري الاتصال بـ {chosen_exchange.upper()} وجلب بيانات الحساب..."):
                res = TradingEngine.test_exchange_connection(
                    exchange_id=chosen_exchange,
                    api_key=ex_key_input.strip(),
                    api_secret=ex_sec_input.strip(),
                    passphrase=ex_pass_input.strip()
                )
                if res.get("success"):
                    st.markdown(f"""
                    <div style="background: #064e3b; border: 1px solid #059669; border-radius: 10px; padding: 16px; margin-top: 10px;">
                        <h4 style="margin: 0; color: #34d399;">✅ تم الاتصال بحساب {res.get('exchange')} بنجاح!</h4>
                        <hr style="border-color: #059669; margin: 10px 0;">
                        <p style="margin: 6px 0; color: #f0fdf4; font-size: 16px;">
                            💵 <b>رصيد USDT المتاح للتداول:</b> <span style="color: #6ee7b7; font-weight: bold; font-size: 20px;">{res.get('free_usdt'):.2f}$</span>
                        </p>
                        <p style="margin: 6px 0; color: #f0fdf4;">
                            🔒 <b>رصيد USDT المحجوز في الأوامر:</b> {res.get('used_usdt'):.2f}$ | <b>الإجمالي:</b> {res.get('total_usdt'):.2f}$
                        </p>
                    </div>
                    """, unsafe_allow_html=True)
                    if res.get('other_assets'):
                        st.markdown("**أصول أخرى متوفرة في الحساب:**")
                        st.json(res['other_assets'])
                else:
                    st.error(f"❌ فشل فحص الاتصال بالمنصة: {res.get('error')}")

        st.warning("""
        🛡️ **تنبيه أمان هام جداً:**
        عند إنشاء مفتاح الـ API في المنصة (Bybit أو Binance أو غيرها)، قم بتفعيل صلاحية **قراءة البيانات (Read) والتداول الفوري (Spot Trading)** فقط، و**تعطيل صلاحية السحب (Withdrawals Disabled)** لحماية أموالك بنسبة 100%.
        """)

    st.markdown("---")
    st.subheader("🤖 وكيل فحص واختبار ربط بايبيت والبث المباشر (Bybit Stream & Health Validator Agent)")
    st.markdown("""
    يقوم هذا الوكيل الذكي بإجراء فحص تشخيصي شامل ودقيق لسرعة اتصال خوادم Bybit، وصلاحيات الأمان لمفاتيح التداول،
    واتصال البث المباشر الحي عبر WebSocket، وقياس دقة الأسعار وتزامن التوقيت في أجزاء من الثانية.
    """)

    col_bh1, col_bh2 = st.columns([2, 1])
    with col_bh1:
        target_diag_sym = st.selectbox(
            "زوج البث المباشر للاختبار:",
            ["BTC/USDT", "ETH/USDT", "SOL/USDT", "XRP/USDT", "DOGE/USDT"],
            key="bybit_diag_sym"
        )
    with col_bh2:
        st.markdown("<div style='margin-top: 28px;'></div>", unsafe_allow_html=True)
        run_health_btn = st.button("🚀 تشغيل فحص الوكيل الشامل لبايبيت", type="primary", use_container_width=True)

    if run_health_btn:
        with st.spinner("جاري تشغيل وكيل الفحص واختبار الاتصال والبث المباشر..."):
            diag_res = BybitHealthValidatorAgent.run_full_diagnostic(
                pair=target_diag_sym,
                api_key=ex_key_input.strip() if 'ex_key_input' in locals() else config.api_key,
                api_secret=ex_sec_input.strip() if 'ex_sec_input' in locals() else config.api_secret
            )
            st.session_state.bybit_diagnostic_result = diag_res

    diag_result = st.session_state.get("bybit_diagnostic_result", None)
    if diag_result:
        score_val = diag_result['overall_score']
        score_badge = "#059669" if score_val >= 80 else ("#d97706" if score_val >= 60 else "#dc2626")
        st.markdown(f"""
        <div style="background: #0f172a; border: 1px solid {score_badge}; border-radius: 12px; padding: 16px; margin: 15px 0;">
            <div style="display: flex; justify-content: space-between; align-items: center;">
                <h3 style="margin: 0; color: #f8fafc;">📋 نتيجة التشخيص الشامل: {diag_result['overall_arabic']}</h3>
                <span style="background: {score_badge}; color: #ffffff; padding: 6px 16px; border-radius: 20px; font-weight: bold; font-size: 16px;">
                    درجة الكفاءة: {score_val}%
                </span>
            </div>
            <div style="color: #94a3b8; font-size: 13px; margin-top: 6px;">
                وقت الفحص: {diag_result['timestamp']} | زوج الاختبار: {diag_result['target_symbol']}
            </div>
        </div>
        """, unsafe_allow_html=True)

        cols_c = st.columns(len(diag_result['checks']))
        for i, chk in enumerate(diag_result['checks']):
            with cols_c[i]:
                chk_st = chk.get("status", "INFO")
                chk_color = "#10b981" if chk_st == "PASS" else ("#f59e0b" if chk_st == "WARN" else ("#3b82f6" if chk_st == "INFO" else "#ef4444"))
                icon = "✅" if chk_st == "PASS" else ("⚠️" if chk_st == "WARN" else ("ℹ️" if chk_st == "INFO" else "❌"))
                st.markdown(f"""
                <div style="background: #1e293b; border: 1px solid {chk_color}55; border-radius: 10px; padding: 14px; height: 100%;">
                    <div style="font-size: 14px; font-weight: bold; color: #f8fafc; margin-bottom: 6px;">
                        {icon} {chk['title']}
                    </div>
                    <div style="font-size: 13px; color: {chk_color}; margin-bottom: 6px; font-weight: bold;">
                        {chk.get('message', '')}
                    </div>
                    <div style="font-size: 11px; color: #94a3b8;">
                        {chk.get('details', '')}
                    </div>
                </div>
                """, unsafe_allow_html=True)

        if diag_result.get("raw_packet"):
            with st.expander("📦 فاحص حزمة البث المباشر اللحظية (Raw Live WebSocket Packet Inspector)"):
                st.markdown("هذه هي الحزمة اللحظية الحقيقية المستلمة مباشرة من خادم البث الفوري لبايبيت في هذه اللحظة:")
                st.json(diag_result["raw_packet"])

# ==============================================================================
# TAB: TELEGRAM ALERTS
# ==============================================================================
with tab_telegram:
    st.markdown("## 📱 إشعارات تيليجرام (Telegram Alerts)")
    st.markdown("احصل على إشعارات فورية بالصفقات الجديدة، الأرباح، الطوارئ، وتحديثات البوت مباشرة على تيليجرام.")
    
    col_t1, col_t2 = st.columns(2)
    with col_t1:
        st.subheader("1. إعدادات البوت")
        tel_enabled = st.toggle("تفعيل إشعارات تيليجرام", value=getattr(config, 'telegram_enabled', False))
        
        bot_token = st.text_input(
            "Bot Token (من @BotFather):", 
            value=getattr(config, 'telegram_bot_token', ''),
            type="password",
            help="قم بإنشاء بوت جديد عبر @BotFather في تيليجرام واحصل على الـ Token"
        )
        chat_id = st.text_input(
            "Chat ID (من @userinfobot):", 
            value=getattr(config, 'telegram_chat_id', ''),
            help="رقم المحادثة الخاص بك. يمكنك معرفته عبر محادثة @userinfobot"
        )
        
        if st.button("💾 حفظ إعدادات تيليجرام", type="primary", use_container_width=True):
            config.telegram_enabled = tel_enabled
            config.telegram_bot_token = bot_token.strip()
            config.telegram_chat_id = chat_id.strip()
            config.save_to_json()
            st.success("✅ تم حفظ إعدادات تيليجرام بنجاح!")
            st.rerun()
            
    with col_t2:
        st.subheader("2. فحص الاتصال")
        if st.button("🔍 إرسال رسالة اختبار", use_container_width=True):
            if not bot_token or not chat_id:
                st.error("❌ يرجى إدخال Bot Token و Chat ID أولاً!")
            else:
                with st.spinner("جاري إرسال رسالة الاختبار..."):
                    success, msg = TelegramNotifier.test_connection(bot_token.strip(), chat_id.strip())
                    if success:
                        st.success(f"✅ {msg}")
                    else:
                        st.error(f"❌ {msg}")
                        
        st.markdown("---")
        st.markdown("""
        #### 💡 كيف تحصل على الإعدادات؟
        1. ابحث عن **@BotFather** في تيليجرام وأرسل `/newbot`.
        2. اتبع الخطوات وانسخ الـ **API Token**.
        3. ابحث عن **@userinfobot** وأرسل أي رسالة لمعرفة الـ **ID** الخاص بك.
        4. **مهم جداً:** قم بإرسال أي رسالة (مثل "مرحبا") للبوت الذي أنشأته لكي يتمكن من مراسلتك!
        """)

# ==============================================================================
# TAB: BACKTEST
# ==============================================================================
with tab_backtest:
    st.markdown("## 🧪 الاختبار الرجعي (Backtest)")
    st.markdown("قم باختبار أداء استراتيجية الذكاء الاصطناعي على البيانات التاريخية قبل المخاطرة بأموال حقيقية.")
    
    bt_c1, bt_c2, bt_c3, bt_c4 = st.columns(4)
    with bt_c1:
        bt_pair = st.selectbox("الزوج:", config.monitored_pairs, key="bt_pair")
    with bt_c2:
        bt_candles = st.number_input("عدد الشموع التاريخية:", min_value=250, max_value=1000, value=250, step=50, key="bt_candles")
    with bt_c3:
        bt_balance = st.number_input("الرصيد الابتدائي ($):", min_value=10.0, max_value=10000.0, value=100.0, step=10.0, key="bt_balance")
    with bt_c4:
        bt_trade_size = st.number_input("حجم الصفقة ($):", min_value=1.0, max_value=1000.0, value=10.0, step=1.0, key="bt_trade_size")
        
    if st.button("▶️ تشغيل الاختبار الرجعي", type="primary", use_container_width=True):
        with st.spinner(f"جاري جلب آخر {bt_candles} شمعة لـ {bt_pair} وإجراء الاختبار..."):
            bt_df = engine.fetch_market_candles(bt_pair, timeframe=config.timeframe, limit=bt_candles)
            if bt_df.empty:
                st.error("❌ فشل في جلب البيانات التاريخية.")
            else:
                bt_results = BacktestEngine.run_backtest(
                    df=bt_df,
                    pair=bt_pair,
                    initial_balance=bt_balance,
                    trade_size=bt_trade_size,
                    take_profit_pct=config.take_profit_pct,
                    stop_loss_pct=config.stop_loss_pct,
                    trailing_stop_activation_pct=config.trailing_stop_activation_pct,
                    trailing_stop_callback_pct=config.trailing_stop_callback_pct
                )
                
                st.markdown("### 📊 نتائج الأداء (KPIs)")
                rk1, rk2, rk3, rk4, rk5 = st.columns(5)
                with rk1:
                    st.metric("نسبة النجاح (Win Rate)", f"{bt_results['win_rate']:.1f}%")
                with rk2:
                    st.metric("إجمالي الصفقات", str(bt_results['total_trades']))
                with rk3:
                    pnl_color = "normal" if bt_results['net_pnl'] >= 0 else "inverse"
                    st.metric("صافي الربح (Net PnL)", f"{bt_results['net_pnl']:+.2f}$", delta_color=pnl_color)
                with rk4:
                    st.metric("عامل الربح (Profit Factor)", f"{bt_results['profit_factor']:.2f}")
                with rk5:
                    st.metric("أقصى تراجع (Max Drawdown)", f"{bt_results['max_drawdown_pct']:.2f}%")
                    
                st.markdown("### 📋 تفاصيل الصفقات المحاكاة")
                if bt_results['trades']:
                    df_trades = pd.DataFrame(bt_results['trades'])
                    # Format dataframe for display
                    st.dataframe(df_trades, use_container_width=True, hide_index=True)
                else:
                    st.info("لم يتم تنفيذ أي صفقات خلال هذه الفترة.")

# ==============================================================================
# TAB 4: SETTINGS & AUTONOMOUS BOT
# ==============================================================================
with tab_settings:
    st.markdown("## ⚙️ إعدادات التداول وإدارة المخاطر")

    c_s1, c_s2 = st.columns(2)
    with c_s1:
        st.subheader("وضع التداول ورأس المال")
        mode_choice = st.radio(
            "اختر وضع التداول:",
            ["محاكاة ورقية بأموال تجريبية (Paper Trading) 🧪", "تداول حقيقي بأموالك الحقيقية (Live Trading) 🔴"],
            index=0 if config.is_paper_trading else 1
        )
        is_paper_val = "محاكاة" in mode_choice
        if is_paper_val != config.is_paper_trading:
            config.is_paper_trading = is_paper_val
            config.save_to_json()
            st.rerun()

        trade_size = st.number_input(
            "قيمة الصفقة الواحدة بالدولار (USDT):",
            min_value=0.5, max_value=1000.0, value=float(config.trade_amount_usdt), step=0.5,
            help="لرأس مال 4$، يمكنك ضبطه على 2.0$ لصفقتين، أو 4.0$ لصفقة واحدة"
        )
        max_trades = st.number_input("الحد الأقصى للصفقات المتزامنة:", min_value=1, max_value=5, value=int(config.max_open_trades))
        
        pairs_input = st.text_input("أزواج التداول المراقبة (مفصولة بفاصلة):", value=", ".join(config.monitored_pairs))
        dash_pwd = st.text_input("كلمة مرور لوحة التحكم (اتركها فارغة للإلغاء):", value=getattr(config, "dashboard_password", ""), type="password")

    with c_s2:
        st.subheader("إدارة المخاطر والوقف المتحرك (Trailing Stop)")
        tp_val = st.number_input("الربح المستهدف % (Take Profit):", min_value=0.5, max_value=25.0, value=float(config.take_profit_pct), step=0.1)
        sl_val = st.number_input("وقف الخسارة الأقصى % (Stop Loss):", min_value=0.5, max_value=10.0, value=float(config.stop_loss_pct), step=0.1)
        ts_act = st.number_input("نسبة تفعيل الوقف المتحرك %:", min_value=0.2, max_value=10.0, value=float(config.trailing_stop_activation_pct), step=0.1)
        ts_call = st.number_input("مسافة التراجع للوقف المتحرك %:", min_value=0.1, max_value=5.0, value=float(config.trailing_stop_callback_pct), step=0.1)
        risk_per_trade = st.number_input("نسبة المخاطرة لكل صفقة % (Risk Per Trade):", min_value=0.1, max_value=10.0, value=float(getattr(config, 'risk_per_trade_pct', 1.0)), step=0.1)
        daily_loss_limit = st.number_input("حد الخسارة اليومية الأقصى % (Daily Loss Limit):", min_value=0.5, max_value=20.0, value=float(getattr(config, 'daily_loss_limit_pct', 3.0)), step=0.5)
        max_consec_losses = st.number_input("أقصى عدد خسائر متتالية (Max Consecutive Losses):", min_value=1, max_value=10, value=int(getattr(config, 'max_consecutive_losses', 3)))
        cooldown_mins = st.number_input("فترة تهدئة الزوج بعد الخسارة (بالدقائق):", min_value=5, max_value=1440, value=int(getattr(config, 'pair_cooldown_minutes', 60)))
        max_api_errs = st.number_input("أقصى عدد أخطاء API في الساعة:", min_value=1, max_value=100, value=int(getattr(config, 'max_api_errors_per_hour', 10)))
        check_sec = st.number_input("فترة تكرار الفحص في الخلفية (بالثواني):", min_value=5, max_value=120, value=int(config.worker_interval_seconds))

    if st.button("💾 حفظ كافة إعدادات التداول والمخاطر", type="primary", use_container_width=True):
        config.trade_amount_usdt = trade_size
        config.max_open_trades = max_trades
        config.max_open_positions = max_trades
        config.monitored_pairs = [p.strip() for p in pairs_input.split(",") if p.strip()]
        config.take_profit_pct = tp_val
        config.stop_loss_pct = sl_val
        config.trailing_stop_activation_pct = ts_act
        config.trailing_stop_callback_pct = ts_call
        config.risk_per_trade_pct = risk_per_trade
        config.daily_loss_limit_pct = daily_loss_limit
        config.max_consecutive_losses = max_consec_losses
        config.pair_cooldown_minutes = cooldown_mins
        config.max_api_errors_per_hour = max_api_errs
        config.worker_interval_seconds = check_sec
        config.dashboard_password = dash_pwd.strip()
        if dash_pwd.strip():
            config.dashboard_password_hash = hashlib.sha256(dash_pwd.strip().encode('utf-8')).hexdigest()
        else:
            config.dashboard_password_hash = ""
        config.save_to_json()
        st.success("✅ تم حفظ إعدادات التداول والمخاطر بنجاح!")
        st.rerun()

    st.markdown("---")
    st.subheader("إجراءات الطوارئ والمحفظة")
    c_rst, c_kill = st.columns(2)
    with c_rst:
        if st.button("🔄 إعادة ضبط المحفظة التجريبية (4$)", use_container_width=True):
            engine.reset_paper_balance(4.0)
            st.toast("تمت إعادة تعيين الرصيد التجريبي إلى 4.00$ بنجاح!", icon="✅")
            st.rerun()
    with c_kill:
        if st.button("🚨 إيقاف طارئ وتسييل فوري لكافة الصفقات (Kill Switch)", type="primary", use_container_width=True):
            engine.add_command('KILL')
            st.toast("تم إدراج أمر التسييل الطارئ (Kill Switch) 🚨", icon="🚨")
            st.rerun()
