"""AI Riwayat page — analisis riwayat dengan Gemini AI."""
from __future__ import annotations

import streamlit as st

from services.gemini_client import analisis_riwayat_global, bersihkan_teks_ai


def render_ai_riwayat_page(ai_riwayat_btn: bool):
    """Render analisis riwayat dengan AI (trigger dari tombol sidebar)."""
    if not ai_riwayat_btn:
        return

    if not st.session_state.gemini_api_key:
        st.error("Masukkan API Key terlebih dahulu!")
    elif not st.session_state.riwayat:
        st.warning("Belum ada riwayat.")
    else:
        with st.spinner("🧠 AI menganalisis riwayat..."):
            hasil, error = analisis_riwayat_global(
                st.session_state.riwayat,
                st.session_state.riwayat_actual,
                st.session_state.gemini_api_key,
            )
            if error:
                st.error(error)
            elif hasil:
                hasil_bersih = bersihkan_teks_ai(hasil)
                st.markdown(
                    f'<div class="ai-insight-card" style="border-left-color:#06b6d4;">'
                    f'<h3 style="color:#67e8f9;">📊 Insight AI dari Riwayat</h3>'
                    f'<p>{hasil_bersih}</p></div>',
                    unsafe_allow_html=True,
                )