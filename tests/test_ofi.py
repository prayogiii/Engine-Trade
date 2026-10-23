import numpy as np
import pandas as pd
import pytest

from core.indicators import compute_ofi_enhanced


def _df(rows):
    """rows: list of (Open, High, Low, Close, Volume)."""
    return pd.DataFrame(rows, columns=['Open', 'High', 'Low', 'Close', 'Volume'])


def test_green_candle_shadows():
    # Green: O=100 C=110 H=115 L=95 → upper=5, lower=5, range=20 → ratio 0.25 each
    df = _df([(100, 115, 95, 110, 1000)] * 10)
    out = compute_ofi_enhanced(df, window=5).iloc[-1]
    assert out['Upper_Shadow_Ratio'] == pytest.approx(0.25, abs=1e-9)
    assert out['Lower_Shadow_Ratio'] == pytest.approx(0.25, abs=1e-9)


def test_red_candle_shadows_regression():
    """
    REGRESSION: candle merah wajib pakai High-Open & Close-Low,
    bukan High-Close & Open-Low.
    Red: O=110 C=100 H=115 L=95, range=20
      CORRECT: upper=115-110=5 (0.25), lower=100-95=5 (0.25)
      BUGGY:   upper=115-100=15 (0.75), lower=110-95=15 (0.75)
    """
    df = _df([(110, 115, 95, 100, 1000)] * 10)
    out = compute_ofi_enhanced(df, window=5).iloc[-1]
    assert out['Upper_Shadow_Ratio'] == pytest.approx(0.25, abs=1e-9), \
        "upper shadow salah — pakai High-Close (buggy) bukan High-Open"
    assert out['Lower_Shadow_Ratio'] == pytest.approx(0.25, abs=1e-9), \
        "lower shadow salah — pakai Open-Low (buggy) bukan Close-Low"


def test_red_marubozu_strong_negative_delta():
    """
    Kasus yang disebut notes: candle merah marubozu (O=H=110, C=L=100).
      CORRECT: delta = -Volume * (1-0) = -Volume   ← tekanan jual kuat
      BUGGY:   delta = -Volume * (1-1) = 0          ← tekanan jual hilang
    """
    df = _df([(110, 110, 100, 100, 5000)] * 10)
    out = compute_ofi_enhanced(df, window=5).iloc[-1]
    assert out['Delta_Enhanced'] == pytest.approx(-5000, rel=1e-9), \
        "marubozu merah harus menghasilkan delta kuat negatif, bukan ~0"


def test_green_marubozu_strong_positive_delta():
    df = _df([(100, 110, 100, 110, 5000)] * 10)
    out = compute_ofi_enhanced(df, window=5).iloc[-1]
    assert out['Delta_Enhanced'] == pytest.approx(5000, rel=1e-9)


def test_ofi_bounded_even_with_extreme_flow():
    # 50 candle hijau marubozu berturut-turut — OFI tetap dalam [-1, 1]
    df = _df([(100, 110, 100, 110, 10000)] * 50)
    ofi = compute_ofi_enhanced(df, window=20)['OFI_Enhanced']
    assert (ofi <= 1.0).all()
    assert (ofi >= -1.0).all()


def test_ofi_positive_on_sustained_buying():
    df = _df([(100, 110, 100, 110, 10000)] * 30)
    ofi = compute_ofi_enhanced(df, window=20)['OFI_Enhanced']
    assert ofi.iloc[-1] > 0.5


def test_ofi_negative_on_sustained_selling():
    df = _df([(110, 110, 100, 100, 10000)] * 30)
    ofi = compute_ofi_enhanced(df, window=20)['OFI_Enhanced']
    assert ofi.iloc[-1] < -0.5


def test_no_nan_even_on_short_history():
    df = _df([(100, 110, 95, 105, 1000)] * 3)
    ofi = compute_ofi_enhanced(df, window=20)['OFI_Enhanced']
    assert ofi.notna().all(), "OFI harus fillna(0) untuk bar historis pendek"


def test_flat_candle_no_crash():
    # Doji sempurna — High=Low=Open=Close
    df = _df([(100, 100, 100, 100, 1000)] * 20)
    out = compute_ofi_enhanced(df, window=10)
    assert out['Upper_Shadow_Ratio'].notna().all()
    assert out['Lower_Shadow_Ratio'].notna().all()