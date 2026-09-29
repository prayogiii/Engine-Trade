"""Prompt untuk scan broksum via Gemini Vision."""

BROKSUM_VISION_PROMPT = """
Anda adalah pakar Bandarmology & Pasar Modal Indonesia (BEI/IDX).
Tugas Anda: Analisis screenshot Broker Summary (Broksum) / Broker Flow / Trade Flow ini dengan SANGAT AKURAT.

Ekstrak seluruh informasi tabel dan berikan analisis terstruktur dalam format JSON MURNI tanpa teks di luar JSON:
{
  "ticker": "KODE_SAHAM (contoh: BBRI, tulis N/A jika tidak terlihat)",
  "periode": "TANGGAL / PERIODE (contoh: 09 Sep 2026, tulis N/A jika tidak terlihat)",
  "bandarmology_status": "Big Accumulation / Normal Accumulation / Neutral / Normal Distribution / Big Distribution",
  "foreign_flow_status": "Net Buy / Net Sell / Neutral / N/A",
  "summary_narrative": "Penjelasan 2-3 kalimat: broker mana yang dominan (sertakan indikasi Bandar vs Retail jika terlihat), konsentrasi top 1 vs top 3, dan implikasi harga.",
  "top_buyers": [
    {
      "broker": "YP",
      "volume_lot": 15000,
      "value_idr": 1500000000,
      "avg_price": 1250,
      "freq": 250,
      "avg_lot_per_freq": 60
    }
  ],
  "top_sellers": [
    {
      "broker": "AK",
      "volume_lot": 20000,
      "value_idr": 2000000000,
      "avg_price": 1260,
      "freq": 85,
      "avg_lot_per_freq": 235
    }
  ]
}

ATURAN EKSTRAKSI:
1. Kolom "freq" adalah frekuensi/jumlah transaksi broker (biasanya ada di kolom "Freq" atau "F").
   Kalau tidak terlihat di screenshot, tulis null.
2. Kolom "avg_lot_per_freq" = volume_lot / freq (rata-rata lot per transaksi).
   Kalau freq null, tulis null.
3. Konversikan angka Milyar (B) / Juta (M/K) ke nilai penuh (contoh: 1.5B = 1500000000).
4. Ambil hingga 5-10 broker pembeli & penjual yang terlihat di screenshot.
5. Kembalikan HANYA JSON yang valid, tanpa teks lain.
"""