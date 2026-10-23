import pytest
from core.regime import normalize_regime_key, RegimeKey, _REGIME_ALIASES

DISPLAY = [
    "Strong Bullish 🚀", "Bullish 📈", "Panic Sell 🚨", "Bearish 🔻",
    "Early Recovery 🔄", "Distribution 📉", "Konsolidasi Tren ↔️",
    "Bullish Accumulation 🏗️", "Bearish Accumulation 🧊",
    "Sideways Bias Naik ↗️", "Sideways Bias Turun ↘️", "Sideways Normal ↔️",
]
LEGACY = ["STABLE BULLISH", "VOLATILE UPTREND", "HIGH-STRESS PANIC",
          "SIDEWAYS / CONSOLIDATION", "BEARISH ACCUMULATION"]

@pytest.mark.parametrize("label", DISPLAY + LEGACY)
def test_known_labels_map(label):
    assert isinstance(normalize_regime_key(label), RegimeKey)

@pytest.mark.parametrize("bad", ["", None, "???", "   ", "Misterius Zone", "XYZ ABC 123"])
def test_unknown_falls_back_to_sideways(bad):
    assert normalize_regime_key(bad) == RegimeKey.SIDEWAYS

def test_case_insensitive():
    assert normalize_regime_key("strong bullish 🚀") == RegimeKey.STABLE_BULLISH

def test_accepts_enum():
    assert normalize_regime_key(RegimeKey.BEARISH_ACCUMULATION) == RegimeKey.BEARISH_ACCUMULATION

def test_every_enum_value_exists_in_regime_defaults():
    from core.scoring import _REGIME_DEFAULTS
    for key in RegimeKey:
        assert key.value in _REGIME_DEFAULTS, f"{key.value} tidak ada di _REGIME_DEFAULTS"

def test_aliases_are_all_valid_enum_targets():
    for alias, target in _REGIME_ALIASES.items():
        assert isinstance(target, RegimeKey), alias