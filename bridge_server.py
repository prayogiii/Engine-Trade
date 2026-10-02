"""
Bridge server — jalan di PC lokal. Terima request dari Streamlit Cloud,
forward ke idx_bridge (Edge CDP), return JSON.

API key dibaca dari urutan prioritas:
  1. Environment variable  BRIDGE_KEY
  2. File .streamlit/secrets.toml  (key: BRIDGE_KEY)  ← sumber utama
  3. File .env                     (key: BRIDGE_KEY)

Jalankan:
    python bridge_server.py

Butuh:
    pip install flask
    Edge sudah jalan dengan --remote-debugging-port=9222 (start_edge.bat)
"""
import os
import sys
import time
import traceback

from flask import Flask, jsonify, request

# Pastikan folder services ada di path
ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT, "services"))

try:
    import idx_bridge
except ImportError as e:
    print(f"[!] idx_bridge gagal di-import: {e}")
    idx_bridge = None


# ═══════════════════════════════════════════════════════════════
# BACA API KEY — multi-sumber
# ═══════════════════════════════════════════════════════════════
def _load_api_key() -> str:
    # 1) Environment variable
    key = os.environ.get("BRIDGE_KEY", "").strip()
    if key:
        print("[✓] BRIDGE_KEY dibaca dari environment variable")
        return key

    # 2) .streamlit/secrets.toml
    secrets_path = os.path.join(ROOT, ".streamlit", "secrets.toml")
    if os.path.isfile(secrets_path):
        try:
            try:
                import tomllib  # Python 3.11+
                with open(secrets_path, "rb") as f:
                    data = tomllib.load(f)
            except ImportError:
                import toml  # pip install toml
                with open(secrets_path, "r", encoding="utf-8") as f:
                    data = toml.load(f)

            key = str(data.get("BRIDGE_KEY", "")).strip()
            if key:
                print(f"[✓] BRIDGE_KEY dibaca dari {secrets_path}")
                return key
            else:
                print(f"[!] {secrets_path} ada tapi tidak berisi BRIDGE_KEY")
        except Exception as e:
            print(f"[!] Gagal baca {secrets_path}: {e}")

    # 3) .env
    env_path = os.path.join(ROOT, ".env")
    if os.path.isfile(env_path):
        try:
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("BRIDGE_KEY"):
                        key = line.split("=", 1)[1].strip().strip('"').strip("'")
                        if key:
                            print(f"[✓] BRIDGE_KEY dibaca dari {env_path}")
                            return key
        except Exception as e:
            print(f"[!] Gagal baca {env_path}: {e}")

    print("[!] BRIDGE_KEY tidak ditemukan di manapun.")
    print("    Set di salah satu:")
    print(f"      - {secrets_path}")
    print(f"      - {env_path}")
    print("      - environment variable: set BRIDGE_KEY=...")
    return ""


API_KEY = _load_api_key()

# Batasi URL yang boleh di-fetch — hanya IDX
ALLOWED_PREFIX = "https://www.idx.co.id/"


# ═══════════════════════════════════════════════════════════════
# FLASK APP
# ═══════════════════════════════════════════════════════════════
app = Flask(__name__)


def _check_auth():
    if not API_KEY:
        return jsonify({
            "ok": False,
            "error": "server misconfigured: BRIDGE_KEY kosong. "
                     "Isi di .streamlit/secrets.toml",
        }), 500
    if request.headers.get("X-Api-Key") != API_KEY:
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    return None


def _check_url(url):
    if not url or not url.startswith(ALLOWED_PREFIX):
        return jsonify({"ok": False, "error": f"URL tidak diizinkan: {url}"}), 400
    return None


# ═══════════════════════════════════════════════════════════════
# ENDPOINTS
# ═══════════════════════════════════════════════════════════════
@app.route("/health")
def health():
    """Cek status bridge. Tidak butuh auth — biar gampang test."""
    return jsonify({
        "ok": True,
        "bridge_available": idx_bridge is not None and idx_bridge.available(),
        "key_loaded": bool(API_KEY),
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
    })


@app.route("/idx")
def idx_fetch():
    """Fetch satu URL IDX."""
    auth_err = _check_auth()
    if auth_err:
        return auth_err

    url = request.args.get("url", "").strip()
    url_err = _check_url(url)
    if url_err:
        return url_err

    if idx_bridge is None:
        return jsonify({"ok": False, "error": "idx_bridge tidak ter-import"}), 503
    if not idx_bridge.available():
        return jsonify({
            "ok": False,
            "error": "port 9222 tidak aktif. Jalankan start_edge.bat.",
        }), 503

    try:
        data = idx_bridge.fetch_json(url)
        return jsonify({"ok": True, "data": data})
    except idx_bridge.IDXBridgeError as e:
        return jsonify({"ok": False, "error": str(e)}), 502
    except Exception as e:
        traceback.print_exc()
        return jsonify({"ok": False, "error": f"unexpected: {e}"}), 500


@app.route("/idx-many", methods=["POST"])
def idx_fetch_many():
    """Fetch banyak URL IDX dalam satu sesi Edge."""
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

    if idx_bridge is None:
        return jsonify({"ok": False, "error": "idx_bridge tidak ter-import"}), 503
    if not idx_bridge.available():
        return jsonify({
            "ok": False,
            "error": "port 9222 tidak aktif. Jalankan start_edge.bat.",
        }), 503

    try:
        data = idx_bridge.fetch_json_many(urls)
        return jsonify({"ok": True, "data": data})
    except idx_bridge.IDXBridgeError as e:
        return jsonify({"ok": False, "error": str(e)}), 502
    except Exception as e:
        traceback.print_exc()
        return jsonify({"ok": False, "error": f"unexpected: {e}"}), 500


# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════
if __name__ == "__main__":
    print("=" * 60)
    print("Bridge Server — untuk Streamlit Cloud")
    print("=" * 60)

    if API_KEY:
        print(f"API Key    : {API_KEY[:6]}...{API_KEY[-4:]}  (panjang: {len(API_KEY)})")
    else:
        print("API Key    : ❌ TIDAK ADA — semua request akan ditolak!")

    print("Port       : 5001")
    print()

    print("[*] Cek Edge CDP...")
    if idx_bridge and idx_bridge.available():
        print("    ✅ Port 9222 aktif — Edge CDP siap")
    else:
        print("    ❌ Port 9222 TIDAK aktif!")
        print("       Jalankan start_edge.bat dulu, buka IDX, klik verifikasi Cloudflare.")
    print()

    print("[*] Test lokal:")
    print("    http://127.0.0.1:5001/health")
    print()
    print("[*] Untuk cloud, jalankan ngrok di terminal lain:")
    print("    .\\ngrok http 5001")
    print("=" * 60)

    if not API_KEY:
        print()
        print("⚠️  PENTING: BRIDGE_KEY kosong.")
        print(f"    Buat file: {os.path.join(ROOT, '.streamlit', 'secrets.toml')}")
        print('    Isi: BRIDGE_KEY = "random-string-panjang-kamu"')
        print()

    app.run(host="127.0.0.1", port=5001, debug=False)