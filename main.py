"""
QuantRisk Pro — entry point utama.

File ini adalah orchestrator tipis:
  1. Page config + dark-mode styling
  2. Session state initialization (Sheets)
  3. Render sidebar
  4. Baca input dari sidebar
  5. Dispatch ke halaman: analysis flow / scanner / dashboard / AI riwayat

Semua logic bisnis ada di:
  - config/     → konstanta
  - core/       → pure logic
  - services/   → I/O & pipeline
  - ui/pages/   → halaman (sidebar, scanner, dashboard, analysis, ai_riwayat)
  - ui/charts/  → chart renderer
  - ui/components/ → komponen reusable
"""
import streamlit as st

# ── Services (init Sheets & session) ──
from services.sheets_client import (
    init_sheets,
    get_broksum_cache,
    load_v12_memory,
    muat_riwayat_dari_sheets,
    muat_riwayat_actual,
    evaluate_pending_signals,
)

# ── UI Pages ──
from ui.pages.sidebar import render_sidebar
from ui.pages.scanner_page import render_scanner_page
from ui.pages.dashboard_page import render_dashboard_page
from ui.pages.analysis_flow_page import render_analysis_flow_page
from ui.pages.ai_riwayat_page import render_ai_riwayat_page
from ui.pages.bandarmology_tab import display_bandarmology_tab


# ═══════════════════════════════════════════════════════════════
# PAGE CONFIG + DARK MODE FORCE
# ═══════════════════════════════════════════════════════════════
st.set_page_config(
    page_title="Quant Risk Engine Pro v2",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
    <style>
    html, body, [data-testid="stAppViewContainer"] { color-scheme: dark !important; }
    #MainMenu { visibility: hidden !important; }
    footer { visibility: hidden !important; }
    .stDeployButton { display: none !important; }
    [data-testid="stAppViewContainer"],
    [data-testid="stHeader"],
    [data-testid="stSidebar"],
    [data-testid="stBottom"] {
        background-color: #0f1116 !important;
    }
    [data-testid="stAppViewContainer"] * { color-scheme: dark; }
    .main { background-color: #0f1116; color: #ffffff; }
    div[data-testid="stMetricValue"] { font-size: 24px; font-weight: bold; color: #00ffcc; }
    div[data-testid="stMetricLabel"] { font-size: 14px; color: #8892b0; }
    .stButton>button { width: 100%; background-color: #1f2937; color: white; border: 1px solid #374151; }
    .stButton>button:hover { background-color: #374151; border-color: #00ffcc; }
    h1, h2, h3 { color: #f3f4f6; }
    .translated { color: #cbd5e1; font-size: 13px; }
    .source { color: #6b7280; font-size: 11px; }
    .summary-card { background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%); border-radius: 16px; padding: 20px; margin: 10px 0; border: 1px solid #334155; }
    .action-card { background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%); border-radius: 16px; padding: 20px; margin: 10px 0; border-left: 5px solid #00ffcc; }
    .section-title { color: #00ffcc; font-size: 18px; font-weight: bold; margin-bottom: 12px; }
    .summary-item { color: #cbd5e1; font-size: 15px; margin-bottom: 8px; }
    .fundamental-table { width: 100%; border-collapse: collapse; color: #cbd5e1; }
    .fundamental-table td { padding: 6px 12px; border-bottom: 1px solid #334155; }
    .fundamental-table td:first-child { color: #8892b0; width: 180px; }
    .ai-insight-card { background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%); border-radius: 16px; padding: 20px; margin: 15px 0; border-left: 5px solid #8b5cf6; color: #cbd5e1; font-size: 15px; line-height: 1.6; }
    .ai-insight-card h3 { color: #a78bfa; margin-top: 0; font-size: 20px; }
    .ai-insight-card p { margin-bottom: 10px; }
    </style>
""", unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════
# SESSION STATE INIT (Sheets)
# ═══════════════════════════════════════════════════════════════
if "sheets_initialized" not in st.session_state:
    init_sheets()
    st.session_state.sheets_initialized = True

if 'broksum_cache' not in st.session_state:
    get_broksum_cache()

if 'v12_memory' not in st.session_state:
    st.session_state.v12_memory = load_v12_memory()

if "riwayat" not in st.session_state:
    st.session_state.riwayat = muat_riwayat_dari_sheets()

if "riwayat_actual" not in st.session_state:
    st.session_state.riwayat_actual = muat_riwayat_actual()

if "signal_eval_done" not in st.session_state:
    try:
        _eval_result = evaluate_pending_signals(max_eval=30)
        st.session_state.last_eval_result = _eval_result
        st.session_state.signal_eval_done = True
    except Exception:
        st.session_state.signal_eval_done = True


# ═══════════════════════════════════════════════════════════════
# RENDER SIDEBAR
# ═══════════════════════════════════════════════════════════════
render_sidebar()


# ═══════════════════════════════════════════════════════════════
# BACA STATE DARI SIDEBAR
# ═══════════════════════════════════════════════════════════════
ticker_input = st.session_state.get('_sb_ticker_input', 'BBRI.JK')
harga_manual = st.session_state.get('_sb_harga_manual', '')
harga_terakhir_manual = st.session_state.get('_sb_harga_terakhir_manual', None)
sudah_beli = st.session_state.get('_sb_sudah_beli', False)
harga_beli_float = st.session_state.get('_sb_harga_beli_float', None)
fee_beli_pct = st.session_state.get('_sb_fee_beli_pct', 0.15)
fee_jual_pct = st.session_state.get('_sb_fee_jual_pct', 0.25)

run_btn = st.session_state.pop('_sb_run_btn', False)
scan_btn = st.session_state.pop('_sb_scan_btn', False)
ai_riwayat_btn = st.session_state.pop('_sb_ai_riwayat_btn', False)

mode_scan = st.session_state.get('_sb_mode_scan', 'Cepat (LQ45)')
likuiditas_min = st.session_state.get('_sb_likuiditas_min', 300_000_000)
hide_active_swings = st.session_state.get('_sb_hide_active_swings', False)
ai_rerank = st.session_state.get('_sb_ai_rerank', False)

ticker_raw = ticker_input.replace('.JK', '').strip().upper()


# ═══════════════════════════════════════════════════════════════
# DISPATCH KE HALAMAN
# ═══════════════════════════════════════════════════════════════

# 1. Analisis saham (jika tombol diklik)
render_analysis_flow_page(
    run_btn, ticker_input, ticker_raw, harga_manual, harga_terakhir_manual,
    sudah_beli, harga_beli_float, fee_beli_pct, fee_jual_pct,
    display_bandarmology_tab_fn=display_bandarmology_tab,
)

# 2. Scanner saham IDX
render_scanner_page(scan_btn, mode_scan, likuiditas_min, ai_rerank)

# 3. Dashboard (kalau tidak ada hasil scan aktif)
if not st.session_state.get('scan_results'):
    render_dashboard_page()

# 4. Analisis riwayat dengan AI (dari tombol sidebar)
render_ai_riwayat_page(ai_riwayat_btn)