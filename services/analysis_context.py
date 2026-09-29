"""
Analysis context loaders — fundamental, bandarmology, foreign flow, news.

Dipisah dari analyze_stock supaya:
  - Reusable (bisa dipakai scanner / CLI)
  - Mudah di-mock saat testing
  - analyze_stock jadi orchestrator tipis

Catatan: file di services/ karena butuh st.cache_data + Sheets/yfinance.
"""
from __future__ import annotations

import re

import numpy as np
import streamlit as st
import yfinance as yf

from config.brokers import get_broker_label
from core.bandarmology import (
    compute_multi_day_bandar_score,
    format_broker_list_for_ai,
)
from services.sheets_client import (
    load_broksum_history,
    get_latest_broksum_for_ticker,
    load_foreign_flow_history,
)
from services.news_client import (
    get_google_news_rss, get_kontan_news, get_cnbc_rss_news, get_ipot_news,
    filter_relevant, analyze_sentiment_weighted,
    TRANSLATOR_AVAILABLE, GoogleTranslator,
)


RETAIL_BROKERS_TRAP = {"YP", "PD", "XC", "KK", "NI", "CC"}


# ═══════════════════════════════════════════════════════════════
# SECTION 4 — FUNDAMENTAL
# ═══════════════════════════════════════════════════════════════
@st.cache_data(ttl=3600, show_spinner=False)
def _safe_ticker_info(ticker):
    try:
        return yf.Ticker(ticker).info or {}
    except Exception:
        return {}


def load_fundamental(ticker_input: str) -> dict:
    """Load ticker_info + fundamental metrics."""
    info = _safe_ticker_info(ticker_input)
    return {
        "ticker_info": info,
        "mc": info.get('marketCap'),
        "per": info.get('trailingPE') or info.get('forwardPE'),
        "pbv": info.get('priceToBook'),
        "roe": info.get('returnOnEquity'),
        "de": info.get('debtToEquity'),
    }


# ═══════════════════════════════════════════════════════════════
# SECTION 4.5 — BANDARMOLOGY + FOREIGN FLOW
# ═══════════════════════════════════════════════════════════════
def load_bandar_and_foreign(ticker_raw: str) -> dict:
    """
    Load bandar flow (multi-day broksum) + foreign flow z-score.
    Return dict: bandar_flow_val, foreign_zscore_val,
                 is_retail_trap, bandar_metadata
    """
    bandar_flow_val = 0.0
    foreign_zscore_val = 0.0
    is_retail_trap = False
    bandar_metadata = {}

    # Multi-day bandar score
    _history = load_broksum_history(ticker_raw)
    bandar_multi = compute_multi_day_bandar_score(_history, days=10)

    if bandar_multi.get('n_snapshots', 0) > 0:
        bandar_flow_val = bandar_multi['score']
        bandar_metadata = bandar_multi

        # Retail trap detection
        latest_bs = get_latest_broksum_for_ticker(ticker_raw)
        if latest_bs:
            top_buyers_latest = latest_bs.get('top_buyers', [])
            top_sellers_latest = latest_bs.get('top_sellers', [])

            top_3_buyer_codes = {
                str(b.get("broker", "")).upper()
                for b in top_buyers_latest[:3] if isinstance(b, dict)
            }
            top_3_seller_codes = {
                str(s.get("broker", "")).upper()
                for s in top_sellers_latest[:3] if isinstance(s, dict)
            }

            bandar_sellers = len(top_3_seller_codes - RETAIL_BROKERS_TRAP)
            if (len(top_3_buyer_codes.intersection(RETAIL_BROKERS_TRAP)) >= 2
                    and bandar_sellers >= 2):
                is_retail_trap = True

    # Foreign flow z-score
    foreign_df = load_foreign_flow_history(ticker_raw, days=30)
    if foreign_df is not None and not foreign_df.empty and 'net_foreign' in foreign_df.columns:
        if len(foreign_df) >= 5:
            net_f = foreign_df['net_foreign'].values
            mean_20 = np.mean(net_f[-20:]) if len(net_f) >= 20 else np.mean(net_f)
            std_20 = np.std(net_f[-20:]) if len(net_f) >= 20 else np.std(net_f)
            if std_20 > 0:
                recent_5_mean = np.mean(net_f[-5:])
                z = (recent_5_mean - mean_20) / std_20
                foreign_zscore_val = float(np.clip(z / 2.0, -1.0, 1.0))

    return {
        "bandar_flow_val": bandar_flow_val,
        "foreign_zscore_val": foreign_zscore_val,
        "is_retail_trap": is_retail_trap,
        "bandar_metadata": bandar_metadata,
    }


# ═══════════════════════════════════════════════════════════════
# SECTION 5 — NEWS + SENTIMENT
# ═══════════════════════════════════════════════════════════════
def load_news_and_sentiment(ticker_raw: str, ticker_info: dict) -> dict:
    """
    Kumpulkan berita dari Google News + Kontan + CNBC + Ipotnews,
    filter relevansi, hitung sentimen tertimbang.
    Return dict: avg_sentiment, sentimen_status, headlines, sources, translated
    """
    news_pool = []
    translator_en = GoogleTranslator(source='auto', target='en') if TRANSLATOR_AVAILABLE else None
    translator_id = GoogleTranslator(source='auto', target='id') if TRANSLATOR_AVAILABLE else None

    # Cari long name
    _long_name = ""
    if isinstance(ticker_info, dict):
        _ln = ticker_info.get("longName", "") or ticker_info.get("shortName", "") or ""
        _ln = re.sub(r'\b(Tbk|PT|Persero|Perseroan|Terbuka)\b', '', _ln, flags=re.IGNORECASE).strip()
        if len(_ln) > 5:
            _long_name = _ln

    _queries = [f'{ticker_raw} saham']
    if _long_name:
        _queries.append(f'"{_long_name}" saham')

    rss_all = []
    for _q in _queries:
        _r, _ = get_google_news_rss(_q, num=10, days_back=30)
        if _r:
            rss_all.extend(_r)

    # Dedup by title
    _seen = set()
    rss = []
    for n in rss_all:
        if n['title'] not in _seen:
            _seen.add(n['title'])
            rss.append(n)
    rss = rss[:15]

    if rss:
        news_pool.extend(rss)

    kontan, _ = get_kontan_news(ticker_raw, ticker_info=ticker_info)
    if kontan:
        news_pool.extend(kontan)
    cnbc, _ = get_cnbc_rss_news(ticker_raw, ticker_info=ticker_info)
    if cnbc:
        news_pool.extend(cnbc)
    ipot, _ = get_ipot_news(f"{ticker_raw}")
    if ipot:
        news_pool.extend(ipot)

    # Filter per sumber
    google_news = filter_relevant(
        [n for n in news_pool if n.get('source') == 'Google News'],
        ticker_raw, ticker_info=ticker_info,
    )
    other_news = filter_relevant(
        [n for n in news_pool if n.get('source') != 'Google News'],
        ticker_raw, ticker_info=ticker_info,
    )

    TARGET_TOTAL = 5
    MAX_OTHER = 2

    other_take = other_news[:MAX_OTHER]
    google_quota = TARGET_TOTAL - len(other_take)
    google_take = google_news[:google_quota]

    final_news = []
    for i in range(max(len(google_take), len(other_take))):
        if i < len(other_take):
            final_news.append(other_take[i])
        if i < len(google_take):
            final_news.append(google_take[i])

    seen = set()
    unique_news = []
    for n in final_news:
        if n['title'] not in seen:
            seen.add(n['title'])
            unique_news.append(n)
        if len(unique_news) >= TARGET_TOTAL:
            break

    avg_sentiment = analyze_sentiment_weighted(unique_news, translator_en)
    headlines = [n['title'] for n in unique_news]
    sources = [n['source'] for n in unique_news]

    translated = []
    for n in unique_news:
        if TRANSLATOR_AVAILABLE and translator_id:
            try:
                translated.append(translator_id.translate(n['title']))
            except Exception:
                translated.append("")
        else:
            translated.append("")

    sentimen_status = (
        "Positif 🟢" if avg_sentiment >= 0.05
        else ("Negatif 🔴" if avg_sentiment <= -0.05 else "Netral ⚪")
    )

    return {
        "avg_sentiment": avg_sentiment,
        "sentimen_status": sentimen_status,
        "headlines": headlines,
        "sources": sources,
        "translated": translated,
    }