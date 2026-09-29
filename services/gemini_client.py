"""
Gemini client — key rotator 2D (key × model) + wrapper + high-level analyzer.

Semua interaksi dengan Gemini API lewat module ini. main.py tidak boleh
`import google.generativeai` langsung.
"""
from __future__ import annotations

import io
import json
import os
import re
import time

import google.generativeai as genai
import streamlit as st

from config.settings import PREFERRED_GEMINI_MODELS
from core.bandarmology import format_broker_list_for_ai
from prompts.stock_analysis import build_stock_analysis_prompt
from prompts.broksum_vision import BROKSUM_VISION_PROMPT
from prompts.mode_evaluation import build_mode_evaluation_prompt
from prompts.riwayat_analysis import build_riwayat_header, RIWAYAT_ANALYSIS_SUFFIX
from services.sheets_client import load_broksum_history


# ═══════════════════════════════════════════════════════════════
# PIL / IMAGE SUPPORT
# ═══════════════════════════════════════════════════════════════
PIL_AVAILABLE = True
try:
    from PIL import Image
except ImportError:
    PIL_AVAILABLE = False


def compress_image_for_gemini(image, max_width=1280, max_height=960, quality=85):
    """Kompresi gambar untuk hemat token Gemini Vision."""
    if not PIL_AVAILABLE:
        return image

    img = None
    try:
        if isinstance(image, str):
            img = Image.open(image)
        elif hasattr(image, "read"):
            try:
                image.seek(0)
            except Exception:
                pass
            img = Image.open(image)
        else:
            img = image

        if img is None:
            return image

        img.thumbnail((max_width, max_height), Image.Resampling.LANCZOS)

        if img.mode in ("RGBA", "LA", "P"):
            rgb_img = Image.new("RGB", img.size, (255, 255, 255))
            try:
                if img.mode == "RGBA":
                    rgb_img.paste(img, mask=img.split()[-1])
                else:
                    rgb_img.paste(img)
            except Exception:
                rgb_img.paste(img.convert("RGB"))
            img = rgb_img

        compressed_io = io.BytesIO()
        img.save(compressed_io, format="JPEG", quality=quality, optimize=True)
        compressed_io.seek(0)
        return Image.open(compressed_io)
    except Exception as e:
        st.warning(f"⚠️ Kompresi gambar gagal: {e}. Menggunakan gambar original.")
        return image


# ═══════════════════════════════════════════════════════════════
# API KEY MANAGEMENT
# ═══════════════════════════════════════════════════════════════
def _load_gemini_keys() -> list[str]:
    """Baca semua Gemini API key dari st.secrets atau env var."""
    keys = []

    try:
        raw = st.secrets.get("GEMINI_API_KEYS", None)
        if isinstance(raw, list):
            keys = [str(k).strip() for k in raw if k]
        elif isinstance(raw, str):
            raw_s = raw.strip()
            if raw_s.startswith("["):
                try:
                    parsed = json.loads(raw_s)
                    keys = [str(k).strip() for k in parsed if k]
                except Exception:
                    keys = [k.strip() for k in raw_s.split(",") if k.strip()]
            else:
                keys = [k.strip() for k in raw_s.split(",") if k.strip()]
    except Exception:
        pass

    if not keys:
        try:
            single = st.secrets.get("GEMINI_API_KEY", "")
            if single:
                keys = [single]
        except Exception:
            pass
    if not keys:
        env = os.getenv("GEMINI_API_KEY", "")
        if env:
            keys = [env]

    seen, out = set(), []
    for k in keys:
        k = str(k).strip()
        if k and len(k) >= 20 and k not in seen:
            seen.add(k)
            out.append(k)
    return out


def get_gemini_api_key() -> str:
    """Ambil key pertama (untuk display)."""
    keys = _load_gemini_keys()
    return keys[0] if keys else ""


def _get_key_rotator_state() -> dict:
    """State rotator 2D: key × model, disimpan di session_state."""
    if "_gemini_rotator" not in st.session_state:
        st.session_state._gemini_rotator = {
            "keys": _load_gemini_keys(),
            "current_idx": 0,
            "cooldown_until": {},
            "cooldown_combos": {},
            "models_cache": {},
            "cache_time": {},
        }
    state = st.session_state._gemini_rotator
    state.setdefault("cooldown_combos", {})
    state.setdefault("models_cache", {})
    state.setdefault("cache_time", {})
    return state


def _get_models_for_key(key_idx: int) -> list[str]:
    """Daftar model yang support generateContent untuk key ini (cache 1 jam)."""
    state = _get_key_rotator_state()
    keys = state["keys"]
    if key_idx >= len(keys):
        return PREFERRED_GEMINI_MODELS

    now = time.time()
    cached_time = state["cache_time"].get(key_idx, 0)
    if now - cached_time < 3600 and key_idx in state["models_cache"]:
        return state["models_cache"][key_idx]

    try:
        genai.configure(api_key=keys[key_idx])
        models = [
            m.name.split("/")[-1]
            for m in genai.list_models()
            if "generateContent" in m.supported_generation_methods
        ]
        ordered = [m for m in PREFERRED_GEMINI_MODELS if m in models]
        ordered += [m for m in models if m not in ordered]
        state["models_cache"][key_idx] = ordered
        state["cache_time"][key_idx] = now
        return ordered
    except Exception:
        state["models_cache"][key_idx] = PREFERRED_GEMINI_MODELS
        state["cache_time"][key_idx] = now
        return PREFERRED_GEMINI_MODELS


def _find_next_combo():
    """Return (key_idx, model_name, key) yang tersedia, atau (None, None, None)."""
    state = _get_key_rotator_state()
    keys = state["keys"]
    if not keys:
        return None, None, None

    now = time.time()
    n_keys = len(keys)

    for key_offset in range(n_keys):
        key_idx = (state["current_idx"] + key_offset) % n_keys
        if now < state["cooldown_until"].get(key_idx, 0):
            continue
        models = _get_models_for_key(key_idx)
        for model_name in models:
            combo_key = f"{key_idx}:{model_name}"
            if now < state["cooldown_combos"].get(combo_key, 0):
                continue
            return key_idx, model_name, keys[key_idx]

    return None, None, None


def _mark_combo_exhausted(key_idx: int, model_name: str, cooldown_sec: int = 70):
    """Tandai combo (key, model) cooldown."""
    state = _get_key_rotator_state()
    state["cooldown_combos"][f"{key_idx}:{model_name}"] = time.time() + cooldown_sec
    models = _get_models_for_key(key_idx)
    now = time.time()
    if all(now < state["cooldown_combos"].get(f"{key_idx}:{m}", 0) for m in models):
        state["cooldown_until"][key_idx] = now + cooldown_sec
        state["current_idx"] = (key_idx + 1) % len(state["keys"])


def get_active_gemini_key() -> str | None:
    key_idx, _, key = _find_next_combo()
    if key:
        return key
    state = _get_key_rotator_state()
    return state["keys"][0] if state["keys"] else None


def mark_gemini_key_exhausted(cooldown_sec: int = 70):
    """Backward compat — tandai key aktif cooldown."""
    state = _get_key_rotator_state()
    if not state["keys"]:
        return
    idx = state["current_idx"]
    state["cooldown_until"][idx] = time.time() + cooldown_sec
    state["current_idx"] = (idx + 1) % len(state["keys"])


def is_gemini_quota_error(err) -> bool:
    """Deteksi error 429/quota dari Gemini."""
    s = str(err).lower()
    signals = [
        "429", "quota", "rate limit", "resource_exhausted",
        "resource has been exhausted", "too many requests",
        "exceeded your current quota", "quota exceeded",
    ]
    return any(sig in s for sig in signals)


def configure_gemini_with_active_key() -> bool:
    """Configure genai pakai key aktif."""
    key = get_active_gemini_key()
    if not key:
        return False
    try:
        genai.configure(api_key=key)
        return True
    except Exception:
        return False


# ═══════════════════════════════════════════════════════════════
# CALL WRAPPER — 2D ROTATION
# ═══════════════════════════════════════════════════════════════
def call_gemini_auto_rotate(prompt, image=None, generation_config=None, max_retries=None):
    """2D rotation wrapper — coba semua kombinasi (key × model) saat kena 429."""
    if max_retries is None:
        state = _get_key_rotator_state()
        n_keys = max(1, len(state["keys"]))
        max_retries = max(10, n_keys * 5 + 4)

    last_err = None
    tried_combos = set()

    _image_errs = (
        "image dimensions", "image size", "image too large",
        "unsupported mime", "unsupported image", "invalid image",
        "failed to process image", "image format", "payload size",
        "request payload size exceeds", "invalid image data",
    )
    _model_invalid_errs = (
        "model not found", "model is not supported",
        "models/", "does not exist", "model does not exist",
    )
    _transient_errs = ("500", "503", "internal error", "overloaded", "temporarily")
    _safety_errs = ("safety", "blocked", "prohibited")

    for attempt in range(max_retries):
        key_idx, model_name, active_key = _find_next_combo()

        if not active_key or not model_name:
            state = _get_key_rotator_state()
            if state["cooldown_combos"]:
                earliest = min(state["cooldown_combos"].values())
                wait = max(1, min(20, earliest - time.time() + 1))
            else:
                wait = 2
            time.sleep(wait)
            continue

        combo_id = (key_idx, model_name)
        if combo_id in tried_combos:
            _mark_combo_exhausted(key_idx, model_name, cooldown_sec=70)
            continue
        tried_combos.add(combo_id)

        try:
            genai.configure(api_key=active_key)
            model = genai.GenerativeModel(model_name)
            content = [prompt, image] if image is not None else prompt

            if generation_config:
                response = model.generate_content(content, generation_config=generation_config)
            else:
                response = model.generate_content(content)

            return response.text.strip(), None

        except Exception as e:
            err_str = str(e)
            err_lower = err_str.lower()
            last_err = err_str

            if is_gemini_quota_error(e):
                _mark_combo_exhausted(key_idx, model_name, cooldown_sec=70)
                st.toast(f"🔄 {model_name} @ key#{key_idx+1} limit → rotate", icon="🔑")
                time.sleep(0.5)
                continue

            if any(x in err_lower for x in _image_errs):
                _mark_combo_exhausted(key_idx, model_name, cooldown_sec=300)
                st.toast(f"⚠️ {model_name} tolak image → coba model lain", icon="🖼️")
                continue

            if any(x in err_lower for x in _model_invalid_errs):
                _mark_combo_exhausted(key_idx, model_name, cooldown_sec=600)
                continue

            if any(x in err_lower for x in _transient_errs) and attempt < max_retries - 1:
                time.sleep(2 ** min(attempt, 3))
                continue

            if any(x in err_lower for x in _safety_errs):
                return None, f"Gambar diblokir safety filter Gemini: {err_str[:120]}"

            break

    return None, f"Gagal setelah {max_retries} percobaan: {last_err}"


def dapatkan_model_gemini(api_key=None):
    """Return (model, error). Auto-rotate kalau key kena limit."""
    state = _get_key_rotator_state()
    if not state["keys"] and api_key:
        state["keys"] = [api_key]

    if not state["keys"]:
        return None, "API key belum diisi."

    tried = 0
    max_tries = len(state["keys"]) + 1

    while tried < max_tries:
        active = get_active_gemini_key()
        if not active:
            return None, "Semua Gemini API key sedang cooldown."

        try:
            genai.configure(api_key=active)
            available = [
                m.name.split("/")[-1]
                for m in genai.list_models()
                if "generateContent" in m.supported_generation_methods
            ]
            if not available:
                return None, "Tidak ada model Gemini."

            for model_id in available:
                try:
                    model = genai.GenerativeModel(model_id)
                    model.generate_content("test", generation_config={"max_output_tokens": 1})
                    return model, None
                except Exception as e_inner:
                    if is_gemini_quota_error(e_inner):
                        mark_gemini_key_exhausted(70)
                        st.toast("🔄 Gemini key kena limit, rotate", icon="🔑")
                        break
                    continue
            else:
                return None, "Model gagal digunakan."

            tried += 1

        except Exception as e_outer:
            if is_gemini_quota_error(e_outer):
                mark_gemini_key_exhausted(70)
                tried += 1
                continue
            return None, f"Error: {str(e_outer)}"

    return None, "Semua Gemini API key sudah dicoba, gagal semua."


# ═══════════════════════════════════════════════════════════════
# UTILS
# ═══════════════════════════════════════════════════════════════
def bersihkan_teks_ai(teks: str) -> str:
    if not teks:
        return teks
    teks = re.sub(r"^#{1,3}\s*", "", teks, flags=re.MULTILINE)
    teks = re.sub(r"\*\*", "", teks)
    teks = re.sub(r"\*", "", teks)
    return teks.replace("\n", "<br>")


# ═══════════════════════════════════════════════════════════════
# HIGH-LEVEL ANALYZERS
# ═══════════════════════════════════════════════════════════════
def analisis_saham_dengan_ai(data_saham, riwayat, api_key, ticker=None):
    """Analisis saham dengan Gemini AI. ticker optional → fetch broksum dari DB."""
    riwayat_text = ""
    if riwayat:
        riwayat_text = "Riwayat analisis sebelumnya (termasuk hasil aktual jika tersedia):\n"
        for r in riwayat:
            base = f"- {r['Waktu']} | {r['Saham']} | Sinyal: {r['Sinyal']} | RRR: {r['RRR']} | Rezim: {r['Rezim']}"
            if r.get("Actual_High") or r.get("Actual_Outcome"):
                base += " | Hasil Aktual: "
                if r.get("Actual_High"):
                    base += f"High={r['Actual_High']}, "
                if r.get("Actual_Low"):
                    base += f"Low={r['Actual_Low']}, "
                if r.get("Actual_Close"):
                    base += f"Close={r['Actual_Close']}, "
                if r.get("Actual_Outcome"):
                    base += f"Outcome={r['Actual_Outcome']}"
                if r.get("Entry_Miss"):
                    base += " (Entry tidak tersentuh)"
            ai_insight = r.get("AI_Insight", "").strip()
            if ai_insight:
                short_insight = (ai_insight[:120] + "...") if len(ai_insight) > 120 else ai_insight
                base += f" | AI Insight: {short_insight}"
            riwayat_text += base + "\n"
    else:
        riwayat_text = "Belum ada riwayat sebelumnya."

    # ── Broksum context ──
    broksum_context = ""
    if ticker:
        try:
            history = load_broksum_history(ticker)
            if history:
                history_sorted = sorted(
                    history, key=lambda r: str(r.get("upload_date", "")), reverse=True
                )
                broksum_entries = []
                for h in history_sorted[:5]:
                    buyers_list = json.loads(h.get("top_buyers", "[]")) if isinstance(h.get("top_buyers"), str) else h.get("top_buyers", [])
                    sellers_list = json.loads(h.get("top_sellers", "[]")) if isinstance(h.get("top_sellers"), str) else h.get("top_sellers", [])
                    buyers_text, buyers_sum = format_broker_list_for_ai(buyers_list)
                    sellers_text, sellers_sum = format_broker_list_for_ai(sellers_list)
                    broksum_entries.append(
                        f"**Upload {h.get('upload_date', 'N/A')}**\n"
                        f"  Status Bandarmologi: {h.get('bandarmology_status', 'N/A')}\n"
                        f"  Pembeli (Komposisi: {buyers_sum}):\n{buyers_text}\n"
                        f"  Penjual (Komposisi: {sellers_sum}):\n{sellers_text}\n"
                        f"  Summary: {h.get('summary_narrative', 'N/A')[:180]}"
                    )
                broksum_context = (
                    f"**🕵🏻‍♂️ Bandarmology (Broker Flow) — {len(history_sorted)} snapshot terakhir**\n\n"
                    + "\n\n".join(broksum_entries)
                )
                if len(history_sorted) > 1:
                    broksum_context += (
                        f"\n\n**⚠️ PENTING:** Ada {len(history_sorted)} snapshot. "
                        f"Bandingkan perubahan dominasi Bandar 🐋 vs Retail 🧑 antar waktu "
                        f"untuk mendeteksi pola akumulasi atau distribusi secara presisi."
                    )
        except Exception:
            pass

    prompt = build_stock_analysis_prompt(data_saham, riwayat_text, broksum_context)
    response_text, err = call_gemini_auto_rotate(prompt)
    if err:
        return None, f"Gagal menghasilkan insight AI: {err}"
    return response_text, None


def analisis_riwayat_global(riwayat_data, riwayat_actual, api_key):
    if not riwayat_data:
        return None, "Belum ada riwayat."
    prompt = build_riwayat_header()
    for r in riwayat_data[:30]:
        gaya_label = "📆 SW" if r.get("Gaya") == "SW" else "⏱️ DT"
        base = f"- {r['Waktu']}|{gaya_label}|{r['Saham']}|Sinyal:{r['Sinyal']}|Harga:{r['Harga']}|RRR:{r['RRR']}|Sentimen:{r['Sentimen']}|Rezim:{r['Rezim']}|TP%:{r['TP%']}%|SL%:{r['SL%']}%"

        gaya = r.get("Gaya", "SW")
        key_actual = (r.get("Waktu"), r.get("Saham"), gaya)
        actual = riwayat_actual.get(key_actual) or riwayat_actual.get((r.get("Waktu"), r.get("Saham")), {})
        if actual:
            base += " | Hasil Aktual: "
            details = []
            if actual.get("Actual_High"):
                details.append(f"High={actual['Actual_High']}")
            if actual.get("Actual_Low"):
                details.append(f"Low={actual['Actual_Low']}")
            if actual.get("Actual_Close"):
                details.append(f"Close={actual['Actual_Close']}")
            if actual.get("Outcome"):
                details.append(f"Outcome={actual['Outcome']}")
            if actual.get("Entry_Miss") == "Yes":
                details.append("Entry Tidak Tersentuh")
            base += ", ".join(details)

        prompt += base + "\n"

    prompt += RIWAYAT_ANALYSIS_SUFFIX
    response_text, err = call_gemini_auto_rotate(prompt)
    if err:
        return None, err
    return response_text, None


def evaluasi_mode_dengan_ai(res_swing, res_day, ticker_raw, api_key):
    """Evaluasi AI Gemini untuk membandingkan mode Swing vs Day Trade."""
    prompt = build_mode_evaluation_prompt(res_swing, res_day, ticker_raw)

    gen_config = {"response_mime_type": "application/json"}
    raw_text, err = call_gemini_auto_rotate(prompt, generation_config=gen_config)

    if err or not raw_text:
        raw_text, err = call_gemini_auto_rotate(prompt)
        if err or not raw_text:
            return None, f"Gagal memanggil Gemini: {err}"

    # Tier 1: Direct
    try:
        data = json.loads(raw_text)
        if isinstance(data, dict) and "swing_score" in data:
            return data, None
    except Exception:
        pass

    # Tier 2: Extract object
    match = re.search(r'\{[^{}]*"swing_score"[^{}]*\}', raw_text, re.DOTALL)
    if not match:
        match = re.search(r"\{.*\}", raw_text, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group(0), strict=False)
            if isinstance(data, dict) and "swing_score" in data:
                return data, None
        except Exception:
            pass

    # Tier 3: Field-by-field
    swing_match = re.search(r'"swing_score"\s*:\s*(\d+(?:\.\d+)?)', raw_text)
    day_match = re.search(r'"day_score"\s*:\s*(\d+(?:\.\d+)?)', raw_text)
    reason_match = re.search(r'"reasoning"\s*:\s*"([^"]+)"', raw_text)
    if swing_match and day_match:
        return {
            "swing_score": float(swing_match.group(1)),
            "day_score": float(day_match.group(1)),
            "reasoning": reason_match.group(1) if reason_match else "Evaluasi AI Gemini untuk kesesuaian mode.",
        }, None

    return None, "Format JSON AI tidak dapat diparse"


# ═══════════════════════════════════════════════════════════════
# VISION — BROKSUM SCAN
# ═══════════════════════════════════════════════════════════════
def analisis_broksum_gemini_vision(image, api_key):
    """Scan Broksum pakai Gemini Vision (2D rotation)."""
    if not PIL_AVAILABLE:
        return None, "Library Pillow (PIL) belum terpasang."
    if not api_key:
        return None, "Gemini API Key belum diisi di sidebar."

    try:
        compressed_image = compress_image_for_gemini(
            image, max_width=1280, max_height=960, quality=85
        )

        response_text, err = call_gemini_auto_rotate(
            BROKSUM_VISION_PROMPT, image=compressed_image,
        )
        if err:
            return None, f"Error Gemini Vision: {err}"
        raw_text = response_text

        if "```json" in raw_text:
            raw_text = raw_text.split("```json")[1].split("```")[0].strip()
        elif "```" in raw_text:
            raw_text = raw_text.split("```")[1].split("```")[0].strip()

        try:
            parsed = json.loads(raw_text, strict=False)
            return parsed, None
        except Exception:
            match = re.search(r"\{.*\}", raw_text, re.DOTALL)
            if match:
                parsed = json.loads(match.group(0), strict=False)
                return parsed, None
            return {"summary_narrative": raw_text, "bandarmology_status": "Raw AI Response"}, None

    except Exception as e:
        return None, f"Error Gemini Vision: {str(e)}"