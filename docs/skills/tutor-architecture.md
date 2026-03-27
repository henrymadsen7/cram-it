# Skill: Cram-It Tutor Architecture

## Overview

The Cram-It tutor is an AI-powered exam preparation engine built on Flask, FSRS spaced repetition, ChromaDB RAG, and Claude. This skill document covers the complete architecture for development, debugging, and extension.

---

## Server Structure (server.py)

### File: `server.py` (~1800 lines)

The main Flask application is organized into sections:

| Section | Lines (approx.) | Purpose |
|---------|-----------------|---------|
| Imports & Setup | 1-50 | Dependencies, Flask app, Anthropic client |
| Data Directories | 33-42 | DB_PATH, CHROMA_DIR, PROFILES_DIR |
| Pack System | 44-139 | load_pack(), list_packs() |
| ChromaDB Init | 140-148 | Slide/textbook collection |
| Agent System | 149-343 | Per-user Claude conversations |
| Core Quiz API | 373-416 | /api/session, quiz, answer, explain, progress |
| Intake Assessment | 418-482 | [ASSESS:] tag parsing, concept seeding |
| Question Management | 483-534 | Flag, history endpoints |
| Slides | 536-554 | ChromaDB slide search |
| Agent Chat | 582-763 | SSE streaming, context enrichment |
| Video Quizzes | 765-845 | Video-linked quiz system |
| Overview | 846-931 | Filterable question browser |
| Drill Map | 932-1076 | Concept map with mastery |
| Exam Mode | 1143-1435 | Submit, history, review, reinforce |
| Similar Generator | 1481-1587 | AI question generation + feedback |
| Pack API | 1734-1762 | List/select packs |
| Health & Startup | 1764-1778 | Health check, app.run() |

### File: `engine/tutor_plugin.py` (~1315 lines)

The core quiz engine, separate from Flask:

| Section | Purpose |
|---------|---------|
| Path Setup | Configurable data directory |
| Lazy Init | ChromaDB, FSRS, embed_fn (loaded on first use) |
| Profile Management | _update_profile(), _get_profile() |
| User Preferences | Auto-adapting explanation style, weak calc types |
| quiz_session_start() | Session init, greeting, stats |
| quiz_start() | 4-phase drill selection (main algorithm) |
| quiz_answer() | Answer checking, FSRS update, mastery update |
| quiz_explain() | ChromaDB RAG for textbook + similar questions |
| quiz_progress() | Overall progress, projected score |
| quiz_compare() | Compare two users |
| quiz_similar() | Find similar questions |

### File: `engine/similar_generator.py` (~370 lines)

AI question generation pipeline:

1. `get_similar_context()` — Get same-concept questions as examples
2. `search_web_questions()` — DuckDuckGo search for existing questions
3. `generate_similar_questions()` — Claude generates new questions
4. `validate_question()` — Second Claude pass to verify answer
5. `generate_for_missed_question()` — Full pipeline orchestration

---

## Endpoints Reference

### Quiz Flow

```
POST /api/session     → Start session, get preferences
POST /api/quiz        → Get questions (mode: drill, chapter, calc_blitz, etc.)
POST /api/answer      → Submit answer, get FSRS update + mastery update
POST /api/explain     → Get textbook context for a question
POST /api/progress    → Get overall progress + concept mastery
POST /api/session_end → End active session
```

### Tutor Flow

```
POST /api/agent/stream → SSE streaming chat with Claude
POST /api/hint         → Quick hint (no conversation history)
POST /api/slides       → ChromaDB slide search
```

### Exam Flow

```
POST /api/quiz (mode=exam) → Get 40-question exam
POST /api/exam_submit      → Submit all answers, get graded
POST /api/exam_history     → Past exam attempts
POST /api/exam_review      → Detailed exam review
POST /api/exam_reinforce   → Feed exam results into FSRS
```

### Question Management

```
POST /api/flag             → Flag/unflag a question
POST /api/questions/history→ All questions with user history
POST /api/overview         → Filterable question browser
POST /api/drill_map        → Concept map with per-question status
POST /api/generate_similar → AI-generate similar questions
POST /api/similar_feedback → Rate generated questions
POST /api/delete_question  → Delete a generated question
```

---

## FSRS Algorithm Details

### Library

Uses the `py-fsrs` library, which implements the Free Spaced Repetition Scheduler.

### Card State

Each question-user pair has an FSRS card with:
- **stability**: How long the memory will last (in days)
- **difficulty**: How hard the card is for this user (0-10)
- **due_date**: When the card should be reviewed next
- **last_review**: When it was last reviewed
- **reps**: Number of successful reviews
- **lapses**: Number of times the card was forgotten
- **state**: New, Learning, Review, or Relearning

### Rating Logic

```python
if not correct:
    rating = Rating.Again      # Forgot — reset interval
elif seconds_spent > 30:
    rating = Rating.Hard       # Got it, but slowly
elif seconds_spent < 10:
    rating = Rating.Easy       # Got it fast — long interval
else:
    rating = Rating.Good       # Normal correct answer
```

### How FSRS State is Stored

```sql
CREATE TABLE fsrs_state (
    user_id TEXT,
    question_id TEXT,
    stability REAL,
    difficulty REAL,
    due_date TEXT,         -- ISO 8601
    last_review TEXT,      -- ISO 8601
    reps INTEGER,
    lapses INTEGER,
    state INTEGER,         -- 0=New, 1=Learning, 2=Review, 3=Relearning
    PRIMARY KEY (user_id, question_id)
);
```

---

## 4-Phase Drill Selection Algorithm

### Phase 1: FSRS-Due (30% of questions)

```sql
SELECT q.* FROM questions q
JOIN fsrs_state fs ON q.id = fs.question_id AND fs.user_id = ?
WHERE fs.due_date <= ?
ORDER BY
    CASE q.frequency_tier WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END,
    RANDOM()
LIMIT ?
```

Questions that FSRS has scheduled for review. High-frequency-tier questions are prioritized.

### Phase 2: Practice/Generated Questions (25%)

```sql
SELECT q.* FROM questions q
WHERE q.source_exam IN ('practice', 'generated', 'custom')
ORDER BY frequency_tier priority, RANDOM()
```

Variant questions from practice exams or AI generation. Different wording of the same concept helps build deeper understanding.

### Phase 3: Unseen Concepts (25%)

1. Get all concepts the user has attempted
2. Get all concepts that exist in the question bank
3. Find the gap (concepts not yet attempted)
4. Select questions tagged with those unseen concepts

This ensures the student doesn't skip entire topic areas.

### Phase 4: Weak Reinforcement (20%)

```sql
SELECT concept_id FROM concept_mastery
WHERE user_id = ? AND mastery_pct < 50 AND total_attempts >= 2
```

Questions from concepts where the student has < 50% mastery with at least 2 attempts. Targets persistent weak spots.

### Backfill

If phases 1-4 don't fill all slots, remaining questions are:
1. Random unseen high-frequency questions (never attempted)
2. If still not enough, any random questions

---

## Multi-User Support

### User Identification

Users are identified by a `user_id` string (set in the frontend, stored in localStorage). There is no authentication — anyone with the URL can create a user ID and start studying.

### Per-User Data

| Data | Storage | Per-User |
|------|---------|----------|
| FSRS card states | SQLite `fsrs_state` | Yes |
| Answer history | SQLite `reviews` | Yes |
| Concept mastery | SQLite `concept_mastery` | Yes |
| Topic mastery | SQLite `topic_mastery` | Yes |
| User preferences | SQLite `user_preferences` | Yes |
| Learning profile | Markdown file in `data/profiles/` | Yes |
| Agent conversation | In-memory `AGENTS` dict | Yes |
| Intake assessment | SQLite `intake_responses` | Yes |
| Exam attempts | SQLite `exam_attempts` | Yes |

### Agent Memory

Each user gets a persistent Claude conversation:
- System prompt includes user's current progress and mastery
- Conversation history is kept (last 20 messages)
- System prompt refreshes every 10 messages
- Agents auto-expire after 30 minutes of inactivity

---

## Data Flow: Answering a Question

```
1. User selects answer in frontend
2. POST /api/answer {user_id, question_id, user_answer, seconds}
3. server.py routes to quiz_answer() in tutor_plugin.py
4. quiz_answer():
   a. Look up question in SQLite
   b. Check if answer is correct
   c. Insert into reviews table
   d. Update active session stats
   e. Get/create FSRS card, determine rating (Again/Hard/Good/Easy)
   f. Call fsrs.review_card() to get new due date
   g. Save FSRS state to fsrs_state table
   h. Update topic_mastery for each topic tag
   i. Update concept_mastery for each concept tag
   j. Auto-adapt user preferences (every 10 answers)
   k. Recalculate difficulty scores (every 20 answers)
   l. Update user learning profile
5. Return JSON: {correct, correct_answer, new_due, mastery_updates, ...}
6. Frontend shows result, animates mastery changes
```

---

## Known Pitfalls & Debugging

### ChromaDB Collection Not Found

If you see `Collection not found` errors:
- Ensure the pack name matches the collection name (`{pack}_slides`)
- Run the textbook/slide ingestion scripts first
- Check `data/chroma_db/` exists and has data

### FSRS State Corruption

If questions keep repeating or never appear:
- Check `fsrs_state` table for the user
- Look for `due_date` values that seem wrong
- Delete the user's fsrs_state rows to reset: `DELETE FROM fsrs_state WHERE user_id = ?`

### Agent System Prompt Too Long

If Claude returns errors about context length:
- The system prompt grows with concept mastery data
- For packs with 50+ concepts, the prompt can exceed 8K tokens
- Solution: truncate the concept mastery section to top 20 weakest + top 10 strongest

### SQLite Locking

With multiple concurrent users, SQLite may lock:
- The server uses separate connections per request
- Keep connections short-lived (open, query, close)
- For production with many users, consider migrating to PostgreSQL

### Sentence Transformers Slow Start

The first request after startup may be slow (10-30 seconds):
- The `all-MiniLM-L6-v2` model loads lazily on first use
- This is expected; subsequent requests are fast
- To pre-warm: make a dummy `/api/slides` request on startup

### Graph Exercises vs Regular Questions

Questions with `gx_` prefix IDs are graph exercises:
- They bypass FSRS (no spaced repetition)
- Logged directly to reviews table
- Grading is handled differently (frontend determines correctness)
