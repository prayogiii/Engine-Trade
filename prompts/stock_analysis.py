"""Prompt untuk analisis saham (analisis_saham_dengan_ai)."""
from __future__ import annotations


def build_stock_analysis_prompt(data_saham: dict, riwayat_text: str,
                                 broksum_context: str) -> str:
    """Bangun prompt analisis saham dari konteks yang sudah disiapkan caller."""
    return f"""
Anda adalah asisten analis saham profesional & pakar Bandarmology. Berikut data analisis teknikal, fundamental, dan broker flow saham {data_saham['Saham']}:

- Harga terakhir: Rp {data_saham['Harga']}
- Sinyal saat ini: {data_saham['Sinyal']}
- Rezim Pasar: {data_saham['Rezim']}
- Sentimen Berita: {data_saham['Sentimen']}
- Risk/Reward Ratio (RRR): {data_saham['RRR']}
- Probabilitas Naik: {data_saham['Prob Naik']}
- Take Profit: +{data_saham['TP%']}%
- Stop Loss: -{data_saham['SL%']}%
- Estimasi: Rp {data_saham['Estimasi']}
- Beta terhadap IHSG: {data_saham.get('Beta', 'N/A')}
- Win Rate Backtest: {data_saham.get('WinRate', 'N/A')}
- Actual Track Record Saham Ini: {data_saham.get('Actual_WinRate_Ticker', 'Belum ada evaluasi')}
- Profit Factor Backtest: {data_saham.get('ProfitFactor', 'N/A')}
- Max Drawdown Backtest: {data_saham.get('MaxDD', 'N/A')}
- Alokasi Kelly Maks: {data_saham.get('Kelly', 'N/A')}%
- Fundamental: Market Cap: {data_saham.get('Fundamental_MC', 'N/A')}, PER: {data_saham.get('Fundamental_PER', 'N/A')}, PBV: {data_saham.get('Fundamental_PBV', 'N/A')}, ROE: {data_saham.get('Fundamental_ROE', 'N/A')}, D/E: {data_saham.get('Fundamental_DE', 'N/A')}
- Status Posisi: {data_saham.get('Status_Posisi', 'Tidak diketahui')}
- Harga Beli: {data_saham.get('Harga_Beli', 'Tidak diisi')}
- Floating P/L: {data_saham.get('Floating_PL', 'N/A')}

{broksum_context}

{riwayat_text}

Berdasarkan data di atas{' (khususnya dominasi Bandar 🐋 vs Retail 🧑 pada broker flow)' if broksum_context else ''}, berikan analisis ringkas (Bahasa Indonesia) yang mencakup:
- Makna sinyal teknikal dalam konteks pergerakan saat ini
{f'- Analisis peta akumulasi/distribusi broker (Bandar vs Retail) & implikasinya pada harga' if broksum_context else ''}
- Kekuatan dan kelemahan saham
- Risiko utama
- Rekomendasi langkah selanjutnya (buy/hold/sell) dengan alasan singkat
- Jika ada pola dari riwayat, sebutkan.
Gunakan bahasa mudah dipahami trader, maksimal 4 paragraf pendek.
"""