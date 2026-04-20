#!/usr/bin/env python3
"""
Cram-It Database Initialization Module

Creates all SQLite tables required by the Cram-It engine and loads
question packs into the database.

Usage:
    python engine/db_init.py --pack-dir packs/demo-study-skills
    python engine/db_init.py --pack-dir packs/demo-study-skills --db-path data/learner.db

Functions:
    init_database(db_path)              - Create DB and all tables
    load_questions_from_pack(db, dir)   - Load questions.json into DB
    generate_scope_from_pack(pack_dir)  - Auto-generate scope.json for tutor_plugin
"""

import argparse
import hashlib
import json
import os
import sqlite3
from pathlib import Path


# ---------------------------------------------------------------------------
# Project-level constants
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "learner.db"


# ===========================================================================
# Table DDL
# ===========================================================================

_TABLES_SQL = """
-- Core question bank
CREATE TABLE IF NOT EXISTS questions (
    id                TEXT PRIMARY KEY,
    question_text     TEXT,
    correct_answer    TEXT,
    answer_choices    TEXT,          -- JSON dict  {"A": "...", ...}
    concept_tags      TEXT,          -- JSON array ["concept1", ...]
    topic_tags        TEXT,          -- JSON array ["chapter_1", ...]
    source_exam       TEXT DEFAULT 'pack',
    frequency_tier    TEXT DEFAULT 'medium',
    has_chart         INTEGER DEFAULT 0,
    chart_table       TEXT,
    figure_image      TEXT,
    graph_spec        TEXT,
    calculation_type  TEXT,
    question_type     TEXT DEFAULT 'conceptual',
    parent_question_id TEXT,
    source_url        TEXT,
    difficulty        TEXT DEFAULT 'medium',
    explanation       TEXT,
    flagged           INTEGER DEFAULT 0
);

-- Users
CREATE TABLE IF NOT EXISTS users (
    id            TEXT PRIMARY KEY,
    display_name  TEXT,
    password_hash TEXT,
    created_at    DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- User preferences (tutor style, session tracking, etc.)
CREATE TABLE IF NOT EXISTS user_preferences (
    user_id                TEXT PRIMARY KEY,
    display_name           TEXT DEFAULT '',
    tutor_persona          TEXT DEFAULT 'Tutor',
    explanation_style      TEXT DEFAULT 'step-by-step',
    weak_calc_types        TEXT DEFAULT '[]',
    preferred_graph_detail TEXT DEFAULT 'annotated',
    session_count          INTEGER DEFAULT 0
);

-- Review log (every answer attempt)
CREATE TABLE IF NOT EXISTS reviews (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id              TEXT,
    question_id          TEXT,
    correct              INTEGER,
    user_answer          TEXT,
    timestamp            DATETIME DEFAULT CURRENT_TIMESTAMP,
    time_spent_seconds   REAL DEFAULT 0,
    explanation_chunks   TEXT,
    session_id           TEXT
);

-- Aggregate topic-level mastery
CREATE TABLE IF NOT EXISTS topic_mastery (
    user_id          TEXT,
    topic            TEXT,
    total_attempts   INTEGER DEFAULT 0,
    correct_attempts INTEGER DEFAULT 0,
    mastery_pct      REAL DEFAULT 0,
    PRIMARY KEY (user_id, topic)
);

-- Aggregate concept-level mastery
CREATE TABLE IF NOT EXISTS concept_mastery (
    user_id          TEXT,
    concept_id       TEXT,
    total_attempts   INTEGER DEFAULT 0,
    correct_attempts INTEGER DEFAULT 0,
    mastery_pct      REAL DEFAULT 0,
    proven           INTEGER DEFAULT 0,
    PRIMARY KEY (user_id, concept_id)
);

-- FSRS spaced-repetition state per (user, question)
CREATE TABLE IF NOT EXISTS fsrs_state (
    user_id      TEXT,
    question_id  TEXT,
    stability    REAL,
    difficulty   REAL,
    due_date     TEXT,
    last_review  TEXT,
    reps         INTEGER DEFAULT 0,
    lapses       INTEGER DEFAULT 0,
    state        INTEGER DEFAULT 0,
    PRIMARY KEY (user_id, question_id)
);

-- Study sessions
CREATE TABLE IF NOT EXISTS sessions (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id            TEXT,
    mode               TEXT,
    started_at         DATETIME DEFAULT CURRENT_TIMESTAMP,
    ended_at           DATETIME,
    questions_answered INTEGER DEFAULT 0,
    correct_count      INTEGER DEFAULT 0,
    active             INTEGER DEFAULT 1
);

-- Intake / diagnostic responses
CREATE TABLE IF NOT EXISTS intake_responses (
    user_id       TEXT,
    question_text TEXT,
    response_text TEXT,
    assessment    TEXT,
    timestamp     DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Mock-exam scoring history
CREATE TABLE IF NOT EXISTS exam_attempts (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id          TEXT,
    timestamp        DATETIME DEFAULT CURRENT_TIMESTAMP,
    total_questions  INTEGER,
    correct          INTEGER,
    score_pct        REAL,
    total_seconds    REAL,
    results_json     TEXT
);

-- AI-generated questions (similar_generator.py)
CREATE TABLE IF NOT EXISTS generated_questions (
    id                  TEXT PRIMARY KEY,
    parent_question_id  TEXT,
    user_id             TEXT,
    question_text       TEXT,
    correct_answer      TEXT,
    answer_choices      TEXT,
    concept_tags        TEXT,
    question_type       TEXT,
    graph_spec          TEXT,
    explanation         TEXT,
    source              TEXT DEFAULT 'generated',
    created_at          DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Feedback on generated questions
CREATE TABLE IF NOT EXISTS similar_feedback (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    question_id         TEXT,
    user_id             TEXT,
    rating              TEXT,
    note                TEXT,
    parent_question_id  TEXT,
    created_at          DATETIME DEFAULT CURRENT_TIMESTAMP
);
"""


# ===========================================================================
# init_database
# ===========================================================================

def init_database(db_path=None):
    """
    Create (or open) the SQLite database and ensure every required table
    exists.  Returns the open ``sqlite3.Connection``.

    Parameters
    ----------
    db_path : str | Path | None
        Filesystem path for the database file.  Defaults to
        ``<project_root>/data/learner.db``.
    """
    db_path = Path(db_path) if db_path else DEFAULT_DB_PATH
    db_path.parent.mkdir(parents=True, exist_ok=True)

    db = sqlite3.connect(str(db_path))
    db.executescript(_TABLES_SQL)
    db.commit()

    print(f"[db_init] Database ready at {db_path}")
    return db


# ===========================================================================
# load_questions_from_pack
# ===========================================================================

def _stable_id(raw_id, question_text):
    """
    Produce a deterministic TEXT id.

    * If *raw_id* is already a non-numeric string → keep it.
    * If *raw_id* is an integer or numeric string → hash it together with
      the question text so we get a short, unique, stable identifier.
    """
    sid = str(raw_id)
    if sid.isdigit():
        # Generate a stable hash from the numeric id + question text
        blob = f"{sid}:{question_text[:120]}".encode()
        return "pack_" + hashlib.md5(blob).hexdigest()[:12]
    return sid


def _detect_schema(item):
    """
    Return ``'demo'`` or ``'full'`` depending on the keys present in a
    single question dict.

    Demo schema keys : question, choices, answer, concept, chapter, difficulty
    Full schema keys : question_text, answer_choices, correct_answer, …
    """
    if "question" in item and "choices" in item and "answer" in item:
        return "demo"
    if "question_text" in item:
        return "full"
    # Ambiguous — try demo first as a fallback
    return "demo" if "question" in item else "full"


def _normalise_demo(item):
    """Map a demo-style question dict to the canonical DB columns."""
    qtext = item.get("question", "")
    raw_id = item.get("id", "")
    qid = _stable_id(raw_id, qtext)

    # choices: already a dict like {"A": "...", "B": "..."}
    choices = item.get("choices", {})
    if isinstance(choices, list):
        # Convert list to dict keyed by letter
        choices = {chr(65 + i): c for i, c in enumerate(choices)}

    concept = item.get("concept", "")
    chapter = item.get("chapter", "")
    difficulty = item.get("difficulty", "medium")
    explanation = item.get("explanation", "")

    return {
        "id":               qid,
        "question_text":    qtext,
        "correct_answer":   item.get("answer", ""),
        "answer_choices":   json.dumps(choices),
        "concept_tags":     json.dumps([concept] if concept else []),
        "topic_tags":       json.dumps([f"chapter_{chapter}"] if chapter else []),
        "source_exam":      "pack",
        "frequency_tier":   "medium",
        "has_chart":        0,
        "chart_table":      None,
        "figure_image":     None,
        "graph_spec":       None,
        "calculation_type": None,
        "question_type":    "conceptual",
        "parent_question_id": None,
        "source_url":       None,
        "difficulty":       difficulty,
        "explanation":      explanation,
    }


def _normalise_full(item):
    """Map a full-schema question dict to the canonical DB columns."""
    qtext = item.get("question_text", "")
    raw_id = item.get("id", "")
    qid = _stable_id(raw_id, qtext)

    # answer_choices may already be a JSON string or a dict/list
    choices = item.get("answer_choices", {})
    if isinstance(choices, str):
        choices_json = choices
    else:
        choices_json = json.dumps(choices)

    # concept_tags / topic_tags — could be list or JSON string
    def _as_json_array(val):
        if val is None:
            return "[]"
        if isinstance(val, str):
            try:
                parsed = json.loads(val)
                if isinstance(parsed, list):
                    return val
            except (json.JSONDecodeError, TypeError):
                pass
            # Treat plain string as single-element array
            return json.dumps([val])
        if isinstance(val, list):
            return json.dumps(val)
        return "[]"

    graph_spec = item.get("graph_spec")
    if graph_spec and not isinstance(graph_spec, str):
        graph_spec = json.dumps(graph_spec)

    return {
        "id":               qid,
        "question_text":    qtext,
        "correct_answer":   item.get("correct_answer", ""),
        "answer_choices":   choices_json,
        "concept_tags":     _as_json_array(item.get("concept_tags")),
        "topic_tags":       _as_json_array(item.get("topic_tags")),
        "source_exam":      item.get("source_exam", "pack"),
        "frequency_tier":   item.get("frequency_tier", "medium"),
        "has_chart":        int(bool(item.get("has_chart", 0))),
        "chart_table":      item.get("chart_table"),
        "figure_image":     item.get("figure_image"),
        "graph_spec":       graph_spec,
        "calculation_type": item.get("calculation_type"),
        "question_type":    item.get("question_type", "conceptual"),
        "parent_question_id": item.get("parent_question_id"),
        "source_url":       item.get("source_url"),
        "difficulty":       item.get("difficulty", "medium"),
        "explanation":      item.get("explanation", ""),
    }


_INSERT_SQL = """
    INSERT OR REPLACE INTO questions (
        id, question_text, correct_answer, answer_choices,
        concept_tags, topic_tags, source_exam, frequency_tier,
        has_chart, chart_table, figure_image, graph_spec,
        calculation_type, question_type, parent_question_id,
        source_url, difficulty, explanation
    ) VALUES (
        :id, :question_text, :correct_answer, :answer_choices,
        :concept_tags, :topic_tags, :source_exam, :frequency_tier,
        :has_chart, :chart_table, :figure_image, :graph_spec,
        :calculation_type, :question_type, :parent_question_id,
        :source_url, :difficulty, :explanation
    )
"""


def load_questions_from_pack(db, pack_dir):
    """
    Read ``questions.json`` from *pack_dir* and upsert every question into
    the ``questions`` table.

    Handles **both** schemas transparently:

    * **Demo schema** — keys: question, choices, answer, concept, chapter,
      difficulty, explanation
    * **Full schema** — keys: question_text, answer_choices, correct_answer,
      concept_tags, topic_tags, …

    Parameters
    ----------
    db : sqlite3.Connection
        An open database connection (tables must already exist).
    pack_dir : str | Path
        Path to the pack directory containing ``questions.json``.

    Returns
    -------
    int
        Number of questions inserted / updated.
    """
    pack_dir = Path(pack_dir)
    questions_path = pack_dir / "questions.json"

    if not questions_path.exists():
        print(f"[db_init] WARNING: {questions_path} not found — skipping.")
        return 0

    with open(questions_path, "r", encoding="utf-8") as f:
        raw_questions = json.load(f)

    if not isinstance(raw_questions, list) or len(raw_questions) == 0:
        print(f"[db_init] WARNING: {questions_path} is empty or not an array.")
        return 0

    # Detect schema from the first real question (skip comment-only entries)
    sample = raw_questions[0]
    schema = _detect_schema(sample)
    normalise = _normalise_demo if schema == "demo" else _normalise_full
    print(f"[db_init] Detected '{schema}' schema in {questions_path}")

    cur = db.cursor()
    count = 0
    for item in raw_questions:
        # Skip comment-only placeholder entries
        if "_comment" in item and len(item) <= 2:
            continue
        row = normalise(item)
        cur.execute(_INSERT_SQL, row)
        count += 1

    db.commit()
    print(f"[db_init] Loaded {count} questions from {pack_dir.name}")
    return count


# ===========================================================================
# generate_scope_from_pack
# ===========================================================================

def generate_scope_from_pack(pack_dir, output_dir=None):
    """
    Auto-generate a ``scope.json`` that the tutor_plugin requires.

    Reads ``concept_map.json`` and ``questions.json`` from *pack_dir* and
    writes a scope file containing:

    * **topics** — one entry per concept, with ``name``, ``chapters`` it
      appears in, and a list of ``concepts`` that belong to it.
    * **calc_types** — (empty list; packs can override later)
    * **tricky_patterns** — (empty list; packs can override later)

    Parameters
    ----------
    pack_dir : str | Path
        The pack directory.
    output_dir : str | Path | None
        Where to write ``scope.json``.  Defaults to
        ``<project_root>/data/``.

    Returns
    -------
    dict
        The generated scope data.
    """
    pack_dir = Path(pack_dir)
    output_dir = Path(output_dir) if output_dir else (PROJECT_ROOT / "data")
    output_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Read concept_map.json  (concept_key → {name, chapter, ...})
    # ------------------------------------------------------------------
    concept_map_path = pack_dir / "concept_map.json"
    concept_map = {}
    if concept_map_path.exists():
        with open(concept_map_path, "r", encoding="utf-8") as f:
            concept_map = json.load(f)

    # ------------------------------------------------------------------
    # Read questions.json to discover chapter → concept associations
    # ------------------------------------------------------------------
    questions_path = pack_dir / "questions.json"
    questions = []
    if questions_path.exists():
        with open(questions_path, "r", encoding="utf-8") as f:
            questions = json.load(f)

    # Build chapter → set-of-concepts from both sources
    chapter_concepts = {}   # chapter_number → {concept_key, ...}
    all_concepts = set()

    # From concept_map
    for key, info in concept_map.items():
        all_concepts.add(key)
        ch = info.get("chapter")
        if ch is not None:
            chapter_concepts.setdefault(int(ch), set()).add(key)

    # From questions
    for q in questions:
        concept = q.get("concept") or None
        chapter = q.get("chapter") or None
        # Also handle full-schema questions
        if concept is None:
            ctags = q.get("concept_tags", [])
            if isinstance(ctags, str):
                try:
                    ctags = json.loads(ctags)
                except (json.JSONDecodeError, TypeError):
                    ctags = [ctags] if ctags else []
            for c in ctags:
                all_concepts.add(c)
                # Try to extract chapter from topic_tags
                ttags = q.get("topic_tags", [])
                if isinstance(ttags, str):
                    try:
                        ttags = json.loads(ttags)
                    except (json.JSONDecodeError, TypeError):
                        ttags = []
                for t in ttags:
                    if isinstance(t, str) and t.startswith("chapter_"):
                        try:
                            ch_num = int(t.split("_", 1)[1])
                            chapter_concepts.setdefault(ch_num, set()).add(c)
                        except (ValueError, IndexError):
                            pass
        else:
            all_concepts.add(concept)
            if chapter is not None:
                chapter_concepts.setdefault(int(chapter), set()).add(concept)

    # ------------------------------------------------------------------
    # Build topics list — one per chapter
    # ------------------------------------------------------------------
    topics = []
    for ch_num in sorted(chapter_concepts.keys()):
        concepts_in_ch = sorted(chapter_concepts[ch_num])

        # Try to build a readable name from concept_map entries
        concept_names = []
        for c in concepts_in_ch:
            if c in concept_map:
                concept_names.append(concept_map[c].get("name", c))
            else:
                concept_names.append(c.replace("_", " ").title())

        topics.append({
            "name":     f"chapter_{ch_num}",
            "label":    f"Chapter {ch_num}: {', '.join(concept_names)}",
            "chapters": [ch_num],
            "concepts": concepts_in_ch,
        })

    # If no chapters were found, create one catch-all topic
    if not topics and all_concepts:
        topics.append({
            "name":     "general",
            "label":    "All Concepts",
            "chapters": [],
            "concepts": sorted(all_concepts),
        })

    scope = {
        "topics":          topics,
        "calc_types":      [],
        "tricky_patterns": [],
    }

    scope_path = output_dir / "scope.json"
    with open(scope_path, "w", encoding="utf-8") as f:
        json.dump(scope, f, indent=2)

    print(f"[db_init] Generated scope.json at {scope_path}")
    print(f"          {len(topics)} topic(s), {len(all_concepts)} concept(s)")
    return scope


# ===========================================================================
# CLI entry point
# ===========================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Initialize the Cram-It database and load a question pack."
    )
    parser.add_argument(
        "--pack-dir",
        type=str,
        default=None,
        help="Path to a pack directory (e.g. packs/demo-study-skills). "
             "Loads questions.json and generates scope.json.",
    )
    parser.add_argument(
        "--db-path",
        type=str,
        default=None,
        help=f"Path to the SQLite database (default: {DEFAULT_DB_PATH}).",
    )
    parser.add_argument(
        "--scope-output",
        type=str,
        default=None,
        help="Directory to write scope.json (default: <project>/data/).",
    )
    args = parser.parse_args()

    db_path = args.db_path or DEFAULT_DB_PATH

    # 1. Create / migrate the database
    db = init_database(db_path)

    # 2. Load questions from pack (if specified)
    if args.pack_dir:
        pack_dir = Path(args.pack_dir)
        # Allow relative paths from project root
        if not pack_dir.is_absolute():
            pack_dir = PROJECT_ROOT / pack_dir

        if not pack_dir.exists():
            print(f"[db_init] ERROR: Pack directory not found: {pack_dir}")
            db.close()
            return 1

        count = load_questions_from_pack(db, pack_dir)
        print(f"[db_init] {count} question(s) ready in database.")

        # 3. Generate scope.json
        scope_out = args.scope_output or None
        generate_scope_from_pack(pack_dir, scope_out)

    db.close()
    print("[db_init] Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
