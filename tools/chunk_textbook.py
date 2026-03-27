#!/usr/bin/env python3
"""
Chunk a Textbook PDF for ChromaDB Vector Store

Splits a textbook PDF into overlapping text segments suitable for
embedding in ChromaDB (or any vector database). Each chunk includes
metadata about its source page, chapter, and position.

Output Structure:
  textbook_chunks/
    chunks.json       - Array of all chunks with metadata
    chunk_000.txt     - Individual chunk files (optional, for inspection)
    chunk_001.txt
    ...

Chunk Format (in chunks.json):
  {
    "id": "chunk_000",
    "text": "The actual text content of this chunk...",
    "metadata": {
      "source_pdf": "textbook.pdf",
      "page_start": 45,
      "page_end": 46,
      "chunk_index": 0,
      "char_count": 1200,
      "word_count": 200
    }
  }

Usage:
  python tools/chunk_textbook.py --pdf textbook.pdf --output-dir packs/econ110
  python tools/chunk_textbook.py --pdf textbook.pdf --output-dir packs/econ110 --chunk-size 1500
"""

import argparse
import json
import re
import sys
from pathlib import Path

# Allow running from project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def extract_pages_from_pdf(pdf_path: str) -> list[dict]:
    """Extract text from each page of a PDF.

    Returns a list of dicts, each with 'page_num' and 'text' keys.
    Tries pdfplumber first, falls back to PyMuPDF.

    Args:
        pdf_path: Path to the PDF file.

    Returns:
        List of {"page_num": int, "text": str} dicts.

    Raises:
        ImportError: If neither pdfplumber nor PyMuPDF is installed.
    """
    try:
        import pdfplumber

        pages = []
        with pdfplumber.open(pdf_path) as pdf:
            for i, page in enumerate(pdf.pages):
                text = page.extract_text() or ""
                pages.append({"page_num": i + 1, "text": text})
        return pages

    except ImportError:
        pass

    try:
        import fitz  # PyMuPDF

        pages = []
        doc = fitz.open(pdf_path)
        for i, page in enumerate(doc):
            text = page.get_text() or ""
            pages.append({"page_num": i + 1, "text": text})
        doc.close()
        return pages

    except ImportError:
        pass

    raise ImportError(
        "PDF text extraction requires pdfplumber or PyMuPDF.\n"
        "Install one: pip install pdfplumber   OR   pip install PyMuPDF"
    )


def clean_text(text: str) -> str:
    """Clean extracted PDF text.

    Removes:
    - Excessive whitespace and blank lines
    - Page headers/footers (common patterns)
    - Non-printable characters

    Args:
        text: Raw extracted text.

    Returns:
        Cleaned text.
    """
    # Remove non-printable characters (keep newlines and tabs)
    text = re.sub(r'[^\x20-\x7E\n\t]', ' ', text)

    # Collapse multiple spaces
    text = re.sub(r'[ \t]+', ' ', text)

    # Collapse multiple blank lines into one
    text = re.sub(r'\n{3,}', '\n\n', text)

    # Remove common header/footer patterns (page numbers, etc.)
    text = re.sub(r'^\s*\d+\s*$', '', text, flags=re.MULTILINE)

    return text.strip()


def chunk_text(
    pages: list[dict],
    chunk_size: int = 1200,
    overlap: int = 200,
) -> list[dict]:
    """Split page-extracted text into overlapping chunks.

    Uses a sliding window approach:
    1. Concatenate all pages into a stream (preserving page boundaries)
    2. Split into chunks of approximately chunk_size characters
    3. Each chunk overlaps the previous by overlap characters
    4. Chunks break at sentence boundaries when possible

    Args:
        pages: List of {"page_num": int, "text": str} from extract_pages_from_pdf.
        chunk_size: Target size of each chunk in characters (default 1200).
        overlap: Number of overlapping characters between chunks (default 200).

    Returns:
        List of chunk dicts with id, text, and metadata.
    """
    # Build a list of (char_offset, page_num) mappings
    full_text = ""
    page_offsets = []  # (start_offset, page_num)

    for page in pages:
        cleaned = clean_text(page["text"])
        if not cleaned:
            continue
        page_offsets.append((len(full_text), page["page_num"]))
        full_text += cleaned + "\n\n"

    if not full_text.strip():
        return []

    # Sentence boundary pattern
    sentence_end = re.compile(r'[.!?]\s+')

    chunks = []
    start = 0
    chunk_index = 0

    while start < len(full_text):
        end = start + chunk_size

        # If not at the end, try to break at a sentence boundary
        if end < len(full_text):
            # Look for sentence end near the target end point
            search_start = max(end - 100, start)
            search_region = full_text[search_start:end + 100]
            matches = list(sentence_end.finditer(search_region))

            if matches:
                # Use the last sentence boundary in the search region
                best_match = matches[-1]
                end = search_start + best_match.end()
        else:
            end = len(full_text)

        chunk_text_content = full_text[start:end].strip()

        if not chunk_text_content or len(chunk_text_content) < 50:
            start = end - overlap if end < len(full_text) else len(full_text)
            continue

        # Determine which pages this chunk spans
        page_start = None
        page_end = None
        for offset, page_num in page_offsets:
            if offset <= start and (page_start is None or page_num > page_start):
                page_start = page_num
            if offset <= end:
                page_end = page_num

        page_start = page_start or 1
        page_end = page_end or page_start

        word_count = len(chunk_text_content.split())

        chunks.append({
            "id": f"chunk_{chunk_index:04d}",
            "text": chunk_text_content,
            "metadata": {
                "page_start": page_start,
                "page_end": page_end,
                "chunk_index": chunk_index,
                "char_count": len(chunk_text_content),
                "word_count": word_count,
            },
        })

        chunk_index += 1
        start = end - overlap

    return chunks


def main():
    parser = argparse.ArgumentParser(
        description="Chunk a textbook PDF into segments for ChromaDB embedding.",
        epilog="Requires pdfplumber or PyMuPDF for text extraction.",
    )
    parser.add_argument(
        "--pdf",
        type=str,
        required=True,
        help="Path to the textbook PDF file.",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        required=True,
        help="Output directory (textbook_chunks/ will be created inside it).",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=1200,
        help="Target chunk size in characters (default: 1200).",
    )
    parser.add_argument(
        "--overlap",
        type=int,
        default=200,
        help="Overlap between chunks in characters (default: 200).",
    )
    parser.add_argument(
        "--save-individual",
        action="store_true",
        help="Also save each chunk as an individual .txt file.",
    )

    args = parser.parse_args()

    pdf_path = Path(args.pdf)
    if not pdf_path.exists():
        print(f"ERROR: PDF file not found: {pdf_path}")
        sys.exit(1)

    chunks_dir = Path(args.output_dir) / "textbook_chunks"
    chunks_dir.mkdir(parents=True, exist_ok=True)

    # Step 1: Extract pages
    print(f"Extracting text from: {pdf_path.name}")
    try:
        pages = extract_pages_from_pdf(str(pdf_path))
    except ImportError as e:
        print(f"ERROR: {e}")
        sys.exit(1)

    non_empty = sum(1 for p in pages if p["text"].strip())
    print(f"Extracted {len(pages)} pages ({non_empty} with text)")

    if non_empty == 0:
        print("ERROR: No text found in PDF. It may be a scanned image requiring OCR.")
        sys.exit(1)

    # Step 2: Chunk the text
    print(f"Chunking with size={args.chunk_size}, overlap={args.overlap}...")
    chunks = chunk_text(pages, chunk_size=args.chunk_size, overlap=args.overlap)
    print(f"Created {len(chunks)} chunks")

    if not chunks:
        print("ERROR: No chunks created. The PDF may have insufficient text.")
        sys.exit(1)

    # Add source PDF to all chunk metadata
    for chunk in chunks:
        chunk["metadata"]["source_pdf"] = pdf_path.name

    # Step 3: Write chunks.json
    chunks_json_path = chunks_dir / "chunks.json"
    with open(chunks_json_path, "w") as f:
        json.dump(chunks, f, indent=2)
    print(f"Wrote chunks: {chunks_json_path}")

    # Step 4: Optionally write individual chunk files
    if args.save_individual:
        for chunk in chunks:
            chunk_path = chunks_dir / f"{chunk['id']}.txt"
            with open(chunk_path, "w") as f:
                f.write(chunk["text"])
        print(f"Wrote {len(chunks)} individual chunk files")

    # Summary statistics
    total_chars = sum(c["metadata"]["char_count"] for c in chunks)
    total_words = sum(c["metadata"]["word_count"] for c in chunks)
    avg_chars = total_chars // len(chunks) if chunks else 0
    avg_words = total_words // len(chunks) if chunks else 0

    print(f"\n{'='*50}")
    print(f"Textbook chunking complete: {pdf_path.name}")
    print(f"  Output:       {chunks_dir}")
    print(f"  Total chunks: {len(chunks)}")
    print(f"  Avg size:     {avg_chars} chars / {avg_words} words per chunk")
    print(f"  Total text:   {total_chars:,} chars / {total_words:,} words")
    print(f"  Page range:   {pages[0]['page_num']}-{pages[-1]['page_num']}")
    print(f"{'='*50}")
    print(f"\nReady for ChromaDB embedding. Load chunks.json into your vector store.")


if __name__ == "__main__":
    main()
