"""
Test Gemini news sentiment integration (Poin 5b).

Unit: `extract_news_sentiment_gemini` (mock call_gemini_auto_rotate).
Integration: `analyze_sentiment_weighted` dengan Gemini tersedia (mock `_extract_gemini_sentiment`).

CATATAN: test ini meng-mock `_extract_gemini_sentiment` langsung sehingga
autouse fixture `_disable_gemini_news_by_default` di conftest.py tidak menghalangi.
"""
import time
import pytest

from services import gemini_client
from services import news_client


# ═══════════════════════════════════════════════════════════════
# UNIT: extract_news_sentiment_gemini
# ═══════════════════════════════════════════════════════════════
@pytest.fixture
def fake_keys(monkeypatch):
    monkeypatch.setattr(gemini_client, "_load_gemini_keys",
                        lambda: ["fake_key_xxxxxxxxxxxxxxxxxxxxxxxxxxxx"])
    monkeypatch.delenv("DISABLE_GEMINI_NEWS", raising=False)


def test_extract_no_keys_returns_empty(monkeypatch):
    monkeypatch.setattr(gemini_client, "_load_gemini_keys", lambda: [])
    monkeypatch.delenv("DISABLE_GEMINI_NEWS", raising=False)
    assert gemini_client.extract_news_sentiment_gemini(["BBRI naik"]) == []


def test_extract_empty_headlines_returns_empty(fake_keys):
    assert gemini_client.extract_news_sentiment_gemini([]) == []


def test_extract_returns_parsed_when_ok(fake_keys, monkeypatch):
    monkeypatch.setattr(
        gemini_client, "call_gemini_auto_rotate",
        lambda prompt, **kw: (
            '[{"sentiment": 0.7, "confidence": 0.9, "entities": ["BBRI"], '
            '"catalyst_type": "earnings"}]',
            None,
        ),
    )
    result = gemini_client.extract_news_sentiment_gemini(["BBRI naik tinggi"])
    assert len(result) == 1
    assert result[0]["sentiment"] == pytest.approx(0.7)
    assert result[0]["confidence"] == pytest.approx(0.9)
    assert result[0]["catalyst_type"] == "earnings"
    assert result[0]["entities"] == ["BBRI"]
    assert not result[0].get("_fallback")


def test_extract_returns_fallback_when_error(fake_keys, monkeypatch):
    monkeypatch.setattr(gemini_client, "call_gemini_auto_rotate",
                        lambda prompt, **kw: (None, "429 rate limit"))
    result = gemini_client.extract_news_sentiment_gemini(["X"])
    assert result == []


def test_extract_parses_multi_items(fake_keys, monkeypatch):
    monkeypatch.setattr(
        gemini_client, "call_gemini_auto_rotate",
        lambda prompt, **kw: (
            '[{"sentiment": 0.5, "confidence": 0.8, "entities": [], "catalyst_type": "dividend"},'
            ' {"sentiment": -0.6, "confidence": 0.85, "entities": ["ANTM"], "catalyst_type": "litigation"}]',
            None,
        ),
    )
    result = gemini_client.extract_news_sentiment_gemini(["BBCA bagi dividen", "ANTM kena sanksi"])
    assert len(result) == 2
    assert result[0]["sentiment"] == pytest.approx(0.5)
    assert result[1]["sentiment"] == pytest.approx(-0.6)


def test_extract_clips_out_of_range(fake_keys, monkeypatch):
    monkeypatch.setattr(
        gemini_client, "call_gemini_auto_rotate",
        lambda prompt, **kw: (
            '[{"sentiment": 99, "confidence": 5, "entities": [], "catalyst_type": "xxx"}]',
            None,
        ),
    )
    result = gemini_client.extract_news_sentiment_gemini(["X"])
    assert result[0]["sentiment"] == 1.0
    assert result[0]["confidence"] == 1.0
    assert result[0]["catalyst_type"] == "other"  # invalid → fallback


def test_extract_handles_markdown_fence(fake_keys, monkeypatch):
    monkeypatch.setattr(
        gemini_client, "call_gemini_auto_rotate",
        lambda prompt, **kw: (
            '```json\n[{"sentiment": 0.4, "confidence": 0.7, "entities": [], "catalyst_type": "macro"}]\n```',
            None,
        ),
    )
    result = gemini_client.extract_news_sentiment_gemini(["X"])
    assert result[0]["sentiment"] == pytest.approx(0.4)


def test_extract_pads_when_fewer_items_returned(fake_keys, monkeypatch):
    """Gemini return 1 item untuk 2 headline → item kedua di-pad fallback."""
    monkeypatch.setattr(
        gemini_client, "call_gemini_auto_rotate",
        lambda prompt, **kw: ('[{"sentiment": 0.5, "confidence": 0.9, "entities": [], "catalyst_type": "other"}]', None),
    )
    result = gemini_client.extract_news_sentiment_gemini(["A", "B"])
    assert len(result) == 2
    assert not result[0].get("_fallback")
    assert result[1].get("_fallback") is True


def test_extract_disabled_by_env(fake_keys, monkeypatch):
    monkeypatch.setenv("DISABLE_GEMINI_NEWS", "true")
    result = gemini_client.extract_news_sentiment_gemini(["X"])
    assert result == []


# ═══════════════════════════════════════════════════════════════
# INTEGRATION: analyze_sentiment_weighted + Gemini
# ═══════════════════════════════════════════════════════════════
def test_gemini_blended_when_available(monkeypatch):
    """Gemini sentiment positif harus mendominasi agregat."""
    def fake_extract(headlines):
        return [
            {"sentiment": 0.8, "confidence": 0.9, "entities": [],
             "catalyst_type": "earnings"}
            for _ in headlines
        ]
    monkeypatch.setattr(news_client, "_extract_gemini_sentiment", fake_extract)

    now = time.time()
    news = [{"title": "laba melonjak tajam", "summary": "", "published_ts": now}]
    score = news_client.analyze_sentiment_weighted(news, translator=None, now_ts=now, use_gemini=True)
    # 0.5·0.8 + 0.3·lex(+0.8) + 0.2·(vader default 0 jika off) → positif jelas
    assert score > 0.5


def test_gemini_fallback_when_empty(monkeypatch):
    """
    Gemini return [] → fallback ke lexicon-only.
    VADER di-disable untuk isolasi: tanpa ini, VADER (compound 0 untuk
    teks Indonesia tanpa translate) menekan rata-rata blend jadi 0.48.
    """
    from services import news_client
    monkeypatch.setattr(news_client, "_ensure_sentiment", lambda: False)
    monkeypatch.setattr(news_client, "_extract_gemini_sentiment", lambda h: [])

    now = time.time()
    news = [{"title": "laba melonjak tajam", "summary": "", "published_ts": now}]
    score = news_client.analyze_sentiment_weighted(news, translator=None, now_ts=now, use_gemini=True)
    assert score > 0.5  # lexicon "laba melonjak" = +0.80

def test_gemini_low_confidence_ignored(monkeypatch):
    """Gemini confidence < 0.4 → dianggap no-signal, fallback ke lex/vader."""
    def fake_extract(headlines):
        return [
            {"sentiment": 0.9, "confidence": 0.2, "entities": [],
             "catalyst_type": "other"}
            for _ in headlines
        ]
    monkeypatch.setattr(news_client, "_extract_gemini_sentiment", fake_extract)

    now = time.time()
    # Lexicon NEGATIF — kalau Gemini (positif) dipakai, hasil jadi positif.
    # Karena confidence rendah, harus tetap negatif dari lexicon.
    news = [{"title": "suspensi perdagangan saham", "summary": "", "published_ts": now}]
    score = news_client.analyze_sentiment_weighted(news, translator=None, now_ts=now, use_gemini=True)
    assert score < -0.3  # negatif dari lexicon, Gemini low-conf diabaikan


def test_gemini_disabled_flag(monkeypatch):
    """use_gemini=False harus tidak panggil _extract_gemini_sentiment."""
    called = {"n": 0}
    def fake_extract(headlines):
        called["n"] += 1
        return []
    monkeypatch.setattr(news_client, "_extract_gemini_sentiment", fake_extract)

    now = time.time()
    news = [{"title": "laba melonjak", "summary": "", "published_ts": now}]
    news_client.analyze_sentiment_weighted(news, translator=None, now_ts=now, use_gemini=False)
    assert called["n"] == 0


def test_gemini_handles_exception_gracefully(monkeypatch):
    """Kalau _extract_gemini_sentiment raise, harus return [] tanpa crash."""
    def fake_extract(headlines):
        raise RuntimeError("Gemini network down")
    monkeypatch.setattr(news_client, "_extract_gemini_sentiment", fake_extract)

    now = time.time()
    news = [{"title": "laba melonjak", "summary": "", "published_ts": now}]
    score = news_client.analyze_sentiment_weighted(news, translator=None, now_ts=now, use_gemini=True)
    assert score > 0.3  # fallback ke lexicon