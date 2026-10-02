"""
idx_bridge.py — ambil JSON dari idx.co.id lewat Edge yang sudah lolos Cloudflare.

Syarat:
  * Edge dibuka dengan --remote-debugging-port=9222 (lihat start_edge.bat)
  * verifikasi Cloudflare sudah diklik, tab IDX terbuka

Request dijalankan DARI DALAM tab IDX (fetch di halaman), jadi cookies dan
fingerprint-nya identik dengan browser asli. Letakkan file ini sejajar dengan
idx_cron.py dan yfinance_client.py.
"""
from __future__ import annotations

import json
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor

PORT = 9222
HOME_URL = "https://www.idx.co.id/id/data-pasar/ringkasan-perdagangan/ringkasan-saham/"

_lock = threading.Lock()  # satu sesi CDP pada satu waktu (Streamlit multi-session)

_JS_FETCH = """async (url) => {
    try {
        const r = await fetch(url, {headers: {'accept': 'application/json, text/plain, */*'}});
        return {status: r.status, text: await r.text()};
    } catch (e) {
        return {status: 0, text: String(e)};
    }
}"""


class IDXBridgeError(RuntimeError):
    """Edge/port tidak tersedia, atau sesi Cloudflare expired."""


def available(port: int = PORT) -> bool:
    """True kalau Edge dengan debugging port sedang jalan."""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            return True
    except OSError:
        return False


def _run(urls, port, delay):
    """Jalankan semua URL dalam SATU sesi Edge. Return list of (status, data)."""
    from playwright.sync_api import sync_playwright

    results = []
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
        if not browser.contexts:
            raise IDXBridgeError("Edge tersambung tapi tidak ada jendela.")
        context = browser.contexts[0]

        page = next((pg for pg in context.pages if "idx.co.id" in pg.url), None)
        if page is None:
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(HOME_URL, wait_until="domcontentloaded", timeout=90000)
            page.wait_for_timeout(5000)

        consecutive_403 = 0
        for i, url in enumerate(urls):
            if consecutive_403 >= 2:  # sesi jelas expired, jangan buang waktu
                results.append((403, None))
                continue
            if i and delay:
                time.sleep(delay)

            res = page.evaluate(_JS_FETCH, url)
            status = res["status"]
            consecutive_403 = consecutive_403 + 1 if status == 403 else 0

            data = None
            if status == 200:
                try:
                    data = json.loads(res["text"])
                except ValueError:
                    status = -1  # 200 tapi bukan JSON (mis. halaman challenge)
            results.append((status, data))
        # keluar dari `with` hanya memutus koneksi; Edge tetap terbuka
    return results


def _call(urls, port, delay):
    if not available(port):
        raise IDXBridgeError(
            f"Port {port} tidak aktif. Buka Edge lewat start_edge.bat dan klik verifikasi Cloudflare."
        )
    try:
        # thread terpisah supaya aman dipanggil dari Streamlit / event loop
        with _lock, ThreadPoolExecutor(max_workers=1) as ex:
            return ex.submit(_run, list(urls), port, delay).result()
    except IDXBridgeError:
        raise
    except Exception as e:
        raise IDXBridgeError(f"Gagal menyambung ke Edge: {e}") from e


def fetch_json(url: str, port: int = PORT):
    """Satu URL. Raise IDXBridgeError kalau bukan HTTP 200 + JSON valid."""
    status, data = _call([url], port, 0)[0]
    if status != 200:
        hint = ""
        if status in (0, 403, -1):
            hint = " — sesi Cloudflare kemungkinan expired: refresh tab IDX di Edge lalu klik verifikasi"
        raise IDXBridgeError(f"HTTP {status}{hint}")
    return data


def fetch_json_many(urls, port: int = PORT, delay: float = 0.8):
    """Banyak URL dalam satu sesi. Return list JSON (None untuk yang gagal), urutan sama."""
    return [d if s == 200 else None for s, d in _call(urls, port, delay)]