"""Web3 and Crypto RSS feed parser for Web3/Blockchain and AI roles."""

from datetime import datetime, timezone
import html
import logging
import re
from typing import Any
import feedparser

from config import HTTP_TIMEOUT
from models import Job, canonical_url, job_id, parse_posted_at

LOGGER = logging.getLogger(__name__)

WEB3_RSS_FEEDS = (
    "https://cryptojobslist.com/rss",
    "https://web3.career/rss",
    "https://crypto.jobs/feed",
    "https://remoteok.com/remote-web3-jobs.rss",
)


def _clean_summary(raw_html: str) -> str:
    """Strip HTML markup from RSS feed summaries."""
    if not raw_html:
        return ""
    text = re.sub(r"<[^>]+>", " ", raw_html)
    return html.unescape(" ".join(text.split())).strip()


def parse_feed_entry(entry: Any, feed_url: str, *, now: datetime | None = None) -> dict[str, Any] | None:
    """Parse a single RSS feed entry into a normalized dictionary."""
    now = now or datetime.now(timezone.utc)
    raw_title = entry.get("title", "").strip()
    raw_link = entry.get("link", "").strip()

    if not raw_title or not raw_link:
        return None

    try:
        url = canonical_url(raw_link)
    except (ValueError, Exception):
        url = raw_link

    # Separate Company and Job Title from common RSS title formats:
    # "Company is hiring a Title", "Company: Title", "Title at Company", "Title - Company"
    company = entry.get("author") or ""
    title = raw_title

    if not company:
        if " is hiring a " in raw_title:
            parts = raw_title.split(" is hiring a ", 1)
            company, title = parts[0].strip(), parts[1].strip()
        elif " is hiring " in raw_title:
            parts = raw_title.split(" is hiring ", 1)
            company, title = parts[0].strip(), parts[1].strip()
        elif " at " in raw_title:
            parts = raw_title.rsplit(" at ", 1)
            title, company = parts[0].strip(), parts[1].strip()
        elif " - " in raw_title:
            parts = raw_title.split(" - ", 1)
            # Typically "Title - Company" or "Company - Title"
            title, company = parts[0].strip(), parts[1].strip()
        elif ":" in raw_title:
            parts = raw_title.split(":", 1)
            company, title = parts[0].strip(), parts[1].strip()

    if not company:
        company = "Web3 Project"

    # Extract location and workplace type
    summary = _clean_summary(entry.get("summary") or entry.get("description") or "")
    tags = [t.get("term", "") for t in entry.get("tags", []) if isinstance(t, dict)]
    tag_blob = " ".join(tags)

    location = entry.get("location") or ""
    blob = f"{raw_title} {summary} {tag_blob} {location}".lower()

    workplace_type = "unknown"
    if "remote" in blob or "anywhere" in blob or "worldwide" in blob:
        workplace_type = "remote"
        if not location:
            location = "Remote"
    elif "hybrid" in blob:
        workplace_type = "hybrid"
    elif "onsite" in blob or "on-site" in blob:
        workplace_type = "onsite"

    if not location:
        location = "Remote" if workplace_type == "remote" else "Global / India"

    # Extract stipend / compensation if present
    stipend = None
    stipend_match = re.search(r"(?:₹|\$|€|£|INR|USD)\s*[\d,kK\.]+(?:\s*(?:-|to)\s*(?:₹|\$|€|£|INR|USD)?\s*[\d,kK\.]+)?(?:\s*(?:per|/|a)\s*(?:month|mo|pm|year|yr|hr))?", blob, re.I)
    if stipend_match:
        stipend = stipend_match.group(0).strip()

    # Parse published date
    published = entry.get("published") or entry.get("updated") or now.isoformat()
    entry_id = entry.get("id") or entry.get("guid") or url

    return {
        "id": job_id("web3", url, entry_id),
        "title": title,
        "company": company,
        "location": location,
        "stipend": stipend,
        "url": url,
        "workplace_type": workplace_type,
        "posted_date": str(published),
        "description": summary,
    }


def dict_to_job(record: dict[str, Any], *, now: datetime | None = None) -> Job | None:
    """Convert normalized dictionary to models.Job instance."""
    now = now or datetime.now(timezone.utc)
    raw_title = record.get("title") or "Web3 Engineer"
    url = record.get("url")
    if not url or not url.startswith("http"):
        return None

    employment = "internship" if re.search(r"\bintern(?:ship)?\b", raw_title, re.I) else "fulltime"

    return Job(
        id=record.get("id") or job_id("web3", url),
        source="web3",
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


def fetch_web3_jobs(feed_urls: tuple[str, ...] = WEB3_RSS_FEEDS) -> list[dict[str, Any]]:
    """Fetch and parse all Web3 RSS feeds, returning normalized records."""
    results = []
    for feed_url in feed_urls:
        try:
            # feedparser supports direct URLs or string data
            feed = feedparser.parse(
                feed_url,
                request_headers={"User-Agent": "Mozilla/5.0 (PersonalJobWatcher/1.0; RSS reader)"},
            )
            for entry in feed.entries:
                record = parse_feed_entry(entry, feed_url)
                if record:
                    results.append(record)
        except Exception as exc:
            LOGGER.warning("Web3 RSS feed '%s' failed: %s: %s", feed_url, type(exc).__name__, exc)
    return results


def fetch_web3() -> list[Job]:
    """Scraper entrypoint returning a list of Job instances."""
    records = fetch_web3_jobs()
    jobs = []
    for rec in records:
        job = dict_to_job(rec)
        if job:
            jobs.append(job)
    return jobs
