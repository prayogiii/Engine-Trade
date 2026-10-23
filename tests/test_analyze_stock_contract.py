"""
Guard contract untuk analyze_stock().

Memastikan variabel-variabel kunci yang dipakai UI & Section 14/16/19
selalu terdefinisi. Mencegah regresi seperti bug "blok Breakout terhapus
saat patch Entry/SL/TP" (yang membuat NameError saat runtime).

Catatan: pakai regex `\\b<var>\\s*[,=]` agar tahan terhadap formatting
multi-spasi (kolom rata) maupun single-space.
"""
import inspect
import re

import pytest


@pytest.mark.parametrize("var", [
    # Section 12-13 (unified entry/exit)
    "entry_low", "entry_high", "entry_low_f", "entry_high_f",
    "entry_zone_f", "entry_ideal_f",
    "sl_harga", "sl_harga_f", "sl_pct",
    "tp_low", "tp_high", "tp_low_f", "tp_high_f",
    "tp_pct_low", "tp_pct_high",
    "rrr", "rrr_status",
    # Breakout (blok yang sempat hilang)
    "breakout", "breakout_label", "res20",
    # Section 16 (Monte Carlo)
    "mc_regime", "mc_regime_label",
    # Section 17-19 (UI)
    "signal_original", "signal_downgrade_reason",
    "DT_MIN_TARGET_PCT", "likuiditas_str",
])
def test_analyze_stock_defines_variable(var):
    from services import analyze_stock as mod
    src = inspect.getsource(mod.analyze_stock)
    # `\b` di awal mencegah match ke substring (mis. `sl_pct` tidak match `sl_pct_f`).
    # `\s*` sebelum [,=] menoleransi alignment multi-spasi.
    # [,=] menangkap assignment `=` maupun tuple unpack / dict key `,`.
    pattern = rf"\b{re.escape(var)}\s*[,=]"
    assert re.search(pattern, src), (
        f"Variable '{var}' tidak didefinisikan di analyze_stock(). "
        f"Apakah blok kode yang menghasilkannya terhapus saat patch?"
    )


def test_analyze_stock_uses_unified_entry_exit():
    """Guard: analyze_stock WAJIB delegasi ke compute_entry_zone_and_sl_tp."""
    from services import analyze_stock as mod
    src = inspect.getsource(mod.analyze_stock)
    assert "compute_entry_zone_and_sl_tp(" in src, (
        "analyze_stock harus memanggil compute_entry_zone_and_sl_tp. "
        "Jangan menduplikasi formula entry/SL/TP inline lagi."
    )


def test_scanner_uses_unified_entry_exit():
    """Guard: scanner WAJIB delegasi ke fungsi yang sama (Poin C notes)."""
    from core import scanner as mod
    src = inspect.getsource(mod.score_stock_tech)
    assert "compute_entry_zone_and_sl_tp(" in src, (
        "scanner harus memanggil compute_entry_zone_and_sl_tp. "
        "Formula entry/SL/TP harus IDENTIK dengan analyze_stock."
    )