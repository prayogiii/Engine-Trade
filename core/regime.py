"""Rezim pasar & klasifikasi bar."""
from __future__ import annotations


REGIME_INFO: dict[str, str] = {
    "Strong Bullish 🚀": "Tren naik kuat dengan momentum tinggi.",
    "Bullish 📈": "Tren naik stabil. Kondisi sehat untuk akumulasi.",
    "Panic Sell 🚨": "Penurunan tajam, sering oversold.",
    "Bearish 🔻": "Tren turun terkendali.",
    "Early Recovery 🔄": "Harga di atas EMA20 tapi EMA20 < EMA50.",
    "Distribution 📉": "Harga di bawah EMA20, EMA20 > EMA50.",
    "Konsolidasi Tren ↔️": "Trending namun harga bolak-balik di EMA.",
    "Bullish Accumulation 🏗️": "Sideways dengan harga > EMA.",
    "Bearish Accumulation 🧊": "Sideways di bawah EMA.",
    "Sideways Bias Naik ↗️": "Sideways cenderung naik.",
    "Sideways Bias Turun ↘️": "Sideways cenderung turun.",
    "Sideways Normal ↔️": "Sideways moderat, tunggu katalis.",
}


def get_regime_row(row, adx_threshold: float, mom_median_th: float,
                   z_oversold_th: float = -1.5) -> tuple[str, str]:
    """
    Klasifikasi regime berdasarkan satu baris df (Close, EMA20, EMA50, ADX, ZScore, Mom5D).
    Return (regime_label, ihsg_cond).
    """
    h, e20, e50, a, z, m = (
        row['Close'], row['EMA20'], row['EMA50'],
        row['ADX'], row['ZScore'], row['Mom5D'],
    )
    if a > adx_threshold:
        if h > e20 and e20 > e50:
            if m > mom_median_th or z > z_oversold_th:
                return "Strong Bullish 🚀", "RISK-ON 🔥"
            return "Bullish 📈", "RISK-ON 🔥"
        if h < e20 and e20 < e50:
            if m < mom_median_th or z < z_oversold_th:
                return "Panic Sell 🚨", "RISK-OFF 🛑"
            return "Bearish 🔻", "RISK-OFF 🛑"
        if h > e20 and e20 < e50:
            return "Early Recovery 🔄", "TRANSISI ⚠️"
        if h < e20 and e20 > e50:
            return "Distribution 📉", "TRANSISI ⚠️"
        return "Konsolidasi Tren ↔️", "NEUTRAL ⚖️"

    if h > e20 and e20 > e50:
        return "Bullish Accumulation 🏗️", "NEUTRAL ⚖️"
    if h < e20 and e20 < e50:
        return "Bearish Accumulation 🧊", "NEUTRAL ⚖️"
    if h > e20 and e20 < e50:
        return "Sideways Bias Naik ↗️", "NEUTRAL ⚖️"
    if h < e20 and e20 > e50:
        return "Sideways Bias Turun ↘️", "NEUTRAL ⚖️"
    return "Sideways Normal ↔️", "NEUTRAL ⚖️"


def generate_regime_insight(regime: str, adx: float, ofi_raw: float, ihsg_cond: str) -> str:
    """Narasi insight dari regime + ADX + OFI + kondisi IHSG."""
    base = REGIME_INFO.get(regime, "Rezim tidak terdefinisi.")
    notes: list[str] = []

    if ofi_raw > 0.5:
        notes.append("🔹 OFI sangat positif → akumulasi agresif, bullish kuat.")
    elif ofi_raw > 0.2:
        notes.append("🔹 OFI moderat positif → akumulasi bertahap, bias bullish.")
    elif ofi_raw > -0.2:
        notes.append("🔹 OFI netral/fluktuasi → pasar balance, indecision.")
    elif ofi_raw > -0.5:
        notes.append("🔹 OFI moderat negatif → distribusi bertahap, bias bearish.")
    else:
        notes.append("🔹 OFI sangat negatif → distribusi agresif, tekanan jual kuat.")

    if adx > 40:
        notes.append("🔹 ADX > 40 → tren sangat kuat, tapi waspadai kejenuhan.")
    elif adx < 20:
        notes.append("🔹 ADX rendah → pasar sedang konsolidasi, breakout mungkin terjadi.")
    else:
        notes.append(f"🔹 ADX {adx:.1f} → kekuatan tren moderat.")

    if "RISK-ON" in ihsg_cond:
        notes.append("🔹 Sentimen pasar luas mendukung (RISK-ON).")
    elif "RISK-OFF" in ihsg_cond:
        notes.append("🔹 Sentimen pasar luas sedang defensif (RISK-OFF).")
    else:
        notes.append(f"🔹 Sentimen pasar luas: {ihsg_cond}")

    return base + " " + " ".join(notes)