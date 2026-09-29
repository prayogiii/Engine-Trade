"""
Scoring & adaptive weight computation — pure functions, no Streamlit.

Semua fungsi di sini murni matematika: input dict → output dict, tanpa I/O.
Wrapper yang menyentuh st.session_state ada di services/.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from config.settings import (
    FACTOR_KEYS, WEIGHT_MIN, WEIGHT_MAX, SOFTMAX_TEMP,
)


# ═══════════════════════════════════════════════════════════════
# DEFAULT WEIGHTS
# ═══════════════════════════════════════════════════════════════
_REGIME_DEFAULTS = {
    "STABLE BULLISH": {"Momentum": 0.25, "AI_Senti": 0.18, "MeanRev": 0.12, "Beta_IHSG": 0.15, "Coppock": 0.30, "OFI": 0.12, "Bandar_Flow": 0.20, "Foreign_ZScore": 0.15},
    "VOLATILE UPTREND": {"Momentum": 0.28, "AI_Senti": 0.14, "MeanRev": 0.12, "Beta_IHSG": 0.16, "Coppock": 0.30, "OFI": 0.10, "Bandar_Flow": 0.18, "Foreign_ZScore": 0.10},
    "HIGH-STRESS PANIC": {"Momentum": 0.15, "AI_Senti": 0.18, "MeanRev": 0.22, "Beta_IHSG": 0.15, "Coppock": 0.30, "OFI": 0.18, "Bandar_Flow": 0.22, "Foreign_ZScore": 0.15},
    "SIDEWAYS / CONSOLIDATION": {"Momentum": 0.15, "AI_Senti": 0.18, "MeanRev": 0.27, "Beta_IHSG": 0.12, "Coppock": 0.28, "OFI": 0.14, "Bandar_Flow": 0.20, "Foreign_ZScore": 0.12},
    "BEARISH ACCUMULATION": {"Momentum": 0.20, "AI_Senti": 0.18, "MeanRev": 0.20, "Beta_IHSG": 0.15, "Coppock": 0.27, "OFI": 0.13, "Bandar_Flow": 0.25, "Foreign_ZScore": 0.15},
}
_FALLBACK_DEFAULT = {
    "Momentum": 0.23, "AI_Senti": 0.17, "MeanRev": 0.15, "Beta_IHSG": 0.15,
    "Coppock": 0.30, "OFI": 0.10, "Bandar_Flow": 0.15, "Foreign_ZScore": 0.10,
}


def default_weight(factor: str, regime: str) -> float:
    """Default weight untuk factor dalam regime tertentu."""
    return _REGIME_DEFAULTS.get(regime, _FALLBACK_DEFAULT).get(factor, 0.15)


# ═══════════════════════════════════════════════════════════════
# ADAPTIVE WEIGHTS
# ═══════════════════════════════════════════════════════════════
def get_adaptive_weights(ticker, regime, v12_mem=None):
    """Hitung adaptive weights dari historical accuracy + error EMA."""
    mem = (v12_mem or {}).get(ticker, {})
    defs = {k: default_weight(k, regime) for k in FACTOR_KEYS}

    w_pri = {}
    for k in FACTOR_KEYS:
        w = mem.get("weights", {}).get(k, defs[k])
        acc = mem.get("accuracy", {}).get(k, 0.5)
        if acc >= 0.65:
            w = min(w * 1.15, WEIGHT_MAX)
        elif acc >= 0.45:
            pass
        elif acc >= 0.35:
            w *= 0.5
        else:
            w = max(w * 0.2, WEIGHT_MIN / 2)
        w_pri[k] = max(WEIGHT_MIN, min(WEIGHT_MAX, w))

    err = {k: mem.get("error_ema", {}).get(k, 1.0) for k in FACTOR_KEYS}
    scores = {k: 1.0 / (max(err[k], 1e-3) + 1e-6) for k in FACTOR_KEYS}

    max_score = max(scores.values()) if scores else 1.0
    exp_s = {k: math.exp((v - max_score) / SOFTMAX_TEMP) for k, v in scores.items()}
    sum_exp = sum(exp_s.values()) if sum(exp_s.values()) > 0 else 1.0
    sm = {k: v / sum_exp for k, v in exp_s.items()}

    final = {}
    for k in FACTOR_KEYS:
        bw = w_pri[k]
        sw = max(0.10, sm[k])
        final[k] = max(WEIGHT_MIN, min(WEIGHT_MAX, 0.6 * bw + 0.4 * bw * sw * len(FACTOR_KEYS)))

    tot = sum(final.values())
    return {k: v / tot for k, v in final.items()}


# ═══════════════════════════════════════════════════════════════
# V12 SCORE SERIES
# ═══════════════════════════════════════════════════════════════
def compute_v12_score_series(
    dataframe, adaptive_w, mom_th, avg_sent,
    use_live_factors=False,
    coppock_val=0.0, bandar_flow_val=0.0, foreign_zscore_val=0.0,
):
    """
    Hitung V12 score per baris.
    use_live_factors=True  → untuk skor terkini (semua 8 faktor)
    use_live_factors=False → untuk backtest (hanya 3 faktor bar-by-bar)
    """
    mom_std = max(0.1, dataframe["Mom5D"].std())
    s_mom = ((dataframe["Mom5D"] - mom_th) / mom_std).clip(-1, 1)
    s_mr = (-dataframe["ZScore"] / 3.0).clip(-1, 1)
    s_ofi = (
        (dataframe["OFI_Enhanced"] / 5.0).clip(-1, 1)
        if "OFI_Enhanced" in dataframe.columns
        else pd.Series(0.0, index=dataframe.index)
    )

    if use_live_factors:
        s_sent = float(np.clip(avg_sent, -1, 1))
        s_copp = float(np.clip(coppock_val / 10.0, -1, 1))
        s_bandar = bandar_flow_val
        s_foreign = foreign_zscore_val
        w_norm = 1.0
    else:
        s_sent = s_copp = s_bandar = s_foreign = 0.0
        w_active = (
            adaptive_w.get("Momentum", 0.23) +
            adaptive_w.get("MeanRev", 0.15) +
            adaptive_w.get("OFI", 0.12)
        )
        w_norm = 1.0 / w_active if w_active > 0 else 1.0

    score = (
        s_mom * adaptive_w.get("Momentum", 0.23) +
        s_mr * adaptive_w.get("MeanRev", 0.15) +
        s_ofi * adaptive_w.get("OFI", 0.12) +
        s_sent * adaptive_w.get("AI_Senti", 0.17) +
        s_copp * adaptive_w.get("Coppock", 0.18) +
        s_bandar * adaptive_w.get("Bandar_Flow", 0.15) +
        s_foreign * adaptive_w.get("Foreign_ZScore", 0.10)
    ) * w_norm
    return score


def classify_v12_signal(score, th_strong, th_buy, th_hold):
    """Klasifikasi signal dari V12 score & threshold."""
    if score > th_strong:
        return "🔥 STRONG BUY"
    if score > th_buy:
        return "⚡ BUY (TACTICAL)"
    if score > th_hold:
        return "⏸️ HOLD / WAIT"
    return "🚨 AVOID"


def compute_score_std(historical_scores, fallback=0.15):
    """Std score dengan clamp reasonable range."""
    if len(historical_scores) > 5:
        std = float(np.std(historical_scores))
    else:
        std = fallback
    return max(0.10, min(0.35, std))


# ═══════════════════════════════════════════════════════════════
# MEMORY UPDATE MATH (PURE)
# ═══════════════════════════════════════════════════════════════
def compute_memory_update_math(mem, factor_signals, actual_return, volatility=0.02):
    """
    Hitung update memory (accuracy, error_ema, weights) — PURE.
    Return new mem dict. Tidak sentuh session_state / Sheets.
    """
    if abs(actual_return) < 0.003:
        return mem

    mem = dict(mem)
    mem.setdefault("weights", {})
    mem.setdefault("accuracy", {})
    mem.setdefault("error_ema", {})

    alpha = max(0.08, 0.20 if volatility > 0.04 else (0.15 if volatility > 0.02 else 0.10))
    ac = max(-1.0, min(1.0, actual_return))

    for k in FACTOR_KEYS:
        sv = max(-1.0, min(1.0, factor_signals.get(k, 0.0)))
        err = abs(sv - ac)
        old = mem["error_ema"].get(k, 1.0)
        mem["error_ema"][k] = old * (1 - alpha) + err * alpha

    alpha_acc = 0.20 if volatility > 0.04 else (0.12 if volatility > 0.02 else 0.06)
    for k in FACTOR_KEYS:
        hit = 1.0 if factor_signals.get(k, 0.0) * actual_return > 0 else 0.0
        old_acc = mem["accuracy"].get(k, 0.5)
        mem["accuracy"][k] = old_acc * (1 - alpha_acc) + hit * alpha_acc

    for k in FACTOR_KEYS:
        acc = mem["accuracy"][k]
        old_w = mem["weights"].get(k, default_weight(k, "SIDEWAYS"))
        if acc >= 0.55:
            drift = min(0.25, (acc - 0.5) * 0.5)
            new_w = min(old_w * (1 + drift), WEIGHT_MAX)
        elif acc <= 0.45:
            drift = min(0.25, (0.5 - acc) * 0.5)
            new_w = max(old_w * (1 - drift), WEIGHT_MIN)
        else:
            new_w = old_w
        mem["weights"][k] = new_w

    total_updates = mem.get("total_updates", 0) + 1
    mem["total_updates"] = total_updates
    if total_updates % 100 == 0:
        for k in FACTOR_KEYS:
            dw = default_weight(k, "SIDEWAYS")
            mem["weights"][k] = mem["weights"][k] * 0.85 + dw * 0.15
    return mem


def compute_entry_error_update(old_entry_error, gap, alpha=0.2):
    """Update entry_error_ema saat terjadi Not Touched."""
    return old_entry_error * (1 - alpha) + gap * alpha