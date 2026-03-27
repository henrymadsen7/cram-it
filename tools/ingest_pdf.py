#!/usr/bin/env python3
"""
Ingest Exam PDF into Cram-It questions.json Format

Extracts text from exam PDFs and uses Claude to parse multiple-choice
questions with answer keys into the standard Cram-It format.

Supports:
  - Scanned and digital PDFs (via pdfplumber/PyMuPDF)
  - Various MC question formats (numbered, lettered, etc.)
  - Answer keys at the end of the document
  - Multi-page exams

Usage:
  python tools/ingest_pdf.py --pdf exam1.pdf --output-dir packs/econ110 --course-name "Econ 110"
  python tools/ingest_pdf.py --pdf midterm.pdf --output-dir packs/bio100 --course-name "Bio 100"
"""

import argparse
import hashlib
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


def extract_text_from_pdf(pdf_path: str) -> str:
    """Extract text from a PDF file.

    Tries pdfplumber first (better for tabular/structured content),
    falls back to PyMuPDF (fitz) if pdfplumber is unavailable.

    Args:
        pdf_path: Path to the PDF file.

    Returns:
        Extracted text as a single string.

    Raises:
        ImportError: If neither pdfplumber nor PyMuPDF is installed.
    """
    try:
        import pdfplumber

        text_parts = []
        with pdfplumber.open(pdf_path) as pdf:
            for i, page in enumerate(pdf.pages):
                page_text = page.extract_text()
                if page_text:
                    text_parts.append(f"--- Page {i + 1} ---\n{page_text}")
        return "\n\n".join(text_parts)

    except ImportError:
        pass

    try:
        import fitz  # PyMuPDF

        text_parts = []
        doc = fitz.open(pdf_path)
        for i, page in enumerate(doc):
            page_text = page.get_text()
            if page_text.strip():
                text_parts.append(f"--- Page {i + 1} ---\n{page_text}")
        doc.close()
        return "\n\n".join(text_parts)

    except ImportError:
        pass

    raise ImportError(
        "PDF text extraction requires pdfplumber or PyMuPDF.\n"
        "Install one: pip install pdfplumber   OR   pip install PyMuPDF"
    )


def parse_questions_with_claude(
    text: str, course_name: str, pdf_filename: str
) -> list[dict]:
    """Use Claude to parse extracted PDF text into structured MC questions.

    Claude analyzes the raw text and identifies:
    - Question numbers and text
    - Answer choices (A, B, C, D, etc.)
    - Correct answers (from answer key if present, or marked answers)
    - Question topics/concepts

    Args:
        text: Raw text extracted from the PDF.
        course_name: Course name for metadata (e.g. "Econ 110").
        pdf_filename: Original PDF filename for source_exam field.

    Returns:
        List of questions in Cram-It format.
    """
    if not CLAUDE_AVAILABLE:
        print("ERROR: anthropic package required for question parsing.")
        print("Install it: pip install anthropic")
        sys.exit(1)

    claude = anthropic.Anthropic()

    # Truncate very long PDFs to stay within context limits
    max_chars = 80000
    if len(text) > max_chars:
        print(f"WARNING: PDF text is {len(text)} chars. Truncating to {max_chars}.")
        text = text[:max_chars]

    source_exam = Path(pdf_filename).stem.lower().replace(" ", "_")

    prompt = f"""Parse this exam PDF text into structured multiple-choice questions.

COURSE: {course_name}
SOURCE FILE: {pdf_filename}

PDF TEXT:
{text}

INSTRUCTIONS:
1. Find ALL multiple-choice questions in the text.
2. Extract the question text, all answer choices, and the correct answer.
3. If there's an answer key section, use it. Otherwise, mark correct_answer as null.
4. Assign 1-3 concept tags (snake_case) to each question based on what it tests.
5. Classify question_type as: "conceptual", "calculation", "definition", or "application".

Return ONLY a valid JSON array:
[
  {{
    "question_text": "Full question text without the question number",
    "correct_answer": "A",
    "answer_choices": {{"A": "choice text", "B": "choice text", "C": "choice text", "D": "choice text"}},
    "concept_tags": ["concept_id"],
    "question_type": "conceptual",
    "source_exam": "{source_exam}"
  }}
]

IMPORTANT:
- Use uppercase letters (A, B, C, D) for answer choices and correct_answer.
- Strip any HTML or formatting artifacts from the text.
- If you can't determine the correct answer, set it to null.
- Include ALL questions you can find, even partial ones."""

    try:
        response = claude.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=8192,
            messages=[{"role": "user", "content": prompt}],
        )
        text_resp = response.content[0].text

        # Parse JSON array from response
        match = re.search(r'\[[\s\S]*\]', text_resp)
        if match:
            raw_questions = json.loads(match.group())
        else:
            print("ERROR: Could not parse Claude response as JSON array.")
            return []

        # Normalize and add IDs
        questions = []
        for i, q in enumerate(raw_questions):
            if not q.get("question_text"):
                continue

            # Generate stable ID from content
            content_hash = hashlib.md5(
                q["question_text"][:100].encode()
            ).hexdigest()[:12]
            qid = f"pdf_{source_exam}_{content_hash}"

            questions.append({
                "id": qid,
                "question_text": q["question_text"].strip(),
                "correct_answer": q.get("correct_answer"),
                "answer_choices": q.get("answer_choices", {}),
                "concept_tags": q.get("concept_tags", []),
                "question_type": q.get("question_type", "multiple_choice"),
                "source_exam": q.get("source_exam", source_exam),
                "difficulty_score": None,
            })

        return questions

    except Exception as e:
        print(f"ERROR: Claude parsing failed: {e}")
        return []


def main():
    parser = argparse.ArgumentParser(
        description="Ingest an exam PDF into Cram-It questions.json format.",
        epilog="Requires pdfplumber or PyMuPDF for text extraction, and anthropic for parsing.",
    )
    parser.add_argument(
        "--pdf",
        type=str,
        required=True,
        help="Path to the exam PDF file.",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        required=True,
        help="Output directory for the pack (e.g. packs/econ110).",
    )
    parser.add_argument(
        "--course-name",
        type=str,
        required=True,
        help="Course name for metadata (e.g. 'Econ 110').",
    )
    parser.add_argument(
        "--append",
        action="store_true",
        help="Append to existing questions.json instead of overwriting.",
    )

    args = parser.parse_args()

    pdf_path = Path(args.pdf)
    if not pdf_path.exists():
        print(f"ERROR: PDF file not found: {pdf_path}")
        sys.exit(1)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Step 1: Extract text from PDF
    print(f"Extracting text from: {pdf_path.name}")
    try:
        text = extract_text_from_pdf(str(pdf_path))
    except ImportError as e:
        print(f"ERROR: {e}")
        sys.exit(1)

    if not text.strip():
        print("ERROR: No text extracted from PDF. It may be a scanned image.")
        print("TIP: Use OCR software first, then try again.")
        sys.exit(1)

    print(f"Extracted {len(text)} characters from {text.count('--- Page')} pages")

    # Step 2: Parse questions with Claude
    print(f"\nParsing questions with Claude...")
    questions = parse_questions_with_claude(text, args.course_name, pdf_path.name)

    if not questions:
        print("ERROR: No questions could be parsed from the PDF.")
        sys.exit(1)

    print(f"Parsed {len(questions)} questions")

    # Count questions with/without answers
    with_answers = sum(1 for q in questions if q["correct_answer"])
    without_answers = len(questions) - with_answers
    print(f"  With correct answer:    {with_answers}")
    print(f"  Without correct answer: {without_answers}")

    # Step 3: Write or append to questions.json
    questions_path = output_dir / "questions.json"

    if args.append and questions_path.exists():
        with open(questions_path) as f:
            existing = json.load(f)
        existing_ids = {q["id"] for q in existing}
        new_questions = [q for q in questions if q["id"] not in existing_ids]
        existing.extend(new_questions)
        questions_to_write = existing
        print(f"\nAppending {len(new_questions)} new questions (skipped {len(questions) - len(new_questions)} duplicates)")
    else:
        questions_to_write = questions

    with open(questions_path, "w") as f:
        json.dump(questions_to_write, f, indent=2)
    print(f"Wrote {len(questions_to_write)} questions to: {questions_path}")

    # Summary
    print(f"\n{'='*50}")
    print(f"PDF ingestion complete: {pdf_path.name}")
    print(f"  Output: {questions_path}")
    print(f"  Questions: {len(questions)}")
    print(f"  Course: {args.course_name}")
    if without_answers:
        print(f"\n  NOTE: {without_answers} questions have no answer key.")
        print(f"  You can manually add correct_answer values in questions.json.")
    print(f"{'='*50}")


if __name__ == "__main__":
    main()
