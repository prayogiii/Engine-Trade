"""
V12 backtest engine — simulate trading di data historis.

Realistic bar-by-bar simulation (sesuai notes Poin 5):
  - Pending entry: BUY signal di bar i → limit @ entry_high aktif di bar i+1
  - Fill terjadi HANYA jika Low bar i+1 <= entry_high (no lookahead)
  - Exit posisi jika salah satu:
      * Low  <= SL  → Loss (conservative — SL first)
      * High >= TP  → Win
      * Signal reversal ke AVOID  → exit di Close
      * Max hold bars tercapai    → exit di Close
  - Asumsi konservatif: jika candle yang sama menyentuh SL dan TP, SL menang.
  - Slippage: fraksi_step dikenakan pada entry, SL, TP, dan signal exit.
  - Entry fill di `entry_high` (worst-case limit fill, konservatif).

Backward-compatible: semua key lama di return dict tetap ada.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from core.scoring import compute_v12_score_series, classify_v12_signal
from core.indicators import fraksi_step
from core.entry_exit import compute_entry_zone_and_sl_tp


# ═══════════════════════════════════════════════════════════════
# HELPERS — series pre-computation
# ═══════════════════════════════════════════════════════════════
def _compute_atr_series(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high, low, close = df['High'], df['Low'], df['Close']
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low - close.shift()).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1.0 / period, adjust=False).mean()


def _compute_rsi_series(df: pd.DataFrame, period: int = 14) -> pd.Series:
    delta = df['Close'].diff()
    gain = delta.clip(lower=0).ewm(alpha=1.0 / period, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1.0 / period, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi = 100.0 - (100.0 / (1.0 + rs))
    return rsi.fillna(50.0)


def _compute_pivot_s1_series(df: pd.DataFrame) -> pd.Series:
    """Pivot S1 rolling dari OHLC bar sebelumnya."""
    prev_h = df['High'].shift(1)
    prev_l = df['Low'].shift(1)
    prev_c = df['Close'].shift(1)
    pivot = (prev_h + prev_l + prev_c) / 3.0
    s1 = 2.0 * pivot - prev_h
    return s1.fillna(df['Close'])


# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════
def run_v12_backtest(
    df: pd.DataFrame,
    backtest_window: int,
    adaptive_w: dict,
    mom_median_th: float,
    avg_sentiment: float,
    coppock_val: float,
    bandar_flow_val: float,
    foreign_zscore_val: float,
    fee_beli_pct: float,
    fee_jual_pct: float,
    annual_factor: float = float(np.sqrt(252)),
    is_daytrade: bool = False,
    max_hold_bars: int | None = None,
    pending_ttl_bars: int | None = None,
    bars_per_day: int | None = None,
) -> dict:
    """
    Backtest realistis dengan simulasi Entry / SL / TP bar-by-bar.

    Side effect: menambahkan kolom 'V12_Score', 'V12_Score_Live', 'Signal'
    ke df. Setelah slicing ke df_back, kolom *_BT ditambahkan untuk audit UI.

    Return dict (backward compatible + field baru):
        df, df_back,
        win_bt, pf_bt, avg_bt, max_dd_bt, sharpe_bt, trades_bt,
        profit_trades, loss_trades,
        bt_th_strong, bt_th_buy, bt_th_hold,
        nt_count, tp_hits, sl_hits, signal_exit_hits, max_hold_hits,
        entry_rate
    """
    _fee_beli = fee_beli_pct / 100.0
    _fee_jual = fee_jual_pct / 100.0

    # ── Resolve defaults berdasarkan mode ──
    if max_hold_bars is None:
        max_hold_bars = 10 if is_daytrade else 30
    if pending_ttl_bars is None:
        pending_ttl_bars = 3 if is_daytrade else 5
    if bars_per_day is None:
        bars_per_day = 64 if is_daytrade else 1

    # ── Hitung V12 score series (unchanged) ──
    df['V12_Score'] = compute_v12_score_series(
        df, adaptive_w, mom_median_th, avg_sentiment,
        use_live_factors=False,
    )
    df['V12_Score_Live'] = compute_v12_score_series(
        df, adaptive_w, mom_median_th, avg_sentiment,
        use_live_factors=True,
        coppock_val=coppock_val,
        bandar_flow_val=bandar_flow_val,
        foreign_zscore_val=foreign_zscore_val,
    )

    bt_score_std = max(0.10, min(0.35, df['V12_Score'].std()))
    bt_th_strong = bt_score_std * 1.0
    bt_th_buy = bt_score_std * 0.4
    bt_th_hold = -bt_score_std * 0.4

    df['Signal'] = df['V12_Score'].apply(
        lambda sc: classify_v12_signal(sc, bt_th_strong, bt_th_buy, bt_th_hold)
    )

    # ── Pre-compute ATR / RSI / pivot S1 series ──
    atr_series = _compute_atr_series(df)
    rsi_series = _compute_rsi_series(df)
    s1_series = _compute_pivot_s1_series(df)

    df_back = df.iloc[-backtest_window:].copy()

    result = {
        "df": df,
        "df_back": df_back,
        "bt_th_strong": bt_th_strong,
        "bt_th_buy": bt_th_buy,
        "bt_th_hold": bt_th_hold,
        "win_bt": 0, "pf_bt": 0, "avg_bt": 0, "max_dd_bt": 0,
        "sharpe_bt": 0, "trades_bt": 0,
        "profit_trades": [], "loss_trades": [],
        # Field baru (backward compatible)
        "nt_count": 0,
        "tp_hits": 0, "sl_hits": 0, "signal_exit_hits": 0, "max_hold_hits": 0,
        "entry_rate": 0.0,
    }

    if len(df_back) == 0:
        return result

    n = len(df_back)

    # ── Pre-compute Entry/SL/TP per bar ──
    entry_low_arr = np.zeros(n)
    entry_high_arr = np.zeros(n)
    sl_arr = np.zeros(n)
    tp_arr = np.zeros(n)

    for i in range(n):
        idx = df_back.index[i]
        close_i = float(df.loc[idx, 'Close'])
        atr_i = float(atr_series.loc[idx]) if not pd.isna(atr_series.loc[idx]) else close_i * 0.02
        atr_i = max(atr_i, close_i * 0.005)
        atr_pct_i = (atr_i / close_i * 100.0) if close_i > 0 else 2.0
        rsi_i = float(rsi_series.loc[idx]) if not pd.isna(rsi_series.loc[idx]) else 50.0
        adx_i = (float(df.loc[idx, 'ADX'])
                 if ('ADX' in df.columns and not pd.isna(df.loc[idx, 'ADX'])) else 25.0)
        s1_i = float(s1_series.loc[idx]) if not pd.isna(s1_series.loc[idx]) else close_i
        signal_i = df_back['Signal'].iloc[i]

        ev = compute_entry_zone_and_sl_tp(
            last_price=close_i,
            s1=s1_i,
            atr_val=atr_i,
            atr_pct=atr_pct_i,
            adx=adx_i,
            rsi14=rsi_i,
            signal=signal_i,
            is_daytrade=is_daytrade,
            entry_error=0.0,
            fee_beli_pct=fee_beli_pct,
            fee_jual_pct=fee_jual_pct,
            bars_per_day=bars_per_day,
        )
        entry_low_arr[i] = ev["entry_low"]
        entry_high_arr[i] = ev["entry_high"]
        sl_arr[i] = ev["sl"]
        tp_arr[i] = ev["tp_low"]  # konservatif: target pakai TP-low

    # Expose per-bar plan untuk audit UI (aman: dict-access tetap kompatibel)
    df_back['Entry_Low_BT'] = entry_low_arr
    df_back['Entry_High_BT'] = entry_high_arr
    df_back['SL_BT'] = sl_arr
    df_back['TP_BT'] = tp_arr

    # ═══════════════════════════════════════════════════════════════
    # Bar-by-bar simulation
    # ═══════════════════════════════════════════════════════════════
    trades = []
    daily_returns = []
    nt_count = 0
    tp_hits = sl_hits = signal_exit_hits = max_hold_hits = 0

    in_position = False
    entry_price_net = 0.0
    entry_idx = -1
    active_sl = 0.0
    active_tp = 0.0
    pending_entry_high = None
    pending_bars_left = 0
    pending_signal_bar = -1

    def _close_position(exit_price: float, kind: str):
        nonlocal in_position, entry_price_net, entry_idx, active_sl, active_tp
        nonlocal tp_hits, sl_hits, signal_exit_hits, max_hold_hits
        slip_jual = fraksi_step(exit_price)
        net_exit = max(0.0, exit_price - slip_jual) * (1 - _fee_jual)
        net_return = (net_exit - entry_price_net) / entry_price_net if entry_price_net > 0 else 0.0
        trades.append(net_return)
        in_position = False
        entry_price_net = 0.0
        entry_idx = -1
        active_sl = active_tp = 0.0
        if kind == "tp":       tp_hits += 1
        elif kind == "sl":     sl_hits += 1
        elif kind == "signal": signal_exit_hits += 1
        elif kind == "timeout": max_hold_hits += 1

    for i in range(n):
        curr_sig   = df_back['Signal'].iloc[i]
        curr_close = float(df_back['Close'].iloc[i])
        curr_high  = float(df_back['High'].iloc[i])
        curr_low   = float(df_back['Low'].iloc[i])
        prev_close = float(df_back['Close'].iloc[i - 1]) if i > 0 else curr_close

        # ── 1. Try to fill pending entry dari BUY signal bar sebelumnya ──
        if not in_position and pending_entry_high is not None and pending_bars_left > 0:
            if curr_low <= pending_entry_high:
                # Fill di entry_high (limit buy worst-case) + slippage
                slip_beli = fraksi_step(pending_entry_high)
                entry_price_net = (pending_entry_high + slip_beli) * (1 + _fee_beli)
                in_position = True
                entry_idx = i
                # SL/TP diambil dari bar sinyal BUY (bukan bar fill)
                active_sl = sl_arr[pending_signal_bar]
                active_tp = tp_arr[pending_signal_bar]
                pending_entry_high = None
                pending_bars_left = 0
                pending_signal_bar = -1
            else:
                pending_bars_left -= 1
                if pending_bars_left <= 0:
                    pending_entry_high = None
                    pending_signal_bar = -1
                    nt_count += 1  # harga tidak pernah sentuh entry zone

        # ── 2. Manage exit posisi aktif ──
        if in_position:
            # SL first (conservative, per notes)
            if curr_low <= active_sl:
                _close_position(active_sl, "sl")
                daily_returns.append(0.0)
                continue
            # TP
            if curr_high >= active_tp:
                _close_position(active_tp, "tp")
                daily_returns.append(0.0)
                continue
            # Signal reversal → exit di Close
            if "AVOID" in curr_sig:
                _close_position(curr_close, "signal")
                daily_returns.append(0.0)
                continue
            # Max hold guard
            if entry_idx >= 0 and (i - entry_idx) >= max_hold_bars:
                _close_position(curr_close, "timeout")
                daily_returns.append(0.0)
                continue

        # ── 3. Queue new pending entry dari BUY signal bar ini ──
        if not in_position and pending_entry_high is None and "BUY" in curr_sig:
            pending_entry_high = entry_high_arr[i]
            pending_bars_left = pending_ttl_bars
            pending_signal_bar = i

        # ── 4. Catat mark-to-market return untuk Sharpe ──
        if in_position:
            daily_returns.append(
                (curr_close - prev_close) / prev_close if prev_close else 0.0
            )
        else:
            daily_returns.append(0.0)

    # ── Force close kalau masih holding di bar terakhir ──
    if in_position:
        last_close = float(df_back['Close'].iloc[-1])
        _close_position(last_close, "timeout")

    # ═══════════════════════════════════════════════════════════════
    # Metrics
    # ═══════════════════════════════════════════════════════════════
    trades_bt = len(trades)

    if trades:
        win_bt = sum(1 for r in trades if r > 0) / len(trades)
        loss_trades = [r for r in trades if r < 0]
        profit_trades = [r for r in trades if r > 0]
        pf_bt = abs(sum(profit_trades) / sum(loss_trades)) if loss_trades else np.inf
        avg_bt = float(np.mean(trades))
        equity = np.cumprod([1 + r for r in trades])
        max_dd_bt = float(np.min(equity / np.maximum.accumulate(equity) - 1) * 100) if len(equity) else 0
        daily_ret = np.array(daily_returns)
        sharpe_bt = (daily_ret.mean() / daily_ret.std()) * annual_factor if daily_ret.std() else 0

        result.update({
            "win_bt": win_bt,
            "pf_bt": pf_bt,
            "avg_bt": avg_bt,
            "max_dd_bt": max_dd_bt,
            "sharpe_bt": sharpe_bt,
            "trades_bt": trades_bt,
            "profit_trades": profit_trades,
            "loss_trades": loss_trades,
        })

    total_attempts = trades_bt + nt_count
    result.update({
        "nt_count": nt_count,
        "tp_hits": tp_hits,
        "sl_hits": sl_hits,
        "signal_exit_hits": signal_exit_hits,
        "max_hold_hits": max_hold_hits,
        "entry_rate": (
            (trades_bt / total_attempts * 100.0) if total_attempts > 0 else 0.0
        ),
    })

    return result
