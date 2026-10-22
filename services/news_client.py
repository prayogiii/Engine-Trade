"""
News client — RSS, Google News, CNBC, Kontan, Ipotnews + sentiment analysis.

Menggabungkan:
  - Sumber berita (RSS, scraping)
  - Relevancy filter (3 tier: strict → medium → fallback)
  - Sentiment scoring (IDX Fin-Lexicon + VADER blended)
"""
from __future__ import annotations

import re
import time
import urllib.parse
from datetime import datetime, timedelta
import numpy as np
import streamlit as st
import yfinance as yf


# ═══════════════════════════════════════════════════════════════
# OPTIONAL DEPENDENCIES
# ═══════════════════════════════════════════════════════════════
RSS_AVAILABLE = True
try:
    import feedparser
except ImportError:
    RSS_AVAILABLE = False

SENTIMENT_AVAILABLE = None  # will be determined lazily


def _ensure_sentiment():
    """Lazy setup NLTK VADER (download sekali saja)."""
    global SENTIMENT_AVAILABLE
    if SENTIMENT_AVAILABLE is not None:
        return SENTIMENT_AVAILABLE

    try:
        import nltk
        from nltk.sentiment import SentimentIntensityAnalyzer
        try:
            nltk.data.find("sentiment/vader_lexicon.zip")
        except LookupError:
            nltk.download("vader_lexicon", quiet=True)
        SENTIMENT_AVAILABLE = True
    except ImportError:
        SENTIMENT_AVAILABLE = False
    return SENTIMENT_AVAILABLE

TRANSLATOR_AVAILABLE = True
try:
    from deep_translator import GoogleTranslator
except ImportError:
    TRANSLATOR_AVAILABLE = False
    GoogleTranslator = None


# ═══════════════════════════════════════════════════════════════
# STOPWORDS & LEXICON
# ═══════════════════════════════════════════════════════════════
_COMPANY_STOPWORDS = {
    "tbk", "pt", "persero", "perseroan", "terbuka", "indonesia",
    "the", "and", "of", "co", "ltd", "inc", "corp", "corporation",
    "group", "holdings", "holding", "international", "investments",
    "investment", "capital", "nusantara", "nasional", "utama", "global",
    "bank", "finance", "financial", "securities", "sekuritas",
    "energi", "energy", "resources", "mining", "tambang",
    "telekomunikasi", "telecom", "property", "properti",
    "agro", "agri", "industri", "industry", "trading",
    "multinational", "multi", "sentral", "prima", "jaya",
    "inti", "bumi", "sumber", "karya", "buana", "makmur",
    "graha", "mitra", "sarana", "dharma", "putra", "kencana",
    "media", "pers", "news", "kabar", "warta", "harian",
    "koran", "tabloid", "portal", "online", "times", "post",
    "tribune", "daily", "today",
}

IDX_FIN_LEXICON = {
    # Katalis Positif
    "dividen jumbo": +0.85, "dividen spesial": +0.80, "dividen interim": +0.70,
    "kenaikan dividen": +0.72, "buyback saham": +0.75, "buy back": +0.65,
    "buyback": +0.65, "tender offer": +0.80, "akuisisi": +0.60, "merger": +0.55,
    "kontrak baru": +0.72, "proyek baru": +0.65, "lonjakan laba": +0.82,
    "laba bersih meningkat": +0.78, "laba melonjak": +0.80,
    "pendapatan meningkat": +0.68, "rights issue standby buyer": +0.62,
    "standby buyer": +0.60, "ekspansi kapasitas": +0.58, "ekspansi bisnis": +0.55,
    "kemitraan strategis": +0.60, "pembelian kembali": +0.65,
    "restrukturisasi berhasil": +0.60, "pelunasan utang": +0.65,
    "upgrade rating": +0.70, "kenaikan target harga": +0.68,
    # Katalis Negatif
    "suspensi perdagangan": -0.92, "suspensi": -0.85,
    "dihentikan perdagangannya": -0.88, "penghentian perdagangan": -0.88,
    "pkpu": -0.92, "penundaan kewajiban pembayaran utang": -0.90,
    "pailit": -0.95, "kepailitan": -0.95, "bangkrut": -0.95,
    "default obligasi": -0.92, "gagal bayar": -0.88, "wanprestasi": -0.85,
    "repo gagal": -0.87, "pengunduran diri direksi mendadak": -0.78,
    "mundur direksi": -0.72, "pengunduran diri direktur": -0.70,
    "pengunduran diri": -0.55, "rugi bersih membengkak": -0.82,
    "rugi bersih meningkat": -0.78, "rugi bersih": -0.72,
    "kerugian meningkat": -0.70, "pendapatan turun": -0.60,
    "laba tergerus": -0.65, "uma": -0.72, "unusual market activity": -0.72,
    "reverse stock split": -0.68, "pemecahan saham terbalik": -0.68,
    "right issue tanpa standby": -0.55, "dilusi saham": -0.58,
    "penambahan modal tanpa hmetd": -0.65, "pmthmetd": -0.62,
    "gugatan": -0.62, "gugatan hukum": -0.68, "investigasi otoritas": -0.75,
    "sanksi ojk": -0.80, "pembekuan": -0.78, "delisting": -0.92,
    "force majeure": -0.60,
}


# ═══════════════════════════════════════════════════════════════
# KEYWORD BUILDER & RELEVANCY FILTER
# ═══════════════════════════════════════════════════════════════
def _build_ticker_keywords(ticker_raw, ticker_info=None):
    """Bangun keyword list dari ticker + longName/shortName yfinance."""
    keywords = set()
    ticker_clean = str(ticker_raw).upper().replace(".JK", "").strip()
    if not ticker_clean:
        return []
    keywords.add(ticker_clean.lower())

    if ticker_info and isinstance(ticker_info, dict):
        for field in ("longName", "shortName", "displayName"):
            name = ticker_info.get(field, "") or ""
            if not name:
                continue
            for word in re.split(r"[\s\-\(\)\,\.]+", name.lower()):
                word = word.strip()
                if len(word) >= 4 and word not in _COMPANY_STOPWORDS:
                    keywords.add(word)
    return sorted(keywords)


def filter_relevant(news_list, ticker, ticker_info=None):
    """Filter berita relevan — 3 tier (strict → medium → fallback)."""
    if not news_list:
        return []

    ticker_clean = str(ticker).upper().replace(".JK", "").strip()
    if not ticker_clean:
        return news_list

    def _strip_source_suffix(title):
        parts = title.rsplit(" - ", 1)
        if len(parts) == 2:
            source_candidate = parts[1].strip()
            if 0 < len(source_candidate.split()) <= 4:
                return parts[0]
        return title

    def _clean_text_for_match(n):
        title = n.get("title", "") or ""
        return _strip_source_suffix(title).lower()

    strong_keywords = {ticker_clean.lower()}
    weak_keywords = {ticker_clean.lower()}

    if ticker_info and isinstance(ticker_info, dict):
        for field in ("longName", "shortName"):
            name = ticker_info.get(field, "") or ""
            if not name:
                continue
            for word in re.split(r"[\s\-\(\)\,\.]+", name.lower()):
                word = word.strip()
                if len(word) < 4 or word in _COMPANY_STOPWORDS:
                    continue
                weak_keywords.add(word)
                if len(word) >= 5:
                    strong_keywords.add(word)

    def _match(text, keywords):
        hits = 0
        for kw in keywords:
            if re.search(r"\b" + re.escape(kw) + r"\b", text):
                hits += 1
        return hits

    tier1 = []
    for n in news_list:
        if _match(_clean_text_for_match(n), strong_keywords) >= 1:
            tier1.append(n)
    if len(tier1) >= 2:
        return tier1

    tier2 = []
    for n in news_list:
        if _match(_clean_text_for_match(n), weak_keywords) >= 1:
            tier2.append(n)

    seen = set()
    combined = []
    for n in tier1 + tier2:
        if n["title"] not in seen:
            seen.add(n["title"])
            combined.append(n)
    return combined


# ═══════════════════════════════════════════════════════════════
# NEWS SOURCES
# ═══════════════════════════════════════════════════════════════
def get_google_news_rss(query_str, num=5, days_back=7, lang="id"):
    """Ambil berita dari Google News RSS, FILTER TANGGAL MANUAL."""
    if not RSS_AVAILABLE:
        return [], "RSS tidak tersedia"
    try:
        cutoff_date = datetime.now() - timedelta(days=days_back)
        cutoff_str = cutoff_date.strftime('%Y-%m-%d')
        cutoff_ts = cutoff_date.timestamp()

        query_with_date = f"{query_str} after:{cutoff_str}"
        if lang == "en":
            url = (
                f"https://news.google.com/rss/search?"
                f"q={urllib.parse.quote(query_with_date)}&hl=en-US&gl=US&ceid=US:en"
            )
        else:
            url = (
                f"https://news.google.com/rss/search?"
                f"q={urllib.parse.quote(query_with_date)}&hl=id&gl=ID&ceid=ID:id"
            )
        feed = feedparser.parse(url)   # ← KUNCI: langsung URL, bukan requests.get

        news = []
        for e in feed.entries[:num * 3]:
            published_parsed = e.get('published_parsed')
            if published_parsed:
                pub_ts = time.mktime(published_parsed)
                if pub_ts < cutoff_ts:
                    continue
            else:
                pub_ts = 0

            news.append({
                'title': e.get('title', '').strip(),
                'summary': re.sub('<[^<]+?>', '', e.get('summary', '') or ''),
                'source': 'Google News',
                'published': e.get('published', ''),
                'published_ts': pub_ts
            })
            if len(news) >= num:
                break

        news.sort(key=lambda x: x['published_ts'], reverse=True)
        return news[:num], None
    except Exception as e:
        return [], str(e)


# ═══════════════════════════════════════════════════════════════
# GLOBAL SECTOR & COMMODITY CATALYSTS
# ═══════════════════════════════════════════════════════════════
SECTOR_CATALYSTS = {
    "COAL": {
        "label": "Batubara (Coal)",
        "tickers": {
            "ADRO", "PTBA", "ITMG", "BUMI", "INDY", "BYAN", "HRUM",
            "KKGI", "MBAP", "ABMM", "DSSA", "CUAN", "BSSR", "GEMS", "TOBA", "TEBE"
        },
        "query": '("thermal coal" OR "newcastle coal" OR "coal price" OR "coal demand")',
    },
    "NICKEL_EV": {
        "label": "Nikel & Baterai EV",
        "tickers": {"ANTM", "INCO", "MBMA", "NCKL", "NICL"},
        "query": '("nickel price" OR "LME nickel" OR "EV battery supply" OR "nickel market")',
    },
    "GOLD_COPPER": {
        "label": "Emas & Tembaga (Gold/Copper)",
        "tickers": {"MDKA", "BRMS", "PSAB", "AMMN", "ARCI"},
        "query": '("gold price" OR "spot gold" OR "copper price" OR "LME copper")',
    },
    "OIL_GAS": {
        "label": "Minyak & Gas Bumi (Oil & Gas)",
        "tickers": {"MEDC", "PGAS", "ENRG", "AKRA", "ELSA", "RAJA", "RUIS"},
        "query": '("crude oil" OR "brent crude" OR "WTI oil" OR "OPEC" OR "natural gas price")',
    },
    "CPO_AGRI": {
        "label": "Minyak Sawit (CPO)",
        "tickers": {
            "AALI", "LSIP", "TAPG", "SIMP", "SSMS", "DSNG", "BWPT", "TBLA", "STAA", "PALM"
        },
        "query": '("crude palm oil" OR "palm oil price" OR "cpo futures" OR "malaysia palm oil")',
    },
    "BANKING_MACRO": {
        "label": "Perbankan & Suku Bunga Makro",
        "tickers": {
            "BBCA", "BBRI", "BMRI", "BBNI", "BBTN", "BDMN", "BRIS", "BNGA", "ARTO", "BTPS"
        },
        "query": '("Federal Reserve interest rate" OR "Treasury yield" OR "Bank Indonesia rate" OR "USD IDR")',
    },
    "PULP_PAPER": {
        "label": "Kertas & Pulp",
        "tickers": {"INKP", "TKIM"},
        "query": '("pulp price" OR "wood pulp market" OR "paper packaging demand")',
    },
    "RENEWABLE_ENERGY": {
        "label": "Energi Terbarukan",
        "tickers": {"BREN", "PGEO", "KEEN", "ARKO"},
        "query": '("geothermal energy" OR "renewable energy capacity" OR "green energy transition")',
    },
    "POULTRY_FEED": {
        "label": "Unggas & Pakan Ternak",
        "tickers": {"CPIN", "JPFA", "MAIN"},
        "query": '("poultry feed cost" OR "corn price" OR "soybean meal price")',
    },
    "TECH_DIGITAL": {
        "label": "Teknologi & Digital",
        "tickers": {"GOTO", "BUKA", "EMTK", "WIRG", "BELI", "DCII", "MTDL"},
        "query": '("tech stocks" OR "southeast asia tech startup" OR "cloud data center demand")',
    },
    "AUTOMOTIVE_HEAVY": {
        "label": "Otomotif & Alat Berat",
        "tickers": {"ASII", "AUTO", "UNTR", "HEXA"},
        "query": '("heavy equipment demand mining" OR "electric vehicle market southeast asia" OR "auto sales")',
    },
    "CONSUMER_STAPLES": {
        "label": "Konsumsi & Bahan Pokok",
        "tickers": {"ICBP", "INDF", "MYOR", "UNVR", "CMRY", "ROTI"},
        "query": '("wheat price" OR "sugar price" OR "packaged food inflation")',
    },
}


def get_sector_catalyst(ticker: str, ticker_info: dict | None = None) -> dict | None:
    """Tentukan katalis sektor global berdasarkan kode saham atau info yfinance."""
    ticker_clean = str(ticker).upper().replace(".JK", "").strip()
    if not ticker_clean:
        return None

    # 1. Cek direct match di ticker list
    for key, data in SECTOR_CATALYSTS.items():
        if ticker_clean in data["tickers"]:
            return {"key": key, "label": data["label"], "query": data["query"]}

    # 2. Fallback: Cocokkan berdasarkan 'sector' / 'industry' yfinance
    if ticker_info and isinstance(ticker_info, dict):
        sector = (ticker_info.get("sector") or "").lower()
        industry = (ticker_info.get("industry") or "").lower()

        if "coal" in industry:
            return {"key": "COAL", "label": SECTOR_CATALYSTS["COAL"]["label"], "query": SECTOR_CATALYSTS["COAL"]["query"]}
        if "oil" in industry or "gas" in industry or "petroleum" in industry:
            return {"key": "OIL_GAS", "label": SECTOR_CATALYSTS["OIL_GAS"]["label"], "query": SECTOR_CATALYSTS["OIL_GAS"]["query"]}
        if "gold" in industry or "copper" in industry:
            return {"key": "GOLD_COPPER", "label": SECTOR_CATALYSTS["GOLD_COPPER"]["label"], "query": SECTOR_CATALYSTS["GOLD_COPPER"]["query"]}
        if "bank" in industry or "financial" in sector:
            return {"key": "BANKING_MACRO", "label": SECTOR_CATALYSTS["BANKING_MACRO"]["label"], "query": SECTOR_CATALYSTS["BANKING_MACRO"]["query"]}
        if "farm" in industry or "agriculture" in industry:
            return {"key": "CPO_AGRI", "label": SECTOR_CATALYSTS["CPO_AGRI"]["label"], "query": SECTOR_CATALYSTS["CPO_AGRI"]["query"]}

    return None


@st.cache_data(ttl=3600, show_spinner=False)
def get_global_sector_news(category_label: str, query_str: str, num: int = 2, days_back: int = 14) -> list[dict]:
    """Ambil berita sektor/komoditas global dalam bahasa Inggris via Google News US RSS (di-cache per sektor)."""
    if not RSS_AVAILABLE:
        return []
    try:
        news, _ = get_google_news_rss(query_str, num=num, days_back=days_back, lang="en")
        for n in news:
            n["source"] = f"Global: {category_label}"
            n["is_global"] = True
        return news
    except Exception:
        return []


@st.cache_data(ttl=600, show_spinner=False)
def _fetch_rss_news(feed_url, ticker, num=5, days_back=7, ticker_info=None):
    if not RSS_AVAILABLE:
        return []
    try:
        import requests
        r = requests.get(
            feed_url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                "Accept": "application/rss+xml, application/xml, text/xml, */*",
            },
            timeout=12,
        )
        if r.status_code != 200:
            return []

        head = r.text.lstrip()[:200].lower()
        if not (head.startswith("<?xml") or "<rss" in head or "<feed" in head):
            return []

        feed = feedparser.parse(r.text)
        cutoff = time.time() - (days_back * 86400)
        keywords = _build_ticker_keywords(ticker, ticker_info) or [str(ticker).lower().strip()]
        out = []
        for e in feed.entries[:num * 6]:
            title = (e.get("title") or "").strip()
            summary = re.sub("<[^<]+?>", "", e.get("summary", "") or "")
            text = (title + " " + summary).lower()
            if not any(kw in text for kw in keywords):
                continue
            pub_parsed = e.get("published_parsed")
            if pub_parsed:
                pub_ts = time.mktime(pub_parsed)
                if pub_ts < cutoff:
                    continue
            else:
                pub_ts = 0
            out.append({
                "title": title,
                "summary": summary[:300],
                "source": "RSS",
                "published": e.get("published", ""),
                "published_ts": pub_ts,
            })
            if len(out) >= num:
                break
        out.sort(key=lambda x: x["published_ts"], reverse=True)
        return out
    except Exception:
        return []


def get_kontan_news(ticker, num=5, ticker_info=None):
    """Kontan RSS 403 → fallback ke Google News."""
    try:
        query = f'"{ticker}" (saham OR emiten OR dividen OR laba) site:kontan.co.id'
        news, err = get_google_news_rss(query, num=num, days_back=14)
        for n in news:
            n["source"] = "Kontan (Google News)"
        return news, None
    except Exception:
        return [], None


def get_cnbc_rss_news(ticker, num=5, ticker_info=None):
    """CNBC Indonesia — 2 feed untuk coverage lebih luas."""
    FEEDS = [
        "https://www.cnbcindonesia.com/market/rss",
        "https://www.cnbcindonesia.com/rss",
    ]

    all_news = []
    for url in FEEDS:
        news = _fetch_rss_news(url, ticker, num=num, ticker_info=ticker_info)
        for n in news:
            n["source"] = "CNBC Indonesia"
        all_news.extend(news)

    seen = set()
    unique = []
    for n in all_news:
        if n["title"] not in seen:
            seen.add(n["title"])
            unique.append(n)
        if len(unique) >= num:
            break
    return unique, None


def get_ipot_news(query, num=5):
    """Ambil berita dari Ipotnews — wajib ada ticker di judul."""
    try:
        import requests
        from bs4 import BeautifulSoup
        url = f"https://www.ipotnews.com/?q={urllib.parse.quote(query)}"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        r = requests.get(url, headers=headers, timeout=10)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")

        query_low = str(query).lower().strip()
        news = []
        for a in soup.find_all("a"):
            t = a.get_text(strip=True)
            if len(t) < 30 or "berita" in t.lower() or "indopremier" in t.lower():
                continue
            if query_low not in t.lower():
                continue
            if not any(n["title"] == t for n in news):
                news.append({"title": t, "summary": "", "source": "Ipotnews"})
            if len(news) >= num:
                break
        return news, None
    except Exception as e:
        return [], str(e)


@st.cache_data(ttl=600, show_spinner=False)
def get_headlines_for_ticker(ticker, include_global=True):
    """Ambil judul berita terbaru yang relevan dengan ticker + konteks katalis global sektor."""
    try:
        ticker_clean = str(ticker).upper().replace(".JK", "").strip()
        if not ticker_clean:
            return ["(ticker kosong)"]

        _long_name = ""
        _info = {}
        try:
            _info = yf.Ticker(f"{ticker_clean}.JK").info or {}
            _ln = _info.get("longName", "") or _info.get("shortName", "") or ""
            _ln = re.sub(r"\b(Tbk|PT|Persero|Perseroan|Terbuka)\b", "", _ln, flags=re.IGNORECASE).strip()
            if len(_ln) > 5:
                _long_name = _ln
        except Exception:
            pass

        _queries = [f"{ticker_clean} saham"]
        if _long_name:
            _queries.append(f'"{_long_name}" saham')

        all_news = []
        for q in _queries:
            n, _ = get_google_news_rss(q, num=10, days_back=30)
            if n:
                all_news.extend(n)

        seen = set()
        unique = []
        for n in all_news:
            if n["title"] not in seen:
                seen.add(n["title"])
                unique.append(n)

        try:
            _info_for_filter = {"longName": _long_name} if _long_name else {}
            filtered = filter_relevant(unique, ticker_clean, ticker_info=_info_for_filter)
        except Exception:
            filtered = unique

        results = []
        if filtered:
            results = [n["title"] for n in filtered[:2]]
        elif unique:
            results = [n["title"] for n in unique[:2]]

        # Sisipkan berita sektor/komoditas global jika tersedia
        if include_global:
            catalyst = get_sector_catalyst(ticker_clean, _info)
            if catalyst:
                global_news = get_global_sector_news(catalyst["label"], catalyst["query"], num=2)
                for g in global_news:
                    results.append(f"[Global {catalyst['label']}] {g['title']}")

        if results:
            return results[:3]
        else:
            return ["(tidak ada berita terbaru)"]
    except Exception:
        return ["(gagal mengambil berita)"]


# ═══════════════════════════════════════════════════════════════
# SENTIMENT ANALYSIS
# ═══════════════════════════════════════════════════════════════
def _score_lexicon_idxfin(text_lower: str):
    matches = []
    for phrase, score in IDX_FIN_LEXICON.items():
        if len(phrase) <= 4:
            pattern = r"\b" + re.escape(phrase) + r"\b"
            if re.search(pattern, text_lower):
                matches.append((len(phrase), score))
        else:
            if phrase in text_lower:
                matches.append((len(phrase), score))
    if not matches:
        return 0.0, False
    total_w = sum(l for l, _ in matches)
    weighted = sum(l * s for l, s in matches) / total_w
    return float(np.clip(weighted, -1.0, 1.0)), True


def analyze_sentiment_weighted(news_items, translator):
    if not _ensure_sentiment():
        return 0.0
    from nltk.sentiment import SentimentIntensityAnalyzer
    if not news_items:
        return 0.0
    analyzer = SentimentIntensityAnalyzer()
    total_w, w_sum = 0, 0
    for i, item in enumerate(news_items):
        text = f"{item['title']}. {item['summary']}" if item["summary"] else item["title"]
        text_for_lexicon = text.lower()

        lex_score, has_lex = _score_lexicon_idxfin(text_for_lexicon)

        _ID_WORDS = re.compile(
            r"\b(yang|dan|di|ke|dari|untuk|dengan|pada|ini|itu|akan|telah|saham|harga|naik|turun)\b",
            re.IGNORECASE,
        )

        if translator and _ID_WORDS.search(text):
            try:
                text = translator.translate(text)
            except Exception:
                pass
        vader_score = analyzer.polarity_scores(text)["compound"]

        if has_lex:
            final_score = 0.6 * lex_score + 0.4 * vader_score
        else:
            final_score = vader_score

        weight = 1 / (i + 1)
        w_sum += final_score * weight
        total_w += weight
    return w_sum / total_w if total_w > 0 else 0.0
