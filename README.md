# 📚 AI Shikshak — NCERT AI Teacher

An intelligent AI-powered teacher for Indian school students (Class 1–12), built with FastAPI, Groq API, and Ollama. Supports Hindi, Hinglish, and English — and works both online and offline.

---

## ✨ Features

| Feature | Description |
|---------|-------------|
| 🧠 Conversation Memory | AI remembers previous messages within a session |
| 📎 File Upload | Send images or PDFs of textbook questions |
| ⚡ Online Mode | Powered by Groq API (llama-3.3-70b + llama-4-scout vision) |
| 📵 Offline Fallback | Automatically switches to local Ollama when internet is unavailable |
| 🌐 Multilingual | Auto-detects Hindi / Hinglish / English |
| 🔢 Instant Math | Solves arithmetic expressions directly, without calling the LLM |
| 📖 Multiplication Tables | Instant pahada for any number 1–100 |
| ⚠️ Smart Warnings | Alerts user when weak offline subjects (History, SST) may be inaccurate |
| 🛡️ Safety Filter | Blocks inappropriate content for school students |

---

## 🛠️ Tech Stack

| Component | Technology |
|-----------|------------|
| Backend | Python + FastAPI |
| Streaming | Server-Sent Events (SSE) |
| Online LLM | Groq API — `llama-3.3-70b-versatile` |
| Vision (images) | Groq — `meta-llama/llama-4-scout-17b-16e-instruct` |
| Offline LLM | Ollama — `qwen2.5:7b` |
| PDF Parsing | pypdf |
| Offline OCR | Tesseract + pytesseract |
| Environment | python-dotenv |

---

## 🚀 Getting Started

### 1. Clone the repository
```bash
git clone https://github.com/ajayJ01/ai-shikshak.git
cd ai-shikshak
```

### 2. Install Python dependencies
```bash
pip install -r requirements.txt
```

### 3. Set up your API key
```bash
cp .env.example .env
```
Open `.env` and add your Groq API key:
```
GROQ_API_KEY=gsk_your_key_here
```
Get a free key at [console.groq.com](https://console.groq.com).

### 4. (Optional) Install Tesseract for offline image OCR
| OS | Command |
|----|---------|
| Windows | Download from [UB-Mannheim/tesseract](https://github.com/UB-Mannheim/tesseract/wiki) |
| Linux | `sudo apt install tesseract-ocr tesseract-ocr-hin` |
| macOS | `brew install tesseract` |

### 5. (Optional) Install Ollama for offline fallback
```bash
# Install from https://ollama.ai, then pull the model:
ollama pull qwen2.5:7b
```

### 6. Run the server
```bash
uvicorn app:app --host 0.0.0.0 --port 8000 --reload
```
Open in browser: **http://localhost:8000**

---

## 📁 Project Structure

```
ai-shikshak/
├── app.py              # FastAPI backend — all endpoints and AI logic
├── index.html          # Frontend — single-page chat UI
├── requirements.txt    # Python dependencies
├── .env.example        # Environment variable template
├── .gitignore          # Excludes .env and cache files
└── README.md
```

---

## 🔌 API Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/` | Serves the frontend HTML |
| `POST` | `/ask` | Text chat with SSE streaming |
| `POST` | `/upload` | Image or PDF upload with SSE streaming |
| `GET` | `/health` | Server and model status |

### POST `/ask` — Request Body
```json
{
  "message": "Explain photosynthesis",
  "class_num": "7",
  "subject": "science",
  "history": [
    { "role": "user",      "content": "previous question" },
    { "role": "assistant", "content": "previous answer" }
  ]
}
```

### POST `/upload` — Form Data
```
file       → image (JPG/PNG/WEBP) or PDF, max 10MB
message    → "Solve this question"
class_num  → "10"
subject    → "maths"
```

---

## 🔄 Request Flow

```
User input
    │
    ├── Instant solver? (math expression / pahada)
    │       └── Return answer immediately — no LLM needed
    │
    ├── Try Groq API (online)
    │       ├── Image  → Groq Vision (llama-4-scout)
    │       ├── PDF    → Extract text → Groq text model
    │       └── Text   → Groq with full conversation history
    │
    └── Groq fails? → Ollama fallback (local)
            ├── Image  → Tesseract OCR → qwen2.5:7b
            ├── PDF    → pypdf extract → qwen2.5:7b
            └── Text   → Inject history as context → qwen2.5:7b
```

---

## ⚙️ Configuration

All settings are controlled via the `.env` file:

```env
GROQ_API_KEY    = gsk_...                                  # Required
GROQ_MODEL      = llama-3.3-70b-versatile                  # Text model
GROQ_VIS_MODEL  = meta-llama/llama-4-scout-17b-16e-instruct  # Vision model
OLLAMA_URL      = http://localhost:11434/api/generate      # Ollama endpoint
OLLAMA_MODEL    = qwen2.5:7b                               # Local model
```

Additional constants in `app.py`:
```python
MAX_FILE_MB       = 10    # Maximum upload size in MB
MAX_HISTORY_TURNS = 10    # Number of conversation turns to remember
```

---

## 🤝 Contributing

Pull requests are welcome. You can contribute by:
- Adding support for more subjects or classes
- Improving language detection accuracy
- Adding more facts to the offline knowledge base
- Improving the UI

---

## 📄 License

MIT License — free to use, modify, and distribute.