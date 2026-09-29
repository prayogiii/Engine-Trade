"""
V12 backtest engine — simulate trading di data historis.

Pure logic — input DataFrame + parameter, output metrik backtest.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from core.scoring import compute_v12_score_series, classify_v12_signal
from core.indicators import fraksi_step


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
) -> dict:
    """
    Run V12-synced backtest.

    Side effect: menambahkan kolom 'V12_Score', 'V12_Score_Live', 'Signal' ke df.

    Return dict:
        df, df_back,
        win_bt, pf_bt, avg_bt, max_dd_bt, sharpe_bt, trades_bt,
        profit_trades, loss_trades,
        bt_th_strong, bt_th_buy, bt_th_hold
    """
    _fee_beli = fee_beli_pct / 100.0
    _fee_jual = fee_jual_pct / 100.0

    # ── Hitung V12 score series ──
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

    df_back = df.iloc[-backtest_window:].copy()

    result = {
        "df": df,
        "df_back": df_back,
        "bt_th_strong": bt_th_strong,
        "bt_th_buy": bt_th_buy,
        "bt_th_hold": bt_th_hold,
        "win_bt": 0,
        "pf_bt": 0,
        "avg_bt": 0,
        "max_dd_bt": 0,
        "sharpe_bt": 0,
        "trades_bt": 0,
        "profit_trades": [],
        "loss_trades": [],
    }

    if len(df_back) == 0:
        return result

    # ── Simulasi trading ──
    trades, daily_returns = [], []
    in_position, entry_price_net = False, 0.0

    for i in range(len(df_back)):
        curr_sig = df_back['Signal'].iloc[i]
        curr_close = float(df_back['Close'].iloc[i])
        prev_close = float(df_back['Close'].iloc[i - 1]) if i > 0 else curr_close

        if in_position:
            daily_returns.append((curr_close - prev_close) / prev_close if prev_close else 0)
            if "AVOID" in curr_sig or i == len(df_back) - 1:
                slip_jual = fraksi_step(curr_close)
                exit_price = max(0, curr_close - slip_jual)
                net_exit = exit_price * (1 - _fee_jual)
                net_return = (net_exit - entry_price_net) / entry_price_net if entry_price_net > 0 else 0
                trades.append(net_return)
                in_position = False
        else:
            daily_returns.append(0.0)
            if "BUY" in curr_sig:
                slip_beli = fraksi_step(curr_close)
                entry_price_net = (curr_close + slip_beli) * (1 + _fee_beli)
                in_position = True

    # ── Hitung metrik ──
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
        trades_bt = len(trades)

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

    return result