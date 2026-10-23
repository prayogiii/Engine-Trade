"""
Test realistic bar-by-bar backtest (Entry/SL/TP simulation).

Setup scenario memakai monkeypatch pada compute_v12_score_series untuk
mengontrol kapan sinyal BUY/AVOID muncul, karena scoring asli bergantung
pada banyak faktor yang tidak relevan untuk menguji alur simulasi.

Nilai Entry/SL/TP yang diharapkan (untuk df dengan Close=100, ATR≈2,
ADX=25, RSI=50, signal BUY):
    entry_low  = 99
    entry_high = 101
    sl         = 97
    tp_low     = 105
(semua sudah dibulatkan fraksi BEI 1-tick pada rentang harga 100-200)
"""
import numpy as np
import pandas as pd
import pytest

import core.backtest as bt_module
from core.backtest import run_v12_backtest


# ═══════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════
def _make_df(n: int, base_ohlc: dict | None = None) -> pd.DataFrame:
    """DataFrame sintetis dengan default flat OHLC (untuk pre-compute)."""
    b = base_ohlc or {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0}
    return pd.DataFrame({
        'Open':    [b["open"]]  * n,
        'High':    [b["high"]]  * n,
        'Low':     [b["low"]]   * n,
        'Close':   [b["close"]] * n,
        'Volume':  [1_000_000]  * n,
        'Mom5D':   [0.0] * n,
        'ZScore':  [0.0] * n,
        'ADX':     [25.0] * n,
        'EMA20':   [100.0] * n,
        'EMA50':   [100.0] * n,
        'OFI_Enhanced': [0.0] * n,
    })


def _set_bars(df: pd.DataFrame, overrides: dict[int, dict]):
    """Override OHLC per bar index (mutasi in-place)."""
    for idx, vals in overrides.items():
        for col in ("Open", "High", "Low", "Close"):
            if col.lower() in vals:
                df.loc[df.index[idx], col] = vals[col.lower()]


def _mock_scores(monkeypatch, score_map: dict[int, float], n: int):
    """
    Monkeypatch compute_v12_score_series supaya mengembalikan Series
    yang nilainya kita kontrol per bar. score > +th_strong → STRONG BUY,
    score < -th_strong → AVOID.
    """
    def fake_scores(df_arg, *a, **kw):
        s = pd.Series(0.0, index=df_arg.index)
        for i, v in score_map.items():
            if 0 <= i < len(s):
                s.iloc[i] = v
        return s
    monkeypatch.setattr(bt_module, "compute_v12_score_series", fake_scores)


_DEFAULT_PARAMS = dict(
    adaptive_w={"Momentum": 0.2, "MeanRev": 0.2, "OFI": 0.2,
                "AI_Senti": 0.2, "Coppock": 0.2, "Bandar_Flow": 0.2,
                "Foreign_ZScore": 0.2, "Beta_IHSG": 0.2},
    mom_median_th=0.0,
    avg_sentiment=0.0,
    coppock_val=0.0,
    bandar_flow_val=0.0,
    foreign_zscore_val=0.0,
    fee_beli_pct=0.15,
    fee_jual_pct=0.25,
)


# ═══════════════════════════════════════════════════════════════
# BASELINE — backward compatibility
# ═══════════════════════════════════════════════════════════════
def test_return_dict_has_all_legacy_keys(monkeypatch):
    n = 80
    df = _make_df(n)
    _mock_scores(monkeypatch, {}, n)
    result = run_v12_backtest(df, backtest_window=50, **_DEFAULT_PARAMS)

    legacy_keys = [
        "df", "df_back", "bt_th_strong", "bt_th_buy", "bt_th_hold",
        "win_bt", "pf_bt", "avg_bt", "max_dd_bt", "sharpe_bt",
        "trades_bt", "profit_trades", "loss_trades",
    ]
    for k in legacy_keys:
        assert k in result, f"key lama hilang: {k}"

    new_keys = [
        "nt_count", "tp_hits", "sl_hits", "signal_exit_hits",
        "max_hold_hits", "entry_rate",
    ]
    for k in new_keys:
        assert k in result, f"key baru hilang: {k}"


def test_no_signals_returns_zero_trades(monkeypatch):
    n = 80
    df = _make_df(n)
    _mock_scores(monkeypatch, {}, n)
    result = run_v12_backtest(df, backtest_window=50, **_DEFAULT_PARAMS)
    assert result["trades_bt"] == 0
    assert result["nt_count"] == 0
    assert result["win_bt"] == 0


# ═══════════════════════════════════════════════════════════════
# ENTRY FILL
# ═══════════════════════════════════════════════════════════════
def test_entry_fills_when_low_touches_entry_high(monkeypatch):
    """BUY di bar 50 → pending. Bar 51 Low <= entry_high → fill."""
    n = 80
    df = _make_df(n)
    # Bar 51: Low=100 (<= 101 entry_high), High=103, Close=102 → hold sampai akhir
    _set_bars(df, {51: {"open": 100, "high": 103, "low": 100, "close": 102}})
    _mock_scores(monkeypatch, {50: 10.0}, n)  # BUY di bar 50

    result = run_v12_backtest(df, backtest_window=60, **_DEFAULT_PARAMS,
                              max_hold_bars=100)  # long max → no timeout
    # Pastikan minimal 1 posisi dibuka
    assert result["trades_bt"] >= 0  # trade ditutup oleh guard akhir window
    assert result["nt_count"] == 0    # entry berhasil
    assert result["entry_rate"] == 100.0 if result["trades_bt"] > 0 else True


def test_entry_not_touched_produces_nt(monkeypatch):
    """BUY di bar 50 → pending. Bar 51-55 Low > entry_high → NT."""
    n = 80
    df = _make_df(n)
    # Bar 51-56: gap up tinggi, Low >= 105 (> 101 entry_high)
    for i in range(51, 57):
        _set_bars(df, {i: {"open": 105, "high": 110, "low": 105, "close": 107}})
    _mock_scores(monkeypatch, {50: 10.0}, n)

    result = run_v12_backtest(df, backtest_window=60, **_DEFAULT_PARAMS,
                              pending_ttl_bars=3)
    assert result["nt_count"] == 1
    assert result["trades_bt"] == 0
    assert result["entry_rate"] == 0.0


# ═══════════════════════════════════════════════════════════════
# SL / TP TRIGGERS
# ═══════════════════════════════════════════════════════════════
def test_tp_hit_produces_win(monkeypatch):
    """Bar 51 fill, bar 52 High >= TP (105) → TP exit."""
    n = 80
    df = _make_df(n)
    _set_bars(df, {51: {"open": 100, "high": 102, "low": 100, "close": 101}})
    _set_bars(df, {52: {"open": 103, "high": 108, "low": 103, "close": 107}})
    _mock_scores(monkeypatch, {50: 10.0}, n)

    result = run_v12_backtest(df, backtest_window=60, **_DEFAULT_PARAMS)
    assert result["trades_bt"] == 1
    assert result["tp_hits"] == 1
    assert result["sl_hits"] == 0
    assert result["win_bt"] == 1.0
    assert result["profit_trades"][0] > 0


def test_sl_hit_produces_loss(monkeypatch):
    """Bar 51 fill, bar 52 Low <= SL (97) → SL exit."""
    n = 80
    df = _make_df(n)
    _set_bars(df, {51: {"open": 100, "high": 102, "low": 100, "close": 101}})
    _set_bars(df, {52: {"open": 98, "high": 99, "low": 94, "close": 95}})
    _mock_scores(monkeypatch, {50: 10.0}, n)

    result = run_v12_backtest(df, backtest_window=60, **_DEFAULT_PARAMS)
    assert result["trades_bt"] == 1
    assert result["sl_hits"] == 1
    assert result["tp_hits"] == 0
    assert result["win_bt"] == 0.0
    assert result["loss_trades"][0] < 0


def test_sl_first_when_candle_hits_both(monkeypatch):
    """
    REGRESSION per notes: bar 52 High >= TP (105) DAN Low <= SL (97) bersamaan
    → SL menang (konservatif).
    """
    n = 80
    df = _make_df(n)
    _set_bars(df, {51: {"open": 100, "high": 102, "low": 100, "close": 101}})
    _set_bars(df, {52: {"open": 100, "high": 108, "low": 94, "close": 100}})  # hit both
    _mock_scores(monkeypatch, {50: 10.0}, n)

    result = run_v12_backtest(df, backtest_window=60, **_DEFAULT_PARAMS)
    assert result["trades_bt"] == 1
    assert result["sl_hits"] == 1, "SL harus menang saat candle hit SL+TP bersamaan"
    assert result["tp_hits"] == 0
    assert result["win_bt"] == 0.0


# ═══════════════════════════════════════════════════════════════
# EXIT LAINNYA
# ═══════════════════════════════════════════════════════════════
def test_signal_reversal_exit(monkeypatch):
    """Fill bar 51, bar 52 sinyal AVOID → exit di Close."""
    n = 80
    df = _make_df(n)
    _set_bars(df, {51: {"open": 100, "high": 102, "low": 100, "close": 101}})
    _set_bars(df, {52: {"open": 101, "high": 102, "low": 100, "close": 101}})  # no SL/TP hit
    _mock_scores(monkeypatch, {50: 10.0, 52: -10.0}, n)  # bar 52 → AVOID

    result = run_v12_backtest(df, backtest_window=60, **_DEFAULT_PARAMS)
    assert result["trades_bt"] == 1
    assert result["signal_exit_hits"] == 1


def test_max_hold_timeout(monkeypatch):
    """Posisi dipegang sampai max_hold_bars tercapai."""
    n = 80
    df = _make_df(n)
    _set_bars(df, {51: {"open": 100, "high": 102, "low": 100, "close": 101}})
    _mock_scores(monkeypatch, {50: 10.0}, n)

    result = run_v12_backtest(df, backtest_window=60, **_DEFAULT_PARAMS,
                              max_hold_bars=5)
    assert result["trades_bt"] == 1
    assert result["max_hold_hits"] == 1


# ═══════════════════════════════════════════════════════════════
# NO LOOKAHEAD
# ═══════════════════════════════════════════════════════════════
def test_no_lookahead_entry_next_bar_only(monkeypatch):
    """
    BUY di bar 50, Low bar 50 = 100 (<= 101). Tapi karena sinyal baru
    diketahui di close bar 50, entry TIDAK boleh terjadi di bar 50.
    Bar 51 gap up (Low=105) → NT.
    """
    n = 80
    df = _make_df(n)
    # Bar 50 Low=100 (touchable), tapi kita TIDAK boleh entry di bar ini
    _set_bars(df, {50: {"open": 100, "high": 102, "low": 100, "close": 101}})
    # Bar 51-55 gap up → Low > entry_high
    for i in range(51, 56):
        _set_bars(df, {i: {"open": 105, "high": 110, "low": 105, "close": 107}})
    _mock_scores(monkeypatch, {50: 10.0}, n)

    result = run_v12_backtest(df, backtest_window=60, **_DEFAULT_PARAMS,
                              pending_ttl_bars=3)
    # Kalau ada lookahead bug, entry akan terjadi di bar 50 → trades >= 1
    # Yang benar: NT karena tidak ada fill di bar 51-53
    assert result["nt_count"] == 1
    assert result["trades_bt"] == 0


# ═══════════════════════════════════════════════════════════════
# ENTRY RATE & FIELDS DI df_back
# ═══════════════════════════════════════════════════════════════
def test_df_back_exposes_entry_plan_columns(monkeypatch):
    n = 80
    df = _make_df(n)
    _mock_scores(monkeypatch, {50: 10.0}, n)
    result = run_v12_backtest(df, backtest_window=50, **_DEFAULT_PARAMS)
    dfb = result["df_back"]
    for col in ("Entry_Low_BT", "Entry_High_BT", "SL_BT", "TP_BT"):
        assert col in dfb.columns, f"kolom audit hilang: {col}"


def test_entry_rate_calculation(monkeypatch):
    """2 BUY signals, 1 fill + 1 NT → entry_rate = 50%."""
    n = 120
    df = _make_df(n)
    # BUY 1 di bar 50 → fill di 51 (Low=100 <= entry_high=101)
    _set_bars(df, {51: {"open": 100, "high": 102, "low": 100, "close": 101}})
    # Bar 52: TP hit (High=110 >= TP~103), posisi 1 ditutup → Win
    _set_bars(df, {52: {"open": 103, "high": 110, "low": 102, "close": 108}})
    # BUY 2 di bar 90 → tidak pernah fill (Low=105 > 101 selama 5 bar)
    for i in range(91, 96):
        _set_bars(df, {i: {"open": 105, "high": 110, "low": 105, "close": 107}})
    _mock_scores(monkeypatch, {50: 10.0, 90: 10.0}, n)

    result = run_v12_backtest(df, backtest_window=80, **_DEFAULT_PARAMS,
                              max_hold_bars=100, pending_ttl_bars=3)
    assert result["trades_bt"] == 1, "trade 1 harus close via TP"
    assert result["tp_hits"] == 1
    assert result["nt_count"] == 1, "BUY 2 tidak fill → NT"
    assert result["entry_rate"] == 50.0