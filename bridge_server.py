"""
Bridge server — jalan di PC lokal. Terima request dari Streamlit Cloud,
forward ke idx_bridge (Edge CDP), return JSON.

Jalankan:
    py bridge_server.py          (Windows)
    python3 bridge_server.py     (Linux/Mac)
"""

import logging
import os
import sys
import time
import traceback

from flask import Flask, jsonify, request

# ═══════════════════════════════════════════════════════════════
# LOGGING — supaya error 502 kelihatan detailnya di terminal
# ═══════════════════════════════════════════════════════════════
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout,
)
log = logging.getLogger("bridge")

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT, "services"))

try:
    import idx_bridge
    log.info("idx_bridge imported OK dari %s",
             getattr(idx_bridge, "__file__", "?"))
except ImportError as e:
    log.error("idx_bridge gagal di-import: %s", e)
    idx_bridge = None


# ═══════════════════════════════════════════════════════════════
# BACA API KEY — multi-sumber
# ═══════════════════════════════════════════════════════════════
def _load_api_key() -> str:
    key = os.environ.get("BRIDGE_KEY", "").strip()
    if key:
        log.info("BRIDGE_KEY dibaca dari environment variable")
        return key

    secrets_path = os.path.join(ROOT, ".streamlit", "secrets.toml")
    if os.path.isfile(secrets_path):
        try:
            try:
                import tomllib
                with open(secrets_path, "rb") as f:
                    data = tomllib.load(f)
            except ImportError:
                import toml
                with open(secrets_path, "r", encoding="utf-8") as f:
                    data = toml.load(f)
            key = str(data.get("BRIDGE_KEY", "")).strip()
            if key:
                log.info("BRIDGE_KEY dibaca dari %s", secrets_path)
                return key
            log.warning("%s ada tapi tidak berisi BRIDGE_KEY", secrets_path)
        except Exception as e:
            log.error("Gagal baca %s: %s", secrets_path, e)

    env_path = os.path.join(ROOT, ".env")
    if os.path.isfile(env_path):
        try:
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("BRIDGE_KEY"):
                        key = line.split("=", 1)[1].strip().strip('"').strip("'")
                        if key:
                            log.info("BRIDGE_KEY dibaca dari %s", env_path)
                            return key
        except Exception as e:
            log.error("Gagal baca %s: %s", env_path, e)

    log.error("BRIDGE_KEY tidak ditemukan di manapun.")
    return ""


API_KEY = _load_api_key()
ALLOWED_PREFIX = "https://www.idx.co.id/"

app = Flask(__name__)


def _check_auth():
    if not API_KEY:
        return jsonify({
            "ok": False,
            "error": "server misconfigured: BRIDGE_KEY kosong. "
                     "Isi di .streamlit/secrets.toml",
        }), 500
    got = request.headers.get("X-Api-Key", "")
    if got != API_KEY:
        log.warning("Auth gagal dari %s (header=%r, expected_len=%d)",
                    request.remote_addr,
                    (got[:8] + "...") if got else None,
                    len(API_KEY))
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    return None


def _check_url(url):
    if not url or not url.startswith(ALLOWED_PREFIX):
        return jsonify({"ok": False, "error": f"URL tidak diizinkan: {url}"}), 400
    return None


def _bridge_ready_or_error():
    if idx_bridge is None:
        return jsonify({"ok": False, "error": "idx_bridge tidak ter-import"}), 503
    if not idx_bridge.available():
        return jsonify({
            "ok": False,
            "error": "port 9222 tidak aktif. Jalankan start_edge.bat.",
        }), 503
    return None


# ═══════════════════════════════════════════════════════════════
# ENDPOINTS
# ═══════════════════════════════════════════════════════════════
@app.route("/health")
def health():
    return jsonify({
        "ok": True,
        "bridge_available": bool(idx_bridge and idx_bridge.available()),
        "key_loaded": bool(API_KEY),
        "python": sys.version.split()[0],
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
    })


@app.route("/idx")
def idx_fetch():
    t0 = time.time()
    auth_err = _check_auth()
    if auth_err:
        return auth_err

    url = request.args.get("url", "").strip()
    url_err = _check_url(url)
    if url_err:
        log.warning("URL ditolak: %r", url[:200])
        return url_err

    bridge_err = _bridge_ready_or_error()
    if bridge_err:
        return bridge_err

    log.info("→ GET /idx  %s", url)
    try:
        data = idx_bridge.fetch_json(url)
        log.info("← OK %.2fs type=%s", time.time() - t0, type(data).__name__)
        return jsonify({"ok": True, "data": data})
    except idx_bridge.IDXBridgeError as e:
        log.error("✗ IDXBridgeError setelah %.2fs: %s",
                  time.time() - t0, e)
        log.error(traceback.format_exc())
        return jsonify({
            "ok": False,
            "error": str(e),
            "error_type": "IDXBridgeError",
            "url": url,
        }), 502
    except Exception as e:
        log.error("✗ Unexpected %s setelah %.2fs: %s",
                  type(e).__name__, time.time() - t0, e)
        log.error(traceback.format_exc())
        return jsonify({
            "ok": False,
            "error": f"unexpected: {e}",
            "error_type": type(e).__name__,
            "url": url,
        }), 500


@app.route("/idx-many", methods=["POST"])
def idx_fetch_many():
    t0 = time.time()
    auth_err = _check_auth()
    if auth_err:
        return auth_err

    body = request.get_json(silent=True) or {}
    urls = body.get("urls", [])
    if not isinstance(urls, list) or not urls:
        return jsonify({"ok": False, "error": "urls harus list non-kosong"}), 400
    if len(urls) > 500:
        return jsonify({"ok": False, "error": "maks 500 URL per request"}), 400
    for u in urls:
        if not isinstance(u, str) or not u.startswith(ALLOWED_PREFIX):
            return jsonify({"ok": False, "error": f"URL tidak diizinkan: {u}"}), 400

    bridge_err = _bridge_ready_or_error()
    if bridge_err:
        return bridge_err

    log.info("→ POST /idx-many  n=%d", len(urls))
    try:
        data = idx_bridge.fetch_json_many(urls)
        log.info("← OK-many %.2fs", time.time() - t0)
        return jsonify({"ok": True, "data": data})
    except idx_bridge.IDXBridgeError as e:
        log.error("✗ IDXBridgeError (many) %.2fs: %s",
                  time.time() - t0, e)
        log.error(traceback.format_exc())
        return jsonify({
            "ok": False,
            "error": str(e),
            "error_type": "IDXBridgeError",
        }), 502
    except Exception as e:
        log.error("✗ Unexpected (many) %s: %s", type(e).__name__, e)
        log.error(traceback.format_exc())
        return jsonify({
            "ok": False,
            "error": f"unexpected: {e}",
            "error_type": type(e).__name__,
        }), 500


@app.route("/idx-debug")
def idx_debug():
    """Debug: kembalikan detail error + traceback langsung ke klien.
    Tetap butuh X-Api-Key."""
    auth_err = _check_auth()
    if auth_err:
        return auth_err

    url = request.args.get("url", "").strip()
    url_err = _check_url(url)
    if url_err:
        return url_err
    bridge_err = _bridge_ready_or_error()
    if bridge_err:
        return bridge_err

    info = {
        "url": url,
        "bridge_available": idx_bridge.available(),
        "python": sys.version.split()[0],
    }
    t0 = time.time()
    try:
        data = idx_bridge.fetch_json(url)
        info.update({
            "ok": True,
            "elapsed_s": round(time.time() - t0, 3),
            "data_type": type(data).__name__,
            "data_preview": str(data)[:1000],
        })
        return jsonify(info)
    except idx_bridge.IDXBridgeError as e:
        tb = traceback.format_exc()
        log.error("idx-debug IDXBridgeError: %s\n%s", e, tb)
        info.update({
            "ok": False,
            "elapsed_s": round(time.time() - t0, 3),
            "error_type": "IDXBridgeError",
            "error": str(e),
            "traceback": tb,
        })
        return jsonify(info), 502
    except Exception as e:
        tb = traceback.format_exc()
        log.error("idx-debug unexpected: %s\n%s", e, tb)
        info.update({
            "ok": False,
            "elapsed_s": round(time.time() - t0, 3),
            "error_type": type(e).__name__,
            "error": str(e),
            "traceback": tb,
        })
        return jsonify(info), 500


if __name__ == "__main__":
    log.info("=" * 60)
    log.info("Bridge Server — untuk Streamlit Cloud")
    log.info("=" * 60)
    if API_KEY:
        log.info("API Key    : %s...%s  (panjang: %d)",
                 API_KEY[:6], API_KEY[-4:], len(API_KEY))
    else:
        log.error("API Key    : TIDAK ADA — semua request akan ditolak!")
    log.info("Port       : 5001")
    log.info("Python     : %s", sys.executable)

    log.info("[*] Cek Edge CDP...")
    if idx_bridge and idx_bridge.available():
        log.info("    ✅ Port 9222 aktif — Edge CDP siap")
    else:
        log.error("    ❌ Port 9222 TIDAK aktif! Jalankan start_edge.bat dulu.")

    log.info("[*] Test lokal  : http://127.0.0.1:5001/health")
    log.info("[*] Debug fetch : http://127.0.0.1:5001/idx-debug?url=...")
    log.info("[*] Untuk cloud : .\\ngrok http 5001")
    log.info("=" * 60)

    app.run(host="127.0.0.1", port=5001, debug=False)
