#!/usr/bin/env python3
"""
Ingest BYU Learning Suite Course into Cram-It Pack

Scrapes a BYU Learning Suite course for assignment and grade data,
then creates a Cram-It pack directory. Since Learning Suite doesn't
expose quiz questions via its web interface the same way Canvas does,
this tool focuses on:
  1. Pulling course structure (assignments, due dates)
  2. Extracting grade breakdowns
  3. Building a pack.yaml with course metadata
  4. Creating a skeleton concept_map.json from assignment names

For actual quiz questions, use ingest_pdf.py with exported exam PDFs.

Usage:
  python tools/ingest_learning_suite.py \\
      --course-url "https://learningsuite.byu.edu/.XXXX/cid-XXXXX/student/" \\
      --output-dir packs/econ110 \\
      --username your_netid --password your_password
"""

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

import yaml

# Allow running from project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.lms.learning_suite import LearningSuiteClient

try:
    import anthropic
    CLAUDE_AVAILABLE = True
except ImportError:
    CLAUDE_AVAILABLE = False


def build_concept_map_from_assignments(assignments: list[dict]) -> dict:
    """Use Claude to infer concepts from assignment names and structure.

    Since Learning Suite doesn't expose individual quiz questions,
    we use assignment names and course structure to build an initial
    concept map that can be refined later.

    Args:
        assignments: List of assignment dicts from Learning Suite scraper.

    Returns:
        Concept map dict.
    """
    if not CLAUDE_AVAILABLE or not assignments:
        return {}

    claude = anthropic.Anthropic()

    assignment_list = "\n".join(
        f"- {a['name']} (due: {a.get('due_date', 'unknown')})"
        for a in assignments
    )

    prompt = f"""Given these course assignments, identify the key academic concepts being taught:

{assignment_list}

Return ONLY valid JSON in this format:
{{
  "concept_id_snake_case": {{
    "name": "Human Readable Name",
    "prereqs": [],
    "keywords": ["keyword1", "keyword2"],
    "description": "Brief description."
  }}
}}"""

    try:
        import re
        response = claude.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text
        match = re.search(r'\{[\s\S]*\}', text)
        if match:
            return json.loads(match.group())
    except Exception as e:
        print(f"WARNING: Claude concept extraction failed: {e}")

    return {}


def main():
    parser = argparse.ArgumentParser(
        description="Ingest a BYU Learning Suite course into a Cram-It study pack.",
        epilog="Credentials can also be set via LS_USERNAME/LS_PASSWORD env vars.",
    )
    parser.add_argument(
        "--course-url",
        type=str,
        required=True,
        help='Full Learning Suite course URL (e.g. "https://learningsuite.byu.edu/.XXXX/cid-XXXXX/student/").',
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        required=True,
        help="Output directory for the pack (e.g. packs/econ110).",
    )
    parser.add_argument(
        "--username",
        type=str,
        default=None,
        help="BYU Net ID (overrides LS_USERNAME env var).",
    )
    parser.add_argument(
        "--password",
        type=str,
        default=None,
        help="BYU password (overrides LS_PASSWORD env var).",
    )
    parser.add_argument(
        "--skip-concepts",
        action="store_true",
        help="Skip Claude concept extraction from assignments.",
    )

    args = parser.parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Set env vars from CLI args if provided
    if args.username:
        os.environ["LS_USERNAME"] = args.username
    if args.password:
        os.environ["LS_PASSWORD"] = args.password

    # Authenticate
    print("Authenticating with BYU Learning Suite...")
    client = LearningSuiteClient()
    try:
        success = client.login(args.username, args.password)
        if not success:
            print("ERROR: Authentication failed. Check your credentials.")
            sys.exit(1)
    except ValueError as e:
        print(f"ERROR: {e}")
        sys.exit(1)

    # Scrape assignments
    print(f"\nScraping assignments from: {args.course_url}")
    assignments = client.get_assignments(args.course_url)
    print(f"Found {len(assignments)} assignments")

    # Scrape grades
    print("Scraping grades...")
    grades = client.get_grades(args.course_url)
    print(f"Found {len(grades)} grade entries")

    # Build concept map from assignment names
    concept_map = {}
    if not args.skip_concepts and assignments:
        print("\nExtracting concepts from assignments via Claude...")
        concept_map = build_concept_map_from_assignments(assignments)
        print(f"Identified {len(concept_map)} concepts")

    # Extract course name from URL
    import re
    url_match = re.search(r'/cid-(\w+)/', args.course_url)
    course_id = url_match.group(1) if url_match else "unknown"

    # Write pack.yaml
    pack_meta = {
        "name": f"Learning Suite Course {course_id}",
        "slug": f"ls-{course_id}",
        "source": "learning_suite",
        "course_url": args.course_url,
        "created_at": datetime.now().isoformat(),
        "total_assignments": len(assignments),
        "total_grade_entries": len(grades),
        "description": (
            f"Auto-imported from BYU Learning Suite. "
            f"Contains assignment structure and grades. "
            f"Add quiz questions via ingest_pdf.py."
        ),
    }

    pack_path = output_dir / "pack.yaml"
    with open(pack_path, "w") as f:
        yaml.dump(pack_meta, f, default_flow_style=False, sort_keys=False)
    print(f"\nWrote pack metadata: {pack_path}")

    # Write assignments.json (supplementary data)
    assignments_path = output_dir / "assignments.json"
    with open(assignments_path, "w") as f:
        json.dump(assignments, f, indent=2)
    print(f"Wrote assignments: {assignments_path}")

    # Write grades.json (supplementary data)
    grades_path = output_dir / "grades.json"
    with open(grades_path, "w") as f:
        json.dump(grades, f, indent=2)
    print(f"Wrote grades: {grades_path}")

    # Write concept_map.json
    concept_map_path = output_dir / "concept_map.json"
    with open(concept_map_path, "w") as f:
        json.dump(concept_map, f, indent=2)
    print(f"Wrote concept map: {concept_map_path}")

    # Write empty questions.json (to be populated via ingest_pdf.py)
    questions_path = output_dir / "questions.json"
    if not questions_path.exists():
        with open(questions_path, "w") as f:
            json.dump([], f, indent=2)
        print(f"Wrote empty questions.json (populate with ingest_pdf.py)")

    # Summary
    print(f"\n{'='*50}")
    print(f"Pack created at: {output_dir}")
    print(f"  pack.yaml:        course metadata")
    print(f"  assignments.json: {len(assignments)} assignments")
    print(f"  grades.json:      {len(grades)} grade entries")
    print(f"  concept_map.json: {len(concept_map)} concepts")
    print(f"  questions.json:   empty (use ingest_pdf.py to add questions)")
    print(f"{'='*50}")
    print(f"\nNOTE: Learning Suite doesn't expose quiz questions directly.")
    print(f"Export exams as PDFs and run:")
    print(f"  python tools/ingest_pdf.py --pdf exam.pdf --output-dir {args.output_dir}")


if __name__ == "__main__":
    main()
