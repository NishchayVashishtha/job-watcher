"""Scraper for Superteam Earn bounties and freelance projects via public JSON API."""

from datetime import datetime, timezone
import logging
import re
from typing import Any
import requests

from config import HTTP_TIMEOUT

LOGGER = logging.getLogger(__name__)
SUPERTEAM_API_URL = "https://earn.superteam.fun/api/listings/"


def parse_superteam_item(item: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any] | None:
    """Normalize a single listing from Superteam Earn into standard opportunity format."""
    now = now or datetime.now(timezone.utc)
    item_id = str(item.get("id") or "").strip()
    title = str(item.get("title") or "").strip()
    slug = str(item.get("slug") or "").strip()
    item_type = str(item.get("type") or "bounty").strip().lower()

    if not item_id or not title:
        return None

    # Check if winners already announced or closed
    if item.get("isWinnersAnnounced") is True:
        return None

    deadline_str = item.get("deadline")
    if deadline_str:
        try:
            deadline_dt = datetime.fromisoformat(str(deadline_str).replace("Z", "+00:00"))
            if deadline_dt < now:
                return None
        except (ValueError, TypeError):
            pass

    sponsor = item.get("sponsor") or {}
    organization = sponsor.get("name") if isinstance(sponsor, dict) else "Superteam"

    # URL construction
    if slug:
        url = f"https://earn.superteam.fun/listings/{item_type}/{slug}"
    else:
        url = f"https://earn.superteam.fun/listings/{item_id}"

    reward_amt = item.get("rewardAmount") or 0
    token = str(item.get("token") or "USDC").strip()
    prize_pool = f"${reward_amt:,} {token}" if reward_amt else ""
    has_cash_prize = reward_amt > 0

    # Career incentives (PPO / Job / Hiring track)
    full_text = f"{title} {slug} {item.get('compensationType', '')}".lower()
    career_incentives = bool(re.search(r"\b(?:hire|hiring|full-?time|part-?time|intern|grant|contract-to-hire)\b", full_text))

    tags = ["Web3", "Solana", token]
    if item_type:
        tags.append(item_type.capitalize())

    return {
        "id": f"superteam:{item_id}",
        "title": title,
        "organization": organization,
        "url": url,
        "tags": [t for t in tags if t],
        "deadline": deadline_str,
        "prize_pool": prize_pool,
        "has_cash_prize": has_cash_prize,
        "career_incentives": career_incentives,
        "team_size": {"min_team": 1, "max_team": 1},
        "description": f"{title} by {organization}. Reward: {prize_pool}",
        "location": "Remote",
        "is_remote": True,
        "source": "superteam",
    }


def fetch_superteam(api_url: str = SUPERTEAM_API_URL) -> list[dict[str, Any]]:
    """Fetch active bounties and freelance projects from Superteam Earn."""
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
        LOGGER.error("Failed to fetch Superteam listings: %s", exc)
        return []

    items = data if isinstance(data, list) else data.get("listings") or data.get("data") or []
    results = []
    for raw in items:
        if isinstance(raw, dict):
            normalized = parse_superteam_item(raw)
            if normalized:
                results.append(normalized)
    LOGGER.info("Fetched %d opportunities from Superteam", len(results))
    return results
