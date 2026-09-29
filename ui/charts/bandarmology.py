"""
Bandarmology chart builders + helpers.

Berisi:
  - fmt_money
  - _ipf_allocate
  - build_broker_flow_chart
  - build_trade_flow_chart
  - build_foreign_flow_chart
  - build_broker_sankey
  - render_trade_flow_spectrum_bar
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import streamlit as st
import plotly.graph_objects as go

from config.brokers import get_broker_label, BROKER_TYPES
from services.yfinance_client import (
    _load_intraday_price_data,
    _fetch_idx_all_stock_summary,
)
from services.sheets_client import load_foreign_flow_history


def fmt_money(v):
    """Format Rupiah dengan satuan T/B/M/K."""
    try:
        v = float(v)
    except Exception:
        return "0"
    av = abs(v)
    sign = "-" if v < 0 else ""
    if av >= 1e12:
        return f"{sign}{av/1e12:.2f}T"
    if av >= 1e9:
        return f"{sign}{av/1e9:.2f}B"
    if av >= 1e6:
        return f"{sign}{av/1e6:.2f}M"
    if av >= 1e3:
        return f"{sign}{av/1e3:.1f}K"
    return f"{sign}{av:,.0f}"


def _ipf_allocate(row_sums, col_sums, iterations=20):
    """Iterative Proportional Fitting."""
    n = len(row_sums)
    m = len(col_sums)
    if n == 0 or m == 0:
        return []

    total_row = sum(row_sums)
    total_col = sum(col_sums)
    if total_row <= 0 or total_col <= 0:
        return [[0.0] * m for _ in range(n)]

    total = min(total_row, total_col)
    row_target = [r * total / total_row for r in row_sums]
    col_target = [c * total / total_col for c in col_sums]

    X = [[1.0] * m for _ in range(n)]

    for _ in range(iterations):
        for i in range(n):
            s = sum(X[i])
            if s > 0:
                f = row_target[i] / s
                for j in range(m):
                    X[i][j] *= f
        for j in range(m):
            s = sum(X[i][j] for i in range(n))
            if s > 0:
                f = col_target[j] / s
                for i in range(n):
                    X[i][j] *= f

    return X


def build_broker_flow_chart(data):
    """Broker Flow time-series: harga intraday + net flow kumulatif per broker."""
    if not data:
        return None, None

    df, interval = _load_intraday_price_data(data["ticker"])
    if df is None or df.empty:
        return None, None

    df = df.copy()
    df["direction"] = np.where(df["Close"] >= df["Open"], 1.0, -1.0)
    df["delta_vol"] = df["Volume"].astype(float) * df["direction"]

    raw_cum = df["delta_vol"].cumsum().values
    if len(raw_cum) == 0:
        return None, None
    final_raw = raw_cum[-1] if abs(raw_cum[-1]) > 0 else 1.0

    buyers = sorted(data["buyers"], key=lambda x: x["volume_lot"], reverse=True)[:4]
    sellers = sorted(data["sellers"], key=lambda x: x["volume_lot"], reverse=True)[:4]

    df["time"] = df.index.strftime("%H:%M")

    fig = go.Figure()

    fig.add_trace(go.Scatter(
        x=df["time"], y=df["Close"], mode="lines", name="Price",
        line=dict(color="#64748b", width=1.5, dash="dot"),
        yaxis="y2",
        hovertemplate="<b>Price</b>: %{y:,.0f}<extra></extra>",
    ))

    buyer_colors = ["#10b981", "#06b6d4", "#3b82f6", "#a855f7"]
    seller_colors = ["#ef4444", "#f97316", "#eab308", "#ec4899"]

    for idx, b in enumerate(buyers):
        target = b["volume_lot"]
        flow_cum = raw_cum / abs(final_raw) * target
        label = get_broker_label(b["broker"])
        custom_text = [
            f"{v/1e9:.2f}B Lot" if abs(v) >= 1e9 else
            f"{v/1e6:.2f}M Lot" if abs(v) >= 1e6 else
            f"{v/1e3:.1f}K Lot" if abs(v) >= 1e3 else
            f"{v:,.0f} Lot" for v in flow_cum
        ]
        fig.add_trace(go.Scatter(
            x=df["time"], y=flow_cum, mode="lines", name=f"Accum {label}",
            customdata=custom_text,
            line=dict(color=buyer_colors[idx % len(buyer_colors)], width=2),
            hovertemplate=f"<b>{label}</b>: %{{customdata}}<extra></extra>",
        ))

    for idx, s in enumerate(sellers):
        target = s["volume_lot"]
        flow_cum = -raw_cum / abs(final_raw) * target
        label = get_broker_label(s["broker"])
        custom_text = [
            f"{v/1e9:.2f}B Lot" if abs(v) >= 1e9 else
            f"{v/1e6:.2f}M Lot" if abs(v) >= 1e6 else
            f"{v/1e3:.1f}K Lot" if abs(v) >= 1e3 else
            f"{v:,.0f} Lot" for v in flow_cum
        ]
        fig.add_trace(go.Scatter(
            x=df["time"], y=flow_cum, mode="lines", name=f"Dist {label}",
            customdata=custom_text,
            line=dict(color=seller_colors[idx % len(seller_colors)], width=2),
            hovertemplate=f"<b>{label}</b>: %{{customdata}}<extra></extra>",
        ))

    tick_vals = df["time"].tolist()[::max(1, len(df) // 12)]

    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="#0f1116", plot_bgcolor="#0f1116",
        height=420, margin=dict(l=10, r=10, t=45, b=10),
        dragmode=False, hovermode="x unified",
        hoverdistance=100, spikedistance=100,
        title=dict(
            text=f"Broker Flow ({interval}) – {data['ticker']} • snapshot {data['upload_date'][:10]}",
            font=dict(size=13, color="#e0e0e0"), x=0.01, xanchor="left",
        ),
        showlegend=False,
        xaxis=dict(
            showgrid=True, gridcolor="#262626", type="category",
            tickmode="array", tickvals=tick_vals,
            showspikes=True, spikemode="across", spikesnap="cursor",
            spikethickness=1, spikecolor="#64748b", spikedash="dot",
        ),
        yaxis=dict(
            title="Net Flow (Lot)", showgrid=True, gridcolor="#262626",
            zeroline=True, zerolinecolor="#525252",
        ),
        yaxis2=dict(
            title="Harga", showgrid=False, overlaying="y", side="right",
        ),
    )
    return fig, df


def build_trade_flow_chart(data):
    """Trade Flow refined: typical price × close position signal."""
    if not data:
        return None, None, None

    df, interval = _load_intraday_price_data(data["ticker"])
    if df is None or df.empty:
        return None, None, None

    df = df.copy()
    df["typical"] = (df["High"] + df["Low"] + df["Close"]) / 3.0

    rng = (df["High"] - df["Low"]).replace(0, np.nan)
    df["close_pos"] = ((df["Close"] - df["Low"]) / rng).fillna(0.5).clip(0, 1)
    df["signal"] = df["close_pos"] * 2 - 1

    df["net_value"] = df["Volume"].astype(float) * df["typical"] * df["signal"]
    df["net_buy"] = df["net_value"].where(df["net_value"] > 0, 0)
    df["net_sell"] = df["net_value"].where(df["net_value"] < 0, 0)
    df["time"] = df.index.strftime("%H:%M")

    fig = go.Figure()

    fig.add_trace(go.Bar(
        x=df["time"], y=df["net_buy"], name="Net Buy",
        marker_color="#10b981",
        hovertemplate="<b>Net Buy</b>: %{y:,.0f}<extra></extra>",
    ))
    fig.add_trace(go.Bar(
        x=df["time"], y=df["net_sell"], name="Net Sell",
        marker_color="#ef4444",
        hovertemplate="<b>Net Sell</b>: %{y:,.0f}<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=df["time"], y=df["Close"], mode="lines", name="Price",
        line=dict(color="#0284c7", width=2), yaxis="y2",
        hovertemplate="<b>Price</b>: %{y:,.0f}<extra></extra>",
    ))

    tick_vals = df["time"].tolist()[::max(1, len(df) // 12)]

    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="#0f1116", plot_bgcolor="#0f1116",
        height=420, margin=dict(l=10, r=10, t=45, b=10), barmode="relative",
        dragmode=False, hovermode="x unified",
        hoverdistance=100, spikedistance=100,
        title=dict(
            text=f"Trade Flow ({interval}) – {data['ticker']}",
            font=dict(size=13, color="#e0e0e0"), x=0.01, xanchor="left",
        ),
        showlegend=False,
        xaxis=dict(
            showgrid=True, gridcolor="#262626", type="category",
            tickmode="array", tickvals=tick_vals,
            showspikes=True, spikemode="across", spikesnap="cursor",
            spikethickness=1, spikecolor="#64748b", spikedash="dot",
        ),
        yaxis=dict(
            title="Value (Rp)", showgrid=True, gridcolor="#262626",
            zeroline=True, zerolinecolor="#525252",
        ),
        yaxis2=dict(
            title="Harga", showgrid=False, overlaying="y", side="right",
        ),
    )

    tot_buy = float(df["net_buy"].sum())
    tot_sell = abs(float(df["net_sell"].sum()))
    tot_flow = tot_buy + tot_sell
    net_val = tot_buy - tot_sell

    net_ratio = (net_val / tot_flow) if tot_flow > 0 else 0.0
    marker_pos = max(2.0, min(98.0, (net_ratio + 1.0) / 2.0 * 100.0))

    if net_ratio > 0.25:
        status_lbl, status_clr = "Big Accumulation 🚀", "#10b981"
    elif net_ratio > 0.05:
        status_lbl, status_clr = "Accumulation 🟢", "#34d399"
    elif net_ratio >= -0.05:
        status_lbl, status_clr = "Netral ⚖️", "#94a3b8"
    elif net_ratio >= -0.25:
        status_lbl, status_clr = "Distribution 🔴", "#f87171"
    else:
        status_lbl, status_clr = "Big Distribution 🚨", "#ef4444"

    stats = {
        "tot_buy": tot_buy,
        "tot_sell": tot_sell,
        "net_val": net_val,
        "net_ratio": net_ratio,
        "net_ratio_pct": net_ratio * 100.0,
        "marker_pos": marker_pos,
        "status_lbl": status_lbl,
        "status_clr": status_clr,
    }
    return fig, df, stats


def build_foreign_flow_chart(data):
    """Foreign Flow — baca dari sheet, fallback IDX 1 hari."""
    if not data:
        return None, None, None

    ticker = str(data.get("ticker", "")).upper().replace(".JK", "").strip()
    if not ticker:
        return None, None, None

    df = load_foreign_flow_history(ticker, days=30)

    if df is None or df.empty:
        items = None
        try:
            items = _fetch_idx_all_stock_summary()
        except Exception:
            items = None

        if items:
            for it in items:
                if not isinstance(it, dict):
                    continue
                if str(it.get("StockCode", "")).upper() != ticker:
                    continue

                def _f(k):
                    v = it.get(k)
                    if v in (None, "", "N/A", "-"):
                        return 0.0
                    try:
                        return float(str(v).replace(",", ""))
                    except Exception:
                        return 0.0

                fb = _f("ForeignBuy")
                fs = _f("ForeignSell")
                close = _f("Close")
                fb_rp = fb * close if close > 0 else 0.0
                fs_rp = fs * close if close > 0 else 0.0
                date_str = str(it.get("Date") or "")[:10]

                df = pd.DataFrame([{
                    "date": date_str,
                    "close": close,
                    "foreign_buy": fb_rp,
                    "foreign_sell": fs_rp,
                    "net_foreign": fb_rp - fs_rp,
                }])
                break

    if df is None or df.empty:
        return None, None, None

    latest = df.iloc[-1]
    stats = {
        "fb": float(latest["foreign_buy"]),
        "fs": float(latest["foreign_sell"]),
        "net": float(latest["net_foreign"]),
        "date": str(latest["date"]),
        "days": len(df),
    }

    if len(df) < 7:
        fig = go.Figure()
        fig.add_annotation(
            text=f"📊 Butuh minimal 7 hari data<br>"
                 f"<span style='font-size:11px;color:#94a3b8;'>"
                 f"Saat ini: {len(df)} hari — cron IDX akan accumulate otomatis"
                 f"</span>",
            xref="paper", yref="paper", x=0.5, y=0.5,
            showarrow=False,
            font=dict(size=14, color="#cbd5e1"),
            align="center",
        )
        fig.update_layout(
            template="plotly_dark",
            paper_bgcolor="#0f1116", plot_bgcolor="#0f1116",
            height=280,
            margin=dict(l=10, r=10, t=40, b=10),
            title=dict(
                text=f"Net Foreign Flow – {ticker}",
                font=dict(size=13, color="#e0e0e0"), x=0.01, xanchor="left",
            ),
            xaxis=dict(visible=False),
            yaxis=dict(visible=False),
        )
        return fig, df, stats

    df_chart = df.copy()
    df_chart["date_str"] = pd.to_datetime(df_chart["date"]).dt.strftime("%d %b")

    bar_colors = ["#10b981" if v >= 0 else "#ef4444" for v in df_chart["net_foreign"]]

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=df_chart["date_str"], y=df_chart["net_foreign"], name="Net F Buy",
        marker_color=bar_colors,
        customdata=[["Net F Buy" if v >= 0 else "Net F Sell"] for v in df_chart["net_foreign"]],
        hovertemplate="<b>%{customdata[0]}</b>: %{y:,.0f}<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=df_chart["date_str"], y=df_chart["close"], mode="lines", name="Price",
        line=dict(color="#0284c7", width=2), yaxis="y2",
        hovertemplate="<b>Price</b>: %{y:,.0f}<extra></extra>",
    ))

    date_range = f"{df_chart['date_str'].iloc[0]} – {df_chart['date_str'].iloc[-1]}"

    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="#0f1116", plot_bgcolor="#0f1116",
        height=380, margin=dict(l=10, r=10, t=45, b=10), barmode="relative",
        dragmode=False, hovermode="x unified",
        hoverdistance=100, spikedistance=100,
        title=dict(
            text=f"Net Foreign Flow – {ticker} <span style='font-size:11px;color:#64748b;'>({date_range})</span>",
            font=dict(size=13, color="#e0e0e0"), x=0.01, xanchor="left",
        ),
        legend=dict(
            orientation="h", yanchor="top", y=-0.18,
            xanchor="center", x=0.5, font=dict(size=11, color="#94a3b8"),
        ),
        xaxis=dict(
            showgrid=True, gridcolor="#262626", type="category",
            showspikes=True, spikemode="across", spikesnap="cursor",
            spikethickness=1, spikecolor="#64748b", spikedash="dot",
        ),
        yaxis=dict(
            title="Net Foreign (Rp)", showgrid=True, gridcolor="#262626",
            zeroline=True, zerolinecolor="#525252",
            tickformat=".2s",
        ),
        yaxis2=dict(
            title="Harga", showgrid=False, overlaying="y", side="right",
        ),
    )
    return fig, df, stats


def build_broker_sankey(data):
    """Broker Distribution Sankey — buyer → seller dengan payload Value + Volume."""
    if not data:
        return None

    buyers = data.get("buyers", [])[:8]
    sellers = data.get("sellers", [])[:8]
    if not buyers and not sellers:
        return None

    def _ppl(item):
        try:
            v = float(item.get("value_idr", 0) or 0)
            vol = float(item.get("volume_lot", 0) or 0)
            if v > 0 and vol > 0:
                return v / (vol * 100)
            ap = float(item.get("avg_price", 0) or 0)
            if ap > 0:
                return ap
        except Exception:
            pass
        return 0.0

    def _val(item, fallback_price=1000.0):
        try:
            v = float(item.get("value_idr", 0) or 0)
            if v > 0:
                return v
            vol = float(item.get("volume_lot", 0) or 0)
            p = _ppl(item)
            if p <= 0:
                p = fallback_price
            return vol * 100 * p
        except Exception:
            return 0.0

    all_prices = []
    for it in (buyers + sellers):
        p = _ppl(it)
        if p > 0:
            all_prices.append(p)
    global_price = (sum(all_prices) / len(all_prices)) if all_prices else 1000.0

    total_buy = sum(float(b.get("volume_lot", 0) or 0) for b in buyers)
    total_sell = sum(float(s.get("volume_lot", 0) or 0) for s in sellers)

    buyer_nodes = [f"{b.get('broker', '??')} (Buy)" for b in buyers]
    seller_nodes = [f"{s.get('broker', '??')} (Sell)" for s in sellers]
    node_idx = {n: i for i, n in enumerate(buyer_nodes + seller_nodes)}

    sources = []
    targets = []
    vol_values = []
    val_values = []
    link_colors = []

    category_rgb = {
        "Domestic": "168, 85, 247",
        "BUMN": "16, 185, 129",
        "Foreign": "239, 68, 68",
    }

    row_sums = [float(b.get("volume_lot", 0) or 0) for b in buyers]
    col_sums = [float(s.get("volume_lot", 0) or 0) for s in sellers]
    allocation = _ipf_allocate(row_sums, col_sums, iterations=20)

    buyer_vpl = []
    for i, b in enumerate(buyers):
        bv = row_sums[i]
        buyer_vpl.append(_val(b, global_price) / bv if bv > 0 else 0)

    seller_vpl = []
    for j, s in enumerate(sellers):
        sv = col_sums[j]
        seller_vpl.append(_val(s, global_price) / sv if sv > 0 else 0)

    for i, b in enumerate(buyers):
        if row_sums[i] <= 0:
            continue
        for j, s in enumerate(sellers):
            if col_sums[j] <= 0:
                continue

            flow_vol = allocation[i][j] if (i < len(allocation) and j < len(allocation[i])) else 0.0
            if flow_vol <= 0:
                continue

            b_vpl = buyer_vpl[i]
            s_vpl = seller_vpl[j]
            if b_vpl > 0 and s_vpl > 0:
                avg_vpl = (b_vpl + s_vpl) / 2
            elif b_vpl > 0:
                avg_vpl = b_vpl
            elif s_vpl > 0:
                avg_vpl = s_vpl
            else:
                avg_vpl = global_price * 100

            flow_val = flow_vol * avg_vpl

            sources.append(node_idx[f"{b.get('broker', '??')} (Buy)"])
            targets.append(node_idx[f"{s.get('broker', '??')} (Sell)"])
            vol_values.append(flow_vol)
            val_values.append(flow_val)

            rgb = category_rgb.get(b.get("category", "Domestic"), "148, 163, 184")
            link_colors.append(f"rgba({rgb}, 0.55)")

    if not vol_values:
        return None

    def _fmt_vol(v):
        try:
            v = float(v)
        except Exception:
            return "0"
        if v >= 1e6:
            return f"{v/1e6:,.2f}M"
        return f"{v:,.0f}"

    def _fmt_val(v):
        try:
            v = float(v)
        except Exception:
            return "0"
        if v >= 1e12:
            return f"{v/1e12:.2f}T"
        if v >= 1e9:
            return f"{v/1e9:.2f}B"
        if v >= 1e6:
            return f"{v/1e6:,.0f}M"
        if v >= 1e3:
            return f"{v/1e3:,.0f}K"
        return f"{v:,.0f}"

    labels_vol = []
    for b in buyers:
        labels_vol.append(f"{b.get('broker', '??')} ({_fmt_vol(b.get('volume_lot', 0))})")
    for s in sellers:
        labels_vol.append(f"{s.get('broker', '??')} ({_fmt_vol(s.get('volume_lot', 0))})")

    labels_val = []
    for b in buyers:
        labels_val.append(f"{b.get('broker', '??')} ({_fmt_val(_val(b, global_price))})")
    for s in sellers:
        labels_val.append(f"{s.get('broker', '??')} ({_fmt_val(_val(s, global_price))})")

    cat_hex = {
        "Domestic": "#a855f7",
        "BUMN": "#10b981",
        "Foreign": "#ef4444",
    }
    node_colors = []
    for b in buyers:
        node_colors.append(cat_hex.get(b.get("category", "Domestic"), "#94a3b8"))
    for s in sellers:
        node_colors.append(cat_hex.get(s.get("category", "Domestic"), "#94a3b8"))

    fig = go.Figure(data=[go.Sankey(
        arrangement="snap",
        node=dict(
            pad=16,
            thickness=12,
            line=dict(color="#121212", width=1),
            label=labels_vol,
            color=node_colors,
        ),
        link=dict(
            source=sources,
            target=targets,
            value=vol_values,
            color=link_colors,
        ),
    )])

    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="#0f1116",
        plot_bgcolor="#0f1116",
        height=450,
        margin=dict(l=5, r=5, t=40, b=5),
        hovermode=False,
        title=dict(
            text=f"Broker Distribution – {data.get('ticker', '?')}",
            font=dict(size=13, color="#e0e0e0"),
            x=0.01,
            xanchor="left",
        ),
        font=dict(size=11, color="#94a3b8"),
        meta={
            "mode_toggle": {
                "volume": {
                    "link_values": vol_values,
                    "node_labels": labels_vol,
                },
                "value": {
                    "link_values": val_values,
                    "node_labels": labels_val,
                },
            },
            "n_buyers": len(buyers),
            "n_sellers": len(sellers),
        },
    )
    return fig


def render_trade_flow_spectrum_bar(stats):
    """Render Trade Flow Spectrum Bar."""
    if not stats:
        return

    marker_pos = stats.get("marker_pos", 50.0)
    status_lbl = stats.get("status_lbl", "Netral")
    status_clr = stats.get("status_clr", "#94a3b8")
    ratio_pct = stats.get("net_ratio_pct", 0.0)

    st.markdown(f"""<div style="background:#131722; border:1px solid #262626; border-radius:10px; padding:12px 16px; margin:10px 0 12px 0; font-family:-apple-system, sans-serif;">
<div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
<span style="color:#94a3b8; font-size:11px; font-weight:600; text-transform:uppercase; letter-spacing:0.8px;"></span>
<span style="color:{status_clr}; font-size:12px; font-weight:700;">{status_lbl} ({ratio_pct:+.1f}%)</span>
</div>
<div style="position:relative; height:18px; border-radius:9px; background:linear-gradient(90deg, #ef4444 0%, #dc2626 25%, #451a03 50%, #15803d 75%, #10b981 100%); padding:2px; box-shadow:inset 0 1px 3px rgba(0,0,0,0.6);">
<div style="position:absolute; left:20%; top:0; bottom:0; width:1px; background:rgba(0,0,0,0.4);"></div>
<div style="position:absolute; left:40%; top:0; bottom:0; width:1px; background:rgba(0,0,0,0.4);"></div>
<div style="position:absolute; left:50%; top:0; bottom:0; width:2px; background:rgba(255,255,255,0.3);"></div>
<div style="position:absolute; left:60%; top:0; bottom:0; width:1px; background:rgba(0,0,0,0.4);"></div>
<div style="position:absolute; left:80%; top:0; bottom:0; width:1px; background:rgba(0,0,0,0.4);"></div>
<div style="position:absolute; left:{marker_pos:.1f}%; top:-3px; bottom:-3px; width:4px; margin-left:-2px; background:#a855f7; border-radius:2px; box-shadow:0 0 10px #c084fc, 0 0 4px #a855f7; z-index:10;"></div>
</div>
<div style="display:flex; justify-content:space-between; color:#64748b; font-size:10px; margin-top:6px; font-weight:600;">
<span style="color:#f87171;">Net Dist</span>
<span style="color:#64748b;">Netral (0%)</span>
<span style="color:#34d399;">Net Acc</span>
</div>
</div>""", unsafe_allow_html=True)