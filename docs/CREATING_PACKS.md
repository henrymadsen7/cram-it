# Creating Course Packs

A course pack is everything Cram-It needs to tutor a specific course: questions, concepts, textbook material, and configuration. This guide covers all methods for creating one.

---

## Table of Contents

1. [Pack Structure](#pack-structure)
2. [Manual Method](#manual-method)
3. [Automated Methods](#automated-methods)
4. [From Canvas LMS](#from-canvas)
5. [From Learning Suite](#from-learning-suite)
6. [From PDFs](#from-pdfs)
7. [ChromaDB Ingestion](#chromadb-ingestion)
8. [Getting LMS Access & Exam Materials](#getting-lms-access--exam-materials)
9. [Tips for Good Concept Maps](#tips-for-good-concept-maps)

---

## Pack Structure

Every pack lives in `packs/<pack-name>/` and must have at minimum:

```
packs/my-course/
├── pack.yaml              # REQUIRED: Course metadata
├── questions.json         # REQUIRED: Question bank
├── concept_map.json       # Recommended: Concept definitions
├── knowledge_graph.json   # Optional: Deep concept connections
├── exam_weights.json      # Optional: Topic distribution
├── concept_categories.json# Optional: Concept groupings
├── battle_bank.json       # Optional: Battle Mode questions
├── flashcards.json        # Optional: Flashcard data
├── graph_specs/           # Optional: Interactive graph definitions
├── figures/               # Optional: Images referenced by questions
└── textbook_chunks/       # Optional: Raw text for ChromaDB
```

---

## Manual Method

### Step 1: Copy the Template

```bash
cp -r packs/_template packs/my-course
```

### Step 2: Edit pack.yaml

```yaml
name: "Organic Chemistry I"
short_name: "OChem I"
description: "Exam prep for first-semester organic chemistry"
textbook: "Organic Chemistry, Wade & Simek, 9th Edition"
professor: "Dr. Example"
exam_format:
  questions: 50
  time_minutes: 75
  question_types: ["multiple_choice", "short_answer"]
  points_each: 2
chapters: [1, 2, 3, 4, 5, 6, 7, 8]
notes_allowed: false
calculator: false

# Optional: Custom AI persona
ai_persona_name: "ChemTutor"
ai_persona: |
  You are ChemTutor, a sharp organic chemistry study partner.
  You explain mechanisms step by step, always drawing attention
  to electron flow and stereochemistry. Be direct and concise.
```

### Step 3: Create questions.json

Questions are loaded into SQLite at startup. Format:

```json
[
  {
    "id": "q001",
    "question_text": "Which of the following is the most stable carbocation?",
    "correct_answer": "B",
    "answer_choices": {
      "a": "Primary carbocation",
      "b": "Tertiary carbocation",
      "c": "Methyl carbocation",
      "d": "Secondary carbocation"
    },
    "concept_tags": ["carbocation_stability"],
    "topic_tags": ["chapter_6_ionic_reactions"],
    "question_type": "conceptual",
    "source_exam": "midterm_1_2024",
    "frequency_tier": "high",
    "has_chart": false,
    "chart_table": null,
    "figure_image": null,
    "graph_spec": null,
    "calculation_type": null
  }
]
```

#### Field Reference

| Field | Required | Description |
|-------|----------|-------------|
| `id` | Yes | Unique question identifier |
| `question_text` | Yes | Full question text |
| `correct_answer` | Yes | Correct answer letter (A, B, C, D) |
| `answer_choices` | Yes | Object with keys a, b, c, d |
| `concept_tags` | Yes | Array of concept IDs from concept_map.json |
| `topic_tags` | No | Array of topic strings |
| `question_type` | No | "conceptual", "calculation", or "graph" |
| `source_exam` | No | Which exam this came from |
| `frequency_tier` | No | "high", "medium", or "low" (exam likelihood) |
| `has_chart` | No | Boolean - question has a table/chart |
| `chart_table` | No | HTML or text table data |
| `figure_image` | No | Path to figure image |
| `graph_spec` | No | JSXGraph JSON spec for interactive graphs |
| `calculation_type` | No | Type of calculation (for calc_blitz mode) |

### Step 4: Create concept_map.json

```json
{
  "carbocation_stability": {
    "name": "Carbocation Stability",
    "chapter": 6,
    "prereqs": ["electronegativity_basics"],
    "keywords": ["carbocation", "tertiary", "hyperconjugation", "stability"],
    "description": "Stability order: methyl < primary < secondary < tertiary. Stabilized by hyperconjugation and inductive effects."
  },
  "electronegativity_basics": {
    "name": "Electronegativity & Polarity",
    "chapter": 1,
    "prereqs": [],
    "keywords": ["electronegativity", "polar", "bond", "dipole"],
    "description": "Electronegativity is an atom's ability to attract shared electrons. Affects bond polarity and reactivity."
  }
}
```

### Step 5: Start the Server

```bash
CRAM_IT_PACK=my-course python server.py
```

Or just start the server — it auto-loads the first available pack.

---

## Automated Methods

The `tools/` directory contains scripts for automated pack creation:

### build_concept_map.py

Generate a concept map from a syllabus or course outline:

```bash
python tools/build_concept_map.py \
  --syllabus "path/to/syllabus.pdf" \
  --output "packs/my-course/concept_map.json"
```

### generate_graph_specs.py

Convert figure images into interactive JSXGraph specifications:

```bash
python tools/generate_graph_specs.py \
  --input "packs/my-course/figures/" \
  --output "packs/my-course/graph_specs/"
```

---

## From Canvas

### Prerequisites

- Canvas API token (see [LMS Integrations](./LMS_INTEGRATIONS.md))
- Course ID from Canvas URL

### Using ingest_canvas.py

```bash
python tools/ingest_canvas.py \
  --base-url "https://your-school.instructure.com" \
  --token "YOUR_CANVAS_API_TOKEN" \
  --course-id 12345 \
  --output "packs/my-course/"
```

This script will:

1. Pull all quizzes from the Canvas course
2. Extract questions with answer choices
3. Map correct answers
4. Generate `questions.json` in the pack format
5. Optionally generate a draft `concept_map.json` using AI

### What It Pulls

- Quiz questions (multiple choice, true/false)
- Quiz submissions (if you have access)
- Assignment descriptions (for context)
- Course modules and content pages

### Limitations

- Canvas API may not expose answer keys for unpublished quizzes
- Some question types (matching, essay) need manual conversion
- Rate-limited to avoid API throttling

---

## From Learning Suite

### Prerequisites

- Your school's SSO credentials
- Course enrollment in Learning Suite

### Using ingest_learning_suite.py

```bash
python tools/ingest_learning_suite.py \
  --course-url "https://learningsuite.example.edu/course/12345" \
  --username "your_username" \
  --output "packs/my-course/"
```

This script will:

1. Authenticate via your school's SSO
2. Scrape quiz pages for questions
3. Extract answer choices and correct answers
4. Generate `questions.json`

### Notes

- Uses browser automation (Playwright/Selenium) for SSO
- May need to handle MFA prompts manually
- Scraping approach — more fragile than Canvas API

---

## From PDFs

### Using ingest_pdf.py

Convert a PDF exam or practice test into structured questions:

```bash
python tools/ingest_pdf.py \
  --input "path/to/exam.pdf" \
  --output "packs/my-course/questions.json" \
  --source-exam "midterm_1_2024" \
  --append  # Append to existing questions.json
```

This script uses Claude to:

1. Extract text from the PDF
2. Identify individual questions
3. Parse answer choices
4. Determine correct answers (if answer key is provided)
5. Tag with concepts and topics

### Tips for PDF Ingestion

- Provide the answer key separately if not in the PDF
- Clean scans work better than photos
- Multiple-choice works best; free-response needs manual review
- Always verify the AI's answer parsing — spot-check at least 20%

---

## ChromaDB Ingestion

### Textbook Chunks

To enable RAG-powered explanations, ingest your textbook:

```bash
python tools/chunk_textbook.py \
  --input "path/to/textbook.pdf" \
  --pack "my-course" \
  --chunk-size 500 \
  --overlap 50
```

This creates a ChromaDB collection `my-course_textbook` with:
- Text chunks with chapter/section metadata
- Embeddings via all-MiniLM-L6-v2

### Lecture Slides

```bash
python tools/chunk_slides.py \
  --input "path/to/slides/" \
  --pack "my-course"
```

Each slide becomes a document with:
- OCR/extracted text
- Slide image path
- Deck name and page number
- Topic tags

---

## Getting LMS Access & Exam Materials

This is often the most important and most overlooked step. The quality of your pack depends directly on the quality of your source material.

### Why This Matters

Cram-It is most effective when it has **real exam questions** from your specific course. Generic practice problems help, but your professor's actual exam questions are gold — they reveal:

- Which concepts are actually tested
- The specific question styles used
- Common distractors and traps
- Topic weighting and distribution

### How to Get Materials

#### 1. Past Exams from Your LMS

Many professors post past exams on Canvas/Learning Suite. Check:
- **Course files** section
- **Modules** — look for "Review" or "Practice" sections
- **Quizzes** — past practice quizzes are often left up

#### 2. Canvas Quiz Scraping

If your professor uses Canvas quizzes:
- After submitting, you can often view correct answers
- Use the Canvas API to programmatically pull quiz data
- See the [Canvas Integration skill](./skills/canvas-integration.md) for details

#### 3. Study Groups / Exam Banks

Many schools have exam repositories:
- Student government exam banks
- Fraternity/sorority test files
- Course-specific study groups
- Previous semester's students

#### 4. Professor's Review Materials

- Attend review sessions and take detailed notes
- Ask your professor for practice exams
- Note which topics they emphasize

#### 5. Textbook Practice Questions

- End-of-chapter questions
- Online textbook resources (publisher websites)
- Study guides that accompany the textbook

### Browser-Based LMS Access

For automated scraping, you may need to provide browser access:

1. **Canvas API Token**: Generate from Account > Settings > Access Tokens
2. **Learning Suite**: Requires browser automation since there's no public API
3. **Chrome DevTools Protocol (CDP)**: For sites that require JavaScript rendering

See [LMS Integrations](./LMS_INTEGRATIONS.md) for detailed setup instructions.

### Legal & Ethical Note

- Only use materials you have legitimate access to
- Respect your school's academic integrity policies
- Don't share scraped exam content outside your study group
- Generated packs with real exam data should stay private

---

## Tips for Good Concept Maps

A well-designed concept map dramatically improves the tutor's effectiveness and the drill algorithm's ability to target weak areas.

### 1. Use Specific, Testable Concepts

Bad: `"chapter_5"` — too broad
Good: `"carbocation_stability"` — specific, testable

### 2. Define Prerequisites

```json
{
  "sn2_mechanism": {
    "prereqs": ["nucleophilicity", "leaving_groups", "steric_effects"],
    ...
  }
}
```

This helps the tutor know *what to teach first* when a student struggles.

### 3. Include Keywords

Keywords help with:
- Question auto-tagging
- ChromaDB search matching
- AI tutor context retrieval

### 4. Write Exam-Focused Descriptions

The description should focus on *how this gets tested*, not just what the concept is:

Bad: `"SN2 is a bimolecular nucleophilic substitution reaction."`
Good: `"SN2: backside attack, inversion of configuration, rate = k[Nu][substrate]. Tested via: identify mechanism from substrate + nucleophile, predict stereochemistry, compare rate with different substrates."`

### 5. Tag Every Question

Each question in `questions.json` should have at least one concept tag. This enables:
- Concept mastery tracking
- Weak spot identification
- Smart drill selection (Phase 3: unseen concepts)

### 6. Aim for 20-40 Concepts

- Fewer than 10: too coarse for meaningful tracking
- More than 50: too granular, mastery signals become noisy
- Sweet spot: ~25 concepts covering all exam material

### 7. Group into Categories

Use `concept_categories.json` to group concepts for the drill map:

```json
{
  "reactions": {
    "label": "Reactions & Mechanisms",
    "concepts": ["sn1_mechanism", "sn2_mechanism", "e1_mechanism", "e2_mechanism"]
  },
  "structure": {
    "label": "Structure & Bonding",
    "concepts": ["hybridization", "electronegativity_basics", "resonance"]
  }
}
```
