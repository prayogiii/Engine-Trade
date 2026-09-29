"""Analysis flow page — eksekusi analyze_stock + render tabs."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import streamlit as st

from services.analyze_stock import analyze_stock
from services.gemini_client import evaluasi_mode_dengan_ai
from services.sheets_client import save_v12_prediction, save_signal_outcome, simpan_riwayat
from ui.pages.analysis_display import display_analysis_result


def render_analysis_flow_page(
    run_btn, ticker_input, ticker_raw, harga_manual, harga_terakhir_manual,
    sudah_beli, harga_beli_float, fee_beli_pct, fee_jual_pct,
    display_bandarmology_tab_fn,
):
    """Render analysis flow. display_bandarmology_tab_fn di-pass dari main.py."""
    if not run_btn:
        return
    if not ticker_input:
        st.warning("⚠️ Kode saham tidak boleh kosong!")
        st.stop()

    with st.spinner("🤖 Menganalisis mode Swing dan Daytrade secara paralel..."):
        from concurrent.futures import ThreadPoolExecutor
        try:
            from streamlit.runtime.scriptrunner import add_script_run_ctx, get_script_run_ctx
        except ImportError:
            try:
                from streamlit.scriptrunner import add_script_run_ctx, get_script_run_ctx
            except ImportError:
                add_script_run_ctx = None
                get_script_run_ctx = None

        ctx = get_script_run_ctx() if get_script_run_ctx is not None else None
        v12_mem_snapshot = dict(st.session_state.v12_memory) if "v12_memory" in st.session_state else {}

        def run_analysis_task(func, *args, **kwargs):
            if add_script_run_ctx and ctx:
                add_script_run_ctx(ctx=ctx)
            return func(*args, **kwargs)

        with ThreadPoolExecutor(max_workers=2) as executor:
            future_swing = executor.submit(
                run_analysis_task,
                analyze_stock,
                ticker_input, harga_manual, harga_terakhir_manual,
                sudah_beli, harga_beli_float,
                False, v12_mem_snapshot, fee_beli_pct, fee_jual_pct
            )
            future_day = executor.submit(
                run_analysis_task,
                analyze_stock,
                ticker_input, harga_manual, harga_terakhir_manual,
                sudah_beli, harga_beli_float,
                True, v12_mem_snapshot, fee_beli_pct, fee_jual_pct
            )
            res_swing = future_swing.result()
            res_day = future_day.result()

    if res_swing is None or res_day is None:
        st.error("❌ Gagal mengambil data untuk salah satu mode.")
        st.stop()

    # ----- REKOMENDASI MODE HYBRID (KUANTITATIF + AI + BANDARMOLOGY) -----
    def skor_mode_math(res):
        sig_raw = res.get('signal_score', 0)
        sig = sig_raw * 100.0 if sig_raw <= 1.0 else sig_raw
        rrr_score = min(max(res.get('rrr', 0), 0.0), 5.0) * 20.0
        conf_raw = res.get('confidence', 0)
        conf = conf_raw * 100.0 if conf_raw <= 1.0 else conf_raw
        return (sig * 0.5) + (rrr_score * 0.2) + (conf * 0.3)

    skor_math_swing = skor_mode_math(res_swing)
    skor_math_day = skor_mode_math(res_day)

    ai_data = None
    ai_err = None
    gemini_key = st.session_state.get("gemini_api_key")
    if gemini_key:
        with st.spinner("🤖 AI Gemini sedang mengevaluasi rekomendasi mode..."):
            ai_data, ai_err = evaluasi_mode_dengan_ai(res_swing, res_day, ticker_raw, gemini_key)

    if ai_data and isinstance(ai_data, dict) and 'swing_score' in ai_data and 'day_score' in ai_data:
        try:
            ai_swing_score = float(ai_data.get('swing_score', 50))
            ai_day_score = float(ai_data.get('day_score', 50))
            
            final_swing_score = (skor_math_swing * 0.7) + (ai_swing_score * 0.3)
            final_day_score = (skor_math_day * 0.7) + (ai_day_score * 0.3)
            
            ai_reason = str(ai_data.get('reasoning', '')).strip()
            mode_badge = "🤖 Hybrid (Kuantitatif 70% + AI 30%)"
        except Exception:
            final_swing_score = skor_math_swing
            final_day_score = skor_math_day
            ai_reason = ""
            mode_badge = "📊 Kuantitatif Only"
    else:
        final_swing_score = skor_math_swing
        final_day_score = skor_math_day
        ai_reason = ""
        if not gemini_key:
            mode_badge = "📊 Kuantitatif Only (Gemini API Key belum diisi di Sidebar)"
        elif ai_err:
            mode_badge = f"📊 Kuantitatif Only (AI Error: {ai_err})"
        else:
            mode_badge = "📊 Kuantitatif Only"

    if final_swing_score >= final_day_score:
        mode_terbaik = "Swing Trade"
        alasan_default = "Sinyal swing lebih kuat dan RRR lebih baik."
        res_terbaik = res_swing
        best_final_score = final_swing_score
    else:
        mode_terbaik = "Day Trade"
        alasan_default = "Sinyal intraday lebih kuat dan probabilitas naik lebih tinggi."
        res_terbaik = res_day
        best_final_score = final_day_score

    alasan_final = ai_reason if ai_reason else alasan_default

    st.success(
        f"🏆 **Rekomendasi Mode: {mode_terbaik}** — {alasan_final}\n\n"
        f"`{mode_badge}` | Skor Final: **{best_final_score:.1f}/100** "
        f"(Swing: {final_swing_score:.1f} vs Day: {final_day_score:.1f})"
    )

    # ----- TAMPILKAN HASIL KETIGA MODE DALAM TAB -----
    tab_swing, tab_day, tab_bandar = st.tabs([
        "📆 Swing Trade",
        "⏱️ Day Trade",
        "🐳 Bandarmology"
    ])

    with tab_swing:
        display_analysis_result(res_swing)

    with tab_day:
        display_analysis_result(res_day)

    with tab_bandar:
        display_bandarmology_tab_fn(ticker_raw)

    # ----- SIMPAN PREDIKSI V12 UNTUK KEDUA MODE -----
    for res in [res_swing, res_day]:
        try:
            # GUNAKAN HARGA ASLI, bukan harga manual user
            close_for_learning = res.get('harga_terakhir_asli') or res['harga_terakhir']
            save_v12_prediction(
                ticker_raw,
                close_for_learning,          # ✅ FIX
                res['norm_signals'],
                entry_low=res['entry_low_f'],
                entry_high=res['entry_high_f'],
                mode=res['mode']
            )
        except Exception as e:
            st.warning(f"Gagal menyimpan prediksi {res['mode']}: {e}")
    for res in [res_swing, res_day]:
        try:
            save_signal_outcome(
                ticker=ticker_raw,
                mode=res['mode'],
                signal=res['signal'],
                regime=res['regime'],
                price=res['harga_terakhir_asli'],
                horizon_days=1 if res['mode'] == 'daytrade' else 5
            )
        except Exception:
            pass
    # ----- SIMPAN RIWAYAT UNTUK KEDUA MODE (SWING & DAYTRADE) -----
    simpan_riwayat(
        [res_swing['ringkasan'], res_day['ringkasan']],
        aksi_mode=st.session_state.get('aksi_simpan_mode', 'simpan_baru'),
        target_saham=ticker_raw
    )

    simpan_riwayat(
        [res_swing['ringkasan'], res_day['ringkasan']],
        aksi_mode=st.session_state.get('aksi_simpan_mode', 'simpan_baru'),
        target_saham=ticker_raw
    )

    st.stop()
    if not run_btn:
        return
    pass