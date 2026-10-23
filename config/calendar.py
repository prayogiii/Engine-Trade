"""Kalender bursa & logika jam perdagangan BEI/IDX."""
from __future__ import annotations
from datetime import datetime, timedelta


# Key: "YYYY-MM-DD", Value: nama hari libur
LIBUR_BURSA: dict[str, str] = {
    "2025-01-01": "Tahun Baru Masehi", "2025-01-29": "Tahun Baru Imlek",
    "2025-03-14": "Hari Suci Nyepi", "2025-04-18": "Wafat Yesus Kristus",
    "2025-05-01": "Hari Buruh", "2025-05-29": "Kenaikan Yesus Kristus",
    "2025-05-30": "Hari Raya Waisak", "2025-06-06": "Idul Adha",
    "2025-06-27": "Tahun Baru Islam", "2025-08-17": "Hari Kemerdekaan",
    "2025-09-05": "Maulid Nabi", "2025-12-25": "Hari Raya Natal",
    "2026-01-01": "Tahun Baru Masehi", "2026-02-17": "Tahun Baru Imlek",
    "2026-03-03": "Hari Suci Nyepi", "2026-04-03": "Wafat Yesus Kristus",
    "2026-05-01": "Hari Buruh", "2026-05-14": "Kenaikan Yesus Kristus",
    "2026-05-15": "Hari Raya Waisak", "2026-05-25": "Idul Adha",
    "2026-06-15": "Tahun Baru Islam", "2026-08-17": "Hari Kemerdekaan",
    "2026-08-24": "Maulid Nabi", "2026-12-25": "Hari Raya Natal",
}


def dalam_jam_perdagangan(hour: int, minute: int, is_friday: bool = False) -> bool:
    """
    Cek apakah jam:menit ada di sesi I atau II BEI.

    Jam bursa BEI (April 2023 – sekarang):
      Senin-Kamis: Sesi I 09:00-12:00, Sesi II 13:30-15:49 WIB
      Jumat:       Sesi I 09:00-11:30, Sesi II 14:00-15:49 WIB
    (pra-penutupan 15:49-16:00 bukan sesi perdagangan reguler)

    is_friday: True untuk hari Jumat. Default False (Senin-Kamis).
    """
    t = hour * 60 + minute
    if is_friday:
        return (9 * 60 <= t <= 11 * 60 + 30) or (14 * 60 <= t <= 15 * 60 + 49)
    return (9 * 60 <= t <= 12 * 60) or (13 * 60 + 30 <= t <= 15 * 60 + 49)


def status_bursa(now_jkt: datetime) -> tuple[str, str]:
    """
    Return (level, pesan).
    level ∈ {"open", "closed", "weekend", "holiday"}
    """
    today_str = now_jkt.strftime("%Y-%m-%d")
    if today_str in LIBUR_BURSA:
        return "holiday", f"🔴 Bursa **TUTUP**: {LIBUR_BURSA[today_str]}"
    if now_jkt.weekday() >= 5:                       # 5=Sabtu, 6=Minggu
        return "weekend", "🔴 Akhir pekan — bursa tutup."

    is_friday = now_jkt.weekday() == 4
    if dalam_jam_perdagangan(now_jkt.hour, now_jkt.minute, is_friday=is_friday):
        return "open", "🟢 Bursa **TERBUKA** (Sesi I & II, tutup 15:49 WIB)"

    # Istirahat siang
    t = now_jkt.hour * 60 + now_jkt.minute
    if is_friday:
        if 11 * 60 + 30 < t < 14 * 60:
            return "closed", "⚪ Istirahat siang (11:30-14:00 WIB)."
    else:
        if 12 * 60 < t < 13 * 60 + 30:
            return "closed", "⚪ Istirahat siang (12:00-13:30 WIB)."

    return "closed", "⚪ Bursa **TUTUP** (di luar jam perdagangan)."


def libur_dalam_n_hari(now_jkt: datetime, days: int = 14) -> list[tuple[datetime, str]]:
    """Return [(tanggal, nama_libur), ...] untuk n hari ke depan."""
    out = []
    for date_str, desc in LIBUR_BURSA.items():
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        delta = (dt.date() - now_jkt.date()).days
        if 0 < delta <= days:
            out.append((dt, desc))
    return out


def hitung_hari_bursa(start_date, end_date) -> int:
    """Hitung jumlah hari bursa (Senin–Jumat, non-libur) antara start_date (eksklusif) dan end_date (inklusif)."""
    if isinstance(start_date, datetime):
        start_date = start_date.date()
    if isinstance(end_date, datetime):
        end_date = end_date.date()
    if start_date >= end_date:
        return 0
    cur = start_date + timedelta(days=1)
    n = 0
    while cur <= end_date:
        if cur.weekday() < 5 and cur.strftime("%Y-%m-%d") not in LIBUR_BURSA:
            n += 1
        cur += timedelta(days=1)
    return n


def tambah_hari_bursa(start, n: int):
    """
    Tambah n hari bursa ke `start`.
    Skip Sabtu/Minggu dan tanggal yang ada di LIBUR_BURSA.
    Return datetime dengan jam yang sama seperti `start`.
    """
    if isinstance(start, str):
        start = datetime.fromisoformat(start)
    cur = start
    added = 0
    while added < n:
        cur = cur + timedelta(days=1)
        if cur.weekday() >= 5:
            continue
        if cur.strftime("%Y-%m-%d") in LIBUR_BURSA:
            continue
        added += 1
    return cur
