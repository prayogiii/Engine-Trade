"""
Monte Carlo price simulation — regime-switching GBM/OU.

Pure — input DataFrame + parameter → output paths & stats. Tanpa Streamlit.
"""
from __future__ import annotations

import numpy as np
from scipy.stats import t as student_t

from core.indicators import estimate_theta_ou


_TRENDING_UP_REGIMES = {"STABLE BULLISH", "VOLATILE UPTREND"}
_TRENDING_DOWN_REGIMES = {"HIGH-STRESS PANIC"}


def determine_mc_regime(regime, signal, breakout):
    """
    Return 'bullish' | 'bearish' | 'sideways'.
    - bullish → GBM dengan drift positif
    - bearish → GBM dengan drift negatif
    - sideways → OU mean-reverting
    """
    is_bullish = (
        regime in _TRENDING_UP_REGIMES
        or "STRONG BUY" in signal
        or (breakout == "YES (🔥)" and "BUY" in signal)
    )
    if is_bullish:
        return "bullish"

    is_bearish = (
        regime in _TRENDING_DOWN_REGIMES
        or "AVOID" in signal
    )
    if is_bearish:
        return "bearish"

    return "sideways"


def simulate_paths(df, harga_terakhir, df_est, mc_regime,
                   n_sim=2000, n_steps=30):
    """
    Jalankan simulasi Monte Carlo.
    Return (paths, mc_regime_label).
    paths: np.ndarray shape (n_steps, n_sim).
    """
    latest_vol = np.sqrt(df["Close"].pct_change().ewm(alpha=0.06).var().iloc[-1])
    scale_corrected = (
        latest_vol / np.sqrt(df_est / (df_est - 2))
        if df_est > 2
        else latest_vol
    )

    paths = np.zeros((n_steps, n_sim))
    current_log = np.ones(n_sim) * np.log(harga_terakhir)

    if mc_regime == "bullish":
        mom5d_raw = df["Mom5D"].iloc[-1] if "Mom5D" in df.columns else 0.0
        drift_daily = float(np.clip(mom5d_raw / 500.0, 0.0005, 0.005)) * 0.6
        mc_regime_label = "GBM Bullish 🚀"
        for step in range(n_steps):
            inov = student_t.rvs(df_est, loc=0, scale=scale_corrected, size=n_sim)
            current_log = current_log + drift_daily + inov
            paths[step] = np.exp(current_log)

    elif mc_regime == "bearish":
        mom5d_raw = df["Mom5D"].iloc[-1] if "Mom5D" in df.columns else 0.0
        drift_daily = float(np.clip(mom5d_raw / 500.0, -0.010, -0.001))
        mc_regime_label = "GBM Bearish 🔻"
        for step in range(n_steps):
            inov = student_t.rvs(df_est, loc=0, scale=scale_corrected, size=n_sim)
            current_log = current_log + drift_daily + inov
            paths[step] = np.exp(current_log)

    else:
        theta_ou = estimate_theta_ou(df["Close"])
        locked_log_mean20 = np.log(df["Close"]).tail(20).mean()
        mc_regime_label = "OU Mean-Reverting ↔️"
        for step in range(n_steps):
            inov = student_t.rvs(df_est, loc=0, scale=scale_corrected, size=n_sim)
            current_log = current_log + theta_ou * (locked_log_mean20 - current_log) + inov
            paths[step] = np.exp(current_log)

    return paths, mc_regime_label


def summarize_paths(paths, harga_terakhir, signal, is_daytrade, r1, s2):
    """
    Ringkas hasil Monte Carlo.
    Return dict dengan semua stats: est_besok, low/up, prob_bull, dst.
    """
    n_sim = paths.shape[1]
    hit_tp = (np.any(paths >= r1, axis=0).sum() / n_sim) * 100
    hit_sl = (np.any(paths <= s2, axis=0).sum() / n_sim) * 100

    def _percentile_for_signal(prices, sig):
        if "STRONG BUY" in sig:
            return float(np.percentile(prices, 75))
        if "BUY" in sig:
            return float(np.percentile(prices, 65))
        if "HOLD" in sig:
            return float(np.percentile(prices, 50))
        return float(np.percentile(prices, 35))

    if is_daytrade:
        # DT: single horizon (sisa sesi ini)
        final_prices = paths[-1, :]
        est_besok = float(np.median(final_prices))
        low_est = float(np.percentile(final_prices, 25))
        up_est = float(np.percentile(final_prices, 75))
        prob_bull = (final_prices > harga_terakhir).mean() * 100
        est_besok_sinyal = _percentile_for_signal(final_prices, signal)

        return {
            "est_besok": est_besok,
            "low_est": low_est,
            "up_est": up_est,
            "prob_bull": prob_bull,
            "est_besok_sinyal": est_besok_sinyal,
            "est_30d": est_besok,
            "low_est_30d": low_est,
            "up_est_30d": up_est,
            "prob_bull_30d": prob_bull,
            "est_30d_sinyal": est_besok_sinyal,
            "estimasi_label": "Estimasi Sesi Berikutnya",
            "prob_label": "Prob Naik Sesi Berikutnya",
            "estimasi_30d_label": None,
            "prob_30d_label": None,
            "hit_tp": hit_tp,
            "hit_sl": hit_sl,
        }

    # Swing: dual horizon (besok + 30 hari)
    prices_besok = paths[0, :]
    est_besok = float(np.median(prices_besok))
    low_est = float(np.percentile(prices_besok, 25))
    up_est = float(np.percentile(prices_besok, 75))
    prob_bull = (prices_besok > harga_terakhir).mean() * 100
    est_besok_sinyal = _percentile_for_signal(prices_besok, signal)

    prices_30d = paths[-1, :]
    est_30d = float(np.median(prices_30d))
    low_est_30d = float(np.percentile(prices_30d, 25))
    up_est_30d = float(np.percentile(prices_30d, 75))
    prob_bull_30d = (prices_30d > harga_terakhir).mean() * 100
    est_30d_sinyal = _percentile_for_signal(prices_30d, signal)

    return {
        "est_besok": est_besok,
        "low_est": low_est,
        "up_est": up_est,
        "prob_bull": prob_bull,
        "est_besok_sinyal": est_besok_sinyal,
        "est_30d": est_30d,
        "low_est_30d": low_est_30d,
        "up_est_30d": up_est_30d,
        "prob_bull_30d": prob_bull_30d,
        "est_30d_sinyal": est_30d_sinyal,
        "estimasi_label": "Estimasi Besok",
        "prob_label": "Prob Naik Besok",
        "estimasi_30d_label": "Outlook 30 Hari",
        "prob_30d_label": "Prob Naik 30 Hari",
        "hit_tp": hit_tp,
        "hit_sl": hit_sl,
    }