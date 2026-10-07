"""
Analysis engine — threshold, regime, indicators, signal (Section 6-11).

Menggantikan Section 6-11 di analyze_stock.
Section 12-13 (entry/SL/TP) tetap di main.py.
"""
from __future__ import annotations

from datetime import datetime

import numpy as np
import pandas as pd
import pytz
from scipy.optimize import minimize
from scipy.stats import t as student_t

from config.settings import FACTOR_KEYS
from core.indicators import (
    coppock_curve, hitung_bars_remaining,
)
from core.regime import get_regime_row
from core.scoring import get_adaptive_weights
from core.signal import parse_signal_category as _parse_signal_category
from core.pivots import (
    compute_pivots_for_swing, compute_pivots_for_daytrade,
)
from services.sheets_client import get_regime_signal_accuracy


def compute_thresholds(df, is_daytrade):
    """Section 6 — Threshold & distribusi."""
    if is_daytrade:
        backtest_bars = 100
        if len(df) < 200:
            split_point = int(len(df) * 0.6)
            df_thresh = df.iloc[:split_point]
            backtest_window = len(df) - split_point
        else:
            df_thresh = df.iloc[-(backtest_bars * 2):-backtest_bars]
            backtest_window = backtest_bars
    else:
        split_idx = max(126, len(df) - 126)
        df_thresh = df.iloc[:split_idx]
        backtest_window = 126

    returns_thresh = df_thresh['Close'].pct_change().dropna()
    adx_threshold = (
        np.percentile(df_thresh['ADX'].dropna(), 75)
        if not df_thresh['ADX'].dropna().empty else 20
    )
    z_oversold_th = -1.5
    mom_median_th = (
        np.percentile(df_thresh['Mom5D'].dropna(), 50)
        if not df_thresh['Mom5D'].dropna().empty else 0.0
    )

    def t_loglike(p, d):
        if p[0] <= 2 or p[2] <= 0:
            return np.inf
        return -np.sum(student_t.logpdf(d, p[0], p[1], p[2]))

    res_opt = minimize(
        t_loglike,
        [5, returns_thresh.mean(), returns_thresh.std()],
        bounds=[(2.1, 100), (-0.1, 0.1), (1e-6, None)],
        args=(returns_thresh,),
        method='L-BFGS-B',
    )
    df_est, t_loc, t_scale = (
        res_opt.x if res_opt.success
        else (5, returns_thresh.mean(), returns_thresh.std())
    )

    return {
        "df_thresh": df_thresh,
        "returns_thresh": returns_thresh,
        "adx_threshold": adx_threshold,
        "z_oversold_th": z_oversold_th,
        "mom_median_th": mom_median_th,
        "df_est": df_est,
        "backtest_window": backtest_window,
    }


def compute_regime_and_beta(df, df_ihsg, returns, adx_threshold, mom_median_th):
    """Section 7-8 — Regime + Beta IHSG."""
    regime, ihsg_cond = get_regime_row(
        df.iloc[-1], adx_threshold, mom_median_th, z_oversold_th=-1.5,
    )
    adx = df['ADX'].iloc[-1]

    beta_ihsg = 1.0
    ihsg_ret = pd.Series(dtype=float)
    try:
        if not df_ihsg.empty:
            ihsg_ret = df_ihsg['Close'].pct_change().dropna()
            common = returns.index.intersection(ihsg_ret.index)
            if len(common) > 20:
                beta_ihsg = (
                    np.cov(returns.loc[common], ihsg_ret.loc[common])[0, 1]
                    / np.var(ihsg_ret.loc[common])
                )
    except Exception:
        pass

    return {
        "regime": regime,
        "ihsg_cond": ihsg_cond,
        "adx": adx,
        "beta_ihsg": beta_ihsg,
        "ihsg_ret": ihsg_ret,
    }


def compute_atr_rsi(df, harga_terakhir_asli, is_daytrade, actual_interval, bars_per_day_map, df_daily=None):
    """Section 9 — ATR & RSI + bars_remaining.

    Tambahan: ATR harian (atr14_daily) untuk basis TP daytrade.
    """
    df['TR'] = pd.concat([
        df['High'] - df['Low'],
        (df['High'] - df['Close'].shift()).abs(),
        (df['Low'] - df['Close'].shift()).abs(),
    ], axis=1).max(axis=1)
    atr14_val = df['TR'].rolling(14).mean().iloc[-1]
    atr_pct = (atr14_val / harga_terakhir_asli) * 100

    # ═══ ATR harian (untuk TP daytrade) ═══
    atr14_daily = None
    atr_pct_daily = None
    if df_daily is not None and len(df_daily) >= 15:
        dfd = df_daily.copy()
        dfd['TR'] = pd.concat([
            dfd['High'] - dfd['Low'],
            (dfd['High'] - dfd['Close'].shift()).abs(),
            (dfd['Low'] - dfd['Close'].shift()).abs(),
        ], axis=1).max(axis=1)
        atr14_daily = dfd['TR'].rolling(14).mean().iloc[-1]
        atr_pct_daily = (atr14_daily / harga_terakhir_asli) * 100

    now_jkt = datetime.now(pytz.timezone("Asia/Jakarta"))
    if is_daytrade:
        bars_remaining = hitung_bars_remaining(now_jkt, actual_interval, bars_per_day_map)
    else:
        bars_remaining = None

    delta = df['Close'].diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.rolling(14).mean().iloc[-1]
    avg_loss = loss.rolling(14).mean().iloc[-1]
    if avg_loss is None or avg_loss == 0:
        rsi14 = 100.0
    else:
        rsi14 = 100.0 - (100.0 / (1.0 + (avg_gain / avg_loss)))

    return {
        "df": df,
        "atr14_val": atr14_val,
        "atr14_daily": atr14_daily,
        "atr_pct": atr_pct,
        "atr_pct_daily": atr_pct_daily,
        "rsi14": rsi14,
        "bars_remaining": bars_remaining,
    }


def compute_pivots(df, df_daily, is_daytrade):
    """Section 10 — Pivot."""
    if is_daytrade:
        today_jkt = datetime.now(pytz.timezone("Asia/Jakarta")).date()
        piv = compute_pivots_for_daytrade(df_daily, today_jkt)
    else:
        piv = compute_pivots_for_swing(df)
    return piv


def compute_v12_signal(
    df, ticker_raw, regime, mom_median_th,
    avg_sentiment, beta_ihsg, ihsg_ret,
    bandar_flow_val, foreign_zscore_val,
    is_retail_trap, is_marking_close, is_no_demand,
    is_mtf_bullish, is_stopping_volume,
    v12_mem=None,
):
    """Section 11 — V12 adaptive signal."""
    adaptive_w = get_adaptive_weights(ticker_raw, regime, v12_mem=v12_mem)
    coppock_val, coppock_prev = coppock_curve(df['Close'].values)

    factor_signals = {
        "Momentum": (df['Mom5D'].iloc[-1] - mom_median_th) / max(0.1, df['Mom5D'].std()),
        "AI_Senti": avg_sentiment,
        "MeanRev": -df['ZScore'].iloc[-1] / 3.0,
        "Beta_IHSG": beta_ihsg * (ihsg_ret.iloc[-1] if not ihsg_ret.empty else 0.0),
        "Coppock": coppock_val / 10.0,
        "OFI": df['OFI_Enhanced'].iloc[-1] / 5.0,
        "Bandar_Flow": bandar_flow_val,
        "Foreign_ZScore": foreign_zscore_val,
    }
    norm_signals = {k: max(-1.0, min(1.0, v)) for k, v in factor_signals.items()}
    total_score = sum(norm_signals[k] * adaptive_w.get(k, 0.15) for k in FACTOR_KEYS)

    historical_scores = []
    for i in range(max(20, len(df) - 60), len(df)):
        row_signals = {
            "Momentum": float(np.clip((df['Mom5D'].iloc[i] - mom_median_th) / max(0.1, df['Mom5D'].std()), -1, 1)),
            "AI_Senti": avg_sentiment,
            "MeanRev": float(np.clip(-df['ZScore'].iloc[i] / 3.0, -1, 1)),
            "Beta_IHSG": 0.0,
            "Coppock": 0.0,
            "OFI": float(np.clip(df['OFI_Enhanced'].iloc[i] / 5.0, -1, 1)),
            "Bandar_Flow": bandar_flow_val,
            "Foreign_ZScore": foreign_zscore_val,
        }
        s = sum(row_signals[k] * adaptive_w.get(k, 0.15) for k in FACTOR_KEYS)
        historical_scores.append(s)

    score_std = np.std(historical_scores) if len(historical_scores) > 5 else 0.15
    score_std = max(0.10, min(0.35, score_std))

    th_strong = score_std * 1.0
    th_buy = score_std * 0.4
    th_hold = -score_std * 0.4

    if total_score > th_buy:
        if regime == "Sideways Bias Turun ↘️":
            signal = "⏸️ HOLD / WAIT (Sideways Downtrend — Low WR Regime)"
            total_score = th_hold + 0.01
        elif is_retail_trap:
            signal = "⏸️ HOLD / WAIT (Retail Trap Warning)"
            total_score = th_hold + 0.01
        elif is_marking_close or is_no_demand:
            signal = "⏸️ HOLD / WAIT (Fake Breakout / Marking Close)"
            total_score = th_hold + 0.01
        elif not is_mtf_bullish:
            if total_score > th_strong:
                signal = "⚡ BUY (TACTICAL) [Counter-Trend]"
            else:
                signal = "⏸️ HOLD / WAIT (Counter-Trend Risk)"
                total_score = th_hold + 0.01
        elif total_score > th_strong:
            signal = "🔥 STRONG BUY"
        else:
            signal = "⚡ BUY (TACTICAL)"
    elif total_score > th_hold:
        signal = "⏸️ HOLD / WAIT"
        if is_stopping_volume:
            signal += " 🟢 (Potential Reversal — Absorption Terdeteksi)"
    else:
        signal = "🚨 AVOID"
        if is_stopping_volume:
            signal += " 🟢 (Watchlist — Absorption Terdeteksi)"

    _cat_info = _parse_signal_category(signal, regime)
    _cat = _cat_info.category
    _ra = get_regime_signal_accuracy(ticker_raw, regime, _cat)

    if _ra['confidence'] >= 0.5:
        if _cat in ('AVOID_BEARISH', 'AVOID_UNCLEAR'):
            if _ra['accuracy'] < 0.40:
                signal = "⏸️ HOLD / WAIT (AVOID low-accuracy in this regime)"
                total_score = th_hold + 0.01
        elif _cat in ('BUY', 'STRONG_BUY'):
            if _ra['accuracy'] < 0.35:
                if total_score < th_strong * 1.3:
                    signal = "⏸️ HOLD / WAIT (BUY low-accuracy in this regime)"
                    total_score = th_hold + 0.01

    return {
        "adaptive_w": adaptive_w,
        "coppock_val": coppock_val,
        "coppock_prev": coppock_prev,
        "factor_signals": factor_signals,
        "norm_signals": norm_signals,
        "total_score": total_score,
        "signal": signal,
        "th_strong": th_strong,
        "th_buy": th_buy,
        "th_hold": th_hold,
        "score_std": score_std,
    }
