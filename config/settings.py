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
    "gemini-2.5-flash-lite",
    "gemini-2.0-flash-lite",
    "gemini-2.0-flash",
    "gemini-2.5-flash",
    "gemini-1.5-flash-lite",
    "gemini-1.5-flash",
    "gemini-flash-lite-latest",
    "gemini-flash-latest",
]

# ── Cache TTL (detik) ──
TTL_INTRADAY = 120
TTL_DAILY = 300
TTL_NEWS = 600
TTL_IDX_SUMMARY = 1800
TTL_BROKSUM_CACHE = 1800       # 30 menit
TTL_STOCK_LIST = 86400         # 1 hari