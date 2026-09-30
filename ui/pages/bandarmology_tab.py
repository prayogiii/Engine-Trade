"""Bandarmology tab renderer — 4 chart broker flow + trade flow + foreign flow + sankey."""
from __future__ import annotations

import streamlit as st

from services.sheets_client import load_bandarmology_data
from ui.charts.realtime import render_plotly_realtime
from ui.charts.sankey import render_sankey_interactive
from ui.charts.bandarmology import (
    build_broker_flow_chart, build_trade_flow_chart, build_foreign_flow_chart,
    build_broker_sankey, render_trade_flow_spectrum_bar, fmt_money,
)
from ui.components.broker_summary import render_broker_summary_and_aggregate_ui

def display_bandarmology_tab(ticker):
    """Render section Bandarmology lengkap (4 chart realtime) di tab."""
    data = load_bandarmology_data(ticker)

    if not data:
        st.info(
            f"📭 Belum ada data Bandarmology untuk **{ticker}**. "
            "Upload screenshot Broksum via sidebar → 📸 Scan Broksum untuk mulai tracking."
        )
        return

    st.markdown(f"### 🕵🏻‍♂️ Bandarmology – {data['ticker']}")
    st.caption(
        f"Snapshot: **{data['upload_date']}** | Status: **{data['bandarmology_status']}** "
        f"| ℹ️ Flow intraday = interpolasi dari snapshot broksum "
    )
    if data.get('summary_narrative'):
        st.info(f"📝 {data['summary_narrative']}")

    render_broker_summary_and_aggregate_ui(data.get('buyers', []), data.get('sellers', []))
    st.divider()

    # CHART 1: BROKER FLOW
    st.markdown("#### 1. Broker Flow")
    fig1, df1 = build_broker_flow_chart(data)
    if fig1 is not None and df1 is not None and len(df1) > 0:
        render_plotly_realtime(fig1, height=420)
    else:
        st.caption("(Data harga intraday tidak tersedia dari yfinance)")
    st.divider()

    # CHART 2: TRADE FLOW
    st.markdown("#### 2. Trade Flow")
    fig2, df2, stats2 = build_trade_flow_chart(data)
    if fig2 is not None and df2 is not None and len(df2) > 0:
        render_plotly_realtime(fig2, height=420)
        render_trade_flow_spectrum_bar(stats2)
    else:
        st.caption("(Data harga intraday tidak tersedia dari yfinance)")
    st.divider()

    # CHART 3: FOREIGN FLOW
    st.markdown("#### 3. Foreign Flow")
    fig3, df3, stats3 = build_foreign_flow_chart(data)

    if stats3:
        fb_str = fmt_money(stats3['fb'])
        fs_str = fmt_money(stats3['fs'])
        net_str = fmt_money(stats3['net'])
        net_color = "#10b981" if stats3['net'] >= 0 else "#ef4444"
        net_sign = "+" if stats3['net'] >= 0 else ""
        tanggal = stats3.get('date', '')

        st.markdown(f"""
        <div style="background:#1a1d24; border-radius:8px; padding:14px 18px; margin:8px 0 4px 0; border:1px solid #262626; display:flex; justify-content:space-around; align-items:center; font-family:-apple-system, sans-serif;">
            <div style="text-align:center;">
                <div style="color:#94a3b8; font-size:11px; margin-bottom:4px;">F Buy</div>
                <div style="color:#10b981; font-size:18px; font-weight:600;">{fb_str}</div>
            </div>
            <div style="color:#334155; font-size:18px;">|</div>
            <div style="text-align:center;">
                <div style="color:#94a3b8; font-size:11px; margin-bottom:4px;">F Sell</div>
                <div style="color:#ef4444; font-size:18px; font-weight:600;">{fs_str}</div>
            </div>
            <div style="color:#334155; font-size:18px;">|</div>
            <div style="text-align:center;">
                <div style="color:#94a3b8; font-size:11px; margin-bottom:4px;">Net F</div>
                <div style="color:{net_color}; font-size:18px; font-weight:600;">{net_sign}{net_str}</div>
            </div>
        </div>
        <div style="text-align:center; color:#64748b; font-size:10px; margin-bottom:12px; font-style:italic;">
            📊 Sumber: IDX resmi (data per {tanggal})
        </div>
        """, unsafe_allow_html=True)

    if fig3 is not None:
        render_plotly_realtime(fig3, height=380)
    else:
        st.caption("(Data foreign flow tidak tersedia — tunggu cron IDX akumulasi data)")

    st.divider()

    # CHART 4: SANKEY
    st.markdown("#### 4. Broker Distribution ")
    fig4 = build_broker_sankey(data)
    if fig4:
        render_sankey_interactive(fig4, height=520)
        st.markdown("""
        <div style="display: flex; justify-content: center; gap: 20px; font-size: 12px; margin-top: 4px; color: #94a3b8;">
            <div><span style="color: #a855f7; font-size: 14px;">■</span> Domestic</div>
            <div><span style="color: #10b981; font-size: 14px;">■</span> BUMN</div>
            <div><span style="color: #ef4444; font-size: 14px;">■</span> Foreign</div>
        </div>
        """, unsafe_allow_html=True)
    else:
        st.caption("(Tidak ada data buyer/seller yang cukup untuk diagram )")

    if len(data['history']) > 1:
        with st.expander(f"📜 Riwayat Upload ({len(data['history'])} entri)"):
            for h in data['history'][:10]:
                st.caption(
                    f"• {h.get('upload_date', 'N/A')} — "
                    f"{h.get('bandarmology_status', 'N/A')}"
                )