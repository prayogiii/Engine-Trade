"""
Test time-decay weighting & sentiment fallback untuk Poin 5 notes.
"""
import time
import pytest

from services.news_client import (
    _time_decay_weight,
    analyze_sentiment_weighted,
    NEWS_HARD_CUTOFF_DAYS,
    NEWS_DECAY_HALF_LIFE_HOURS,
)


# ═══════════════════════════════════════════════════════════════
# TIME-DECAY — pure function
# ═══════════════════════════════════════════════════════════════
def test_decay_fresh_news_full_weight():
    now = time.time()
    assert _time_decay_weight(now, now) == pytest.approx(1.0, abs=1e-9)


def test_decay_one_hour():
    now = time.time()
    w = _time_decay_weight(now - 3600, now)
    assert 0.95 < w < 1.0


def test_decay_half_life():
    now = time.time()
    published = now - NEWS_DECAY_HALF_LIFE_HOURS * 3600
    assert _time_decay_weight(published, now) == pytest.approx(0.5, abs=1e-6)


def test_decay_two_half_lives():
    now = time.time()
    published = now - 2 * NEWS_DECAY_HALF_LIFE_HOURS * 3600
    assert _time_decay_weight(published, now) == pytest.approx(0.25, abs=1e-6)


def test_decay_beyond_hard_cutoff_zero():
    now = time.time()
    published = now - (NEWS_HARD_CUTOFF_DAYS + 1) * 86400
    assert _time_decay_weight(published, now) == 0.0


def test_decay_exactly_at_cutoff_still_positive():
    """
    Tepat di batas cutoff — masih > 0 (exclusive cutoff).
    Weight ≈ 0.5^(7×24/36) = 0.5^4.667 ≈ 0.039.
    """
    now = time.time()
    published = now - NEWS_HARD_CUTOFF_DAYS * 86400
    w = _time_decay_weight(published, now)
    assert w > 0
    assert w < 0.05   # sangat kecil tapi masih > 0
    assert w == pytest.approx(0.0394, abs=0.01)


def test_decay_no_timestamp_fallback():
    assert _time_decay_weight(0) == 0.3


def test_decay_future_timestamp_clamped():
    now = time.time()
    published = now + 3600  # clock skew, timestamp di masa depan
    assert _time_decay_weight(published, now) == pytest.approx(1.0, abs=1e-9)


# ═══════════════════════════════════════════════════════════════
# SENTIMENT AGGREGATION dengan decay
# ═══════════════════════════════════════════════════════════════
@pytest.fixture
def disable_vader(monkeypatch):
    """Force VADER off → sentiment harus fallback ke lexicon-only."""
    from services import news_client
    monkeypatch.setattr(news_client, "_ensure_sentiment", lambda: False)


def test_sentiment_lexicon_only_fallback(disable_vader):
    """
    VADER off → fallback ke lexicon, bukan return 0.
    Pakai frasa yang benar-benar ada di IDX_FIN_LEXICON:
    "laba melonjak" (+0.80) atau "lonjakan laba" (+0.82).
    """
    now = time.time()
    news = [{
        "title": "laba melonjak tajam",
        "summary": "",
        "published_ts": now - 3600,
    }]
    score = analyze_sentiment_weighted(news, translator=None, now_ts=now)
    assert score > 0.3  # lexicon "laba melonjak" = +0.80


def test_sentiment_negative_lexicon(disable_vader):
    now = time.time()
    news = [{
        "title": "suspensi perdagangan saham perusahaan",
        "summary": "",
        "published_ts": now - 3600,
    }]
    score = analyze_sentiment_weighted(news, translator=None, now_ts=now)
    assert score < -0.3  # "suspensi perdagangan" = -0.92


def test_sentiment_empty_returns_zero():
    assert analyze_sentiment_weighted([], translator=None) == 0.0


def test_sentiment_all_too_old_returns_zero(disable_vader):
    """Semua berita > cutoff → di-skip semua → return 0."""
    now = time.time()
    news = [{
        "title": "laba bersih melonjak",
        "summary": "",
        "published_ts": now - (NEWS_HARD_CUTOFF_DAYS + 2) * 86400,
    }]
    assert analyze_sentiment_weighted(news, translator=None, now_ts=now) == 0.0


def test_sentiment_recent_dominates_old(disable_vader):
    """Berita baru positif harus mendominasi berita lama negatif."""
    now = time.time()
    news = [
        {"title": "laba melonjak", "summary": "",
         "published_ts": now - 3600},            # 1 jam lalu, +
        {"title": "rugi bersih", "summary": "",
         "published_ts": now - 5 * 86400},       # 5 hari lalu, -
    ]
    score = analyze_sentiment_weighted(news, translator=None, now_ts=now)
    # Positif harus dominan karena time-decay
    assert score > 0.2


def test_sentiment_old_news_weight_low(disable_vader):
    """
    Dua berita bobot sama tapi beda umur → hasil condong ke yang baru.
    """
    now = time.time()
    news = [
        {"title": "rugi bersih", "summary": "",
         "published_ts": now - 86400},           # 1 hari, -
        {"title": "laba melonjak", "summary": "",
         "published_ts": now - 30},              # fresh, +
    ]
    score = analyze_sentiment_weighted(news, translator=None, now_ts=now)
    assert score > 0  # yang fresh (positif) menang


def test_sentiment_no_timestamp_gets_fallback_weight(disable_vader):
    """Item tanpa published_ts (mis. dari ipot news) → weight 0.3, tetap dihitung."""
    now = time.time()
    news = [{"title": "laba melonjak", "summary": "", "published_ts": 0}]
    score = analyze_sentiment_weighted(news, translator=None, now_ts=now)
    assert score > 0.3  # tetap positif, bobot 0.3