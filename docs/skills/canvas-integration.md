# Skill: Canvas LMS Integration

## Overview

Cram-It integrates with Canvas LMS to pull quiz questions, course structure, and grade data. This skill covers the API patterns, scraping approaches, and data format conversion.

---

## Canvas API Basics

### Authentication

All Canvas API calls use a Bearer token:

```python
import requests

BASE_URL = "https://your-school.instructure.com/api/v1"
TOKEN = "your_canvas_api_token"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}

def canvas_get(endpoint, params=None):
    url = f"{BASE_URL}/{endpoint}"
    response = requests.get(url, headers=HEADERS, params=params)
    response.raise_for_status()
    return response.json()
```

### Pagination

Canvas uses Link header pagination:

```python
def canvas_get_all(endpoint, params=None):
    """Fetch all pages of a paginated Canvas API endpoint."""
    url = f"{BASE_URL}/{endpoint}"
    all_items = []
    params = params or {}
    params['per_page'] = 100

    while url:
        response = requests.get(url, headers=HEADERS, params=params)
        response.raise_for_status()
        all_items.extend(response.json())

        # Check for next page
        links = response.headers.get('Link', '')
        url = None
        for link in links.split(','):
            if 'rel="next"' in link:
                url = link.split(';')[0].strip('<> ')
                params = None  # URL already has params
                break

    return all_items
```

### Rate Limiting

```python
import time

def canvas_get_safe(endpoint, params=None):
    """Canvas API call with rate limit handling."""
    response = requests.get(
        f"{BASE_URL}/{endpoint}",
        headers=HEADERS,
        params=params
    )

    # Check rate limit
    remaining = int(response.headers.get('X-Rate-Limit-Remaining', 100))
    if remaining < 50:
        time.sleep(1)  # Back off when getting close to limit

    if response.status_code == 403:
        # Rate limited — wait and retry
        time.sleep(10)
        return canvas_get_safe(endpoint, params)

    response.raise_for_status()
    return response.json()
```

---

## Quiz Scraping

### Approach 1: Canvas Quiz API (Preferred)

```python
def scrape_quizzes(course_id):
    """Pull all quizzes and their questions from a Canvas course."""
    questions = []

    # Get all quizzes
    quizzes = canvas_get_all(f"courses/{course_id}/quizzes")

    for quiz in quizzes:
        quiz_id = quiz['id']
        quiz_title = quiz['title']
        print(f"Processing: {quiz_title}")

        # Get questions for this quiz
        quiz_questions = canvas_get_all(
            f"courses/{course_id}/quizzes/{quiz_id}/questions"
        )

        for q in quiz_questions:
            if q['question_type'] == 'multiple_choice_question':
                question = convert_canvas_mc(q, quiz_title)
                if question:
                    questions.append(question)
            elif q['question_type'] == 'true_false_question':
                question = convert_canvas_tf(q, quiz_title)
                if question:
                    questions.append(question)
            # Skip: essay, matching, fill_in_the_blank, etc.

    return questions
```

### Converting Canvas Question Format

Canvas questions have a specific JSON format:

```python
def convert_canvas_mc(canvas_q, source_exam):
    """Convert a Canvas multiple_choice_question to Cram-It format."""
    answers = canvas_q.get('answers', [])
    if not answers:
        return None

    # Build choices dict
    choices = {}
    correct_answer = None
    for i, ans in enumerate(answers):
        letter = chr(97 + i)  # a, b, c, d...
        choices[letter] = clean_html(ans.get('text', '') or ans.get('html', ''))
        if ans.get('weight', 0) > 0:
            correct_answer = letter.upper()

    if not correct_answer or len(choices) < 2:
        return None

    return {
        "id": f"canvas_{canvas_q['id']}",
        "question_text": clean_html(canvas_q.get('question_text', '')),
        "correct_answer": correct_answer,
        "answer_choices": choices,
        "concept_tags": [],  # Will be AI-tagged later
        "topic_tags": [],
        "question_type": "conceptual",
        "source_exam": source_exam,
        "frequency_tier": "medium",
        "has_chart": bool(canvas_q.get('question_text', '').find('<table') >= 0),
        "chart_table": extract_table(canvas_q.get('question_text', '')),
        "figure_image": extract_image(canvas_q.get('question_text', '')),
    }

def clean_html(html_text):
    """Strip HTML tags from Canvas question text."""
    from html import unescape
    import re
    text = re.sub(r'<[^>]+>', '', html_text)
    return unescape(text).strip()
```

### Approach 2: Chrome DevTools Protocol (CDP)

For cases where the API doesn't expose answer keys (e.g., you need to view the quiz review page in the browser):

```python
from playwright.async_api import async_playwright

async def scrape_quiz_review_page(course_id, quiz_id):
    """Scrape the quiz review page for answers using browser automation."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context()
        page = await context.new_page()

        # Navigate to Canvas login
        await page.goto(f"{BASE_URL.replace('/api/v1', '')}/login")

        # Wait for manual login (handles SSO, MFA, etc.)
        print("Please log in to Canvas in the browser window...")
        await page.wait_for_url("**/dashboard**", timeout=120000)

        # Navigate to quiz review
        review_url = f"{BASE_URL.replace('/api/v1', '')}/courses/{course_id}/quizzes/{quiz_id}"
        await page.goto(review_url)

        # Extract questions from the review page HTML
        questions = await page.evaluate("""
            () => {
                const items = document.querySelectorAll('.question');
                return Array.from(items).map(q => ({
                    text: q.querySelector('.question_text')?.textContent?.trim(),
                    answers: Array.from(q.querySelectorAll('.answer')).map(a => ({
                        text: a.textContent?.trim(),
                        correct: a.classList.contains('correct_answer'),
                    })),
                }));
            }
        """)

        await browser.close()
        return questions
```

### When to Use CDP vs API

| Scenario | Use API | Use CDP |
|----------|---------|---------|
| Published quiz with visible answers | ✅ | |
| Quiz review page after submission | | ✅ |
| Bulk quiz data extraction | ✅ | |
| Questions behind JavaScript rendering | | ✅ |
| Rate-limited or no API token | | ✅ |

---

## Data Format Conversion

### Canvas → Cram-It Question Format

```python
def convert_all_questions(canvas_questions, source_exam):
    """Convert a list of Canvas questions to Cram-It format."""
    cram_questions = []
    for cq in canvas_questions:
        q_type = cq.get('question_type', '')

        if q_type == 'multiple_choice_question':
            converted = convert_canvas_mc(cq, source_exam)
        elif q_type == 'true_false_question':
            converted = convert_canvas_tf(cq, source_exam)
        elif q_type == 'short_answer_question':
            converted = convert_canvas_short_answer(cq, source_exam)
        else:
            print(f"  Skipping unsupported type: {q_type}")
            continue

        if converted:
            cram_questions.append(converted)

    return cram_questions
```

### AI Concept Tagging

After extraction, use Claude to tag questions with concepts:

```python
def ai_tag_questions(questions, concept_map):
    """Use Claude to add concept_tags to each question."""
    concept_list = "\n".join([
        f"- {cid}: {cdata['name']} — {cdata['description']}"
        for cid, cdata in concept_map.items()
    ])

    for q in questions:
        prompt = f"""Given these course concepts:
{concept_list}

Tag this question with the most relevant concept IDs (1-3 tags):
Q: {q['question_text'][:300]}
Choices: {json.dumps(q.get('answer_choices', {}))}

Return ONLY a JSON array of concept IDs, e.g.: ["concept_a", "concept_b"]"""

        response = claude.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}]
        )

        try:
            tags = json.loads(response.content[0].text)
            q['concept_tags'] = [t for t in tags if t in concept_map]
        except:
            q['concept_tags'] = ["general"]

    return questions
```

---

## Grade Fetching

### Get Course Grades

```python
def get_grades(course_id):
    """Fetch all assignment grades for the current user."""
    enrollments = canvas_get(
        f"courses/{course_id}/enrollments",
        params={"user_id": "self", "include[]": "grades"}
    )

    assignments = canvas_get_all(f"courses/{course_id}/assignments")

    grades = []
    for assignment in assignments:
        submission = canvas_get(
            f"courses/{course_id}/assignments/{assignment['id']}/submissions/self"
        )
        grades.append({
            "name": assignment['name'],
            "score": submission.get('score'),
            "max_score": assignment.get('points_possible'),
            "category": assignment.get('assignment_group_id'),
            "submitted_at": submission.get('submitted_at'),
        })

    return grades
```

---

## Common Patterns

### Error Handling

```python
def safe_canvas_get(endpoint, default=None):
    """Canvas API call that returns default on failure."""
    try:
        return canvas_get(endpoint)
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 404:
            return default
        elif e.response.status_code == 401:
            print("Canvas API token expired or invalid")
            return default
        raise
```

### Filtering by Date

```python
def get_recent_quizzes(course_id, since_date):
    """Get quizzes created or updated after a date."""
    quizzes = canvas_get_all(f"courses/{course_id}/quizzes")
    return [q for q in quizzes
            if q.get('updated_at', '') >= since_date]
```

### Handling Images in Questions

Canvas questions may contain embedded images:

```python
import re, urllib.request

def extract_and_download_images(question_html, output_dir):
    """Download images from Canvas question HTML."""
    img_pattern = r'<img[^>]+src="([^"]+)"'
    images = re.findall(img_pattern, question_html)

    local_paths = []
    for i, url in enumerate(images):
        if url.startswith('/'):
            url = BASE_URL.replace('/api/v1', '') + url
        local_path = f"{output_dir}/fig_{i}.png"
        urllib.request.urlretrieve(url, local_path)
        local_paths.append(local_path)

    return local_paths
```
