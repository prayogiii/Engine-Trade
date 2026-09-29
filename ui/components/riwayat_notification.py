"""Notifikasi form evaluasi outcome untuk signal yang jatuh tempo."""
from __future__ import annotations

import streamlit as st

from core.riwayat import (
    dapatkan_sinyal_perlu_dicatat, get_dip_entry,
)
from services.yfinance_client import fetch_actual_data_yfinance
from services.sheets_client import simpan_riwayat_actual, integrate_actual_to_v12
def render_notifikasi_evaluasi_riwayat():
    riwayat_data = st.session_state.get('riwayat', [])
    riwayat_actual = st.session_state.get('riwayat_actual', {})

    if not riwayat_data:
        return

    urgent_items, active_swing_items = dapatkan_sinyal_perlu_dicatat(riwayat_data, riwayat_actual)

    if not urgent_items and not active_swing_items:
        return

    n_urgent = len(urgent_items)
    n_active = len(active_swing_items)

    st.markdown("""
        <style>
        .notif-box {
            background: linear-gradient(135deg, #1e1b4b 0%, #311042 100%);
            border-left: 5px solid #a855f7;
            border-radius: 12px;
            padding: 14px 18px;
            margin-bottom: 18px;
        }
        </style>
    """, unsafe_allow_html=True)

    title_text = "🔔 <b>Pengingat Evaluasi Outcome Trading</b>"
    details = []
    if n_urgent > 0:
        details.append(f"⚠️ <b>{n_urgent} sinyal perlu dicatat</b> (Daytrade atau Swing ≥7 hari bursa)")
    if n_active > 0:
        details.append(f"⏳ <b>{n_active} Swing aktif</b> (1-6 hari bursa)")

    st.markdown(f"""
    <div class="notif-box">
        <div style="font-size:15px; font-weight:bold; color:#f472b6;">
            {title_text}
        </div>
        <div style="font-size:13px; color:#e2e8f0; margin-top:4px;">
            {' | '.join(details)}
        </div>
    </div>
    """, unsafe_allow_html=True)

    with st.expander("📝 Form Evaluasi Sinyal (Quick Outcome Journal)", expanded=(n_urgent > 0)):
        tab_urgent, tab_active = st.tabs([
            f"🚨 Perlu Catat Immediate ({n_urgent})",
            f"⏳ Swing Aktif ({n_active})"
        ])

        with tab_urgent:
            if not urgent_items:
                st.success("🎉 Semua sinyal jatuh tempo sudah dicatat!")
            else:
                for idx, item in enumerate(urgent_items):
                    r = item['record']
                    waktu_key = item['waktu']
                    saham_key = item['saham']
                    gaya_key = item['gaya']
                    mode_actual = item['mode_actual']
                    alasan = item['alasan']
                    dip_entry = get_dip_entry(r)
                    dip_str = f" | 💡 Dip Entry: {dip_entry}" if dip_entry else ""

                    st.markdown(f"**📌 {saham_key} ({gaya_key}) - {waktu_key}** | `{alasan}`")
                    st.caption(f"Sinyal: {r.get('Sinyal','?')} | 🎯 Entry: {r.get('Entry_Zone','?')}{dip_str} | TP: {r.get('TP_Range','?')} | SL: Rp {r.get('SL_Harga','?')}")

                    fetch_key = f"fetch_urg_{idx}_{waktu_key}_{saham_key}_{gaya_key}"
                    form_key = f"form_urg_{idx}_{waktu_key}_{saham_key}_{gaya_key}"

                    col_auto, _ = st.columns([2, 1])
                    with col_auto:
                        if st.button(f"⚡ Fetch Otomatis Data Harga ({saham_key})", key=fetch_key):
                            fetched = fetch_actual_data_yfinance(saham_key, waktu_key)
                            if fetched:
                                st.session_state[f"hi_{fetch_key}"] = fetched['Actual_High']
                                st.session_state[f"lo_{fetch_key}"] = fetched['Actual_Low']
                                st.session_state[f"cl_{fetch_key}"] = fetched['Actual_Close']
                                msg = f"Data harga {saham_key} berhasil ditarik!"
                                if dip_entry:
                                    msg += f" (Dip Entry Target: {dip_entry})"
                                st.success(msg)
                            else:
                                st.error(f"Gagal mengambil data {saham_key} dari yfinance")

                    with st.form(key=form_key):
                        if dip_entry:
                            st.caption(f"💡 Target Dip Entry: **{dip_entry}** | 🎯 Entry Zone: **{r.get('Entry_Zone', '-')}**")
                        def_hi = st.session_state.get(f"hi_{fetch_key}", "")
                        def_lo = st.session_state.get(f"lo_{fetch_key}", "")
                        def_cl = st.session_state.get(f"cl_{fetch_key}", "")

                        c1, c2, c3 = st.columns(3)
                        actual_high = c1.text_input("Actual High", value=def_hi, placeholder="contoh: 5350")
                        actual_low = c2.text_input("Actual Low", value=def_lo, placeholder="contoh: 5050")
                        actual_close = c3.text_input("Actual Close", value=def_cl, placeholder="contoh: 5200")

                        c4, c5 = st.columns(2)
                        entry_miss = c4.checkbox("🚫 Entry Tidak Tersentuh", value=False)
                        if entry_miss:
                            outcome = "Not Touched"
                        else:
                            outcome = c5.selectbox("Outcome", ["", "Win", "Loss", "Not Touched"], format_func=lambda x: "Pilih Outcome" if x=="" else x)

                        submitted = st.form_submit_button("💾 Simpan Outcome")
                        if submitted:
                            if not entry_miss and outcome == "":
                                st.error("Pilih Outcome terlebih dahulu.")
                            else:
                                data = {
                                    'Actual_High': actual_high.strip(),
                                    'Actual_Low': actual_low.strip(),
                                    'Actual_Close': actual_close.strip(),
                                    'Outcome': outcome,
                                    'Entry_Miss': 'Yes' if entry_miss else 'No',
                                    'Mode': mode_actual
                                }
                                simpan_riwayat_actual(
                                    waktu_key, saham_key, data, mode=mode_actual,
                                    on_update_callback=integrate_actual_to_v12,
                                )
                                st.success(f"✅ Outcome {saham_key} berhasil disimpan!")
                                st.rerun()
                    st.divider()

        with tab_active:
            if not active_swing_items:
                st.info("Tidak ada posisi Swing aktif (1-6 hari bursa) yang sedang berjalan.")
            else:
                for idx, item in enumerate(active_swing_items):
                    r = item['record']
                    waktu_key = item['waktu']
                    saham_key = item['saham']
                    gaya_key = item['gaya']
                    mode_actual = item['mode_actual']
                    alasan = item['alasan']
                    dip_entry = get_dip_entry(r)
                    dip_str = f" | 💡 Dip Entry: {dip_entry}" if dip_entry else ""

                    st.markdown(f"**⏳ {saham_key} ({gaya_key}) - {waktu_key}** | `{alasan}`")
                    st.caption(f"Sinyal: {r.get('Sinyal','?')} | 🎯 Entry: {r.get('Entry_Zone','?')}{dip_str} | TP: {r.get('TP_Range','?')} | SL: Rp {r.get('SL_Harga','?')}")

                    fetch_key = f"fetch_act_{idx}_{waktu_key}_{saham_key}_{gaya_key}"
                    form_key = f"form_act_{idx}_{waktu_key}_{saham_key}_{gaya_key}"

                    col_auto, _ = st.columns([2, 1])
                    with col_auto:
                        if st.button(f"⚡ Fetch Otomatis Data Harga ({saham_key})", key=fetch_key):
                            fetched = fetch_actual_data_yfinance(saham_key, waktu_key)
                            if fetched:
                                st.session_state[f"hi_{fetch_key}"] = fetched['Actual_High']
                                st.session_state[f"lo_{fetch_key}"] = fetched['Actual_Low']
                                st.session_state[f"cl_{fetch_key}"] = fetched['Actual_Close']
                                msg = f"Data harga {saham_key} berhasil ditarik!"
                                if dip_entry:
                                    msg += f" (Dip Entry Target: {dip_entry})"
                                st.success(msg)
                            else:
                                st.error(f"Gagal mengambil data {saham_key} dari yfinance")

                    with st.form(key=form_key):
                        if dip_entry:
                            st.caption(f"💡 Target Dip Entry: **{dip_entry}** | 🎯 Entry Zone: **{r.get('Entry_Zone', '-')}**")
                        def_hi = st.session_state.get(f"hi_{fetch_key}", "")
                        def_lo = st.session_state.get(f"lo_{fetch_key}", "")
                        def_cl = st.session_state.get(f"cl_{fetch_key}", "")

                        c1, c2, c3 = st.columns(3)
                        actual_high = c1.text_input("Actual High", value=def_hi, placeholder="contoh: 5350")
                        actual_low = c2.text_input("Actual Low", value=def_lo, placeholder="contoh: 5050")
                        actual_close = c3.text_input("Actual Close", value=def_cl, placeholder="contoh: 5200")

                        c4, c5 = st.columns(2)
                        entry_miss = c4.checkbox("🚫 Entry Tidak Tersentuh", value=False)
                        if entry_miss:
                            outcome = "Not Touched"
                        else:
                            outcome = c5.selectbox("Outcome", ["", "Win", "Loss", "Not Touched"], format_func=lambda x: "Pilih Outcome" if x=="" else x)

                        submitted = st.form_submit_button("💾 Simpan Outcome (Early Exit)")
                        if submitted:
                            if not entry_miss and outcome == "":
                                st.error("Pilih Outcome terlebih dahulu.")
                            else:
                                data = {
                                    'Actual_High': actual_high.strip(),
                                    'Actual_Low': actual_low.strip(),
                                    'Actual_Close': actual_close.strip(),
                                    'Outcome': outcome,
                                    'Entry_Miss': 'Yes' if entry_miss else 'No',
                                    'Mode': mode_actual
                                }
                                simpan_riwayat_actual(
                                    waktu_key, saham_key, data, mode=mode_actual,
                                    on_update_callback=integrate_actual_to_v12,
                                )
                                st.success(f"✅ Outcome {saham_key} berhasil disimpan!")
                                st.rerun()
                    st.divider()