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


def dalam_jam_perdagangan(hour: int, minute: int) -> bool:
    """Cek apakah jam:menit ada di sesi I atau II BEI."""
    sesi1 = (hour == 9 and minute >= 0) or (10 <= hour < 12) or (hour == 12 and minute == 0)
    sesi2 = (hour == 13 and minute >= 30) or (hour == 14) or (hour == 15 and minute == 0)
    return sesi1 or sesi2


def status_bursa(now_jkt: datetime) -> tuple[str, str]:
    """
    Return (level, pesan).
    level ∈ {"open", "closed", "weekend", "holiday"}
    """
    today_str = now_jkt.strftime("%Y-%m-%d")
    today_day = now_jkt.strftime("%A")
    if today_str in LIBUR_BURSA:
        return "holiday", f"🔴 Bursa **TUTUP**: {LIBUR_BURSA[today_str]}"
    if today_day in ("Saturday", "Sunday"):
        return "weekend", "🔴 Akhir pekan — bursa tutup."
    if dalam_jam_perdagangan(now_jkt.hour, now_jkt.minute):
        return "open", "🟢 Bursa **TERBUKA** (09:00-12:00 & 13:30-15:00 WIB)"
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
    """Hitung jumlah hari bursa (Senin–Jumat) antara start_date (eksklusif) dan end_date (inklusif)."""
    if isinstance(start_date, datetime):
        start_date = start_date.date()
    if isinstance(end_date, datetime):
        end_date = end_date.date()
    if start_date >= end_date:
        return 0
    cur = start_date + timedelta(days=1)
    n = 0
    while cur <= end_date:
        if cur.weekday() < 5:
            n += 1
        cur += timedelta(days=1)
    return n