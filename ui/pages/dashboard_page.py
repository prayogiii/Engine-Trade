"""
Dashboard page — hero, capabilities, performance metrics, learning engine,
quick start, recent signals, top brokers, IHSG snapshot, footer.
"""
from __future__ import annotations

import json
from datetime import datetime

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import yfinance as yf
PLOTLY_AVAILABLE = True
try:
    import plotly.graph_objects as go
except ImportError:
    PLOTLY_AVAILABLE = False
from config.brokers import get_broker_label
from core.bandarmology import klasifikasi_broker
from core.riwayat import hitung_statistik_riwayat_actual
from services.yfinance_client import load_ihsg_data
from services.sheets_client import get_broksum_cache, get_signal_outcomes_stats


# ═══════════════════════════════════════════════════════════════
# PUBLIC API
# ═══════════════════════════════════════════════════════════════
@st.cache_data(ttl=300, show_spinner=False)
def _cached_signal_stats():
    return get_signal_outcomes_stats()
def render_dashboard_page():
    """Render halaman awal (sebelum analisis / scan)."""
    # HERO SECTION
    st.markdown("""
    <div style="
        background: linear-gradient(135deg, #0f1116 0%, #1a1d24 50%, #0f1116 100%);
        border: 1px solid #262626;
        border-radius: 20px;
        padding: 48px 40px 44px 40px;
        margin: 8px 0 24px 0;
        position: relative;
        overflow: hidden;
    ">
        <div style="position: absolute; top: -50%; right: -10%;
            width: 500px; height: 500px;
            background: radial-gradient(circle, rgba(0,255,204,0.08) 0%, transparent 70%);
            border-radius: 50%; pointer-events: none;"></div>
        <div style="position: absolute; bottom: -60%; left: -5%;
            width: 400px; height: 400px;
            background: radial-gradient(circle, rgba(168,85,247,0.08) 0%, transparent 70%);
            border-radius: 50%; pointer-events: none;"></div>
        <div style="position: relative; z-index: 1;">
            <div style="display: inline-block;
                background: rgba(0,255,204,0.10);
                border: 1px solid rgba(0,255,204,0.30);
                color: #00ffcc; padding: 6px 14px;
                border-radius: 20px; font-size: 11px;
                font-weight: 600; letter-spacing: 1.5px;
                text-transform: uppercase; margin-bottom: 20px;">
                Quantitative Trading Intelligence · IDX
            </div>
            <h1 style="color: #f3f4f6; font-size: 42px;
                font-weight: 800; margin: 0 0 12px 0;
                line-height: 1.15; letter-spacing: -0.02em;">
                QuantRisk <span style="color: #00ffcc;">Pro</span>
            </h1>
            <p style="color: #94a3b8; font-size: 16px;
                line-height: 1.6; max-width: 720px; margin: 0 0 28px 0;">
                Platform analisis saham institusional untuk Bursa Efek Indonesia.
                Kombinasi <b style="color:#cbd5e1;">analisis teknikal kuantitatif</b>,
                <b style="color:#cbd5e1;">bandarmology</b>, dan
                <b style="color:#cbd5e1;">AI insight</b> dalam satu dashboard terintegrasi.
            </p>
            <div style="display: flex; flex-wrap: wrap; gap: 8px;">
                <span style="background: #1e293b; color: #cbd5e1;
                    padding: 6px 12px; border-radius: 6px;
                    font-size: 11px; font-weight: 500;
                    border-left: 2px solid #00ffcc;">
                    🧬 V12 Adaptive Engine</span>
                <span style="background: #1e293b; color: #cbd5e1;
                    padding: 6px 12px; border-radius: 6px;
                    font-size: 11px; font-weight: 500;
                    border-left: 2px solid #a855f7;">
                    🤖 Gemini AI Insight</span>
                <span style="background: #1e293b; color: #cbd5e1;
                    padding: 6px 12px; border-radius: 6px;
                    font-size: 11px; font-weight: 500;
                    border-left: 2px solid #10b981;">
                    🐋 Bandarmology</span>
                <span style="background: #1e293b; color: #cbd5e1;
                    padding: 6px 12px; border-radius: 6px;
                    font-size: 11px; font-weight: 500;
                    border-left: 2px solid #f59e0b;">
                    🎲 Monte Carlo Simulation</span>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # CAPABILITIES GRID
    st.markdown("""
    <div style="margin: 0 0 16px 0;">
        <span style="color:#f3f4f6; font-size:20px; font-weight:700;">Capabilities</span>
        <span style="color:#64748b; font-size:12px; margin-left:10px;">
            — Everything you need for data-driven trading decisions</span>
    </div>
    """, unsafe_allow_html=True)

    def _feature_card(icon, title, desc, color):
        return f"""
        <div style="background: linear-gradient(135deg, #1a1d24 0%, #0f1116 100%);
            border: 1px solid #262626; border-radius: 12px;
            padding: 20px 18px; height: 100%;
            position: relative; overflow: hidden;">
            <div style="position: absolute; top: 0; left: 0;
                width: 3px; height: 100%; background: {color};"></div>
            <div style="font-size: 24px; margin-bottom: 10px;">{icon}</div>
            <div style="color: #f3f4f6; font-size: 14px; font-weight: 700;
                margin-bottom: 6px; letter-spacing: 0.02em;">{title}</div>
            <div style="color: #94a3b8; font-size: 12px; line-height: 1.5;">{desc}</div>
        </div>
        """

    r1c1, r1c2, r1c3 = st.columns(3)
    with r1c1:
        st.markdown(_feature_card("📊", "Technical Analysis",
            "EMA, RSI, ADX, Z-Score, Coppock Curve, and multi-timeframe momentum analysis.",
            "#00ffcc"), unsafe_allow_html=True)
    with r1c2:
        st.markdown(_feature_card("🐋", "Bandarmology",
            "Broker flow tracking, Bandar vs Retail composition, and foreign net flow monitoring.",
            "#a855f7"), unsafe_allow_html=True)
    with r1c3:
        st.markdown(_feature_card("🤖", "AI-Powered Insight",
            "Gemini analyzes news sentiment, technicals, and broker flow holistically.",
            "#8b5cf6"), unsafe_allow_html=True)

    st.markdown('<div style="height: 12px;"></div>', unsafe_allow_html=True)

    r2c1, r2c2, r2c3 = st.columns(3)
    with r2c1:
        st.markdown(_feature_card("🎯", "Backtest & Risk",
            "Win rate, Sharpe ratio, max drawdown, and Kelly criterion position sizing.",
            "#10b981"), unsafe_allow_html=True)
    with r2c2:
        st.markdown(_feature_card("🎲", "Monte Carlo",
            "Regime-switching simulation for probability-based price forecasting.",
            "#f59e0b"), unsafe_allow_html=True)
    with r2c3:
        st.markdown(_feature_card("📰", "News Sentiment",
            "IDX Fin-Lexicon + VADER hybrid scoring, filtered for ticker relevance.",
            "#06b6d4"), unsafe_allow_html=True)

    # PERFORMANCE METRICS
    st.markdown('<div style="height: 32px;"></div>', unsafe_allow_html=True)
    st.markdown("""
    <div style="margin: 0 0 16px 0;">
        <span style="color:#f3f4f6; font-size:20px; font-weight:700;">Performance Metrics</span>
        <span style="color:#64748b; font-size:12px; margin-left:10px;">
            — Live engine track record from evaluated signals</span>
    </div>
    """, unsafe_allow_html=True)

    stats_actual = hitung_statistik_riwayat_actual(st.session_state.get('riwayat_actual', {}))

    if stats_actual and stats_actual['total_eval'] > 0:
        wr_val = stats_actual['win_rate']
        wr_color = "#10b981" if wr_val >= 50 else "#ef4444"
        wr_icon = "📈" if wr_val >= 50 else "📉"

        def _stat_card(label, value, sublabel, color, icon=""):
            return f"""
            <div style="background: linear-gradient(135deg, #1a1d24 0%, #0f1116 100%);
                border: 1px solid #262626; border-radius: 12px;
                padding: 20px 18px; height: 100%;">
                <div style="color:#64748b; font-size:10px; text-transform:uppercase;
                    letter-spacing:1.2px; font-weight:600; margin-bottom:8px;">
                    {icon} {label}</div>
                <div style="color:{color}; font-size:28px; font-weight:800;
                    line-height:1; letter-spacing:-0.02em;">{value}</div>
                <div style="color:#94a3b8; font-size:11px; margin-top:6px;">{sublabel}</div>
            </div>
            """

        sc1, sc2, sc3, sc4, sc5 = st.columns(5)
        with sc1:
            st.markdown(_stat_card(
                "System Win Rate", 
                f"{wr_val:.1f}%",
                f"Honest: {stats_actual.get('win_rate_honest', 0):.1f}% · {stats_actual['total_eval']} eval",
                wr_color, wr_icon
            ), unsafe_allow_html=True)
        with sc2:
            st.markdown(_stat_card(
                "Win / Loss", f"{stats_actual['total_win']} / {stats_actual['total_loss']}",
                f"{stats_actual['total_not_touched']} not touched",
                "#00ffcc", "🏆"), unsafe_allow_html=True)
        with sc3:
            sw_txt = f"{stats_actual['wr_sw']:.1f}%" if stats_actual['wr_sw'] is not None else "—"
            sw_sub = f"{stats_actual['eval_sw']} trades" if stats_actual['eval_sw'] > 0 else "No data yet"
            sw_col = "#a855f7" if stats_actual['wr_sw'] is not None else "#64748b"
            st.markdown(_stat_card("Swing Win Rate", sw_txt, sw_sub, sw_col, "📆"), unsafe_allow_html=True)
        with sc4:
            dt_txt = f"{stats_actual['wr_dt']:.1f}%" if stats_actual['wr_dt'] is not None else "—"
            dt_sub = f"{stats_actual['eval_dt']} trades" if stats_actual['eval_dt'] > 0 else "No data yet"
            dt_col = "#06b6d4" if stats_actual['wr_dt'] is not None else "#64748b"
            st.markdown(_stat_card("Day Trade Win Rate", dt_txt, dt_sub, dt_col, "⏱️"), unsafe_allow_html=True)
        nt = stats_actual.get('nt_rate', 0)
        nt_color = "#ef4444" if nt > 25 else ("#f59e0b" if nt > 15 else "#10b981")
        with sc5:
            st.markdown(_stat_card("Not Touched", f"{nt:.1f}%", f"{stats_actual['total_not_touched']} entries missed", nt_color, "🚫"), unsafe_allow_html=True)
    else:
        st.markdown("""
        <div style="background:#1a1d24; border:1px dashed #334155;
            border-radius:12px; padding:28px 24px; text-align:center;">
            <div style="font-size:32px; margin-bottom:10px;">📊</div>
            <div style="color:#cbd5e1; font-size:14px; font-weight:600; margin-bottom:6px;">
                No evaluation data yet</div>
            <div style="color:#64748b; font-size:12px; line-height:1.6; max-width:520px; margin:0 auto;">
                Run your first analysis, then fill in the <b style="color:#94a3b8;">Quick Outcome Journal</b>
                after the signal plays out to start tracking live engine performance.
            </div>
        </div>
        """, unsafe_allow_html=True)
    # 🧠 FULL LEARNING DASHBOARD
    st.markdown('<div style="height: 32px;"></div>', unsafe_allow_html=True)
    st.markdown("""
    <div style="margin: 0 0 16px 0;">
        <span style="color:#f3f4f6; font-size:20px; font-weight:700;">🧠 Full Learning Engine</span>
        <span style="color:#64748b; font-size:12px; margin-left:10px;">
            — Engine learns from EVERY signal (BUY, HOLD, AVOID)</span>
    </div>
    """, unsafe_allow_html=True)

    with st.expander("📊 Signal Accuracy per Regime", expanded=False):
        st.caption(
            "📌 Evaluator jalan otomatis di background saat app dibuka. "
            "Setiap signal (BUY/HOLD/AVOID) yang sudah melewati horizon-nya "
            "akan divalidasi terhadap harga aktual → mengupdate accuracy tracker. "
            "Setelah 10+ sample per kombinasi, filter PART 4 mulai aktif otomatis."
        )
        try:
            stats = _cached_signal_stats()
        except Exception as e:
            stats = {"evaluated": 0, "correct": 0, "error": str(e)}

        c1, c2, c3 = st.columns(3)
        c1.metric("Signals Evaluated", stats.get("evaluated", 0))
        c2.metric("Correct", stats.get("correct", 0))
        if stats.get("evaluated", 0) > 0:
            acc = stats["correct"] / stats["evaluated"] * 100
            c3.metric("Accuracy", f"{acc:.1f}%")
            # Breakdown per mode
            bm = stats.get("by_mode", {})
            sw = bm.get("swing", {"total": 0, "correct": 0})
            dt = bm.get("daytrade", {"total": 0, "correct": 0})
            if sw["total"] or dt["total"]:
                st.caption(
                    f"📆 Swing: {sw['correct']}/{sw['total']} · "
                    f"⏱️ Daytrade: {dt['correct']}/{dt['total']}"
                )

        # Info run evaluator di sesi ini (kalau ada)
        lr = st.session_state.get('last_eval_result')
        if lr and lr.get('evaluated', 0) > 0:
            st.caption(
                f"🔄 Sesi ini: {lr['evaluated']} sinyal baru dievaluasi, "
                f"{lr['correct']} benar."
            )

        st.markdown("---")
        st.markdown("**🎯 Accuracy Matrix (Regime × Signal Type)**")

        matrix_data = []
        for ticker_key, mem in st.session_state.v12_memory.items():
            if ticker_key == '__global__':
                continue
            rsa = mem.get('regime_signal_accuracy', {})
            for regime, signals in rsa.items():
                for sig_cat, stats in signals.items():
                    if stats['total'] >= 3:
                        matrix_data.append({
                            'Ticker': ticker_key,
                            'Regime': regime,
                            'Signal': sig_cat,
                            'Hits': stats['hits'],
                            'Total': stats['total'],
                            'Accuracy': f"{stats['accuracy']*100:.1f}%"
                        })

        gm = st.session_state.v12_memory.get('__global__', {})
        grs = gm.get('regime_signal_accuracy', {})
        for regime, signals in grs.items():
            for sig_cat, stats in signals.items():
                if stats['total'] >= 3:
                    matrix_data.append({
                        'Ticker': '🌐 GLOBAL',
                        'Regime': regime,
                        'Signal': sig_cat,
                        'Hits': stats['hits'],
                        'Total': stats['total'],
                        'Accuracy': f"{stats['accuracy']*100:.1f}%"
                    })

        if matrix_data:
            df_matrix = pd.DataFrame(matrix_data)
            df_matrix = df_matrix.sort_values(['Ticker', 'Regime', 'Signal'])
            st.dataframe(df_matrix, use_container_width=True, hide_index=True)
        else:
            st.caption("Belum cukup data. Butuh minimal 3 evaluasi per kombinasi regime × signal.")

        st.markdown("---")
        st.info(
            "💡 **Cara baca:** Kalau **AVOID_BEARISH di regime Panic Sell** akurasinya "
            "**< 40%**, artinya sinyal AVOID sering salah di regime itu → "
            "engine otomatis akan longgarkan AVOID di regime tersebut ke depannya."
        )
    # QUICK START
    st.markdown('<div style="height: 32px;"></div>', unsafe_allow_html=True)
    st.markdown("""
    <div style="margin: 0 0 16px 0;">
        <span style="color:#f3f4f6; font-size:20px; font-weight:700;">Quick Start</span>
        <span style="color:#64748b; font-size:12px; margin-left:10px;">
            — Get your first signal in 3 steps</span>
    </div>
    """, unsafe_allow_html=True)

    steps = [
        ("01", "Enter Ticker", "Type the IDX stock code in the sidebar (e.g., BBRI, TLKM, BMRI).", "#00ffcc"),
        ("02", "Optional Context", "Add current price, fee settings, or mark your position if you already own it.", "#a855f7"),
        ("03", "Run Analysis", "Click ANALISIS to get signal, RRR, AI insight, and bandarmology data.", "#10b981"),
    ]
    step_cols = st.columns(3)
    for col, (num, title, desc, color) in zip(step_cols, steps):
        with col:
            st.markdown(f"""
            <div style="background: #1a1d24; border: 1px solid #262626;
                border-radius: 12px; padding: 20px 18px; height: 100%;">
                <div style="display: inline-block;
                    background: {color}20; color: {color};
                    font-size: 11px; font-weight: 700;
                    padding: 4px 12px; border-radius: 4px;
                    margin-bottom: 12px; letter-spacing: 1px;">
                    STEP {num}</div>
                <div style="color:#f3f4f6; font-size:14px; font-weight:700;
                    margin-bottom:6px;">{title}</div>
                <div style="color:#94a3b8; font-size:12px; line-height:1.5;">{desc}</div>
            </div>
            """, unsafe_allow_html=True)
    # RECENT SIGNALS — Last 6 analyses
    st.markdown('<div style="height: 32px;"></div>', unsafe_allow_html=True)
    st.markdown("""
    <div style="margin: 0 0 16px 0; display:flex; justify-content:space-between; align-items:baseline;">
        <div>
            <span style="color:#f3f4f6; font-size:20px; font-weight:700;">Recent Signals</span>
            <span style="color:#64748b; font-size:12px; margin-left:10px;">
                — Top 3 by score</span>
        </div>
    </div>
    """, unsafe_allow_html=True)
    
    def _has_outcome(r):
        """Cek apakah signal sudah ada outcome actual."""
        waktu = r.get('Waktu', '')
        saham = r.get('Saham', '')
        gaya = r.get('Gaya', 'SW')
        mode_actual = "swing" if gaya == "SW" else "daytrade"
        actual = (
            st.session_state.riwayat_actual.get((waktu, saham, gaya)) or
            st.session_state.riwayat_actual.get((waktu, saham, mode_actual)) or
            st.session_state.riwayat_actual.get((waktu, saham))
        )
        if not actual:
            return False
        return bool(
            actual.get('Actual_High') or
            actual.get('Actual_Low') or
            actual.get('Actual_Close') or
            actual.get('Outcome') or
            actual.get('Entry_Miss') == 'Yes'
        )
    
    def _parse_score(r):
        if not r:
            return -1.0
        try:
            return float(r.get('Score', 0))
        except (ValueError, TypeError):
            return -1.0
    
    def _parse_datetime(r):
        """Parse Waktu jadi datetime untuk sort."""
        try:
            return datetime.strptime(str(r.get('Waktu', '')), "%Y-%m-%d %H:%M")
        except Exception:
            return datetime.min
    
    # ── Step 1: Filter yang belum ada outcome ──
    riwayat_recent = st.session_state.get('riwayat', []) or []
    riwayat_unevaluated = [r for r in riwayat_recent if not _has_outcome(r)]
    
    # ── Step 2: Dedup per ticker, ambil yang TERBARU ──
    by_ticker = {}
    for r in riwayat_unevaluated:
        saham = r.get('Saham', '')
        if not saham:
            continue
        if saham not in by_ticker:
            by_ticker[saham] = []
        by_ticker[saham].append(r)
    
    picks = []
    for saham, entries in by_ticker.items():
        # Sort by waktu terbaru dulu
        entries.sort(key=_parse_datetime, reverse=True)
        
        # Ambil entry SW & DT terbaru per ticker
        r_sw = next((e for e in entries if e.get('Gaya') == 'SW'), None)
        r_dt = next((e for e in entries if e.get('Gaya') == 'DT'), None)
        
        # Pilih mode dengan score tertinggi
        best = r_sw if _parse_score(r_sw) >= _parse_score(r_dt) else r_dt
        if best:
            picks.append(best)
    
    # ── Step 3: Sort by Score, ambil top 3 ──
    picks.sort(key=_parse_score, reverse=True)
    top3 = picks[:3]

    # ── Step 4: Render ──
    def _sig_style(sig):
        if not sig: return "#64748b", "—", "—"
        if "STRONG BUY" in sig: return "#10b981", "🔥", "STRONG BUY"
        if "BUY" in sig:        return "#84cc16", "⚡", "BUY"
        if "HOLD" in sig:       return "#3b82f6", "⏸️", "HOLD"
        return "#ef4444", "🚨", "AVOID"

    if top3:
        sig_cols = st.columns(3)
        for col, r in zip(sig_cols, top3):
            with col:
                saham = r.get('Saham', '?')
                sinyal = r.get('Sinyal', '?')
                harga = r.get('Harga', '?')
                waktu = r.get('Waktu', '?')
                gaya = r.get('Gaya', 'SW')
                score = r.get('Score', '?')
                rrr = r.get('RRR', '?')

                s_color, s_icon, s_label = _sig_style(sinyal)
                gaya_icon = "⏱️" if gaya == "DT" else "📆"
                gaya_color = "#06b6d4" if gaya == "DT" else "#a855f7"
                waktu_short = waktu.split()[1] if len(waktu.split()) > 1 else waktu

                # Outcome badge
                actual = (
                    st.session_state.riwayat_actual.get((waktu, saham, gaya)) or
                    st.session_state.riwayat_actual.get((waktu, saham,
                        "daytrade" if gaya == "DT" else "swing")) or
                    st.session_state.riwayat_actual.get((waktu, saham))
                )
                outcome_badge = ""
                if actual:
                    out = actual.get('Outcome', '')
                    if actual.get('Entry_Miss') == 'Yes' or out == 'Not Touched':
                        outcome_badge = '<span style="background:#94a3b820;color:#94a3b8;font-size:9px;padding:2px 6px;border-radius:4px;margin-left:6px;">NOT TOUCHED</span>'
                    elif out == 'Win':
                        outcome_badge = '<span style="background:#10b98120;color:#10b981;font-size:9px;padding:2px 6px;border-radius:4px;margin-left:6px;">✓ WIN</span>'
                    elif out == 'Loss':
                        outcome_badge = '<span style="background:#ef444420;color:#ef4444;font-size:9px;padding:2px 6px;border-radius:4px;margin-left:6px;">✗ LOSS</span>'

                card_html = f"""
<div style="background:linear-gradient(135deg,#1a1d24 0%,#0f1116 100%);border:1px solid #262626;border-radius:12px;padding:14px 16px;margin-bottom:12px;border-left:3px solid {s_color};">
<div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:8px;">
<div style="display:flex;align-items:center;gap:6px;">
<span style="color:#f3f4f6;font-size:16px;font-weight:800;letter-spacing:0.02em;">{saham}</span>
<span style="color:{gaya_color};font-size:9px;font-weight:700;padding:2px 6px;background:{gaya_color}15;border-radius:4px;letter-spacing:0.5px;">{gaya_icon} {gaya}</span>
</div>
<div style="color:#64748b;font-size:9px;">{waktu_short}</div>
</div>
<div style="display:flex;align-items:center;margin-bottom:10px;">
<span style="color:{s_color};font-size:11px;font-weight:700;">{s_icon} {s_label}</span>
{outcome_badge}
</div>
<div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:6px;padding-top:8px;border-top:1px solid #1e293b;">
<div>
<div style="color:#64748b;font-size:8px;text-transform:uppercase;letter-spacing:0.5px;">Price</div>
<div style="color:#e2e8f0;font-size:11px;font-weight:600;margin-top:2px;">Rp {harga}</div>
</div>
<div>
<div style="color:#64748b;font-size:8px;text-transform:uppercase;letter-spacing:0.5px;">RRR</div>
<div style="color:#e2e8f0;font-size:11px;font-weight:600;margin-top:2px;">{rrr}</div>
</div>
<div>
<div style="color:#64748b;font-size:8px;text-transform:uppercase;letter-spacing:0.5px;">Score</div>
<div style="color:#e2e8f0;font-size:11px;font-weight:600;margin-top:2px;">{score}</div>
</div>
</div>
</div>
"""
                st.markdown(card_html, unsafe_allow_html=True)
    else:
        st.markdown("""
        <div style="background:#1a1d24; border:1px dashed #334155;
            border-radius:12px; padding:24px; text-align:center;">
            <div style="font-size:28px; margin-bottom:8px;">📡</div>
            <div style="color:#cbd5e1; font-size:13px; font-weight:600; margin-bottom:4px;">
                No signals yet</div>
            <div style="color:#64748b; font-size:11px;">
                Run your first analysis to see recent signals here.</div>
        </div>
        """, unsafe_allow_html=True)
    # TOP BROKERS THIS WEEK — Aggregate from broksum_history
    st.markdown('<div style="height: 32px;"></div>', unsafe_allow_html=True)
    st.markdown("""
    <div style="margin: 0 0 16px 0;">
        <span style="color:#f3f4f6; font-size:20px; font-weight:700;">Top Brokers This Week</span>
        <span style="color:#64748b; font-size:12px; margin-left:10px;">
            — Most active brokers in the last 7 days</span>
    </div>
    """, unsafe_allow_html=True)

    def _get_top_brokers_week():
        """Agregasi top brokers dari CACHE session."""
        records = get_broksum_cache()

        from datetime import datetime as _dt, timedelta as _td
        cutoff = _dt.now() - _td(days=7)
        cutoff_str = cutoff.strftime("%Y-%m-%d")

        buyer_agg = {}
        seller_agg = {}

        for rec in records:
            up_date = str(rec.get('upload_date', ''))[:10]
            if not up_date or up_date < cutoff_str:
                continue

            ticker = str(rec.get('ticker', '')).upper()
            for side_key, agg in [("top_buyers", buyer_agg), ("top_sellers", seller_agg)]:
                raw = rec.get(side_key, '[]')
                try:
                    items = json.loads(raw) if isinstance(raw, str) else (raw or [])
                except Exception:
                    items = []
                for it in items:
                    if not isinstance(it, dict):
                        continue
                    code = str(it.get('broker', '')).upper().strip()
                    if not code:
                        continue
                    vol = float(it.get('volume_lot', 0) or 0)
                    if code not in agg:
                        agg[code] = {'vol': 0, 'count': 0, 'tickers': set()}
                    agg[code]['vol'] += vol
                    agg[code]['count'] += 1
                    agg[code]['tickers'].add(ticker)

        top_buyers = sorted(buyer_agg.items(), key=lambda x: x[1]['vol'], reverse=True)[:5]
        top_sellers = sorted(seller_agg.items(), key=lambda x: x[1]['vol'], reverse=True)[:5]

        return {
            'buyers': top_buyers,
            'sellers': top_sellers,
            'n_records': len([
                r for r in records
                if str(r.get('upload_date', ''))[:10] >= cutoff_str
            ]),
        }

    _broker_data = None
    _broker_error = None
    try:
        _broker_data = _get_top_brokers_week()
    except Exception as _e:
        _broker_error = str(_e)

    if _broker_data and (_broker_data['buyers'] or _broker_data['sellers']):
        st.caption(f"📊 Aggregated from **{_broker_data['n_records']}** broksum uploads in the last 7 days")

        col_buy, col_sell = st.columns(2)

        with col_buy:
            st.markdown("""
            <div style="color:#10b981; font-size:12px; font-weight:700;
                margin-bottom:10px; letter-spacing:0.5px; text-transform:uppercase;">
                🟢 Top Buyers</div>
            """, unsafe_allow_html=True)

            if _broker_data['buyers']:
                max_vol = _broker_data['buyers'][0][1]['vol'] or 1
                for rank, (code, info) in enumerate(_broker_data['buyers'], 1):
                    kat, icon = klasifikasi_broker(code, info['vol'])
                    bar_pct = (info['vol'] / max_vol) * 100
                    tickers_preview = ", ".join(sorted(info['tickers'])[:3])
                    if len(info['tickers']) > 3:
                        tickers_preview += f" +{len(info['tickers']) - 3}"

                    # Warna berdasarkan kategori
                    if kat == "Bandar":
                        bar_color = "#a855f7"
                    elif kat == "Retail":
                        bar_color = "#f59e0b"
                    else:
                        bar_color = "#64748b"

                    st.markdown(f"""
                    <div style="background:#1a1d24; border:1px solid #262626;
                        border-radius:8px; padding:10px 14px; margin-bottom:8px;">
                        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;">
                            <div style="display:flex; align-items:center; gap:8px;">
                                <span style="color:#64748b; font-size:10px; font-weight:700;
                                    min-width:20px;">#{rank}</span>
                                <span style="color:#f3f4f6; font-size:13px; font-weight:700;
                                    letter-spacing:0.02em;">{code}</span>
                                <span style="color:{bar_color}; font-size:10px; font-weight:600;">
                                    {icon} {kat}</span>
                            </div>
                            <div style="color:#cbd5e1; font-size:11px; font-weight:600;">
                                {info['vol']:,.0f} lot</div>
                        </div>
                        <div style="background:#0f1116; height:4px; border-radius:2px;
                            overflow:hidden; margin-bottom:5px;">
                            <div style="width:{bar_pct:.1f}%; height:100%;
                                background:linear-gradient(90deg, {bar_color}, {bar_color}aa);
                                border-radius:2px;"></div>
                        </div>
                        <div style="color:#64748b; font-size:9px;">
                            {info['count']} appearance{'s' if info['count'] > 1 else ''} · {tickers_preview}</div>
                    </div>
                    """, unsafe_allow_html=True)
            else:
                st.caption("(No buyer data)")

        with col_sell:
            st.markdown("""
            <div style="color:#ef4444; font-size:12px; font-weight:700;
                margin-bottom:10px; letter-spacing:0.5px; text-transform:uppercase;">
                🔴 Top Sellers</div>
            """, unsafe_allow_html=True)

            if _broker_data['sellers']:
                max_vol = _broker_data['sellers'][0][1]['vol'] or 1
                for rank, (code, info) in enumerate(_broker_data['sellers'], 1):
                    kat, icon = klasifikasi_broker(code, info['vol'])
                    bar_pct = (info['vol'] / max_vol) * 100
                    tickers_preview = ", ".join(sorted(info['tickers'])[:3])
                    if len(info['tickers']) > 3:
                        tickers_preview += f" +{len(info['tickers']) - 3}"

                    if kat == "Bandar":
                        bar_color = "#a855f7"
                    elif kat == "Retail":
                        bar_color = "#f59e0b"
                    else:
                        bar_color = "#64748b"

                    st.markdown(f"""
                    <div style="background:#1a1d24; border:1px solid #262626;
                        border-radius:8px; padding:10px 14px; margin-bottom:8px;">
                        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;">
                            <div style="display:flex; align-items:center; gap:8px;">
                                <span style="color:#64748b; font-size:10px; font-weight:700;
                                    min-width:20px;">#{rank}</span>
                                <span style="color:#f3f4f6; font-size:13px; font-weight:700;
                                    letter-spacing:0.02em;">{code}</span>
                                <span style="color:{bar_color}; font-size:10px; font-weight:600;">
                                    {icon} {kat}</span>
                            </div>
                            <div style="color:#cbd5e1; font-size:11px; font-weight:600;">
                                {info['vol']:,.0f} lot</div>
                        </div>
                        <div style="background:#0f1116; height:4px; border-radius:2px;
                            overflow:hidden; margin-bottom:5px;">
                            <div style="width:{bar_pct:.1f}%; height:100%;
                                background:linear-gradient(90deg, {bar_color}, {bar_color}aa);
                                border-radius:2px;"></div>
                        </div>
                        <div style="color:#64748b; font-size:9px;">
                            {info['count']} appearance{'s' if info['count'] > 1 else ''} · {tickers_preview}</div>
                    </div>
                    """, unsafe_allow_html=True)
            else:
                st.caption("(No seller data)")

    else:
        _err_msg = ""
        if _broker_error:
            _err_msg = (f"<div style='color:#f59e0b; font-size:10px; margin-top:6px;'>"
                        f"⚠️ Error: {_broker_error[:100]}</div>")

        st.markdown(f"""
        <div style="background:#1a1d24; border:1px dashed #334155;
            border-radius:12px; padding:24px; text-align:center;">
            <div style="font-size:28px; margin-bottom:8px;">🐋</div>
            <div style="color:#cbd5e1; font-size:13px; font-weight:600; margin-bottom:4px;">
                {"Data broker sedang tidak tersedia" if _broker_error else "No broker data this week"}</div>
            <div style="color:#64748b; font-size:11px; line-height:1.6; max-width:520px; margin:0 auto;">
                {"Coba refresh halaman. Sistem akan retry otomatis." if _broker_error else 
                 'Upload Broksum screenshots via sidebar → <b style="color:#94a3b8;">📸 Scan Broksum</b> untuk mulai aggregasi broker activity.'}
            </div>
            {_err_msg}
        </div>
        """, unsafe_allow_html=True)
    # MARKET SNAPSHOT (IHSG) — Keep existing functionality
    st.markdown('<div style="height: 32px;"></div>', unsafe_allow_html=True)
    st.markdown("""
    <div style="margin: 0 0 16px 0;">
        <span style="color:#f3f4f6; font-size:20px; font-weight:700;">Market Snapshot</span>
        <span style="color:#64748b; font-size:12px; margin-left:10px;">
            — Live IHSG data</span>
    </div>
    """, unsafe_allow_html=True)

    periode_pilihan = st.selectbox(
        "Periode data IHSG:",
        options=["1d", "5d", "1mo"],
        format_func=lambda x: {"1d": "1 Hari", "5d": "5 Hari", "1mo": "1 Bulan"}[x],
        index=0,
        key="ihsg_period"
    )

    if periode_pilihan == "1d":
        interval_candidates = ["1m", "5m", "15m", "30m", "60m", "1d"]
    elif periode_pilihan == "5d":
        interval_candidates = ["5m", "15m", "30m", "60m", "1d"]
    else:
        interval_candidates = ["1d"]

    df_ihsg_preview = pd.DataFrame()
    interval_terpakai = None

    for interval in interval_candidates:
        temp_df = load_ihsg_data(period=periode_pilihan, interval=interval)
        if not temp_df.empty and len(temp_df) >= 2:
            df_ihsg_preview = temp_df
            interval_terpakai = interval
            break
        elif not temp_df.empty and len(temp_df) == 1 and interval == interval_candidates[-1]:
            df_ihsg_preview = temp_df
            interval_terpakai = interval
            break

    try:
        try:
            ihsg_info = yf.Ticker("^JKSE").info
            prev_close = ihsg_info.get('previousClose', None)
            open_price = ihsg_info.get('regularMarketOpen', None)
        except:
            prev_close = None
            open_price = None

        if not df_ihsg_preview.empty and len(df_ihsg_preview) >= 2:
            ihsg_close = float(df_ihsg_preview['Close'].iloc[-1])
            open_period = float(df_ihsg_preview['Open'].iloc[0])

            if periode_pilihan == "1d":
                if prev_close is not None and prev_close > 0:
                    ihsg_change = (ihsg_close - prev_close) / prev_close * 100
                else:
                    ihsg_prev = float(df_ihsg_preview['Close'].iloc[-2])
                    ihsg_change = (ihsg_close - ihsg_prev) / ihsg_prev * 100
            else:
                if open_period > 0:
                    ihsg_change = (ihsg_close - open_period) / open_period * 100
                else:
                    ihsg_change = 0.0

            ihsg_high = float(df_ihsg_preview['High'].max())
            ihsg_low = float(df_ihsg_preview['Low'].min())
            if open_price is None or open_price == 0:
                open_price = open_period

            if interval_terpakai in ("1m", "5m", "15m", "30m", "60m"):
                vol_val = df_ihsg_preview['Volume'].sum()
            else:
                vol_val = float(df_ihsg_preview['Volume'].iloc[-1])
            volume_str = f"{vol_val:,.0f}" if vol_val > 0 else "N/A"

            col1, col2, col3, col4, col5 = st.columns(5)
            col1.metric("IHSG", f"{ihsg_close:,.0f}", f"{ihsg_change:+.2f}%")
            col2.metric("Open", f"{open_price:,.0f}" if open_price else "N/A")
            col3.metric("High", f"{ihsg_high:,.0f}")
            col4.metric("Low", f"{ihsg_low:,.0f}")
            col5.metric("Volume", volume_str)

            if PLOTLY_AVAILABLE:
                line_color = '#26a69a' if ihsg_change >= 0 else '#ef5350'
                area_color = f"rgba({38 if ihsg_change >= 0 else 239}, {166 if ihsg_change >= 0 else 83}, {154 if ihsg_change >= 0 else 80}, 0.25)"

                fig = go.Figure()
                fig.add_trace(go.Scatter(
                    x=df_ihsg_preview.index,
                    y=df_ihsg_preview['Close'],
                    mode='lines',
                    line=dict(color=line_color, width=1.5),
                    fill='tozeroy',
                    fillcolor=area_color,
                    name='IHSG',
                    hovertemplate='<b>%{x|%d %b %H:%M WIB}</b><br>Close: %{y:,.0f}<extra></extra>'
                ))
                fig.add_hline(y=ihsg_high, line_dash='dot', line_color='rgba(255,255,255,0.4)')
                fig.add_annotation(x=0.5, y=ihsg_high, xref='paper', yref='y',
                                   text=f'H {ihsg_high:,.0f}', showarrow=False,
                                   font=dict(size=9, color='rgba(255,255,255,0.6)'),
                                   bgcolor='rgba(15, 17, 22, 0.7)',
                                   bordercolor='rgba(255,255,255,0.3)',
                                   borderwidth=1, borderpad=4, xanchor='center', yanchor='bottom')
                fig.add_hline(y=ihsg_low, line_dash='dot', line_color='rgba(255,255,255,0.4)')
                fig.add_annotation(x=0.5, y=ihsg_low, xref='paper', yref='y',
                                   text=f'L {ihsg_low:,.0f}', showarrow=False,
                                   font=dict(size=9, color='rgba(255,255,255,0.6)'),
                                   bgcolor='rgba(15, 17, 22, 0.7)',
                                   bordercolor='rgba(255,255,255,0.3)',
                                   borderwidth=1, borderpad=4, xanchor='center', yanchor='bottom')
                y_min = float(df_ihsg_preview['Low'].min()) * 0.998
                y_max = float(df_ihsg_preview['High'].max()) * 1.002
                fig.update_yaxes(range=[y_min, y_max])

                chart_title = {
                    "1d": "IHSG Hari Ini",
                    "5d": "IHSG 5 Hari Terakhir",
                    "1mo": "IHSG 1 Bulan Terakhir"
                }.get(periode_pilihan, "IHSG")

                fig.update_layout(
                    title=dict(text=chart_title, x=0.01, xanchor='left', font=dict(size=14, color='#e0e0e0')),
                    template="plotly_dark",
                    height=400,
                    margin=dict(l=10, r=20, t=40, b=10),
                    dragmode='pan',
                    xaxis=dict(title=None, showgrid=False, zeroline=False, showline=True, linecolor='rgba(128,128,128,0.2)'),
                    yaxis=dict(title=None, showgrid=True, gridcolor='rgba(128,128,128,0.1)', zeroline=False, side='right'),
                    hovermode='x unified',
                    hoverlabel=dict(bgcolor='#1e293b', font_size=11, font_family="monospace"),
                    paper_bgcolor='#0f1116',
                    plot_bgcolor='#0f1116',
                    showlegend=False
                )
                st.plotly_chart(fig, use_container_width=True, config={
                    'modeBarButtonSize': 4,
                    'displaylogo': False
                })
                if interval_terpakai != "1m" and periode_pilihan == "1d":
                    st.info("ℹ️ Data 1 menit tidak tersedia, menggunakan interval yang lebih besar.")
            else:
                st.line_chart(df_ihsg_preview['Close'])
        elif not df_ihsg_preview.empty and len(df_ihsg_preview) == 1:
            ihsg_close = float(df_ihsg_preview['Close'].iloc[-1])
            if prev_close:
                ihsg_change = (ihsg_close - prev_close) / prev_close * 100
                st.metric("IHSG", f"{ihsg_close:,.0f}", f"{ihsg_change:+.2f}%")
            else:
                st.metric("IHSG", f"{ihsg_close:,.0f}")
            st.warning("Data IHSG hanya tersedia 1 titik (kemungkinan di luar jam bursa).")
            if PLOTLY_AVAILABLE:
                fig = go.Figure()
                fig.add_trace(go.Scatter(
                    x=df_ihsg_preview.index,
                    y=df_ihsg_preview['Close'],
                    mode='lines+markers',
                    marker=dict(color='#f59e0b', size=8),
                    line=dict(color='#f59e0b', width=2),
                    name='IHSG'
                ))
                fig.update_layout(title="IHSG (Data Terbatas)", template="plotly_dark", height=350, dragmode='pan')
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.line_chart(df_ihsg_preview['Close'])
        else:
            st.warning("Data IHSG tidak tersedia untuk periode yang dipilih.")
    except Exception as e:
        st.error(f"Gagal memuat data IHSG: {e}")

    # FOOTER DISCLAIMER
    st.markdown('<div style="height: 24px;"></div>', unsafe_allow_html=True)
    st.markdown("""
    <div style="background:#1a1d24; border-left:3px solid #64748b;
        border-radius:8px; padding:14px 20px; margin-top:8px;">
        <div style="color:#94a3b8; font-size:11px; line-height:1.7;">
            <b style="color:#cbd5e1;">⚠️ Disclaimer:</b>
            QuantRisk Pro merupakan alat bantu analisis kuantitatif berbasis data historis.
            Hasil analisis bukan rekomendasi investasi. Semua keputusan trading dan investasi
            sepenuhnya tanggung jawab pengguna. Data historis tidak menjamin performa masa depan.
        </div>
    </div>
    """, unsafe_allow_html=True)
