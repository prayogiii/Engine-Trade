"""Unit test core.bandarmology."""
from core.bandarmology import (
    klasifikasi_broker, parse_broker_list, format_broker_list_for_ai,
    enrich_broker_kategori, compute_multi_day_bandar_score,
)


class TestKlasifikasiBroker:
    def test_bandar_broker_code(self):
        kat, icon = klasifikasi_broker("AK")
        assert kat == "Bandar"
        assert icon == "🐋"

    def test_retail_broker_code(self):
        kat, icon = klasifikasi_broker("YP")
        assert kat == "Retail"
        assert icon == "🧑"

    def test_avg_lot_high(self):
        # freq=100, vol=30_000 → avg=300 → Bandar
        kat, _ = klasifikasi_broker("ZZ", 30_000, 100)
        assert kat == "Bandar"

    def test_avg_lot_low(self):
        kat, _ = klasifikasi_broker("ZZ", 1_000, 100)  # avg=10 → Retail
        assert kat == "Retail"

    def test_mixed_default(self):
        kat, _ = klasifikasi_broker("ZZ")
        assert kat == "Mixed"


class TestParseBrokerList:
    def test_json_string(self):
        raw = '[{"broker": "AK", "volume_lot": 100}]'
        out = parse_broker_list(raw)
        assert len(out) == 1
        assert out[0]["broker"] == "AK"

    def test_already_list(self):
        assert parse_broker_list([1, 2]) == [1, 2]

    def test_invalid(self):
        assert parse_broker_list("not json") == []
        assert parse_broker_list(None) == []


class TestFormatBrokerList:
    def test_empty(self):
        s, summary = format_broker_list_for_ai([])
        assert s == "- (tidak ada data)"

    def test_composition(self):
        lst = [
            {"broker": "AK", "volume_lot": 5000},   # Bandar
            {"broker": "YP", "volume_lot": 5000},   # Retail
        ]
        s, summary = format_broker_list_for_ai(lst)
        assert "AK" in s and "YP" in s
        assert "Bandar" in summary and "Retail" in summary


class TestEnrich:
    def test_adds_kategori(self):
        res = {
            "top_buyers": [{"broker": "AK", "volume_lot": 5000}],
            "top_sellers": [{"broker": "YP", "volume_lot": 3000}],
            "summary_narrative": "Broker flow hari ini.",
        }
        out = enrich_broker_kategori(res)
        assert out["top_buyers"][0]["kategori"] == "Bandar"
        assert out["top_sellers"][0]["kategori"] == "Retail"
        assert "broker_summary_stats" in out


class TestMultiDay:
    def test_empty_history(self):
        out = compute_multi_day_bandar_score([])
        assert out["n_snapshots"] == 0
        assert out["trend"] == "no_data"

    def test_accumulating_pattern(self):
        # 5 snapshot konsisten bandar beli banyak
        history = [
            {
                "upload_date": f"2026-01-0{i+1}",
                "top_buyers": '[{"broker": "AK", "volume_lot": 10000}]',
                "top_sellers": '[{"broker": "YP", "volume_lot": 1000}]',
            }
            for i in range(5)
        ]
        out = compute_multi_day_bandar_score(history)
        assert out["n_snapshots"] == 5
        assert out["trend"] in ("accumulating", "mixed")  # akumulasi terdeteksi
        assert "AK" in out["consistent_buyers"]