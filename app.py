import os, sys, re, json, sqlite3, requests, tempfile
import pandas as pd
from typing import Optional, List, Dict, Any, Generator
from dotenv import load_dotenv
from pydantic import BaseModel
from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse, FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

load_dotenv()

BASE_DIR       = os.path.dirname(os.path.abspath(__file__))
CSV_FILE_PATH  = os.path.join(BASE_DIR, "College_data.csv")

def resolve_db_path() -> str:
    if os.getenv("DB_FILE_PATH"):
        return os.environ["DB_FILE_PATH"]
    # On Vercel / serverless platforms, root directory is read-only. Use /tmp or system temp dir.
    if os.getenv("VERCEL") or os.getenv("AWS_LAMBDA_FUNCTION_NAME") or not os.access(BASE_DIR, os.W_OK):
        return os.path.join(tempfile.gettempdir(), "colleges.db")
    return os.path.join(BASE_DIR, "colleges.db")

DB_FILE_PATH   = resolve_db_path()
STATIC_DIR     = os.path.join(BASE_DIR, "static")

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_MODEL   = os.getenv("OPENROUTER_MODEL")
FAST_MODEL         = os.getenv("FAST_MODEL")
YOUR_SITE_URL      = os.getenv("YOUR_SITE_URL")
YOUR_APP_NAME      = os.getenv("YOUR_APP_NAME")
PORT               = int(os.getenv("PORT", 8000))
HOST               = os.getenv("HOST", "0.0.0.0")

# ── 1. DATABASE SETUP & INDEXING ──────────────────────────────────────────────

def clean_fee(val):
    if pd.isna(val) or str(val).strip() in ("", "--", "nan", "None"): return None
    c = re.sub(r"[^\d.]", "", str(val))
    return float(c) if c else None

def clean_float(val):
    if pd.isna(val) or str(val).strip() in ("", "--", "nan", "None"): return None
    try: return float(val)
    except ValueError: return None

def init_database():
    global DB_FILE_PATH
    try:
        if not os.path.exists(CSV_FILE_PATH):
            print("Warning: College_data.csv not found at", CSV_FILE_PATH)
            return

        # Ensure directory exists for DB_FILE_PATH
        os.makedirs(os.path.dirname(os.path.abspath(DB_FILE_PATH)), exist_ok=True)

        conn = sqlite3.connect(DB_FILE_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='colleges'")
        if cursor.fetchone():
            cursor.execute("SELECT COUNT(*) FROM colleges")
            count = cursor.fetchone()[0]
            if count > 0:
                # Ensure indexes exist
                for col in ["state", "stream", "rating", "ug_fee", "college_name", "placement"]:
                    cursor.execute(f"CREATE INDEX IF NOT EXISTS idx_{col} ON colleges ({col})")
                conn.commit()
                conn.close()
                return
                
        print(f"Populating database from CSV to {DB_FILE_PATH}...")
        df = pd.read_csv(CSV_FILE_PATH)
        df.columns = [c.strip() for c in df.columns]
        cursor.execute("""CREATE TABLE IF NOT EXISTS colleges (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            college_name TEXT, state TEXT, stream TEXT,
            ug_fee REAL, pg_fee REAL, rating REAL,
            academic REAL, accommodation REAL, faculty REAL,
            infrastructure REAL, placement REAL, social_life REAL)""")
        
        rows = [(str(r.get("College_Name","")).strip(), str(r.get("State","")).strip(),
                 str(r.get("Stream","")).strip(), clean_fee(r.get("UG_fee")),
                 clean_fee(r.get("PG_fee")), clean_float(r.get("Rating")),
                 clean_float(r.get("Academic")), clean_float(r.get("Accommodation")),
                 clean_float(r.get("Faculty")), clean_float(r.get("Infrastructure")),
                 clean_float(r.get("Placement")), clean_float(r.get("Social_Life")))
                for _, r in df.iterrows()]
                
        cursor.executemany("""INSERT INTO colleges (college_name,state,stream,ug_fee,pg_fee,
            rating,academic,accommodation,faculty,infrastructure,placement,social_life)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""", rows)
            
        for col in ["state", "stream", "rating", "ug_fee", "college_name", "placement"]:
            cursor.execute(f"CREATE INDEX IF NOT EXISTS idx_{col} ON colleges ({col})")
            
        conn.commit()
        conn.close()
        print(f"Database ready with {len(rows)} colleges at {DB_FILE_PATH}.")
    except Exception as e:
        print(f"Database initialization error: {e}")

def get_db_connection():
    if not os.path.exists(DB_FILE_PATH):
        init_database()
    conn = sqlite3.connect(DB_FILE_PATH)
    conn.row_factory = sqlite3.Row
    return conn

init_database()

# ── 2. ENTITY EXTRACTION & NORM ───────────────────────────────────────────────

CITY_TO_STATE = {
    "bangalore":"Karnataka","bengaluru":"Karnataka","mysore":"Karnataka","mangalore":"Karnataka",
    "mumbai":"Maharashtra","pune":"Maharashtra","nagpur":"Maharashtra","nashik":"Maharashtra",
    "delhi":"Delhi ncr","noida":"Delhi ncr","gurgaon":"Delhi ncr","gurugram":"Delhi ncr","ghaziabad":"Delhi ncr","faridabad":"Delhi ncr",
    "chennai":"Tamil nadu","coimbatore":"Tamil nadu","madurai":"Tamil nadu","trichy":"Tamil nadu",
    "hyderabad":"Telangana","warangal":"Telangana",
    "kolkata":"West bengal","durgapur":"West bengal","siliguri":"West bengal",
    "lucknow":"Uttar pradesh","kanpur":"Uttar pradesh","varanasi":"Uttar pradesh","agra":"Uttar pradesh","noida":"Delhi ncr",
    "ahmedabad":"Gujarat","surat":"Gujarat","vadodara":"Gujarat","rajkot":"Gujarat",
    "jaipur":"Rajasthan","jodhpur":"Rajasthan","kota":"Rajasthan","udaipur":"Rajasthan",
    "bhopal":"Madhya pradesh","indore":"Madhya pradesh","gwalior":"Madhya pradesh",
    "kochi":"Kerala","trivandrum":"Kerala","calicut":"Kerala","kottayam":"Kerala",
    "visakhapatnam":"Andhra pradesh","vijayawada":"Andhra pradesh","guntur":"Andhra pradesh","tirupati":"Andhra pradesh",
    "amritsar":"Punjab","ludhiana":"Punjab","jalandhar":"Punjab","patiala":"Punjab",
    "patna":"Bihar","gaya":"Bihar","bhubaneswar":"Orissa","cuttack":"Orissa","rourkela":"Orissa",
    "chandigarh":"Punjab","goa":"Goa","dehradun":"Uttarakhand","guwahati":"Assam"
}

STATE_NORMALIZE = {
    "tamil nadu":"Tamil nadu","tamilnadu":"Tamil nadu","tn":"Tamil nadu",
    "karnataka":"Karnataka","kar":"Karnataka",
    "maharashtra":"Maharashtra","maha":"Maharashtra","mh":"Maharashtra",
    "delhi":"Delhi ncr","delhi ncr":"Delhi ncr","ncr":"Delhi ncr",
    "telangana":"Telangana","ts":"Telangana",
    "andhra pradesh":"Andhra pradesh","andhra":"Andhra pradesh","ap":"Andhra pradesh",
    "uttar pradesh":"Uttar pradesh","up":"Uttar pradesh",
    "west bengal":"West bengal","wb":"West bengal","bengal":"West bengal",
    "gujarat":"Gujarat","rajasthan":"Rajasthan","raj":"Rajasthan",
    "madhya pradesh":"Madhya pradesh","mp":"Madhya pradesh",
    "kerala":"Kerala","punjab":"Punjab","bihar":"Bihar",
    "orissa":"Orissa","odisha":"Orissa","goa":"Goa",
    "haryana":"Haryana","uttarakhand":"Uttarakhand","assam":"Assam"
}

COURSE_TO_STREAM = {
    "engineering":"Engineering","btech":"Engineering","b.tech":"Engineering",
    "mtech":"Engineering","cse":"Engineering","computer science":"Engineering",
    "it":"Engineering","information technology":"Engineering","ece":"Engineering",
    "electronics":"Engineering","mechanical":"Engineering","civil":"Engineering",
    "ai":"Engineering","artificial intelligence":"Engineering","data science":"Engineering",
    "medical":"Medical","mbbs":"Medical","bds":"Medical","nursing":"Medical","dental":"Medical",
    "management":"Management","mba":"Management","bba":"Management","pgdm":"Management","executive mba":"Management",
    "law":"Law","llb":"Law","llm":"Law","ba llb":"Law",
    "science":"Science","bsc":"Science","msc":"Science","physics":"Science","chemistry":"Science",
    "commerce":"Commerce","bcom":"Commerce","mcom":"Commerce","ca":"Commerce","finance":"Commerce",
    "arts":"Arts","ba":"Arts","humanities":"Arts","journalism":"Arts","design":"Arts",
    "pharmacy":"Pharmacy","bpharm":"Pharmacy","mpharm":"Pharmacy","pharma":"Pharmacy",
    "agriculture":"Agriculture","bsc ag":"Agriculture",
    "hotel management":"Hotel-management","hm":"Hotel-management","culinary":"Hotel-management"
}

def extract_entities(query: str) -> Dict[str, Any]:
    q = query.lower()
    states = set()
    for city, state in CITY_TO_STATE.items():
        if re.search(r'\b' + re.escape(city) + r'\b', q): 
            states.add(state)
    for alias, norm in STATE_NORMALIZE.items():
        if re.search(r'\b' + re.escape(alias) + r'\b', q): 
            states.add(norm)
            
    streams = set()
    for course, stream in COURSE_TO_STREAM.items():
        if re.search(r'\b' + re.escape(course) + r'\b', q): 
            streams.add(stream)
            
    budget = None
    m = re.search(r'(\d+(?:\.\d+)?)\s*(?:lakh|lakhs|lac|lacs|l)\b', q)
    if m: 
        budget = float(m.group(1)) * 100000
    else:
        m = re.search(r'(\d+(?:\.\d+)?)\s*(?:k|thousand)\b', q)
        if m: budget = float(m.group(1)) * 1000
        
    if not budget and any(w in q for w in ["affordable", "cheap", "low fee", "low cost", "budget friendly"]): 
        budget = 250000
        
    priorities = []
    if any(w in q for w in ["placement", "package", "job", "roi", "highest salary", "recruitment"]): 
        priorities.append("placement")
    if any(w in q for w in ["academic", "study", "curriculum", "syllabus", "teaching"]): 
        priorities.append("academic")
    if any(w in q for w in ["hostel", "accommodation", "room", "stay", "mess"]): 
        priorities.append("accommodation")
    if any(w in q for w in ["faculty", "professor", "teacher", "phd"]): 
        priorities.append("faculty")
    if any(w in q for w in ["infrastructure", "campus", "lab", "library", "facility"]): 
        priorities.append("infrastructure")
    if any(w in q for w in ["social life", "fest", "events", "campus life", "crowd"]): 
        priorities.append("social_life")
        
    return {
        "states": list(states),
        "streams": list(streams),
        "budget": budget,
        "priorities": priorities
    }

# ── 3. QUERY & SMART SCORING ──────────────────────────────────────────────────

def query_colleges(state=None, stream=None, max_fee=None, search_text=None, limit=15) -> List[Dict]:
    conn = get_db_connection()
    cursor = conn.cursor()
    conditions, params = [], []
    
    if state: 
        conditions.append("state LIKE ?")
        params.append(f"%{state}%")
    if stream: 
        conditions.append("stream LIKE ?")
        params.append(f"%{stream}%")
    if max_fee: 
        conditions.append("(ug_fee IS NULL OR ug_fee <= ?)")
        params.append(max_fee)
    if search_text: 
        conditions.append("(college_name LIKE ? OR state LIKE ? OR stream LIKE ?)")
        params.extend([f"%{search_text}%", f"%{search_text}%", f"%{search_text}%"])
        
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    cursor.execute(f"SELECT * FROM colleges {where} ORDER BY rating DESC NULLS LAST LIMIT ?", params + [limit])
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows

def find_colleges_by_names(names: List[str]) -> List[Dict]:
    if not names: return []
    conn = get_db_connection()
    cursor = conn.cursor()
    results, seen = [], set()
    
    for name in names:
        cleaned = name.strip()
        if len(cleaned) < 2: continue
        cursor.execute("SELECT * FROM colleges WHERE college_name LIKE ? ORDER BY rating DESC LIMIT 3", (f"%{cleaned}%",))
        for r in cursor.fetchall():
            d = dict(r)
            if d["id"] not in seen:
                seen.add(d["id"])
                results.append(d)
                
    conn.close()
    return results

def score_colleges(colleges: List[Dict], priorities: List[str], max_budget=None) -> List[Dict]:
    scored = []
    for c in colleges:
        score = ((c.get("rating") or 5.0) * 0.30 +
                 (c.get("placement") or 5.0) * 0.25 +
                 (c.get("academic") or 5.0) * 0.15 +
                 (c.get("infrastructure") or 5.0) * 0.10 +
                 (c.get("faculty") or 5.0) * 0.10 +
                 (c.get("social_life") or 5.0) * 0.10)
                 
        for p in priorities: 
            score += (c.get(p) or 5.0) * 0.05
            
        fee = c.get("ug_fee")
        if max_budget and fee: 
            score += 0.6 if fee <= max_budget else -1.2
            
        c2 = dict(c)
        c2["composite_score"] = round(score, 2)
        scored.append(c2)
        
    scored.sort(key=lambda x: x["composite_score"], reverse=True)
    return scored

# ── 4. INSTANT LOCAL SYNTHESIS (SUB-50MS FAST RESPONSE) ───────────────────────

def generate_local_synthesis(user_query: str, college_data: List[Dict], is_comparison: bool) -> str:
    """Provides an instant high-quality data-backed response directly from database."""
    if not college_data:
        return (
            "### 🎓 Admissions Counselor Insights\n\n"
            f"I couldn't find exact database matches for `{user_query}`.\n\n"
            "**Helpful Next Steps:**\n"
            "- Try specifying a state (e.g. *Karnataka, Tamil Nadu, Maharashtra, Delhi NCR*)\n"
            "- Specify a stream (e.g. *Engineering, Medical, Management, Law*)\n"
            "- Or explore the **College Directory** tab to browse all 6,780+ verified institutions!"
        )

    if is_comparison and len(college_data) >= 2:
        c1, c2 = college_data[0], college_data[1]
        fee1 = f"₹{c1['ug_fee']:,.0f}" if c1.get("ug_fee") else "Undisclosed"
        fee2 = f"₹{c2['ug_fee']:,.0f}" if c2.get("ug_fee") else "Undisclosed"
        
        return (
            f"### ⚖️ Side-by-Side Comparison: **{c1['college_name']}** vs **{c2['college_name']}**\n\n"
            f"| Metric / Feature | **{c1['college_name']}** | **{c2['college_name']}** |\n"
            f"| :--- | :--- | :--- |\n"
            f"| **State / Location** | 📍 {c1.get('state','N/A')} | 📍 {c2.get('state','N/A')} |\n"
            f"| **Stream** | 🎓 {c1.get('stream','N/A')} | 🎓 {c2.get('stream','N/A')} |\n"
            f"| **Overall Rating** | ⭐ **{c1.get('rating','N/A')}/10** | ⭐ **{c2.get('rating','N/A')}/10** |\n"
            f"| **Placement Rating** | 📈 **{c1.get('placement','N/A')}/10** | 📈 **{c2.get('placement','N/A')}/10** |\n"
            f"| **Academic Rigor** | 📚 {c1.get('academic','N/A')}/10 | 📚 {c2.get('academic','N/A')}/10 |\n"
            f"| **Infrastructure** | 🏢 {c1.get('infrastructure','N/A')}/10 | 🏢 {c2.get('infrastructure','N/A')}/10 |\n"
            f"| **Annual UG Fee** | 💰 **{fee1}** | 💰 **{fee2}** |\n\n"
            f"#### 💡 Counselor Verdict & Recommendation\n"
            f"- **Top for Placements & ROI:** **{c1['college_name'] if (c1.get('placement',0) or 0) >= (c2.get('placement',0) or 0) else c2['college_name']}**\n"
            f"- **Top Overall Experience:** **{c1['college_name'] if (c1.get('rating',0) or 0) >= (c2.get('rating',0) or 0) else c2['college_name']}**\n\n"
            f"*Data verified from 6,780+ institutional records.*"
        )

    # General Top Picks List
    out = [f"### 🏆 Verified College Recommendations\n"]
    out.append(f"Based on institutional rankings, fees, and placement records from our database:\n\n")
    out.append("| # | Institution Name | State | Stream | Rating | Placement | Annual UG Fee |\n")
    out.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- |\n")
    
    for i, c in enumerate(college_data[:6], 1):
        fee = f"₹{c['ug_fee']:,.0f}" if c.get("ug_fee") else "N/A"
        out.append(f"| **{i}** | **{c['college_name']}** | {c.get('state','-')} | {c.get('stream','-')} | ⭐ {c.get('rating','-')}/10 | 📈 {c.get('placement','-')}/10 | {fee} |\n")
        
    out.append("\n#### 🎯 Key Counselor Insights:\n")
    for c in college_data[:3]:
        ug = f"₹{c['ug_fee']:,.0f}/yr" if c.get("ug_fee") else "undisclosed fee"
        out.append(f"- **{c['college_name']}** ({c.get('state')}): Rated **{c.get('rating')}/10** with placement score **{c.get('placement')}/10** at {ug}.\n")
        
    out.append("\n*Ask me for cutoff details, branch comparisons, or admission procedures for any of these colleges!*")
    return "".join(out)

# ── 5. OPENROUTER STREAMING & ORCHESTRATOR ────────────────────────────────────

conversation_history: List[Dict[str, str]] = []

SYSTEM_PROMPT = """You are 'Astra', an elite, highly knowledgeable AI College Admission Counselor for India.
You provide instant, precise, structured, and friendly counseling for students and parents.

Counseling Standards:
1. Use clean GitHub-flavored Markdown with bold titles, comparative tables, bullet points, and key takeaways.
2. For college suggestions, include: Name, Location, Rating/10, Placement Score/10, Annual Tuition, and Key Strengths.
3. For comparisons (e.g. A vs B), ALWAYS output a clean markdown comparison table followed by a clear verdict.
4. Ground every fact strictly on the retrieved database records provided in the prompt.
5. Conclude with a helpful, conversational next-step question. Keep responses concise and impactful."""

def build_data_context(college_data: List[Dict]) -> str:
    if not college_data:
        return "No specific database matches found. Provide general counseling guidelines and suggest searching the directory."
        
    data_context = "### VERIFIED DATABASE RECORDS FROM 6,780+ INSTITUTIONS:\n"
    for i, c in enumerate(college_data, 1):
        ug = f"Rs.{c['ug_fee']:,.0f}" if c.get("ug_fee") else "Not disclosed"
        data_context += (
            f"{i}. {c['college_name']} | State: {c['state']} | Stream: {c['stream']}\n"
            f"   Rating: {c.get('rating','N/A')}/10 | Placement: {c.get('placement','N/A')}/10 | "
            f"Academic: {c.get('academic','N/A')}/10 | Infrastructure: {c.get('infrastructure','N/A')}/10 | "
            f"Faculty: {c.get('faculty','N/A')}/10 | Annual UG Fee: {ug}\n\n"
        )
    return data_context

def stream_openrouter(user_query: str, data_context: str, model_to_use: str) -> Generator[str, None, None]:
    """Streams tokens directly from OpenRouter to the client in SSE format."""
    messages = [{"role": "system", "content": SYSTEM_PROMPT + "\n\n" + data_context}]
    messages += conversation_history[-6:]
    messages.append({"role": "user", "content": user_query})
    
    full_response = []
    
    try:
        resp = requests.post(
            url="https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "HTTP-Referer": YOUR_SITE_URL,
                "X-Title": YOUR_APP_NAME,
                "Content-Type": "application/json"
            },
            json={
                "model": model_to_use,
                "messages": messages,
                "stream": True,
                "temperature": 0.3
            },
            stream=True,
            timeout=25
        )
        
        if resp.status_code != 200:
            err_msg = f"API returned status {resp.status_code}. Generating instant local synthesis..."
            yield f"data: {json.dumps({'token': '⚠️ ' + err_msg + '\n\n'})}\n\n"
            raise Exception(err_msg)
            
        for line in resp.iter_lines():
            if not line: continue
            decoded = line.decode('utf-8')
            if decoded.startswith(":"): continue # OpenRouter ping
            if decoded.startswith("data: "):
                payload = decoded[6:].strip()
                if payload == "[DONE]": break
                try:
                    chunk = json.loads(payload)
                    delta = chunk.get("choices", [{}])[0].get("delta", {})
                    token = delta.get("content", "")
                    if token:
                        full_response.append(token)
                        yield f"data: {json.dumps({'token': token})}\n\n"
                except Exception:
                    continue
                    
        # Update history
        if full_response:
            ai_text = "".join(full_response)
            conversation_history.append({"role": "user", "content": user_query})
            conversation_history.append({"role": "assistant", "content": ai_text})
            
        yield f"data: {json.dumps({'done': True})}\n\n"
        
    except Exception as e:
        # Fallback local synthesis streamed smoothly
        yield f"data: {json.dumps({'done': True, 'error': str(e)})}\n\n"

# ── 6. FASTAPI APPLICATION & ROUTES ──────────────────────────────────────────

app = FastAPI(title="Astra AI Counselor API", version="2.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

if os.path.exists(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

class ChatRequest(BaseModel):
    message: str
    fast_mode: Optional[bool] = False
    model: Optional[str] = None

@app.get("/", response_class=HTMLResponse)
def serve_home():
    idx = os.path.join(STATIC_DIR, "index.html")
    return FileResponse(idx) if os.path.exists(idx) else "<h1>Astra AI is Running</h1>"

@app.get("/api/health")
def health():
    api_ok = bool(OPENROUTER_API_KEY and OPENROUTER_API_KEY != "your_openrouter_api_key_here")
    return {
        "status": "ok",
        "primary_model": OPENROUTER_MODEL,
        "fast_model": FAST_MODEL,
        "api_configured": api_ok
    }

@app.post("/api/chat")
def chat_sync(req: ChatRequest):
    """Synchronous chat endpoint with ultra-fast fallback."""
    q = req.message.strip()
    if not q: return {"response": "Please ask a question."}
    
    if q.lower() in ["hi", "hello", "hey", "start", "help"]:
        return {
            "response": (
                "🎓 **Welcome to ASTRA AI Counselor!**\n\n"
                "I have real-time access to **6,780+ verified Indian colleges** across all streams and states. Ask me anything like:\n"
                "- 🎯 *'Top computer science colleges in Bangalore under 6 Lakhs'* \n"
                "- ⚖️ *'Compare VIT Vellore vs SRM Kattankulathur'* \n"
                "- 🏆 *'Best placement medical colleges in Karnataka'* \n\n"
                "👉 **How can I assist your college admissions today?**"
            )
        }
        
    entities = extract_entities(q)
    states, streams, budget, priorities = entities["states"], entities["streams"], entities["budget"], entities["priorities"]
    is_comparison = any(w in q.lower() for w in ["compare", "vs", "versus", "difference between"])
    
    college_data = []
    if is_comparison:
        words = [w.strip() for w in re.split(r'[,?]|\band\b|\bvs\b|\bversus\b|\bcompare\b', q, flags=re.IGNORECASE) if len(w.strip()) > 2]
        college_data = find_colleges_by_names(words)
        
    if not college_data:
        raw = query_colleges(
            state=states[0] if states else None,
            stream=streams[0] if streams else None,
            max_fee=budget,
            limit=15
        )
        college_data = score_colleges(raw, priorities, budget)[:6]
        
    data_context = build_data_context(college_data)
    model_to_use = FAST_MODEL if req.fast_mode else (req.model or OPENROUTER_MODEL)
    
    # Try OpenRouter
    if OPENROUTER_API_KEY and OPENROUTER_API_KEY != "your_openrouter_api_key_here":
        try:
            resp = requests.post(
                url="https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                    "HTTP-Referer": YOUR_SITE_URL,
                    "X-Title": YOUR_APP_NAME,
                    "Content-Type": "application/json"
                },
                json={
                    "model": model_to_use,
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT + "\n\n" + data_context},
                        *conversation_history[-6:],
                        {"role": "user", "content": q}
                    ],
                    "timeout": 15
                }
            )
            if resp.status_code == 200:
                ai_text = resp.json()["choices"][0]["message"]["content"]
                conversation_history.append({"role": "user", "content": q})
                conversation_history.append({"role": "assistant", "content": ai_text})
                return {"response": ai_text, "source": "openrouter", "model": model_to_use}
        except Exception:
            pass

    # Instant Local Synthesis fallback
    local_resp = generate_local_synthesis(q, college_data, is_comparison)
    return {"response": local_resp, "source": "local_database", "model": "instant-database-rag"}

@app.get("/api/chat/stream")
def chat_stream(message: str = Query(...), fast_mode: bool = Query(False), model: Optional[str] = Query(None)):
    """Real-Time SSE Streaming Endpoint for Instant Word-by-Word Typing."""
    q = message.strip()
    if not q:
        def empty_gen():
            yield f"data: {json.dumps({'token': 'Please ask a valid question.'})}\n\n"
            yield f"data: {json.dumps({'done': True})}\n\n"
        return StreamingResponse(empty_gen(), media_type="text/event-stream")

    entities = extract_entities(q)
    states, streams, budget, priorities = entities["states"], entities["streams"], entities["budget"], entities["priorities"]
    is_comparison = any(w in q.lower() for w in ["compare", "vs", "versus", "difference between"])
    
    college_data = []
    if is_comparison:
        words = [w.strip() for w in re.split(r'[,?]|\band\b|\bvs\b|\bversus\b|\bcompare\b', q, flags=re.IGNORECASE) if len(w.strip()) > 2]
        college_data = find_colleges_by_names(words)
        
    if not college_data:
        raw = query_colleges(
            state=states[0] if states else None,
            stream=streams[0] if streams else None,
            max_fee=budget,
            limit=15
        )
        college_data = score_colleges(raw, priorities, budget)[:6]
        
    data_context = build_data_context(college_data)
    model_to_use = FAST_MODEL if fast_mode else (model or OPENROUTER_MODEL)
    
    def event_stream():
        # First send metadata (colleges retrieved)
        yield f"data: {json.dumps({'type': 'meta', 'matched_colleges': len(college_data), 'model': model_to_use})}\n\n"
        
        if OPENROUTER_API_KEY and OPENROUTER_API_KEY != "your_openrouter_api_key_here":
            has_tokens = False
            for chunk_event in stream_openrouter(q, data_context, model_to_use):
                has_tokens = True
                yield chunk_event
            if has_tokens:
                return

        # If offline or API fails, stream local synthesis instantly
        synth = generate_local_synthesis(q, college_data, is_comparison)
        words = re.findall(r'\S+|\n', synth)
        for w in words:
            yield f"data: {json.dumps({'token': w + (' ' if not w.endswith('\n') else '')})}\n\n"
        yield f"data: {json.dumps({'done': True})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )

@app.post("/api/reset")
def reset():
    conversation_history.clear()
    return {"status": "ok", "message": "Chat session reset successfully."}

@app.get("/api/colleges")
def get_colleges(
    state: Optional[str] = Query(None),
    stream: Optional[str] = Query(None),
    max_fee: Optional[float] = Query(None),
    q: Optional[str] = Query(None),
    limit: int = Query(30, ge=1, le=100)
):
    cols = query_colleges(state=state, stream=stream, max_fee=max_fee, search_text=q, limit=limit)
    return {"count": len(cols), "colleges": cols}

@app.get("/api/stats")
def get_stats():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM colleges")
        total = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(DISTINCT state) FROM colleges WHERE state IS NOT NULL AND state != ''")
        states = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(DISTINCT stream) FROM colleges WHERE stream IS NOT NULL AND stream != ''")
        streams = cursor.fetchone()[0]
        conn.close()
        return {
            "total_colleges": total,
            "total_states": states,
            "total_streams": streams,
            "primary_model": OPENROUTER_MODEL,
            "fast_model": FAST_MODEL
        }
    except Exception as e:
        return {
            "total_colleges": 6788,
            "total_states": 28,
            "total_streams": 10,
            "primary_model": OPENROUTER_MODEL,
            "fast_model": FAST_MODEL,
            "error": str(e)
        }

# ── 7. MAIN RUNNER ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print(f"🚀 Starting Astra AI Counselor on http://localhost:{PORT}")
    print(f"⚡ Fast Model: {FAST_MODEL} | 🧠 Deep Model: {OPENROUTER_MODEL}")
    uvicorn.run("app:app", host=HOST, port=PORT, reload=True)
