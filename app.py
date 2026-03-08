from fastapi import FastAPI, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel
from groq import Groq
import requests, re, json, os, base64, io

# ── Optional: PDF support
try:
    from pypdf import PdfReader
    PDF_SUPPORT = True
except ImportError:
    PDF_SUPPORT = False
    print("⚠ pypdf not found — PDF disabled. Run: pip install pypdf")

# ── Optional: OCR support
try:
    from PIL import Image
    import pytesseract
    # Windows path — Linux pe comment out karo
    if os.path.exists(r"C:\Program Files\Tesseract-OCR\tesseract.exe"):
        pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    OCR_SUPPORT = True
except ImportError:
    OCR_SUPPORT = False
    print("⚠ pytesseract/PIL not found — offline OCR disabled. Run: pip install pytesseract pillow")

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ─── CONFIG (.env se load hoga) ───────────────────────────
from dotenv import load_dotenv
load_dotenv()

GROQ_API_KEY   = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL     = os.getenv("GROQ_MODEL",     "llama-3.3-70b-versatile")
GROQ_VIS_MODEL = os.getenv("GROQ_VIS_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct")
OLLAMA_URL     = os.getenv("OLLAMA_URL",     "http://localhost:11434/api/generate")
OLLAMA_MODEL   = os.getenv("OLLAMA_MODEL",   "qwen2.5:7b")

if not GROQ_API_KEY:
    print("❌ ERROR: GROQ_API_KEY missing! .env file mein set karo.")
    print("   Copy karo: cp .env.example .env  phir apni key daalo")

MAX_FILE_MB       = 10
ALLOWED_IMG_EXTS  = {"jpg","jpeg","png","webp","gif"}
ALLOWED_IMG_TYPES = {"image/jpeg","image/png","image/webp","image/gif","image/jpg"}

client = Groq(api_key=GROQ_API_KEY)

WEAK_OFFLINE_SUBJECTS = {"sst","history","geography","economics","accounts","business"}

# ─── SAFETY ───────────────────────────────────────────────
BLOCKED = [
    r"\bsex\b", r"\bporn\b", r"\bnude\b", r"\bweapon\b",
    r"\bdrugs\b", r"\bgambling\b", r"\bkill\b", r"\bmurder\b",
    r"\bहिंसा\b", r"\bअश्लील\b", r"\bnasha\b",
]
def is_safe(text: str) -> bool:
    if not text:
        return True
    return not any(re.search(p, text.lower()) for p in BLOCKED)

# ─── LANGUAGE ─────────────────────────────────────────────
HINGLISH_WORDS = {
    "kya","kaise","kyun","hai","hota","hoti","hoga","matlab","karo","likho",
    "batao","btao","kaun","kitna","kab","kahan","aur","mujhe","toh","kuch",
    "nahi","chahiye","naam","ke","ka","ki","mein","se","ko","samjhao","bata",
    "chapter","padhao","explain","solve","wala","wali","yeh","woh","pura",
    "accha","theek","concept","kaa","me","samajh","padh","likha","ye","wo",
    "iska","uska","konsa","kitne","kaunsa","de","do","dedo","yrr","yaar",
    "bhai","sirf","bas","abhi","jaldi","thoda","bohot","bahut","chal","chalo",
    "suno","dekho","pta","pata","lgta","lagta",
}
def detect_language(text: str) -> str:
    if re.search(r"[\u0900-\u097F]", text): return "hindi"
    words = set(re.findall(r"[a-zA-Z]+", text.lower()))
    return "hinglish" if words & HINGLISH_WORDS else "english"

# ─── SUBJECT MAP ──────────────────────────────────────────
SUBJECT_MAP = {
    "maths":"maths","math":"maths","ganit":"maths","ganith":"maths","गणित":"maths",
    "science":"science","vigyan":"science","विज्ञान":"science",
    "hindi":"hindi","हिंदी":"hindi",
    "english":"english","angrezi":"english",
    "sst":"sst","social":"sst","history":"sst","geography":"sst","itihas":"sst","bhugol":"sst",
    "sanskrit":"sanskrit","computer":"computer",
    "physics":"physics","chemistry":"chemistry","biology":"biology",
    "economics":"economics","accounts":"accounts","business":"business",
}

def parse_query(text: str) -> dict:
    lower = text.lower()
    result = {
        "class_num": None, "subject": None, "chapter": None,
        "language": detect_language(text), "intent": "explain",
    }
    cm = re.search(r"(?:class|kaksha|कक्षा|std)\s*(\d{1,2})|(\d{1,2})(?:st|nd|rd|th)?\s*(?:class|kaksha)", lower)
    if cm: result["class_num"] = cm.group(1) or cm.group(2)
    for kw, subj in SUBJECT_MAP.items():
        if kw in lower: result["subject"] = subj; break
    ch = re.search(r"(?:chapter|ch|adhyay|अध्याय)\s*(\d{1,2})", lower)
    if ch: result["chapter"] = ch.group(1)
    if any(w in lower for w in ["solve","calculate","hisab","hal karo","हल","equal","barabar"]):
        result["intent"] = "solve"
    elif any(w in lower for w in ["test","quiz","mock","practice","mcq","exam"]):
        result["intent"] = "test"
    elif any(w in lower for w in ["list","naam","name","kitne","kaun se","total","sare","saare"]):
        result["intent"] = "list"
    elif any(w in lower for w in ["homework","hw","assignment"]):
        result["intent"] = "homework"
    return result

# ─── INSTANT SOLVERS ──────────────────────────────────────
def solve_math_instant(text: str):
    cleaned = re.sub(r"[?？]", "", text)
    cleaned = re.sub(r"is\s+equal\s+to|kitna\s+hai|barabar\s+hai", "", cleaned, flags=re.IGNORECASE)
    m = re.search(r"([\d\s\+\-\*/\^\(\)\.]+)", cleaned)
    if m:
        raw = m.group(1).strip()
        if len(raw) >= 3 and re.search(r"[\+\-\*/\^]", raw):
            try:
                result = eval(raw.replace("^","**").replace(" ",""), {"__builtins__":{}})
                if isinstance(result, (int, float)):
                    if isinstance(result, float) and result == int(result): result = int(result)
                    return f"{raw.strip()} = {result}"
            except: pass
    return None

def get_pahada(text: str):
    lower = text.lower()
    if not any(w in lower for w in ["pahada","table","पहाड़ा","paada","pada"]): return None
    m = re.search(r"\b(\d+)\b", text)
    if m:
        n = int(m.group(1))
        if 1 <= n <= 100:
            return "\n".join([f"{n} × {i} = {n*i}" for i in range(1, 11)])
    return None

# ─── FILE VALIDATION ──────────────────────────────────────
def validate_file(filename: str, content_type: str, size_bytes: int):
    """Returns (True, "image"|"pdf") or (False, error_message)"""
    if size_bytes == 0:
        return False, "File empty hai. Dobara try karo."
    if size_bytes > MAX_FILE_MB * 1024 * 1024:
        return False, f"File bahut badi hai! Maximum {MAX_FILE_MB}MB allowed hai."
    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    ct  = (content_type or "").lower()
    if ct in ALLOWED_IMG_TYPES or ext in ALLOWED_IMG_EXTS:
        return True, "image"
    elif ct == "application/pdf" or ext == "pdf":
        if not PDF_SUPPORT:
            return False, "PDF support install nahi hai. Server pe 'pip install pypdf' run karo."
        return True, "pdf"
    else:
        return False, f"Sirf Image (JPG/PNG/WEBP) ya PDF allowed hai. '{ext}' format supported nahi."

def extract_pdf_text(file_bytes: bytes):
    """Returns (text, error_str). error_str is empty on success."""
    if not PDF_SUPPORT: return "", "pypdf install nahi hai."
    try:
        reader = PdfReader(io.BytesIO(file_bytes))
        if len(reader.pages) > 20:
            return "", "PDF mein 20 se zyada pages hain. Chhoti PDF upload karo (max 20 pages)."
        text = ""
        for page in reader.pages:
            t = page.extract_text() or ""
            t = re.sub(r"[\u200b-\u200f\u00ad\u200c\u200d\ufeff]", "", t)
            text += t + "\n"
        text = text.strip()
        if not text:
            return "", "PDF se text nahi mila. Scanned image-based PDF hai — image ke roop mein upload karo."
        return text[:4500], ""
    except Exception as e:
        return "", f"PDF read error: {str(e)[:120]}"

def extract_image_ocr(file_bytes: bytes):
    """Returns (text, error_str). error_str is empty on success."""
    if not OCR_SUPPORT:
        return "", "Offline OCR available nahi — Tesseract install nahi hai. (pip install pytesseract pillow)"
    try:
        img = Image.open(io.BytesIO(file_bytes)).convert("RGB")
        # Try Hindi+English first, fallback to English only
        try:
            text = pytesseract.image_to_string(img, lang="hin+eng")
        except:
            text = pytesseract.image_to_string(img, lang="eng")
        text = text.strip()
        if not text or len(text) < 10:
            return "", "Image se text nahi mila. Clear aur high-resolution photo upload karo."
        return text[:3500], ""
    except Exception as e:
        return "", f"OCR error: {str(e)[:120]}"

# ─── SYSTEM PROMPT ────────────────────────────────────────
def build_system_prompt(qi: dict, offline: bool = False, msg: str = "") -> str:
    lang    = qi.get("language", "hinglish")
    intent  = qi.get("intent", "explain")
    cls     = qi.get("class_num") or "school"
    subject = qi.get("subject") or "general"
    chapter = qi.get("chapter")

    FACTS_DB = {
        "swatantrata bharat azaadi independence 1947":
            "VERIFIED: Bharat 15 AUGUST 1947 ko azaad hua. Leaders: Gandhi, Nehru, Bose, Bhagat Singh. Constitution: 26 Jan 1950.",
        "photosynthesis prakaash sansleshan":
            "VERIFIED: 6CO2+6H2O+sunlight→C6H12O6+6O2. Chloroplast mein hota hai. Chlorophyll = green pigment.",
        "asman neela sky blue":
            "VERIFIED: Rayleigh scattering. Neela rang sabse zyada scatter hota hai isliye aasman neela dikhta hai.",
        "pythagoras pithagoras":
            "VERIFIED: a²+b²=c². Right angle triangle mein karn² = aadhar² + lambai².",
        "newton":
            "VERIFIED: Newton ke 3 niyam: 1)Jadatva niyam 2)F=ma 3)Kriya=Pratikriya.",
    }
    fact_ctx = ""
    for keys, fact in FACTS_DB.items():
        if any(k in msg.lower() for k in keys.split()):
            fact_ctx = f"\n\nVERIFIED FACTS (inhe zaroor use karo, contradict mat karo):\n{fact}"
            break

    if offline:
        base = {
            "hindi":    f"Tu Class {cls} {subject} ka Indian school teacher hai.\nRULES: Sirf Hindi mein jawab do. Seedha topic se shuru karo — koi greeting nahi. Clarification mat maango, seedha samjhao. Accurate facts do. Pura jawab do. Max 200 words.",
            "hinglish": f"Tu Class {cls} {subject} ka Indian school teacher hai.\nRULES: Sirf Hinglish (Roman script) mein jawab do — Devanagari mat use karo. Seedha topic se shuru — koi greeting nahi. Seedha samjhao. Accurate facts. Pura jawab. Max 200 words.",
            "english":  f"You are a Class {cls} {subject} Indian school teacher.\nRULES: Answer in simple English only. Start directly with the answer — no greetings. Give accurate facts. Complete the full answer. Max 200 words.",
        }
        return base.get(lang, base["hinglish"]) + fact_ctx

    # Online — full prompt
    ch_hint = f"Chapter {chapter}" if chapter else ""

    lang_rules = {
        "hindi":    "हमेशा शुद्ध, सरल हिंदी में। Scientific terms English में रख सकते हो।",
        "hinglish": "Hamesha Hinglish (Roman Hindi) mein. Devanagari mat likho. Friendly casual tone.",
        "english":  "Always simple clear English. Short sentences. School-level vocabulary.",
    }
    style_map = {
        "solve":    "Step-by-step solution: Step 1, Step 2... Working dikhao. Final Answer bold karo. Formula use hua toh explain karo.",
        "test":     "5 practice questions do (MCQ + short answer mix). Answers end mein alag section mein.",
        "list":     "Clean numbered list. Har point crisp aur short. Max 10 items. Important terms bold.",
        "homework": "Har question ka direct answer do with brief 1-line explanation. Clear aur to-the-point.",
        "explain":  "1) Simple 1-2 line definition  2) Real Indian life example  3) Key points numbered  4) 1-line summary",
    }
    return f"""Tu ek experienced Indian school teacher hai.
Class: {cls} | Subject: {subject} | {ch_hint}

Language: {lang_rules.get(lang, lang_rules['hinglish'])}

Style: {style_map.get(intent, style_map['explain'])}

STRICT Rules:
- PEHLI LINE seedha topic se shuru — koi "Main bataunga", "Sure!", "Great question!", "Bilkul!" BILKUL NAHI
- No intro sentences — directly answer karo
- Accurate information — galat facts NAHI
- Class {cls} level ki appropriate language
- Student ko naturally encourage karo — forced nahi"""

# ─── SSE HELPERS ──────────────────────────────────────────
def sse(obj): return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"

def warn_message(subj, lang, reason):
    if subj not in WEAK_OFFLINE_SUBJECTS: return ""
    msgs = {
        "offline": {
            "hindi":    "\n\n⚠️ **नोट:** इंटरनेट नहीं है — इस विषय में गलत तथ्य आ सकते हैं। इंटरनेट से कनेक्ट करें।",
            "hinglish": "\n\n⚠️ **Note:** Internet nahi hai — is subject mein galat facts aa sakte hain. Internet connect karo.",
            "english":  "\n\n⚠️ **Note:** No internet — facts in this subject may be inaccurate. Please connect to internet.",
        },
        "technical": {
            "hindi":    "\n\n⚠️ **नोट:** AI सेवा में तकनीकी समस्या है — इस विषय के तथ्य verify करें।",
            "hinglish": "\n\n⚠️ **Note:** AI service mein technical problem hai — is subject ke facts verify karo.",
            "english":  "\n\n⚠️ **Note:** AI service has a technical issue — please verify facts for this subject.",
        }
    }
    return msgs.get(reason, msgs["technical"]).get(lang, msgs[reason]["hinglish"])

def groq_fail_reason(err_str: str) -> str:
    err_lower = err_str.lower()
    if any(w in err_lower for w in ["connection","network","timeout","resolve","unreachable"]):
        return "offline"
    return "technical"

# ─── FALLBACK STREAM (Ollama) ─────────────────────────────
def ollama_stream(system_prompt, prompt, parsed_info, subj, lang, fail_reason):
    """Yields SSE events from Ollama with optional warning at end."""
    try:
        r = requests.post(
            OLLAMA_URL,
            json={
                "model": OLLAMA_MODEL, "system": system_prompt, "prompt": prompt,
                "stream": True,
                "options": {"num_predict":900,"temperature":0.1,"num_ctx":2048,"num_thread":6}
            },
            stream=True, timeout=180
        )
        for line in r.iter_lines():
            if line:
                chunk = json.loads(line.decode("utf-8"))
                token = chunk.get("response","")
                done  = chunk.get("done", False)
                if token: yield sse({"type":"token","token":token,"done":False})
                if done:
                    warning = warn_message(subj, lang, fail_reason)
                    if warning: yield sse({"type":"token","token":warning,"done":False})
                    yield sse({"type":"token","token":"","done":True})
                    break
    except Exception as e:
        msg = "Local AI bhi available nahi hai. Internet check karo aur Ollama chal raha hai check karo."
        yield sse({"type":"token","token":msg,"done":False})
        yield sse({"type":"token","token":"","done":True})

# ─── /upload ENDPOINT ─────────────────────────────────────
@app.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    message: str = Form(default=""),
    class_num: str = Form(default=""),
    subject: str = Form(default=""),
):
    # 1. Read file bytes
    try:
        file_bytes = await file.read()
    except Exception as e:
        def err():
            yield sse({"type":"error","message":f"File read error: {str(e)[:100]}"})
        return StreamingResponse(err(), media_type="text/event-stream")

    # 2. Validate file
    is_valid, file_type_or_err = validate_file(
        file.filename or "unknown",
        file.content_type or "",
        len(file_bytes)
    )
    if not is_valid:
        def err():
            yield sse({"type":"error","message": file_type_or_err})
        return StreamingResponse(err(), media_type="text/event-stream")

    file_type = file_type_or_err  # "image" or "pdf"

    # 3. Validate user question
    user_q = message.strip() or "Is file mein kya likha hai? Explain karo."
    if not is_safe(user_q):
        def err():
            yield sse({"type":"error","message":"Yeh topic school ke liye allowed nahi hai."})
        return StreamingResponse(err(), media_type="text/event-stream")

    # 4. Parse query context
    qi = parse_query(user_q)
    if class_num: qi["class_num"] = class_num
    if subject and subject != "auto": qi["subject"] = subject
    subj = qi.get("subject","") or ""
    lang = qi.get("language","hinglish")

    base_parsed = {
        "class": qi["class_num"], "subject": qi["subject"],
        "chapter": qi["chapter"], "intent": qi["intent"],
        "language": lang, "source":"groq", "file_type": file_type,
    }

    def stream():
        failed = False; fail_rsn = "technical"

        # ── Try Groq (Vision for image, Text for PDF)
        try:
            sys_prompt = build_system_prompt(qi, offline=False)

            if file_type == "image":
                # Groq Vision API
                b64    = base64.b64encode(file_bytes).decode("utf-8")
                media  = file.content_type or "image/jpeg"
                # Normalize media type
                if media not in ALLOWED_IMG_TYPES: media = "image/jpeg"
                msgs = [
                    {"role":"system","content": sys_prompt},
                    {"role":"user","content":[
                        {"type":"image_url","image_url":{"url":f"data:{media};base64,{b64}"}},
                        {"type":"text","text": user_q}
                    ]}
                ]
                stream_obj = client.chat.completions.create(
                    model=GROQ_VIS_MODEL, messages=msgs,
                    stream=True, max_tokens=1200, temperature=0.2,
                )
            else:
                # PDF — extract text, use text model
                pdf_text, pdf_err = extract_pdf_text(file_bytes)
                if pdf_err:
                    yield sse({"type":"error","message": pdf_err})
                    return
                combined = f"[PDF ka content]:\n{pdf_text}\n\n[Student ka sawaal]: {user_q}"
                msgs = [
                    {"role":"system","content": sys_prompt},
                    {"role":"user","content": combined}
                ]
                stream_obj = client.chat.completions.create(
                    model=GROQ_MODEL, messages=msgs,
                    stream=True, max_tokens=1400, temperature=0.2,
                )

            yield sse({"type":"meta","parsed": base_parsed,"sources":[]})
            for chunk in stream_obj:
                token = chunk.choices[0].delta.content or ""
                done  = chunk.choices[0].finish_reason is not None
                if token: yield sse({"type":"token","token":token,"done":False})
                if done:
                    yield sse({"type":"token","token":"","done":True})
                    break

        except Exception as e:
            err_str = str(e)
            print(f"⚠ Groq upload failed: {err_str}")
            failed  = True
            fail_rsn = groq_fail_reason(err_str)

        # ── Fallback to Ollama
        if failed:
            off_parsed = {**base_parsed, "source":"offline_mode", "groq_fail_reason": fail_rsn}
            yield sse({"type":"meta","parsed": off_parsed,"sources":[]})

            # Extract text locally
            if file_type == "image":
                local_text, local_err = extract_image_ocr(file_bytes)
            else:
                local_text, local_err = extract_pdf_text(file_bytes)

            if local_err:
                yield sse({"type":"token","token":f"File process nahi ho saki: {local_err}","done":False})
                yield sse({"type":"token","token":"","done":True})
                return

            off_prompt  = build_system_prompt(qi, offline=True, msg=user_q)
            combined_q  = f"[File content]:\n{local_text}\n\nSawaal: {user_q}"
            yield from ollama_stream(off_prompt, combined_q, off_parsed, subj, lang, fail_rsn)

    return StreamingResponse(stream(), media_type="text/event-stream")

# ─── /ask ENDPOINT ────────────────────────────────────────
# History item format: {"role": "user"|"assistant", "content": "..."}
class Question(BaseModel):
    message:  str
    class_num: str = ""
    subject:   str = ""
    history:   list = []   # conversation history from frontend

# Max turns to send to LLM (older messages trimmed to save tokens)
MAX_HISTORY_TURNS = 10   # 10 pairs = 20 messages max

def build_messages(system_prompt: str, history: list, current_msg: str) -> list:
    """
    Build full messages list for Groq:
    [system] + last N history turns + [current user msg]
    Each history item: {"role":"user"|"assistant","content":"..."}
    """
    msgs = [{"role": "system", "content": system_prompt}]

    # Trim to last MAX_HISTORY_TURNS pairs (oldest dropped first)
    trimmed = history[-(MAX_HISTORY_TURNS * 2):]
    for h in trimmed:
        role = h.get("role","")
        content = h.get("content","")
        if role in ("user","assistant") and content:
            msgs.append({"role": role, "content": str(content)[:2000]})  # cap each msg to 2000 chars

    msgs.append({"role": "user", "content": current_msg})
    return msgs

def build_ollama_context(history: list, current_msg: str) -> str:
    """
    Ollama /api/generate doesn't support messages array —
    so we inject recent history as plain text context in the prompt.
    Keep it short (last 4 turns only) to stay within num_ctx.
    """
    recent = history[-(4 * 2):]  # last 4 pairs
    if not recent:
        return current_msg

    lines = ["[Pichli baat-cheet (context ke liye):"]
    for h in recent:
        role = h.get("role","")
        content = str(h.get("content",""))[:600]  # short trim
        if role == "user":
            lines.append(f"Student: {content}")
        elif role == "assistant":
            lines.append(f"Teacher: {content}")
    lines.append("]\n")
    lines.append(f"[Abka sawaal]: {current_msg}")
    return "\n".join(lines)

@app.post("/ask")
def ask(q: Question):
    msg = q.message.strip()
    if not msg:
        def e(): yield sse({"type":"error","message":"Kuch poochho toh sahi!"})
        return StreamingResponse(e(), media_type="text/event-stream")
    if not is_safe(msg):
        def e(): yield sse({"type":"error","message":"Yeh topic school ke liye allowed nahi hai."})
        return StreamingResponse(e(), media_type="text/event-stream")

    # Instant: pahada (no history needed)
    pahada = get_pahada(msg)
    if pahada:
        def ps():
            yield sse({"type":"meta","parsed":{"intent":"pahada"},"sources":[]})
            for line in pahada.split("\n"):
                yield sse({"type":"token","token":line+"\n","done":False})
            yield sse({"type":"token","token":"","done":True})
        return StreamingResponse(ps(), media_type="text/event-stream")

    # Instant: math (no history needed)
    math_ans = solve_math_instant(msg)
    if math_ans:
        def ms():
            yield sse({"type":"meta","parsed":{"intent":"math"},"sources":[]})
            yield sse({"type":"token","token":math_ans,"done":False})
            yield sse({"type":"token","token":"","done":True})
        return StreamingResponse(ms(), media_type="text/event-stream")

    # Parse
    qi = parse_query(msg)
    if q.class_num: qi["class_num"] = q.class_num
    if q.subject and q.subject != "auto": qi["subject"] = q.subject
    subj = qi.get("subject","") or ""
    lang = qi.get("language","hinglish")

    # Build prompts
    online_prompt  = build_system_prompt(qi, offline=False)
    offline_prompt = build_system_prompt(qi, offline=True, msg=msg)
    parsed_info = {
        "class":qi["class_num"],"subject":qi["subject"],"chapter":qi["chapter"],
        "intent":qi["intent"],"language":lang,"source":"groq"
    }

    # History from frontend
    history = q.history or []

    def stream_response():
        failed = False; fail_rsn = "technical"
        try:
            # Build messages WITH history
            messages = build_messages(online_prompt, history, msg)
            stream_obj = client.chat.completions.create(
                model=GROQ_MODEL,
                messages=messages,
                stream=True, max_tokens=1200, temperature=0.2,
            )
            yield sse({"type":"meta","parsed":parsed_info,"sources":[]})
            for chunk in stream_obj:
                token = chunk.choices[0].delta.content or ""
                done  = chunk.choices[0].finish_reason is not None
                if token: yield sse({"type":"token","token":token,"done":False})
                if done:
                    yield sse({"type":"token","token":"","done":True})
                    break
        except Exception as e:
            err_str = str(e)
            print(f"⚠ Groq failed: {err_str}")
            failed  = True
            fail_rsn = groq_fail_reason(err_str)

        if failed:
            off_parsed = {**parsed_info,"source":"offline_mode","groq_fail_reason":fail_rsn}
            yield sse({"type":"meta","parsed":off_parsed,"sources":[]})
            # Ollama: inject history as text context
            ollama_prompt = build_ollama_context(history, msg)
            yield from ollama_stream(offline_prompt, ollama_prompt, off_parsed, subj, lang, fail_rsn)

    return StreamingResponse(stream_response(), media_type="text/event-stream")

# ─── ROOT ─────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
def home():
    with open("index.html", "r", encoding="utf8") as f:
        return f.read()

@app.get("/health")
def health():
    return {
        "status":      "AI Shikshak running",
        "primary":     GROQ_MODEL,
        "vision":      GROQ_VIS_MODEL,
        "fallback":    OLLAMA_MODEL,
        "pdf_support": PDF_SUPPORT,
        "ocr_support": OCR_SUPPORT,
    }
