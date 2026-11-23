# 📊 IDX Analyzer

Tool analisis saham IDX dengan pendekatan VSA + Bandarmology + AI Vision.

## ✨ Fitur
- Backtest engine
- VSA (Volume Spread Analysis)
- Bandarmology detection
- AI Analysis (Gemini Vision)

## 📁 Struktur

```
.
├── config/
├── core/
├── prompts/
├── services/
├── state/
├── tests/
├── ui/
├── bridge_server.py
├── main.py
└── requirements.txt
```

## ⚙️ Instalasi

```bash
git clone <repo>
cd <repo>
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## ▶️ Menjalankan

```bash
python main.py
# atau untuk UI
streamlit run ui/app.py
```

## 🧪 Testing

```bash
pytest tests/
```
