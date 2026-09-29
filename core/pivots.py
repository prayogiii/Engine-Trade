"""
Pivot point & support/resistance calculation.

Pure — input OHLC, output pivot levels.
"""
from __future__ import annotations

import pandas as pd


def find_last_valid_bar(df: pd.DataFrame, max_lookback: int = 6):
    """
    Cari bar terakhir dengan High != Low (bar valid untuk pivot).
    Return: (hi, lo, cl) atau None kalau tidak ada.
    """
    if df is None or df.empty:
        return None

    for i in range(1, min(max_lookback, len(df))):
        row = df.iloc[-i]
        h_val = float(row["High"])
        l_val = float(row["Low"])
        c_val = float(row["Close"])
        if h_val != l_val and h_val > 0 and l_val > 0:
            return h_val, l_val, c_val

    # Fallback: bar terakhir
    last = df.iloc[-1]
    return float(last["High"]), float(last["Low"]), float(last["Close"])


def compute_pivots_from_ohlc(hi: float, lo: float, cl: float) -> dict:
    """
    Hitung pivot levels dari 1 set OHLC.
    Return: {"pp": ..., "r1": ..., "r2": ..., "s1": ..., "s2": ...}
    """
    if hi == lo:
        return {"pp": cl, "r1": cl, "r2": cl, "s1": cl, "s2": cl}

    pp = (hi + lo + cl) / 3
    r1 = 2 * pp - lo
    s1 = 2 * pp - hi
    r2 = pp + (hi - lo)
    s2 = pp - (hi - lo)

    return {"pp": pp, "r1": r1, "r2": r2, "s1": s1, "s2": s2}


def compute_pivots_for_swing(df: pd.DataFrame) -> dict:
    """Pivot untuk swing — pakai bar valid terakhir dari df harian."""
    result = find_last_valid_bar(df)
    if result is None:
        return {"pp": 0, "r1": 0, "r2": 0, "s1": 0, "s2": 0}
    hi, lo, cl = result
    return compute_pivots_from_ohlc(hi, lo, cl)


def compute_pivots_for_daytrade(df_daily: pd.DataFrame, today_date) -> dict:
    """
    Pivot untuk daytrade — pakai OHLC hari sebelumnya.
    df_daily: data harian
    today_date: date object (untuk filter bar < today)
    """
    if df_daily is None or df_daily.empty:
        return {"pp": 0, "r1": 0, "r2": 0, "s1": 0, "s2": 0}

    df_daily_filtered = df_daily[df_daily.index.date < today_date]
    if not df_daily_filtered.empty:
        prev_day = df_daily_filtered.iloc[-1]
        hi = float(prev_day["High"])
        lo = float(prev_day["Low"])
        cl = float(prev_day["Close"])
    else:
        result = find_last_valid_bar(df_daily)
        if result is None:
            return {"pp": 0, "r1": 0, "r2": 0, "s1": 0, "s2": 0}
        hi, lo, cl = result

    return compute_pivots_from_ohlc(hi, lo, cl)