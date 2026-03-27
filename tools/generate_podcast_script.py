#!/usr/bin/env python3
"""
Generate Podcast Script from Course Pack Content

Uses Claude to write a two-voice review podcast script based on the course
pack's questions, concept map, and knowledge graph. Outputs a formatted
script.txt with [VOICE1] and [VOICE2] markers ready for TTS generation.

VOICE1 = Host (asks questions, guides the conversation)
VOICE2 = Expert (explains concepts, gives exam tips)

Requirements:
  pip install anthropic pyyaml
  ANTHROPIC_API_KEY environment variable set

Usage:
  # Generate from a pack:
  python tools/generate_podcast_script.py --pack-dir packs/my-course

  # Focus on specific topic:
  python tools/generate_podcast_script.py --pack-dir packs/my-course --topic "market structures"

  # Custom output:
  python tools/generate_podcast_script.py --pack-dir packs/my-course -o my_script.txt
"""
import json
import os
import sys
import argparse
import yaml
from pathlib import Path
from dotenv import load_dotenv

# Load env
load_dotenv(Path(__file__).parent.parent / ".env")
load_dotenv(Path.home() / ".hermes/.env")


# ─────────────────────────────────────────────
# Minimum Content Requirements
# ─────────────────────────────────────────────
MIN_QUESTIONS = 10
MIN_CONCEPTS = 3


def validate_pack_readiness(pack_dir, force=False):
    """
    Check that a pack has enough content to produce a useful podcast.

    Requirements:
      - pack.yaml must exist (enforced elsewhere)
      - At least MIN_QUESTIONS questions in questions.json
      - At least MIN_CONCEPTS concepts in concept_map.json

    Returns (ok: bool, issues: list[str]).
    If force=True, prints warnings but doesn't block.
    """
    pack_path = Path(pack_dir)
    issues = []

    # Check questions
    q_path = pack_path / "questions.json"
    q_count = 0
    if q_path.exists():
        try:
            import json as _json
            with open(q_path) as f:
                data = _json.load(f)
            q_count = len(data) if isinstance(data, list) else len(data.values()) if isinstance(data, dict) else 0
        except Exception:
            q_count = 0
    if q_count < MIN_QUESTIONS:
        issues.append(
            f"questions.json has {q_count} questions (minimum: {MIN_QUESTIONS}). "
            f"Add {MIN_QUESTIONS - q_count} more questions before generating a podcast."
        )

    # Check concepts
    cm_path = pack_path / "concept_map.json"
    cm_count = 0
    if cm_path.exists():
        try:
            import json as _json
            with open(cm_path) as f:
                data = _json.load(f)
            cm_count = len(data) if isinstance(data, dict) else 0
        except Exception:
            cm_count = 0
    if cm_count < MIN_CONCEPTS:
        issues.append(
            f"concept_map.json has {cm_count} concepts (minimum: {MIN_CONCEPTS}). "
            f"Add {MIN_CONCEPTS - cm_count} more concepts before generating a podcast."
        )

    if issues:
        print("\n⚠️  PACK CONTENT CHECK FAILED")
        print("=" * 50)
        for issue in issues:
            print(f"  ✗ {issue}")
        print("=" * 50)
        if force:
            print("  --force flag set, proceeding anyway...\n")
            return True, issues
        else:
            print(
                "\nPodcast generation requires a minimum amount of coursework.\n"
                "This ensures the AI has enough material to produce a useful review.\n"
                "\nOptions:\n"
                "  1. Add more content to your pack (questions, concepts)\n"
                "  2. Use --force to override this check\n"
            )
            return False, issues

    print(f"✓ Pack content check passed ({q_count} questions, {cm_count} concepts)")
    return True, []


def load_pack_content(pack_dir):
    """
    Load all available content from a course pack directory.

    Returns dict with keys: config, questions, concept_map, knowledge_graph,
    exam_weights, concept_categories, flashcards
    """
    pack_path = Path(pack_dir)
    content = {}

    # Required: pack.yaml
    config_path = pack_path / "pack.yaml"
    if not config_path.exists():
        raise FileNotFoundError(f"pack.yaml not found in {pack_dir}")
    with open(config_path) as f:
        content["config"] = yaml.safe_load(f)

    # Optional data files
    optional_files = {
        "questions": "questions.json",
        "concept_map": "concept_map.json",
        "knowledge_graph": "knowledge_graph.json",
        "exam_weights": "exam_weights.json",
        "concept_categories": "concept_categories.json",
        "flashcards": "flashcards.json",
    }

    for key, filename in optional_files.items():
        filepath = pack_path / filename
        if filepath.exists():
            with open(filepath) as f:
                content[key] = json.load(f)
        else:
            content[key] = {}

    return content


def build_prompt(content, topic=None, target_minutes=10):
    """
    Build the Claude prompt for generating the podcast script.

    Args:
        content: Dict from load_pack_content()
        topic: Optional focus topic
        target_minutes: Target podcast length in minutes
    """
    config = content["config"]
    course_name = config.get("name", "this course")
    short_name = config.get("short_name", "the course")
    textbook = config.get("textbook", "the textbook")
    chapters = config.get("chapters", [])

    # Build content summary for Claude
    sections = []

    # Concept map summary
    concept_map = content.get("concept_map", {})
    if concept_map:
        concepts_list = []
        for cid, info in concept_map.items():
            if isinstance(info, dict):
                name = info.get("name", cid)
                desc = info.get("description", "")
                chapter = info.get("chapter", "?")
                concepts_list.append(f"- {name} (Ch.{chapter}): {desc}")
            else:
                concepts_list.append(f"- {cid}: {info}")
        sections.append("CONCEPTS:\n" + "\n".join(concepts_list[:50]))

    # Sample questions
    questions = content.get("questions", {})
    if isinstance(questions, list):
        q_sample = questions[:30]
    elif isinstance(questions, dict):
        q_sample = list(questions.values())[:30]
    else:
        q_sample = []

    if q_sample:
        q_texts = []
        for q in q_sample:
            if isinstance(q, dict):
                qt = q.get("question", q.get("text", str(q)))
                ans = q.get("correct_answer", q.get("answer", ""))
                q_texts.append(f"Q: {qt}\nA: {ans}")
            else:
                q_texts.append(str(q))
        sections.append("SAMPLE EXAM QUESTIONS:\n" + "\n\n".join(q_texts[:20]))

    # Knowledge graph
    kg = content.get("knowledge_graph", {})
    if kg:
        kg_summary = json.dumps(kg, indent=2)[:3000]
        sections.append(f"KNOWLEDGE GRAPH (excerpt):\n{kg_summary}")

    # Exam weights
    weights = content.get("exam_weights", {})
    if weights:
        w_lines = [f"- {k}: {v}" for k, v in weights.items()]
        sections.append("EXAM TOPIC WEIGHTS:\n" + "\n".join(w_lines))

    # Flashcards
    flashcards = content.get("flashcards", {})
    if isinstance(flashcards, list) and flashcards:
        fc_sample = flashcards[:15]
        fc_lines = []
        for fc in fc_sample:
            if isinstance(fc, dict):
                fc_lines.append(f"- {fc.get('front', fc.get('term', ''))}: {fc.get('back', fc.get('definition', ''))}")
        if fc_lines:
            sections.append("KEY FLASHCARDS:\n" + "\n".join(fc_lines))

    content_block = "\n\n".join(sections)

    topic_instruction = ""
    if topic:
        topic_instruction = f"\nFOCUS TOPIC: Focus primarily on '{topic}' and related concepts.\n"

    prompt = f"""Write a {target_minutes}-minute two-voice podcast script for studying {course_name} ({short_name}).

The podcast is a review/study session between a Host (VOICE1) and an Expert (VOICE2).

VOICE1 (Host): Friendly, curious, asks the questions students would ask. Keeps things moving.
VOICE2 (Expert): Knowledgeable, gives clear explanations, shares exam tips and common mistakes.
{topic_instruction}
FORMAT RULES:
- Each line must start with [VOICE1] or [VOICE2] followed by the spoken text
- NO stage directions, sound effects, or parenthetical notes
- NO markdown or special formatting
- Keep each line to 1-3 sentences (good for TTS pacing)
- Make it sound natural and conversational, not like reading a textbook
- Include a brief intro and outro
- Cover the most important/frequently tested concepts
- Include "exam tips" and "common mistakes" throughout
- For quantitative concepts, walk through example calculations

COURSE INFO:
- Course: {course_name}
- Textbook: {textbook}
- Chapters: {', '.join(str(c) for c in chapters) if chapters else 'All'}

{content_block}

Write the complete script now. Start with [VOICE1] for the intro."""

    return prompt


def generate_script(pack_dir, output_path=None, topic=None, target_minutes=10, model="claude-sonnet-4-20250514"):
    """
    Generate a podcast script from pack content using Claude.

    Args:
        pack_dir: Path to the course pack directory
        output_path: Where to write the script (default: <pack_dir>/podcast_script.txt)
        topic: Optional focus topic
        target_minutes: Target podcast duration in minutes
        model: Claude model to use

    Returns:
        Path to the generated script, or None on failure
    """
    import anthropic

    if output_path is None:
        output_path = os.path.join(pack_dir, "podcast_script.txt")

    # Load pack content
    print(f"Loading pack content from {pack_dir}...")
    content = load_pack_content(pack_dir)
    config = content["config"]
    print(f"  Course: {config.get('name', 'Unknown')}")
    print(f"  Concepts: {len(content.get('concept_map', {}))}")
    print(f"  Questions: {len(content.get('questions', {}))}")

    # Build prompt
    prompt = build_prompt(content, topic=topic, target_minutes=target_minutes)

    # Call Claude
    print(f"\nGenerating script with Claude ({model})...")
    client = anthropic.Anthropic()

    message = client.messages.create(
        model=model,
        max_tokens=8192,
        messages=[{"role": "user", "content": prompt}]
    )

    script_text = message.content[0].text

    # Validate: make sure it has [VOICE1] and [VOICE2] markers
    v1_count = script_text.count("[VOICE1]")
    v2_count = script_text.count("[VOICE2]")
    if v1_count == 0 or v2_count == 0:
        print(f"WARNING: Script may be malformed. VOICE1 count: {v1_count}, VOICE2 count: {v2_count}")

    # Write to file
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, "w") as f:
        f.write(f"# Podcast script for {config.get('name', 'course')}\n")
        f.write(f"# Generated by Cram-It podcast script generator\n")
        if topic:
            f.write(f"# Focus topic: {topic}\n")
        f.write(f"# Target duration: ~{target_minutes} minutes\n\n")
        f.write(script_text)

    total_lines = v1_count + v2_count
    print(f"\nScript written to: {output_path}")
    print(f"  {total_lines} dialogue lines ({v1_count} Host, {v2_count} Expert)")
    print(f"  Estimated duration: ~{target_minutes} minutes")

    return output_path


def main():
    parser = argparse.ArgumentParser(
        description="Generate a two-voice podcast script from course pack content",
        epilog="Requires: pip install anthropic pyyaml; ANTHROPIC_API_KEY env var"
    )
    parser.add_argument("--pack-dir", type=str, required=True,
                        help="Path to course pack directory (must contain pack.yaml)")
    parser.add_argument("--output", "-o", type=str, default=None,
                        help="Output script file path (default: <pack-dir>/podcast_script.txt)")
    parser.add_argument("--topic", type=str, default=None,
                        help="Focus topic or area (e.g., 'market structures', 'chapter 5')")
    parser.add_argument("--minutes", type=int, default=10,
                        help="Target podcast duration in minutes (default: 10)")
    parser.add_argument("--model", type=str, default="claude-sonnet-4-20250514",
                        help="Claude model to use (default: claude-sonnet-4-20250514)")
    parser.add_argument("--force", action="store_true",
                        help="Override minimum content requirements check")

    args = parser.parse_args()

    if not os.path.exists(os.path.join(args.pack_dir, "pack.yaml")):
        print(f"ERROR: pack.yaml not found in {args.pack_dir}")
        sys.exit(1)

    # Validate pack has enough content
    ok, issues = validate_pack_readiness(args.pack_dir, force=args.force)
    if not ok:
        sys.exit(1)

    result = generate_script(
        pack_dir=args.pack_dir,
        output_path=args.output,
        topic=args.topic,
        target_minutes=args.minutes,
        model=args.model,
    )

    if not result:
        sys.exit(1)


if __name__ == "__main__":
    main()
