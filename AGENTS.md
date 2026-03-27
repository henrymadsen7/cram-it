# AGENTS.md — Cram-It Developer Guide

> This file is for AI agents (Hermes, OpenClaw, Codex, etc.) working on the Cram-It codebase. Read this first.

---

## Project Overview

Cram-It is a self-hosted, AI-powered exam preparation platform. Students add "course packs" containing exam questions, concept maps, and textbook material. The platform then provides:

- FSRS spaced repetition drilling
- Claude-powered AI tutoring with RAG
- Practice exams matching real exam format
- Kahoot-style multiplayer battle mode
- Question generation for missed problems

**Stack**: Python 3.10+, Flask, SQLite, ChromaDB, Anthropic Claude, Flask-SocketIO

---

## How to Run

```bash
# Setup
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # Add ANTHROPIC_API_KEY

# Run main server (port 3000)
python server.py

# Run battle mode (port 4000, optional)
cd kahoot && python game.py
```

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `ANTHROPIC_API_KEY` | Yes | Claude API key |
| `CRAM_IT_PORT` | No (3000) | Server port |
| `CRAM_IT_PACK` | No | Default pack name |
| `CRAM_IT_DATA_DIR` | No (./data) | Data directory |

---

## Project Structure

```
cram-it/
├── server.py                  # Main Flask app (~1800 lines)
│                              # Sections: Pack system, Agent system, Quiz API,
│                              # Tutor chat, Exam mode, Question gen, Pack API
│
├── engine/
│   ├── tutor_plugin.py        # Core quiz engine (~1315 lines)
│   │                          # FSRS scheduling, drill selection, mastery tracking
│   │                          # Functions: quiz_start, quiz_answer, quiz_explain,
│   │                          # quiz_progress, quiz_session_start
│   │
│   └── similar_generator.py   # AI question generator (~370 lines)
│                              # Pipeline: context → web search → AI gen → validate → save
│
├── kahoot/
│   └── game.py                # Battle Mode (~1378 lines)
│                              # Flask-SocketIO, Kahoot-style multiplayer quiz
│                              # Host screen + player phones
│
├── templates/
│   └── index.html             # PWA single-page app (all tabs)
│
├── static/
│   ├── graphs.js              # JSXGraph preset + dynamic renderer
│   ├── graph_exercises.js     # Interactive graph exercises
│   ├── sw.js                  # Service worker (cache strategies)
│   └── manifest.json          # PWA manifest
│
├── packs/                     # Course packs (content)
│   ├── _template/             # Empty template with examples
│   │   ├── pack.yaml          # Course config schema
│   │   ├── concept_map.json.example
│   │   └── knowledge_graph.json.example
│   └── <course-name>/        # Actual course packs
│
├── tools/                     # Ingestion scripts
│   ├── ingest_canvas.py       # Canvas LMS → questions.json
│   ├── ingest_learning_suite.py # Learning Suite → questions.json
│   ├── ingest_pdf.py          # PDF exam → questions.json
│   ├── build_concept_map.py   # Syllabus → concept_map.json
│   └── chunk_textbook.py      # Textbook → ChromaDB embeddings
│
├── data/                      # Runtime data (GITIGNORED)
│   ├── learner.db             # SQLite (questions, reviews, FSRS, mastery)
│   ├── chroma_db/             # ChromaDB persistent store
│   └── profiles/              # User learning profile markdown files
│
├── docs/                      # Documentation
│   ├── ARCHITECTURE.md        # System design
│   ├── CREATING_PACKS.md      # How to create packs
│   ├── LMS_INTEGRATIONS.md    # Canvas/LS/Cengage
│   ├── DEPLOYMENT.md          # Hosting guide
│   ├── HERMES_INTEGRATION.md  # AI agent workflow
│   └── skills/                # Hermes skill files
│       ├── tutor-architecture.md
│       ├── graph-rendering.md
│       ├── podcast-generation.md
│       ├── canvas-integration.md
│       └── grade-portal.md
│
├── .env.example               # Environment template
├── .gitignore                 # Excludes data/, .env, __pycache__
├── requirements.txt           # Python deps
├── LICENSE                    # MIT
└── PLAN.md                    # Original generalization plan
```

---

## Key Files and Their Purposes

### server.py
The main Flask application. Everything routes through here. Key sections:
- **Lines 44-139**: Pack system (load_pack, list_packs)
- **Lines 149-343**: Agent system (per-user Claude conversations)
- **Lines 373-416**: Core quiz API (session, quiz, answer, explain, progress)
- **Lines 582-763**: AI tutor streaming chat (SSE)
- **Lines 932-1076**: Drill map with concept mastery
- **Lines 1143-1435**: Exam mode (submit, review, reinforce)
- **Lines 1481-1587**: Similar question generator
- **Lines 1734-1778**: Pack management API + startup

### engine/tutor_plugin.py
The core quiz engine, independent of Flask. Key functions:
- `quiz_start(user_id, mode, chapter, count)` — Returns questions for a drill
- `quiz_answer(user_id, question_id, user_answer, seconds)` — Grades answer, updates FSRS
- `quiz_explain(question_id)` — ChromaDB RAG for textbook context
- `quiz_progress(user_id)` — Overall progress, projected score

### engine/similar_generator.py
AI question generation pipeline:
- `generate_for_missed_question(question_id, user_answer, user_id)` — Full pipeline

---

## How to Create Packs

### Quick Way

```bash
cp -r packs/_template packs/my-course
# Edit packs/my-course/pack.yaml
# Add questions to questions.json
```

### From Canvas

```bash
python tools/ingest_canvas.py \
  --base-url https://your-school.instructure.com \
  --token YOUR_TOKEN \
  --course-id 12345 \
  --output packs/my-course/
```

### From PDF

```bash
python tools/ingest_pdf.py \
  --input exam.pdf \
  --output packs/my-course/questions.json
```

See `docs/CREATING_PACKS.md` for full details.

---

## Development Conventions

### Code Style
- Python: Standard library imports first, then third-party, then local
- SQL: Raw SQLite queries (no ORM)
- Frontend: Vanilla JS, no build step, inline in index.html
- No TypeScript, no React, no webpack — keep it simple

### Data Handling
- All user data lives in `data/` (gitignored)
- Pack content lives in `packs/<name>/`
- No hardcoded paths — use `PROJECT_ROOT`, `DATA_DIR`, `PACKS_DIR`
- Environment variables for secrets and configuration

### API Patterns
- All quiz/tutor endpoints are POST with JSON body
- `user_id` is always required in the request body
- Responses are JSON
- Streaming uses SSE (Server-Sent Events), not WebSocket

### Database
- SQLite (`data/learner.db`) — single file, no migrations
- Tables are created on first use (CREATE IF NOT EXISTS)
- ChromaDB (`data/chroma_db/`) — persistent client

### Testing
- Manual testing with a pack of 20+ questions
- Health check: `GET /api/health`
- Progress check: `POST /api/progress {"user_id": "test"}`

---

## Common Tasks

### Add a new API endpoint

1. Add the route to `server.py`
2. If it involves quiz logic, add the function to `engine/tutor_plugin.py`
3. Add frontend integration in `templates/index.html`
4. Document in `docs/ARCHITECTURE.md`

### Add a new drill mode

1. Edit `quiz_start()` in `engine/tutor_plugin.py`
2. Add an `elif mode == "your_mode":` block
3. Follow the existing patterns for query + format + session tracking
4. Add to the mode selector in the frontend

### Add a new pack

1. Create `packs/<name>/pack.yaml` with course metadata
2. Add `questions.json` with at least 10-20 questions
3. Create `concept_map.json` mapping concepts to questions
4. Optionally add `battle_bank.json`, `flashcards.json`, etc.

### Debug FSRS issues

1. Check the `fsrs_state` table: `SELECT * FROM fsrs_state WHERE user_id = ?`
2. Look for `due_date` values — are they in the past or future?
3. Reset a user's FSRS: `DELETE FROM fsrs_state WHERE user_id = ?`
4. The FSRS rating is based on correctness + time spent (see tutor_plugin.py)

### Debug the AI tutor

1. Check agent system prompt: look at `get_agent_system_prompt()` in server.py
2. The system prompt includes: pack config, user progress, concept mastery, user profile
3. Agent conversations expire after 30 min of inactivity
4. Force reset: delete user from `AGENTS` dict or restart server

### Ingest new content

```bash
# From Canvas
python tools/ingest_canvas.py --course-id ID --output packs/PACK/

# From PDF
python tools/ingest_pdf.py --input file.pdf --output packs/PACK/questions.json --append

# Textbook to ChromaDB
python tools/chunk_textbook.py --input textbook.pdf --pack PACK
```

---

## Where the Skill Docs Are

For detailed subsystem documentation, read:

| If you need to work on... | Read this skill file |
|---------------------------|---------------------|
| Server, FSRS, drill logic | `docs/skills/tutor-architecture.md` |
| JSXGraph, interactive graphs | `docs/skills/graph-rendering.md` |
| Audio/video podcast generation | `docs/skills/podcast-generation.md` |
| Canvas API, quiz scraping | `docs/skills/canvas-integration.md` |
| Grade fetching from LMS | `docs/skills/grade-portal.md` |

For architecture overview: `docs/ARCHITECTURE.md`
For deployment: `docs/DEPLOYMENT.md`
For pack creation: `docs/CREATING_PACKS.md`
