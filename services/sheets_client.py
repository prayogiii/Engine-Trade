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
import time
from datetime import datetime, timedelta

import gspread
import numpy as np
import pandas as pd
import pytz
import streamlit as st
import yfinance as yf
from google.oauth2.service_account import Credentials

from core.signal import parse_signal_category as _parse_signal_category
from config.settings import FACTOR_KEYS, TTL_BROKSUM_CACHE
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
    """Mengembalikan objek spreadsheet berdasarkan secrets."""
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
        ws.append_row(values, value_input_option="RAW")
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

        sheet.append_row([
            row_data["ticker"], row_data["date"], row_data["close"],
            row_data["foreign_buy"], row_data["foreign_sell"],
            row_data["net_foreign"], row_data["source"],
        ], value_input_option="RAW")
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
                          on_update_callback=None):
    """
    Simpan outcome actual ke riwayat_actual + trigger V12 learning.
    on_update_callback: optional callable(waktu, saham, actual_data, mode) → dijalankan
                        sebelum mark V12_Consumed=Yes (untuk inject `integrate_actual_to_v12`).
    """
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
        v12_consumed = "No"
        target_mode_norm = norm_gaya(mode)
        for i, row in enumerate(records):
            r_mode = row.get("Mode") or row.get("Gaya") or ""
            if (str(row.get("Waktu")) == str(waktu)
                    and str(row.get("Saham")) == str(saham)
                    and norm_gaya(r_mode) == target_mode_norm):
                row_index = i + 2
                v12_consumed = str(row.get("V12_Consumed", "No")).strip()
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
            sheet.append_row(new_row, value_input_option="RAW")

        st.session_state.riwayat_actual = muat_riwayat_actual()

        if v12_consumed != "Yes":
            if on_update_callback is not None:
                on_update_callback(waktu, saham, actual_data, mode)
            if row_index:
                sheet.update(f"I{row_index}", [["Yes"]], value_input_option="RAW")
            else:
                last_row = len(sheet.get_all_values())
                sheet.update(f"I{last_row}", [["Yes"]], value_input_option="RAW")
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

        sheet.append_row([
            datetime.now(pytz.timezone("Asia/Jakarta")).strftime("%Y-%m-%d %H:%M:%S"),
            ticker_clean, mode, signal, cat, regime,
            str(float(price)).replace(",", "."),
            int(horizon_days),
            int(exp_dir),
            str(float(exp_mag)),
            False, "", "", "", "",
        ], value_input_option="RAW")
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


def evaluate_pending_signals(max_eval: int = 50) -> dict:
    """
    Evaluasi signal yang sudah lewat horizon.

    Perubahan penting:
      - Pakai `_to_float()` untuk parse angka (handle "0,02" format Indonesia).
      - Cek `evaluated` fleksibel (bool / "TRUE" / "Yes" / "1").
      - Error tidak ditelan — di-print ke terminal untuk debugging.
    """
    result = {"evaluated": 0, "correct": 0, "details": [], "skipped": []}
    try:
        sheet = get_gsheet().worksheet("signal_outcomes")
        records = sheet.get_all_records()
        if not records:
            return result

        now = datetime.now(pytz.timezone("Asia/Jakarta"))

        for i, r in enumerate(records):
            if _is_evaluated(r.get("evaluated")):
                continue

            ticker_str = str(r.get("ticker", "")).strip()
            mode_str = str(r.get("mode", "")).strip()

            try:
                ts = pd.to_datetime(str(r["timestamp"]))
                if ts.tzinfo is None:
                    ts = ts.tz_localize("Asia/Jakarta")

                horizon = int(_to_float(r["horizon_days"], 1))
                eval_time = ts + timedelta(days=int(horizon * 1.5) + 1)

                if now < eval_time:
                    continue

                ticker = ticker_str
                price_at_signal = _to_float(r["price_at_signal"])
                expected_dir = int(_to_float(r["expected_direction"]))
                expected_mag = _to_float(r["expected_magnitude"])

                if price_at_signal <= 0:
                    result["skipped"].append(f"{ticker} {mode_str}: price_at_signal invalid")
                    continue

                t = f"{ticker}.JK"
                df = yf.download(t, period="1mo", interval="1d", progress=False)
                if df is None or df.empty:
                    result["skipped"].append(f"{ticker} {mode_str}: yfinance empty")
                    continue
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)

                eval_date = eval_time.normalize().tz_localize(None)
                if getattr(df.index, "tz", None) is not None:
                    df = df.copy()
                    df.index = df.index.tz_localize(None)
                future = df[df.index >= eval_date]
                if future.empty:
                    result["skipped"].append(f"{ticker} {mode_str}: no future bar")
                    continue

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
                sheet.update(
                    f"K{row_idx}:O{row_idx}",
                    [[True, price_now, round(actual_return, 6),
                      was_correct, now.strftime("%Y-%m-%d %H:%M:%S")]],
                    value_input_option="RAW",
                )

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

                _update_regime_signal_accuracy(
                    ticker, str(r.get("regime", "")),
                    str(r.get("signal_category", "")), was_correct,
                )

                if result["evaluated"] >= max_eval:
                    break

            except Exception as e:
                result["skipped"].append(f"{ticker_str} {mode_str}: {e}")
                print(f"[!] Eval skip {ticker_str} {mode_str}: {e}")
                continue

        if result["skipped"]:
            print(f"[!] {len(result['skipped'])} signal di-skip. Detail:")
            for s in result["skipped"][:10]:
                print(f"    - {s}")

        return result
    except Exception as e:
        return {**result, "error": str(e)}


def update_v12_memory(ticker, factor_signals, actual_return, volatility=0.02):
    """Wrapper — delegasi math ke core.scoring, persist ke Sheets."""
    if ticker not in st.session_state.v12_memory:
        st.session_state.v12_memory[ticker] = {
            "weights": {}, "accuracy": {}, "error_ema": {},
        }
    mem = st.session_state.v12_memory[ticker]
    new_mem = compute_memory_update_math(mem, factor_signals, actual_return, volatility)
    st.session_state.v12_memory[ticker] = new_mem
    save_v12_memory(st.session_state.v12_memory)


# ═══════════════════════════════════════════════════════════════
# V12 LEARNING INTEGRATION
# ═══════════════════════════════════════════════════════════════
def integrate_actual_to_v12(waktu, saham, actual_data, mode="swing"):
    """Belajar dari OUTCOME TRADE (Win/Loss/NT), bukan cuma close-to-close."""
    try:
        ticker = saham
        last_pred = load_v12_predictions(ticker, mode=mode)
        if not last_pred:
            return

        factor_signals = {}
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

        if entry_miss or outcome_raw == 'NOT TOUCHED':
            entry_low = last_pred.get('entry_low')
            entry_high = last_pred.get('entry_high')
            if entry_low is not None and entry_high is not None:
                try:
                    entry_low_f = safe_float(entry_low, None)
                    entry_high_f = safe_float(entry_high, None)
                except Exception:
                    entry_low_f, entry_high_f = None, None

                if entry_low_f and entry_high_f and entry_low_f < entry_high_f:
                    gap = None
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
                            gap = entry_high_f * 0.01

                    if gap and gap > 0:
                        mem = st.session_state.v12_memory.get(ticker, {})
                        old_err = mem.get("entry_error_ema", 0.0)
                        mem["entry_error_ema"] = compute_entry_error_update(old_err, gap)
                        st.session_state.v12_memory[ticker] = mem
                        save_v12_memory(st.session_state.v12_memory)
            return

        # ═══ PRIORITAS 2: Win/Loss → belajar dari trade outcome ═══
        if outcome_raw == 'WIN':
            update_v12_memory(ticker, factor_signals, +0.03, volatility=_vol)
            return
        elif outcome_raw == 'LOSS':
            update_v12_memory(ticker, factor_signals, -0.03, volatility=_vol)
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
                        update_v12_memory(ticker, factor_signals, actual_return, volatility=_vol)
            except Exception:
                pass

    except Exception as e:
        st.error(f"Gagal integrasi V12: {e}")


# ═══════════════════════════════════════════════════════════════
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
