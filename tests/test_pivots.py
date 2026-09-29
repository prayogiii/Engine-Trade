"""Unit test core.pivots."""
import pandas as pd
import pytest

from core.pivots import (
    find_last_valid_bar, compute_pivots_from_ohlc,
    compute_pivots_for_swing,
)


class TestFindLastValidBar:
    def test_empty_returns_none(self):
        assert find_last_valid_bar(pd.DataFrame()) is None

    def test_picks_valid_bar(self):
        df = pd.DataFrame({
            "High":  [110, 120, 100],  # 3rd bar High==Low (invalid)
            "Low":   [100, 110, 100],
            "Close": [105, 115, 100],
        })
        hi, lo, cl = find_last_valid_bar(df)
        assert hi == 120
        assert lo == 110
        assert cl == 115


class TestComputePivotsFromOhlc:
    def test_basic(self):
        p = compute_pivots_from_ohlc(110, 90, 100)
        assert p["pp"] == (110 + 90 + 100) / 3
        assert p["r1"] == 2 * p["pp"] - 90
        assert p["s1"] == 2 * p["pp"] - 110

    def test_flat_bar(self):
        p = compute_pivots_from_ohlc(100, 100, 100)
        assert p["pp"] == 100
        assert p["r1"] == 100