"""
BYU Learning Suite Scraper for Cram-It

Learning Suite (learningsuite.byu.edu) does not provide a public API,
so this module uses session-based web scraping to extract course data.

Authentication Flow:
  1. POST to BYU's CAS (Central Authentication Service) login endpoint
     with username (Net ID) and password.
  2. CAS returns a ticket and redirects back to Learning Suite.
  3. The session cookie is then used for all subsequent requests.
  4. Sessions expire after ~30 minutes of inactivity.

URL Patterns:
  Course page: https://learningsuite.byu.edu/.XXXX/cid-XXXXX/student/
  Assignments: https://learningsuite.byu.edu/.XXXX/cid-XXXXX/student/assignments
  Grades:      https://learningsuite.byu.edu/.XXXX/cid-XXXXX/student/grades

Usage:
  from engine.lms.learning_suite import LearningSuiteClient
  client = LearningSuiteClient()
  client.login("netid", "password")
  courses = client.get_courses()

NOTE: This scraper is fragile by nature. BYU may change their HTML
      structure at any time. Always check for None returns and handle
      gracefully. Web scraping may also be subject to BYU's terms of use.
"""

import os
import re
from typing import Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup


# BYU CAS and Learning Suite endpoints
CAS_LOGIN_URL = "https://cas.byu.edu/cas/login"
LS_BASE_URL = "https://learningsuite.byu.edu"


class LearningSuiteClient:
    """Session-based scraper for BYU Learning Suite.

    Authenticates through BYU's CAS system and scrapes course content.
    Since Learning Suite has no public API, all data extraction is done
    by parsing HTML pages.
    """

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        })
        self.authenticated = False

    def login(self, username: Optional[str] = None, password: Optional[str] = None) -> bool:
        """Authenticate with BYU CAS and establish a Learning Suite session.

        The CAS login flow:
          1. GET the CAS login page to obtain the hidden 'lt' (login ticket)
             and 'execution' tokens from the form.
          2. POST credentials + tokens to CAS.
          3. CAS redirects to Learning Suite with a service ticket.
          4. Learning Suite sets session cookies.

        Args:
            username: BYU Net ID. Falls back to LS_USERNAME env var.
            password: BYU password. Falls back to LS_PASSWORD env var.

        Returns:
            True if login succeeded, False otherwise.

        Raises:
            ValueError: If username or password is not provided.
        """
        username = username or os.environ.get("LS_USERNAME", "")
        password = password or os.environ.get("LS_PASSWORD", "")

        if not username or not password:
            raise ValueError(
                "BYU credentials required. Pass username/password or set "
                "LS_USERNAME and LS_PASSWORD env vars."
            )

        # Step 1: Get the CAS login page to extract form tokens
        service_url = f"{LS_BASE_URL}/auth/cas"
        login_page = self.session.get(
            CAS_LOGIN_URL,
            params={"service": service_url},
            timeout=15,
        )

        if login_page.status_code != 200:
            print(f"Failed to load CAS login page: {login_page.status_code}")
            return False

        # Parse hidden form fields (lt, execution, _eventId)
        soup = BeautifulSoup(login_page.text, "html.parser")
        form = soup.find("form", {"id": "fm1"}) or soup.find("form")

        if not form:
            print("Could not find CAS login form")
            return False

        hidden_fields = {}
        for inp in form.find_all("input", {"type": "hidden"}):
            name = inp.get("name")
            value = inp.get("value", "")
            if name:
                hidden_fields[name] = value

        # Step 2: POST credentials
        payload = {
            **hidden_fields,
            "username": username,
            "password": password,
            "_eventId": "submit",
        }

        login_resp = self.session.post(
            CAS_LOGIN_URL,
            params={"service": service_url},
            data=payload,
            timeout=15,
            allow_redirects=True,
        )

        # Step 3: Check if we landed on Learning Suite (not back at CAS)
        if "learningsuite.byu.edu" in login_resp.url and "cas.byu.edu" not in login_resp.url:
            self.authenticated = True
            print("Successfully authenticated with Learning Suite")
            return True
        else:
            print("CAS login failed. Check credentials.")
            self.authenticated = False
            return False

    def _require_auth(self):
        """Raise if not authenticated."""
        if not self.authenticated:
            raise RuntimeError(
                "Not authenticated. Call login() first."
            )

    def get_courses(self) -> list[dict]:
        """Scrape the list of courses from the Learning Suite dashboard.

        Returns a list of dicts with keys:
          - name: Course display name (e.g. "ECON 110 - Principles of Economics")
          - url: Full URL to the course student page
          - course_id: Extracted course ID from the URL (cid-XXXXX)
          - term_code: Term code from URL (.XXXX)

        Returns:
            List of course dicts, or empty list on failure.
        """
        self._require_auth()

        resp = self.session.get(f"{LS_BASE_URL}/", timeout=15)
        if resp.status_code != 200:
            print(f"Failed to load dashboard: {resp.status_code}")
            return []

        soup = BeautifulSoup(resp.text, "html.parser")
        courses = []

        # Learning Suite typically lists courses as links matching the URL pattern
        # Pattern: /.XXXX/cid-XXXXX/student/
        course_pattern = re.compile(r"/\.(\w+)/cid-(\w+)/student/?")

        for link in soup.find_all("a", href=course_pattern):
            href = link.get("href", "")
            match = course_pattern.search(href)
            if match:
                term_code = match.group(1)
                course_id = match.group(2)
                name = link.get_text(strip=True) or f"Course {course_id}"

                courses.append({
                    "name": name,
                    "url": urljoin(LS_BASE_URL, href),
                    "course_id": course_id,
                    "term_code": term_code,
                })

        return courses

    def get_assignments(self, course_url: str) -> list[dict]:
        """Scrape assignments for a specific course.

        Navigates to the course's assignments page and extracts
        assignment names, due dates, and scores.

        Args:
            course_url: Full URL to the course student page, e.g.
                "https://learningsuite.byu.edu/.XXXX/cid-XXXXX/student/"

        Returns:
            List of assignment dicts with keys:
              - name: Assignment title
              - due_date: Due date string (as displayed)
              - score: Score string (e.g. "85/100") or None
              - url: Link to assignment details, if available
        """
        self._require_auth()

        assignments_url = course_url.rstrip("/") + "/assignments"
        resp = self.session.get(assignments_url, timeout=15)

        if resp.status_code != 200:
            print(f"Failed to load assignments: {resp.status_code}")
            return []

        soup = BeautifulSoup(resp.text, "html.parser")
        assignments = []

        # Look for assignment rows — LS typically uses table or list structure
        # The exact selectors may change if BYU updates the page layout
        for row in soup.select("tr.assignment-row, .assignment-item, [data-assignment-id]"):
            name_el = row.select_one(".assignment-name, .title, td:first-child")
            date_el = row.select_one(".due-date, .date, td:nth-child(2)")
            score_el = row.select_one(".score, .grade, td:nth-child(3)")
            link_el = row.select_one("a[href]")

            assignments.append({
                "name": name_el.get_text(strip=True) if name_el else "Unknown",
                "due_date": date_el.get_text(strip=True) if date_el else None,
                "score": score_el.get_text(strip=True) if score_el else None,
                "url": urljoin(LS_BASE_URL, link_el["href"]) if link_el else None,
            })

        return assignments

    def get_grades(self, course_url: str) -> list[dict]:
        """Scrape the grades page for a specific course.

        Navigates to the course's grades page and extracts category
        names, individual grades, and summary statistics.

        Args:
            course_url: Full URL to the course student page, e.g.
                "https://learningsuite.byu.edu/.XXXX/cid-XXXXX/student/"

        Returns:
            List of grade entry dicts with keys:
              - category: Grade category (e.g. "Exams", "Homework")
              - item_name: Individual grade item name
              - score: Numeric or string score
              - possible: Total possible points
              - percentage: Percentage score, if calculable
        """
        self._require_auth()

        grades_url = course_url.rstrip("/") + "/grades"
        resp = self.session.get(grades_url, timeout=15)

        if resp.status_code != 200:
            print(f"Failed to load grades: {resp.status_code}")
            return []

        soup = BeautifulSoup(resp.text, "html.parser")
        grades = []
        current_category = "Uncategorized"

        # LS grades page typically has categories as headers and items as rows
        for row in soup.select("tr, .grade-row, .grade-item"):
            # Check if this is a category header
            header = row.select_one(".category-header, th, .category-name")
            if header and header.get_text(strip=True):
                current_category = header.get_text(strip=True)
                continue

            name_el = row.select_one(".item-name, .assignment-name, td:first-child")
            score_el = row.select_one(".score, td:nth-child(2)")
            possible_el = row.select_one(".possible, td:nth-child(3)")

            if name_el:
                item_name = name_el.get_text(strip=True)
                score_text = score_el.get_text(strip=True) if score_el else "—"
                possible_text = possible_el.get_text(strip=True) if possible_el else "—"

                # Try to compute percentage
                percentage = None
                try:
                    score_num = float(score_text)
                    possible_num = float(possible_text)
                    if possible_num > 0:
                        percentage = round((score_num / possible_num) * 100, 1)
                except (ValueError, ZeroDivisionError):
                    pass

                grades.append({
                    "category": current_category,
                    "item_name": item_name,
                    "score": score_text,
                    "possible": possible_text,
                    "percentage": percentage,
                })

        return grades


# ------------------------------------------------------------------
# Convenience functions (module-level)
# ------------------------------------------------------------------


def login(username: str, password: str) -> LearningSuiteClient:
    """Create and authenticate a Learning Suite client.

    Args:
        username: BYU Net ID.
        password: BYU password.

    Returns:
        Authenticated LearningSuiteClient instance.
    """
    client = LearningSuiteClient()
    client.login(username, password)
    return client


def get_courses(username: str, password: str) -> list[dict]:
    """Quick helper: login and return course list."""
    client = login(username, password)
    return client.get_courses()


def get_assignments(username: str, password: str, course_url: str) -> list[dict]:
    """Quick helper: login and return assignments for a course."""
    client = login(username, password)
    return client.get_assignments(course_url)


def get_grades(username: str, password: str, course_url: str) -> list[dict]:
    """Quick helper: login and return grades for a course."""
    client = login(username, password)
    return client.get_grades(course_url)
