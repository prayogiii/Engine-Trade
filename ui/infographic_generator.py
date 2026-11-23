import io
from datetime import datetime
import matplotlib.pyplot as plt
import yfinance as yf
from PIL import Image, ImageDraw, ImageFont
import re

def generate_infographic_combined(res_swing, res_dt):
    """Menggabungkan SW & DT jadi 1 infografis Landscape rapi (Grid System)."""
    
    # 1. Ekstrak Data Utama
    raw_ticker = (res_swing or res_dt).get('Saham', 'N/A')
    ticker = str(raw_ticker).replace(".JK", "").strip()
    ticker_jk = f"{ticker}.JK"
    
    pt_name = "Nama Perusahaan Tidak Diketahui"
    df_chart = None
    try:
        if ticker != 'N/A':
            t = yf.Ticker(ticker_jk)
            pt_name = t.info.get('longName', ticker)
            df_chart = t.history(period="1mo")
    except Exception:
        pass

    # 2. Setup Kanvas (Lebih ringkas: 1200 x 1050)
    W, H = 1200, 1050
    BG_COLOR = "#0f1116"
    CARD_BG = "#1e293b"
    TEXT_MAIN = "#f8fafc"
    TEXT_MUTED = "#94a3b8"
    GREEN = "#10b981"
    RED = "#ef4444"
    YELLOW = "#f59e0b"
    
    img = Image.new('RGB', (W, H), color=BG_COLOR)
    draw = ImageDraw.Draw(img)

    # 3. Load Font (Pastikan Arial tersedia)
    def get_font(size, bold=False):
        fonts = ["arialbd.ttf", "arial.ttf"] if bold else ["arial.ttf"]
        for f in fonts:
            try: return ImageFont.truetype(f, size)
            except: pass
        return ImageFont.load_default()

    font_h1 = get_font(40, True)
    font_h2 = get_font(24, True)
    font_sub = get_font(18)
    font_val = get_font(20, True)
    font_small = get_font(14)

    # ═══════════════════════════════════════════════════════════
    # BAGIAN 1: HEADER
    # ═══════════════════════════════════════════════════════════
    draw.text((40, 40), f"${ticker}", font=font_h1, fill=TEXT_MAIN)
    draw.text((40, 90), pt_name, font=font_sub, fill=TEXT_MUTED)
    
    harga_str = (res_swing or res_dt).get('Harga', '0')
    draw.text((W-200, 40), f"Rp {harga_str}", font=font_h1, fill="#00ffcc")
    
    now_str = datetime.now().strftime("%d %b %Y | %H:%M WIB")
    draw.text((W-200, 90), now_str, font=font_small, fill=TEXT_MUTED)

    # ═══════════════════════════════════════════════════════════
    # BAGIAN 2: MINI CHART
    # ═══════════════════════════════════════════════════════════
    chart_y_offset = 130
    if df_chart is not None and not df_chart.empty:
        fig, ax = plt.subplots(figsize=(12, 2), facecolor=BG_COLOR)
        ax.set_facecolor(BG_COLOR)
        
        # Garis dan Area Fill
        ax.plot(df_chart.index, df_chart['Close'], color='#00ffcc', linewidth=2)
        ax.fill_between(df_chart.index, df_chart['Close'], df_chart['Close'].min(), color='#00ffcc', alpha=0.1)
        
        ax.tick_params(colors=TEXT_MUTED, labelsize=10)
        for spine in ax.spines.values(): spine.set_visible(False)
        ax.grid(color='#1e293b', linestyle='--', linewidth=0.5)
        
        buf = io.BytesIO()
        plt.savefig(buf, format='png', bbox_inches='tight', transparent=True, dpi=100)
        plt.close(fig)
        buf.seek(0)
        chart_img = Image.open(buf)
        chart_img = chart_img.resize((W-80, 200))
        img.paste(chart_img, (40, chart_y_offset))
    
    # Garis Pemisah Horizontal
    draw.line([(40, 350), (W-40, 350)], fill="#334155", width=2)

    # ═══════════════════════════════════════════════════════════
    # BAGIAN 3: KARTU SWING & DAYTRADE
    # ═══════════════════════════════════════════════════════════
    
    def draw_card(res, x_pos, mode_title, color_theme):
        card_y = 370
        card_w = 540
        card_h = 600
        
        # Background Kartu
        draw.rounded_rectangle([x_pos, card_y, x_pos + card_w, card_y + card_h], radius=15, fill=CARD_BG)
        
        if not res:
            draw.text((x_pos + 20, card_y + 20), f"Data {mode_title} Tidak Tersedia", font=font_h2, fill=TEXT_MUTED)
            return

        y = card_y + 20
        
        # 3.1 Judul Mode
        draw.text((x_pos + 20, y), mode_title.upper(), font=font_h2, fill=color_theme)
        y += 40
        
        # 3.2 Sinyal & Skor
        sinyal = str(res.get('Sinyal', 'N/A')).upper()
        sig_color = GREEN if "BUY" in sinyal else (RED if "AVOID" in sinyal else YELLOW)
        draw.text((x_pos + 20, y), sinyal, font=font_val, fill=sig_color)
        
        # Kotak Skor
        draw.rounded_rectangle([x_pos + 20, y + 30, x_pos + card_w - 20, y + 80], radius=8, fill="#0f1116")
        draw.text((x_pos + 30, y + 45), f"Score: {res.get('Score', '-')}", font=font_sub, fill=TEXT_MAIN)
        draw.text((x_pos + 180, y + 45), f"RRR: {res.get('RRR', '-')}", font=font_sub, fill=TEXT_MAIN)
        draw.text((x_pos + 320, y + 45), f"Conf: {res.get('Confidence', '-')}", font=font_sub, fill=TEXT_MAIN)
        y += 100
        
        # 3.3 AI Summary Box
        draw.rounded_rectangle([x_pos + 20, y, x_pos + card_w - 20, y + 120], radius=8, fill="#0f1116", outline="#334155", width=1)
        draw.text((x_pos + 30, y + 10), "AI SUMMARY + NET BANDAR", font=font_small, fill=TEXT_MUTED)
        
        f_buy = str(res.get('Foreign_Net_Buy', '0'))
        f_sell = str(res.get('Foreign_Net_Sell', '0'))
        draw.text((x_pos + 30, y + 30), f"Net Buy: {f_buy}", font=font_sub, fill=GREEN)
        draw.text((x_pos + 250, y + 30), f"Net Sell: {f_sell}", font=font_sub, fill=RED)
        
        insight = str(res.get('AI_Insight', ''))
        insight = re.sub(r'<[^>]+>', ' ', insight) # Bersihkan HTML
        if insight and insight != 'None':
            words = insight.split()
            line = ""
            line_y = y + 60
            for w in words:
                if len(line + w) < 50: # Batasi karakter per baris
                    line += w + " "
                else:
                    draw.text((x_pos + 30, line_y), line, font=font_small, fill="#cbd5e1")
                    line = w + " "
                    line_y += 18
                    if line_y > y + 100: break
        y += 140

        # 3.4 TP & SL Box (Grid 2 Kolom)
        box_w = (card_w - 50) // 2
        draw.rounded_rectangle([x_pos + 20, y, x_pos + 20 + box_w, y + 70], radius=8, fill="#0f1116", outline=GREEN, width=1)
        draw.text((x_pos + 30, y + 10), "ENTRY / TP", font=font_small, fill=TEXT_MUTED)
        draw.text((x_pos + 30, y + 30), f"{res.get('TP_Harga', '-')}", font=font_val, fill=GREEN)
        
        draw.rounded_rectangle([x_pos + 30 + box_w, y, x_pos + card_w - 20, y + 70], radius=8, fill="#0f1116", outline=RED, width=1)
        draw.text((x_pos + 40 + box_w, y + 10), "STOP LOSS", font=font_small, fill=TEXT_MUTED)
        draw.text((x_pos + 40 + box_w, y + 30), f"{res.get('SL_Harga', '-')}", font=font_val, fill=RED)
        y += 90

        # 3.5 Indikator Teknikal
        draw.text((x_pos + 20, y), "INDIKATOR TEKNIKAL", font=font_small, fill=TEXT_MUTED)
        y += 25
        draw.text((x_pos + 20, y), f"RSI: {res.get('RSI', '-')}   |   Vol: {res.get('Vol_Surge', '-')}   |   Z-Score: {res.get('ZScore', '-')}", font=font_sub, fill=TEXT_MAIN)
        y += 30
        draw.text((x_pos + 20, y), f"Beta: {res.get('Beta', '-')}  |  Momentum: {res.get('Momentum', '-')}", font=font_sub, fill=TEXT_MAIN)
        y += 30
        draw.text((x_pos + 20, y), f"Regime: {res.get('Rezim', '-')}", font=font_sub, fill=TEXT_MAIN)
        y += 30
        draw.text((x_pos + 20, y), f"Coppock: {res.get('Coppock', '-')}", font=font_sub, fill=TEXT_MAIN)

    # Gambar Kartu Kiri & Kanan
    draw_card(res_swing, 40, "SWING / SW", "#a855f7")
    draw_card(res_dt, 620, "DAYTRADE / DT", "#06b6d4")

    # Watermark Bawah
    draw.text((W//2 - 100, H - 40), "Generated by Engine Trade Pro", font=font_small, fill="#475569")

    # Simpan ke BytesIO
    img_byte_arr = io.BytesIO()
    img.save(img_byte_arr, format='PNG')
    img_byte_arr.seek(0)
    return img_byte_arr
