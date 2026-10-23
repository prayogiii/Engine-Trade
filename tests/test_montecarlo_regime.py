import pytest
from core.montecarlo import determine_mc_regime


@pytest.mark.parametrize("regime,expected", [
    # ── Trending up (GBM bullish) ──
    ("Strong Bullish 🚀",        "bullish"),
    ("Bullish 📈",               "bullish"),
    ("Early Recovery 🔄",        "bullish"),
    ("Bullish Accumulation 🏗️",  "bullish"),
    ("STABLE BULLISH",           "bullish"),
    ("VOLATILE UPTREND",         "bullish"),
    # ── Trending down (GBM bearish) ──
    ("Panic Sell 🚨",            "bearish"),
    ("Bearish 🔻",               "bearish"),
    ("Distribution 📉",          "bearish"),
    ("HIGH-STRESS PANIC",        "bearish"),
    # ── Sideways (OU mean-reverting) ──
    ("Sideways Normal ↔️",       "sideways"),
    ("Sideways Bias Naik ↗️",    "sideways"),
    ("Sideways Bias Turun ↘️",   "sideways"),
    ("Konsolidasi Tren ↔️",      "sideways"),
    ("Bearish Accumulation 🧊",  "sideways"),   # BEARISH_ACCUMULATION → default
    ("SIDEWAYS / CONSOLIDATION", "sideways"),
])
def test_regime_classification(regime, expected):
    assert determine_mc_regime(regime, "HOLD", "NO") == expected


def test_signal_override_strong_buy():
    assert determine_mc_regime("Sideways Normal ↔️", "🔥 STRONG BUY", "NO") == "bullish"


def test_signal_override_avoid():
    assert determine_mc_regime("Sideways Normal ↔️", "🚨 AVOID", "NO") == "bearish"


def test_breakout_buy_is_bullish():
    assert determine_mc_regime("Sideways Normal ↔️", "⚡ BUY (TACTICAL)", "YES (🔥)") == "bullish"


@pytest.mark.parametrize("bad", ["", None, "???", "Misterius"])
def test_unknown_regime_falls_back_to_sideways(bad):
    assert determine_mc_regime(bad, "HOLD", "NO") == "sideways"


def test_analyze_stock_import_determine_mc_regime():
    """Guard anti-regresi: analyze_stock wajib delegasi ke determine_mc_regime."""
    import inspect
    from services import analyze_stock as mod
    src = inspect.getsource(mod.analyze_stock)
    assert "determine_mc_regime(" in src, (
        "analyze_stock harus memanggil determine_mc_regime; "
        "jangan menduplikasi logika regime inline lagi."
    )