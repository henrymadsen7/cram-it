#!/usr/bin/env python3
"""
Cram-It — AI-Powered Exam Prep Platform
Multi-course study engine with FSRS spaced repetition, AI tutoring, and LMS integrations.
"""
import sys, json, sqlite3, os, time, threading, yaml
from datetime import datetime, timezone
from pathlib import Path
from flask import Flask, request, jsonify, render_template, send_from_directory, Response, stream_with_context
from dotenv import load_dotenv
import anthropic
import chromadb
from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction

# Load .env from project root first, then fallback
load_dotenv(Path(__file__).parent / ".env")
load_dotenv(Path.home() / ".hermes/.env")

# Engine imports (local)
sys.path.insert(0, str(Path(__file__).parent))
from engine.tutor_plugin import (
    quiz_session_start, quiz_start, quiz_answer,
    quiz_explain, quiz_progress, quiz_compare, quiz_similar,
    _get_profile, _update_profile, _get_user_preferences, _get_db,
    end_session, recalculate_difficulty
)
from engine.similar_generator import generate_for_missed_question, _ensure_generated_tables

app = Flask(__name__, static_folder="static", template_folder="templates")
app.secret_key = os.environ.get("SECRET_KEY", os.urandom(24).hex())
claude = anthropic.Anthropic()

# === DATA DIRECTORIES ===
PROJECT_ROOT = Path(__file__).parent
DATA_DIR = Path(os.environ.get("CRAM_IT_DATA_DIR", PROJECT_ROOT / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = DATA_DIR / "learner.db"
CHROMA_DIR = DATA_DIR / "chroma_db"
PROFILES_DIR = DATA_DIR / "profiles"
PROFILES_DIR.mkdir(parents=True, exist_ok=True)
FEEDBACK_LOG = DATA_DIR / "feedback_log.jsonl"

# === PACK SYSTEM ===
PACKS_DIR = PROJECT_ROOT / "packs"
ACTIVE_PACK = None  # loaded at startup
PACK_CONFIG = {}
KNOWLEDGE_GRAPH = {}
CONCEPT_MAP = {}
EXAM_WEIGHT_MAP = {}
CONCEPT_CATEGORIES = {}


def load_pack(pack_name):
    """Load a course pack by name. Reads pack.yaml and all data files."""
    global ACTIVE_PACK, PACK_CONFIG, KNOWLEDGE_GRAPH, CONCEPT_MAP, EXAM_WEIGHT_MAP, CONCEPT_CATEGORIES
    
    pack_dir = PACKS_DIR / pack_name
    config_path = pack_dir / "pack.yaml"
    
    if not config_path.exists():
        raise FileNotFoundError(f"Pack '{pack_name}' not found at {config_path}")
    
    with open(config_path) as f:
        PACK_CONFIG = yaml.safe_load(f)
    
    ACTIVE_PACK = pack_name
    
    # Load optional data files
    kg_path = pack_dir / "knowledge_graph.json"
    if kg_path.exists():
        with open(kg_path) as f:
            KNOWLEDGE_GRAPH = json.load(f)
    else:
        KNOWLEDGE_GRAPH = {}
    
    cm_path = pack_dir / "concept_map.json"
    if cm_path.exists():
        with open(cm_path) as f:
            CONCEPT_MAP = json.load(f)
    else:
        CONCEPT_MAP = {}
    
    ew_path = pack_dir / "exam_weights.json"
    if ew_path.exists():
        with open(ew_path) as f:
            EXAM_WEIGHT_MAP = json.load(f)
    else:
        EXAM_WEIGHT_MAP = {}
    
    cc_path = pack_dir / "concept_categories.json"
    if cc_path.exists():
        with open(cc_path) as f:
            CONCEPT_CATEGORIES = json.load(f)
    else:
        CONCEPT_CATEGORIES = {}
    
    print(f"[Cram-It] Loaded pack: {PACK_CONFIG.get('name', pack_name)}")
    return PACK_CONFIG


def list_packs():
    """List all available course packs."""
    packs = []
    if not PACKS_DIR.exists():
        return packs
    for d in sorted(PACKS_DIR.iterdir()):
        config = d / "pack.yaml"
        if config.exists():
            with open(config) as f:
                cfg = yaml.safe_load(f)
            packs.append({
                "id": d.name,
                "name": cfg.get("name", d.name),
                "short_name": cfg.get("short_name", d.name),
                "description": cfg.get("description", ""),
                "active": d.name == ACTIVE_PACK,
            })
    return packs


# Load initial pack from env or first available
_initial_pack = os.environ.get("CRAM_IT_PACK", "")
if _initial_pack:
    try:
        load_pack(_initial_pack)
    except Exception as e:
        print(f"[Cram-It] Warning: Could not load pack '{_initial_pack}': {e}")
else:
    # Auto-load first available pack
    if PACKS_DIR.exists():
        for d in sorted(PACKS_DIR.iterdir()):
            if (d / "pack.yaml").exists() and d.name != "_template":
                try:
                    load_pack(d.name)
                    break
                except:
                    pass

# Slide search (ChromaDB)
_slide_embed = SentenceTransformerEmbeddingFunction(model_name="all-MiniLM-L6-v2")
_chroma = chromadb.PersistentClient(path=str(CHROMA_DIR))
try:
    _col_name = f"{ACTIVE_PACK}_slides" if ACTIVE_PACK else "slides"
    SLIDES_COL = _chroma.get_collection(_col_name, embedding_function=_slide_embed)
except:
    SLIDES_COL = None

# === AGENT INSTANCES ===
# Each user gets a persistent conversation thread with Claude
# Agents auto-shutdown after 30min of inactivity
AGENTS = {}  # user_id -> {client, messages, last_active, system_prompt}
AGENT_TIMEOUT = 1800  # 30 minutes

def get_agent_system_prompt(user_id):
    """Build a rich system prompt for this user's agent."""
    prefs = {}
    try:
        db = _get_db()
        prefs = _get_user_preferences(db, user_id)
        db.close()
    except:
        pass
    
    persona = prefs.get("tutor_persona", PACK_CONFIG.get("ai_persona_name", "Tutor"))
    display = prefs.get("display_name", user_id)
    profile = _get_profile(user_id)
    prog_data = json.loads(quiz_progress(user_id))
    
    # Pack info
    course_name = PACK_CONFIG.get("name", "this course")
    textbook = PACK_CONFIG.get("textbook", "the course textbook")
    professor = PACK_CONFIG.get("professor", "the professor")
    exam_fmt = PACK_CONFIG.get("exam_format", {})
    chapters = PACK_CONFIG.get("chapters", [])
    chapters_str = ", ".join(str(c) for c in chapters) if chapters else "all covered chapters"
    notes_allowed = PACK_CONFIG.get("notes_allowed", False)
    calculator = PACK_CONFIG.get("calculator", False)
    
    # Get concept mastery
    db = sqlite3.connect(str(DB_PATH))
    cur = db.cursor()
    cur.execute("SELECT concept_id, mastery_pct, total_attempts, proven FROM concept_mastery WHERE user_id = ?", (user_id,))
    concept_rows = cur.fetchall()
    cur.execute("SELECT COUNT(*) FROM intake_responses WHERE user_id = ?", (user_id,))
    has_intake = cur.fetchone()[0] > 0
    cur.execute("SELECT COUNT(*) FROM sessions WHERE user_id = ? AND active = 1", (user_id,))
    has_active_session = cur.fetchone()[0] > 0
    db.close()
    
    concept_status = ""
    if concept_rows:
        concept_status = "CONCEPT MASTERY:\n"
        for cid, pct, attempts, proven in sorted(concept_rows, key=lambda x: x[1]):
            status = "PROVEN" if proven else f"{pct}%"
            concept_status += f"  {cid}: {status} ({attempts} attempts)\n"
    
    # Build exam details from pack config
    exam_details = f"EXAM DETAILS:\n- Chapters: {chapters_str}"
    if exam_fmt:
        exam_details += f"\n- {exam_fmt.get('questions', '?')} {', '.join(exam_fmt.get('question_types', ['questions']))}"
        if exam_fmt.get('points_each'):
            exam_details += f", {exam_fmt['points_each']} pts each"
        if exam_fmt.get('time_minutes'):
            exam_details += f"\n- Time limit: {exam_fmt['time_minutes']} minutes"
    exam_details += f"\n- Textbook: {textbook}"
    exam_details += f"\n- Notes allowed: {'Yes' if notes_allowed else 'No'}"
    if calculator:
        exam_details += f"\n- Calculator: Yes"
    
    # Custom AI persona or default
    custom_persona = PACK_CONFIG.get("ai_persona", "")
    if custom_persona:
        persona_block = custom_persona
    else:
        persona_block = f"You are {persona}, a dedicated tutor for {display}. You are preparing them for their {course_name} exam.\n\nYOUR PERSONALITY: Sharp, direct, no-nonsense. No emojis. Use -- for dashes. You're a smart study partner who knows the material cold and cares about {display}'s success. Be concise but thorough."
    
    # Count available resources
    q_count = 0
    try:
        dbc = sqlite3.connect(str(DB_PATH))
        q_count = dbc.execute("SELECT COUNT(*) FROM questions").fetchone()[0]
        dbc.close()
    except:
        pass
    
    system = f"""{persona_block}

{exam_details}

{display}'S CURRENT STATE:
- Accuracy: {prog_data.get('overall_pct', 0)}%
- Questions attempted: {prog_data.get('total_attempts', 0)}/{q_count}
- Projected exam score: {prog_data.get('projected_exam_score', 0)}%
- Questions due for review: {prog_data.get('due_today', 0)}
- Has completed intake: {has_intake}
- Has active drill session: {has_active_session}

{concept_status}

PROFILE:
{profile[:800] if profile else 'New student.'}

YOUR CAPABILITIES (you have REAL database access):
- You see the actual exam questions from the database injected into your context -- cite them directly
- You have {q_count} verified exam questions with answer keys
- You have textbook chunks searchable by concept via ChromaDB
- You have a knowledge graph with {len(CONCEPT_MAP)} testable concepts, their prerequisites, equations, and misconceptions
- When the student asks "which questions" or "list" or "show me", the system injects actual database results into your context -- USE them, don't say you don't have access
- When visuals help, add [SLIDES: topic keyword] to show lecture slides
- To render an INTERACTIVE graph, add [GRAPH: type] where type is one of: cost_curves, monopoly, supply_demand, consumer_choice
- You can use BOTH [GRAPH:] and [SLIDES:] in the same message
- For CUSTOM graphs with specific numbers, use [DYNAMIC_GRAPH: JSON] -- see GRAPH_SPEC_FORMAT below."""

    system += """

GRAPH_SPEC_FORMAT for [DYNAMIC_GRAPH: ...]:
The JSON spec has: boundingbox, xLabel, yLabel, elements array, annotation string.
Element types: curve (fn as JS expression with x), point (x,y,label), segment (x1,y1,x2,y2), line (y1 for horizontal), polygon (points array), text (x,y,text), table (rows array).
Curve fn examples: "51-4*x" (linear), "0.8*x*x-6*x+20" (quadratic/U-shape), "15" (constant MC), "20/x" (hyperbola/AFC).
Colors: "#2563eb" blue/demand, "#ea580c" orange/MR, "#dc2626" red/MC, "#16a34a" green/supply, "#ca8a04" yellow/price.
Example monopoly: [DYNAMIC_GRAPH: {"boundingbox":[-1,60,15,-5],"xLabel":"Quantity","yLabel":"Price","elements":[{"type":"curve","fn":"51-4*x","color":"#2563eb","label":"D"},{"type":"curve","fn":"51-8*x","color":"#ea580c","label":"MR"},{"type":"curve","fn":"15","color":"#dc2626","label":"MC"},{"type":"point","x":4.5,"y":33,"label":"P*"},{"type":"segment","x1":4.5,"y1":0,"x2":4.5,"y2":33}],"annotation":"MR=MC at Q=4.5, P=33"}]
Use DYNAMIC_GRAPH when a question has specific numbers. Use plain [GRAPH: type] for generic illustrations.
ALWAYS include annotation with the step-by-step calculation.
For tables: add element {"type":"table","rows":[["Q","P","TR"],["1","47","47"],["2","43","86"]]}"""

    system += f"""
- You can reference specific exam questions by source: "[W2024] Question about shutdown..." 
- NEVER say "I don't have access to" -- you DO have access. The data is in your context.

YOUR JOB:
1. If this is {display}'s first time (no intake), assess them with 3-5 free-response questions about core concepts
2. Help them understand concepts ONLY in service of answering exam questions correctly
3. Track their understanding -- when they master a concept, note it. When they struggle, dig into WHY.
4. Every explanation should connect to "here's how this gets tested on the exam"

RULES:
- Teaching exists ONLY to help answer questions correctly. No tangents.
- When explaining: concept -> formula (if any) -> apply to this question -> arrive at answer
- Cite the textbook (chapter/section) when relevant
- When a concept has a visual, use [SLIDES: concept] to show the relevant lecture slide
- If they've seen a concept before and got it right, don't over-explain. Move on.
- Track patterns in their mistakes. If they keep confusing the same thing, address it directly.

INTAKE ASSESSMENT:
When you complete an intake assessment question and evaluate the student's understanding:
- Rate their understanding 0-100 for each relevant concept
- Include [ASSESS: concept_id=X, mastery=Y, evidence="reason"] in your response
The system will parse this and update their concept mastery estimates.
Valid concept_ids: """ + ", ".join(sorted(CONCEPT_MAP.keys()))

    # Load past intake assessment responses
    try:
        db2 = sqlite3.connect(str(DB_PATH))
        cur2 = db2.cursor()
        cur2.execute("SELECT question_text, response_text, assessment FROM intake_responses WHERE user_id = ? ORDER BY timestamp", (user_id,))
        intake_rows = cur2.fetchall()
        if intake_rows:
            system += "\nPAST INTAKE ASSESSMENT:\n"
            for q, r, a in intake_rows:
                system += f"Q: {q}\nStudent: {r}\nAssessment: {a}\n\n"
        db2.close()
    except:
        pass

    return system


def get_or_create_agent(user_id):
    """Get existing agent or create a new one."""
    now = time.time()
    
    if user_id in AGENTS:
        agent = AGENTS[user_id]
        agent["last_active"] = now
        return agent
    
    system = get_agent_system_prompt(user_id)
    AGENTS[user_id] = {
        "messages": [],
        "system": system,
        "last_active": now,
        "created": now,
    }
    return AGENTS[user_id]


def cleanup_agents():
    """Remove inactive agents."""
    now = time.time()
    expired = [uid for uid, a in AGENTS.items() if now - a["last_active"] > AGENT_TIMEOUT]
    for uid in expired:
        del AGENTS[uid]


# Run cleanup every 5 minutes
def cleanup_loop():
    while True:
        time.sleep(300)
        cleanup_agents()

cleanup_thread = threading.Thread(target=cleanup_loop, daemon=True)
cleanup_thread.start()


# === PAGES ===
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/battle")
def battle_redirect():
    from flask import redirect, request as req
    # If accessed via tunnel, redirect to battle tunnel; else localhost
    host = req.host or ""
    if "trycloudflare" in host or "view-ai" in host:
        return redirect("https://battle.view-ai.com/")
    return redirect("http://localhost:4000/")

@app.route("/podcast/<path:fn>")
def serve_podcast(fn):
    """Serve podcast files from the active pack's podcast/ directory."""
    from flask import send_from_directory
    if ACTIVE_PACK:
        pack_podcast_dir = PACKS_DIR / ACTIVE_PACK / "podcast"
        if pack_podcast_dir.exists():
            return send_from_directory(str(pack_podcast_dir), fn)
    # Fallback to legacy top-level podcast/ directory
    return send_from_directory("podcast", fn)

@app.route("/podcast/<pack_name>/<path:fn>")
def serve_pack_podcast(pack_name, fn):
    """Serve podcast files from a specific pack's podcast/ directory."""
    from flask import send_from_directory, abort
    pack_podcast_dir = PACKS_DIR / pack_name / "podcast"
    if not pack_podcast_dir.exists():
        abort(404)
    return send_from_directory(str(pack_podcast_dir), fn)

@app.route("/static/figures/<path:fn>")
def fig(fn):
    return send_from_directory("static/figures", fn)

@app.route("/static/slide_graphs/<path:fn>")
def slide_fig(fn):
    return send_from_directory("static/slide_graphs", fn)

# === CORE QUIZ API ===
@app.route("/api/session", methods=["POST"])
def session():
    return jsonify(json.loads(quiz_session_start(request.json["user_id"])))

@app.route("/api/quiz", methods=["POST"])
def quiz():
    d = request.json
    return jsonify(json.loads(quiz_start(d["user_id"], d.get("mode","drill"), d.get("chapter"), d.get("count",10))))

@app.route("/api/answer", methods=["POST"])
def answer():
    d = request.json

    # Handle graph exercise answers (gx_ prefix) — log directly, no FSRS
    if d.get("question_id", "").startswith("gx_"):
        gx_correct = d.get("correct", d.get("user_answer", "").lower() == "correct")
        try:
            db = sqlite3.connect(str(DB_PATH))
            db.execute("""
                INSERT INTO reviews (user_id, question_id, user_answer, correct, time_spent_seconds)
                VALUES (?, ?, ?, ?, ?)
            """, (d["user_id"], d["question_id"], d.get("user_answer",""), 1 if gx_correct else 0, d.get("seconds",0)))
            db.commit()
            db.close()
        except Exception as e:
            print(f"Graph exercise log error: {e}")
        return jsonify({"correct": bool(gx_correct), "graph_exercise": True, "question_id": d["question_id"]})

    result = json.loads(quiz_answer(d["user_id"], d["question_id"], d["user_answer"], d.get("seconds",0)))
    # concept_mastery is now updated inside quiz_answer() in tutor_plugin.py
    return jsonify(result)

@app.route("/api/explain", methods=["POST"])
def explain():
    return jsonify(json.loads(quiz_explain(request.json["question_id"])))

@app.route("/api/progress", methods=["POST"])
def progress():
    d = request.json
    prog = json.loads(quiz_progress(d["user_id"]))
    # concept_mastery and concepts_proven are now included by quiz_progress() in tutor_plugin.py
    prog["concepts_total"] = len(CONCEPT_MAP)
    return jsonify(prog)

# === INTAKE ASSESSMENT ===
import re

def _process_intake_assess(user_id, concept_id, estimated_mastery, evidence=""):
    """Insert intake assessment and seed concept_mastery if no real quiz data exists."""
    db = sqlite3.connect(str(DB_PATH))
    cur = db.cursor()
    
    # Insert into intake_responses
    cur.execute("""
        INSERT INTO intake_responses (user_id, question_text, response_text, assessment)
        VALUES (?, ?, ?, ?)
    """, (user_id, f"intake_assess:{concept_id}", evidence, f"mastery={estimated_mastery}"))
    
    # Only SEED concept_mastery if no real quiz data exists (total_attempts == 0 or no row)
    cur.execute("SELECT total_attempts FROM concept_mastery WHERE user_id = ? AND concept_id = ?",
                (user_id, concept_id))
    row = cur.fetchone()
    if row is None:
        # No entry -- seed with intake estimate
        cur.execute("""
            INSERT INTO concept_mastery (user_id, concept_id, total_attempts, correct_attempts, mastery_pct, proven)
            VALUES (?, ?, 0, 0, ?, 0)
        """, (user_id, concept_id, float(estimated_mastery)))
    elif row[0] == 0:
        # Entry exists but no real quiz data -- update the estimate
        cur.execute("""
            UPDATE concept_mastery SET mastery_pct = ? WHERE user_id = ? AND concept_id = ? AND total_attempts = 0
        """, (float(estimated_mastery), user_id, concept_id))
    # If total_attempts > 0, do NOT overwrite real quiz data
    
    db.commit()
    db.close()
    return True

def _parse_assess_tags(text):
    """Parse [ASSESS: concept_id=X, mastery=Y, evidence="reason"] from agent response."""
    pattern = r'\[ASSESS:\s*concept_id=([^,\]]+),\s*mastery=(\d+)(?:,\s*evidence="([^"]*)")?\]'
    matches = re.findall(pattern, text)
    results = []
    for concept_id, mastery, evidence in matches:
        concept_id = concept_id.strip()
        mastery = int(mastery)
        evidence = evidence.strip() if evidence else ""
        if concept_id in CONCEPT_MAP and 0 <= mastery <= 100:
            results.append({"concept_id": concept_id, "mastery": mastery, "evidence": evidence})
    return results

@app.route("/api/intake_assess", methods=["POST"])
def intake_assess():
    """Accept intake assessment data and seed concept mastery."""
    d = request.json
    user_id = d.get("user_id")
    concept_id = d.get("concept_id")
    estimated_mastery = d.get("estimated_mastery", 50)
    evidence = d.get("evidence", "")
    
    if not user_id or not concept_id:
        return jsonify({"error": "user_id and concept_id required"}), 400
    if concept_id not in CONCEPT_MAP:
        return jsonify({"error": f"Unknown concept_id: {concept_id}"}), 400
    
    _process_intake_assess(user_id, concept_id, estimated_mastery, evidence)
    return jsonify({"ok": True, "concept_id": concept_id, "estimated_mastery": estimated_mastery})

# === QUESTION MANAGEMENT ===
@app.route("/api/flag", methods=["POST"])
def flag_question():
    d = request.json
    db = sqlite3.connect(str(DB_PATH))
    db.execute("UPDATE questions SET flagged = ? WHERE id = ?", (1 if d.get("flag", True) else 0, d["question_id"]))
    db.commit()
    db.close()
    return jsonify({"ok": True})

@app.route("/api/questions/history", methods=["POST"])
def question_history():
    """Get all questions with user's answer history, concept tags, source exam."""
    d = request.json
    user_id = d["user_id"]
    
    db = sqlite3.connect(str(DB_PATH))
    db.row_factory = sqlite3.Row
    cur = db.cursor()
    
    cur.execute("""
        SELECT q.id, q.question_text, q.correct_answer, q.source_exam, q.topic_tags, 
               q.concept_tags, q.question_type, q.frequency_tier, q.has_chart, q.flagged,
               COUNT(r.id) as attempts, SUM(r.correct) as correct_count,
               MAX(r.timestamp) as last_attempted
        FROM questions q
        LEFT JOIN reviews r ON q.id = r.question_id AND r.user_id = ?
        GROUP BY q.id
        ORDER BY q.source_exam, q.id
    """, (user_id,))
    
    questions = []
    for row in cur.fetchall():
        questions.append({
            "id": row["id"],
            "text": row["question_text"][:100],
            "correct_answer": row["correct_answer"],
            "source_exam": row["source_exam"],
            "topics": json.loads(row["topic_tags"] or "[]"),
            "concepts": json.loads(row["concept_tags"] or "[]"),
            "type": row["question_type"],
            "frequency": row["frequency_tier"],
            "has_chart": bool(row["has_chart"]),
            "flagged": bool(row["flagged"]),
            "attempts": row["attempts"] or 0,
            "correct": row["correct_count"] or 0,
            "last_attempted": row["last_attempted"],
        })
    
    db.close()
    return jsonify({"questions": questions, "total": len(questions)})

# === SLIDES ===
@app.route("/api/slides", methods=["POST"])
def slide_lookup():
    d = request.json
    query = d.get("topic", "") or d.get("query", "")
    if not query or not SLIDES_COL:
        return jsonify({"slides": [], "total": 0})
    
    results = SLIDES_COL.query(query_texts=[query], n_results=min(d.get("count", 3), 6))
    matches = []
    if results and results["documents"]:
        for doc, meta in zip(results["documents"][0], results["metadatas"][0]):
            matches.append({
                "image": meta.get("image", ""),
                "deck": meta.get("deck", ""),
                "page": meta.get("page", 0),
                "description": doc[:300],
                "topics": json.loads(meta.get("topics", "[]")),
            })
    return jsonify({"slides": matches, "total": len(matches)})

# === HINT ===
@app.route("/api/hint", methods=["POST"])
def hint():
    d = request.json
    exp = json.loads(quiz_explain(d["question_id"]))
    topics = exp.get("question", {}).get("topics", [])
    
    try:
        resp = claude.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=150,
            system="Give a concise economics hint. 2-3 lines max. State the key concept and formula if applicable. No fluff, no emojis. Use -- for dashes. Do NOT reveal the answer.",
            messages=[{"role": "user", "content": f"Hint for: {exp['question'].get('text','')}\nChoices: {json.dumps(exp['question'].get('choices',{}))}"}]
        )
        hint_text = resp.content[0].text
    except:
        # Fallback
        hints = []
        for node in KNOWLEDGE_GRAPH.get("nodes", []):
            if any(t in node["id"] or node["id"] in t for t in topics):
                hints.append(node["key_insight"])
                break
        hint_text = hints[0] if hints else "No hint available."
    
    return jsonify({"hint": hint_text, "topics": topics})

# === AGENT CHAT (streaming) ===
@app.route("/api/agent/stream", methods=["POST"])
def agent_stream():
    """Main agent chat. Persistent conversation with memory."""
    d = request.json
    user_id = d["user_id"]
    message = d["message"]
    question_id = d.get("question_id")
    
    agent = get_or_create_agent(user_id)
    
    # Handle notes
    if message.lower().startswith(("note:", "remember:", "save:")):
        note_text = message.split(":", 1)[1].strip() if ":" in message else message
        if note_text:
            profile_path = PROFILES_DIR / f"{user_id}.md"
            if profile_path.exists():
                content = profile_path.read_text()
                idx = content.find("### Notes\n")
                if idx >= 0:
                    at = idx + len("### Notes\n")
                    content = content.replace("- (none yet)\n\n### Chat Insights", "\n### Chat Insights")
                    content = content[:at] + f"- {note_text}\n" + content[at:]
                    profile_path.write_text(content)
        def gn():
            yield f'data: {json.dumps({"text": f"Noted."})}\n\n'
            yield f'data: {json.dumps({"done": True})}\n\n'
        return Response(stream_with_context(gn()), mimetype='text/event-stream')
    
    # Build rich context by actually querying our data
    context_parts = [message]
    
    # If there's a current question, pull EVERYTHING about it
    if question_id:
        try:
            exp = json.loads(quiz_explain(question_id))
            q = exp.get("question", {})
            context_parts = [f"[CURRENT QUESTION: {q.get('text','')}]"]
            context_parts.append(f"[CORRECT ANSWER: {q.get('correct_answer','')}]")
            context_parts.append(f"[CHOICES: {json.dumps(q.get('choices',{}))}]")
            
            if exp.get("textbook_context"):
                for ctx in exp["textbook_context"][:2]:
                    context_parts.append(f'[TEXTBOOK Ch{ctx["chapter"]}, {ctx["section"]}]: {ctx["text"][:400]}')
            if exp.get("calc_formula"):
                context_parts.append(f'[FORMULA: {exp["calc_formula"]["name"]}: {exp["calc_formula"]["formula"]}]')
            if exp.get("tricky_pattern"):
                context_parts.append(f'[TRAP: {exp["tricky_pattern"]}]')
            if exp.get("similar_questions"):
                for sq in exp["similar_questions"][:2]:
                    src = sq.get("source_exam") or sq.get("source") or "other"
                    context_parts.append(f'[BUTLER VARIANT from {src}: {sq.get("text","")[:200]}]')
            
            # Get concept info
            db2 = sqlite3.connect(str(DB_PATH))
            cur2 = db2.cursor()
            cur2.execute("SELECT concept_tags FROM questions WHERE id = ?", (question_id,))
            row2 = cur2.fetchone()
            if row2:
                concepts = json.loads(row2[0] or "[]")
                for cid in concepts:
                    if cid in CONCEPT_MAP:
                        c = CONCEPT_MAP[cid]
                        context_parts.append(f'[CONCEPT {c.get("name","")}: {c.get("description","")}]')
            db2.close()
            
            # Knowledge graph nodes
            topics = q.get("topics", [])
            for node in KNOWLEDGE_GRAPH.get("nodes", []):
                if any(t in node["id"] or node["id"] in t for t in topics):
                    context_parts.append(f'[KEY INSIGHT: {node["key_insight"]}]')
                    for eq in node.get("equations", []):
                        context_parts.append(f'[EQUATION: {eq["formula"]} -- use when: {eq["when"]}]')
                    for m in node.get("misconceptions", []):
                        context_parts.append(f'[COMMON MISTAKE: {m}]')
                    break
            
            context_parts.append(f"\nStudent asks: {message}")
        except Exception as e:
            context_parts = [f"(Error loading question context: {e})\n\nStudent asks: {message}"]
    
    # If student asks about questions or data, query the database
    msg_lower = message.lower()
    if any(w in msg_lower for w in ["list", "show me", "which questions", "how many", "what questions", "13%", "27%", "percent"]):
        try:
            db3 = sqlite3.connect(str(DB_PATH))
            cur3 = db3.cursor()
            # Get question counts by concept
            cur3.execute("""
                SELECT concept_tags, COUNT(*) as cnt FROM questions 
                GROUP BY concept_tags ORDER BY cnt DESC
            """)
            concept_counts = {}
            for row in cur3.fetchall():
                for c in json.loads(row[0] or "[]"):
                    concept_counts[c] = concept_counts.get(c, 0) + row[1]
            
            context_parts.append("\n[DATABASE - QUESTION COUNTS BY CONCEPT:]")
            for c, cnt in sorted(concept_counts.items(), key=lambda x: -x[1])[:15]:
                name = CONCEPT_MAP.get(c, {}).get("name", c)
                context_parts.append(f"  {name}: {cnt} questions ({round(100*cnt/120)}%)")
            
            # If they ask about specific questions, pull them
            if any(w in msg_lower for w in ["list", "show me", "which"]):
                # Try to figure out what concept they're asking about
                for cid, cdata in CONCEPT_MAP.items():
                    if cid.replace("_", " ") in msg_lower or cdata.get("name","").lower() in msg_lower:
                        cur3.execute("SELECT question_text, source_exam, correct_answer FROM questions WHERE concept_tags LIKE ?", (f'%{cid}%',))
                        qs = cur3.fetchall()
                        context_parts.append(f"\n[ACTUAL QUESTIONS tagged '{cid}' ({len(qs)} total):]")
                        for i, qr in enumerate(qs[:10]):
                            context_parts.append(f"  {i+1}. [{qr[1]}] {qr[0][:120]}... (Answer: {qr[2]})")
                        break
            db3.close()
        except:
            pass
    
    # If they ask about slides
    if any(w in msg_lower for w in ["slide", "butler's slide", "show slide", "lecture"]):
        try:
            if SLIDES_COL:
                sr = SLIDES_COL.query(query_texts=[message], n_results=3)
                if sr and sr["documents"]:
                    context_parts.append("\n[RELEVANT BUTLER SLIDES:]")
                    for doc, meta in zip(sr["documents"][0], sr["metadatas"][0]):
                        context_parts.append(f"  [{meta.get('deck','')} slide {meta.get('page','')}]: {doc[:200]}")
                        context_parts.append(f"  Image: /static/{meta.get('image','')}")
        except:
            pass
    
    full_context = "\n".join(context_parts)
    
    # Add to conversation history
    agent["messages"].append({"role": "user", "content": full_context})
    
    # Keep conversation manageable (last 20 messages)
    if len(agent["messages"]) > 20:
        agent["messages"] = agent["messages"][-20:]
    
    # Refresh system prompt periodically (every 10 messages)
    if len(agent["messages"]) % 10 == 0:
        agent["system"] = get_agent_system_prompt(user_id)
    
    collected = []
    
    def generate():
        try:
            with claude.messages.stream(
                model="claude-sonnet-4-20250514",
                max_tokens=800,
                system=agent["system"],
                messages=agent["messages"]
            ) as stream:
                for text in stream.text_stream:
                    collected.append(text)
                    yield f"data: {json.dumps({'text': text})}\n\n"
            
            # Save assistant response to conversation
            full = "".join(collected)
            agent["messages"].append({"role": "assistant", "content": full})
            
            # Parse [ASSESS: ...] tags and update concept mastery from intake
            try:
                assess_tags = _parse_assess_tags(full)
                for tag in assess_tags:
                    _process_intake_assess(user_id, tag["concept_id"], tag["mastery"], tag["evidence"])
            except Exception as ae:
                print(f"Assess tag processing error: {ae}")
            
            # Update profile every 5 messages
            if len(agent["messages"]) % 5 == 0:
                try:
                    _update_profile(user_id)
                except:
                    pass
            
            yield f'data: {json.dumps({"done": True})}\n\n'
        except Exception as e:
            yield f'data: {json.dumps({"text": f"Error: {str(e)}"})}\n\n'
            yield f'data: {json.dumps({"done": True})}\n\n'
    
    return Response(stream_with_context(generate()), mimetype='text/event-stream')

# === VIDEO QUIZZES ===
VIDEO_QUIZ_PATH = DATA_DIR / "video_quizzes.json"
with open(VIDEO_QUIZ_PATH) as f:
    VIDEO_QUIZZES = json.load(f)

@app.route("/api/videos")
def get_videos():
    """Return all video quizzes with completion status per user."""
    user_id = request.args.get("user_id", "")
    quizzes = []
    for q in VIDEO_QUIZZES.get("quizzes", []):
        quiz = {
            "video_id": q["video_id"],
            "title": q["video_title"],
            "url": q["video_url"],
            "concept": q["concept"],
            "chapter": q["chapter"],
            "question_count": len(q["questions"]),
        }
        quizzes.append(quiz)
    return jsonify({"quizzes": quizzes})

@app.route("/api/video_quiz", methods=["POST"])
def get_video_quiz():
    """Return questions for a specific video quiz, pulling exam bank questions."""
    d = request.json
    video_id = d["video_id"]
    
    quiz = None
    for q in VIDEO_QUIZZES.get("quizzes", []):
        if q["video_id"] == video_id:
            quiz = q
            break
    
    if not quiz:
        return jsonify({"error": "Quiz not found"}), 404
    
    questions = []
    for vq in quiz["questions"]:
        if vq["type"] == "custom":
            questions.append({
                "id": vq["id"],
                "text": vq["text"],
                "choices": vq["choices"],
                "correct": vq["correct"],
                "explanation": vq["explanation"],
                "equation": vq.get("equation"),
                "graph": vq.get("graph"),
                "type": "custom",
            })
        elif vq["type"] == "exam_bank":
            # Pull a real question from the database matching the concept
            concept = vq.get("source_concept", quiz["concept"])
            db = sqlite3.connect(str(DB_PATH))
            cur = db.cursor()
            cur.execute("""
                SELECT id, question_text, correct_answer, answer_choices, source_exam, chart_table, figure_image
                FROM questions WHERE concept_tags LIKE ? ORDER BY RANDOM() LIMIT 1
            """, (f'%{concept}%',))
            row = cur.fetchone()
            db.close()
            if row:
                questions.append({
                    "id": row[0],
                    "text": row[1],
                    "choices": json.loads(row[3] or "{}"),
                    "correct": row[2],
                    "explanation": None,
                    "source_exam": row[4],
                    "chart_table": row[5],
                    "figure_image": row[6],
                    "type": "exam_bank",
                })
    
    return jsonify({
        "video_id": video_id,
        "title": quiz["video_title"],
        "url": quiz["video_url"],
        "questions": questions,
    })

# === OVERVIEW (filterable question browser) ===
@app.route("/api/overview", methods=["POST"])
def overview():
    """Filterable question browser. Filter by chapter, concept, most-missed, flagged."""
    d = request.json
    user_id = d["user_id"]
    filters = d.get("filters", {})
    
    db = sqlite3.connect(str(DB_PATH))
    db.row_factory = sqlite3.Row
    cur = db.cursor()
    
    query = """
        SELECT q.id, q.question_text, q.correct_answer, q.source_exam, q.topic_tags,
               q.concept_tags, q.question_type, q.frequency_tier, q.has_chart, q.flagged,
               q.figure_image, q.chart_table, q.source_url, q.parent_question_id,
               COUNT(r.id) as attempts, SUM(r.correct) as correct_count,
               MAX(r.timestamp) as last_attempted
        FROM questions q
        LEFT JOIN reviews r ON q.id = r.question_id AND r.user_id = ?
        GROUP BY q.id
    """
    params = [user_id]
    
    # Apply filters in Python (simpler than dynamic SQL)
    cur.execute(query, params)
    rows = cur.fetchall()
    db.close()
    
    questions = []
    for row in rows:
        is_generated = row["source_exam"] == "generated"
        q = {
            "id": row["id"],
            "text": row["question_text"],
            "text_short": row["question_text"][:120],
            "correct_answer": row["correct_answer"],
            "source_exam": row["source_exam"],
            "topics": json.loads(row["topic_tags"] or "[]"),
            "concepts": json.loads(row["concept_tags"] or "[]"),
            "type": row["question_type"],
            "frequency": row["frequency_tier"],
            "has_chart": bool(row["has_chart"]),
            "flagged": bool(row["flagged"]),
            "figure_image": row["figure_image"],
            "chart_table": row["chart_table"],
            "attempts": row["attempts"] or 0,
            "correct": row["correct_count"] or 0,
            "accuracy": round(100 * (row["correct_count"] or 0) / row["attempts"], 0) if row["attempts"] else -1,
            "last_attempted": row["last_attempted"],
            "is_generated": is_generated,
            "source_url": row["source_url"] or "",
            "parent_question_id": row["parent_question_id"] or "",
        }
        
        # Apply filters
        if filters.get("chapter"):
            ch = str(filters["chapter"])
            # Check if any concept belongs to this chapter
            concept_chapters = [str(CONCEPT_MAP.get(c, {}).get("chapter", "")) for c in q["concepts"]]
            if ch not in concept_chapters:
                continue
        if filters.get("concept"):
            if filters["concept"] not in q["concepts"]:
                continue
        if filters.get("source"):
            if q["source_exam"] != filters["source"]:
                continue
        if filters.get("flagged_only") and not q["flagged"]:
            continue
        if filters.get("missed_only") and q["accuracy"] >= 50:
            continue
        
        questions.append(q)
    
    # Sort
    sort_by = filters.get("sort", "default")
    if sort_by == "most_missed":
        questions.sort(key=lambda x: x["accuracy"] if x["accuracy"] >= 0 else 999)
    elif sort_by == "flagged":
        questions.sort(key=lambda x: (-int(x["flagged"]), x["source_exam"]))
    elif sort_by == "recent":
        questions.sort(key=lambda x: x["last_attempted"] or "", reverse=True)
    
    return jsonify({"questions": questions, "total": len(questions)})

# === DRILL MAP ===
# EXAM_WEIGHT_MAP and CONCEPT_CATEGORIES are loaded from the active pack (see load_pack())

@app.route("/api/drill_map", methods=["POST"])
def drill_map():
    """Complete concept map with per-question progress and queue preview."""
    d = request.json
    user_id = d["user_id"]

    db = sqlite3.connect(str(DB_PATH))
    db.row_factory = sqlite3.Row
    cur = db.cursor()

    # Get all questions with review data
    cur.execute("""
        SELECT q.id, q.question_text, q.source_exam, q.concept_tags,
               COUNT(r.id) as attempts, SUM(r.correct) as correct_count,
               MAX(r.correct) as ever_correct
        FROM questions q
        LEFT JOIN reviews r ON q.id = r.question_id AND r.user_id = ?
        GROUP BY q.id
    """, (user_id,))
    all_questions = cur.fetchall()

    # Get last review correctness per question
    cur.execute("""
        SELECT question_id, correct FROM reviews
        WHERE user_id = ? AND id IN (
            SELECT MAX(id) FROM reviews WHERE user_id = ? GROUP BY question_id
        )
    """, (user_id, user_id))
    last_correct_map = {row["question_id"]: bool(row["correct"]) for row in cur.fetchall()}

    # Get concept mastery
    cur.execute("SELECT concept_id, mastery_pct, total_attempts, proven FROM concept_mastery WHERE user_id = ?", (user_id,))
    mastery_map = {row["concept_id"]: {"pct": row["mastery_pct"], "attempts": row["total_attempts"], "proven": bool(row["proven"])} for row in cur.fetchall()}

    # Build concept -> questions map
    concept_questions = {}  # concept_id -> list of question dicts
    for row in all_questions:
        concepts = json.loads(row["concept_tags"] or "[]")
        attempts = row["attempts"] or 0
        correct_count = row["correct_count"] or 0
        if attempts == 0:
            status = "unseen"
        elif correct_count > 0 and last_correct_map.get(row["id"], False):
            status = "correct"
        else:
            status = "wrong"

        qdata = {
            "id": row["id"],
            "text_short": (row["question_text"] or "")[:80],
            "source_exam": row["source_exam"],
            "status": status,
            "attempts": attempts,
            "last_correct": last_correct_map.get(row["id"], False) if attempts > 0 else None,
        }
        for cid in concepts:
            if cid == "general":
                continue
            if cid not in concept_questions:
                concept_questions[cid] = []
            concept_questions[cid].append(qdata)

    # Build concepts array
    concepts_out = []
    for cid, cdata in CONCEPT_MAP.items():
        qs = concept_questions.get(cid, [])
        m = mastery_map.get(cid, {"pct": 0, "attempts": 0, "proven": False})
        concepts_out.append({
            "id": cid,
            "name": cdata.get("name", cid),
            "chapter": cdata.get("chapter", 0),
            "exam_weight": EXAM_WEIGHT_MAP.get(cid, "?"),
            "question_count": len(qs),
            "mastery": m,
            "questions": qs,
        })

    # Sort by chapter then name
    concepts_out.sort(key=lambda c: (c["chapter"], c["name"]))

    # Queue preview: replicate drill mode logic (FSRS-due first, then weak, then unseen)
    now_iso = datetime.now(timezone.utc).isoformat()
    cur.execute("""
        SELECT q.id, q.question_text, q.concept_tags, fs.due_date, fs.state
        FROM questions q
        LEFT JOIN fsrs_state fs ON q.id = fs.question_id AND fs.user_id = ?
        ORDER BY
            CASE WHEN fs.due_date IS NULL OR fs.due_date <= ? THEN 0 ELSE 1 END,
            CASE q.frequency_tier WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END,
            RANDOM()
        LIMIT 5
    """, (user_id, now_iso))

    queue_preview = []
    for row in cur.fetchall():
        concepts = json.loads(row["concept_tags"] or "[]")
        concept_id = concepts[0] if concepts else "general"
        if concept_id == "general" and len(concepts) > 1:
            concept_id = concepts[1]

        # Determine reason
        if row["due_date"] and row["due_date"] <= now_iso:
            reason = "FSRS due"
        elif row["due_date"] is None:
            reason = "unseen"
        else:
            m = mastery_map.get(concept_id, {})
            pct = m.get("pct", 0) if m else 0
            if pct < 50 and m.get("attempts", 0) > 0:
                reason = f"weak spot ({int(pct)}%)"
            else:
                reason = "scheduled"

        queue_preview.append({
            "id": row["id"],
            "text_short": (row["question_text"] or "")[:80],
            "concept": concept_id,
            "reason": reason,
        })

    # Stats
    total_qs = len(all_questions)
    seen = sum(1 for q in all_questions if (q["attempts"] or 0) > 0)
    correct = sum(1 for q in all_questions if (q["correct_count"] or 0) > 0)
    concepts_proven = sum(1 for m in mastery_map.values() if m["proven"])

    db.close()

    return jsonify({
        "concepts": concepts_out,
        "categories": CONCEPT_CATEGORIES,
        "queue_preview": queue_preview,
        "stats": {
            "total": total_qs,
            "seen": seen,
            "correct": correct,
            "unseen": total_qs - seen,
            "concepts_proven": concepts_proven,
            "concepts_total": len(CONCEPT_MAP),
        }
    })

@app.route("/api/session_end", methods=["POST"])
def session_end():
    """End a user's active drill session."""
    d = request.json
    user_id = d.get("user_id", "")
    if not user_id:
        return jsonify({"error": "user_id required"}), 400
    result = json.loads(end_session(user_id))
    return jsonify(result)


@app.route("/api/intake", methods=["POST"])
def intake():
    """Store an intake assessment response."""
    d = request.json
    user_id = d.get("user_id", "")
    if not user_id:
        return jsonify({"error": "user_id required"}), 400
    question_text = d.get("question_text", "")
    response_text = d.get("response_text", "")
    assessment = d.get("assessment", "")
    db = sqlite3.connect(str(DB_PATH))
    cur = db.cursor()
    cur.execute("""
        INSERT INTO intake_responses (user_id, question_text, response_text, assessment)
        VALUES (?, ?, ?, ?)
    """, (user_id, question_text, response_text, assessment))
    db.commit()
    row_id = cur.lastrowid
    db.close()
    # Invalidate cached agent so system prompt refreshes with new intake data
    if user_id in AGENTS:
        del AGENTS[user_id]
    return jsonify({"saved": True, "id": row_id})


@app.route("/api/difficulty")
def difficulty():
    """Return all questions with difficulty scores, sorted hardest first."""
    # Recalculate first to ensure fresh data
    try:
        recalculate_difficulty()
    except:
        pass
    db = sqlite3.connect(str(DB_PATH))
    cur = db.cursor()
    cur.execute("""
        SELECT id, question_text, difficulty_score, question_type, frequency_tier, topic_tags
        FROM questions WHERE difficulty_score IS NOT NULL
        ORDER BY difficulty_score DESC
    """)
    rows = cur.fetchall()
    db.close()
    questions = []
    for qid, text, score, qtype, tier, tags in rows:
        questions.append({
            "id": qid,
            "text": text[:120],
            "difficulty_score": score,
            "question_type": qtype,
            "frequency_tier": tier,
            "topic_tags": json.loads(tags) if tags else [],
        })
    return jsonify({"questions": questions, "count": len(questions)})


# === EXAM MODE ===

@app.route("/api/exam_submit", methods=["POST"])
def exam_submit():
    """Submit a completed exam for grading. Receives all 40 answers at once."""
    d = request.json
    user_id = d["user_id"]
    answers = d["answers"]  # list of {question_id, user_answer, seconds}
    total_seconds = d.get("total_seconds", 0)
    
    db = sqlite3.connect(str(DB_PATH))
    db.row_factory = sqlite3.Row
    cur = db.cursor()
    
    # Grade each question
    results = []
    correct_count = 0
    concept_breakdown = {}
    category_breakdown = {
        "firm_theory": {"correct": 0, "total": 0, "label": "Firm Theory (Ch 14-18)"},
        "consumer_labor": {"correct": 0, "total": 0, "label": "Consumer & Labor (Ch 19-22)"},
        "game_info": {"correct": 0, "total": 0, "label": "Game Theory & Info (Ch 23)"},
        "macro": {"correct": 0, "total": 0, "label": "Macro Basics (Ch 24-25,29)"},
    }
    
    CATEGORY_MAP = {
        "cost_curve_shapes": "firm_theory", "profit_max_mr_equals_mc": "firm_theory",
        "shutdown_decision": "firm_theory", "supply_curve_and_long_run_eq": "firm_theory",
        "explicit_vs_implicit_costs": "firm_theory", "production_function_diminishing_mp": "firm_theory",
        "economies_of_scale": "firm_theory", "competitive_firm_price_taker": "firm_theory",
        "monopoly_mr_below_demand": "firm_theory", "monopoly_pricing_two_step": "firm_theory",
        "natural_monopoly_regulation": "firm_theory", "price_discrimination": "firm_theory",
        "monopolistic_competition_sr_lr": "firm_theory",
        "budget_constraint_intercepts": "consumer_labor", "indifference_curves_mrs": "consumer_labor",
        "optimal_choice_tangency": "consumer_labor", "income_substitution_effects": "consumer_labor",
        "vmp_and_labor_demand": "consumer_labor", "labor_supply_shifts": "consumer_labor",
        "discrimination_and_human_capital": "consumer_labor",
        "game_theory_nash_dominant": "game_info", "cartel_instability": "game_info",
        "moral_hazard_adverse_selection": "game_info", "voting_condorcet_arrow": "game_info",
        "gdp_real_nominal_deflator": "macro", "cpi_inflation_real_interest": "macro",
        "unemployment_types_measurement": "macro",
    }
    
    time_per_question = []
    unanswered_count = 0
    answered_count = 0
    
    for a in answers:
        qid = a["question_id"]
        user_ans = a.get("user_answer", "").strip()
        secs = a.get("seconds", 0)
        
        cur.execute("SELECT id, question_text, correct_answer, answer_choices, concept_tags, question_type FROM questions WHERE id = ?", (qid,))
        row = cur.fetchone()
        if not row:
            continue
        
        # Determine status: answered, unanswered, or correct
        was_answered = bool(user_ans)
        is_correct = was_answered and user_ans.upper() == row["correct_answer"].upper()
        
        if was_answered:
            answered_count += 1
            if is_correct:
                correct_count += 1
            # Only log reviews for ANSWERED questions
            cur.execute("""
                INSERT INTO reviews (user_id, question_id, user_answer, correct, time_spent_seconds, explanation_chunks)
                VALUES (?, ?, ?, ?, ?, '[]')
            """, (user_id, qid, user_ans.upper(), is_correct, secs))
        else:
            unanswered_count += 1
        
        concepts = json.loads(row["concept_tags"]) if row["concept_tags"] else []
        
        # Only count ANSWERED questions toward concept/category breakdown
        if was_answered:
            for concept in concepts:
                if concept not in concept_breakdown:
                    concept_breakdown[concept] = {"correct": 0, "total": 0}
                concept_breakdown[concept]["total"] += 1
                if is_correct:
                    concept_breakdown[concept]["correct"] += 1
                
                cat = CATEGORY_MAP.get(concept, "firm_theory")
                category_breakdown[cat]["total"] += 1
                if is_correct:
                    category_breakdown[cat]["correct"] += 1
        
        if was_answered:
            time_per_question.append(secs)
        
        results.append({
            "question_id": qid,
            "user_answer": user_ans.upper() if was_answered else "",
            "correct_answer": row["correct_answer"],
            "correct": is_correct,
            "answered": was_answered,
            "question_text": row["question_text"][:120],
            "concepts": concepts,
            "question_type": row["question_type"],
            "seconds": secs,
            "choices": json.loads(row["answer_choices"]) if row["answer_choices"] else {},
        })
    
    total_questions = len(results)
    # Score based on ALL questions (unanswered = 0 points, like the real exam)
    score_pct = round(100 * correct_count / total_questions, 1) if total_questions > 0 else 0
    # But also track accuracy on ANSWERED questions only
    answered_pct = round(100 * correct_count / answered_count, 1) if answered_count > 0 else 0
    points = correct_count * 2.5  # Each question worth 2.5 points on real exam
    
    # Save exam attempt
    cur.execute("""
        CREATE TABLE IF NOT EXISTS exam_attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            total_questions INTEGER,
            correct INTEGER,
            score_pct REAL,
            total_seconds REAL,
            results_json TEXT
        )
    """)
    cur.execute("""
        INSERT INTO exam_attempts (user_id, total_questions, correct, score_pct, total_seconds, results_json)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (user_id, total_questions, correct_count, score_pct, total_seconds,
          json.dumps({"results": results, "category_breakdown": category_breakdown, "concept_breakdown": concept_breakdown})))
    exam_id = cur.lastrowid
    
    db.commit()
    db.close()
    
    # Build concept breakdown with percentages
    concept_report = []
    for concept, data in sorted(concept_breakdown.items(), key=lambda x: x[1]["total"], reverse=True):
        pct = round(100 * data["correct"] / data["total"]) if data["total"] > 0 else 0
        concept_report.append({
            "concept": concept,
            "correct": data["correct"],
            "total": data["total"],
            "pct": pct,
        })
    
    # Category report
    category_report = []
    for cat, data in category_breakdown.items():
        pct = round(100 * data["correct"] / data["total"]) if data["total"] > 0 else 0
        category_report.append({
            "category": cat,
            "label": data["label"],
            "correct": data["correct"],
            "total": data["total"],
            "pct": pct,
        })
    
    # Time analysis
    avg_time = round(sum(time_per_question) / len(time_per_question), 1) if time_per_question else 0
    slowest = sorted(enumerate(results), key=lambda x: x[1]["seconds"], reverse=True)[:5]
    
    return jsonify({
        "exam_id": exam_id,
        "score": {
            "correct": correct_count,
            "total": total_questions,
            "answered": answered_count,
            "unanswered": unanswered_count,
            "pct": score_pct,
            "answered_pct": answered_pct,
            "points": points,
            "out_of": 100,
            "grade_letter": "A" if score_pct >= 93 else "A-" if score_pct >= 90 else "B+" if score_pct >= 87 else "B" if score_pct >= 83 else "B-" if score_pct >= 80 else "C+" if score_pct >= 77 else "C" if score_pct >= 73 else "C-" if score_pct >= 70 else "D+" if score_pct >= 67 else "D" if score_pct >= 60 else "F",
        },
        "categories": category_report,
        "concepts": concept_report,
        "time": {
            "total_seconds": total_seconds,
            "total_minutes": round(total_seconds / 60, 1),
            "avg_per_question": avg_time,
            "target_per_question": 112.5,
        },
        "results": results,
        "wrong_questions": [r for r in results if r.get("answered") and not r["correct"]],
        "unanswered_questions": [r for r in results if not r.get("answered")],
    })


@app.route("/api/exam_history", methods=["POST"])
def exam_history():
    """Get past exam attempts for a user."""
    d = request.json
    user_id = d["user_id"]
    
    db = sqlite3.connect(str(DB_PATH))
    cur = db.cursor()
    
    # Ensure table exists
    cur.execute("""
        CREATE TABLE IF NOT EXISTS exam_attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            total_questions INTEGER,
            correct INTEGER,
            score_pct REAL,
            total_seconds REAL,
            results_json TEXT
        )
    """)
    
    cur.execute("""
        SELECT id, timestamp, total_questions, correct, score_pct, total_seconds
        FROM exam_attempts WHERE user_id = ? ORDER BY timestamp DESC LIMIT 20
    """, (user_id,))
    rows = cur.fetchall()
    db.close()
    
    attempts = []
    for row in rows:
        attempts.append({
            "id": row[0],
            "timestamp": row[1],
            "total_questions": row[2],
            "correct": row[3],
            "score_pct": row[4],
            "total_seconds": row[5],
            "total_minutes": round(row[5] / 60, 1) if row[5] else 0,
        })
    
    return jsonify({"attempts": attempts, "count": len(attempts)})


@app.route("/api/exam_review", methods=["POST"])
def exam_review():
    """Get full exam results for review, including enriched question data."""
    d = request.json
    exam_id = d["exam_id"]
    user_id = d["user_id"]
    
    db = sqlite3.connect(str(DB_PATH))
    db.row_factory = sqlite3.Row
    cur = db.cursor()
    
    cur.execute("SELECT * FROM exam_attempts WHERE id = ? AND user_id = ?", (exam_id, user_id))
    attempt = cur.fetchone()
    if not attempt:
        db.close()
        return jsonify({"error": "Exam not found"}), 404
    
    stored = json.loads(attempt["results_json"])
    results = stored.get("results", [])
    
    # Enrich each question with full data (choices, chart_table, graph_spec, figure_image)
    enriched = []
    for r in results:
        cur.execute("""SELECT id, question_text, correct_answer, answer_choices, chart_table, 
                       graph_spec, figure_image, concept_tags, question_type, has_chart, source_exam
                       FROM questions WHERE id = ?""", (r["question_id"],))
        qrow = cur.fetchone()
        if qrow:
            enriched.append({
                "id": qrow["id"],
                "text": qrow["question_text"],
                "correct_answer": qrow["correct_answer"],
                "user_answer": r.get("user_answer", ""),
                "correct": r.get("correct", False),
                "choices": json.loads(qrow["answer_choices"]) if qrow["answer_choices"] else {},
                "chart_table": qrow["chart_table"] or "",
                "graph_spec": json.loads(qrow["graph_spec"]) if qrow["graph_spec"] else None,
                "figure_image": qrow["figure_image"] or "",
                "concepts": json.loads(qrow["concept_tags"]) if qrow["concept_tags"] else [],
                "question_type": qrow["question_type"],
                "has_chart": bool(qrow["has_chart"]),
                "source_exam": qrow["source_exam"] or "",
                "seconds": r.get("seconds", 0),
            })
    
    db.close()
    
    return jsonify({
        "exam_id": exam_id,
        "timestamp": attempt["timestamp"],
        "score_pct": attempt["score_pct"],
        "correct": attempt["correct"],
        "total": attempt["total_questions"],
        "total_seconds": attempt["total_seconds"],
        "categories": stored.get("category_breakdown", {}),
        "concept_breakdown": stored.get("concept_breakdown", {}),
        "questions": enriched,
    })


@app.route("/api/exam_reinforce", methods=["POST"])
def exam_reinforce():
    """Feed exam wrong answers into FSRS so the drill algorithm learns from them."""
    d = request.json
    exam_id = d["exam_id"]
    user_id = d["user_id"]
    
    db = sqlite3.connect(str(DB_PATH))
    db.row_factory = sqlite3.Row
    cur = db.cursor()
    
    cur.execute("SELECT results_json FROM exam_attempts WHERE id = ? AND user_id = ?", (exam_id, user_id))
    row = cur.fetchone()
    if not row:
        db.close()
        return jsonify({"error": "Exam not found"}), 404
    
    stored = json.loads(row["results_json"])
    results = stored.get("results", [])
    
    reinforced = 0
    skipped = 0
    for r in results:
        qid = r["question_id"]
        user_ans = r.get("user_answer", "")
        secs = r.get("seconds", 0)
        
        # SKIP unanswered questions — don't pollute FSRS with fake "wrong" data
        if not user_ans or not user_ans.strip():
            skipped += 1
            continue
        
        # Use quiz_answer to properly update FSRS + concept_mastery
        # This feeds the exam performance back into the learning algorithm
        try:
            quiz_answer(user_id, qid, user_ans, secs)
            reinforced += 1
        except Exception as e:
            print(f"Reinforce error for {qid}: {e}")
    
    db.close()
    return jsonify({"reinforced": reinforced, "skipped_unanswered": skipped, "total": len(results)})


# === SIMILAR QUESTION GENERATOR ===

@app.route("/api/generate_similar", methods=["POST"])
def generate_similar():
    """Generate 2-3 similar questions for a missed exam question."""
    d = request.json
    user_id = d["user_id"]
    question_id = d["question_id"]
    user_answer = d.get("user_answer", "")
    count = d.get("count", 3)
    
    result = generate_for_missed_question(question_id, user_answer, user_id, count=count)
    return jsonify(result)


@app.route("/api/similar_feedback", methods=["POST"])
def similar_feedback():
    """Record thumbs up/down + note for a generated question."""
    d = request.json
    user_id = d["user_id"]
    question_id = d["question_id"]
    rating = d["rating"]  # "up" or "down"
    note = d.get("note", "")
    parent_id = d.get("parent_question_id", "")
    
    db = sqlite3.connect(str(DB_PATH))
    _ensure_generated_tables(db)
    cur = db.cursor()
    
    # Save feedback
    cur.execute("""
        INSERT INTO similar_feedback (question_id, user_id, rating, note, parent_question_id)
        VALUES (?, ?, ?, ?, ?)
    """, (question_id, user_id, rating, note, parent_id))
    
    # Get the generated question details for the notification
    cur.execute("SELECT question_text, correct_answer, explanation FROM generated_questions WHERE id = ?", (question_id,))
    gen_q = cur.fetchone()
    
    # Get the parent question text
    cur.execute("SELECT question_text FROM questions WHERE id = ?", (parent_id,))
    parent_q = cur.fetchone()
    
    db.commit()
    db.close()
    
    # Build notification message
    emoji = "👍" if rating == "up" else "👎"
    gen_text = gen_q[0][:150] if gen_q else "?"
    parent_text = parent_q[0][:120] if parent_q else "?"
    
    notification = f"""{emoji} Similar Q Feedback from {user_id}

Rating: {rating.upper()}
{f'Note: {note}' if note else ''}

Generated Q: {gen_text}...
Answer: {gen_q[1] if gen_q else '?'}

Original missed Q: {parent_text}...
Parent ID: {parent_id[:12]}
Gen ID: {question_id}

Please review this feedback and adjust the generator if needed."""
    
    # Write to feedback log
    try:
        feedback_log = FEEDBACK_LOG
        with open(feedback_log, "a") as f:
            f.write(json.dumps({
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "user_id": user_id,
                "question_id": question_id,
                "parent_id": parent_id,
                "rating": rating,
                "note": note,
                "gen_text": gen_text,
                "gen_answer": gen_q[1] if gen_q else "?",
            }) + "\n")
    except:
        pass
    
    # Send notification via Telegram (optional, configure in .env)
    try:
        import urllib.request
        tg_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        tg_chat = os.getenv("TELEGRAM_CHAT_ID", os.getenv("HERMES_ADMIN_CHAT_ID", ""))
        if not tg_chat:
            allowed = os.getenv("TELEGRAM_ALLOWED_USERS", "")
            if allowed:
                tg_chat = allowed.split(",")[0].strip()
        if tg_token and tg_chat:
            tg_data = json.dumps({
                "chat_id": tg_chat,
                "text": notification,
            }).encode()
            req = urllib.request.Request(
                f"https://api.telegram.org/bot{tg_token}/sendMessage",
                data=tg_data,
                headers={"Content-Type": "application/json"},
            )
            urllib.request.urlopen(req, timeout=5)
    except Exception as e:
        print(f"Telegram notification failed: {e}")
    
    return jsonify({"saved": True, "rating": rating, "question_id": question_id})


@app.route("/api/answer_similar", methods=["POST"])
def answer_similar():
    """Submit an answer for a generated question. Feeds into FSRS via concept mastery."""
    d = request.json
    user_id = d["user_id"]
    question_id = d["question_id"]
    user_answer = d.get("user_answer", "").upper()
    seconds = d.get("seconds", 0)
    
    db = sqlite3.connect(str(DB_PATH))
    db.row_factory = sqlite3.Row
    cur = db.cursor()
    
    cur.execute("SELECT * FROM generated_questions WHERE id = ?", (question_id,))
    q = cur.fetchone()
    if not q:
        db.close()
        return jsonify({"error": "Question not found"}), 404
    
    correct = user_answer == q["correct_answer"].upper()
    
    # Log the review
    cur.execute("""
        INSERT INTO reviews (user_id, question_id, user_answer, correct, time_spent_seconds, explanation_chunks)
        VALUES (?, ?, ?, ?, ?, '[]')
    """, (user_id, question_id, user_answer, correct, seconds))
    
    # Update concept mastery for the concepts this question covers
    concept_tags = json.loads(q["concept_tags"]) if q["concept_tags"] else []
    for concept in concept_tags:
        if concept == "general":
            continue
        cur.execute("""
            INSERT INTO concept_mastery (user_id, concept_id, total_attempts, correct_attempts, mastery_pct)
            VALUES (?, ?, 1, ?, ?)
            ON CONFLICT(user_id, concept_id) DO UPDATE SET
                total_attempts = total_attempts + 1,
                correct_attempts = correct_attempts + ?,
                mastery_pct = ROUND(100.0 * (correct_attempts + ?) / (total_attempts + 1), 1),
                proven = CASE WHEN ROUND(100.0 * (correct_attempts + ?) / (total_attempts + 1), 1) >= 80 
                              AND total_attempts + 1 >= 3 THEN 1 ELSE 0 END
        """, (user_id, concept, int(correct), 100.0 if correct else 0.0,
              int(correct), int(correct), int(correct)))
    
    db.commit()
    db.close()
    
    return jsonify({
        "correct": correct,
        "correct_answer": q["correct_answer"],
        "explanation": q["explanation"] or "",
        "question_id": question_id,
    })


@app.route("/api/custom_exam", methods=["POST"])
def custom_exam():
    """Serve a custom exam from a named set of questions."""
    d = request.json
    user_id = d["user_id"]
    exam_name = d.get("exam_name", "")
    
    db = sqlite3.connect(str(DB_PATH))
    db.row_factory = sqlite3.Row
    cur = db.cursor()
    
    if exam_name:
        # Get ALL questions for this named exam set
        cur.execute("SELECT * FROM questions WHERE source_exam = ? ORDER BY RANDOM()", (exam_name,))
        gen_rows = cur.fetchall()
    else:
        gen_rows = []
    
    # If the named exam has 40 questions, serve it directly (it's a complete exam)
    unseen_rows = []
    if len(gen_rows) >= 40:
        all_rows = list(gen_rows)
    else:
        # Get unseen real questions to fill remaining slots
        cur.execute("""
            SELECT * FROM questions WHERE source_exam != 'generated'
            AND NOT EXISTS (SELECT 1 FROM reviews r WHERE r.question_id = questions.id AND r.user_id = ?)
            ORDER BY RANDOM()
        """, (user_id,))
        unseen_rows = cur.fetchall()
        all_rows = list(unseen_rows) + list(gen_rows)
    
    # Format questions
    import random
    questions = []
    for row in all_rows[:40]:
        q = {
            "id": row["id"],
            "text": row["question_text"],
            "choices": json.loads(row["answer_choices"]) if row["answer_choices"] else {},
            "correct_answer": row["correct_answer"],
            "concept_tags": json.loads(row["concept_tags"]) if row["concept_tags"] else [],
            "concepts": json.loads(row["concept_tags"]) if row["concept_tags"] else [],
            "question_type": row["question_type"],
            "has_chart": bool(row["has_chart"]),
            "chart_table": row["chart_table"] or "",
            "graph_spec": json.loads(row["graph_spec"]) if row["graph_spec"] else None,
            "figure_image": row["figure_image"] or "",
            "source_exam": row["source_exam"],
        }
        questions.append(q)
    
    random.shuffle(questions)
    db.close()
    
    return jsonify({
        "questions": questions,
        "count": len(questions),
        "mode": "custom_exam",
        "exam_name": exam_name,
        "unseen_count": min(len(unseen_rows), 40),
        "generated_count": min(len(gen_rows), max(0, 40 - len(unseen_rows))),
    })


@app.route("/api/delete_question", methods=["POST"])
def delete_question():
    """Delete a generated question. Only works for source_exam='generated'."""
    d = request.json
    question_id = d["question_id"]
    
    db = sqlite3.connect(str(DB_PATH))
    cur = db.cursor()
    
    # Only allow deleting generated questions
    cur.execute("SELECT source_exam FROM questions WHERE id = ?", (question_id,))
    row = cur.fetchone()
    if not row or row[0] != "generated":
        db.close()
        return jsonify({"error": "Can only delete generated questions"}), 403
    
    cur.execute("DELETE FROM questions WHERE id = ?", (question_id,))
    cur.execute("DELETE FROM generated_questions WHERE id = ?", (question_id,))
    cur.execute("DELETE FROM reviews WHERE question_id = ?", (question_id,))
    db.commit()
    db.close()
    
    return jsonify({"deleted": True, "question_id": question_id})


# === PACK API ===

@app.route("/api/packs")
def api_packs():
    """List all available course packs."""
    return jsonify({"packs": list_packs(), "active": ACTIVE_PACK})


@app.route("/api/pack/select", methods=["POST"])
def api_pack_select():
    """Switch the active course pack."""
    global SLIDES_COL
    d = request.json
    pack_name = d.get("pack_id", "")
    if not pack_name:
        return jsonify({"error": "pack_id required"}), 400
    try:
        load_pack(pack_name)
        # Reload ChromaDB collection for new pack
        try:
            SLIDES_COL = _chroma.get_collection(f"{pack_name}_slides", embedding_function=_slide_embed)
        except:
            SLIDES_COL = None
        # Clear all agent caches so system prompts refresh
        AGENTS.clear()
        return jsonify({"success": True, "pack": PACK_CONFIG})
    except Exception as e:
        return jsonify({"error": str(e)}), 404


@app.route("/api/health")
def health():
    active = len(AGENTS)
    return jsonify({
        "status": "ok",
        "active_agents": active,
        "active_pack": ACTIVE_PACK,
        "pack_name": PACK_CONFIG.get("name", ""),
        "concepts": len(CONCEPT_MAP),
    })

if __name__ == "__main__":
    port = int(os.environ.get("CRAM_IT_PORT", 3000))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
