"""Unit test core.mtf."""
import numpy as np
import pandas as pd
import pytest

from core.mtf import check_mtf_anchor


@pytest.fixture
def bullish_df():
    """60 bar uptrend → bullish."""
    n = 60
    close = np.linspace(1000, 1200, n)
    return pd.DataFrame({"Close": close, "High": close * 1.01, "Low": close * 0.99})


@pytest.fixture
def bearish_df():
    """60 bar downtrend → bearish."""
    n = 60
    close = np.linspace(1200, 1000, n)
    return pd.DataFrame({"Close": close, "High": close * 1.01, "Low": close * 0.99})


class TestCheckMtfAnchor:
    def test_none_returns_bullish_default(self):
        is_bull, status = check_mtf_anchor(None)
        assert is_bull is True

    def test_short_df_returns_bullish(self):
        df = pd.DataFrame({"Close": [100] * 10})
        is_bull, _ = check_mtf_anchor(df)
        assert is_bull is True

    def test_bullish_uptrend(self, bullish_df):
        is_bull, status = check_mtf_anchor(bullish_df, "Daily")
        assert is_bull is True
        assert "Bullish" in status

    def test_bearish_downtrend(self, bearish_df):
        is_bull, status = check_mtf_anchor(bearish_df, "Weekly")
        assert is_bull is False
        assert "Bearish" in status