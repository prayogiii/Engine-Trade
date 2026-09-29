"""Indikator teknikal & utilitas matematis murni."""
from __future__ import annotations
import math
import numpy as np
import pandas as pd


# ═══════════════════════════════════════════════════════════════
# FRAKSI HARGA BEI
# ═══════════════════════════════════════════════════════════════
def fraksi_bei(harga) -> int:
    """Bulatkan harga ke kelipatan fraksi BEI. Return 0 kalau input invalid."""
    try:
        if harga is None:
            return 0
        h = float(harga)
        if math.isnan(h) or math.isinf(h) or h <= 0:
            return 0
        if h < 200:
            f = 1
        elif h < 500:
            f = 2
        elif h < 2000:
            f = 5
        elif h < 5000:
            f = 10
        else:
            f = 25
        return round(h / f) * f
    except (ValueError, TypeError, OverflowError):
        return 0


def fraksi_step(harga) -> int:
    """Return nilai 1 tick fraksi BEI."""
    try:
        if harga is None:
            return 1
        h = float(harga)
        if math.isnan(h) or math.isinf(h) or h <= 0:
            return 1
        if h < 200:
            return 1
        if h < 500:
            return 2
        if h < 2000:
            return 5
        if h < 5000:
            return 10
        return 25
    except (ValueError, TypeError, OverflowError):
        return 1


# ═══════════════════════════════════════════════════════════════
# COPPOCK CURVE
# ═══════════════════════════════════════════════════════════════
def coppock_curve(prices, rP1: int = 14, rP2: int = 11, wP: int = 10) -> tuple[float, float]:
    """Return (curr, prev) Coppock Curve."""
    if len(prices) < max(rP1, rP2) + wP + 2:
        return 0.0, 0.0
    roc1 = [(prices[i] - prices[i - rP1]) / prices[i - rP1] * 100 for i in range(rP1, len(prices))]
    roc2 = [(prices[i] - prices[i - rP2]) / prices[i - rP2] * 100 for i in range(rP2, len(prices))]
    mn = min(len(roc1), len(roc2))
    combined = [roc1[i] + roc2[i] for i in range(-mn, 0)]

    def wma(data, per):
        if len(data) < per:
            return 0.0
        w = np.arange(1, per + 1)
        vals = [np.dot(data[i:i + per], w) / w.sum() for i in range(len(data) - per + 1)]
        return vals[-1]

    curr = wma(combined, wP)
    prev = wma(combined[:-1], wP) if len(combined) > wP else 0.0
    return curr, prev


# ═══════════════════════════════════════════════════════════════
# ADX SERIES
# ═══════════════════════════════════════════════════════════════
def compute_adx_series(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high, low, close = df['High'], df['Low'], df['Close']
    up = high.diff()
    down = -low.diff()
    plus_dm = np.where((up > down) & (up > 0), up, 0.0)
    minus_dm = np.where((down > up) & (down > 0), down, 0.0)
    plus_dm = pd.Series(plus_dm, index=df.index)
    minus_dm = pd.Series(minus_dm, index=df.index)
    tr = pd.concat(
        [high - low, (high - close.shift()).abs(), (low - close.shift()).abs()],
        axis=1,
    ).max(axis=1)
    atr = tr.ewm(alpha=1 / period, adjust=False).mean()
    plus_di = 100 * (plus_dm.ewm(alpha=1 / period, adjust=False).mean() / atr)
    minus_di = 100 * (minus_dm.ewm(alpha=1 / period, adjust=False).mean() / atr)
    dx = (abs(plus_di - minus_di) / (plus_di + minus_di)) * 100
    return dx.ewm(alpha=1 / period, adjust=False).mean()


# ═══════════════════════════════════════════════════════════════
# OU / STATISTIK
# ═══════════════════════════════════════════════════════════════
def estimate_theta_ou(close_series) -> float:
    """Estimasi theta (mean reversion speed) model Ornstein–Uhlenbeck."""
    log_price = np.log(close_series.dropna())
    log_lag = log_price.shift(1).dropna()
    diff = log_price.diff().dropna()
    common_idx = diff.index.intersection(log_lag.index)
    if len(common_idx) < 20:
        return 0.05
    y = diff.loc[common_idx].values
    X = np.vstack([np.ones(len(common_idx)), log_lag.loc[common_idx].values]).T
    coeff = np.linalg.lstsq(X, y, rcond=None)[0]
    theta = -coeff[1] if coeff[1] < 0 else 0.05
    return float(theta)


def robust_std(series) -> float:
    """Standard deviation berbasis MAD (tahan outlier)."""
    arr = np.array(series)
    if len(arr) < 4:
        return float(np.std(arr, ddof=0)) if len(arr) > 1 else 0.001
    median = np.median(arr)
    mad = np.median(np.abs(arr - median))
    return float(mad * 1.4826)


# ═══════════════════════════════════════════════════════════════
# BAR COUNTING (sisa sesi intraday)
# ═══════════════════════════════════════════════════════════════
BARS_PER_DAY_MAP = {"5m": 54, "15m": 18, "30m": 9, "60m": 5}
_INTERVAL_MINUTES = {"5m": 5, "15m": 15, "30m": 30, "60m": 60}


def hitung_bars_remaining(now_jkt, actual_interval: str,
                          bars_per_day_map: dict | None = None) -> int:
    """Estimasi sisa bar intraday sampai jam tutup (15:00 WIB)."""
    if bars_per_day_map is None:
        bars_per_day_map = BARS_PER_DAY_MAP
    h, m = now_jkt.hour, now_jkt.minute
    interval_menit = _INTERVAL_MINUTES.get(actual_interval, 5)

    if h < 12 or (h == 12 and m == 0):
        sisa = (12 * 60 - (h * 60 + m)) + 90
    elif h == 12 or (h == 13 and m < 30):
        sisa = 90
    elif (h == 13 and m >= 30) or h == 14 or (h == 15 and m == 0):
        sisa = 15 * 60 - (h * 60 + m)
    else:
        return max(1, bars_per_day_map.get(actual_interval, 54))

    return max(1, math.ceil(sisa / interval_menit))
def safe_float(value, default=0.0):
    """Konversi aman ke float, kembalikan default jika gagal."""
    try:
        return float(value)
    except (ValueError, TypeError):
        return default