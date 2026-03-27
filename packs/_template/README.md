# Cram-It Pack Template

Copy this entire `_template/` folder to create a new course pack.

```
cp -r packs/_template packs/your-course-slug
```

## File Reference

| File | Purpose |
|------|---------|
| `pack.yaml` | **Required.** Course metadata, exam format, AI persona settings. |
| `questions.json` | **Required.** Array of multiple-choice (or other) questions with answers, concepts, and explanations. |
| `concept_map.json` | Concept graph — each concept has a name, description, chapter, and list of prerequisite concepts. Used by the AI to sequence learning. |
| `exam_weights.json` | How heavily each concept is weighted on the exam (0.0–1.0). Drives the smart-quiz algorithm. |
| `concept_categories.json` | Groups concepts into broader categories for the dashboard and progress tracking. |
| `flashcards.json` | Array of `{front, back, concept, chapter}` flashcard objects for spaced-repetition review. |

---

## Schema Details

### questions.json

```json
[
  {
    "id": 1,
    "question": "The question text?",
    "choices": {
      "A": "First option",
      "B": "Second option",
      "C": "Third option",
      "D": "Fourth option"
    },
    "answer": "C",
    "concept": "concept_slug",
    "chapter": 1,
    "difficulty": "easy | medium | hard",
    "explanation": "Why C is correct."
  }
]
```

### concept_map.json

```json
{
  "concept_slug": {
    "name": "Human-Readable Name",
    "description": "One-sentence explanation of this concept.",
    "chapter": 1,
    "prerequisites": ["other_concept_slug"]
  }
}
```

### exam_weights.json

```json
{
  "concept_slug": 0.25,
  "other_concept": 0.15
}
```

Values should roughly sum to 1.0.

### concept_categories.json

```json
{
  "Category Name": ["concept_slug", "other_concept"],
  "Another Category": ["third_concept"]
}
```

### flashcards.json

```json
[
  {
    "front": "Question or prompt",
    "back": "Answer or explanation",
    "concept": "concept_slug",
    "chapter": 1
  }
]
```

---

## Tips

- **Slug naming:** Use lowercase with underscores for concept slugs (`spaced_repetition`, not `Spaced Repetition`).
- **IDs:** Question IDs should be unique integers starting at 1.
- **Chapters:** Use integers that match `chapters` in `pack.yaml`.
- **Difficulty:** Use `easy`, `medium`, or `hard`.
- **AI Persona:** Write a clear system prompt in `pack.yaml`. The AI will stay in character.
