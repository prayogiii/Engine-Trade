"""
Riwayat & outcome analysis — pure logic, tanpa Streamlit.

Berisi:
  - Statistik WR (win rate honest + NT rate)
  - WR per ticker
  - Diagnostik WR per bulan / regime / gaya
  - Dip entry extraction
  - Swing aktif detection
  - Sinyal perlu dicatat (urgent / active)
"""
from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime

import pytz

from config.calendar import hitung_hari_bursa


# ═══════════════════════════════════════════════════════════════
# STATISTIK WR
# ═══════════════════════════════════════════════════════════════
def hitung_statistik_riwayat_actual(riwayat_actual):
    """WR v2 — skip data misalign (< 2026-08-18), dedup by id(val)."""
    if not riwayat_actual or not isinstance(riwayat_actual, dict):
        return None

    seen_ids = set()
    total_win = 0
    total_loss = 0
    total_not_touched = 0

    win_sw, loss_sw = 0, 0
    win_dt, loss_dt = 0, 0

    for key, val in riwayat_actual.items():
        if not isinstance(val, dict):
            continue

        # Skip data misalign
        waktu = ""
        if isinstance(key, tuple) and len(key) >= 1:
            waktu = str(key[0])
        elif isinstance(val, dict):
            waktu = str(val.get("Waktu", ""))
        if waktu and waktu < "2026-08-18":
            continue

        # Dedup by id(val) — karena satu val di-map ke 2 key (SW + swing)
        vid = id(val)
        if vid in seen_ids:
            continue
        seen_ids.add(vid)

        outcome = val.get("Outcome", "")
        gaya = str(val.get("Mode", "")).upper()

        if outcome == "Win":
            total_win += 1
            if gaya == "SW":
                win_sw += 1
            elif gaya == "DT":
                win_dt += 1
        elif outcome == "Loss":
            total_loss += 1
            if gaya == "SW":
                loss_sw += 1
            elif gaya == "DT":
                loss_dt += 1
        elif outcome == "Not Touched" or val.get("Entry_Miss") == "Yes":
            total_not_touched += 1

    total_eval = total_win + total_loss
    total_all = total_eval + total_not_touched

    eval_sw = win_sw + loss_sw
    wr_sw = (win_sw / eval_sw * 100) if eval_sw > 0 else None

    eval_dt = win_dt + loss_dt
    wr_dt = (win_dt / eval_dt * 100) if eval_dt > 0 else None

    win_rate_honest = (total_win / total_all * 100) if total_all > 0 else None
    nt_rate = (total_not_touched / total_all * 100) if total_all > 0 else None

    return {
        "total_eval": total_eval,
        "total_all": total_all,
        "total_win": total_win,
        "total_loss": total_loss,
        "total_not_touched": total_not_touched,
        "win_rate": (total_win / total_eval * 100) if total_eval > 0 else None,
        "win_rate_honest": win_rate_honest,
        "nt_rate": nt_rate,
        "wr_sw": wr_sw,
        "eval_sw": eval_sw,
        "wr_dt": wr_dt,
        "eval_dt": eval_dt,
    }


def hitung_winrate_ticker_actual(ticker_raw, riwayat_actual):
    """WR khusus untuk 1 ticker."""
    if not riwayat_actual or not isinstance(riwayat_actual, dict):
        return None

    ticker_clean = str(ticker_raw).replace(".JK", "").upper().strip()
    seen_ids = set()
    win, loss, not_touched = 0, 0, 0

    for key, val in riwayat_actual.items():
        if not isinstance(val, dict):
            continue

        saham_key = ""
        if isinstance(key, tuple) and len(key) >= 2:
            saham_key = str(key[1]).replace(".JK", "").upper().strip()
        elif isinstance(key, str):
            saham_key = str(val.get("Saham", "")).replace(".JK", "").upper().strip()

        if saham_key != ticker_clean:
            continue

        obj_id = id(val)
        if obj_id in seen_ids:
            continue
        seen_ids.add(obj_id)

        outcome = val.get("Outcome", "")
        if outcome == "Win":
            win += 1
        elif outcome == "Loss":
            loss += 1
        elif outcome == "Not Touched" or val.get("Entry_Miss") == "Yes":
            not_touched += 1

    total = win + loss
    if total == 0:
        return {"win": 0, "loss": 0, "total": 0, "win_rate": None, "not_touched": not_touched}

    return {
        "win": win,
        "loss": loss,
        "total": total,
        "win_rate": (win / total) * 100,
        "not_touched": not_touched,
    }


# ═══════════════════════════════════════════════════════════════
# DIAGNOSTIK TREND WR
# ═══════════════════════════════════════════════════════════════
def diagnose_winrate_trend(riwayat_data, riwayat_actual):
    seen_keys = set()
    records = []

    for r in riwayat_data:
        waktu = r.get("Waktu", "")

        # Skip data misalign
        if waktu and waktu < "2026-08-18":
            continue

        saham = r.get("Saham", "")
        gaya = r.get("Gaya", "SW")
        regime = r.get("Rezim", "unknown")
        mode_actual = "swing" if gaya == "SW" else "daytrade"

        actual = (
            riwayat_actual.get((waktu, saham, gaya))
            or riwayat_actual.get((waktu, saham, mode_actual))
            or riwayat_actual.get((waktu, saham))
        )
        if not actual:
            continue

        dedup_key = (waktu, saham, gaya)
        if dedup_key in seen_keys:
            continue
        seen_keys.add(dedup_key)

        outcome = actual.get("Outcome", "")
        entry_miss = actual.get("Entry_Miss") == "Yes"

        try:
            bulan = waktu[:7]
        except Exception:
            bulan = "unknown"

        records.append({
            "bulan": bulan,
            "gaya": gaya,
            "regime": regime,
            "saham": saham,
            "outcome": "NT" if (entry_miss or outcome == "Not Touched")
                       else (outcome if outcome in ("Win", "Loss") else "kosong"),
        })

    per_bulan = defaultdict(lambda: {"win": 0, "loss": 0, "nt": 0})
    per_regime = defaultdict(lambda: {"win": 0, "loss": 0, "nt": 0})
    per_gaya = defaultdict(lambda: {"win": 0, "loss": 0, "nt": 0})

    for r in records:
        for bucket, key in [
            (per_bulan, r["bulan"]),
            (per_regime, r["regime"]),
            (per_gaya, r["gaya"]),
        ]:
            if r["outcome"] == "Win":
                bucket[key]["win"] += 1
            elif r["outcome"] == "Loss":
                bucket[key]["loss"] += 1
            elif r["outcome"] == "NT":
                bucket[key]["nt"] += 1

    return {
        "per_bulan": dict(sorted(per_bulan.items())),
        "per_regime": dict(per_regime),
        "per_gaya": dict(per_gaya),
        "total_records": len(records),
    }


# ═══════════════════════════════════════════════════════════════
# DIP ENTRY
# ═══════════════════════════════════════════════════════════════
def get_dip_entry(r):
    """Harga dip entry (RRR 1:2.0) dari record riwayat."""
    if not r or not isinstance(r, dict):
        return ""
    val = r.get("Entry_Ideal_RRR2", "")
    if val and str(val).strip() and str(val).strip() != "?":
        val_str = str(val).strip()
        return val_str if val_str.startswith("Rp") else f"Rp {val_str}"

    try:
        tp_str = r.get("TP_Harga") or r.get("TP_Range", "")
        sl_str = r.get("SL_Harga", "")

        clean_tp = str(tp_str).replace("Rp", "").replace(".", "").replace(",", "").strip()
        clean_sl = str(sl_str).replace("Rp", "").replace(".", "").replace(",", "").strip()

        tp_matches = re.findall(r"\d+", clean_tp)
        sl_matches = re.findall(r"\d+", clean_sl)

        if tp_matches and sl_matches:
            tp_val = float(tp_matches[0])
            sl_val = float(sl_matches[0])
            if tp_val > sl_val:
                dip_val = (tp_val + 2 * sl_val) / 3.0
                return f"Rp {dip_val:,.0f}"
    except Exception:
        pass
    return ""


# ═══════════════════════════════════════════════════════════════
# SWING AKTIF
# ═══════════════════════════════════════════════════════════════
def _has_actual_data(actual_data) -> bool:
    """Helper — cek apakah outcome sudah diisi."""
    if not actual_data:
        return False
    return bool(
        actual_data.get("Actual_High")
        or actual_data.get("Actual_Low")
        or actual_data.get("Actual_Close")
        or actual_data.get("Outcome")
        or actual_data.get("Entry_Miss") == "Yes"
    )


def dapatkan_dict_swing_aktif(riwayat_data, riwayat_actual):
    """
    Dict {saham_clean: item_info} untuk emiten dengan Swing (SW) aktif.
    Belum diisi outcome & belum kadaluarsa (< 7 hari bursa).
    """
    active_map = {}
    now_jkt = datetime.now(pytz.timezone("Asia/Jakarta"))
    today_date = now_jkt.date()

    for r in riwayat_data:
        waktu_str = str(r.get("Waktu", ""))
        saham = str(r.get("Saham", "")).strip().upper()
        saham_clean = saham.replace(".JK", "")
        gaya = str(r.get("Gaya", "SW")).strip().upper()

        if gaya not in ("SW", "SWING"):
            continue

        mode_actual = "swing"

        actual_data = (
            riwayat_actual.get((waktu_str, saham, gaya))
            or riwayat_actual.get((waktu_str, saham_clean, gaya))
            or riwayat_actual.get((waktu_str, saham, mode_actual))
            or riwayat_actual.get((waktu_str, saham_clean, mode_actual))
            or riwayat_actual.get((waktu_str, saham))
            or riwayat_actual.get((waktu_str, saham_clean))
        )

        if _has_actual_data(actual_data):
            continue

        try:
            dt_sinyal = datetime.strptime(waktu_str.split()[0], "%Y-%m-%d").date()
        except Exception:
            dt_sinyal = today_date

        b_days = hitung_hari_bursa(dt_sinyal, today_date)

        if b_days < 7 and saham_clean not in active_map:
            active_map[saham_clean] = {
                "record": r,
                "waktu": waktu_str,
                "saham": saham_clean,
                "gaya": gaya,
                "b_days": b_days,
                "dt_sinyal": dt_sinyal,
            }

    return active_map


def dapatkan_sinyal_perlu_dicatat(riwayat_data, riwayat_actual):
    """
    Return (urgent_items, active_swing_items).
    - urgent: DT sesi lalu atau SW ≥ 7 hari bursa
    - active: SW 1–6 hari bursa
    """
    urgent_items = []
    active_swing_items = []
    now_jkt = datetime.now(pytz.timezone("Asia/Jakarta"))
    today_date = now_jkt.date()

    for r in riwayat_data:
        _sinyal_upper = str(r.get("Sinyal", "")).upper()
        if "AVOID" in _sinyal_upper:
            continue
        waktu_str = r.get("Waktu", "")
        saham = r.get("Saham", "")
        gaya = r.get("Gaya", "SW")
        mode_actual = "swing" if gaya == "SW" else "daytrade"

        actual_data = (
            riwayat_actual.get((waktu_str, saham, gaya))
            or riwayat_actual.get((waktu_str, saham, mode_actual))
            or riwayat_actual.get((waktu_str, saham))
        )

        if _has_actual_data(actual_data):
            continue

        try:
            dt_sinyal = datetime.strptime(waktu_str.split()[0], "%Y-%m-%d").date()
        except Exception:
            dt_sinyal = today_date

        b_days = hitung_hari_bursa(dt_sinyal, today_date)

        item = {
            "record": r,
            "waktu": waktu_str,
            "saham": saham,
            "gaya": gaya,
            "mode_actual": mode_actual,
            "b_days": b_days,
            "dt_sinyal": dt_sinyal,
        }

        if gaya == "DT" or mode_actual == "daytrade":
            if dt_sinyal < today_date:
                item["alasan"] = f"Daytrade Sesi Sebelumnya ({waktu_str})"
                urgent_items.append(item)
        else:
            if b_days >= 7:
                item["alasan"] = f"Mencapai Batas Maksimal 7 Hari Bursa ({b_days} hari kerja)"
                urgent_items.append(item)
            elif b_days >= 1:
                item["alasan"] = f"Swing Berjalan (Hari bursa ke-{b_days})"
                active_swing_items.append(item)

    return urgent_items, active_swing_items
