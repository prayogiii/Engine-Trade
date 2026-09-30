"""
Summary Floating Position per broker — ala Sabarkaya.
Fitur:
  1. Batch yfinance (1 request untuk N ticker)
  2. Alert broker baru (fresh money)
  3. 2 tabel terpisah: Akumulator | Distributor + filter lot
  4. Historical floating chart (plotly)
  5. @st.fragment agar ganti filter tidak refresh halaman
"""
from __future__ import annotations

import json
from datetime import datetime

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import yfinance as yf


# ═══════════════════════════════════════════════════════════════
# FRAGMENT FALLBACK (Streamlit < 1.33)
# ═══════════════════════════════════════════════════════════════
try:
    _fragment = st.fragment
except AttributeError:
    def _fragment(func):
        return func


# ═══════════════════════════════════════════════════════════════
# 1. YFINANCE — SINGLE + BATCH (cached)
# ═══════════════════════════════════════════════════════════════
@st.cache_data(ttl=300, show_spinner=False)
def _get_closing(ticker: str):
    """Closing terakhir untuk 1 ticker."""
    t = ticker if ticker.endswith(".JK") else f"{ticker}.JK"
    try:
        df = yf.download(t, period="5d", interval="1d", progress=False)
        if df is None or df.empty:
            return None
        if hasattr(df.columns, "get_level_values"):
            df.columns = df.columns.get_level_values(0)
        close = df["Close"].dropna()
        return float(close.iloc[-1]) if not close.empty else None
    except Exception:
        return None


@st.cache_data(ttl=300, show_spinner=False)
def _batch_closing(tickers_tuple: tuple) -> dict:
    """Batch closing untuk banyak ticker sekaligus."""
    if not tickers_tuple:
        return {}
    syms = [t if t.endswith(".JK") else f"{t}.JK" for t in tickers_tuple]
    try:
        df = yf.download(
            syms if len(syms) > 1 else syms[0],
            period="5d", interval="1d",
            progress=False, group_by="ticker",
        )
        if df is None or df.empty:
            return {t: None for t in tickers_tuple}

        result = {}
        for t, s in zip(tickers_tuple, syms):
            try:
                if len(tickers_tuple) == 1:
                    close = df["Close"].dropna()
                else:
                    close = df[s]["Close"].dropna()
                result[t] = float(close.iloc[-1]) if not close.empty else None
            except Exception:
                result[t] = None
        return result
    except Exception:
        return {t: None for t in tickers_tuple}


@st.cache_data(ttl=300, show_spinner=False)
def _get_close_history(ticker: str, days: int = 90) -> dict:
    """Return {date_str: close} untuk 90 hari terakhir."""
    t = ticker if ticker.endswith(".JK") else f"{ticker}.JK"
    try:
        df = yf.download(t, period=f"{days}d", interval="1d", progress=False)
        if df is None or df.empty:
            return {}
        if hasattr(df.columns, "get_level_values"):
            df.columns = df.columns.get_level_values(0)
        out = {}
        for idx, row in df.iterrows():
            try:
                d = idx.date() if hasattr(idx, "date") else idx
                out[str(d)] = float(row["Close"])
            except Exception:
                continue
        return out
    except Exception:
        return {}


# ═══════════════════════════════════════════════════════════════
# 2. AGGREGATION HELPERS
# ═══════════════════════════════════════════════════════════════
def _safe_json_loads(s):
    try:
        return json.loads(s) if s else []
    except (json.JSONDecodeError, TypeError):
        return []


def _aggregate_brokers(history: list) -> dict:
    """Gabungin top_buyers + top_sellers dari SEMUA entry history."""
    agg: dict = {}

    def _ensure(code):
        if code not in agg:
            agg[code] = {"akum_lot": 0.0, "akum_val": 0.0,
                         "dist_lot": 0.0, "dist_val": 0.0}

    for h in history:
        for b in _safe_json_loads(h.get("top_buyers")):
            if not isinstance(b, dict):
                continue
            code = str(b.get("broker", "")).strip().upper()
            if not code:
                continue
            _ensure(code)
            agg[code]["akum_lot"] += float(b.get("volume_lot", 0) or 0)
            agg[code]["akum_val"] += float(b.get("value_idr", 0) or 0)

        for s in _safe_json_loads(h.get("top_sellers")):
            if not isinstance(s, dict):
                continue
            code = str(s.get("broker", "")).strip().upper()
            if not code:
                continue
            _ensure(code)
            agg[code]["dist_lot"] += float(s.get("volume_lot", 0) or 0)
            agg[code]["dist_val"] += float(s.get("value_idr", 0) or 0)

    return agg


def _aggregate_until_date(history: list, cutoff_date: str) -> dict:
    """Agregasi hanya dari entry dengan upload_date <= cutoff_date."""
    filtered = [
        h for h in history
        if str(h.get("upload_date", ""))[:10] <= cutoff_date
    ]
    return _aggregate_brokers(filtered)


def _build_rows(agg: dict, closing: float) -> list:
    """Hitung floating per broker dari hasil agregasi."""
    rows = []
    for code, d in agg.items():
        akum, dist = d["akum_lot"], d["dist_lot"]
        avg_buy = d["akum_val"] / (akum * 100) if akum > 0 else 0.0
        avg_sell = d["dist_val"] / (dist * 100) if dist > 0 else 0.0
        net = akum - dist

        if net > 0 and avg_buy > 0:
            basis = avg_buy
            fp = closing - basis
            fp_pct = (closing / basis - 1) * 100
            fp_idr = fp * net * 100
        elif net < 0 and avg_sell > 0:
            basis = avg_sell
            fp = basis - closing
            fp_pct = (basis / closing - 1) * 100
            fp_idr = fp * abs(net) * 100
        else:
            basis = fp = fp_pct = fp_idr = 0.0

        rows.append({
            "BROKER": code,
            "NET": int(net),
            "AKUM": int(akum),
            "DIST": int(dist),
            "AVG": round(basis, 1),
            "CLOSING": closing,
            "FLOATING POINT": round(fp, 1),
            "FLOATING %": round(fp_pct, 2),
            "FLOATING IDR": int(fp_idr),
        })

    rows.sort(key=lambda x: x["FLOATING IDR"], reverse=True)
    return rows


# ═══════════════════════════════════════════════════════════════
# 3. FORMATTERS
# ═══════════════════════════════════════════════════════════════
def _fmt_idr(v: float) -> str:
    sign = "+" if v >= 0 else ""
    a = abs(v)
    if a >= 1e12:
        return f"{sign}Rp {v/1e12:.2f} T"
    if a >= 1e9:
        return f"{sign}Rp {v/1e9:.2f} B"
    if a >= 1e6:
        return f"{sign}Rp {v/1e6:.2f} M"
    return f"{sign}Rp {v:,.0f}"


def _fmt_lot(v: int) -> str:
    a = abs(v)
    if a >= 1e6:
        return f"{v/1e6:.1f}M"
    if a >= 1e3:
        return f"{v/1e3:.0f}K"
    return f"{v:,}"


# ═══════════════════════════════════════════════════════════════
# 4. TABLE RENDERER
# ═══════════════════════════════════════════════════════════════
def _render_broker_table(rows: list, title: str, accent_color: str):
    """Render 1 tabel broker dengan header + rows."""
    if not rows:
        st.caption(f"(Tidak ada {title.lower()})")
        return

    st.markdown(
        f"<div style='color:{accent_color};font-size:13px;"
        f"font-weight:700;letter-spacing:0.5px;margin-bottom:6px;'>"
        f"{title} ({len(rows)})</div>",
        unsafe_allow_html=True,
    )

    widths = [0.6, 1.1, 0.9, 0.8, 0.9, 1.0, 1.0, 1.3]
    labels = ["BROKER", "NET", "AKUM", "AVG", "CLOSING",
              "FLOAT PT", "FLOAT %", "FLOAT IDR"]

    head = st.columns(widths)
    for col, lab in zip(head, labels):
        col.markdown(
            f"<div style='color:#94a3b8;font-size:10px;font-weight:600;"
            f"letter-spacing:0.5px;'>{lab}</div>",
            unsafe_allow_html=True,
        )

    st.markdown(
        "<hr style='margin:2px 0 6px 0;border-color:#262626;'>",
        unsafe_allow_html=True,
    )

    for r in rows:
        fp = r["FLOATING IDR"]
        c = "#10b981" if fp > 0 else ("#ef4444" if fp < 0 else "#94a3b8")
        cols = st.columns(widths)

        cols[0].markdown(f"**{r['BROKER']}**")
        cols[1].markdown(
            f"<span style='color:{'#10b981' if r['NET']>0 else '#ef4444'};'>"
            f"{r['NET']:+,}</span>",
            unsafe_allow_html=True,
        )
        cols[2].markdown(_fmt_lot(r["AKUM"]) if r["AKUM"] else "—")
        cols[3].markdown(f"{r['AVG']:,.1f}" if r["AVG"] else "—")
        cols[4].markdown(f"{r['CLOSING']:,.0f}")
        cols[5].markdown(
            f"<span style='color:{c};'>{r['FLOATING POINT']:+,.1f}</span>",
            unsafe_allow_html=True,
        )
        cols[6].markdown(
            f"<span style='color:{c};'>{r['FLOATING %']:+.2f}%</span>",
            unsafe_allow_html=True,
        )
        cols[7].markdown(
            f"<span style='color:{c};font-weight:600;'>"
            f"{_fmt_idr(fp)}</span>",
            unsafe_allow_html=True,
        )


# ═══════════════════════════════════════════════════════════════
# 5. FEATURE 1: ALERT BROKER BARU
# ═══════════════════════════════════════════════════════════════
def _get_fresh_brokers(history: list) -> dict:
    """Bandingkan top buyer/seller entry terbaru vs sebelumnya."""
    if len(history) < 2:
        return {"buyers": [], "sellers": []}

    sorted_h = sorted(history, key=lambda r: str(r.get("upload_date", "")), reverse=True)
    latest, prev = sorted_h[0], sorted_h[1]

    latest_buyers = {str(b.get("broker", "")).upper()
                     for b in _safe_json_loads(latest.get("top_buyers"))
                     if isinstance(b, dict)}
    prev_buyers = {str(b.get("broker", "")).upper()
                   for b in _safe_json_loads(prev.get("top_buyers"))
                   if isinstance(b, dict)}

    latest_sellers = {str(s.get("broker", "")).upper()
                      for s in _safe_json_loads(latest.get("top_sellers"))
                      if isinstance(s, dict)}
    prev_sellers = {str(s.get("broker", "")).upper()
                    for s in _safe_json_loads(prev.get("top_sellers"))
                    if isinstance(s, dict)}

    return {
        "buyers": sorted(latest_buyers - prev_buyers),
        "sellers": sorted(latest_sellers - prev_sellers),
    }


def _render_fresh_alert(history: list):
    """Banner: broker baru masuk top 10 hari ini."""
    fresh = _get_fresh_brokers(history)
    new_buy = fresh["buyers"]
    new_sell = fresh["sellers"]

    if not new_buy and not new_sell:
        return

    parts = []
    if new_buy:
        parts.append(
            f"<span style='color:#10b981;'>🆕 <b>Buyer baru:</b> "
            f"{', '.join(new_buy)}</span>"
        )
    if new_sell:
        parts.append(
            f"<span style='color:#ef4444;'>🆕 <b>Seller baru:</b> "
            f"{', '.join(new_sell)}</span>"
        )

    st.markdown(
        "<div style='background:#1e293b;border-left:3px solid #f59e0b;"
        "padding:8px 14px;border-radius:6px;margin-bottom:12px;"
        "font-size:12px;'>" + " &nbsp;|&nbsp; ".join(parts) + "</div>",
        unsafe_allow_html=True,
    )


# ═══════════════════════════════════════════════════════════════
# 6. FEATURE 2: HISTORICAL FLOATING CHART
# ═══════════════════════════════════════════════════════════════
def _render_historical_chart(ticker: str, history: list):
    """Chart: floating total per tanggal (cumulative up to date)."""
    if len(history) < 2:
        st.caption("(Butuh ≥2 hari data untuk chart historis)")
        return

    close_history = _get_close_history(ticker, days=180)
    if not close_history:
        st.caption("(Data historis harga tidak tersedia)")
        return

    sorted_h = sorted(history, key=lambda r: str(r.get("upload_date", "")))
    dates, fp_buyer, fp_seller, net_flows = [], [], [], []

    for h in sorted_h:
        d = str(h.get("upload_date", ""))[:10]
        if d not in close_history:
            continue

        agg = _aggregate_until_date(history, d)
        rows = _build_rows(agg, close_history[d])

        total_buyer_fp = sum(r["FLOATING IDR"] for r in rows if r["NET"] > 0)
        total_seller_fp = sum(r["FLOATING IDR"] for r in rows if r["NET"] < 0)

        dates.append(d)
        fp_buyer.append(total_buyer_fp / 1e9)
        fp_seller.append(total_seller_fp / 1e9)
        net_flows.append((total_buyer_fp + total_seller_fp) / 1e9)

    if not dates:
        st.caption("(Tidak bisa match tanggal upload dengan data harga)")
        return

    fig = go.Figure()

    fig.add_trace(go.Bar(
        x=dates, y=fp_buyer, name="Floating Buyer",
        marker_color="#10b981", opacity=0.85,
    ))
    fig.add_trace(go.Bar(
        x=dates, y=fp_seller, name="Floating Seller",
        marker_color="#ef4444", opacity=0.85,
    ))
    fig.add_trace(go.Scatter(
        x=dates, y=net_flows, name="Net Floating",
        mode="lines+markers",
        line=dict(color="#f59e0b", width=2),
        marker=dict(size=8),
    ))

    fig.update_layout(
        height=320,
        margin=dict(l=10, r=10, t=30, b=10),
        barmode="relative",
        plot_bgcolor="#0e1117",
        paper_bgcolor="#0e1117",
        font=dict(color="#94a3b8", size=11),
        legend=dict(orientation="h", y=1.1, x=0),
        xaxis=dict(gridcolor="#262626"),
        yaxis=dict(gridcolor="#262626", title="Floating (Rp B)"),
        hovermode="x unified",
    )

    st.plotly_chart(fig, use_container_width=True,
                    config={"displayModeBar": False})


# ═══════════════════════════════════════════════════════════════
# 7. MAIN ENTRY POINT
# ═══════════════════════════════════════════════════════════════
def render_floating_position(ticker: str, history: list):
    """Render lengkap: alert, metric, tabel interaktif, chart, verdict."""
    if not history:
        st.caption("(Belum ada history untuk hitung floating position)")
        return

    closing = _get_closing(ticker)
    if closing is None:
        st.caption("(Harga closing tidak tersedia dari yfinance)")
        return

    # Alert broker baru
    _render_fresh_alert(history)

    # Agregasi
    agg = _aggregate_brokers(history)
    if not agg:
        st.caption("(Tidak ada data broker di history)")
        return

    rows = _build_rows(agg, closing)
    buyers = [r for r in rows if r["NET"] > 0]
    sellers = [r for r in rows if r["NET"] < 0]

    # ── Metric header (di luar fragment) ──
    total_buyer_fp = sum(r["FLOATING IDR"] for r in buyers)
    total_seller_fp = sum(r["FLOATING IDR"] for r in sellers)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Closing", f"{closing:,.0f}")
    c2.metric("Akumulator", len(buyers))
    c3.metric("Distributor", len(sellers))
    c4.metric("Net Floating", _fmt_idr(total_buyer_fp + total_seller_fp))

    # ── Tabel interaktif (fragment) ──
    _render_floating_tables(ticker, buyers, sellers)

    # ── Chart historis (static) ──
    if len(history) >= 2:
        st.markdown("##### 📈 Historis Floating")
        _render_historical_chart(ticker, history)

    # ── Verdict ──
    _render_verdict(buyers, sellers, closing)


# ═══════════════════════════════════════════════════════════════
# 8. FRAGMENT: SELECTBOX + 2 TABEL
# ═══════════════════════════════════════════════════════════════
@_fragment
def _render_floating_tables(ticker: str, buyers: list, sellers: list):
    """Bagian interaktif — pakai @st.fragment supaya ganti lot tidak refresh halaman."""

    # Auto-default min lot berdasar volume terbesar di ticker ini
    all_rows = buyers + sellers
    max_vol = max((max(r["AKUM"], r["DIST"]) for r in all_rows), default=0)

    options = [0, 10_000, 50_000, 100_000, 500_000, 1_000_000]
    threshold = max_vol * 0.10
    default_idx = next(
        (i for i, v in enumerate(options) if v >= threshold and v > 0),
        2,
    )

    min_lot = st.selectbox(
        "Minimum lot (filter broker kecil)",
        options=options,
        index=default_idx,
        format_func=lambda x: f"{x:,} lot" if x > 0 else "Tampilkan semua",
        key=f"fp_min_lot_{ticker}",
    )

    big_buyers    = [r for r in buyers  if max(r["AKUM"], r["DIST"]) >= min_lot]
    small_buyers  = [r for r in buyers  if max(r["AKUM"], r["DIST"]) <  min_lot]
    big_sellers   = [r for r in sellers if max(r["AKUM"], r["DIST"]) >= min_lot]
    small_sellers = [r for r in sellers if max(r["AKUM"], r["DIST"]) <  min_lot]

    col_a, col_b = st.columns(2)
    with col_a:
        _render_broker_table(big_buyers, "📈 AKUMULATOR (net buyer)", "#10b981")
    with col_b:
        _render_broker_table(big_sellers, "📉 DISTRIBUTOR (net seller)", "#ef4444")

    if small_buyers or small_sellers:
        with st.expander(
            f"🔍 Broker kecil (lot < {min_lot:,}) — "
            f"{len(small_buyers) + len(small_sellers)} broker"
        ):
            c1, c2 = st.columns(2)
            with c1:
                _render_broker_table(small_buyers, "Akumulator kecil", "#10b981")
            with c2:
                _render_broker_table(small_sellers, "Distributor kecil", "#ef4444")


# ═══════════════════════════════════════════════════════════════
# 9. VERDICT
# ═══════════════════════════════════════════════════════════════
def _render_verdict(buyers, sellers, closing):
    """Kesimpulan teks di bawah."""
    if not buyers and not sellers:
        return

    top_buyer = buyers[0] if buyers else None
    top_seller = sellers[0] if sellers else None

    st.markdown("<div style='height:8px;'></div>", unsafe_allow_html=True)

    c1, c2 = st.columns(2)

    if top_buyer:
        status = "🟢 cuan" if top_buyer["FLOATING IDR"] > 0 else "🔴 nyangkut"
        with c1:
            st.info(
                f"**Top Akumulator:** `{top_buyer['BROKER']}` — "
                f"{_fmt_idr(top_buyer['FLOATING IDR'])} "
                f"({top_buyer['FLOATING %']:+.2f}%) {status}\n\n"
                f"Avg beli: **{top_buyer['AVG']:,.1f}** → closing: **{closing:,.0f}**"
            )

    if top_seller:
        status = "🟢 cuan" if top_seller["FLOATING IDR"] > 0 else "🔴 nyangkut"
        with c2:
            st.warning(
                f"**Top Distributor:** `{top_seller['BROKER']}` — "
                f"{_fmt_idr(top_seller['FLOATING IDR'])} "
                f"({top_seller['FLOATING %']:+.2f}%) {status}\n\n"
                f"Avg jual: **{top_seller['AVG']:,.1f}** → closing: **{closing:,.0f}**"
            )