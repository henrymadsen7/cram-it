#!/usr/bin/env python3
"""
Cram-It Course Pack Setup Wizard

Interactive guided wizard that walks users through creating a new course pack.
This is the first thing a new user should run after cloning the project.

Usage:
  Interactive:       python tools/setup_pack.py
  Non-interactive:   python tools/setup_pack.py --non-interactive --name "Econ 110" --short-name "ECON 110"
"""

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

# Project root (one level up from tools/)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
PACKS_DIR = PROJECT_ROOT / "packs"

# Try to import yaml; guide the user if missing
try:
    import yaml
except ImportError:
    print("ERROR: PyYAML is required but not installed.")
    print("Install it:  pip install pyyaml")
    print("Or:          pip install -r requirements.txt")
    sys.exit(1)


# ── Helpers ──────────────────────────────────────────────────────────────────

def slugify(text: str) -> str:
    """Convert a string to a URL/directory-friendly slug.

    Examples:
        'ECON 110'  -> 'econ-110'
        'Bio 201 - Genetics' -> 'bio-201-genetics'
    """
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)   # strip non-word chars (except hyphens)
    text = re.sub(r"[\s_]+", "-", text)     # spaces/underscores -> hyphens
    text = re.sub(r"-{2,}", "-", text)      # collapse multiple hyphens
    return text.strip("-")


def ask(prompt: str, default: str = "", required: bool = False) -> str:
    """Prompt the user for input with optional default value.

    Args:
        prompt: The question to display.
        default: Default value shown in brackets. Empty string means no default.
        required: If True, keep asking until a non-empty answer is provided.

    Returns:
        The user's input, or the default if they pressed Enter.
    """
    suffix = f" [{default}]" if default else ""
    while True:
        try:
            answer = input(f"  {prompt}{suffix}: ").strip()
        except EOFError:
            answer = ""
        if not answer and default:
            return default
        if answer:
            return answer
        if not required:
            return ""
        print("    This field is required. Please enter a value.")


def ask_yes_no(prompt: str, default: bool = False) -> bool:
    """Ask a yes/no question.

    Args:
        prompt: The question to display.
        default: Default answer if user just presses Enter.

    Returns:
        True for yes, False for no.
    """
    hint = "Y/n" if default else "y/N"
    while True:
        try:
            answer = input(f"  {prompt} [{hint}]: ").strip().lower()
        except EOFError:
            answer = ""
        if not answer:
            return default
        if answer in ("y", "yes"):
            return True
        if answer in ("n", "no"):
            return False
        print("    Please enter y or n.")


def parse_chapters(text: str) -> list:
    """Parse a comma-separated string of chapter numbers.

    Args:
        text: e.g. '1, 2, 3, 10-12'

    Returns:
        Sorted list of integers. Returns empty list if parsing fails.
    """
    if not text.strip():
        return []
    chapters = []
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        # Support range notation: 5-8
        if "-" in part:
            try:
                start, end = part.split("-", 1)
                for n in range(int(start.strip()), int(end.strip()) + 1):
                    chapters.append(n)
            except ValueError:
                pass
        else:
            try:
                chapters.append(int(part))
            except ValueError:
                pass
    return sorted(set(chapters))


def print_banner():
    """Print the welcome banner."""
    print()
    print("=" * 58)
    print("     Cram-It  --  New Course Pack Setup Wizard")
    print("=" * 58)
    print()
    print("  This wizard will walk you through creating a new")
    print("  course pack step by step. A course pack contains")
    print("  your questions, concept map, and study configuration.")
    print()
    print("  You can import questions from Canvas LMS or a PDF,")
    print("  or start with an empty pack and add questions later.")
    print()
    print("  Press Ctrl+C at any time to cancel.")
    print()
    print("-" * 58)


def print_step(num: int, title: str):
    """Print a step header."""
    print(f"\n  Step {num}: {title}")
    print(f"  {'~' * (len(title) + 8)}")


def build_pack_yaml(config: dict) -> dict:
    """Build the pack.yaml data structure.

    Args:
        config: Dict with keys: name, short_name, slug, textbook, professor,
                chapters, etc.

    Returns:
        Ordered dict ready for YAML serialization.
    """
    return {
        "name": config["name"],
        "short_name": config["short_name"],
        "slug": config["slug"],
        "description": config.get("description", ""),
        "textbook": config.get("textbook", ""),
        "professor": config.get("professor", ""),
        "exam_format": config.get("exam_format", {}),
        "chapters": config.get("chapters", []),
        "notes_allowed": config.get("notes_allowed", False),
        "calculator": config.get("calculator", False),
        "ai_persona_name": config.get("ai_persona_name", "Tutor"),
        "ai_persona": config.get("ai_persona", ""),
    }


def write_pack(pack_dir: Path, config: dict, questions: list | None = None,
               concept_map: dict | None = None):
    """Write all pack files to disk.

    Args:
        pack_dir: Target directory for the pack.
        config: Pack configuration dict.
        questions: List of question dicts (default: empty list).
        concept_map: Concept map dict (default: empty dict).
    """
    pack_dir.mkdir(parents=True, exist_ok=True)

    # pack.yaml
    pack_data = build_pack_yaml(config)
    with open(pack_dir / "pack.yaml", "w") as f:
        yaml.dump(pack_data, f, default_flow_style=False, sort_keys=False,
                  allow_unicode=True)

    # questions.json
    with open(pack_dir / "questions.json", "w") as f:
        json.dump(questions or [], f, indent=2)

    # concept_map.json
    with open(pack_dir / "concept_map.json", "w") as f:
        json.dump(concept_map or {}, f, indent=2)


def run_canvas_import(pack_dir: Path, api_url: str, api_token: str,
                      course_id: str) -> bool:
    """Run ingest_canvas.py as a subprocess.

    Args:
        pack_dir: Output directory for the pack.
        api_url: Canvas API base URL.
        api_token: Canvas API token.
        course_id: Canvas course ID.

    Returns:
        True if the import succeeded, False otherwise.
    """
    script = PROJECT_ROOT / "tools" / "ingest_canvas.py"
    if not script.exists():
        print(f"    ERROR: {script} not found.")
        return False

    cmd = [
        sys.executable, str(script),
        "--course-id", str(course_id),
        "--output-dir", str(pack_dir),
        "--api-url", api_url,
        "--api-token", api_token,
    ]
    print(f"\n    Running: python tools/ingest_canvas.py --course-id {course_id} ...")
    print()
    try:
        result = subprocess.run(cmd, cwd=str(PROJECT_ROOT))
        return result.returncode == 0
    except Exception as e:
        print(f"    ERROR running Canvas import: {e}")
        return False


def run_pdf_import(pack_dir: Path, pdf_path: str, course_name: str) -> bool:
    """Run ingest_pdf.py as a subprocess.

    Args:
        pack_dir: Output directory for the pack.
        pdf_path: Path to the PDF file.
        course_name: Course name for metadata.

    Returns:
        True if the import succeeded, False otherwise.
    """
    script = PROJECT_ROOT / "tools" / "ingest_pdf.py"
    if not script.exists():
        print(f"    ERROR: {script} not found.")
        return False

    # Resolve relative paths from the user's cwd, not the project root
    resolved_pdf = Path(pdf_path).expanduser()
    if not resolved_pdf.is_absolute():
        resolved_pdf = Path.cwd() / resolved_pdf
    resolved_pdf = resolved_pdf.resolve()

    if not resolved_pdf.exists():
        print(f"    ERROR: PDF file not found: {resolved_pdf}")
        return False

    cmd = [
        sys.executable, str(script),
        "--pdf", str(resolved_pdf),
        "--output-dir", str(pack_dir),
        "--course-name", course_name,
    ]
    print(f"\n    Running: python tools/ingest_pdf.py --pdf {resolved_pdf.name} ...")
    print()
    try:
        result = subprocess.run(cmd, cwd=str(PROJECT_ROOT))
        return result.returncode == 0
    except Exception as e:
        print(f"    ERROR running PDF import: {e}")
        return False


def print_summary(pack_dir: Path, config: dict, import_source: str):
    """Print a summary of what was created.

    Args:
        pack_dir: Path to the created pack directory.
        config: Pack configuration dict.
        import_source: 'canvas', 'pdf', or 'none'.
    """
    # Count questions if file exists
    q_count = 0
    q_path = pack_dir / "questions.json"
    if q_path.exists():
        try:
            with open(q_path) as f:
                q_count = len(json.load(f))
        except (json.JSONDecodeError, ValueError):
            pass

    # Count concepts if file exists
    c_count = 0
    c_path = pack_dir / "concept_map.json"
    if c_path.exists():
        try:
            with open(c_path) as f:
                c_count = len(json.load(f))
        except (json.JSONDecodeError, ValueError):
            pass

    print()
    print("=" * 58)
    print("     Pack Created Successfully!")
    print("=" * 58)
    print()
    print(f"  Course:     {config['name']}")
    print(f"  Short name: {config['short_name']}")
    print(f"  Slug:       {config['slug']}")
    print(f"  Directory:  {pack_dir}")
    print()
    print("  Files created:")
    print(f"    pack.yaml        - Pack configuration")
    print(f"    questions.json   - {q_count} question(s)")
    print(f"    concept_map.json - {c_count} concept(s)")
    if import_source == "canvas":
        print(f"    (imported from Canvas LMS)")
    elif import_source == "pdf":
        print(f"    (imported from PDF)")
    print()
    print("-" * 58)
    print("  Next steps:")
    print()
    step = 1
    if q_count == 0:
        print(f"  {step}. Add questions to questions.json")
        print("     (see packs/_template/questions.json for the schema)")
        print()
        step += 1
        print(f"  {step}. Or import questions from a source:")
        print(f"     python tools/ingest_pdf.py --pdf exam.pdf \\")
        print(f"       --output-dir {pack_dir.relative_to(PROJECT_ROOT)} \\")
        print(f"       --course-name \"{config['short_name']}\"")
        print()
        step += 1
    else:
        print(f"  {step}. Review your questions in questions.json")
        print()
        step += 1
    print(f"  {step}. Build a concept map:")
    print(f"     python tools/build_concept_map.py --pack {pack_dir.relative_to(PROJECT_ROOT)}")
    print()
    step += 1
    print(f"  {step}. Start studying!")
    print(f"     python server.py")
    print(f"     Then open http://localhost:8000 and select your pack.")
    print()
    print("=" * 58)


# ── Interactive Wizard ───────────────────────────────────────────────────────

def run_interactive():
    """Run the full interactive setup wizard."""
    print_banner()

    # ── Step 1: Course Name ──
    print_step(1, "Course Name")
    print("  The full name of your course, as shown in the UI.\n")
    name = ask("Course name", required=True)

    # ── Step 2: Short Name ──
    print_step(2, "Short Name")
    print("  A short identifier (e.g., 'ECON 110', 'BIO 201').\n")
    default_short = name if len(name) <= 20 else ""
    short_name = ask("Short name", default=default_short, required=True)

    # Auto-generate slug
    slug = slugify(short_name)
    pack_dir = PACKS_DIR / slug

    # Check if pack already exists
    if pack_dir.exists():
        print(f"\n    A pack already exists at: {pack_dir}")
        overwrite = ask_yes_no("Overwrite it?", default=False)
        if not overwrite:
            # Let user pick a different slug
            new_slug = ask("Enter a different slug", default=slug + "-2")
            slug = slugify(new_slug)
            pack_dir = PACKS_DIR / slug

    print(f"\n    Pack directory: packs/{slug}/")

    # ── Step 3: Textbook (optional) ──
    print_step(3, "Textbook (optional)")
    print("  The primary textbook used in this course.\n")
    textbook = ask("Textbook title")

    # ── Step 4: Professor (optional) ──
    print_step(4, "Professor (optional)")
    print("  Your professor or instructor's name.\n")
    professor = ask("Professor name")

    # ── Step 5: Chapters (optional) ──
    print_step(5, "Chapters (optional)")
    print("  Which chapters or units does this pack cover?")
    print("  Enter comma-separated numbers (e.g., 1,2,3 or 1-5,8,10).\n")
    chapters_str = ask("Chapters")
    chapters = parse_chapters(chapters_str)
    if chapters:
        print(f"    Chapters: {chapters}")

    # Build config so far
    config = {
        "name": name,
        "short_name": short_name,
        "slug": slug,
        "textbook": textbook,
        "professor": professor,
        "chapters": chapters,
        "description": "",
        "exam_format": {},
        "notes_allowed": False,
        "calculator": False,
        "ai_persona_name": "Tutor",
        "ai_persona": "",
    }

    import_source = "none"

    # ── Step 6: Canvas Import ──
    print_step(6, "Import from Canvas LMS")
    print("  Import quizzes and questions directly from Canvas.\n")
    use_canvas = ask_yes_no("Import from Canvas?", default=False)

    if use_canvas:
        print()
        api_url = ask("Canvas API URL (e.g., https://school.instructure.com)",
                       required=True)
        api_token = ask("Canvas API token", required=True)
        course_id = ask("Canvas course ID", required=True)

        # Ensure pack.yaml is written before import (import may overwrite)
        write_pack(pack_dir, config)
        success = run_canvas_import(pack_dir, api_url, api_token, course_id)
        if success:
            import_source = "canvas"
            print("\n    Canvas import complete!")
        else:
            print("\n    Canvas import had issues. Your empty pack was still created.")
            print("    You can retry later with: python tools/ingest_canvas.py")

    # ── Step 7: PDF Import ──
    if import_source == "none":
        print_step(7, "Import from PDF")
        print("  Import questions from an exam PDF using AI.\n")
        use_pdf = ask_yes_no("Import from a PDF?", default=False)

        if use_pdf:
            print()
            pdf_path = ask("Path to PDF file", required=True)

            # Ensure pack.yaml is written before import
            write_pack(pack_dir, config)
            success = run_pdf_import(pack_dir, pdf_path, short_name)
            if success:
                import_source = "pdf"
                print("\n    PDF import complete!")
            else:
                print("\n    PDF import had issues. Your empty pack was still created.")
                print("    You can retry later with: python tools/ingest_pdf.py")

    # ── Write pack files (if no import was done, or to ensure pack.yaml has our fields) ──
    if import_source == "none":
        write_pack(pack_dir, config)
    else:
        # Re-write pack.yaml to ensure it has all our fields,
        # but preserve questions.json and concept_map.json from the import
        pack_yaml_path = pack_dir / "pack.yaml"
        pack_data = build_pack_yaml(config)
        with open(pack_yaml_path, "w") as f:
            yaml.dump(pack_data, f, default_flow_style=False, sort_keys=False,
                      allow_unicode=True)

    # ── Summary ──
    print_summary(pack_dir, config, import_source)


# ── Non-Interactive Mode ─────────────────────────────────────────────────────

def run_non_interactive(args):
    """Run pack creation from CLI arguments (no prompts).

    Args:
        args: Parsed argparse namespace with all required fields.
    """
    if not args.name:
        print("ERROR: --name is required in non-interactive mode.")
        sys.exit(1)
    if not args.short_name:
        print("ERROR: --short-name is required in non-interactive mode.")
        sys.exit(1)

    slug = slugify(args.slug or args.short_name)
    pack_dir = PACKS_DIR / slug

    chapters = parse_chapters(args.chapters or "")

    config = {
        "name": args.name,
        "short_name": args.short_name,
        "slug": slug,
        "textbook": args.textbook or "",
        "professor": args.professor or "",
        "chapters": chapters,
        "description": args.description or "",
        "exam_format": {},
        "notes_allowed": False,
        "calculator": False,
        "ai_persona_name": args.ai_persona_name or "Tutor",
        "ai_persona": "",
    }

    import_source = "none"

    # Handle Canvas import
    if args.canvas_course_id:
        api_url = args.canvas_api_url or os.environ.get("CANVAS_API_URL", "")
        api_token = args.canvas_api_token or os.environ.get("CANVAS_API_TOKEN", "")
        if not api_url or not api_token:
            print("ERROR: Canvas import requires --canvas-api-url and --canvas-api-token")
            print("       (or CANVAS_API_URL and CANVAS_API_TOKEN env vars).")
            sys.exit(1)
        write_pack(pack_dir, config)
        success = run_canvas_import(pack_dir, api_url, api_token,
                                    args.canvas_course_id)
        if success:
            import_source = "canvas"

    # Handle PDF import
    if args.pdf and import_source == "none":
        write_pack(pack_dir, config)
        success = run_pdf_import(pack_dir, args.pdf, args.short_name)
        if success:
            import_source = "pdf"

    # Write pack files
    if import_source == "none":
        write_pack(pack_dir, config)
    else:
        # Re-write pack.yaml with our config, preserving imported data
        pack_data = build_pack_yaml(config)
        with open(pack_dir / "pack.yaml", "w") as f:
            yaml.dump(pack_data, f, default_flow_style=False, sort_keys=False,
                      allow_unicode=True)

    print_summary(pack_dir, config, import_source)


# ── CLI ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Cram-It Course Pack Setup Wizard",
        epilog=(
            "Examples:\n"
            "  Interactive:      python tools/setup_pack.py\n"
            "  Non-interactive:  python tools/setup_pack.py --non-interactive "
            '--name "Intro to Econ" --short-name "ECON 110"\n'
            "  With PDF import:  python tools/setup_pack.py --non-interactive "
            '--name "Bio 201" --short-name "BIO 201" --pdf midterm.pdf\n'
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "--non-interactive", action="store_true",
        help="Run without prompts (requires --name and --short-name).",
    )

    # Pack metadata
    parser.add_argument("--name", type=str, help="Full course name.")
    parser.add_argument("--short-name", type=str, dest="short_name",
                        help="Short name (e.g., 'ECON 110').")
    parser.add_argument("--slug", type=str,
                        help="Directory slug (auto-generated from short name if omitted).")
    parser.add_argument("--textbook", type=str, help="Textbook title.")
    parser.add_argument("--professor", type=str, help="Professor name.")
    parser.add_argument("--chapters", type=str,
                        help="Chapters covered (comma-separated, e.g., '1,2,3-5').")
    parser.add_argument("--description", type=str, help="Pack description.")
    parser.add_argument("--ai-persona-name", type=str, dest="ai_persona_name",
                        help="AI tutor display name (default: 'Tutor').")

    # Import options
    parser.add_argument("--pdf", type=str,
                        help="Path to exam PDF to import.")
    parser.add_argument("--canvas-course-id", type=str, dest="canvas_course_id",
                        help="Canvas course ID to import.")
    parser.add_argument("--canvas-api-url", type=str, dest="canvas_api_url",
                        help="Canvas API URL (or set CANVAS_API_URL env var).")
    parser.add_argument("--canvas-api-token", type=str, dest="canvas_api_token",
                        help="Canvas API token (or set CANVAS_API_TOKEN env var).")

    args = parser.parse_args()

    if args.non_interactive:
        run_non_interactive(args)
    else:
        try:
            run_interactive()
        except KeyboardInterrupt:
            print("\n\n  Setup cancelled. No files were created.\n")
            sys.exit(0)


if __name__ == "__main__":
    main()
