"""
Google Sheets client — semua operasi baca/tulis ke spreadsheet QuantRisk Pro.

Dipisah dari main.py supaya:
  - Testable tanpa runtime Streamlit UI
  - Cache invalidation terpusat
  - Error handling konsisten

Catatan: Modul ini masih menggunakan `st.secrets`, `st.session_state`, `st.cache_data`.
Itu by design — services boleh bergantung pada konteks Streamlit, yang PENTING
adalah UI (rendering) TIDAK bercampur dengan I/O.
"""
from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timedelta
from config.calendar import tambah_hari_bursa
import gspread
import numpy as np
import pandas as pd
import pytz
import streamlit as st
import yfinance as yf
from google.oauth2.service_account import Credentials

from core.signal import parse_signal_category as _parse_signal_category
from config.settings import FACTOR_KEYS, TTL_BROKSUM_CACHE, SUSPEND_TIMEOUT_BDAYS
from core.scoring import compute_memory_update_math, compute_entry_error_update
from core.bandarmology import (
    klasifikasi_broker,
    parse_broker_list as _parse_broker_list,
)
from config.brokers import BROKER_TYPES
from core.indicators import safe_float

# ═══════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════
def _to_float(v, default=0.0):
    """
    Parse angka dari Sheets — handle format Indonesia (koma desimal).

    Contoh:
      "0,02"        → 0.02
      "1.234,56"    → 1234.56
      "1,234.56"    → 1234.56
      "1.234"       → 1234.0   (anggap titik = ribuan)
      "1234.56"     → 1234.56
      0.02          → 0.02
      "" / None     → default
    """
    if v is None or v == "":
        return default
    if isinstance(v, bool):
        return float(v)
    if isinstance(v, (int, float)):
        return float(v)

    s = str(v).strip()
    if not s:
        return default

    has_comma = "," in s
    has_dot = "." in s

    if has_comma and has_dot:
        # Format yang lebih umum: titik ribuan, koma desimal
        # "1.234,56" → 1234.56
        # Tapi handle juga "1,234.56" (US)
        # Heuristik: yang muncul terakhir = desimal
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif has_comma:
        # Cuma koma → koma = desimal
        # "0,02" → 0.02
        s = s.replace(",", ".")
    # else: cuma titik atau tidak ada pemisah → biarkan

    try:
        return float(s)
    except ValueError:
        return default


def _is_evaluated(val) -> bool:
    """Cek apakah kolom `evaluated` bernilai True, terlepas dari format."""
    if isinstance(val, bool):
        return val
    return str(val).strip().upper() in ("TRUE", "YES", "1", "Y")


# ═══════════════════════════════════════════════════════════════
# KONEKSI
# ═══════════════════════════════════════════════════════════════
def get_gsheet():
    """
    Mengembalikan objek spreadsheet.

    Dual-context auth (Poin 7):
      - Cron: env var CRON_GCP_CREDENTIALS_PATH + CRON_SHEET_ID (file-based).
      - Streamlit UI: st.secrets (fallback default).
    """
    cron_creds = os.getenv("CRON_GCP_CREDENTIALS_PATH")
    cron_sheet = os.getenv("CRON_SHEET_ID")
    if cron_creds and cron_sheet:
        creds = Credentials.from_service_account_file(
            cron_creds,
            scopes=["https://www.googleapis.com/auth/spreadsheets"],
        )
        client = gspread.authorize(creds)
        return client.open_by_key(cron_sheet)

    creds = Credentials.from_service_account_info(
        st.secrets["gcp_service_account"],
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
    )
    client = gspread.authorize(creds)
    return client.open_by_key(st.secrets["google_sheets"]["sheet_id"])


def init_sheets():
    """Membuat semua worksheet yang diperlukan jika belum ada."""
    try:
        sheet = get_gsheet()
        existing = {ws.title: ws for ws in sheet.worksheets()}

        if "riwayat" not in existing:
            sheet.add_worksheet("riwayat", rows=3000, cols=35)

        if "v12_memory" not in existing:
            sheet.add_worksheet("v12_memory", rows=100, cols=3)

        if "v12_predictions" not in existing:
            sheet.add_worksheet("v12_predictions", rows=500, cols=9)
        else:
            ws = existing["v12_predictions"]
            if ws.col_count < 9:
                ws.add_cols(9 - ws.col_count)

        if "riwayat_actual" not in existing:
            ws = sheet.add_worksheet("riwayat_actual", rows=100, cols=8)
            ws.update(
                "A1:H1",
                [["Waktu", "Saham", "Mode", "Actual_High", "Actual_Low",
                  "Actual_Close", "Outcome", "Entry_Miss"]],
                value_input_option="RAW",
            )

        if "broksum_history" not in existing:
            ws = sheet.add_worksheet("broksum_history", rows=2000, cols=8)
            ws.update(
                "A1:H1",
                [["ticker", "upload_date", "bandarmology_status", "top_buyers",
                  "top_sellers", "summary_narrative", "full_data", "source"]],
                value_input_option="RAW",
            )

        if "foreign_flow_history" not in existing:
            ws = sheet.add_worksheet("foreign_flow_history", rows=5000, cols=7)
            ws.update(
                "A1:G1",
                [["ticker", "date", "close",
                  "foreign_buy", "foreign_sell", "net_foreign", "source"]],
                value_input_option="RAW",
            )

        if "signal_outcomes" not in existing:
            ws = sheet.add_worksheet("signal_outcomes", rows=10000, cols=15)
            ws.update("A1:O1", [[
                "timestamp", "ticker", "mode", "signal", "signal_category",
                "regime", "price_at_signal", "horizon_days",
                "expected_direction", "expected_magnitude",
                "evaluated", "price_at_horizon", "actual_return",
                "was_correct", "evaluated_at",
            ]], value_input_option="RAW")
    except Exception as e:
        st.error(f"❌ Gagal inisialisasi Google Sheets: {e}")


# ═══════════════════════════════════════════════════════════════
# CACHE BROKSUM (session-level, hemat quota Sheets)
# ═══════════════════════════════════════════════════════════════
def get_broksum_cache(force_refresh: bool = False) -> list:
    """Baca broksum_history sekali per sesi, cache di session_state."""
    now = time.time()
    cache_age = now - st.session_state.get("_broksum_cache_time", 0)
    cache_exists = "broksum_cache" in st.session_state

    need_refresh = (
        force_refresh
        or not cache_exists
        or cache_age > TTL_BROKSUM_CACHE
    )

    if need_refresh:
        try:
            sheet = get_gsheet().worksheet("broksum_history")
            st.session_state.broksum_cache = sheet.get_all_records()
            st.session_state._broksum_cache_time = now
        except Exception as e:
            if not cache_exists:
                st.session_state.broksum_cache = []
            st.session_state._broksum_cache_time = now
            st.session_state._broksum_cache_error = str(e)

    return st.session_state.get("broksum_cache", [])


def invalidate_broksum_cache():
    """Paksa refresh cache broksum di rerun berikutnya."""
    st.session_state._broksum_cache_time = 0


# ═══════════════════════════════════════════════════════════════
# V12 MEMORY (self-learning weights)
# ═══════════════════════════════════════════════════════════════
def load_v12_memory() -> dict:
    mem = {}
    try:
        sheet = get_gsheet().worksheet("v12_memory")
        records = sheet.get_all_records()
        for row in records:
            t = row.get("ticker")
            if t and "data" in row and row["data"]:
                try:
                    mem[t] = json.loads(row["data"])
                except Exception:
                    pass
    except Exception as e:
        st.error(f"Gagal memuat V12 memory: {e}")
    return mem


def save_v12_memory(mem: dict):
    try:
        sheet = get_gsheet().worksheet("v12_memory")
        rows = [{"ticker": t, "data": json.dumps(d)} for t, d in mem.items()]
        sheet.clear()
        if rows:
            all_values = [["ticker", "data"]] + [
                [r["ticker"], r["data"]] for r in rows
            ]
            sheet.update(all_values, value_input_option="RAW")
    except Exception as e:
        st.error(f"Gagal menyimpan V12 memory: {e}")


# ═══════════════════════════════════════════════════════════════
# V12 PREDICTIONS
# ═══════════════════════════════════════════════════════════════
def load_v12_predictions(ticker: str, mode: str = "swing"):
    try:
        sheet = get_gsheet().worksheet("v12_predictions")
        records = sheet.get_all_records()
        for row in records:
            if row.get("ticker") == ticker and row.get("mode") == mode:
                return row
        return None
    except Exception as e:
        st.error(f"Gagal memuat prediksi: {e}")
        return None


def save_v12_prediction(ticker, close_price, factor_signals,
                        entry_low=None, entry_high=None, mode="swing"):
    try:
        sheet = get_gsheet()
        ws = sheet.worksheet("v12_predictions")
        new_row = {
            "ticker": ticker,
            "mode": mode,
            "close_price": close_price,
            "timestamp": datetime.now(pytz.timezone("Asia/Jakarta")).strftime("%Y-%m-%d %H:%M:%S"),
            "entry_low": entry_low,
            "entry_high": entry_high,
        }
        for k in FACTOR_KEYS:
            new_row[f"sig_{k}"] = factor_signals.get(k, 0.0)

        headers = list(new_row.keys())
        if ws.col_count < len(headers):
            ws.add_cols(len(headers) - ws.col_count)

        last_col = chr(64 + len(headers))
        ws.update(f"A1:{last_col}1", [headers], value_input_option="RAW")

        records = ws.get_all_records()
        row_index = None
        for i, row in enumerate(records):
            if row.get("ticker") == ticker and row.get("mode") == mode:
                row_index = i + 2
                break

        values = [new_row[h] for h in headers]
        if row_index:
            ws.update(f"A{row_index}:{last_col}{row_index}", [values], value_input_option="RAW")
        else:
            ws.append_row(values, value_input_option="RAW")
    except Exception as e:
        st.error(f"Gagal menyimpan prediksi: {e}")


# ═══════════════════════════════════════════════════════════════
# BROKSUM HISTORY
# ═══════════════════════════════════════════════════════════════
def save_broksum_data(ticker, res_json, source="gemini") -> bool:
    """Simpan hasil parsing broker flow ke broksum_history."""
    try:
        sheet = get_gsheet()
        ws = sheet.worksheet("broksum_history")
        upload_date = datetime.now(pytz.timezone("Asia/Jakarta")).strftime("%Y-%m-%d %H:%M:%S")

        new_row = {
            "ticker": ticker.upper(),
            "upload_date": upload_date,
            "bandarmology_status": res_json.get("bandarmology_status", "N/A"),
            "top_buyers": json.dumps(res_json.get("top_buyers", [])),
            "top_sellers": json.dumps(res_json.get("top_sellers", [])),
            "summary_narrative": res_json.get("summary_narrative", ""),
            "full_data": json.dumps(res_json),
            "source": source,
        }

        try:
            headers = ws.row_values(1)
            if not headers or headers[0] != "ticker":
                ws.update(
                    "A1:H1",
                    [["ticker", "upload_date", "bandarmology_status", "top_buyers",
                      "top_sellers", "summary_narrative", "full_data", "source"]],
                    value_input_option="RAW",
                )
        except Exception:
            ws.update(
                "A1:H1",
                [["ticker", "upload_date", "bandarmology_status", "top_buyers",
                  "top_sellers", "summary_narrative", "full_data", "source"]],
                value_input_option="RAW",
            )

        values = [
            new_row["ticker"], new_row["upload_date"], new_row["bandarmology_status"],
            new_row["top_buyers"], new_row["top_sellers"],
            new_row["summary_narrative"], new_row["full_data"], new_row["source"],
        ]
        ws.insert_row(values, index=2, value_input_option="RAW")
        return True
    except Exception as e:
        st.error(f"❌ Gagal menyimpan broker flow ke Sheets: {e}")
        return False


def load_broksum_history(ticker) -> list:
    """Filter broksum history dari cache session."""
    try:
        records = get_broksum_cache()
        ticker_upper = str(ticker).upper().replace(".JK", "").strip()
        return [
            r for r in records
            if str(r.get("ticker", "")).upper() == ticker_upper
        ]
    except Exception as e:
        st.error(f"❌ Gagal memuat broker flow history: {e}")
        return []


def get_latest_broksum_for_ticker(ticker):
    """Ambil data broker flow terbaru untuk ticker tertentu."""
    try:
        history = load_broksum_history(ticker)
        if history:
            latest = history[0]
            return {
                "ticker": latest.get("ticker"),
                "upload_date": latest.get("upload_date"),
                "bandarmology_status": latest.get("bandarmology_status"),
                "top_buyers": json.loads(latest.get("top_buyers", "[]")),
                "top_sellers": json.loads(latest.get("top_sellers", "[]")),
                "summary_narrative": latest.get("summary_narrative"),
                "full_data": json.loads(latest.get("full_data", "{}")),
            }
        return None
    except Exception as e:
        st.error(f"❌ Error get latest broksum: {e}")
        return None


# ═══════════════════════════════════════════════════════════════
# FOREIGN FLOW
# ═══════════════════════════════════════════════════════════════
def save_foreign_flow_snapshot(ticker) -> bool:
    """Ambil foreign flow IDX hari ini & simpan ke sheet (skip kalau duplikat)."""
    try:
        ticker_clean = str(ticker).upper().replace(".JK", "").strip()
        if not ticker_clean:
            return False

        today_wib = datetime.now(pytz.timezone("Asia/Jakarta")).strftime("%Y-%m-%d")

        # Pre-check duplikat
        try:
            _sheet = get_gsheet().worksheet("foreign_flow_history")
            _records = _sheet.get_all_records()
            for r in _records:
                if (str(r.get("ticker", "")).upper() == ticker_clean
                        and str(r.get("date", "")) == today_wib):
                    return True
        except Exception:
            pass

        # Lazy import — hindari circular dengan yfinance_client
        from services.yfinance_client import _fetch_idx_all_stock_summary
        items = _fetch_idx_all_stock_summary()
        if not items:
            return False

        row_data = None
        for it in items:
            if not isinstance(it, dict):
                continue
            code = str(it.get("StockCode", "")).upper().strip()
            if code != ticker_clean:
                continue

            def _f(k):
                v = it.get(k)
                if v in (None, "", "N/A", "-"):
                    return 0.0
                try:
                    return float(str(v).replace(",", ""))
                except Exception:
                    return 0.0

            fb = _f("ForeignBuy")
            fs = _f("ForeignSell")
            close = _f("Close")

            fb_rp = fb * close if close > 0 else 0.0
            fs_rp = fs * close if close > 0 else 0.0

            date_str = str(it.get("Date") or "")[:10]
            if not date_str:
                date_str = datetime.now(pytz.timezone("Asia/Jakarta")).strftime("%Y-%m-%d")

            row_data = {
                "ticker": ticker_clean,
                "date": date_str,
                "close": close,
                "foreign_buy": fb_rp,
                "foreign_sell": fs_rp,
                "net_foreign": fb_rp - fs_rp,
                "source": "idx",
            }
            break

        if not row_data:
            return False

        sheet = get_gsheet().worksheet("foreign_flow_history")
        records = sheet.get_all_records()
        for r in records:
            if (str(r.get("ticker", "")).upper() == row_data["ticker"]
                    and str(r.get("date", "")) == row_data["date"]):
                return True

        sheet.insert_row([
            row_data["ticker"], row_data["date"], row_data["close"],
            row_data["foreign_buy"], row_data["foreign_sell"],
            row_data["net_foreign"], row_data["source"],
        ], index=2, value_input_option="RAW")
        return True
    except Exception as e:
        st.error(f"❌ Gagal simpan foreign flow snapshot: {e}")
        return False


def load_foreign_flow_history(ticker, days: int = 30):
    """Ambil history foreign flow dari sheet → DataFrame atau None."""
    try:
        ticker_clean = str(ticker).upper().replace(".JK", "").strip()
        sheet = get_gsheet().worksheet("foreign_flow_history")
        records = sheet.get_all_records()

        rows = []
        for r in records:
            if str(r.get("ticker", "")).upper() != ticker_clean:
                continue
            try:
                rows.append({
                    "date": str(r.get("date", "")),
                    "close": _to_float(r.get("close", 0)),
                    "foreign_buy": _to_float(r.get("foreign_buy", 0)),
                    "foreign_sell": _to_float(r.get("foreign_sell", 0)),
                    "net_foreign": _to_float(r.get("net_foreign", 0)),
                })
            except Exception:
                continue

        if not rows:
            return None

        df = pd.DataFrame(rows)
        df = df.sort_values("date").tail(days).reset_index(drop=True)
        return df if not df.empty else None
    except Exception:
        return None


# ═══════════════════════════════════════════════════════════════
# RIWAYAT (analysis log)
# ═══════════════════════════════════════════════════════════════
def _bersihkan_untuk_json(obj):
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.floating):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, pd.Timestamp):
        return obj.isoformat()
    if isinstance(obj, np.bool_):
        return bool(obj)
    return obj


def simpan_riwayat(ringkasan, aksi_mode="simpan_baru", target_saham=None):
    if aksi_mode == "lewati":
        st.info("ℹ️ Riwayat tidak disimpan (Opsi 'Lewati Simpan' aktif untuk Swing Aktif).")
        return

    try:
        sheet = get_gsheet().worksheet("riwayat")
        items_to_add = ringkasan if isinstance(ringkasan, list) else [ringkasan]
        records = sheet.get_all_records()
        valid_records = [r for r in records if any(str(v).strip() for v in r.values())]
        data = list(valid_records)

        def _norm_key(rec):
            """Key dedup: Waktu (dipotong ke menit) + Saham + Gaya."""
            waktu = str(rec.get("Waktu", "")).strip()
            if len(waktu) >= 16:
                waktu = waktu[:16]
            saham = str(rec.get("Saham", "")).replace(".JK", "").strip().upper()
            gaya = str(rec.get("Gaya", "SW")).strip().upper()
            return (waktu, saham, gaya)

        if aksi_mode == "update" and target_saham:
            saham_target_clean = str(target_saham).replace(".JK", "").strip().upper()
            for item_new in items_to_add:
                gaya_new = str(item_new.get("Gaya", "SW")).strip().upper()
                ringkasan_bersih = {k: _bersihkan_untuk_json(v) for k, v in item_new.items()}
                updated = False
                for idx, record in enumerate(data):
                    s_rec = str(record.get("Saham", "")).replace(".JK", "").strip().upper()
                    g_rec = str(record.get("Gaya", "SW")).strip().upper()
                    if s_rec == saham_target_clean and g_rec == gaya_new:
                        data[idx] = ringkasan_bersih
                        updated = True
                        break
                if not updated:
                    data.insert(0, ringkasan_bersih)
        else:
            for item in reversed(items_to_add):
                ringkasan_bersih = {k: _bersihkan_untuk_json(v) for k, v in item.items()}
                key_new = _norm_key(ringkasan_bersih)

                replaced = False
                for idx, record in enumerate(data):
                    if _norm_key(record) == key_new:
                        data[idx] = ringkasan_bersih
                        replaced = True
                        break

                if not replaced:
                    data.insert(0, ringkasan_bersih)

        data = data[:3000]
        if data:
            headers = list(data[0].keys())
            rows = [[row.get(h, "") for h in headers] for row in data]
            sheet.clear()
            sheet.update([headers] + rows, value_input_option="RAW")

        st.session_state.riwayat = data
        if aksi_mode == "update":
            st.success("✅ Catatan Swing Aktif berhasil diperbarui di riwayat!")
        else:
            st.success("✅ Riwayat berhasil disimpan!")
    except Exception as e:
        st.error(f"❌ Gagal menyimpan riwayat: {e}")


def muat_riwayat_dari_sheets() -> list:
    try:
        sheet = get_gsheet().worksheet("riwayat")
        records = sheet.get_all_records()
        valid_records = [r for r in records if any(str(v).strip() for v in r.values())]
        return valid_records[:3000]
    except Exception as e:
        st.error(f"❌ Gagal memuat riwayat: {e}")
        return []


def muat_riwayat_actual() -> dict:
    data = {}

    def norm_gaya(val):
        v = str(val).strip().lower()
        if v in ("sw", "swing"):
            return "SW"
        if v in ("dt", "daytrade", "day_trade", "day trade"):
            return "DT"
        return val

    avoid_set = set()
    try:
        riwayat_ws = get_gsheet().worksheet("riwayat")
        for r in riwayat_ws.get_all_records():
            if "AVOID" in str(r.get("Sinyal", "")).upper():
                w = str(r.get("Waktu", ""))[:16]
                s = str(r.get("Saham", "")).replace(".JK", "").strip().upper()
                avoid_set.add((w, s))
    except Exception:
        pass

    try:
        sheet = get_gsheet().worksheet("riwayat_actual")
        records = sheet.get_all_records()
        for row in records:
            waktu = str(row.get("Waktu", ""))
            saham = str(row.get("Saham", ""))
            raw_gaya = row.get("Mode", "") or row.get("Gaya", "")
            gaya = norm_gaya(raw_gaya) if raw_gaya else ""

            w_key = waktu[:16]
            s_key = saham.replace(".JK", "").strip().upper()
            is_avoid = (w_key, s_key) in avoid_set

            val = {
                "Actual_High": str(row.get("Actual_High", "") or "").strip(),
                "Actual_Low": str(row.get("Actual_Low", "") or "").strip(),
                "Actual_Close": str(row.get("Actual_Close", "") or "").strip(),
                "Outcome": str(row.get("Outcome", "") or "").strip(),
                "Entry_Miss": str(row.get("Entry_Miss", "") or "").strip(),
                "Mode": gaya if gaya else "",
                "V12_Consumed": str(row.get("V12_Consumed", "No") or "No").strip(),
                "_is_avoid": is_avoid,
            }

            if waktu and saham:
                if gaya:
                    data[(waktu, saham, gaya)] = val
                    mode_long = "swing" if gaya == "SW" else (
                        "daytrade" if gaya == "DT" else gaya
                    )
                    data[(waktu, saham, mode_long)] = val
                elif raw_gaya:
                    data[(waktu, saham, str(raw_gaya))] = val
                else:
                    data[(waktu, saham)] = val
    except Exception as e:
        st.error(f"Gagal memuat actual: {e}")
    return data


def hapus_riwayat_item(waktu, saham, gaya=None):
    """Hapus 1 item riwayat — pakai delete_rows agar tidak clear-all."""
    try:
        sheet = get_gsheet().worksheet("riwayat")
        records = sheet.get_all_records()

        waktu_str = str(waktu).strip()
        saham_str = str(saham).strip()
        gaya_str = str(gaya).strip().upper() if gaya else None

        rows_to_delete = []
        for i, r in enumerate(records):
            r_waktu = str(r.get("Waktu", "")).strip()
            r_saham = str(r.get("Saham", "")).strip()
            r_gaya = str(r.get("Gaya", "")).strip().upper()

            match = (r_waktu == waktu_str and r_saham == saham_str)
            if gaya_str:
                match = match and (r_gaya == gaya_str)

            if match:
                rows_to_delete.append(i + 2)

        if not rows_to_delete:
            st.warning("⚠️ Item tidak ditemukan di riwayat.")
            return

        for row_idx in sorted(rows_to_delete, reverse=True):
            sheet.delete_rows(row_idx)

        try:
            fresh = sheet.get_all_records()
            valid = [r for r in fresh if any(str(v).strip() for v in r.values())]
            st.session_state.riwayat = valid
        except Exception:
            pass

        st.success(f"✅ {len(rows_to_delete)} item dihapus dari riwayat.")
    except Exception as e:
        st.error(f"❌ Gagal menghapus riwayat: {e}")


def simpan_riwayat_actual(waktu, saham, actual_data, mode="swing",
                          on_update_callback=None, memory_store=None):
    def norm_gaya(val):
        v = str(val).strip().lower()
        if v in ("sw", "swing"):
            return "SW"
        if v in ("dt", "daytrade", "day_trade", "day trade"):
            return "DT"
        return val

    try:
        sheet = get_gsheet().worksheet("riwayat_actual")
        records = sheet.get_all_records()
        headers_8 = ["Waktu", "Saham", "Mode", "Actual_High", "Actual_Low",
                     "Actual_Close", "Outcome", "Entry_Miss"]
        headers_9 = headers_8 + ["V12_Consumed"]

        if sheet.col_count < 9:
            sheet.add_cols(9 - sheet.col_count)

        if not records:
            sheet.update("A1:I1", [headers_9], value_input_option="RAW")
            records = sheet.get_all_records()
        else:
            existing_headers = list(records[0].keys())
            if "Mode" not in existing_headers:
                sheet.update("A1:I1", [headers_9], value_input_option="RAW")
                records = sheet.get_all_records()
            elif "V12_Consumed" not in existing_headers:
                sheet.update("I1", [["V12_Consumed"]], value_input_option="RAW")
                records = sheet.get_all_records()

        row_index = None
        target_mode_norm = norm_gaya(mode)
        for i, row in enumerate(records):
            r_mode = row.get("Mode") or row.get("Gaya") or ""
            if (str(row.get("Waktu")) == str(waktu)
                    and str(row.get("Saham")) == str(saham)
                    and norm_gaya(r_mode) == target_mode_norm):
                row_index = i + 2
                break

        new_row = [
            waktu, saham, mode,
            actual_data.get("Actual_High", ""),
            actual_data.get("Actual_Low", ""),
            actual_data.get("Actual_Close", ""),
            actual_data.get("Outcome", ""),
            actual_data.get("Entry_Miss", ""),
        ]

        if row_index:
            sheet.update(f"A{row_index}:H{row_index}", [new_row], value_input_option="RAW")
        else:
            sheet.insert_row(new_row, index=2, value_input_option="RAW")

        try:
            st.session_state.riwayat_actual = muat_riwayat_actual()
        except Exception:
            pass

        # ═══ PERBAIKAN: SELALU PANGGIL CALLBACK JIKA ADA ═══
        if on_update_callback is not None:
            on_update_callback(waktu, saham, actual_data, mode)
            
        # Tandai V12_Consumed = Yes
        if row_index:
            sheet.update(f"I{row_index}", [["Yes"]], value_input_option="RAW")
        else:
            sheet.update("I2", [["Yes"]], value_input_option="RAW")
            
    except Exception as e:
        st.error(f"Gagal menyimpan actual: {e}")


# ═══════════════════════════════════════════════════════════════
# SIGNAL OUTCOMES
# ═══════════════════════════════════════════════════════════════
def save_signal_outcome(ticker, mode, signal, regime, price, horizon_days=None) -> bool:
    """
    Simpan setiap signal yang di-generate untuk evaluasi masa depan.

    Catatan: angka ditulis sebagai STRING dengan titik desimal
    supaya Sheets tidak auto-convert ke format koma (locale Indonesia).
    """
    try:
        ticker_clean = str(ticker).upper().replace(".JK", "").strip()
        if not ticker_clean:
            return False

        cat_info = _parse_signal_category(signal, regime)
        cat, exp_dir, exp_mag = cat_info.category, cat_info.expected_direction, cat_info.expected_magnitude
        if cat == "UNKNOWN":
            return False

        if horizon_days is None:
            horizon_days = 1 if mode == "daytrade" else 5

        sheet = get_gsheet().worksheet("signal_outcomes")
        today = datetime.now(pytz.timezone("Asia/Jakarta")).strftime("%Y-%m-%d")

        records = sheet.get_all_records()
        for i, r in enumerate(records):
            if (str(r.get("ticker", "")).upper() == ticker_clean
                    and str(r.get("mode", "")) == mode
                    and str(r.get("timestamp", ""))[:10] == today):
                row_idx = i + 2
                sheet.update(
                    f"A{row_idx}:J{row_idx}",
                    [[
                        datetime.now(pytz.timezone("Asia/Jakarta")).strftime("%Y-%m-%d %H:%M:%S"),
                        ticker_clean, mode, signal, cat, regime,
                        str(float(price)).replace(",", "."),
                        int(horizon_days),
                        int(exp_dir),
                        str(float(exp_mag)),
                    ]],
                    value_input_option="RAW",
                )
                return True

        sheet.insert_row([
            datetime.now(pytz.timezone("Asia/Jakarta")).strftime("%Y-%m-%d %H:%M:%S"),
            ticker_clean, mode, signal, cat, regime,
            str(float(price)).replace(",", "."),
            int(horizon_days),
            int(exp_dir),
            str(float(exp_mag)),
            False, "", "", "", "",
        ], index=2, value_input_option="RAW")
        return True
    except Exception:
        return False


def _update_regime_signal_accuracy(ticker, regime, signal_cat, was_correct):
    """Update akurasi per (regime, signal_category) dengan EMA."""
    import re
    if ticker not in st.session_state.v12_memory:
        st.session_state.v12_memory[ticker] = {
            "weights": {}, "accuracy": {}, "error_ema": {},
        }

    mem = st.session_state.v12_memory[ticker]
    mem.setdefault("regime_signal_accuracy", {})

    regime_key = re.sub(
        r"\s*[\U0001F300-\U0001FAFF\u2600-\u27BF]+\s*", "", str(regime)
    ).strip() or "unknown"

    mem["regime_signal_accuracy"].setdefault(regime_key, {})
    mem["regime_signal_accuracy"][regime_key].setdefault(signal_cat, {
        "hits": 0, "total": 0, "accuracy": 0.5,
    })

    stats = mem["regime_signal_accuracy"][regime_key][signal_cat]
    stats["total"] += 1
    if was_correct:
        stats["hits"] += 1

    alpha = 0.15
    hit_val = 1.0 if was_correct else 0.0
    stats["accuracy"] = stats["accuracy"] * (1 - alpha) + hit_val * alpha
    st.session_state.v12_memory[ticker] = mem

    if "__global__" not in st.session_state.v12_memory:
        st.session_state.v12_memory["__global__"] = {"regime_signal_accuracy": {}}
    gm = st.session_state.v12_memory["__global__"]
    gm.setdefault("regime_signal_accuracy", {})
    gm["regime_signal_accuracy"].setdefault(regime_key, {})
    gm["regime_signal_accuracy"][regime_key].setdefault(signal_cat, {
        "hits": 0, "total": 0, "accuracy": 0.5,
    })
    gs = gm["regime_signal_accuracy"][regime_key][signal_cat]
    gs["total"] += 1
    if was_correct:
        gs["hits"] += 1
    gs["accuracy"] = gs["accuracy"] * (1 - alpha) + hit_val * alpha

    save_v12_memory(st.session_state.v12_memory)


def get_regime_signal_accuracy(ticker, regime, signal_cat) -> dict:
    """Ambil akurasi historis untuk (ticker, regime, signal_category)."""
    import re
    regime_key = re.sub(
        r"\s*[\U0001F300-\U0001FAFF\u2600-\u27BF]+\s*", "", str(regime)
    ).strip() or "unknown"

    ticker_stats = {"total": 0, "accuracy": 0.5}
    mem = st.session_state.v12_memory.get(ticker, {})
    rsa = mem.get("regime_signal_accuracy", {}).get(regime_key, {}).get(signal_cat)
    if rsa:
        ticker_stats = rsa

    global_stats = {"total": 0, "accuracy": 0.5}
    gm = st.session_state.v12_memory.get("__global__", {})
    grs = gm.get("regime_signal_accuracy", {}).get(regime_key, {}).get(signal_cat)
    if grs:
        global_stats = grs

    ticker_conf = min(1.0, ticker_stats["total"] / 20)
    global_conf = min(1.0, global_stats["total"] / 50)

    if ticker_conf + global_conf == 0:
        return {"accuracy": 0.5, "total": 0, "confidence": 0.0,
                "ticker_accuracy": 0.5, "global_accuracy": 0.5}

    total_conf = ticker_conf + global_conf
    blended = (
        ticker_stats["accuracy"] * ticker_conf
        + global_stats["accuracy"] * global_conf
    ) / total_conf

    return {
        "accuracy": blended,
        "total": ticker_stats["total"] + global_stats["total"],
        "ticker_accuracy": ticker_stats["accuracy"],
        "global_accuracy": global_stats["accuracy"],
        "confidence": min(1.0, total_conf / 2),
    }
def get_signal_outcomes_stats() -> dict:
    """Total kumulatif sinyal yang sudah dievaluasi (bukan cuma sesi ini)."""
    result = {
        "evaluated": 0,
        "correct": 0,
        "suspended": 0,
        "by_mode": {
            "swing": {"total": 0, "correct": 0},
            "daytrade": {"total": 0, "correct": 0},
        },
    }
    try:
        ws = get_gsheet().worksheet("signal_outcomes")
        records = ws.get_all_records()
        for r in records:
            if not _is_evaluated(r.get("evaluated")):
                continue

            was_correct_raw = str(r.get("was_correct", "")).strip().upper()
            if was_correct_raw == "SUSPENDED":
                result["evaluated"] += 1
                result["suspended"] += 1
                continue

            result["evaluated"] += 1
            correct = _is_evaluated(r.get("was_correct"))
            if correct:
                result["correct"] += 1

            mode = str(r.get("mode", "")).strip().lower()
            if mode in result["by_mode"]:
                result["by_mode"][mode]["total"] += 1
                if correct:
                    result["by_mode"][mode]["correct"] += 1
        return result
    except Exception as e:
        return {**result, "error": str(e)}

def evaluate_pending_signals(max_eval: int = 50) -> dict:
    """
    Evaluasi signal yang sudah lewat horizon.

    Perubahan:
      - eval_time pakai hari bursa (tambah_hari_bursa)
      - timezone handling defensif
      - batch update (hemat quota Sheets)
      - guard expected_direction/magnitude kosong
      - timeout → SUSPENDED (biar tidak nyangkut selamanya)
    """
    result = {
        "evaluated": 0, "correct": 0, "suspended": 0,
        "details": [], "skipped": [],
    }
    try:
        sheet = get_gsheet().worksheet("signal_outcomes")
        records = sheet.get_all_records()
        if not records:
            return result

        now = datetime.now(pytz.timezone("Asia/Jakarta"))
        updates = []            # batch update untuk sheet
        pending_accuracy = []   # batch update V12 memory

        for i, r in enumerate(records):
            if _is_evaluated(r.get("evaluated")):
                continue

            ticker_str = str(r.get("ticker", "")).strip()
            mode_str = str(r.get("mode", "")).strip()

            try:
                # ─── Parse timestamp ───
                ts = pd.to_datetime(str(r["timestamp"]))
                if ts.tzinfo is None:
                    ts = ts.tz_localize("Asia/Jakarta")

                horizon = int(_to_float(r["horizon_days"], 1))
                eval_time = tambah_hari_bursa(ts, horizon + 1)
                suspend_timeout = tambah_hari_bursa(
                    ts, horizon + 1 + SUSPEND_TIMEOUT_BDAYS
                )

                if now < eval_time:
                    continue

                # ─── Guard expected_dir/mag kosong ───
                raw_dir = str(r.get("expected_direction", "")).strip()
                raw_mag = str(r.get("expected_magnitude", "")).strip()
                if raw_dir == "" or raw_mag == "":
                    result["skipped"].append(
                        f"{ticker_str} {mode_str}: expected_dir/mag kosong"
                    )
                    continue

                ticker = ticker_str
                price_at_signal = _to_float(r["price_at_signal"])
                expected_dir = int(_to_float(raw_dir))
                expected_mag = _to_float(raw_mag)

                if price_at_signal <= 0:
                    result["skipped"].append(
                        f"{ticker} {mode_str}: price_at_signal invalid"
                    )
                    continue

                # ─── Fetch harga ───
                t = f"{ticker}.JK"
                df = yf.download(t, period="1mo", interval="1d", progress=False)
                if df is None or df.empty:
                    result["skipped"].append(f"{ticker} {mode_str}: yfinance empty")
                    continue
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)

                # ─── Normalisasi timezone (defensif) ───
                eval_date = eval_time.normalize()
                if getattr(eval_date, "tz", None) is not None:
                    eval_date = eval_date.tz_localize(None)

                if getattr(df.index, "tz", None) is not None:
                    df = df.copy()
                    df.index = df.index.tz_localize(None)

                future = df[df.index.normalize() >= eval_date]

                # ─── Handle: tidak ada bar future ───
                if future.empty:
                    row_idx = i + 2
                    if now > suspend_timeout:
                        # Timeout → tandai SUSPENDED
                        updates.append({
                            "range": f"K{row_idx}:O{row_idx}",
                            "values": [[
                                True, "", "", "SUSPENDED",
                                now.strftime("%Y-%m-%d %H:%M:%S"),
                            ]],
                        })
                        result["suspended"] += 1
                        result["skipped"].append(
                            f"{ticker} {mode_str}: SUSPENDED (timeout)"
                        )
                    else:
                        result["skipped"].append(
                            f"{ticker} {mode_str}: no future bar (masih nunggu)"
                        )
                    continue

                # ─── Hitung actual return ───
                price_now = float(future["Close"].iloc[0])
                actual_return = (price_now - price_at_signal) / price_at_signal
                actual_return = max(-1.0, min(1.0, actual_return))

                if expected_dir == +1:
                    was_correct = actual_return >= expected_mag
                elif expected_dir == -1:
                    was_correct = actual_return <= -expected_mag
                else:
                    was_correct = abs(actual_return) <= expected_mag

                row_idx = i + 2
                updates.append({
                    "range": f"K{row_idx}:O{row_idx}",
                    "values": [[
                        True, price_now, round(actual_return, 6),
                        was_correct, now.strftime("%Y-%m-%d %H:%M:%S"),
                    ]],
                })

                result["evaluated"] += 1
                if was_correct:
                    result["correct"] += 1
                result["details"].append({
                    "ticker": ticker,
                    "signal": r.get("signal", ""),
                    "regime": r.get("regime", ""),
                    "actual_return": actual_return,
                    "correct": was_correct,
                })

                pending_accuracy.append((
                    ticker,
                    str(r.get("regime", "")),
                    str(r.get("signal_category", "")),
                    was_correct,
                ))

                if result["evaluated"] >= max_eval:
                    break

            except Exception as e:
                result["skipped"].append(f"{ticker_str} {mode_str}: {e}")
                print(f"[!] Eval skip {ticker_str} {mode_str}: {e}")
                continue

        # ─── Batch update ke Sheets ───
        if updates:
            try:
                sheet.batch_update(updates, value_input_option="RAW")
            except Exception as e:
                print(f"[!] Batch update gagal: {e}")

        # ─── Update V12 memory (bisa batch kalau perlu) ───
        for ticker_acc, regime_acc, cat_acc, correct_acc in pending_accuracy:
            _update_regime_signal_accuracy(
                ticker_acc, regime_acc, cat_acc, correct_acc
            )

        if result["skipped"]:
            print(f"[!] {len(result['skipped'])} signal di-skip. Detail:")
            for s in result["skipped"][:10]:
                print(f"    - {s}")

        return result
    except Exception as e:
        return {**result, "error": str(e)}


def update_v12_memory(ticker, factor_signals, actual_return, volatility=0.02,
                      memory_store=None, skip_save=False):
    """
    Wrapper — delegasi math ke core.scoring, persist ke Sheets.

    memory_store: dict opsional (cron context — bypass session_state).
                  None → pakai st.session_state.v12_memory (UI context).
    skip_save:    kalau True, caller bertanggung jawab save batch di akhir
                  (untuk cron loop — hindari N kali write ke Sheets).
    """
    store = memory_store if memory_store is not None else st.session_state.v12_memory
    if ticker not in store:
        store[ticker] = {"weights": {}, "accuracy": {}, "error_ema": {}}
    mem = store[ticker]
    new_mem = compute_memory_update_math(mem, factor_signals, actual_return, volatility)
    store[ticker] = new_mem
    if not skip_save:
        save_v12_memory(store)


# ═══════════════════════════════════════════════════════════════
# V12 LEARNING INTEGRATION
# ═══════════════════════════════════════════════════════════════
def integrate_actual_to_v12(waktu, saham, actual_data, mode="swing",
                            memory_store=None):
    """
    Belajar dari OUTCOME TRADE (Win/Loss/NT).

    Poin 7 fix: actual_return dihitung riil dari Actual_High/Low vs Entry,
    bukan hardcode ±0.03. Konsekuensi: factor learning bereaksi proporsional
    terhadap besaran alpha — Win +10% ≠ Win +0.5%.

    memory_store: dict opsional untuk cron (bypass session_state).
                  None → fallback st.session_state (UI path).
    """
    try:
        ticker = saham
        last_pred = load_v12_predictions(ticker, mode=mode)

        # Ekstrak factor_signals (hanya kalau last_pred ada)
        factor_signals = {}
        _vol = 0.02
        if last_pred:
            for k in FACTOR_KEYS:
                key = f'sig_{k}'
                if key in last_pred:
                    factor_signals[k] = safe_float(last_pred[key], 0.0)
                else:
                    factor_signals[k] = 0.0
            _vol = factor_signals.get('_volatility', 0.02)

        # ═══ PRIORITAS 1: Entry Miss / Not Touched ═══
        entry_miss = str(actual_data.get('Entry_Miss', '')).strip() == 'Yes'
        outcome_raw = str(actual_data.get('Outcome', '')).strip().upper()

        if entry_miss or outcome_raw in ('NOT TOUCHED', 'SUSPENDED'):
            gap = None

            # --- Coba hitung gap dari entry_high vs actual_low (pakai last_pred jika ada) ---
            if last_pred:
                entry_low = last_pred.get('entry_low')
                entry_high = last_pred.get('entry_high')
                if entry_low is not None and entry_high is not None:
                    try:
                        entry_low_f = safe_float(entry_low, None)
                        entry_high_f = safe_float(entry_high, None)
                    except Exception:
                        entry_low_f, entry_high_f = None, None

                    if entry_low_f and entry_high_f and entry_low_f < entry_high_f:
                        actual_low_str = actual_data.get('Actual_Low', '')
                        if actual_low_str:
                            try:
                                actual_low_f = _to_float(actual_low_str)
                                if actual_low_f > entry_high_f:
                                    gap = actual_low_f - entry_high_f
                            except Exception:
                                pass

                        if gap is None:
                            last_close = safe_float(last_pred.get('close_price'), 0.0)
                            if last_close > entry_high_f:
                                gap = last_close - entry_high_f
                            else:
                                gap = entry_high_f * 0.01  # fallback minimum

            # --- Fallback jika last_pred None: pakai Actual_Low vs Actual_Close ---
            if gap is None:
                actual_low_str = actual_data.get('Actual_Low', '')
                actual_close_str = actual_data.get('Actual_Close', '')
                if actual_low_str and actual_close_str:
                    try:
                        al = _to_float(actual_low_str)
                        ac = _to_float(actual_close_str)
                        if al > 0 and ac > 0:
                            # Estimasi gap: close minus low sebagai proxy entry miss distance
                            gap = max(ac - al, ac * 0.005)  # minimal 0.5% dari close
                    except Exception:
                        pass
                elif actual_close_str:
                    try:
                        ac = _to_float(actual_close_str)
                        if ac > 0:
                            gap = ac * 0.01  # 1% proxy kalau tidak ada data lengkap
                    except Exception:
                        pass

            if gap and gap > 0:
                store = (
                    memory_store if memory_store is not None
                    else st.session_state.v12_memory
                )
                mem = store.get(ticker, {})
                old_err = mem.get("entry_error_ema", 0.0)
                mem["entry_error_ema"] = compute_entry_error_update(old_err, gap)
                store[ticker] = mem
                # Cron: batch save di caller. UI: save langsung.
                if memory_store is None:
                    save_v12_memory(store)
            return

        # Jika tidak ada last_pred dan bukan NT/suspended, tidak ada yang bisa dipelajari
        if not last_pred:
            return

        # ═══ PRIORITAS 2: Win/Loss → hitung alpha RIIL (bukan ±0.03) ═══
        if outcome_raw in ('WIN', 'LOSS'):
            entry_high_f = safe_float(last_pred.get('entry_high'), 0.0)
            entry_low_f = safe_float(last_pred.get('entry_low'), 0.0)
            entry_ref = entry_high_f if entry_high_f > 0 else entry_low_f
            if entry_ref <= 0:
                return

            actual_high = _to_float(actual_data.get('Actual_High', 0))
            actual_low = _to_float(actual_data.get('Actual_Low', 0))
            actual_close = _to_float(actual_data.get('Actual_Close', 0))

            if outcome_raw == 'WIN':
                # Notes: pakai Actual_High sebagai best-case capture
                best = actual_high if actual_high > 0 else (
                    actual_close if actual_close > 0 else entry_ref
                )
                actual_return = (best - entry_ref) / entry_ref
            else:  # LOSS
                # Simetris: pakai Actual_Low (worst-case drawdown)
                worst = actual_low if actual_low > 0 else (
                    actual_close if actual_close > 0 else entry_ref
                )
                actual_return = (worst - entry_ref) / entry_ref

            actual_return = max(-1.0, min(1.0, actual_return))
            update_v12_memory(
                ticker, factor_signals, actual_return, volatility=_vol,
                memory_store=memory_store,
                skip_save=(memory_store is not None),  # cron: batch di caller
            )
            return

        # ═══ PRIORITAS 3: Fallback close-to-close ═══
        actual_close_str = actual_data.get('Actual_Close', '')
        if actual_close_str:
            try:
                actual_close = _to_float(actual_close_str)
                last_close = safe_float(last_pred.get('close_price'), 0.0)
                if last_close > 0:
                    actual_return = (actual_close - last_close) / last_close
                    actual_return = max(-1.0, min(1.0, actual_return))
                    if abs(actual_return) >= 0.003:
                        update_v12_memory(
                            ticker, factor_signals, actual_return,
                            volatility=_vol,
                            memory_store=memory_store,
                            skip_save=(memory_store is not None),
                        )
            except Exception:
                pass

    except Exception as e:
        try:
            if not (hasattr(st, "runtime") and st.runtime.exists()):
                print(f"[sheets] integrate_actual_to_v12 error: {e}")
            else:
                st.error(f"Gagal integrasi V12: {e}")
        except Exception:
            print(f"[sheets] integrate_actual_to_v12 error (silent): {e}")


# ═══════════════════════════════════════════════════════════════
# REPAIR: Backfill entry_error_ema dari data NT yang sudah ada
# ═══════════════════════════════════════════════════════════════
def repair_entry_error_ema(dry_run: bool = False) -> dict:
    result = {"processed": 0, "updated_tickers": {}, "skipped": [], "dry_run": dry_run}

    try:
        sheet = get_gsheet().worksheet("riwayat_actual")
        records = sheet.get_all_records()
    except Exception as e:
        result["error"] = str(e)
        return result

    ticker_gaps: dict[str, list[float]] = {}

    for row in records:
        outcome_raw = str(row.get("Outcome", "")).strip().upper()
        entry_miss   = str(row.get("Entry_Miss", "")).strip()
        is_nt = outcome_raw in ("NOT TOUCHED", "NOT_TOUCHED") or entry_miss == "Yes"
        if not is_nt:
            continue

        saham = str(row.get("Saham", "")).replace(".JK", "").strip().upper()
        if not saham:
            result["skipped"].append("baris tanpa saham")
            continue

        gap = None
        actual_low_str   = str(row.get("Actual_Low", "")).strip()
        actual_close_str = str(row.get("Actual_Close", "")).strip()

        if actual_low_str and actual_close_str:
            try:
                al = _to_float(actual_low_str)
                ac = _to_float(actual_close_str)
                if al > 0 and ac > 0:
                    gap = max(ac - al, ac * 0.005)
            except Exception:
                pass
        elif actual_close_str:
            try:
                ac = _to_float(actual_close_str)
                if ac > 0:
                    gap = ac * 0.01
            except Exception:
                pass

        if gap and gap > 0:
            ticker_gaps.setdefault(saham, []).append(gap)
            result["processed"] += 1
        else:
            result["skipped"].append(f"{saham}: tidak bisa hitung gap")

    if dry_run:
        result["would_update"] = {t: len(gs) for t, gs in ticker_gaps.items()}
        return result

    # ═══ PERBAIKAN: AMBIL DATA DARI DATABASE (JANGAN DARI SESSION STATE) ═══
    store = load_v12_memory()

    for ticker, gaps in ticker_gaps.items():
        mem = store.get(ticker, {})
        old_err = mem.get("entry_error_ema", 0.0)
        new_err = old_err
        for g in gaps:
            new_err = compute_entry_error_update(new_err, g)
        mem["entry_error_ema"] = new_err
        store[ticker] = mem
        result["updated_tickers"][ticker] = {
            "gap_count": len(gaps),
            "old_ema": round(old_err, 4),
            "new_ema": round(new_err, 4),
        }

    if store:
        try:
            save_v12_memory(store)
            try:
                st.session_state.v12_memory = store
            except Exception:
                pass
        except Exception as e:
            result["save_error"] = str(e)

    return result
# BANDARMOLOGY DATA LOADER
# ═══════════════════════════════════════════════════════════════
def load_bandarmology_data(ticker):
    """Load & normalisasi broksum history untuk 1 ticker."""
    try:
        history = load_broksum_history(ticker)
    except Exception:
        return None
    if not history:
        return None

    history_sorted = sorted(
        history, key=lambda r: str(r.get('upload_date', '')), reverse=True
    )
    latest = history_sorted[0]

    def _norm(lst):
        out = []
        for it in _parse_broker_list(lst):
            if not isinstance(it, dict):
                continue
            code = str(it.get('broker', '')).strip().upper()
            if not code:
                continue
            vol = safe_float(it.get('volume_lot', 0))
            frq = it.get('freq')
            kat = it.get('kategori')
            icon = it.get('kategori_icon')
            if not kat or not icon:
                kat, icon = klasifikasi_broker(code, vol, frq)
            out.append({
                'broker': code,
                'volume_lot': vol,
                'value_idr': safe_float(it.get('value_idr', 0)),
                'avg_price': safe_float(it.get('avg_price', 0)),
                'freq': frq,
                'kategori': kat,
                'kategori_icon': icon,
                'category': BROKER_TYPES.get(code, 'Domestic'),
            })
        return out

    return {
        'ticker': ticker.upper().replace('.JK', ''),
        'history': history_sorted,
        'latest': latest,
        'buyers': _norm(latest.get('top_buyers', '[]')),
        'sellers': _norm(latest.get('top_sellers', '[]')),
        'upload_date': latest.get('upload_date', 'N/A'),
        'bandarmology_status': latest.get('bandarmology_status', 'N/A'),
        'summary_narrative': latest.get('summary_narrative', ''),
    }
# ═══════════════════════════════════════════════════════════════
# POIN 7 — AUTO-EVALUATION CRON (feedback loop otonom)
# ═══════════════════════════════════════════════════════════════
def _parse_price_range(s: str) -> tuple[float | None, float | None]:
    """Parse 'Rp 1,000 - Rp 1,100' → (1000.0, 1100.0). Comma = ribuan."""
    if not s:
        return None, None
    nums = [n for n in re.findall(r"[\d,]+", str(s)) if n]
    if len(nums) < 2:
        return None, None
    try:
        return (float(nums[0].replace(",", "")), float(nums[1].replace(",", "")))
    except ValueError:
        return None, None


def _parse_price_single(s: str) -> float | None:
    """Parse 'Rp 1,000' atau '1,000' → 1000.0."""
    if not s:
        return None
    nums = [n for n in re.findall(r"[\d,]+", str(s)) if n]
    if not nums:
        return None
    try:
        return float(nums[0].replace(",", ""))
    except ValueError:
        return None


def _determine_outcome(
    entry_low: float, entry_high: float,
    tp_low: float | None, sl: float | None,
    actual_high: float, actual_low: float, actual_close: float,
    entry_miss: str,
) -> str:
    """
    Tentukan outcome dari actual HL C vs Entry/TP/SL.
    Prioritas: Suspended > Not Touched > SL (SL menang duluan) > TP > Close-vs-Entry.
    """
    if actual_high <= 0 or actual_low <= 0:
        return "Suspended"
    if entry_miss == "Yes":
        return "Not Touched"
    if sl is not None and sl > 0 and actual_low <= sl:
        return "Loss"
    if tp_low is not None and tp_low > 0 and actual_high >= tp_low:
        return "Win"
    entry_ref = entry_high if entry_high > 0 else entry_low
    return "Win" if actual_close > entry_ref else "Loss"


def _save_actual_to_sheets_cron(
    waktu: str, saham: str, mode: str,
    actual_high: float, actual_low: float, actual_close: float,
    outcome: str, entry_miss: str,
) -> bool:
    """Cron-safe versi simpan_riwayat_actual — tanpa session_state."""
    def norm_gaya(val):
        v = str(val).strip().lower()
        if v in ("sw", "swing"): return "SW"
        if v in ("dt", "daytrade", "day_trade", "day trade"): return "DT"
        return val

    try:
        sheet = get_gsheet().worksheet("riwayat_actual")
        records = sheet.get_all_records()
        headers_9 = ["Waktu", "Saham", "Mode", "Actual_High", "Actual_Low",
                     "Actual_Close", "Outcome", "Entry_Miss", "V12_Consumed"]
        if sheet.col_count < 9:
            sheet.add_cols(9 - sheet.col_count)
        if not records:
            sheet.update("A1:I1", [headers_9], value_input_option="RAW")
            records = sheet.get_all_records()

        target_gaya = norm_gaya(mode)
        row_index = None
        for i, row in enumerate(records):
            r_mode = row.get("Mode") or row.get("Gaya") or ""
            if (str(row.get("Waktu")) == str(waktu)
                    and str(row.get("Saham")) == str(saham)
                    and norm_gaya(r_mode) == target_gaya):
                row_index = i + 2
                break

        new_row = [waktu, saham, mode,
                   f"{actual_high:.0f}", f"{actual_low:.0f}", f"{actual_close:.0f}",
                   outcome, entry_miss]
        if row_index:
            sheet.update(f"A{row_index}:H{row_index}", [new_row],
                         value_input_option="RAW")
        else:
            sheet.insert_row(new_row, index=2, value_input_option="RAW")
        return True
    except Exception as e:
        print(f"[cron] gagal simpan actual {saham}: {e}")
        return False

def _compute_learning_return(
    entry_ref: float, outcome: str,
    actual_high: float, actual_low: float, actual_close: float,
) -> float:
    """
    Return yang SAMA dengan yang dipakai integrate_actual_to_v12 untuk memory.
    - Win  → best-case (actual_high) — sesuai notes "alpha"
    - Loss → worst-case (actual_low) — simetris
    - NT / Suspended → 0.0
    """
    if entry_ref <= 0:
        return 0.0
    if outcome == "Win":
        best = actual_high if actual_high > 0 else (
            actual_close if actual_close > 0 else entry_ref
        )
        return max(-1.0, min(1.0, (best - entry_ref) / entry_ref))
    if outcome == "Loss":
        worst = actual_low if actual_low > 0 else (
            actual_close if actual_close > 0 else entry_ref
        )
        return max(-1.0, min(1.0, (worst - entry_ref) / entry_ref))
    return 0.0
def auto_evaluate_riwayat_actual(
    min_bdays: int = 5,
    max_bdays: int = 30,
    max_eval: int = 50,
    dry_run: bool = False,
) -> dict:
    """
    Poin 7 — Auto-evaluasi sinyal lama yang belum punya outcome.

    Cron-safe (bypass session_state via memory_store + _save_actual_to_sheets_cron).
    Return dict: {evaluated, wins, losses, nt, suspended,
                  memory_updates, details, skipped, error?}
    """
    import yfinance as yf
    from config.calendar import hitung_hari_bursa

    result = {
        "evaluated": 0, "wins": 0, "losses": 0, "nt": 0, "suspended": 0,
        "memory_updates": 0, "details": [], "skipped": [],
    }

    try:
        riwayat = muat_riwayat_dari_sheets()
        actual_map = muat_riwayat_actual()
        memory_store = load_v12_memory() if not dry_run else {}

        now_jkt = datetime.now(pytz.timezone("Asia/Jakarta"))
        today = now_jkt.date()

        for r in riwayat:
            if result["evaluated"] + result["suspended"] >= max_eval:
                break

            waktu_str = str(r.get("Waktu", "")).strip()
            saham = str(r.get("Saham", "")).strip().upper().replace(".JK", "")
            gaya = str(r.get("Gaya", "SW")).strip().upper()

            if not waktu_str or not saham:
                continue
            if "AVOID" in str(r.get("Sinyal", "")).upper():
                continue

            existing = (
                actual_map.get((waktu_str, saham, gaya))
                or actual_map.get((waktu_str, saham,
                                   "swing" if gaya == "SW" else "daytrade"))
            )
            if existing and existing.get("Outcome"):
                continue

            try:
                dt_signal = datetime.strptime(waktu_str.split()[0], "%Y-%m-%d").date()
            except Exception:
                result["skipped"].append(f"{saham} {gaya}: parse date")
                continue

            bdays = hitung_hari_bursa(dt_signal, today)
            if bdays < min_bdays:
                continue
            if bdays > max_bdays:
                result["suspended"] += 1
                result["skipped"].append(f"{saham} {gaya}: timeout {bdays}bdays")
                continue

            entry_low, entry_high = _parse_price_range(r.get("Entry_Zone", ""))
            tp_low, _ = _parse_price_range(
                r.get("TP_Range", "") or r.get("TP_Harga", "")
            )
            sl = _parse_price_single(r.get("SL_Harga", ""))
            if entry_low is None or entry_high is None:
                result["skipped"].append(f"{saham} {gaya}: entry_zone unparseable")
                continue

            try:
                # auto_adjust=False: pakai harga UNADJUSTED, konsisten dengan
                # Entry_Zone/SL/TP di Sheets (dibuat saat itu = unadjusted).
                # Kalau True (default), dividend/split adjust bisa bikin harga
                # historis "terlihat lebih rendah" → false Loss.
                df = yf.download(
                    f"{saham}.JK", period="3mo", interval="1d",
                    progress=False, auto_adjust=False,
                )
            except Exception as e:
                result["skipped"].append(f"{saham} {gaya}: yf error {e}")
                continue
            if df is None or df.empty:
                result["skipped"].append(f"{saham} {gaya}: yf empty")
                continue
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            try:
                if getattr(df.index, "tz", None) is not None:
                    df = df.copy()
                    df.index = df.index.tz_localize(None)
            except Exception:
                pass

            # Konservatif: mulai H+1 setelah hari sinyal.
            # Menghindari lookahead bias dari bar hari sinyal yang sebagian
            # besar terbentuk SEBELUM sinyal dibuat (mis. low pagi hari
            # sebelum harga naik ke level sinyal).
            # Lookahead guard (SQMI case):
            #   - Sinyal post-market (>=16:00 WIB): trader entry H+1 → filter >
            #   - Sinyal intraday (<16:00 WIB): boleh entry hari sinyal → filter >=
            #     (accept small lookahead risk dari bar pagi, karena daily OHLC
            #      tidak punya granularity intraday)
            signal_hour = 16  # default conservative: treat as post-market
            try:
                _parts = waktu_str.split()
                if len(_parts) >= 2:
                    signal_dt_parse = datetime.strptime(
                        f"{_parts[0]} {_parts[1]}", "%Y-%m-%d %H:%M"
                    )
                    signal_hour = signal_dt_parse.hour
                else:
                    signal_dt_parse = datetime.strptime(waktu_str, "%Y-%m-%d")
                    signal_hour = 16
            except Exception:
                pass

            if signal_hour >= 16:
                df_future = df[df.index.date > dt_signal]
            else:
                df_future = df[df.index.date >= dt_signal]

            if df_future.empty:
                result["skipped"].append(f"{saham} {gaya}: no future bars")
                continue

            actual_high = float(df_future["High"].max())
            actual_low = float(df_future["Low"].min())
            actual_close = float(df_future["Close"].iloc[-1])
            if actual_high <= 0 or actual_low <= 0:
                result["skipped"].append(f"{saham} {gaya}: invalid OHLC")
                continue

            entry_miss = "Yes" if actual_low > entry_high else "No"
            outcome = _determine_outcome(
                entry_low, entry_high, tp_low, sl,
                actual_high, actual_low, actual_close, entry_miss,
            )
            if outcome == "Suspended":
                result["suspended"] += 1
                continue

            if not dry_run:
                saved = _save_actual_to_sheets_cron(
                    waktu=waktu_str, saham=saham, mode=gaya,
                    actual_high=actual_high, actual_low=actual_low,
                    actual_close=actual_close, outcome=outcome,
                    entry_miss=entry_miss,
                )
                if not saved:
                    result["skipped"].append(f"{saham} {gaya}: save fail")
                    continue

                integrate_actual_to_v12(
                    waktu=waktu_str, saham=saham, mode=gaya,
                    actual_data={
                        "Actual_High": f"{actual_high:.0f}",
                        "Actual_Low": f"{actual_low:.0f}",
                        "Actual_Close": f"{actual_close:.0f}",
                        "Outcome": outcome,
                        "Entry_Miss": entry_miss,
                    },
                    memory_store=memory_store,
                )

            result["evaluated"] += 1
            if outcome == "Win":           result["wins"] += 1
            elif outcome == "Loss":        result["losses"] += 1
            elif outcome == "Not Touched": result["nt"] += 1
            entry_ref_for_report = entry_high if entry_high > 0 else entry_low
            result["details"].append({
                "ticker": saham, "mode": gaya, "outcome": outcome,
                "bdays": bdays,
                "entry_low": entry_low,
                "entry_high": entry_high,
                "actual_low": actual_low,
                "actual_high": actual_high,
                "actual_close": actual_close,
                "entry_miss": entry_miss,
                "actual_return": _compute_learning_return(
                    entry_ref_for_report, outcome,
                    actual_high, actual_low, actual_close,
                ),
            })

        if not dry_run and result["evaluated"] > 0:
            save_v12_memory(memory_store)
            result["memory_updates"] = result["evaluated"]

        return result

    except Exception as e:
        return {**result, "error": str(e)}
