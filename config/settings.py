"""Konstanta global engine (threshold, weight, model)."""

# ── V12 Adaptive Engine ──
FACTOR_KEYS = [
    "Momentum", "AI_Senti", "MeanRev", "Beta_IHSG",
    "Coppock", "OFI", "Bandar_Flow", "Foreign_ZScore",
]
WEIGHT_MIN = 0.08
WEIGHT_MAX = 0.40
SOFTMAX_TEMP = 2.5
AI_SIGNAL_CAP = 0.30
MC_PESSIMISM = 0.82

# ── Gemini model prioritas (dari paling murah/reliable) ──
PREFERRED_GEMINI_MODELS = [
    # ═══ Kuota besar (500 RPD) — prioritas utama untuk volume ═══
    "gemini-3.1-flash-lite",
    "gemini-3.5-flash-lite",

    # ═══ Terbaru (20 RPD) — kualitas tinggi, backup ═══
    "gemini-3.8-flash",
    "gemini-3.7-flash",
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-3-flash",

    # ═══ Legacy 2.5 (20 RPD) — fallback terakhir ═══
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
]

# ── Cache TTL (detik) ──
TTL_INTRADAY = 120
TTL_DAILY = 300
TTL_NEWS = 600
TTL_IDX_SUMMARY = 1800
TTL_BROKSUM_CACHE = 1800       # 30 menit
TTL_STOCK_LIST = 86400         # 1 hari