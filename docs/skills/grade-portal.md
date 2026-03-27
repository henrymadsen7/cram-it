# Skill: Grade Portal

## Overview

The Grade Portal skill covers fetching, parsing, and displaying grade data from Canvas LMS and Learning Suite. This data can be used for progress tracking, study prioritization, and exam score prediction.

---

## Canvas Grade Fetching

### Authentication

Uses the same Canvas API token as quiz scraping (see [Canvas Integration](./canvas-integration.md)):

```python
import requests

BASE_URL = "https://your-school.instructure.com/api/v1"
HEADERS = {"Authorization": f"Bearer {os.environ['CANVAS_API_TOKEN']}"}
```

### Fetching Enrollment Grades

```python
def get_canvas_course_grade(course_id):
    """Get overall course grade from Canvas."""
    response = requests.get(
        f"{BASE_URL}/courses/{course_id}/enrollments",
        headers=HEADERS,
        params={"user_id": "self", "include[]": "grades"}
    )
    enrollments = response.json()

    if enrollments:
        grades = enrollments[0].get('grades', {})
        return {
            "current_score": grades.get('current_score'),
            "current_grade": grades.get('current_grade'),
            "final_score": grades.get('final_score'),
            "final_grade": grades.get('final_grade'),
        }
    return None
```

### Fetching Assignment Scores

```python
def get_canvas_assignments(course_id):
    """Get all assignment scores for a Canvas course."""
    # Get assignments
    assignments = requests.get(
        f"{BASE_URL}/courses/{course_id}/assignments",
        headers=HEADERS,
        params={"per_page": 100, "order_by": "due_at"}
    ).json()

    # Get submissions
    results = []
    for assignment in assignments:
        sub = requests.get(
            f"{BASE_URL}/courses/{course_id}/assignments/{assignment['id']}/submissions/self",
            headers=HEADERS
        ).json()

        results.append({
            "name": assignment['name'],
            "due_at": assignment.get('due_at'),
            "points_possible": assignment.get('points_possible'),
            "score": sub.get('score'),
            "grade": sub.get('grade'),
            "submitted_at": sub.get('submitted_at'),
            "late": sub.get('late', False),
            "missing": sub.get('missing', False),
            "assignment_group_id": assignment.get('assignment_group_id'),
        })

    return results
```

### Fetching Assignment Groups (Categories)

```python
def get_canvas_assignment_groups(course_id):
    """Get assignment group weights (e.g., Exams 40%, Homework 30%)."""
    groups = requests.get(
        f"{BASE_URL}/courses/{course_id}/assignment_groups",
        headers=HEADERS,
        params={"include[]": "assignments"}
    ).json()

    return [{
        "id": g['id'],
        "name": g['name'],
        "weight": g.get('group_weight', 0),
        "assignments": len(g.get('assignments', [])),
    } for g in groups]
```

---

## Learning Suite Grade Fetching

Learning Suite does not have a public API. Grades must be scraped via browser automation.

### Authentication Flow

```python
from playwright.async_api import async_playwright

async def login_to_learning_suite():
    """Authenticate with Learning Suite via school SSO."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page()

        # Navigate to Learning Suite
        await page.goto("https://learningsuite.example.edu")

        # This redirects to SSO
        # Wait for user to complete login (including MFA)
        print("Please log in to Learning Suite...")
        await page.wait_for_url("**/learningsuite**/main**", timeout=120000)

        # Now we're authenticated — extract cookies
        cookies = await page.context.cookies()

        return browser, page, cookies
```

### Scraping Grades

```python
async def scrape_learning_suite_grades(page, course_url):
    """Scrape grades from a Learning Suite course page."""
    # Navigate to grades page
    await page.goto(f"{course_url}/grades")
    await page.wait_for_selector('.grade-table', timeout=10000)

    # Extract grade data
    grades = await page.evaluate("""
        () => {
            const rows = document.querySelectorAll('.grade-row');
            return Array.from(rows).map(row => ({
                name: row.querySelector('.assignment-name')?.textContent?.trim(),
                score: parseFloat(row.querySelector('.score')?.textContent) || null,
                max_score: parseFloat(row.querySelector('.max-score')?.textContent) || null,
                category: row.querySelector('.category')?.textContent?.trim(),
                weight: parseFloat(row.querySelector('.weight')?.textContent) || null,
            }));
        }
    """)

    return grades
```

---

## Output Formats

### Unified Grade Format

Both Canvas and Learning Suite data is normalized to:

```json
{
  "course_name": "Introduction to Microeconomics",
  "overall": {
    "current_score": 87.5,
    "current_grade": "B+",
    "projected_final": 85.2
  },
  "categories": [
    {
      "name": "Exams",
      "weight": 40.0,
      "score": 82.0,
      "assignments": [
        {"name": "Midterm 1", "score": 78, "max": 100},
        {"name": "Midterm 2", "score": 86, "max": 100}
      ]
    },
    {
      "name": "Homework",
      "weight": 30.0,
      "score": 95.0,
      "assignments": [
        {"name": "HW 1", "score": 10, "max": 10},
        {"name": "HW 2", "score": 9, "max": 10}
      ]
    }
  ],
  "upcoming": [
    {"name": "Final Exam", "due_at": "2025-04-15T14:00:00Z", "weight": 30.0}
  ]
}
```

### Grade Analysis

```python
def analyze_grades(grades_data):
    """Compute insights from grade data."""
    categories = grades_data['categories']

    # What grade do I need on the final?
    current_earned = sum(
        c['score'] * c['weight'] / 100
        for c in categories
        if c['score'] is not None
    )
    remaining_weight = sum(
        c['weight']
        for c in categories
        if c['score'] is None
    )

    targets = {}
    for target_grade, min_score in [('A', 93), ('A-', 90), ('B+', 87), ('B', 83)]:
        needed = (min_score - current_earned) / (remaining_weight / 100)
        targets[target_grade] = round(needed, 1)

    return {
        "current_weighted": round(current_earned, 1),
        "remaining_weight": remaining_weight,
        "needed_for": targets,
        "strongest_category": max(categories, key=lambda c: c.get('score', 0) or 0)['name'],
        "weakest_category": min(
            (c for c in categories if c.get('score') is not None),
            key=lambda c: c['score']
        )['name'],
    }
```

---

## Integration with Cram-It

### Study Prioritization

Grade data informs study prioritization:

```python
def prioritize_study(grades, concept_mastery):
    """Determine which concepts to study based on grades and mastery."""
    # Low exam scores → focus on weak exam concepts
    exam_categories = [c for c in grades['categories'] if 'exam' in c['name'].lower()]
    exam_score = sum(c.get('score', 0) or 0 for c in exam_categories) / len(exam_categories)

    # Map exam weakness to concepts
    weak_concepts = [
        cid for cid, mastery in concept_mastery.items()
        if mastery['mastery_pct'] < 60
    ]

    return {
        "exam_average": exam_score,
        "priority_concepts": weak_concepts[:10],
        "recommended_mode": "weak_spots" if exam_score < 80 else "drill",
        "hours_to_target": estimate_study_hours(weak_concepts, concept_mastery),
    }
```

### Projected Exam Score

```python
def project_exam_score(concept_mastery, exam_weights):
    """Project exam score from concept mastery data."""
    if not concept_mastery:
        return 0

    total_weight = sum(exam_weights.values())
    weighted_mastery = sum(
        concept_mastery.get(cid, {}).get('mastery_pct', 0) * weight
        for cid, weight in exam_weights.items()
    )

    return round(weighted_mastery / total_weight, 1) if total_weight > 0 else 0
```

---

## Auth Flow Summary

### Canvas

```
1. User generates API token in Canvas Settings
2. Token stored in .env as CANVAS_API_TOKEN
3. All API calls use Bearer token auth
4. Token has same permissions as the user
5. No MFA needed — token bypasses SSO
```

### Learning Suite

```
1. User opens browser automation window
2. Redirected to school SSO (CAS/SAML)
3. User enters credentials + MFA
4. Session cookie captured by Playwright
5. Subsequent requests use session cookie
6. Session expires after ~1 hour of inactivity
```

---

## Common Issues

### Canvas: "Unauthorized" (401)

- Token may have expired (if you set an expiry date)
- Token may have been revoked by admin
- Solution: Generate a new token in Canvas Settings

### Learning Suite: "Session Expired"

- SSO sessions time out
- Solution: Re-run the login flow

### Missing Grades

- Canvas: Some assignments may not have submissions yet
- Learning Suite: Grades may be hidden until a certain date
- Check the `missing` and `late` flags in the output

### Rate Limiting (Canvas)

- Canvas limits to ~700 requests / 10 minutes
- Grade fetching for a single course uses ~10-20 requests
- Batch fetching across many courses may hit limits
- Use `time.sleep(0.5)` between courses
