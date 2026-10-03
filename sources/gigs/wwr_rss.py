"""Parser for We Work Remotely (WWR) contract and freelance RSS feeds."""

from datetime import datetime, timezone
import hashlib
import html
import logging
import re
from typing import Any
import feedparser

LOGGER = logging.getLogger(__name__)

WWR_RSS_URLS = (
    "https://weworkremotely.com/categories/remote-back-end-programming-jobs.rss",
    "https://weworkremotely.com/categories/remote-full-stack-programming-jobs.rss",
    "https://weworkremotely.com/categories/remote-devops-sysadmin-jobs.rss",
)


def _clean_text(raw_html: str) -> str:
    if not raw_html:
        return ""
    text = re.sub(r"<[^>]+>", " ", raw_html)
    return html.unescape(" ".join(text.split())).strip()


def parse_wwr_entry(entry: Any, *, now: datetime | None = None) -> dict[str, Any] | None:
    """Normalize a single WWR entry. Keeps contract, freelance, and part-time roles."""
    now = now or datetime.now(timezone.utc)
    raw_title = str(getattr(entry, "title", "") or "").strip()
    link = str(getattr(entry, "link", "") or "").strip()
    if not raw_title or not link:
        return None

    # WWR format is often: "Company Name: Job Title"
    company = "WeWorkRemotely Client"
    title = raw_title
    if ":" in raw_title:
        parts = raw_title.split(":", 1)
        company = parts[0].strip()
        title = parts[1].strip()

    job_type = str(getattr(entry, "type", "") or "").strip().lower()
    summary_raw = str(getattr(entry, "summary", "") or "")
    clean_desc = _clean_text(summary_raw)
    full_text = f"{raw_title} {job_type} {clean_desc}".lower()

    # Filter for Contract, Freelance, Part-time, Bounty, or Hourly roles
    is_gig = (
        "contract" in job_type
        or "freelance" in job_type
        or "part-time" in job_type
        or bool(re.search(r"\b(?:contract|freelance|part-?time|bounty|hourly|contractor)\b", full_text))
    )
    if not is_gig:
        return None

    # Check for geographic restriction (e.g. US Only)
    region = str(getattr(entry, "region", "") or "").strip()
    is_us_only = bool(re.search(r"\b(?:usa?|united\s+states|north\s+america)\s+only\b", f"{region} {clean_desc}", re.I))

    # Compensation parsing
    rate_match = re.search(r"\$([\d,]+(?:\.\d+)?)\s*(?:-|to)?\s*(?:\$([\d,]+(?:\.\d+)?))?\s*(?:/(?:hr|hour|mo|yr|year)|per\s+(?:hour|month|year))", clean_desc, re.I)
    if rate_match:
        prize_pool = rate_match.group(0).strip()
    else:
        prize_pool = "Contract"

    # Extract tags
    tags = [t.get("term", "") for t in getattr(entry, "tags", []) if isinstance(t, dict)]
    if not tags:
        for tag in getattr(entry, "tags", []):
            if hasattr(tag, "term"):
                tags.append(str(tag.term))
    tags = [t.strip() for t in tags if t.strip()]

    entry_id = getattr(entry, "id", None) or getattr(entry, "guid", None) or link
    safe_id = f"wwr:{hashlib.sha256(entry_id.encode()).hexdigest()[:16]}"

    career_incentives = bool(re.search(r"\b(?:contract[- ]to[- ]hire|full[- ]time\s+potential|permanent)\b", clean_desc, re.I))

    return {
        "id": safe_id,
        "title": title,
        "organization": company,
        "url": link,
        "tags": tags[:6],
        "deadline": getattr(entry, "published", None),
        "prize_pool": prize_pool,
        "has_cash_prize": True,
        "career_incentives": career_incentives,
        "team_size": {"min_team": 1, "max_team": 1},
        "description": clean_desc,
        "location": "Remote",
        "is_remote": not is_us_only,
        "source": "wwr",
    }


def fetch_wwr_rss(urls: tuple[str, ...] = WWR_RSS_URLS) -> list[dict[str, Any]]:
    """Parse contract and freelance gigs from We Work Remotely RSS feeds."""
    results = []
    seen_ids = set()

    for url in urls:
        try:
            feed = feedparser.parse(
                url,
                request_headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
            )
            for entry in feed.entries:
                normalized = parse_wwr_entry(entry)
                if normalized and normalized["id"] not in seen_ids:
                    seen_ids.add(normalized["id"])
                    results.append(normalized)
        except Exception as exc:
            LOGGER.error("Failed to parse WWR feed %s: %s", url, exc)

    LOGGER.info("Fetched %d contract/freelance opportunities from WWR", len(results))
    return results
