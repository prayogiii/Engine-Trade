"""OCR fallback untuk scan broksum — hemat kuota Gemini. Lazy import."""
from __future__ import annotations

import re

import numpy as np
import streamlit as st

PIL_AVAILABLE = True
try:
    from PIL import Image
except ImportError:
    PIL_AVAILABLE = False


# Lazy getter — cache di module-level supaya hanya di-import sekali
_easyocr_reader = None
_easyocr_checked = False
_pytesseract_available = None


def _get_easyocr_reader():
    """Lazy import easyocr. Return reader atau None."""
    global _easyocr_reader, _easyocr_checked
    if _easyocr_checked:
        return _easyocr_reader

    _easyocr_checked = True
    try:
        import easyocr
        _easyocr_reader = easyocr.Reader(["id", "en"], gpu=False)
    except Exception:
        _easyocr_reader = None
    return _easyocr_reader


def _is_pytesseract_available():
    global _pytesseract_available
    if _pytesseract_available is None:
        try:
            import pytesseract  # noqa: F401
            _pytesseract_available = True
        except Exception:
            _pytesseract_available = False
    return _pytesseract_available


def analisis_broksum_ocr(image):
    """Analisis screenshot Broksum pakai OCR offline."""
    if not PIL_AVAILABLE:
        return None, "Library Pillow (PIL) belum terpasang."

    extracted_text = ""
    engine_used = ""

    # Strategy 1: EasyOCR (lazy)
    reader = _get_easyocr_reader()
    if reader is not None:
        try:
            img_np = np.array(image.convert("RGB"))
            results = reader.readtext(img_np, detail=0)
            extracted_text = "\n".join(results)
            engine_used = "EasyOCR"
        except Exception:
            extracted_text = ""

    # Strategy 2: PyTesseract (lazy)
    if not extracted_text and _is_pytesseract_available():
        try:
            import pytesseract
            extracted_text = pytesseract.image_to_string(image)
            engine_used = "PyTesseract"
        except Exception:
            extracted_text = ""

    if not extracted_text:
        return None, "Library OCR (EasyOCR / PyTesseract) belum terpasang di server."

    known_brokers = {
        "YP", "BK", "ZP", "AK", "KZ", "NI", "GR", "RX", "PD", "CC", "CP", "DX", "AZ", "DR",
        "LG", "IF", "OD", "XC", "EP", "YU", "XL", "AI", "DB", "IU", "TP", "HD", "YJ", "CS",
        "KK", "MG", "SQ", "XA", "LS", "BD", "AT", "AN", "OD", "YU", "GA", "RG", "CD",
    }

    buyers = []
    sellers = []
    lines = extracted_text.split("\n")
    is_seller = False

    for line in lines:
        u_line = line.upper()
        if "SELL" in u_line or "SELLER" in u_line or "NET SELL" in u_line:
            is_seller = True

        found_brks = re.findall(r"\b([A-Z]{2})\b", u_line)
        numbers = re.findall(r"\b(\d+[\d\.,]*)\b", line)

        for brk in found_brks:
            if brk in known_brokers or len(found_brks) == 1:
                val = 0
                if numbers:
                    try:
                        val = int(numbers[0].replace(".", "").replace(",", ""))
                    except Exception:
                        val = 0
                item = {"broker": brk, "volume_lot": val, "value_idr": val * 100, "avg_price": 0.0}
                if is_seller:
                    sellers.append(item)
                else:
                    buyers.append(item)

    tot_b = sum(b["volume_lot"] for b in buyers)
    tot_s = sum(s["volume_lot"] for s in sellers)

    if tot_b > tot_s * 1.5:
        status = "Big Accumulation"
    elif tot_b > tot_s * 1.1:
        status = "Normal Accumulation"
    elif tot_s > tot_b * 1.5:
        status = "Big Distribution"
    elif tot_s > tot_b * 1.1:
        status = "Normal Distribution"
    else:
        status = "Neutral"

    narrative = f"Hasil OCR ({engine_used}): Terbaca {len(buyers)} Buyer, {len(sellers)} Seller. Status: {status}."

    return {
        "bandarmology_status": status,
        "foreign_flow_status": "Neutral",
        "summary_narrative": narrative,
        "top_buyers": buyers[:5],
        "top_sellers": sellers[:5],
    }, None