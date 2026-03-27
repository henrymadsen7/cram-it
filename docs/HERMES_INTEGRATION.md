# Hermes / OpenClaw Integration

Cram-It is designed to work alongside AI agent systems like Hermes Agent and OpenClaw. This document explains the integration and how an AI agent can manage, extend, and build content for Cram-It.

---

## What is Hermes Agent / OpenClaw?

**Hermes Agent** (by Nous Research) is an AI assistant framework that provides persistent memory, tool use, and skill-based knowledge management. **OpenClaw** is the open-source platform for running Hermes agents.

Key features relevant to Cram-It:
- **Skills**: Structured knowledge files that teach the agent how to perform tasks
- **Tool use**: Agents can read/write files, run code, and interact with APIs
- **Persistent memory**: Agents remember context across conversations
- **Multi-step workflows**: Complex tasks like "build a course pack from Canvas"

---

## How an AI Agent Can Manage Cram-It

### The Agent as Course Builder

The primary use case is having your AI agent build and maintain course packs:

```
User: "I need a pack for my Biology 101 final. Here's my Canvas course ID: 45678"

Agent:
1. Runs ingest_canvas.py to pull quiz data
2. Generates concept_map.json from the syllabus
3. Creates pack.yaml with course details
4. Ingests textbook chunks into ChromaDB
5. Validates the pack and reports back
```

### The Agent as System Admin

Your agent can also:
- Monitor `data/feedback_log.jsonl` for user feedback on generated questions
- Review and fix flagged questions
- Generate additional practice questions for weak areas
- Update concept maps based on new exam material
- Debug issues with the server or data

### The Agent as Content Creator

- Generate Battle Mode question banks
- Create podcast review scripts
- Build flashcard sets from concept maps
- Design interactive graph exercises

---

## Skill Files

The `docs/skills/` directory contains Hermes skill files — structured documentation that teaches an AI agent how to work with specific Cram-It subsystems.

### Available Skills

| Skill File | What It Teaches |
|------------|-----------------|
| `tutor-architecture.md` | Full server architecture, FSRS algorithm, endpoints, data flow |
| `graph-rendering.md` | JSXGraph integration, graph spec format, adding new graph types |
| `podcast-generation.md` | Edge-TTS pipeline, two-voice dialogue, video generation |
| `canvas-integration.md` | Canvas API patterns, quiz scraping, data conversion |
| `grade-portal.md` | Grade fetching from Canvas and Learning Suite |

### Using Skills with Your Agent

When your Hermes/OpenClaw agent needs to work on Cram-It:

1. Point the agent to this repository
2. Have it read `AGENTS.md` for an overview
3. For specific tasks, reference the relevant skill file:
   - "Read `docs/skills/tutor-architecture.md` to understand the server"
   - "Read `docs/skills/canvas-integration.md` to set up Canvas scraping"

### Skill File Format

Each skill file follows this structure:

```markdown
# Skill Name

## Overview
What this subsystem does and why.

## Architecture
How the components fit together.

## Key Files
Which files to read/modify.

## Common Tasks
Step-by-step guides for common operations.

## Pitfalls & Debugging
Known issues and how to fix them.
```

---

## Creating New Course Packs with Your Agent

### The Workflow

1. **Tell your agent what course you need**
   ```
   "I need a Cram-It pack for CS 261 Data Structures.
   The textbook is 'Data Structures and Algorithm Analysis in C++' by Weiss.
   The exam covers chapters 1-7, 40 questions, 90 minutes."
   ```

2. **Agent creates the pack skeleton**
   ```
   packs/cs261-data-structures/
   ├── pack.yaml
   ├── questions.json (empty array)
   ├── concept_map.json
   └── (other files as needed)
   ```

3. **Agent populates content**
   - If Canvas access is available: `python tools/ingest_canvas.py ...`
   - If you provide PDFs: `python tools/ingest_pdf.py ...`
   - If neither: Agent generates starter questions from the concept map

4. **Agent validates the pack**
   - Checks all questions have concept tags
   - Verifies answer keys
   - Ensures concept_map covers all exam topics

### Providing Source Materials

The most effective workflow is:
1. Share your Canvas API token with the agent
2. Point it at your course ID
3. Provide any PDF exams or practice tests
4. Let the agent build the pack automatically

### Agent-Generated Concept Maps

Your agent can generate concept maps from:
- Course syllabus
- Table of contents
- Textbook chapter summaries
- Previous exam content

Example prompt for your agent:
```
"Generate a concept_map.json for CS 261 covering:
- Arrays and Linked Lists (Ch 1-2)
- Stacks and Queues (Ch 3)
- Trees: BST, AVL, Splay (Ch 4)
- Hashing (Ch 5)
- Priority Queues / Heaps (Ch 6)
- Sorting algorithms (Ch 7)

Each concept should have prereqs, keywords, and a description
focused on how it gets tested on exams."
```

---

## Automating Canvas Scraping

### Setup

1. Obtain your Canvas API token (see [LMS Integrations](./LMS_INTEGRATIONS.md))
2. Add to `.env`:
   ```
   CANVAS_BASE_URL=https://your-school.instructure.com
   CANVAS_API_TOKEN=your_token
   ```

### Agent Workflow

Tell your agent:
```
"Scrape all quizzes from Canvas course 45678 and add them
to the cs261-data-structures pack. Use the concept map
to auto-tag questions."
```

The agent will:
1. Read `tools/ingest_canvas.py` to understand the pipeline
2. Run the script with appropriate arguments
3. Review the output for quality
4. Fix any tagging issues
5. Report back with stats

### Incremental Updates

```
"Check Canvas course 45678 for new quizzes since last week
and add any new questions to the pack."
```

---

## The Development Workflow

### User Tells Agent → Agent Builds Pack → Student Studies

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│              │     │              │     │              │
│    User      │────►│  AI Agent    │────►│  Cram-It     │
│  (Student)   │     │  (Hermes/    │     │  Server      │
│              │     │   OpenClaw)  │     │              │
│  "I need     │     │              │     │  Serves the  │
│   help with  │     │  1. Reads    │     │  pack to the │
│   Bio 101"   │     │     skills   │     │  student     │
│              │     │  2. Scrapes  │     │              │
│  Provides:   │     │     LMS      │     │  Features:   │
│  - Canvas ID │     │  3. Builds   │     │  - Drill     │
│  - Textbook  │     │     pack     │     │  - Tutor     │
│  - PDFs      │     │  4. Ingests  │     │  - Exam      │
│              │     │     to       │     │  - Battle    │
│              │     │     ChromaDB │     │              │
└──────────────┘     └──────────────┘     └──────────────┘
```

### Iterative Improvement

After studying, the student can tell their agent:
```
"I keep getting game theory questions wrong. Can you generate
10 more practice questions focused on Nash equilibrium and
dominant strategies?"
```

The agent:
1. Reads the student's mastery data from `data/learner.db`
2. Identifies specific misconceptions from review history
3. Generates targeted practice questions
4. Adds them to the pack with appropriate tags

---

## Extending Cram-It with Your Agent

### Adding New Features

Your agent can extend Cram-It by:

1. **Reading the architecture docs** to understand the codebase
2. **Adding new endpoints** to `server.py`
3. **Creating new tools** in `tools/`
4. **Modifying the frontend** in `templates/index.html`

### Example: Adding a New Drill Mode

Tell your agent:
```
"Add a 'spaced review' drill mode that only shows questions
that are overdue by more than 24 hours, sorted by how
overdue they are."
```

The agent would:
1. Read `docs/skills/tutor-architecture.md`
2. Find the drill mode section in `engine/tutor_plugin.py`
3. Add the new mode following the existing pattern
4. Test the new mode

### Example: Adding a New LMS Integration

```
"Add support for Blackboard LMS. Here's the API documentation: ..."
```

The agent would:
1. Read `docs/skills/canvas-integration.md` for the pattern
2. Create `engine/lms/blackboard.py`
3. Create `tools/ingest_blackboard.py`
4. Update `docs/LMS_INTEGRATIONS.md`
