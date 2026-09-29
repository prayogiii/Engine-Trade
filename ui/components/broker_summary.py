"""Compact broker summary + agregat Bandar vs Retail."""
from __future__ import annotations

import json
from datetime import datetime, timedelta

import streamlit as st

from core.bandarmology import klasifikasi_broker
from services.sheets_client import get_broksum_cache
def render_broker_summary_and_aggregate_ui(buyers_list, sellers_list):
    if not buyers_list and not sellers_list:
        return

    for b in buyers_list:
        if isinstance(b, dict) and (not b.get("kategori") or not b.get("kategori_icon")):
            b["kategori"], b["kategori_icon"] = klasifikasi_broker(
                b.get("broker"), b.get("volume_lot"), b.get("freq")
            )
    for s in sellers_list:
        if isinstance(s, dict) and (not s.get("kategori") or not s.get("kategori_icon")):
            s["kategori"], s["kategori_icon"] = klasifikasi_broker(
                s.get("broker"), s.get("volume_lot"), s.get("freq")
            )

    col_b, col_s = st.columns(2)
    with col_b:
        st.markdown("**🟢 Top Buyers:**")
        for b in buyers_list:
            if not isinstance(b, dict):
                continue
            kode = b.get("broker", "")
            vol = b.get("volume_lot", 0) or 0
            frq = b.get("freq")
            icon = b.get("kategori_icon", "")
            kat = b.get("kategori", "")
            frq_str = f" · Freq {frq}" if frq else ""
            st.caption(f"- {icon} **{kode}**: {vol:,.0f} lot{frq_str} — *{kat}*")
    with col_s:
        st.markdown("**🔴 Top Sellers:**")
        for s in sellers_list:
            if not isinstance(s, dict):
                continue
            kode = s.get("broker", "")
            vol = s.get("volume_lot", 0) or 0
            frq = s.get("freq")
            icon = s.get("kategori_icon", "")
            kat = s.get("kategori", "")
            frq_str = f" · Freq {frq}" if frq else ""
            st.caption(f"- {icon} **{kode}**: {vol:,.0f} lot{frq_str} — *{kat}*")

    st.markdown("---")
    st.markdown("**📊 Agregat Bandar vs Retail**")
    st.caption(
        "⚠️ Angka di bawah **hanya dari broker yang terlihat di screenshot** "
        "(biasanya Top 5-10) — bukan total market."
    )

    bandar_buy = sum((b.get("volume_lot") or 0) for b in buyers_list if isinstance(b, dict) and b.get("kategori") == "Bandar")
    retail_buy = sum((b.get("volume_lot") or 0) for b in buyers_list if isinstance(b, dict) and b.get("kategori") == "Retail")
    mixed_buy = sum((b.get("volume_lot") or 0) for b in buyers_list if isinstance(b, dict) and b.get("kategori") == "Mixed")

    bandar_sell = sum((s.get("volume_lot") or 0) for s in sellers_list if isinstance(s, dict) and s.get("kategori") == "Bandar")
    retail_sell = sum((s.get("volume_lot") or 0) for s in sellers_list if isinstance(s, dict) and s.get("kategori") == "Retail")
    mixed_sell = sum((s.get("volume_lot") or 0) for s in sellers_list if isinstance(s, dict) and s.get("kategori") == "Mixed")

    col_ab, col_as = st.columns(2)
    with col_ab:
        st.markdown("**🟢 Buy Side**")
        st.metric("🐋 Bandar (Buy)", f"{bandar_buy:,.0f} lot")
        st.metric("🧑 Retail (Buy)", f"{retail_buy:,.0f} lot")
        if mixed_buy > 0:
            st.caption(f"⚖️ Mixed: {mixed_buy:,.0f} lot")
    with col_as:
        st.markdown("**🔴 Sell Side**")
        st.metric("🐋 Bandar (Sell)", f"{bandar_sell:,.0f} lot")
        st.metric("🧑 Retail (Sell)", f"{retail_sell:,.0f} lot")
        if mixed_sell > 0:
            st.caption(f"⚖️ Mixed: {mixed_sell:,.0f} lot")

    net_bandar = bandar_buy - bandar_sell
    net_retail = retail_buy - retail_sell

    if net_bandar > 0 and net_retail < 0:
        insight_icon = "🟢"
        insight = ("<b>Bandar akumulasi, retail distribusi</b> — sinyal bullish. "
                   "Bandar sedang menyerap supply dari retail.")
    elif net_bandar < 0 and net_retail > 0:
        insight_icon = "🔴"
        insight = ("<b>Bandar distribusi, retail akumulasi</b> — hati-hati. "
                   "Bandar sedang melepas barang ke retail (kemungkinan puncak).")
    elif net_bandar > 0 and net_retail > 0:
        insight_icon = "⚖️"
        insight = "<b>Kedua pihak net buy</b> — minat beli kuat, tapi perlu konfirmasi arah lanjut."
    elif net_bandar < 0 and net_retail < 0:
        insight_icon = "⚠️"
        insight = "<b>Kedua pihak net sell</b> — tekanan jual kuat, waspadai koreksi lanjut."
    else:
        insight_icon = "⚖️"
        insight = "<b>Net flow seimbang</b> — pasar belum ada dominasi jelas."

    if net_bandar > 0:
        net_color = "#10b981"
    elif net_bandar < 0:
        net_color = "#ef4444"
    else:
        net_color = "#94a3b8"

    st.markdown(f"""<div style="background:{net_color}12; border-left:4px solid {net_color}; border-radius:8px; padding:12px 16px; margin-top:12px; color:#cbd5e1; font-size:13px; line-height:1.6;">
<div style="font-weight:600; color:{net_color}; font-size:14px; margin-bottom:6px;">{insight_icon} Net Bandar: {net_bandar:+,.0f} lot · Net Retail: {net_retail:+,.0f} lot</div>
<div>{insight}</div>
</div>""", unsafe_allow_html=True)
def _get_broksum_for_date(ticker, date_str):
    """Ambil broksum dari CACHE session (bukan hit Sheets)."""
    try:
        records = get_broksum_cache()
        ticker_clean = str(ticker).upper().replace(".JK", "").strip()

        def _parse(rec):
            try:
                tb_raw = rec.get('top_buyers', '[]')
                ts_raw = rec.get('top_sellers', '[]')
                try:
                    tb = json.loads(tb_raw) if isinstance(tb_raw, str) else (tb_raw or [])
                except Exception:
                    tb = []
                try:
                    ts = json.loads(ts_raw) if isinstance(ts_raw, str) else (ts_raw or [])
                except Exception:
                    ts = []
                return {
                    'status': rec.get('bandarmology_status', 'N/A'),
                    'upload_date': rec.get('upload_date', ''),
                    'narrative': rec.get('summary_narrative', ''),
                    'top_buyers': tb,
                    'top_sellers': ts,
                }
            except Exception:
                return None

        # Exact match
        for r in records:
            if str(r.get('ticker', '')).upper() != ticker_clean:
                continue
            if str(r.get('upload_date', '')).startswith(date_str):
                parsed = _parse(r)
                if parsed:
                    return parsed

        # Fallback ±2 hari
        try:
            target = datetime.strptime(date_str, "%Y-%m-%d")
            for delta in [1, -1, 2, -2]:
                alt = (target + timedelta(days=delta)).strftime("%Y-%m-%d")
                for r in records:
                    if str(r.get('ticker', '')).upper() != ticker_clean:
                        continue
                    if str(r.get('upload_date', '')).startswith(alt):
                        parsed = _parse(r)
                        if parsed:
                            parsed['matched_offset'] = delta
                            return parsed
        except Exception:
            pass

        return None
    except Exception:
        return None
def _render_broksum_net_insight(bs_data):
    """Compact Net Bandar vs Retail + narrative untuk riwayat view."""
    if not bs_data:
        return
    tb = bs_data.get('top_buyers', []) or []
    ts = bs_data.get('top_sellers', []) or []
    narrative = (bs_data.get('narrative') or '').strip()

    if not tb and not ts and not narrative:
        return

    # Enrich kategori (kalau belum ada)
    for item in tb + ts:
        if isinstance(item, dict) and not item.get('kategori'):
            k, ic = klasifikasi_broker(
                item.get('broker', ''),
                item.get('volume_lot', 0),
                item.get('freq')
            )
            item['kategori'] = k
            item['kategori_icon'] = ic

    def _vol(lst, kat):
        return sum(
            (x.get('volume_lot') or 0) for x in lst
            if isinstance(x, dict) and x.get('kategori') == kat
        )

    bandar_buy  = _vol(tb, 'Bandar')
    retail_buy  = _vol(tb, 'Retail')
    bandar_sell = _vol(ts, 'Bandar')
    retail_sell = _vol(ts, 'Retail')

    net_bandar = bandar_buy - bandar_sell
    net_retail = retail_buy - retail_sell

    if net_bandar > 0 and net_retail < 0:
        icon, insight, color = "🟢", "Bandar akumulasi, retail distribusi — sinyal bullish.", "#10b981"
    elif net_bandar < 0 and net_retail > 0:
        icon, insight, color = "🔴", "Bandar distribusi, retail akumulasi — hati-hati.", "#ef4444"
    elif net_bandar > 0 and net_retail > 0:
        icon, insight, color = "⚖️", "Kedua pihak net buy — minat beli kuat.", "#f59e0b"
    elif net_bandar < 0 and net_retail < 0:
        icon, insight, color = "⚠️", "Kedua pihak net sell — tekanan jual kuat.", "#ef4444"
    else:
        icon, insight, color = "⚖️", "Net flow seimbang.", "#94a3b8"

    has_brokers = bool(tb or ts)

    brokers_html = ""
    if has_brokers:
        brokers_html = (
            f'<div style="display:grid; grid-template-columns:1fr 1fr; gap:6px; margin-bottom:8px;">'
            f'<div style="background:#0f172a; border-radius:6px; padding:6px 10px; border-left:2px solid #10b981;">'
            f'<div style="color:#10b981; font-size:9px; font-weight:700; text-transform:uppercase; letter-spacing:0.5px;">🐋 Buy Side</div>'
            f'<div style="color:#cbd5e1; font-size:11px; margin-top:2px;">Bandar <b style="color:#e2e8f0;">{bandar_buy:,.0f}</b> · Retail <b style="color:#e2e8f0;">{retail_buy:,.0f}</b></div>'
            f'</div>'
            f'<div style="background:#0f172a; border-radius:6px; padding:6px 10px; border-left:2px solid #ef4444;">'
            f'<div style="color:#ef4444; font-size:9px; font-weight:700; text-transform:uppercase; letter-spacing:0.5px;">🐋 Sell Side</div>'
            f'<div style="color:#cbd5e1; font-size:11px; margin-top:2px;">Bandar <b style="color:#e2e8f0;">{bandar_sell:,.0f}</b> · Retail <b style="color:#e2e8f0;">{retail_sell:,.0f}</b></div>'
            f'</div>'
            f'</div>'
            f'<div style="display:flex; justify-content:space-between; align-items:center; padding:5px 10px; background:{color}18; border-radius:6px; margin-bottom:4px;">'
            f'<span style="color:#94a3b8; font-size:10px;">Net Bandar</span>'
            f'<span style="color:{color}; font-size:12px; font-weight:700;">{net_bandar:+,.0f} lot</span>'
            f'<span style="color:#94a3b8; font-size:10px;">Net Retail</span>'
            f'<span style="color:{color}; font-size:12px; font-weight:700;">{net_retail:+,.0f} lot</span>'
            f'</div>'
        )

    narrative_html = ""
    if narrative:
        narrative_html = (
            f'<div style="color:#cbd5e1; font-size:11px; line-height:1.6; margin-top:8px; '
            f'padding-top:8px; border-top:1px solid #334155; font-style:italic;">'
            f'📝 "{narrative}"</div>'
        )

    st.markdown(
        f"""<div style="background:linear-gradient(135deg,{color}12 0%,#1e293b 100%);
            border-left:4px solid {color}; border-radius:8px;
            padding:10px 14px; margin-bottom:10px;">
        <div style="color:{color}; font-size:10px; font-weight:700;
            letter-spacing:1px; text-transform:uppercase; margin-bottom:8px;">
            📝 AI Summary + Net Bandar vs Retail
        </div>
        {brokers_html}
        <div style="color:{color}; font-size:11px; font-weight:600; margin-top:6px;">
            {icon} {insight}
        </div>
        {narrative_html}
        </div>""",
        unsafe_allow_html=True
    )
def _get_broksum_for_date(ticker, date_str):
    """Ambil broksum dari CACHE session (bukan hit Sheets)."""
    try:
        records = get_broksum_cache()
        ticker_clean = str(ticker).upper().replace(".JK", "").strip()

        def _parse(rec):
            try:
                tb_raw = rec.get("top_buyers", "[]")
                ts_raw = rec.get("top_sellers", "[]")
                try:
                    tb = json.loads(tb_raw) if isinstance(tb_raw, str) else (tb_raw or [])
                except Exception:
                    tb = []
                try:
                    ts = json.loads(ts_raw) if isinstance(ts_raw, str) else (ts_raw or [])
                except Exception:
                    ts = []
                return {
                    "status": rec.get("bandarmology_status", "N/A"),
                    "upload_date": rec.get("upload_date", ""),
                    "narrative": rec.get("summary_narrative", ""),
                    "top_buyers": tb,
                    "top_sellers": ts,
                }
            except Exception:
                return None

        # Exact match
        for r in records:
            if str(r.get("ticker", "")).upper() != ticker_clean:
                continue
            if str(r.get("upload_date", "")).startswith(date_str):
                parsed = _parse(r)
                if parsed:
                    return parsed

        # Fallback ±2 hari
        try:
            target = datetime.strptime(date_str, "%Y-%m-%d")
            for delta in [1, -1, 2, -2]:
                alt = (target + timedelta(days=delta)).strftime("%Y-%m-%d")
                for r in records:
                    if str(r.get("ticker", "")).upper() != ticker_clean:
                        continue
                    if str(r.get("upload_date", "")).startswith(alt):
                        parsed = _parse(r)
                        if parsed:
                            parsed["matched_offset"] = delta
                            return parsed
        except Exception:
            pass

        return None
    except Exception:
        return None


def _render_broksum_net_insight(bs_data):
    """Compact Net Bandar vs Retail + narrative untuk riwayat view."""
    if not bs_data:
        return
    tb = bs_data.get("top_buyers", []) or []
    ts = bs_data.get("top_sellers", []) or []
    narrative = (bs_data.get("narrative") or "").strip()

    if not tb and not ts and not narrative:
        return

    # Enrich kategori kalau belum ada
    for item in tb + ts:
        if isinstance(item, dict) and not item.get("kategori"):
            k, ic = klasifikasi_broker(
                item.get("broker", ""),
                item.get("volume_lot", 0),
                item.get("freq"),
            )
            item["kategori"] = k
            item["kategori_icon"] = ic

    def _vol(lst, kat):
        return sum(
            (x.get("volume_lot") or 0) for x in lst
            if isinstance(x, dict) and x.get("kategori") == kat
        )

    bandar_buy = _vol(tb, "Bandar")
    retail_buy = _vol(tb, "Retail")
    bandar_sell = _vol(ts, "Bandar")
    retail_sell = _vol(ts, "Retail")

    net_bandar = bandar_buy - bandar_sell
    net_retail = retail_buy - retail_sell

    if net_bandar > 0 and net_retail < 0:
        icon, insight, color = "🟢", "Bandar akumulasi, retail distribusi — sinyal bullish.", "#10b981"
    elif net_bandar < 0 and net_retail > 0:
        icon, insight, color = "🔴", "Bandar distribusi, retail akumulasi — hati-hati.", "#ef4444"
    elif net_bandar > 0 and net_retail > 0:
        icon, insight, color = "⚖️", "Kedua pihak net buy — minat beli kuat.", "#f59e0b"
    elif net_bandar < 0 and net_retail < 0:
        icon, insight, color = "⚠️", "Kedua pihak net sell — tekanan jual kuat.", "#ef4444"
    else:
        icon, insight, color = "⚖️", "Net flow seimbang.", "#94a3b8"

    has_brokers = bool(tb or ts)

    brokers_html = ""
    if has_brokers:
        brokers_html = (
            f'<div style="display:grid; grid-template-columns:1fr 1fr; gap:6px; margin-bottom:8px;">'
            f'<div style="background:#0f172a; border-radius:6px; padding:6px 10px; border-left:2px solid #10b981;">'
            f'<div style="color:#10b981; font-size:9px; font-weight:700; text-transform:uppercase; letter-spacing:0.5px;">🐋 Buy Side</div>'
            f'<div style="color:#cbd5e1; font-size:11px; margin-top:2px;">Bandar <b style="color:#e2e8f0;">{bandar_buy:,.0f}</b> · Retail <b style="color:#e2e8f0;">{retail_buy:,.0f}</b></div>'
            f'</div>'
            f'<div style="background:#0f172a; border-radius:6px; padding:6px 10px; border-left:2px solid #ef4444;">'
            f'<div style="color:#ef4444; font-size:9px; font-weight:700; text-transform:uppercase; letter-spacing:0.5px;">🐋 Sell Side</div>'
            f'<div style="color:#cbd5e1; font-size:11px; margin-top:2px;">Bandar <b style="color:#e2e8f0;">{bandar_sell:,.0f}</b> · Retail <b style="color:#e2e8f0;">{retail_sell:,.0f}</b></div>'
            f'</div>'
            f'</div>'
            f'<div style="display:flex; justify-content:space-between; align-items:center; padding:5px 10px; background:{color}18; border-radius:6px; margin-bottom:4px;">'
            f'<span style="color:#94a3b8; font-size:10px;">Net Bandar</span>'
            f'<span style="color:{color}; font-size:12px; font-weight:700;">{net_bandar:+,.0f} lot</span>'
            f'<span style="color:#94a3b8; font-size:10px;">Net Retail</span>'
            f'<span style="color:{color}; font-size:12px; font-weight:700;">{net_retail:+,.0f} lot</span>'
            f'</div>'
        )

    narrative_html = ""
    if narrative:
        narrative_html = (
            f'<div style="color:#cbd5e1; font-size:11px; line-height:1.6; margin-top:8px; '
            f'padding-top:8px; border-top:1px solid #334155; font-style:italic;">'
            f'📝 "{narrative}"</div>'
        )

    st.markdown(
        f"""<div style="background:linear-gradient(135deg,{color}12 0%,#1e293b 100%);
            border-left:4px solid {color}; border-radius:8px;
            padding:10px 14px; margin-bottom:10px;">
        <div style="color:{color}; font-size:10px; font-weight:700;
            letter-spacing:1px; text-transform:uppercase; margin-bottom:8px;">
            📝 AI Summary + Net Bandar vs Retail
        </div>
        {brokers_html}
        <div style="color:{color}; font-size:11px; font-weight:600; margin-top:6px;">
            {icon} {insight}
        </div>
        {narrative_html}
        </div>""",
        unsafe_allow_html=True,
    )