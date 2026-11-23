"""Infografis sinyal saham (Swing + Daytrade) dalam satu gambar."""
import io
import os
import re
import json
from datetime import datetime, timedelta, timezone

import matplotlib
import numpy as np
import yfinance as yf
from matplotlib.figure import Figure
from matplotlib.ticker import FuncFormatter
from PIL import Image, ImageDraw, ImageFont

# ── IMPORT DATABASE KAMU ──
from services.sheets_client import load_broksum_history, load_foreign_flow_history

# ── Palet ──
BG = "#0e1726"
SURFACE = "#152238"
RULE = "#26385a"
TEXT = "#eef2f7"
MUTED = "#8fa1bd"
UP = "#34d399"
DOWN = "#fb7185"
WARN = "#fbbf24"
SWING = "#a78bfa"      
DAYTRADE = "#38bdf8"   

# ── Ukuran (Card ditambah tingginya untuk muat info baru) ──
W, M, GAP = 1200, 40, 24
SCALE = 2
CARDS_Y, CARD_H = 364, 930  
H = CARDS_Y + CARD_H + 64

# ── Font ──
_FONTS = {
    False: ["segoeui.ttf", "arial.ttf", "Arial.ttf", "Roboto-Regular.ttf", "DejaVuSans.ttf"],
    True: ["segoeuib.ttf", "arialbd.ttf", "Arial Bold.ttf", "Roboto-Bold.ttf", "DejaVuSans-Bold.ttf"],
}
_font_cache = {}

def _font(size, bold=False):
    key = (size, bold)
    if key in _font_cache:
        return _font_cache[key]
    px = round(size * SCALE)
    bundled = os.path.join(
        matplotlib.get_data_path(), "fonts", "ttf",
        "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf",
    )
    font = None
    for name in _FONTS[bold] + [bundled]:
        try:
            font = ImageFont.truetype(name, px)
            break
        except OSError:
            continue
    if font is None:
        try:
            font = ImageFont.load_default(px)
        except TypeError:
            font = ImageFont.load_default()
    _font_cache[key] = font
    return font

# ── Kanvas ──
class _Canvas:
    def __init__(self, w, h):
        self.img = Image.new("RGB", (w * SCALE, h * SCALE), BG)
        self.d = ImageDraw.Draw(self.img)

    @staticmethod
    def _px(*v):
        return [round(i * SCALE) for i in v]

    def rect(self, x0, y0, x1, y1, fill=None, r=0):
        box = self._px(x0, y0, x1, y1)
        if r:
            self.d.rounded_rectangle(box, radius=round(r * SCALE), fill=fill)
        else:
            self.d.rectangle(box, fill=fill)

    def circle(self, cx, cy, r, fill):
        self.d.ellipse(self._px(cx - r, cy - r, cx + r, cy + r), fill=fill)

    def hline(self, x0, x1, y, color):
        self.d.line(self._px(x0, y, x1, y), fill=color, width=SCALE)

    def text(self, x, y, s, font, fill, anchor="la"):
        self.d.text((x * SCALE, y * SCALE), s, font=font, fill=fill, anchor=anchor)

    def tw(self, s, font):
        return self.d.textlength(s, font=font) / SCALE

    def paste(self, im, x, y):
        self.img.paste(im, (round(x * SCALE), round(y * SCALE)))

# ── Helper ──
def _txt(v, default="-"):
    if v is None:
        return default
    s = str(v).strip()
    return default if s.lower() in ("", "none", "nan") else s

def _remove_emojis(text):
    """Menghapus semua karakter non-ASCII (termasuk emoji) agar tidak jadi kotak."""
    if not text:
        return ""
    # Hapus karakter di luar ASCII standar
    text = re.sub(r'[^\x00-\x7F]+', '', str(text))
    # Rapikan spasi ganda
    return re.sub(r'\s+', ' ', text).strip()

def _num(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return None if v != v else float(v)
    m = re.search(r"-?\d[\d.,]*", str(v))
    if not m:
        return None
    s = m.group(0).rstrip(".,")
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s or "." in s:
        sep = "," if "," in s else "."
        parts = s.split(sep)
        if len(parts) > 2 or len(parts[-1]) == 3:
            s = s.replace(sep, "")
        elif sep == ",":
            s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None

def _idr(v):
    return f"{v:,.0f}".replace(",", ".")

def _mix(c1, c2, t):
    a = [int(c1.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)]
    b = [int(c2.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)]
    return "#%02x%02x%02x" % tuple(int(a[i] * t + b[i] * (1 - t)) for i in range(3))

def _fit(cv, s, font, max_w):
    if cv.tw(s, font) <= max_w:
        return s
    while s and cv.tw(s + "…", font) > max_w:
        s = s[:-1]
    return s.rstrip() + "…"

def _fit_font(cv, s, sizes, bold, max_w):
    for size in sizes:
        f = _font(size, bold)
        if cv.tw(s, f) <= max_w:
            return f
    return _font(sizes[-1], bold)

def _wrap(cv, text, font, max_w, max_lines=10):
    lines, cur = [], ""
    for word in text.split():
        trial = f"{cur} {word}".strip()
        if cv.tw(trial, font) <= max_w:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1] + "..."
    return lines

def _signal_color(sig):
    s = sig.upper()
    if any(k in s for k in ("AVOID", "SELL", "JUAL", "HINDARI")):
        return DOWN
    if "BUY" in s or "BELI" in s:
        return UP
    return WARN

def _sep(cv, x, w, cy):
    cv.hline(x, x + w, cy + 12, RULE)
    return cy + 24

# ── Chart ──
def _render_chart(close, w, h):
    ys = close.to_numpy(dtype=float)
    xs = np.arange(len(ys))
    color = UP if ys[-1] >= ys[0] else DOWN
    dpi = 100 * SCALE

    fig = Figure(figsize=(w / 100, h / 100), dpi=dpi, facecolor=SURFACE)
    fig.subplots_adjust(left=0.012, right=0.925, top=0.95, bottom=0.2)
    ax = fig.add_subplot(111)
    ax.set_facecolor(SURFACE)

    lo, hi = ys.min(), ys.max()
    pad = (hi - lo) * 0.18 or max(hi * 0.02, 1)
    ax.set_ylim(lo - pad, hi + pad)
    ax.set_xlim(-0.4, len(ys) - 0.6)
    ax.fill_between(xs, ys, lo - pad, color=color, alpha=0.13, linewidth=0)
    ax.plot(xs, ys, color=color, linewidth=2.4, solid_capstyle="round")
    ax.scatter([xs[-1]], [ys[-1]], s=70, color=color, edgecolors=SURFACE, linewidths=2.5, zorder=5)

    ax.grid(axis="y", color=RULE, linewidth=0.8)
    ax.set_axisbelow(True)
    for sp in ax.spines.values():
        sp.set_visible(False)
    ax.yaxis.tick_right()
    ax.tick_params(colors=MUTED, labelsize=9, length=0, pad=8)
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: _idr(v)))
    ticks = sorted({int(t) for t in np.linspace(0, len(ys) - 1, 5).round()})
    ax.set_xticks(ticks)
    ax.set_xticklabels([close.index[i].strftime("%d %b") for i in ticks])

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi, facecolor=SURFACE)
    buf.seek(0)
    return Image.open(buf).convert("RGB")

# ── Bar Level Harga ──
def _levels(cv, res, x, y, w, price_raw):
    f_cap, f_val = _font(12), _font(16, True)
    tp_raw, sl_raw = _txt(res.get("TP_Harga")), _txt(res.get("SL_Harga"))
    pr, tp, sl = _num(price_raw), _num(res.get("TP_Harga")), _num(res.get("SL_Harga"))

    if None in (pr, tp, sl):
        half = w / 2
        for i, (lab, val, col) in enumerate((("Target (TP)", tp_raw, UP), ("Stop loss (SL)", sl_raw, DOWN))):
            cv.text(x + i * half, y + 8, lab, _font(13), MUTED, "la")
            cv.text(x + i * half, y + 30, val, _fit_font(cv, val, (26, 22, 18), True, half - 12), col, "la")
        return

    bx0, bx1 = x + 10, x + w - 10
    lo, hi = min(pr, tp, sl), max(pr, tp, sl)

    def pos(v):
        return bx0 + (bx1 - bx0) * (((v - lo) / (hi - lo)) if hi > lo else 0.5)

    py = y + 52
    cv.rect(bx0, py - 4, bx1, py + 4, fill=RULE, r=4)
    for target, col in ((sl, DOWN), (tp, UP)):
        a, b = sorted((pos(pr), pos(target)))
        if b - a > 0.5:
            cv.rect(a, py - 4, b, py + 4, fill=col, r=min(4, (b - a) / 2))
    px = pos(pr)
    cv.circle(px, py, 9, TEXT)
    cv.circle(px, py, 4, SURFACE)

    price_txt = _txt(price_raw)
    half_w = cv.tw(price_txt, f_val) / 2
    lx = min(max(px, x + half_w), x + w - half_w)
    cv.text(lx, y, "Harga", f_cap, MUTED, "ma")
    cv.text(lx, y + 15, price_txt, f_val, TEXT, "ma")

    left, right = sorted(
        (("Stop loss", sl_raw, DOWN, sl), ("Target", tp_raw, UP, tp)), key=lambda t: t[3]
    )
    cv.text(x, y + 66, left[0], f_cap, MUTED, "la")
    cv.text(x, y + 80, left[1], f_val, left[2], "la")
    cv.text(x + w, y + 66, right[0], f_cap, MUTED, "ra")
    cv.text(x + w, y + 80, right[1], f_val, right[2], "ra")

# ── Kartu Strategi ──
def _card(cv, res, x, y, w, h, title, accent, fallback_price, ai_summary, flow_data, broker_data):
    cv.rect(x, y, x + w, y + h, fill=SURFACE, r=22)
    pad = 28
    ix, iw, cy = x + pad, w - 2 * pad, y + pad
    f_lab = _font(13)

    cv.circle(ix + 5, cy + 10, 5, accent)
    cv.text(ix + 18, cy + 10, title, _font(17, True), TEXT, "lm")
    if not res:
        cv.text(x + w / 2, y + h / 2, "Data belum tersedia", _font(18), MUTED, "mm")
        return
    cy += 30

    # 1. Sinyal (Bersih dari Emoji & Kurung)
    sig_raw = _txt(res.get("Sinyal"), "N/A").upper()
    sig_clean = _remove_emojis(sig_raw).split('(')[0].strip()
    cv.text(ix, cy, sig_clean, _fit_font(cv, sig_clean, (36, 32, 28, 24), True, iw), _signal_color(sig_clean), "la")
    cy += 45

    # 2. Skor, RRR, Conf
    colw = iw / 3
    for i, (lab, key) in enumerate((("Score", "Score"), ("Risk reward", "RRR"), ("Confidence", "Confidence"))):
        cx = ix + i * colw
        val = _txt(res.get(key))
        cv.text(cx, cy, lab, f_lab, MUTED, "la")
        cv.text(cx, cy + 20, val, _fit_font(cv, val, (24, 21, 18, 15), True, colw - 12), TEXT, "la")
    cy = _sep(cv, ix, iw, cy + 48)

    # 3. Entry & Dip Entry
    half = iw / 2
    entry_val = _txt(res.get("Entry_Zone"), "-")
    dip_val = _txt(res.get("Entry_Ideal_RRR2"), "-")
    cv.text(ix, cy, "Entry Zone", f_lab, MUTED, "la")
    cv.text(ix, cy + 20, entry_val, _fit_font(cv, entry_val, (20, 18, 16), True, half - 12), accent, "la")
    cv.text(ix + half, cy, "Dip Entry", f_lab, MUTED, "la")
    cv.text(ix + half, cy + 20, dip_val, _fit_font(cv, dip_val, (20, 18, 16), True, half - 12), WARN, "la")
    cy = _sep(cv, ix, iw, cy + 48)

    # 4. Level Harga (TP/SL)
    cv.text(ix, cy, "Level harga", f_lab, MUTED, "la")
    cy += 22
    _levels(cv, res, ix, cy, iw, res.get("Harga") or fallback_price)
    cy = _sep(cv, ix, iw, cy + 100)

    # 5. Bandar & Foreign Flow (3 Kolom + 1 Baris Net)
    cv.text(ix, cy, "Foreign Flow & Broker", f_lab, MUTED, "la")
    cy += 20
    cw3 = iw / 3
    
    # Baris 1: Buy, Sell, Net Asing
    cv.text(ix, cy, "Buy Asing", _font(11), MUTED, "la")
    cv.text(ix, cy + 15, flow_data['buy'], _font(15, True), UP, "la")
    
    cv.text(ix + cw3, cy, "Sell Asing", _font(11), MUTED, "la")
    cv.text(ix + cw3, cy + 15, flow_data['sell'], _font(15, True), DOWN, "la")
    
    cv.text(ix + cw3*2, cy, "Net Asing", _font(11), MUTED, "la")
    net_color = UP if flow_data['net_val'] >= 0 else DOWN
    cv.text(ix + cw3*2, cy + 15, flow_data['net'], _font(15, True), net_color, "la")

    cy += 40
    # Baris 2: Net Bandar & Retail
    nb_color = UP if broker_data['net_bandar'] >= 0 else DOWN
    nr_color = DOWN if broker_data['net_retail'] <= 0 else UP
    cv.text(ix, cy, f"Net Bandar: {broker_data['net_bandar']:+.1f}%", _font(13, True), nb_color, "la")
    cv.text(ix + half, cy, f"Net Retail: {broker_data['net_retail']:+.1f}%", _font(13, True), nr_color, "la")
    
    cy = _sep(cv, ix, iw, cy + 30)

    # 6. Ringkasan AI (Redesign Rapi & Bersih)
    cv.text(ix, cy, "Ringkasan AI", f_lab, MUTED, "la")
    cy += 20
    
    # Kotak background khusus untuk AI (gelap, membedakan dari card)
    box_h = 135
    cv.rect(ix, cy, ix + iw, cy + box_h, fill="#0d1626", r=8)
    cv.rect(ix, cy, ix + 4, cy + box_h, fill=accent, r=2) # Garis aksen kiri
    
    insight = _remove_emojis(ai_summary)
    if not insight:
        insight = "Belum ada ringkasan."
        
    f_ins = _font(12) # Font dikecilkan sedikit agar muat banyak
    # max_lines disesuaikan dengan tinggi kotak (135px / 18px per baris = ~7 baris)
    lines = _wrap(cv, insight, f_ins, iw - 24, max_lines=7)
    for i, line in enumerate(lines):
        cv.text(ix + 16, cy + 12 + i * 17, line, f_ins, "#cbd5e1", "la")
    
    cy = _sep(cv, ix, iw, cy + box_h + 10)

    # 7. Indikator (Termasuk Likuiditas & Trend)
    cv.text(ix, cy, "Indikator teknikal", f_lab, MUTED, "la")
    cy += 22
    items = (
        ("RSI", "RSI"), ("Vol surge", "Vol_Surge"), ("Z-score", "ZScore"), ("Beta", "Beta"),
        ("Momentum", "Momentum"), ("Coppock", "Coppock"), ("Trend", "Trend_Consistency"), 
        ("Likuiditas", "Likuiditas")
    )
    cw = (iw - 28) / 2
    f_row = _font(14)
    faint = _mix(RULE, SURFACE, 0.55)
    for i, (lab, key) in enumerate(items):
        col, row = divmod(i, 4)
        cx, ry = ix + col * (cw + 28), cy + row * 28
        val, vcol = _txt(res.get(key)), TEXT
        if key == "RSI":
            n = _num(val)
            if n is not None and (n >= 70 or n <= 30):
                vcol = WARN
        max_w = cw - cv.tw(lab, f_row) - 14
        vf = _fit_font(cv, val, (16, 14, 12), True, max_w)
        cv.text(cx, ry + 12, lab, f_row, MUTED, "lm")
        cv.text(cx + cw, ry + 12, _fit(cv, val, vf, max_w), vf, vcol, "rm")
        if i not in (3, 7):
            cv.hline(cx, cx + cw, ry + 28, faint)

# ── Fungsi Utama ──
def generate_infographic_combined(res_swing, res_dt, hires=False):
    base = res_swing or res_dt or {}
    ticker = str(base.get("Saham", "N/A")).replace(".JK", "").replace("$", "").strip() or "N/A"

    # Ambil Nama PT & Chart
    pt_name, df = "Bursa Efek Indonesia", None
    if ticker != "N/A":
        t = yf.Ticker(f"{ticker}.JK")
        try:
            info = t.info or {}
            pt_name = info.get("longName") or info.get("shortName") or pt_name
        except Exception:
            pass
        try:
            df = t.history(period="1mo")
        except Exception:
            pass

    close = None
    if df is not None and not df.empty and "Close" in df:
        close = df["Close"].dropna()
        if len(close) < 2:
            close = None
    chg = (close.iloc[-1] / close.iloc[-2] - 1) * 100 if close is not None else None

    # ═══ TARIK DATA DARI DATABASE ═══
    ai_summary = "Belum ada ringkasan AI."
    flow_data = {"buy": "-", "sell": "-", "net": "-", "net_val": 0}
    broker_data = {"net_bandar": 0.0, "net_retail": 0.0}
    
    if ticker != "N/A":
        try:
            # 1. Ambil Data dari broksum_history
            broksum_data = load_broksum_history(ticker)
            if broksum_data:
                sorted_bs = sorted(broksum_data, key=lambda x: str(x.get('upload_date', '')), reverse=True)
                latest_bs = sorted_bs[0]
                ai_summary = latest_bs.get('summary_narrative', ai_summary)
                
                # Ekstrak Net Bandar & Retail dari full_data
                full_data_raw = latest_bs.get('full_data', '{}')
                try:
                    full_data = json.loads(full_data_raw) if isinstance(full_data_raw, str) else full_data_raw
                    stats = full_data.get('broker_summary_stats', {})
                    
                    b_buy = float(stats.get('buyer_bandar_pct', 0))
                    b_sell = float(stats.get('seller_bandar_pct', 0))
                    r_buy = float(stats.get('buyer_retail_pct', 0))
                    r_sell = float(stats.get('seller_retail_pct', 0))
                    
                    broker_data['net_bandar'] = b_buy - b_sell
                    broker_data['net_retail'] = r_buy - r_sell
                except Exception:
                    pass
                
            # 2. Ambil Foreign Flow dari foreign_flow_history
            f_df = load_foreign_flow_history(ticker, days=1)
            if f_df is not None and not f_df.empty:
                latest_flow = f_df.iloc[-1]
                fb = float(latest_flow.get('foreign_buy', 0))
                fs = float(latest_flow.get('foreign_sell', 0))
                net_val = fb - fs
                
                def fmt_flow(n):
                    if abs(n) >= 1e9: return f"{n/1e9:.2f} M"
                    if abs(n) >= 1e6: return f"{n/1e6:.2f} Jt"
                    return f"{n:,.0f}"
                
                flow_data["buy"] = fmt_flow(fb)
                flow_data["sell"] = fmt_flow(fs)
                flow_data["net_val"] = net_val
                flow_data["net"] = fmt_flow(net_val)

        except Exception as e:
            print(f"Gagal load DB untuk infografis: {e}")

    cv = _Canvas(W, H)

    # Header
    f_tick = _font(48, True)
    cv.text(M, 34, ticker, f_tick, TEXT, "la")
    cv.text(M, 96, _fit(cv, pt_name, _font(19), 640), _font(19), MUTED, "la")

    price_str = _txt(base.get("Harga"), "-")
    cv.text(W - M, 34, price_str if price_str.startswith("Rp") else f"Rp {price_str}", f_tick, TEXT, "ra")
    now = datetime.now(timezone(timedelta(hours=7))).strftime("%d %b %Y, %H:%M WIB")
    f_pill, f_date = _font(15, True), _font(14)
    date_x = W - M
    if chg is not None:
        col = UP if chg >= 0 else DOWN
        label = f"{chg:+.2f}%"
        pw = cv.tw(label, f_pill) + 28
        cv.rect(W - M - pw, 94, W - M, 122, fill=_mix(col, BG, 0.18), r=14)
        cv.text(W - M - pw / 2, 108, label, f_pill, col, "mm")
        date_x = W - M - pw - 14
    cv.text(date_x, 108, now, f_date, MUTED, "rm")

    # Chart
    cv.rect(M, 140, W - M, 340, fill=SURFACE, r=22)
    cv.text(M + 24, 158, "Penutupan 1 bulan terakhir", _font(14), MUTED, "la")
    if close is not None:
        cv.text(W - M - 24, 158, f"Tertinggi {_idr(close.max())}, terendah {_idr(close.min())}",
                _font(14), MUTED, "ra")
        cv.paste(_render_chart(close, W - 2 * M - 32, 148), M + 16, 184)
    else:
        cv.text(W / 2, 262, "Data chart tidak tersedia", _font(18), MUTED, "mm")

    # Kartu Kiri & Kanan
    cw = (W - 2 * M - GAP) / 2
    _card(cv, res_swing, M, CARDS_Y, cw, CARD_H, "Swing", SWING, price_str, ai_summary, flow_data, broker_data)
    _card(cv, res_dt, M + cw + GAP, CARDS_Y, cw, CARD_H, "Daytrade", DAYTRADE, price_str, ai_summary, flow_data, broker_data)

    # Footer
    cv.text(W / 2, H - 32, "Engine Trade Pro. Sinyal ini alat bantu analisis, bukan rekomendasi investasi.",
            _font(13), MUTED, "mm")

    out = cv.img
    if not hires:
        resample = Image.Resampling.LANCZOS if hasattr(Image, "Resampling") else Image.LANCZOS
        out = out.resize((W, H), resample)
    buf = io.BytesIO()
    out.save(buf, format="PNG", optimize=True)
    buf.seek(0)
    return buf
