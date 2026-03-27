"""
Canvas LMS API Client for Cram-It

Connects to a Canvas LMS instance via its REST API to pull courses,
quizzes, and quiz questions into the Cram-It questions.json format.

Authentication:
  Set CANVAS_API_URL (e.g. "https://school.instructure.com") and
  CANVAS_API_TOKEN (your Canvas personal access token) as environment
  variables, or pass them directly to CanvasClient().

Canvas API reference:
  - GET /api/v1/courses
  - GET /api/v1/courses/:course_id/quizzes
  - GET /api/v1/courses/:course_id/quizzes/:quiz_id/questions
  - GET /api/v1/courses/:course_id/quizzes/:quiz_id/submissions

Usage:
  from engine.lms.canvas import CanvasClient
  client = CanvasClient()
  courses = client.list_courses()
  questions = client.get_quiz_questions(course_id=12345, quiz_id=678)
"""

import os
import json
import hashlib
from pathlib import Path
from typing import Optional

import requests


class CanvasClient:
    """Client for the Canvas LMS REST API.

    Reads CANVAS_API_URL and CANVAS_API_TOKEN from the environment
    unless explicitly provided at construction time.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_token: Optional[str] = None,
    ):
        self.base_url = (base_url or os.environ.get("CANVAS_API_URL", "")).rstrip("/")
        self.api_token = api_token or os.environ.get("CANVAS_API_TOKEN", "")

        if not self.base_url:
            raise ValueError(
                "Canvas API URL required. Set CANVAS_API_URL env var or pass base_url."
            )
        if not self.api_token:
            raise ValueError(
                "Canvas API token required. Set CANVAS_API_TOKEN env var or pass api_token."
            )

        self.session = requests.Session()
        self.session.headers.update(
            {"Authorization": f"Bearer {self.api_token}", "Accept": "application/json"}
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get(self, endpoint: str, params: Optional[dict] = None) -> list | dict:
        """Make an authenticated GET request, handling Canvas pagination.

        Canvas returns paginated results via Link headers. This method
        follows all 'next' links and returns the full result set.

        Args:
            endpoint: API path relative to /api/v1/ (e.g. "courses").
            params: Optional query parameters.

        Returns:
            Parsed JSON response (list or dict).
        """
        url = f"{self.base_url}/api/v1/{endpoint}"
        all_results = []

        while url:
            resp = self.session.get(url, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()

            if isinstance(data, list):
                all_results.extend(data)
            else:
                return data  # Single-object endpoints

            # Follow Canvas pagination
            links = resp.headers.get("Link", "")
            url = None
            for part in links.split(","):
                if 'rel="next"' in part:
                    url = part.split("<")[1].split(">")[0]
                    params = None  # URL already contains params
                    break

        return all_results

    # ------------------------------------------------------------------
    # Public API methods
    # ------------------------------------------------------------------

    def list_courses(self, enrollment_state: str = "active") -> list[dict]:
        """List all courses the authenticated user is enrolled in.

        Args:
            enrollment_state: Filter by enrollment state.
                Options: "active", "completed", "invited".

        Returns:
            List of course dicts with keys like:
              id, name, course_code, enrollment_term_id, etc.
        """
        return self._get(
            "courses", params={"enrollment_state": enrollment_state, "per_page": 100}
        )

    def get_quizzes(self, course_id: int) -> list[dict]:
        """List all quizzes in a course.

        Args:
            course_id: Canvas course ID.

        Returns:
            List of quiz dicts with keys like:
              id, title, description, quiz_type, question_count,
              points_possible, published, etc.
        """
        return self._get(f"courses/{course_id}/quizzes", params={"per_page": 100})

    def get_quiz_questions(self, course_id: int, quiz_id: int) -> list[dict]:
        """Fetch all questions from a specific quiz.

        Canvas returns question objects with fields like:
          id, question_name, question_text, question_type,
          answers (array of {id, text, weight}), points_possible.

        The 'weight' field on answers indicates correctness:
          weight=100 means correct, weight=0 means incorrect.

        Args:
            course_id: Canvas course ID.
            quiz_id: Canvas quiz ID.

        Returns:
            List of raw Canvas question objects.
        """
        return self._get(
            f"courses/{course_id}/quizzes/{quiz_id}/questions",
            params={"per_page": 100},
        )

    def get_submissions(self, course_id: int, quiz_id: int) -> list[dict]:
        """Fetch quiz submissions for the current user.

        Useful for checking which questions the student got wrong.
        Only returns submissions visible to the authenticated user
        (students see their own; teachers see all).

        Args:
            course_id: Canvas course ID.
            quiz_id: Canvas quiz ID.

        Returns:
            List of submission dicts with keys like:
              id, quiz_id, user_id, score, kept_score,
              attempt, workflow_state, etc.
        """
        return self._get(
            f"courses/{course_id}/quizzes/{quiz_id}/submissions",
            params={"per_page": 100},
        )

    # ------------------------------------------------------------------
    # Export helpers
    # ------------------------------------------------------------------

    def _convert_question(
        self, canvas_q: dict, quiz_title: str, quiz_id: int
    ) -> Optional[dict]:
        """Convert a Canvas question object to Cram-It questions.json format.

        Maps Canvas question types to the Cram-It schema. Currently
        supports multiple_choice_question and true_false_question types.
        Other types are skipped with a warning.

        Args:
            canvas_q: Raw Canvas question dict.
            quiz_title: Title of the source quiz (for source_exam field).
            quiz_id: Canvas quiz ID (for ID generation).

        Returns:
            Cram-It question dict, or None if the type is unsupported.
        """
        q_type = canvas_q.get("question_type", "")
        if q_type not in ("multiple_choice_question", "true_false_question"):
            print(f"  Skipping unsupported question type: {q_type}")
            return None

        # Build answer choices from Canvas answers array
        answers = canvas_q.get("answers", [])
        letters = ["A", "B", "C", "D", "E", "F"]
        answer_choices = {}
        correct_answer = None

        for i, ans in enumerate(answers):
            if i >= len(letters):
                break
            letter = letters[i]
            answer_choices[letter] = ans.get("text", ans.get("html", "")).strip()
            if ans.get("weight", 0) == 100:
                correct_answer = letter

        if not correct_answer or not answer_choices:
            return None

        # Generate a stable ID from Canvas IDs
        raw_id = f"canvas_{quiz_id}_{canvas_q.get('id', '')}"
        stable_id = hashlib.md5(raw_id.encode()).hexdigest()[:16]

        # Clean quiz title for source_exam field
        source_exam = quiz_title.lower().replace(" ", "_")[:50]

        return {
            "id": f"canvas_{stable_id}",
            "question_text": (
                canvas_q.get("question_text", "")
                .replace("<p>", "")
                .replace("</p>", "")
                .strip()
            ),
            "correct_answer": correct_answer,
            "answer_choices": answer_choices,
            "concept_tags": [],  # Populated later by Claude tagging
            "question_type": "multiple_choice",
            "source_exam": source_exam,
            "difficulty_score": None,
            "canvas_quiz_id": quiz_id,
            "canvas_question_id": canvas_q.get("id"),
        }

    def export_to_pack(self, course_id: int, output_dir: str) -> dict:
        """Export all quizzes from a Canvas course into Cram-It pack format.

        Creates a questions.json file containing all MC questions from
        every quiz in the course. Questions are converted to the standard
        Cram-It format with stable IDs derived from Canvas IDs.

        Args:
            course_id: Canvas course ID to export.
            output_dir: Directory to write questions.json into.

        Returns:
            Summary dict with keys:
              total_quizzes, total_questions, skipped, output_path.
        """
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)

        quizzes = self.get_quizzes(course_id)
        all_questions = []
        skipped = 0

        for quiz in quizzes:
            quiz_id = quiz["id"]
            quiz_title = quiz.get("title", f"quiz_{quiz_id}")
            print(f"Fetching quiz: {quiz_title} ({quiz.get('question_count', '?')} questions)")

            try:
                raw_questions = self.get_quiz_questions(course_id, quiz_id)
            except requests.HTTPError as e:
                print(f"  Error fetching questions: {e}")
                continue

            for raw_q in raw_questions:
                converted = self._convert_question(raw_q, quiz_title, quiz_id)
                if converted:
                    all_questions.append(converted)
                else:
                    skipped += 1

        # Write questions.json
        output_path = out / "questions.json"
        with open(output_path, "w") as f:
            json.dump(all_questions, f, indent=2)

        summary = {
            "total_quizzes": len(quizzes),
            "total_questions": len(all_questions),
            "skipped": skipped,
            "output_path": str(output_path),
        }
        print(f"\nExported {summary['total_questions']} questions from {summary['total_quizzes']} quizzes")
        print(f"Output: {output_path}")
        return summary


# ------------------------------------------------------------------
# Convenience functions (module-level)
# ------------------------------------------------------------------


def list_courses(**kwargs) -> list[dict]:
    """List courses using env-configured Canvas client."""
    return CanvasClient(**kwargs).list_courses()


def get_quizzes(course_id: int, **kwargs) -> list[dict]:
    """List quizzes for a course using env-configured Canvas client."""
    return CanvasClient(**kwargs).get_quizzes(course_id)


def get_quiz_questions(course_id: int, quiz_id: int, **kwargs) -> list[dict]:
    """Get quiz questions using env-configured Canvas client."""
    return CanvasClient(**kwargs).get_quiz_questions(course_id, quiz_id)


def get_submissions(course_id: int, quiz_id: int, **kwargs) -> list[dict]:
    """Get quiz submissions using env-configured Canvas client."""
    return CanvasClient(**kwargs).get_submissions(course_id, quiz_id)


def export_to_pack(course_id: int, output_dir: str, **kwargs) -> dict:
    """Export a course to Cram-It pack format using env-configured Canvas client."""
    return CanvasClient(**kwargs).export_to_pack(course_id, output_dir)
