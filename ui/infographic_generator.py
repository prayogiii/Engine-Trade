import io
import re
from datetime import datetime
import matplotlib.pyplot as plt
import yfinance as yf
from PIL import Image, ImageDraw, ImageFont


def generate_infographic_combined(res_swing, res_dt):
    """Redesign infografis SW & DT bergaya dark dashboard (1600 x 1200)."""

    base_res = res_swing or res_dt or {}

    # 1. Ekstrak Ticker & Data yfinance
    raw_ticker = base_res.get("Saham") or base_res.get("ticker_raw") or "N/A"
    ticker = str(raw_ticker).replace(".JK", "").strip().upper()
    ticker_jk = f"{ticker}.JK"

    pt_name = "Nama Perusahaan Tidak Diketahui"
    sector_label = "IDX EQUITY"
    df_chart = None
    try:
        if ticker and ticker != "N/A":
            t = yf.Ticker(ticker_jk)
            info = t.info or {}
            pt_name = info.get("longName") or info.get("shortName") or ticker
            sector_raw = info.get("sector") or info.get("industry")
            if sector_raw:
                sector_label = f"INDONESIA SECTOR: {str(sector_raw).upper()}"
            df_chart = t.history(period="1mo")
    except Exception:
        pass

    # 2. Setup Kanvas & Palet Warna
    W, H = 1600, 1200
    BG_COLOR = "#0b0e14"
    CARD_BG = "#131822"
    INNER_BG = "#19202e"
    BORDER_COLOR = "#252f42"
    TEXT_MAIN = "#f8fafc"
    TEXT_MUTED = "#94a3b8"
    CYAN = "#00ffcc"
    PURPLE = "#9333ea"
    TEAL = "#06b6d4"
    GREEN = "#10b981"
    RED = "#ef4444"

    img = Image.new("RGB", (W, H), color=BG_COLOR)
    draw = ImageDraw.Draw(img)

    # 3. Load Font (Prioritas font sistem agar tidak jatuh ke font kecil / missing glyph)
    def get_font(size, bold=False):
        candidates = (
            [
                "arialbd.ttf",
                "Arial Bold.ttf",
                "DejaVuSans-Bold.ttf",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                "arial.ttf",
            ]
            if bold
            else [
                "arial.ttf",
                "Arial.ttf",
                "DejaVuSans.ttf",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            ]
        )
        for f in candidates:
            try:
                return ImageFont.truetype(f, size)
            except Exception:
                pass
        return ImageFont.load_default()

    font_ticker = get_font(54, True)
    font_price = get_font(48, True)
    font_badge = get_font(16, True)
    font_h2 = get_font(30, True)
    font_sub = get_font(22)
    font_val = get_font(23, True)
    font_small = get_font(18)
    font_xs = get_font(16)

    def text_w(text, font):
        bbox = draw.textbbox((0, 0), str(text), font=font)
        return bbox[2] - bbox[0]

    def text_h(text, font):
        bbox = draw.textbbox((0, 0), str(text), font=font)
        return bbox[3] - bbox[1]

    def draw_wrapped_lines(text, x, y, max_w, max_lines, font, fill, line_h=24, prefix_bullet=False):
        clean = re.sub(r"<[^>]+>", " ", str(text or "")).strip()
        if not clean or clean.lower() == "none":
            return y

        # Pisahkan berdasarkan titik / newline jika ada agar poin terlihat rapi seperti bullet
        raw_parts = [p.strip() for p in re.split(r"[\n]+|(?<=\.)\s+", clean) if p.strip()]
        if not raw_parts:
            raw_parts = [clean]

        lines_drawn = 0
        cur_y = y
        for part in raw_parts:
            prefix = "• " if prefix_bullet else ""
            words = (prefix + part).split()
            line = ""
            for w in words:
                test = f"{line} {w}".strip()
                if text_w(test, font) <= max_w:
                    line = test
                else:
                    if line:
                        draw.text((x, cur_y), line, font=font, fill=fill)
                        cur_y += line_h
                        lines_drawn += 1
                        if lines_drawn >= max_lines:
                            return cur_y
                    line = w
            if line:
                draw.text((x, cur_y), line, font=font, fill=fill)
                cur_y += line_h
                lines_drawn += 1
                if lines_drawn >= max_lines:
                    return cur_y
        return cur_y

    def pick_val(res, keys, default="-"):
        if not res:
            return default
        for k in keys:
            if k in res and res[k] is not None and str(res[k]).strip() != "":
                return res[k]
        return default

    # ═══════════════════════════════════════════════════════════
    # 1. HEADER
    # ═══════════════════════════════════════════════════════════
    ticker_str = f"${ticker}"
    draw.text((50, 36), ticker_str, font=font_ticker, fill=TEXT_MAIN)

    badge_x = 50 + text_w(ticker_str, font_ticker) + 22
    badge_w = text_w(sector_label, font_badge) + 24
    draw.rounded_rectangle([badge_x, 52, badge_x + badge_w, 84], radius=6, fill=INNER_BG, outline=BORDER_COLOR, width=1)
    draw.text((badge_x + 12, 59), sector_label, font=font_badge, fill=TEXT_MUTED)

    draw.text((50, 102), pt_name, font=font_sub, fill=TEXT_MUTED)

    raw_harga = str(pick_val(base_res, ["Harga", "harga_terakhir"], "0")).strip()
    harga_display = raw_harga if raw_harga.upper().startswith("RP") else f"Rp {raw_harga}"
    draw.text((W - 50 - text_w(harga_display, font_price), 38), harga_display, font=font_price, fill=CYAN)

    now_str = datetime.now().strftime("%d %b %Y | %H:%M WIB")
    draw.text((W - 50 - text_w(now_str, font_small), 102), now_str, font=font_small, fill=TEXT_MUTED)

    # ═══════════════════════════════════════════════════════════
    # 2. MINI CHART (HARGA + AREA FILL + MINI VOLUME BAR)
    # ═══════════════════════════════════════════════════════════
    chart_y = 148
    chart_h = 225
    if df_chart is not None and not df_chart.empty:
        fig = plt.figure(figsize=(15, 2.3), facecolor=BG_COLOR)
        gs = fig.add_gridspec(2, 1, height_ratios=[4.2, 1.0], hspace=0.06)

        ax_price = fig.add_subplot(gs[0])
        ax_vol = fig.add_subplot(gs[1], sharex=ax_price)

        for ax in (ax_price, ax_vol):
            ax.set_facecolor(BG_COLOR)
            for spine in ax.spines.values():
                spine.set_visible(False)

        closes = df_chart["Close"]
        y_min = float(closes.min()) * 0.992
        y_max = float(closes.max()) * 1.005

        ax_price.plot(df_chart.index, closes, color=CYAN, linewidth=2.4)
        ax_price.fill_between(df_chart.index, closes, y_min, color=CYAN, alpha=0.14)
        ax_price.set_ylim(y_min, y_max)
        ax_price.tick_params(axis="y", colors=TEXT_MUTED, labelsize=9)
        ax_price.tick_params(axis="x", which="both", bottom=False, labelbottom=False)
        ax_price.grid(axis="y", color="#1b2230", linestyle="-", linewidth=0.6)

        if "Volume" in df_chart.columns:
            vols = df_chart["Volume"].fillna(0)
            ax_vol.bar(df_chart.index, vols, color="#334155", width=0.65, alpha=0.85)
        ax_vol.set_yticks([])
        ax_vol.tick_params(axis="x", colors=TEXT_MUTED, labelsize=9)

        buf = io.BytesIO()
        plt.savefig(buf, format="png", bbox_inches="tight", facecolor=BG_COLOR, dpi=110)
        plt.close(fig)
        buf.seek(0)

        chart_img = Image.open(buf).convert("RGB").resize((W - 100, chart_h))
        img.paste(chart_img, (50, chart_y))

    # Garis Pemisah Horizontal & Vertikal Tengah
    div_y = 395
    draw.line([(50, div_y), (W - 50, div_y)], fill=BORDER_COLOR, width=2)
    draw.line([(W // 2, div_y + 20), (W // 2, H - 65)], fill=BORDER_COLOR, width=2)

    # ═══════════════════════════════════════════════════════════
    # 3. KOLOM SWING & DAYTRADE (STYLE CARD DASHBOARD)
    # ═══════════════════════════════════════════════════════════
    def draw_panel(res, x0, title, accent_color):
        col_w = (W // 2) - 85
        y = div_y + 28

        if not res:
            draw.text((x0, y), title.upper(), font=font_h2, fill=accent_color)
            draw.rounded_rectangle([x0, y + 48, x0 + col_w, y + 140], radius=12, fill=CARD_BG, outline=BORDER_COLOR, width=1)
            draw.text((x0 + 20, y + 80), f"Data {title} Tidak Tersedia", font=font_sub, fill=TEXT_MUTED)
            return

        # Judul Kolom + Badge Sinyal di Kanan
        draw.text((x0, y), title.upper(), font=font_h2, fill=accent_color)

        sinyal_str = str(pick_val(res, ["Sinyal", "signal"], "N/A")).strip().upper()
        pill_w = max(110, text_w(sinyal_str, font_badge) + 32)
        pill_h = 36
        pill_x = x0 + col_w - pill_w
        draw.rounded_rectangle([pill_x, y - 2, pill_x + pill_w, y - 2 + pill_h], radius=8, fill=accent_color)
        draw.text(
            (pill_x + (pill_w - text_w(sinyal_str, font_badge)) // 2, y - 2 + (pill_h - text_h(sinyal_str, font_badge)) // 2 - 1),
            sinyal_str,
            font=font_badge,
            fill=TEXT_MAIN,
        )
        y += 44

        # Baris Score | RRR | Conf
        score_v = pick_val(res, ["Score", "signal_score"], "-")
        rrr_v = pick_val(res, ["RRR", "rrr"], "-")
        conf_v = pick_val(res, ["Confidence", "confidence"], "-")
        meta_line = f"Score: {score_v}   |   RRR: {rrr_v}   |   Conf: {conf_v}"
        draw.text((x0, y), meta_line, font=font_sub, fill=TEXT_MUTED)
        y += 42

        # Box 1: AI SUMMARY + NET BANDAR
        box1_h = 215
        draw.rounded_rectangle([x0, y, x0 + col_w, y + box1_h], radius=12, fill=CARD_BG, outline=BORDER_COLOR, width=1)
        draw.text((x0 + 20, y + 16), "AI SUMMARY + NET BANDAR", font=font_xs, fill=TEXT_MUTED)

        f_buy = str(pick_val(res, ["Foreign_Net_Buy", "foreign_net_buy"], "0"))
        f_sell = str(pick_val(res, ["Foreign_Net_Sell", "foreign_net_sell"], "0"))
        buy_pill = f"Net Buy: {f_buy}"
        sell_pill = f"Net Sell: {f_sell}"

        bp_w = text_w(buy_pill, font_xs) + 20
        sp_w = text_w(sell_pill, font_xs) + 20
        draw.rounded_rectangle([x0 + 20, y + 44, x0 + 20 + bp_w, y + 72], radius=6, fill="#0d2922", outline="#14532d", width=1)
        draw.text((x0 + 30, y + 49), buy_pill, font=font_xs, fill=GREEN)

        draw.rounded_rectangle([x0 + 32 + bp_w, y + 44, x0 + 32 + bp_w + sp_w, y + 72], radius=6, fill="#2a1215", outline="#7f1d1d", width=1)
        draw.text((x0 + 42 + bp_w, y + 49), sell_pill, font=font_xs, fill=RED)

        insight_raw = pick_val(res, ["AI_Insight", "AI_Summary", "insight"], "")
        draw_wrapped_lines(insight_raw, x0 + 20, y + 86, col_w - 40, max_lines=4, font=font_small, fill="#cbd5e1", line_h=28, prefix_bullet=True)
        y += box1_h + 18

        # Box 2: Coppock & Regime
        box2_h = 58
        draw.rounded_rectangle([x0, y, x0 + col_w, y + box2_h], radius=12, fill=CARD_BG, outline=BORDER_COLOR, width=1)
        coppock_v = pick_val(res, ["Coppock", "coppock_status"], "-")
        regime_v = pick_val(res, ["Rezim", "regime"], "-")
        draw.text((x0 + 20, y + 17), f"Coppock: {coppock_v}", font=font_sub, fill=TEXT_MAIN)
        draw.text((x0 + col_w // 2 + 10, y + 17), f"Regime: {regime_v}", font=font_sub, fill=TEXT_MAIN)
        y += box2_h + 18

        # Box 3: Estimasi, Entry Zone, TP & SL
        box3_h = 132
        draw.rounded_rectangle([x0, y, x0 + col_w, y + box3_h], radius=12, fill=CARD_BG, outline=BORDER_COLOR, width=1)
        est_netral = pick_val(res, ["Est_Netral", "est_besok_f"], "-")
        est_sinyal = pick_val(res, ["Est_Sinyal", "est_besok_sinyal_f"], "-")
        entry_zone = pick_val(res, ["Entry_Zone", "entry_zone_f"], "-")
        tp_val = pick_val(res, ["TP_Harga", "tp_low_f"], "-")
        sl_val = pick_val(res, ["SL_Harga", "sl_harga_f"], "-")

        draw.text((x0 + 20, y + 16), f"Estimasi Netral: Rp {est_netral}  |  Sinyal: Rp {est_sinyal}", font=font_sub, fill=CYAN)
        draw.text((x0 + 20, y + 52), f"Entry Zone: {entry_zone}", font=font_val, fill=CYAN)
        draw.text((x0 + 20, y + 90), f"TP: Rp {tp_val}", font=font_val, fill=GREEN)
        draw.text((x0 + col_w // 2 + 10, y + 90), f"SL: Rp {sl_val}", font=font_val, fill=RED)
        y += box3_h + 18

        # Box 4: Indikator Teknikal
        box4_h = 98
        draw.rounded_rectangle([x0, y, x0 + col_w, y + box4_h], radius=12, fill=CARD_BG, outline=BORDER_COLOR, width=1)
        rsi_v = pick_val(res, ["RSI", "rsi14"], "-")
        vol_v = pick_val(res, ["Vol_Surge", "vol_surge_pct"], "-")
        zs_v = pick_val(res, ["ZScore", "zscore_val"], "-")
        beta_v = pick_val(res, ["Beta", "beta_ihsg"], "-")
        mom_v = pick_val(res, ["Momentum", "mom_median_th"], "-")

        draw.text((x0 + 20, y + 18), f"RSI: {rsi_v}   |   Vol Surge: {vol_v}   |   Z-Score: {zs_v}", font=font_sub, fill=TEXT_MAIN)
        draw.text((x0 + 20, y + 54), f"Beta: {beta_v}   |   Momentum: {mom_v}", font=font_sub, fill=TEXT_MAIN)

    draw_panel(res_swing, 50, "SWING", PURPLE)
    draw_panel(res_dt, W // 2 + 35, "DAYTRADE", TEAL)

    # ═══════════════════════════════════════════════════════════
    # 4. WATERMARK BAWAH
    # ═══════════════════════════════════════════════════════════
    wm_text = "Generated by Engine Trade Pro"
    draw.text(((W - text_w(wm_text, font_small)) // 2, H - 42), wm_text, font=font_small, fill="#64748b")

    img_byte_arr = io.BytesIO()
    img.save(img_byte_arr, format="PNG")
    img_byte_arr.seek(0)
    return img_byte_arr
