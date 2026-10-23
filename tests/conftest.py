import os
import pytest


@pytest.fixture(autouse=True)
def _disable_gemini_news_by_default():
    """
    Cegah test tidak sengaja memanggil Gemini API sungguhan.
    Test yang memang menguji jalur Gemini harus mock
    `news_client._extract_gemini_sentiment` (bypass env check ini).
    """
    old = os.environ.get("DISABLE_GEMINI_NEWS")
    os.environ["DISABLE_GEMINI_NEWS"] = "true"
    yield
    if old is None:
        os.environ.pop("DISABLE_GEMINI_NEWS", None)
    else:
        os.environ["DISABLE_GEMINI_NEWS"] = old