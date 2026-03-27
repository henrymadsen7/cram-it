# Cram-It System Architecture

## Overview

Cram-It is an AI-powered, self-hosted exam preparation platform. It combines spaced repetition, RAG-enhanced tutoring, real-time multiplayer battle mode, and LMS integrations into a single-page PWA.

```
┌──────────────────────────────────────────────────────────────────────┐
│                        USER DEVICES (PWA)                            │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐  │
│  │  Drill   │ │  Tutor   │ │  Exam    │ │  Bank    │ │  Stats   │  │
│  │  Mode    │ │  Chat    │ │  Mode    │ │  Browse  │ │  View    │  │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘  │
└───────┼────────────┼────────────┼────────────┼────────────┼─────────┘
        │            │            │            │            │
   ─────┴────────────┴────────────┴────────────┴────────────┴─────
                     HTTPS / Cloudflare Tunnel
   ───────────────────────────────────────────────────────────────
        │                    │                    │
   ┌────▼────────────────────▼────────────────────▼────┐
   │             Flask Server (server.py)               │
   │                   Port 3000                        │
   │  ┌─────────────┐ ┌──────────┐ ┌────────────────┐  │
   │  │ Quiz API    │ │ Agent    │ │ Pack Manager   │  │
   │  │ /api/quiz   │ │ /api/    │ │ /api/packs     │  │
   │  │ /api/answer │ │ agent/   │ │ /api/pack/     │  │
   │  │ /api/explain│ │ stream   │ │ select         │  │
   │  └──────┬──────┘ └────┬─────┘ └───────┬────────┘  │
   │         │             │               │            │
   │  ┌──────▼──────┐ ┌────▼─────┐ ┌───────▼────────┐  │
   │  │ Tutor Plugin│ │ Claude   │ │ YAML + JSON    │  │
   │  │ (FSRS +    │ │ Anthropic│ │ Loader         │  │
   │  │  Mastery)  │ │ API      │ │                │  │
   │  └──────┬──────┘ └────┬─────┘ └───────┬────────┘  │
   │         │             │               │            │
   │  ┌──────▼──────┐ ┌────▼─────┐ ┌───────▼────────┐  │
   │  │ SQLite DB   │ │ChromaDB  │ │ packs/         │  │
   │  │ learner.db  │ │ RAG      │ │ pack.yaml      │  │
   │  │ (FSRS state,│ │ Search   │ │ questions.json │  │
   │  │  reviews,   │ │          │ │ concept_map    │  │
   │  │  mastery)   │ │          │ │ etc.           │  │
   │  └─────────────┘ └──────────┘ └────────────────┘  │
   └────────────────────────────────────────────────────┘
                          │
   ┌──────────────────────▼────────────────────────────┐
   │         Battle Mode (kahoot/game.py)               │
   │         Flask-SocketIO — Port 4000                 │
   │  ┌──────────┐ ┌──────────┐ ┌──────────────────┐   │
   │  │  Host    │ │  Player  │ │  AI Grading      │   │
   │  │  Screen  │ │  Mobile  │ │  (Free Response)  │   │
   │  └──────────┘ └──────────┘ └──────────────────┘   │
   └────────────────────────────────────────────────────┘
```

---

## Flask Server (server.py)

The main server is a single Flask application (~1800 lines) that handles:

### Routes & Endpoints

| Category | Endpoint | Method | Purpose |
|----------|----------|--------|---------|
| **Pages** | `/` | GET | Serve SPA (index.html) |
| **Pages** | `/battle` | GET | Redirect to Battle Mode |
| **Quiz** | `/api/session` | POST | Start study session |
| **Quiz** | `/api/quiz` | POST | Get drill questions |
| **Quiz** | `/api/answer` | POST | Submit answer, get FSRS update |
| **Quiz** | `/api/explain` | POST | Get textbook context for question |
| **Quiz** | `/api/progress` | POST | Get user progress & mastery |
| **Tutor** | `/api/agent/stream` | POST | AI tutor chat (SSE streaming) |
| **Tutor** | `/api/hint` | POST | Quick hint for a question |
| **Content** | `/api/slides` | POST | ChromaDB slide/textbook search |
| **Content** | `/api/overview` | POST | Filterable question browser |
| **Content** | `/api/drill_map` | POST | Concept map with mastery data |
| **Exam** | `/api/exam_submit` | POST | Submit full practice exam |
| **Exam** | `/api/exam_history` | POST | Past exam attempts |
| **Exam** | `/api/exam_review` | POST | Detailed exam review |
| **Gen** | `/api/generate_similar` | POST | AI-generate similar questions |
| **Packs** | `/api/packs` | GET | List available course packs |
| **Packs** | `/api/pack/select` | POST | Switch active pack |
| **System** | `/api/health` | GET | Health check |

### Server Startup Flow

1. Load `.env` from project root (fallback: `~/.hermes/.env`)
2. Initialize Flask app, Anthropic client
3. Set up data directories (`data/`, `data/profiles/`)
4. Load first available pack from `packs/` directory
5. Initialize ChromaDB with `all-MiniLM-L6-v2` embeddings
6. Start agent cleanup thread (purge inactive agents every 5 min)
7. Listen on port 3000 (configurable via `CRAM_IT_PORT`)

---

## The Pack System

A "pack" is a self-contained course module. Each pack lives in `packs/<pack-name>/` and contains:

### Required Files

| File | Format | Purpose |
|------|--------|---------|
| `pack.yaml` | YAML | Course metadata, AI persona, exam format |
| `questions.json` | JSON | Question bank (loaded into SQLite) |

### Optional Files

| File | Format | Purpose |
|------|--------|---------|
| `concept_map.json` | JSON | Concept definitions, prerequisites, keywords |
| `knowledge_graph.json` | JSON | Concept chains, equations, misconceptions |
| `exam_weights.json` | JSON | Topic weighting for exam simulation |
| `concept_categories.json` | JSON | Grouping concepts into categories |
| `battle_bank.json` | JSON | Pre-generated Battle Mode questions |
| `flashcards.json` | JSON | Flashcard data |
| `graph_specs/` | Directory | JSXGraph interactive graph definitions |
| `figures/` | Directory | Exam/lecture images |
| `textbook_chunks/` | Directory | Raw text chunks for ChromaDB ingestion |

### pack.yaml Schema

```yaml
name: "Introduction to Microeconomics"
short_name: "Econ 101"
description: "Microeconomics exam prep covering chapters 14-29"
textbook: "Your Textbook Title"
professor: "Dr. Smith"
exam_format:
  questions: 40
  time_minutes: 75
  question_types: ["multiple_choice"]
  points_each: 2.5
chapters: [14, 15, 16, 17, 18, 19, 20, 22, 23, 24, 25, 29]
notes_allowed: false
calculator: true
ai_persona_name: "Tutor"
ai_persona: |
  You are a dedicated tutor. Sharp, direct, no-nonsense.
  No emojis. Use -- for dashes. Be concise but thorough.
```

### concept_map.json Schema

```json
{
  "concept_id": {
    "name": "Human-readable concept name",
    "chapter": 14,
    "prereqs": ["other_concept_id"],
    "keywords": ["keyword1", "keyword2"],
    "description": "Brief description for the AI tutor"
  }
}
```

### Pack Loading

When a pack is loaded (at startup or via `/api/pack/select`):

1. `pack.yaml` is parsed → `PACK_CONFIG` global
2. Optional JSON files are loaded → `CONCEPT_MAP`, `KNOWLEDGE_GRAPH`, `EXAM_WEIGHT_MAP`, `CONCEPT_CATEGORIES`
3. ChromaDB collection is loaded: `{pack_name}_slides`
4. All agent caches are cleared so system prompts refresh with new pack context

---

## FSRS Spaced Repetition Algorithm

Cram-It uses the [FSRS](https://github.com/open-spaced-repetition/py-fsrs) (Free Spaced Repetition Scheduler) algorithm for optimal review scheduling, wrapped in a custom 4-phase drill selection system.

### The 4-Phase Drill Selection

When a user starts a drill session (mode="drill"), questions are selected in 4 phases:

```
┌─────────────────────────────────────────────────────┐
│              10 Questions per Drill                  │
│                                                      │
│  Phase 1: FSRS-Due (30%)  ████████░░░░░░░░░░░  3 Qs │
│  Questions scheduled for review by FSRS algorithm    │
│  Ordered by frequency tier (high > medium > low)     │
│                                                      │
│  Phase 2: Weak Concepts (25%)  ██████░░░░░░░░░  2 Qs │
│  Practice/generated questions from exam variants     │
│  Source: practice, generated, custom exams            │
│                                                      │
│  Phase 3: Unseen Concepts (25%)  ██████░░░░░░░  3 Qs │
│  Questions tagged with concepts not yet attempted    │
│  Ensures coverage of the full concept map            │
│                                                      │
│  Phase 4: Reinforcement (20%)  ████░░░░░░░░░░  2 Qs │
│  Concept mastery < 50% with >= 2 attempts            │
│  Targets persistent weak spots                       │
│                                                      │
│  Backfill: Random unseen high-frequency questions    │
│  (fills any remaining slots)                         │
└─────────────────────────────────────────────────────┘
```

### FSRS Rating Determination

After each answer, the FSRS rating is determined by:

| Condition | FSRS Rating |
|-----------|-------------|
| Incorrect answer | `Again` |
| Correct, > 30 seconds | `Hard` |
| Correct, 10-30 seconds | `Good` |
| Correct, < 10 seconds | `Easy` |

The FSRS scheduler then calculates the next review date based on the card's stability, difficulty, and the rating.

### Concept Mastery

Each concept has a mastery percentage tracked per user:

- **mastery_pct** = `(correct_attempts / total_attempts) * 100`
- **proven** = `true` when `mastery_pct >= 80` AND `total_attempts >= 3`
- Mastery is updated on every answer for each concept tag on the question

### Other Drill Modes

| Mode | Description |
|------|-------------|
| `drill` | 4-phase smart selection (default) |
| `chapter` | Filter to one chapter |
| `calc_blitz` | Calculation questions only |
| `weak_spots` | Lowest mastery topics |
| `mock_exam` | 30 questions matching exam topic distribution |
| `exam` | True exam mode: 40 questions, timed, no feedback |
| `tricky` | Questions matching known tricky patterns |

---

## ChromaDB RAG Integration

ChromaDB provides semantic search over textbook content, lecture slides, and exam questions.

### Embedding Model

- **Model**: `all-MiniLM-L6-v2` (sentence-transformers)
- **Dimension**: 384
- **Storage**: `data/chroma_db/` (persistent client)

### Collections

| Collection | Content | Used By |
|------------|---------|---------|
| `{pack}_slides` | Lecture slide text + image paths | `/api/slides`, agent context |
| `textbook` | Textbook chapter chunks | `/api/explain` (textbook context) |
| `exam_questions` | Question text + metadata | `/api/explain` (similar questions) |

### How RAG Enriches the Tutor

When a student asks about a question:

1. **Textbook chunks** are retrieved (top 5 by semantic similarity)
2. **Similar exam questions** from other exams are retrieved
3. **Concept map data** (equations, misconceptions, prerequisites) is loaded
4. **Knowledge graph nodes** (key insights, equations) are loaded
5. All context is injected into the Claude conversation

---

## AI Tutor (Claude Streaming via SSE)

The tutor is a persistent Claude conversation per user, streamed via Server-Sent Events.

### Agent Architecture

```
User Message → Context Enrichment → Claude API (streaming) → SSE → Frontend
                    │
                    ├── Current question details
                    ├── Textbook context (ChromaDB)
                    ├── Knowledge graph (equations, misconceptions)
                    ├── Concept map data
                    ├── Slide search results
                    ├── Database query results
                    └── Conversation history (last 20 messages)
```

### Agent Lifecycle

1. **Creation**: On first message, an agent is created with a rich system prompt containing:
   - Pack config (course name, textbook, exam format)
   - User's current progress (accuracy, projected score)
   - Concept mastery breakdown
   - User profile (learning patterns, mistakes)
   - Available tools description (slides, graphs, database)

2. **Memory**: Conversation history is maintained (last 20 messages)

3. **System Prompt Refresh**: Every 10 messages, the system prompt is rebuilt with latest mastery data

4. **Cleanup**: Agents inactive for 30 minutes are automatically garbage collected

### Special Features

- **[ASSESS: ...]** tags: The tutor can rate student understanding during intake assessment, which seeds concept mastery
- **[SLIDES: topic]** tags: Trigger slide image display
- **[GRAPH: type]** tags: Render preset interactive graphs
- **[DYNAMIC_GRAPH: JSON]** tags: Render custom graphs with specific data points
- **Notes**: Messages starting with "note:" / "remember:" / "save:" are saved to user profile

---

## Battle Mode (Socket.IO Real-Time)

Battle Mode is a Kahoot-style multiplayer quiz game using Flask-SocketIO on port 4000.

### Architecture

```
┌──────────────┐     SocketIO      ┌──────────────┐
│  Host Screen │ ◄──────────────► │  game.py     │
│  (Computer)  │                   │  Port 4000   │
└──────────────┘                   │              │
                                   │  Game State: │
┌──────────────┐     SocketIO      │  - phase     │
│  Player 1    │ ◄──────────────► │  - players   │
│  (Phone)     │                   │  - questions │
└──────────────┘                   │  - scores    │
                                   │              │
┌──────────────┐     SocketIO      │  Claude API: │
│  Player 2    │ ◄──────────────► │  - Free resp │
│  (Phone)     │                   │  - Explain   │
└──────────────┘                   └──────────────┘
```

### Game Flow

1. **Lobby**: Players join via phone, host sees player cards
2. **Question**: 10 questions per game (5 conceptual + 5 calculation)
3. **Answering**: 60-second timer, live answer count updates
4. **Reveal**: Correct answer highlighted, AI explanation generated
5. **Leaderboard**: Scores updated (Kahoot-style time-based points)
6. **Podium**: Final results with winner celebration

### Question Sources

Questions come from `battle_bank.json` in the active pack. The bank cycles every 5 games (50 questions, 10 per game).

### Scoring

Points = `(1 - (responseTime / timerTime) / 2) * 1000`
- Faster correct answers earn more points (max 1000)
- Free-response questions are graded 0-100 by Claude

---

## PWA Architecture

Cram-It is a Progressive Web App installable on iOS and Android.

### Service Worker (sw.js)

| Strategy | Used For |
|----------|----------|
| **Cache-first** | Static assets, fonts, CDN resources |
| **Network-first** | API calls, navigation, HTML |

### Offline Capabilities

- App shell (HTML, CSS, JS, icons) is pre-cached on install
- API responses are cached dynamically — last successful response serves as fallback
- Navigation requests fall back to cached root page

### Manifest

```json
{
  "name": "Cram-It",
  "short_name": "Cram-It",
  "display": "standalone",
  "background_color": "#08080b",
  "theme_color": "#818cf8"
}
```

### Installation

The PWA is installable when accessed over HTTPS (e.g., via Cloudflare Tunnel). On iOS, use "Add to Home Screen" from Safari's share menu.

---

## Data Flow Diagram

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│  LMS (Canvas │     │  PDF Exams   │     │  Manual      │
│  / Learning  │     │  / Textbooks │     │  Entry       │
│  Suite)      │     │              │     │              │
└──────┬───────┘     └──────┬───────┘     └──────┬───────┘
       │                    │                    │
       ▼                    ▼                    ▼
┌──────────────────────────────────────────────────────┐
│              tools/ (Ingestion Scripts)               │
│  ingest_canvas.py  ingest_pdf.py  build_concept_map  │
│  chunk_textbook.py  ingest_learning_suite.py         │
└──────────────────────┬───────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────┐
│                 packs/<course>/                        │
│  pack.yaml  questions.json  concept_map.json          │
│  knowledge_graph.json  battle_bank.json               │
└──────────────────────┬───────────────────────────────┘
                       │
          ┌────────────┤
          │            │
          ▼            ▼
┌──────────────┐ ┌──────────────┐
│  SQLite DB   │ │  ChromaDB    │
│  (learner.db)│ │  (chroma_db/)│
│              │ │              │
│  - questions │ │  - textbook  │
│  - reviews   │ │  - slides    │
│  - fsrs_state│ │  - exam_qs   │
│  - sessions  │ │              │
│  - mastery   │ │  Embeddings: │
│  - profiles  │ │  MiniLM-L6   │
└──────┬───────┘ └──────┬───────┘
       │                │
       ▼                ▼
┌──────────────────────────────────────────────────────┐
│              server.py (Flask Application)             │
│                                                        │
│  Quiz Engine ←→ FSRS Scheduler                        │
│  AI Tutor ←→ Claude API + RAG Context                 │
│  Question Generator ←→ Claude API                     │
│  Progress Tracker ←→ Mastery + Profiles               │
└──────────────────────┬───────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────┐
│           Frontend (templates/index.html)              │
│                                                        │
│  Tabs: Tutor | Drill | Bank | Stats | Exam | Podcast  │
│  Service Worker: Offline caching                      │
│  PWA: Installable on mobile                           │
└──────────────────────────────────────────────────────┘
```

---

## Key Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| Flask | >= 3.0 | Web framework |
| flask-socketio | >= 5.3 | Battle Mode real-time |
| anthropic | >= 0.40 | Claude AI API |
| chromadb | >= 0.4 | Vector database for RAG |
| sentence-transformers | >= 2.2 | Embedding model |
| python-dotenv | >= 1.0 | Environment config |
| fsrs | latest | Spaced repetition algorithm |
| PyYAML | latest | Pack config parsing |
| Pillow | >= 10.0 | Image handling |
| edge-tts | >= 6.1 | Podcast voice synthesis |

---

## Database Schema (SQLite)

### Core Tables

- **questions**: Question bank (id, text, correct_answer, choices, concepts, topics, source_exam, frequency_tier, difficulty_score, graph_spec, figure_image)
- **reviews**: Answer history (user_id, question_id, user_answer, correct, time_spent_seconds)
- **fsrs_state**: FSRS card state per user per question (stability, difficulty, due_date, last_review, reps, lapses, state)
- **sessions**: Study sessions (user_id, mode, active, questions_answered, correct)
- **topic_mastery**: Mastery per topic per user
- **concept_mastery**: Mastery per concept per user (mastery_pct, total_attempts, correct_attempts, proven)
- **users**: User records (id, display_name)
- **user_preferences**: Per-user settings (tutor_persona, explanation_style, weak_calc_types)
- **intake_responses**: Initial assessment data
- **exam_attempts**: Full practice exam results
- **generated_questions**: AI-generated question details
- **similar_feedback**: User feedback on generated questions
