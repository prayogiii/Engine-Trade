"""
Single source of truth: Entry Zone, Stop Loss, Take Profit.

Dipakai IDENTIK oleh services/analyze_stock.py (Detail) dan
core/scanner.py (mass scan). Input superset — parameter yang tidak
tersedia (mis. atr_daily di scanner) diisi None, fungsi fallback ke σ20.

Invariant yang dijaga:
  - SL < entry_low <= entry_high < tp_low <= tp_high
  - Entry pullback swing BUY di-cap maksimal 2.5% di bawah last_price
    (aturan scanner), dan min_width TIDAK boleh merusak cap tsb.
  - TP selalu strictly di atas entry_high (worst-case fill).
  - TP daytrade selalu cover total fee + net margin 0.6%.

Dual Entry Mode (notes Poin 3):
  - breakout : BUY + volume surge > 50% + close > res20 → entry tight
               [last_price, last_price + 1 tick] (jangan tunggu pullback).
  - dip      : BUY + oversold (RSI ≤ 42 & Z ≤ -1.0, atau RSI ≤ 32) →
               entry [max(support, last_price*0.98), last_price - 1 tick].
               Support WAJIB di bawah (last - 1 tick); kalau tidak → auto.
  - auto     : default adaptive (perilaku lama).
  Mode invalid / kondisi tidak terpenuhi → downgrade ke auto (fail-safe).
"""
from __future__ import annotations

import math

from core.indicators import fraksi_bei, fraksi_step


# ═══════════════════════════════════════════════════════════════
# KLASIFIKASI ENTRY MODE (single source of truth)
# ═══════════════════════════════════════════════════════════════
VOL_SURGE_THRESHOLD_PCT = 50.0    # Q1
OVERSOLD_RSI_MAX = 42.0           # Q2 (sama dengan scanner)
OVERSOLD_ZSCORE_MAX = -1.0        # Q2
OVERSOLD_RSI_EXTREME = 32.0       # Q2
OVERSOLD_RSI_GUARD = 48.0         # Q2 (sama dengan scanner)


def classify_entry_mode(
    signal: str,
    rsi14: float,
    vol_surge_pct: float,
    zscore: float = 0.0,
    is_breakout: bool = False,
    setup_type: str | None = None,
) -> tuple[str, str]:
    """
    Return (entry_mode, reason).

    entry_mode ∈ {"breakout", "dip", "auto"}.

    Priority:
      1. setup_type dari scanner (Oversold Rebound / Strong Leader / Breakout Play)
      2. Klasifikasi dari signal + indikator (fallback untuk analyzer)
    """
    is_buy = "BUY" in signal
    is_oversold = (
        ((zscore <= OVERSOLD_ZSCORE_MAX and rsi14 <= OVERSOLD_RSI_MAX)
         or (rsi14 <= OVERSOLD_RSI_EXTREME))
        and (rsi14 < OVERSOLD_RSI_GUARD)
    )
    has_volume_surge = vol_surge_pct > VOL_SURGE_THRESHOLD_PCT
    is_breakout_setup = is_buy and has_volume_surge and is_breakout

    # ── Priority 1: setup_type dari scanner ──
    if setup_type:
        st = setup_type.upper()
        if "OVERSOLD REBOUND" in st:
            if is_buy and is_oversold:
                return "dip", f"Oversold Rebound (RSI {rsi14:.0f}, Z {zscore:.1f})"
            return "auto", "Oversold Rebound setup tapi indikator tidak oversold"
        if "STRONG LEADER" in st or "BREAKOUT" in st:
            if is_breakout_setup:
                return "breakout", (
                    f"{setup_type}: vol {vol_surge_pct:.0f}% + close>res20"
                )
            missing = []
            if not is_buy:
                missing.append("no BUY")
            if not has_volume_surge:
                missing.append(f"vol {vol_surge_pct:.0f}%<=50%")
            if not is_breakout:
                missing.append("close<=res20")
            return "auto", f"{setup_type} downgrade: {', '.join(missing)}"

    # ── Priority 2: klasifikasi berbasis signal ──
    if is_breakout_setup:
        return "breakout", f"Breakout (vol {vol_surge_pct:.0f}% + close>res20)"
    if is_buy and is_oversold:
        return "dip", f"Dip (RSI {rsi14:.0f}, Z {zscore:.1f} oversold)"

    return "auto", "default adaptive entry"


# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════
def compute_entry_zone_and_sl_tp(
    *,
    last_price: float,
    s1: float,
    r1: float = None,
    r2: float = None,
    res20: float = None,          # backward-compat, tidak dipakai untuk entry
    atr_val: float = None,
    atr_pct: float = None,
    atr_daily: float = None,
    sigma_ret: float = None,
    adx: float = None,
    rsi14: float = None,
    signal: str = "",
    is_daytrade: bool = False,
    entry_error: float = 0.0,
    fee_beli_pct: float = 0.15,
    fee_jual_pct: float = 0.25,
    bars_per_day: int = 54,
    # ── Dual Entry Mode (Poin 3) ──
    entry_mode: str = "auto",
    vol_surge_pct: float = 0.0,
    is_breakout: bool = False,
    zscore: float = 0.0,
    setup_type: str | None = None,
) -> dict:
    """
    Hitung Entry Zone + SL + TP yang konsisten untuk Scanner & Detail.
    Return dict berisi semua nilai (float + fraksi_bei rounded + %).
    """
    # ── Normalisasi volatilitas ──
    if atr_pct is None and atr_val is not None and last_price > 0:
        atr_pct = atr_val / last_price * 100.0
    if atr_val is None and atr_pct is not None:
        atr_val = atr_pct / 100.0 * last_price
    if atr_pct is None and sigma_ret is not None:
        atr_pct = sigma_ret * 100.0
        atr_val = sigma_ret * last_price
    if atr_pct is None:
        atr_pct = 3.0
        atr_val = last_price * 0.03
    atr_pct = max(0.1, float(atr_pct))
    atr_val = max(0.1, float(atr_val))

    has_adx_rsi = adx is not None and rsi14 is not None
    rsi_for_classify = rsi14 if rsi14 is not None else 50.0

    # ── Klasifikasi entry mode ──
    entry_mode_used, entry_mode_reason = classify_entry_mode(
        signal=signal,
        rsi14=rsi_for_classify,
        vol_surge_pct=vol_surge_pct,
        zscore=zscore,
        is_breakout=is_breakout,
        setup_type=setup_type,
    )

    # ── Manual override (Q4: validasi & downgrade jika kondisi gagal) ──
    if entry_mode not in ("auto", "breakout", "dip"):
        entry_mode = "auto"

    if entry_mode != "auto" and entry_mode != entry_mode_used:
        if entry_mode == "breakout":
            if ("BUY" in signal and vol_surge_pct > VOL_SURGE_THRESHOLD_PCT
                    and is_breakout):
                entry_mode_used = "breakout"
                entry_mode_reason = "forced breakout (kondisi terpenuhi)"
            else:
                entry_mode_used = "auto"
                entry_mode_reason = "forced breakout tapi kondisi gagal → auto"
        elif entry_mode == "dip":
            is_ovs = (
                ((zscore <= OVERSOLD_ZSCORE_MAX and rsi_for_classify <= OVERSOLD_RSI_MAX)
                 or (rsi_for_classify <= OVERSOLD_RSI_EXTREME))
                and (rsi_for_classify < OVERSOLD_RSI_GUARD)
            )
            if "BUY" in signal and is_ovs:
                entry_mode_used = "dip"
                entry_mode_reason = "forced dip (kondisi terpenuhi)"
            else:
                entry_mode_used = "auto"
                entry_mode_reason = "forced dip tapi tidak oversold → auto"

    # ═══════════════════════════════════════════════════════════
    # ENTRY ZONE — compute AUTO dulu sebagai fallback
    # ═══════════════════════════════════════════════════════════
    swing_buy_floor = None
    if (not is_daytrade) and ("BUY" in signal):
        swing_buy_floor = last_price * 0.975

    if s1 >= last_price * 0.98:
        entry_low = s1
    else:
        entry_low = last_price * (1 - atr_pct / 100.0)

    if swing_buy_floor is not None:
        entry_low = max(entry_low, swing_buy_floor)

    if "BUY" in signal:
        gap_catch = min(0.5 * atr_pct / 100.0, 0.015)
        entry_high = last_price * (1 + gap_catch)
    else:
        entry_high = last_price * (1 - 0.15 * atr_pct / 100.0)

    if entry_low > entry_high:
        entry_low, entry_high = entry_high, entry_low

    min_width = 0.6 * atr_val
    if swing_buy_floor is not None:
        min_width = min(min_width, max(0.0, entry_high - swing_buy_floor))
    if (entry_high - entry_low) < min_width:
        entry_low = max(0.0, entry_high - min_width)
        entry_high = entry_low + min_width

    _auto_low, _auto_high = entry_low, entry_high

    # ═══════════════════════════════════════════════════════════
    # APPLY MODE OVERRIDE (breakout / dip)
    # ═══════════════════════════════════════════════════════════
    if entry_mode_used == "breakout":
        tick_b = fraksi_step(last_price)
        entry_low = last_price
        entry_high = last_price + tick_b

    elif entry_mode_used == "dip":
        tick_d = fraksi_step(last_price)
        floor_d = last_price * 0.98
        # Support harus benar-benar di bawah (last - 1 tick).
        # Kalau support ≥ last - tick → bukan setup dip, downgrade ke auto.
        support_valid = (s1 is not None) and (s1 < last_price - tick_d)

        if not support_valid:
            entry_mode_used = "auto"
            entry_mode_reason += " (downgrade: support terlalu dekat / tidak valid)"
            entry_low, entry_high = _auto_low, _auto_high
        else:
            entry_high = last_price - tick_d
            if entry_high < floor_d:
                entry_high = floor_d
            entry_low = max(s1, floor_d)
            if entry_low >= entry_high:
                entry_mode_used = "auto"
                entry_mode_reason += " (downgrade: band terlalu sempit)"
                entry_low, entry_high = _auto_low, _auto_high

    # ── Entry-error shift (auto & dip saja, breakout dikecualikan) ──
    if entry_mode_used != "breakout" and entry_error and entry_error > 0:
        max_shift = last_price * 0.015
        shift = min(entry_error * 0.15, max_shift)
        if entry_mode_used == "dip":
            room = (last_price - fraksi_step(last_price)) - entry_high
            shift = max(0.0, min(shift, room))
        entry_low += shift
        entry_high += shift

    # ── Sanity guard ──
    if (not math.isfinite(entry_low)) or entry_low <= 0:
        entry_low = last_price * 0.98 if last_price > 0 else 1.0
    if (not math.isfinite(entry_high)) or entry_high <= 0:
        entry_high = last_price if last_price > 0 else 1.0
    if entry_low > entry_high:
        entry_low, entry_high = entry_high, entry_low

    entry_low_f = fraksi_bei(entry_low)
    entry_high_f = fraksi_bei(entry_high)

    # ═══════════════════════════════════════════════════════════
    # STOP LOSS
    # ═══════════════════════════════════════════════════════════
    sl_mult = 1.0
    if has_adx_rsi:
        if adx > 30 and 30 < rsi14 < 70:
            sl_mult = 0.75
        elif adx < 20:
            sl_mult = 1.25
        if rsi14 > 70 or rsi14 < 30:
            sl_mult = 1.5

    if is_daytrade:
        base_sl_dist = last_price * 0.04 * sl_mult
        min_ticks = 2 * fraksi_step(entry_low)
        sl_dist = max(min_ticks, base_sl_dist)
        sl = entry_low - sl_dist
    else:
        sl = entry_low - sl_mult * atr_val

    sl = fraksi_bei(sl)
    step = fraksi_step(entry_low)
    if sl >= entry_low:
        sl = fraksi_bei(entry_low - 2 * step)
    if sl <= 0:
        sl = fraksi_bei(last_price * 0.95)

    # ═══════════════════════════════════════════════════════════
    # TAKE PROFIT
    # ═══════════════════════════════════════════════════════════
    if is_daytrade:
        tp_base = (atr_daily if (atr_daily and atr_daily > 0)
                   else atr_val * (bars_per_day ** 0.5))
        tp_mult_low, tp_mult_high = 0.35, 0.65
        if has_adx_rsi:
            if adx > 30 and 30 < rsi14 < 70:
                tp_mult_low, tp_mult_high = 0.5, 0.8
            elif adx < 20:
                tp_mult_low, tp_mult_high = 0.3, 0.55
        tp_low_raw = entry_low + tp_mult_low * tp_base
        tp_high_raw = entry_low + tp_mult_high * tp_base
        tp_low_raw = min(tp_low_raw, entry_low * 1.08)
        tp_high_raw = min(tp_high_raw, entry_low * 1.12)
        fee_floor = entry_low * (1 + (fee_beli_pct + fee_jual_pct) / 100.0 + 0.006)
        tp_low_raw = max(tp_low_raw, fee_floor)
        tp_high_raw = max(tp_high_raw, tp_low_raw + 2 * fraksi_step(tp_low_raw))
        min_tp = max(entry_low + 2 * step, last_price + 2 * fraksi_step(last_price))
        tp_low_raw = max(tp_low_raw, min_tp)
        tp_low = fraksi_bei(tp_low_raw)
        tp_high = fraksi_bei(tp_high_raw)
        if tp_low <= entry_low:
            tp_low = fraksi_bei(entry_low + 2 * step)
        if tp_high <= tp_low:
            tp_high = fraksi_bei(tp_low + 2 * fraksi_step(tp_low))
    else:
        tp_mult_low, tp_mult_high = 1.5, 2.5
        if has_adx_rsi:
            if adx > 30 and 30 < rsi14 < 70:
                tp_mult_low, tp_mult_high = 2.0, 3.0
            elif adx < 20:
                tp_mult_low, tp_mult_high = 1.2, 1.8
        tp_low = r1 if (r1 and r1 > last_price) else last_price + tp_mult_low * atr_val
        tp_high = r2 if (r2 and r2 > last_price) else last_price + tp_mult_high * atr_val
        if tp_low > tp_high:
            tp_low, tp_high = tp_high, tp_low
        entry_ref = (entry_low + entry_high) / 2.0
        risk_ref = entry_ref - sl
        if risk_ref > 0:
            min_tp_for_rrr = entry_ref + risk_ref * 1.6
            if tp_low < min_tp_for_rrr:
                tp_low = min_tp_for_rrr
            if tp_high < tp_low:
                tp_high = tp_low * 1.08
        tp_low = min(tp_low, last_price * 1.15)
        tp_high = min(tp_high, last_price * 1.15)
        tp_low = fraksi_bei(tp_low)
        tp_high = fraksi_bei(tp_high)
        if tp_low <= entry_low:
            tp_low = fraksi_bei(entry_low + 2 * fraksi_step(entry_low))
        if tp_high <= tp_low:
            tp_high = fraksi_bei(tp_low + 2 * fraksi_step(tp_low))

    # ── FINAL GUARD: TP wajib strictly di atas entry_high ──
    step_tp_guard = fraksi_step(entry_high if entry_high > 0 else entry_low)
    if tp_low <= entry_high:
        tp_low = fraksi_bei(entry_high + 2 * step_tp_guard)
    if tp_high <= tp_low:
        tp_high = fraksi_bei(tp_low + 2 * fraksi_step(tp_low))

    # ═══════════════════════════════════════════════════════════
    # RRR & PERSENTASE
    # ═══════════════════════════════════════════════════════════
    entry_ref = (entry_low + entry_high) / 2.0
    risk = entry_ref - sl
    reward = tp_low - entry_ref
    rrr = reward / risk if risk > 0 else 0.0

    sl_pct = (last_price - sl) / last_price * 100.0 if last_price > 0 else 0.0
    tp_pct_low = (tp_low - entry_low_f) / entry_low_f * 100.0 if entry_low_f > 0 else 0.0
    tp_pct_high = (tp_high - entry_low_f) / entry_low_f * 100.0 if entry_low_f > 0 else 0.0

    return {
        "entry_low": entry_low, "entry_high": entry_high,
        "entry_low_f": entry_low_f, "entry_high_f": entry_high_f,
        "entry_zone_f": f"Rp {entry_low_f:,.0f} - Rp {entry_high_f:,.0f}",
        "entry_ref": entry_ref,
        "sl": sl, "sl_f": fraksi_bei(sl), "sl_pct": sl_pct,
        "tp_low": tp_low, "tp_high": tp_high,
        "tp_low_f": fraksi_bei(tp_low), "tp_high_f": fraksi_bei(tp_high),
        "tp_pct_low": tp_pct_low, "tp_pct_high": tp_pct_high,
        "rrr": rrr,
        "atr_pct_used": atr_pct,
        "atr_val_used": atr_val,
        "sl_mult_used": sl_mult,
        # ── Dual Entry Mode audit (Poin 3) ──
        "entry_mode_used": entry_mode_used,
        "entry_mode_reason": entry_mode_reason,
    }
