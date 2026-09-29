"""
Bandarmology: klasifikasi broker, format untuk AI, multi-day score.

CATATAN: `compute_multi_day_bandar_score` sekarang menerima LIST history sebagai
parameter (bukan ticker), supaya tidak tergantung service layer.
"""
from __future__ import annotations
import json
import numpy as np
from datetime import datetime
from collections import Counter

from config.brokers import BROKER_TYPES, RETAIL_BROKERS, BANDAR_BROKERS


# ═══════════════════════════════════════════════════════════════
# PARSING & KLASIFIKASI
# ═══════════════════════════════════════════════════════════════
def parse_broker_list(raw) -> list[dict]:
    """Parse JSON string / list dari Google Sheets → list of dict."""
    if isinstance(raw, list):
        return raw
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except Exception:
            return []
    return []


def klasifikasi_broker(broker_code, volume_lot=None, freq=None) -> tuple[str, str]:
    """
    Return (kategori, icon):
      - Bandar / 🐋
      - Retail / 🧑
      - Mixed / ⚖️

    Rule:
      1. code ∈ BANDAR_BROKERS → Bandar
      2. code ∈ RETAIL_BROKERS → Retail
      3. Pakai avg_lot_per_freq: >200 Bandar | <50 Retail | else Mixed
      4. Default → Mixed
    """
    code = str(broker_code).upper().strip()
    if code in BANDAR_BROKERS:
        return "Bandar", "🐋"
    if code in RETAIL_BROKERS:
        return "Retail", "🧑"

    try:
        vol = float(volume_lot or 0)
        frq = float(freq) if freq not in (None, "", "null") else None
    except Exception:
        vol, frq = 0, None

    if frq and frq > 0 and vol > 0:
        avg = vol / frq
        if avg > 200:
            return "Bandar", "🐋"
        if avg < 50:
            return "Retail", "🧑"
        return "Mixed", "⚖️"
    return "Mixed", "⚖️"


# ═══════════════════════════════════════════════════════════════
# FORMAT UNTUK AI
# ═══════════════════════════════════════════════════════════════
def format_broker_list_for_ai(broker_list) -> tuple[str, str]:
    """
    Return (list_str, summary_str):
      list_str: "- AK (Bandar 🐋): 15,000 lot\n- YP (Retail 🧑): 8,500 lot"
      summary_str: "Bandar 🐋: 45.2% (15,000 lot) | Retail 🧑: 32.1% (8,500 lot)"
    """
    if not broker_list:
        return "- (tidak ada data)", "Tidak ada data"

    lines: list[str] = []
    tot_vol = 0.0
    vol_by_cat = {"Bandar": 0.0, "Retail": 0.0, "Mixed": 0.0}

    for item in broker_list:
        if not isinstance(item, dict):
            continue
        code = str(item.get("broker", "N/A")).upper().strip()
        vol = float(item.get("volume_lot", 0) or 0)
        frq = item.get("freq")
        kat = item.get("kategori")
        icon = item.get("kategori_icon")
        if not kat or not icon:
            kat, icon = klasifikasi_broker(code, vol, frq)
        tot_vol += vol
        vol_by_cat[kat] = vol_by_cat.get(kat, 0) + vol
        lines.append(f"- {code} ({kat} {icon}): {vol:,.0f} lot")

    cat_summary = []
    if tot_vol > 0:
        for cat_name, cat_icon in [("Bandar", "🐋"), ("Retail", "🧑"), ("Mixed", "⚖️")]:
            v = vol_by_cat.get(cat_name, 0)
            if v > 0:
                pct = v / tot_vol * 100
                cat_summary.append(f"{cat_name} {cat_icon}: {pct:.1f}% ({v:,.0f} lot)")

    summary_str = " | ".join(cat_summary) if cat_summary else "N/A"
    list_str = "\n".join(lines) if lines else "- (tidak ada data)"
    return list_str, summary_str


# ═══════════════════════════════════════════════════════════════
# ENRICH
# ═══════════════════════════════════════════════════════════════
def enrich_broker_kategori(res_json: dict) -> dict:
    """
    Tambah field kategori + kategori_icon ke tiap item top_buyers/top_sellers.
    Juga hitung broker_summary_stats. In-place + return.
    """
    if not isinstance(res_json, dict):
        return res_json

    for side_key in ("top_buyers", "top_sellers"):
        for item in res_json.get(side_key, []) or []:
            if not isinstance(item, dict):
                continue
            kat, icon = klasifikasi_broker(
                item.get("broker", ""),
                item.get("volume_lot", 0) or 0,
                item.get("freq"),
            )
            item["kategori"] = kat
            item["kategori_icon"] = icon

    def _sum(side, kat):
        return sum(
            float(x.get("volume_lot", 0) or 0)
            for x in res_json.get(side, []) or []
            if isinstance(x, dict) and x.get("kategori") == kat
        )

    tot_buy = sum(float(b.get("volume_lot", 0) or 0)
                  for b in res_json.get("top_buyers", []) or [] if isinstance(b, dict))
    tot_sell = sum(float(s.get("volume_lot", 0) or 0)
                   for s in res_json.get("top_sellers", []) or [] if isinstance(s, dict))

    b_buy, r_buy = _sum("top_buyers", "Bandar"), _sum("top_buyers", "Retail")
    b_sell, r_sell = _sum("top_sellers", "Bandar"), _sum("top_sellers", "Retail")

    b_buy_pct = (b_buy / tot_buy * 100) if tot_buy > 0 else 0
    r_buy_pct = (r_buy / tot_buy * 100) if tot_buy > 0 else 0
    b_sell_pct = (b_sell / tot_sell * 100) if tot_sell > 0 else 0
    r_sell_pct = (r_sell / tot_sell * 100) if tot_sell > 0 else 0

    res_json["broker_summary_stats"] = {
        "buyer_bandar_pct": round(b_buy_pct, 1),
        "buyer_retail_pct": round(r_buy_pct, 1),
        "seller_bandar_pct": round(b_sell_pct, 1),
        "seller_retail_pct": round(r_sell_pct, 1),
    }

    curr = res_json.get("summary_narrative", "")
    if curr and "Bandar" not in curr and "Retail" not in curr:
        note = (f" (Komposisi Pembeli: {b_buy_pct:.0f}% Bandar 🐋 / "
                f"{r_buy_pct:.0f}% Retail 🧑 | Penjual: {b_sell_pct:.0f}% Bandar 🐋 / "
                f"{r_sell_pct:.0f}% Retail 🧑)")
        res_json["summary_narrative"] = curr.rstrip(".") + note + "."

    return res_json


# ═══════════════════════════════════════════════════════════════
# MULTI-DAY SCORE
# ═══════════════════════════════════════════════════════════════
_EMPTY_MULTIDAY = {
    'score': 0.0, 'raw_weighted': 0.0,
    'consistency_bonus': 0.0, 'panic_bonus': 0.0,
    'n_snapshots': 0, 'consistent_buyers': [], 'consistent_sellers': [],
    'retail_panic_detected': False, 'freshness_hours': None,
    'trend': 'no_data', 'latest_date': None,
}


def compute_multi_day_bandar_score(history: list[dict], days: int = 10) -> dict:
    """
    Hitung skor akumulasi/distribusi dari N snapshot broksum.
    Dipanggil dari service layer yang sudah fetch `history`.
    """
    if not history:
        return dict(_EMPTY_MULTIDAY)

    try:
        history_sorted = sorted(
            history,
            key=lambda r: str(r.get('upload_date', '')),
            reverse=True,
        )
        recent = history_sorted[:days]

        snapshots: list[dict] = []
        for h in recent:
            try:
                buyers = parse_broker_list(h.get('top_buyers', '[]'))
                sellers = parse_broker_list(h.get('top_sellers', '[]'))
                if not buyers and not sellers:
                    continue

                top3_buy = sum(float(b.get('volume_lot', 0) or 0)
                               for b in buyers[:3] if isinstance(b, dict))
                top3_sell = sum(float(s.get('volume_lot', 0) or 0)
                                for s in sellers[:3] if isinstance(s, dict))
                tot_buy = sum(float(b.get('volume_lot', 0) or 0)
                              for b in buyers if isinstance(b, dict))
                tot_sell = sum(float(s.get('volume_lot', 0) or 0)
                               for s in sellers if isinstance(s, dict))

                proxy = max(tot_buy, tot_sell, 1.0)
                net_ratio = float(np.clip((top3_buy - top3_sell) / proxy, -1.0, 1.0))

                buyer_codes = [str(b.get('broker', '')).upper().strip()
                               for b in buyers[:5] if isinstance(b, dict)]
                seller_codes = [str(s.get('broker', '')).upper().strip()
                                for s in sellers[:5] if isinstance(s, dict)]

                snapshots.append({
                    'date': str(h.get('upload_date', ''))[:10],
                    'net_ratio': net_ratio,
                    'buyer_codes': [c for c in buyer_codes if c],
                    'seller_codes': [c for c in seller_codes if c],
                })
            except Exception:
                continue

        if not snapshots:
            return dict(_EMPTY_MULTIDAY)

        DECAY = 0.75
        weights = [DECAY ** i for i in range(len(snapshots))]
        total_w = sum(weights)
        weighted_score = sum(s['net_ratio'] * w for s, w in zip(snapshots, weights)) / total_w

        buyer_counter = Counter()
        seller_counter = Counter()
        for s in snapshots:
            for code in s['buyer_codes']:
                buyer_counter[code] += 1
            for code in s['seller_codes']:
                seller_counter[code] += 1

        threshold = max(3, int(len(snapshots) * 0.6))
        consistent_buyers = [c for c, n in buyer_counter.items() if n >= threshold]
        consistent_sellers = [c for c, n in seller_counter.items() if n >= threshold]

        consistency_bonus = 0.0
        if consistent_buyers:
            consistency_bonus += min(0.15 * len(consistent_buyers), 0.30)
        if consistent_sellers:
            consistency_bonus -= min(0.15 * len(consistent_sellers), 0.30)

        retail_brokers = {"YP", "PD", "XC", "KK", "NI", "CC", "XL", "AZ"}
        retail_seller_days = sum(
            1 for s in snapshots
            if len(set(s['seller_codes'][:3]) & retail_brokers) >= 2
        )
        retail_panic = retail_seller_days >= max(3, int(len(snapshots) * 0.6))
        panic_bonus = 0.15 if retail_panic else 0.0

        final_score = float(np.clip(
            weighted_score * 0.7 + consistency_bonus + panic_bonus,
            -1.0, 1.0,
        ))

        try:
            latest_date = snapshots[0]['date']
            dt_latest = datetime.strptime(latest_date, "%Y-%m-%d")
            now_naive = datetime.now()
            freshness_hours = (now_naive - dt_latest).total_seconds() / 3600
        except Exception:
            freshness_hours = None
            latest_date = snapshots[0].get('date')

        if final_score > 0.30:
            trend = 'accumulating'
        elif final_score < -0.30:
            trend = 'distributing'
        else:
            trend = 'mixed'

        return {
            'score': final_score,
            'raw_weighted': float(weighted_score),
            'consistency_bonus': float(consistency_bonus),
            'panic_bonus': float(panic_bonus),
            'n_snapshots': len(snapshots),
            'consistent_buyers': consistent_buyers,
            'consistent_sellers': consistent_sellers,
            'retail_panic_detected': retail_panic,
            'freshness_hours': freshness_hours,
            'trend': trend,
            'latest_date': latest_date,
        }
    except Exception as e:
        return {**_EMPTY_MULTIDAY, 'error': str(e)}