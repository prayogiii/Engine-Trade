"""Unit test core.vsa."""
import numpy as np
import pandas as pd
import pytest

from core.vsa import detect_marking_close, detect_vsa_flags, build_vsa_status_text


@pytest.fixture
def normal_df():
    """25 bar dengan spread & volume normal."""
    np.random.seed(42)
    n = 25
    base = 1000
    close = base + np.cumsum(np.random.randn(n) * 5)
    return pd.DataFrame({
        "Open": close - 2,
        "High": close + 5,
        "Low": close - 5,
        "Close": close,
        "Volume": np.random.randint(100_000, 200_000, n),
    })


class TestDetectMarkingClose:
    def test_none_input(self):
        assert detect_marking_close(None) is False

    def test_empty_input(self):
        assert detect_marking_close(pd.DataFrame()) is False

    def test_too_short(self):
        df = pd.DataFrame({"Close": [100] * 4, "Volume": [1000] * 4})
        assert detect_marking_close(df) is False


class TestDetectVsaFlags:
    def test_normal_no_flags(self, normal_df):
        result = detect_vsa_flags(normal_df)
        assert result["no_demand"] is False
        assert result["stopping_volume"] is False

    def test_short_df_no_crash(self):
        df = pd.DataFrame({"Open": [1], "High": [2], "Low": [0], "Close": [1], "Volume": [100]})
        result = detect_vsa_flags(df)
        assert result["no_demand"] is False


class TestBuildVsaStatusText:
    def test_no_flags(self):
        assert "Normal" in build_vsa_status_text(False, False, False)

    def test_all_flags(self):
        txt = build_vsa_status_text(True, True, True)
        assert "Marking" in txt
        assert "No Demand" in txt
        assert "Stopping" in txt