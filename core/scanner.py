"""
Scanner saham IDX — technical scoring untuk screening.

Pure logic, tanpa Streamlit. Input: DataFrame + IHSG data → output dict score.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from core.indicators import (
    fraksi_bei, fraksi_step, coppock_curve, robust_std,
)
from core.entry_exit import compute_entry_zone_and_sl_tp


def score_stock_tech(df_stock, ticker, ihsg_data, v12_mem=None, max_price=10000):
    """Menghitung skor teknikal + metrik lengkap untuk scanner V12."""
    try:
        closes = df_stock['Close'].values
        highs = df_stock['High'].values
        lows = df_stock['Low'].values
        volumes = df_stock['Volume'].values
        last_price = float(closes[-1])
        if last_price <= 0:
            return None
        if last_price > max_price:
            return None
        ihsg_closes = ihsg_data['Close'].values
        if len(closes) < 65 or len(ihsg_closes) < 65:
            return None

        n = min(60, len(closes) - 1, len(ihsg_closes) - 1)
        s_adj = closes[-n-1:]
        i_adj = ihsg_closes[-n-1:]
        sT = len(s_adj) - 1
        iT = len(i_adj) - 1
        if sT < 20 or iT < 20:
            return None

        s_ret = np.diff(s_adj) / s_adj[:-1]
        i_ret = np.diff(i_adj) / i_adj[:-1]

        # Beta & IHSG return — blend 5D+20D agar tidak mati saat IHSG flat/sideways
        i_ret5 = (i_adj[iT] - i_adj[iT-5]) / i_adj[iT-5] if iT >= 5 else 0.0
        i_ret10 = (i_adj[iT] - i_adj[iT-10]) / i_adj[iT-10] if iT >= 10 else i_ret5
        i_ret20 = (i_adj[iT] - i_adj[iT-20]) / i_adj[iT-20] if iT >= 20 else i_ret5
        i_ret_blend = i_ret5 * 0.6 + i_ret20 * 0.4
        common_len = min(len(s_ret), len(i_ret))
        cov = np.cov(s_ret[:common_len], i_ret[:common_len])[0, 1]
        var_i = np.var(i_ret[:common_len])
        beta = (cov / var_i).clip(-3, 3) if var_i > 1e-8 else 1.0
        beta_norm = np.clip(beta * i_ret_blend / 0.05, -1, 1)

        # Relative Strength vs IHSG — inti dari market-aware scanner
        # Saham naik saat IHSG turun = SANGAT kuat → bonus besar
        # Saham turun saat IHSG naik = lemah → penalty
        # Saham naik bersama IHSG = netral (bisa karena market saja)
        s_ret5  = (s_adj[sT] - s_adj[sT-5])  / s_adj[sT-5]  if sT >= 5  else 0.0
        s_ret10 = (s_adj[sT] - s_adj[sT-10]) / s_adj[sT-10] if sT >= 10 else s_ret5
        rs5  = s_ret5  - i_ret5          # outperformance 5D vs IHSG
        rs10 = s_ret10 - i_ret10         # outperformance 10D vs IHSG
        rs_blend = rs5 * 0.65 + rs10 * 0.35
        # Normalisasi: ±3% outperformance = skor penuh ±1
        # Saat IHSG crash -4% dan saham +1% → rs=+5% → rs_norm=+1.0 (top candidat)
        # Saat IHSG crash -4% dan saham -4% → rs=0%  → rs_norm= 0.0 (netral)
        # Saat IHSG crash -4% dan saham -7% → rs=-3% → rs_norm=-1.0 (buang)
        rs_norm = float(np.clip(rs_blend / 0.03, -1, 1))

        # Label RS untuk ditampilkan di UI
        if rs_blend > 0.03:
            rs_label = "🔥 Outperform Kuat"
        elif rs_blend > 0.01:
            rs_label = "✅ Outperform"
        elif rs_blend > -0.01:
            rs_label = "➡️ Inline Market"
        elif rs_blend > -0.03:
            rs_label = "⚠️ Underperform"
        else:
            rs_label = "🔴 Underperform Kuat"

        # Momentum combo (3/5/10)
        mom3 = (s_adj[sT] - s_adj[sT-3]) / s_adj[sT-3] if sT >= 3 else 0.0
        mom5 = (s_adj[sT] - s_adj[sT-5]) / s_adj[sT-5] if sT >= 5 else 0.0
        mom10 = (s_adj[sT] - s_adj[sT-10]) / s_adj[sT-10] if sT >= 10 else 0.0
        mom_combo = mom3*0.50 + mom5*0.30 + mom10*0.20
        mom_norm = np.clip(mom_combo / 0.05, -1, 1)

        # Coppock Curve
        copp_std, copp_prev = coppock_curve(s_adj, 14, 11, 10)
        copp_fast, copp_fast_prev = coppock_curve(s_adj, 6, 4, 5)
        copp_rising = copp_std > copp_prev
        copp_fast_rising = copp_fast > copp_fast_prev
        is_turning_up = copp_rising and copp_prev <= 0.0
        is_turning_down = not copp_rising and copp_prev >= 0.0
        fast_align = 1.08 if (copp_fast_rising == copp_rising) else 0.92

        if is_turning_up:
            copp_dir_base = 1.0
        elif copp_std > 0 and copp_rising:
            copp_dir_base = 0.70
        elif copp_std <= 0 and copp_rising:
            copp_dir_base = 0.40
        elif is_turning_down:
            copp_dir_base = -1.0
        elif copp_std > 0 and not copp_rising:
            copp_dir_base = -0.30
        else:
            copp_dir_base = -0.70
        copp_norm = np.clip(copp_dir_base * fast_align, -1, 1)

        if is_turning_up:
            copp_label = "🔼 Turning Up"
        elif copp_std > 0 and copp_rising:
            copp_label = "↑ Rising+"
        elif copp_std <= 0 and copp_rising:
            copp_label = "↑ Recovering"
        elif is_turning_down:
            copp_label = "🔽 Turning Down"
        else:
            copp_label = "↓ Bearish"

        # Mean Reversion (Z-Score)
        sigma20 = robust_std(s_ret[-20:])
        sigma20 = max(sigma20, 0.005)
        sma20 = np.mean(s_adj[-20:])
        sigma_price = sigma20 * sma20
        if sigma_price < 1e-6:
            sigma_price = sma20 * 0.02
        z_score_val = float(np.clip((last_price - sma20) / sigma_price, -5.0, 5.0))
        mr_norm = np.clip(-z_score_val / 3.0, -1, 1)  # /3.0 konsisten dengan analysis_engine

        # RSI — filter/bonus, BUKAN komponen score (anti double-count dengan MeanRev/ZScore)
        rsi_ch = s_ret[-14:]
        gains = np.mean(rsi_ch[rsi_ch > 0]) if np.any(rsi_ch > 0) else 0.0
        losses = -np.mean(rsi_ch[rsi_ch < 0]) if np.any(rsi_ch < 0) else 1e-6
        rsi_val = 100.0 - (100.0 / (1.0 + gains / (losses + 1e-9)))
        rsi_bonus   = +0.06 if rsi_val < 25 else 0.0
        rsi_penalty = -0.08 if rsi_val > 75 else 0.0
        rsi_adj     = rsi_bonus + rsi_penalty

        # Volume Surge
        vol_ma20 = np.mean(volumes[-20:]) if len(volumes) >= 20 else volumes[-20:].mean()
        vol5 = np.mean(volumes[-5:]) if len(volumes) >= 5 else 0
        vol_surge = np.clip((vol5 / max(vol_ma20, 1.0) - 1.0), -1, 1)

        # Breakout bonus — harus close BENAR-BENAR di atas high20 + volume kuat
        res20 = np.max(highs[-21:-1]) if len(highs) >= 21 else np.max(highs)
        breakout_bonus = 0.10 if (last_price > res20 and vol_surge > 0.8) else 0.0

        # Tech Score V14 — Dual Adaptive Scoring (Leader vs Rebound)
        beta_effective = max(0.0, beta_norm) if rs_norm > 0 else beta_norm

        # 1. Jalur Strong Leader (Trend Following & Outperformer Lawan Arus)
        score_leader = (mom_norm*0.25 + copp_norm*0.28 + beta_effective*0.15 +
                        mr_norm*0.10 + vol_surge*0.10 + rs_norm*0.12 +
                        breakout_bonus + rsi_adj)

        # 2. Jalur Oversold Rebound (Saham diskon ekstrem yang mulai memantul saat crash)
        is_oversold = ((z_score_val <= -1.0 and rsi_val <= 42.0) or (rsi_val <= 32.0)) and (rsi_val < 48.0)
        has_rebound_trigger = (is_turning_up or copp_rising or s_ret[-1] > 0) and (vol_surge > -0.6)

        if is_oversold and has_rebound_trigger:
            rs_rebound_boost = max(0.0, rs_norm) * 0.10
            mom_rebound = max(mom_norm, 0.0) * 0.10
            vol_boost = max(0.0, vol_surge) * 0.12
            reversal_kicker = 0.08 if s_ret[-1] > 0 else 0.04
            score_rebound = (mr_norm * 0.32 +
                             copp_norm * 0.24 +
                             mom_rebound +
                             vol_boost +
                             rs_rebound_boost +
                             rsi_bonus +
                             reversal_kicker)
        else:
            score_rebound = -1.0

        # Hierarki Penentuan Tipe Setup & Scoring (Mutually Exclusive):
        is_strong_leader = (rs_norm >= 0.50 or rs_blend >= 0.030) and (rsi_val >= 46.0 or (last_price > sma20 and vol_surge > 0))

        if is_strong_leader:
            tech_score = score_leader
            setup_type = "🔥 Strong Leader"
        elif is_oversold and has_rebound_trigger and score_rebound > score_leader:
            tech_score = score_rebound
            setup_type = "🎯 Oversold Rebound"
        elif breakout_bonus > 0:
            tech_score = score_leader
            setup_type = "🚀 Breakout Play"
        else:
            tech_score = score_leader
            if rs_norm >= 0.15:
                setup_type = "🔥 Strong Leader"
            else:
                setup_type = "⚡ Trend Follower"

        tech_score = float(np.clip(tech_score, -1.0, 1.0))

        # Sinyal — threshold dinamis
        _ema20_ihsg = pd.Series(i_adj).ewm(span=20, adjust=False).mean().iloc[-1]
        _sma20_ihsg = np.mean(i_adj[-20:])
        risk_on_pre = _ema20_ihsg > _sma20_ihsg and i_ret5 > 0

        if risk_on_pre:
            th_strong, th_buy, th_weak = 0.50, 0.30, 0.15
        else:
            if setup_type == "🎯 Oversold Rebound":
                th_strong, th_buy, th_weak = 0.55, 0.35, 0.15
            else:
                th_strong, th_buy, th_weak = 0.60, 0.40, 0.20

        if tech_score > th_strong:    signal = "STRONG BUY ▲▲"
        elif tech_score > th_buy:     signal = "BUY ▲"
        elif tech_score > th_weak:    signal = "WEAK BUY ▲"
        elif tech_score < -th_strong: signal = "STRONG SELL ▼▼"
        elif tech_score < -th_buy:    signal = "SELL ▼"
        else:                          signal = "NEUTRAL →"

        # Regime
        ema20_ihsg = pd.Series(i_adj).ewm(span=20, adjust=False).mean().iloc[-1]
        sma20_ihsg = np.mean(i_adj[-20:])
        risk_on = ema20_ihsg > sma20_ihsg and i_ret5 > 0
        fast_vc = np.std(i_ret[-3:]) / (np.std(i_ret[-20:]) + 1e-9)
        if not risk_on and fast_vc >= 1.2:
            regime = "Market Panic 🚨"
        elif risk_on and fast_vc >= 1.0:
            regime = "Market Bullish 📈"
        elif risk_on:
            regime = "Market Bullish 📈"
        else:
            regime = "Market Bearish 🔻"

        # Estimasi return forward-looking
        alpha = np.mean(s_ret) - beta * np.mean(i_ret)
        if tech_score > 0.05:
            upside_mom = max(0.0, mom_combo) * 0.25
            upside_alpha = max(0.0, alpha) * 2.0
            upside_vol = 0.5 * sigma20
            dist_to_sma = (sma20 - last_price) / max(last_price, 1.0)
            upside_rebound = min(dist_to_sma * 0.7, 0.08) if (dist_to_sma > 0 and setup_type == "🎯 Oversold Rebound") else 0.0
            mu_est = float(np.clip(max(0.02, upside_mom + upside_alpha + upside_vol + upside_rebound), 0.015, 0.08))
        elif tech_score < -0.05:
            downside_mom = min(0.0, mom_combo) * 0.25
            mu_est = float(np.clip(-0.02 + downside_mom - 0.5 * sigma20, -0.08, -0.015))
        else:
            mu_est = float(np.clip(alpha + mom_combo * 0.10, -0.02, 0.02))

        # Bollinger %B
        std20 = np.std(s_adj[-20:])
        upper_bb = sma20 + 2*std20
        lower_bb = sma20 - 2*std20
        bb_pct = np.clip((last_price - lower_bb) / (upper_bb - lower_bb + 1e-9), -0.5, 1.5)

        # Trend Consistency
        ema20 = pd.Series(closes).ewm(span=20, adjust=False).mean().iloc[-1]
        ema50 = pd.Series(closes).ewm(span=50, adjust=False).mean().iloc[-1] if len(closes) >= 50 else ema20
        trend_searah = 0
        if len(closes) >= 6:
            for i in range(1, 6):
                if ((closes[-i] > closes[-i-1]) and (ema20 > ema50)) or \
                   ((closes[-i] < closes[-i-1]) and (ema20 < ema50)):
                    trend_searah += 1
            trend_consistency = trend_searah / 5 * 100
        else:
            trend_consistency = 50.0

        # ── Pivot S1 (input unified entry/exit) ──
        pivot = (float(highs[-1]) + float(lows[-1]) + float(closes[-1])) / 3.0
        s1 = 2 * pivot - float(highs[-1])

        # ── Entry / SL / TP — UNIFIED (core.entry_exit + Dual Entry Mode) ──
        _mem = (v12_mem or {}).get(ticker, {}) if v12_mem else {}
        _entry_error = _mem.get('entry_error_ema', 0.0)

        _ev = compute_entry_zone_and_sl_tp(
            last_price=last_price,
            s1=s1,
            res20=res20,
            sigma_ret=sigma20,        # ATR fallback untuk scanner
            adx=None, rsi14=rsi_val,  # scanner tidak hitung ADX → sl_mult=1.0
            signal=signal,
            is_daytrade=False,
            entry_error=_entry_error,
            # ── Dual Entry Mode inputs ──
            vol_surge_pct=vol_surge * 100.0,   # vol_surge ∈ [-1,1]
            is_breakout=(last_price > res20),
            zscore=z_score_val,
            setup_type=setup_type,
        )
        entry_low  = _ev["entry_low"]
        entry_high = _ev["entry_high"]
        sl_est     = _ev["sl"]
        tp_est     = _ev["tp_low"]
        rrr        = _ev["rrr"]

        # Likuiditas
        avg_value = np.mean(volumes[-20:] * closes[-20:])
        if avg_value >= 1e9:
            likuiditas_str = f"Rp {avg_value/1e9:.2f} M/hari"
        elif avg_value >= 1e6:
            likuiditas_str = f"Rp {avg_value/1e6:.0f} Jt/hari"
        else:
            likuiditas_str = f"Rp {avg_value:,.0f}"

        # Confidence
        confidence = min(0.99, 0.5 + abs(tech_score) * 0.5)

        return {
            "ticker": ticker,
            "techScore": tech_score,
            "signal": signal,
            "muEst": mu_est,
            "coppockLabel": copp_label,
            "lastPrice": last_price,
            "tpEst": tp_est,
            "slEst": sl_est,
            "regime": regime,
            "rsi": rsi_val,
            "beta": beta,
            "momScore": mom_combo,
            "isCoppockTurningUp": is_turning_up,
            "volSurge": vol_surge,
            "zScore": z_score_val,
            "bbPct": bb_pct,
            "trendConsistency": trend_consistency,
            "entryLow": entry_low,
            "entryHigh": entry_high,
            "likuiditas": likuiditas_str,
            "rrr": rrr,
            "confidence": confidence,
            # Relative Strength vs IHSG & Adaptive Setup Type (V14)
            "rsScore": rs_blend,
            "rsNorm": rs_norm,
            "rsLabel": rs_label,
            "setupType": setup_type,
            # Dual Entry Mode audit (Poin 3)
            "entryMode": _ev["entry_mode_used"],
            "entryModeReason": _ev["entry_mode_reason"],
        }

    except Exception:
        return None
