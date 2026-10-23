"""Test — cek AVOID match antara riwayat dan riwayat_actual."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.sheets_client import get_gsheet


def test_avoid_check():
    ws = get_gsheet().worksheet("riwayat")
    records = ws.get_all_records()

    print(f"\n=== RIWAYAT ===")
    print(f"Total: {len(records)}")
    if records:
        print(f"Kolom: {list(records[0].keys())}")

    # Cari AVOID
    avoid_rows = [r for r in records if "AVOID" in str(r.get("Sinyal", "")).upper()]
    print(f"\nTotal AVOID di riwayat: {len(avoid_rows)}")
    print("\nSample 5 AVOID:")
    for r in avoid_rows[:5]:
        print(f"  Waktu={repr(str(r.get('Waktu','')))} | "
              f"Saham={repr(r.get('Saham',''))} | Gaya={repr(r.get('Gaya',''))}")

    # === RIWAYAT_ACTUAL ===
    actual_ws = get_gsheet().worksheet("riwayat_actual")
    actual = actual_ws.get_all_records()
    print(f"\n=== RIWAYAT_ACTUAL ===")
    print(f"Total: {len(actual)}")
    print("\nSample 5:")
    for r in actual[:5]:
        print(f"  Waktu={repr(str(r.get('Waktu','')))} | "
              f"Saham={repr(r.get('Saham',''))} | "
              f"Mode={repr(r.get('Mode',''))} | "
              f"Outcome={repr(r.get('Outcome',''))} | "
              f"Entry_Miss={repr(r.get('Entry_Miss',''))}")

    # Test match
    print(f"\n=== MATCH TEST ===")
    avoid_keys = set()
    for r in avoid_rows:
        w = str(r.get("Waktu", ""))[:16]
        s = str(r.get("Saham", "")).replace(".JK", "").strip().upper()
        avoid_keys.add((w, s))

    matched = 0
    for r in actual:
        w = str(r.get("Waktu", ""))[:16]
        s = str(r.get("Saham", "")).replace(".JK", "").strip().upper()
        if (w, s) in avoid_keys:
            matched += 1

    print(f"Baris di riwayat_actual yang match AVOID: {matched}")


if __name__ == "__main__":
    test_avoid_check()