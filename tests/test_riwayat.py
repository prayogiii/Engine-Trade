"""Unit test core.riwayat."""
import pytest

from core.riwayat import (
    hitung_statistik_riwayat_actual,
    hitung_winrate_ticker_actual,
    get_dip_entry,
    diagnose_winrate_trend,
    dapatkan_dict_swing_aktif,
    dapatkan_sinyal_perlu_dicatat,
)


class TestHitungStatistik:
    def test_empty(self):
        assert hitung_statistik_riwayat_actual({}) is None
        assert hitung_statistik_riwayat_actual(None) is None

    def test_all_wins(self):
        actual = {
            ("2026-01-01", "BBRI", "SW"): {"Outcome": "Win", "Mode": "SW"},
            ("2026-01-02", "TLKM", "SW"): {"Outcome": "Win", "Mode": "SW"},
        }
        result = hitung_statistik_riwayat_actual(actual)
        assert result["total_win"] == 2
        assert result["win_rate"] == 100.0

    def test_mixed_with_nt(self):
        actual = {
            ("a", "BBRI", "SW"): {"Outcome": "Win", "Mode": "SW"},
            ("b", "TLKM", "SW"): {"Outcome": "Loss", "Mode": "SW"},
            ("c", "ASII", "SW"): {"Outcome": "Not Touched", "Mode": "SW"},
        }
        result = hitung_statistik_riwayat_actual(actual)
        assert result["total_win"] == 1
        assert result["total_loss"] == 1
        assert result["total_not_touched"] == 1
        assert result["win_rate"] == 50.0
        assert result["win_rate_honest"] == pytest.approx(33.33, rel=0.01)


class TestWinrateTicker:
    def test_no_data(self):
        assert hitung_winrate_ticker_actual("BBRI", {}) is None

    def test_ticker_filter(self):
        actual = {
            ("2026-01-01", "BBRI", "SW"): {"Outcome": "Win"},
            ("2026-01-02", "TLKM", "SW"): {"Outcome": "Loss"},
            ("2026-01-03", "BBRI", "SW"): {"Outcome": "Loss"},
        }
        result = hitung_winrate_ticker_actual("BBRI", actual)
        assert result["total"] == 2
        assert result["win_rate"] == 50.0


class TestGetDipEntry:
    def test_from_entry_ideal(self):
        r = {"Entry_Ideal_RRR2": "Rp 5,000"}
        assert get_dip_entry(r) == "Rp 5,000"

    def test_from_entry_ideal_no_prefix(self):
        r = {"Entry_Ideal_RRR2": "5000"}
        assert get_dip_entry(r) == "Rp 5000"

    def test_compute_from_tp_sl(self):
        r = {"TP_Harga": "Rp 6,000", "SL_Harga": "Rp 4,000"}
        # (6000 + 2*4000) / 3 = 4666.67
        assert "4,667" in get_dip_entry(r) or "4666" in get_dip_entry(r)

    def test_empty(self):
        assert get_dip_entry({}) == ""
        assert get_dip_entry(None) == ""


class TestDapatkanSwingAktif:
    def test_empty(self):
        assert dapatkan_dict_swing_aktif([], {}) == {}

    def test_active_swing(self):
        from datetime import datetime, timedelta
        recent = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d %H:%M")
        riwayat = [{
            "Waktu": recent,
            "Saham": "BBRI",
            "Gaya": "SW",
        }]
        result = dapatkan_dict_swing_aktif(riwayat, {})
        assert "BBRI" in result
        assert result["BBRI"]["b_days"] == 1

    def test_old_swing_excluded(self):
        from datetime import datetime, timedelta
        old = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d %H:%M")
        riwayat = [{"Waktu": old, "Saham": "BBRI", "Gaya": "SW"}]
        result = dapatkan_dict_swing_aktif(riwayat, {})
        assert "BBRI" not in result


class TestSinyalPerluDicatat:
    def test_avoid_skipped(self):
        riwayat = [{
            "Waktu": "2026-01-01 10:00", "Saham": "BBRI",
            "Gaya": "SW", "Sinyal": "AVOID",
        }]
        urgent, active = dapatkan_sinyal_perlu_dicatat(riwayat, {})
        assert len(urgent) == 0
        assert len(active) == 0

    def test_empty(self):
        urgent, active = dapatkan_sinyal_perlu_dicatat([], {})
        assert urgent == []
        assert active == []