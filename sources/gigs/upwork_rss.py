"""Parser for custom Upwork RSS feeds."""

from datetime import datetime, timezone
import hashlib
import html
import logging
import re
from typing import Any
import feedparser

LOGGER = logging.getLogger(__name__)

# Default query: remote Python, AI, Web3, Backend freelance contracts
DEFAULT_UPWORK_RSS_URL = (
    "https://www.upwork.com/ab/feed/jobs/rss?q=python+OR+fastapi+OR+ai+OR+web3&sort=recency"
)


def _clean_text(raw_html: str) -> str:
    if not raw_html:
        return ""
    text = re.sub(r"<[^>]+>", " ", raw_html)
    return html.unescape(" ".join(text.split())).strip()


def parse_upwork_budget(text: str) -> tuple[str, bool, float | None]:
    """Extract budget / hourly rate from Upwork job text. Returns (prize_pool_str, has_cash_prize, numeric_val)."""
    # Hourly Range: $25.00 - $50.00 / hr
    hourly_match = re.search(r"Hourly\s+Range:\s*\$([\d\.]+)(?:\s*-\s*\$([\d\.]+))?", text, re.I)
    if hourly_match:
        low = float(hourly_match.group(1))
        high = float(hourly_match.group(2)) if hourly_match.group(2) else low
        return f"${low:g} - ${high:g}/hr", True, high

    # Budget: $500
    budget_match = re.search(r"Budget:\s*\$([\d,]+(?:\.\d+)?)", text, re.I)
    if budget_match:
        val = float(budget_match.group(1).replace(",", ""))
        return f"${val:g}", True, val

    # Hourly: $30
    single_hourly = re.search(r"\$([\d\.]+)\s*(?:/hr|per\s+hour)", text, re.I)
    if single_hourly:
        val = float(single_hourly.group(1))
        return f"${val:g}/hr", True, val

    return "Fixed/Negotiable", True, None


def parse_upwork_entry(entry: Any, *, now: datetime | None = None) -> dict[str, Any] | None:
    """Normalize a single Upwork RSS entry."""
    now = now or datetime.now(timezone.utc)
    raw_title = str(getattr(entry, "title", "") or "").strip()
    if not raw_title:
        return None

    # Clean Upwork suffix
    title = re.sub(r"\s*-\s*Upwork$", "", raw_title, flags=re.I).strip()
    link = str(getattr(entry, "link", "") or "").strip()
    if not link:
        return None

    summary_raw = str(getattr(entry, "summary", "") or getattr(entry, "description", "") or "")
    clean_desc = _clean_text(summary_raw)

    entry_id = getattr(entry, "id", None) or getattr(entry, "guid", None) or link
    safe_id = f"upwork:{hashlib.sha256(entry_id.encode()).hexdigest()[:16]}"

    prize_pool, has_cash_prize, num_val = parse_upwork_budget(clean_desc)

    # Check for US-only / specific region restrictions in description
    is_us_only = bool(re.search(
        r"\b(?:us\s+only|usa\s+only|united\s+states\s+only|us\s+citizens?\s+only|only\s+freelancers\s+located\s+in\s+the\s+u\.?s\.?)\b",
        clean_desc,
        re.I
    ))

    # Career incentives
    career_incentives = bool(re.search(
        r"\b(?:contract[- ]to[- ]hire|full[- ]time\s+potential|ongoing\s+project|long[- ]term\s+role|hire\s+permanently)\b",
        clean_desc,
        re.I
    ))

    # Extract skills / tags
    tags = []
    skills_match = re.search(r"Skills:\s*([^<]+)", summary_raw, re.I)
    if skills_match:
        tags = [s.strip() for s in skills_match.group(1).split(",") if s.strip()]
    if not tags:
        for kw in ("Python", "FastAPI", "AI", "GenAI", "LangChain", "RAG", "Web3", "Docker", "PostgreSQL"):
            if re.search(rf"\b{kw}\b", f"{title} {clean_desc}", re.I):
                tags.append(kw)

    deadline = None
    if hasattr(entry, "published"):
        deadline = entry.published

    return {
        "id": safe_id,
        "title": title,
        "organization": "Upwork Client",
        "url": link,
        "tags": tags[:6],
        "deadline": deadline,
        "prize_pool": prize_pool,
        "has_cash_prize": has_cash_prize,
        "career_incentives": career_incentives,
        "team_size": {"min_team": 1, "max_team": 1},
        "description": clean_desc,
        "location": "Remote",
        "is_remote": not is_us_only,  # if US only, not globally remote
        "source": "upwork",
        "hourly_rate": num_val if "/hr" in prize_pool else None,
        "fixed_budget": num_val if "/hr" not in prize_pool else None,
    }


def fetch_upwork_rss(feed_url: str | None = None) -> list[dict[str, Any]]:
    """Parse opportunities from a custom Upwork RSS feed URL."""
    url = feed_url or DEFAULT_UPWORK_RSS_URL
    try:
        feed = feedparser.parse(
            url,
            request_headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        )
    except Exception as exc:
        LOGGER.error("Failed to parse Upwork RSS from %s: %s", url, exc)
        return []

    if getattr(feed, "bozo", 0) and not feed.entries:
        LOGGER.warning("Upwork RSS feed returned bozo exception or empty entries: %s", getattr(feed, "bozo_exception", ""))
        return []

    results = []
    for entry in feed.entries:
        normalized = parse_upwork_entry(entry)
        if normalized:
            results.append(normalized)

    LOGGER.info("Fetched %d opportunities from Upwork RSS", len(results))
    return results
