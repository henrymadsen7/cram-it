#!/usr/bin/env python3
"""
Build Concept Map from Syllabus

Takes a course syllabus (PDF or plain text) and uses Claude to identify
the key concepts, their prerequisites, and relationships. Outputs a
concept_map.json compatible with the Cram-It study engine.

The concept map drives:
  - Prerequisite-aware question ordering
  - Knowledge gap detection
  - Study path recommendations
  - Concept mastery tracking

Output Format (concept_map.json):
  {
    "concept_id": {
      "name": "Human Readable Name",
      "chapter": 14,
      "prereqs": ["other_concept_id"],
      "keywords": ["keyword1", "keyword2"],
      "description": "Brief description of the concept."
    }
  }

Usage:
  python tools/build_concept_map.py --syllabus syllabus.pdf --output-dir packs/econ110
  python tools/build_concept_map.py --syllabus syllabus.txt --output-dir packs/econ110
"""

import argparse
import json
import re
import sys
from pathlib import Path

# Allow running from project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    import anthropic
    CLAUDE_AVAILABLE = True
except ImportError:
    CLAUDE_AVAILABLE = False


def extract_syllabus_text(syllabus_path: str) -> str:
    """Extract text from a syllabus file (PDF or plain text).

    Supports:
    - .txt files (read directly)
    - .pdf files (via pdfplumber or PyMuPDF)
    - .md files (read directly)

    Args:
        syllabus_path: Path to the syllabus file.

    Returns:
        Extracted text content.
    """
    path = Path(syllabus_path)
    suffix = path.suffix.lower()

    if suffix in (".txt", ".md", ".text"):
        return path.read_text(encoding="utf-8")

    if suffix == ".pdf":
        try:
            import pdfplumber
            text_parts = []
            with pdfplumber.open(str(path)) as pdf:
                for page in pdf.pages:
                    page_text = page.extract_text()
                    if page_text:
                        text_parts.append(page_text)
            return "\n\n".join(text_parts)
        except ImportError:
            pass

        try:
            import fitz  # PyMuPDF
            text_parts = []
            doc = fitz.open(str(path))
            for page in doc:
                page_text = page.get_text()
                if page_text.strip():
                    text_parts.append(page_text)
            doc.close()
            return "\n\n".join(text_parts)
        except ImportError:
            pass

        raise ImportError(
            "PDF reading requires pdfplumber or PyMuPDF.\n"
            "Install one: pip install pdfplumber   OR   pip install PyMuPDF"
        )

    raise ValueError(f"Unsupported file format: {suffix}. Use .txt, .md, or .pdf")


def build_concept_map_with_claude(syllabus_text: str) -> dict:
    """Use Claude to analyze a syllabus and build a concept map.

    Claude identifies:
    1. Key academic concepts from the course schedule/topics
    2. Prerequisite relationships between concepts
    3. Keywords associated with each concept
    4. Chapter/week numbers where concepts appear
    5. Brief descriptions suitable for study guidance

    Args:
        syllabus_text: Full text of the course syllabus.

    Returns:
        Concept map dict keyed by concept_id (snake_case).
    """
    if not CLAUDE_AVAILABLE:
        print("ERROR: anthropic package required for concept map generation.")
        print("Install it: pip install anthropic")
        sys.exit(1)

    claude = anthropic.Anthropic()

    # Truncate very long syllabi
    max_chars = 30000
    if len(syllabus_text) > max_chars:
        print(f"WARNING: Syllabus text is {len(syllabus_text)} chars. Truncating to {max_chars}.")
        syllabus_text = syllabus_text[:max_chars]

    prompt = f"""Analyze this course syllabus and build a comprehensive concept map.

SYLLABUS:
{syllabus_text}

INSTRUCTIONS:
1. Identify ALL key academic concepts that students need to master in this course.
2. For each concept, determine:
   - A snake_case ID (concise, descriptive)
   - A human-readable name
   - Chapter or week number (if identifiable from the schedule)
   - Prerequisites (which other concepts must be understood first)
   - Keywords (terms a student would search for)
   - A brief description (1-2 sentences explaining the concept)
3. Order concepts roughly by when they appear in the course.
4. Ensure prerequisite chains are logical (no circular dependencies).
5. Aim for 15-40 concepts depending on the course scope.

Return ONLY valid JSON in this exact format:
{{
  "concept_id_snake_case": {{
    "name": "Human Readable Concept Name",
    "chapter": 1,
    "prereqs": ["prerequisite_concept_id"],
    "keywords": ["keyword1", "keyword2", "keyword3"],
    "description": "Brief explanation of what this concept covers and why it matters."
  }},
  "another_concept_id": {{
    "name": "Another Concept",
    "chapter": 2,
    "prereqs": ["concept_id_snake_case"],
    "keywords": ["term1", "term2"],
    "description": "Description of this concept."
  }}
}}

IMPORTANT:
- Use snake_case for all concept IDs.
- prereqs should only reference other concept IDs in the map.
- Keep descriptions concise but informative.
- Include foundational concepts even if they seem basic.
- Chapter can be null if not determinable from the syllabus."""

    try:
        response = claude.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=8192,
            messages=[{"role": "user", "content": prompt}],
        )
        text_resp = response.content[0].text

        # Parse JSON from response
        match = re.search(r'\{[\s\S]*\}', text_resp)
        if match:
            concept_map = json.loads(match.group())
        else:
            print("ERROR: Could not parse Claude response as JSON.")
            return {}

        # Validate the concept map structure
        validated = {}
        all_ids = set(concept_map.keys())

        for cid, concept in concept_map.items():
            if not isinstance(concept, dict):
                continue

            # Ensure required fields exist
            validated[cid] = {
                "name": concept.get("name", cid.replace("_", " ").title()),
                "chapter": concept.get("chapter"),
                "prereqs": [
                    p for p in concept.get("prereqs", [])
                    if p in all_ids and p != cid  # Remove invalid/self-referencing prereqs
                ],
                "keywords": concept.get("keywords", []),
                "description": concept.get("description", ""),
            }

        return validated

    except json.JSONDecodeError as e:
        print(f"ERROR: Failed to parse Claude response as JSON: {e}")
        return {}
    except Exception as e:
        print(f"ERROR: Claude concept map generation failed: {e}")
        return {}


def validate_no_cycles(concept_map: dict) -> list[str]:
    """Check for circular dependencies in the concept map.

    Uses depth-first search to detect cycles in the prerequisite graph.

    Args:
        concept_map: The concept map to validate.

    Returns:
        List of warning messages about cycles found (empty if none).
    """
    warnings = []
    visited = set()
    in_stack = set()

    def dfs(node, path):
        if node in in_stack:
            cycle_start = path.index(node)
            cycle = " -> ".join(path[cycle_start:] + [node])
            warnings.append(f"Circular dependency detected: {cycle}")
            return
        if node in visited:
            return

        visited.add(node)
        in_stack.add(node)
        path.append(node)

        for prereq in concept_map.get(node, {}).get("prereqs", []):
            if prereq in concept_map:
                dfs(prereq, path[:])

        in_stack.discard(node)

    for concept_id in concept_map:
        if concept_id not in visited:
            dfs(concept_id, [])

    return warnings


def main():
    parser = argparse.ArgumentParser(
        description="Build a concept map from a course syllabus using Claude.",
        epilog="Requires the anthropic package. Supports PDF and text syllabi.",
    )
    parser.add_argument(
        "--syllabus",
        type=str,
        required=True,
        help="Path to the syllabus file (.pdf, .txt, or .md).",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        required=True,
        help="Output directory for concept_map.json.",
    )
    parser.add_argument(
        "--merge",
        action="store_true",
        help="Merge with existing concept_map.json instead of overwriting.",
    )

    args = parser.parse_args()

    syllabus_path = Path(args.syllabus)
    if not syllabus_path.exists():
        print(f"ERROR: Syllabus file not found: {syllabus_path}")
        sys.exit(1)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Step 1: Extract syllabus text
    print(f"Reading syllabus: {syllabus_path.name}")
    try:
        text = extract_syllabus_text(str(syllabus_path))
    except (ImportError, ValueError) as e:
        print(f"ERROR: {e}")
        sys.exit(1)

    if not text.strip():
        print("ERROR: No text extracted from syllabus file.")
        sys.exit(1)

    word_count = len(text.split())
    print(f"Extracted {word_count} words")

    # Step 2: Build concept map with Claude
    print("\nAnalyzing syllabus with Claude...")
    concept_map = build_concept_map_with_claude(text)

    if not concept_map:
        print("ERROR: No concepts could be extracted.")
        sys.exit(1)

    print(f"Identified {len(concept_map)} concepts")

    # Step 3: Validate prerequisites
    warnings = validate_no_cycles(concept_map)
    for w in warnings:
        print(f"WARNING: {w}")

    # Step 4: Optionally merge with existing concept map
    output_path = output_dir / "concept_map.json"

    if args.merge and output_path.exists():
        print(f"\nMerging with existing concept map...")
        with open(output_path) as f:
            existing = json.load(f)

        # New concepts override existing ones with the same ID
        merged = {**existing, **concept_map}
        concept_map = merged
        print(f"Merged map has {len(concept_map)} total concepts")

    # Step 5: Write concept_map.json
    with open(output_path, "w") as f:
        json.dump(concept_map, f, indent=2)
    print(f"Wrote concept map: {output_path}")

    # Summary
    prereq_count = sum(
        len(c.get("prereqs", []))
        for c in concept_map.values()
    )
    root_concepts = [
        cid for cid, c in concept_map.items()
        if not c.get("prereqs")
    ]
    leaf_concepts = [
        cid for cid in concept_map
        if not any(cid in c.get("prereqs", []) for c in concept_map.values())
    ]

    chapters = sorted(set(
        c.get("chapter") for c in concept_map.values()
        if c.get("chapter") is not None
    ))

    print(f"\n{'='*50}")
    print(f"Concept map built from: {syllabus_path.name}")
    print(f"  Total concepts:   {len(concept_map)}")
    print(f"  Prerequisite links: {prereq_count}")
    print(f"  Root concepts:    {len(root_concepts)} (no prerequisites)")
    print(f"  Leaf concepts:    {len(leaf_concepts)} (nothing depends on them)")
    if chapters:
        print(f"  Chapters covered: {', '.join(str(c) for c in chapters)}")
    if warnings:
        print(f"  Warnings:         {len(warnings)} circular dependencies")
    print(f"  Output:           {output_path}")
    print(f"{'='*50}")


if __name__ == "__main__":
    main()
