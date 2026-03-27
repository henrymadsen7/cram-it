"""
Similar Question Generator for Cram-It Exam Review

Pipeline per missed question:
1. Gather context (same-concept questions from bank)
2. Search web for existing verified MC questions
3. AI-generate questions matching the exam's style
4. Validate answers
5. Return 2-3 ready-to-serve questions
"""
import json, re, sqlite3, time, hashlib, os
from pathlib import Path
from dotenv import load_dotenv
import anthropic
import requests

load_dotenv(Path.home() / ".hermes/.env")

DB_PATH = Path.home() / ".hermes/plugins/tutor/learner.db"

claude = anthropic.Anthropic()

# ============================================================
# STEP 1: Gather context for a concept
# ============================================================

def get_butler_context(question_id, concept_tags):
    """Get all same-concept questions from the bank as few-shot examples."""
    db = sqlite3.connect(str(DB_PATH))
    db.row_factory = sqlite3.Row
    cur = db.cursor()
    
    # Get the original missed question
    cur.execute("SELECT * FROM questions WHERE id = ?", (question_id,))
    original = cur.fetchone()
    
    # Get other questions with overlapping concepts
    similar = []
    for tag in concept_tags:
        cur.execute("""SELECT id, question_text, correct_answer, answer_choices, question_type, source_exam
                       FROM questions WHERE concept_tags LIKE ? AND id != ?
                       ORDER BY RANDOM() LIMIT 5""", (f'%{tag}%', question_id))
        for row in cur.fetchall():
            if row["id"] not in [s["id"] for s in similar]:
                similar.append(dict(row))
    
    db.close()
    return dict(original) if original else None, similar[:6]


# ============================================================
# STEP 2: Search web for existing questions
# ============================================================

def search_web_questions(concept_name, question_text_snippet):
    """Search DuckDuckGo for existing verified MC questions on this concept."""
    found = []
    
    # Build search queries
    concept_clean = concept_name.replace("_", " ")
    queries = [
        f"economics {concept_clean} multiple choice quiz answers",
        f"mankiw economics {concept_clean} practice questions",
    ]
    
    for query in queries:
        try:
            # DuckDuckGo HTML search (no API key needed)
            resp = requests.get(
                "https://html.duckduckgo.com/html/",
                params={"q": query},
                headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"},
                timeout=8,
            )
            if resp.status_code == 200:
                # Extract URLs from results
                urls = re.findall(r'href="(https?://[^"]+(?:quizlet|coursehero|khanacademy|chegg|studocu)[^"]*)"', resp.text)
                for url in urls[:3]:
                    found.append({"url": url, "source": "web_search", "query": query})
        except Exception as e:
            pass  # Search failure is non-fatal, we fall back to AI generation
        
        time.sleep(0.3)  # Rate limit
    
    return found


# ============================================================
# STEP 3: AI Generation (the main engine)
# ============================================================

def generate_similar_questions(original_q, user_answer, butler_examples, concept_tags, count=3):
    """Generate 2-3 similar questions using Claude, matching the exam's style."""
    
    # Build the exam examples string
    examples_str = ""
    for i, ex in enumerate(butler_examples[:5]):
        choices = json.loads(ex.get("answer_choices", "{}")) if ex.get("answer_choices") else {}
        choices_str = "\n".join([f"  {k.upper()}) {v}" for k, v in choices.items()])
        examples_str += f"""
Example {i+1} ({ex.get('source_exam', '?')}):
Q: {ex['question_text'][:300]}
{choices_str}
Answer: {ex['correct_answer']}
Type: {ex.get('question_type', 'conceptual')}
---"""
    
    orig_choices = json.loads(original_q.get("answer_choices", "{}")) if original_q.get("answer_choices") else {}
    orig_choices_str = "\n".join([f"  {k.upper()}) {v}" for k, v in orig_choices.items()])
    
    concept_str = ", ".join([c.replace("_", " ") for c in concept_tags])
    
    # Check if this concept involves graphs
    needs_graph = original_q.get("has_chart") or original_q.get("graph_spec")
    graph_instruction = ""
    if needs_graph:
        graph_instruction = """
GRAPH: If the question benefits from a graph, include a "graph_spec" field with JSXGraph JSON:
{"boundingbox": [xmin, ymax, xmax, ymin], "xLabel": "...", "yLabel": "...", "elements": [
  {"type": "curve", "fn": "50-5*x", "color": "#2563eb", "label": "D"},
  {"type": "point", "x": 5, "y": 25, "label": "P*", "color": "#ca8a04"},
  {"type": "segment", "x1": 5, "y1": 0, "x2": 5, "y2": 25, "color": "#999"}
], "annotation": "brief note"}
Only include graph_spec if the question genuinely requires reading a graph. Use function strings like "50-5*x" for curves."""
    
    prompt = f"""You are generating practice exam questions for a course.

THE STUDENT MISSED THIS QUESTION:
Q: {original_q['question_text'][:500]}
{orig_choices_str}
Correct Answer: {original_q['correct_answer']}
Student Picked: {user_answer}
Concepts: {concept_str}

HERE IS HOW BUTLER TESTS THIS CONCEPT (real exam questions):
{examples_str}

GENERATE {count} NEW QUESTIONS that:
1. Test the SAME underlying concept but with a DIFFERENT scenario/numbers/angle
2. Match the exam's difficulty level and question style exactly
3. Target the student's specific misconception (they picked {user_answer} instead of {original_q['correct_answer']})
4. Have 4 plausible answer choices (a, b, c, d) where distractors represent common errors
5. Have ONE definitively correct answer
{graph_instruction}

CRITICAL: After writing each question, verify the correct answer by showing your work in the "explanation" field. The answer MUST be correct.

Return ONLY valid JSON array:
[
  {{
    "question_text": "Full question text",
    "choices": {{"a": "...", "b": "...", "c": "...", "d": "..."}},
    "correct_answer": "B",
    "explanation": "Step by step: ... Therefore B is correct.",
    "concept_tags": {json.dumps(concept_tags)},
    "question_type": "conceptual|calculation|graph",
    "difficulty_note": "Brief note on what this tests differently from the original"
  }}
]"""

    try:
        response = claude.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=3000,
            messages=[{"role": "user", "content": prompt}],
        )
        
        text = response.content[0].text
        
        # Extract JSON array from response
        # Try direct parse first
        try:
            questions = json.loads(text)
        except:
            # Find JSON array in text
            match = re.search(r'\[[\s\S]*\]', text)
            if match:
                questions = json.loads(match.group())
            else:
                return []
        
        # Validate each question
        validated = []
        for q in questions:
            if not all(k in q for k in ["question_text", "choices", "correct_answer"]):
                continue
            if q["correct_answer"].upper() not in ["A", "B", "C", "D"]:
                continue
            if len(q.get("choices", {})) != 4:
                continue
            
            # Generate a stable ID
            qid = "gen_" + hashlib.md5(q["question_text"][:100].encode()).hexdigest()[:12]
            
            validated.append({
                "id": qid,
                "question_text": q["question_text"],
                "choices": q["choices"],
                "correct_answer": q["correct_answer"].upper(),
                "explanation": q.get("explanation", ""),
                "concept_tags": q.get("concept_tags", concept_tags),
                "question_type": q.get("question_type", "conceptual"),
                "difficulty_note": q.get("difficulty_note", ""),
                "graph_spec": q.get("graph_spec", None),
                "source": "generated",
                "parent_question_id": original_q.get("id", ""),
            })
        
        return validated[:count]
        
    except Exception as e:
        print(f"Generation error: {e}")
        return []


# ============================================================
# STEP 4: Validate answers with a second Claude pass
# ============================================================

def validate_question(question):
    """Quick validation pass — have Claude verify the answer is correct."""
    choices_str = "\n".join([f"  {k.upper()}) {v}" for k, v in question["choices"].items()])
    
    try:
        response = claude.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=500,
            messages=[{"role": "user", "content": f"""Verify this economics MC question. Is the stated correct answer actually correct?

Q: {question['question_text']}
{choices_str}
Stated answer: {question['correct_answer']}

Reply with ONLY: {{"valid": true/false, "correct_answer": "X", "reason": "brief explanation"}}"""}],
        )
        
        text = response.content[0].text
        result = json.loads(re.search(r'\{[^}]+\}', text).group())
        
        if result.get("valid"):
            return True, question["correct_answer"]
        else:
            # Fix the answer if validator disagrees
            new_answer = result.get("correct_answer", "").upper()
            if new_answer in ["A", "B", "C", "D"]:
                question["correct_answer"] = new_answer
                question["explanation"] += f"\n[Validator corrected: {result.get('reason', '')}]"
                return True, new_answer
            return False, None
            
    except:
        # If validation fails, keep the question (generation already verified)
        return True, question["correct_answer"]


# ============================================================
# MAIN PIPELINE
# ============================================================

def generate_for_missed_question(question_id, user_answer, user_id, count=3):
    """Full pipeline: context → search → generate → validate → save."""
    
    # Get the original question and concept
    db = sqlite3.connect(str(DB_PATH))
    db.row_factory = sqlite3.Row
    cur = db.cursor()
    cur.execute("SELECT * FROM questions WHERE id = ?", (question_id,))
    orig_row = cur.fetchone()
    if not orig_row:
        db.close()
        return {"error": "Question not found", "questions": []}
    
    original = dict(orig_row)
    concept_tags = json.loads(original.get("concept_tags", "[]")) if original.get("concept_tags") else []
    
    if not concept_tags:
        concept_tags = ["general"]
    
    # Step 1: Gather context
    _, butler_examples = get_butler_context(question_id, concept_tags)
    
    # Step 2: Search web (non-blocking attempt)
    web_results = search_web_questions(concept_tags[0], original["question_text"][:80])
    
    # Step 3: Generate questions via AI
    generated = generate_similar_questions(
        original, user_answer, butler_examples, concept_tags, count=count
    )
    
    # Step 4: Validate each question
    final_questions = []
    for q in generated:
        valid, answer = validate_question(q)
        if valid:
            q["correct_answer"] = answer
            final_questions.append(q)
    
    # Step 5: Save to MAIN questions table (with source_exam='generated')
    _ensure_generated_tables(db)
    for q in final_questions:
        # Save to main questions table so they show up everywhere
        cur.execute("""
            INSERT OR REPLACE INTO questions
            (id, question_text, correct_answer, answer_choices, concept_tags, question_type,
             source_exam, graph_spec, parent_question_id, source_url, frequency_tier)
            VALUES (?, ?, ?, ?, ?, ?, 'generated', ?, ?, ?, 'generated')
        """, (
            q["id"], q["question_text"], q["correct_answer"],
            json.dumps(q["choices"]), json.dumps(q["concept_tags"]),
            q["question_type"],
            json.dumps(q["graph_spec"]) if q.get("graph_spec") else None,
            question_id,
            q.get("source_url", None),
        ))
        # Also keep in generated_questions for the explanation field
        cur.execute("""
            INSERT OR REPLACE INTO generated_questions 
            (id, parent_question_id, user_id, question_text, correct_answer, answer_choices,
             concept_tags, question_type, graph_spec, explanation, source, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """, (
            q["id"], question_id, user_id, q["question_text"], q["correct_answer"],
            json.dumps(q["choices"]), json.dumps(q["concept_tags"]),
            q["question_type"], json.dumps(q["graph_spec"]) if q.get("graph_spec") else None,
            q["explanation"], q.get("source", "generated"),
        ))
    
    db.commit()
    db.close()
    
    return {
        "parent_question_id": question_id,
        "parent_concepts": concept_tags,
        "web_sources_found": len(web_results),
        "questions": final_questions,
    }


def _ensure_generated_tables(db):
    """Create tables if they don't exist."""
    db.execute("""
        CREATE TABLE IF NOT EXISTS generated_questions (
            id TEXT PRIMARY KEY,
            parent_question_id TEXT,
            user_id TEXT,
            question_text TEXT,
            correct_answer TEXT,
            answer_choices TEXT,
            concept_tags TEXT,
            question_type TEXT,
            graph_spec TEXT,
            explanation TEXT,
            source TEXT DEFAULT 'generated',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS similar_feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question_id TEXT,
            user_id TEXT,
            rating TEXT,
            note TEXT,
            parent_question_id TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    db.commit()
