"""UI upload & scan broksum (Gemini AI atau OCR offline)."""
from __future__ import annotations

import streamlit as st
from PIL import Image

from core.bandarmology import klasifikasi_broker, enrich_broker_kategori
from services.gemini_client import analisis_broksum_gemini_vision
from services.ocr_client import analisis_broksum_ocr
from services.sheets_client import (
    save_broksum_data,
    get_broksum_cache,
    save_foreign_flow_snapshot,
)

def render_broksum_scan_ui(api_key="", key_prefix="broksum"):
    st.markdown("### 📸 Scan Broker Summary (Broksum)")
    st.caption("Upload screenshot Broksum (Stockbit, IPOT, HOTS, dll) untuk dianalisis & tersimpan ke database.")

    # ========== INPUT TICKER ==========
    st.markdown("**Ticker Saham** (wajib untuk menyimpan ke database)")
    ticker_input = st.text_input(
        "Masukkan kode saham (contoh: BBCA, GOTO, ASII)",
        key=f"{key_prefix}_ticker_input",
        placeholder="BBCA"
    ).strip().upper()

    uploaded_file = st.file_uploader(
        "Pilih Foto / Screenshot Broksum",
        type=["png", "jpg", "jpeg", "webp"],
        key=f"{key_prefix}_file_uploader"
    )

    if uploaded_file is not None:
        try:
            image = Image.open(uploaded_file)
            st.image(image, caption="Preview Broksum", use_container_width=True)

            result_key  = f"{key_prefix}_result"
            error_key   = f"{key_prefix}_error"
            source_key  = f"{key_prefix}_source"

            col_btn1, col_btn2 = st.columns(2)
            with col_btn1:
                btn_gemini = st.button("🤖 Scan AI Gemini (Akurat)", key=f"{key_prefix}_btn_gemini", use_container_width=True)
            with col_btn2:
                btn_ocr = st.button("⚡ Scan Offline (OCR)", key=f"{key_prefix}_btn_ocr", use_container_width=True)

            if btn_gemini:
                if not api_key:
                    st.error("⚠️ Gemini API Key belum diisi di sidebar.")
                else:
                    with st.spinner("🧠 Gemini Vision sedang membaca tabel Broksum... [Retry enabled]"):
                        res_json, err = analisis_broksum_gemini_vision(image, api_key)
                    if err:
                        st.session_state[error_key] = err
                    else:
                        res_json = enrich_broker_kategori(res_json)
                        st.session_state[result_key] = res_json
                        st.session_state[error_key]  = None
                        st.session_state[source_key] = "gemini"

            elif btn_ocr:
                with st.spinner("🔍 Membaca screenshot Broksum via OCR..."):
                    res_json, err = analisis_broksum_ocr(image)
                if err:
                    st.session_state[error_key] = err
                else:
                    res_json = enrich_broker_kategori(res_json)
                    st.session_state[result_key] = res_json
                    st.session_state[error_key]  = None
                    st.session_state[source_key] = "ocr"

            res_json = st.session_state.get(result_key)
            err      = st.session_state.get(error_key)
            source   = st.session_state.get(source_key, "")

            # ═══ ENRICH: Klasifikasi Bandar vs Retail ═══
            if res_json:
                for side_key in ["top_buyers", "top_sellers"]:
                    for item in res_json.get(side_key, []):
                        kode = item.get("broker", "")
                        vol  = item.get("volume_lot", 0) or 0
                        frq  = item.get("freq")
                        kategori, icon = klasifikasi_broker(kode, vol, frq)
                        item["kategori"] = kategori
                        item["kategori_icon"] = icon

            if res_json:
                st.success(f"✅ **Status:** {res_json.get('bandarmology_status', 'N/A')}")
                if res_json.get("summary_narrative"):
                    st.info(f"📝 {res_json.get('summary_narrative')}")

                # ========== SAVE TO DATABASE ==========
                st.divider()
                col_save_1, col_save_2 = st.columns([2, 1])
                with col_save_1:
                    if not ticker_input:
                        st.warning("⚠️ Masukkan ticker terlebih dahulu untuk menyimpan ke database.")
                    else:
                        st.info(f"💾 Siap simpan ke database untuk **{ticker_input}**")
                with col_save_2:
                    btn_save = st.button("💾 Simpan ", key=f"{key_prefix}_btn_save", use_container_width=True)
                    
                if btn_save:
                    if not ticker_input:
                        st.error("❌ Ticker tidak boleh kosong!")
                    else:
                        with st.spinner(f"💾 Menyimpan data {ticker_input} ke Google Sheets..."):
                            success = save_broksum_data(ticker_input, res_json, source=source)

                        if success:
                            # ═══ AUTO-REFRESH CACHE setelah upload ═══
                            get_broksum_cache(force_refresh=True)

                            with st.spinner(f"📊 Mengambil foreign flow IDX untuk {ticker_input}..."):
                                ff_ok = save_foreign_flow_snapshot(ticker_input)

                            if ff_ok:
                                st.success(f"✅ Broksum + Foreign Flow IDX **{ticker_input}** tersimpan!")
                            else:
                                st.warning(
                                    f"✅ Broksum **{ticker_input}** tersimpan! "
                                    f"⚠️ Foreign flow IDX gagal diambil sekarang (kemungkinan rate limit). "
                                    f"Data akan di-nambal otomatis oleh cron jam 19:30 WIB."
                                )

                            st.session_state[f"{key_prefix}_result"] = None

            elif err:
                st.warning(f"⚠️ {err}")

        except Exception as e_img:
            st.error(f"Gagal memuat gambar: {e_img}")

    with st.expander("📝 Input Manual Broksum", expanded=False):
        st.caption("Isi data Top Buyers & Top Sellers secara manual.")
        n_broker = st.number_input("Jumlah broker per sisi", min_value=1, max_value=10, value=5, key=f"{key_prefix}_n_broker")

        st.markdown("**🟢 Top Buyers**")
        buyers_manual = []
        for idx in range(int(n_broker)):
            ca, cb = st.columns([2, 3])
            brk = ca.text_input("", key=f"{key_prefix}_b_brk_{idx}", placeholder=f"Broker {idx+1}", label_visibility="collapsed")
            vol = cb.number_input("", key=f"{key_prefix}_b_vol_{idx}", min_value=0, value=0, label_visibility="collapsed")
            if brk.strip():
                buyers_manual.append({"broker": brk.strip(), "volume_lot": int(vol)})

        st.markdown("**🔴 Top Sellers**")
        sellers_manual = []
        for idx in range(int(n_broker)):
            ca, cb = st.columns([2, 3])
            brk = ca.text_input("", key=f"{key_prefix}_s_brk_{idx}", placeholder=f"Broker {idx+1}", label_visibility="collapsed")
            vol = cb.number_input("", key=f"{key_prefix}_s_vol_{idx}", min_value=0, value=0, label_visibility="collapsed")
            if brk.strip():
                sellers_manual.append({"broker": brk.strip(), "volume_lot": int(vol)})

        bandarmology_status = st.selectbox(
            "Status Bandarmologi",
            ["Akumulasi", "Distribusi", "Sideways/Tidak Jelas", "Mixed"],
            key=f"{key_prefix}_manual_status"
        )

        if st.button("✅ Simpan Data Manual", key=f"{key_prefix}_manual_submit", use_container_width=True):
            if buyers_manual or sellers_manual:
                st.session_state[f"{key_prefix}_result"] = {
                    "top_buyers": buyers_manual,
                    "top_sellers": sellers_manual,
                    "bandarmology_status": bandarmology_status,
                    "summary_narrative": f"Input manual: Status {bandarmology_status}."
                }
                st.session_state[f"{key_prefix}_error"] = None
                st.success("✅ Data manual berhasil disimpan.")
                st.rerun()
