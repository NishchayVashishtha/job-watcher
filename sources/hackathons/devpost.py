"""Parser for Devpost hackathons via RSS feed."""

from datetime import datetime, timezone
import hashlib
import html
import logging
import re
from typing import Any
import feedparser

LOGGER = logging.getLogger(__name__)

DEFAULT_DEVPOST_RSS_URL = "https://devpost.com/hackathons.rss"


def _clean_text(raw_html: str) -> str:
    if not raw_html:
        return ""
    text = re.sub(r"<[^>]+>", " ", raw_html)
    return html.unescape(" ".join(text.split())).strip()


def parse_devpost_entry(entry: Any, *, now: datetime | None = None) -> dict[str, Any] | None:
    """Normalize a Devpost RSS entry into standard hackathon format."""
    now = now or datetime.now(timezone.utc)
    title = str(getattr(entry, "title", "") or "").strip()
    link = str(getattr(entry, "link", "") or "").strip()
    if not title or not link:
        return None

    summary_raw = str(getattr(entry, "summary", "") or getattr(entry, "description", "") or "")
    clean_desc = _clean_text(summary_raw)
    full_text = f"{title} {clean_desc}".lower()

    # Cash prize extraction (e.g., "$50,000 in prizes", "$10,000 in cash")
    prize_pool = ""
    has_cash_prize = False
    cash_match = re.search(r"(\$[\d,]+(?:\.\d+)?)\s*(?:in\s+prizes|prize\s+pool|in\s+cash)?", clean_desc, re.I)
    if cash_match:
        prize_pool = cash_match.group(1).strip()
        has_cash_prize = True
    elif "cash" in full_text or "prize" in full_text:
        has_cash_prize = True
        prize_pool = "Prizes Available"

    # Location check: Online vs In-person
    is_online = ("online" in full_text) or ("virtual" in full_text) or ("global" in full_text)
    location = "Online" if is_online else "In-person"
    loc_match = re.search(r"\b(?:located in|location:|in)\s+([A-Za-z\s,]+)", clean_desc, re.I)
    if loc_match and not is_online:
        location = loc_match.group(1).strip()

    # Team size parsing
    min_team = 1
    max_team = 4
    team_match = re.search(r"teams?\s+of\s+(?:up\s+to\s+)?(\d+)(?:\s*(?:-|to)\s*(\d+))?", clean_desc, re.I)
    if team_match:
        if team_match.group(2):
            min_team = int(team_match.group(1))
            max_team = int(team_match.group(2))
        else:
            max_team = int(team_match.group(1))
    elif "solo" in full_text or "individuals" in full_text:
        min_team = 1

    # Career incentives
    career_incentives = bool(re.search(
        r"\b(?:ppo|ppi|job\s+offer|recruitment|interview\s+fast-?track|hiring|internship\s+opportunity)\b",
        full_text,
        re.I
    ))

    # Tags
    tags = []
    for kw in ("AI", "GenAI", "Web3", "Blockchain", "Machine Learning", "Backend", "Cloud", "Mobile", "Security"):
        if re.search(rf"\b{kw}\b", full_text, re.I):
            tags.append(kw)

    entry_id = getattr(entry, "id", None) or getattr(entry, "guid", None) or link
    safe_id = f"devpost:{hashlib.sha256(entry_id.encode()).hexdigest()[:16]}"

    # Deadline
    deadline = getattr(entry, "published", None)

    return {
        "id": safe_id,
        "title": title,
        "organization": "Devpost Organizer",
        "url": link,
        "tags": tags[:6],
        "deadline": deadline,
        "prize_pool": prize_pool,
        "has_cash_prize": has_cash_prize,
        "career_incentives": career_incentives,
        "team_size": {"min_team": min_team, "max_team": max_team},
        "description": clean_desc,
        "location": location,
        "is_remote": is_online,
        "source": "devpost",
    }


def fetch_devpost(feed_url: str = DEFAULT_DEVPOST_RSS_URL) -> list[dict[str, Any]]:
    """Parse hackathons from Devpost RSS feed."""
    try:
        feed = feedparser.parse(
            feed_url,
            request_headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        )
    except Exception as exc:
        LOGGER.error("Failed to parse Devpost RSS feed from %s: %s", feed_url, exc)
        return []

    if getattr(feed, "bozo", 0) and not feed.entries:
        LOGGER.warning("Devpost RSS returned bozo exception or empty entries: %s", getattr(feed, "bozo_exception", ""))
        return []

    results = []
    for entry in feed.entries:
        normalized = parse_devpost_entry(entry)
        if normalized:
            results.append(normalized)

    LOGGER.info("Fetched %d hackathons from Devpost RSS", len(results))
    return results
