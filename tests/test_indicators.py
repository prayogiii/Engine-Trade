"""Unit test core.indicators — tidak butuh Streamlit."""
import pytest
from core.indicators import (
    fraksi_bei, fraksi_step, coppock_curve,
    robust_std, hitung_bars_remaining,
)


class TestFraksiBei:
    def test_below_200(self):
        assert fraksi_bei(150) == 150

    def test_200_to_500(self):
        # Fraksi = 2 (harga 200–500)
        # 201/2 = 100.5 → banker's rounding → 100 → 200
        assert fraksi_bei(201) == 200
        assert fraksi_bei(203) == 204
        assert fraksi_bei(499) == 500        # 499/2 = 249.5 → 250 → 500
        assert fraksi_bei(300) == 300

    def test_500_to_2000(self):
        assert fraksi_bei(1003) == 1005

    def test_2000_to_5000(self):
        assert fraksi_bei(2455) == 2460

    def test_above_5000(self):
        assert fraksi_bei(5013) == 5025

    def test_invalid(self):
        assert fraksi_bei(None) == 0
        assert fraksi_bei(float('nan')) == 0
        assert fraksi_bei(-100) == 0
        assert fraksi_bei("abc") == 0


class TestFraksiStep:
    def test_tiers(self):
        assert fraksi_step(150) == 1
        assert fraksi_step(300) == 2
        assert fraksi_step(1000) == 5
        assert fraksi_step(3000) == 10
        assert fraksi_step(10000) == 25

    def test_invalid_returns_1(self):
        assert fraksi_step(None) == 1
        assert fraksi_step(-1) == 1


class TestCoppock:
    def test_insufficient_data(self):
        assert coppock_curve([100, 101, 102]) == (0.0, 0.0)

    def test_returns_tuple(self):
        prices = list(range(100, 200))  # 100 data
        curr, prev = coppock_curve(prices)
        assert isinstance(curr, float)
        assert isinstance(prev, float)


class TestRobustStd:
    def test_small_series(self):
        assert robust_std([1, 2, 3]) >= 0

    def test_outlier_resistant(self):
        normal = [10, 11, 10, 12, 11, 10, 11]
        with_outlier = normal + [10000]
        # robust_std harus berubah sedikit, std biasa meledak
        assert robust_std(with_outlier) < 5


class TestBarsRemaining:
    def test_minimum_one(self):
        from datetime import datetime
        dt = datetime(2024, 1, 1, 16, 0)
        assert hitung_bars_remaining(dt, "5m") >= 1