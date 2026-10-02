"""
yfinance + IDX API client — semua operasi market data dari sumber eksternal.

Sections:
  1. yfinance wrappers (cached)
  2. IDX API scraping (Trading Summary, Stock List)
  3. Stock list builder (static + API combined)
"""
from __future__ import annotations

import os
import sys
import socket
import subprocess
import time
from datetime import datetime, timedelta

import pandas as pd
import pytz
import requests
import streamlit as st
import yfinance as yf

# Pastikan folder file ini ada di sys.path, supaya `import idx_bridge` selalu ketemu
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    import idx_bridge
except ImportError as e:
    idx_bridge = None
    print(f"[!] idx_bridge GAGAL di-import: {e}")


# ═══════════════════════════════════════════════════════════════
# BRIDGE HELPERS (Edge + CDP)
# ═══════════════════════════════════════════════════════════════
_EDGE_EXE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
_BRIDGE_PORT = 9222
_IDX_HOME = "https://www.idx.co.id/id/data-pasar/ringkasan-perdagangan/ringkasan-saham/"


def _port_open(port: int = _BRIDGE_PORT) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            return True
    except OSError:
        return False


def _edge_profile_dir() -> str:
    """Profil yang sama dengan start_edge.bat / idx_cron.py."""
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "edge_profile")


def ensure_bridge(timeout: int = 30) -> bool:
    """
    Pastikan Edge dengan CDP aktif. Kalau belum, coba buka sendiri.
    Return True kalau port siap dipakai.
    Catatan: kalau Cloudflare challenge belum lolos, fetch pertama akan 403
             — buka jendela Edge & klik verifikasi, lalu ulangi.
    """
    if idx_bridge is None:
        print("[!] idx_bridge belum ter-import — tidak bisa pakai bridge.")
        return False
    if idx_bridge.available():
        return True

    print("[*] Port 9222 belum aktif. Membuka Edge...")
    try:
        subprocess.Popen([
            _EDGE_EXE,
            f"--remote-debugging-port={_BRIDGE_PORT}",
            f"--user-data-dir={_edge_profile_dir()}",
            "--no-first-run",
            _IDX_HOME,
        ])
    except Exception as e:
        print(f"[!] Gagal buka Edge: {e}")
        return False

    for _ in range(timeout):
        if _port_open():
            time.sleep(8)   # beri waktu halaman + challenge selesai
            return True
        time.sleep(1)

    print("[!] Timeout menunggu Edge CDP aktif.")
    return False


def _bridge_ready() -> bool:
    """Cek ringan: bridge ter-import & port aktif. Tidak auto-open Edge."""
    return idx_bridge is not None and idx_bridge.available()


def _bridge_status() -> str:
    """Alasan bridge tidak siap — untuk pesan error yang jelas."""
    if idx_bridge is None:
        return "idx_bridge tidak ter-import (cek folder & sys.path)"
    if not idx_bridge.available():
        return "port 9222 tidak aktif (jalankan start_edge.bat / ensure_bridge())"
    return ""


# ═══════════════════════════════════════════════════════════════
# SECTION 1 — YFINANCE WRAPPERS
# ═══════════════════════════════════════════════════════════════
@st.cache_data(ttl=60)
def load_stock_data(ticker, period="2y", interval="1d"):
    try:
        df = yf.download(ticker, period=period, interval=interval, prepost=True, actions=False)
    except Exception:
        return pd.DataFrame()

    if df is None or df.empty:
        return pd.DataFrame()

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    try:
        if "Close" in df.columns:
            df = df.dropna(subset=["Close"])
    except Exception:
        pass

    return df


@st.cache_data(ttl=60)
def load_ihsg_data(period="2y", interval="1d"):
    try:
        df = yf.download("^JKSE", period=period, interval=interval, prepost=True, actions=False)
    except Exception:
        return pd.DataFrame()

    if df is None or df.empty:
        return pd.DataFrame()

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    try:
        if "Close" in df.columns:
            df = df.dropna(subset=["Close"])
    except Exception:
        pass

    return df


@st.cache_data(ttl=30)
def get_realtime_price(ticker):
    """Harga real-time terpisah dari bar historis."""
    try:
        t = yf.Ticker(ticker)
        fi = t.fast_info
        return {
            "last_price": fi.get("last_price"),
            "market_state": fi.get("market_state") if hasattr(fi, "get") else None,
        }
    except Exception:
        return None


def cek_kesegaran_data(df_ihsg_preview, now_jkt, max_lag_minutes=20):
    """Return (is_stale, lag_minutes)."""
    if df_ihsg_preview.empty:
        return True, None
    last_bar_time = df_ihsg_preview.index[-1]
    if last_bar_time.tzinfo is None:
        last_bar_time = pytz.timezone("Asia/Jakarta").localize(last_bar_time)
    else:
        last_bar_time = last_bar_time.astimezone(pytz.timezone("Asia/Jakarta"))
    lag = (now_jkt - last_bar_time).total_seconds() / 60
    return lag > max_lag_minutes, lag


@st.cache_data(ttl=120, show_spinner=False)
def _load_intraday_price_data(ticker):
    """Intraday OHLC — prioritaskan 1m, fallback 5m/15m/30m/60m."""
    t = ticker.upper().strip()
    if not t.endswith(".JK"):
        t = f"{t}.JK"

    intervals = ["1m", "2m", "5m", "15m", "30m", "60m"]
    period_map = {"1m": "5d", "2m": "5d", "5m": "5d",
                  "15m": "5d", "30m": "5d", "60m": "5d"}

    for interval in intervals:
        try:
            df = yf.download(
                t, period=period_map[interval], interval=interval,
                progress=False, prepost=False,
            )
            if df is None or df.empty:
                continue
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)

            try:
                if df.index.tz is not None:
                    df = df.tz_convert("Asia/Jakarta")
            except Exception:
                pass

            last_date = df.index[-1].date()
            df_last = df[df.index.date == last_date].copy()

            if df_last.empty:
                continue

            min_bars = 30 if interval == "1m" else 20
            if len(df_last) < min_bars:
                if interval == "1m":
                    unique_dates = sorted(set(df.index.date), reverse=True)
                    for d in unique_dates:
                        df_candidate = df[df.index.date == d].copy()
                        if len(df_candidate) >= 50:
                            return df_candidate, interval
                continue

            return df_last, interval
        except Exception:
            continue

    return None, None


@st.cache_data(ttl=300, show_spinner=False)
def _load_daily_price_data(ticker, period="1mo"):
    """Daily OHLC."""
    t = ticker.upper().strip()
    if not t.endswith(".JK"):
        t = f"{t}.JK"
    try:
        df = yf.download(t, period=period, interval="1d", progress=False)
        if df is None or df.empty:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        return df
    except Exception:
        return None


def fetch_actual_data_yfinance(saham, waktu_str):
    """
    Data High/Low/Close historis dari yfinance sejak tanggal sinyal.
    Kalau analisis dilakukan ≥16:00 WIB (pasar tutup), efektif mulai H+1.
    """
    try:
        ticker_input = saham if saham.endswith(".JK") else f"{saham}.JK"
        clean_waktu = str(waktu_str).strip()

        dt_obj = None
        formats = [
            "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M",
            "%d %B %Y, %H:%M WIB", "%d %B %Y, %H:%M:%S WIB",
            "%Y-%m-%d",
        ]
        for fmt in formats:
            try:
                dt_obj = datetime.strptime(clean_waktu, fmt)
                break
            except ValueError:
                continue

        if dt_obj is None:
            try:
                dt_part = clean_waktu.split()[0]
                dt_obj = datetime.strptime(dt_part, "%Y-%m-%d")
            except Exception:
                dt_obj = datetime.now()

        effective_date = dt_obj.date()
        if dt_obj.hour >= 16:
            effective_date += timedelta(days=1)

        start_str = (effective_date - timedelta(days=1)).strftime("%Y-%m-%d")
        df_hist = yf.download(ticker_input, start=start_str, progress=False)
        if df_hist is None or df_hist.empty:
            return None

        if isinstance(df_hist.columns, pd.MultiIndex):
            try:
                df_hist = df_hist.xs(ticker_input, axis=1, level=1)
            except Exception:
                df_hist.columns = [c[0] for c in df_hist.columns]

        df_filtered = df_hist[df_hist.index.date >= effective_date]
        if df_filtered.empty:
            return None

        max_hi = float(df_filtered["High"].max())
        min_lo = float(df_filtered["Low"].min())
        last_cl = float(df_filtered["Close"].iloc[-1])

        return {
            "Actual_High": f"{max_hi:,.0f}".replace(",", ""),
            "Actual_Low": f"{min_lo:,.0f}".replace(",", ""),
            "Actual_Close": f"{last_cl:,.0f}".replace(",", ""),
        }
    except Exception:
        return None


# ═══════════════════════════════════════════════════════════════
# SECTION 2 — IDX API SCRAPING
# ═══════════════════════════════════════════════════════════════
_IDX_HEADERS = {
    "accept": "application/json, text/plain, */*",
    "accept-language": "en-US,en;q=0.9,id;q=0.8",
    "egrum": "isAjax:true",
    "referer": "https://www.idx.co.id/id/data-pasar/ringkasan-perdagangan/ringkasan-saham/",
    "user-agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "x-requested-with": "XMLHttpRequest",
}

_IDX_SUMMARY_URL = (
    "https://www.idx.co.id/primary/TradingSummary/GetStockSummary?length=9999&start=0"
)

def _get_bridge_config():
    try:
        return (
            st.secrets.get("BRIDGE_URL", "").rstrip("/"),
            st.secrets.get("BRIDGE_KEY", ""),
        )
    except Exception:
        return "", ""
def _idx_get_json(url, timeout=25, use_bridge=True):
    bridge_err = None
    tunnel_url, tunnel_key = _get_bridge_config()

    # Jalur 1: tunnel (untuk Streamlit Cloud)
    if use_bridge and tunnel_url:
        try:
            r = requests.get(
                f"{tunnel_url}/idx",
                params={"url": url},
                headers={"X-Api-Key": tunnel_key},
                timeout=timeout,
            )
            if r.status_code == 200:
                body = r.json()
                if body.get("ok"):
                    return body["data"]
                bridge_err = f"tunnel: {body.get('error', 'unknown')}"
            else:
                bridge_err = f"tunnel HTTP {r.status_code}"
        except Exception as e:
            bridge_err = f"tunnel unreachable: {e}"

    # Jalur 2: idx_bridge lokal
    if use_bridge and bridge_err is None:
        if idx_bridge is None:
            bridge_err = "idx_bridge tidak ter-import"
        elif not idx_bridge.available():
            bridge_err = "port 9222 tidak aktif"
        else:
            try:
                return idx_bridge.fetch_json(url)
            except idx_bridge.IDXBridgeError as e:
                bridge_err = f"bridge aktif tapi gagal: {e}"

    # Jalur 3: fallback
    try:
        from curl_cffi import requests as curl_requests
        r = curl_requests.get(url, headers=_IDX_HEADERS, timeout=timeout, impersonate="chrome120")
    except ImportError:
        r = requests.get(url, headers=_IDX_HEADERS, timeout=timeout)

    if r.status_code != 200:
        msg = f"IDX HTTP {r.status_code}"
        if bridge_err:
            msg += f" (bridge: {bridge_err})"
        raise RuntimeError(msg)
    return r.json()


def _idx_get_many(urls):
    tunnel_url, tunnel_key = _get_bridge_config()

    if tunnel_url:
        try:
            r = requests.post(
                f"{tunnel_url}/idx-many",
                json={"urls": list(urls)},
                headers={"X-Api-Key": tunnel_key},
                timeout=90,
            )
            if r.status_code == 200:
                body = r.json()
                if body.get("ok"):
                    return body["data"]
        except Exception:
            pass

    if _bridge_ready():
        try:
            return idx_bridge.fetch_json_many(urls)
        except idx_bridge.IDXBridgeError as e:
            raise RuntimeError(f"Bridge IDX gagal: {e}") from e

    out = []
    for u in urls:
        try:
            out.append(_idx_get_json(u, use_bridge=False))
        except Exception:
            out.append(None)
    return out


def _extract_items(payload):
    """Ekstrak list item dari response IDX. Handle nested data.data."""
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("data", "Data", "result", "Result", "results"):
            v = payload.get(key)
            if isinstance(v, list):
                return v
            if isinstance(v, dict):
                for key2 in ("data", "Data", "result", "Result", "results"):
                    v2 = v.get(key2)
                    if isinstance(v2, list):
                        return v2
        return []
    return []


@st.cache_data(ttl=1800, show_spinner=False)
def _fetch_idx_all_stock_summary():
    """Semua data saham dari IDX sekali request (cache 30 menit)."""
    try:
        data = _extract_items(_idx_get_json(_IDX_SUMMARY_URL))
    except Exception as e:
        raise RuntimeError(f"IDX fetch error: {e}")

    if not data:
        raise RuntimeError("IDX response kosong")
    return data


@st.cache_data(ttl=1800, show_spinner=False)
def _fetch_idx_summaries(date_strs):
    """
    Ringkasan SEMUA saham per tanggal, semua tanggal dalam satu sesi Edge.
    date_strs: tuple 'YYYY-MM-DD' (terbaru dulu). Di-cache lintas ticker.
    Return {date_str: items}; tanggal libur/gagal tidak ikut.
    """
    def url_for(d, style):  # style 0 = YYYY-MM-DD, 1 = YYYYMMDD
        return f"{_IDX_SUMMARY_URL}&date={d if style == 0 else d.replace('-', '')}"

    # Format tanggal yang diterima API belum pasti -> probe 3 tanggal terbaru x 2 format
    probe = date_strs[:3]
    probe_urls = [url_for(d, s) for s in (0, 1) for d in probe]
    style = None
    for i, payload in enumerate(_idx_get_many(probe_urls)):
        if _extract_items(payload):
            style = 0 if i < len(probe) else 1
            break
    if style is None:
        return {}

    out = {}
    payloads = _idx_get_many([url_for(d, style) for d in date_strs])
    for d, payload in zip(date_strs, payloads):
        items = _extract_items(payload)
        if items:
            out[d] = items
    return out


@st.cache_data(ttl=1800, show_spinner=False)
def _fetch_idx_foreign_flow(ticker, days=30):
    """Foreign Flow harian dari IDX Trading Summary."""
    ticker_clean = str(ticker).upper().replace(".JK", "").strip()

    today = datetime.now(pytz.timezone("Asia/Jakarta")).date()
    candidates = [today - timedelta(days=i) for i in range(days + 20)]
    date_strs = tuple(d.strftime("%Y-%m-%d") for d in candidates if d.weekday() < 5)

    summaries = _fetch_idx_summaries(date_strs)
    if not summaries:
        return None

    def _num(it, *keys):
        for k in keys:
            v = it.get(k)
            if v not in (None, "", "N/A", "-"):
                try:
                    return float(str(v).replace(",", ""))
                except Exception:
                    continue
        return 0.0

    rows = []
    for d_str, items in summaries.items():
        for it in items:
            if not isinstance(it, dict):
                continue
            code = str(it.get("StockCode") or it.get("KodeSaham") or "").upper().strip()
            if code != ticker_clean:
                continue

            fb = _num(it, "ForeignBuy", "ForeignBuyValue", "Foreign_Buy",
                      "ForeignBuyIDR", "ForeignBuyRp", "ForeignBuyValueIDR")
            fs = _num(it, "ForeignSell", "ForeignSellValue", "Foreign_Sell",
                      "ForeignSellIDR", "ForeignSellRp", "ForeignSellValueIDR")
            close_px = _num(it, "Close", "Previous", "ClosePrice", "Price")
            if 0 < fb < 1e8 and close_px > 0:
                fb *= 100 * close_px
            if 0 < fs < 1e8 and close_px > 0:
                fs *= 100 * close_px

            try:
                real_date = datetime.strptime(str(it.get("Date") or d_str)[:10], "%Y-%m-%d").date()
            except ValueError:
                real_date = datetime.strptime(d_str, "%Y-%m-%d").date()

            rows.append({
                "date": real_date,
                "foreign_buy": abs(fb),
                "foreign_sell": abs(fs),
                "net_foreign": fb - fs,
            })
            break

    if not rows:
        return None

    df = (pd.DataFrame(rows).drop_duplicates(subset=["date"])
          .sort_values("date").tail(days))
    df = df[(df["foreign_buy"] > 0) | (df["foreign_sell"] > 0)]
    return df if not df.empty else None


@st.cache_data(ttl=86400)
def fetch_idx_stock_list_exclude_monitoring():
    """Ambil semua saham BEI non-Pemantauan Khusus."""
    excluded_boards = {
        "pemantauankhusus", "pemantauan_khusus", "pemantauankhusus",
        "monitoring", "special_monitoring", "specialmonitoring",
    }
    endpoints = [
        "https://www.idx.co.id/umbraco/Surface/ListedCompany/GetStockList?start=0&length=9999",
        "https://www.idx.co.id/umbraco/Surface/ListedCompany/GetStockList?language=id-id&start=0&length=9999",
        "https://www.idx.co.id/umbraco/Surface/ListedCompany/GetStockList?start=0&length=9999&exchangeBoard=&industry=&subIndustry=&search=",
    ]
    all_codes = []
    seen = set()
    for url in endpoints:
        try:
            raw = _idx_get_json(url)

            items = None
            if isinstance(raw, list):
                items = raw
            else:
                for key in ("data", "Data", "result", "Result", "results"):
                    if key in raw:
                        items = raw[key]
                        break
                if items is None:
                    def extract(obj):
                        out = []
                        if isinstance(obj, dict):
                            if "code" in obj or "Code" in obj or "KodeSaham" in obj:
                                out.append(obj)
                            for v in obj.values():
                                out.extend(extract(v))
                        elif isinstance(obj, list):
                            for v in obj:
                                out.extend(extract(v))
                        return out
                    items = extract(raw)

            if not items:
                continue

            for item in items:
                if not isinstance(item, dict):
                    continue
                code = item.get("Code") or item.get("code") or item.get("KodeSaham")
                if not code:
                    continue
                code = str(code).strip().upper()
                if len(code) > 6 or not code.isalnum():
                    continue

                board = item.get("BoardId") or item.get("Board") or item.get("boardId") or ""
                board_lower = str(board).lower().replace(" ", "").replace("-", "").replace("_", "")
                if board_lower in excluded_boards:
                    continue

                if code not in seen:
                    seen.add(code)
                    all_codes.append(code)

            if len(all_codes) >= 100:
                break
        except Exception:
            continue

    return sorted(all_codes) if all_codes else None


def fetch_all_idx_stocks():
    """Wrapper — semua saham BEI non-Pemantauan Khusus."""
    return fetch_idx_stock_list_exclude_monitoring()


# ═══════════════════════════════════════════════════════════════
# SECTION 3 — STOCK LIST BUILDER (static + API)
# ═══════════════════════════════════════════════════════════════
@st.cache_data(ttl=3600)
def get_daftar_saham(mode):
    """Return list kode saham (tanpa .JK) berdasarkan mode scan."""
    lq45 = ["AADI", "ADMR", "ADRO", "AKRA", "AMMN", "AMRT", "ANTM", "ASII", "BBCA", "BBNI", "BBRI", "BBTN", "BMRI", "BRPT", "BUMI", "CPIN", "CUAN", "DEWA", "EMTK", "ESSA",
            "EXCL", "HRTA", "ICBP", "INCO", "INDF", "INDY", "INKP", "ISAT", "ITMG", "JPFA", "KLBF", "MAPI", "MBMA", "MDKA", "MEDC", "PGAS", "PGEO", "PTBA", "SCMA", "TLKM",
            "UNTR", "UNVR", "WIFI", "GOTO", "NCKL"]

    papan_utama = lq45 + ["AALI", "ABMM", "ACES", "ADHI", "AISA", "ALDO", "AMAG", "APLN", "ARNA", "ARTO", "ASGR", "ASRI", "ASSA", "AUTO", "BACA", "BALI", "BAYU", "BBHI", "BBMD", "BBYB",
                          "BCAP", "BDMN", "BEST", "BFIN", "BGTG", "BINA", "BIRD", "BISI", "BJBR", "BJTM", "BKSL", "BMTR", "BNGA", "BNII", "BNLI", "BRMS", "BSDE", "BSIM", "BSSR", "BTPN",
                          "BUDI", "BVIC", "BWPT", "BYAN", "CASS", "CFIN", "CITA", "CMNP", "CTRA", "DILD", "DKFT", "DLTA", "DMAS", "DNET", "DSNG", "DSSA", "ELSA", "ENRG", "EPMT", "ERAA",
                          "FISH", "GEMS", "GGRM", "GJTL", "GZCO", "HERO", "HEXA", "HMSP", "HRUM", "IMAS", "IMPC", "INPC", "INTP", "ISSP", "JIHD", "JKON", "JRPT", "JSMR", "JSPT", "JTPE",
                          "KBLI", "KIJA", "KKGI", "KPIG", "LPCK", "LPKR", "LPPF", "LSIP", "LTLS", "MAIN", "MAYA", "MBSS", "MCOR", "MEGA", "MERK", "MIDI", "MIKA", "MLBI", "MLPL", "MNCN",
                          "MPMX", "MTDL", "MTLA", "MYOR", "NISP", "NOBU", "PADI", "PALM", "PANS", "PNBN", "PNIN", "PNLF", "PTPP", "PTRO", "PWON", "RAJA", "RALS", "SAME", "SGRO", "SIDO",
                          "SILO", "SIMP", "SMAR", "SMBR", "SMDR", "SMGR", "SMRA", "SMSM", "SRTG", "SSIA", "SSMS", "TBIG", "TBLA", "TINS", "TKIM", "TMAS", "TOBA", "TOTL", "TOTO", "TOWR",
                          "TPIA", "TPMA", "TRIM", "TSPC", "ULTJ", "UNIC", "VICO", "WIIM", "WINS", "WTON", "SHIP", "POWR", "PRDA", "BRIS", "PORT", "CARS", "CLEO", "WOOD", "MARK", "PSSI",
                          "MORA", "PBID", "IPCM", "BTPS", "SPTO", "HEAL", "TUGU", "MSIN", "MAPA", "IPCC", "MLIA", "PNGO", "FILM", "PANI", "GOOD", "SKRN", "BOLA", "KOTA", "HDIT", "KEEN",
                          "TEBE", "KEJU", "SMCB", "BHIT", "IPTV", "PSGO", "UCID", "GLVA", "AMAR", "DMND", "SAMF", "SGER", "BBSI", "VICI", "TAPG", "ADES", "MASB", "BMHS", "MCOL", "MTEL",
                          "CMRY", "STAA", "TLDN", "MTMH", "TRGU", "HATM", "PLIN", "JARR", "ELPI", "PRAY", "CBUT", "MKTR", "OMED", "SUNI", "BDKR", "SMIL", "MAHA", "WMPP", "ERAL", "BREN",
                          "MSTI", "ALII", "GOLF", "DAAZ", "MDIY", "DGWG", "CBDK", "BLOG", "ASMI", "YUPI", "MDLA", "RAAM", "JECX", "BACH", "RMKE", "AVIA", "DRMA", "AGRO", "PBRX", "ALTO",
                          "BLTA", "GAMA", "IKAI", "TARA", "TAXI", "KREN", "PPRO", "FASW", "WINR", "IBST", "WSKT"]

    pengembangan = papan_utama + ["ABDA", "AKPI", "AKSI", "AMFG", "AMIN", "ANJT", "APEX", "APIC", "APII", "APLI", "ARGO", "ARII", "ARTA", "ASBI", "ASDM", "ASJT", "ASRM", "ATIC", "BABP", "BAJA",
                                  "BAPA", "BBKP", "BBLD", "BBRM", "BCIC", "BCIP", "BIPI", "BIPP", "BKDP", "BKSW", "BMAS", "BMSR", "BNBA", "BNBR", "BOLT", "BPFI", "BPII", "BRAM", "BRNA", "BTON",
                                  "BUKK", "BULL", "BUVA", "CEKA", "CENT", "CINT", "CLPI", "CPRO", "CSAP", "CTBN", "CTTH", "DART", "DEFI", "DGIK", "DNAR", "DOID", "DPNS", "DSFI", "DVLA", "DYAN",
                                  "ECII", "EKAD", "EMDE", "ERTX", "ESTI", "FAST", "FMII", "FORU", "FPNI", "GDST", "GDYR", "GEMA", "GIAA", "GMTD", "GOLD", "GPRA", "GSMF", "GTBO", "GWSA", "HDFA",
                                  "IATA", "ICON", "IGAR", "IKBI", "IMJS", "INAI", "INCI", "INDR", "INDS", "INDX", "INPP", "INTD", "IPOL", "ITMA", "JAWA", "JECC", "KAEF", "KBLM", "KBLV", "KDSI",
                                  "KICI", "KOBX", "KONI", "KOPI", "KRAS", "LAPD", "LEAD", "LINK", "LION", "LMPI", "LPGI", "LPIN", "LPLI", "LPPS", "LRNA", "MBAP", "MBTO", "MDIA", "MDLN", "META",
                                  "MGNA", "MICE", "MITI", "MKPI", "MLPT", "MMLP", "MRAT", "MREI", "MSKY", "MYOH", "NELY", "NIKL", "NIRO", "NRCA", "OKAS", "OMRE", "PANR", "PDES", "PEGE", "PGLI",
                                  "PICO", "PJAA", "PKPK", "PNBS", "PSAB", "PSDN", "PSKT", "PTIS", "PTSN", "PTSP", "PUDP", "PYFA", "RANC", "RBMS", "RDTX", "RELI", "RICY", "RIGS", "RODA", "ROTI",
                                  "RUIS", "SAFE", "SCCO", "SDMU", "SDPC", "SDRA", "SHID", "SIPD", "SKBM", "SKLT", "SMDM", "SMMA", "SMMT", "SOCI", "SPMA", "SQMI", "SRAJ", "SRSN", "SSTM", "STAR",
                                  "STTP", "SULI", "TALF", "TBMS", "TCID", "TGKA", "TIFA", "TIRA", "TMPO", "TRIS", "TRST", "TRUS", "UNIT", "VINS", "VOKS", "VRNA", "WAPO", "WEHA", "WOMF", "YPAS",
                                  "YULE", "CASA", "DAYA", "DPUM", "IDPR", "JGLE", "KINO", "OASA", "PBSA", "BOGA", "MINA", "CSIS", "FIRE", "KMTR", "HOKI", "MPOW", "MDKI", "BELL", "KIOS", "GMFI",
                                  "MTWI", "MCAS", "PPRE", "WEGE", "DWGL", "JMAS", "CAMP", "LCKM", "HELI", "GHON", "DFAM", "NICK", "PRIM", "TRUK", "PZZA", "TNCA", "TCPI", "RISE", "BPTR", "NFCX",
                                  "MGRO", "LAND", "MOLI", "CITY", "SAPX", "SURE", "MPRO", "YELO", "CAKK", "SATU", "POLA", "DIVA", "LUCK", "SOTS", "ZONE", "PEHA", "BEEF", "POLI", "CLAY", "NATO",
                                  "JAYA", "COCO", "JAST", "FITT", "CCSI", "SFAN", "POLU", "KJEN", "ITIC", "PAMG", "BLUE", "EAST", "LIFE", "FUJI", "INOV", "SMKL", "TFAS", "GGRP", "OPMS", "NZIA",
                                  "SLIS", "IRRA", "DMMX", "WOWS", "ESIP", "REAL", "IFII", "PMJS", "CSRA", "INDO", "AMOR", "TRIN", "PTPW", "TAMA", "IKAN", "RONY", "CSMI", "BBSS", "BHAT", "EPAC",
                                  "UANG", "PGUN", "TRJA", "SCNP", "KMDS", "PURI", "SOHO", "HOMI", "ROCK", "ENZO", "ATAP", "BANK", "WMUU", "EDGE", "UNIQ", "SNLK", "ZYRX", "NPGF", "ADCP", "HOPE",
                                  "TRUE", "LABA", "ARCI", "NICL", "UVCR", "HAIS", "OILS", "GPSO", "RSGK", "SBMA", "CMNT", "GTSI", "KUAS", "BOBA", "DEPO", "BINO", "TAYS", "SEMA", "ASLC", "NETV",
                                  "ENAK", "NTBK", "BIKE", "WIRG", "SICO", "GOTO", "ASHA", "SWID", "ARKO", "CHEM", "PCAR", "INRU", "PTMR", "WIKA", "DEWI", "AXIO", "KRYA", "GULA", "TOOL", "BUAH",
                                  "BSBK", "PDPP", "KDTN", "ZATA", "MMIX", "PADA", "VTNY", "ELIT", "BEER", "CBPE", "RAFI", "SAGE", "DUTI", "CRAB", "MEDS", "COAL", "BELI", "MAPB", "SOSS", "MTSM",
                                  "CBRE", "WINE", "PEVE", "LAJU", "FWCT", "IRSX", "VAST", "HALO", "FUTR", "PTMP", "TRON", "NSSS", "GTRA", "JATI", "TYRE", "MPXL", "KLAS", "MAXI", "VKTR", "CRSN",
                                  "INET", "RMKO", "CNMA", "FOLK", "GRIA", "PPRI", "CYBR", "MUTU", "HUMI", "RSCH", "MFMI", "BABY", "IOTF", "KOCI", "PTPS", "STRK", "KOKA", "RGAS", "IKPM", "AYAM",
                                  "ASLI", "GRPH", "SMGA", "UNTD", "TOSK", "MPIX", "MKAP", "LIVE", "HYGN", "BAIK", "IPPE", "ALMI", "SURI", "IFSH", "VISI", "AREA", "MHKI", "ATLA", "DATA", "LMSH",
                                  "SOLA", "BATR", "PART", "ISEA", "BLES", "INCF", "GUNA", "LABS", "DOSS", "NEST", "VERN", "BOAT", "NAIK", "KSIX", "RATU", "YOII", "HRME", "HGII", "SUPA", "PURA",
                                  "BRRC", "OBAT", "MINE", "ASPR", "PSAT", "COIN", "CDIA", "MERI", "KAQI", "BEBS", "FORE", "DKHH", "AYLS", "DADA", "ASPI", "ESTA", "BESS", "AMAN", "CARE", "PIPA",
                                  "NCKL", "AWAN", "DOOH", "CGAS", "NICE", "MSJA", "SMLE", "ACRO", "WIFI", "FAPA", "BAUT", "DCII", "KETR", "DGNS", "UFOE", "CHEK", "PMUI", "EMAS", "PJHB", "RLCO",
                                  "WBSA", "JELI", "EMMI", "PRDL", "RANS", "OBMD", "NASI", "BSML", "ADMF", "ADMG", "NASA", "AGII", "AGRS", "AHAP", "AIMS", "PNSE", "POLL", "TECH", "SUPR", "ARKA",
                                  "ANDI", "ARMY", "BAPI", "BLTZ", "BSWD", "BTEK", "CPRI", "DUCK", "ELTY", "HADE", "CBMF", "HOME", "IIKP", "KIAS", "LCGP", "MAGP", "MIRA", "NUSA", "PLAS", "POOL",
                                  "SCPI", "SKYB", "SONA", "SUGI", "TAMU", "TFCO", "TRAM", "TRIL", "VIVA", "HITS", "SWAT", "AKKU", "KBAG", "RIMO", "BEKS"]

    akselerasi_ekonomi = ["CASH", "SOFA", "PPGL", "PLAN", "LFLO", "LUCY", "MGLV", "IPAC", "FLMC", "RUNS", "IDEA", "WGSH", "SMKM", "NANO", "IBOS", "OLIV", "RCCC",
                          "AMMS", "EURO", "KLIN", "NINE", "ISAP", "SOUL", "BMBL", "NAYZ", "PACK", "CHIP", "KING", "HAJJ", "RELF", "GRPM", "WIDI", "HBAT", "LMAX",
                          "MSIE", "AEGS", "LOPI", "UDNG", "MEJA", "SPRE", "MANG", "BUKA", "FIMP", "MENN"]

    pemantauan_khusus = ["ABBA", "ACST", "ALKA", "ARTI", "BATA", "BIKA", "BIMA", "BTEL", "CANI", "CMPP", "CNKO", "COWL", "ETWA", "GLOB", "GOLL",
                         "HOTL", "IBFN", "INAF", "INTA", "KARW", "KBRI", "KOIN", "LMAS", "MDRN", "MPPA", "MTFN", "MYTX", "OCAP", "SIMA", "SMRU",
                         "SRIL", "TELE", "TIRT", "TRIO", "UNSP", "WICO", "ZBRA", "MARI", "MKNT", "MTRA", "WSBP", "TGRA", "TOPS", "MABA", "ZINC",
                         "BOSS", "JSKY", "INPS", "TDPM", "DIGI", "HKMU", "DEAL", "URBN", "FOOD", "MTPS", "POSA", "KAYU", "ENVY", "PURE", "SINI",
                         "PGJO", "SBAT", "TOYS", "PTDU", "PMMP", "KKES", "HILL", "TGUK", "RGAS", "POLY"]

    pemantauan_khusus_set = set(pemantauan_khusus)
    base_non_khusus = list(dict.fromkeys(pengembangan + akselerasi_ekonomi))
    full_idx_static_non_khusus = [c for c in base_non_khusus if c not in pemantauan_khusus_set]
    full_idx_static_all = list(dict.fromkeys(base_non_khusus + pemantauan_khusus))

    if mode == "Cepat (LQ45)":
        return lq45
    elif mode == "Papan Utama":
        return papan_utama
    elif mode == "Komprehensif (Utama + Pengembangan)":
        return pengembangan
    elif mode == "Full IDX":
        api_codes = fetch_all_idx_stocks()
        if api_codes:
            combined = list(dict.fromkeys(api_codes + full_idx_static_non_khusus))
            combined = [c for c in combined if c not in pemantauan_khusus_set]
            return combined
        return full_idx_static_non_khusus
    elif mode == "Auto-Fetch (API BEI)":
        api_codes = fetch_all_idx_stocks()
        if api_codes:
            combined = list(dict.fromkeys(api_codes + full_idx_static_all))
            return combined[:1000]
        return full_idx_static_all
    return []
