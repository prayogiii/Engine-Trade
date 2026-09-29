"""Prompt untuk evaluasi mode Swing vs Daytrade."""
from __future__ import annotations


def build_mode_evaluation_prompt(res_swing: dict, res_day: dict, ticker_raw: str) -> str:
    return f"""
Anda adalah analis kuantitatif pasar saham profesional. Evaluasi emiten {ticker_raw} untuk menentukan apakah lebih cocok diperdagangkan secara **Swing Trade (SW)** atau **Day Trade (DT)**.

DATA SWING TRADE:
- Sinyal: {res_swing.get('signal', 'N/A')}
- RRR: {res_swing.get('rrr', 0):.2f}
- Confidence: {res_swing.get('confidence', 0):.1f}%
- Win Rate Backtest: {res_swing.get('win_bt', 0)*100 if res_swing.get('win_bt') else 0:.1f}%

DATA DAY TRADE:
- Sinyal: {res_day.get('signal', 'N/A')}
- RRR: {res_day.get('rrr', 0):.2f}
- Confidence: {res_day.get('confidence', 0):.1f}%
- Win Rate Backtest: {res_day.get('win_bt', 0)*100 if res_day.get('win_bt') else 0:.1f}%

KONTEKS EMITEN:
- Beta IHSG: {res_swing.get('beta_ihsg', 1.0):.2f}
- Harga Terakhir: Rp {res_swing.get('harga_terakhir', 0):,.0f}

TUGAS ANDA:
Berikan evaluasi dalam format JSON murni dengan struktur persis seperti ini (tanpa tanda petik ganda di dalam string reasoning):
{{
  "swing_score": 60,
  "day_score": 80,
  "recommended_mode": "Day Trade",
  "reasoning": "Alasan singkat 1-2 kalimat tanpa tanda petik ganda."
}}
"""