"""
Typed accessor untuk st.session_state.

Manfaat:
  - Satu tempat untuk tahu key apa saja yang valid
  - Lazy init — key otomatis dibuat kalau belum ada
  - Type hints → IDE autocomplete
  - Mudah di-refactor kalau skema state berubah

Catatan: Fungsi di sini masih boleh import Streamlit (mereka bagian state layer).
"""
from __future__ import annotations

from typing import Any

import streamlit as st


# ═══════════════════════════════════════════════════════════════
# V12 MEMORY (self-learning weights)
# ═══════════════════════════════════════════════════════════════
def get_v12_memory() -> dict:
    """Return v12_memory dict — lazy init kalau belum ada."""
    if "v12_memory" not in st.session_state:
        st.session_state.v12_memory = {}
    return st.session_state.v12_memory


def set_v12_memory(mem: dict):
    st.session_state.v12_memory = mem


# ═══════════════════════════════════════════════════════════════
# RIWAYAT (analysis log)
# ═══════════════════════════════════════════════════════════════
def get_riwayat() -> list:
    if "riwayat" not in st.session_state:
        st.session_state.riwayat = []
    return st.session_state.riwayat


def set_riwayat(riwayat: list):
    st.session_state.riwayat = riwayat


# ═══════════════════════════════════════════════════════════════
# RIWAYAT ACTUAL (outcome log)
# ═══════════════════════════════════════════════════════════════
def get_riwayat_actual() -> dict:
    if "riwayat_actual" not in st.session_state:
        st.session_state.riwayat_actual = {}
    return st.session_state.riwayat_actual


def set_riwayat_actual(actual: dict):
    st.session_state.riwayat_actual = actual


# ═══════════════════════════════════════════════════════════════
# BROKSUM CACHE
# ═══════════════════════════════════════════════════════════════
def get_broksum_cache_state() -> list:
    return st.session_state.get("broksum_cache", [])


def get_broksum_cache_time() -> float:
    return st.session_state.get("_broksum_cache_time", 0)


# ═══════════════════════════════════════════════════════════════
# SIDEBAR STATE (input yang di-set oleh fragment)
# ═══════════════════════════════════════════════════════════════
def get_ticker_input(default: str = "BBRI.JK") -> str:
    return st.session_state.get("_sb_ticker_input", default)


def get_harga_manual() -> str:
    return st.session_state.get("_sb_harga_manual", "")


def get_harga_terakhir_manual():
    return st.session_state.get("_sb_harga_terakhir_manual", None)


def get_sudah_beli() -> bool:
    return st.session_state.get("_sb_sudah_beli", False)


def get_harga_beli_float():
    return st.session_state.get("_sb_harga_beli_float", None)


def get_fee_beli_pct() -> float:
    return st.session_state.get("_sb_fee_beli_pct", 0.15)


def get_fee_jual_pct() -> float:
    return st.session_state.get("_sb_fee_jual_pct", 0.25)


def get_mode_scan(default: str = "Cepat (LQ45)") -> str:
    return st.session_state.get("_sb_mode_scan", default)


def get_likuiditas_min(default: int = 300_000_000) -> int:
    return st.session_state.get("_sb_likuiditas_min", default)


def get_hide_active_swings() -> bool:
    return st.session_state.get("_sb_hide_active_swings", False)


def get_ai_rerank() -> bool:
    return st.session_state.get("_sb_ai_rerank", False)


def get_aksi_simpan_mode() -> str:
    return st.session_state.get("aksi_simpan_mode", "simpan_baru")


def get_gemini_api_key_state() -> str:
    return st.session_state.get("gemini_api_key", "")


def set_gemini_api_key_state(key: str):
    st.session_state.gemini_api_key = key


# ═══════════════════════════════════════════════════════════════
# BUTTON FLAGS (event based)
# ═══════════════════════════════════════════════════════════════
def pop_run_btn() -> bool:
    return st.session_state.pop("_sb_run_btn", False)


def pop_scan_btn() -> bool:
    return st.session_state.pop("_sb_scan_btn", False)


def pop_ai_riwayat_btn() -> bool:
    return st.session_state.pop("_sb_ai_riwayat_btn", False)


# ═══════════════════════════════════════════════════════════════
# SCAN RESULTS (scanner history)
# ═══════════════════════════════════════════════════════════════
def get_scan_results() -> dict | None:
    return st.session_state.get("scan_results")


# ═══════════════════════════════════════════════════════════════
# GENERIC HELPERS
# ═══════════════════════════════════════════════════════════════
def get_key(key: str, default: Any = None) -> Any:
    return st.session_state.get(key, default)


def set_key(key: str, value: Any):
    st.session_state[key] = value


def has_key(key: str) -> bool:
    return key in st.session_state