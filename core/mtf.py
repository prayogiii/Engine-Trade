"""
Multi-Timeframe (MTF) Anchor check.

Pure — input df_anchor (DataFrame dari timeframe atasan), output status.
Fetch df_anchor dari service layer terpisah.
"""
from __future__ import annotations

import pandas as pd


def check_mtf_anchor(df_anchor: pd.DataFrame | None, anchor_name: str = "Daily") -> tuple[bool, str]:
    """
    Cek apakah timeframe atasan mendukung (bullish) atau tidak.

    Return:
        (is_bullish: bool, status_text: str)

    Bull score = jumlah dari 3 kondisi:
      1. close > EMA20
      2. close > EMA50
      3. MACD histogram > 0

    Bullish kalau score ≥ 2 dari 3.
    """
    if df_anchor is None or df_anchor.empty or len(df_anchor) < 50:
        return True, f"Tren {anchor_name}: data tidak cukup (asumsi bullish)"

    try:
        df = df_anchor.copy()
        df["EMA20"] = df["Close"].ewm(span=20, adjust=False).mean()
        df["EMA50"] = df["Close"].ewm(span=50, adjust=False).mean()

        ema12 = df["Close"].ewm(span=12, adjust=False).mean()
        ema26 = df["Close"].ewm(span=26, adjust=False).mean()
        macd = ema12 - ema26
        macd_signal = macd.ewm(span=9, adjust=False).mean()
        macd_hist = macd - macd_signal

        last_close = float(df["Close"].iloc[-1])
        last_ema20 = float(df["EMA20"].iloc[-1])
        last_ema50 = float(df["EMA50"].iloc[-1])
        last_macd_hist = float(macd_hist.iloc[-1])

        bull_score = 0
        if last_close > last_ema20:
            bull_score += 1
        if last_close > last_ema50:
            bull_score += 1
        if last_macd_hist > 0:
            bull_score += 1

        is_bullish = bull_score >= 2
        status = f"Tren {anchor_name}: {'Bullish ✅' if is_bullish else 'Bearish ⚠️'} (Score {bull_score}/3)"
        return is_bullish, status
    except Exception as e:
        return True, f"Error MTF: {str(e)}"