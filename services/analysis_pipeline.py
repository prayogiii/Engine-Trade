"""
Analysis pipeline — load data + prepare context untuk analyze_stock.

Pindah dari body analyze_stock supaya:
  - analyze_stock jadi orchestrator tipis
  - Data loading reusable (bisa dipakai scanner / CLI)
  - Testable dengan mock dataframe

Catatan: file ini di services/ karena butuh st.cache_data dari yfinance_client.
"""
from __future__ import annotations

import math

import numpy as np

from services.yfinance_client import load_stock_data, load_ihsg_data
from core.mtf import check_mtf_anchor
from core.vsa import detect_marking_close, detect_vsa_flags, build_vsa_status_text
from core.indicators import compute_adx_series


BARS_PER_DAY_MAP = {"5m": 54, "15m": 18, "30m": 9, "60m": 5}


def prepare_analysis_data(
    ticker_input: str,
    harga_manual,
    harga_terakhir_manual,
    sudah_beli: bool,
    harga_beli_float,
    is_daytrade: bool,
):
    """
    Load + prepare data untuk analisis.
    Return dict context, atau None kalau data tidak cukup / invalid.

    Section yang di-handle:
      - Section 1: load df, df_ihsg, df_daily
      - Section 1.5: MTF anchor
      - Section 1.6: VSA
      - Section 2: harga_terakhir, floating_pl, returns
      - Section 3: indikator teknikal (EMA, ADX, Mom5D, ZScore, OFI, VWAP)
    """
    bars_per_day_map = BARS_PER_DAY_MAP

    # ═══ Section 1: Load data ═══
    if is_daytrade:
        actual_interval = "5m"
        df = load_stock_data(ticker_input, period="5d", interval=actual_interval)
        if df.empty or len(df) < 20:
            actual_interval = "15m"
            df = load_stock_data(ticker_input, period="5d", interval=actual_interval)
        if df.empty or len(df) < 20:
            actual_interval = "30m"
            df = load_stock_data(ticker_input, period="5d", interval=actual_interval)
        if df.empty or len(df) < 20:
            actual_interval = "60m"
            df = load_stock_data(ticker_input, period="5d", interval=actual_interval)
        df_ihsg = load_ihsg_data(period="5d", interval="5m")
        df_daily = load_stock_data(ticker_input, period="1mo", interval="1d")
    else:
        actual_interval = "1d"
        df = load_stock_data(ticker_input, period="2y", interval="1d")
        df_ihsg = load_ihsg_data(period="2y", interval="1d")
        df_daily = df

    if df.empty:
        return None

    # Validasi
    try:
        _last_close = float(df['Close'].iloc[-1])
        if math.isnan(_last_close) or _last_close <= 0:
            return None
    except Exception:
        return None

    try:
        _valid_count = df['Close'].tail(20).dropna().shape[0]
        if _valid_count < 10:
            return None
    except Exception:
        return None

    # ═══ Section 1.5: MTF Anchor ═══
    if is_daytrade:
        df_anchor = load_stock_data(ticker_input, period="1y", interval="1d")
        anchor_name = "Daily"
    else:
        df_anchor = load_stock_data(ticker_input, period="3y", interval="1wk")
        anchor_name = "Weekly"
    is_mtf_bullish, mtf_status_text = check_mtf_anchor(df_anchor, anchor_name)

    # ═══ Section 1.6: VSA ═══
    is_marking_close = False
    try:
        df_5m_today = load_stock_data(ticker_input, period="1d", interval="5m")
        is_marking_close = detect_marking_close(df_5m_today)
    except Exception:
        pass

    vsa_flags = detect_vsa_flags(df)
    is_no_demand = vsa_flags["no_demand"]
    is_stopping_volume = vsa_flags["stopping_volume"]
    vsa_status_text = build_vsa_status_text(
        is_marking_close, is_no_demand, is_stopping_volume
    )

    # ═══ Section 2: Perhitungan dasar ═══
    harga_terakhir_asli = float(df['Close'].iloc[-1])
    harga_terakhir = harga_terakhir_manual if harga_terakhir_manual else harga_terakhir_asli

    floating_pl_pct = None
    if sudah_beli and harga_beli_float and harga_beli_float > 0:
        floating_pl_pct = (harga_terakhir - harga_beli_float) / harga_beli_float * 100

    returns = df['Close'].pct_change().dropna()
    if len(returns) < 20:
        return None

    # ═══ Section 3: Indikator teknikal ═══
    df['EMA20'] = df['Close'].ewm(span=20, adjust=False).mean()
    df['EMA50'] = df['Close'].ewm(span=50, adjust=False).mean()
    df['ADX'] = compute_adx_series(df)

    if is_daytrade:
        df['Mom5D'] = df['Close'].pct_change(10) * 100
    else:
        df['Mom5D'] = df['Close'].pct_change(5) * 100

    df['ZScore'] = (
        (df['Close'] - df['Close'].rolling(20).mean())
        / df['Close'].rolling(20).std()
    )
    df['Vol_MA20'] = df['Volume'].rolling(20).mean() if 'Volume' in df.columns else 0

    # OFI — simple
    df['Delta'] = np.where(df['Close'] > df['Open'], df['Volume'], -df['Volume'])
    df['Cumulative_OFI'] = df['Delta'].cumsum()
    df['OFI_raw'] = df['Delta'] / df['Volume'].rolling(20).mean().fillna(1)

    # OFI — enhanced (shadow-weighted)
    df['Upper_Shadow'] = df['High'] - df['Close']
    df['Lower_Shadow'] = df['Open'] - df['Low']
    df['Range'] = df['High'] - df['Low'] + 0.0001
    df['Upper_Shadow_Ratio'] = df['Upper_Shadow'] / df['Range']
    df['Lower_Shadow_Ratio'] = df['Lower_Shadow'] / df['Range']
    df['Delta_Enhanced'] = np.where(
        df['Close'] > df['Open'],
        df['Volume'] * (1 - df['Upper_Shadow_Ratio']),
        -df['Volume'] * (1 - df['Lower_Shadow_Ratio']),
    )
    df['Cumulative_OFI_Enhanced'] = df['Delta_Enhanced'].cumsum()
    df['OFI_Enhanced'] = (
        df['Cumulative_OFI_Enhanced']
        / df['Volume'].rolling(20).mean().fillna(1)
    )

    # VWAP (daytrade only)
    if is_daytrade:
        df['CumVol'] = df['Volume'].cumsum()
        df['CumPV'] = (df['Close'] * df['Volume']).cumsum()
        df['VWAP'] = df['CumPV'] / df['CumVol']
        vwap_now = df['VWAP'].iloc[-1]
        vwap_bias = (
            "Di Atas VWAP (Bullish)"
            if harga_terakhir > vwap_now
            else "Di Bawah VWAP (Bearish)"
        )
    else:
        vwap_now = None
        vwap_bias = "N/A"

    return {
        "df": df,
        "df_ihsg": df_ihsg,
        "df_daily": df_daily,
        "actual_interval": actual_interval,
        "bars_per_day_map": bars_per_day_map,
        "harga_terakhir_asli": harga_terakhir_asli,
        "harga_terakhir": harga_terakhir,
        "floating_pl_pct": floating_pl_pct,
        "returns": returns,
        "is_mtf_bullish": is_mtf_bullish,
        "mtf_status_text": mtf_status_text,
        "is_marking_close": is_marking_close,
        "is_no_demand": is_no_demand,
        "is_stopping_volume": is_stopping_volume,
        "vsa_status_text": vsa_status_text,
        "vwap_now": vwap_now,
        "vwap_bias": vwap_bias,
    }