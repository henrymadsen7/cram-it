# Cram-It: Open-Source Generalization Plan
## From "Dane's Econ Tutor" → Shareable Multi-Course Study Platform

---

## 1. Vision

Cram-It becomes a self-hosted, AI-powered exam prep platform that any student can clone, configure with their own API keys, and use for ANY course. Ships with LMS integrations (Canvas, Learning Suite, Cengage) to auto-pull course content, ChromaDB for RAG, and the full PWA experience.

**Target:** Push to `babyLegionite/cram-it` on GitHub as a private repo, shareable with one collaborator who has their own OpenClaw/Hermes instance.

---

## 2. Current State (What Exists)

### Codebase: `~/Desktop/econ/tutor-app/`
- **server.py** (1647 lines) — Flask backend, AI tutor, drill engine, exam mode
- **templates/index.html** (1892 lines) — Full PWA SPA (Tutor/Drill/Bank/Stats/Exam/Pod/Cards tabs)
- **kahoot/game.py** (1364 lines) — Battle Mode (Kahoot-style multiplayer)
- **similar_generator.py** (368 lines) — AI question generation pipeline
- **static/** — PWA manifest, service worker, graphs.js, graph_exercises.js, flashcards, icons
- **podcast/** and **podcast2/** — Generated review podcasts (audio + video)

### External Dependencies:
- **tutor_plugin.py** at `~/.hermes/plugins/tutor/` — FSRS + mastery + drill logic (THE CORE ENGINE)
- **learner.db** at `~/.hermes/plugins/tutor/` — SQLite user data
- **chroma_db/** at `~/.hermes/plugins/tutor/` — ChromaDB slide/textbook embeddings
- **knowledge_graph.json**, **concept_map.json**, **video_quizzes.json** — same dir

### Skills (Albert's Hermes instance):
- `economics/butler-tutor` — Architecture doc for the tutor
- `economics/econ-graphs` — SVG graph rendering
- `economics/video-podcast` — Podcast generation pipeline
- `economics/voice-tutor` — Real-time voice tutoring (Pipecat)
- `grade-portal` — Canvas + Learning Suite grade scraping
- `grade-portal/canvas-quiz-automation` — Canvas quiz automation via CDP

### MSB 430 Data: `~/Desktop/msb430/data/`
- `all_questions.json` (250 scraped Canvas quiz questions)
- `raw_quiz_texts.json` (raw Canvas HTML)

---

## 3. Target Architecture

```
cram-it/
├── README.md                     # Setup guide, screenshots, how to contribute
├── LICENSE                       # MIT
├── .env.example                  # Template (ANTHROPIC_API_KEY, etc.)
├── requirements.txt              # Python dependencies
├── setup.py                      # Optional pip install
├── Makefile                      # Common commands (setup, run, tunnel, etc.)
│
├── server.py                     # Flask backend (generalized, no hardcoded courses)
├── engine/
│   ├── tutor_plugin.py           # FSRS + mastery + drill logic (from ~/.hermes/plugins/tutor/)
│   ├── similar_generator.py      # AI question generation
│   ├── podcast_generator.py      # Podcast creation pipeline
│   └── lms/                      # LMS integrations
│       ├── __init__.py
│       ├── canvas.py             # Canvas LMS API (quiz scraping, grade pulling)
│       ├── learning_suite.py     # BYU Learning Suite scraping
│       └── cengage.py            # Cengage/MindTap integration
│
├── data/                         # Runtime data (gitignored, created on first run)
│   ├── learner.db                # SQLite (moved from ~/.hermes/plugins/tutor/)
│   ├── chroma_db/                # ChromaDB persistent store
│   └── profiles/                 # User profile markdowns
│
├── packs/                        # Course packs (the actual course content)
│   ├── _template/                # Empty template for creating new packs
│   │   ├── pack.yaml             # Course metadata (name, textbook, exam format, etc.)
│   │   ├── questions.json        # Question bank schema
│   │   ├── concept_map.json      # Concept graph schema
│   │   ├── exam_weights.json     # Topic distribution schema
│   │   ├── flashcards.json       # Flashcard schema
│   │   ├── knowledge_graph.json  # Knowledge graph schema
│   │   ├── graph_specs/          # JSXGraph interactive specs
│   │   ├── figures/              # Exam/lecture images
│   │   └── textbook_chunks/      # For ChromaDB ingestion
│   │
│   └── demo-econ-intro/          # Minimal demo pack (10 generic econ questions, no BYU data)
│       └── ...
│
├── tools/                        # Pack creation utilities
│   ├── ingest_canvas.py          # Canvas → questions.json
│   ├── ingest_learning_suite.py  # Learning Suite → questions.json
│   ├── ingest_cengage.py         # Cengage → questions.json
│   ├── ingest_pdf.py             # PDF exam → structured questions
│   ├── build_concept_map.py      # Syllabus → concept graph
│   ├── chunk_textbook.py         # Textbook → ChromaDB embeddings
│   └── generate_graph_specs.py   # Figure images → JSXGraph specs
│
├── templates/
│   └── index.html                # PWA SPA (generalized UI)
│
├── static/
│   ├── manifest.json             # PWA manifest (generic "Cram-It")
│   ├── sw.js                     # Service worker
│   ├── graphs.js                 # JSXGraph renderer
│   ├── graph_exercises.js        # Interactive graph exercises
│   ├── icon-192.png              # Generic Cram-It icons
│   └── icon-512.png
│
├── kahoot/
│   ├── game.py                   # Battle mode (generalized)
│   └── audio/                    # Sound effects (no personal audio)
│
├── docs/                         # Documentation for contributors
│   ├── ARCHITECTURE.md           # System architecture overview
│   ├── CREATING_PACKS.md         # How to create a course pack
│   ├── LMS_INTEGRATIONS.md       # Canvas/LS/Cengage setup guides
│   ├── DEPLOYMENT.md             # Cloudflare tunnel + self-hosting
│   ├── HERMES_INTEGRATION.md     # How Cram-It works with Hermes/OpenClaw
│   └── skills/                   # Hermes skill files for AI-assisted development
│       ├── butler-tutor.md       # Tutor architecture skill (generalized)
│       ├── econ-graphs.md        # Graph rendering skill
│       ├── video-podcast.md      # Podcast generation skill
│       ├── voice-tutor.md        # Voice tutor skill
│       ├── canvas-integration.md # Canvas LMS skill
│       ├── learning-suite.md     # Learning Suite skill
│       └── grade-portal.md       # Grade portal skill
│
├── .gitignore
└── docker-compose.yml            # Optional: containerized deployment
```

---

## 4. Execution Plan (Ordered Steps)

### Phase 1: Clean & Consolidate (do first)

- [ ] **1.1** Create `~/Desktop/cram-it/` as the new project root
- [ ] **1.2** Copy `tutor_plugin.py` from `~/.hermes/plugins/tutor/` into `engine/`
- [ ] **1.3** Copy `server.py`, `similar_generator.py` into project root / engine
- [ ] **1.4** Copy `templates/`, `static/`, `kahoot/` (minus personal audio)
- [ ] **1.5** Create `requirements.txt` from inferred dependencies:
  ```
  flask>=3.0
  flask-socketio>=5.3
  anthropic>=0.40
  chromadb>=0.4
  sentence-transformers>=2.2
  python-dotenv>=1.0
  requests>=2.31
  Pillow>=10.0
  edge-tts>=6.1
  ```
- [ ] **1.6** Create `.env.example`:
  ```
  ANTHROPIC_API_KEY=sk-ant-...
  # Optional: for feedback notifications
  TELEGRAM_BOT_TOKEN=
  TELEGRAM_CHAT_ID=
  ```

### Phase 2: Strip Personal Data

- [ ] **2.1** Remove hardcoded users ("dane", "gwen", "albert") → replace with registration/login system
- [ ] **2.2** Remove all `/Users/danemel/` hardcoded paths → use relative paths + config
- [ ] **2.3** Remove "Butler", "Econ 110", "Mankiw 10e" from server.py system prompts → read from pack.yaml
- [ ] **2.4** Remove hardcoded exam dates, chapter ranges, concept IDs → read from pack
- [ ] **2.5** Remove hardcoded EXAM_WEIGHT_MAP → load from pack's exam_weights.json
- [ ] **2.6** Remove BYU-specific references (course numbers, professor names)
- [ ] **2.7** Replace Flask secret key `'econ110battle'` → generate from env or random
- [ ] **2.8** Strip Telegram admin chat IDs → make configurable
- [ ] **2.9** Remove exam figures, slide_graphs, podcast audio (course-specific media)
- [ ] **2.10** Do NOT ship learner.db, chroma_db, or user profiles (gitignored, created on first run)

### Phase 3: Generalize the Engine

- [ ] **3.1** Create **pack.yaml** schema:
  ```yaml
  name: "Introduction to Microeconomics"
  short_name: "Econ 101"
  textbook: "Principles of Economics, Mankiw"
  professor: "Dr. Smith"
  exam_format:
    questions: 40
    time_minutes: 75
    question_types: ["multiple_choice"]
    points_each: 2.5
  chapters: [1, 2, 3, 4, 5]
  notes_allowed: false
  calculator: true
  ```
- [ ] **3.2** Modify `server.py` to load active pack from config/env var
- [ ] **3.3** Make the AI tutor system prompt template-driven (reads pack.yaml for course context)
- [ ] **3.4** Generalize ChromaDB collection names per-pack (not just "slides")
- [ ] **3.5** Move data storage to `./data/` (relative to project, not `~/.hermes/plugins/`)
- [ ] **3.6** Make battle mode pack-aware (load battle_bank.json from active pack)
- [ ] **3.7** Add pack selection UI (if multiple packs exist, show picker on login)

### Phase 4: LMS Integrations

- [ ] **4.1** Create `engine/lms/canvas.py`:
  - Canvas REST API client (needs user API token)
  - Pull quizzes, questions, submissions
  - Export to questions.json format
  - Based on existing canvas-quiz-automation skill knowledge
- [ ] **4.2** Create `engine/lms/learning_suite.py`:
  - BYU Learning Suite scraper (session-based auth)
  - Pull assignments, grades, content
  - Based on existing grade-portal skill knowledge
- [ ] **4.3** Create `engine/lms/cengage.py`:
  - Cengage/MindTap integration (stub initially)
  - Document the auth flow and data format
- [ ] **4.4** Create `tools/ingest_canvas.py` — CLI tool: Canvas course → course pack
- [ ] **4.5** Create `tools/ingest_learning_suite.py` — CLI tool: LS course → course pack
- [ ] **4.6** Create `tools/ingest_pdf.py` — CLI tool: exam PDF → questions.json

### Phase 5: ChromaDB Backend Robustness

- [ ] **5.1** Move ChromaDB init to engine/ with proper collection management
- [ ] **5.2** Per-pack collections (e.g., `econ101_slides`, `econ101_textbook`)
- [ ] **5.3** Embedding model configurable (default: all-MiniLM-L6-v2)
- [ ] **5.4** Add textbook chunking pipeline (`tools/chunk_textbook.py`)
- [ ] **5.5** Add slide ingestion pipeline (PDF slides → chunks → embeddings)
- [ ] **5.6** Health check endpoint that verifies ChromaDB status + collection stats

### Phase 6: Documentation & Hermes Skills

- [ ] **6.1** Write `README.md` — quickstart, screenshots, features
- [ ] **6.2** Write `docs/ARCHITECTURE.md` — system overview, data flow
- [ ] **6.3** Write `docs/CREATING_PACKS.md` — how to build a course pack from scratch
- [ ] **6.4** Write `docs/LMS_INTEGRATIONS.md` — Canvas/LS/Cengage setup
- [ ] **6.5** Write `docs/DEPLOYMENT.md` — Cloudflare tunnel, nginx, systemd
- [ ] **6.6** Write `docs/HERMES_INTEGRATION.md` — how the AI agent ecosystem fits in
- [ ] **6.7** Export and generalize skill files into `docs/skills/`:
  - butler-tutor → `tutor-architecture.md` (strip BYU specifics, keep architecture)
  - econ-graphs → `graph-rendering.md` (keep as-is, it's generic enough)
  - video-podcast → `podcast-generation.md`
  - voice-tutor → `voice-tutor.md`
  - grade-portal → `grade-portal.md` (generalize from BYU to any Canvas/LS instance)
  - canvas-quiz-automation → `canvas-integration.md`

### Phase 7: GitHub Prep

- [ ] **7.1** Create `.gitignore`:
  ```
  .env
  data/
  __pycache__/
  *.pyc
  packs/*/figures/
  packs/*/textbook_chunks/
  podcast/
  podcast2/
  *.mp3
  *.mp4
  *.ogg
  *.wav
  ```
- [ ] **7.2** Create demo pack with ~10 generic intro econ questions (no BYU content)
- [ ] **7.3** Git init, initial commit
- [ ] **7.4** Create repo on GitHub under `babyLegionite/cram-it`
- [ ] **7.5** Push and add collaborator
- [ ] **7.6** Add AGENTS.md for the collaborator's Hermes/OpenClaw to read

---

## 5. What Ships vs. What Doesn't

### SHIPS (in the repo):
- All engine code (server, tutor plugin, drill logic, FSRS, battle mode)
- PWA frontend (all tabs, responsive UI)
- LMS integration code (Canvas, Learning Suite, Cengage)
- Pack creation tools
- ChromaDB integration
- Generalized Hermes skill files (architecture docs, not personal data)
- Demo course pack (generic, not from BYU)
- Full documentation
- .env.example, requirements.txt, Makefile, docker-compose.yml

### DOES NOT SHIP:
- Any .env or API keys
- learner.db (user study data)
- chroma_db/ (embeddings — rebuilt per user)
- User profiles
- Dane's grades, student IDs, course enrollments
- BYU-specific exam figures, lecture slides
- Podcast audio files (generated per course)
- Professor names tied to real people (only in demo as "Dr. Example")
- MSB 430 scraped quiz data
- battle_bank.json with real exam content

---

## 6. Data Dane's Collaborator DOES Get:

### From Albert's Knowledge Base:
- How the FSRS drill algorithm works and was tuned
- The 4-phase drill architecture (30/25/25/20 split)
- How ChromaDB RAG is integrated for slide/textbook search
- The AI tutor system prompt patterns that work well
- Canvas API patterns for scraping quizzes
- Learning Suite auth flow and page structure
- The JSXGraph rendering pipeline
- Battle mode architecture and real-time scoring
- Podcast generation workflow (edge-tts + ffmpeg)
- Voice tutor architecture (Pipecat dual-brain)
- PWA setup patterns (manifest, service worker, offline)
- What study strategies produced results (interleaving, spaced repetition tuning)

### NOT included:
- Dane's grades or performance data
- Dane's study weaknesses or mastery levels
- Any personal information about Dane or Gwen
- BYU student/course IDs
- Telegram chat IDs or bot tokens

---

## 7. Estimated Effort

| Phase | Est. Time | Complexity |
|-------|-----------|------------|
| Phase 1: Clean & Consolidate | 1-2 hours | Low (copy + organize) |
| Phase 2: Strip Personal Data | 2-3 hours | Medium (careful search-replace) |
| Phase 3: Generalize Engine | 3-4 hours | Medium-High (refactor server.py) |
| Phase 4: LMS Integrations | 3-4 hours | Medium (Canvas API exists, LS needs scraper) |
| Phase 5: ChromaDB Robustness | 1-2 hours | Medium (mostly reorganization) |
| Phase 6: Documentation | 2-3 hours | Low-Medium (writing) |
| Phase 7: GitHub Prep | 30 min | Low |
| **Total** | **~12-18 hours** | |

---

## 8. Open Questions

1. Should we keep the Kahoot battle mode sound effects? They're generated (not personal) but add bulk.
2. Do we want a CLI wizard for pack creation (`python -m tools.create_pack`) or just docs?
3. Should the demo pack be econ or something more universal (like a "Study Skills 101" meta-pack)?
4. Docker: worth including docker-compose.yml now or defer?
5. Auth: simple username/password or just username-only like current?
