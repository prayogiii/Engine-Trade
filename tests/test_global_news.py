"""Unit tests for global sector news & catalyst mapping."""
import pytest
from services.news_client import (
    SECTOR_CATALYSTS,
    get_sector_catalyst,
)


def test_catalyst_direct_mapping():
    # Komoditas batubara
    c_ptba = get_sector_catalyst("PTBA")
    assert c_ptba is not None
    assert c_ptba["key"] == "COAL"
    assert "thermal coal" in c_ptba["query"]

    # Nikel
    c_antm = get_sector_catalyst("ANTM")
    assert c_antm is not None
    assert c_antm["key"] == "NICKEL_EV"

    # Perbankan
    c_bbca = get_sector_catalyst("BBCA")
    assert c_bbca is not None
    assert c_bbca["key"] == "BANKING_MACRO"

    # Migas
    c_medc = get_sector_catalyst("MEDC")
    assert c_medc is not None
    assert c_medc["key"] == "OIL_GAS"

    # Sawit CPO
    c_aali = get_sector_catalyst("AALI")
    assert c_aali is not None
    assert c_aali["key"] == "CPO_AGRI"


def test_catalyst_fallback_yfinance():
    # Saham luar daftar direct tapi info industrinya mengandung kata kunci
    info_gold = {"sector": "Basic Materials", "industry": "Gold Mining"}
    res = get_sector_catalyst("CUSTOM", info_gold)
    assert res is not None
    assert res["key"] == "GOLD_COPPER"

    info_oil = {"sector": "Energy", "industry": "Oil & Gas E&P"}
    res_oil = get_sector_catalyst("CUSTOM2", info_oil)
    assert res_oil is not None
    assert res_oil["key"] == "OIL_GAS"


def test_catalyst_unknown():
    # Saham tidak terdaftar dan info kosong
    res = get_sector_catalyst("UNKNOWN_TICKER", {})
    assert res is None
