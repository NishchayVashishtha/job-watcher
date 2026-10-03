"""Hacker News Algolia API source for 'Who is Hiring?' threads."""

from datetime import datetime, timezone
import html
import logging
import re
from typing import Any
import requests

from config import HTTP_TIMEOUT
from models import Job, canonical_url, job_id, parse_posted_at

LOGGER = logging.getLogger(__name__)

HN_ALGOLIA_URL = "https://hn.algolia.com/api/v1/search_by_date"
DEFAULT_KEYWORDS = ("intern", "remote", "backend", "ai", "genai", "rag", "software", "developer", "engineer", "web3", "blockchain")


def _clean_html(raw_html: str) -> str:
    """Convert HTML tags from HN comments into clean plain text."""
    if not raw_html:
        return ""
    text = re.sub(r"<p\s*/?>", "\n", raw_html, flags=re.IGNORECASE)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<a\s+(?:[^>]*?\s+)?href=([\"'])(.*?)\1[^>]*>(.*?)</a>", r"\3 (\2)", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    return html.unescape(text).strip()


def parse_hn_comment(hit: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any] | None:
    """Parse a single HN comment hit into a normalized dictionary."""
    now = now or datetime.now(timezone.utc)
    raw_text = hit.get("comment_text") or ""
    text = _clean_html(raw_text)
    if not text:
        return None

    object_id = str(hit.get("objectID") or "")
    if not object_id:
        return None

    comment_url = f"https://news.ycombinator.com/item?id={object_id}"
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return None

    header = lines[0]
    
    # Check if comment mentions relevant keywords
    searchable = (header + "\n" + text).lower()
    if not any(kw in searchable for kw in DEFAULT_KEYWORDS):
        return None

    # Parse header: typically 'Company | Title/Role | Location | Remote/Onsite | Compensation'
    parts = [p.strip() for p in header.split("|")]
    
    company = "Unknown"
    title = "Software Engineer"
    location = "Remote"
    workplace_type = "unknown"
    stipend = None

    if len(parts) >= 2:
        company = parts[0]
        title = parts[1]
        if len(parts) >= 3:
            location = parts[2]
    else:
        # Fallback if no pipe separator
        first_line = lines[0]
        dash_parts = [p.strip() for p in first_line.split(" - ")]
        if len(dash_parts) >= 2:
            company = dash_parts[0]
            title = dash_parts[1]
        else:
            company = hit.get("author") or "Hacker News Hiring"
            title = lines[0][:80]

    # Detect workplace type
    full_blob = (header + " " + location).lower()
    if "remote" in full_blob:
        workplace_type = "remote"
    elif "hybrid" in full_blob:
        workplace_type = "hybrid"
    elif "onsite" in full_blob or "on-site" in full_blob:
        workplace_type = "onsite"

    # Extract primary apply URL from body if available
    url_match = re.search(r"https?://[^\s<>\"')]+", text)
    primary_url = url_match.group(0) if url_match else comment_url

    # Check for compensation/stipend in header or text
    stipend_match = re.search(r"(?:₹|\$|INR|USD|EUR|£)?\s*\d[\d,kK\.\s]*(?:(?:per|/|-|to|\+)\s*(?:month|mo|pm|hr|hour|year|yr|annum|lpa|k))?", text, re.I)
    if stipend_match:
        stipend = stipend_match.group(0).strip()

    posted_date = hit.get("created_at") or datetime.fromtimestamp(hit.get("created_at_i", 0), tz=timezone.utc).isoformat() if hit.get("created_at_i") else now.isoformat()

    return {
        "id": f"hackernews:{object_id}",
        "title": title,
        "company": company,
        "location": location,
        "stipend": stipend,
        "url": primary_url,
        "workplace_type": workplace_type,
        "posted_date": posted_date,
        "description": text,
    }


def dict_to_job(record: dict[str, Any], *, now: datetime | None = None) -> Job | None:
    """Convert normalized dictionary to models.Job instance."""
    now = now or datetime.now(timezone.utc)
    try:
        url = canonical_url(record["url"])
    except (ValueError, KeyError):
        url = record.get("url") or ""
        if not url.startswith("http"):
            return None

    raw_title = record.get("title") or "Software Engineer"
    employment = "internship" if re.search(r"\bintern(?:ship)?\b", raw_title, re.I) else "fulltime"

    return Job(
        id=record.get("id") or job_id("hackernews", url),
        source="hackernews",
        title=raw_title,
        url=url,
        company=record.get("company"),
        location=record.get("location"),
        compensation=record.get("stipend"),
        description=record.get("description"),
        posted_at=parse_posted_at(record.get("posted_date"), now),
        employment_type=employment,
        workplace_type=record.get("workplace_type") or "unknown",
    )


def fetch_hn_jobs() -> list[dict[str, Any]]:
    """Fetch and return raw normalized dictionaries from Algolia HN API."""
    params = {
        "tags": "comment,author_whoishiring",
        "hitsPerPage": 100,
    }
    try:
        response = requests.get(HN_ALGOLIA_URL, params=params, timeout=HTTP_TIMEOUT)
        response.raise_for_status()
        data = response.json()
        hits = data.get("hits", [])
        results = []
        for hit in hits:
            record = parse_hn_comment(hit)
            if record:
                results.append(record)
        return results
    except Exception as exc:
        LOGGER.warning("HN Algolia search failed: %s: %s", type(exc).__name__, exc)
        return []


def fetch_hackernews() -> list[Job]:
    """Scraper entrypoint returning a list of Job instances."""
    records = fetch_hn_jobs()
    jobs = []
    for rec in records:
        job = dict_to_job(rec)
        if job:
            jobs.append(job)
    return jobs
