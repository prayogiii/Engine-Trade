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


def score_stock_tech(df_stock, ticker, ihsg_data):
    """Menghitung skor teknikal + metrik lengkap untuk scanner V12."""
    try:
        closes = df_stock['Close'].values
        highs = df_stock['High'].values
        lows = df_stock['Low'].values
        volumes = df_stock['Volume'].values
        last_price = float(closes[-1])
        if last_price <= 0:
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

        # Beta & IHSG return 5 hari
        i_ret5 = (i_adj[iT] - i_adj[iT-5]) / i_adj[iT-5] if iT >= 5 else 0.0
        common_len = min(len(s_ret), len(i_ret))
        cov = np.cov(s_ret[:common_len], i_ret[:common_len])[0, 1]
        var_i = np.var(i_ret[:common_len])
        beta = (cov / var_i).clip(-3, 3) if var_i > 1e-8 else 1.0
        beta_norm = np.clip(beta * i_ret5 / 0.05, -1, 1)

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
        mr_norm = np.clip(-z_score_val / 0.05, -1, 1)

        # RSI
        rsi_ch = s_ret[-14:]
        gains = np.mean(rsi_ch[rsi_ch > 0]) if np.any(rsi_ch > 0) else 0.0
        losses = -np.mean(rsi_ch[rsi_ch < 0]) if np.any(rsi_ch < 0) else 1e-6
        rsi_val = 100.0 - (100.0 / (1.0 + gains / (losses + 1e-9)))
        if rsi_val < 25: rsi_norm = 0.90
        elif rsi_val < 35: rsi_norm = 0.55
        elif rsi_val < 45: rsi_norm = 0.20
        elif rsi_val < 55: rsi_norm = -0.10
        elif rsi_val < 65: rsi_norm = -0.35
        elif rsi_val < 75: rsi_norm = -0.55
        else: rsi_norm = -0.80

        # Volume Surge
        vol_ma20 = np.mean(volumes[-20:]) if len(volumes) >= 20 else volumes[-20:].mean()
        vol5 = np.mean(volumes[-5:]) if len(volumes) >= 5 else 0
        vol_surge = np.clip((vol5 / max(vol_ma20, 1.0) - 1.0), -1, 1)

        # Breakout bonus
        res20 = np.max(highs[-21:-1]) if len(highs) >= 21 else np.max(highs)
        breakout_bonus = 0.10 if (last_price > res20 * 0.995 and vol_surge > 0.3) else 0.0

        # Tech Score
        tech_score = (mom_norm*0.30 + copp_norm*0.28 + beta_norm*0.17 +
                      mr_norm*0.10 + vol_surge*0.08 + rsi_norm*0.07 +
                      breakout_bonus)
        tech_score = np.clip(tech_score, -1.0, 1.0)

        # Sinyal
        if tech_score > 0.42: signal = "STRONG BUY ▲▲"
        elif tech_score > 0.18: signal = "BUY ▲"
        elif tech_score > 0.05: signal = "WEAK BUY ▲"
        elif tech_score < -0.42: signal = "STRONG SELL ▼▼"
        elif tech_score < -0.18: signal = "SELL ▼"
        else: signal = "NEUTRAL →"

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

        # Estimasi return
        alpha = np.mean(s_ret) - beta * np.mean(i_ret)
        mu_est = np.clip(beta * i_ret5 + alpha + mom_combo * 0.15, -0.04, 0.04)

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

        # Entry Zone
        pivot = (highs[-1] + lows[-1] + closes[-1]) / 3.0
        s1 = 2 * pivot - highs[-1]
        entry_low = fraksi_bei(min(s1, last_price * (1 - sigma20)))
        entry_high = fraksi_bei(last_price)
        if entry_low >= entry_high:
            step = fraksi_step(last_price)
            entry_low = fraksi_bei(entry_high - step)

        # Take Profit Est
        tp_dist_pct = max(0.02, max(mu_est, 0.01) + 0.8 * sigma20)
        tp_est = fraksi_bei(last_price * (1 + tp_dist_pct))
        if tp_est <= last_price:
            step = fraksi_step(last_price)
            tp_est = fraksi_bei(last_price + 2 * step)

        # Stop Loss Est
        sl_dist_pct = max(0.02, 1.5 * sigma20)
        sl_est = fraksi_bei(entry_low * (1 - sl_dist_pct))
        if sl_est >= entry_low:
            step = fraksi_step(entry_low)
            sl_est = fraksi_bei(entry_low - 2 * step)

        # Likuiditas
        avg_value = np.mean(volumes[-20:] * closes[-20:])
        if avg_value >= 1e9:
            likuiditas_str = f"Rp {avg_value/1e9:.2f} M/hari"
        elif avg_value >= 1e6:
            likuiditas_str = f"Rp {avg_value/1e6:.0f} Jt/hari"
        else:
            likuiditas_str = f"Rp {avg_value:,.0f}"

        # Risk/Reward
        entry_ref = (entry_low + entry_high) / 2.0
        risk = entry_ref - sl_est
        reward = tp_est - entry_ref
        rrr = reward / risk if risk > 0 else 0.0

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
            "confidence": confidence
        }

    except Exception:
        return None