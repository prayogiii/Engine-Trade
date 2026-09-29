"""
Volume Spread Analysis (VSA) detection.

Pure — input DataFrame, output flags dict. Tanpa Streamlit.

Deteksi:
  - Marking Close: harga ditarik naik di menit terakhir dengan volume tipis
  - No Demand: candle bullish spread sempit + volume sepi
  - Stopping Volume: candle bearish volume meledak, close di atas mid candle
"""
from __future__ import annotations

import pandas as pd


def detect_marking_close(df_5m_today: pd.DataFrame | None) -> bool:
    """
    Cek apakah 10 menit terakhir menunjukkan marking close.
    Marking close: naik > 1.5% dengan volume < 30% rata-rata.
    """
    if df_5m_today is None or df_5m_today.empty or len(df_5m_today) < 5:
        return False

    try:
        last2 = df_5m_today.tail(2)
        vol_last2 = last2["Volume"].mean()
        vol_avg5m = df_5m_today["Volume"].mean()
        close_last = float(last2["Close"].iloc[-1])
        close_ref = float(df_5m_today.iloc[-3]["Close"])

        if close_ref <= 0:
            return False

        move_pct = (close_last - close_ref) / close_ref * 100
        if move_pct > 1.5 and vol_avg5m > 0 and vol_last2 < vol_avg5m * 0.30:
            return True
    except Exception:
        pass
    return False


def detect_vsa_flags(df: pd.DataFrame) -> dict:
    """
    Deteksi No Demand & Stopping Volume dari bar terakhir.

    Return:
        {
            "no_demand": bool,
            "stopping_volume": bool,
        }
    """
    result = {"no_demand": False, "stopping_volume": False}

    if df is None or df.empty or len(df) < 21:
        return result

    try:
        recent = df.tail(21).copy()
        spread = recent["High"] - recent["Low"]
        avg_spread = spread.iloc[:-1].mean()
        avg_vol = recent["Volume"].iloc[:-1].mean()

        last_bar = recent.iloc[-1]
        last_spread = float(last_bar["High"] - last_bar["Low"])
        last_vol = float(last_bar["Volume"])
        last_close = float(last_bar["Close"])
        last_open = float(last_bar["Open"])
        last_low = float(last_bar["Low"])
        last_high = float(last_bar["High"])
        last_rng = last_high - last_low

        # No Demand
        if (
            last_close > last_open
            and avg_spread > 0
            and last_spread < avg_spread * 0.70
            and avg_vol > 0
            and last_vol < avg_vol * 0.80
        ):
            result["no_demand"] = True

        # Stopping Volume
        mid_candle = last_low + last_rng / 2 if last_rng > 0 else last_close
        if (
            last_close < last_open
            and avg_vol > 0
            and last_vol > avg_vol * 1.8
            and last_close >= mid_candle
        ):
            result["stopping_volume"] = True
    except Exception:
        pass

    return result


def build_vsa_status_text(is_marking_close: bool, is_no_demand: bool,
                          is_stopping_volume: bool) -> str:
    """Rangkum semua flag VSA jadi 1 string status."""
    tags = []
    if is_marking_close:
        tags.append("⚠️ Marking Close Detected")
    if is_no_demand:
        tags.append("🔴 No Demand (False Breakout Risk)")
    if is_stopping_volume:
        tags.append("🟢 Stopping Volume (Potential Reversal)")
    return " | ".join(tags) if tags else "✅ VSA: Normal"