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
from backtest import BacktestEngine, walk_forward
from risk_manager import RiskConfig
from market_scanner import MarketOpportunityScanner
from bybit_health_agent import BybitHealthValidatorAgent

# Page Configuration
st.set_page_config(
    page_title="المركز الشامل للتداول الفوري الذكي | Universal AI Spot Bot",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Custom Styling for Modern Dark Theme & Native RTL Arabic (Responsive: Desktop + Mobile)
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Cairo:wght@400;600;700;900&display=swap');
    
    html, body, [class*="css"], .stMarkdown, .stText, h1, h2, h3, h4, h5, h6, .stSelectbox, .stTextInput, .stNumberInput {
        font-family: 'Cairo', sans-serif !important;
        direction: rtl;
        text-align: right;
    }

    /* ===== Desktop Baseline ===== */
    .block-container { padding-top: 1.6rem; padding-bottom: 2.5rem; }
    h1 { font-size: 1.7rem; font-weight: 800; }
    h2 { font-size: 1.35rem; font-weight: 700; margin-bottom: 0.8rem; }
    h3 { font-weight: 700; }
    hr { border-color: #2d3748; opacity: 0.6; }

    /* Top Bar Styling */
    .top-bar {
        background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%);
        border: 1px solid #334155;
        border-radius: 14px;
        padding: 16px 22px;
        margin-bottom: 20px;
        display: flex;
        justify-content: space-between;
        align-items: center;
        gap: 12px;
        flex-wrap: wrap;
    }

    /* Metric Cards */
    .metric-card {
        background: linear-gradient(135deg, #1e2638 0%, #151a28 100%);
        border: 1px solid #2d3748;
        border-radius: 14px;
        padding: 16px 20px;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.2);
        margin-bottom: 12px;
        transition: border-color 0.2s;
    }
    .metric-card:hover { border-color: #3b82f688; }
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
        line-height: 1.3;
        word-break: break-word;
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
        border-radius: 14px;
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
        gap: 8px;
        flex-wrap: wrap;
    }

    /* Tabs: horizontally swipeable on narrow screens */
    .stTabs [data-baseweb="tab-list"] {
        gap: 4px;
        overflow-x: auto;
        justify-content: flex-start;
        -webkit-overflow-scrolling: touch;
        scrollbar-width: thin;
    }
    .stTabs [data-baseweb="tab"] {
        white-space: nowrap;
        padding: 0.5rem 0.9rem;
        font-size: 0.92rem;
    }

    /* Dataframes & code blocks */
    [data-testid="stDataFrame"] { overflow-x: auto; }
    pre { font-size: 0.82rem; line-height: 1.5; }

    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}

    /* ================= MOBILE (phones) ================= */
    @media (max-width: 640px) {
        .block-container {
            padding-top: 0.8rem;
            padding-bottom: 2rem;
            padding-left: 0.5rem;
            padding-right: 0.5rem;
        }
        /* Stack all multi-column rows vertically for readability */
        div[data-testid="stHorizontalBlock"] {
            flex-wrap: wrap !important;
            row-gap: 10px !important;
        }
        div[data-testid="stHorizontalBlock"] > div[data-testid="stVerticalBlock"] {
            flex: 0 0 100% !important;
            max-width: 100% !important;
        }
        h1 { font-size: 1.3rem; }
        h2 { font-size: 1.15rem; }
        .top-bar { padding: 12px 14px; }
        .top-bar h2 { font-size: 1.15rem; }
        .metric-value { font-size: 19px; }
        .ai-box { padding: 14px; }
        .ai-box > div[style*="display: flex"] { flex-wrap: wrap; gap: 8px; }
        .scanner-card-header { flex-direction: column; align-items: flex-start; }
        .stTabs [data-baseweb="tab"] { font-size: 0.82rem; padding: 0.4rem 0.6rem; }
        div[data-testid="stButton"] > button { width: 100%; }
    }
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

def fmt_price(p):
    """تنسيق ذكي للأسعار (يدعم العملات الدقيقة مثل PEPE و BTC الكبير)"""
    try:
        p = float(p or 0)
    except Exception:
        return "-"
    if p <= 0:
        return "-"
    if p >= 1000:
        return f"{p:,.2f}"
    if p >= 1:
        return f"{p:,.4f}"
    s = f"{p:.10f}".rstrip("0").rstrip(".")
    return s

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
    "📊 المتابعة الحية",
    "🎯 اقتناص الفرص",
    "🤖 ربط الذكاء الاصطناعي",
    "🔌 ربط المنصة",
    "📱 تيليجرام",
    "🧪 الاختبار الرجعي",
    "⚙️ الإعدادات"
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

    # Quick-select chips (5×2 — readable on phones and desktops alike)
    popular_chips = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "XRP/USDT", "DOGE/USDT", "PEPE/USDT", "SUI/USDT", "ADA/USDT", "NEAR/USDT", "AVAX/USDT"]
    for row_start in range(0, len(popular_chips), 5):
        chip_cols = st.columns(5)
        for idx, p_chip in enumerate(popular_chips[row_start:row_start + 5]):
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
        # إعادة حساب حالة المحرك داخل الـ fragment (القيمة الأصلية على مستوى الصفحة قد تصبح قديمة)
        worker_running_live = get_worker_status()

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
            try:
                curr_p_live = engine.get_current_price(curr_active_pair)
            except Exception:
                curr_p_live = 0.0
            live_price_display = f"{curr_p_live:.4f}$" if (0 < curr_p_live < 1) else (f"{curr_p_live:.2f}$" if curr_p_live >= 1 else "غير متوفر")
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
        # ملاحظة: أي فشل شبكة (انقطاع إنترنت/حجب المنصة) لا يجب أن يسقط الصفحة — نتعامل معه بهدوء
        try:
            candles_df = engine.fetch_market_candles(curr_active_pair, timeframe=config.timeframe, limit=250)
        except Exception as fetch_err:
            candles_df = pd.DataFrame()
            st.error(f"⚠️ تعذر جلب بيانات {curr_active_pair} حالياً ({type(fetch_err).__name__}). سيتم إعادة المحاولة في التحديث القادم.")
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
        # تسجيل تحليلات الذكاء الاصطناعي مع كبح (فقط عند تغيّر الإشارة أو كل 5 دقائق) لتفادي تضخم قاعدة البيانات
        if not candles_df.empty:
            _ai_log_key = (curr_active_pair, ai_res.signal_arabic, ai_res.market_sentiment)
            _now_ts = time.time()
            _last_log = st.session_state.get("ai_log_state", {})
            if _last_log.get("key") != _ai_log_key or _now_ts - _last_log.get("ts", 0.0) > 300:
                try:
                    engine.log_ai_analysis(curr_active_pair, ai_res)
                    st.session_state["ai_log_state"] = {"key": _ai_log_key, "ts": _now_ts}
                except Exception:
                    pass

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
                        if not worker_running_live:
                            st.warning("شغّل المحرك الآلي أولاً")
                        elif live_portfolio['usdt_balance'] < config.trade_amount_usdt:
                            st.error("الرصيد المتاح غير كافٍ لفتح الصفقة!")
                        else:
                            cmd_id = engine.add_command('OPEN', pair=curr_active_pair, amount_usdt=config.trade_amount_usdt)
                            st.toast(f"تم إدراج أمر شراء لـ {curr_active_pair} (في الانتظار) ⏳", icon="📥")
                            st.rerun()

        # حالة أوامر الواجهة الأخيرة (PENDING / DONE / FAILED)
        try:
            recent_cmds = engine.get_recent_commands(limit=6)
        except Exception:
            recent_cmds = []
        if recent_cmds:
            with st.expander("📨 حالة أوامر الواجهة (آخر 6 أوامر)"):
                type_map = {"OPEN": "فتح شراء 🛒", "CLOSE": "إغلاق صفقة ❌", "KILL": "تسييل طارئ 🚨"}
                status_map = {"PENDING": "⏳ قيد الانتظار", "DONE": "✅ تم التنفيذ", "FAILED": "❌ فشل"}
                cmd_rows = []
                for c in sorted(recent_cmds, key=lambda x: x["id"]):
                    cmd_rows.append({
                        "الوقت": c["created_at"],
                        "النوع": type_map.get(c["type"], c["type"]),
                        "الزوج": c.get("pair") or "-",
                        "القيمة $": f"{c['amount_usdt']:.2f}" if c.get("amount_usdt") else "-",
                        "الحالة": status_map.get(c["status"], c["status"]),
                        "النتيجة": c.get("result") or "-",
                    })
                st.dataframe(pd.DataFrame(cmd_rows), use_container_width=True, hide_index=True)
                latest_cmd = max(recent_cmds, key=lambda x: x["id"])
                if latest_cmd["status"] == "FAILED":
                    st.error(f"❌ آخر أمر فشل: {latest_cmd.get('result') or 'السبب غير معروف'}")
                elif latest_cmd["status"] == "DONE":
                    st.success(f"✅ آخر أمر نُفذ بنجاح: {latest_cmd.get('result') or ''}")

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
                c1, c2, c3 = st.columns([2, 2, 2])
                pnl_val = t['pnl_pct']
                pnl_color = "#10b981" if pnl_val >= 0 else "#ef4444"
                pnl_sign = "+" if pnl_val >= 0 else ""
                with c1:
                    st.markdown(f"<div class='metric-card'><div class='metric-title'>🪙 الزوج</div><div style='font-size: 18px; font-weight: 700;'>{t['pair']}</div><div style='color: #94a3b8; font-size: 12px; margin-top: 4px;'>دخول: {t['entry_time']}</div></div>", unsafe_allow_html=True)
                with c2:
                    st.markdown(f"<div class='metric-card'><div class='metric-title'>💲 الأسعار</div><div style='font-size: 15px;'>الدخول: <b>{fmt_price(t['entry_price'])}$</b> ← الحالي: <b>{fmt_price(t['current_price'])}$</b></div><div style='color: #94a3b8; font-size: 12px; margin-top: 4px;'>القيمة: {t['cost']:.2f}$ | الكمية: {t['amount']:.6f}</div></div>", unsafe_allow_html=True)
                with c3:
                    st.markdown(f"<div class='metric-card'><div class='metric-title'>📈 الربح اللحظي</div><div style='color: {pnl_color}; font-size: 18px; font-weight: bold;'>{pnl_sign}{t['pnl_amount']:.3f}$ ({pnl_sign}{pnl_val:.2f}%)</div><div style='color: #94a3b8; font-size: 12px; margin-top: 4px;'>🎯 الهدف: {fmt_price(t['take_profit_price'])}$ | 🛡️ المتحرك: {fmt_price(t['trailing_stop_price'])}$</div></div>", unsafe_allow_html=True)
                close_bar = st.container()
                with close_bar:
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

    # المسح يتم فقط عند الضغط على الزر (تجنب تحميل الصفحة أول مرة بمسح شبكة كامل)
    if scan_now_btn:
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
    st.markdown("## 🧪 الاختبار الرجعي الواقعي (Realistic Backtest)")
    st.markdown("قم باختبار أداء الاستراتيجية الكمية وإدارة المخاطر بنفس الكود الفعلي وحساب الرسوم والانزلاق السعري.")

    bt_c1, bt_c2, bt_c3, bt_c4, bt_c5 = st.columns(5)
    with bt_c1:
        bt_pair = st.selectbox("الزوج:", config.monitored_pairs if config.monitored_pairs else ["BTC/USDT"], key="bt_pair")
    with bt_c2:
        bt_candles = st.number_input("عدد الشموع (5m):", min_value=250, max_value=5000, value=3000, step=250, key="bt_candles")
    with bt_c3:
        bt_balance = st.number_input("الرصيد الابتدائي ($):", min_value=10.0, max_value=100000.0, value=100.0, step=10.0, key="bt_balance")
    with bt_c4:
        bt_fee = st.number_input("نسبة الرسوم %:", min_value=0.0, max_value=1.0, value=0.1, step=0.01, key="bt_fee") / 100.0
    with bt_c5:
        bt_slippage = st.number_input("نسبة الانزلاق %:", min_value=0.0, max_value=1.0, value=0.05, step=0.01, key="bt_slippage") / 100.0

    c_bt_btn1, c_bt_btn2 = st.columns(2)
    with c_bt_btn1:
        run_bt_btn = st.button("▶️ تشغيل الاختبار الرجعي", type="primary", use_container_width=True)
    with c_bt_btn2:
        run_wf_btn = st.button("🔄 تشغيل تحليل Walk-Forward (4 أجزاء)", use_container_width=True)

    st.caption("💡 لحفظ بيانات تاريخية (3000 شمعة 5m + 1000 شمعة 1h) واختبار رجعي أسرع: شغّل `python tools/fetch_history.py BTC/USDT` — تُحفظ في مجلد `data/` وتُحمَّل تلقائياً.")

    # Function to get LTF and HTF data
    def get_backtest_data(pair, candles_limit):
        clean_sym = pair.replace("/", "_")
        # مسار مطلق يعتمد على مجلد المشروع (لا يعتمد على مجلد التشغيل الحالي)
        data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
        file_5m = os.path.join(data_dir, f"{clean_sym}_5m.csv")
        file_1h = os.path.join(data_dir, f"{clean_sym}_1h.csv")

        df_ltf = None
        df_htf = None

        if os.path.exists(file_5m):
            try:
                df_ltf = pd.read_csv(file_5m)
            except Exception:
                pass
        if os.path.exists(file_1h):
            try:
                df_htf = pd.read_csv(file_1h)
            except Exception:
                pass

        # عند غياب ملفات CSV: جلب بالتصفح (Pagination) لتجاوز حد الطلب الواحد (1000 شمعة)
        if df_ltf is None or df_ltf.empty:
            try:
                df_ltf = engine.fetch_history_candles(pair, timeframe="5m", limit=int(candles_limit))
            except Exception as e:
                st.warning(f"تعذر الجلب المتصفح لشموع 5m: {e}. جرّب حفظ البيانات عبر: python tools/fetch_history.py {pair}")
                df_ltf = pd.DataFrame()
        if df_htf is None or df_htf.empty:
            try:
                df_htf = engine.fetch_history_candles(pair, timeframe="1h", limit=max(300, int(candles_limit) // 3))
            except Exception:
                df_htf = pd.DataFrame()

        return df_ltf, df_htf

    if run_bt_btn or run_wf_btn:
        with st.spinner(f"جاري تجهيز البيانات وإجراء المحاكاة لـ {bt_pair}..."):
            df_ltf, df_htf = get_backtest_data(bt_pair, bt_candles)

            if df_ltf is None or df_ltf.empty:
                st.error("❌ فشل في جلب بيانات الاختبار الرجعي.")
            else:
                risk_c = RiskConfig(
                    risk_per_trade_pct=getattr(config, 'risk_per_trade_pct', 1.0),
                    daily_loss_limit_pct=getattr(config, 'daily_loss_limit_pct', 3.0),
                    max_consecutive_losses=getattr(config, 'max_consecutive_losses', 3)
                )

                if run_bt_btn:
                    bt_results = BacktestEngine.run_backtest(
                        df_ltf=df_ltf,
                        df_htf=df_htf,
                        initial_balance=bt_balance,
                        fee_pct=bt_fee,
                        slippage_pct=bt_slippage,
                        risk_cfg=risk_c,
                        strategy_cfg=config,
                        pair=bt_pair
                    )

                    st.markdown("### 📊 نتائج الأداء المتقدمة (Realistic KPIs)")
                    k1, k2, k3, k4 = st.columns(4)
                    with k1:
                        st.metric("إجمالي الصفقات (Total Trades)", str(bt_results['total_trades']))
                    with k2:
                        st.metric("نسبة النجاح (Win Rate)", f"{bt_results['win_rate']:.1f}%")
                    with k3:
                        pnl_color = "normal" if bt_results['net_pnl'] >= 0 else "inverse"
                        st.metric("صافي الربح (Net PnL)", f"{bt_results['net_pnl']:+.4f}$ ({bt_results['net_pnl_pct']:+.2f}%)", delta_color=pnl_color)
                    with k4:
                        st.metric("معامل الربحية (Profit Factor)", f"{bt_results['profit_factor']:.2f}")

                    k5, k6, k7, k8 = st.columns(4)
                    with k5:
                        st.metric("أقصى تراجع (Max Drawdown)", f"{bt_results['max_drawdown_pct']:.2f}%")
                    with k6:
                        st.metric("عائد الصفقة (Expectancy)", f"{bt_results['expectancy_per_trade']:+.4f}$")
                    with k7:
                        st.metric("متوسط R:R", f"{bt_results['avg_rr']:.2f}")
                    with k8:
                        st.metric("إجمالي الرسوم (Fees Paid)", f"{bt_results['fees_paid']:.4f}$")

                    st.markdown("### 📋 سجل الصفقات المنفذة في المحاكاة")
                    if bt_results['trades']:
                        df_trades = pd.DataFrame(bt_results['trades'])
                        st.dataframe(df_trades, use_container_width=True, hide_index=True)
                    else:
                        st.info("لم يتم تنفيذ أي صفقات خلال هذه الفترة الزمنية.")

                elif run_wf_btn:
                    wf_res = walk_forward(
                        df_ltf=df_ltf,
                        df_htf=df_htf,
                        n_splits=4,
                        initial_balance=bt_balance,
                        fee_pct=bt_fee,
                        slippage_pct=bt_slippage,
                        risk_cfg=risk_c,
                        strategy_cfg=config,
                        pair=bt_pair
                    )

                    st.markdown("### 🔄 نتائج تحليل Walk-Forward (4 أجزاء متتالية)")
                    if wf_res.get("unstable_warning"):
                        st.error("⚠️ تحذير: الاستراتيجية غير مستقرة (الربح الصافي سالب في أكثر من نصف الأجزاء)")
                    else:
                        st.success("✅ الاستراتيجية مستقرة عبر الفترات الزمنية الاختيارية.")

                    if wf_res.get("splits"):
                        df_wf = pd.DataFrame(wf_res["splits"])
                        df_wf.columns = ['الجزء', 'تاريخ البداية', 'تاريخ النهاية', 'الصفقات', 'نسبة النجاح %', 'صافي الربح ($)', 'معامل الربحية', 'أقصى تراجع %', 'الرسوم ($)']
                        st.dataframe(df_wf, use_container_width=True, hide_index=True)

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
            if not is_paper_val:
                st.error("⚠️ أنت على وشك التحويل إلى **التداول الحقيقي بأموالك الفعلية**. تأكد من: (1) إدخال مفاتيح API بصلاحية Spot فقط بدون سحب، (2) تجربة الوضع على Testnet أولاً.")
            confirm_c1, confirm_c2 = st.columns(2)
            if confirm_c1.button("✅ تأكيد تغيير وضع التداول", use_container_width=True):
                config.is_paper_trading = is_paper_val
                config.save_to_json()
                st.rerun()
            if confirm_c2.button("↩️ إلغاء والبقاء على الوضع الحالي", use_container_width=True):
                st.rerun()

        use_testnet_val = st.toggle(
            "استخدام بيئة التجربة (Testnet Sandbox) للتداول الحقيقي",
            value=bool(getattr(config, "use_testnet", False)),
            help="عند التفعيل تُوجَّه أوامر التداول الحقيقي إلى testnet.bybit.com بدل الحساب الفعلي. احصل على مفاتيح testnet من testnet.bybit.com. يُطبق التغيير بعد إعادة التشغيل."
        )
        if use_testnet_val != bool(getattr(config, "use_testnet", False)):
            config.use_testnet = use_testnet_val
            config.save_to_json()
            st.toast("تم تحديث وضع Testnet (يُطبق بعد إعادة التشغيل)", icon="⚙️")

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

        st.markdown("---")
        st.markdown("**إعدادات الاستراتيجية (نظام السوق + ATR):**")
        _htf_options = ["1h", "2h", "4h"]
        htf_tf_choice = st.selectbox(
            "فريم التحليل الأعلى HTF (تحديد نظام السوق):",
            _htf_options,
            index=_htf_options.index(config.htf_timeframe) if config.htf_timeframe in _htf_options else 0,
            key="htf_tf_select"
        )
        atr_stop_mult_val = st.number_input("مسافة وقف الخسارة من إشارة الدخول (× ATR):", min_value=0.2, max_value=5.0, value=float(config.atr_stop_mult), step=0.1)
        atr_tp_mult_val = st.number_input("مسافة الهدف من إشارة الدخول (× ATR):", min_value=0.5, max_value=10.0, value=float(config.atr_tp_mult), step=0.1)
        min_rr_val = st.number_input("أدنى نسبة عائد/مخاطرة R:R مقبولة:", min_value=0.5, max_value=5.0, value=float(config.min_rr), step=0.1)
        trail_act_atr_val = st.number_input("تفعيل الوقف المتحرك عند ربح (× ATR):", min_value=0.2, max_value=5.0, value=float(config.trail_activation_atr), step=0.1)
        trail_dist_atr_val = st.number_input("مسافة الوقف المتحرك عن قمة السعر (× ATR):", min_value=0.2, max_value=5.0, value=float(config.trail_distance_atr), step=0.1)

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
        config.htf_timeframe = htf_tf_choice
        config.atr_stop_mult = atr_stop_mult_val
        config.atr_tp_mult = atr_tp_mult_val
        config.min_rr = min_rr_val
        config.trail_activation_atr = trail_act_atr_val
        config.trail_distance_atr = trail_dist_atr_val
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

    # ------------------------------------------------------------------
    # قسم التشخيص والسجل التقني: انسخ التقرير وأرسله للذكاء الاصطناعي عند أي خطأ
    # ------------------------------------------------------------------
    st.markdown("---")
    st.subheader("🩺 التشخيص والسجل التقني (Diagnostics & Logs)")
    st.caption("إذا حدث أي خطأ أو سلوك غير متوقع: ولّد التقرير التشخيصي وانسخه كاملاً (زر النسخ أعلى صندوق النص) وأرسله لأي نموذج ذكاء اصطناعي — سيشخّص لك المشكلة بدقة.")

    _app_dir = os.path.dirname(os.path.abspath(__file__))

    def _read_log_tail(name, n=60):
        path = os.path.join(_app_dir, name)
        if not os.path.exists(path):
            return f"(الملف غير موجود: {name})"
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
            tail = "".join(lines[-n:]).rstrip()
            return tail if tail else "(الملف فارغ)"
        except Exception as e:
            return f"(تعذر القراءة: {e})"

    def _read_log_errors(names, n=25):
        out = []
        for name in names:
            path = os.path.join(_app_dir, name)
            if not os.path.exists(path):
                continue
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    lines = f.readlines()
            except Exception:
                continue
            errs = [ln.rstrip() for ln in lines if ("| ERROR " in ln) or ("| CRITICAL " in ln) or ("Traceback" in ln) or ln.startswith("  File ")]
            if errs:
                out.append(f"--- {name} (آخر {min(n, len(errs))} خطأ) ---")
                out.extend(errs[-n:])
        return "\n".join(out) if out else "✅ لا توجد أخطاء (ERROR/CRITICAL/Traceback) في السجلات."

    def build_diagnostic_report():
        import platform
        L = []
        L.append("=" * 62)
        L.append("T4crte Smart Bot — Full Diagnostic Report (تقرير تشخيصي كامل)")
        L.append(f"وقت توليد التقرير: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        L.append("=" * 62)
        L.append("")
        L.append("[1] بيئة التشغيل (Runtime)")
        L.append(f"    Python: {platform.python_version()} | OS: {platform.platform()} | Streamlit: {st.__version__}")
        L.append("")
        L.append("[2] وضع التشغيل (Mode)")
        L.append(f"    وضع التداول: {'PAPER (محاكاة ورقية)' if config.is_paper_trading else 'LIVE (أموال حقيقية!)'}")
        L.append(f"    Testnet: {'مفعّل' if bool(getattr(config, 'use_testnet', False)) else 'معطّل'}")
        L.append(f"    المنصة: {config.exchange_id} | مفاتيح API: {'مدخلة' if config.api_key else 'غير مدخلة'}")
        L.append(f"    التداول التلقائي: {'مفعّل' if config.auto_trading_enabled else 'معطّل'} | الفترة: {config.timeframe} | HTF: {config.htf_timeframe}")
        L.append(f"    AI: {config.ai_provider} / {config.ai_model} | Telegram: {'مفعّل' if getattr(config, 'telegram_enabled', False) else 'معطّل'}")
        L.append("")
        L.append("[3] إعدادات المخاطرة والاستراتيجية (Risk & Strategy)")
        L.append(f"    قيمة الصفقة: ${config.trade_amount_usdt} | أقصى متزامن: {config.max_open_trades} | الأزواج: {', '.join(config.monitored_pairs)}")
        L.append(f"    TP: {config.take_profit_pct}% | SL: {config.stop_loss_pct}% | Risk/trade: {getattr(config, 'risk_per_trade_pct', 1.0)}% | حد يومي: {getattr(config, 'daily_loss_limit_pct', 3.0)}%")
        L.append(f"    ATR: وقف ×{config.atr_stop_mult} | هدف ×{config.atr_tp_mult} | أدنى R:R: {config.min_rr} | متحرك: تفعيل ×{config.trail_activation_atr} / مسافة ×{config.trail_distance_atr}")
        L.append(f"    أقصى خسائر متتالية: {getattr(config, 'max_consecutive_losses', 3)} | تهدئة الزوج: {getattr(config, 'pair_cooldown_minutes', 60)} دقيقة | حد أخطاء API/ساعة: {getattr(config, 'max_api_errors_per_hour', 10)} | دورة الفحص: كل {config.worker_interval_seconds} ث")
        L.append("")
        L.append("[4] حالة المحرك (Worker & Kill Switch)")
        _ws = worker_state or {}
        L.append(f"    يعمل الآن: {'نعم' if worker_running else 'لا'} | عدد الدورات: {_ws.get('cycle_count', '?')} | آخر نبضة: {_ws.get('last_heartbeat', '?')}")
        L.append(f"    آخر رسالة: {_ws.get('last_message') or 'لا يوجد'}")
        try:
            L.append(f"    Kill Switch: {'⚠️ مفعل (لن تُفتح صفقات جديدة!)' if engine.risk_manager.kill_switch else 'غير مفعل'}")
        except Exception:
            L.append("    Kill Switch: (تعذر جلب الحالة)")
        L.append("")
        L.append("[5] المحفظة (Portfolio)")
        try:
            pf = engine.get_portfolio_state()
            L.append(f"    USDT متاح: {pf['usdt_balance']:.2f}$ | إجمالي: {pf['total_equity']:.2f}$ | صافي PnL: {pf['total_pnl']:+.3f}$ ({pf['total_pnl_pct']:+.2f}%)")
            L.append(f"    صفقات مفتوحة: {len(engine.get_open_trades())} | نسبة النجاح: {pf['win_rate']:.1f}%")
        except Exception as e:
            L.append(f"    (تعذر جلب المحفظة: {e})")
        L.append("")
        L.append("[6] آخر أوامر الواجهة (Commands)")
        try:
            cmds = engine.get_recent_commands(limit=5)
            if cmds:
                for c in sorted(cmds, key=lambda x: x["id"]):
                    L.append(f"    #{c['id']} {c['type']} | {c['status']} | {c.get('result') or '-'} | {c['created_at']}")
            else:
                L.append("    (لا توجد أوامر)")
        except Exception as e:
            L.append(f"    (تعذر الجلب: {e})")
        L.append("")
        L.append("[7] آخر أسطر السجل (trading.log — آخر 40)")
        L.append(_read_log_tail("trading.log", 40))
        L.append("")
        L.append("[8] آخر الأخطاء (trading.log + worker.log)")
        L.append(_read_log_errors(["trading.log", "worker.log"], 25))
        L.append("")
        L.append("=" * 62)
        L.append("تعليمات: أرسل هذا التقرير كاملاً للذكاء الاصطناعي مع وصف مختصر للمشكلة التي تواجهها.")
        return "\n".join(L)

    with st.expander("📋 التقرير التشخيصي الكامل (ولّد ← انسخ ← أرسل للذكاء الاصطناعي)"):
        st.markdown("يشمل التقرير: وضع التشغيل، إعدادات المخاطرة، حالة المحرك والـ Kill Switch، المحفظة، آخر الأوامر، وذيل السجلات والأخطاء — كل ما يحتاجه أي مهندس أو نموذج ذكاء اصطناعي لتشخيص المشكلة.")
        if st.button("⚙️ توليد التقرير التشخيصي", type="primary", use_container_width=True):
            st.session_state["diag_report"] = build_diagnostic_report()
            st.rerun()
        _rep = st.session_state.get("diag_report")
        if _rep:
            st.code(_rep, language="text")
            st.caption("💡 اضغط زر النسخ أعلى الصندوق لنسخ التقرير كاملاً، ثم ألصقه في محادثة الذكاء الاصطناعي.")

    with st.expander("📄 السجل الحي المباشر (آخر 60 سطراً)"):
        _lg1, _lg2 = st.tabs(["📁 trading.log (المحرك)", "📁 worker.log (العامل الخلفي)"])
        with _lg1:
            st.code(_read_log_tail("trading.log", 60), language="text")
        with _lg2:
            st.code(_read_log_tail("worker.log", 60), language="text")
