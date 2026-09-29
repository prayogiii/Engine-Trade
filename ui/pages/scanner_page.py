"""Scanner page — scan saham IDX + render hasil."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
import streamlit as st

from services.yfinance_client import get_daftar_saham, load_ihsg_data, load_stock_data
from services.gemini_client import dapatkan_model_gemini
from services.news_client import get_headlines_for_ticker
from core.scanner import score_stock_tech
from core.riwayat import dapatkan_dict_swing_aktif


# ═══════════════════════════════════════════════════════════════
# PUBLIC API
# ═══════════════════════════════════════════════════════════════
def render_scanner_page(scan_btn: bool, mode_scan: str, likuiditas_min: int, ai_rerank: bool):
    """Render scanner — execute scan + render hasil."""
    if scan_btn:
        _execute_scan(mode_scan, likuiditas_min)

    if st.session_state.get('scan_results'):
        _render_scan_results(mode_scan, likuiditas_min, ai_rerank)


# ═══════════════════════════════════════════════════════════════
# EXECUTE SCAN
# ═══════════════════════════════════════════════════════════════
def _execute_scan(mode_scan: str, likuiditas_min: int):
    st.title("🔍 Scanner Saham IDX (V12 Tech Score)")
    st.write(f"Mode: {mode_scan} | Likuiditas Min: Rp {likuiditas_min:,.0f}/hari")

    with st.spinner("📡 Mengambil daftar saham..."):
        daftar_saham = get_daftar_saham(mode_scan)
        st.info(f"📋 {len(daftar_saham)} saham akan dipindai.")

    ihsg_data = load_ihsg_data(period="6mo", interval="1d")
    if ihsg_data.empty:
        st.error("❌ Gagal mengambil data IHSG. Pastikan koneksi internet stabil.")
        st.stop()

    if "cancel_scan" not in st.session_state:
        st.session_state.cancel_scan = False

    cancel_col, _ = st.columns([1, 5])
    with cancel_col:
        if st.button("⏹️ Batalkan Scan"):
            st.session_state.cancel_scan = True

    progress_bar = st.progress(0)
    status_text = st.empty()
    hasil_scan = []

    def process_ticker(ticker):
        try:
            ticker_jk = f"{ticker}.JK"
            df = load_stock_data(ticker_jk, period="6mo", interval="1d")
            if df.empty or len(df) < 65:
                return None
            if 'Volume' in df.columns and len(df) >= 20:
                avg_vol = df['Volume'].rolling(20).mean().iloc[-1]
                last_price = float(df['Close'].iloc[-1])
                if avg_vol * last_price < likuiditas_min:
                    return None
            return score_stock_tech(df, ticker, ihsg_data)
        except Exception:
            return None

    total = len(daftar_saham)
    max_workers = 4

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_ticker = {executor.submit(process_ticker, t): t for t in daftar_saham}
        completed = 0
        for future in as_completed(future_to_ticker):
            if st.session_state.cancel_scan:
                executor.shutdown(wait=False, cancel_futures=True)
                break
            res = future.result()
            if res is not None:
                hasil_scan.append(res)
            completed += 1
            progress_bar.progress(completed / total)
            status_text.text(f"Memindai {future_to_ticker[future]} ({completed}/{total})...")

    if st.session_state.cancel_scan:
        st.warning("Scan dibatalkan oleh pengguna.")
        st.stop()

    progress_bar.empty()
    status_text.empty()

    if not hasil_scan:
        st.warning("Tidak ada saham yang lolos filter likuiditas atau data tidak lengkap.")
        st.stop()

    hasil_scan.sort(key=lambda x: x['techScore'], reverse=True)
    buy_signals = [r for r in hasil_scan if r['techScore'] > 0.05]
    sell_signals = [r for r in hasil_scan if r['techScore'] < -0.05]
    top_buys = buy_signals[:10]
    top_sells = sorted(sell_signals, key=lambda x: x['techScore'])[:10]

    st.session_state.scan_results = {
        'buy_signals': buy_signals,
        'sell_signals': sell_signals,
        'top_buys': top_buys,
        'top_sells': top_sells,
        'total': total,
        'hasil_scan_count': len(hasil_scan),
        'daftar_saham_count': len(daftar_saham),
    }
    st.rerun()


# ═══════════════════════════════════════════════════════════════
# RENDER RESULTS
# ═══════════════════════════════════════════════════════════════
def _render_scan_results(mode_scan: str, likuiditas_min: int, ai_rerank: bool):
    sr = st.session_state.scan_results
    buy_signals = sr['buy_signals']
    sell_signals = sr['sell_signals']
    top_buys = sr['top_buys']
    top_sells = sr['top_sells']
    total = sr['total']
    hasil_scan_count = sr['hasil_scan_count']
    daftar_saham_count = sr['daftar_saham_count']

    dict_active_swings = dapatkan_dict_swing_aktif(
        st.session_state.get('riwayat', []),
        st.session_state.get('riwayat_actual', {}),
    )
    if st.session_state.get('hide_active_swings', False):
        buy_signals = [r for r in buy_signals if r['ticker'].replace(".JK", "").strip().upper() not in dict_active_swings]
        top_buys = [r for r in top_buys if r['ticker'].replace(".JK", "").strip().upper() not in dict_active_swings]

    st.title("🔍 Scanner Saham IDX (V12 Tech Score)")
    st.write(f"Mode: {mode_scan} | Likuiditas Min: Rp {likuiditas_min:,.0f}/hari")
    st.markdown(f"✅ **Berhasil scan:** {hasil_scan_count}/{daftar_saham_count} saham")
    st.markdown(f"📈 Kandidat Beli: {len(buy_signals)} | 📉 Kandidat Jual: {len(sell_signals)}")

    col_buy, col_sell = st.columns([3, 1])
    with col_buy:
        st.subheader(f"🏆 TOP {len(top_buys)} RELATIF TERKUAT - Beli")
    with col_sell:
        st.subheader(f"🔻 TOP {len(top_sells)} RELATIF TERLEMAH - Jual")

    # ═══ AI RE-RANK ═══
    if ai_rerank and st.session_state.get("gemini_api_key"):
        with st.spinner("🤖 AI memverifikasi 15 kandidat (1 panggilan batch)..."):
            candidates = buy_signals[:15]
            if not candidates:
                st.info("Tidak ada kandidat Beli untuk diverifikasi AI.")
            else:
                headlines_map = {}
                for r in candidates:
                    headlines_map[r['ticker']] = get_headlines_for_ticker(r['ticker'])

                prompt = (
                    "Berikut hasil scan teknikal 15 saham. Verifikasi sinyal BUY dengan sentimen berita TERBARU yang saya berikan untuk setiap saham. "
                    "KELUARKAN HANYA JSON array, TANPA teks pembuka, analisis, atau catatan apapun. "
                    "Format: [{\"ticker\": \"BBRI\", \"confirm\": true, \"confidence_boost\": 0.0-0.15, \"reason\": \"singkat berdasarkan berita\"}]\n\n"
                )
                for r in candidates:
                    tick = r['ticker']
                    headlines = headlines_map.get(tick, ["(tidak ada berita)"])
                    prompt += (
                        f"{tick} | Signal: {r['signal']} | Tech Score: {r['techScore']:.3f} | "
                        f"Coppock: {r['coppockLabel']} | Est Return: {r['muEst']*100:.2f}% | "
                        f"Vol Surge: {r['volSurge']*100:.0f}% | RSI: {r['rsi']:.1f} | "
                        f"Z-Score: {r['zScore']:.2f} | Regime: {r['regime']} | "
                        f"Berita: {'; '.join(headlines)}\n"
                    )

                model, err = dapatkan_model_gemini(st.session_state.gemini_api_key)
                if model and not err:
                    try:
                        response = model.generate_content(prompt)
                        raw = response.text.strip()

                        start_idx = raw.rfind('[')
                        ai_data = []
                        if start_idx != -1:
                            json_str = raw[start_idx:].strip()
                            if json_str.startswith("```json"):
                                json_str = json_str[7:]
                            if json_str.endswith("```"):
                                json_str = json_str[:-3]
                            try:
                                import json
                                ai_data = json.loads(json_str)
                            except Exception:
                                st.error("Gagal parse JSON dari akhir respons.")
                        else:
                            st.error("Tidak ditemukan array JSON dalam respons AI.")

                        ai_confirmed = 0
                        ai_upgraded = 0
                        for item in ai_data:
                            ticker = item.get("ticker", "").upper()
                            for r in candidates:
                                if r['ticker'] == ticker:
                                    r['ai_confirm'] = item.get('confirm', False)
                                    r['ai_reason'] = item.get('reason', '')
                                    boost = item.get('confidence_boost', 0.0)
                                    r['ai_boost'] = boost
                                    r['hybrid_score'] = r['techScore'] + boost
                                    if r['ai_confirm']:
                                        ai_confirmed += 1
                                        if boost > 0.01:
                                            ai_upgraded += 1
                                    break

                        msg = f"🤖 AI Re‑Rank selesai: **{ai_confirmed}** saham dikonfirmasi"
                        if ai_upgraded > 0:
                            msg += f", **{ai_upgraded}** naik peringkat karena AI"
                        st.success(msg)

                        if candidates:
                            for r in candidates:
                                if 'hybrid_score' not in r:
                                    r['hybrid_score'] = r['techScore']
                            buy_signals.sort(key=lambda x: x.get('hybrid_score', x['techScore']), reverse=True)
                            top_buys = buy_signals[:10]
                            st.session_state.scan_results['buy_signals'] = buy_signals
                            st.session_state.scan_results['top_buys'] = top_buys
                    except Exception as e:
                        st.error(f"Gagal memproses respons AI: {e}")
                else:
                    st.error("Gagal mengakses Gemini untuk AI Re‑Rank.")
    elif ai_rerank:
        st.info("Isi API Key Gemini di sidebar untuk mengaktifkan AI Re‑Rank.")

    # ═══ KARTU BUY ═══
    for idx, r in enumerate(top_buys):
        rank = idx + 1
        tick_clean = r['ticker'].replace(".JK", "").strip().upper()
        active_info = dict_active_swings.get(tick_clean)

        with st.container():
            col1, col2 = st.columns([3, 1])
            with col1:
                badge = ["🥇", "🥈", "🥉"][idx] if idx < 3 else f"#{rank}"
                title_text = f"### {badge} {r['ticker']}  —  **{r['signal']}**"
                if active_info:
                    title_text += f" &nbsp; ⏳ `[SWING AKTIF - Hari ke-{active_info['b_days']}]`"
                st.markdown(title_text)
            with col2:
                st.metric("Harga", f"Rp {r['lastPrice']:,.0f}")

            if active_info:
                st.caption(f"⏳ **Swing Aktif dari {active_info['waktu']}** (Hari bursa ke-{active_info['b_days']})")

            bar_len = int(abs(r['techScore']) * 10)
            bar_str = "█" * bar_len + "░" * (10 - bar_len)
            score_text = f"Tech Score: **{r['techScore']:.3f}**  {bar_str}"
            if r.get('ai_confirm'):
                score_text += f"  |  Hybrid: **{r.get('hybrid_score', r['techScore']):.3f}**"
            st.caption(score_text)

            with st.expander("🔎 Detail Indikator"):
                ca, cb, cc = st.columns(3)
                ca.metric("Coppock", r['coppockLabel'])
                cb.metric("Est. Return", f"{r['muEst']*100:.2f}%")
                cc.metric("Regime", r['regime'])
                ca.metric("Confidence", f"{r['confidence']*100:.0f}%")
                cb.metric("Risk‑Adj (RRR)", f"{r['rrr']:.2f}")
                cc.metric("Likuiditas", r['likuiditas'])
                ca.metric("Est. TP Besok", f"Rp {r['tpEst']:,.0f}")
                cb.metric("Est. SL Besok", f"Rp {r['slEst']:,.0f}")
                cc.metric("Zona Entry", f"Rp {r['entryLow']:,.0f}-{r['entryHigh']:,.0f}")
                ca.metric("RSI-14", f"{r['rsi']:.1f}")
                cb.metric("Volume Surge", f"{r['volSurge']*100:.0f}%")
                cc.metric("Z‑Score", f"{r['zScore']:.2f}σ")
                if r['isCoppockTurningUp']:
                    st.info("⚡ **Coppock Turning Up** — Sinyal akumulasi terkuat!")
            st.divider()

    # ═══ KARTU SELL ═══
    if top_sells:
        for idx, r in enumerate(top_sells):
            rank = idx + 1
            col1, col2 = st.columns([3, 1])
            with col1:
                st.markdown(f"#{rank} **{r['ticker']}** — {r['signal']}")
                st.caption(f"Tech Score: {r['techScore']:.3f} | Est Return: {r['muEst']*100:.2f}% | Regime: {r['regime']}")
            with col2:
                st.metric("Harga", f"Rp {r['lastPrice']:,.0f}")
            st.divider()
    else:
        st.caption("(Tidak ada kandidat Jual yang memenuhi threshold)")