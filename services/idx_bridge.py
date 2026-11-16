"""
idx_bridge.py — ambil JSON dari idx.co.id lewat Edge yang sudah lolos Cloudflare.

Syarat:
  * Edge dibuka dengan --remote-debugging-port=9222 (lihat start_edge.bat)
  * verifikasi Cloudflare sudah diklik DI WINDOW edge_profile, tab IDX terbuka
"""
from __future__ import annotations

import json
import logging
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor

log = logging.getLogger("idx_bridge")

PORT = 9222
HOME_URL = "https://www.idx.co.id/id/data-pasar/ringkasan-perdagangan/ringkasan-saham/"

CHALLENGE_TITLE_MARKERS = (
    "just a moment",
    "attention required",
    "verifying you are human",
    "checking your browser",
    "please wait",
)

_lock = threading.Lock()  # satu sesi CDP pada satu waktu

_JS_FETCH = """async (url) => {
    try {
        const r = await fetch(url, {
            credentials: 'include',
            headers: {'accept': 'application/json, text/plain, */*'},
        });
        return {status: r.status, text: await r.text()};
    } catch (e) {
        return {status: 0, text: String(e)};
    }
}"""


class IDXBridgeError(RuntimeError):
    """Edge/port tidak tersedia, challenge belum lolos, atau sesi expired."""


def available(port: int = PORT) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            return True
    except OSError:
        return False


def _safe_title(page) -> str:
    try:
        return (page.title() or "").strip()
    except Exception:
        return ""


def _is_challenge(page) -> bool:
    t = _safe_title(page).lower()
    return any(m in t for m in CHALLENGE_TITLE_MARKERS)


def _has_clearance(context) -> bool:
    try:
        cookies = context.cookies("https://www.idx.co.id")
    except Exception:
        return False
    return any(c.get("name") == "cf_clearance" for c in cookies)


def _pick_or_create_page(context):
    # 1) halaman HOME_URL yang sudah ada
    for pg in context.pages:
        try:
            if pg.url.startswith(HOME_URL):
                return pg
        except Exception:
            continue
    # 2) halaman idx.co.id lain yang bukan challenge
    for pg in context.pages:
        try:
            if "idx.co.id" in pg.url and not _is_challenge(pg):
                return pg
        except Exception:
            continue
    # 3) buat baru
    pg = context.new_page()
    try:
        pg.goto(HOME_URL, wait_until="domcontentloaded", timeout=90000)
    except Exception as e:
        raise IDXBridgeError(f"Gagal membuka halaman IDX: {e}") from e
    return pg


def _ensure_clearance(page, context):
    """Cek cepat (tanpa menunggu) — kalau belum lolos, beri pesan jelas."""
    if "idx.co.id" not in page.url:
        raise IDXBridgeError(
            f"Page aktif bukan IDX (url={page.url!r}). "
            "Buka halaman IDX di window edge_profile, lalu ulangi."
        )
    if _is_challenge(page):
        raise IDXBridgeError(
            "Halaman Edge masih menampilkan challenge Cloudflare "
            f"(title={_safe_title(page)!r}). Selesaikan verifikasi "
            "'Just a moment...' di window edge_profile sampai halaman "
            "ringkasan saham IDX tampil, lalu ulangi request."
        )
    if not _has_clearance(context):
        raise IDXBridgeError(
            "Cookie cf_clearance tidak ditemukan. Selesaikan verifikasi "
            "Cloudflare di window edge_profile, lalu ulangi request."
        )


def _run(urls, port, delay):
    from playwright.sync_api import sync_playwright

    results = []
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
        if not browser.contexts:
            raise IDXBridgeError("Edge tersambung tapi tidak ada context/jendela.")
        context = browser.contexts[0]
        log.info("Terhubung ke Edge: %d page(s)", len(context.pages))

        page = _pick_or_create_page(context)
        log.info("Memakai page: url=%s title=%r", page.url, _safe_title(page))
        _ensure_clearance(page, context)

        consecutive_403 = 0
        for i, url in enumerate(urls):
            if consecutive_403 >= 2:  # sesi jelas expired, jangan buang waktu
                results.append((403, None))
                continue
            if i and delay:
                time.sleep(delay)

            res = page.evaluate(_JS_FETCH, url)
            status = res.get("status", 0)
            text = res.get("text") or ""
            if status != 200:
                log.warning(
                    "IDX status=%s url=%s body=%r",
                    status, url[:120], text[:300].replace("\n", " "),
                )
            consecutive_403 = consecutive_403 + 1 if status == 403 else 0

            data = None
            if status == 200:
                try:
                    data = json.loads(text)
                except ValueError:
                    log.warning("HTTP 200 tapi bukan JSON: %r", text[:200])
                    status = -1
            results.append((status, data))
    return results


def _call(urls, port, delay):
    if not available(port):
        raise IDXBridgeError(
            f"Port {port} tidak aktif. Buka Edge lewat start_edge.bat dan "
            f"selesaikan verifikasi Cloudflare di window edge_profile."
        )
    try:
        with _lock, ThreadPoolExecutor(max_workers=1) as ex:
            return ex.submit(_run, list(urls), port, delay).result()
    except IDXBridgeError:
        raise
    except Exception as e:
        raise IDXBridgeError(f"Gagal menyambung ke Edge: {e}") from e


def fetch_json(url: str, port: int = PORT):
    status, data = _call([url], port, 0)[0]
    if status != 200:
        raise IDXBridgeError(f"IDX HTTP {status} — {_hint(status)}")
    return data


def fetch_json_many(urls, port: int = PORT, delay: float = 0.8):
    return [d if s == 200 else None for s, d in _call(urls, port, delay)]


def _hint(status: int) -> str:
    if status in (0, 403, -1):
        return (
            "sesi Cloudflare kemungkinan expired atau challenge belum lolos; "
            "buka window Edge profil edge_profile, refresh tab IDX, "
            "selesaikan verifikasi, lalu ulangi."
        )
    return "lihat log bridge_server untuk cuplikan body respons."
