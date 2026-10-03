"""Scraper for active Devfolio hackathons via public JSON API."""

from datetime import datetime, timezone
import logging
import re
from typing import Any
import requests

from config import HTTP_TIMEOUT

LOGGER = logging.getLogger(__name__)
DEVFOLIO_API_URL = "https://api.devfolio.co/api/hackathons?page=1&limit=30"


def parse_devfolio_item(item: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any] | None:
    """Normalize a Devfolio hackathon record."""
    now = now or datetime.now(timezone.utc)
    slug = str(item.get("slug") or "").strip()
    name = str(item.get("name") or "").strip()
    if not slug or not name:
        return None

    # Status check - skip unlisted or closed
    status = str(item.get("status") or "").lower()
    if status in {"draft", "completed"}:
        return None

    ends_at_str = item.get("ends_at")
    if ends_at_str:
        try:
            ends_at_dt = datetime.fromisoformat(str(ends_at_str).replace("Z", "+00:00"))
            if ends_at_dt < now:
                return None
        except (ValueError, TypeError):
            pass

    setting = item.get("hackathon_setting") or {}
    reg_ends_at = setting.get("reg_ends_at") if isinstance(setting, dict) else None
    if reg_ends_at:
        try:
            reg_dt = datetime.fromisoformat(str(reg_ends_at).replace("Z", "+00:00"))
            if reg_dt < now:
                return None
        except (ValueError, TypeError):
            pass

    tagline = str(item.get("tagline") or "").strip()
    desc = str(item.get("desc") or "").strip()
    full_text = f"{name} {tagline} {desc}".lower()

    # Team size parsing
    min_team = int(item.get("team_min") or 1)
    max_team = int(item.get("team_size") or 4)

    # Location & Online status
    is_online = bool(item.get("is_online"))
    location = str(item.get("location") or ("Online" if is_online else "In-person")).strip()

    # Themes and tags
    themes = item.get("themes") or []
    tags = [t.get("name") for t in themes if isinstance(t, dict) and t.get("name")]
    if not tags:
        for kw in ("AI", "Web3", "Blockchain", "FinTech", "HealthTech", "Cybersecurity", "Open Innovation"):
            if re.search(rf"\b{kw}\b", full_text, re.I):
                tags.append(kw)

    # Cash prize evaluation
    prizes = item.get("prizes") or []
    prize_pool = ""
    has_cash_prize = False

    # Check quadratic voting prize or prizes array or prize text
    qv_amount = setting.get("quadratic_voting_prize_pool_amount") if isinstance(setting, dict) else None
    if qv_amount:
        prize_pool = f"${qv_amount:,}"
        has_cash_prize = True
    elif prizes:
        has_cash_prize = True
        prize_pool = "Cash Prizes Available"
    else:
        # Search text for prize figures like ₹5,00,000 or $10,000
        cash_match = re.search(r"(?:₹|rs\.?|inr|\$)\s*([\d,]+(?:\.\d+)?)\s*(?:lakhs?|k)?", full_text, re.I)
        if cash_match:
            prize_pool = cash_match.group(0).strip()
            has_cash_prize = True
        elif "cash prize" in full_text or "prize pool" in full_text:
            prize_pool = "Prize Pool Announced"
            has_cash_prize = True

    # Career Incentives (PPO, PPI, Job Offer, Hiring track)
    career_incentives = bool(re.search(
        r"\b(?:ppo|ppi|job\s+offer|pre-?placement\s+interview|pre-?placement\s+offer|interview\s+fast-?track|hiring\s+partner|recruitment\s+track)\b",
        full_text,
        re.I
    ))

    url = f"https://{slug}.devfolio.co"

    brand = item.get("hackathon_brand")
    organization = brand.get("name") if isinstance(brand, dict) else name

    uuid = item.get("uuid") or slug

    return {
        "id": f"devfolio:{uuid}",
        "title": name,
        "organization": organization,
        "url": url,
        "tags": tags[:6],
        "deadline": reg_ends_at or ends_at_str,
        "prize_pool": prize_pool,
        "has_cash_prize": has_cash_prize,
        "career_incentives": career_incentives,
        "team_size": {"min_team": min_team, "max_team": max_team},
        "description": f"{tagline}. {desc}".strip(". "),
        "location": location,
        "is_remote": is_online,
        "source": "devfolio",
    }


def fetch_devfolio(api_url: str = DEVFOLIO_API_URL) -> list[dict[str, Any]]:
    """Fetch active hackathons from Devfolio."""
    try:
        response = requests.get(
            api_url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "application/json",
            },
            timeout=HTTP_TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()
    except Exception as exc:
        LOGGER.error("Failed to fetch Devfolio hackathons: %s", exc)
        return []

    items = data.get("result") or []
    results = []
    for raw in items:
        if isinstance(raw, dict):
            normalized = parse_devfolio_item(raw)
            if normalized:
                results.append(normalized)

    LOGGER.info("Fetched %d hackathons from Devfolio", len(results))
    return results
