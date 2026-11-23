import io
from datetime import datetime
import matplotlib.pyplot as plt
import yfinance as yf
from PIL import Image, ImageDraw, ImageFont
import re

def generate_infographic_combined(res_swing, res_dt):
    """Menggabungkan SW & DT jadi 1 infografis Landscape lengkap."""
    
    # Ambil Ticker dari key 'Saham'
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

    # Setup Kanvas Infografis (Landscape 1600 x 1300)
    W, H = 1600, 1300
    img = Image.new('RGB', (W, H), color='#0f1116')
    draw = ImageDraw.Draw(img)

    # Load Font
    def get_font(size, bold=False):
        fonts = ["arialbd.ttf", "arial.ttf"] if bold else ["arial.ttf"]
        for f in fonts:
            try: return ImageFont.truetype(f, size)
            except: pass
        return ImageFont.load_default()

    font_h1 = get_font(55, True)
    font_h2 = get_font(35, True)
    font_sub = get_font(25)
    font_val = get_font(28, True)
    font_small = get_font(20)

    # Header: Ticker & Nama PT
    draw.text((50, 40), f"${ticker}", font=font_h1, fill="#ffffff")
    draw.text((50, 100), pt_name, font=font_sub, fill="#94a3b8")
    
    # Harga (Key 'Harga' berbentuk string, contoh: "76")
    harga_str = (res_swing or res_dt).get('Harga', '0')
    draw.text((W-350, 40), f"Rp {harga_str}", font=font_h1, fill="#00ffcc")
    
    now_str = datetime.now().strftime("%d %b %Y | %H:%M WIB")
    draw.text((W-350, 100), now_str, font=font_small, fill="#64748b")

    # Gambar Mini Chart (Matplotlib)
    chart_y_offset = 160
    if df_chart is not None and not df_chart.empty:
        fig, ax = plt.subplots(figsize=(16, 2.5), facecolor='#0f1116')
        ax.set_facecolor('#0f1116')
        ax.plot(df_chart.index, df_chart['Close'], color='#00ffcc', linewidth=2)
        
        ax.tick_params(colors='#64748b', labelsize=10)
        for spine in ax.spines.values(): spine.set_visible(False)
        ax.grid(color='#1e293b', linestyle='--', linewidth=0.5)
        
        buf = io.BytesIO()
        plt.savefig(buf, format='png', bbox_inches='tight', transparent=True, dpi=100)
        plt.close(fig)
        buf.seek(0)
        chart_img = Image.open(buf)
        chart_img = chart_img.resize((W-100, 250))
        img.paste(chart_img, (50, chart_y_offset))
    else:
        draw.text((50, 200), "Data grafik tidak tersedia (Gagal load yfinance)", font=font_sub, fill="#ef4444")
    
    # Garis pemisah
    draw.line([(50, 450), (W-50, 450)], fill="#334155", width=3)
    draw.line([(W//2, 470), (W//2, H-50)], fill="#334155", width=2)

    # Fungsi Helper untuk Menggambar Kolom
    def draw_column(res, x_start, mode_title, mode_icon, color_theme):
        if not res:
            draw.text((x_start, 480), f"Data {mode_title} Tidak Tersedia", font=font_h2, fill="#64748b")
            return

        y = 480
        col_w = (W // 2) - 80
        
        # Judul Kolom
        draw.text((x_start, y), f"{mode_icon} {mode_title.upper()}", font=font_h2, fill=color_theme)
        y += 50

        # Sinyal & Skor (Key: 'Sinyal', 'Score', 'RRR', 'Confidence')
        sinyal = str(res.get('Sinyal', 'N/A'))
        draw.text((x_start, y), sinyal.upper(), font=font_h2, fill="#10b981" if "BUY" in sinyal else "#f59e0b")
        y += 40
        draw.text((x_start, y), f"Score: {res.get('Score', '0.000')} | RRR: {res.get('RRR', '0.0')} | Conf: {res.get('Confidence', '0%')}", font=font_val, fill="#e2e8f0")
        y += 40

        # AI Summary & Foreign Flow Box
        draw.rectangle([x_start, y, x_start + col_w, y + 180], fill="#1e293b", outline="#334155")
        draw.text((x_start + 15, y + 15), "AI SUMMARY + NET BANDAR", font=font_small, fill="#94a3b8")
        
        # Key: 'Foreign_Net_Buy' & 'Foreign_Net_Sell'
        f_buy = str(res.get('Foreign_Net_Buy', '0'))
        f_sell = str(res.get('Foreign_Net_Sell', '0'))
        draw.text((x_start + 15, y + 50), f"Net Buy: {f_buy}", font=font_sub, fill="#10b981")
        draw.text((x_start + 250, y + 50), f"Net Sell: {f_sell}", font=font_sub, fill="#ef4444")
        
        # Key: 'AI_Insight'
        insight = str(res.get('AI_Insight', ''))
        # Bersihkan tag HTML <br> jika ada
        insight = re.sub(r'<[^>]+>', ' ', insight)
        if insight and insight != 'None':
            words = insight.split()
            line = ""
            line_y = y + 95
            for w in words:
                if len(line + w) < 75:
                    line += w + " "
                else:
                    draw.text((x_start + 15, line_y), line, font=font_small, fill="#cbd5e1")
                    line = w + " "
                    line_y += 25
                    if line_y > y + 160: break
        y += 200

        # Coppock & Regime Box (Key: 'Coppock', 'Rezim')
        draw.rectangle([x_start, y, x_start + col_w, y + 70], fill="#1e293b")
        draw.text((x_start + 15, y + 10), f"Coppock: {res.get('Coppock', 'N/A')}", font=font_sub, fill="#e2e8f0")
        draw.text((x_start + col_w//2, y + 10), f"Regime: {res.get('Rezim', 'N/A')}", font=font_sub, fill="#e2e8f0")
        y += 90

        # Harga Estimasi, TP, SL (Key: 'Estimasi_Netral', 'Estimasi_Sinyal', 'TP_Harga', 'SL_Harga')
        est_netral = str(res.get('Estimasi_Netral', '-'))
        est_sinyal = str(res.get('Estimasi_Sinyal', '-'))
        tp_val = str(res.get('TP_Harga', '-'))
        sl_val = str(res.get('SL_Harga', '-'))
        
        draw.text((x_start, y), f"Estimasi Netral: {est_netral} | Sinyal: {est_sinyal}", font=font_val, fill="#00ffcc")
        y += 40
        draw.text((x_start, y), f"🎯 Entry Zone: {res.get('Entry_Zone', 'N/A')}", font=font_val, fill="#00ffcc")
        y += 40
        draw.text((x_start, y), f"📈 TP: {tp_val}", font=font_val, fill="#10b981")
        draw.text((x_start + 350, y), f"🛑 SL: {sl_val}", font=font_val, fill="#ef4444")
        y += 60

        # Indikator Teknikal (Key: 'RSI', 'Vol_Surge', 'ZScore', 'Beta', 'Momentum')
        draw.text((x_start, y), "INDIKATOR TEKNIKAL", font=font_small, fill="#94a3b8")
        y += 30
        draw.text((x_start, y), f"RSI: {res.get('RSI', '-')}  |  Vol Surge: {res.get('Vol_Surge', '-')}  |  Z-Score: {res.get('ZScore', '-')}", font=font_sub, fill="#e2e8f0")
        y += 40
        draw.text((x_start, y), f"Beta: {res.get('Beta', '-')}  |  Momentum: {res.get('Momentum', '-')}", font=font_sub, fill="#e2e8f0")

    # Gambar Kiri (Swing) & Kanan (Daytrade)
    draw_column(res_swing, 50, "Swing", "📆", "#a855f7")
    draw_column(res_dt, W//2 + 30, "Daytrade", "⏱️", "#06b6d4")

    # Watermark Bawah
    draw.text((W//2 - 150, H - 40), "Generated by Engine Trade Pro", font=font_small, fill="#475569")

    # Simpan ke BytesIO
    img_byte_arr = io.BytesIO()
    img.save(img_byte_arr, format='PNG')
    img_byte_arr.seek(0)
    return img_byte_arr
