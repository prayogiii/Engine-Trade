"""
Test jam bursa BEI & hitung_bars_remaining.

Referensi jam bursa (April 2023 – sekarang):
  Senin-Kamis: Sesi I 09:00-12:00, Sesi II 13:30-15:49 WIB
  Jumat:       Sesi I 09:00-11:30, Sesi II 14:00-15:49 WIB
"""
from datetime import datetime
import pytest

from config.calendar import dalam_jam_perdagangan, status_bursa
from core.indicators import hitung_bars_remaining


def _dt(y, mo, d, h, mi):
    return datetime(y, mo, d, h, mi)


# ═══════════════════════════════════════════════════════════════
# dalam_jam_perdagangan — Senin-Kamis
# ═══════════════════════════════════════════════════════════════
@pytest.mark.parametrize("hour,minute,expected", [
    (8, 59, False),
    (9, 0,  True),
    (10, 0, True),
    (11, 59, True),
    (12, 0, True),    # tick terakhir sesi I
    (12, 1, False),   # istirahat
    (13, 0, False),
    (13, 29, False),
    (13, 30, True),   # sesi II mulai
    (14, 30, True),
    (15, 48, True),
    (15, 49, True),   # tick terakhir sesi II
    (15, 50, False),  # pra-penutupan
    (16, 0, False),
])
def test_dalam_jam_senin_kamis(hour, minute, expected):
    assert dalam_jam_perdagangan(hour, minute, is_friday=False) is expected


# ═══════════════════════════════════════════════════════════════
# dalam_jam_perdagangan — Jumat
# ═══════════════════════════════════════════════════════════════
@pytest.mark.parametrize("hour,minute,expected", [
    (9, 0,  True),
    (11, 29, True),
    (11, 30, True),   # tick terakhir sesi I Jumat
    (11, 31, False),  # istirahat Jumat 11:30-14:00
    (12, 0, False),
    (13, 0, False),
    (13, 59, False),
    (14, 0, True),    # sesi II Jumat mulai
    (15, 49, True),
    (15, 50, False),
])
def test_dalam_jam_jumat(hour, minute, expected):
    assert dalam_jam_perdagangan(hour, minute, is_friday=True) is expected


# ═══════════════════════════════════════════════════════════════
# hitung_bars_remaining — Senin-Kamis
# ═══════════════════════════════════════════════════════════════
def test_remaining_monday_before_open():
    # Senin 08:30 — semua sesi tersedia: 319 min / 5 = 64
    assert hitung_bars_remaining(_dt(2026, 9, 7, 8, 30), "5m") == 64


def test_remaining_monday_0930():
    # 09:30 → sisa 150 sesi I + 139 sesi II = 289 → ceil(289/5) = 58
    assert hitung_bars_remaining(_dt(2026, 9, 7, 9, 30), "5m") == 58


def test_remaining_monday_1130():
    # 11:30 → 30 + 139 = 169 → ceil(169/5) = 34
    assert hitung_bars_remaining(_dt(2026, 9, 7, 11, 30), "5m") == 34


def test_remaining_monday_lunch_break():
    # 12:30 → istirahat, tinggal sesi II 139 min → 28
    assert hitung_bars_remaining(_dt(2026, 9, 7, 12, 30), "5m") == 28


def test_remaining_monday_1400():
    # 14:00 → 109 min sisa → ceil(109/5) = 22 (dulu return 12: BUG)
    assert hitung_bars_remaining(_dt(2026, 9, 7, 14, 0), "5m") == 22


def test_remaining_monday_1548():
    assert hitung_bars_remaining(_dt(2026, 9, 7, 15, 48), "5m") == 1


def test_remaining_monday_1549():
    assert hitung_bars_remaining(_dt(2026, 9, 7, 15, 49), "5m") == 1


def test_remaining_monday_after_close():
    assert hitung_bars_remaining(_dt(2026, 9, 7, 15, 50), "5m") == 1


# ═══════════════════════════════════════════════════════════════
# hitung_bars_remaining — Jumat
# ═══════════════════════════════════════════════════════════════
def test_remaining_friday_1100():
    # Jumat 11:00 → 30 + 109 = 139 → ceil(139/5) = 28
    assert hitung_bars_remaining(_dt(2026, 9, 11, 11, 0), "5m") == 28


def test_remaining_friday_break():
    # Jumat 12:00 → istirahat, sisa sesi II 109 min = 22
    assert hitung_bars_remaining(_dt(2026, 9, 11, 12, 0), "5m") == 22


def test_remaining_friday_1330_still_break():
    # Jumat 13:30 → MASIH istirahat (bukan sesi II spt Senin-Kamis), sisa 109 min = 22
    assert hitung_bars_remaining(_dt(2026, 9, 11, 13, 30), "5m") == 22


def test_remaining_friday_1430():
    # Jumat 14:30 → sesi II sudah jalan, sisa 79 min → ceil(79/5) = 16
    assert hitung_bars_remaining(_dt(2026, 9, 11, 14, 30), "5m") == 16


# ═══════════════════════════════════════════════════════════════
# hitung_bars_remaining — Weekend
# ═══════════════════════════════════════════════════════════════
def test_remaining_saturday():
    assert hitung_bars_remaining(_dt(2026, 9, 12, 10, 0), "5m") == 64


def test_remaining_sunday():
    assert hitung_bars_remaining(_dt(2026, 9, 13, 10, 0), "5m") == 64


# ═══════════════════════════════════════════════════════════════
# Konsistensi antar interval
# ═══════════════════════════════════════════════════════════════
def test_remaining_interval_consistency_monday_1400():
    """14:00 Senin → sisa 109 menit. Konversi konsisten."""
    dt = _dt(2026, 9, 7, 14, 0)
    assert hitung_bars_remaining(dt, "5m")  == 22   # ceil(109/5)
    assert hitung_bars_remaining(dt, "15m") == 8    # ceil(109/15)
    assert hitung_bars_remaining(dt, "30m") == 4    # ceil(109/30)
    assert hitung_bars_remaining(dt, "60m") == 2    # ceil(109/60)


# ═══════════════════════════════════════════════════════════════
# status_bursa
# ═══════════════════════════════════════════════════════════════
def test_status_open_monday():
    assert status_bursa(_dt(2026, 9, 7, 10, 0))[0] == "open"


def test_status_break_monday():
    assert status_bursa(_dt(2026, 9, 7, 12, 30))[0] == "closed"


def test_status_open_friday_morning():
    assert status_bursa(_dt(2026, 9, 11, 10, 0))[0] == "open"


def test_status_friday_long_break():
    # Jumat 13:30 harus closed (Mon-Kamis sudah open)
    assert status_bursa(_dt(2026, 9, 11, 13, 30))[0] == "closed"
    # Jumat 14:30 harus open
    assert status_bursa(_dt(2026, 9, 11, 14, 30))[0] == "open"


def test_status_weekend():
    assert status_bursa(_dt(2026, 9, 12, 10, 0))[0] == "weekend"


def test_status_holiday():
    # 2025-12-25 (Kamis) = Hari Raya Natal
    assert status_bursa(_dt(2025, 12, 25, 10, 0))[0] == "holiday"


def test_status_after_close():
    assert status_bursa(_dt(2026, 9, 7, 16, 0))[0] == "closed"