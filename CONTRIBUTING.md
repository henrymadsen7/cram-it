# Contributing to Cram-It

This is a student-built project. We keep things simple. If you want to help — whether it's fixing a bug, adding a course pack, or building a new LMS integration — here's how.

## Quick Start

```bash
# 1. Fork the repo on GitHub, then:
git clone https://github.com/YOUR_USERNAME/cram-it.git
cd cram-it

# 2. Install dependencies (use a venv if you want)
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 3. Copy .env.example to .env and add your API keys
cp .env.example .env

# 4. Run the server
python server.py
# or: make run

# 5. Open http://localhost:3000, poke around, break things, fix things.
```

## Code Style

- **Python 3.11+**. We use modern syntax — `match`, `|` union types, etc.
- **No type stubs needed.** Inline type hints are fine but don't stress about full coverage.
- **Flask patterns.** Routes in `server.py`, engine logic in `engine/`, CLI tools in `tools/`.
- **Use `pathlib`** for all file paths. No `os.path.join()`.
- **Docstrings on public functions.** One-liner is fine for simple ones. See `engine/lms/canvas.py` for the style we like.
- **No linter wars.** Just be consistent with what's already there.

## How to Add a Course Pack

Course packs live in `packs/`. Each pack is a folder with questions, metadata, and optional concept maps.

1. **Copy the template:**
   ```bash
   cp -r packs/_template packs/your-course-slug
   ```
   Use lowercase, hyphens for the folder name (e.g., `econ-110`, `bio-201`).

2. **Fill out `pack.yaml`:**
   Open `packs/your-course-slug/pack.yaml` and fill in the course name, short name, textbook, professor, exam format, chapters, and AI persona. Every field is documented with comments in the template.

3. **Add questions:**
   Edit `questions.json`. Each question needs an `id`, `text`, `choices`, `correct_answer`, and `concept` tag. Look at `packs/demo-study-skills/questions.json` for the format.

4. **Optional files:**
   - `flashcards.json` — flashcard decks
   - `concept_map.json` — concept graph for the knowledge map view
   - `concept_categories.json` — groupings for concept categories
   - `exam_weights.json` — how much each topic is weighted on the exam

5. **Test it:**
   ```bash
   python server.py
   ```
   Select your pack in the UI. Make sure questions load, the tutor works, and the concept map renders (if you added one).

See `docs/CREATING_PACKS.md` for the full spec.

## How to Add an LMS Integration

LMS clients live in `engine/lms/`. Each one is a Python class that talks to an LMS API.

1. **Create the client** at `engine/lms/your_lms.py`.

2. **Follow the Canvas pattern.** `engine/lms/canvas.py` is the reference implementation. Your client should:
   - Accept credentials via constructor args or environment variables
   - Have a `list_courses()` method
   - Have methods to pull quizzes/questions
   - Convert questions to Cram-It's `questions.json` format
   - Use `requests.Session()` for HTTP
   - Handle pagination if the API uses it

3. **Write an ingest tool** at `tools/ingest_your_lms.py`. This is the CLI script students actually run. Pattern:
   ```bash
   python tools/ingest_canvas.py --course-id 12345 --output-dir packs/econ110
   ```
   Use `argparse`, import your client from `engine/lms/`, and output a complete pack directory. See `tools/ingest_canvas.py` for the exact structure.

4. **Update `engine/lms/__init__.py`** docstring to list your new platform.

5. **Add docs** — update `docs/LMS_INTEGRATIONS.md` with setup instructions for your LMS.

## How to Add a Tool

CLI tools live in `tools/`. They do things like ingest content, generate podcasts, build concept maps, etc.

1. **Create** `tools/your_tool.py`.
2. **Use `argparse`** for CLI arguments. Include a `--help` description.
3. **Add `#!/usr/bin/env python3`** and a module docstring with usage examples.
4. **Use `pathlib`** for paths, and add `sys.path.insert(0, ...)` if you need to import from `engine/`.
5. **Document it** — if it's podcast-related, add to `docs/PODCAST_GUIDE.md`. Otherwise, mention it in the relevant doc or in `README.md`.

Existing tools for reference:
- `tools/ingest_canvas.py` — pulls from Canvas LMS
- `tools/ingest_learning_suite.py` — pulls from BYU Learning Suite
- `tools/ingest_pdf.py` — extracts questions from PDFs
- `tools/generate_podcast.py` — generates study podcasts
- `tools/build_concept_map.py` — auto-generates concept maps
- `tools/chunk_textbook.py` — chunks textbook content for RAG

## Pull Request Process

### Branch naming
- `feat/short-description` — new features
- `fix/short-description` — bug fixes
- `docs/short-description` — documentation only
- `pack/course-name` — new course packs

### Commit messages
Keep them short and useful:
```
feat: add Blackboard LMS client
fix: concept map crashes on empty graph
docs: add deployment instructions for Railway
pack: add ECON 110 final exam pack
```

### Before submitting
- [ ] The server starts without errors (`python server.py`)
- [ ] Your new pack loads in the UI (if you added one)
- [ ] Your tool runs with `--help` and produces expected output (if you added one)
- [ ] You didn't commit `.env`, API keys, or `__pycache__/`
- [ ] You added/updated docs if needed

### Review
- Keep PRs focused. One feature or fix per PR.
- If it's a big change, open an issue first to discuss.
- We'll review within a few days. Be patient — we're students too.

## Reporting Issues

When filing an issue, include:

- **Python version** (`python --version`)
- **OS** (macOS, Windows, Linux distro)
- **Which pack** you were using (if applicable)
- **What you did** (steps to reproduce)
- **What happened** (full error output, traceback)
- **What you expected** to happen

Use the issue templates if they fit. If not, just be clear.

## Code of Conduct

This is short because it should be obvious:

1. **Be respectful.** We're all learning. Don't be a jerk in issues, PRs, or discussions.
2. **No academic dishonesty.** Cram-It is a study tool, not a cheating tool. Don't submit PRs that facilitate cheating (e.g., scraping live exam answers, bypassing proctoring software). We will reject them.
3. **Give credit.** If you use someone else's code or ideas, attribute them.
4. **Keep it constructive.** Criticism of code is fine. Criticism of people is not.

That's it. Go build something cool.
