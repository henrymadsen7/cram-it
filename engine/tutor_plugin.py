#!/usr/bin/env python3
"""
Cram-It Tutor Plugin
Exposes quiz tools: quiz_start, quiz_answer, quiz_explain, quiz_progress, quiz_compare, quiz_similar
"""

import json
import sqlite3
import random
from datetime import datetime, timezone, timedelta
from pathlib import Path

import chromadb
from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction
from fsrs import Scheduler, Card, Rating

# === PATHS ===
# Configurable via CRAM_IT_DATA_DIR env var; defaults to ./data/ relative to project root
import os as _os
_project_root = Path(__file__).resolve().parent.parent
TUTOR_DIR = Path(_os.environ.get('CRAM_IT_DATA_DIR', str(_project_root / "data")))
TUTOR_DIR.mkdir(parents=True, exist_ok=True)
CHROMA_DIR = TUTOR_DIR / "chroma_db"
DB_PATH = TUTOR_DIR / "learner.db"
SCOPE_PATH = TUTOR_DIR / "scope.json"

# === GLOBALS (lazy init) ===
_embed_fn = None
_chroma_client = None
_textbook_col = None
_exam_col = None
_fsrs = None
_scope = None


def _get_embed_fn():
    global _embed_fn
    if _embed_fn is None:
        _embed_fn = SentenceTransformerEmbeddingFunction(model_name="all-MiniLM-L6-v2")
    return _embed_fn


def _get_chroma():
    global _chroma_client, _textbook_col, _exam_col
    if _chroma_client is None:
        ef = _get_embed_fn()
        _chroma_client = chromadb.PersistentClient(path=str(CHROMA_DIR))
        _textbook_col = _chroma_client.get_collection("textbook", embedding_function=ef)
        _exam_col = _chroma_client.get_collection("exam_questions", embedding_function=ef)
    return _textbook_col, _exam_col


def _get_db():
    return sqlite3.connect(str(DB_PATH))


def _get_fsrs():
    global _fsrs
    if _fsrs is None:
        _fsrs = Scheduler()
    return _fsrs


PROFILES_DIR = TUTOR_DIR / "profiles"
PROFILES_DIR.mkdir(parents=True, exist_ok=True)

def _update_profile(user_id):
    """Rebuild the user's learning profile markdown from their data."""
    db = _get_db()
    cur = db.cursor()
    prefs = _get_user_preferences(db, user_id)
    
    # Get mastery data
    cur.execute("""
        SELECT topic, total_attempts, correct_attempts, mastery_pct
        FROM topic_mastery WHERE user_id = ? ORDER BY mastery_pct DESC
    """, (user_id,))
    topics = cur.fetchall()
    
    mastered = [t for t in topics if t[3] >= 80 and t[1] >= 3]
    weak = [t for t in topics if t[3] < 50 and t[1] >= 2]
    
    # Get recent wrong answers for pattern detection
    cur.execute("""
        SELECT q.question_text, q.topic_tags, q.calculation_type, r.user_answer, q.correct_answer
        FROM reviews r JOIN questions q ON r.question_id = q.id
        WHERE r.user_id = ? AND r.correct = 0
        ORDER BY r.timestamp DESC LIMIT 10
    """, (user_id,))
    recent_wrong = cur.fetchall()
    
    # Overall stats
    cur.execute("SELECT COUNT(*), SUM(correct) FROM reviews WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    total = row[0] or 0
    correct = row[1] or 0
    
    # Build markdown
    from datetime import datetime
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    
    md = f"# {prefs['display_name']} — Learning Profile\n"
    md += f"## Updated: {now}\n"
    md += f"## Stats: {correct}/{total} correct ({round(100*correct/total,1) if total else 0}%)\n\n"
    
    md += "### Mastered (80%+ with 3+ attempts)\n"
    if mastered:
        for t in mastered:
            md += f"- {t[0]}: {t[3]}% ({t[2]}/{t[1]})\n"
    else:
        md += "- Nothing mastered yet\n"
    
    md += "\n### Weak Areas (<50% with 2+ attempts)\n"
    if weak:
        for t in weak:
            md += f"- {t[0]}: {t[3]}% ({t[2]}/{t[1]})\n"
    else:
        md += "- No weak areas detected\n"
    
    md += "\n### Recent Mistakes\n"
    if recent_wrong:
        for rw in recent_wrong[:5]:
            topic = json.loads(rw[1])[0] if rw[1] else "unknown"
            md += f"- [{topic}] Answered {rw[3]}, correct was {rw[4]}: {rw[0][:80]}...\n"
    else:
        md += "- None yet\n"
    
    md += "\n### Notes\n"
    # Read existing notes from current file (preserve user notes)
    profile_path = PROFILES_DIR / f"{user_id}.md"
    if profile_path.exists():
        existing = profile_path.read_text()
        notes_idx = existing.find("### Notes\n")
        insights_idx = existing.find("### Chat Insights\n")
        if notes_idx >= 0 and insights_idx >= 0:
            notes_section = existing[notes_idx + len("### Notes\n"):insights_idx].strip()
            if notes_section and notes_section != "- (none yet)":
                md += notes_section + "\n"
            else:
                md += "- (none yet)\n"
        else:
            md += "- (none yet)\n"
        # Preserve chat insights too
        if insights_idx >= 0:
            insights_section = existing[insights_idx + len("### Chat Insights\n"):].strip()
            md += "\n### Chat Insights\n"
            if insights_section and insights_section != "- (none yet)":
                md += insights_section + "\n"
            else:
                md += "- (none yet)\n"
        else:
            md += "\n### Chat Insights\n- (none yet)\n"
    else:
        md += "- (none yet)\n\n### Chat Insights\n- (none yet)\n"
    
    profile_path.write_text(md)
    db.close()
    return md


def _get_profile(user_id):
    """Read the user's current profile."""
    profile_path = PROFILES_DIR / f"{user_id}.md"
    if profile_path.exists():
        return profile_path.read_text()
    return ""


def _get_scope():
    global _scope
    if _scope is None:
        with open(SCOPE_PATH) as f:
            _scope = json.load(f)
    return _scope


def _ensure_user(db, user_id, display_name=None):
    cur = db.cursor()
    cur.execute("SELECT id FROM users WHERE id = ?", (user_id,))
    if not cur.fetchone():
        cur.execute("INSERT INTO users (id, display_name) VALUES (?, ?)",
                     (user_id, display_name or user_id))
        db.commit()


def _get_question_by_id(db, question_id):
    cur = db.cursor()
    cur.execute("SELECT * FROM questions WHERE id = ?", (question_id,))
    row = cur.fetchone()
    if not row:
        return None
    cols = [d[0] for d in cur.description]
    return dict(zip(cols, row))


def _get_user_preferences(db, user_id):
    """Load user preferences. Returns dict or defaults."""
    cur = db.cursor()
    cur.execute("SELECT * FROM user_preferences WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    if not row:
        return {
            "user_id": user_id, "display_name": user_id,
            "tutor_persona": "Albert", "explanation_style": "step-by-step",
            "weak_calc_types": [], "preferred_graph_detail": "annotated",
            "session_count": 0
        }
    return {
        "user_id": row[0], "display_name": row[1],
        "tutor_persona": row[2], "explanation_style": row[3],
        "weak_calc_types": json.loads(row[4] or "[]"),
        "preferred_graph_detail": row[5], "session_count": row[6]
    }


def _update_user_preferences(db, user_id, updates):
    """Update specific preference fields."""
    cur = db.cursor()
    for key, val in updates.items():
        if key in ("explanation_style", "weak_calc_types", "preferred_graph_detail", "session_count", "tutor_persona"):
            if isinstance(val, (list, dict)):
                val = json.dumps(val)
            cur.execute(f"UPDATE user_preferences SET {key} = ? WHERE user_id = ?", (val, user_id))
    db.commit()


def _auto_adapt_preferences(db, user_id):
    """After every 10 answers, auto-update weak_calc_types and explanation_style."""
    cur = db.cursor()

    # Check total reviews
    cur.execute("SELECT COUNT(*) FROM reviews WHERE user_id = ?", (user_id,))
    total = cur.fetchone()[0] or 0
    if total % 10 != 0 or total == 0:
        return  # Only adapt every 10 answers

    # Find weak calc types (< 50% accuracy with >= 2 attempts)
    cur.execute("""
        SELECT q.calculation_type, COUNT(*), SUM(r.correct)
        FROM reviews r JOIN questions q ON r.question_id = q.id
        WHERE r.user_id = ? AND q.calculation_type IS NOT NULL
        GROUP BY q.calculation_type
        HAVING COUNT(*) >= 2
    """, (user_id,))
    weak_calcs = []
    for row in cur.fetchall():
        if row[1] > 0 and (row[2] / row[1]) < 0.5:
            weak_calcs.append(row[0])

    # Check explanation style — if avg time on wrong answers is very short,
    # they might be skipping explanations → switch to concise
    # If they spend a long time, they're reading → keep step-by-step
    cur.execute("""
        SELECT AVG(time_spent_seconds) FROM reviews
        WHERE user_id = ? AND correct = 0
    """, (user_id,))
    avg_wrong_time = cur.fetchone()[0] or 15

    style = "step-by-step"
    if avg_wrong_time < 5:
        style = "concise"
    elif avg_wrong_time > 45:
        style = "analogy-heavy"

    _update_user_preferences(db, user_id, {
        "weak_calc_types": weak_calcs,
        "explanation_style": style,
    })


def _format_question(q):
    """Format a question dict for display."""
    choices = json.loads(q.get("answer_choices") or "{}")
    result = {
        "id": q["id"],
        "text": q["question_text"],
        "choices": choices,
        "question_type": q.get("question_type", "conceptual"),
        "frequency_tier": q.get("frequency_tier", "medium"),
        "has_chart": bool(q.get("has_chart")),
        "chart_table": q.get("chart_table") or None,
        "figure_image": q.get("figure_image") or None,
        "graph_spec": q.get("graph_spec") or None,
        "source_exam": q.get("source_exam", ""),
        "topic_tags": json.loads(q.get("topic_tags") or "[]"),
        "concepts": json.loads(q.get("concept_tags") or "[]"),
        "difficulty_score": q.get("difficulty_score"),
    }
    return result


# ============================================================
# TOOL: quiz_session_start
# ============================================================

def quiz_session_start(user_id):
    """Initialize a session — load preferences, greet user, increment session count."""
    db = _get_db()
    _ensure_user(db, user_id)
    prefs = _get_user_preferences(db, user_id)

    # Increment session count
    new_count = prefs["session_count"] + 1
    _update_user_preferences(db, user_id, {"session_count": new_count})
    prefs["session_count"] = new_count

    # Get quick stats
    cur = db.cursor()
    cur.execute("SELECT COUNT(*), SUM(correct) FROM reviews WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    total = row[0] or 0
    correct = row[1] or 0

    now = datetime.now(timezone.utc).isoformat()
    cur.execute("""
        SELECT COUNT(*) FROM fsrs_state 
        WHERE user_id = ? AND (due_date IS NULL OR due_date <= ?)
    """, (user_id, now))
    due = cur.fetchone()[0]

    db.close()

    return json.dumps({
        "preferences": prefs,
        "greeting": f"Hey {prefs['display_name']}! Session #{new_count}.",
        "persona": prefs["tutor_persona"],
        "stats": {
            "total_answered": total,
            "total_correct": correct,
            "accuracy": round(100 * correct / total, 1) if total > 0 else 0,
            "due_today": due,
        }
    })


# ============================================================
# TOOL: quiz_start
# ============================================================

def quiz_start(user_id, mode="drill", chapter=None, count=10):
    """
    Start a quiz session. Returns JSON array of question objects.
    
    Modes:
    - drill: FSRS-due questions, weighted by frequency_tier
    - chapter: filter to one chapter
    - calc_blitz: only calculation questions
    - weak_spots: lowest mastery topics with ≥3 attempts
    - mock_exam: 30 questions matching exam topic distribution
    - tricky: questions matching known tricky patterns
    """
    db = _get_db()
    _ensure_user(db, user_id)
    cur = db.cursor()

    now = datetime.now(timezone.utc).isoformat()

    if mode == "drill":
        # Smart 4-phase concept-coverage-aware drill selection
        seen_ids = set()
        final_rows = []

        # Phase 1 (30%): FSRS-due questions
        phase1_count = max(1, count * 3 // 10)
        cur.execute("""
            SELECT q.* FROM questions q
            JOIN fsrs_state fs ON q.id = fs.question_id AND fs.user_id = ?
            WHERE fs.due_date <= ?
            ORDER BY
                CASE q.frequency_tier WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END,
                RANDOM()
            LIMIT ?
        """, (user_id, now, phase1_count))
        p1_rows = cur.fetchall()
        cols = [d[0] for d in cur.description]
        for row in p1_rows:
            q = dict(zip(cols, row))
            if q["id"] not in seen_ids:
                seen_ids.add(q["id"])
                final_rows.append(q)

        # Phase 2 (25%): Practice exam & generated questions (different wording teaches better)
        phase2_exam_count = max(1, count * 25 // 100)
        exclude_clause = "AND q.id NOT IN ({})".format(",".join("?" for _ in seen_ids)) if seen_ids else ""
        exam_params = (tuple(seen_ids) + (phase2_exam_count,)) if seen_ids else (phase2_exam_count,)
        cur.execute("""
            SELECT q.* FROM questions q
            WHERE q.source_exam IN ('practice', 'generated', 'custom')
                {}
            ORDER BY
                CASE q.frequency_tier WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END,
                RANDOM()
            LIMIT ?
        """.format(exclude_clause), exam_params)
        pe_rows = cur.fetchall()
        pe_cols = [d[0] for d in cur.description]
        for row in pe_rows:
            q = dict(zip(pe_cols, row))
            if q["id"] not in seen_ids:
                seen_ids.add(q["id"])
                final_rows.append(q)

        # Phase 3 (25%): Concept coverage gaps -- unseen concepts
        phase3_count = max(1, count * 25 // 100)
        cur.execute("SELECT DISTINCT concept_id FROM concept_mastery WHERE user_id = ?", (user_id,))
        seen_concepts = set(r[0] for r in cur.fetchall())

        all_concepts = set()
        cur.execute("SELECT DISTINCT concept_tags FROM questions")
        for row in cur.fetchall():
            for c in json.loads(row[0] or '[]'):
                if c != 'general':
                    all_concepts.add(c)
        unseen_concepts = all_concepts - seen_concepts

        if unseen_concepts:
            # Get questions tagged with unseen concepts, prefer high frequency
            exclude_clause = "AND q.id NOT IN ({})".format(",".join("?" for _ in seen_ids)) if seen_ids else ""
            cur.execute("""
                SELECT q.* FROM questions q
                WHERE 1=1 {}
                ORDER BY
                    CASE q.frequency_tier WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END,
                    RANDOM()
            """.format(exclude_clause), tuple(seen_ids) if seen_ids else ())
            p3_candidates = cur.fetchall()
            p3_cols = [d[0] for d in cur.description]
            p3_added = 0
            for row in p3_candidates:
                if p3_added >= phase3_count:
                    break
                q = dict(zip(p3_cols, row))
                if q["id"] in seen_ids:
                    continue
                q_concepts = set(json.loads(q.get("concept_tags") or "[]"))
                if q_concepts & unseen_concepts:
                    seen_ids.add(q["id"])
                    final_rows.append(q)
                    p3_added += 1

        # Phase 4 (20%): Weak concept reinforcement -- mastery < 50%, attempts >= 2
        phase4_count = max(1, count * 2 // 10)
        cur.execute("""
            SELECT concept_id FROM concept_mastery
            WHERE user_id = ? AND mastery_pct < 50 AND total_attempts >= 2
        """, (user_id,))
        weak_concepts = set(r[0] for r in cur.fetchall())

        if weak_concepts:
            exclude_clause = "AND q.id NOT IN ({})".format(",".join("?" for _ in seen_ids)) if seen_ids else ""
            params = ((user_id,) + tuple(seen_ids)) if seen_ids else (user_id,)
            cur.execute("""
                SELECT q.* FROM questions q
                LEFT JOIN fsrs_state fs ON q.id = fs.question_id AND fs.user_id = ?
                WHERE 1=1 {}
                ORDER BY
                    CASE WHEN fs.state IS NULL THEN 0 ELSE 1 END,
                    CASE q.frequency_tier WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END,
                    RANDOM()
            """.format(exclude_clause), params)
            p4_candidates = cur.fetchall()
            p4_cols = [d[0] for d in cur.description]
            p4_added = 0
            for row in p4_candidates:
                if p4_added >= phase4_count:
                    break
                q = dict(zip(p4_cols, row))
                if q["id"] in seen_ids:
                    continue
                q_concepts = set(json.loads(q.get("concept_tags") or "[]"))
                if q_concepts & weak_concepts:
                    seen_ids.add(q["id"])
                    final_rows.append(q)
                    p4_added += 1

        # Backfill remaining slots with random unseen high-frequency questions
        remaining = count - len(final_rows)
        if remaining > 0:
            exclude_clause = "AND q.id NOT IN ({})".format(",".join("?" for _ in seen_ids)) if seen_ids else ""
            params = ((user_id,) + tuple(seen_ids) + (remaining,)) if seen_ids else (user_id, remaining)
            cur.execute("""
                SELECT q.* FROM questions q
                LEFT JOIN reviews r ON q.id = r.question_id AND r.user_id = ?
                WHERE r.id IS NULL
                    {}
                ORDER BY
                    CASE q.frequency_tier WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END,
                    RANDOM()
                LIMIT ?
            """.format(exclude_clause), params)
            bf_rows = cur.fetchall()
            bf_cols = [d[0] for d in cur.description]
            for row in bf_rows:
                q = dict(zip(bf_cols, row))
                if q["id"] not in seen_ids:
                    seen_ids.add(q["id"])
                    final_rows.append(q)

        # If still not enough, add any random questions
        remaining = count - len(final_rows)
        if remaining > 0:
            exclude_clause = "WHERE q.id NOT IN ({})".format(",".join("?" for _ in seen_ids)) if seen_ids else ""
            params = (tuple(seen_ids) + (remaining,)) if seen_ids else (remaining,)
            cur.execute("""
                SELECT q.* FROM questions q
                {}
                ORDER BY RANDOM()
                LIMIT ?
            """.format(exclude_clause), params)
            extra_rows = cur.fetchall()
            extra_cols = [d[0] for d in cur.description]
            for row in extra_rows:
                q = dict(zip(extra_cols, row))
                if q["id"] not in seen_ids:
                    seen_ids.add(q["id"])
                    final_rows.append(q)

        rows = final_rows[:count]
        if not rows:
            # Absolute fallback
            cur.execute("SELECT q.* FROM questions q ORDER BY RANDOM() LIMIT ?", (count,))
            fb_rows = cur.fetchall()
            fb_cols = [d[0] for d in cur.description]
            rows = [dict(zip(fb_cols, r)) for r in fb_rows]
        # rows is now always a list of dicts

    elif mode == "chapter":
        if chapter is None:
            db.close()
            return json.dumps({"error": "chapter parameter required for chapter mode"})
        ch_str = str(chapter)
        # Match questions whose topic_tags contain chapter-related topics
        cur.execute("""
            SELECT q.* FROM questions q
            ORDER BY 
                CASE q.frequency_tier WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END,
                RANDOM()
        """)
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description]
        # Filter by chapter in topic_tags
        scope = _get_scope()
        chapter_topics = set()
        for t in scope["topics"]:
            if int(chapter) in t.get("chapters", []):
                chapter_topics.add(t["name"])
        
        filtered = []
        for row in rows:
            q = dict(zip(cols, row))
            tags = json.loads(q.get("topic_tags", "[]"))
            if any(t in chapter_topics for t in tags):
                filtered.append(row)
        rows = filtered

    elif mode == "calc_blitz":
        cur.execute("""
            SELECT q.* FROM questions q
            WHERE q.question_type = 'calculation' OR q.calculation_type IS NOT NULL
            ORDER BY RANDOM()
        """)
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description]

    elif mode == "weak_spots":
        cur.execute("""
            SELECT topic, mastery_pct FROM topic_mastery
            WHERE user_id = ? AND total_attempts >= 3
            ORDER BY mastery_pct ASC
            LIMIT 5
        """, (user_id,))
        weak_topics = [row[0] for row in cur.fetchall()]

        if not weak_topics:
            # No mastery data yet, fall back to drill
            return quiz_start(user_id, "drill", count=count)

        cur.execute("SELECT q.* FROM questions q ORDER BY RANDOM()")
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description]
        filtered = []
        for row in rows:
            q = dict(zip(cols, row))
            tags = json.loads(q.get("topic_tags", "[]"))
            if any(t in weak_topics for t in tags):
                filtered.append(row)
        rows = filtered

    elif mode == "mock_exam":
        count = 30
        # Get all questions and sample by frequency tier
        cur.execute("SELECT q.* FROM questions q ORDER BY RANDOM()")
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description]
        
        high, med, low = [], [], []
        for row in rows:
            q = dict(zip(cols, row))
            tier = q.get("frequency_tier", "low")
            if tier == "high":
                high.append(row)
            elif tier == "medium":
                med.append(row)
            else:
                low.append(row)
        
        # Mock exam distribution: ~60% high, ~25% medium, ~15% low
        selected = random.sample(high, min(18, len(high)))
        selected += random.sample(med, min(8, len(med)))
        selected += random.sample(low, min(4, len(low)))
        random.shuffle(selected)
        rows = selected[:30]

    elif mode == "exam":
        # TRUE EXAM MODE: 40 questions weighted by actual topic distribution
        # No feedback during exam. Timed. Matches real exam conditions.
        count = 40
        
        # Approximate exam distribution (40 questions total):
        # Firm Theory (costs, competitive, monopoly): ~24 questions (60%)
        # Consumer & Labor: ~8 questions (21%)
        # Game Theory & Info: ~4 questions (10%)
        # Macro: ~4 questions (10%)
        EXAM_DISTRIBUTION = {
            "firm_theory": {
                "concepts": ["cost_curve_shapes", "profit_max_mr_equals_mc", "shutdown_decision",
                            "supply_curve_and_long_run_eq", "explicit_vs_implicit_costs",
                            "production_function_diminishing_mp", "economies_of_scale",
                            "competitive_firm_price_taker", "monopoly_mr_below_demand",
                            "monopoly_pricing_two_step", "natural_monopoly_regulation",
                            "price_discrimination", "monopolistic_competition_sr_lr"],
                "target": 24,
            },
            "consumer_labor": {
                "concepts": ["budget_constraint_intercepts", "indifference_curves_mrs",
                            "optimal_choice_tangency", "income_substitution_effects",
                            "vmp_and_labor_demand", "labor_supply_shifts",
                            "discrimination_and_human_capital"],
                "target": 8,
            },
            "game_info": {
                "concepts": ["game_theory_nash_dominant", "cartel_instability",
                            "moral_hazard_adverse_selection", "voting_condorcet_arrow"],
                "target": 4,
            },
            "macro": {
                "concepts": ["gdp_real_nominal_deflator", "cpi_inflation_real_interest",
                            "unemployment_types_measurement"],
                "target": 4,
            },
        }
        
        cur.execute("SELECT q.* FROM questions q ORDER BY RANDOM()")
        all_rows = cur.fetchall()
        cols = [d[0] for d in cur.description]
        
        # Bucket questions by category
        buckets = {cat: [] for cat in EXAM_DISTRIBUTION}
        uncategorized = []
        for row in all_rows:
            q = dict(zip(cols, row))
            concept_tags = json.loads(q.get("concept_tags", "[]")) if q.get("concept_tags") else []
            placed = False
            for cat, info in EXAM_DISTRIBUTION.items():
                if any(tag in info["concepts"] for tag in concept_tags):
                    buckets[cat].append(row)
                    placed = True
                    break
            if not placed:
                uncategorized.append(row)
        
        # Sample from each bucket according to distribution
        selected = []
        seen_ids = set()
        for cat, info in EXAM_DISTRIBUTION.items():
            target = info["target"]
            available = [r for r in buckets[cat] if dict(zip(cols, r))["id"] not in seen_ids]
            picked = random.sample(available, min(target, len(available)))
            for r in picked:
                seen_ids.add(dict(zip(cols, r))["id"])
            selected.extend(picked)
        
        # Fill remaining slots from uncategorized or any bucket
        remaining = 40 - len(selected)
        if remaining > 0:
            extras = [r for r in all_rows if dict(zip(cols, r))["id"] not in seen_ids]
            selected.extend(random.sample(extras, min(remaining, len(extras))))
        
        random.shuffle(selected)
        rows = selected[:40]

    elif mode == "tricky":
        scope = _get_scope()
        tricky_keywords = []
        for pattern in scope.get("tricky_patterns", []):
            words = pattern.lower().split()[:4]
            tricky_keywords.extend(words)

        cur.execute("SELECT q.* FROM questions q ORDER BY RANDOM()")
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description]
        filtered = []
        for row in rows:
            q = dict(zip(cols, row))
            text = q.get("question_text", "").lower()
            if any(kw in text for kw in ["shut down", "sunk", "deflation", "discrimination", 
                                          "natural monopoly", "backward", "condorcet", "price taker",
                                          "implicit cost", "accounting profit"]):
                filtered.append(row)
        rows = filtered

    else:
        db.close()
        return json.dumps({"error": f"Unknown mode: {mode}"})

    # Limit and format
    if not isinstance(rows[0], dict) if rows else True:
        if not rows:
            db.close()
            return json.dumps({"questions": [], "count": 0, "mode": mode})
        cols = cols if 'cols' in dir() else [d[0] for d in cur.description]

    questions = []
    for row in rows[:count]:
        if isinstance(row, dict):
            q = row
        else:
            q = dict(zip(cols, row))
        questions.append(_format_question(q))

    # Insert a new session row
    cur.execute("""
        UPDATE sessions SET active = 0, ended_at = CURRENT_TIMESTAMP
        WHERE user_id = ? AND active = 1
    """, (user_id,))
    cur.execute("""
        INSERT INTO sessions (user_id, mode, active)
        VALUES (?, ?, 1)
    """, (user_id, mode))
    session_id = cur.lastrowid
    db.commit()

    db.close()
    return json.dumps({"questions": questions, "count": len(questions), "mode": mode, "session_id": session_id})


# ============================================================
# TOOL: quiz_answer
# ============================================================

def quiz_answer(user_id, question_id, user_answer, seconds_spent=0):
    """Check answer, update FSRS and mastery. Returns feedback."""
    db = _get_db()
    _ensure_user(db, user_id)
    cur = db.cursor()

    q = _get_question_by_id(db, question_id)
    if not q:
        db.close()
        return json.dumps({"error": "Question not found"})

    correct = user_answer.upper() == q["correct_answer"].upper()

    # Insert review with explanation_chunks placeholder
    cur.execute("""
        INSERT INTO reviews (user_id, question_id, user_answer, correct, time_spent_seconds, explanation_chunks)
        VALUES (?, ?, ?, ?, ?, '[]')
    """, (user_id, question_id, user_answer.upper(), correct, seconds_spent))

    # Update active session stats
    cur.execute("""
        UPDATE sessions SET questions_answered = questions_answered + 1, correct = correct + ?
        WHERE user_id = ? AND active = 1
    """, (int(correct), user_id))

    # FSRS update
    fsrs = _get_fsrs()
    cur.execute("SELECT * FROM fsrs_state WHERE user_id = ? AND question_id = ?",
                (user_id, question_id))
    fs_row = cur.fetchone()

    card = Card()
    now = datetime.now(timezone.utc)

    if fs_row:
        # Reconstruct card from saved state
        try:
            card.stability = fs_row[2] if fs_row[2] else None
            card.difficulty = fs_row[3] if fs_row[3] else None
            card.step = fs_row[6] or 0
            # lapses stored in field 7
        except:
            pass
    
    # Determine rating
    if not correct:
        rating = Rating.Again
    elif seconds_spent > 30:
        rating = Rating.Hard
    elif seconds_spent < 10:
        rating = Rating.Easy
    else:
        rating = Rating.Good

    card, review_log = fsrs.review_card(card, rating, now)

    # Save FSRS state
    cur.execute("""
        INSERT OR REPLACE INTO fsrs_state 
        (user_id, question_id, stability, difficulty, due_date, last_review, reps, lapses, state)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        user_id, question_id,
        card.stability, card.difficulty,
        card.due.isoformat(), now.isoformat(),
        getattr(card, 'step', 0), 0, card.state.value
    ))

    # Update topic mastery
    topics = json.loads(q.get("topic_tags", "[]"))
    mastery_updates = {}
    for topic in topics:
        cur.execute("""
            INSERT INTO topic_mastery (user_id, topic, total_attempts, correct_attempts, mastery_pct)
            VALUES (?, ?, 1, ?, ?)
            ON CONFLICT(user_id, topic) DO UPDATE SET
                total_attempts = total_attempts + 1,
                correct_attempts = correct_attempts + ?,
                mastery_pct = ROUND(100.0 * (correct_attempts + ?) / (total_attempts + 1), 1)
        """, (user_id, topic, int(correct), 100.0 if correct else 0.0,
              int(correct), int(correct)))
        
        cur.execute("SELECT mastery_pct FROM topic_mastery WHERE user_id = ? AND topic = ?",
                     (user_id, topic))
        row = cur.fetchone()
        if row:
            mastery_updates[topic] = row[0]

    # Update concept mastery (concept_tags are more granular than topic_tags)
    concepts = json.loads(q.get("concept_tags", "[]") or "[]")
    concept_updates = {}
    for cid in concepts:
        if cid == "general":
            continue
        correct_int = int(correct)
        cur.execute("""
            INSERT INTO concept_mastery (user_id, concept_id, total_attempts, correct_attempts, mastery_pct, proven)
            VALUES (?, ?, 1, ?, ?, 0)
            ON CONFLICT(user_id, concept_id) DO UPDATE SET
                total_attempts = total_attempts + 1,
                correct_attempts = correct_attempts + ?,
                mastery_pct = ROUND(100.0 * (correct_attempts + ?) / (total_attempts + 1), 1),
                proven = CASE WHEN ROUND(100.0 * (correct_attempts + ?) / (total_attempts + 1), 1) >= 80 AND total_attempts + 1 >= 3 THEN 1 ELSE 0 END
        """, (user_id, cid, correct_int, 100.0 if correct else 0.0,
              correct_int, correct_int, correct_int))
        cur.execute("SELECT mastery_pct FROM concept_mastery WHERE user_id = ? AND concept_id = ?",
                     (user_id, cid))
        row = cur.fetchone()
        if row:
            concept_updates[cid] = row[0]

    db.commit()

    # Auto-adapt preferences every 10 answers
    _auto_adapt_preferences(db, user_id)

    # Recalculate difficulty scores every 20 answers
    cur.execute("SELECT COUNT(*) FROM reviews WHERE user_id = ?", (user_id,))
    review_count = cur.fetchone()[0]
    if review_count % 20 == 0:
        try:
            recalculate_difficulty()
        except:
            pass

    # Load current preferences for response
    prefs = _get_user_preferences(db, user_id)

    db.close()

    # Update learning profile
    try:
        _update_profile(user_id)
    except:
        pass

    return json.dumps({
        "correct": correct,
        "correct_answer": q["correct_answer"],
        "user_answer": user_answer.upper(),
        "new_due": card.due.isoformat(),
        "topics": topics,
        "mastery_updates": mastery_updates,
        "concept_updates": concept_updates,
        "rating": rating.name,
        "explanation_style": prefs["explanation_style"],
    })


# ============================================================
# SESSION & DIFFICULTY HELPERS
# ============================================================

def end_session(user_id):
    """End the user's active session."""
    db = _get_db()
    cur = db.cursor()
    cur.execute("""
        UPDATE sessions SET active = 0, ended_at = CURRENT_TIMESTAMP
        WHERE user_id = ? AND active = 1
    """, (user_id,))
    db.commit()
    affected = cur.rowcount
    db.close()
    return json.dumps({"ended": affected > 0, "user_id": user_id})


def recalculate_difficulty():
    """Recalculate difficulty_score for all questions with >=2 reviews."""
    db = _get_db()
    cur = db.cursor()
    # Ensure column exists
    try:
        cur.execute("ALTER TABLE questions ADD COLUMN difficulty_score REAL")
        db.commit()
    except sqlite3.OperationalError:
        pass  # column already exists
    cur.execute("""
        SELECT question_id, COUNT(*) as attempts, AVG(correct) as avg_correct,
               AVG(time_spent_seconds) as avg_time
        FROM reviews GROUP BY question_id HAVING COUNT(*) >= 2
    """)
    rows = cur.fetchall()
    for qid, attempts, avg_correct, avg_time in rows:
        difficulty = max(0.0, min(100.0, (1 - avg_correct) * 100))
        cur.execute("UPDATE questions SET difficulty_score = ? WHERE id = ?", (round(difficulty, 1), qid))
    db.commit()
    db.close()
    return len(rows)


# ============================================================
# TOOL: quiz_explain
# ============================================================

def quiz_explain(question_id):
    """Get textbook context and similar questions for explanation."""
    db = _get_db()
    q = _get_question_by_id(db, question_id)
    db.close()

    if not q:
        return json.dumps({"error": "Question not found"})

    textbook_col, exam_col = _get_chroma()
    scope = _get_scope()

    query_text = q["question_text"]

    # Query textbook for relevant chunks
    tb_results = textbook_col.query(
        query_texts=[query_text],
        n_results=5
    )

    textbook_context = []
    chunk_ids = []
    if tb_results and tb_results["documents"]:
        for doc, meta, cid in zip(tb_results["documents"][0], tb_results["metadatas"][0], tb_results["ids"][0]):
            textbook_context.append({
                "text": doc,
                "chapter": meta.get("chapter", ""),
                "section": meta.get("section", ""),
                "chunk_id": cid,
            })
            chunk_ids.append(cid)

    # Query exam_questions for similar questions from OTHER exams
    eq_results = exam_col.query(
        query_texts=[query_text],
        n_results=5,
        where={"source_exam": {"$ne": q.get("source_exam", "")}}
    )

    similar_questions = []
    if eq_results and eq_results["documents"]:
        for doc, meta in zip(eq_results["documents"][0], eq_results["metadatas"][0]):
            similar_questions.append({
                "text": doc[:300],
                "source": meta.get("source_exam", ""),
                "correct_answer": meta.get("correct_answer", ""),
            })

    # Find relevant calc type formula
    calc_formula = None
    if q.get("calculation_type"):
        for ct in scope.get("calc_types", []):
            if ct["name"] == q["calculation_type"]:
                calc_formula = ct
                break

    # Find relevant tricky pattern
    tricky = None
    q_text_lower = q["question_text"].lower()
    for pattern in scope.get("tricky_patterns", []):
        keywords = pattern.lower().split()[:3]
        if any(kw in q_text_lower for kw in keywords):
            tricky = pattern
            break

    # Backfill the most recent review for this question with chunk IDs
    if chunk_ids:
        try:
            backfill_db = _get_db()
            backfill_db.execute("""
                UPDATE reviews SET explanation_chunks = ?
                WHERE rowid = (
                    SELECT rowid FROM reviews 
                    WHERE question_id = ? 
                    ORDER BY timestamp DESC LIMIT 1
                )
            """, (json.dumps(chunk_ids), question_id))
            backfill_db.commit()
            backfill_db.close()
        except:
            pass

    # Load user prefs for explanation style hint
    user_prefs = None
    try:
        pdb = _get_db()
        cur = pdb.cursor()
        cur.execute("SELECT user_id FROM reviews WHERE question_id = ? ORDER BY timestamp DESC LIMIT 1", (question_id,))
        row = cur.fetchone()
        if row:
            user_prefs = _get_user_preferences(pdb, row[0])
        pdb.close()
    except:
        pass

    return json.dumps({
        "question": {
            "text": q["question_text"],
            "correct_answer": q["correct_answer"],
            "choices": json.loads(q.get("answer_choices", "{}")),
            "topics": json.loads(q.get("topic_tags", "[]")),
            "question_type": q.get("question_type"),
            "has_chart": bool(q.get("has_chart")),
            "chart_table": q.get("chart_table"),
        },
        "textbook_context": textbook_context,
        "chunk_ids": chunk_ids,
        "similar_questions": similar_questions[:3],
        "calc_formula": calc_formula,
        "tricky_pattern": tricky,
        "explanation_style": user_prefs["explanation_style"] if user_prefs else "step-by-step",
    })


# ============================================================
# TOOL: quiz_progress
# ============================================================

def quiz_progress(user_id):
    """Return comprehensive progress report."""
    db = _get_db()
    _ensure_user(db, user_id)
    cur = db.cursor()

    scope = _get_scope()

    # Overall stats
    cur.execute("""
        SELECT COUNT(*), SUM(correct), AVG(time_spent_seconds)
        FROM reviews WHERE user_id = ?
    """, (user_id,))
    row = cur.fetchone()
    total_attempts = row[0] or 0
    total_correct = row[1] or 0
    avg_time = row[2] or 0
    overall_pct = round(100 * total_correct / total_attempts, 1) if total_attempts > 0 else 0

    # Per-topic mastery
    cur.execute("""
        SELECT topic, total_attempts, correct_attempts, mastery_pct
        FROM topic_mastery WHERE user_id = ?
        ORDER BY mastery_pct ASC
    """, (user_id,))
    topic_rows = cur.fetchall()
    topic_mastery = {}
    for t in topic_rows:
        topic_mastery[t[0]] = {"attempts": t[1], "correct": t[2], "pct": t[3]}

    # Per calc-type accuracy
    cur.execute("""
        SELECT q.calculation_type, COUNT(*), SUM(r.correct)
        FROM reviews r JOIN questions q ON r.question_id = q.id
        WHERE r.user_id = ? AND q.calculation_type IS NOT NULL
        GROUP BY q.calculation_type
    """, (user_id,))
    calc_rows = cur.fetchall()
    calc_mastery = {}
    for c in calc_rows:
        calc_mastery[c[0]] = {"attempts": c[1], "correct": c[2], 
                               "pct": round(100 * c[2] / c[1], 1) if c[1] > 0 else 0}

    # Weak topics (bottom 5)
    weak = [{"topic": t[0], "pct": t[3], "attempts": t[1]} 
            for t in topic_rows[:5] if t[1] >= 1]

    # Questions due today
    now = datetime.now(timezone.utc).isoformat()
    cur.execute("""
        SELECT COUNT(*) FROM fsrs_state 
        WHERE user_id = ? AND (due_date IS NULL OR due_date <= ?)
    """, (user_id, now))
    due_today = cur.fetchone()[0]

    # Total unique questions answered
    cur.execute("SELECT COUNT(DISTINCT question_id) FROM reviews WHERE user_id = ?", (user_id,))
    unique_questions = cur.fetchone()[0]

    # Projected exam score (weighted by frequency tier)
    cur.execute("""
        SELECT q.frequency_tier, COUNT(*), SUM(r.correct)
        FROM reviews r JOIN questions q ON r.question_id = q.id
        WHERE r.user_id = ?
        GROUP BY q.frequency_tier
    """, (user_id,))
    tier_rows = cur.fetchall()
    tier_weights = {"high": 3, "medium": 2, "low": 1}
    weighted_sum = 0
    weight_total = 0
    for t in tier_rows:
        tier = t[0] or "low"
        w = tier_weights.get(tier, 1)
        pct = t[2] / t[1] if t[1] > 0 else 0
        weighted_sum += pct * w * t[1]
        weight_total += w * t[1]
    
    projected = round(100 * weighted_sum / weight_total, 1) if weight_total > 0 else 0

    # Study streak (consecutive days with reviews)
    cur.execute("""
        SELECT DISTINCT DATE(timestamp) as d FROM reviews 
        WHERE user_id = ? ORDER BY d DESC
    """, (user_id,))
    dates = [row[0] for row in cur.fetchall()]
    streak = 0
    today = datetime.now().strftime("%Y-%m-%d")
    for i, d in enumerate(dates):
        expected = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
        if d == expected:
            streak += 1
        else:
            break

    # Concept mastery (granular per-concept tracking)
    cur.execute("""
        SELECT concept_id, mastery_pct, total_attempts, proven
        FROM concept_mastery WHERE user_id = ?
    """, (user_id,))
    concept_mastery_data = {}
    concepts_proven = 0
    for r in cur.fetchall():
        concept_mastery_data[r[0]] = {"pct": r[1], "attempts": r[2], "proven": bool(r[3])}
        if r[3]:
            concepts_proven += 1

    db.close()

    return json.dumps({
        "user_id": user_id,
        "overall_pct": overall_pct,
        "total_attempts": total_attempts,
        "total_correct": total_correct,
        "unique_questions_seen": unique_questions,
        "total_questions_available": 120,
        "avg_time_seconds": round(avg_time, 1),
        "topic_mastery": topic_mastery,
        "calc_mastery": calc_mastery,
        "concept_mastery": concept_mastery_data,
        "concepts_proven": concepts_proven,
        "weak_topics": weak,
        "due_today": due_today,
        "projected_exam_score": projected,
        "study_streak_days": streak,
    })


# ============================================================
# TOOL: quiz_compare
# ============================================================

def quiz_compare():
    """Compare all users side-by-side."""
    db = _get_db()
    cur = db.cursor()

    cur.execute("SELECT id, display_name FROM users")
    users = cur.fetchall()

    if len(users) < 2:
        db.close()
        return json.dumps({"message": "Need at least 2 users to compare", "users": len(users)})

    comparison = {}
    for uid, name in users:
        # Overall
        cur.execute("SELECT COUNT(*), SUM(correct) FROM reviews WHERE user_id = ?", (uid,))
        row = cur.fetchone()
        total = row[0] or 0
        correct = row[1] or 0
        
        # Topics
        cur.execute("""
            SELECT topic, mastery_pct FROM topic_mastery 
            WHERE user_id = ? ORDER BY mastery_pct DESC
        """, (uid,))
        topics = {r[0]: r[1] for r in cur.fetchall()}

        strongest = list(topics.keys())[:3] if topics else []
        weakest = list(topics.keys())[-3:] if topics else []

        comparison[uid] = {
            "display_name": name or uid,
            "overall_pct": round(100 * correct / total, 1) if total > 0 else 0,
            "total_attempts": total,
            "topic_mastery": topics,
            "strongest": strongest,
            "weakest": weakest,
        }

    db.close()
    return json.dumps(comparison)


# ============================================================
# TOOL: quiz_similar
# ============================================================

def quiz_similar(question_id):
    """Find similar questions from other exams."""
    db = _get_db()
    q = _get_question_by_id(db, question_id)
    db.close()

    if not q:
        return json.dumps({"error": "Question not found"})

    _, exam_col = _get_chroma()

    results = exam_col.query(
        query_texts=[q["question_text"]],
        n_results=5,
        where={"source_exam": {"$ne": q.get("source_exam", "")}}
    )

    similar = []
    if results and results["documents"]:
        for doc, meta, dist in zip(results["documents"][0], results["metadatas"][0], results["distances"][0]):
            similar.append({
                "text": doc[:400],
                "source_exam": meta.get("source_exam", ""),
                "correct_answer": meta.get("correct_answer", ""),
                "similarity": round(1 - dist, 3) if dist else 0,
            })

    return json.dumps({
        "original": q["question_text"][:200],
        "original_source": q.get("source_exam", ""),
        "similar": similar[:3],
        "message": "The same concept often appears reframed across exams — study the variations."
    })


# ============================================================
# CLI TEST
# ============================================================

if __name__ == "__main__":
    import sys
    
    print("=== TUTOR PLUGIN TEST ===\n")
    
    # Test quiz_start
    test_user = "test_user"
    result = json.loads(quiz_start(test_user, "drill", count=3))
    print(f"Drill: {result['count']} questions")
    for q in result["questions"]:
        print(f"  [{q['frequency_tier']}] {q['text'][:80]}...")
        print(f"    Choices: {list(q['choices'].keys())}")
    
    if result["questions"]:
        q_id = result["questions"][0]["id"]
        
        # Test quiz_answer
        ans = json.loads(quiz_answer(test_user, q_id, "A", 15))
        print(f"\nAnswer: correct={ans['correct']}, correct_answer={ans['correct_answer']}")
        
        # Test quiz_explain
        exp = json.loads(quiz_explain(q_id))
        print(f"\nExplain: {len(exp['textbook_context'])} textbook chunks, {len(exp['similar_questions'])} similar Q's")
        if exp["textbook_context"]:
            print(f"  Top chunk (Ch{exp['textbook_context'][0]['chapter']}): {exp['textbook_context'][0]['text'][:100]}...")
        
        # Test quiz_similar
        sim = json.loads(quiz_similar(q_id))
        print(f"\nSimilar: {len(sim['similar'])} from other exams")
    
    # Test quiz_progress
    prog = json.loads(quiz_progress(test_user))
    print(f"\nProgress: {prog['overall_pct']}% overall, {prog['due_today']} due, streak={prog['study_streak_days']}")
    
    print("\n=== ALL TESTS PASSED ===")
