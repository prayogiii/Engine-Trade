"""
Sidebar QuantRisk Pro — input analysis, scan broksum, riwayat, kalender.

Berisi SATU fungsi publik: render_sidebar().
Semua helper nested tetap di dalam body-nya supaya konsisten dengan versi lama.
"""
from __future__ import annotations

import time
from datetime import datetime

import pandas as pd
import pytz
import streamlit as st

# ── Config & Core ──
from config.calendar import status_bursa, libur_dalam_n_hari
from core.indicators import fraksi_bei
from core.riwayat import (
    hitung_winrate_ticker_actual,
    diagnose_winrate_trend,
    get_dip_entry,
    dapatkan_dict_swing_aktif,
    dapatkan_sinyal_perlu_dicatat,
)

# ── Services ──
from services.gemini_client import _load_gemini_keys, _get_key_rotator_state
from services.sheets_client import (
    get_gsheet,
    get_broksum_cache,
    hapus_riwayat_item,
    simpan_riwayat_actual,
    muat_riwayat_actual,
    integrate_actual_to_v12,
)
from ui.components.broker_summary import (
    render_broker_summary_and_aggregate_ui,
    _render_broksum_net_insight,
    _get_broksum_for_date,
)
from ui.components.riwayat_notification import render_notifikasi_evaluasi_riwayat
# ── UI components ──
from ui.components.broksum_upload import render_broksum_scan_ui

def render_sidebar():
    with st.sidebar:
        # SIDEBAR CUSTOM STYLING
        st.markdown("""
            <style>
            /* Sidebar container */
            section[data-testid="stSidebar"] {
                background: linear-gradient(180deg, #0f1116 0%, #131720 100%);
                border-right: 1px solid #1e293b;
            }
            section[data-testid="stSidebar"] > div {
                padding-top: 10px;
            }

            /* Section header */
            .sb-section {
                display: flex;
                align-items: baseline;
                gap: 8px;
                padding: 14px 0 6px 0;
                margin: 6px 0 4px 0;
                border-top: 1px solid #1e293b;
            }
            .sb-section.first { border-top: none; margin-top: 0; padding-top: 4px; }
            .sb-section-icon { font-size: 15px; line-height: 1; }
            .sb-section-title {
                color: #f3f4f6;
                font-size: 11px;
                font-weight: 700;
                letter-spacing: 1.3px;
                text-transform: uppercase;
            }
            .sb-section-caption {
                color: #64748b;
                font-size: 10px;
                margin-left: 2px;
                font-weight: 500;
                letter-spacing: 0.2px;
                text-transform: none;
            }

            /* Brand header */
            .sb-brand {
                background: linear-gradient(135deg, #00ffcc0a 0%, #a855f70a 100%);
                border: 1px solid #1e293b;
                border-radius: 12px;
                padding: 14px 16px;
                margin: 4px 0 6px 0;
                position: relative;
                overflow: hidden;
            }
            .sb-brand::before {
                content: '';
                position: absolute;
                top: 0; left: 0; right: 0;
                height: 2px;
                background: linear-gradient(90deg, #00ffcc, #a855f7, #00ffcc);
            }
            .sb-brand-title {
                color: #f3f4f6;
                font-size: 19px;
                font-weight: 800;
                letter-spacing: -0.02em;
                margin: 0;
                line-height: 1.1;
            }
            .sb-brand-title span { color: #00ffcc; }
            .sb-brand-sub {
                color: #64748b;
                font-size: 9px;
                margin-top: 5px;
                letter-spacing: 1.4px;
                text-transform: uppercase;
                font-weight: 600;
            }

            /* Active swing alert */
            .sb-alert-swing {
                background: linear-gradient(135deg, #a855f718 0%, #a855f705 100%);
                border-left: 3px solid #a855f7;
                border-radius: 8px;
                padding: 10px 12px;
                margin: 10px 0;
            }
            .sb-alert-swing-title {
                color: #c084fc;
                font-size: 10px;
                font-weight: 700;
                letter-spacing: 1px;
                margin-bottom: 5px;
                text-transform: uppercase;
            }
            .sb-alert-swing-body {
                color: #cbd5e1;
                font-size: 11px;
                line-height: 1.55;
            }
            .sb-alert-swing-body b { color: #e9d5ff; }

            /* API status pill */
            .sb-api-ok {
                background: #10b98115;
                border: 1px solid #10b98140;
                color: #10b981;
                font-size: 10px;
                font-weight: 700;
                padding: 7px 10px;
                border-radius: 7px;
                text-align: center;
                letter-spacing: 0.4px;
            }
            .sb-api-off {
                background: #f59e0b15;
                border: 1px solid #f59e0b40;
                color: #f59e0b;
                font-size: 10px;
                font-weight: 700;
                padding: 7px 10px;
                border-radius: 7px;
                text-align: center;
                letter-spacing: 0.4px;
            }

            /* Buttons */
            section[data-testid="stSidebar"] .stButton > button {
                border-radius: 8px;
                font-weight: 600;
                font-size: 12px;
                padding: 8px 12px;
                transition: all 0.15s ease;
            }
            section[data-testid="stSidebar"] .stButton > button[kind="primary"] {
                background: linear-gradient(135deg, #00ffcc 0%, #10b981 100%);
                color: #0f1116;
                border: none;
                font-weight: 700;
                letter-spacing: 0.4px;
            }
            section[data-testid="stSidebar"] .stButton > button[kind="primary"]:hover {
                box-shadow: 0 4px 14px rgba(0, 255, 204, 0.35);
                transform: translateY(-1px);
            }

            /* Inputs */
            section[data-testid="stSidebar"] .stTextInput > div > div > input,
            section[data-testid="stSidebar"] .stNumberInput > div > div > input,
            section[data-testid="stSidebar"] .stSelectbox > div > div > div {
                border-radius: 8px;
                font-size: 12px;
            }

            /* Expander polish */
            section[data-testid="stSidebar"] details {
                border: 1px solid #1e293b !important;
                border-radius: 10px;
                background: #0d1017;
                overflow: hidden;
                margin-top: 6px;
            }
            section[data-testid="stSidebar"] details > summary {
                font-size: 12px;
                font-weight: 600;
                padding: 10px 12px;
                color: #cbd5e1;
            }
            section[data-testid="stSidebar"] details[open] > summary {
                border-bottom: 1px solid #1e293b;
                background: #131720;
            }
            section[data-testid="stSidebar"] details > div {
                padding: 12px;
            }

            /* Dividers */
            section[data-testid="stSidebar"] hr {
                margin: 12px 0;
                border-color: #1e293b;
            }
            </style>
        """, unsafe_allow_html=True)

        # BRAND HEADER
        st.markdown("""
            <div class="sb-brand">
                <div class="sb-brand-title">QuantRisk <span>Pro</span></div>
                <div class="sb-brand-sub">Trading Intelligence · IDX</div>
            </div>
        """, unsafe_allow_html=True)
        st.caption("⚙️ Analisis otomatis **Swing (harian)** + **Daytrade (intraday)**")

        # SECTION 1: ANALYSIS INPUT
        st.markdown("""
            <div class="sb-section first">
                <span class="sb-section-icon">🎯</span>
                <span class="sb-section-title">Analysis Input</span>
            </div>
        """, unsafe_allow_html=True)

        ticker_raw = st.text_input(
            "🔍 Kode Saham",
            value="",
            placeholder="Contoh: BBRI, TLKM, BMRI",
            help="Masukkan kode saham IHSG (tanpa suffix .JK)"
        ).upper().strip()
        if ticker_raw and not ticker_raw.endswith(".JK"):
            ticker_input = f"{ticker_raw}.JK"
        else:
            ticker_input = ticker_raw
        # ── Load Gemini API Key lebih awal (dibutuhkan untuk Scan Broksum di bawah) ──
        def _get_api_key_early():
            """Ambil key pertama dari rotator (untuk status display)."""
            keys = _load_gemini_keys()
            if keys:
                return keys[0]
            return ""
        if not st.session_state.get("gemini_api_key"):
            st.session_state.gemini_api_key = _get_api_key_early()
        # ── Harga Pasar Manual ──
        harga_manual = st.text_input(
            "💵 Harga Pasar (opsional)",
            placeholder="Kosongkan = pakai data Yahoo",
            help="Override harga terakhir kalau data Yahoo stale"
        )
        if harga_manual:
            try:
                harga_terakhir_manual = float(harga_manual.replace(",", ""))
            except:
                st.error("Format harga salah")
                harga_terakhir_manual = None
        else:
            harga_terakhir_manual = None
        # ── Status Posisi ──
        sudah_beli = st.checkbox(
            "🟢 Saya sudah punya posisi di saham ini",
            value=False,
            help="Centang untuk melacak floating P/L"
        )
        harga_beli_float = None
        if sudah_beli:
            harga_beli_str = st.text_input(
                "💰 Harga Beli Rata-rata (opsional)",
                placeholder="Kosongkan jika tidak tahu"
            )
            if harga_beli_str:
                try:
                    harga_beli_float = float(harga_beli_str.replace(",", ""))
                except:
                    st.error("Format harga beli salah")
        # SECTION 2: SCAN BROKSUM (expander)
        with st.expander("📸 Scan Broksum (Gemini AI / OCR)", expanded=False):
            render_broksum_scan_ui(
                api_key=st.session_state.get("gemini_api_key", ""),
                key_prefix="sb_broksum"
            )
        # SECTION 3: ACTIVE SWING DETECTION
        ticker_clean = ticker_raw.replace(".JK", "").strip().upper()
        dict_active_swings = dapatkan_dict_swing_aktif(
            st.session_state.get('riwayat', []),
            st.session_state.get('riwayat_actual', {}),
        )
        aksi_simpan_mode = "simpan_baru"

        if ticker_clean in dict_active_swings:
            active_info = dict_active_swings[ticker_clean]
            st.markdown(f"""
                <div class="sb-alert-swing">
                    <div class="sb-alert-swing-title">⏳ Swing Aktif Terdeteksi</div>
                    <div class="sb-alert-swing-body">
                        <b>{ticker_clean}</b> · Entry {active_info['waktu']}<br>
                        Hari bursa ke-<b>{active_info['b_days']}</b> · Outcome belum diisi
                    </div>
                </div>
            """, unsafe_allow_html=True)

            pilihan_aksi = st.radio(
                "📋 Tindakan Penyimpanan:",
                [
                    "🛡️ Lewati Simpan (Hanya Lihat Analisis)",
                    "🔄 Update Entry Swing Aktif",
                    "➕ Simpan Setup Baru (Re-entry / Add Lot)"
                ],
                index=0,
                key="pilihan_aksi_riwayat_active"
            )
            if "Lewati" in pilihan_aksi:
                aksi_simpan_mode = "lewati"
            elif "Update" in pilihan_aksi:
                aksi_simpan_mode = "update"
            else:
                aksi_simpan_mode = "simpan_baru"

        st.session_state['aksi_simpan_mode'] = aksi_simpan_mode
        # SECTION 4: FEE BROKER (expander)
        with st.expander("⚙️ Fee Broker (Beli & Jual)", expanded=False):
            st.caption("Digunakan untuk hitung nett profit DT & backtest.")
            col_f1, col_f2 = st.columns(2)
            with col_f1:
                fee_beli_pct = st.number_input(
                    "Fee Beli (%)",
                    min_value=0.0, max_value=2.0, value=0.15, step=0.05,
                    key="fee_beli_pct"
                )
            with col_f2:
                fee_jual_pct = st.number_input(
                    "Fee Jual (%)",
                    min_value=0.0, max_value=2.0, value=0.25, step=0.05,
                    key="fee_jual_pct"
                )

        # SECTION 5: ACTION BUTTONS
        st.markdown("<div style='height:8px;'></div>", unsafe_allow_html=True)

        if st.button(
            "🚀  ANALISIS SEKARANG",
            use_container_width=True,
            type="primary",
            key="btn_analisis_primary"
        ):
            st.session_state['_sb_ticker_input'] = ticker_input
            st.session_state['_sb_harga_manual'] = harga_manual
            st.session_state['_sb_harga_terakhir_manual'] = harga_terakhir_manual
            st.session_state['_sb_sudah_beli'] = sudah_beli
            st.session_state['_sb_harga_beli_float'] = harga_beli_float
            st.session_state['_sb_fee_beli_pct'] = fee_beli_pct
            st.session_state['_sb_fee_jual_pct'] = fee_jual_pct
            st.session_state['_sb_run_btn'] = True
            st.rerun()
        # CACHE MANAGEMENT
        col_cache1, col_cache2 = st.columns(2)
        with col_cache1:
            if st.button("🔄 Refresh Broksum", use_container_width=True,
                         key="btn_refresh_broksum",
                         help="Sync data broksum dari device lain"):
                with st.spinner("📡 Mengambil data terbaru..."):
                    get_broksum_cache(force_refresh=True)
                st.success("✅ Cache broksum di-refresh!")
                st.rerun()

        with col_cache2:
            if st.button("🗑️ Reset Cache", use_container_width=True,
                         key="btn_reset_cache"):
                st.cache_data.clear()
                for k in ['broksum_cache', '_broksum_cache_time', '_broksum_cache_error']:
                    st.session_state.pop(k, None)
                st.success("Cache dibersihkan!")
                st.rerun()

        # ── Info status cache ──
        _cache_time = st.session_state.get('_broksum_cache_time', 0)
        if _cache_time > 0:
            _age_min = (time.time() - _cache_time) / 60
            _n_records = len(st.session_state.get('broksum_cache', []))
            st.caption(f"💾 Cache: {_n_records} records · {_age_min:.0f} menit lalu")

        # SECTION 6: SCANNER SAHAM IDX
        st.markdown("""
            <div class="sb-section">
                <span class="sb-section-icon">🔍</span>
                <span class="sb-section-title">Scanner Saham IDX</span>
            </div>
        """, unsafe_allow_html=True)

        mode_scan = st.selectbox(
            "Mode Scan",
            ["Cepat (LQ45)", "Papan Utama", "Komprehensif (Utama + Pengembangan)", "Full IDX", "Auto-Fetch (API BEI)"],
            index=0,
            key="mode_scan"
        )
        likuiditas_min = st.number_input(
            "Likuiditas Min (Rp/hari)",
            min_value=0, value=300_000_000, step=100_000_000,
            key="likuiditas_min",
            help="Rata-rata nilai transaksi 20 hari"
        )
        hide_active_swings = st.checkbox(
            "🚫 Sembunyikan emiten dengan Swing Aktif",
            value=False,
            key="hide_active_swings"
        )
        ai_rerank = st.checkbox(
            "🤖 AI Re-Rank (Top 15)",
            value=False,
            key="ai_rerank"
        )
        if ai_rerank:
            st.caption("ℹ️ +15-30 detik. Hemat kuota Gemini: 1 panggilan batch.")

        if st.button(
            "🔍  SCAN SAHAM",
            use_container_width=True,
            key="btn_scan"
        ):
            st.session_state['_sb_mode_scan'] = mode_scan
            st.session_state['_sb_likuiditas_min'] = likuiditas_min
            st.session_state['_sb_hide_active_swings'] = hide_active_swings
            st.session_state['_sb_ai_rerank'] = ai_rerank
            st.session_state['_sb_scan_btn'] = True
            st.rerun()

        # ---------- HELPER RENDER CARD PER MODE (SIDE-BY-SIDE) ----------
        def render_mode_card(r, mode_title, mode_icon, container, idx_key):
            with container:
                if not r:
                    st.markdown(
                        '<div style="color:#64748b; font-size:11px; font-style:italic; '
                        'padding:10px; text-align:center; background:#0f172a; '
                        'border-radius:8px; border:1px dashed #334155;">'
                        'Data tidak tersedia</div>',
                        unsafe_allow_html=True
                    )
                    return

                sinyal = r.get('Sinyal', '?')
                if "STRONG BUY" in sinyal:
                    sig_color, sig_icon = "#10b981", "🔥"
                elif "BUY" in sinyal:
                    sig_color, sig_icon = "#84cc16", "⚡"
                elif "HOLD" in sinyal:
                    sig_color, sig_icon = "#3b82f6", "⏸️"
                else:
                    sig_color, sig_icon = "#ef4444", "🚨"

                mode_color = "#a855f7" if "Swing" in mode_title else "#06b6d4"

                st.markdown(f"""
                <div style="
                    background: linear-gradient(135deg, {sig_color}18 0%, {sig_color}06 100%);
                    border-left: 4px solid {sig_color};
                    border-radius: 8px;
                    padding: 10px 14px;
                    margin-bottom: 8px;
                ">
                    <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 4px;">
                        <span style="color:{mode_color}; font-size:10px; font-weight:700;
                            letter-spacing:1.2px; text-transform:uppercase;">
                            {mode_icon} {mode_title}
                        </span>
                    </div>
                    <div style="display: flex; align-items: center; gap: 8px;">
                        <span style="font-size:18px; line-height:1;">{sig_icon}</span>
                        <span style="color:{sig_color}; font-size:13px; font-weight:700;">
                            {sinyal.replace('🔥', '').replace('⚡', '').strip()}
                        </span>
                    </div>
                    <div style="color:#94a3b8; font-size:10px; margin-top:4px;">
                        Score <b style="color:#e2e8f0;">{r.get('Score','?')}</b> ·
                        RRR <b style="color:#e2e8f0;">{r.get('RRR','?')}</b> ·
                        Conf <b style="color:#e2e8f0;">{r.get('Confidence','?')}</b>
                    </div>
                </div>
                """, unsafe_allow_html=True)

                # ── Harga beli + floating P/L ──
                harga_beli_r = r.get('Harga_Beli', '')
                if harga_beli_r:
                    floating_pl = r.get('Floating_PL', '')
                    try:
                        pl_val = float(str(floating_pl).replace('%', '').replace('+', ''))
                    except Exception:
                        pl_val = 0
                    pl_color = "#10b981" if pl_val > 0 else ("#ef4444" if pl_val < 0 else "#94a3b8")

                    st.markdown(f"""
                    <div style="background:#1e293b; border-radius:6px; padding:8px 10px;
                        margin-bottom:8px; border-left:3px solid {pl_color};">
                        <div style="display:flex; justify-content:space-between; align-items:center;">
                            <div>
                                <div style="color:#94a3b8; font-size:9px; text-transform:uppercase;">
                                    Beli
                                </div>
                                <div style="color:#e2e8f0; font-size:11px; font-weight:600;">
                                    Rp {harga_beli_r}
                                </div>
                            </div>
                            <div style="text-align:right;">
                                <div style="color:#94a3b8; font-size:9px; text-transform:uppercase;">
                                    Float P/L
                                </div>
                                <div style="color:{pl_color}; font-size:13px; font-weight:700;">
                                    {floating_pl}
                                </div>
                            </div>
                        </div>
                    </div>
                    """, unsafe_allow_html=True)

                # ── Grid teknikal 2x2 ──
                entry_zone = r.get('Entry_Zone', '')
                dip_entry  = get_dip_entry(r)
                tp_range   = r.get('TP_Range', '')
                sl_harga   = r.get('SL_Harga', '')

                cells = []
                if entry_zone:
                    cells.append(("🎯", "Entry", entry_zone, "#00ffcc"))
                if dip_entry:
                    cells.append(("💡", "Dip Entry", dip_entry, "#facc15"))
                if tp_range:
                    cells.append(("📈", "TP", tp_range, "#10b981"))
                if sl_harga:
                    cells.append(("🛑", "SL", f"Rp {sl_harga}", "#ef4444"))

                if cells:
                    html = '<div style="display:grid; grid-template-columns:1fr 1fr; gap:5px; margin-bottom:8px;">'
                    for icon, label, value, color in cells:
                        html += (
                            f'<div style="background:#1e293b; border-radius:5px; padding:6px 8px; '
                            f'border-left:2px solid {color};">'
                            f'<div style="color:#94a3b8; font-size:8px; text-transform:uppercase;">'
                            f'{icon} {label}</div>'
                            f'<div style="color:{color}; font-size:10px; font-weight:600; '
                            f'margin-top:2px; word-break:break-word;">'
                            f'{value}</div>'
                            f'</div>'
                        )
                    html += '</div>'
                    st.markdown(html, unsafe_allow_html=True)

                # ── Status actual / outcome ──
                waktu_key = r.get('Waktu','')
                saham_key = r.get('Saham','')
                gaya_key = r.get('Gaya', 'SW')
                mode_actual = "swing" if gaya_key == "SW" else "daytrade"
                actual_data = (
                    st.session_state.riwayat_actual.get((waktu_key, saham_key, gaya_key)) or
                    st.session_state.riwayat_actual.get((waktu_key, saham_key, mode_actual)) or
                    st.session_state.riwayat_actual.get((waktu_key, saham_key))
                )

                has_actual = False
                if actual_data:
                    if (actual_data.get('Actual_High') or
                        actual_data.get('Actual_Low') or
                        actual_data.get('Actual_Close') or
                        actual_data.get('Outcome') or
                        actual_data.get('Entry_Miss') == 'Yes'):
                        has_actual = True

                if has_actual:
                    outcome = actual_data.get('Outcome', '')
                    entry_miss = actual_data.get('Entry_Miss') == 'Yes'

                    if entry_miss or outcome == 'Not Touched':
                        out_icon, out_color, out_label = "⚪", "#94a3b8", "NOT TOUCHED"
                    elif outcome == 'Win':
                        out_icon, out_color, out_label = "🏆", "#10b981", "WIN"
                    elif outcome == 'Loss':
                        out_icon, out_color, out_label = "💔", "#ef4444", "LOSS"
                    else:
                        out_icon, out_color, out_label = "❓", "#64748b", "PENDING"

                    hi = actual_data.get('Actual_High', '-') or '-'
                    lo = actual_data.get('Actual_Low', '-') or '-'
                    cl = actual_data.get('Actual_Close', '-') or '-'

                    st.markdown(f"""
                    <div style="background:{out_color}10; border:1px solid {out_color}40;
                        border-radius:6px; padding:8px 10px; margin-bottom:6px;">
                        <div style="display:flex; align-items:center; gap:6px; margin-bottom:6px;">
                            <span style="font-size:14px;">{out_icon}</span>
                            <span style="color:{out_color}; font-size:10px; font-weight:700;
                                letter-spacing:1px;">{out_label}</span>
                        </div>
                        <div style="display:grid; grid-template-columns:1fr 1fr 1fr; gap:4px;">
                            <div style="text-align:center;">
                                <div style="color:#94a3b8; font-size:8px;">H</div>
                                <div style="color:#e2e8f0; font-size:10px; font-weight:600;">{hi}</div>
                            </div>
                            <div style="text-align:center;">
                                <div style="color:#94a3b8; font-size:8px;">L</div>
                                <div style="color:#e2e8f0; font-size:10px; font-weight:600;">{lo}</div>
                            </div>
                            <div style="text-align:center;">
                                <div style="color:#94a3b8; font-size:8px;">C</div>
                                <div style="color:#e2e8f0; font-size:10px; font-weight:600;">{cl}</div>
                            </div>
                        </div>
                    </div>
                    """, unsafe_allow_html=True)

                else:
                    _is_avoid = 'AVOID' in str(r.get('Sinyal', '')).upper()
                    if _is_avoid:
                        st.markdown("""
                        <div style="background:#ef444418; border:1px dashed #ef444460;
                            border-radius:6px; padding:6px 10px;
                            font-size:10px; color:#f87171; text-align:center;
                            margin-bottom:6px; font-weight:600;">
                            🚨 Sinyal AVOID — Sebaiknya dihindari · Engine auto-learn
                        </div>
                        """, unsafe_allow_html=True)
                    else:
                        st.markdown("""
                        <div style="background:#1e293b; border-radius:6px; padding:6px 10px;
                            font-size:10px; color:#94a3b8; text-align:center;
                            border:1px dashed #334155; margin-bottom:6px;">
                            ⏳ Outcome belum dicatat · <i>Cek Quick Outcome di atas</i>
                        </div>
                        """, unsafe_allow_html=True)
                # ── Tombol Hapus ──
                del_key = f"del_{idx_key}_{waktu_key}_{saham_key}_{gaya_key}"
                if st.button("🗑️ Hapus dari Riwayat",
                             key=del_key,
                             use_container_width=True,
                             help="Hapus entri ini dari riwayat"):
                    hapus_riwayat_item(waktu_key, saham_key, gaya=gaya_key)
                    st.rerun()

        # SECTION 7: RIWAYAT ANALISIS
        # DIAGNOSTIK WR — cek trend & regime
        with st.expander("🔬 Diagnostik WR (cek trend & regime)", expanded=False):
            diag = diagnose_winrate_trend(
                st.session_state.get('riwayat', []),
                st.session_state.get('riwayat_actual', {})
            )
    
            st.caption(f"Total records dianalisis: **{diag['total_records']}**")
        
            # ── Per bulan ──
            st.markdown("#### 📅 WR per Bulan")
            bulan_rows = []
            for b, d in diag['per_bulan'].items():
                total_eval = d['win'] + d['loss']
                total_all = total_eval + d['nt']
                if total_all < 3:
                    continue
                wr = (d['win'] / total_eval * 100) if total_eval > 0 else 0
                wr_honest = (d['win'] / total_all * 100) if total_all > 0 else 0
                nt_rate = (d['nt'] / total_all * 100) if total_all > 0 else 0
                bulan_rows.append({
                    'Bulan': b,
                    'Win': d['win'],
                    'Loss': d['loss'],
                    'NT': d['nt'],
                    'WR%': f"{wr:.1f}%",
                    'WR_Honest%': f"{wr_honest:.1f}%",
                    'NT%': f"{nt_rate:.1f}%",
                })
            if bulan_rows:
                st.dataframe(pd.DataFrame(bulan_rows), use_container_width=True, hide_index=True)
            
                # Chart trend
                chart_data = {r['Bulan']: float(r['WR_Honest%'].replace('%','')) 
                            for r in bulan_rows}
                st.line_chart(pd.Series(chart_data), height=200)
                st.caption("📈 **WR_Honest** = Win / (Win+Loss+NT). Ini yang jujur.")
            else:
                st.info("Belum cukup data per bulan.")
        
            # ── Per regime ──
            st.markdown("#### 🎯 WR per Regime")
            regime_rows = []
            for reg, d in diag['per_regime'].items():
                total_eval = d['win'] + d['loss']
                if total_eval < 3:
                    continue
                wr = d['win'] / total_eval * 100
                icon = "🟢" if wr >= 55 else ("🟡" if wr >= 45 else "🔴")
                regime_rows.append({
                    'Regime': f"{icon} {reg}",
                    'Win': d['win'],
                    'Loss': d['loss'],
                    'WR%': f"{wr:.1f}%",
                })
            if regime_rows:
                st.dataframe(pd.DataFrame(regime_rows), use_container_width=True, hide_index=True)
        
            # ── Per gaya ──
            st.markdown("#### 📊 WR per Mode")
            for gaya, d in diag['per_gaya'].items():
                total_eval = d['win'] + d['loss']
                if total_eval < 3:
                    continue
                wr = d['win'] / total_eval * 100
                icon = "🟢" if wr >= 55 else ("🟡" if wr >= 45 else "🔴")
                st.caption(f"{icon} **{gaya}**: {wr:.1f}% ({d['win']}W / {d['loss']}L / {d['nt']}NT)")
        st.markdown("""
            <div class="sb-section">
                <span class="sb-section-icon">📜</span>
                <span class="sb-section-title">Riwayat Analisis</span>
            </div>
        """, unsafe_allow_html=True)

        if "riwayat_page" not in st.session_state:
            st.session_state.riwayat_page = 0
        if "prev_search" not in st.session_state:
            st.session_state.prev_search = ""

        render_notifikasi_evaluasi_riwayat()

        search_query = st.text_input(
            "🔎 Cari Saham",
            key="search_riwayat",
            placeholder="Ketik kode saham..."
        )

        if search_query != st.session_state.prev_search:
            st.session_state.riwayat_page = 0
            st.session_state.prev_search = search_query

        riwayat_data = st.session_state.riwayat if st.session_state.riwayat else []
        if search_query:
            riwayat_data = [r for r in riwayat_data if search_query.lower() in r.get('Saham', '').lower()]

        group_by_day = st.checkbox("📅 Kelompokkan per Hari", value=True)

        if group_by_day:
            from collections import defaultdict
            grouped = defaultdict(list)
            for r in riwayat_data:
                tgl = r.get('Waktu', '')[:10]
                if tgl:
                    grouped[tgl].append(r)
            sorted_days = sorted(grouped.keys(), reverse=True)
            items_per_page = 5
            total_items = len(sorted_days)
            total_pages = max(1, (total_items + items_per_page - 1) // items_per_page)

            if total_pages > 1:
                col1, col2, col3 = st.columns([1, 2, 1])
                with col1:
                    if st.button("◀", disabled=(st.session_state.riwayat_page == 0), key="prev_day"):
                        st.session_state.riwayat_page = max(0, st.session_state.riwayat_page - 1)
                with col2:
                    st.markdown(
                        f"<div style='text-align:center; color:#8892b0; font-size:12px;'>"
                        f"Hal. {st.session_state.riwayat_page+1} / {total_pages}</div>",
                        unsafe_allow_html=True
                    )
                with col3:
                    if st.button("▶", disabled=(st.session_state.riwayat_page >= total_pages - 1), key="next_day"):
                        st.session_state.riwayat_page = min(total_pages - 1, st.session_state.riwayat_page + 1)

            start_idx = st.session_state.riwayat_page * items_per_page
            end_idx = start_idx + items_per_page
            display_days = sorted_days[start_idx:end_idx]

            if display_days:
                for day in display_days:
                    entries = grouped[day]
                    session_map = defaultdict(dict)
                    for r in entries:
                        s_key = (r.get('Waktu', ''), r.get('Saham', ''))
                        gaya = r.get('Gaya', 'SW')
                        session_map[s_key][gaya] = r

                    try:
                        dt_obj = datetime.strptime(day, "%Y-%m-%d")
                        day_map = {
                            "Monday": "Senin", "Tuesday": "Selasa", "Wednesday": "Rabu",
                            "Thursday": "Kamis", "Friday": "Jumat",
                            "Saturday": "Sabtu", "Sunday": "Minggu"
                        }
                        day_label = f"{day_map.get(dt_obj.strftime('%A'), dt_obj.strftime('%A'))}, {dt_obj.strftime('%d %b %Y')}"
                    except Exception:
                        day_label = day

                    n_sesi = len(session_map)
                    with st.expander(f"📅 {day_label}  ·  {n_sesi} sesi", expanded=False):
                        for s_idx, ((waktu, saham), modes) in enumerate(session_map.items()):
                            r_sw = modes.get('SW')
                            r_dt = modes.get('DT')
                            harga_val = r_sw.get('Harga') if r_sw else (r_dt.get('Harga') if r_dt else '?')

                            _sig = (r_sw or r_dt or {}).get('Sinyal', '')
                            if "STRONG BUY" in _sig:
                                _border = "#10b981"
                            elif "BUY" in _sig:
                                _border = "#84cc16"
                            elif "HOLD" in _sig:
                                _border = "#3b82f6"
                            else:
                                _border = "#ef4444"

                            waktu_short = waktu.split()[1] if len(waktu.split()) > 1 else waktu

                            st.markdown(f"""
                            <div style="background:#1a1d24; border-radius:8px;
                                padding:10px 14px; margin-bottom:10px;
                                border-left:4px solid {_border};">
                                <div style="display:flex; justify-content:space-between;
                                    align-items:center; flex-wrap:wrap; gap:8px;">
                                    <div>
                                        <span style="color:#f3f4f6; font-size:15px;
                                            font-weight:700;">{saham}</span>
                                        <span style="color:#94a3b8; font-size:11px;
                                            margin-left:8px;">@ Rp {harga_val}</span>
                                    </div>
                                    <div style="color:#64748b; font-size:10px;">
                                        🕒 {waktu_short}
                                    </div>
                                </div>
                            </div>
                            """, unsafe_allow_html=True)

                            _riwayat_date = waktu[:10] if waktu else ""
                            _bs = _get_broksum_for_date(saham, _riwayat_date) if _riwayat_date else None
                            _render_broksum_net_insight(_bs)
                            col_sw, col_dt = st.columns(2)
                            render_mode_card(r_sw, "Swing", "📆", col_sw, f"g_{day}_{s_idx}")
                            render_mode_card(r_dt, "Daytrade", "⏱️", col_dt, f"g_{day}_{s_idx}")
                            st.markdown("<div style='height:4px;'></div>", unsafe_allow_html=True)

                st.caption(
                    f"📋 {start_idx+1}-{min(end_idx, total_items)} / {total_items} hari"
                    + (f" (cari '{search_query}')" if search_query else "")
                )
            else:
                if search_query:
                    st.caption(f"❌ Tidak ada hasil untuk '{search_query}'.")
                else:
                    st.caption("Belum ada riwayat.")
        else:
            items_per_page = 10
            total_items = len(riwayat_data)
            total_pages = max(1, (total_items + items_per_page - 1) // items_per_page)

            if total_pages > 1:
                col1, col2, col3 = st.columns([1, 2, 1])
                with col1:
                    if st.button("◀", disabled=(st.session_state.riwayat_page == 0), key="prev_flat"):
                        st.session_state.riwayat_page = max(0, st.session_state.riwayat_page - 1)
                with col2:
                    st.markdown(
                        f"<div style='text-align:center; color:#8892b0; font-size:12px;'>"
                        f"Hal. {st.session_state.riwayat_page+1} / {total_pages}</div>",
                        unsafe_allow_html=True
                    )
                with col3:
                    if st.button("▶", disabled=(st.session_state.riwayat_page >= total_pages - 1), key="next_flat"):
                        st.session_state.riwayat_page = min(total_pages - 1, st.session_state.riwayat_page + 1)

            start_idx = st.session_state.riwayat_page * items_per_page
            end_idx = start_idx + items_per_page
            display_riwayat = riwayat_data[start_idx:end_idx]

            if display_riwayat:
                for idx, r in enumerate(display_riwayat):
                    sinyal = r.get('Sinyal', '?')
                    if "STRONG BUY" in sinyal:
                        sig_color, sig_icon, sig_label = "#10b981", "🔥", "STRONG BUY"
                    elif "BUY" in sinyal:
                        sig_color, sig_icon, sig_label = "#84cc16", "⚡", "BUY"
                    elif "HOLD" in sinyal:
                        sig_color, sig_icon, sig_label = "#3b82f6", "⏸️", "HOLD"
                    else:
                        sig_color, sig_icon, sig_label = "#ef4444", "🚨", "AVOID"

                    gaya = r.get('Gaya', '?')
                    gaya_label = "DT" if gaya == "DT" else ("SW" if gaya == "SW" else "?")
                    gaya_icon = "⏱️" if gaya == "DT" else "📆"

                    saham_key = r.get('Saham', '?')
                    harga = r.get('Harga', '?')
                    waktu = r.get('Waktu', '?')
                    score_val = r.get('Score', '?')
                    gaya_color = "#06b6d4" if gaya == "DT" else "#a855f7"

                    expander_title = (
                        f"{sig_icon} {saham_key} @ Rp {harga}  ·  "
                        f"{sig_label} ({gaya_icon}{gaya_label})  ·  Score: {score_val}"
                    )

                    with st.expander(expander_title, expanded=False):
                        st.markdown(f"""
                        <div style="background:linear-gradient(135deg,#1a1d24 0%,#0f1116 100%);
                            border-radius:12px; padding:14px 18px; margin-bottom:10px;
                            border-left:5px solid {sig_color};
                            border-top:1px solid #262626; border-right:1px solid #262626;
                            border-bottom:1px solid #262626;">
                            <div style="display:flex; justify-content:space-between;
                                align-items:flex-start; flex-wrap:wrap; gap:10px;">
                                <div>
                                    <div style="display:flex; align-items:center; gap:8px; margin-bottom:4px;">
                                        <span style="color:{gaya_color}; font-size:10px; font-weight:700;
                                            letter-spacing:1.2px; text-transform:uppercase;">
                                            {gaya_icon} {gaya_label}
                                        </span>
                                    </div>
                                    <div style="display:flex; align-items:center; gap:10px; flex-wrap:wrap;">
                                        <span style="color:#f3f4f6; font-size:22px;
                                            font-weight:700; letter-spacing:0.5px;">{saham_key}</span>
                                        <span style="color:#94a3b8; font-size:13px;">@ Rp {harga}</span>
                                    </div>
                                </div>
                                <div style="text-align:right;">
                                    <div style="color:{sig_color}; font-size:15px; font-weight:700;">
                                        {sig_icon} {sig_label}
                                    </div>
                                    <div style="color:#64748b; font-size:10px; margin-top:2px;">
                                        🕒 {waktu}
                                    </div>
                                </div>
                            </div>
                        </div>
                        """, unsafe_allow_html=True)

                        st.markdown(f"""
                        <div style="background:#1e293b; border-radius:8px; padding:10px 14px;
                            margin-bottom:10px;">
                            <div style="display:grid; grid-template-columns:1fr 1fr 1fr; gap:8px;">
                                <div style="text-align:center;">
                                    <div style="color:#94a3b8; font-size:9px; text-transform:uppercase;
                                        letter-spacing:0.5px;">Score</div>
                                    <div style="color:#00ffcc; font-size:14px; font-weight:700;
                                        margin-top:2px;">{r.get('Score','?')}</div>
                                </div>
                                <div style="text-align:center; border-left:1px solid #334155;
                                    border-right:1px solid #334155;">
                                    <div style="color:#94a3b8; font-size:9px; text-transform:uppercase;
                                        letter-spacing:0.5px;">RRR</div>
                                    <div style="color:#e2e8f0; font-size:14px; font-weight:700;
                                        margin-top:2px;">{r.get('RRR','?')}</div>
                                </div>
                                <div style="text-align:center;">
                                    <div style="color:#94a3b8; font-size:9px; text-transform:uppercase;
                                        letter-spacing:0.5px;">Confidence</div>
                                    <div style="color:#e2e8f0; font-size:14px; font-weight:700;
                                        margin-top:2px;">{r.get('Confidence','?')}</div>
                                </div>
                            </div>
                        </div>
                        """, unsafe_allow_html=True)

                        riwayat_date = waktu[:10] if waktu else ""
                        _bs = _get_broksum_for_date(saham_key, riwayat_date) if riwayat_date else None
                        _render_broksum_net_insight(_bs)

                        coppock = r.get('Coppock', '?')
                        if "Turning Up" in coppock:
                            cop_icon, cop_color = "🔼", "#10b981"
                        elif "Rising" in coppock:
                            cop_icon, cop_color = "📈", "#84cc16"
                        else:
                            cop_icon, cop_color = "📉", "#ef4444"

                        regime = r.get('Rezim', '?')
                        st.markdown(f"""
                        <div style="display:grid; grid-template-columns:1fr 1fr; gap:6px;
                            margin-bottom:10px;">
                            <div style="background:#1e293b; border-radius:6px; padding:8px 12px;
                                border-left:2px solid {cop_color};">
                                <div style="color:#94a3b8; font-size:9px; text-transform:uppercase;
                                    letter-spacing:0.5px;">Coppock</div>
                                <div style="color:{cop_color}; font-size:12px; font-weight:600;
                                    margin-top:2px;">{cop_icon} {coppock}</div>
                            </div>
                            <div style="background:#1e293b; border-radius:6px; padding:8px 12px;
                                border-left:2px solid #a855f7;">
                                <div style="color:#94a3b8; font-size:9px; text-transform:uppercase;
                                    letter-spacing:0.5px;">Regime</div>
                                <div style="color:#e2e8f0; font-size:11px; font-weight:600;
                                    margin-top:2px;">{regime}</div>
                            </div>
                        </div>
                        """, unsafe_allow_html=True)

                        est_netral = r.get('Estimasi_Netral', '?')
                        est_sinyal = r.get('Estimasi_Sinyal', '?')
                        ret_netral = r.get('Est_Return', '?')
                        ret_sinyal = r.get('Est_Return_Sinyal', '?')
                        st.markdown(f"""
                        <div style="background:#1e293b; border-radius:8px; padding:10px 14px;
                            margin-bottom:10px;">
                            <div style="color:#94a3b8; font-size:9px; text-transform:uppercase;
                                letter-spacing:0.5px; margin-bottom:8px;">📊 Estimasi Harga</div>
                            <div style="display:grid; grid-template-columns:1fr 1fr; gap:8px;">
                                <div style="text-align:center;">
                                    <div style="color:#64748b; font-size:9px; margin-bottom:3px;">Netral</div>
                                    <div style="color:#e2e8f0; font-size:13px; font-weight:600;">{est_netral}</div>
                                    <div style="color:#94a3b8; font-size:10px; margin-top:2px;">{ret_netral}</div>
                                </div>
                                <div style="text-align:center; border-left:1px solid #334155;">
                                    <div style="color:#64748b; font-size:9px; margin-bottom:3px;">🎯 Sinyal</div>
                                    <div style="color:#00ffcc; font-size:13px; font-weight:600;">{est_sinyal}</div>
                                    <div style="color:#10b981; font-size:10px; margin-top:2px;">{ret_sinyal}</div>
                                </div>
                            </div>
                        </div>
                        """, unsafe_allow_html=True)

                        tp_val = r.get('TP_Harga') or r.get('TP_Range', '?')
                        sl_val = r.get('SL_Harga', '?')
                        tp_label = "TP Sesi Berikutnya" if gaya == "DT" else "TP Besok"
                        sl_label = "SL Sesi Berikutnya" if gaya == "DT" else "SL Besok"
                        st.markdown(f"""
                        <div style="display:grid; grid-template-columns:1fr 1fr; gap:8px;
                            margin-bottom:10px;">
                            <div style="background:#1e293b; border-radius:8px; padding:10px 12px;
                                border-left:3px solid #10b981;">
                                <div style="color:#94a3b8; font-size:9px; text-transform:uppercase;
                                    letter-spacing:0.5px;">📈 {tp_label}</div>
                                <div style="color:#10b981; font-size:14px; font-weight:700;
                                    margin-top:4px;">{tp_val}</div>
                            </div>
                            <div style="background:#1e293b; border-radius:8px; padding:10px 12px;
                                border-left:3px solid #ef4444;">
                                <div style="color:#94a3b8; font-size:9px; text-transform:uppercase;
                                    letter-spacing:0.5px;">🛑 {sl_label}</div>
                                <div style="color:#ef4444; font-size:14px; font-weight:700;
                                    margin-top:4px;">Rp {sl_val}</div>
                            </div>
                        </div>
                        """, unsafe_allow_html=True)

                        entry_zone_val = r.get('Entry_Zone', '?')
                        dip_entry_val = get_dip_entry(r)
                        if (entry_zone_val and entry_zone_val != '?') or dip_entry_val:
                            st.markdown(f"""
                            <div style="display:grid; grid-template-columns:1fr 1fr; gap:8px;
                                margin-bottom:10px;">
                                <div style="background:#1e293b; border-radius:8px; padding:10px 12px;
                                    border-left:3px solid #00ffcc;">
                                    <div style="color:#94a3b8; font-size:9px; text-transform:uppercase;
                                        letter-spacing:0.5px;">🎯 Entry Zone</div>
                                    <div style="color:#00ffcc; font-size:12px; font-weight:600;
                                        margin-top:4px;">{entry_zone_val if entry_zone_val else '-'}</div>
                                </div>
                                <div style="background:#1e293b; border-radius:8px; padding:10px 12px;
                                    border-left:3px solid #facc15;">
                                    <div style="color:#94a3b8; font-size:9px; text-transform:uppercase;
                                        letter-spacing:0.5px;">💡 Dip Entry</div>
                                    <div style="color:#facc15; font-size:12px; font-weight:600;
                                        margin-top:4px;">{dip_entry_val if dip_entry_val else '-'}</div>
                                </div>
                            </div>
                            """, unsafe_allow_html=True)

                        rsi = r.get('RSI', '?')
                        rsi_status = r.get('RSI_Status', '')
                        vol_surge = r.get('Vol_Surge', '?')
                        vs_status = r.get('VS_Status', '')
                        zscore = r.get('ZScore', '?')
                        zs_status = r.get('ZS_Status', '')
                        trend = r.get('Trend_Consistency', '?')

                        def _ind_color(status):
                            s = str(status).lower()
                            if "overbought" in s or "high" in s or "tinggi" in s:
                                return "#ef4444"
                            if "oversold" in s or "low" in s or "rendah" in s:
                                return "#10b981"
                            return "#94a3b8"

                        st.markdown(f"""
                        <div style="background:#1e293b; border-radius:8px; padding:10px 14px;
                            margin-bottom:10px;">
                            <div style="color:#94a3b8; font-size:9px; text-transform:uppercase;
                                letter-spacing:0.5px; margin-bottom:8px;">📊 Indikator Teknikal</div>
                            <div style="display:grid; grid-template-columns:1fr 1fr 1fr 1fr; gap:6px;">
                                <div style="text-align:center;">
                                    <div style="color:#64748b; font-size:8px;">RSI-14</div>
                                    <div style="color:#e2e8f0; font-size:12px; font-weight:700;
                                        margin-top:2px;">{rsi}</div>
                                    <div style="color:{_ind_color(rsi_status)}; font-size:8px;
                                        margin-top:1px;">{rsi_status}</div>
                                </div>
                                <div style="text-align:center; border-left:1px solid #334155;
                                    border-right:1px solid #334155;">
                                    <div style="color:#64748b; font-size:8px;">Vol Surge</div>
                                    <div style="color:#e2e8f0; font-size:12px; font-weight:700;
                                        margin-top:2px;">{vol_surge}</div>
                                    <div style="color:{_ind_color(vs_status)}; font-size:8px;
                                        margin-top:1px;">{vs_status}</div>
                                </div>
                                <div style="text-align:center;">
                                    <div style="color:#64748b; font-size:8px;">Z-Score</div>
                                    <div style="color:#e2e8f0; font-size:12px; font-weight:700;
                                        margin-top:2px;">{zscore}</div>
                                    <div style="color:{_ind_color(zs_status)}; font-size:8px;
                                        margin-top:1px;">{zs_status}</div>
                                </div>
                                <div style="text-align:center; border-left:1px solid #334155;">
                                    <div style="color:#64748b; font-size:8px;">Trend</div>
                                    <div style="color:#e2e8f0; font-size:12px; font-weight:700;
                                        margin-top:2px;">{trend}</div>
                                    <div style="color:#94a3b8; font-size:8px; margin-top:1px;">Cons.</div>
                                </div>
                            </div>
                        </div>
                        """, unsafe_allow_html=True)

                        beta = r.get('Beta', '?')
                        momentum = r.get('Momentum', '?')
                        likuiditas = r.get('Likuiditas', '?')
                        st.markdown(f"""
                        <div style="display:grid; grid-template-columns:1fr 1fr 1fr; gap:6px;
                            margin-bottom:10px;">
                            <div style="background:#1e293b; border-radius:6px; padding:8px 10px;">
                                <div style="color:#94a3b8; font-size:8px; text-transform:uppercase;
                                    letter-spacing:0.5px;">Beta</div>
                                <div style="color:#e2e8f0; font-size:11px; font-weight:600;
                                    margin-top:2px;">{beta}</div>
                            </div>
                            <div style="background:#1e293b; border-radius:6px; padding:8px 10px;">
                                <div style="color:#94a3b8; font-size:8px; text-transform:uppercase;
                                    letter-spacing:0.5px;">Momentum 5D</div>
                                <div style="color:#e2e8f0; font-size:11px; font-weight:600;
                                    margin-top:2px;">{momentum}</div>
                            </div>
                            <div style="background:#1e293b; border-radius:6px; padding:8px 10px;">
                                <div style="color:#94a3b8; font-size:8px; text-transform:uppercase;
                                    letter-spacing:0.5px;">Likuiditas</div>
                                <div style="color:#e2e8f0; font-size:11px; font-weight:600;
                                    margin-top:2px;">{likuiditas}</div>
                            </div>
                        </div>
                        """, unsafe_allow_html=True)

                        if r.get('Status_Posisi', '') == 'Sudah Beli':
                            harga_beli_r = r.get('Harga_Beli', '')
                            floating_pl = r.get('Floating_PL', '')
                            try:
                                pl_val = float(str(floating_pl).replace('%', '').replace('+', ''))
                            except Exception:
                                pl_val = 0
                            pl_color = "#10b981" if pl_val > 0 else ("#ef4444" if pl_val < 0 else "#94a3b8")
                            st.markdown(f"""
                            <div style="background:#1e293b; border-radius:8px; padding:10px 14px;
                                margin-bottom:10px; border-left:3px solid {pl_color};">
                                <div style="display:flex; justify-content:space-between;
                                    align-items:center; flex-wrap:wrap; gap:8px;">
                                    <div>
                                        <div style="color:#94a3b8; font-size:9px; text-transform:uppercase;">
                                            💰 Harga Beli</div>
                                        <div style="color:#e2e8f0; font-size:13px; font-weight:600;
                                            margin-top:2px;">Rp {harga_beli_r}</div>
                                    </div>
                                    <div style="text-align:right;">
                                        <div style="color:#94a3b8; font-size:9px; text-transform:uppercase;">
                                            Floating P/L</div>
                                        <div style="color:{pl_color}; font-size:15px; font-weight:700;
                                            margin-top:2px;">{floating_pl}</div>
                                    </div>
                                </div>
                            </div>
                            """, unsafe_allow_html=True)

                        waktu_key = r.get('Waktu','')
                        gaya_key = r.get('Gaya', 'SW')
                        mode_actual = "swing" if gaya_key == "SW" else "daytrade"
                        actual_data = (
                            st.session_state.riwayat_actual.get((waktu_key, saham_key, gaya_key)) or
                            st.session_state.riwayat_actual.get((waktu_key, saham_key, mode_actual)) or
                            st.session_state.riwayat_actual.get((waktu_key, saham_key))
                        )

                        has_actual = False
                        if actual_data:
                            if (actual_data.get('Actual_High') or actual_data.get('Actual_Low') or
                                actual_data.get('Actual_Close') or actual_data.get('Outcome') or
                                actual_data.get('Entry_Miss') == 'Yes'):
                                has_actual = True

                        if has_actual:
                            outcome = actual_data.get('Outcome', '')
                            entry_miss = actual_data.get('Entry_Miss') == 'Yes'
                            if entry_miss or outcome == 'Not Touched':
                                oi, oc, ol = "⚪", "#94a3b8", "NOT TOUCHED"
                            elif outcome == 'Win':
                                oi, oc, ol = "🏆", "#10b981", "WIN"
                            elif outcome == 'Loss':
                                oi, oc, ol = "💔", "#ef4444", "LOSS"
                            else:
                                oi, oc, ol = "❓", "#64748b", "PENDING"

                            hi = actual_data.get('Actual_High', '-') or '-'
                            lo = actual_data.get('Actual_Low', '-') or '-'
                            cl = actual_data.get('Actual_Close', '-') or '-'

                            st.markdown(f"""
                            <div style="background:{oc}10; border:1px solid {oc}40;
                                border-radius:8px; padding:10px 14px; margin-bottom:6px;">
                                <div style="display:flex; align-items:center; gap:8px;
                                    margin-bottom:8px;">
                                    <span style="font-size:16px;">{oi}</span>
                                    <span style="color:{oc}; font-size:11px; font-weight:700;
                                        letter-spacing:1px;">{ol}</span>
                                </div>
                                <div style="display:grid; grid-template-columns:1fr 1fr 1fr; gap:6px;">
                                    <div style="text-align:center;">
                                        <div style="color:#94a3b8; font-size:9px;">High</div>
                                        <div style="color:#e2e8f0; font-size:11px; font-weight:600;
                                            margin-top:2px;">{hi}</div>
                                    </div>
                                    <div style="text-align:center; border-left:1px solid {oc}30;
                                        border-right:1px solid {oc}30;">
                                        <div style="color:#94a3b8; font-size:9px;">Low</div>
                                        <div style="color:#e2e8f0; font-size:11px; font-weight:600;
                                            margin-top:2px;">{lo}</div>
                                    </div>
                                    <div style="text-align:center;">
                                        <div style="color:#94a3b8; font-size:9px;">Close</div>
                                        <div style="color:#e2e8f0; font-size:11px; font-weight:600;
                                            margin-top:2px;">{cl}</div>
                                    </div>
                                </div>
                            </div>
                            """, unsafe_allow_html=True)
                        else:
                            _is_avoid_r = 'AVOID' in str(r.get('Sinyal', '')).upper()
                            if _is_avoid_r:
                                st.markdown("""
                                <div style="background:#ef444418; border:1px dashed #ef444460;
                                border-radius:6px; padding:8px 12px;
                                font-size:10px; color:#f87171; text-align:center;
                                margin-bottom:6px; font-weight:600;">
                                🚨 Sinyal AVOID — Sebaiknya dihindari · Engine auto-learn dari harga 5 hari kemudian
                            </div>
                            """, unsafe_allow_html=True)
                            else:
                                st.markdown("""
                                <div style="background:#1e293b; border-radius:6px; padding:8px 12px;
                                font-size:10px; color:#94a3b8; text-align:center;
                                border:1px dashed #334155; margin-bottom:6px;">
                                ⏳ Outcome belum dicatat · <i>Cek Quick Outcome di atas</i>
                            </div>
                            """, unsafe_allow_html=True)
                        ai = r.get("AI_Insight", "").strip()
                        if ai:
                            st.markdown(f"""
                            <div style="background:linear-gradient(135deg,#8b5cf615 0%,#1e293b 100%);
                                border-left:3px solid #8b5cf6; border-radius:6px;
                                padding:8px 12px; margin-bottom:8px; font-size:10px;
                                color:#cbd5e1; line-height:1.5;">
                                💡 <b>AI Insight:</b> {ai[:200]}{'...' if len(ai) > 200 else ''}
                            </div>
                            """, unsafe_allow_html=True)

                        hapus_key = f"hapus_{idx}_{waktu_key}_{saham_key}_{gaya_key}"
                        if st.button("🗑️ Hapus dari Riwayat", key=hapus_key,
                                     use_container_width=True):
                            hapus_riwayat_item(waktu_key, saham_key, gaya=gaya_key)
                            st.rerun()

                st.caption(
                    f"📋 {start_idx+1}-{min(end_idx, total_items)} / {total_items} riwayat"
                    + (f" (cari '{search_query}')" if search_query else "")
                )
            else:
                if search_query:
                    st.caption(f"❌ Tidak ada hasil untuk '{search_query}'.")
                else:
                    st.caption("Belum ada riwayat.")
        # SECTION 8: AI GEMINI
        st.markdown("""
            <div class="sb-section">
                <span class="sb-section-icon">🧠</span>
                <span class="sb-section-title">AI Gemini</span>
            </div>
        """, unsafe_allow_html=True)

        def get_api_key():
            keys = _load_gemini_keys()
            return keys[0] if keys else ""

        api_key_loaded = get_api_key()
        st.session_state.gemini_api_key = api_key_loaded

        # ── Status display dengan info jumlah key + cooldown ──
        keys = _load_gemini_keys()
        n_keys = len(keys)

        if n_keys > 0:
            state = _get_key_rotator_state()
            now = time.time()
            active_count = sum(
                1 for i in range(n_keys)
                if now >= state["cooldown_until"].get(i, 0)
            )
            if active_count == n_keys:
                st.markdown(
                    f'<div class="sb-api-ok">🟢 Gemini Aktif · {n_keys} key siap</div>',
                    unsafe_allow_html=True
                )
            elif active_count > 0:
                st.markdown(
                    f'<div class="sb-api-ok">🟡 Gemini Aktif · {active_count}/{n_keys} key ready</div>',
                    unsafe_allow_html=True
                )
            else:
                st.markdown(
                    f'<div class="sb-api-off">🔴 Semua {n_keys} key cooldown · tunggu ~1 menit</div>',
                    unsafe_allow_html=True
                )
        else:
            st.markdown(
                '<div class="sb-api-off">⚠️ Gemini API Key belum ada</div>',
                unsafe_allow_html=True
            )

        st.markdown("<div style='height:8px;'></div>", unsafe_allow_html=True)
        if st.button("📊 Analisis Riwayat dgn AI", use_container_width=True, key="btn_ai_riwayat"):
            st.session_state['_sb_ai_riwayat_btn'] = True
            st.rerun()
        if st.button("🗑️ Hapus Semua Riwayat", use_container_width=True, key="btn_hapus_all_riwayat"):
            try:
                sheet = get_gsheet().worksheet("riwayat")
                sheet.clear()
                st.session_state.riwayat = []
                st.success("Riwayat dihapus!")
            except Exception as e:
                st.error(f"Gagal menghapus riwayat: {e}")
        # SECTION 9: KALENDER BURSA
        st.markdown("""
            <div class="sb-section">
                <span class="sb-section-icon">📅</span>
                <span class="sb-section-title">Kalender Bursa</span>
            </div>
        """, unsafe_allow_html=True)

        # SESUDAH (main.py):
        now_jkt = datetime.now(pytz.timezone("Asia/Jakarta"))

        _level, _msg = status_bursa(now_jkt)
        {"open": st.success, "closed": st.info,
         "weekend": st.warning, "holiday": st.warning}[_level](_msg)

        st.caption("Libur 2 minggu ke depan:")
        _future = libur_dalam_n_hari(now_jkt, days=14)
        if _future:
            for dt, desc in _future:
                st.caption(f"• {dt.strftime('%d %b')}: {desc}")
        else:
            st.caption("Tidak ada libur dalam 2 minggu.")

        # FOOTER
        st.markdown("---")
        st.caption("📡 Data dari Yahoo Finance · Bukan rekomendasi investasi")

