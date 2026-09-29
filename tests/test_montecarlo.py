"""Unit test core.montecarlo — pure simulation, no Streamlit."""
import numpy as np
import pandas as pd
import pytest

from core.montecarlo import (
    determine_mc_regime, simulate_paths, summarize_paths,
)


# ═══════════════════════════════════════════════════════════════
# FIXTURES
# ═══════════════════════════════════════════════════════════════
@pytest.fixture
def dummy_df():
    """DataFrame minimal untuk simulate_paths."""
    np.random.seed(42)
    n = 100
    close = np.cumsum(np.random.randn(n) * 0.5) + 1000
    close = np.maximum(close, 100)
    return pd.DataFrame({
        "Close": close,
        "Mom5D": np.random.randn(n) * 2,
    })


# ═══════════════════════════════════════════════════════════════
# REGIME DETECTION
# ═══════════════════════════════════════════════════════════════
class TestDetermineMcRegime:
    def test_bullish_from_regime(self):
        assert determine_mc_regime("STABLE BULLISH", "HOLD", "NO") == "bullish"

    def test_bullish_from_strong_buy(self):
        assert determine_mc_regime("unknown", "🔥 STRONG BUY", "NO") == "bullish"

    def test_bearish_from_panic(self):
        assert determine_mc_regime("HIGH-STRESS PANIC", "HOLD", "NO") == "bearish"

    def test_bearish_from_avoid(self):
        assert determine_mc_regime("unknown", "🚨 AVOID", "NO") == "bearish"

    def test_sideways_default(self):
        assert determine_mc_regime("SIDEWAYS / CONSOLIDATION", "HOLD", "NO") == "sideways"

    def test_breakout_with_buy_is_bullish(self):
        assert determine_mc_regime("unknown", "⚡ BUY (TACTICAL)", "YES (🔥)") == "bullish"


# ═══════════════════════════════════════════════════════════════
# SIMULATE PATHS
# ═══════════════════════════════════════════════════════════════
class TestSimulatePaths:
    def test_bullish_shape(self, dummy_df):
        paths, label = simulate_paths(
            dummy_df, 1000.0, df_est=5.0, mc_regime="bullish",
            n_sim=100, n_steps=10,
        )
        assert paths.shape == (10, 100)
        assert "Bullish" in label

    def test_bearish_label(self, dummy_df):
        paths, label = simulate_paths(
            dummy_df, 1000.0, df_est=5.0, mc_regime="bearish",
            n_sim=100, n_steps=10,
        )
        assert "Bearish" in label

    def test_sideways_label(self, dummy_df):
        paths, label = simulate_paths(
            dummy_df, 1000.0, df_est=5.0, mc_regime="sideways",
            n_sim=100, n_steps=10,
        )
        assert "OU" in label or "Mean" in label

    def test_paths_all_positive(self, dummy_df):
        paths, _ = simulate_paths(
            dummy_df, 1000.0, df_est=5.0, mc_regime="bullish",
            n_sim=100, n_steps=10,
        )
        # Harga selalu > 0 (hasil exp)
        assert (paths > 0).all()


# ═══════════════════════════════════════════════════════════════
# SUMMARIZE PATHS
# ═══════════════════════════════════════════════════════════════
class TestSummarizePaths:
    def test_swing_has_30d_outlook(self):
        paths = np.random.uniform(950, 1050, (30, 500))
        stats = summarize_paths(paths, 1000.0, "BUY", is_daytrade=False, r1=1050, s2=950)
        assert stats["estimasi_30d_label"] == "Outlook 30 Hari"
        assert stats["prob_30d_label"] == "Prob Naik 30 Hari"
        assert 0 <= stats["prob_bull"] <= 100
        assert 0 <= stats["prob_bull_30d"] <= 100

    def test_daytrade_no_30d(self):
        paths = np.random.uniform(950, 1050, (10, 500))
        stats = summarize_paths(paths, 1000.0, "BUY", is_daytrade=True, r1=1050, s2=950)
        assert stats["estimasi_30d_label"] is None
        assert stats["prob_30d_label"] is None

    def test_prob_bull_bounds(self):
        paths = np.random.uniform(900, 1100, (30, 1000))
        stats = summarize_paths(paths, 1000.0, "HOLD", is_daytrade=False, r1=1050, s2=950)
        assert 0 <= stats["hit_tp"] <= 100
        assert 0 <= stats["hit_sl"] <= 100

    def test_strong_buy_uses_75th_percentile(self):
        # Semua path = 1000, tapi percentile 75 juga 1000
        paths = np.ones((30, 100)) * 1000
        stats = summarize_paths(paths, 900.0, "STRONG BUY", is_daytrade=False, r1=1100, s2=800)
        # est_besok_sinyal = percentile 75 dari 1000 → 1000
        assert abs(stats["est_besok_sinyal"] - 1000) < 1