"""GitHub Tech Internships Markdown parser (SimplifyJobs / PittCSC style repositories)."""

from datetime import datetime, timezone
import logging
import re
from typing import Any
import requests

from config import HTTP_TIMEOUT
from models import Job, canonical_url, job_id, parse_posted_at

LOGGER = logging.getLogger(__name__)

GITHUB_INTERNSHIP_MD_URLS = (
    "https://raw.githubusercontent.com/SimplifyJobs/Summer2025-Internships/dev/README.md",
    "https://raw.githubusercontent.com/SimplifyJobs/Summer2026-Internships/dev/README.md",
    "https://raw.githubusercontent.com/SimplifyJobs/Off-Season-Internships/dev/README.md",
    "https://raw.githubusercontent.com/SimplifyJobs/New-Grad-Positions/dev/README.md",
)


def _extract_link_and_text(cell: str) -> tuple[str, str]:
    """Extract plain text and the first URL from markdown cell (handling [text](url) and <a href='...'>)."""
    cell = cell.strip()
    url = ""
    # Check for Markdown link [text](url)
    md_match = re.search(r"\[([^\]]+)\]\((https?://[^\)]+)\)", cell)
    if md_match:
        text = md_match.group(1).strip()
        url = md_match.group(2).strip()
        # Clean extra markdown like **bold**
        text = re.sub(r"[*_~`]", "", text).strip()
        return text, url

    # Check for HTML link <a href="...">text</a>
    html_match = re.search(r'<a\s+(?:[^>]*?\s+)?href=["\'](https?://[^"\']+)["\'][^>]*>(.*?)</a>', cell, re.I)
    if html_match:
        url = html_match.group(1).strip()
        text = re.sub(r"<[^>]+>", "", html_match.group(2)).strip()
        text = re.sub(r"[*_~`]", "", text).strip()
        return text, url

    # Plain text / clean markdown formatting
    cleaned = re.sub(r"[*_~`]", "", cell).strip()
    return cleaned, ""


def parse_markdown_table(md_content: str, source_url: str = "", *, now: datetime | None = None) -> list[dict[str, Any]]:
    """Parse markdown table rows from GitHub internship tracking READMEs."""
    now = now or datetime.now(timezone.utc)
    results = []
    lines = md_content.splitlines()

    headers = []
    company_idx = 0
    role_idx = 1
    loc_idx = 2
    link_idx = 3
    date_idx = 4

    in_table = False

    for line in lines:
        stripped = line.strip()
        if not stripped.startswith("|") or not stripped.endswith("|"):
            in_table = False
            continue

        cols = [c.strip() for c in stripped.strip("|").split("|")]
        if not cols or len(cols) < 3:
            continue

        # Check if line is header
        lower_cols = [c.lower() for c in cols]
        if any("company" in c for c in lower_cols) and any("role" in c or "position" in c or "title" in c for c in lower_cols):
            headers = lower_cols
            in_table = True
            for i, h in enumerate(headers):
                if "company" in h:
                    company_idx = i
                elif "role" in h or "position" in h or "title" in h:
                    role_idx = i
                elif "location" in h:
                    loc_idx = i
                elif "link" in h or "application" in h or "apply" in h:
                    link_idx = i
                elif "date" in h or "age" in h or "posted" in h:
                    date_idx = i
            continue

        # Skip divider row |---|---|
        if any(re.match(r"^:?-+:?$", c) for c in cols):
            continue

        if not in_table and len(cols) < 3:
            continue

        # Extract cells safely
        raw_company = cols[company_idx] if company_idx < len(cols) else ""
        raw_role = cols[role_idx] if role_idx < len(cols) else ""
        raw_loc = cols[loc_idx] if loc_idx < len(cols) else ""
        raw_link = cols[link_idx] if link_idx < len(cols) else ""
        raw_date = cols[date_idx] if date_idx < len(cols) else ""

        company_name, comp_link = _extract_link_and_text(raw_company)
        role_title, _ = _extract_link_and_text(raw_role)
        location, _ = _extract_link_and_text(raw_loc)
        _, apply_url = _extract_link_and_text(raw_link)
        date_posted_str, _ = _extract_link_and_text(raw_date)

        # Fallback for apply URL: sometimes it is in the role column or company column
        if not apply_url:
            _, role_url = _extract_link_and_text(raw_role)
            apply_url = role_url or comp_link

        if not apply_url or not role_title or not company_name:
            continue

        try:
            url = canonical_url(apply_url)
        except (ValueError, Exception):
            url = apply_url

        # Check workplace type
        workplace_type = "unknown"
        loc_lower = (location + " " + role_title).lower()
        if "remote" in loc_lower or "anywhere" in loc_lower:
            workplace_type = "remote"
        elif "hybrid" in loc_lower:
            workplace_type = "hybrid"
        elif "onsite" in loc_lower or "on-site" in loc_lower or ("india" in loc_lower or "usa" in loc_lower or "ca" in loc_lower):
            workplace_type = "onsite"

        # Check for stipend in text if any
        stipend = None
        stipend_match = re.search(r"(?:₹|\$|INR|USD)\s*[\d,kK\.]+(?:\s*(?:/|per)\s*(?:mo|month|hr|year))?", stripped, re.I)
        if stipend_match:
            stipend = stipend_match.group(0).strip()

        job_record = {
            "id": job_id("github_internships", url),
            "title": role_title,
            "company": company_name,
            "location": location or "Not Specified",
            "stipend": stipend,
            "url": url,
            "workplace_type": workplace_type,
            "posted_date": date_posted_str or now.strftime("%b %d"),
            "description": f"{role_title} at {company_name} ({location})",
        }
        results.append(job_record)

    return results


def dict_to_job(record: dict[str, Any], *, now: datetime | None = None) -> Job | None:
    """Convert normalized dictionary to models.Job instance."""
    now = now or datetime.now(timezone.utc)
    raw_title = record.get("title") or "Intern"
    url = record.get("url")
    if not url or not url.startswith("http"):
        return None

    return Job(
        id=record.get("id") or job_id("github_internships", url),
        source="github_internships",
        title=raw_title,
        url=url,
        company=record.get("company"),
        location=record.get("location"),
        compensation=record.get("stipend"),
        description=record.get("description"),
        posted_at=parse_posted_at(record.get("posted_date"), now),
        employment_type="internship",
        workplace_type=record.get("workplace_type") or "unknown",
    )


def fetch_github_internships_data(urls: tuple[str, ...] = GITHUB_INTERNSHIP_MD_URLS) -> list[dict[str, Any]]:
    """Fetch raw markdown from GitHub internship repos and parse records."""
    records = []
    for url in urls:
        try:
            resp = requests.get(url, headers={"User-Agent": "PersonalJobWatcher/1.0"}, timeout=HTTP_TIMEOUT)
            if resp.status_code == 200:
                parsed = parse_markdown_table(resp.text, url)
                records.extend(parsed)
            else:
                LOGGER.warning("GitHub MD URL returned status %d: %s", resp.status_code, url)
        except Exception as exc:
            LOGGER.warning("Failed fetching GitHub internship repo '%s': %s: %s", url, type(exc).__name__, exc)
    return records


def fetch_github_internships() -> list[Job]:
    """Scraper entrypoint returning a list of Job instances."""
    records = fetch_github_internships_data()
    jobs = []
    for rec in records:
        job = dict_to_job(rec)
        if job:
            jobs.append(job)
    return jobs
