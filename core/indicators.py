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
# Bar per hari bursa penuh (Senin-Kamis, 319 menit efektif: 09:00-12:00 + 13:30-15:49)
# Jumat punya sesi lebih pendek (259 menit) — di-cover oleh hitung_bars_remaining
# via perhitungan sesi eksplisit, tidak lewat map ini.
BARS_PER_DAY_MAP = {"5m": 64, "15m": 22, "30m": 11, "60m": 6}
_INTERVAL_MINUTES = {"5m": 5, "15m": 15, "30m": 30, "60m": 60}


def hitung_bars_remaining(now_jkt, actual_interval: str,
                          bars_per_day_map: dict | None = None) -> int:
    """
    Estimasi sisa bar intraday sampai akhir sesi bursa BEI.

    Jam bursa BEI (sejak April 2023):
      Senin-Kamis: Sesi I 09:00-12:00, Sesi II 13:30-15:49 WIB
      Jumat:       Sesi I 09:00-11:30, Sesi II 14:00-15:49 WIB
    (pra-penutupan 15:49-16:00 tidak dihitung sebagai sesi trading)

    Return:
      - Dalam sesi / istirahat hari bursa: sisa bar dari sekarang sampai 15:49
        (atau sisa sesi I + sesi II untuk pagi Jumat).
      - Weekend: estimasi total bar per hari penuh (bars_per_day_map).
      - Selalu minimal 1 (kompatibel dengan sizing Monte Carlo).
    """
    if bars_per_day_map is None:
        bars_per_day_map = BARS_PER_DAY_MAP
    interval_menit = _INTERVAL_MINUTES.get(actual_interval, 5)
    full_day_bars = max(1, bars_per_day_map.get(actual_interval, 64))

    if now_jkt.weekday() >= 5:
        return full_day_bars

    is_friday = now_jkt.weekday() == 4
    if is_friday:
        s1_start, s1_end = 9 * 60, 11 * 60 + 30
        s2_start, s2_end = 14 * 60, 15 * 60 + 49
    else:
        s1_start, s1_end = 9 * 60, 12 * 60
        s2_start, s2_end = 13 * 60 + 30, 15 * 60 + 49

    t = now_jkt.hour * 60 + now_jkt.minute

    if t < s1_start:
        sisa_menit = (s1_end - s1_start) + (s2_end - s2_start)
    elif t <= s1_end:
        sisa_menit = (s1_end - t) + (s2_end - s2_start)
    elif t < s2_start:
        sisa_menit = s2_end - s2_start
    elif t <= s2_end:
        sisa_menit = s2_end - t
    else:
        return 1

    return max(1, math.ceil(sisa_menit / interval_menit))
def safe_float(value, default=0.0):
    """Konversi aman ke float, kembalikan default jika gagal."""
    try:
        return float(value)
    except (ValueError, TypeError):
        return default
def compute_ofi_enhanced(df, window: int = 20):
    """
    Enhanced Order Flow Imbalance — shadow-weighted directional volume.

    FIX: bayangan candle dihitung sesuai jenis candle.
      - Green (Close >= Open): upper = High - Close, lower = Open - Low
      - Red   (Close <  Open): upper = High - Open,  lower = Close - Low
    (Bug lama: High-Close & Open-Low untuk semua candle → merah marubozu
     menghasilkan lower_ratio ≈ 1 → delta ≈ 0, padahal tekanan jual masif.)

    OFI_Enhanced = rolling_sum(Delta_Enhanced, window) / rolling_sum(Volume, window)
      → naturally bounded [-1, 1], interpretable sebagai
        "net directional flow over last N bars, as fraction of total volume".

    Returns DataFrame [Upper_Shadow_Ratio, Lower_Shadow_Ratio,
                       Delta_Enhanced, OFI_Enhanced] sejajar index df.
    """
    is_green = df['Close'] >= df['Open']
    upper_shadow = np.where(is_green, df['High'] - df['Close'], df['High'] - df['Open'])
    lower_shadow = np.where(is_green, df['Open'] - df['Low'],  df['Close'] - df['Low'])

    full_range = (df['High'] - df['Low']).replace(0, np.nan)

    upper_ratio = (upper_shadow / full_range).fillna(0.0).clip(0.0, 1.0)
    lower_ratio = (lower_shadow / full_range).fillna(0.0).clip(0.0, 1.0)

    delta_enhanced = np.where(
        is_green,
        df['Volume'] * (1 - upper_ratio),
        -df['Volume'] * (1 - lower_ratio),
    )
    delta_series = pd.Series(delta_enhanced, index=df.index, dtype='float64')

    vol_sum = df['Volume'].rolling(window, min_periods=5).sum()
    delta_sum = delta_series.rolling(window, min_periods=5).sum()
    ofi = (delta_sum / (vol_sum + 1e-9)).clip(-1.0, 1.0).fillna(0.0)

    return pd.DataFrame({
        'Upper_Shadow_Ratio': upper_ratio,
        'Lower_Shadow_Ratio': lower_ratio,
        'Delta_Enhanced':     delta_series,
        'OFI_Enhanced':       ofi,
    }, index=df.index)
