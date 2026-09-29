"""
Analyze stock — orchestrator utama analisis (swing + daytrade).

Sudah delegasi ke:
  - services/analysis_pipeline.py    (Section 1-3: data + indicators)
  - services/analysis_context.py     (Section 4-5: fundamental + bandar + news)
  - services/analysis_engine.py      (Section 6-11: threshold + regime + signal)
  - core/backtest.py                 (Section 14: backtest)
"""
from __future__ import annotations

import math
from datetime import datetime

import numpy as np
import pandas as pd
import pytz
import streamlit as st
from scipy.stats import skew, kurtosis, t as student_t

from config.settings import FACTOR_KEYS
from core.indicators import (
    fraksi_bei, fraksi_step, coppock_curve, hitung_bars_remaining,
    estimate_theta_ou,
)
from core.montecarlo import determine_mc_regime, simulate_paths, summarize_paths
from core.regime import get_regime_row
from core.scoring import (
    get_adaptive_weights,
    compute_v12_score_series, classify_v12_signal,
)
from core.backtest import run_v12_backtest
from core.signal import parse_signal_category as _parse_signal_category
from services.analysis_pipeline import prepare_analysis_data
from services.analysis_context import (
    load_fundamental, load_bandar_and_foreign, load_news_and_sentiment,
)
from services.analysis_engine import (
    compute_thresholds, compute_regime_and_beta, compute_atr_rsi,
    compute_pivots, compute_v12_signal,
)
from services.sheets_client import get_regime_signal_accuracy


def analyze_stock(ticker_input, harga_manual, harga_terakhir_manual,
                  sudah_beli, harga_beli_float,
                  is_daytrade, v12_mem=None, fee_beli_pct=0.15, fee_jual_pct=0.25):
    """
    Menjalankan analisis lengkap untuk satu mode (swing/daytrade).
    Mengembalikan dictionary hasil atau None jika data tidak cukup.
    """
    # 1-3. LOAD DATA + PREPARE CONTEXT — delegate ke services.analysis_pipeline
    ctx = prepare_analysis_data(
        ticker_input, harga_manual, harga_terakhir_manual,
        sudah_beli, harga_beli_float, is_daytrade,
    )
    if ctx is None:
        return None

    df = ctx["df"]
    df_ihsg = ctx["df_ihsg"]
    df_daily = ctx["df_daily"]
    actual_interval = ctx["actual_interval"]
    bars_per_day_map = ctx["bars_per_day_map"]
    harga_terakhir_asli = ctx["harga_terakhir_asli"]
    harga_terakhir = ctx["harga_terakhir"]
    floating_pl_pct = ctx["floating_pl_pct"]
    returns = ctx["returns"]
    is_mtf_bullish = ctx["is_mtf_bullish"]
    mtf_status_text = ctx["mtf_status_text"]
    is_marking_close = ctx["is_marking_close"]
    is_no_demand = ctx["is_no_demand"]
    is_stopping_volume = ctx["is_stopping_volume"]
    vsa_status_text = ctx["vsa_status_text"]
    vwap_now = ctx["vwap_now"]
    vwap_bias = ctx["vwap_bias"]

    # 4. FUNDAMENTAL — delegate ke services.analysis_context
    _fund = load_fundamental(ticker_input)
    ticker_info = _fund["ticker_info"]
    mc = _fund["mc"]
    per = _fund["per"]
    pbv = _fund["pbv"]
    roe = _fund["roe"]
    de = _fund["de"]

    # 4.5. BANDARMOLOGY + FOREIGN FLOW
    ticker_raw = ticker_input.replace('.JK', '')
    _bandar = load_bandar_and_foreign(ticker_raw)
    bandar_flow_val = _bandar["bandar_flow_val"]
    foreign_zscore_val = _bandar["foreign_zscore_val"]
    is_retail_trap = _bandar["is_retail_trap"]
    bandar_metadata = _bandar["bandar_metadata"]

    # 5. BERITA & SENTIMEN
    _news = load_news_and_sentiment(ticker_raw, ticker_info)
    avg_sentiment = _news["avg_sentiment"]
    sentimen_status = _news["sentimen_status"]
    headlines = _news["headlines"]
    sources = _news["sources"]
    translated = _news["translated"]

    # 6. THRESHOLD & DISTRIBUSI
    _th = compute_thresholds(df, is_daytrade)
    df_thresh = _th["df_thresh"]
    returns_thresh = _th["returns_thresh"]
    adx_threshold = _th["adx_threshold"]
    z_oversold_th = _th["z_oversold_th"]
    mom_median_th = _th["mom_median_th"]
    df_est = _th["df_est"]
    backtest_window = _th["backtest_window"]

    # 7-8. REGIME + BETA
    _rb = compute_regime_and_beta(df, df_ihsg, returns, adx_threshold, mom_median_th)
    regime = _rb["regime"]
    ihsg_cond = _rb["ihsg_cond"]
    adx = _rb["adx"]
    beta_ihsg = _rb["beta_ihsg"]
    ihsg_ret = _rb["ihsg_ret"]

    # 9. ATR & RSI
    _atr = compute_atr_rsi(df, harga_terakhir_asli, is_daytrade, actual_interval, bars_per_day_map)
    df = _atr["df"]
    atr14_val = _atr["atr14_val"]
    atr_pct = _atr["atr_pct"]
    rsi14 = _atr["rsi14"]
    bars_remaining = _atr["bars_remaining"]

    # 10. PIVOT
    piv = compute_pivots(df, df_daily, is_daytrade)
    pp = piv["pp"]
    r1 = piv["r1"]
    r2 = piv["r2"]
    s1 = piv["s1"]
    s2 = piv["s2"]

    # 11. V12 SIGNAL
    _v12 = compute_v12_signal(
        df, ticker_raw, regime, mom_median_th,
        avg_sentiment, beta_ihsg, ihsg_ret,
        bandar_flow_val, foreign_zscore_val,
        is_retail_trap, is_marking_close, is_no_demand,
        is_mtf_bullish, is_stopping_volume,
        v12_mem=v12_mem,
    )
    adaptive_w = _v12["adaptive_w"]
    coppock_val = _v12["coppock_val"]
    coppock_prev = _v12["coppock_prev"]
    factor_signals = _v12["factor_signals"]
    norm_signals = _v12["norm_signals"]
    total_score = _v12["total_score"]
    signal = _v12["signal"]
    th_strong = _v12["th_strong"]
    th_buy = _v12["th_buy"]
    th_hold = _v12["th_hold"]
    score_std = _v12["score_std"]
    # 12. ENTRY ZONE (v2 — anti-NT, more accommodating)
    if s1 >= harga_terakhir * 0.98:
        entry_low = s1
    else:
        entry_low = harga_terakhir * (1 - atr_pct / 100)

    if "STRONG BUY" in signal or "BUY" in signal:
        gap_catch_bonus = min(0.5 * atr_pct / 100, 0.015) 
        entry_high = harga_terakhir * (1 + gap_catch_bonus)
    else:
        entry_high = harga_terakhir * (1 - 0.15 * atr_pct / 100)

    if entry_low > entry_high:
        entry_low, entry_high = entry_high, entry_low
    min_entry_width = 0.6 * atr14_val
    if (entry_high - entry_low) < min_entry_width:
        entry_low = max(0, entry_high - min_entry_width)
        entry_high = entry_low + min_entry_width
    if v12_mem is not None:
        mem_for_entry = v12_mem.get(ticker_raw, {})
    else:
        mem_for_entry = st.session_state.v12_memory.get(ticker_raw, {})
    entry_error = mem_for_entry.get('entry_error_ema', 0.0)

    if entry_error > 0:
        max_shift = harga_terakhir * 0.015   
        shift = min(entry_error * 0.15, max_shift)   
        entry_low += shift
        entry_high += shift
    if (entry_low is None) or (isinstance(entry_low, float) and math.isnan(entry_low)) or entry_low <= 0:
        entry_low = harga_terakhir * 0.98 if harga_terakhir > 0 else 1
    if (entry_high is None) or (isinstance(entry_high, float) and math.isnan(entry_high)) or entry_high <= 0:
        entry_high = harga_terakhir if harga_terakhir > 0 else 1
    if entry_low > entry_high:
        entry_low, entry_high = entry_high, entry_low
    entry_low_f = fraksi_bei(entry_low)
    entry_high_f = fraksi_bei(entry_high)
    entry_zone_f = f"Rp {entry_low_f:,.0f} - Rp {entry_high_f:,.0f}"

    # 13. SL & TP
    sl_mult = 1.0
    if adx > 30 and 30 < rsi14 < 70:
        sl_mult = 0.75
    elif adx < 20:
        sl_mult = 1.25
    if rsi14 > 70 or rsi14 < 30:
        sl_mult = 1.5

    tp_mult_low = 1.5
    tp_mult_high = 2.5
    if adx > 30 and 30 < rsi14 < 70:
        tp_mult_low, tp_mult_high = 2.0, 3.0
    elif adx < 20:
        tp_mult_low, tp_mult_high = 1.2, 1.8

    if is_daytrade:
        base_sl_dist = harga_terakhir * 0.04 * sl_mult
        min_ticks_dist = 2 * fraksi_step(entry_low)
        sl_dist = max(min_ticks_dist, base_sl_dist)
        sl_harga = entry_low - sl_dist
    else:
        sl_harga = entry_low - sl_mult * atr14_val

    sl_harga = fraksi_bei(sl_harga)
    step = fraksi_step(entry_low)
    if sl_harga >= entry_low:
        sl_harga = fraksi_bei(entry_low - 2 * step)
    if sl_harga <= 0:
        sl_harga = fraksi_bei(harga_terakhir * 0.95)
    sl_pct = (harga_terakhir - sl_harga) / harga_terakhir * 100

    if is_daytrade:
        # --- PERHITUNGAN TP DAYTRADE BERBASIS ATR INTRADAY & FAKTOR FEE BROKER ---
        # 1. Target ATR Intraday (5m)
        tp_low_raw = entry_low + (tp_mult_low * atr14_val)
        tp_high_raw = entry_low + (tp_mult_high * atr14_val)

        # 2. Safety Floor untuk Memastikan Cover Fee Broker (Beli + Jual) + Target Net Profit Margin (+0.6% net)
        total_fee_pct = (fee_beli_pct + fee_jual_pct) / 100.0
        min_net_margin = 0.0060
        fee_floor = entry_low * (1.0 + total_fee_pct + min_net_margin)

        # Gunakan nilai terbesar antara ATR Intraday & Fee Floor
        tp_low_raw = max(tp_low_raw, fee_floor)
        tp_high_raw = max(tp_high_raw, tp_low_raw + (2 * fraksi_step(tp_low_raw)))

        # 3. Pastikan minimal 2 tick di atas entry_low dan harga_terakhir agar komisi tercover penuh
        min_tp_low_ticks = max(entry_low + (2 * step), harga_terakhir + (2 * fraksi_step(harga_terakhir)))
        if tp_low_raw < min_tp_low_ticks:
            tp_low_raw = min_tp_low_ticks

        tp_low = fraksi_bei(tp_low_raw)
        tp_high = fraksi_bei(tp_high_raw)
        if tp_low <= entry_low:
            tp_low = fraksi_bei(entry_low + 2 * step)
        if tp_high <= tp_low:
            tp_high = fraksi_bei(tp_low + 2 * fraksi_step(tp_low))
    else:
        # --- PERHITUNGAN TP SWING (RESISTANCE HARIAN / PIVOT R1 R2) ---
        if r1 > harga_terakhir:
            tp_low = r1
        else:
            tp_low = harga_terakhir + tp_mult_low * atr14_val
        if r2 > harga_terakhir:
            tp_high = r2
        else:
            tp_high = harga_terakhir + tp_mult_high * atr14_val
        if tp_low > tp_high:
            tp_low, tp_high = tp_high, tp_low

    tp_pct_low = (tp_low - harga_terakhir) / harga_terakhir * 100
    tp_pct_high = (tp_high - harga_terakhir) / harga_terakhir * 100

    risk = harga_terakhir - sl_harga
    reward = tp_low - harga_terakhir
    rrr = reward / risk if risk > 0 else 0
    if rrr >= 2.0:
        rrr_status = "Sangat Baik (≥ 2.0) 🟢"
    elif rrr >= 1.5:
        rrr_status = "Baik (1.5 - 2.0) 🟢"
    elif rrr >= 1.0:
        rrr_status = "Cukup (1.0 - 1.5) 🟡"
    else:
        rrr_status = "Buruk (< 1.0) 🔴"

    # Dynamic Dip Target untuk RRR Ideal 1:2.0
    if tp_low > sl_harga:
        entry_ideal_raw = (tp_low + 2 * sl_harga) / 3.0
        entry_ideal_f = fraksi_bei(entry_ideal_raw)
        entry_ideal_f = min(entry_ideal_f, harga_terakhir)
        entry_ideal_f = max(entry_ideal_f, fraksi_bei(sl_harga + 2 * fraksi_step(sl_harga)))
    else:
        entry_ideal_f = fraksi_bei(entry_low)

    # Breakout
    if is_daytrade:
        bars_per_day = bars_per_day_map.get(actual_interval, 54)
        if len(df) >= bars_per_day:
            res20 = float(df['High'].iloc[-bars_per_day:-1].max())
            breakout_label = f"Breakout Sesi Sebelumnya ({bars_per_day} bar)"
        else:
            res20 = float(df['High'].max())
            breakout_label = "Breakout N-Bar"
    else:
        if len(df) >= 21:
            res20 = float(df['High'].iloc[-21:-1].max())
        else:
            res20 = float(df['High'].max())
        breakout_label = "Breakout 20 Hari"
    breakout = f"YES (🔥)" if harga_terakhir > res20 else "NO"

    # 14. BACKTEST — delegate ke core.backtest
    if is_daytrade:
        _bars_per_day = bars_per_day_map.get(actual_interval, 54)
        _annual_factor = float(np.sqrt(_bars_per_day * 252))
    else:
        _annual_factor = float(np.sqrt(252))

    _bt = run_v12_backtest(
        df=df,
        backtest_window=backtest_window,
        adaptive_w=adaptive_w,
        mom_median_th=mom_median_th,
        avg_sentiment=avg_sentiment,
        coppock_val=coppock_val,
        bandar_flow_val=bandar_flow_val,
        foreign_zscore_val=foreign_zscore_val,
        fee_beli_pct=fee_beli_pct,
        fee_jual_pct=fee_jual_pct,
        annual_factor=_annual_factor,
    )

    df = _bt["df"]
    df_back = _bt["df_back"]
    bt_th_strong = _bt["bt_th_strong"]
    bt_th_buy = _bt["bt_th_buy"]
    bt_th_hold = _bt["bt_th_hold"]
    win_bt = _bt["win_bt"]
    pf_bt = _bt["pf_bt"]
    avg_bt = _bt["avg_bt"]
    max_dd_bt = _bt["max_dd_bt"]
    sharpe_bt = _bt["sharpe_bt"]
    trades_bt = _bt["trades_bt"]
    profit_trades = _bt["profit_trades"]
    loss_trades = _bt["loss_trades"]

    # 15. KELLY & DRAWDOWN
    roll_max_th = df_thresh['Close'].cummax()
    drawdown_th = (df_thresh['Close'] - roll_max_th) / roll_max_th
    max_dd = float(drawdown_th.min() * 100)
    max_dd_30 = float(drawdown_th.tail(30).min() * 100) if len(drawdown_th) >= 30 else max_dd

    if trades_bt >= 2:
        win_r = win_bt
        avg_g = np.mean(profit_trades) if profit_trades else 0.01
        avg_l = abs(np.mean(loss_trades)) if loss_trades else 0.01
    else:
        win_r = len(returns_thresh[returns_thresh > 0]) / len(returns_thresh)
        avg_g = returns_thresh[returns_thresh > 0].mean() if win_r > 0 else 0.01
        avg_l = abs(returns_thresh[returns_thresh < 0].mean()) if len(returns_thresh[returns_thresh < 0]) else 0.01

    wl = avg_g / avg_l if avg_l else 1
    kelly_raw = win_r - (1 - win_r) / wl
    ret_skew = float(skew(returns_thresh))
    ret_kurt = float(kurtosis(returns_thresh, fisher=True))
    kurt_penalty = 0.5 if ret_kurt > 3 else 1.0
    kelly_adj = min(0.25, max(0.0, kelly_raw * 0.3 * (0.5 if ret_skew < -0.5 else 1) * kurt_penalty))
    target_risk_pct = 1.5
    risk_adjusted_alloc = min(kelly_adj * 100, (target_risk_pct / sl_pct) * 100) if sl_pct > 0 else kelly_adj * 100

    # 16. MONTE CARLO — Regime-Switching (GBM untuk trending, OU untuk sideways)
    # Problem lama: OU murni memaksa proyeksi kembali ke mean 20 hari untuk
    # SEMUA kondisi, termasuk saham yang baru saja breakout ATH / super-trend.
    # Akibatnya prob_bull dan estimasi harga besok terlalu pesimistis.
    # Solusi:
    #  • BULLISH / STRONG BUY / Breakout  → GBM drift positif (momentum-based)
    #  • BEARISH / PANIC / AVOID          → GBM drift negatif
    #  • SIDEWAYS / CONSOLIDATION / HOLD  → OU mean-reverting (seperti sebelumnya)
    if is_daytrade:
        n_sim   = 2000
        n_steps = max(1, bars_remaining)
    else:
        n_sim   = 2000
        n_steps = 30

    latest_vol = np.sqrt(df['Close'].pct_change().ewm(alpha=0.06).var().iloc[-1])
    scale_corrected = latest_vol / np.sqrt(df_est / (df_est - 2)) if df_est > 2 else latest_vol

    # ── Deteksi regime Monte Carlo ──
    _trending_up_regimes   = {"STABLE BULLISH", "VOLATILE UPTREND"}
    _trending_down_regimes = {"HIGH-STRESS PANIC"}
    _sideways_regimes      = {"SIDEWAYS / CONSOLIDATION", "BEARISH ACCUMULATION"}

    _is_mc_bullish = (
        regime in _trending_up_regimes or
        "STRONG BUY" in signal or
        (breakout == "YES (🔥)" and "BUY" in signal)
    )
    _is_mc_bearish = (
        regime in _trending_down_regimes or
        "AVOID" in signal
    )
    # Default: sideways / mean-reverting

    paths       = np.zeros((n_steps, n_sim))
    current_log = np.ones(n_sim) * np.log(harga_terakhir)

    if _is_mc_bullish:
        # ── GBM Bullish: drift berbasis momentum 5D harian (annualized → per-step) ──
        mom5d_raw  = df['Mom5D'].iloc[-1] if 'Mom5D' in df.columns else 0.0
        # Konversi: Mom5D adalah pct change 5D, bagi 5 → per-hari, lalu clamp +0.1%~+1%
        drift_daily = float(np.clip(mom5d_raw / 500.0, 0.0005, 0.005)) * 0.6
        mc_regime_label = "GBM Bullish 🚀"
        for step in range(n_steps):
            inov        = student_t.rvs(df_est, loc=0, scale=scale_corrected, size=n_sim)
            current_log = current_log + drift_daily + inov
            paths[step] = np.exp(current_log)

    elif _is_mc_bearish:
        # ── GBM Bearish: drift negatif berbasis momentum ──
        mom5d_raw   = df['Mom5D'].iloc[-1] if 'Mom5D' in df.columns else 0.0
        drift_daily = float(np.clip(mom5d_raw / 500.0, -0.010, -0.001))
        mc_regime_label = "GBM Bearish 🔻"
        for step in range(n_steps):
            inov        = student_t.rvs(df_est, loc=0, scale=scale_corrected, size=n_sim)
            current_log = current_log + drift_daily + inov
            paths[step] = np.exp(current_log)

    else:
        # ── OU Mean-Reverting: untuk sideways / konsolidasi ──
        theta_ou           = estimate_theta_ou(df['Close'])
        locked_log_mean20  = np.log(df['Close']).tail(20).mean()
        mc_regime_label    = "OU Mean-Reverting ↔️"
        for step in range(n_steps):
            inov        = student_t.rvs(df_est, loc=0, scale=scale_corrected, size=n_sim)
            current_log = current_log + theta_ou * (locked_log_mean20 - current_log) + inov
            paths[step] = np.exp(current_log)

    if is_daytrade:
        # ═══ DT: horizon tunggal = sisa sesi ini ═══
        final_prices = paths[-1, :]
        est_besok        = float(np.median(final_prices))
        low_est          = float(np.percentile(final_prices, 25))
        up_est           = float(np.percentile(final_prices, 75))
        prob_bull        = (final_prices > harga_terakhir).mean() * 100
        if "STRONG BUY" in signal:
            est_besok_sinyal = float(np.percentile(final_prices, 75))
        elif "BUY" in signal:
            est_besok_sinyal = float(np.percentile(final_prices, 65))
        elif "HOLD" in signal:
            est_besok_sinyal = float(np.percentile(final_prices, 50))
        else:
            est_besok_sinyal = float(np.percentile(final_prices, 35))

        # Alias supaya konsisten (DT tidak punya horizon 30d)
        est_30d          = est_besok
        low_est_30d      = low_est
        up_est_30d       = up_est
        prob_bull_30d    = prob_bull
        est_30d_sinyal   = est_besok_sinyal

        estimasi_label     = "Estimasi Sesi Berikutnya"
        prob_label         = "Prob Naik Sesi Berikutnya"
        estimasi_30d_label = None        # DT: tidak ada outlook 30d
        prob_30d_label     = None

    else:
        # ═══ SWING: DUAL HORIZON (A + B) ═══
        # ── Horizon 1: BESOK (paths[0, :]) ──
        prices_besok = paths[0, :]
        est_besok        = float(np.median(prices_besok))
        low_est          = float(np.percentile(prices_besok, 25))
        up_est           = float(np.percentile(prices_besok, 75))
        prob_bull        = (prices_besok > harga_terakhir).mean() * 100
        if "STRONG BUY" in signal:
            est_besok_sinyal = float(np.percentile(prices_besok, 75))
        elif "BUY" in signal:
            est_besok_sinyal = float(np.percentile(prices_besok, 65))
        elif "HOLD" in signal:
            est_besok_sinyal = float(np.percentile(prices_besok, 50))
        else:
            est_besok_sinyal = float(np.percentile(prices_besok, 35))

        # ── Horizon 2: 30 HARI (paths[-1, :]) ──
        prices_30d = paths[-1, :]
        est_30d          = float(np.median(prices_30d))
        low_est_30d      = float(np.percentile(prices_30d, 25))
        up_est_30d       = float(np.percentile(prices_30d, 75))
        prob_bull_30d    = (prices_30d > harga_terakhir).mean() * 100
        if "STRONG BUY" in signal:
            est_30d_sinyal = float(np.percentile(prices_30d, 75))
        elif "BUY" in signal:
            est_30d_sinyal = float(np.percentile(prices_30d, 65))
        elif "HOLD" in signal:
            est_30d_sinyal = float(np.percentile(prices_30d, 50))
        else:
            est_30d_sinyal = float(np.percentile(prices_30d, 35))

        estimasi_label     = "Estimasi Besok"
        prob_label         = "Prob Naik Besok"
        estimasi_30d_label = "Outlook 30 Hari"
        prob_30d_label     = "Prob Naik 30 Hari"

    # hit_tp & hit_sl tetap pakai seluruh jalur (valid untuk kedua horizon)
    hit_tp = (np.any(paths >= r1, axis=0).sum() / n_sim) * 100
    hit_sl = (np.any(paths <= s2, axis=0).sum() / n_sim) * 100

    # 17. METRIK TAMBAHAN
    if "STRONG BUY" in signal:
        signal_score = 0.7 + (prob_bull / 200)
    elif "BUY" in signal:
        signal_score = 0.4 + (prob_bull / 200)
    elif "HOLD" in signal:
        signal_score = 0.2 + (prob_bull / 300)
    else:
        signal_score = max(0, (prob_bull - 30) / 100)
    signal_score = min(1.0, max(0.0, signal_score))
    confidence = min(0.99, 0.5 + (signal_score * 0.5) + (win_bt - 0.5) * 0.1)
    if confidence is None or np.isnan(confidence):
        confidence = 0.5

    trend_consistency = np.mean([
        1 if (df['Close'].iloc[-i] > df['Close'].iloc[-i-1]) == (df['EMA20'].iloc[-1] > df['EMA50'].iloc[-1]) else 0
        for i in range(1, 11)
    ]) * 100
    if np.isnan(trend_consistency):
        trend_consistency = 50.0

    avg_vol_5 = df['Volume'].iloc[-5:].mean()
    avg_vol_20 = df['Volume'].iloc[-20:].mean()
    if avg_vol_20 > 0:
        vol_surge_pct = ((avg_vol_5 / avg_vol_20) - 1) * 100
    else:
        vol_surge_pct = 0.0

    avg_value = (df['Volume'].iloc[-5:] * df['Close'].iloc[-5:]).mean()
    if np.isnan(avg_value):
        avg_value = 0.0
    if avg_value >= 1e9:
        likuiditas_str = f"Rp {avg_value/1e9:.2f} M"
    elif avg_value >= 1e6:
        likuiditas_str = f"Rp {avg_value/1e6:.0f} Jt"
    elif avg_value >= 1e3:
        likuiditas_str = f"Rp {avg_value/1e3:.0f} rb"
    else:
        likuiditas_str = f"Rp {avg_value:,.0f}"

    if rsi14 > 70:
        rsi_status = "Overbought"
    elif rsi14 < 30:
        rsi_status = "Oversold"
    else:
        rsi_status = "Normal"

    zscore_val = df['ZScore'].iloc[-1]
    if pd.isna(zscore_val):
        zscore_val = 0.0
    if zscore_val > 2:
        zs_status = "Overbought"
    elif zscore_val < -2:
        zs_status = "Oversold"
    else:
        zs_status = "Normal"

    if vol_surge_pct > 50:
        vs_status = "Tinggi"
    elif vol_surge_pct < -30:
        vs_status = "Rendah"
    else:
        vs_status = "Normal"

    coppock_rising = coppock_val > coppock_prev
    coppock_turning_up = coppock_rising and coppock_prev <= 0
    if coppock_turning_up:
        coppock_status = "Turning Up"
    elif coppock_rising:
        coppock_status = "Rising"
    else:
        coppock_status = "Falling"

    est_besok_f = fraksi_bei(est_besok)
    est_besok_sinyal_f = fraksi_bei(est_besok_sinyal)
    low_est_f = fraksi_bei(low_est)
    up_est_f = fraksi_bei(up_est)
    tp_low_f = fraksi_bei(tp_low)
    tp_high_f = fraksi_bei(tp_high)
    sl_harga_f = fraksi_bei(sl_harga)
    est_30d_f        = fraksi_bei(est_30d)
    est_30d_sinyal_f = fraksi_bei(est_30d_sinyal)
    low_est_30d_f    = fraksi_bei(low_est_30d)
    up_est_30d_f     = fraksi_bei(up_est_30d)

    # 18. RINGKASAN UNTUK RIWAYAT
    ringkasan = {
        "Waktu": datetime.now(pytz.timezone("Asia/Jakarta")).strftime("%Y-%m-%d %H:%M"),
        "Saham": ticker_raw,
        "Harga": f"{harga_terakhir:,.0f}",
        "Sinyal": signal,
        "Estimasi": f"{est_besok:,.0f}",
        "Estimasi_Netral": f"Rp {est_besok_f:,.0f}",
        "Estimasi_Sinyal": f"Rp {est_besok_sinyal_f:,.0f}",
        "Prob Naik": f"{prob_bull:.1f}%",
        "RRR": f"{rrr:.2f}",
        "Sentimen": f"{avg_sentiment:.2f} ({sentimen_status})",
        "Rezim": regime,
        "TP%": f"{tp_pct_low:.1f}% - {tp_pct_high:.1f}%",
        "SL%": f"{sl_pct:.1f}%",
        "AI_Insight": "",
        "Score": f"{signal_score:.3f}",
        "Confidence": f"{confidence:.0%}",
        "Coppock": coppock_status,
        "Est_Return": f"{((est_besok - harga_terakhir) / harga_terakhir * 100):+.2f}%",
        "Est_Return_Sinyal": f"{((est_besok_sinyal - harga_terakhir) / harga_terakhir * 100):+.2f}%",
        "TP_Harga": f"{tp_low_f:,.0f} - {tp_high_f:,.0f}",
        "TP_Range": f"Rp {tp_low_f:,.0f} - Rp {tp_high_f:,.0f}",
        "SL_Harga": f"{sl_harga_f:,.0f}",
        "Likuiditas": likuiditas_str,
        "RSI": f"{rsi14:.1f}",
        "RSI_Status": rsi_status,
        "Vol_Surge": f"{vol_surge_pct:+.0f}%",
        "VS_Status": vs_status,
        "ZScore": f"{zscore_val:.2f}",
        "ZS_Status": zs_status,
        "Trend_Consistency": f"{trend_consistency:.0f}%",
        "Beta": f"{beta_ihsg:.2f}",
        "Momentum": f"{df['Mom5D'].iloc[-1]:.2f}%",
        "Entry_Zone": entry_zone_f,
        "Entry_Ideal_RRR2": f"Rp {entry_ideal_f:,.0f}",
        "Risk_Adjusted_Alloc": f"{risk_adjusted_alloc:.1f}%",
        "Gaya": "DT" if is_daytrade else "SW",
        "Status_Posisi": "Sudah Beli" if sudah_beli else "Belum",
        "Harga_Beli": f"{harga_beli_float:,.0f}" if harga_beli_float else "",
        "Floating_PL": f"{floating_pl_pct:+.2f}%" if floating_pl_pct is not None else ""
    }

    # 19. KUMPULKAN RESULT
    result = {
        "df": df,
        "df_back": df_back,
        "harga_terakhir": harga_terakhir,
        "signal": signal,
        "entry_zone_f": entry_zone_f,
        "entry_ideal_f": entry_ideal_f,
        "risk_adjusted_alloc": risk_adjusted_alloc,
        "sl_harga_f": sl_harga_f,

        "tp_low_f": tp_low_f,
        "tp_high_f": tp_high_f,
        "rrr": rrr,
        "rrr_status": rrr_status,
        "prob_bull": prob_bull,
        "signal_score": signal_score,
        "confidence": confidence,
        "est_besok_f": est_besok_f,
        "est_besok_sinyal_f": est_besok_sinyal_f,
        "low_est_f": low_est_f,
        "up_est_f": up_est_f,
        "tp_pct_low": tp_pct_low,
        "tp_pct_high": tp_pct_high,
        "sl_pct": sl_pct,
        "adx": adx,
        "rsi14": rsi14,
        "atr_pct": atr_pct,
        "avg_sentiment": avg_sentiment,
        "sentimen_status": sentimen_status,
        "headlines": headlines,
        "sources": sources,
        "translated": translated,
        "regime": regime,
        "ihsg_cond": ihsg_cond,
        "coppock_val": coppock_val,
        "coppock_prev": coppock_prev,
        "coppock_turning_up": coppock_turning_up,
        "beta_ihsg": beta_ihsg,
        "win_bt": win_bt,
        "pf_bt": pf_bt,
        "avg_bt": avg_bt,
        "max_dd_bt": max_dd_bt,
        "sharpe_bt": sharpe_bt,
        "trades_bt": trades_bt,
        "kelly_adj": kelly_adj,
        "max_dd": max_dd,
        "max_dd_30": max_dd_30,
        "breakout": breakout,
        "breakout_label": breakout_label,
        "vwap_now": vwap_now,
        "vwap_bias": vwap_bias,
        "r1": r1, "r2": r2, "s1": s1, "s2": s2, "pp": pp,
        "mc": mc, "per": per, "pbv": pbv, "roe": roe, "de": de,
        "norm_signals": norm_signals,   # untuk simpan prediksi
        "ringkasan": ringkasan,
        "is_daytrade": is_daytrade,
        "mode": "daytrade" if is_daytrade else "swing",
        "actual_interval": actual_interval,
        "harga_terakhir_asli": harga_terakhir_asli,
        "floating_pl_pct": floating_pl_pct,
        "harga_beli_float": harga_beli_float,
        "sudah_beli": sudah_beli,
        "ticker_raw": ticker_raw,
        "bandar_flow_val": bandar_flow_val,
        "foreign_zscore_val": foreign_zscore_val,
        "is_retail_trap": is_retail_trap,
        "bandar_metadata": bandar_metadata,
        "is_mtf_bullish": is_mtf_bullish,
        "mtf_status_text": mtf_status_text,
        "is_marking_close": is_marking_close,
        "is_no_demand": is_no_demand,
        "is_stopping_volume": is_stopping_volume,
        "vsa_status_text": vsa_status_text
    }
    # Tambahan untuk UI
    result["ticker_info"] = ticker_info
    result["adx_threshold"] = adx_threshold
    result["hit_tp"] = hit_tp
    result["hit_sl"] = hit_sl
    result["estimasi_label"] = estimasi_label
    result["prob_label"] = prob_label
    result["backtest_window"] = backtest_window
    result["ofi_now"] = df['OFI_Enhanced'].iloc[-1]  
    result["adaptive_w"] = adaptive_w
    result["mc_regime_label"] = mc_regime_label   
    result["returns"] = returns
    result["mom_median_th"] = mom_median_th
    result["coppock_rising"] = coppock_rising
    result["coppock_turning_up"] = coppock_turning_up
    result["coppock_status"] = coppock_status
    result["avg_sentiment"] = avg_sentiment
    result["norm_signals"] = norm_signals
    result["entry_low_f"] = entry_low_f
    result["entry_high_f"] = entry_high_f
    result["ticker_raw"] = ticker_raw
    result["harga_terakhir_asli"] = harga_terakhir_asli
    result["floating_pl_pct"] = floating_pl_pct
    result["sudah_beli"] = sudah_beli
    result["harga_beli_float"] = harga_beli_float
    result["df_est"] = df_est
    # ═══ FIX: Simpan versi fraksi-bei untuk UI ═══
    result["est_30d_f"]        = est_30d_f
    result["est_30d_sinyal_f"] = est_30d_sinyal_f
    result["low_est_30d_f"]    = low_est_30d_f
    result["up_est_30d_f"]     = up_est_30d_f
    result["est_30d"]          = est_30d
    result["est_30d_sinyal"]   = est_30d_sinyal
    result["low_est_30d"]      = low_est_30d
    result["up_est_30d"]       = up_est_30d
    result["prob_bull_30d"]    = prob_bull_30d
    result["estimasi_30d_label"] = estimasi_30d_label
    result["prob_30d_label"]     = prob_30d_label
    return result