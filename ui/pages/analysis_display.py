"""
Display hasil analisis saham — satu fungsi publik: display_analysis_result(res).
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import pytz
import streamlit as st

PLOTLY_AVAILABLE = True


# ── Config & Core ──
from config.settings import FACTOR_KEYS
from core.indicators import fraksi_bei, safe_float
from core.regime import generate_regime_insight
from core.riwayat import hitung_winrate_ticker_actual

# ── Services ──
from services.gemini_client import (
    analisis_saham_dengan_ai,
    bersihkan_teks_ai,
)
from services.sheets_client import (
    load_v12_predictions,
    update_v12_memory,
)
# ═══════════════════════════════════════════════════════════════
# PUBLIC API
# ═══════════════════════════════════════════════════════════════
def display_analysis_result(res):
    """Render seluruh hasil analisis ke UI. Body di bawah."""
    # ...body kamu...

# ═══════════════════════════════════════════════════════════════
# PUBLIC API
# ═══════════════════════════════════════════════════════════════
def display_analysis_result(res):
    # ===== AMBIL SEMUA VARIABEL DARI RES =====
    df = res['df']
    df_back = res['df_back']
    harga_terakhir = res['harga_terakhir']
    signal = res['signal']
    entry_zone_f = res['entry_zone_f']
    entry_ideal_f = res.get('entry_ideal_f', fraksi_bei(harga_terakhir))
    risk_adjusted_alloc = res.get('risk_adjusted_alloc', res['kelly_adj'] * 100)
    sl_harga_f = res['sl_harga_f']

    tp_low_f = res['tp_low_f']
    tp_high_f = res['tp_high_f']
    rrr = res['rrr']
    rrr_status = res['rrr_status']
    prob_bull = res['prob_bull']
    est_besok_f = res['est_besok_f']
    est_besok_sinyal_f = res['est_besok_sinyal_f']
    low_est_f = res['low_est_f']
    up_est_f = res['up_est_f']
    tp_pct_low = res['tp_pct_low']
    tp_pct_high = res['tp_pct_high']
    sl_pct = res['sl_pct']
    adx = res['adx']
    rsi14 = res['rsi14']
    atr_pct = res['atr_pct']
    avg_sentiment = res['avg_sentiment']
    sentimen_status = res['sentimen_status']
    headlines = res['headlines']
    sources = res['sources']
    translated = res['translated']
    regime = res['regime']
    ihsg_cond = res['ihsg_cond']
    coppock_val = res['coppock_val']
    coppock_prev = res['coppock_prev']
    coppock_turning_up = res['coppock_turning_up']
    coppock_rising = res['coppock_rising']
    coppock_status = res['coppock_status']
    beta_ihsg = res['beta_ihsg']
    win_bt = res['win_bt']
    pf_bt = res['pf_bt']
    avg_bt = res['avg_bt']
    max_dd_bt = res['max_dd_bt']
    sharpe_bt = res['sharpe_bt']
    trades_bt = res['trades_bt']
    kelly_adj = res['kelly_adj']
    max_dd = res['max_dd']
    max_dd_30 = res['max_dd_30']
    breakout = res['breakout']
    breakout_label = res['breakout_label']
    vwap_now = res['vwap_now']
    vwap_bias = res['vwap_bias']
    r1 = res['r1']
    r2 = res['r2']
    s1 = res['s1']
    s2 = res['s2']
    pp = res['pp']
    mc = res['mc']
    per = res['per']
    pbv = res['pbv']
    roe = res['roe']
    de = res['de']
    ticker_info = res['ticker_info']
    adx_threshold = res['adx_threshold']
    hit_tp = res['hit_tp']
    hit_sl = res['hit_sl']
    estimasi_label = res['estimasi_label']
    prob_label = res['prob_label']
    backtest_window = res['backtest_window']
    ofi_now = res['ofi_now']
    is_daytrade = res['is_daytrade']
    floating_pl_pct = res['floating_pl_pct']
    sudah_beli = res['sudah_beli']
    ticker_raw = res['ticker_raw']

    # === Tambahan untuk V12 Adaptive & AI Insight ===
    adaptive_w = res['adaptive_w']
    returns = res['returns']
    mom_median_th = res['mom_median_th']
    harga_beli_float = res['harga_beli_float']

    # ===== TAMPILAN UTAMA =====
    st.title("📊 Quant & Risk Engine Pro")
    st.write("Algoritma kuantitatif + Berita + Backtest + AI + Grafik Interaktif + Fundamental")
    st.success(f"✅ Analisis Berhasil: {ticker_raw} | Closing Price: Rp {harga_terakhir:,.0f}".replace(",", "."))

    now_jkt = datetime.now(pytz.timezone("Asia/Jakarta"))
    st.caption(f"⏱️ **Waktu Analisis:** {now_jkt.strftime('%d %B %Y, %H:%M:%S WIB')}")
    waktu_str = now_jkt.strftime('%d %B %Y, %H:%M WIB')

    col1, col2, col3 = st.columns(3)
    col1.metric(
        "Sinyal Eksekusi",
        signal,
        delta=f"per {now_jkt.strftime('%d/%m %H:%M')} WIB",
        delta_color="off"
    )
    with col2:
        st.metric(
            label=f"{estimasi_label} (Netral)",
            value=f"Rp {est_besok_f:,.0f}",
            delta=f"Range: Rp {low_est_f:,.0f} - {up_est_f:,.0f}"
        )
        st.metric(
            label=f"{estimasi_label} (Sinyal {signal.split()[0]})",
            value=f"Rp {est_besok_sinyal_f:,.0f}",
            delta=f"{((est_besok_sinyal_f - harga_terakhir) / harga_terakhir * 100):+.2f}%"
        )
    col3.metric(prob_label, f"{prob_bull:.1f}%")
    # ═══ OUTLOOK 30 HARI — hanya untuk Swing ═══
    if not is_daytrade and res.get('estimasi_30d_label'):
        st.markdown(
            f"<div style='color:#94a3b8; font-size:11px; text-transform:uppercase; "
            f"letter-spacing:1px; margin-top:12px; margin-bottom:4px;'>"
            f"📅 {res['estimasi_30d_label']}</div>",
            unsafe_allow_html=True
        )
        o1, o2, o3 = st.columns(3)
        o1.metric(
            f"{res['estimasi_30d_label']} (Netral)",
            f"Rp {res['est_30d_f']:,.0f}",
            delta=f"Range: Rp {res['low_est_30d_f']:,.0f} - {res['up_est_30d_f']:,.0f}"
        )
        o2.metric(
            f"{res['estimasi_30d_label']} (Sinyal)",
            f"Rp {res['est_30d_sinyal_f']:,.0f}",
            delta=f"{((res['est_30d_sinyal_f'] - harga_terakhir) / harga_terakhir * 100):+.2f}%"
        )
        o3.metric(res['prob_30d_label'], f"{res['prob_bull_30d']:.1f}%")

    # ===== GRAFIK =====
    if PLOTLY_AVAILABLE:
        st.header("📈 Chart Harga & Sinyal")
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=df.index, y=df['Close'], name='Close', line=dict(color='#00ffcc')))
        fig.add_trace(go.Scatter(x=df.index, y=df['EMA20'], name='EMA20', line=dict(color='#f59e0b', dash='dot')))
        fig.add_trace(go.Scatter(x=df.index, y=df['EMA50'], name='EMA50', line=dict(color='#ef4444', dash='dot')))
        buy_signals = df_back[df_back['Signal'].str.contains("BUY")]
        fig.add_trace(go.Scatter(x=buy_signals.index, y=buy_signals['Close'], mode='markers',
                                 marker=dict(symbol='triangle-up', size=10, color='#10b981'), name='Buy Signal'))
        for lvl, lbl, clr in [(r1, 'R1', 'orange'), (s1, 'S1', 'red'), (pp, 'PP', 'gray')]:
            fig.add_hline(y=lvl, line_dash="dash", line_color=clr, annotation_text=lbl, annotation_position="right")
        fig.update_layout(template="plotly_dark", height=450, margin=dict(l=10, r=10, t=20, b=10), dragmode='pan')
        st.plotly_chart(fig, use_container_width=True)

    # RINGKASAN EKSEKUTIF — REDESIGN v2 (Visual & Interaktif)
    st.markdown("---")
    st.header("📋 Ringkasan Eksekutif & Rekomendasi")

    # ── Tentukan level sinyal ──
    if rrr < 1.0 and ("BUY" in signal):
        sig_color, sig_icon = "#ef4444", "⚠️"
        sig_label = "BUY ON WEAKNESS"
        sig_desc = "Tren valid, tapi RRR di bawah 1.0"
        kondisi_txt = f"Tren valid, RRR {rrr:.2f} ({rrr_status})"
        langkah_txt = f"Entry di zona {entry_zone_f}, SL Rp {sl_harga_f:,.0f}, TP bertahap Rp {tp_low_f:,.0f} - Rp {tp_high_f:,.0f}"
    elif "STRONG BUY" in signal:
        sig_color, sig_icon = "#10b981", "🟢"
        sig_label = "AGGRESSIVE BUY"
        sig_desc = "Tren kuat & akumulasi volume"
        kondisi_txt = "Tren Kuat & Akumulasi Volume"
        langkah_txt = f"Entry di zona {entry_zone_f}, SL Rp {sl_harga_f:,.0f} (-{sl_pct:.1f}%), TP bertahap Rp {tp_low_f:,.0f} - Rp {tp_high_f:,.0f}"
    elif "BUY" in signal:
        sig_color, sig_icon = "#f59e0b", "🟡"
        sig_label = "BUY ON WEAKNESS"
        sig_desc = "Tren valid, entry bertahap"
        kondisi_txt = f"Tren valid, RRR {rrr:.2f} ({rrr_status})"
        langkah_txt = f"Entry di zona {entry_zone_f}, SL Rp {sl_harga_f:,.0f}, TP bertahap Rp {tp_low_f:,.0f} - Rp {tp_high_f:,.0f}"
    elif "HOLD" in signal:
        sig_color, sig_icon = "#3b82f6", "🔵"
        sig_label = "HOLD"
        sig_desc = "Konsolidasi / transisi"
        kondisi_txt = "Konsolidasi / Transisi"
        langkah_txt = "Jangan tambah posisi, pantau SL"
    else:
        sig_color, sig_icon = "#ef4444", "🔴"
        sig_label = "AVOID / LIQUIDATE"
        sig_desc = "Risiko penurunan / distribusi"
        kondisi_txt = "Risiko Penurunan / Distribusi"
        langkah_txt = "Amankan modal, hindari entry baru"

    # ═══ CARD 1 — SIGNAL BADGE (prominent) ═══
    st.markdown(f"""<div style="background: linear-gradient(135deg, {sig_color}22 0%, {sig_color}08 100%); border-left: 6px solid {sig_color}; border-radius: 12px; padding: 18px 24px; margin-bottom: 16px;">
<div style="display: flex; align-items: center; gap: 16px;">
<div style="font-size: 42px; line-height: 1;">{sig_icon}</div>
<div style="flex: 1;">
<div style="color: #94a3b8; font-size: 11px; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 4px;">Rekomendasi</div>
<div style="color: {sig_color}; font-size: 24px; font-weight: 700; line-height: 1.1;">{sig_label}</div>
<div style="color: #cbd5e1; font-size: 13px; margin-top: 4px;">{sig_desc}</div>
</div>
</div>
</div>""", unsafe_allow_html=True)

    # ═══ CARD 2 — 3 PILAR: KONDISI | REKOMENDASI | LANGKAH ═══
    col_k, col_r, col_l = st.columns(3)

    with col_k:
        st.markdown(f"""<div style="background:#1e293b; border-radius:10px; padding:14px; min-height:100px; border-top:3px solid #64748b;">
<div style="color:#94a3b8; font-size:10px; text-transform:uppercase; letter-spacing:1.2px;">Kondisi</div>
<div style="color:#e2e8f0; font-size:13px; margin-top:8px; line-height:1.5;">{kondisi_txt}</div>
</div>""", unsafe_allow_html=True)

    with col_r:
        st.markdown(f"""<div style="background:#1e293b; border-radius:10px; padding:14px; min-height:100px; border-top:3px solid {sig_color};">
<div style="color:#94a3b8; font-size:10px; text-transform:uppercase; letter-spacing:1.2px;">Rekomendasi</div>
<div style="color:{sig_color}; font-size:13px; font-weight:600; margin-top:8px; line-height:1.5;">{sig_label}</div>
</div>""", unsafe_allow_html=True)

    with col_l:
        st.markdown(f"""<div style="background:#1e293b; border-radius:10px; padding:14px; min-height:100px; border-top:3px solid #00ffcc;">
<div style="color:#94a3b8; font-size:10px; text-transform:uppercase; letter-spacing:1.2px;">Langkah</div>
<div style="color:#e2e8f0; font-size:13px; margin-top:8px; line-height:1.5;">{langkah_txt}</div>
</div>""", unsafe_allow_html=True)

    # ═══ CARD 3 — POSITION STATUS (khusus sudah_beli) ═══
    if sudah_beli:
        if floating_pl_pct is not None:
            if floating_pl_pct > 5:
                pl_color, pl_icon, pl_status = "#10b981", "🚀", "PROFIT BESAR"
                pl_action = "Take profit sebagian / trailing stop"
            elif floating_pl_pct > 0:
                pl_color, pl_icon, pl_status = "#84cc16", "✅", "PROFIT"
                pl_action = "Pantau SL ketat, naikkan trailing stop"
            elif floating_pl_pct > -3:
                pl_color, pl_icon, pl_status = "#f59e0b", "⚠️", "RUGI KECIL"
                pl_action = "Tahan dengan SL sesuai rekomendasi"
            else:
                pl_color, pl_icon, pl_status = "#ef4444", "🔴", "RUGI BESAR"
                pl_action = "Jika menembus SL, segera keluar"
        else:
            pl_color, pl_icon, pl_status = "#64748b", "❔", "P/L Tidak Tersedia"
            pl_action = "Isi harga beli untuk kalkulasi P/L"
            floating_pl_pct = 0

        # Gauge bar position (clamp -20..+20)
        pl_val = floating_pl_pct or 0
        pl_bar_pct = max(-20, min(20, pl_val))
        pl_bar_position = (pl_bar_pct + 20) / 40 * 100  # 0..100

        st.markdown(f"""<div style="background:linear-gradient(135deg,#1e293b 0%,#0f172a 100%); border-radius:12px; padding:18px; margin-top:16px; border:1px solid #334155;">
<div style="display:flex; align-items:center; gap:14px; margin-bottom:14px; flex-wrap:wrap;">
<div style="font-size:36px;">{pl_icon}</div>
<div style="flex:1; min-width:150px;">
<div style="color:#94a3b8; font-size:10px; text-transform:uppercase; letter-spacing:1.2px;">Status Posisi Kamu</div>
<div style="color:{pl_color}; font-size:20px; font-weight:700; margin-top:2px;">{pl_status} {pl_val:+.2f}%</div>
</div>
<div style="background:{pl_color}22; border:1px solid {pl_color}; border-radius:8px; padding:6px 12px; color:{pl_color}; font-size:11px; font-weight:600;">{pl_action}</div>
</div>
<div style="background:#0f1116; border-radius:6px; padding:6px; height:24px; position:relative; margin-top:8px;">
<div style="position:absolute; left:50%; top:0; bottom:0; width:2px; background:#475569;"></div>
<div style="position:absolute; left:{pl_bar_position:.1f}%; top:3px; bottom:3px; width:14px; margin-left:-7px; background:{pl_color}; border-radius:7px; box-shadow:0 0 8px {pl_color};"></div>
</div>
<div style="display:flex; justify-content:space-between; color:#64748b; font-size:10px; margin-top:6px;">
<span>-20%</span>
<span>0%</span>
<span>+20%</span>
</div>
</div>""", unsafe_allow_html=True)
    else:
        # Kalau belum punya posisi, tampilkan hint
        st.markdown(f"""<div style="background:#1e293b; border-radius:10px; padding:14px 18px; margin-top:16px; border-left:4px solid #64748b; display:flex; align-items:center; gap:12px;">
<div style="font-size:28px;">🆓</div>
<div>
<div style="color:#94a3b8; font-size:10px; text-transform:uppercase; letter-spacing:1.2px;">Status Posisi</div>
<div style="color:#cbd5e1; font-size:13px; margin-top:2px;">Belum punya posisi di saham ini. Siap entry di zona rekomendasi.</div>
</div>
</div>""", unsafe_allow_html=True)

    # ═══ CARD 4 — TIPS & WARNINGS ═══
    tips = []
    if "BUY" in signal:
        if rrr < 1.5:
            tips.append(("💡", "#f59e0b",
                         f"<b>Tips Dip Entry:</b> Untuk RRR ideal 1:2.0, antri beli di <b>Rp {entry_ideal_f:,.0f}</b> atau lebih rendah"))
        if sl_pct > 10.0:
            tips.append(("⚠️", "#ef4444",
                         f"<b>SL Lebar (-{sl_pct:.1f}%):</b> Sesuaikan ukuran posisi maksimal <b>{risk_adjusted_alloc:.1f}%</b> dari modal agar risiko total terjaga"))

    if tips:
        for icon, color, text in tips:
            st.markdown(f"""<div style="background:{color}12; border-left:4px solid {color}; border-radius:8px; padding:12px 16px; margin-top:10px; color:#cbd5e1; font-size:13px; line-height:1.5;">
<span style="color:{color}; font-weight:bold; font-size:15px;">{icon}</span>&nbsp;&nbsp;{text}
</div>""", unsafe_allow_html=True)

    # ═══ DISCLAIMER ═══
    st.markdown("""<div style="color:#64748b; font-size:11px; margin-top:20px; text-align:center; font-style:italic;">
⚠️ Hasil pengujian berbasis permodelan matematika probabilitas kuantitatif historis. Keputusan akhir eksekusi modal tetap merupakan tanggung jawab penuh masing-masing investor.
</div>""", unsafe_allow_html=True)

    # ===== DETAIL EXPANDER =====
    with st.expander("🔍 Lihat Detail Analisis (Berita, Fundamental, Backtest, dll)"):
        st.subheader("📰 Sentimen Berita Terbobot")
        c1, c2 = st.columns([1, 2])
        c1.metric("Sentimen Skor", f"{avg_sentiment:.2f}", sentimen_status)
        with c2:
            st.markdown("**5 Berita Utama Pasar:**")
            for i, h in enumerate(headlines):
                src = sources[i] if i < len(sources) else ""
                t = translated[i] if i < len(translated) else ""
                st.markdown(f"{i+1}. **{h}** <span class='source'>({src})</span>", unsafe_allow_html=True)
                if t and t != h:
                    st.markdown(f"<span class='translated'>🇮🇩 {t}</span>", unsafe_allow_html=True)

        st.divider()
        st.subheader("🧬 Regime Pasar & Volatilitas")
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Market Regime", regime)
        m2.metric("Kondisi Makro IHSG", ihsg_cond)
        m3.metric("ADX Adaptif", f"{adx:.1f} (Thresh: {adx_threshold:.1f})")
        m4.metric("OFI Ratio", f"{ofi_now:.2f}")
        if is_daytrade:
            vwap_col = st.columns(1)[0]
            vwap_col.metric("VWAP", f"{vwap_now:,.0f}", vwap_bias)
        st.markdown(f"**Insight Regime:** {generate_regime_insight(regime, adx, ofi_now, ihsg_cond)}")

        st.divider()
        st.subheader("📊 Metrik Fundamental Saham (IDX)")
        if ticker_info:
            def clean_val(v, f="{:.2f}"):
                return "N/A" if v is None else f.format(v)

            def singkat_angka(n):
                if n is None:
                    return "N/A"
                n = float(n)
                if n >= 1e12:
                    return f"{n/1e12:,.1f} T"
                elif n >= 1e9:
                    return f"{n/1e9:,.0f} M"
                else:
                    return f"{n:,.0f}"

            mc_short = singkat_angka(mc)
            table_html = (
                f"<table class='fundamental-table'>"
                f"<tr><td>Market Cap</td><td>{mc_short} IDR</td></tr>"
                f"<tr><td>PER</td><td>{clean_val(per, '{:.2f}x')}</td></tr>"
                f"<tr><td>PBV</td><td>{clean_val(pbv, '{:.2f}x')}</td></tr>"
                f"<tr><td>ROE</td><td>{clean_val(roe*100 if roe else None, '{:.1f}%')}</td></tr>"
                f"<tr><td>D/E</td><td>{clean_val(de, '{:.2f}%')}</td></tr>"
                f"</table>"
            )
            st.markdown(table_html, unsafe_allow_html=True)

            interpretation_items = []
            if mc:
                if mc >= 1e13:
                    mct = f"Market Cap Rp {mc:,.0f} tergolong sangat besar (Mega Cap)."
                elif mc >= 1e12:
                    mct = f"Market Cap Rp {mc:,.0f} tergolong besar (Blue Chip)."
                elif mc >= 1e10:
                    mct = f"Market Cap Rp {mc:,.0f} tergolong menengah (Mid Cap)."
                else:
                    mct = f"Market Cap Rp {mc:,.0f} tergolong kecil (Small Cap)."
            else:
                mct = "Market Cap tidak tersedia."
            interpretation_items.append(f"<li><b>Market Cap:</b> {mct}</li>")

            if per:
                if per < 10:
                    pt = f"PER {per:.2f}x tergolong rendah (potensi undervalue)."
                elif per < 20:
                    pt = f"PER {per:.2f}x moderat."
                else:
                    pt = f"PER {per:.2f}x tergolong tinggi (premium)."
            else:
                pt = "PER tidak tersedia."
            interpretation_items.append(f"<li><b>PER:</b> {pt}</li>")

            if pbv:
                if pbv < 1:
                    pbt = f"PBV {pbv:.2f}x di bawah 1 (di bawah nilai buku, bisa undervalue)."
                elif pbv < 3:
                    pbt = f"PBV {pbv:.2f}x moderat."
                else:
                    pbt = f"PBV {pbv:.2f}x tinggi (premium)."
            else:
                pbt = "PBV tidak tersedia."
            interpretation_items.append(f"<li><b>PBV:</b> {pbt}</li>")

            if roe:
                roep = roe * 100
                if roep > 20:
                    rt = f"ROE {roep:.1f}% sangat baik (profitabilitas tinggi)."
                elif roep > 10:
                    rt = f"ROE {roep:.1f}% cukup baik."
                else:
                    rt = f"ROE {roep:.1f}% rendah."
            else:
                rt = "ROE tidak tersedia."
            interpretation_items.append(f"<li><b>ROE:</b> {rt}</li>")

            if de:
                if de > 1:
                    dt = f"D/E {de:.2f} tinggi (leverage tinggi, risiko lebih besar)."
                elif de > 0.5:
                    dt = f"D/E {de:.2f} moderat."
                else:
                    dt = f"D/E {de:.2f} rendah (konservatif)."
            else:
                dt = "D/E tidak tersedia."
            interpretation_items.append(f"<li><b>D/E:</b> {dt}</li>")

            st.markdown(f'<div style="background-color:#1e293b;border-radius:12px;padding:15px;margin-top:15px;color:#cbd5e1;font-size:14px;"><b style="color:#00ffcc;">📝 Interpretasi Metrik:</b><ul style="margin-top:8px;padding-left:20px;">{"".join(interpretation_items)}</ul></div>', unsafe_allow_html=True)
        else:
            st.warning("⚠️ Data fundamental finansial tidak tersedia.")

        st.divider()
        st.subheader("🎯 Target Pivot & Support/Resistance")
        p1, p2, p3, p4, p5 = st.columns(5)
        r2_f = fraksi_bei(r2)
        r1_f = fraksi_bei(r1)
        pp_f = fraksi_bei(pp)
        s1_f = fraksi_bei(s1)
        s2_f = fraksi_bei(s2)

        p1.metric("R2", f"Rp {r2_f:,.0f}".replace(",", "."))
        p2.metric("R1", f"Rp {r1_f:,.0f}".replace(",", "."))
        p3.metric("Pivot", f"Rp {pp_f:,.0f}".replace(",", "."))
        p4.metric("S1", f"Rp {s1_f:,.0f}".replace(",", "."))
        p5.metric("S2", f"Rp {s2_f:,.0f}".replace(",", "."))
        st.write(f"Kondisi {breakout_label}: **{breakout}**")

        st.divider()
        st.subheader("🔮 Sinyal Kuantitatif & Hasil Backtest" + (" (Intraday)" if is_daytrade else " (6 Bulan)"))
        if "AVOID" not in signal:
            c1, c2, c3, c4, c5 = st.columns(5)
            c1.metric("Sinyal", signal)
            c2.metric(estimasi_label, f"Rp {est_besok_f:,.0f}".replace(",", "."))
            c3.metric("Entry Zone", entry_zone_f)
            c4.metric("TP Range", f"Rp {tp_low_f:,.0f} - Rp {tp_high_f:,.0f}",
                      f"+{tp_pct_low:.1f}% ~ +{tp_pct_high:.1f}%")
            c5.metric("Stop Loss", f"Rp {sl_harga_f:,.0f}", f"-{sl_pct:.1f}%")
        else:
            c1, c2 = st.columns(2)
            c1.metric("Sinyal", signal)
            c2.metric(estimasi_label, f"Rp {est_besok_f:,.0f}".replace(",", "."))
            st.info("⛔ Tidak ada rekomendasi entry, TP, atau SL untuk sinyal AVOID.")

        st.markdown(f"**Hasil Backtest ({backtest_window} Bar):**")
        b1, b2, b3, b4, b5, b6 = st.columns(6)
        b1.metric("Win Rate", f"{win_bt:.1%}" if trades_bt else "N/A")
        b2.metric("Profit Factor", f"{pf_bt:.2f}" if trades_bt and pf_bt != np.inf else "N/A")
        b3.metric("Avg Return/Trade", f"{avg_bt:.2%}" if trades_bt else "N/A")
        b4.metric("Max DD Strat", f"{max_dd_bt:.2f}%" if trades_bt else "N/A")
        b5.metric("Sharpe", f"{sharpe_bt:.2f}" if trades_bt else "N/A")
        b6.metric("Total Trades", trades_bt)
        st.caption(
            "ℹ️ WR & PF dihitung dari 3 faktor bar-by-bar (Momentum, MeanRev, OFI). "
            "Faktor Bandar/Senti/Foreign/Coppock tidak direkonstruksi historis — "
            "angka ini *lower bound*, bukan proyeksi."
        )
        st.divider()
        st.subheader("🛡️ Manajemen Risiko Portofolio (Kelly)")
        rc1, rc2 = st.columns(2)
        rc1.metric("Alokasi Maks (Kelly)", f"{kelly_adj*100:.1f}%")
        rc2.metric("Beta IHSG", f"{beta_ihsg:.2f}x")
        st.markdown(f"**Interpretasi:** Berdasarkan Win Rate **{win_bt:.1%}**, maksimal alokasi **{kelly_adj*100:.1f}%** dari total ekuitas.")
        st.markdown(f"Max DD Historis: `{max_dd:.2f}%` | DD 30 Hari: `{max_dd_30:.2f}%`")

        st.divider()
        _mc_label = res.get("mc_regime_label", "Monte Carlo")
        st.subheader(f"🎲 Simulasi Monte Carlo — {_mc_label}")
        pr1, pr2, pr3 = st.columns(3)
        pr1.metric(prob_label, f"{prob_bull:.1f}%")
        pr2.metric("Prob. Sentuh R1 (30H)", f"{hit_tp:.1f}%")
        pr3.metric("Prob. Sentuh S2 (30H)", f"{hit_sl:.1f}%")

    # V12 ADAPTIVE ENGINE – EXPANDER & LOGIC (DENGAN INSIGHT)
    with st.expander("🧬 V12 Adaptive Engine (Coppock, Self‑Learning)"):
        st.info(
            "⚙️ **Bagian ini adalah otak adaptif dari QuantRisk Pro.** "
            "Engine secara otomatis mempelajari akurasi setiap faktor teknikal berdasarkan riwayat analisis kamu. "
            "Semakin sering suatu ticker dianalisis, semakin akurat bobot yang dihasilkan."
        )

        if not is_daytrade:
            st.markdown("### 📈 Coppock Curve & Beta IHSG")
            if coppock_turning_up:
                coppock_insight = "🟢 **Turning Up** – Sinyal awal akumulasi. Momentum bullish jangka panjang mulai terbentuk, potensi tren naik."
            elif coppock_rising:
                coppock_insight = "🟢 **Rising** – Tren bullish jangka panjang masih sehat. Akumulasi masih berlangsung."
            else:
                coppock_insight = "🔴 **Falling** – Momentum bullish melemah. Waspadai potensi koreksi atau perubahan tren."
            if beta_ihsg > 1.2:
                beta_insight = f"⚠️ **Beta Tinggi ({beta_ihsg:.2f})** – Saham lebih volatile dari IHSG. Cocok untuk *trading agresif*, namun risikonya lebih besar saat pasar turun."
            elif beta_ihsg > 0.8:
                beta_insight = f"✅ **Beta Moderat ({beta_ihsg:.2f})** – Pergerakan selaras dengan IHSG. Cocok untuk *swing trading*."
            else:
                beta_insight = f"🛡️ **Beta Rendah ({beta_ihsg:.2f})** – Saham defensif, lebih stabil dari IHSG. Cocok untuk *investasi jangka panjang*."
            col_cop1, col_cop2 = st.columns(2)
            with col_cop1:
                st.metric("Coppock Curve", f"{coppock_val:.3f}",
                          "Turning Up ✅" if coppock_turning_up else ("Rising 📈" if coppock_rising else "Falling 📉"))
                st.caption(coppock_insight)
            with col_cop2:
                st.metric("Beta IHSG", f"{beta_ihsg:.2f}x", help="Beta > 1 : lebih volatile dari IHSG, Beta < 1 : lebih stabil.")
                st.caption(beta_insight)
        else:
            st.markdown("### 📈 Beta IHSG")
            if beta_ihsg > 1.2:
                beta_insight = f"⚠️ **Beta Tinggi ({beta_ihsg:.2f})** – Saham lebih volatile dari IHSG. Cocok untuk *trading agresif*, namun risikonya lebih besar saat pasar turun."
            elif beta_ihsg > 0.8:
                beta_insight = f"✅ **Beta Moderat ({beta_ihsg:.2f})** – Pergerakan selaras dengan IHSG. Cocok untuk *swing trading*."
            else:
                beta_insight = f"🛡️ **Beta Rendah ({beta_ihsg:.2f})** – Saham defensif, lebih stabil dari IHSG. Cocok untuk *investasi jangka panjang*."
            st.metric("Beta IHSG", f"{beta_ihsg:.2f}x", help="Beta > 1 : lebih volatile dari IHSG, Beta < 1 : lebih stabil.")
            st.caption(beta_insight)
            st.info("ℹ️ Coppock Curve tidak ditampilkan untuk Day Trade karena kurang relevan dengan timeframe intraday.")

        st.markdown("### ⚓ Multi-Timeframe (MTF) Alignment")
        st.info(res.get('mtf_status_text', 'N/A'))
        if not res.get('is_mtf_bullish', True):
            st.warning("⚠️ Tren timeframe atasan sedang tidak mendukung (Counter-Trend). Sinyal beli diturunkan risikonya.")

        st.markdown("### 🔬 Volume Spread Analysis (VSA)")
        vsa_text = res.get('vsa_status_text', 'N/A')
        if res.get('is_marking_close') or res.get('is_no_demand'):
            st.error(f"**{vsa_text}**")
        elif res.get('is_stopping_volume'):
            st.success(f"**{vsa_text}**")
        else:
            st.info(vsa_text)
        # Legenda interpretasi VSA
        with st.expander("ℹ️ Cara Membaca VSA", expanded=False):
            st.markdown(
                "- **⚠️ Marking Close:** Harga ditarik naik di 10 menit terakhir penutupan dengan volume sangat sepi. "
                "Kemungkinan besar saham akan *gap down* atau tertekan keesokan harinya.\n"
                "- **🔴 No Demand:** Candle bullish dengan spread sempit & volume di bawah rata-rata. "
                "Breakout palsu — tidak ada partisipasi buyer besar.\n"
                "- **🟢 Stopping Volume:** Candle bearish besar dengan volume meledak, tetapi harga menutup di atas tengah candle. "
                "Sinyal *smart money* sedang menampung barang (*absorption*). Waspadai *reversal*."
            )

        st.markdown("### ⚖️ Bobot Adaptif per Faktor")
        st.caption(
            "Bobot di bawah dihitung otomatis berdasarkan **akurasi historis** masing‑masing faktor. "
            "Faktor yang sering benar mendapat bobot lebih tinggi. Bobot ini digunakan untuk sinyal akhir."
        )

        if is_daytrade:
            display_adaptive_w = {k: v for k, v in adaptive_w.items() if k != "Coppock"}
            st.caption("ℹ️ Faktor **Coppock** tidak ditampilkan dalam bobot adaptif untuk Day Trade karena kurang relevan secara intraday. "
                       "Namun, data-nya tetap dihitung di background untuk menjaga konsistensi historis.")
        else:
            display_adaptive_w = adaptive_w

        w_df = pd.DataFrame.from_dict(display_adaptive_w, orient='index', columns=['Weight'])
        st.bar_chart(w_df)

        if display_adaptive_w:
            max_factor = max(display_adaptive_w, key=display_adaptive_w.get)
            min_factor = min(display_adaptive_w, key=display_adaptive_w.get)
            max_weight = display_adaptive_w[max_factor]
            min_weight = display_adaptive_w[min_factor]

            weight_insight = f"🔍 **Faktor paling dominan:** **{max_factor}** (bobot {max_weight:.1%}). "
            weight_insight += f"**{min_factor}** memiliki bobot terendah ({min_weight:.1%}).\n\n"

            interpretations = {
                "Momentum": "Sinyal momentum (harga 5 hari) paling berpengaruh – pasar sedang *trend-following*. Ikuti tren yang sedang berlangsung.",
                "AI_Senti": "Sentimen berita paling berpengaruh – pergerakan saham banyak dipicu oleh berita/isu terkini. Pantau terus sentimen.",
                "MeanRev": "*Reversal* ke rata-rata (Z-Score) paling berpengaruh – saham cenderung kembali ke level wajar setelah jenuh beli/jual.",
                "Beta_IHSG": "Beta IHSG paling berpengaruh – saham sangat terpengaruh oleh pergerakan pasar secara keseluruhan. Perhatikan arah IHSG.",
                "Coppock": "Coppock Curve paling berpengaruh – sinyal jangka panjang mendominasi, tren utama sedang kuat. Ikuti sinyal makro.",
                "OFI": "Order Flow Imbalance (OFI) paling berpengaruh – tekanan order book agresif sangat menentukan arah pergerakan.",
                "Bandar_Flow": "Bandarmology (Top 3 Net Buy) paling berpengaruh – akumulasi/distribusi bandar memegang kendali atas tren saat ini.",
                "Foreign_ZScore": "Foreign Flow paling berpengaruh – aksi beli/jual investor asing menjadi penggerak utama saham ini."
            }
            weight_insight += interpretations.get(max_factor, "")
            st.info(weight_insight)
        st.markdown("### 🐋 Bandar Flow (Multi-Day)")
        bm = res.get('bandar_metadata', {})

        if bm.get('n_snapshots', 0) > 0:
            score = bm['score']
            trend = bm['trend']
            n_snap = bm['n_snapshots']
            fresh = bm.get('freshness_hours')
            latest_date = bm.get('latest_date', 'N/A')

            # Tentukan warna & label
            if trend == 'accumulating':
                trend_icon, trend_color, trend_label = "🟢", "#10b981", "AKUMULASI"
            elif trend == 'distributing':
                trend_icon, trend_color, trend_label = "🔴", "#ef4444", "DISTRIBUSI"
            else:
                trend_icon, trend_color, trend_label = "⚖️", "#94a3b8", "MIXED"

            # Freshness label
            if fresh is not None:
                if fresh < 24:
                    fresh_str = f"{fresh:.0f} jam lalu"
                else:
                    fresh_str = f"{fresh/24:.1f} hari lalu"
            else:
                fresh_str = "unknown"

            # ── Header card ──
            st.markdown(f"""
            <div style="background:linear-gradient(135deg,{trend_color}18 0%,#1e293b 100%);
                border-left:4px solid {trend_color}; border-radius:10px;
                padding:12px 16px; margin-bottom:10px;">
                <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;">
                    <div>
                        <div style="color:{trend_color};font-size:10px;font-weight:700;
                            letter-spacing:1.2px;text-transform:uppercase;">
                            {trend_icon} {trend_label}
                        </div>
                        <div style="color:#f3f4f6;font-size:22px;font-weight:800;
                            margin-top:4px;letter-spacing:-0.01em;">
                            {score:+.3f}
                        </div>
                    </div>
                    <div style="text-align:right;">
                        <div style="color:#94a3b8;font-size:10px;">
                            {n_snap} snapshot · EOD {latest_date}
                        </div>
                        <div style="color:#64748b;font-size:10px;margin-top:2px;">
                            🕒 {fresh_str}
                        </div>
                    </div>
                </div>
            </div>
            """, unsafe_allow_html=True)

            # ── Breakdown komponen skor ──
            comp1, comp2, comp3 = st.columns(3)
            comp1.metric(
                "Weighted Net",
                f"{bm['raw_weighted']:+.3f}",
                help="Weighted average net flow dari N snapshot (decay 0.75)"
            )
            comp2.metric(
                "Consistency Bonus",
                f"{bm['consistency_bonus']:+.2f}",
                help="Bonus dari broker yang muncul konsisten di top buyer/seller"
            )
            comp3.metric(
                "Panic Bonus",
                f"{bm['panic_bonus']:+.2f}",
                help="Retail panic → contrarian bullish signal"
            )

            # ── Konsistensi broker ──
            cb = bm.get('consistent_buyers', [])
            cs = bm.get('consistent_sellers', [])

            if cb or cs:
                st.markdown("**🔁 Broker Konsisten (≥60% snapshot):**")
                cols = st.columns(2)
                with cols[0]:
                    if cb:
                        st.markdown(
                            f"<div style='background:#10b98115;border-left:3px solid #10b981;"
                            f"border-radius:6px;padding:8px 12px;'>"
                            f"<div style='color:#10b981;font-size:10px;font-weight:700;'>"
                            f"🐋 AKUMULATOR KONSISTEN</div>"
                            f"<div style='color:#cbd5e1;font-size:12px;margin-top:4px;'>"
                            f"{', '.join(cb)}</div></div>",
                            unsafe_allow_html=True
                        )
                    else:
                        st.caption("_Tidak ada akumulator konsisten_")
                with cols[1]:
                    if cs:
                        st.markdown(
                            f"<div style='background:#ef444415;border-left:3px solid #ef4444;"
                            f"border-radius:6px;padding:8px 12px;'>"
                            f"<div style='color:#ef4444;font-size:10px;font-weight:700;'>"
                            f"🔻 DISTRIBUTOR KONSISTEN</div>"
                            f"<div style='color:#cbd5e1;font-size:12px;margin-top:4px;'>"
                            f"{', '.join(cs)}</div></div>",
                            unsafe_allow_html=True
                        )
                    else:
                        st.caption("_Tidak ada distributor konsisten_")

            # ── Retail panic warning — soft green card (bukan st.warning kuning) ──
            if bm.get('retail_panic_detected'):
                st.markdown("""
                    <div style="background:linear-gradient(135deg,#10b98112 0%,#10b98105 100%);
                        border-left:4px solid #10b981;
                        border-radius:8px;
                        padding:10px 14px;
                        margin-top:10px;">
                        <div style="display:flex;align-items:flex-start;gap:10px;">
                            <span style="font-size:16px;line-height:1.2;">🟢</span>
                            <div>
                                <div style="color:#10b981;font-size:11px;font-weight:700;
                                    letter-spacing:0.8px;text-transform:uppercase;margin-bottom:3px;">
                                    Retail Panic Detected
                                </div>
                                <div style="color:#cbd5e1;font-size:11.5px;line-height:1.55;">
                                    Retail konsisten jual <b style="color:#e2e8f0;">3+ hari</b>.
                                    Secara contrarian, ini sering jadi sinyal <b style="color:#34d399;">bottom</b> —
                                    retail sudah cutloss.
                                </div>
                            </div>
                        </div>
                    </div>
                """, unsafe_allow_html=True)
        else:
            st.info(
                "ℹ️ Belum cukup snapshot broksum untuk multi-day analysis. "
                "Upload broksum minimal 3-5 hari untuk mengaktifkan fitur ini."
            )
        st.markdown("### 🧠 Status Memori Adaptif")
        st.caption(
            "**Accuracy** = seberapa sering sinyal faktor sesuai arah harga. **Error EMA** = rata‑rata kesalahan prediksi (makin kecil makin baik)."
        )
        mem = st.session_state.v12_memory.get(ticker_raw, {})
        if mem:
            keys_to_show = [k for k in FACTOR_KEYS if not (is_daytrade and k == "Coppock")]
            acc_data = {k: mem.get('accuracy', {}).get(k, 0.5) for k in keys_to_show}
            err_data = {k: mem.get('error_ema', {}).get(k, 1.0) for k in keys_to_show}

            col_a, col_e = st.columns(2)
            with col_a:
                st.caption("✅ Accuracy (higher = better)")
                st.bar_chart(pd.Series(acc_data))
            with col_e:
                st.caption("⚠️ Error EMA (lower = better)")
                st.bar_chart(pd.Series(err_data))

            best_factor = max(acc_data, key=acc_data.get)
            worst_factor = min(acc_data, key=acc_data.get)
            mem_insight = f"🏆 **Faktor paling akurat:** **{best_factor}** (akurasi {acc_data[best_factor]:.1%}). "
            mem_insight += f"Faktor **{worst_factor}** perlu dievaluasi (akurasi {acc_data[worst_factor]:.1%})."
            st.caption(mem_insight)

            entry_err = mem.get('entry_error_ema', 0.0)
            if entry_err > 0:
                st.caption(
                    f"🎯 **Rata‑rata error entry:** {entry_err:.2f} poin. "
                    "Entry sering tidak tersentuh, engine akan menggeser zona entry lebih dekat ke harga."
                )
            else:
                st.caption("🎯 **Error entry:** 0 — entry zone sudah cukup baik atau belum ada data Not Touched.")
        else:
            st.info("Belum ada data memori untuk ticker ini. Lakukan analisis beberapa kali agar engine mulai belajar.")

        st.markdown("### 🔁 Proses Self‑Learning")
        st.caption(
            "Setiap analisis, engine membandingkan prediksi sebelumnya dengan harga aktual. "
            "Jika benar → akurasi naik. Jika salah → error bertambah. Bobot otomatis menyesuaikan. "
            "Selain itu, engine juga mempelajari **level entry** dari kejadian Entry Tidak Tersentuh."
        )

        last_pred = load_v12_predictions(ticker_raw, mode='daytrade' if is_daytrade else 'swing')
        if last_pred:
            last_close = safe_float(last_pred.get('close_price'), 0.0)
            if last_close > 0:
                last_signals = {}
                for k in FACTOR_KEYS:
                    key = f'sig_{k}'
                    if key in last_pred:
                        last_signals[k] = safe_float(last_pred[key], 0.0)
                    else:
                        last_signals[k] = 0.0

                actual_return = (harga_terakhir - last_close) / last_close
                volatility = returns.std()
                update_v12_memory(ticker_raw, last_signals, actual_return, volatility)
                st.success(f"✅ Memory updated! Actual return sejak prediksi terakhir: {actual_return*100:.2f}%")
            else:
                st.info("ℹ️ Prediksi sebelumnya tidak memiliki close_price yang valid.")
        else:
            st.info("ℹ️ Tidak ada prediksi sebelumnya. Engine akan mulai belajar pada analisis berikutnya.")

    # ==================== AI INSIGHT OTOMATIS ====================
    st.markdown("---")
    if st.session_state.get("gemini_api_key"):
        with st.spinner("🧠 AI sedang menganalisis hasil dan riwayat..."):

            # ═══ FIX: Definisikan act_ticker_data di sini (safe) ═══
            act_ticker_data = hitung_winrate_ticker_actual(
                ticker_raw,
                st.session_state.get('riwayat_actual', {})
            )

            # Safe extraction
            _act_str = "Belum ada evaluasi"
            try:
                if isinstance(act_ticker_data, dict):
                    _tot = act_ticker_data.get('total', 0) or 0
                    _wr  = act_ticker_data.get('win_rate')
                    _w   = act_ticker_data.get('win', 0) or 0
                    _l   = act_ticker_data.get('loss', 0) or 0
                    if _tot > 0 and isinstance(_wr, (int, float)):
                        _act_str = f"{_wr:.1f}% ({_w} Win / {_l} Loss)"
            except Exception:
                _act_str = "Belum ada evaluasi"
            # ═══════════════════════════════════════════════════════

            data_ai = {
                "Saham": ticker_raw,
                "Harga": f"{harga_terakhir:,.0f}",
                "Sinyal": signal,
                "Rezim": regime,
                "Sentimen": f"{avg_sentiment:.2f} ({sentimen_status})",
                "RRR": f"{rrr:.2f} (Kontekstual)",
                "Prob Naik": f"{prob_bull:.1f}%",
                "TP%": f"{tp_pct_low:.1f}% - {tp_pct_high:.1f}%",
                "SL%": f"{sl_pct:.1f}",
                "Estimasi": f"{est_besok_f:,.0f}",
                "Beta": f"{beta_ihsg:.2f}x",
                "WinRate": f"{win_bt:.1%}" if trades_bt else "N/A",
                "Actual_WinRate_Ticker": _act_str,   # ← pakai variable safe
                "ProfitFactor": f"{pf_bt:.2f}" if trades_bt else "N/A",
                "MaxDD": f"{max_dd_bt:.2f}%" if trades_bt else "N/A",
                "Kelly": f"{kelly_adj*100:.1f}",
                "Fundamental_MC": f"{mc:,.0f}" if mc else "N/A",
                "Fundamental_PER": f"{per:.2f}" if per else "N/A",
                "Fundamental_PBV": f"{pbv:.2f}" if pbv else "N/A",
                "Fundamental_ROE": f"{roe*100:.1f}" if roe else "N/A",
                "Fundamental_DE": f"{de:.2f}" if de else "N/A",
                "Status_Posisi": "Sudah memiliki saham" if sudah_beli else "Belum memiliki saham",
                "Harga_Beli": f"Rp {harga_beli_float:,.0f}" if harga_beli_float else "Tidak diisi",
                "Floating_PL": f"{floating_pl_pct:+.2f}%" if floating_pl_pct is not None else "N/A"
            }
            riwayat_konteks = []
            for r in st.session_state.riwayat:
                if r['Saham'] == ticker_raw:
                    r_copy = dict(r)
                    # Ambil mode/gaya dari baris riwayat
                    mode_actual = r.get('Gaya', 'SW')   # "SW" atau "DT"

                    # Coba key 3 elemen (format baru)
                    key_actual_baru = (r.get('Waktu'), r.get('Saham'), mode_actual)
                    actual = st.session_state.riwayat_actual.get(key_actual_baru)

                    # Fallback ke key 2 elemen (format lama)
                    if actual is None:
                        key_actual_lama = (r.get('Waktu'), r.get('Saham'))
                        actual = st.session_state.riwayat_actual.get(key_actual_lama, {})

                    if actual:
                        r_copy['Actual_High']   = actual.get('Actual_High', '')
                        r_copy['Actual_Low']    = actual.get('Actual_Low', '')
                        r_copy['Actual_Close']  = actual.get('Actual_Close', '')
                        r_copy['Actual_Outcome']= actual.get('Outcome', '')
                        r_copy['Entry_Miss']    = actual.get('Entry_Miss', '')

                    riwayat_konteks.append(r_copy)
                    if len(riwayat_konteks) >= 20:
                        break

            hasil_ai, error_ai = analisis_saham_dengan_ai(
                data_ai,
                riwayat_konteks,
                st.session_state.gemini_api_key,
                ticker=ticker_raw
            )            
            if not error_ai and hasil_ai:
                hasil_ai_bersih = bersihkan_teks_ai(hasil_ai)
                html_ai = f'<div class="ai-insight-card"><h3>🤖 Insight AI</h3><p>{hasil_ai_bersih}</p></div>'
                st.markdown(html_ai, unsafe_allow_html=True)
            elif error_ai:
                st.warning(f"AI tidak dapat memberikan insight: {error_ai}")
    else:
        st.info("💡 Isi API Key Gemini di sidebar untuk mendapatkan insight AI otomatis.")