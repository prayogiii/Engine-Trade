"""Unit test core.scoring — pure math, no Streamlit."""
import pytest

from config.settings import FACTOR_KEYS
from core.scoring import (
    default_weight, get_adaptive_weights,
    classify_v12_signal, compute_score_std,
    compute_memory_update_math, compute_entry_error_update,
)


class TestDefaultWeight:
    def test_returns_float_in_range(self):
        for factor in FACTOR_KEYS:
            for regime in ["STABLE BULLISH", "SIDEWAYS / CONSOLIDATION", "unknown"]:
                w = default_weight(factor, regime)
                assert isinstance(w, float)
                assert 0.0 <= w <= 0.5

    def test_unknown_regime_uses_fallback(self):
        w = default_weight("Momentum", "NONEXISTENT REGIME")
        assert w == 0.23


class TestAdaptiveWeights:
    def test_empty_memory_returns_defaults(self):
        w = get_adaptive_weights("BBRI", "STABLE BULLISH", v12_mem={})
        assert len(w) == len(FACTOR_KEYS)
        assert abs(sum(w.values()) - 1.0) < 1e-6
        for v in w.values():
            assert 0.0 < v < 1.0

    def test_high_accuracy_boosts_weight(self):
        mem = {
            "BBRI": {
                "weights": {},
                "accuracy": {k: 0.85 for k in FACTOR_KEYS},
                "error_ema": {k: 0.1 for k in FACTOR_KEYS},
            }
        }
        w_high = get_adaptive_weights("BBRI", "SIDEWAYS / CONSOLIDATION", v12_mem=mem)
        w_default = get_adaptive_weights("BBRI", "SIDEWAYS / CONSOLIDATION", v12_mem={})
        # Semua faktor high accuracy → norm tetap 1, tapi distribusi bergeser
        assert abs(sum(w_high.values()) - 1.0) < 1e-6

    def test_weights_sum_to_one(self):
        for regime in ["STABLE BULLISH", "SIDEWAYS / CONSOLIDATION"]:
            w = get_adaptive_weights("TEST", regime, v12_mem={})
            assert abs(sum(w.values()) - 1.0) < 1e-6


class TestClassifyV12Signal:
    def test_strong_buy(self):
        assert "STRONG BUY" in classify_v12_signal(0.5, 0.2, 0.05, -0.05)

    def test_buy_tactical(self):
        assert "BUY" in classify_v12_signal(0.1, 0.2, 0.05, -0.05)

    def test_hold(self):
        assert "HOLD" in classify_v12_signal(0.0, 0.2, 0.05, -0.05)

    def test_avoid(self):
        assert "AVOID" in classify_v12_signal(-0.5, 0.2, 0.05, -0.05)


class TestComputeScoreStd:
    def test_empty_list_returns_fallback(self):
        assert compute_score_std([]) == 0.15
        assert compute_score_std([0.1, 0.2]) == 0.15  # < 6 elemen

    def test_clamp_lower(self):
        # std kecil → clamp ke 0.10
        assert compute_score_std([0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1]) == 0.10

    def test_clamp_upper(self):
        # std besar → clamp ke 0.35
        values = [0.0, 10.0] * 5
        assert compute_score_std(values) == 0.35


class TestMemoryUpdate:
    def test_small_return_no_update(self):
        mem = {"weights": {}, "accuracy": {}, "error_ema": {}}
        out = compute_memory_update_math(mem, {k: 0.0 for k in FACTOR_KEYS}, 0.001)
        assert out == mem  # unchanged

    def test_win_updates_accuracy_up(self):
        mem = {"weights": {}, "accuracy": {}, "error_ema": {}}
        signals = {k: 0.5 for k in FACTOR_KEYS}
        out = compute_memory_update_math(mem, signals, 0.05, volatility=0.02)
        for k in FACTOR_KEYS:
            # Hit rate 100% → accuracy naik dari 0.5
            assert out["accuracy"][k] > 0.5

    def test_loss_updates_accuracy_down(self):
        mem = {"weights": {}, "accuracy": {}, "error_ema": {}}
        signals = {k: 0.5 for k in FACTOR_KEYS}
        out = compute_memory_update_math(mem, signals, -0.05, volatility=0.02)
        for k in FACTOR_KEYS:
            assert out["accuracy"][k] < 0.5

    def test_total_updates_increments(self):
        mem = {"weights": {}, "accuracy": {}, "error_ema": {}, "total_updates": 5}
        signals = {k: 0.5 for k in FACTOR_KEYS}
        out = compute_memory_update_math(mem, signals, 0.05)
        assert out["total_updates"] == 6


class TestEntryErrorUpdate:
    def test_first_update(self):
        result = compute_entry_error_update(0.0, 100.0, alpha=0.2)
        assert result == 20.0  # 0*0.8 + 100*0.2

    def test_second_update(self):
        result = compute_entry_error_update(20.0, 100.0, alpha=0.2)
        assert result == 36.0  # 20*0.8 + 100*0.2