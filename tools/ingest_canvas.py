#!/usr/bin/env python3
"""
Ingest Canvas LMS Course into Cram-It Pack

Pulls quizzes and questions from a Canvas course via the REST API,
then uses Claude to auto-tag each question with concept IDs. Outputs
a complete Cram-It pack directory with:
  - pack.yaml        (pack metadata)
  - questions.json   (all MC questions in Cram-It format)
  - concept_map.json (concepts and prerequisites)

Usage:
  python tools/ingest_canvas.py --course-id 12345 --output-dir packs/econ110
  python tools/ingest_canvas.py --course-id 12345 --output-dir packs/econ110 \\
      --api-url https://school.instructure.com --api-token YOUR_TOKEN
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

from engine.lms.canvas import CanvasClient

try:
    import anthropic
    CLAUDE_AVAILABLE = True
except ImportError:
    CLAUDE_AVAILABLE = False


def tag_questions_with_concepts(questions: list[dict]) -> tuple[list[dict], dict]:
    """Use Claude to auto-tag questions with concept IDs.

    Sends all questions to Claude and asks it to:
    1. Identify the key concepts tested by each question
    2. Generate concept IDs (snake_case) for each
    3. Build a concept map with prerequisites

    Args:
        questions: List of Cram-It question dicts (without concept_tags).

    Returns:
        Tuple of (tagged_questions, concept_map).
    """
    if not CLAUDE_AVAILABLE:
        print("WARNING: anthropic package not installed. Skipping concept tagging.")
        concept_map = {}
        return questions, concept_map

    claude = anthropic.Anthropic()

    # Build a condensed version of questions for the prompt
    q_summary = []
    for i, q in enumerate(questions):
        q_summary.append({
            "idx": i,
            "text": q["question_text"][:300],
            "answer": q["correct_answer"],
            "choices": q["answer_choices"],
            "source": q.get("source_exam", "unknown"),
        })

    prompt = f"""Analyze these {len(q_summary)} exam questions and:

1. For EACH question, assign 1-3 concept_tag IDs (snake_case, descriptive).
2. Build a concept_map of ALL unique concepts found.

Questions:
{json.dumps(q_summary, indent=1)}

Return ONLY valid JSON with this exact structure:
{{
  "tagged": [
    {{"idx": 0, "concept_tags": ["concept_id_1", "concept_id_2"]}},
    ...
  ],
  "concept_map": {{
    "concept_id_1": {{
      "name": "Human-readable Concept Name",
      "prereqs": ["other_concept_id"],
      "keywords": ["keyword1", "keyword2"],
      "description": "Brief description of the concept."
    }}
  }}
}}"""

    try:
        response = claude.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text

        # Parse JSON from response
        import re
        match = re.search(r'\{[\s\S]*\}', text)
        if match:
            result = json.loads(match.group())
        else:
            print("WARNING: Could not parse Claude response for concept tagging.")
            return questions, {}

        # Apply tags to questions
        for item in result.get("tagged", []):
            idx = item.get("idx")
            tags = item.get("concept_tags", [])
            if idx is not None and 0 <= idx < len(questions):
                questions[idx]["concept_tags"] = tags

        concept_map = result.get("concept_map", {})
        print(f"Tagged {len(result.get('tagged', []))} questions with {len(concept_map)} concepts")
        return questions, concept_map

    except Exception as e:
        print(f"WARNING: Claude tagging failed: {e}")
        return questions, {}


def create_pack_yaml(course_info: dict, output_dir: Path, summary: dict) -> Path:
    """Generate a pack.yaml metadata file.

    Args:
        course_info: Course dict from Canvas API (has name, course_code, etc.).
        output_dir: Pack output directory.
        summary: Export summary with question counts.

    Returns:
        Path to the created pack.yaml file.
    """
    pack_meta = {
        "name": course_info.get("name", "Canvas Course"),
        "slug": course_info.get("course_code", "canvas-course").lower().replace(" ", "-"),
        "source": "canvas",
        "canvas_course_id": course_info.get("id"),
        "created_at": datetime.now().isoformat(),
        "total_questions": summary.get("total_questions", 0),
        "total_quizzes": summary.get("total_quizzes", 0),
        "description": f"Auto-imported from Canvas: {course_info.get('name', 'Unknown Course')}",
    }

    path = output_dir / "pack.yaml"
    with open(path, "w") as f:
        yaml.dump(pack_meta, f, default_flow_style=False, sort_keys=False)

    return path


def main():
    parser = argparse.ArgumentParser(
        description="Ingest a Canvas LMS course into a Cram-It study pack.",
        epilog="Set CANVAS_API_URL and CANVAS_API_TOKEN env vars, or use --api-url/--api-token.",
    )
    parser.add_argument(
        "--course-id",
        type=int,
        required=True,
        help="Canvas course ID to import.",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        required=True,
        help="Output directory for the pack (e.g. packs/econ110).",
    )
    parser.add_argument(
        "--api-url",
        type=str,
        default=None,
        help="Canvas API base URL (overrides CANVAS_API_URL env var).",
    )
    parser.add_argument(
        "--api-token",
        type=str,
        default=None,
        help="Canvas API token (overrides CANVAS_API_TOKEN env var).",
    )
    parser.add_argument(
        "--skip-tagging",
        action="store_true",
        help="Skip Claude concept tagging (faster, no API cost).",
    )

    args = parser.parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Override env vars if CLI args provided
    if args.api_url:
        os.environ["CANVAS_API_URL"] = args.api_url
    if args.api_token:
        os.environ["CANVAS_API_TOKEN"] = args.api_token

    # Initialize Canvas client
    try:
        client = CanvasClient()
    except ValueError as e:
        print(f"ERROR: {e}")
        sys.exit(1)

    # Fetch course info
    print(f"Fetching course {args.course_id}...")
    try:
        courses = client.list_courses()
        course_info = next((c for c in courses if c["id"] == args.course_id), None)
        if not course_info:
            course_info = {"id": args.course_id, "name": f"Course {args.course_id}"}
            print("WARNING: Could not find course in enrollment list. Using basic info.")
        else:
            print(f"Course: {course_info.get('name')}")
    except Exception as e:
        print(f"WARNING: Could not fetch course info: {e}")
        course_info = {"id": args.course_id, "name": f"Course {args.course_id}"}

    # Export quizzes to questions.json
    print("\nExporting quizzes...")
    summary = client.export_to_pack(args.course_id, str(output_dir))

    # Load the exported questions for tagging
    questions_path = output_dir / "questions.json"
    with open(questions_path) as f:
        questions = json.load(f)

    # Auto-tag with concepts using Claude
    concept_map = {}
    if not args.skip_tagging and questions:
        print("\nAuto-tagging questions with concepts via Claude...")
        questions, concept_map = tag_questions_with_concepts(questions)

        # Re-save tagged questions
        with open(questions_path, "w") as f:
            json.dump(questions, f, indent=2)

    # Write concept_map.json
    concept_map_path = output_dir / "concept_map.json"
    with open(concept_map_path, "w") as f:
        json.dump(concept_map, f, indent=2)
    print(f"Wrote concept map: {concept_map_path}")

    # Write pack.yaml
    pack_yaml_path = create_pack_yaml(course_info, output_dir, summary)
    print(f"Wrote pack metadata: {pack_yaml_path}")

    # Summary
    print(f"\n{'='*50}")
    print(f"Pack created at: {output_dir}")
    print(f"  questions.json:   {summary['total_questions']} questions")
    print(f"  concept_map.json: {len(concept_map)} concepts")
    print(f"  pack.yaml:        metadata")
    print(f"  Skipped:          {summary['skipped']} non-MC questions")
    print(f"{'='*50}")


if __name__ == "__main__":
    main()
