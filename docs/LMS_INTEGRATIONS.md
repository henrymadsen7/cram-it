# LMS Integrations

Cram-It can pull course content from various Learning Management Systems. This guide covers setup for Canvas, Learning Suite, and Cengage.

---

## Table of Contents

1. [Canvas LMS](#canvas-lms)
2. [Learning Suite](#learning-suite)
3. [Cengage / MindTap](#cengage--mindtap)
4. [General Data Flow](#general-data-flow)

---

## Canvas LMS

Canvas is the most well-supported integration, using the official REST API.

### Getting Your API Token

1. Log in to your Canvas instance (e.g., `https://your-school.instructure.com`)
2. Go to **Account** > **Settings**
3. Scroll to **Approved Integrations**
4. Click **+ New Access Token**
5. Set a purpose (e.g., "Cram-It study tool") and optional expiry
6. Copy the token — you won't see it again

### Configuration

Add to your `.env`:

```bash
CANVAS_BASE_URL=https://your-school.instructure.com
CANVAS_API_TOKEN=your_token_here
```

### Finding Your Course ID

The course ID is in the Canvas URL:
```
https://your-school.instructure.com/courses/12345
                                            ^^^^^
                                         Course ID
```

### What the API Can Access

| Resource | API Endpoint | What You Get |
|----------|-------------|--------------|
| Quizzes | `GET /courses/:id/quizzes` | Quiz metadata |
| Quiz Questions | `GET /courses/:id/quizzes/:qid/questions` | Questions + choices |
| Quiz Submissions | `GET /courses/:id/quizzes/:qid/submissions` | Your answers + scores |
| Assignments | `GET /courses/:id/assignments` | Assignment details |
| Modules | `GET /courses/:id/modules` | Course structure |
| Files | `GET /courses/:id/files` | Uploaded documents |
| Pages | `GET /courses/:id/pages` | Course content pages |

### Permissions Needed

Your API token inherits your student permissions:
- **As a student**: You can see published quizzes, your own submissions, course files, and module content
- **After submission**: Some professors allow viewing correct answers — this is when you can scrape answer keys
- **Limitation**: Unpublished content and other students' data are not accessible

### Quiz Scraping Approaches

#### Approach 1: API (Preferred)

```python
import requests

headers = {"Authorization": f"Bearer {token}"}
base = "https://your-school.instructure.com/api/v1"

# Get quizzes
quizzes = requests.get(f"{base}/courses/{course_id}/quizzes", headers=headers).json()

# Get questions for each quiz
for quiz in quizzes:
    questions = requests.get(
        f"{base}/courses/{course_id}/quizzes/{quiz['id']}/questions",
        headers=headers
    ).json()
```

#### Approach 2: Chrome DevTools Protocol (CDP)

For cases where the API doesn't expose answers (e.g., viewing quiz review pages):

1. Use Playwright or Puppeteer to navigate to the quiz review page
2. Extract HTML content containing questions and correct answers
3. Parse with BeautifulSoup

This approach is more fragile but can capture data the API doesn't expose.

### Rate Limits

Canvas API has rate limits:
- ~700 requests per 10 minutes per user
- The `X-Rate-Limit-Remaining` header tells you how many requests are left
- The ingestion scripts handle rate limiting automatically

---

## Learning Suite

Learning Suite is an LMS used at some universities. It does not have a public API, so integration requires browser-based scraping.

### Authentication Flow

1. Navigate to Learning Suite login page
2. Redirected to your school's SSO (CAS/SAML)
3. Enter credentials + handle MFA
4. Redirected back to Learning Suite with session cookie
5. Use session cookie for subsequent requests

### Scraping Approach

The ingestion script uses browser automation:

```bash
python tools/ingest_learning_suite.py \
  --course-url "https://learningsuite.example.edu/course/12345" \
  --username "your_username" \
  --output "packs/my-course/"
```

The script will:
1. Launch a browser (Playwright)
2. Navigate to SSO login
3. Wait for you to complete authentication (including MFA)
4. Scrape quiz/exam pages
5. Extract questions and answers
6. Generate `questions.json`

### What Can Be Scraped

| Content | Method | Reliability |
|---------|--------|-------------|
| Quiz questions | Page scraping | High |
| Correct answers | After submission | Medium (depends on professor settings) |
| Assignments | Page scraping | High |
| Grades | Grade page scraping | High |
| Course content | Page scraping | Medium |

### Authentication Tips

- The script opens a browser window — you may need to interact with MFA prompts
- Session cookies expire; re-authenticate if scraping fails
- Some features may require JavaScript rendering (use Playwright, not requests)

### Grade Fetching

Learning Suite grades can be fetched for progress tracking:

```python
# After authentication
grades = scrape_grades(session, course_url)
# Returns: {assignment_name: {score, max_score, weight, category}}
```

---

## Cengage / MindTap

### Current Status: Stub

Cengage/MindTap integration is planned but not yet fully implemented. The challenges:

### What's Needed

1. **Authentication**: Cengage uses institution-linked SSO
2. **Content Access**: MindTap content is heavily JavaScript-rendered
3. **Question Extraction**: Questions are delivered dynamically
4. **Answer Keys**: Often not accessible after submission

### Potential Approach

1. Use Playwright to authenticate and navigate MindTap
2. Intercept XHR/fetch requests to capture question data
3. Parse the JSON payloads for question content
4. Map to Cram-It question format

### Contributing

If you have experience with Cengage API or MindTap scraping, contributions are welcome. The key files:

- `engine/lms/cengage.py` — Main integration module
- `tools/ingest_cengage.py` — CLI ingestion tool

---

## General Data Flow

### From LMS to Pack

```
┌──────────────┐      ┌──────────────┐      ┌──────────────┐
│   Canvas /   │      │  tools/      │      │  packs/      │
│   Learning   │ ──── │  ingest_*.py │ ──── │  my-course/  │
│   Suite /    │      │              │      │              │
│   Cengage    │      │  Transforms: │      │  Output:     │
│              │      │  - Parse HTML│      │  questions.  │
│  Raw Data:   │      │  - Extract   │      │    json      │
│  - Quiz HTML │      │    Q/A pairs │      │  concept_    │
│  - API JSON  │      │  - Tag       │      │    map.json  │
│  - PDF files │      │    concepts  │      │  pack.yaml   │
└──────────────┘      │  - Validate  │      └──────────────┘
                      │    answers   │
                      │  - AI enrich │
                      └──────────────┘
```

### Data Transformation

The ingestion scripts perform these transformations:

1. **Extract**: Pull raw question data from the LMS
2. **Normalize**: Convert to Cram-It's JSON format
3. **Validate**: Verify answer keys are correct
4. **Enrich**: Use Claude to:
   - Tag questions with concepts
   - Determine frequency tier
   - Classify question type (conceptual/calculation/graph)
5. **Output**: Write to pack directory

### Keeping Packs Updated

When new quizzes are posted:

```bash
# Pull new quiz data and append to existing pack
python tools/ingest_canvas.py \
  --course-id 12345 \
  --output "packs/my-course/" \
  --append \
  --since "2024-01-15"  # Only new quizzes after this date
```

### Multi-Source Packs

A pack can combine data from multiple sources:

```bash
# Start with Canvas quizzes
python tools/ingest_canvas.py --output packs/my-course/

# Add PDF practice exams
python tools/ingest_pdf.py --input exam1.pdf --output packs/my-course/questions.json --append

# Add textbook for RAG
python tools/chunk_textbook.py --input textbook.pdf --pack my-course
```

The ingestion scripts use `--append` to add to existing `questions.json` without overwriting.
